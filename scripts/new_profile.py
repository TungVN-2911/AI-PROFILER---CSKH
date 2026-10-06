"""Create a fill-in profile file for a real Facebook profile you have consent to use (FR-020).

Usage:  python scripts/new_profile.py --url "https://www.facebook.com/<username>" [--out FILE] [--force]
Writes: runs/real/<username or id>.json by default (git-ignored). The agent never collects real data itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.input import InputError, validate_profile_url  # noqa: E402
from app.sources.base import SourceError  # noqa: E402
from app.sources.provided import load_raw_profile  # noqa: E402

INSTRUCTIONS = """Đã tạo file mẫu: {path}

Cách điền (chỉ với trang cá nhân bạn được chủ nhân đồng ý sử dụng):
  1. Mở trang cá nhân, chỉ chép lại những gì đang hiển thị công khai. Không đoán, không thêm thắt.
  2. Điền display_name, bio, public_info (công việc, học vấn, sở thích, nơi sống…), và 2–3 bài đăng công khai gần nhất
     vào public_posts dạng {{"date": "YYYY-MM-DD", "text": "..."}}.
  3. Ảnh đại diện: mô tả ngắn những gì nhìn thấy vào images[0].alt_text ("Ảnh đại diện có vẻ cho thấy …"), hoặc lưu ảnh
     vào máy và ghi đường dẫn vào images[0].path để mô hình AI tự mô tả. Không có ảnh → kết quả sẽ là NO_IMAGE.
  4. Trang bị khóa / link chết: đặt access.state = "PRIVATE" hoặc "NOT_FOUND" và ghi chú vào access.note.
  5. Chạy thử:  python main.py --url "{url}" --profile-file "{path}"
     Hoặc chạy cả thư mục:  python scripts/run_test_profiles.py --profiles-dir "{folder}"

Lưu ý quyền riêng tư: file nằm trong runs/ (đã git-ignore). Chỉ commit kết quả khi chủ trang đồng ý công bố. Với hạng
miễn phí của Gemini, dữ liệu gửi lên có thể được Google dùng để cải thiện sản phẩm."""


def template(url: str) -> dict:
    return {
        "facebook_url": url,
        "synthetic": False,
        "access": {"state": "PUBLIC", "note": ""},
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "collection_method": "manual_export",
        "display_name": "",
        "bio": "",
        "public_info": {
            "work": [],
            "education": [],
            "interests": [],
            "current_city": None,
            "hometown": None,
            "pronouns": None,
            "gender": None,
            "birth_year": None,
            "links": [],
        },
        "public_posts": [],
        "images": [{"kind": "avatar", "path": None, "url": None, "alt_text": None}],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="Facebook profile URL")
    parser.add_argument("--out", type=Path, help="output file (default: runs/real/<username or id>.json)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)

    try:
        url = validate_profile_url(args.url)
    except InputError as exc:
        print(exc.error_note, file=sys.stderr)
        return 2
    out = args.out or ROOT / "runs" / "real" / f"{url.identifier}.json"
    if out.exists() and not args.force:
        print(f"File đã tồn tại, không ghi đè: {out} (dùng --force nếu muốn ghi đè)", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(template(url.url), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        load_raw_profile(out)  # the template must always be a valid profile file
    except SourceError as exc:  # pragma: no cover - guards future format changes
        print(f"INTERNAL_ERROR: {exc}", file=sys.stderr)
        return 1
    print(INSTRUCTIONS.format(path=out, url=url.url, folder=out.parent))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
