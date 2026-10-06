"""Gemini adapter. The ONLY module in the application that imports the `google-genai` SDK.

Structured output uses `response_mime_type="application/json"` with `response_json_schema` derived from the
Pydantic model (local `$ref`s inlined). The finish reason and prompt-block feedback are checked before the text is
validated, so safety blocks and truncation are reported as such rather than as bad JSON.

Models are tried in order (`GEMINI_MODEL`, then `GEMINI_FALLBACK_MODELS`). A model that is overloaded,
out of quota, missing or timing out is skipped for the rest of the run; `model_id` names the model that answered.
"""

from __future__ import annotations

from typing import Any

import logging

import httpx
from google import genai
from google.genai import errors, types
from pydantic import TypeAdapter, ValidationError

from app.config import Settings
from app.llm.base import LLMError, T, VisionResult

log = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 16000
SUPPORTED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
BLOCKED_FINISH_REASONS = frozenset(
    {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT"}
)


def inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace local `#/$defs/...` references by their definitions (our models are not recursive)."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
                return {**target, **{k: resolve(v) for k, v in node.items() if k != "$ref"}}
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _classify(exc: Exception) -> tuple[LLMError, bool]:
    """Map an SDK/transport error to (LLMError, try the next model?)."""
    if isinstance(exc, errors.ClientError):
        if exc.code in (401, 403):
            return LLMError("auth", "the Gemini API rejected the credentials"), False
        if exc.code == 429:
            return LLMError("rate_limited", "the Gemini API quota or rate limit was reached"), True
        if exc.code == 404:
            return LLMError("api_error", f"model not found: {exc.message}"), True
        return LLMError("api_error", f"HTTP {exc.code}: {exc.message}"), False
    if isinstance(exc, errors.APIError):
        return LLMError("api_error", f"HTTP {exc.code}: {exc.message}"), True
    if isinstance(exc, httpx.TimeoutException):
        return LLMError("timeout", "the Gemini API request timed out"), True
    if isinstance(exc, httpx.HTTPError):
        return LLMError("api_error", f"connection error: {type(exc).__name__}"), True
    raise exc


def _reason_name(value: Any) -> str:
    return getattr(value, "name", None) or str(value or "")


class GeminiLLMClient:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._chain = settings.gemini_model_chain
        self._unavailable: set[str] = set()
        self.model_id = self._chain[0]
        if client is None:
            if not settings.has_gemini_credentials:
                raise LLMError("no_credentials", "chưa đặt GEMINI_API_KEY")
            client = genai.Client(
                api_key=settings.gemini_api_key.get_secret_value(),
                http_options=types.HttpOptions(timeout=int(settings.llm_timeout_seconds * 1000)),
            )
        self._client = client

    def generate_structured(self, *, system: str, user: str, output_model: type[T]) -> T:
        return self._call(system=system, contents=[user], output_model=output_model)

    def describe_image(self, *, image_bytes: bytes, media_type: str, instructions: str) -> VisionResult:
        if media_type not in SUPPORTED_IMAGE_TYPES:
            raise LLMError("unsupported_input", f"image type {media_type!r} is not supported")
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type=media_type),
            "Describe this public profile image following the system instructions.",
        ]
        return self._call(system=instructions, contents=contents, output_model=VisionResult)

    def _call(self, *, system: str, contents: list[Any], output_model: type[T]) -> T:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=inline_schema(TypeAdapter(output_model).json_schema()),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        last_error: LLMError | None = None
        for model in [m for m in self._chain if m not in self._unavailable]:
            try:
                response = self._client.models.generate_content(model=model, contents=contents, config=config)
            except Exception as exc:  # noqa: BLE001 - classified below; unknown errors are re-raised
                error, fall_back = _classify(exc)
                if not fall_back:
                    raise error from None
                log.warning("Gemini model %s unavailable (%s); trying the next model", model, error.detail)
                self._unavailable.add(model)
                last_error = error
                continue
            self.model_id = model
            return self._parse(response, output_model)
        raise last_error or LLMError("api_error", "no Gemini model is available")

    def _parse(self, response: Any, output_model: type[T]) -> T:
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise LLMError("refusal", f"prompt blocked ({_reason_name(feedback.block_reason)})")
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            raise LLMError("invalid_output", "response contained no candidates")
        candidate = candidates[0]
        finish = _reason_name(getattr(candidate, "finish_reason", None))
        if finish in BLOCKED_FINISH_REASONS:
            raise LLMError("refusal", f"model declined the request ({finish})")
        if finish == "MAX_TOKENS":
            raise LLMError("max_tokens", "output was truncated at max_output_tokens")

        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)).strip()
        if not text:
            raise LLMError("invalid_output", "response contained no text output")
        try:
            return output_model.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError(
                "invalid_output", f"output does not match {output_model.__name__}: {exc.error_count()} error(s)"
            ) from None
