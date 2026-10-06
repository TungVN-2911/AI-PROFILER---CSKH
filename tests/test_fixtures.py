"""Every repository fixture loads and maps to the status documented in fixtures/README.md."""

import json

import pytest

from app.config import PROJECT_ROOT, load_settings
from app.input import validate_profile_url
from app.pipeline import PipelineOptions, run_pipeline
from app.schema import PartialOutput, SuccessOutput
from app.sources.provided import FixtureStoreSource

STORE = PROJECT_ROOT / "fixtures" / "profiles"
SETTINGS = load_settings(env={}, dotenv_path=None)

# url, access state, output status, error_note prefix (PARTIAL only)
EXPECTED = [
    ("https://www.facebook.com/fixture.minh.anh", "PUBLIC", "SUCCESS", None),
    ("https://www.facebook.com/fixture.quoc.bao", "PUBLIC", "SUCCESS", None),
    ("https://www.facebook.com/fixture.khanh.linh", "PUBLIC", "SUCCESS", None),
    ("https://www.facebook.com/profile.php?id=100000000000042", "PUBLIC", "SUCCESS", None),
    ("https://www.facebook.com/fixture.thu.ha", "PARTIAL", "SUCCESS", None),
    ("https://www.facebook.com/fixture.name.only", "PUBLIC", "PARTIAL_OR_PRIVATE", "INSUFFICIENT_DATA:"),
    ("https://www.facebook.com/fixture.private.user", "PRIVATE", "PARTIAL_OR_PRIVATE", "PRIVATE_PROFILE:"),
    ("https://www.facebook.com/fixture.dead.link", "NOT_FOUND", "PARTIAL_OR_PRIVATE", "NOT_FOUND:"),
]


def test_at_least_seven_fixtures_all_synthetic_and_indexed():
    files = sorted(STORE.glob("*.json"))
    assert len(files) >= 7
    readme = (PROJECT_ROOT / "fixtures" / "README.md").read_text(encoding="utf-8")
    for path in files:
        assert json.loads(path.read_text(encoding="utf-8"))["synthetic"] is True
        assert path.name in readme
    store = FixtureStoreSource(STORE)
    store.acquire(validate_profile_url(EXPECTED[0][0]))
    assert store.load_errors == []
    assert len(EXPECTED) == len(files)


@pytest.mark.parametrize("url,state,status,prefix", EXPECTED)
def test_fixture_maps_to_intended_status(url, state, status, prefix):
    result = run_pipeline(url, PipelineOptions(mode="deterministic"), SETTINGS)
    assert result.evidence.access_state.value == state
    assert result.output.status == status
    assert result.exit_code == 0
    if prefix:
        assert isinstance(result.output, PartialOutput) and result.output.error_note.startswith(prefix)
    else:
        assert isinstance(result.output, SuccessOutput)
        assert result.output.ethical_rapport.sales_mention_check == "ZERO_SALES_CONFIRMED"


def test_no_image_fixture_visual_not_available():
    out = run_pipeline("https://www.facebook.com/fixture.quoc.bao", PipelineOptions(mode="deterministic"), SETTINGS).output
    assert out.profile_data.visual_context == "NOT_AVAILABLE: no public image provided"
    assert len(out.ethical_rapport.dialogue_sequence_10) == 10


def test_declared_fixture_demographics_are_derived_and_labelled():
    out = run_pipeline("https://www.facebook.com/fixture.khanh.linh", PipelineOptions(mode="deterministic"), SETTINGS).output
    demo = out.profile_data.estimated_demographics
    assert demo.gender.startswith("Female (self-declared gender field [F")
    assert "derived from stated birth year 1996" in demo.estimated_age_range
    texts = " ".join(out.ethical_rapport.dialogue_sequence_10)
    assert "1996" not in texts and "she/her" not in texts


def test_partial_fixture_gets_shorter_sequence():
    out = run_pipeline("https://www.facebook.com/fixture.thu.ha", PipelineOptions(mode="deterministic"), SETTINGS).output
    assert 5 <= len(out.ethical_rapport.dialogue_sequence_10) < 10
