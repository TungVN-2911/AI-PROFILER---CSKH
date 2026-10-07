"""Profile intelligence: `customer_name` and `estimated_demographics`.

- gender: self-declared gender field, else self-declared pronouns (reported verbatim, never mapped to a gender), else
  a perceived estimate from the profile picture (labelled INFERENCE with confidence), else UNKNOWN. Never from names.
- estimated_age_range: arithmetic on a stated birth year, else a perceived apparent-age estimate (labelled
  INFERENCE), else UNKNOWN.
- apparent_lifestyle: a labelled INFERENCE citing the facts it rests on, or UNKNOWN.
Self-declared data always wins over perceived estimates; model-generated visual observations are never used. Perceived
gender estimates are not used to choose a form of address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.models import EpistemicStatus, Fact, FactLedger

UNKNOWN = "UNKNOWN"
MIN_PLAUSIBLE_AGE = 13
MAX_PLAUSIBLE_AGE = 110

_GENDER_LABELS = {
    "nữ": "Nữ", "female": "Nữ", "woman": "Nữ", "f": "Nữ",
    "nam": "Nam", "male": "Nam", "man": "Nam", "m": "Nam",
}


@dataclass(frozen=True)
class Addressing:
    """Vietnamese forms of address: how the agent calls the customer and itself."""

    customer: str  # "chị" | "anh" | "bạn"
    agent: str  # "em" | "mình"
    basis: str

    def fields(self) -> dict[str, str]:
        return {
            "you": self.customer,
            "You": self.customer.capitalize(),
            "me": self.agent,
            "Me": self.agent.capitalize(),
            "q": "" if self.is_neutral else " ạ",  # polite particle at the end of questions for chị/anh
        }

    @property
    def is_neutral(self) -> bool:
        return self.customer == "bạn"

    def label(self) -> str:
        return f"{self.customer}/{self.agent} ({self.basis})"


NEUTRAL_ADDRESSING = Addressing("bạn", "mình", "chưa rõ giới tính")

_PRONOUN_ADDRESS = {"she": "chị", "he": "anh"}


@dataclass(frozen=True)
class Intelligence:
    customer_name: str | None
    gender: str
    estimated_age_range: str
    apparent_lifestyle: str
    gender_fact_ids: list[str] = field(default_factory=list)
    age_fact_ids: list[str] = field(default_factory=list)
    lifestyle_fact_ids: list[str] = field(default_factory=list)
    addressing: Addressing = NEUTRAL_ADDRESSING


def _facts(ledger: FactLedger, category: str) -> list[Fact]:
    return [f for f in ledger.facts if f.category == category and f.epistemic_status is EpistemicStatus.FACT]


def _estimate(ledger: FactLedger, category: str) -> Fact | None:
    """A perceived estimate added by app/vision.py (INFERENCE, source vision:<kind>:estimate)."""
    return next(
        (f for f in ledger.facts if f.category == category and f.epistemic_status is EpistemicStatus.INFERENCE),
        None,
    )


def _image_kind(fact: Fact) -> str:
    parts = fact.source.split(":")
    kind = parts[1] if len(parts) > 2 else "photo"
    return {"avatar": "ảnh đại diện", "cover": "ảnh bìa"}.get(kind, "ảnh công khai")


def derive_gender(ledger: FactLedger) -> tuple[str, list[str]]:
    declared = _facts(ledger, "gender")
    if declared:
        fact = declared[0]
        label = _GENDER_LABELS.get(fact.statement.strip().casefold(), fact.statement.strip())
        return f"{label} (tự khai báo trên trang cá nhân [{fact.id}])", [fact.id]
    pronouns = _facts(ledger, "pronouns")
    if pronouns:
        fact = pronouns[0]
        return f"Đại từ tự khai báo: {fact.statement.strip()} [{fact.id}] (không nêu giới tính)", [fact.id]
    perceived = _estimate(ledger, "perceived_gender")
    if perceived:
        label = _GENDER_LABELS.get(perceived.statement, perceived.statement)
        return (
            f"INFERENCE: {label} (ước lượng từ {_image_kind(perceived)}, "
            f"độ tin cậy {perceived.confidence:.2f}) [{perceived.id}]",
            [perceived.id],
        )
    return UNKNOWN, []


def derive_age_range(ledger: FactLedger, reference_year: int) -> tuple[str, list[str]]:
    years = _facts(ledger, "birth_year")
    if years:
        fact = years[0]
        try:
            birth_year = int(fact.statement)
        except ValueError:
            birth_year = None
        if birth_year is not None:
            # Birthday unknown → the age is one of two consecutive values.
            low, high = reference_year - birth_year - 1, reference_year - birth_year
            if MIN_PLAUSIBLE_AGE <= low and high <= MAX_PLAUSIBLE_AGE:
                return (
                    f"{low}–{high} tuổi (tính từ năm sinh tự khai báo {birth_year} [{fact.id}], tại năm {reference_year})",
                    [fact.id],
                )
    perceived = _estimate(ledger, "perceived_age")
    if perceived:
        low_s, high_s = perceived.statement.split("-")
        return (
            f"INFERENCE: {low_s}–{high_s} tuổi (ước lượng từ {_image_kind(perceived)}, "
            f"độ tin cậy {perceived.confidence:.2f}) [{perceived.id}]",
            [perceived.id],
        )
    return UNKNOWN, []


def derive_lifestyle(ledger: FactLedger) -> tuple[str, list[str]]:
    interests = _facts(ledger, "interest")[:3]
    work = _facts(ledger, "work")[:1]
    parts: list[str] = []
    if interests:
        parts.append("sở thích: " + ", ".join(f.statement for f in interests))
    if work:
        parts.append("công việc: " + work[0].statement)
    used = interests + work
    if not used:
        bio = [
            fact
            for fact in _facts(ledger, "bio")
            if not re.search(
                r"\b(?:người theo dõi|followers|người đang nói về điều này|people talking about this)\b",
                fact.statement,
                re.IGNORECASE,
            )
        ][:1]
        if not bio:
            return UNKNOWN, []
        parts.append("tự giới thiệu: " + bio[0].statement)
        used = bio
    ids = [f.id for f in used]
    return f"INFERENCE: đời sống thường ngày có vẻ gắn với {'; '.join(parts)} (dựa trên {', '.join(ids)})", ids


def derive_addressing(ledger: FactLedger) -> Addressing:
    """Use familiar address only when gender or pronouns were self-declared."""
    declared = _facts(ledger, "gender")
    if declared:
        label = _GENDER_LABELS.get(declared[0].statement.strip().casefold())
        if label:
            customer = "chị" if label == "Nữ" else "anh"
            return Addressing(customer, "em", f"giới tính tự khai báo [{declared[0].id}]")
    pronouns = _facts(ledger, "pronouns")
    if pronouns:
        first = pronouns[0].statement.strip().casefold().split("/")[0].strip()
        if first in _PRONOUN_ADDRESS:
            return Addressing(_PRONOUN_ADDRESS[first], "em", f"đại từ tự khai báo {pronouns[0].statement} [{pronouns[0].id}]")
        return NEUTRAL_ADDRESSING
    return NEUTRAL_ADDRESSING


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
        addressing=derive_addressing(ledger),
    )
