"""Opt-in, best-effort live source: ONE unauthenticated GET, public HTML meta tags only.

Compliance rules: no login, no cookies or credentials, honest User-Agent, redirects are
not followed, no retries, no CAPTCHA solving. A login wall / checkpoint is reported, never worked around.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

from app.input import CanonicalUrl
from app.models import AccessState, AcquisitionResult, ProfileImage, ProfileType, RawProfile

log = logging.getLogger(__name__)

USER_AGENT = "FacebookProfilerAgent/0.1 (+TES-3808 test)"
MAX_BODY_BYTES = 2_000_000

SCOPE_NOTE = (
    "Chế độ --live chỉ đọc các thẻ meta HTML công khai (og:title, og:description, og:image) từ một request "
    "không đăng nhập; bài đăng, mục Giới thiệu và phần lớn nội dung trang cá nhân không truy cập được nếu không đăng nhập."
)
LOGIN_LIMITATION = (
    "TECHNICAL LIMITATION: Facebook trả về trang đăng nhập/xác minh (checkpoint) cho trang cá nhân này. Agent không "
    "đăng nhập hay vượt qua cơ chế kiểm soát truy cập. Hãy cung cấp dữ liệu qua --profile-file."
)

LOGIN_PATH_MARKERS = ("/login", "checkpoint", "captcha", "/recover")
LOGIN_BODY_MARKERS = re.compile(
    r'id="login_form"|name="login"|action="[^"]*/login|/checkpoint/|captcha|'
    r"log in to facebook|log into facebook|đăng nhập facebook|you must log in",
    re.IGNORECASE,
)
NOT_FOUND_BODY_MARKERS = re.compile(
    r"this content isn.t available|content isn.t available right now|this page isn.t available|"
    r"nội dung này hiện không|trang này không hiển thị",
    re.IGNORECASE,
)
GENERIC_TITLES = re.compile(
    r"^(facebook|error|log in|log into facebook|log in to facebook|đăng nhập facebook|"
    r"facebook\s*[–-]\s*log in or sign up|facebook\s*[–-]\s*đăng nhập hoặc đăng ký)$",
    re.IGNORECASE,
)
# Facebook's logged-out boilerplate description carries no profile information.
BOILERPLATE_DESCRIPTION = re.compile(
    r"is on facebook\. join facebook to connect|tham gia facebook để kết nối|đang ở trên facebook",
    re.IGNORECASE,
)
PUBLIC_PAGE_MARKERS = re.compile(
    r"\b(?:official page|official account|page chính thức|trang chính thức)\b"
    r"|(?:this is|đây là)\s+(?:the\s+)?(?:official\s+)?page\b",
    re.IGNORECASE,
)
TITLE_SUFFIX = re.compile(r"\s*[|–-]\s*facebook\s*$", re.IGNORECASE)


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attr = {k.lower(): (v or "") for k, v in attrs}
        key = (attr.get("property") or attr.get("name") or "").lower()
        if key in {"og:title", "og:description", "og:image", "og:type"} and key not in self.meta:
            content = attr.get("content", "").strip()
            if content:
                self.meta[key] = content


def parse_meta(html: str) -> dict[str, str]:
    parser = _MetaParser()
    parser.feed(html)
    return parser.meta


class LivePublicMetaSource:
    name = "live_meta"

    def __init__(
        self,
        enabled: bool,
        timeout_seconds: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def acquire(self, url: CanonicalUrl) -> AcquisitionResult | None:
        if not self.enabled:
            return None
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html", "Accept-Language": "vi,en;q=0.8"},
            ) as client:
                response = client.get(url.url)
                body = response.content[:MAX_BODY_BYTES].decode(response.encoding or "utf-8", errors="replace")
        except httpx.TimeoutException:
            return self._fail(url, AccessState.UNREACHABLE, "UNREACHABLE: Request tới facebook.com bị quá thời gian chờ.")
        except httpx.HTTPError as exc:
            return self._fail(url, AccessState.UNREACHABLE, f"UNREACHABLE: Lỗi mạng ({type(exc).__name__}).")
        return self._classify(url, response, body)

    def _classify(self, url: CanonicalUrl, response: httpx.Response, body: str) -> AcquisitionResult:
        status = response.status_code
        if status in (404, 410):
            return self._fail(url, AccessState.NOT_FOUND, f"NOT_FOUND: Facebook trả về HTTP {status}.")
        if 300 <= status < 400:
            location = response.headers.get("location", "")
            if any(m in location.lower() for m in LOGIN_PATH_MARKERS):
                return self._fail(url, AccessState.LOGIN_REQUIRED, LOGIN_LIMITATION)
            return self._fail(
                url,
                AccessState.UNREACHABLE,
                f"UNREACHABLE: Facebook chuyển hướng (HTTP {status}); agent không đi theo chuyển hướng "
                "vì chỉ gửi đúng một request.",
            )
        if status != 200:
            return self._fail(
                url, AccessState.UNREACHABLE, f"UNREACHABLE: Facebook trả về HTTP {status}; không thử lại."
            )

        if NOT_FOUND_BODY_MARKERS.search(body):
            return self._fail(url, AccessState.NOT_FOUND, "NOT_FOUND: Facebook báo nội dung không còn khả dụng.")

        meta = parse_meta(body)
        name = TITLE_SUFFIX.sub("", meta.get("og:title", "")).strip()
        if name and not GENERIC_TITLES.match(name):
            return self._public(url, name, meta)
        if LOGIN_BODY_MARKERS.search(body):
            return self._fail(url, AccessState.LOGIN_REQUIRED, LOGIN_LIMITATION)
        return self._fail(
            url,
            AccessState.NO_ACCESSIBLE_DATA,
            "TECHNICAL LIMITATION: Trang công khai không có thẻ meta nào về trang cá nhân.",
        )

    def _public(self, url: CanonicalUrl, name: str, meta: dict[str, str]) -> AcquisitionResult:
        description = meta.get("og:description")
        if description and BOILERPLATE_DESCRIPTION.search(description):
            description = None
        image = meta.get("og:image")
        profile_type: ProfileType = "UNKNOWN"
        if meta.get("og:type", "").casefold() == "profile":
            profile_type = "PERSONAL_PROFILE"
        elif PUBLIC_PAGE_MARKERS.search(f"{name} {description or ''}"):
            profile_type = "PUBLIC_PAGE"
        raw = RawProfile(
            facebook_url=url.url,
            synthetic=False,
            profile_type=profile_type,
            access={"state": AccessState.PUBLIC if description else AccessState.PARTIAL},
            collected_at=datetime.now(timezone.utc),
            collection_method="live_meta",
            display_name=name,
            bio=description,
            images=[ProfileImage(kind="avatar", url=image)] if image else [],
        )
        return AcquisitionResult(
            canonical_url=url.url,
            access_state=raw.access.state,
            raw=raw,
            source_name=self.name,
            limitations=[SCOPE_NOTE],
        )

    def _fail(self, url: CanonicalUrl, state: AccessState, note: str) -> AcquisitionResult:
        log.info("live meta fetch for %s: %s", url.url, state.value)
        return AcquisitionResult(
            canonical_url=url.url,
            access_state=state,
            source_name=self.name,
            limitations=[note, SCOPE_NOTE],
        )
