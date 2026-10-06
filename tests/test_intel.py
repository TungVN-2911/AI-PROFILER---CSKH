import re

import pytest

from app.config import PROJECT_ROOT
from app.intel import UNKNOWN, build_intelligence
from app.ledger import append_fact, build_ledger
from app.models import EpistemicStatus, RawProfile
from app.sources.provided import load_raw_profile

RICH = load_raw_profile(PROJECT_ROOT / "fixtures" / "profiles" / "minh_anh.json")


def raw(**kwargs):
    return RawProfile.model_validate({"facebook_url": "https://www.facebook.com/x.y.z", "display_name": "Lan Chi", **kwargs})


def intel_for(profile, year=2026):
    return build_intelligence(build_ledger(profile), reference_year=year)


def test_rich_fixture_without_explicit_data_has_unknown_gender_and_age():
    intel = intel_for(RICH)
    assert intel.customer_name == "Nguyễn Minh Anh"
    assert intel.gender == UNKNOWN == "UNKNOWN"
    assert intel.estimated_age_range == UNKNOWN
    assert intel.gender_fact_ids == [] and intel.age_fact_ids == []


def test_name_alone_never_implies_gender():
    # "Anh"/"Chi" style names are deliberately not interpreted.
    assert intel_for(raw()).gender == UNKNOWN


def test_appearance_observations_never_feed_demographics():
    ledger = build_ledger(raw())
    ledger, _ = append_fact(ledger, "visual_observation", "appears to show a person in a dress", "vision:avatar",
                            EpistemicStatus.INFERENCE, 0.9)
    intel = build_intelligence(ledger, reference_year=2026)
    assert intel.gender == UNKNOWN and intel.estimated_age_range == UNKNOWN


def test_pronouns_and_birth_year_are_derived_and_labelled():
    profile = raw(public_info={"pronouns": "she/her", "birth_year": 1995})
    ledger = build_ledger(profile)
    intel = build_intelligence(ledger, reference_year=2026)
    pronoun_id = next(f.id for f in ledger.facts if f.category == "pronouns")
    year_id = next(f.id for f in ledger.facts if f.category == "birth_year")
    assert intel.gender == f"Đại từ tự khai báo: she/her [{pronoun_id}] (không nêu giới tính)"
    assert intel.estimated_age_range == f"30–31 tuổi (tính từ năm sinh tự khai báo 1995 [{year_id}], tại năm 2026)"
    assert intel.gender_fact_ids == [pronoun_id] and intel.age_fact_ids == [year_id]


@pytest.mark.parametrize("value,label", [("Nữ", "Nữ"), ("male", "Nam"), ("Non-binary", "Non-binary")])
def test_declared_gender_field_takes_precedence(value, label):
    intel = intel_for(raw(public_info={"gender": value, "pronouns": "they/them"}))
    assert intel.gender.startswith(f"{label} (tự khai báo trên trang cá nhân [F")


@pytest.mark.parametrize("birth_year", [2020, 1900])
def test_implausible_birth_year_is_unknown(birth_year):
    assert intel_for(raw(public_info={"birth_year": birth_year})).estimated_age_range == UNKNOWN


def test_lifestyle_is_labelled_inference_citing_existing_facts():
    ledger = build_ledger(RICH)
    intel = build_intelligence(ledger, reference_year=2026)
    assert intel.apparent_lifestyle.startswith("INFERENCE: ")
    cited = re.findall(r"F\d+", intel.apparent_lifestyle.split("(dựa trên")[1])
    assert cited == intel.lifestyle_fact_ids and cited
    assert set(cited) <= ledger.ids()
    for fid in cited:
        assert ledger.get(fid).statement in intel.apparent_lifestyle
        assert ledger.get(fid).category in {"interest", "work"}


def test_lifestyle_falls_back_to_bio_then_unknown():
    with_bio = intel_for(raw(bio="Yêu mèo và trà chiều"))
    assert with_bio.apparent_lifestyle.startswith("INFERENCE: ") and "Yêu mèo và trà chiều" in with_bio.apparent_lifestyle
    nothing = intel_for(raw(public_info={"current_city": "Huế"}))
    assert nothing.apparent_lifestyle == UNKNOWN and nothing.lifestyle_fact_ids == []


def test_missing_name_is_none():
    profile = RawProfile.model_validate({"facebook_url": "https://www.facebook.com/x.y.z", "bio": "b"})
    assert intel_for(profile).customer_name is None


# --- Perceived estimates ------------------------------------------------------------------------


def with_estimates(profile, gender=("female", 0.85), age=("25-35", 0.7)):
    ledger = build_ledger(profile)
    if gender:
        ledger, _ = append_fact(ledger, "perceived_gender", gender[0], "vision:avatar:estimate", EpistemicStatus.INFERENCE, gender[1])
    if age:
        ledger, _ = append_fact(ledger, "perceived_age", age[0], "vision:avatar:estimate", EpistemicStatus.INFERENCE, age[1])
    return ledger


def test_perceived_estimates_are_labelled_inference():
    ledger = with_estimates(raw())
    intel = build_intelligence(ledger, reference_year=2026)
    gid = next(f.id for f in ledger.facts if f.category == "perceived_gender")
    aid = next(f.id for f in ledger.facts if f.category == "perceived_age")
    assert intel.gender == f"INFERENCE: Nữ (ước lượng từ ảnh đại diện, độ tin cậy 0.85) [{gid}]"
    assert intel.estimated_age_range == f"INFERENCE: 25–35 tuổi (ước lượng từ ảnh đại diện, độ tin cậy 0.70) [{aid}]"
    assert intel.gender_fact_ids == [gid] and intel.age_fact_ids == [aid]


def test_male_estimate_label():
    assert build_intelligence(with_estimates(raw(), gender=("male", 0.9), age=None), 2026).gender.startswith("INFERENCE: Nam (ước lượng từ ảnh đại diện")


def test_self_declared_data_beats_perceived_estimates():
    profile = raw(public_info={"gender": "Nam", "birth_year": 1990})
    intel = build_intelligence(with_estimates(profile), reference_year=2026)
    assert intel.gender.startswith("Nam (tự khai báo trên trang cá nhân")
    assert intel.estimated_age_range.startswith("35–36 tuổi (tính từ năm sinh tự khai báo 1990")


def test_pronouns_beat_perceived_gender():
    intel = build_intelligence(with_estimates(raw(public_info={"pronouns": "they/them"})), reference_year=2026)
    assert intel.gender.startswith("Đại từ tự khai báo: they/them")


def test_implausible_birth_year_falls_back_to_perceived_age():
    intel = build_intelligence(with_estimates(raw(public_info={"birth_year": 2020})), reference_year=2026)
    assert intel.estimated_age_range.startswith("INFERENCE: 25–35")


# --- Forms of address ---------------------------------------------------------------------------

from app.intel import NEUTRAL_ADDRESSING, derive_addressing  # noqa: E402


@pytest.mark.parametrize(
    "public_info,expected",
    [
        ({"gender": "Nữ"}, ("chị", "em")),
        ({"gender": "Nam"}, ("anh", "em")),
        ({"gender": "Non-binary"}, ("bạn", "mình")),
        ({"pronouns": "she/her"}, ("chị", "em")),
        ({"pronouns": "he/him"}, ("anh", "em")),
        ({"pronouns": "they/them"}, ("bạn", "mình")),
        ({}, ("bạn", "mình")),
    ],
)
def test_addressing_from_self_declared_data(public_info, expected):
    a = derive_addressing(build_ledger(raw(public_info=public_info)))
    assert (a.customer, a.agent) == expected


def test_addressing_from_perceived_estimate_and_precedence():
    perceived = derive_addressing(with_estimates(raw(), gender=("male", 0.9), age=None))
    assert (perceived.customer, perceived.agent) == ("anh", "em") and "ước lượng từ ảnh đại diện" in perceived.basis
    declared_wins = derive_addressing(with_estimates(raw(public_info={"gender": "Nữ"}), gender=("male", 0.9), age=None))
    assert declared_wins.customer == "chị"
    pronouns_win = derive_addressing(with_estimates(raw(public_info={"pronouns": "they/them"}), gender=("female", 0.9), age=None))
    assert pronouns_win == NEUTRAL_ADDRESSING


def test_intelligence_carries_addressing_label():
    intel = build_intelligence(build_ledger(raw(public_info={"gender": "Nữ"})), 2026)
    assert intel.addressing.label().startswith("chị/em (giới tính tự khai báo [F")
