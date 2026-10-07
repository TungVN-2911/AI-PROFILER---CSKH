import pytest

from app.config import PROJECT_ROOT, load_settings
from app.ledger import TRACKED_FIELDS, build_ledger, evaluate_sufficiency
from app.models import AccessState, EpistemicStatus, FactLedger, RawProfile
from app.sources.provided import load_raw_profile

SETTINGS = load_settings(env={}, dotenv_path=None)
RICH = load_raw_profile(PROJECT_ROOT / "fixtures" / "profiles" / "minh_anh.json")


def raw(**kwargs):
    return RawProfile.model_validate({"facebook_url": "https://www.facebook.com/x.y.z", **kwargs})


def test_rich_fixture_produces_sourced_facts():
    ledger = build_ledger(RICH)
    assert len(ledger.facts) >= 4
    assert all(f.epistemic_status is EpistemicStatus.FACT for f in ledger.facts)
    assert [f.id for f in ledger.facts] == [f"F{i}" for i in range(1, len(ledger.facts) + 1)]

    by_source = {f.source: f for f in ledger.facts}
    assert by_source["fixture:display_name"].statement == "Nguyễn Minh Anh"
    assert by_source["fixture:display_name"].category == "name"
    assert by_source["fixture:bio"].statement == RICH.bio
    assert by_source["fixture:public_info.work[0]"].category == "work"
    assert by_source["fixture:public_info.interests[0]"].statement == "chạy bộ"
    assert by_source["fixture:public_info.current_city"].category == "location"
    assert by_source["fixture:public_posts[0]@2026-09-28"].category == "post"
    assert by_source["fixture:images[0].alt_text"].category == "visual_observation"
    assert len(ledger.usable_facts()) >= 8


def test_every_statement_is_verbatim_from_input():
    ledger = build_ledger(RICH)
    dumped = RICH.model_dump_json()
    for fact in ledger.facts:
        assert fact.statement in dumped or fact.statement in RICH.bio


def test_rich_fixture_unknown_fields_are_listed_not_filled():
    ledger = build_ledger(RICH)
    assert {"hometown", "pronouns", "gender", "birth_year"} <= set(ledger.unknown_fields)
    categories = {f.category for f in ledger.facts}
    assert not categories & {"pronouns", "gender", "birth_year"}


def test_missing_bio_is_unknown_and_not_fabricated():
    ledger = build_ledger(raw(display_name="A B", public_info={"interests": ["đọc sách"]}))
    assert "bio" in ledger.unknown_fields
    assert all(f.category != "bio" for f in ledger.facts)


def test_none_raw_gives_empty_ledger_with_all_fields_unknown():
    ledger = build_ledger(None)
    assert ledger.facts == []
    assert ledger.unknown_fields == list(TRACKED_FIELDS)


def test_demographic_facts_recorded_but_not_usable_for_grounding():
    ledger = build_ledger(raw(display_name="A", public_info={"pronouns": "she/her", "gender": "Nữ", "birth_year": 1995}))
    assert {f.category for f in ledger.facts} == {"name", "pronouns", "gender", "birth_year"}
    assert ledger.usable_facts() == []


def test_duplicates_are_collapsed_and_links_ignored():
    ledger = build_ledger(
        raw(display_name="A", public_info={"interests": ["Chạy bộ", "chạy bộ"], "links": ["https://shop.example"]})
    )
    assert [f.statement for f in ledger.facts if f.category == "interest"] == ["Chạy bộ"]
    assert all("http" not in f.statement for f in ledger.facts)


def test_image_without_alt_text_adds_no_fact():
    ledger = build_ledger(raw(display_name="A", images=[{"kind": "avatar", "path": "a.jpg"}]))
    assert all(f.category != "visual_observation" for f in ledger.facts)
    assert "images" not in ledger.unknown_fields


def test_source_prefix_uses_collection_method():
    ledger = build_ledger(raw(display_name="A", collection_method="live_meta"))
    assert ledger.facts[0].source == "live_meta:display_name"


def test_public_browser_bio_is_split_into_groundable_clauses():
    ledger = build_ledger(
        raw(
            display_name="A",
            bio="Yêu mèo · Thích đọc sách",
            collection_method="public_browser",
        )
    )
    assert [fact.statement for fact in ledger.facts if fact.category == "bio"] == [
        "Yêu mèo",
        "Thích đọc sách",
    ]


def test_profile_name_repeated_in_bio_is_not_a_separate_fact():
    ledger = build_ledger(
        raw(
            display_name="Vũ Trọng Đức",
            bio="Vũ Trọng Đức · 1.189 người theo dõi · Yêu mèo",
            collection_method="public_browser",
        )
    )
    assert [fact.statement for fact in ledger.facts if fact.category == "bio"] == ["Yêu mèo"]
    assert "Vũ Trọng Đức" not in [fact.statement for fact in ledger.usable_facts()]


@pytest.mark.parametrize(
    "boilerplate",
    [
        "Thanh Hưng is on Facebook",
        "Join Facebook to connect with Thanh Hưng and others you may know",
        "Facebook gives people the power to share and makes the world more open and connected.",
        "Tham gia Facebook để kết nối với Thanh Hưng",
    ],
)
def test_facebook_boilerplate_is_not_grounding_data(boilerplate):
    ledger = build_ledger(
        raw(
            display_name="Thanh Hưng",
            bio=boilerplate,
            collection_method="public_browser",
        )
    )
    assert [fact.category for fact in ledger.facts] == ["name"]
    assert "bio" in ledger.unknown_fields
    assert not ledger.usable_facts()


def test_live_meta_bio_is_split_into_independent_verbatim_facts():
    ledger = build_ledger(raw(
        display_name="Trinh Trinh",
        bio="16.191 người theo dõi · 19.004 người đang nói về điều này. Người sáng tạo nội dung số",
        collection_method="live_meta",
    ))
    bio_facts = [fact for fact in ledger.facts if fact.category in {"bio", "metric"}]
    assert [fact.statement for fact in bio_facts] == [
        "16.191 người theo dõi",
        "19.004 người đang nói về điều này",
        "Người sáng tạo nội dung số",
    ]
    assert [fact.category for fact in bio_facts] == ["metric", "metric", "bio"]
    assert [fact.source for fact in bio_facts] == [
        "live_meta:bio[0]",
        "live_meta:bio[1]",
        "live_meta:bio[2]",
    ]
    assert len(ledger.usable_facts()) == 1
    assert not evaluate_sufficiency(AccessState.PUBLIC, ledger, SETTINGS).ok


def test_facebook_boilerplate_posts_are_not_grounding_data():
    ledger = build_ledger(
        raw(
            display_name="Thanh Hưng",
            public_posts=[
                {"text": "Join Facebook to connect with Thanh Hưng and others you may know"}
            ],
            collection_method="public_browser",
        )
    )
    assert [fact.category for fact in ledger.facts] == ["name"]
    assert "public_posts" in ledger.unknown_fields


def test_contact_details_are_excluded_from_ledger_and_marked_unknown():
    ledger = build_ledger(
        raw(
            display_name="Lan Chi",
            bio="Người sáng tạo nội dung · Liên hệ 0912 345 678 hoặc lan@example.com",
            public_posts=[{"text": "Xem thêm tại https://example.com/profile"}],
        )
    )
    serialized_facts = " ".join(f.statement for f in ledger.facts)
    assert "0912" not in serialized_facts
    assert "lan@example.com" not in serialized_facts
    assert "https://" not in serialized_facts
    assert "contact_details_redacted" in ledger.unknown_fields


def test_provided_bio_is_not_split():
    bio = "Yêu mèo. Thích đọc sách."
    ledger = build_ledger(raw(display_name="A", bio=bio))
    assert [fact.statement for fact in ledger.facts if fact.category == "bio"] == [bio]


# --- Sufficiency gate ---------------------------------------------------------------------------


def test_rich_public_profile_passes_gate():
    gate = evaluate_sufficiency(AccessState.PUBLIC, build_ledger(RICH), SETTINGS)
    assert gate.ok and gate.reason_code is None


def test_name_only_profile_is_insufficient():
    gate = evaluate_sufficiency(AccessState.PARTIAL, build_ledger(raw(display_name="A")), SETTINGS)
    assert not gate.ok
    assert gate.reason_code == "INSUFFICIENT_DATA"
    assert gate.note.startswith("INSUFFICIENT_DATA:")
    assert "Chỉ thu thập được 0 thông tin" in gate.note


def test_one_fact_is_below_default_threshold_two_passes():
    one = build_ledger(raw(display_name="A", bio="Yêu mèo"))
    two = build_ledger(raw(display_name="A", bio="Yêu mèo", public_info={"current_city": "Huế"}))
    assert evaluate_sufficiency(AccessState.PUBLIC, one, SETTINGS).reason_code == "INSUFFICIENT_DATA"
    assert evaluate_sufficiency(AccessState.PUBLIC, two, SETTINGS).ok


def test_threshold_comes_from_settings():
    strict = load_settings(env={"MIN_GROUNDING_FACTS": "20"}, dotenv_path=None)
    assert not evaluate_sufficiency(AccessState.PUBLIC, build_ledger(RICH), strict).ok


def test_facts_without_name_are_insufficient():
    ledger = build_ledger(raw(bio="Yêu mèo", public_info={"current_city": "Huế"}))
    gate = evaluate_sufficiency(AccessState.PUBLIC, ledger, SETTINGS)
    assert gate.reason_code == "INSUFFICIENT_DATA"
    assert "tên hiển thị" in gate.note


@pytest.mark.parametrize(
    "state,code,prefix",
    [
        (AccessState.PRIVATE, "PRIVATE_PROFILE", "PRIVATE_PROFILE:"),
        (AccessState.NOT_FOUND, "NOT_FOUND", "NOT_FOUND:"),
        (AccessState.LOGIN_REQUIRED, "LOGIN_REQUIRED", "TECHNICAL LIMITATION:"),
        (AccessState.NO_ACCESSIBLE_DATA, "NO_ACCESSIBLE_DATA", "TECHNICAL LIMITATION:"),
        (AccessState.UNREACHABLE, "UNREACHABLE", "UNREACHABLE:"),
        (AccessState.INVALID_INPUT, "INVALID_INPUT", "INVALID_INPUT:"),
    ],
)
def test_blocked_states_fail_with_matching_code(state, code, prefix):
    # Even a rich ledger must not pass when access is not readable.
    gate = evaluate_sufficiency(state, build_ledger(RICH), SETTINGS)
    assert not gate.ok
    assert gate.reason_code == code
    assert gate.note.startswith(prefix)


def test_every_access_state_is_handled():
    for state in AccessState:
        evaluate_sufficiency(state, FactLedger(), SETTINGS)  # must not raise


def test_append_fact_uses_next_free_id_and_keeps_existing_ids():
    from app.ledger import append_fact, without_facts

    ledger = build_ledger(RICH)
    trimmed = without_facts(ledger, {"F3"})
    assert "F3" not in trimmed.ids() and len(trimmed.facts) == len(ledger.facts) - 1
    extended, fact = append_fact(trimmed, "visual_observation", "appears to show a cup", "vision:avatar",
                                 EpistemicStatus.INFERENCE, 0.7)
    assert fact.id == f"F{len(ledger.facts) + 1}"
    assert [f.id for f in extended.facts[:-1]] == [f.id for f in trimmed.facts]
    assert extended.unknown_fields == ledger.unknown_fields
