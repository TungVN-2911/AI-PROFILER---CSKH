"""Provider-neutral LLM interface. Application code depends only on this module (NFR-005)."""

from __future__ import annotations

from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T", bound=BaseModel)

LLMErrorKind = Literal[
    "no_credentials",
    "refusal",
    "max_tokens",
    "invalid_output",
    "timeout",
    "rate_limited",
    "auth",
    "api_error",
    "unsupported_input",
]


class LLMError(Exception):
    """Any LLM failure. Callers treat it as a failed attempt and fall back; never as data."""

    def __init__(self, kind: LLMErrorKind, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


class VisionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="One visible element, phrased as 'appears to show ...'.")
    confidence: float = Field(ge=0.0, le=1.0)


class VisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_usable: bool
    observations: list[VisionObservation] = Field(default_factory=list, max_length=5)


class LLMClient(Protocol):
    model_id: str

    def generate_structured(self, *, system: str, user: str, output_model: type[T]) -> T:
        """Return an instance of `output_model` or raise LLMError."""
        ...

    def describe_image(self, *, image_bytes: bytes, media_type: str, instructions: str) -> VisionResult:
        """Describe one image as structured observations or raise LLMError."""
        ...
