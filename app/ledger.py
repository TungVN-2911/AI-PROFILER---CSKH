"""Normalization of provided profile data into a fact ledger, and the sufficiency gate.

Every ledger entry is a verbatim (whitespace-trimmed) value from the provided data with its source.
Nothing is inferred here; missing fields are listed in `unknown_fields`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings
from app.lexicons import EMAIL_PATTERN, PHONE_PATTERN, URL_PATTERN
from app.models import READABLE_STATES, AccessState, EpistemicStatus, Fact, FactCategory, FactLedger, RawProfile
from app.sources.base import NO_DATA_LIMITATION
from app.sources.live_meta import LOGIN_LIMITATION

# Fields whose absence is recorded as UNKNOWN.
TRACKED_FIELDS = (
    "display_name",
    "bio",
    "work",
    "education",
    "interests",
    "current_city",
    "hometown",
    "pronouns",
    "gender",
    "birth_year",
    "public_posts",
    "images",
)

_BIO_FACT_SEPARATOR = re.compile(r"\s*(?:[·•]|\r?\n+)\s*|\.\s+(?=[A-ZÀ-Ỵ0-9])")
_PROFILE_METRIC = re.compile(
    r"\b(?:người theo dõi|followers|người đang nói về điều này|people talking about this)\b",
    re.IGNORECASE,
)
_FACEBOOK_BOILERPLATE = (
    re.compile(r"^join facebook to connect with .+ and others you may know\.?$", re.IGNORECASE),
    re.compile(
        r"^facebook gives people the power to share and makes the world more open and connected\.?$",
        re.IGNORECASE,
    ),
    re.compile(r"^tham gia facebook để kết nối với .+$", re.IGNORECASE),
    re.compile(r"^facebook giúp mọi người chia sẻ và kết nối với nhau\.?$", re.IGNORECASE),
)


def _is_platform_boilerplate(statement: str, display_name: str | None) -> bool:
    normalized = " ".join(statement.split()).strip()
    if any(pattern.fullmatch(normalized) for pattern in _FACEBOOK_BOILERPLATE):
        return True
    return bool(
        display_name
        and re.fullmatch(
            rf"{re.escape(display_name)}\s+is on Facebook\.?",
            normalized,
            re.IGNORECASE,
        )
    )


class _LedgerBuilder:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.facts: list[Fact] = []
        self.unknown: list[str] = []
        self._seen: set[tuple[str, str]] = set()

    def add(self, category: FactCategory, statement: str, field: str) -> None:
        if EMAIL_PATTERN.search(statement) or PHONE_PATTERN.search(statement) or URL_PATTERN.search(statement):
            if "contact_details_redacted" not in self.unknown:
                self.unknown.append("contact_details_redacted")
            return
        key = (category, statement.casefold())
        if key in self._seen:
            return
        self._seen.add(key)
        self.facts.append(
            Fact(
                id=f"F{len(self.facts) + 1}",
                category=category,
                statement=statement,
                source=f"{self.prefix}:{field}",
            )
        )

    def add_value(self, category: FactCategory, value: str | int | None, field: str) -> None:
        if value is None:
            self.unknown.append(field.rsplit(".", 1)[-1])
        else:
            self.add(category, str(value), field)

    def add_list(self, category: FactCategory, values: list[str], field: str) -> None:
        if not values:
            self.unknown.append(field.rsplit(".", 1)[-1])
        for i, value in enumerate(values):
            self.add(category, value, f"{field}[{i}]")


def build_ledger(raw: RawProfile | None) -> FactLedger:
    """Turn provided profile data into an ID'd ledger. `None` (no readable data) → empty ledger."""
    if raw is None:
        return FactLedger(facts=[], unknown_fields=list(TRACKED_FIELDS))

    b = _LedgerBuilder(raw.collection_method or "provided")
    info = raw.public_info

    def bio_category(statement: str) -> FactCategory:
        return "metric" if _PROFILE_METRIC.search(statement) else "bio"

    b.add_value("name", raw.display_name, "display_name")
    if raw.bio is None:
        b.add_value("bio", None, "bio")
    elif raw.collection_method in {"live_meta", "public_browser"}:
        bio_facts = [part.strip() for part in _BIO_FACT_SEPARATOR.split(raw.bio) if part.strip()]
        if raw.display_name:
            bio_facts = [part for part in bio_facts if part.casefold() != raw.display_name.casefold()]
        if raw.collection_method == "public_browser":
            bio_facts = [
                part for part in bio_facts
                if not _is_platform_boilerplate(part, raw.display_name)
            ]
        if not bio_facts:
            b.unknown.append("bio")
        for i, statement in enumerate(bio_facts):
            b.add(bio_category(statement), statement, f"bio[{i}]")
    else:
        if raw.display_name and raw.bio.casefold() == raw.display_name.casefold():
            b.unknown.append("bio")
        else:
            b.add(bio_category(raw.bio), raw.bio, "bio")
    b.add_list("work", info.work, "public_info.work")
    b.add_list("education", info.education, "public_info.education")
    b.add_list("interest", info.interests, "public_info.interests")
    b.add_value("location", info.current_city, "public_info.current_city")
    b.add_value("location", info.hometown, "public_info.hometown")
    b.add_value("pronouns", info.pronouns, "public_info.pronouns")
    b.add_value("gender", info.gender, "public_info.gender")
    b.add_value("birth_year", info.birth_year, "public_info.birth_year")
    # public_info.links are deliberately not ledgered: URLs must never appear in rapport messages.

    usable_posts = [
        (i, post)
        for i, post in enumerate(raw.public_posts)
        if raw.collection_method != "public_browser"
        or not _is_platform_boilerplate(post.text, raw.display_name)
    ]
    if not usable_posts:
        b.unknown.append("public_posts")
    for i, post in usable_posts:
        when = f"@{post.date.isoformat()}" if post.date else ""
        b.add("post", post.text, f"public_posts[{i}]{when}")

    if not raw.images:
        b.unknown.append("images")
    for i, image in enumerate(raw.images):
        # Provided alt text is a description supplied with the data; a vision description is added later
        # only for images without alt text.
        if image.alt_text:
            b.add("visual_observation", image.alt_text, f"images[{i}].alt_text")

    return FactLedger(facts=b.facts, unknown_fields=b.unknown)


def append_fact(
    ledger: FactLedger,
    category: FactCategory,
    statement: str,
    source: str,
    epistemic_status: EpistemicStatus = EpistemicStatus.FACT,
    confidence: float | None = None,
) -> tuple[FactLedger, Fact]:
    """Return a new ledger with one more entry (next free id). Existing ids never change."""
    next_id = max((int(f.id[1:]) for f in ledger.facts), default=0) + 1
    fact = Fact(
        id=f"F{next_id}",
        category=category,
        statement=statement,
        source=source,
        epistemic_status=epistemic_status,
        confidence=confidence,
    )
    return FactLedger(facts=[*ledger.facts, fact], unknown_fields=list(ledger.unknown_fields)), fact


def without_facts(ledger: FactLedger, fact_ids: set[str]) -> FactLedger:
    """Return a new ledger without the given entries (remaining ids unchanged)."""
    return FactLedger(
        facts=[f for f in ledger.facts if f.id not in fact_ids], unknown_fields=list(ledger.unknown_fields)
    )


@dataclass(frozen=True)
class GateResult:
    ok: bool
    reason_code: str | None = None
    note: str = ""


_BLOCKED_STATES: dict[AccessState, tuple[str, str]] = {
    AccessState.INVALID_INPUT: ("INVALID_INPUT", "INVALID_INPUT: Dữ liệu đầu vào không phải URL trang Facebook cá nhân hợp lệ."),
    AccessState.NO_ACCESSIBLE_DATA: ("NO_ACCESSIBLE_DATA", NO_DATA_LIMITATION),
    AccessState.LOGIN_REQUIRED: ("LOGIN_REQUIRED", LOGIN_LIMITATION),
    AccessState.PRIVATE: (
        "PRIVATE_PROFILE",
        "PRIVATE_PROFILE: Trang cá nhân bị khóa riêng tư, không có nội dung công khai để phân tích.",
    ),
    AccessState.NOT_FOUND: (
        "NOT_FOUND",
        "NOT_FOUND: Trang cá nhân không tồn tại hoặc không còn truy cập được (link chết).",
    ),
    AccessState.UNREACHABLE: (
        "UNREACHABLE",
        "UNREACHABLE: Không kết nối được tới trang cá nhân, chưa thu thập được dữ liệu nào.",
    ),
}


def evaluate_sufficiency(access_state: AccessState, ledger: FactLedger, settings: Settings) -> GateResult:
    """Decide whether a SUCCESS output may be produced. Never relaxes rules to force SUCCESS."""
    if access_state not in READABLE_STATES:
        code, note = _BLOCKED_STATES[access_state]
        return GateResult(ok=False, reason_code=code, note=note)

    if ledger.name_fact() is None:
        return GateResult(
            ok=False,
            reason_code="INSUFFICIENT_DATA",
            note="INSUFFICIENT_DATA: Không đọc được tên hiển thị của trang cá nhân.",
        )

    usable = ledger.usable_facts()
    if len(usable) < settings.min_grounding_facts:
        return GateResult(
            ok=False,
            reason_code="INSUFFICIENT_DATA",
            note=(
                f"INSUFFICIENT_DATA: Chỉ thu thập được {len(usable)} thông tin công khai ngoài tên "
                f"(cần tối thiểu {settings.min_grounding_facts}); không đủ dữ liệu thật để viết tin nhắn mà không bịa."
            ),
        )
    return GateResult(ok=True)
