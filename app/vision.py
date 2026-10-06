"""Visual context extraction (FR-007, architecture.md §5.1).

Two paths:
- Provided `alt_text` (a description supplied with the data): used as-is, no AI call. Ledger status FACT.
- No alt text: one image is described by the vision model. Observations are model-generated, so they are
  stored as INFERENCE with their confidence: they appear in `visual_context` but are never used to ground
  rapport messages or demographics.
Every description is screened for sensitive attributes. Any failure yields `NOT_AVAILABLE: <reason>`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import PROJECT_ROOT
from app.ledger import append_fact, without_facts
from app.lexicons import find_sensitive
from app.llm.base import LLMClient, LLMError
from app.models import EpistemicStatus, FactLedger, ProfileImage, RawProfile

log = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.6
MAX_OBSERVATIONS = 5
MAX_IMAGE_BYTES = 5_000_000
USER_AGENT = "FacebookProfilerAgent/0.1 (+TES-3808 test)"
EXTENSION_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
SUPPORTED_TYPES = frozenset(EXTENSION_TYPES.values())
HEDGE_PHRASES = ("appears to show", "appear to show", "có vẻ")

NO_IMAGE = "NOT_AVAILABLE: no public image provided"

VISION_INSTRUCTIONS = """You describe a public social-media profile image for a customer-care profile.
Rules:
- Describe ONLY concrete things that are visible: objects, activities, setting, clothing style, text visible in the image.
- Every observation MUST start with "appears to show".
- Refer to any person only as "a person" or "people". Do NOT state or guess gender, age, ethnicity, religion,
  health, body shape, sexual orientation, political views, relationships or family roles (e.g. never "mother", "couple").
- Do NOT guess the person's job, income, personality or life situation.
- Give at most 5 observations, each with a confidence between 0 and 1. Omit anything you are unsure about.
- If the image is blank, unreadable, a logo/default avatar, or shows nothing describable, set image_usable to false."""


@dataclass(frozen=True)
class VisualContextResult:
    visual_context: str
    ledger: FactLedger
    fact_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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

    # Path 1: provided alt text (already in the ledger as visual_observation FACTs).
    alt_facts = [f for f in ledger.facts if f.category == "visual_observation" and f.source.endswith(".alt_text")]
    if alt_facts:
        notes: list[str] = []
        rejected = {f.id for f in alt_facts if find_sensitive(f.statement)}
        for fid in sorted(rejected):
            notes.append(f"{fid}: provided image description removed (sensitive attribute).")
        ledger = without_facts(ledger, rejected)
        kept = [f for f in alt_facts if f.id not in rejected]
        if kept:
            text = "; ".join(f.statement for f in kept)
            return VisualContextResult(
                f"PROVIDED IMAGE DESCRIPTION: {text}", ledger, [f.id for f in kept], notes
            )
        if not _undescribed_images(raw):
            return VisualContextResult(
                "NOT_AVAILABLE: provided image description failed the sensitive-attribute check", ledger, [], notes
            )

    # Path 2: describe one image with the vision model.
    candidates = _undescribed_images(raw)
    if not candidates:
        return VisualContextResult(NO_IMAGE, ledger)
    image = candidates[0]
    if llm is None:
        return VisualContextResult(
            "NOT_AVAILABLE: a public image exists but no vision model is configured (deterministic mode)", ledger
        )

    try:
        data, media_type = _load_image(image, base_dir, transport)
    except _ImageError as exc:
        return VisualContextResult(f"NOT_AVAILABLE: {exc}", ledger)

    try:
        result = llm.describe_image(image_bytes=data, media_type=media_type, instructions=VISION_INSTRUCTIONS)
    except LLMError as exc:
        return VisualContextResult(f"NOT_AVAILABLE: vision analysis failed ({exc.kind})", ledger)
    if not result.image_usable:
        return VisualContextResult("NOT_AVAILABLE: the image shows nothing describable", ledger)

    notes = []
    accepted: list[tuple[str, float]] = []
    for obs in result.observations[:MAX_OBSERVATIONS]:
        reason = _rejection_reason(obs.text, obs.confidence)
        if reason:
            notes.append(f"vision observation rejected ({reason}): {obs.text!r}")
        else:
            accepted.append((obs.text.strip(), obs.confidence))
    if not accepted:
        return VisualContextResult("NOT_AVAILABLE: no image observation passed validation", ledger, [], notes)

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
        f"AI VISUAL OBSERVATION ({image.kind} image, model-generated, unverified): {joined}", ledger, fact_ids, notes
    )


def _undescribed_images(raw: RawProfile) -> list[ProfileImage]:
    """Images without alt text, local files first, then provided/og URLs."""
    pending = [img for img in raw.images if not img.alt_text and (img.path or img.url)]
    return sorted(pending, key=lambda img: 0 if img.path else 1)


def _rejection_reason(text: str, confidence: float) -> str | None:
    if confidence < MIN_CONFIDENCE:
        return f"confidence {confidence:.2f} < {MIN_CONFIDENCE}"
    hits = find_sensitive(text)
    if hits:
        return "sensitive attribute: " + ", ".join(f"{cat}={term}" for cat, term in hits)
    if not any(p in text.lower() for p in HEDGE_PHRASES):
        return "not phrased as an observation ('appears to show ...')"
    return None


class _ImageError(Exception):
    pass


def _load_image(image: ProfileImage, base_dir: Path, transport: httpx.BaseTransport | None) -> tuple[bytes, str]:
    if image.path:
        path = Path(image.path)
        path = path if path.is_absolute() else base_dir / path
        media_type = EXTENSION_TYPES.get(path.suffix.lower())
        if media_type is None:
            raise _ImageError(f"unsupported image file type '{path.suffix}'")
        try:
            data = path.read_bytes()
        except OSError:
            raise _ImageError("the provided image file could not be read") from None
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise _ImageError("the provided image file is empty or too large")
        return data, media_type

    # A single GET of a URL that was supplied with the data (or og:image); no crawling, no auth.
    try:
        with httpx.Client(transport=transport, timeout=15.0, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(image.url)
    except httpx.HTTPError as exc:
        raise _ImageError(f"the image URL could not be fetched ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise _ImageError(f"the image URL returned HTTP {response.status_code}")
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in SUPPORTED_TYPES:
        raise _ImageError(f"the image URL returned unsupported content type '{media_type or 'unknown'}'")
    data = response.content
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise _ImageError("the downloaded image is empty or too large")
    return data, media_type
