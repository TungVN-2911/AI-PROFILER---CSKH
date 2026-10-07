"""Provider-neutral LLM interface. Application code depends only on this module."""

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


class VisionEstimate(BaseModel):
    """Perceived visual impression of a profile-picture subject. Never a fact or identity claim."""

    model_config = ConfigDict(extra="forbid")

    single_person_visible: bool = Field(
        description="True only if exactly one person's face/body is clearly visible as the main subject."
    )
    perceived_gender: Literal["female", "male", "unclear"] = Field(
        description="Visible gender presentation only, not actual gender identity; use unclear if uncertain."
    )
    gender_confidence: float = Field(ge=0.0, le=1.0)
    age_min: int | None = Field(default=None, ge=0, le=120)
    age_max: int | None = Field(default=None, ge=0, le=120)
    age_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class VisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_usable: bool
    observations: list[VisionObservation] = Field(default_factory=list, max_length=5)
    estimate: VisionEstimate | None = Field(
        description="Always include this key. Use null if the image is unusable; otherwise return an explicit estimate, marking uncertain values unclear/null."
    )


class LLMClient(Protocol):
    model_id: str

    def generate_structured(self, *, system: str, user: str, output_model: type[T]) -> T:
        """Return an instance of `output_model` or raise LLMError."""
        ...

    def describe_image(self, *, image_bytes: bytes, media_type: str, instructions: str) -> VisionResult:
        """Describe one image as structured observations or raise LLMError."""
        ...
