"""Deterministic guardrails every engagement draft must pass (FR-010..FR-012, NFR-002, C-005, C-007).

A draft that produces no violations may be emitted with `ZERO_SALES_CONFIRMED`. Nothing here trusts the
generator: citations are checked against the ledger, and text is screened independently of citations.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.lexicons import (
    EMAIL_PATTERN,
    HASHTAG_PATTERN,
    PHONE_PATTERN,
    PRICE_PATTERN,
    URL_PATTERN,
    find_presumptions,
    find_sales_terms,
    find_sensitive,
)
from app.models import NON_GROUNDING_CATEGORIES, EpistemicStatus, Fact, FactLedger
from app.schema import MAX_MESSAGES, MIN_MESSAGES

MAX_MESSAGE_CHARS = 400
ALWAYS_ALLOWED_WORDS = frozenset({"facebook"})


# --- Draft model (also the LLM structured-output schema in TASK-013) -----------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CitedText(_Strict):
    text: str = Field(min_length=1)
    fact_ids: list[str] = Field(default_factory=list)


class DraftMessage(_Strict):
    text: str = Field(min_length=1)
    kind: Literal["grounded", "neutral"]
    fact_ids: list[str] = Field(default_factory=list)


class EngagementDraft(_Strict):
    core_empathy_angle: CitedText
    messages: list[DraftMessage]
    evening_hook: CitedText
    apparent_lifestyle: CitedText | None = None


@dataclass(frozen=True)
class Violation:
    code: str
    location: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.location}: {self.detail}"


# --- Text-level checks ---------------------------------------------------------------------

_NEUTRAL_CLAIM = re.compile(
    r"\b(?:bạn|anh|chị|em)\s+(?:là|thích|yêu|đang|hay|thường|có vẻ|rất|cũng|vừa|đã)\b"
    r"|\byou(?:'re| are| like| love| seem| always| usually| just| have)\b",
    re.IGNORECASE,
)
# A sentence also ends after a closing quote that follows end punctuation: `… ghê.” Chuyện …`.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…:\n])\s+|(?<=[.!?…][”\"’)])\s+")
_WORD = re.compile(r"\w+", re.UNICODE)


def _allowed_in_facts(term: str, cited: list[Fact]) -> bool:
    term_cf = term.casefold()
    return any(term_cf in f.statement.casefold() for f in cited)


def check_text(text: str, location: str, cited: list[Fact] | None = None) -> list[Violation]:
    """Zero-sales, contact/price, presumption and sensitive-attribute checks for one text."""
    cited = cited or []
    out: list[Violation] = []
    for term in find_sales_terms(text):
        if not _allowed_in_facts(term, cited):
            out.append(Violation("SALES_TERM", location, f"commercial term '{term}'"))
    for pattern, code in (
        (PRICE_PATTERN, "PRICE"),
        (URL_PATTERN, "URL"),
        (PHONE_PATTERN, "PHONE"),
        (EMAIL_PATTERN, "EMAIL"),
        (HASHTAG_PATTERN, "HASHTAG"),
    ):
        for m in pattern.finditer(text):
            out.append(Violation(code, location, f"'{m.group(0)}' is not allowed in rapport messages"))
    for phrase in find_presumptions(text):
        # Quoting the customer's own words (e.g. a post saying "mệt mỏi") is grounded, not presumed.
        if not _allowed_in_facts(phrase, cited):
            out.append(Violation("PRESUMPTION", location, f"presumes the customer's situation: '{phrase}'"))
    for category, term in find_sensitive(text):
        if not _allowed_in_facts(term, cited):
            out.append(Violation("SENSITIVE_TERM", location, f"sensitive attribute ({category}): '{term}'"))
    if len(text) > MAX_MESSAGE_CHARS:
        out.append(Violation("TOO_LONG", location, f"{len(text)} characters (max {MAX_MESSAGE_CHARS})"))
    return out


def check_entities(text: str, location: str, cited: list[Fact], name: Fact | None) -> list[Violation]:
    """Heuristic: numbers and mid-sentence capitalised words must come from cited facts (or the name)."""
    allowed_text = " ".join(f.statement for f in cited).casefold()
    allowed_words = {w.casefold() for f in cited for w in _WORD.findall(f.statement)} | ALWAYS_ALLOWED_WORDS
    if name:
        allowed_words |= {w.casefold() for w in _WORD.findall(name.statement)}
    # References to the cited facts themselves (e.g. "(based on F5, F6)") are not entities.
    cited_ids = {f.id for f in cited}
    text = re.sub(r"\bF\d+\b", lambda m: "" if m.group(0) in cited_ids else m.group(0), text)
    out: list[Violation] = []
    for number in re.findall(r"\d+", text):
        if number not in allowed_text:
            out.append(Violation("UNGROUNDED_NUMBER", location, f"number '{number}' is not in the cited facts"))
    for sentence in _SENTENCE_SPLIT.split(text):
        words = _WORD.findall(sentence)
        for word in words[1:]:
            if word[0].isupper() and not word.isdigit() and word.casefold() not in allowed_words:
                out.append(Violation("UNGROUNDED_ENTITY", location, f"'{word}' does not appear in the cited facts"))
    return out


# --- Draft-level validation ----------------------------------------------------------------


def _resolve(ids: list[str], ledger: FactLedger, location: str) -> tuple[list[Fact], list[Violation]]:
    facts: list[Fact] = []
    out: list[Violation] = []
    for fid in ids:
        fact = ledger.get(fid)
        if fact is None:
            out.append(Violation("UNKNOWN_FACT_ID", location, f"cites {fid}, which does not exist"))
        elif fact.epistemic_status is not EpistemicStatus.FACT:
            out.append(Violation("NON_FACT_CITATION", location, f"cites {fid}, which is an {fact.epistemic_status.value}"))
        elif fact.category in NON_GROUNDING_CATEGORIES - {"name"}:
            out.append(Violation("DEMOGRAPHIC_CITATION", location, f"cites {fid} ({fact.category}), which must not be a message topic"))
        else:
            facts.append(fact)
    return facts, out


def _grounding(facts: list[Fact]) -> list[Fact]:
    return [f for f in facts if f.category != "name"]


def _check_cited(item: CitedText, location: str, ledger: FactLedger) -> list[Violation]:
    facts, out = _resolve(item.fact_ids, ledger, location)
    if not _grounding(facts):
        out.append(Violation("MISSING_CITATION", location, "must cite at least one usable fact"))
    out += check_text(item.text, location, facts)
    out += check_entities(item.text, location, facts, ledger.name_fact())
    return out


def validate_draft(draft: EngagementDraft, ledger: FactLedger) -> list[Violation]:
    out: list[Violation] = []
    name = ledger.name_fact()

    n = len(draft.messages)
    if not MIN_MESSAGES <= n <= MAX_MESSAGES:
        out.append(Violation("MESSAGE_COUNT", "messages", f"{n} messages (must be {MIN_MESSAGES}–{MAX_MESSAGES})"))

    out += _check_cited(draft.core_empathy_angle, "core_empathy_angle", ledger)
    out += _check_cited(draft.evening_hook, "evening_hook", ledger)

    seen: set[str] = set()
    grounded_count = 0
    for i, msg in enumerate(draft.messages):
        loc = f"messages[{i}]"
        facts, errors = _resolve(msg.fact_ids, ledger, loc)
        out += errors
        if msg.kind == "grounded":
            if _grounding(facts):
                grounded_count += 1
            else:
                out.append(Violation("MISSING_CITATION", loc, "grounded message must cite at least one usable fact"))
        else:
            if _grounding(facts):
                out.append(Violation("NEUTRAL_CITES_FACTS", loc, "neutral message cites facts; mark it grounded"))
            if any(_NEUTRAL_CLAIM.search(s) and not s.rstrip().endswith("?") for s in _SENTENCE_SPLIT.split(msg.text)):
                out.append(Violation("NEUTRAL_CLAIM", loc, "neutral message asserts something about the customer"))
        out += check_text(msg.text, loc, facts)
        out += check_entities(msg.text, loc, facts, name)
        key = msg.text.strip().casefold()
        if key in seen:
            out.append(Violation("DUPLICATE_MESSAGE", loc, "same text as an earlier message"))
        seen.add(key)

    usable = len(ledger.usable_facts())
    if usable >= 3 and n and grounded_count < math.ceil(n / 2):
        out.append(
            Violation("TOO_FEW_GROUNDED", "messages", f"{grounded_count} of {n} grounded (need ≥ {math.ceil(n / 2)})")
        )

    if draft.apparent_lifestyle is not None:
        loc = "apparent_lifestyle"
        if not draft.apparent_lifestyle.text.startswith("INFERENCE:"):
            out.append(Violation("LIFESTYLE_LABEL", loc, "must start with 'INFERENCE:'"))
        out += _check_cited(draft.apparent_lifestyle, loc, ledger)
    return out
