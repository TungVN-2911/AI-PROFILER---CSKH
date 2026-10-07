"""Deterministic (template) generator: offline, always available, fully grounded.

Each grounded message quotes or names exactly one cited fact; neutral messages are greetings or open
questions that claim nothing about the customer. Every rendered candidate is checked with the guardrails
and dropped if it fails, so unusual fact text (prices, links, very long posts) never leaks into messages.
When there are few facts the sequence gets shorter (never below 5) instead of being padded with claims.
"""

from __future__ import annotations

import math
import re

from app.guardrails import CitedText, DraftMessage, EngagementDraft, check_entities, check_text
from app.intel import NEUTRAL_ADDRESSING, Addressing
from app.models import Fact, FactLedger
from app.schema import MAX_MESSAGES, MIN_MESSAGES

MAX_QUOTE_CHARS = 120

# Grounded-message priority: the customer's own recent words first.
CATEGORY_ORDER = ("post", "interest", "bio", "work", "education", "location", "visual_observation", "other")

# Templates use {you}/{You} (customer) and {me}/{Me} (agent) from `Addressing`; {s} is the quoted fact text,
# inserted last so that braces or pronouns inside the customer's own words are never altered.
NEUTRAL_QUESTIONS = (
    "Dạo này có điều gì nhỏ nhỏ khiến {you} mỉm cười không{q}?",
    "Cuối tuần {you} thường dành thời gian cho điều gì để nạp lại năng lượng{q}?",
    "Nếu có cuốn sách hay bộ phim nào {you} thấy đáng xem, {you} giới thiệu cho {me} với được không{q}?",
    "{Me} luôn ở đây lắng nghe nếu {you} muốn chia sẻ thêm bất cứ điều gì.",
)
CLOSING = "Trò chuyện cùng {you} thật sự là niềm vui của {me}. Chúc {you} một ngày thật nhẹ nhàng và nhiều niềm vui nhé!"
GREETING_NEUTRAL = "Chào {name}, mình rất vui được làm quen với bạn!"
GREETING_POLITE = "{Me} chào {you} {name}, {me} rất vui được làm quen với {you} ạ!"
# The first message mentions a first impression of the profile picture when an image description exists.
AVATAR_IMPRESSION = "{Me} vừa ghé thăm trang cá nhân của {you}, ấn tượng đầu tiên là tấm ảnh đại diện nhìn thật dễ mến."
ANGLE = "{Me} trân trọng chia sẻ của {you}: {s}"

_QUOTE_SLOT = "\ue000"


def _fill(template: str, addressing: Addressing, s: str = "", **extra: str) -> str:
    text = template.replace("{s}", _QUOTE_SLOT).format(**addressing.fields(), **extra)
    return text.replace(_QUOTE_SLOT, s)


def _clip(text: str, limit: int = MAX_QUOTE_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > 0 else limit].rstrip(" ,;:-") + "…"


POST_TEMPLATES = (
    "{Me} có đọc dòng {you} chia sẻ: “{s}”. Những khoảnh khắc như vậy thật đáng trân trọng, {you} kể {me} nghe thêm được không{q}?",
    "Đọc bài viết “{s}” của {you}, {me} thấy thật gần gũi. Lúc ấy {you} cảm thấy thế nào{q}?",
    "{Me} nhớ {you} từng viết: “{s}”. Cảm ơn {you} đã chia sẻ thật chân thành, {me} rất muốn nghe câu chuyện phía sau{q}.",
)
INTEREST_TEMPLATES = (
    "{Me} thấy {you} có niềm yêu thích với {s}, nghe thôi đã thấy thật thú vị. Điều gì khiến {you} gắn bó với {s} vậy{q}?",
    "{You} bắt đầu đến với {s} từ khi nào vậy{q}? {Me} rất tò mò về hành trình ấy.",
    "Dành thời gian cho {s} là một cách chăm sóc tâm hồn thật đẹp. {You} có bí quyết nhỏ nào muốn chia sẻ không{q}?",
)
# Each category offers a few phrasings; the per-category variant counter cycles through them so a customer
# with several facts of one kind (two schools, two jobs) never gets two identically worded messages.
CATEGORY_TEMPLATES = {
    "bio": (
        "{Me} rất thích cách {you} giới thiệu bản thân: “{s}”. Đọc là thấy ngay nét riêng thật đáng mến của {you}.",
        "Dòng giới thiệu “{s}” của {you} thật có duyên. {Me} đọc mà thấy quý cái nét riêng ấy.",
        "{Me} ấn tượng với cách {you} viết về mình: “{s}”. Nghe thật gần gũi và chân thành.",
    ),
    "work": (
        "{Me} thấy {you} đang gắn bó với công việc “{s}”. Công việc nào cũng có những vất vả riêng, {me} thật sự nể {you}. "
        "Điều gì ở công việc này khiến {you} thấy vui nhất{q}?",
        "{Me} có thấy {you} làm “{s}”. {Me} luôn trân trọng những người gắn bó với nghề của mình, {you} kể {me} nghe cơ duyên "
        "đến với công việc này nhé{q}?",
        "Nghề “{s}” của {you} thật ý nghĩa. {Me} rất muốn biết điều gì khiến {you} chọn gắn bó với công việc này{q}?",
    ),
    "education": (
        "{Me} thấy {you} từng học tại “{s}”. Quãng thời gian ấy hẳn có nhiều kỷ niệm đẹp, {you} nhớ nhất điều gì{q}?",
        "{Me} thấy {you} có thời gian học ở “{s}”. Mỗi ngôi trường đều mang một màu kỷ niệm riêng, {you} nhớ nhất điều gì ở nơi đó{q}?",
        "“{s}” là nơi {you} từng theo học. {Me} rất tò mò, kỷ niệm nào ở đó khiến {you} mỉm cười mỗi khi nhớ lại{q}?",
    ),
    "hometown": (
        "Quê {you} ở {s}, nghe thôi đã thấy thân thương. Ở {s} có món ăn hay góc nhỏ nào {you} nhớ nhất không{q}?",
    ),
    "location": (
        "{You} đang sống ở {s}, một nơi có nhiều nét riêng thật đáng yêu. Ở {s}, {you} hay ghé góc nào nhất{q}?",
        "{Me} thấy {you} đang ở {s}. {Me} nghe nói nơi này có nhiều điều thú vị, {you} thích nhất điều gì ở {s} vậy{q}?",
        "Sống ở {s} hẳn có nhiều điều để khám phá. {You} có nơi quen thuộc nào ở {s} muốn kể cho {me} nghe không{q}?",
    ),
    "visual_observation": (
        "Tấm ảnh đại diện của {you} nhìn thật dễ mến, {me} xem mà thấy nhẹ nhõm hẳn. "
        "Bức ảnh ấy có câu chuyện gì đặc biệt không{q}?",
    ),
    "other": (
        "{Me} có để ý {you} chia sẻ “{s}”. {Me} rất muốn nghe thêm về điều này{q}.",
        "{You} có nhắc tới “{s}”. {Me} thấy điều này thật thú vị, {you} kể {me} nghe thêm nhé{q}?",
        "{Me} đọc được chia sẻ “{s}” của {you}. {Me} rất muốn hiểu thêm về điều đó{q}.",
    ),
}
HOOK_TOPICS = {
    "interest": "niềm yêu thích {s} của {you}",
    "education": "quãng thời gian {you} học tại “{s}”",
    "hometown": "quê {you} ở {s}",
    "location": "{s}, nơi {you} đang sống",
    "other": "điều {you} từng chia sẻ: “{s}”",
}
HOOK = "Buổi tối an lành nhé {you}! {Me} chợt nhớ tới {topic}. Nếu {you} muốn, {you} kể {me} nghe thêm về điều đó nhé."


def _pick(templates: tuple[str, ...], variant: int) -> str:
    return templates[variant % len(templates)]


def _render_message(fact: Fact, variant: int, addressing: Addressing) -> str:
    s = _clip(fact.statement)
    if fact.category == "post":
        template = _pick(POST_TEMPLATES, variant)
    elif fact.category == "interest":
        template = _pick(INTEREST_TEMPLATES, variant)
    elif fact.category == "location" and fact.source.endswith("hometown"):
        template = CATEGORY_TEMPLATES["hometown"][0]
    else:
        template = _pick(CATEGORY_TEMPLATES.get(fact.category, CATEGORY_TEMPLATES["other"]), variant)
    return _fill(template, addressing, s)


def _render_hook(fact: Fact, addressing: Addressing) -> str:
    key = "hometown" if fact.category == "location" and fact.source.endswith("hometown") else fact.category
    topic = HOOK_TOPICS.get(key, HOOK_TOPICS["other"])
    return _fill(HOOK.replace("{topic}", topic), addressing, _clip(fact.statement))


_DOUBLE_PUNCT = re.compile(r"([.!?…])”\.")


def _tidy(text: str) -> str:
    """Drop the template's period after a quote that already ends a sentence (`ghê.”.` → `ghê.”`)."""
    return _DOUBLE_PUNCT.sub(r"\1”", text)


def _message_for(fact: Fact, variant: int = 0, addressing: Addressing = NEUTRAL_ADDRESSING) -> str:
    return _tidy(_render_message(fact, variant, addressing))


def _hook_for(fact: Fact, addressing: Addressing = NEUTRAL_ADDRESSING) -> str:
    return _tidy(_render_hook(fact, addressing))


def _avatar_greeting(ledger: FactLedger, name: Fact | None, addressing: Addressing) -> DraftMessage | None:
    """Warm greeting + first impression of the profile picture, grounded on the image description."""
    visual = next((f for f in ledger.facts if f.category == "visual_observation"), None)
    if visual is None:
        return None
    if addressing.is_neutral:
        hello = f"Chào {name.statement}!" if name else "Chào bạn!"
    else:
        hello = _fill("{Me} chào {you} {name} ạ!", addressing, name=_short_name(name.statement) if name else "").replace("  ", " ")
    text = f"{hello} {_fill(AVATAR_IMPRESSION, addressing)}"
    if not _passes(text, visual, ledger, "messages[0]"):
        return None
    return DraftMessage(text=text, kind="grounded", fact_ids=[*([name.id] if name else []), visual.id])


def _short_name(full: str) -> str:
    """Vietnamese given name for "chị/anh <name>": the last two words of a 3+ word name."""
    words = full.split()
    return " ".join(words[-2:]) if len(words) >= 3 else full


def _passes(text: str, fact: Fact, ledger: FactLedger, location: str) -> bool:
    return not check_text(text, location, [fact]) and not check_entities(text, location, [fact], ledger.name_fact())


def _grounded_candidates(ledger: FactLedger, addressing: Addressing) -> list[tuple[Fact, str]]:
    usable = ledger.usable_facts()
    ordered = sorted(usable, key=lambda f: (CATEGORY_ORDER.index(f.category) if f.category in CATEGORY_ORDER else 99, int(f.id[1:])))
    out = []
    per_category: dict[str, int] = {}
    visual_used = False
    for fact in ordered:
        if fact.category == "visual_observation":
            if visual_used:
                continue
            visual_used = True
        variant = per_category.get(fact.category, 0)
        text = _message_for(fact, variant, addressing)
        if _passes(text, fact, ledger, "messages"):
            out.append((fact, text))
            per_category[fact.category] = variant + 1
    return out


def generate_deterministic(
    ledger: FactLedger, target_count: int = MAX_MESSAGES, addressing: Addressing = NEUTRAL_ADDRESSING
) -> EngagementDraft:
    """Build a draft from the ledger. Raises ValueError if there is nothing usable to ground on."""
    candidates = _grounded_candidates(ledger, addressing)
    if len(candidates) < 2:
        raise ValueError("cần ít nhất hai thông tin an toàn để tạo chuỗi tin nhắn có căn cứ")

    # The strongest fact becomes the evening hook; it is not repeated in the sequence when others remain.
    hook = None
    for fact, _ in candidates:
        text = _hook_for(fact, addressing)
        if _passes(text, fact, ledger, "evening_hook"):
            hook = CitedText(text=text, fact_ids=[fact.id])
            break
    if hook is None:
        raise ValueError("không có thông tin nào làm căn cứ được cho câu mồi 20h")
    # Reserving it needs ≥ 3 other facts so the sequence can stay at least half grounded.
    if len(candidates) >= 4:
        candidates = [(f, t) for f, t in candidates if f.id != hook.fact_ids[0]]

    name = ledger.name_fact()
    greeting = _avatar_greeting(ledger, name, addressing)
    if greeting is not None:
        # The avatar is already acknowledged in the greeting; do not repeat it as a separate message.
        candidates = [(f, t) for f, t in candidates if f.id not in greeting.fact_ids]
    grounded_greeting = 1 if greeting is not None else 0
    neutral_pool = len(NEUTRAL_QUESTIONS) + 2  # greeting + questions + closing
    g_available = len(candidates)
    n = min(max(target_count, MIN_MESSAGES), MAX_MESSAGES, g_available + neutral_pool)
    if len(ledger.usable_facts()) >= 3:
        n = min(n, 2 * (g_available + grounded_greeting))  # keep ≥ ⌈n/2⌉ grounded
    n = max(n, MIN_MESSAGES)
    if len(ledger.usable_facts()) >= 3 and g_available + grounded_greeting < math.ceil(n / 2):
        raise ValueError("quá ít thông tin an toàn để trích dẫn, không giữ được tối thiểu một nửa số tin nhắn có căn cứ")
    min_neutral = 3 if n >= 8 else 1  # greeting (+ one open question + closing in longer sequences)
    g = min(g_available, n - min_neutral)
    neutral_needed = n - g

    if greeting is None:
        if addressing.is_neutral:
            greeting_text = GREETING_NEUTRAL.format(name=name.statement) if name else "Chào bạn, mình rất vui được làm quen với bạn!"
        else:
            greeting_text = _fill(GREETING_POLITE, addressing, name=_short_name(name.statement) if name else "").replace("  ", " ")
        greeting = DraftMessage(text=greeting_text, kind="neutral", fact_ids=[name.id] if name else [])
    extras = neutral_needed - 1
    closing = [DraftMessage(text=_fill(CLOSING, addressing), kind="neutral")] if extras >= 1 else []
    questions = [DraftMessage(text=_fill(q, addressing), kind="neutral") for q in NEUTRAL_QUESTIONS[: max(extras - 1, 0)]]
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
        text=_fill(ANGLE, addressing, "; ".join(f"“{_clip(f.statement, 60)}”" for f in angle_facts)),
        fact_ids=[f.id for f in angle_facts],
    )

    if len(messages) != n:  # defensive: composition arithmetic must hold
        raise ValueError(f"composed {len(messages)} messages, expected {n}")
    return EngagementDraft(core_empathy_angle=angle, messages=messages, evening_hook=hook)
