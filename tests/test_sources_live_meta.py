import httpx
import pytest

from app.input import validate_profile_url
from app.models import AccessState
from app.sources.live_meta import USER_AGENT, LivePublicMetaSource, parse_meta

URL = validate_profile_url("https://www.facebook.com/fixture.live.user")

PUBLIC_HTML = """<html><head>
<meta property="og:title" content="Lê Thu Hà | Facebook" />
<meta property="og:description" content="Giáo viên tiếng Anh &amp; mê đọc sách. Sống tại Đà Nẵng." />
<meta property="og:image" content="https://scontent.example/avatar.jpg" />
</head><body><form id="login_form" action="/login/"></form></body></html>"""

NAME_ONLY_HTML = """<html><head>
<meta property="og:title" content="Lê Thu Hà" />
<meta property="og:description" content="Lê Thu Hà is on Facebook. Join Facebook to connect with Lê Thu Hà and others you may know." />
</head></html>"""

LOGIN_HTML = """<html><head><title>Log into Facebook</title>
<meta property="og:title" content="Log into Facebook" /></head>
<body><form id="login_form" action="https://www.facebook.com/login/device-based/regular/login/"></form></body></html>"""

NOT_FOUND_HTML = "<html><body><h2>This content isn't available right now</h2></body></html>"


class Recorder:
    """MockTransport handler that records every request."""

    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.exc:
            raise self.exc
        return self.response


def source_for(handler):
    return LivePublicMetaSource(enabled=True, timeout_seconds=1, transport=httpx.MockTransport(handler))


def html(body, status=200, headers=None):
    return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8", **(headers or {})}, text=body)


def test_public_page_yields_public_raw_profile():
    rec = Recorder(html(PUBLIC_HTML))
    result = source_for(rec).acquire(URL)
    assert result.access_state is AccessState.PUBLIC
    assert result.source_name == "live_meta"
    raw = result.raw
    assert raw.display_name == "Lê Thu Hà"
    assert raw.bio == "Giáo viên tiếng Anh & mê đọc sách. Sống tại Đà Nẵng."
    assert raw.images[0].url == "https://scontent.example/avatar.jpg"
    assert raw.collection_method == "live_meta"
    assert raw.synthetic is False
    assert result.synthetic is False
    assert any("only public HTML meta tags" in n for n in result.limitations)


def test_boilerplate_description_is_dropped_and_state_is_partial():
    result = source_for(Recorder(html(NAME_ONLY_HTML))).acquire(URL)
    assert result.access_state is AccessState.PARTIAL
    assert result.raw.display_name == "Lê Thu Hà"
    assert result.raw.bio is None
    assert result.raw.images == []


def test_login_redirect_is_login_required_and_not_followed():
    rec = Recorder(httpx.Response(302, headers={"location": "https://www.facebook.com/login/?next=x"}))
    result = source_for(rec).acquire(URL)
    assert result.access_state is AccessState.LOGIN_REQUIRED
    assert result.raw is None
    assert result.limitations[0].startswith("TECHNICAL LIMITATION:")
    assert len(rec.requests) == 1


def test_checkpoint_redirect_is_login_required():
    rec = Recorder(httpx.Response(302, headers={"location": "https://www.facebook.com/checkpoint/block/"}))
    assert source_for(rec).acquire(URL).access_state is AccessState.LOGIN_REQUIRED


def test_login_html_is_login_required():
    result = source_for(Recorder(html(LOGIN_HTML))).acquire(URL)
    assert result.access_state is AccessState.LOGIN_REQUIRED
    assert result.limitations[0].startswith("TECHNICAL LIMITATION:")


def test_other_redirect_is_unreachable_and_not_followed():
    rec = Recorder(httpx.Response(301, headers={"location": "https://www.facebook.com/someone.else"}))
    result = source_for(rec).acquire(URL)
    assert result.access_state is AccessState.UNREACHABLE
    assert len(rec.requests) == 1


@pytest.mark.parametrize("status", [404, 410])
def test_dead_link_status_is_not_found(status):
    result = source_for(Recorder(html("gone", status=status))).acquire(URL)
    assert result.access_state is AccessState.NOT_FOUND
    assert result.limitations[0].startswith("NOT_FOUND:")


def test_content_unavailable_page_is_not_found():
    assert source_for(Recorder(html(NOT_FOUND_HTML))).acquire(URL).access_state is AccessState.NOT_FOUND


def test_timeout_is_unreachable():
    rec = Recorder(exc=httpx.ReadTimeout("timed out"))
    result = source_for(rec).acquire(URL)
    assert result.access_state is AccessState.UNREACHABLE
    assert "timed out" in result.limitations[0]
    assert len(rec.requests) == 1  # no retry


def test_connection_error_is_unreachable():
    result = source_for(Recorder(exc=httpx.ConnectError("refused"))).acquire(URL)
    assert result.access_state is AccessState.UNREACHABLE


@pytest.mark.parametrize("status", [429, 500, 403])
def test_other_status_is_unreachable_without_retry(status):
    rec = Recorder(html("x", status=status))
    result = source_for(rec).acquire(URL)
    assert result.access_state is AccessState.UNREACHABLE
    assert str(status) in result.limitations[0]
    assert len(rec.requests) == 1


def test_page_without_meta_is_no_accessible_data():
    result = source_for(Recorder(html("<html><head></head><body>hi</body></html>"))).acquire(URL)
    assert result.access_state is AccessState.NO_ACCESSIBLE_DATA
    assert result.raw is None


def test_request_is_honest_unauthenticated_single_get():
    rec = Recorder(html(PUBLIC_HTML))
    source_for(rec).acquire(URL)
    assert len(rec.requests) == 1
    req = rec.requests[0]
    assert req.method == "GET"
    assert str(req.url) == URL.url
    assert req.headers["user-agent"] == USER_AGENT
    assert "cookie" not in req.headers
    assert "authorization" not in req.headers


def test_disabled_by_default_makes_no_request():
    rec = Recorder(html(PUBLIC_HTML))
    source = LivePublicMetaSource(enabled=False, transport=httpx.MockTransport(rec))
    assert source.acquire(URL) is None
    assert rec.requests == []


def test_parse_meta_takes_first_value_and_ignores_empty():
    meta = parse_meta('<meta property="og:title" content=""><meta property="og:title" content="A"><meta property="og:title" content="B">')
    assert meta == {"og:title": "A"}
