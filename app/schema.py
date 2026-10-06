"""Output models.

`SuccessOutput` / `PartialOutput` reproduce the brief's schema exactly (no extra keys, fixed
literals). `EvidenceReport` is written to a separate evidence.json and may carry provenance.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from app.models import AccessState, Fact

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

MIN_MESSAGES = 5
MAX_MESSAGES = 10
TRIGGER_TIME = "20:00"
ZERO_SALES_CONFIRMED = "ZERO_SALES_CONFIRMED"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Strict output schema (brief §2) --------------------------------------------------------


class EstimatedDemographics(_Strict):
    gender: NonEmptyStr
    estimated_age_range: NonEmptyStr
    apparent_lifestyle: NonEmptyStr


class ProfileData(_Strict):
    customer_name: NonEmptyStr
    visual_context: NonEmptyStr
    estimated_demographics: EstimatedDemographics


class EthicalRapport(_Strict):
    core_empathy_angle: NonEmptyStr
    dialogue_sequence_10: list[NonEmptyStr] = Field(min_length=MIN_MESSAGES, max_length=MAX_MESSAGES)
    sales_mention_check: Literal["ZERO_SALES_CONFIRMED"]


class EveningCadence(_Strict):
    trigger_time: Literal["20:00"]
    evening_hook_message: NonEmptyStr


class SuccessOutput(_Strict):
    status: Literal["SUCCESS"]
    facebook_url: NonEmptyStr
    profile_data: ProfileData
    ethical_rapport: EthicalRapport
    evening_cadence_20pm: EveningCadence


class PartialOutput(_Strict):
    status: Literal["PARTIAL_OR_PRIVATE"]
    # May be empty or the raw (invalid) input when the URL itself was the problem.
    facebook_url: str
    error_note: NonEmptyStr


AgentOutput = Annotated[Union[SuccessOutput, PartialOutput], Field(discriminator="status")]
_OUTPUT_ADAPTER: TypeAdapter[SuccessOutput | PartialOutput] = TypeAdapter(AgentOutput)


def parse_output(data: Any) -> SuccessOutput | PartialOutput:
    """Validate a decoded JSON document against the strict output schema."""
    return _OUTPUT_ADAPTER.validate_python(data)


def to_json_dict(output: SuccessOutput | PartialOutput) -> dict[str, Any]:
    return output.model_dump(mode="json")


# --- Evidence report (evidence.json) --------------------------------------------------------


class MessageGrounding(_Strict):
    index: int = Field(ge=0)
    kind: Literal["grounded", "neutral"]
    fact_ids: list[str] = Field(default_factory=list)


class Grounding(_Strict):
    core_empathy_angle: list[str] = Field(default_factory=list)
    gender: list[str] = Field(default_factory=list)
    estimated_age_range: list[str] = Field(default_factory=list)
    apparent_lifestyle: list[str] = Field(default_factory=list)
    messages: list[MessageGrounding] = Field(default_factory=list)
    evening_hook: list[str] = Field(default_factory=list)


class ValidationSummary(_Strict):
    passed: bool = False
    attempts: int = Field(default=0, ge=0)
    violations: list[str] = Field(default_factory=list)


class EvidenceReport(_Strict):
    facebook_url: str
    output_status: Literal["SUCCESS", "PARTIAL_OR_PRIVATE"]
    access_state: AccessState | None = None
    sources_used: list[str] = Field(default_factory=list)
    synthetic_data: bool = False
    collected_at: str | None = None
    addressing: str | None = None
    generation_mode: Literal["llm", "deterministic", "none"] = "none"
    model_id: str | None = None
    fact_ledger: list[Fact] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    grounding: Grounding = Field(default_factory=Grounding)
    validation: ValidationSummary = Field(default_factory=ValidationSummary)
    technical_limitations: list[str] = Field(default_factory=list)
