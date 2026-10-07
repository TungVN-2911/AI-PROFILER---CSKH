"""Selenium source for content Facebook exposes using a persistent browser profile.

This source uses a shared browser session with a persistent profile to reuse
the logged-in cookies and avoid login barriers.
"""

from __future__ import annotations

import logging
import re
import time
import random
import random
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from app.input import CanonicalUrl
from app.models import (
    AccessInfo,
    AccessInfo,
    AccessState,
    AcquisitionResult,
    ProfileImage,
    ProfileType,
    PublicPost,
    ProfileType,
    PublicPost,
    RawProfile,
)

log = logging.getLogger(__name__)

LOGIN_MARKERS = ("login", "checkpoint", "captcha")
LOGIN_TEXT_MARKERS = ("must log in", "log in to see", "đăng nhập để xem")
NOT_FOUND_MARKERS = (
    "this content isn't available right now",
    "this page isn't available",
    "nội dung này hiện không khả dụng",
    "trang này không khả dụng",
)
MAX_POSTS = 15
TITLE_SUFFIX = re.compile(r"\s*[|–-]\s*facebook\s*$", re.IGNORECASE)
PUBLIC_PAGE_MARKERS = (
    "official page",
    "official account",
    "page chính thức",
    "trang chính thức",
)
GENERIC_TITLES = frozenset(
    {
        "facebook",
        "log in",
        "log into facebook",
        "log in to facebook",
        "đăng nhập facebook",
    }
)


def _is_login_redirect(url: str) -> bool:
    return any(marker in url.casefold() for marker in LOGIN_MARKERS)


LOGIN_MARKERS = ("login", "checkpoint", "captcha")
NOT_FOUND_MARKERS = (
    "this content isn't available right now",
    "this page isn't available",
    "nội dung này hiện không khả dụng",
    "trang này không khả dụng",
)
MAX_POSTS = 15
TITLE_SUFFIX = re.compile(r"\s*[|–-]\s*facebook\s*$", re.IGNORECASE)
PUBLIC_PAGE_MARKERS = (
    "official page",
    "official account",
    "page chính thức",
    "trang chính thức",
)
GENERIC_TITLES = frozenset(
    {
        "facebook",
        "log in",
        "log into facebook",
        "log in to facebook",
        "đăng nhập facebook",
    }
)


def _is_login_redirect(url: str) -> bool:
    return any(marker in url.casefold() for marker in LOGIN_MARKERS)


class FacebookSeleniumSource:
    """Read visible profile content using a persistent, authenticated browser session."""

    name = "facebook_selenium"
    
    def __init__(
        self, enabled: bool, settings: any, timeout_seconds: int = 20
    ) -> None:
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        
        self.headless = getattr(settings, "selenium_headless", True)  
        
        raw_cookie = getattr(settings, "facebook_cookie", None)
        self.cookie_string = raw_cookie.get_secret_value() if raw_cookie else None


    def _failure(
        self, url: CanonicalUrl, state: AccessState, note: str
    ) -> AcquisitionResult:
        return AcquisitionResult(
            canonical_url=url.url,
            access_state=state,
            source_name=self.name,
            limitations=[note],
        )

    def _human_scroll(self, driver: webdriver.Chrome) -> None:
        """Giả lập hành vi cuộn lướt ngẫu nhiên tránh hệ thống AI của Facebook quét bot."""
        scroll_amount = random.randint(350, 650)
        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        time.sleep(random.uniform(2.5, 4.0))

        # 20% tỷ lệ người dùng cuộn ngược nhẹ để đọc lại
        if random.random() < 0.2:
            driver.execute_script(f"window.scrollBy(0, -{random.randint(100, 200)});")
            time.sleep(random.uniform(1.0, 1.5))

    def acquire(self, url: CanonicalUrl) -> AcquisitionResult | None:
        if not self.enabled:
            return None
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")

        # Cấu hình ẩn danh và giả lập trình duyệt thật
        options.add_argument("--disable-notifications")
        options.add_argument("--window-size=1280,1024")
        options.add_argument("--lang=vi")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(self.timeout_seconds)

            # --- BƯỚC 1: TRUY CẬP ĐỂ THIẾT LẬP DOMAIN FACEBOOK ---
            log.info("Đang khởi tạo domain Facebook để nạp Cookie...")
            driver.get("https://facebook.com")
            time.sleep(2)

            if not self.cookie_string:
                log.warning("FacebookSeleniumSource: Thiếu cấu hình FACEBOOK_COOKIE trong file .env.")
                return self._failure(url, AccessState.LOGIN_REQUIRED, "Thiếu thiết lập Token Cookie.")

            log.info("Đang tiến hành nạp Cookie vào phiên chạy ngầm...")
            for item in self.cookie_string.split(";"):
                if "=" in item:
                    name, value = item.strip().split("=", 1)
                    try:
                        driver.add_cookie(
                            {
                                "name": name,
                                "value": value,
                                "domain": ".facebook.com",
                                "path": "/",
                            }
                        )
                    except Exception as e:
                        log.debug(f"Bỏ qua thành phần cookie phụ {name}: {e}")

            driver.refresh()
            time.sleep(3)

            log.info("Selenium đang tiến vào mục tiêu: %s", url.url)
            driver.get(url.url)
            time.sleep(random.uniform(5.0, 7.0))

            try:
                screenshot_path = str(
                    Path(__file__).parent.parent / "storage" / "debug_fb.png"
                )
                driver.save_screenshot(screenshot_path)
                log.info(f"👉 ĐÃ CHỤP ẢNH MÀN HÌNH DEBUG MỚI TẠI: {screenshot_path}")
            except Exception as e:
                log.warning(f"Không thể chụp ảnh debug: {e}")

            page_url = driver.current_url
            if _is_login_redirect(page_url):
                return self._failure(
                    url,
                    AccessState.LOGIN_REQUIRED,
                    "Facebook yêu cầu đăng nhập hoặc phiên Cookie đã hết hạn.",
                )

            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text
            except StaleElementReferenceException:
                page_text = ""

            if any(marker in page_text.casefold() for marker in LOGIN_TEXT_MARKERS):
                return self._failure(
                    url,
                    AccessState.LOGIN_REQUIRED,
                    "Facebook yêu cầu đăng nhập để xem nội dung.",
                )

            if any(marker in page_text.casefold() for marker in NOT_FOUND_MARKERS):
                return self._failure(
                    url,
                    AccessState.NOT_FOUND,
                    "Facebook báo nội dung không tồn tại hoặc không khả dụng.",
                )

            # 1. Trích xuất Tên hiển thị (Ưu tiên thẻ H1 chính thống của profile)
            # --- BƯỚC 4: TRÍCH XUẤT TÊN HIỂN THỊ CHUẨN XÁC THEO HTML THỰC TẾ ---
            display_name = None
            try:
                # Thuật toán 1: Tìm trực tiếp thẻ span có class 'x1lliihq' nằm trong vùng nội dung chính (main role)
                # Loại trừ các phần tử nằm trong hộp thoại pop-up (dialog) nếu có
                span_names = driver.find_elements(
                    By.XPATH,
                    "//div[@role='main']//span[contains(@class, 'x1lliihq') and not(ancestor::div[@role='dialog'])]",
                )
                for element in span_names:
                    text = element.text.strip()
                    # Bộ lọc loại bỏ các text rác hệ thống hoặc nút tương tác gần ảnh bìa
                    if (
                        text
                        and len(text) > 1
                        and not any(
                            k in text.lower()
                            for k in [
                                "profile picture",
                                "ảnh đại diện",
                                "bài viết",
                                "bản tin",
                                "thích",
                                "bình luận",
                                "chia sẻ",
                                "theo dõi",
                                "bạn bè",
                                "thêm",
                            ]
                        )
                    ):
                        display_name = text
                        break  # Bốc được tên thật đầu tiên thì dừng vòng lặp ngay

                # Thuật toán 2 (Dự phòng): Nếu không tìm thấy bằng class, quét qua thẻ h1 chính thống
                if not display_name:
                    h1_main = driver.find_elements(
                        By.XPATH,
                        "//div[@role='main']//h1[not(ancestor::div[@role='dialog'])]",
                    )
                    for element in h1_main:
                        text = element.text.strip()
                        if text and not any(
                            k in text.lower()
                            for k in ["profile picture", "ảnh đại diện", "bài viết"]
                        ):
                            display_name = text
                            break
            except Exception as e:
                log.warning(f"Lỗi khi quét Selector tên x1lliihq trực tiếp: {e}")

            # Thuật toán 3 (Dự phòng tầng cuối): Bóc tách qua thẻ meta og:title nằm trong mã nguồn HTML tĩnh
            if not display_name:
                try:
                    title_meta = self._meta_content(driver, "og:title")
                    if title_meta:
                        display_name = TITLE_SUFFIX.sub("", title_meta).strip()
                except Exception:
                    pass

            # ĐỒNG BỘ: Nếu tìm thấy tên hợp lệ, gán vào. Nếu không, giữ nguyên định danh mặc định hệ thống
            profile_name_for_image = display_name
            if not display_name or display_name.casefold() in GENERIC_TITLES:
                display_name = "Khách hàng Facebook"

            log.info(
                "🎉 Hệ thống đã bóc tách thành công tên hiển thị hồ sơ: %s",
                display_name,
            )

            description = self._meta_content(driver, "og:description")
            page_type = self._meta_content(driver, "og:type")

            # 2. Thực hiện cuộn trang lấy Bài viết (Mô phỏng 3 chu kỳ lướt sâu)
            posts: list[PublicPost] = []
            seen_posts: set[str] = set()

            for _ in range(3):
                self._human_scroll(driver)

                # Bộ lọc CSS đa tầng (Tương thích cả giao diện dòng thời gian đăng nhập mới nhất)
                post_elements = driver.find_elements(
                    By.CSS_SELECTOR,
                    "[data-ad-preview='message'], [data-testid='post_message'], div[dir='auto'] span[lang]",
                )

                for element in post_elements:
                    try:
                        text = element.text.strip()
                    except StaleElementReferenceException:
                        continue

                    # Loại bỏ các phân đoạn chữ rác của nút hệ thống
                    if (
                        len(text) > 15
                        and text not in seen_posts
                        and not any(
                            trash in text.lower()
                            for trash in [
                                "bình luận",
                                "chia sẻ",
                                "thích",
                                "phản hồi",
                                "gợi ý",
                            ]
                        )
                    ):
                        seen_posts.add(text)
                        posts.append(PublicPost(text=text))
                        if len(posts) >= MAX_POSTS:
                            break
                if len(posts) >= MAX_POSTS:
                    break

            avatar_url = self._avatar_url(driver, profile_name_for_image)
            cover_url = self._cover_url(driver)
            if avatar_url and avatar_url == cover_url:
                avatar_url = None
            preview_image_url = self._meta_content(driver, "og:image")
            profile_image = _profile_image(avatar_url, cover_url, preview_image_url)
            profile_image_url = profile_image.url if profile_image else None

            if not display_name and not posts and not profile_image_url:
                return self._failure(
                    url,
                    AccessState.NO_ACCESSIBLE_DATA,
                    "Facebook chặn không hiển thị dữ liệu hoặc cấu trúc trang thay đổi.",
                )

            profile_type: ProfileType = "UNKNOWN"
            if page_type and page_type.casefold() == "profile":
                profile_type = "PERSONAL_PROFILE"
            elif display_name and any(
                marker in f"{display_name} {description or ''}".casefold()
                for marker in PUBLIC_PAGE_MARKERS
            ):
                profile_type = "PUBLIC_PAGE"
            else:
                profile_type = (
                    "PERSONAL_PROFILE"  # Mặc định an toàn cho pipeline cá nhân
                )

            raw = RawProfile(
                facebook_url=url.url,
                synthetic=False,
                profile_type=profile_type,
                access=AccessInfo(
                    state=AccessState.PUBLIC if posts else AccessState.PARTIAL
                ),
                collected_at=datetime.now(timezone.utc),
                collection_method="public_browser",
                display_name=display_name or "Người dùng Facebook",
                bio=description,
                public_posts=posts,
                images=[profile_image] if profile_image else [],
            )
            return AcquisitionResult(
                canonical_url=url.url,
                access_state=raw.access.state,
                raw=raw,
                source_name=self.name,
                limitations=["Crawl an toàn qua cơ chế lưu phiên Profile cố định."],
            )
        except WebDriverException as exc:
            log.warning("Facebook browser fetch failed: %s", type(exc).__name__)
            return self._failure(
                url,
                AccessState.UNREACHABLE,
                f"Không thể kết nối tới trình duyệt ({type(exc).__name__}).",
            )
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except WebDriverException as exc:
                    log.warning(
                        "Could not clean up browser session: %s", type(exc).__name__
                    )

    @staticmethod
    def _meta_content(driver: webdriver.Chrome, key: str) -> str | None:
        elements = driver.find_elements(By.CSS_SELECTOR, f'meta[property="{key}"]')
        if not elements:
            return None
        try:
            content = elements[0].get_attribute("content")
        except StaleElementReferenceException:
            return None
        return content.strip() if content and content.strip() else None

    @staticmethod
    def _avatar_url(
        driver: webdriver.Chrome, display_name: str | None = None
    ) -> str | None:
        """Bóc tách link ảnh đại diện thông qua cấu trúc thẻ SVG và thẻ <image> thực tế sau đăng nhập."""

        # 1. Thuật toán ưu tiên cao nhất: Quét Xpath động dựa trên cấu trúc DOM thực tế của bạn
        # Tìm tất cả thẻ image nằm bên trong khối SVG của cụm đầu trang cá nhân (Vùng main)
        try:
            # Lọc các thẻ image nằm trong khối có thuộc tính chiều cao/chiều rộng đặc trưng của khối avatar lớn (168px)
            avatar_images = driver.find_elements(
                By.XPATH,
                "//div[@role='main']//svg[@aria-label='profile picture']//image | "
                "//div[@role='main']//svg[@aria-label='ảnh đại diện']//image",
            )
            for img in avatar_images:
                try:
                    source = (
                        img.get_attribute("xlink:href")
                        or img.get_attribute("href")
                        or ""
                    )
                    if source.startswith("https://") and "fbcdn.net" in source:
                        log.info(
                            "🎉 Đã tìm thấy link ảnh đại diện qua thẻ SVG/image hệ thống."
                        )
                        return source
                except StaleElementReferenceException:
                    continue
        except Exception as e:
            log.debug(f"Bỏ qua lỗi quét nhanh thuật toán ảnh SVG: {e}")

        # 2. Thuật toán dự phòng 2: Duyệt qua tất cả các khối SVG chứa nhãn tên (Thuật toán gốc được tối ưu hóa)
        expected_name = " ".join((display_name or "").casefold().split())
        for svg in driver.find_elements(By.CSS_SELECTOR, "svg[aria-label]"):
            try:
                label = " ".join(
                    (svg.get_attribute("aria-label") or "").casefold().split()
                )
                explicitly_named = label in {
                    "profile picture",
                    "profile photo",
                    "ảnh đại diện",
                    "ảnh hồ sơ",
                }
                labels_cover = any(marker in label for marker in ("cover", "ảnh bìa"))
                # Tối ưu: Dùng cơ chế tìm kiếm chứa chuỗi (contains) hoặc so khớp tương đối thay vì bằng tuyệt đối
                is_display_name = bool(expected_name) and (
                    expected_name in label or label in expected_name
                )

                if labels_cover or not (explicitly_named or is_display_name):
                    continue

                for image in svg.find_elements(By.TAG_NAME, "image"):
                    source = (
                        image.get_attribute("href")
                        or image.get_attribute("xlink:href")
                        or ""
                    )
                    if source.startswith("https://"):
                        return source
            except StaleElementReferenceException:
                continue

        # 3. Thuật toán dự phòng 3: Quét thẻ <img> truyền thống trong vùng nội dung chính
        for image in driver.find_elements(By.XPATH, "//div[@role='main']//img"):
            try:
                source = image.get_attribute("src") or ""
                labels = " ".join(
                    image.get_attribute(attribute) or ""
                    for attribute in ("alt", "aria-label", "data-testid")
                ).casefold()
            except StaleElementReferenceException:
                continue
            is_cover = any(marker in labels for marker in ("cover", "ảnh bìa"))
            identifies_avatar = any(
                marker in labels
                for marker in (
                    "profile picture",
                    "profile photo",
                    "ảnh đại diện",
                    "ảnh hồ sơ",
                )
            )
            if expected_name and expected_name in labels:
                identifies_avatar = True

            if source.startswith("https://") and identifies_avatar and not is_cover:
                return source

        return None

    @staticmethod
    def _cover_url(driver: webdriver.Chrome) -> str | None:
        for svg in driver.find_elements(By.CSS_SELECTOR, "svg[aria-label]"):
            try:
                label = " ".join(
                    (svg.get_attribute("aria-label") or "").casefold().split()
                )
                if not any(marker in label for marker in ("cover", "ảnh bìa")):
                    continue
                for image in svg.find_elements(By.TAG_NAME, "image"):
                    source = (
                        image.get_attribute("href")
                        or image.get_attribute("xlink:href")
                        or ""
                    )
                    if source.startswith("https://"):
                        return source
            except StaleElementReferenceException:
                continue

        for image in driver.find_elements(By.XPATH, "//div[@role='main']//img"):
            try:
                source = image.get_attribute("src") or ""
                labels = " ".join(
                    image.get_attribute(attribute) or ""
                    for attribute in ("alt", "aria-label", "data-testid")
                ).casefold()
            except StaleElementReferenceException:
                continue
            if source.startswith("https://") and any(
                marker in labels for marker in ("cover", "ảnh bìa")
            ):
                return source
        return None


def _profile_image(
    avatar_url: str | None,
    cover_url: str | None,
    preview_image_url: str | None,
) -> ProfileImage | None:
    if avatar_url:
        return ProfileImage(kind="avatar", url=avatar_url)
    if cover_url:
        return ProfileImage(kind="cover", url=cover_url)
    if preview_image_url:
        return ProfileImage(kind="photo", url=preview_image_url)
    return None
