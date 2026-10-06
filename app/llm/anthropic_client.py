"""Claude adapter. The ONLY module in the application that imports the `anthropic` SDK.

Structured output uses `output_config.format` with a JSON schema derived from the Pydantic model
(`anthropic.transform_schema`, the same transform `messages.parse` applies). The stop reason is checked
before the text is validated, so refusals and truncation are reported as such rather than as bad JSON.
"""

from __future__ import annotations

import base64
from typing import Any

import anthropic
from pydantic import TypeAdapter, ValidationError

from app.config import Settings
from app.llm.base import LLMError, T, VisionResult

MAX_TOKENS = 16000
SUPPORTED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})

# Models that accept the server-side refusal fallback (`fallbacks: "default"`) and `output_config.effort`.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"})


class AnthropicLLMClient:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model_id = settings.llm_model
        if client is None:
            if not settings.has_anthropic_credentials:
                raise LLMError("no_credentials", "chưa đặt ANTHROPIC_API_KEY")
            client = anthropic.Anthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                timeout=settings.llm_timeout_seconds,
                max_retries=1,
            )
        self._client = client
        self.last_served_model: str | None = None

    def generate_structured(self, *, system: str, user: str, output_model: type[T]) -> T:
        return self._call(system=system, content=[{"type": "text", "text": user}], output_model=output_model)

    def describe_image(self, *, image_bytes: bytes, media_type: str, instructions: str) -> VisionResult:
        if media_type not in SUPPORTED_IMAGE_TYPES:
            raise LLMError("unsupported_input", f"image type {media_type!r} is not supported")
        data = base64.standard_b64encode(image_bytes).decode("ascii")
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": "Describe this public profile image following the system instructions."},
        ]
        return self._call(system=instructions, content=content, output_model=VisionResult)

    def _call(self, *, system: str, content: list[dict[str, Any]], output_model: type[T]) -> T:
        schema = anthropic.transform_schema(TypeAdapter(output_model).json_schema())
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }
        if self.model_id in FALLBACK_MODELS:
            output_config["effort"] = "medium"
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        kwargs["output_config"] = output_config

        try:
            response = self._client.beta.messages.create(**kwargs)
        except anthropic.APITimeoutError:
            raise LLMError("timeout", "the Claude API request timed out") from None
        except anthropic.APIConnectionError as exc:
            raise LLMError("api_error", f"connection error: {exc}") from None
        except anthropic.AuthenticationError:
            raise LLMError("auth", "the Claude API rejected the credentials") from None
        except anthropic.RateLimitError:
            raise LLMError("rate_limited", "the Claude API rate limit was reached") from None
        except anthropic.APIStatusError as exc:
            raise LLMError("api_error", f"HTTP {exc.status_code}: {exc.message}") from None

        self.last_served_model = getattr(response, "model", None)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMError("refusal", f"model declined the request (category: {category})")
        if response.stop_reason == "max_tokens":
            raise LLMError("max_tokens", "output was truncated at max_tokens")

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise LLMError("invalid_output", "response contained no text output")
        try:
            return output_model.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError("invalid_output", f"output does not match {output_model.__name__}: {exc.error_count()} error(s)") from None
