"""Profile source protocol and the acquisition chain (architecture.md §7.3, plan.md §5.1)."""

from __future__ import annotations

from typing import Iterable, Protocol

from app.input import CanonicalUrl
from app.models import READABLE_STATES, AccessState, AcquisitionResult, RawProfile

SYNTHETIC_NOTE = "Persona thử nghiệm giả lập: dữ liệu là hư cấu, không thu thập từ Facebook."

NO_DATA_LIMITATION = (
    "TECHNICAL LIMITATION: Không có dữ liệu truy cập hợp lệ cho trang cá nhân này. Facebook yêu cầu đăng nhập "
    "để xem gần như toàn bộ nội dung trang cá nhân, và agent không đăng nhập hay vượt qua cơ chế kiểm soát truy cập. "
    "Hãy cung cấp dữ liệu qua --profile-file, hoặc bật chế độ đọc metadata công khai --live."
)


class SourceError(Exception):
    """Provided profile data could not be used (unreadable, malformed or inconsistent)."""


class ProfileSource(Protocol):
    name: str

    def acquire(self, url: CanonicalUrl) -> AcquisitionResult | None:
        """Return a result for this profile, or None when this source has nothing for it."""
        ...


def result_from_raw(raw: RawProfile, url: CanonicalUrl, source_name: str) -> AcquisitionResult:
    """Wrap provided data, honouring its declared access state."""
    state = raw.access.state
    limitations: list[str] = []
    if raw.synthetic:
        limitations.append(SYNTHETIC_NOTE)
    if raw.access.note:
        limitations.append(raw.access.note)
    return AcquisitionResult(
        canonical_url=url.url,
        access_state=state,
        # Profile fields are only passed on when access is readable.
        raw=raw if state in READABLE_STATES else None,
        source_name=source_name,
        synthetic=raw.synthetic,
        limitations=limitations,
    )


def acquire_from_chain(sources: Iterable[ProfileSource], url: CanonicalUrl) -> AcquisitionResult:
    """First source returning a result wins; no result at all means NO_ACCESSIBLE_DATA."""
    for source in sources:
        result = source.acquire(url)
        if result is not None:
            return result
    return AcquisitionResult(
        canonical_url=url.url,
        access_state=AccessState.NO_ACCESSIBLE_DATA,
        source_name="none",
        limitations=[NO_DATA_LIMITATION],
    )
