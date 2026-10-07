"""Visual context extraction.

Two paths:
- Provided `alt_text` (a description supplied with the data): used as-is, no AI call. Ledger status FACT.
- No alt text: one image is described by the vision model. Observations are model-generated, so they are
  stored as INFERENCE with their confidence: they appear in `visual_context` but are never used to ground
  rapport messages or demographics.
Every description is screened for sensitive attributes. Any failure yields `NOT_AVAILABLE: <reason>`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import PROJECT_ROOT
from app.ledger import append_fact, without_facts
from app.lexicons import EMAIL_PATTERN, PHONE_PATTERN, URL_PATTERN, find_sensitive
from app.llm.base import LLMClient, LLMError, VisionEstimate
from app.models import EpistemicStatus, FactLedger, ProfileImage, RawProfile

log = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.6
MAX_OBSERVATIONS = 5
MAX_IMAGE_BYTES = 5_000_000
USER_AGENT = "FacebookProfilerAgent/0.1 (+TES-3808 test)"
EXTENSION_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
SUPPORTED_TYPES = frozenset(EXTENSION_TYPES.values())
HEDGE_PHRASES = ("appears to show", "appear to show", "có vẻ")

# Perceived demographic estimate: accepted only from an avatar showing exactly one person.
GENDER_MIN_CONFIDENCE = 0.7
AGE_MIN_CONFIDENCE = 0.6
AGE_MAX_WIDTH = 15
AGE_BOUNDS = (13, 90)

NO_IMAGE = "NOT_AVAILABLE: không có ảnh công khai nào được cung cấp"
IMAGE_KIND_VI = {"avatar": "ảnh đại diện", "cover": "ảnh bìa", "photo": "ảnh công khai"}

VISION_INSTRUCTIONS = """You describe a public social-media profile image for a customer-care profile.
Rules:
- Describe ONLY concrete things that are visible: objects, activities, setting, clothing style, text visible in the image.
- Write every observation in Vietnamese, starting with "Ảnh có vẻ cho thấy".
- If a person is visible, refer to them in Vietnamese as "một người" or "người này"; never use English phrases
  such as "a person". Do NOT state or guess gender, age, ethnicity, religion,
  health, body shape, sexual orientation, political views, relationships or family roles (e.g. never "mother", "couple").
- Do NOT guess the person's job, income, personality or life situation.
- Give at most 5 observations, each with a confidence between 0 and 1. Omit anything you are unsure about.
- If the image is blank, unreadable, a logo/default avatar, or shows nothing describable, set image_usable to false.

Required separate field "estimate" (never mention any of this in the observations):
- Always return the "estimate" key. Use null only when the image is unusable.
- If exactly one person's face/body is clearly visible as the main subject, set single_person_visible to true.
- For that person, estimate visible gender presentation as "female" or "male" only when reasonably clear;
  otherwise use "unclear". Give gender_confidence from 0 to 1.
- Give a rough apparent age_min/age_max range for that person, no wider than 15 years, only when visually
  estimable; otherwise set both to null and age_confidence to 0.
- If no single person is clearly visible, set single_person_visible to false, perceived_gender to "unclear",
  and age_min/age_max to null.
- These are uncertain visual impressions, not the person's actual gender identity or verified age. They must
  be labelled as INFERENCE downstream and must not be used to choose a form of address or personalize messages.
- Never infer ethnicity, religion, health, sexual orientation, political views, relationships or family roles."""


@dataclass(frozen=True)
class VisualContextResult:
    visual_context: str
    ledger: FactLedger
    fact_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    estimate_fact_ids: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        """True when a public image yielded a usable description (provided or accepted vision observations)."""
        return bool(self.fact_ids)


def extract_visual_context(
    raw: RawProfile | None,
    ledger: FactLedger,
    llm: LLMClient | None,
    *,
    base_dir: Path = PROJECT_ROOT,
    transport: httpx.BaseTransport | None = None,
) -> VisualContextResult:
    if raw is None or not raw.images:
        return VisualContextResult(NO_IMAGE, ledger)

    # Provided alt text (already in the ledger as visual_observation FACTs), screened for sensitive attributes.
    notes: list[str] = []
    alt_facts = [f for f in ledger.facts if f.category == "visual_observation" and f.source.endswith(".alt_text")]
    rejected = {f.id for f in alt_facts if find_sensitive(f.statement)}
    for fid in sorted(rejected):
        notes.append(f"{fid}: đã loại mô tả ảnh được cung cấp (chứa thuộc tính nhạy cảm).")
    ledger = without_facts(ledger, rejected)
    kept_alt = [f for f in alt_facts if f.id not in rejected]

    # One image for the vision model: needed for observations when no description is kept, and for the
    # perceived demographic estimate when an avatar file/URL is available.
    candidates = _undescribed_images(raw) if not kept_alt else _loadable_images(raw)
    image = candidates[0] if candidates else None
    vision = None
    vision_error: str | None = None
    if image is not None and llm is not None:
        try:
            data, media_type = _load_image(image, base_dir, transport)
            vision = llm.describe_image(image_bytes=data, media_type=media_type, instructions=VISION_INSTRUCTIONS)
        except _ImageError as exc:
            vision_error = str(exc)
        except LLMError as exc:
            vision_error = f"phân tích ảnh thất bại ({exc.kind})"

    estimate_ids: list[str] = []
    if vision is not None and vision.image_usable and vision.estimate is not None:
        ledger, estimate_ids, estimate_notes = _apply_estimate(ledger, vision.estimate, image.kind)
        notes += estimate_notes

    if kept_alt:
        if vision_error:
            notes.append(f"bỏ qua ước lượng từ ảnh: {vision_error}")
        text = "; ".join(f.statement for f in kept_alt)
        return VisualContextResult(
            f"MÔ TẢ ẢNH (từ dữ liệu được cung cấp): {text}", ledger, [f.id for f in kept_alt], notes, estimate_ids
        )

    if image is None:
        if rejected:
            return VisualContextResult(
                "NOT_AVAILABLE: mô tả ảnh được cung cấp chứa thuộc tính nhạy cảm nên bị loại", ledger, [], notes
            )
        return VisualContextResult(NO_IMAGE, ledger, [], notes)
    if llm is None:
        return VisualContextResult(
            "NOT_AVAILABLE: có ảnh công khai nhưng chưa cấu hình mô hình đọc ảnh (chế độ không dùng AI)", ledger, [], notes
        )
    if vision_error:
        return VisualContextResult(f"NOT_AVAILABLE: {vision_error}", ledger, [], notes)
    if not vision.image_usable:
        return VisualContextResult("NOT_AVAILABLE: ảnh không có nội dung mô tả được", ledger, [], notes)

    accepted: list[tuple[str, float]] = []
    for obs in vision.observations[:MAX_OBSERVATIONS]:
        text = _normalize_observation_text(obs.text.strip())
        reason = _rejection_reason(text, obs.confidence)
        if reason:
            notes.append(f"đã loại quan sát ảnh ({reason}).")
        else:
            accepted.append((text, obs.confidence))
    if not accepted:
        return VisualContextResult(
            "NOT_AVAILABLE: không có quan sát ảnh nào qua được kiểm tra", ledger, [], notes, estimate_ids
        )

    fact_ids = []
    for text, confidence in accepted:
        ledger, fact = append_fact(
            ledger,
            "visual_observation",
            text,
            f"vision:{image.kind}",
            epistemic_status=EpistemicStatus.INFERENCE,
            confidence=confidence,
        )
        fact_ids.append(fact.id)
    joined = "; ".join(text for text, _ in accepted)
    return VisualContextResult(
        f"QUAN SÁT ẢNH BẰNG AI ({IMAGE_KIND_VI.get(image.kind, image.kind)}; do mô hình tạo, chưa kiểm chứng): {joined}",
        ledger,
        fact_ids,
        notes,
        estimate_ids,
    )


def _apply_estimate(
    ledger: FactLedger, estimate: VisionEstimate, kind: str
) -> tuple[FactLedger, list[str], list[str]]:
    """Turn a perceived estimate into INFERENCE ledger entries when it clears every threshold."""
    notes: list[str] = []
    if kind != "avatar":
        return ledger, [], [f"bỏ qua ước lượng: lấy từ {IMAGE_KIND_VI.get(kind, kind)}, không phải ảnh đại diện"]
    if not estimate.single_person_visible:
        return ledger, [], ["bỏ qua ước lượng: ảnh không có đúng một người nhìn rõ"]
    source = f"vision:{kind}:estimate"
    ids: list[str] = []
    if estimate.perceived_gender != "unclear" and estimate.gender_confidence >= GENDER_MIN_CONFIDENCE:
        ledger, fact = append_fact(ledger, "perceived_gender", estimate.perceived_gender, source,
                                   EpistemicStatus.INFERENCE, estimate.gender_confidence)
        ids.append(fact.id)
    else:
        notes.append(f"bỏ qua ước lượng giới tính ({estimate.perceived_gender}, độ tin cậy {estimate.gender_confidence:.2f})")
    low, high = estimate.age_min, estimate.age_max
    if (
        low is not None
        and high is not None
        and AGE_BOUNDS[0] <= low <= high <= AGE_BOUNDS[1]
        and high - low <= AGE_MAX_WIDTH
        and estimate.age_confidence >= AGE_MIN_CONFIDENCE
    ):
        ledger, fact = append_fact(ledger, "perceived_age", f"{low}-{high}", source,
                                   EpistemicStatus.INFERENCE, estimate.age_confidence)
        ids.append(fact.id)
    else:
        notes.append(f"bỏ qua ước lượng độ tuổi ({low}-{high}, độ tin cậy {estimate.age_confidence:.2f})")
    return ledger, ids, notes


def _loadable_images(raw: RawProfile) -> list[ProfileImage]:
    """Images with a file or URL, avatar first, local files first."""
    return sorted(
        (img for img in raw.images if img.path or img.url),
        key=lambda img: (0 if img.kind == "avatar" else 1, 0 if img.path else 1),
    )


def _undescribed_images(raw: RawProfile) -> list[ProfileImage]:
    """Images without alt text, local files first, then provided/og URLs."""
    pending = [img for img in raw.images if not img.alt_text and (img.path or img.url)]
    return sorted(pending, key=lambda img: 0 if img.path else 1)


def _rejection_reason(text: str, confidence: float) -> str | None:
    if confidence < MIN_CONFIDENCE:
        return f"độ tin cậy {confidence:.2f} < {MIN_CONFIDENCE}"
    hits = find_sensitive(text)
    if hits:
        return "thuộc tính nhạy cảm: " + ", ".join(f"{cat}={term}" for cat, term in hits)
    if EMAIL_PATTERN.search(text) or PHONE_PATTERN.search(text) or URL_PATTERN.search(text):
        return "có thể chứa thông tin liên hệ hoặc URL"
    if not any(p in text.lower() for p in HEDGE_PHRASES):
        return "không viết dưới dạng quan sát ('có vẻ cho thấy ...')"
    return None


def _normalize_observation_text(text: str) -> str:
    """Keep common model-generated person references natural and Vietnamese."""
    text = re.sub(r"\bthe person\b", "người này", text, flags=re.IGNORECASE)
    text = re.sub(r"\ba person\b", "một người", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpeople\b", "mọi người", text, flags=re.IGNORECASE)
    return text


class _ImageError(Exception):
    pass


def _load_image(image: ProfileImage, base_dir: Path, transport: httpx.BaseTransport | None) -> tuple[bytes, str]:
    if image.path:
        path = Path(image.path)
        path = path if path.is_absolute() else base_dir / path
        media_type = EXTENSION_TYPES.get(path.suffix.lower())
        if media_type is None:
            raise _ImageError(f"định dạng file ảnh '{path.suffix}' không được hỗ trợ")
        try:
            data = path.read_bytes()
        except OSError:
            raise _ImageError("không đọc được file ảnh được cung cấp") from None
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise _ImageError("file ảnh được cung cấp trống hoặc quá lớn")
        return data, media_type

    # A single GET of a URL that was supplied with the data (or og:image); no crawling, no auth.
    try:
        with httpx.Client(transport=transport, timeout=15.0, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(image.url)
    except httpx.HTTPError as exc:
        raise _ImageError(f"không tải được ảnh từ URL ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise _ImageError(f"URL ảnh trả về HTTP {response.status_code}")
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in SUPPORTED_TYPES:
        raise _ImageError(f"URL ảnh trả về kiểu nội dung không hỗ trợ '{media_type or 'không rõ'}'")
    data = response.content
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise _ImageError("ảnh tải về trống hoặc quá lớn")
    return data, media_type
