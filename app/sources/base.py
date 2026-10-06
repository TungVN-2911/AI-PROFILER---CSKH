"""Profile source protocol and the acquisition chain (architecture.md §7.3, plan.md §5.1)."""

from __future__ import annotations

from typing import Iterable, Protocol

from app.input import CanonicalUrl
from app.models import READABLE_STATES, AccessState, AcquisitionResult, RawProfile

SYNTHETIC_NOTE = "Synthetic test persona: data is fictional, not collected from Facebook."

NO_DATA_LIMITATION = (
    "TECHNICAL LIMITATION: no legitimately accessible data for this profile. Facebook requires login for "
    "nearly all profile content and this agent does not log in or bypass access controls. Provide the "
    "profile data with --profile-file, or enable the opt-in public meta fetch with --live."
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
