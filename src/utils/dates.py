"""
Shared date normalization utility.

Used by both the News and Jobs verticals (and available to any future
source) since both share the exact same "24-hour freshness" requirement
and the same real-world variety of date formats: RFC 822 (RSS), ISO 8601
(Atom/JSON APIs), Unix epoch timestamps (some JSON job-board APIs), and
relative phrases like "2 hours ago" (sources with no structured date at
all).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Union

_RELATIVE_PATTERN = re.compile(
    r"(\d+)\s*(second|minute|hour|day)s?\s*ago", re.IGNORECASE
)


def parse_flexible_date(raw: Optional[Union[str, int, float]]) -> Optional[datetime]:
    """
    Normalize a publication date from any of several real-world formats:
      - RFC 822 (e.g. "Mon, 15 Sep 2026 10:00:00 GMT") -- standard RSS
      - ISO 8601 (e.g. "2026-09-15T10:00:00Z") -- standard Atom/JSON APIs
      - Unix epoch (int/float seconds, e.g. 1757930400) -- some JSON job
        board APIs (Arbeitnow, RemoteOK) return this instead of a string
      - Relative phrases (e.g. "2 hours ago") -- sources with no proper
        timestamp field at all

    Returns a timezone-aware UTC datetime, or None if missing/unparseable
    -- callers should treat None as "cannot verify freshness" and apply
    their own conservative heuristic (typically: exclude it) rather than
    assuming it's fresh.
    """
    if raw is None or raw == "":
        return None

    # Unix epoch (int or numeric string)
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    raw = str(raw).strip()
    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            pass

    # Relative phrase, e.g. "2 hours ago"
    m = _RELATIVE_PATTERN.search(raw)
    if m:
        amount, unit = int(m.group(1)), m.group(2).lower()
        return datetime.now(timezone.utc) - timedelta(**{f"{unit}s": amount})

    # RFC 822 (standard for RSS pubDate)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass

    # ISO 8601 (standard for Atom <published> / JSON APIs)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    return None


def is_within_last_24h(dt: Optional[datetime]) -> bool:
    """Conservative freshness check: None (unparseable/missing) is NOT fresh."""
    if dt is None:
        return False
    return dt >= datetime.now(timezone.utc) - timedelta(hours=24)

