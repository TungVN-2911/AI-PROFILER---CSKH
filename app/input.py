"""Validation and canonicalization of Facebook profile URLs (FR-002).

Canonical forms:
    https://www.facebook.com/<username>            (username lowercased)
    https://www.facebook.com/profile.php?id=<id>   (numeric id)
Tracking parameters, fragments, trailing slashes and known profile sub-pages are dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit

CANONICAL_BASE = "https://www.facebook.com"

ALLOWED_HOSTS = frozenset(
    {"facebook.com", "www.facebook.com", "m.facebook.com", "mbasic.facebook.com", "web.facebook.com"}
)

# First path segments that are Facebook features, not profiles.
RESERVED_SEGMENTS = frozenset(
    {
        "ads", "apps", "bookmarks", "business", "checkpoint", "dialog", "events", "friends",
        "fundraisers", "gaming", "games", "groups", "hashtag", "help", "home.php", "jobs", "l.php",
        "legal", "live", "login", "login.php", "logout.php", "marketplace", "media", "messages",
        "news", "notes", "notifications", "pages", "permalink.php", "photo", "photo.php", "photos",
        "places", "plugins", "policies", "privacy", "recover", "reel", "reels", "saved", "search",
        "settings", "share", "sharer", "sharer.php", "story.php", "stories", "tr", "video.php",
        "videos", "watch",
    }
)

# Profile sub-pages that still identify the same profile; they are stripped.
PROFILE_SUBPAGES = frozenset({"about", "photos", "friends", "posts", "videos", "reels", "followers"})

USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._\-]{0,48}[A-Za-z0-9])?$")
PROFILE_ID_RE = re.compile(r"^\d{1,20}$")


class InputError(ValueError):
    """The input is not a usable Facebook profile URL."""

    def __init__(self, reason: str, raw: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw = raw or ""

    @property
    def error_note(self) -> str:
        return f"INVALID_INPUT: {self.reason}"


@dataclass(frozen=True)
class CanonicalUrl:
    url: str
    kind: Literal["username", "profile_id"]
    identifier: str
    original: str


def validate_profile_url(raw: str | None) -> CanonicalUrl:
    """Return the canonical profile URL or raise InputError with a human-readable reason."""
    if raw is None or not raw.strip():
        raise InputError("a Facebook profile URL is required (--url)", raw)
    text = raw.strip()

    if "://" not in text:
        # Allow scheme-less input such as "facebook.com/username".
        if not text.lower().startswith(tuple(ALLOWED_HOSTS)):
            raise InputError("not a URL: expected https://www.facebook.com/<username>", raw)
        text = "https://" + text

    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise InputError("malformed URL", raw) from None

    if parts.scheme.lower() not in {"http", "https"}:
        raise InputError(f"unsupported URL scheme '{parts.scheme}'", raw)
    if parts.username is not None or parts.password is not None:
        raise InputError("URLs with embedded credentials are not accepted", raw)
    if port is not None:
        raise InputError("URLs with an explicit port are not accepted", raw)
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in ALLOWED_HOSTS:
        raise InputError(f"host '{host or '(none)'}' is not facebook.com", raw)

    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        raise InputError("URL does not point to a profile (no username or id)", raw)

    first = segments[0].lower()
    if first == "profile.php":
        ids = parse_qs(parts.query).get("id", [])
        if len(ids) != 1 or not PROFILE_ID_RE.match(ids[0]):
            raise InputError("profile.php URL must contain a numeric ?id=", raw)
        return _profile_id(ids[0], raw)

    if first == "people":
        # /people/<Display-Name>/<numeric id>
        if len(segments) >= 3 and PROFILE_ID_RE.match(segments[2]):
            return _profile_id(segments[2], raw)
        raise InputError("/people/ URL must end with a numeric profile id", raw)

    if first in RESERVED_SEGMENTS:
        raise InputError(f"'/{segments[0]}' is not a personal profile URL", raw)
    if not USERNAME_RE.match(segments[0]):
        raise InputError(f"'{segments[0]}' is not a valid Facebook username", raw)
    extra = [s.lower() for s in segments[1:]]
    if extra and (len(extra) > 1 or extra[0] not in PROFILE_SUBPAGES):
        raise InputError(f"'/{'/'.join(segments)}' is not a profile URL", raw)

    username = first
    return CanonicalUrl(url=f"{CANONICAL_BASE}/{username}", kind="username", identifier=username, original=raw)


def _profile_id(profile_id: str, raw: str) -> CanonicalUrl:
    return CanonicalUrl(
        url=f"{CANONICAL_BASE}/profile.php?id={profile_id}",
        kind="profile_id",
        identifier=profile_id,
        original=raw,
    )
