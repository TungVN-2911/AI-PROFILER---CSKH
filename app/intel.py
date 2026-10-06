"""Profile intelligence: `customer_name` and `estimated_demographics` (FR-008, Decision D-3).

- gender: only from a self-declared gender field, else self-declared pronouns (reported verbatim, never mapped to
  a gender); otherwise UNKNOWN. Never from appearance or names.
- estimated_age_range: only arithmetic on a stated birth year; otherwise UNKNOWN.
- apparent_lifestyle: a labelled INFERENCE citing the facts it rests on, or UNKNOWN.
Only FACT entries are used; model-generated (INFERENCE) visual observations are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models import EpistemicStatus, Fact, FactLedger

UNKNOWN = "UNKNOWN"
MIN_PLAUSIBLE_AGE = 13
MAX_PLAUSIBLE_AGE = 110

_GENDER_LABELS = {
    "nữ": "Female", "female": "Female", "woman": "Female", "f": "Female",
    "nam": "Male", "male": "Male", "man": "Male", "m": "Male",
}


@dataclass(frozen=True)
class Intelligence:
    customer_name: str | None
    gender: str
    estimated_age_range: str
    apparent_lifestyle: str
    gender_fact_ids: list[str] = field(default_factory=list)
    age_fact_ids: list[str] = field(default_factory=list)
    lifestyle_fact_ids: list[str] = field(default_factory=list)


def _facts(ledger: FactLedger, category: str) -> list[Fact]:
    return [f for f in ledger.facts if f.category == category and f.epistemic_status is EpistemicStatus.FACT]


def derive_gender(ledger: FactLedger) -> tuple[str, list[str]]:
    declared = _facts(ledger, "gender")
    if declared:
        fact = declared[0]
        label = _GENDER_LABELS.get(fact.statement.strip().casefold(), fact.statement.strip())
        return f"{label} (self-declared gender field [{fact.id}])", [fact.id]
    pronouns = _facts(ledger, "pronouns")
    if pronouns:
        fact = pronouns[0]
        return f"Self-declared pronouns: {fact.statement.strip()} [{fact.id}] (gender not stated)", [fact.id]
    return UNKNOWN, []


def derive_age_range(ledger: FactLedger, reference_year: int) -> tuple[str, list[str]]:
    years = _facts(ledger, "birth_year")
    if not years:
        return UNKNOWN, []
    fact = years[0]
    try:
        birth_year = int(fact.statement)
    except ValueError:
        return UNKNOWN, []
    # Birthday unknown → the age is one of two consecutive values.
    low, high = reference_year - birth_year - 1, reference_year - birth_year
    if low < MIN_PLAUSIBLE_AGE or high > MAX_PLAUSIBLE_AGE:
        return UNKNOWN, []
    return f"{low}–{high} (derived from stated birth year {birth_year} [{fact.id}], as of {reference_year})", [fact.id]


def derive_lifestyle(ledger: FactLedger) -> tuple[str, list[str]]:
    interests = _facts(ledger, "interest")[:3]
    work = _facts(ledger, "work")[:1]
    parts: list[str] = []
    if interests:
        parts.append("stated interests: " + "; ".join(f.statement for f in interests))
    if work:
        parts.append("stated work: " + work[0].statement)
    used = interests + work
    if not used:
        bio = _facts(ledger, "bio")[:1]
        if not bio:
            return UNKNOWN, []
        parts.append("self-description: " + bio[0].statement)
        used = bio
    ids = [f.id for f in used]
    return f"INFERENCE: day-to-day life appears to involve {', '.join(parts)} (based on {', '.join(ids)})", ids


def build_intelligence(ledger: FactLedger, reference_year: int | None = None) -> Intelligence:
    year = reference_year or date.today().year
    name = ledger.name_fact()
    gender, gender_ids = derive_gender(ledger)
    age, age_ids = derive_age_range(ledger, year)
    lifestyle, lifestyle_ids = derive_lifestyle(ledger)
    return Intelligence(
        customer_name=name.statement if name else None,
        gender=gender,
        estimated_age_range=age,
        apparent_lifestyle=lifestyle,
        gender_fact_ids=gender_ids,
        age_fact_ids=age_ids,
        lifestyle_fact_ids=lifestyle_ids,
    )
