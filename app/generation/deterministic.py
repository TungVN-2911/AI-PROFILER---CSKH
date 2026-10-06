"""Deterministic (template) generator: offline, always available, fully grounded (FR-015, NFR-004).

Each grounded message quotes or names exactly one cited fact; neutral messages are greetings or open
questions that claim nothing about the customer. Every rendered candidate is checked with the guardrails
and dropped if it fails, so unusual fact text (prices, links, very long posts) never leaks into messages.
When there are few facts the sequence gets shorter (never below 5) instead of being padded with claims.
"""

from __future__ import annotations

import math
import re

from app.guardrails import CitedText, DraftMessage, EngagementDraft, check_entities, check_text
from app.models import Fact, FactLedger
from app.schema import MAX_MESSAGES, MIN_MESSAGES

MAX_QUOTE_CHARS = 120

# Grounded-message priority: the customer's own recent words first.
CATEGORY_ORDER = ("post", "interest", "bio", "work", "education", "location", "visual_observation", "other")

NEUTRAL_QUESTIONS = (
    "Dạo này có điều gì nhỏ nhỏ khiến bạn thấy vui không?",
    "Cuối tuần bạn thường thích làm gì để thư giãn?",
    "Nếu có cuốn sách hay bộ phim nào bạn thấy đáng xem, bạn giới thiệu mình với được không?",
    "Mình luôn sẵn lòng lắng nghe nếu bạn muốn trò chuyện thêm.",
)
CLOSING = "Rất vui được trò chuyện với bạn, hẹn sớm nói chuyện tiếp nhé!"


def _clip(text: str, limit: int = MAX_QUOTE_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > 0 else limit].rstrip(" ,;:-") + "…"


POST_TEMPLATES = (
    "Mình có đọc bài bạn chia sẻ: “{s}”. Bạn có muốn kể thêm một chút về chuyện đó không?",
    "Bài viết “{s}” của bạn làm mình ấn tượng ghê. Lúc đó bạn cảm thấy thế nào?",
    "Mình nhớ bạn có viết: “{s}”. Chuyện đó có gì thú vị, bạn kể mình nghe với?",
)
INTEREST_TEMPLATES = (
    "Mình thấy bạn có nhắc đến sở thích {s}. Điều gì khiến bạn gắn bó với {s} vậy?",
    "Bạn bắt đầu thích {s} từ khi nào vậy?",
    "Với {s}, bạn có mẹo nhỏ nào muốn chia sẻ cho người mới bắt đầu không?",
)


def _render_message(fact: Fact, variant: int = 0) -> str:
    s = _clip(fact.statement)
    if fact.category == "post":
        return POST_TEMPLATES[variant % len(POST_TEMPLATES)].format(s=s)
    if fact.category == "interest":
        return INTEREST_TEMPLATES[variant % len(INTEREST_TEMPLATES)].format(s=s)
    if fact.category == "bio":
        return f"Mình rất thích phần giới thiệu của bạn: “{s}”."
    if fact.category == "work":
        return f"Mình thấy bạn có ghi “{s}” ở phần công việc. Bạn thấy điều gì thú vị nhất trong công việc này?"
    if fact.category == "education":
        return f"Mình thấy bạn có ghi “{s}” ở phần học vấn. Quãng thời gian đó có kỷ niệm nào đáng nhớ không bạn?"
    if fact.category == "location":
        if fact.source.endswith("hometown"):
            return f"Mình thấy bạn có ghi quê ở {s}. Ở {s} có điều gì bạn nhớ nhất không?"
        return f"Mình thấy bạn có ghi nơi sống hiện tại là {s}. Ở {s} bạn thích ghé chỗ nào nhất?"
    if fact.category == "visual_observation":
        return f"Mình có xem ảnh đại diện của bạn ({s}). Bức ảnh đó có câu chuyện gì đặc biệt không?"
    return f"Mình có để ý bạn ghi “{s}”. Bạn có thể kể thêm không?"


def _render_hook(fact: Fact) -> str:
    s = _clip(fact.statement)
    if fact.category == "interest":
        topic = f"sở thích {s} mà bạn có nhắc đến"
    elif fact.category == "work":
        topic = f"công việc “{s}” bạn có ghi trên trang cá nhân"
    elif fact.category == "education":
        topic = f"quãng thời gian ở “{s}” bạn có ghi trên trang cá nhân"
    elif fact.category == "location":
        topic = f"{s} mà bạn có ghi trên trang cá nhân"
    else:
        topic = f"điều bạn từng chia sẻ: “{s}”"
    return f"Chào buổi tối! Mình chợt nhớ tới {topic}. Khi nào rảnh, bạn kể mình nghe thêm nhé?"


_DOUBLE_PUNCT = re.compile(r"([.!?…])”\.")


def _tidy(text: str) -> str:
    """Drop the template's period after a quote that already ends a sentence (`ghê.”.` → `ghê.”`)."""
    return _DOUBLE_PUNCT.sub(r"\1”", text)


def _message_for(fact: Fact, variant: int = 0) -> str:
    return _tidy(_render_message(fact, variant))


def _hook_for(fact: Fact) -> str:
    return _tidy(_render_hook(fact))


def _passes(text: str, fact: Fact, ledger: FactLedger, location: str) -> bool:
    return not check_text(text, location, [fact]) and not check_entities(text, location, [fact], ledger.name_fact())


def _grounded_candidates(ledger: FactLedger) -> list[tuple[Fact, str]]:
    usable = ledger.usable_facts()
    ordered = sorted(usable, key=lambda f: (CATEGORY_ORDER.index(f.category) if f.category in CATEGORY_ORDER else 99, int(f.id[1:])))
    out = []
    per_category: dict[str, int] = {}
    for fact in ordered:
        variant = per_category.get(fact.category, 0)
        text = _message_for(fact, variant)
        if _passes(text, fact, ledger, "messages"):
            out.append((fact, text))
            per_category[fact.category] = variant + 1
    return out


def generate_deterministic(ledger: FactLedger, target_count: int = MAX_MESSAGES) -> EngagementDraft:
    """Build a draft from the ledger. Raises ValueError if there is nothing usable to ground on."""
    candidates = _grounded_candidates(ledger)
    if not candidates:
        raise ValueError("no usable facts to ground rapport messages on")

    # The strongest fact becomes the evening hook; it is not repeated in the sequence when others remain.
    hook = None
    for fact, _ in candidates:
        text = _hook_for(fact)
        if _passes(text, fact, ledger, "evening_hook"):
            hook = CitedText(text=text, fact_ids=[fact.id])
            break
    if hook is None:
        raise ValueError("no fact could ground an evening hook")
    # Reserving it needs ≥ 3 other facts so the sequence can stay at least half grounded.
    if len(candidates) >= 4:
        candidates = [(f, t) for f, t in candidates if f.id != hook.fact_ids[0]]

    name = ledger.name_fact()
    neutral_pool = len(NEUTRAL_QUESTIONS) + 2  # greeting + questions + closing
    g_available = len(candidates)
    n = min(max(target_count, MIN_MESSAGES), MAX_MESSAGES, g_available + neutral_pool)
    if len(ledger.usable_facts()) >= 3:
        n = min(n, 2 * g_available)  # keep ≥ ⌈n/2⌉ grounded
    n = max(n, MIN_MESSAGES)
    if len(ledger.usable_facts()) >= 3 and g_available < math.ceil(n / 2):
        raise ValueError("too few facts are safe to quote to keep the sequence at least half grounded")
    min_neutral = 3 if n >= 8 else 1  # greeting (+ one open question + closing in longer sequences)
    g = min(g_available, n - min_neutral)
    neutral_needed = n - g

    greeting = DraftMessage(
        text=f"Chào {name.statement}, mình rất vui được làm quen với bạn!" if name else "Chào bạn, mình rất vui được làm quen với bạn!",
        kind="neutral",
        fact_ids=[name.id] if name else [],
    )
    extras = neutral_needed - 1
    closing = [DraftMessage(text=CLOSING, kind="neutral")] if extras >= 1 else []
    questions = [DraftMessage(text=q, kind="neutral") for q in NEUTRAL_QUESTIONS[: max(extras - 1, 0)]]
    grounded = [DraftMessage(text=text, kind="grounded", fact_ids=[fact.id]) for fact, text in candidates[:g]]

    # Interleave: a neutral question after every three grounded messages.
    middle: list[DraftMessage] = []
    q = iter(questions)
    for i, msg in enumerate(grounded, 1):
        middle.append(msg)
        if i % 3 == 0:
            nxt = next(q, None)
            if nxt:
                middle.append(nxt)
    middle.extend(q)
    messages = [greeting, *middle, *closing]

    angle_facts = [ledger.get(hook.fact_ids[0])] + [fact for fact, _ in candidates[:1]]
    angle = CitedText(
        text="Quan tâm chân thành tới những điều bạn ấy tự chia sẻ công khai: "
        + "; ".join(f"“{_clip(f.statement, 60)}”" for f in angle_facts),
        fact_ids=[f.id for f in angle_facts],
    )

    if len(messages) != n:  # defensive: composition arithmetic must hold
        raise ValueError(f"composed {len(messages)} messages, expected {n}")
    return EngagementDraft(core_empathy_angle=angle, messages=messages, evening_hook=hook)
