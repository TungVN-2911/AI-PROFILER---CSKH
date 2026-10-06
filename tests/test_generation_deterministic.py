import pytest

from app.config import PROJECT_ROOT
from app.generation.deterministic import generate_deterministic
from app.guardrails import validate_draft
from app.ledger import build_ledger
from app.models import RawProfile
from app.sources.provided import load_raw_profile

RICH = load_raw_profile(PROJECT_ROOT / "fixtures" / "profiles" / "minh_anh.json")


def raw(**kwargs):
    return RawProfile.model_validate({"facebook_url": "https://www.facebook.com/x.y.z", "display_name": "Lan Chi", **kwargs})


MINIMAL = raw(bio="Yêu mèo và trà chiều", public_info={"current_city": "Huế"})  # exactly 2 usable facts


def test_rich_fixture_gives_ten_valid_messages():
    ledger = build_ledger(RICH)
    draft = generate_deterministic(ledger, 10)
    assert len(draft.messages) == 10
    assert validate_draft(draft, ledger) == []
    assert draft.messages[0].text.startswith("Chào Nguyễn Minh Anh")
    grounded = [m for m in draft.messages if m.kind == "grounded"]
    assert len(grounded) >= 5
    # Every grounded message cites exactly one fact whose text it contains.
    # Message 0 is the avatar greeting (name + image description); every other grounded message cites one fact.
    assert draft.messages[0].kind == "grounded" and "ảnh đại diện" in draft.messages[0].text
    for m in grounded[1:]:
        (fid,) = m.fact_ids
        assert ledger.get(fid).statement[:40] in m.text
    assert draft.evening_hook.fact_ids and draft.core_empathy_angle.fact_ids


def test_minimal_eligible_profile_gives_5_to_10_valid_messages():
    ledger = build_ledger(MINIMAL)
    draft = generate_deterministic(ledger, 10)
    assert 5 <= len(draft.messages) <= 10
    assert validate_draft(draft, ledger) == []
    assert sum(m.kind == "grounded" for m in draft.messages) == 2


@pytest.mark.parametrize("target", [5, 6, 7, 8, 9, 10])
def test_target_count_is_respected_and_valid(target):
    ledger = build_ledger(RICH)
    draft = generate_deterministic(ledger, target)
    assert len(draft.messages) == target
    assert validate_draft(draft, ledger) == []


def test_count_is_reduced_not_padded_with_three_facts():
    profile = raw(bio="Yêu mèo", public_info={"current_city": "Huế", "interests": ["vẽ màu nước"]})
    ledger = build_ledger(profile)
    draft = generate_deterministic(ledger, 10)
    assert len(draft.messages) == 6  # 3 grounded + 3 neutral keeps ≥ half grounded
    assert validate_draft(draft, ledger) == []


def test_deterministic_same_input_same_output():
    ledger = build_ledger(RICH)
    assert generate_deterministic(ledger, 10) == generate_deterministic(build_ledger(RICH), 10)


def test_facts_with_prices_or_links_are_skipped():
    profile = raw(
        bio="Chuyên order hàng Nhật giá 199k, ib zalo 0912345678",
        public_posts=[{"text": "Ghé https://shop.example.vn nhé"}, {"text": "Hoàn thành bức tranh màu nước đầu tiên"}],
        public_info={"interests": ["vẽ màu nước"], "current_city": "Đà Nẵng"},
    )
    ledger = build_ledger(profile)
    draft = generate_deterministic(ledger, 10)
    assert validate_draft(draft, ledger) == []
    joined = " ".join(m.text for m in draft.messages) + draft.evening_hook.text + draft.core_empathy_angle.text
    assert "199k" not in joined and "https" not in joined and "0912" not in joined


def test_customer_quoting_own_tiredness_is_not_presumption():
    profile = raw(public_posts=[{"text": "Hôm nay mệt mỏi quá nhưng vẫn đi bơi"}], public_info={"interests": ["bơi lội"]})
    ledger = build_ledger(profile)
    draft = generate_deterministic(ledger, 10)
    assert validate_draft(draft, ledger) == []
    assert any("mệt mỏi" in m.text for m in draft.messages)


def test_long_post_is_clipped():
    profile = raw(public_posts=[{"text": "Hôm nay " + "đi dạo quanh hồ " * 20}], public_info={"interests": ["đi dạo"]})
    ledger = build_ledger(profile)
    draft = generate_deterministic(ledger, 10)
    assert validate_draft(draft, ledger) == []
    assert all(len(m.text) <= 400 for m in draft.messages)
    assert any("…" in m.text for m in draft.messages)


def test_hometown_and_education_templates():
    profile = raw(public_info={"hometown": "Nam Định", "education": ["Trường THPT Lê Hồng Phong"]})
    ledger = build_ledger(profile)
    draft = generate_deterministic(ledger, 10)
    assert validate_draft(draft, ledger) == []
    texts = " ".join(m.text for m in draft.messages)
    assert "Quê bạn ở Nam Định" in texts and "từng học tại" in texts


def test_no_usable_facts_raises():
    with pytest.raises(ValueError):
        generate_deterministic(build_ledger(raw()), 10)


def test_messages_contain_no_inference_or_demographics():
    profile = raw(bio="Yêu mèo", public_info={"current_city": "Huế", "pronouns": "she/her", "birth_year": 1990})
    ledger = build_ledger(profile)
    draft = generate_deterministic(ledger, 10)
    texts = " ".join(m.text for m in draft.messages) + draft.evening_hook.text
    assert "she/her" not in texts and "1990" not in texts


def test_hook_fact_not_repeated_in_sequence_when_enough_facts():
    draft = generate_deterministic(build_ledger(RICH), 10)
    hook_id = draft.evening_hook.fact_ids[0]
    assert all(hook_id not in m.fact_ids for m in draft.messages)
    # Greeting (now grounded on the avatar) + at least one open question + closing.
    assert "ảnh đại diện" in draft.messages[0].text
    assert sum(m.kind == "neutral" for m in draft.messages) >= 2


def test_template_variety_within_category():
    draft = generate_deterministic(build_ledger(RICH), 10)
    openings = [m.text[:20] for m in draft.messages if m.kind == "grounded"]
    assert len(set(openings)) == len(openings)


def test_raises_when_too_few_facts_are_safe_to_quote():
    profile = raw(
        bio="Order hàng giá 199k",
        public_posts=[{"text": "Ghé https://a.example.vn"}, {"text": "Liên hệ 0912345678"}],
        public_info={"interests": ["vẽ"]},
    )
    with pytest.raises(ValueError):
        generate_deterministic(build_ledger(profile), 10)


def test_bug001_no_double_punctuation_after_quotes_in_any_fixture():
    import re

    store = PROJECT_ROOT / "fixtures" / "profiles"
    checked = 0
    for path in sorted(store.glob("*.json")):
        profile = load_raw_profile(path)
        ledger = build_ledger(profile)
        if len(ledger.usable_facts()) < 2:
            continue
        draft = generate_deterministic(ledger, 10)
        texts = [m.text for m in draft.messages] + [draft.evening_hook.text, draft.core_empathy_angle.text]
        for text in texts:
            assert not re.search(r"[.!?…]”\.", text), text
        assert validate_draft(draft, ledger) == []
        checked += 1
    assert checked >= 5


def test_bug001_plain_quote_keeps_its_period():
    from app.generation.deterministic import _tidy

    assert _tidy("mừng ghê.”. Chuyện") == "mừng ghê.” Chuyện"
    assert _tidy("vui!”. Khi") == "vui!” Khi"
    assert _tidy("sourdough”.") == "sourdough”."


# --- Forms of address (CR-001, TASK-023) ----------------------------------------------------

import re  # noqa: E402

from app.intel import NEUTRAL_ADDRESSING, Addressing  # noqa: E402

CHI = Addressing("chị", "em", "test")
ANH = Addressing("anh", "em", "test")
STANDALONE_BAN = re.compile(r"(?<!\w)bạn(?!\w)", re.IGNORECASE)


def all_texts(draft):
    return [m.text for m in draft.messages] + [draft.evening_hook.text, draft.core_empathy_angle.text]


@pytest.mark.parametrize("addressing,word", [(CHI, "chị"), (ANH, "anh")])
def test_polite_addressing_replaces_ban_minh(addressing, word):
    ledger = build_ledger(RICH)
    draft = generate_deterministic(ledger, 10, addressing)
    assert validate_draft(draft, ledger) == []
    texts = all_texts(draft)
    assert not any(STANDALONE_BAN.search(t) for t in texts)
    assert not any(re.search(r"(?<!\w)mình(?!\w)", t, re.IGNORECASE) for t in texts)
    assert draft.messages[0].text == (
        f"Em chào {word} Minh Anh ạ! Em vừa ghé thăm trang cá nhân của {word}, "
        "ấn tượng đầu tiên là tấm ảnh đại diện nhìn thật dễ mến."
    )
    assert any(t.endswith(" ạ?") for t in texts)  # polite particle on questions
    assert sum(word in t for t in texts) >= 8


def test_neutral_addressing_unchanged():
    draft = generate_deterministic(build_ledger(RICH), 10, NEUTRAL_ADDRESSING)
    assert draft == generate_deterministic(build_ledger(RICH), 10)
    assert draft.messages[0].text.startswith("Chào Nguyễn Minh Anh! Mình vừa ghé thăm")
    assert not any(t.endswith(" ạ?") for t in all_texts(draft))


def test_customer_quote_is_never_rewritten_and_braces_are_safe():
    profile = raw(
        public_posts=[{"text": "Cảm ơn các bạn đã đến dự {sinh nhật} của mình!"}],
        public_info={"interests": ["đan len"], "current_city": "Huế"},
    )
    ledger = build_ledger(profile)
    draft = generate_deterministic(ledger, 10, CHI)
    assert validate_draft(draft, ledger) == []
    quoted = [t for t in all_texts(draft) if "Cảm ơn các bạn" in t]
    assert quoted and "Cảm ơn các bạn đã đến dự {sinh nhật} của mình!" in quoted[0]


def test_deterministic_never_quotes_brand_or_product_facts():
    profile = raw(
        bio="Đang dùng thử dầu gội Dr.Bee",
        public_posts=[{"text": "Dạo này rụng tóc nhiều quá"}, {"text": "Vườn rau ban công đã lên mầm"}],
        public_info={"interests": ["làm vườn", "nấu ăn"], "current_city": "Huế"},
    )
    ledger = build_ledger(profile)
    draft = generate_deterministic(ledger, 10)
    assert validate_draft(draft, ledger) == []
    joined = " ".join(all_texts(draft))
    assert "Dr.Bee" not in joined and "rụng tóc" not in joined and "dầu gội" not in joined


# --- Emotional quality (CR-003, TASK-026) ---------------------------------------------------


def test_work_hook_uses_relaxing_evening_wish():
    profile = raw(
        public_info={"work": ["Điều dưỡng tại Bệnh viện Hòa An"], "current_city": "Huế"},
        images=[{"kind": "avatar", "alt_text": "Ảnh đại diện có vẻ cho thấy một người mỉm cười"}],
    )
    ledger = build_ledger(profile)
    draft = generate_deterministic(ledger, 10)
    assert validate_draft(draft, ledger) == []
    work = next(f for f in ledger.facts if f.category == "work")
    assert draft.evening_hook.fact_ids == [work.id]
    assert "sau giờ làm việc" in draft.evening_hook.text and draft.evening_hook.text.startswith("Buổi tối an lành")


def test_every_fixture_draft_is_warm_and_valid():
    for path in sorted((PROJECT_ROOT / "fixtures" / "profiles").glob("*.json")):
        ledger = build_ledger(load_raw_profile(path))
        if len(ledger.usable_facts()) < 2 or not any(f.category == "visual_observation" for f in ledger.facts):
            continue
        draft = generate_deterministic(ledger, 10)
        assert validate_draft(draft, ledger) == []
        assert "ảnh đại diện" in draft.messages[0].text
        assert not any("đúng không" in t or "phải không" in t for t in all_texts(draft))
