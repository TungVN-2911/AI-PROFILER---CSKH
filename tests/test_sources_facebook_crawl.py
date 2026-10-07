import pytest

from app.input import validate_profile_url
from app.models import AccessState
from app.sources import facebook_crawl


@pytest.fixture(autouse=True)
def no_browser_waits(monkeypatch):
    monkeypatch.setattr(facebook_crawl.time, "sleep", lambda _seconds: None)


class _Element:
    def __init__(self, text="", content=None, attributes=None):
        self.text = text
        self.content = content
        self.attributes = attributes or {}

    def get_attribute(self, name):
        return self.content if name == "content" else self.attributes.get(name)


class _Driver:
    def __init__(self, *, body_text="Public profile", page_type=None):
        self.current_url = "https://www.facebook.com/public.user"
        self.visited = []
        self.body_text = body_text
        self.page_type = page_type

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def refresh(self):
        self.current_url = self.visited[-1]

    def set_page_load_timeout(self, _timeout):
        pass

    def execute_script(self, _script):
        return "complete"

    def save_screenshot(self, _path):
        return True

    def find_element(self, by, selector):
        assert selector == "body"
        return _Element(text=self.body_text)

    def find_elements(self, by, selector):
        if selector == "h1" or selector.endswith("//h1[not(ancestor::div[@role='dialog'])]"):
            return [_Element(text="Public User")]
        if selector == (
            "[data-ad-preview='message'], [data-testid='post_message'], "
            "div[dir='auto'] span[lang]"
        ):
            return [_Element(text="A public post with enough text to be collected.")]
        if selector == 'meta[property="og:description"]':
            return [_Element(content="Public bio text")]
        if selector == 'meta[property="og:type"]' and self.page_type:
            return [_Element(content=self.page_type)]
        return []

    def quit(self):
        pass


class _Wait:
    def __init__(self, driver, _timeout):
        self.driver = driver

    def until(self, condition):
        assert condition(self.driver)


def test_disabled_collector_does_not_start_browser(monkeypatch):
    def fail_if_called(**_kwargs):
        raise AssertionError("browser must not start when the source is disabled")

    monkeypatch.setattr(facebook_crawl.webdriver, "Chrome", fail_if_called)
    source = facebook_crawl.FacebookSeleniumSource(enabled=False)

    assert source.acquire(validate_profile_url("https://www.facebook.com/public.user")) is None


def test_collector_visits_only_profile_without_login(monkeypatch):
    driver = _Driver()
    monkeypatch.setattr(facebook_crawl.webdriver, "Chrome", lambda **_kwargs: driver)
    monkeypatch.setattr(facebook_crawl, "WebDriverWait", _Wait)
    source = facebook_crawl.FacebookSeleniumSource(enabled=True)
    url = validate_profile_url("https://www.facebook.com/public.user")

    result = source.acquire(url)

    assert result is not None
    assert result.access_state is AccessState.PUBLIC
    assert result.raw is not None
    assert result.raw.display_name == "Public User"
    assert result.raw.bio == "Public bio text"
    assert result.raw.collection_method == "public_browser"
    assert driver.visited == ["https://facebook.com", url.url]


def test_login_wall_is_reported_as_blocked():
    assert facebook_crawl._is_login_redirect("https://www.facebook.com/login/")
    assert not facebook_crawl._is_login_redirect("https://www.facebook.com/public.user")


def test_login_wall_text_is_classified_when_no_profile_content_exists(monkeypatch):
    driver = _Driver(body_text="You must log in to see this profile")
    driver.find_elements = lambda _by, selector: []
    monkeypatch.setattr(facebook_crawl.webdriver, "Chrome", lambda **_kwargs: driver)
    monkeypatch.setattr(facebook_crawl, "WebDriverWait", _Wait)
    source = facebook_crawl.FacebookSeleniumSource(enabled=True)
    url = validate_profile_url("https://www.facebook.com/public.user")

    result = source.acquire(url)

    assert result is not None and result.access_state is AccessState.LOGIN_REQUIRED


def test_og_profile_type_marks_personal_profile(monkeypatch):
    driver = _Driver(page_type="profile")
    monkeypatch.setattr(facebook_crawl.webdriver, "Chrome", lambda **_kwargs: driver)
    monkeypatch.setattr(facebook_crawl, "WebDriverWait", _Wait)
    source = facebook_crawl.FacebookSeleniumSource(enabled=True)

    result = source.acquire(validate_profile_url("https://www.facebook.com/public.user"))

    assert result is not None and result.raw is not None
    assert result.raw.profile_type == "PERSONAL_PROFILE"


def test_avatar_extractor_requires_explicit_profile_picture_label():
    avatar = "https://cdn.example/avatar.jpg"
    cover = "https://cdn.example/cover.jpg"

    class _Images:
        def find_elements(self, by, selector):
            if by == facebook_crawl.By.XPATH:
                if selector.endswith("//img"):
                    return [
                        _Element(
                            attributes={"src": cover, "alt": "Cover photo"}
                        ),
                        _Element(
                            attributes={
                                "src": avatar,
                                "alt": "Public User's profile picture",
                            }
                        ),
                    ]
                return []
            if by == facebook_crawl.By.CSS_SELECTOR:
                assert selector == "svg[aria-label]"
                return []
            return []

    assert facebook_crawl.FacebookSeleniumSource._avatar_url(_Images()) == avatar


def test_avatar_extractor_reads_labeled_svg_image_href():
    avatar = "https://cdn.example/avatar-from-svg.jpg"
    cover = "https://cdn.example/cover.jpg"

    class _Svg:
        def __init__(self, label, href):
            self.label = label
            self.image = _Element(
                attributes={"href": href, "xlink:href": None}
            )

        def get_attribute(self, name):
            return self.label if name == "aria-label" else None

        def find_elements(self, _by, selector):
            assert selector == "image"
            return [self.image]

    class _Profile:
        def find_elements(self, by, selector):
            if by == facebook_crawl.By.XPATH:
                return []
            if by == facebook_crawl.By.CSS_SELECTOR:
                assert selector == "svg[aria-label]"
                return [
                    _Svg("Cover photo", cover),
                    _Svg("Thanh Tùng", avatar),
                ]
            assert by == facebook_crawl.By.TAG_NAME
            assert selector == "img"
            return []

    assert (
        facebook_crawl.FacebookSeleniumSource._avatar_url(
            _Profile(), "Thanh Tùng"
        )
        == avatar
    )


def test_avatar_extractor_does_not_treat_unmatched_svg_image_as_avatar():
    cover = "https://cdn.example/cover.jpg"

    class _Svg:
        def get_attribute(self, name):
            return "Cover photo" if name == "aria-label" else None

        def find_elements(self, _by, _selector):
            return [_Element(attributes={"href": cover})]

    class _Profile:
        def find_elements(self, by, selector):
            if by == facebook_crawl.By.XPATH:
                return []
            if by == facebook_crawl.By.CSS_SELECTOR:
                return [_Svg()]
            return []

    assert (
        facebook_crawl.FacebookSeleniumSource._avatar_url(
            _Profile(), "Thanh Tùng"
        )
        is None
    )


def test_cover_extractor_reads_labeled_svg_image_href():
    cover = "https://cdn.example/cover-from-svg.jpg"

    class _Svg:
        def get_attribute(self, name):
            return "Cover photo" if name == "aria-label" else None

        def find_elements(self, _by, selector):
            assert selector == "image"
            return [_Element(attributes={"href": cover})]

    class _Profile:
        def find_elements(self, by, selector):
            if by == facebook_crawl.By.XPATH:
                return []
            if by == facebook_crawl.By.CSS_SELECTOR:
                assert selector == "svg[aria-label]"
                return [_Svg()]
            assert by == facebook_crawl.By.XPATH
            return []

    assert facebook_crawl.FacebookSeleniumSource._cover_url(_Profile()) == cover


def test_cover_is_selected_when_avatar_is_unavailable():
    cover = "https://cdn.example/cover.jpg"

    profile_image = facebook_crawl._profile_image(None, cover, None)

    assert profile_image is not None
    assert profile_image.kind == "cover"
    assert profile_image.url == cover


def test_cover_is_not_used_when_avatar_is_available():
    avatar = "https://cdn.example/avatar.jpg"
    cover = "https://cdn.example/cover.jpg"

    profile_image = facebook_crawl._profile_image(avatar, cover, None)

    assert profile_image is not None
    assert profile_image.kind == "avatar"
    assert profile_image.url == avatar


def test_generic_open_graph_image_is_not_mislabeled_as_avatar_or_cover():
    preview = "https://cdn.example/cover.jpg"

    profile_image = facebook_crawl._profile_image(None, None, preview)

    assert profile_image is not None
    assert profile_image.kind == "photo"
    assert profile_image.url == preview


def test_explicit_avatar_takes_precedence_over_generic_preview_image():
    avatar = "https://cdn.example/avatar.jpg"
    preview = "https://cdn.example/cover.jpg"

    profile_image = facebook_crawl._profile_image(avatar, None, preview)

    assert profile_image is not None
    assert profile_image.kind == "avatar"
    assert profile_image.url == avatar


def test_platform_boilerplate_alone_does_not_satisfy_pipeline(monkeypatch):
    from app.config import load_settings
    from app.models import AccessInfo, AcquisitionResult, RawProfile
    from app.pipeline import PipelineOptions, run_pipeline
    from app.schema import PartialOutput

    url = validate_profile_url("https://www.facebook.com/thanh.hung.844")

    class _PublicBrowser:
        def __init__(self, enabled):
            assert enabled

        def acquire(self, canonical_url):
            raw = RawProfile(
                facebook_url=canonical_url.url,
                display_name="Thanh Hưng",
                bio=(
                    "Thanh Hưng is on Facebook · Join Facebook to connect with Thanh Hưng "
                    "and others you may know · Facebook gives people the power to share and "
                    "makes the world more open and connected."
                ),
                access=AccessInfo(state=AccessState.PUBLIC),
                collection_method="public_browser",
            )
            return AcquisitionResult(
                canonical_url=canonical_url.url,
                access_state=AccessState.PUBLIC,
                raw=raw,
                source_name="facebook_selenium",
            )

    monkeypatch.setattr("app.pipeline.FacebookSeleniumSource", _PublicBrowser)
    result = run_pipeline(
        url.url,
        PipelineOptions(mode="deterministic"),
        load_settings(env={}, dotenv_path=None),
    )

    assert isinstance(result.output, PartialOutput)
    assert result.output.error_note.startswith("INSUFFICIENT_DATA:")
    assert [fact.category for fact in result.evidence.fact_ledger] == ["name"]
