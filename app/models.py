"""Domain models: provided profile data, access states and the fact ledger.

The fact ledger is the only source of truth that generators may draw on. Missing data is
recorded as UNKNOWN (in `FactLedger.unknown_fields`) and never filled in.
"""

from __future__ import annotations

from datetime import date as Date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccessState(str, Enum):
    PUBLIC = "PUBLIC"
    PARTIAL = "PARTIAL"
    PRIVATE = "PRIVATE"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    UNREACHABLE = "UNREACHABLE"
    INVALID_INPUT = "INVALID_INPUT"
    NO_ACCESSIBLE_DATA = "NO_ACCESSIBLE_DATA"


# Access states under which profile content may be used at all.
READABLE_STATES = frozenset({AccessState.PUBLIC, AccessState.PARTIAL})


class EpistemicStatus(str, Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    UNKNOWN = "UNKNOWN"


FactCategory = Literal[
    "name",
    "bio",
    "work",
    "education",
    "location",
    "interest",
    "post",
    "visual_observation",
    "pronouns",
    "gender",
    "birth_year",
    "perceived_gender",
    "perceived_age",
    "other",
]


NON_GROUNDING_CATEGORIES = frozenset({"name", "pronouns", "gender", "birth_year", "perceived_gender", "perceived_age"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _clean_list(values: object) -> object:
    if isinstance(values, list):
        return [v.strip() for v in values if isinstance(v, str) and v.strip()]
    return values


# --- Provided profile data ----------------------------------------------------------------------


class AccessInfo(_Strict):
    state: AccessState = AccessState.PUBLIC
    note: str = ""


class PublicInfo(_Strict):
    work: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    current_city: str | None = None
    hometown: str | None = None
    pronouns: str | None = None
    # Gender exactly as displayed in the profile's public About section (self-declared).
    gender: str | None = None
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    links: list[str] = Field(default_factory=list)

    _strip_text = field_validator("current_city", "hometown", "pronouns", "gender", mode="before")(
        _blank_to_none
    )
    _strip_lists = field_validator("work", "education", "interests", "links", mode="before")(_clean_list)


class PublicPost(_Strict):
    date: Date | None = None
    text: str = Field(min_length=1)


class ProfileImage(_Strict):
    kind: Literal["avatar", "cover", "photo"] = "avatar"
    path: str | None = None
    url: str | None = None
    alt_text: str | None = None

    _strip = field_validator("path", "url", "alt_text", mode="before")(_blank_to_none)


class RawProfile(_Strict):
    facebook_url: str = Field(min_length=1)
    synthetic: bool = False
    access: AccessInfo = Field(default_factory=AccessInfo)
    collected_at: datetime | None = None
    collection_method: Literal["manual_export", "fixture", "live_meta"] | None = None
    display_name: str | None = None
    bio: str | None = None
    public_info: PublicInfo = Field(default_factory=PublicInfo)
    public_posts: list[PublicPost] = Field(default_factory=list)
    images: list[ProfileImage] = Field(default_factory=list)

    _strip = field_validator("display_name", "bio", mode="before")(_blank_to_none)


class AcquisitionResult(_Strict):
    canonical_url: str
    access_state: AccessState
    # Only set when access_state is readable (PUBLIC/PARTIAL); otherwise profile fields must not be used.
    raw: RawProfile | None = None
    source_name: str
    synthetic: bool = False
    limitations: list[str] = Field(default_factory=list)


# --- Fact ledger --------------------------------------------------------------------------------


class Fact(_Strict):
    id: str = Field(pattern=r"^F[1-9]\d*$")
    category: FactCategory
    statement: str = Field(min_length=1)
    source: str = Field(min_length=1)
    epistemic_status: EpistemicStatus = EpistemicStatus.FACT
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _unknown_is_not_a_fact_entry(self) -> "Fact":
        # Unknowns live in FactLedger.unknown_fields; a ledger entry must carry content.
        if self.epistemic_status is EpistemicStatus.UNKNOWN:
            raise ValueError("UNKNOWN items belong in FactLedger.unknown_fields, not in facts")
        return self


class FactLedger(_Strict):
    facts: list[Fact] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> "FactLedger":
        ids = [f.id for f in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("fact ids must be unique")
        return self

    def get(self, fact_id: str) -> Fact | None:
        return next((f for f in self.facts if f.id == fact_id), None)

    def ids(self) -> set[str]:
        return {f.id for f in self.facts}

    def name_fact(self) -> Fact | None:
        return next((f for f in self.facts if f.category == "name"), None)

    def usable_facts(self) -> list[Fact]:
        """FACT entries that messages can be grounded on.

        Excludes the name and demographic facts (pronouns, gender, birth year): those only feed
        `estimated_demographics` and must never be the topic of a rapport message.
        """
        return [
            f
            for f in self.facts
            if f.epistemic_status is EpistemicStatus.FACT and f.category not in NON_GROUNDING_CATEGORIES
        ]
