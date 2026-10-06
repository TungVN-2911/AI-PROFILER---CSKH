"""Sources for legitimately provided profile data: an explicit --profile-file, or a local store."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.input import CanonicalUrl, InputError, validate_profile_url
from app.models import AcquisitionResult, RawProfile
from app.sources.base import SourceError, result_from_raw

log = logging.getLogger(__name__)


def load_raw_profile(path: Path) -> RawProfile:
    """Read and validate one profile JSON file; raise SourceError with a readable reason."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SourceError(f"không đọc được file dữ liệu '{path}': {exc.strerror or exc}") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(f"file dữ liệu '{path}' không phải JSON hợp lệ (dòng {exc.lineno}: {exc.msg})") from None
    try:
        return RawProfile.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}" for err in exc.errors()[:5]
        )
        raise SourceError(f"file dữ liệu '{path}' không đúng định dạng profile: {problems}") from None


def _canonical_of(raw: RawProfile, path: Path) -> CanonicalUrl:
    try:
        return validate_profile_url(raw.facebook_url)
    except InputError as exc:
        raise SourceError(f"file dữ liệu '{path}' có facebook_url không hợp lệ: {exc.reason}") from None


class ProvidedFileSource:
    """Profile data passed explicitly with --profile-file."""

    name = "profile_file"

    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire(self, url: CanonicalUrl) -> AcquisitionResult:
        raw = load_raw_profile(self.path)
        if _canonical_of(raw, self.path).url != url.url:
            # Using another person's data for this URL would be fabrication.
            raise SourceError(
                f"file dữ liệu '{self.path}' là của {raw.facebook_url}, không khớp với --url {url.url}"
            )
        return result_from_raw(raw, url, self.name)


class FixtureStoreSource:
    """Directory of provided profile JSON files, matched by canonical facebook_url."""

    name = "profile_store"

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.load_errors: list[str] = []
        self._index: dict[str, RawProfile] | None = None

    def _build_index(self) -> dict[str, RawProfile]:
        index: dict[str, RawProfile] = {}
        if not self.directory.is_dir():
            self.load_errors.append(f"thư mục dữ liệu '{self.directory}' không tồn tại")
            return index
        for path in sorted(self.directory.glob("*.json")):
            try:
                raw = load_raw_profile(path)
                key = _canonical_of(raw, path).url
            except SourceError as exc:
                # A broken file must not prevent other profiles from loading.
                self.load_errors.append(str(exc))
                log.warning("skipping profile store file: %s", exc)
                continue
            if key in index:
                self.load_errors.append(f"trùng dữ liệu cho {key} trong '{path}' (bỏ qua)")
                log.warning("duplicate profile for %s in %s (ignored)", key, path)
                continue
            index[key] = raw
        return index

    def acquire(self, url: CanonicalUrl) -> AcquisitionResult | None:
        if self._index is None:
            self._index = self._build_index()
        raw = self._index.get(url.url)
        return None if raw is None else result_from_raw(raw, url, self.name)
