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
    assert intel.gender == f"Self-declared pronouns: she/her [{pronoun_id}] (gender not stated)"
    assert intel.estimated_age_range == f"30–31 (derived from stated birth year 1995 [{year_id}], as of 2026)"
    assert intel.gender_fact_ids == [pronoun_id] and intel.age_fact_ids == [year_id]


@pytest.mark.parametrize("value,label", [("Nữ", "Female"), ("male", "Male"), ("Non-binary", "Non-binary")])
def test_declared_gender_field_takes_precedence(value, label):
    intel = intel_for(raw(public_info={"gender": value, "pronouns": "they/them"}))
    assert intel.gender.startswith(f"{label} (self-declared gender field [F")


@pytest.mark.parametrize("birth_year", [2020, 1900])
def test_implausible_birth_year_is_unknown(birth_year):
    assert intel_for(raw(public_info={"birth_year": birth_year})).estimated_age_range == UNKNOWN


def test_lifestyle_is_labelled_inference_citing_existing_facts():
    ledger = build_ledger(RICH)
    intel = build_intelligence(ledger, reference_year=2026)
    assert intel.apparent_lifestyle.startswith("INFERENCE: ")
    cited = re.findall(r"F\d+", intel.apparent_lifestyle.split("(based on")[1])
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
