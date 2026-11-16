"""Entry point: ``python -m cal_widget``."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from cal_widget import auth, calendar_client
from cal_widget.events import Event


def _format_event(event: Event) -> str:
    """One human-readable line for ``--dump``."""
    if event.all_day:
        when = f"{event.start:%a %d}  all day    "
    else:
        when = f"{event.start.astimezone():%a %d}  {event.start.astimezone():%H:%M}–{event.end.astimezone():%H:%M}"
    flags = []
    if event.status != "confirmed":
        flags.append(event.status)
    if event.response_status == "declined":
        flags.append("declined")
    suffix = f"  ({', '.join(flags)})" if flags else ""
    return f"{when}  {event.title}  [{event.calendar_name}]{suffix}"


def dump() -> int:
    """Log in if needed, then print the upcoming events as text."""
    try:
        creds = auth.get_credentials(allow_login=True)
    except auth.CredentialsMissingError as exc:
        print(exc, file=sys.stderr)
        return 1

    now = datetime.now().astimezone()
    events = calendar_client.fetch_events(creds, now)
    print(f"{len(events)} events from now until the end of tomorrow:\n")
    for event in events:
        print(_format_event(event))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, start the app and return a process exit code."""
    parser = argparse.ArgumentParser(
        prog="cal_widget",
        description="iOS-style Google Calendar widget for the Windows 11 taskbar.",
    )
    parser.add_argument(
        "--dump", action="store_true", help="print the upcoming events and exit (no UI)"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.dump:
        return dump()
    print("The widget UI arrives in Phase 4. Use --dump for now.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
