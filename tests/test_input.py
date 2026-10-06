import pytest

from app.input import InputError, validate_profile_url

USER = "https://www.facebook.com/fixture.minh.anh"
PID = "https://www.facebook.com/profile.php?id=100012345678901"


@pytest.mark.parametrize(
    "raw,expected,kind",
    [
        ("https://www.facebook.com/fixture.minh.anh", USER, "username"),
        ("https://facebook.com/fixture.minh.anh", USER, "username"),
        ("https://m.facebook.com/fixture.minh.anh", USER, "username"),
        ("https://mbasic.facebook.com/fixture.minh.anh", USER, "username"),
        ("http://web.facebook.com/fixture.minh.anh", USER, "username"),
        ("https://www.facebook.com/fixture.minh.anh/", USER, "username"),
        ("  https://www.facebook.com/Fixture.Minh.Anh  ", USER, "username"),
        ("https://www.facebook.com/fixture.minh.anh?mibextid=ZbWKwL&ref=share#posts", USER, "username"),
        ("https://www.facebook.com/fixture.minh.anh/about", USER, "username"),
        ("facebook.com/fixture.minh.anh", USER, "username"),
        ("https://WWW.FACEBOOK.COM/fixture.minh.anh", USER, "username"),
        ("https://www.facebook.com/example_user", "https://www.facebook.com/example_user", "username"),
        ("https://www.facebook.com/profile.php?id=100012345678901", PID, "profile_id"),
        ("https://m.facebook.com/profile.php?id=100012345678901&ref=bookmarks", PID, "profile_id"),
        ("https://www.facebook.com/people/Minh-Anh/100012345678901/", PID, "profile_id"),
    ],
)
def test_valid_urls_canonicalize(raw, expected, kind):
    result = validate_profile_url(raw)
    assert result.url == expected
    assert result.kind == kind
    assert result.original == raw


@pytest.mark.parametrize(
    "raw,reason_fragment",
    [
        (None, "required"),
        ("", "required"),
        ("   ", "required"),
        ("not a url", "not a URL"),
        ("ftp://www.facebook.com/fixture.minh.anh", "scheme"),
        ("https://www.facebook.com.evil.io/fixture.minh.anh", "not facebook.com"),
        ("https://evilfacebook.com/fixture.minh.anh", "not facebook.com"),
        ("https://facebook.com@evil.io/fixture.minh.anh", "credentials"),
        ("https://www.facebook.com:8080/fixture.minh.anh", "port"),
        ("https://www.instagram.com/fixture.minh.anh", "not facebook.com"),
        ("https://www.facebook.com/", "no username"),
        ("https://www.facebook.com/groups/123456", "not a personal profile"),
        ("https://www.facebook.com/events/987", "not a personal profile"),
        ("https://www.facebook.com/watch?v=1", "not a personal profile"),
        ("https://www.facebook.com/marketplace/item/1", "not a personal profile"),
        ("https://www.facebook.com/login.php", "not a personal profile"),
        ("https://www.facebook.com/share/abc123/", "not a personal profile"),
        ("https://www.facebook.com/profile.php", "numeric ?id="),
        ("https://www.facebook.com/profile.php?id=abc", "numeric ?id="),
        ("https://www.facebook.com/fixture.minh.anh/posts/123456", "not a profile URL"),
        ("https://www.facebook.com/bad%20name", "not a valid Facebook username"),
        ("https://www.facebook.com/people/Minh-Anh/", "numeric profile id"),
    ],
)
def test_invalid_inputs_rejected_with_reason(raw, reason_fragment):
    with pytest.raises(InputError) as exc:
        validate_profile_url(raw)
    assert reason_fragment in exc.value.reason
    assert exc.value.error_note.startswith("INVALID_INPUT: ")
    assert exc.value.raw == (raw or "")
