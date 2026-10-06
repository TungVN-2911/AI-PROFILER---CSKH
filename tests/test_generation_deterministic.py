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
    for m in grounded:
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
    assert "quê ở Nam Định" in texts and "phần học vấn" in texts


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
    assert sum(m.kind == "neutral" for m in draft.messages) >= 3  # greeting, open question, closing


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
