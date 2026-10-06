# app/sources/facebook_selenium.py
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.input import CanonicalUrl
from app.models import (
    AccessState,
    AcquisitionResult,
    ProfileImage,
    RawProfile,
    AccessInfo,
    PublicInfo,
    PublicPost,
)

log = logging.getLogger(__name__)


class FacebookSeleniumSource:
    name = "facebook_selenium"

    def __init__(self, enabled: bool, settings: any) -> None:
        self.enabled = enabled
        self.email = getattr(settings, "facebook_email", None)

        # Giải mã chuỗi SecretStr từ Pydantic an toàn bằng .get_secret_value()
        raw_password = getattr(settings, "facebook_password", None)
        self.password = raw_password.get_secret_value() if raw_password else None

        self.headless = getattr(settings, "selenium_headless", True)

        self.user_data_dir = (
            Path(__file__).parent.parent / "storage" / "selenium_profile"
        )
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

    def acquire(self, url: CanonicalUrl) -> AcquisitionResult | None:
        if not self.enabled:
            return None

        if not self.email or not self.password:
            log.warning(
                "FacebookSeleniumSource: Thiếu cấu hình tài khoản facebook_email/facebook_password."
            )
            return None

        # 1. Cấu hình Chrome Driver nâng cao phòng chống chống quét bot
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless=new")

        chrome_options.add_argument(f"--user-data-dir={self.user_data_dir.absolute()}")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--window-size=1280,1024")
        chrome_options.add_argument(
            "--lang=vi"
        )  # Ép tiếng Việt để đồng bộ bóc tách chữ
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 10)

        try:
            # 2. Xử lý Đăng nhập
            driver.get("https://www.facebook.com")
            time.sleep(3)

            # Tìm ô nhập email xem có hiển thị không
            email_fields = driver.find_elements(By.ID, "email")
            if email_fields and email_fields[0].is_displayed():
                log.info(
                    "Phát hiện chưa đăng nhập Facebook. Đang tiến hành đăng nhập..."
                )

                # Chờ các ô nhập liệu sẵn sàng tương tác
                email_input = wait.until(EC.element_to_be_clickable((By.ID, "email")))
                pass_input = wait.until(EC.element_to_be_clickable((By.ID, "pass")))

                email_input.clear()
                email_input.send_keys(self.email)
                time.sleep(1)  # Nghỉ 1 giây giả lập người dùng nhập

                pass_input.clear()
                pass_input.send_keys(self.password)
                time.sleep(1)

                wait.until(EC.element_to_be_clickable((By.NAME, "login"))).click()
                log.info("Đã bấm nút Đăng nhập. Chờ xử lý session...")
                time.sleep(
                    8
                )  # Tăng thời gian chờ để Facebook thiết lập Cookie/Session ổn định

            # 3. Tiến vào Trang cá nhân mục tiêu
            log.info("Đang điều hướng tới trang cá nhân: %s", url.url)
            driver.get(url.url)
            time.sleep(5)

            # Kiểm tra tường chặn / nội dung không hiển thị (Tài khoản chết hoặc block)
            current_url = driver.current_url
            if "login" in current_url or "checkpoint" in current_url:
                return AcquisitionResult(
                    canonical_url=url.url,
                    access_state=AccessState.LOGIN_REQUIRED,
                    source_name=self.name,
                    limitations=[
                        "Selenium bị chặn bởi màn hình login/checkpoint của Facebook."
                    ],
                )

            # 4. Trích xuất Tên hiển thị (Facebook Desktop thường bọc tên trong thẻ h1 hoặc aria-label)
            display_name = "Không tìm thấy tên"
            try:
                # Đợi cho tới khi phần tử tên hiển thị xuất hiện
                h1_elements = driver.find_elements(By.XPATH, "//h1")
                for element in h1_elements:
                    text = element.text.strip()
                    if text and "Profile picture" not in text:
                        display_name = text
                        break
            except Exception:
                pass

            # 5. Thu thập link ảnh Đại diện (Avatar) phục vụ cho app/vision.py
            avatar_images = []
            try:
                # Tìm thẻ ảnh đại diện bằng cách định vị vòng tròn avatar
                # Facebook thường dùng thẻ SVG bao quanh hoặc thuộc tính vai trò cụ thể
                images = driver.find_elements(By.TAG_NAME, "img")
                for img in images:
                    src = img.get_attribute("src")
                    if src and (
                        "s160x160" in src
                        or "p160x160" in src
                        or "/cp0/" in src
                        or "images/user" in src
                    ):
                        avatar_images.append(ProfileImage(kind="avatar", url=src))
                        break
            except Exception:
                pass

            # 6. Cuộn trang lấy nội dung bài đăng (Crawl sâu)
            log.info("Đang cuộn trang và thu quét dữ liệu văn bản thực tế hiển thị...")
            collected_chunks = []

            # Cuộn 4 lần để Facebook tải thêm bài đăng công khai của khách
            for scroll_idx in range(4):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3.0)  # Tăng thời gian chờ lên 3 giây để dữ liệu kịp tải về

                # BỘ LỌC CỰC MẠNH: Quét tất cả các phần tử chứa văn bản hiển thị có ý nghĩa trên màn hình
                # Cách tiếp cận này gom toàn bộ bài viết, mô tả ảnh, thông tin giới thiệu công việc, nơi sống...
                elements = driver.find_elements(
                    By.XPATH,
                    "//*[@data-ad-preview='message'] | //div[@data-testid='post_message'] | //span[@dir='auto']",
                )

                for elem in elements:
                    try:
                        text_content = elem.text.strip()
                        # Loại bỏ các chuỗi rác, nút tương tác ngắn để giữ lại sự thật chất lượng cao
                        if (
                            text_content
                            and len(text_content) > 15
                            and text_content not in collected_chunks
                            and not any(
                                trash in text_content.lower()
                                for trash in [
                                    "bình luận",
                                    "chia sẻ",
                                    "thích",
                                    "phản hồi",
                                    "gợi ý cho bạn",
                                    "theo dõi",
                                ]
                            )
                        ):
                            collected_chunks.append(text_content)
                    except Exception:
                        continue

            # Chiến lược phòng ngự dự phòng: Nếu bộ lọc sâu ở trên trống do Facebook thay đổi cấu trúc,
            # lấy toàn bộ Text trần của vùng nội dung chính để nuôi Ledger, tuyệt đối không để thiếu thông tin
            if not collected_chunks:
                try:
                    main_content = driver.find_element(
                        By.XPATH, "//div[@role='main']"
                    ).text
                    lines = [
                        line.strip()
                        for line in main_content.split("\n")
                        if len(line.strip()) > 15
                    ]
                    collected_chunks = list(dict.fromkeys(lines))[
                        :30
                    ]  # Lấy 30 dòng chữ chất lượng nhất
                except Exception:
                    pass

            # Gộp toàn bộ văn bản bóc tách được chuyển đổi thành cấu trúc Pydantic
            full_bio_context = "\n---\n".join(collected_chunks)[:40000]

            # 7. Chuyển đổi danh sách bài viết thô thành danh sách các đối tượng PublicPost
            posts_objects = []
            for chunk in collected_chunks:
                if chunk and len(chunk.strip()) > 0:
                    posts_objects.append(PublicPost(date=None, text=chunk.strip()))

            # 8. Phân tách thông tin giới thiệu từ văn bản đã thu thập để đưa vào PublicInfo
            current_city = None
            hometown = None
            work_info = []
            education_info = []

            for chunk in collected_chunks:
                lower_chunk = chunk.lower()
                if "sống tại" in lower_chunk or "lives in" in lower_chunk:
                    current_city = chunk.split("tại")[-1].split("in")[-1].strip()
                elif "đến từ" in lower_chunk or "from" in lower_chunk:
                    hometown = chunk.split("từ")[-1].split("from")[-1].strip()
                elif "làm việc tại" in lower_chunk or "works at" in lower_chunk:
                    work_info.append(chunk.strip())
                elif (
                    "học tại" in lower_chunk
                    or "studied at" in lower_chunk
                    or "trường" in lower_chunk
                ):
                    education_info.append(chunk.strip())

            # 9. Khởi tạo đối tượng RawProfile đồng bộ cấu trúc phân tích của hệ thống
            raw = RawProfile(
                facebook_url=url.url,
                synthetic=False,
                access=AccessInfo(
                    state=AccessState.PUBLIC
                    if collected_chunks
                    else AccessState.PARTIAL,
                    note="",
                ),
                collected_at=datetime.now(timezone.utc),
                collection_method="live_meta",  # Tránh lỗi Literal giới hạn giá trị phương thức
                display_name=display_name
                if display_name != "Không tìm thấy tên"
                else "Khách hàng Facebook",
                bio=full_bio_context
                if full_bio_context
                else "Thông tin tài liệu công khai",
                public_info=PublicInfo(
                    work=work_info,
                    education=education_info,
                    interests=[],
                    current_city=current_city,
                    hometown=hometown,
                    pronouns=None,
                    gender=None,
                    birth_year=None,
                    links=[],
                ),
                public_posts=posts_objects,
                images=avatar_images,
            )
            return AcquisitionResult(
                canonical_url=url.url,
                access_state=raw.access.state,
                raw=raw,
                source_name=self.name,
                synthetic=False,
                limitations=[],
            )
        except Exception as exc:
            log.exception("Lỗi nghiêm trọng trong luồng crawl Selenium")
            return AcquisitionResult(
                canonical_url=url.url,
                access_state=AccessState.UNREACHABLE,
                source_name=self.name,
                limitations=[f"Selenium Network Error: {type(exc).name}"],
            )
        finally:
            driver.quit()
