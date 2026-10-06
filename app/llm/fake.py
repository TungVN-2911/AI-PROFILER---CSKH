"""Scripted LLM client for tests. Queued items are returned (or raised) in order."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from app.llm.base import LLMError, T, VisionResult


def _coerce(item: Any, output_model: type[T]) -> T:
    if isinstance(item, BaseException):
        raise item
    try:
        if isinstance(item, str):
            return output_model.model_validate_json(item)
        if isinstance(item, BaseModel):
            item = item.model_dump()
        return output_model.model_validate(item)
    except ValidationError as exc:
        raise LLMError("invalid_output", f"output does not match {output_model.__name__}: {exc.error_count()} error(s)") from None


class FakeLLMClient:
    """`responses` feed generate_structured; `vision_responses` feed describe_image.

    Each item may be a dict, a JSON string, a Pydantic model instance, or an exception to raise.
    """

    def __init__(self, responses: list[Any] | None = None, vision_responses: list[Any] | None = None) -> None:
        self.model_id = "fake-llm"
        self._responses = list(responses or [])
        self._vision = list(vision_responses or [])
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, *, system: str, user: str, output_model: type[T]) -> T:
        self.calls.append({"kind": "generate", "system": system, "user": user, "output_model": output_model})
        if not self._responses:
            raise LLMError("api_error", "fake response queue exhausted")
        return _coerce(self._responses.pop(0), output_model)

    def describe_image(self, *, image_bytes: bytes, media_type: str, instructions: str) -> VisionResult:
        self.calls.append({"kind": "vision", "media_type": media_type, "instructions": instructions, "size": len(image_bytes)})
        if not self._vision:
            raise LLMError("api_error", "fake vision queue exhausted")
        return _coerce(self._vision.pop(0), VisionResult)
