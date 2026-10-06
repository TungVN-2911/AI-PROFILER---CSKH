import copy
import json

import pytest
from pydantic import ValidationError

from app.models import AccessState, EpistemicStatus, Fact, FactLedger, RawProfile
from app.schema import (
    EvidenceReport,
    PartialOutput,
    SuccessOutput,
    parse_output,
    to_json_dict,
)

# Key structure of the brief's SUCCESS example (TES-3808 §2).
BRIEF_SUCCESS_KEYS = {
    "status": None,
    "facebook_url": None,
    "profile_data": {
        "customer_name": None,
        "visual_context": None,
        "estimated_demographics": {
            "gender": None,
            "estimated_age_range": None,
            "apparent_lifestyle": None,
        },
    },
    "ethical_rapport": {
        "core_empathy_angle": None,
        "dialogue_sequence_10": None,
        "sales_mention_check": None,
    },
    "evening_cadence_20pm": {"trigger_time": None, "evening_hook_message": None},
}


def key_tree(d):
    return {k: key_tree(v) if isinstance(v, dict) else None for k, v in d.items()}


def success_doc(n_messages=5):
    return {
        "status": "SUCCESS",
        "facebook_url": "https://www.facebook.com/example_user",
        "profile_data": {
            "customer_name": "Minh Anh",
            "visual_context": "NOT_AVAILABLE: không có ảnh công khai nào được cung cấp",
            "estimated_demographics": {
                "gender": "UNKNOWN",
                "estimated_age_range": "UNKNOWN",
                "apparent_lifestyle": "UNKNOWN",
            },
        },
        "ethical_rapport": {
            "core_empathy_angle": "Shared interest in morning coffee",
            "dialogue_sequence_10": [f"message {i}" for i in range(n_messages)],
            "sales_mention_check": "ZERO_SALES_CONFIRMED",
        },
        "evening_cadence_20pm": {"trigger_time": "20:00", "evening_hook_message": "hook"},
    }


# --- Strict output schema -------------------------------------------------------------------


def test_success_output_serializes_to_exact_brief_key_set():
    out = SuccessOutput.model_validate(success_doc())
    dumped = to_json_dict(out)
    assert key_tree(dumped) == BRIEF_SUCCESS_KEYS
    assert list(dumped) == list(BRIEF_SUCCESS_KEYS)  # same key order as the brief
    assert json.loads(json.dumps(dumped, ensure_ascii=False)) == dumped


@pytest.mark.parametrize("n", [5, 10])
def test_message_count_bounds_accepted(n):
    assert len(SuccessOutput.model_validate(success_doc(n)).ethical_rapport.dialogue_sequence_10) == n


@pytest.mark.parametrize("n", [0, 4, 11])
def test_message_count_out_of_bounds_rejected(n):
    with pytest.raises(ValidationError):
        SuccessOutput.model_validate(success_doc(n))


@pytest.mark.parametrize(
    "path,value",
    [
        (("status",), "OK"),
        (("evening_cadence_20pm", "trigger_time"), "21:00"),
        (("evening_cadence_20pm", "trigger_time"), "8pm"),
        (("ethical_rapport", "sales_mention_check"), "SALES_FOUND"),
        (("profile_data", "customer_name"), "   "),
        (("ethical_rapport", "dialogue_sequence_10"), ["ok"] * 4 + [""]),
    ],
)
def test_wrong_literals_and_empty_values_rejected(path, value):
    doc = success_doc()
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        SuccessOutput.model_validate(doc)


@pytest.mark.parametrize(
    "path",
    [(), ("profile_data",), ("profile_data", "estimated_demographics"), ("ethical_rapport",), ("evening_cadence_20pm",)],
)
def test_extra_keys_rejected_at_every_level(path):
    doc = copy.deepcopy(success_doc())
    target = doc
    for key in path:
        target = target[key]
    target["extra"] = "x"
    with pytest.raises(ValidationError):
        SuccessOutput.model_validate(doc)


def test_missing_key_rejected():
    doc = success_doc()
    del doc["profile_data"]["estimated_demographics"]["gender"]
    with pytest.raises(ValidationError):
        SuccessOutput.model_validate(doc)


def test_partial_output_has_exactly_three_keys():
    out = PartialOutput(status="PARTIAL_OR_PRIVATE", facebook_url="https://www.facebook.com/x", error_note="PRIVATE_PROFILE: ...")
    assert set(to_json_dict(out)) == {"status", "facebook_url", "error_note"}


def test_partial_output_rejects_extra_keys_and_empty_note():
    with pytest.raises(ValidationError):
        PartialOutput.model_validate({"status": "PARTIAL_OR_PRIVATE", "facebook_url": "", "error_note": "x", "profile_data": {}})
    with pytest.raises(ValidationError):
        PartialOutput.model_validate({"status": "PARTIAL_OR_PRIVATE", "facebook_url": "", "error_note": " "})


def test_partial_output_allows_empty_url_for_missing_input():
    out = PartialOutput(status="PARTIAL_OR_PRIVATE", facebook_url="", error_note="INVALID_INPUT: --url is required")
    assert out.facebook_url == ""


def test_parse_output_dispatches_on_status():
    assert isinstance(parse_output(success_doc()), SuccessOutput)
    partial = {"status": "PARTIAL_OR_PRIVATE", "facebook_url": "u", "error_note": "NOT_FOUND: dead link"}
    assert isinstance(parse_output(partial), PartialOutput)
    with pytest.raises(ValidationError):
        parse_output({"status": "ERROR", "facebook_url": "u", "error_note": "x"})
    with pytest.raises(ValidationError):
        # SUCCESS status with the partial shape must not validate.
        parse_output({"status": "SUCCESS", "facebook_url": "u", "error_note": "x"})


# --- Domain models --------------------------------------------------------------------------


def test_raw_profile_minimal_and_blank_values_become_none():
    raw = RawProfile.model_validate(
        {
            "facebook_url": "https://www.facebook.com/fixture.minh.anh",
            "display_name": "  ",
            "bio": "",
            "public_info": {"work": ["  ", "Designer"], "pronouns": " "},
            "public_posts": [{"date": "2026-09-28", "text": "Chạy bộ sáng nay"}],
        }
    )
    assert raw.display_name is None
    assert raw.bio is None
    assert raw.public_info.work == ["Designer"]
    assert raw.public_info.pronouns is None
    assert raw.access.state is AccessState.PUBLIC
    assert str(raw.public_posts[0].date) == "2026-09-28"


def test_raw_profile_rejects_unknown_fields_and_bad_state():
    with pytest.raises(ValidationError):
        RawProfile.model_validate({"facebook_url": "u", "biography": "typo field"})
    with pytest.raises(ValidationError):
        RawProfile.model_validate({"facebook_url": "u", "access": {"state": "SECRET"}})


def test_fact_rules():
    Fact(id="F1", category="bio", statement="Yêu cà phê", source="profile_file:bio")
    with pytest.raises(ValidationError):
        Fact(id="X1", category="bio", statement="s", source="src")
    with pytest.raises(ValidationError):
        Fact(id="F1", category="bio", statement="s", source="src", epistemic_status=EpistemicStatus.UNKNOWN)
    with pytest.raises(ValidationError):
        Fact(id="F1", category="bio", statement="s", source="src", confidence=1.5)


def test_fact_ledger_helpers_and_unique_ids():
    ledger = FactLedger(
        facts=[
            Fact(id="F1", category="name", statement="Minh Anh", source="profile_file:display_name"),
            Fact(id="F2", category="interest", statement="chạy bộ", source="profile_file:interests"),
            Fact(id="F3", category="other", statement="likely active", source="rule", epistemic_status=EpistemicStatus.INFERENCE),
        ],
        unknown_fields=["bio"],
    )
    assert ledger.name_fact().id == "F1"
    assert [f.id for f in ledger.usable_facts()] == ["F2"]
    assert ledger.get("F3").epistemic_status is EpistemicStatus.INFERENCE
    assert ledger.get("F9") is None
    assert ledger.ids() == {"F1", "F2", "F3"}
    with pytest.raises(ValidationError):
        FactLedger(facts=[ledger.facts[0], ledger.facts[0]])


def test_evidence_report_defaults_and_strictness():
    ev = EvidenceReport(facebook_url="u", output_status="PARTIAL_OR_PRIVATE")
    dumped = ev.model_dump(mode="json")
    assert dumped["generation_mode"] == "none"
    assert dumped["validation"] == {"passed": False, "attempts": 0, "violations": []}
    with pytest.raises(ValidationError):
        EvidenceReport(facebook_url="u", output_status="SUCCESS", unexpected=True)
