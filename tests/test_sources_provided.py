import json

import pytest

from app.config import PROJECT_ROOT
from app.input import validate_profile_url
from app.models import AccessState
from app.sources.base import NO_DATA_LIMITATION, SYNTHETIC_NOTE, acquire_from_chain
from app.sources.provided import FixtureStoreSource, ProvidedFileSource

STORE = PROJECT_ROOT / "fixtures" / "profiles"
RICH_URL = validate_profile_url("https://www.facebook.com/fixture.minh.anh")
PRIVATE_URL = validate_profile_url("https://m.facebook.com/fixture.private.user/")
UNKNOWN_URL = validate_profile_url("https://www.facebook.com/nobody.here.12345")


def test_matching_fixture_loads_as_public_raw_profile():
    result = FixtureStoreSource(STORE).acquire(RICH_URL)
    assert result is not None
    assert result.access_state is AccessState.PUBLIC
    assert result.source_name == "profile_store"
    assert result.canonical_url == RICH_URL.url
    assert result.synthetic is True
    assert SYNTHETIC_NOTE in result.limitations
    assert result.raw.display_name == "Nguyễn Minh Anh"
    assert len(result.raw.public_posts) == 3


def test_store_matches_non_canonical_input_url():
    url = validate_profile_url("https://m.facebook.com/Fixture.Minh.Anh/?ref=share")
    assert FixtureStoreSource(STORE).acquire(url).access_state is AccessState.PUBLIC


def test_private_fixture_returns_private_without_profile_fields():
    result = FixtureStoreSource(STORE).acquire(PRIVATE_URL)
    assert result.access_state is AccessState.PRIVATE
    assert result.raw is None  # display name in the file must not be used
    assert result.synthetic is True
    assert any("restricted to friends" in note for note in result.limitations)


def test_unknown_url_returns_none_and_chain_reports_no_accessible_data():
    store = FixtureStoreSource(STORE)
    assert store.acquire(UNKNOWN_URL) is None
    result = acquire_from_chain([store], UNKNOWN_URL)
    assert result.access_state is AccessState.NO_ACCESSIBLE_DATA
    assert result.raw is None
    assert result.limitations == [NO_DATA_LIMITATION]
    assert result.limitations[0].startswith("TECHNICAL LIMITATION:")


def test_chain_first_source_wins(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"facebook_url": RICH_URL.url, "display_name": "From file"}), encoding="utf-8")
    result = acquire_from_chain([ProvidedFileSource(path), FixtureStoreSource(STORE)], RICH_URL)
    assert result.source_name == "profile_file"
    assert result.raw.display_name == "From file"
    assert result.synthetic is False


@pytest.mark.parametrize(
    "content,fragment",
    [
        ("{not json", "not valid JSON"),
        (json.dumps({"display_name": "no url"}), "does not match the profile format"),
        (json.dumps({"facebook_url": RICH_URL.url, "unexpected": 1}), "does not match the profile format"),
        (json.dumps({"facebook_url": "https://example.com/x"}), "invalid facebook_url"),
    ],
)
def test_malformed_profile_file_raises_handled_error(tmp_path, content, fragment):
    from app.sources.base import SourceError

    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SourceError) as exc:
        ProvidedFileSource(path).acquire(RICH_URL)
    assert fragment in str(exc.value)


def test_missing_profile_file_raises_handled_error(tmp_path):
    from app.sources.base import SourceError

    with pytest.raises(SourceError, match="cannot read profile file"):
        ProvidedFileSource(tmp_path / "missing.json").acquire(RICH_URL)


def test_profile_file_for_another_url_is_rejected(tmp_path):
    from app.sources.base import SourceError

    path = tmp_path / "other.json"
    path.write_text(json.dumps({"facebook_url": "https://www.facebook.com/someone.else"}), encoding="utf-8")
    with pytest.raises(SourceError, match="does not match --url"):
        ProvidedFileSource(path).acquire(RICH_URL)


def test_store_skips_malformed_and_duplicate_files(tmp_path):
    (tmp_path / "a_good.json").write_text(json.dumps({"facebook_url": RICH_URL.url, "display_name": "A"}), encoding="utf-8")
    (tmp_path / "b_dup.json").write_text(json.dumps({"facebook_url": RICH_URL.url, "display_name": "B"}), encoding="utf-8")
    (tmp_path / "c_broken.json").write_text("{", encoding="utf-8")
    store = FixtureStoreSource(tmp_path)
    result = store.acquire(RICH_URL)
    assert result.raw.display_name == "A"
    assert len(store.load_errors) == 2
    assert any("duplicate" in e for e in store.load_errors)
    assert any("not valid JSON" in e for e in store.load_errors)


def test_missing_store_directory_is_handled(tmp_path):
    store = FixtureStoreSource(tmp_path / "nope")
    assert store.acquire(RICH_URL) is None
    assert store.load_errors and "does not exist" in store.load_errors[0]


def test_repository_fixtures_all_load_and_are_synthetic():
    store = FixtureStoreSource(STORE)
    assert store.acquire(RICH_URL) is not None
    assert store.load_errors == []
    for path in STORE.glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["synthetic"] is True
