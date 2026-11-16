"""Pure event model and selection logic (no I/O, no Qt)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Event:
    """A single calendar event, already normalised from the Google API format.

    ``start`` and ``end`` are always timezone-aware. For all-day events they
    are local midnights and ``all_day`` is True.
    """

    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    status: str = "confirmed"  # "confirmed" | "tentative" | "cancelled"
    response_status: str | None = None  # my RSVP: "accepted", "declined", ... or None
    calendar_id: str = ""
    calendar_name: str = ""
    calendar_color: str | None = None  # "#rrggbb"
    html_link: str | None = None
