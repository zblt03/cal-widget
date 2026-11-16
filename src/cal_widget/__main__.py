"""Entry point: ``python -m cal_widget``."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from types import TracebackType

from cal_widget import __version__, auth, calendar_client, paths
from cal_widget.config import load_config
from cal_widget.events import Event, select_event
from cal_widget.single_instance import SingleInstance

log = logging.getLogger("cal_widget")

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3


def _log_uncaught(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> None:
    """Send otherwise-silent crashes (there is no console under pythonw) to the log."""
    log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))


def _log_uncaught_in_thread(args: threading.ExceptHookArgs) -> None:
    """Same as :func:`_log_uncaught`, for exceptions in background threads."""
    log.critical(
        "Uncaught exception in thread %s",
        args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def setup_logging(to_file: bool) -> None:
    """Log to a rotating file in %LOCALAPPDATA%\\cal-widget and, if present, the console."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if to_file:
        handler = RotatingFileHandler(
            paths.log_path(), maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
    if sys.stderr is not None:  # None when started with pythonw / as a windowed .exe
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(console)
    # Third-party libraries are chatty at INFO; we only want their problems.
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)

    sys.excepthook = _log_uncaught
    threading.excepthook = _log_uncaught_in_thread


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

    config = load_config(paths.config_path())
    now = datetime.now().astimezone()
    events = calendar_client.fetch_events(creds, now, config.excluded_calendars)
    print(f"{len(events)} events from now until the end of tomorrow:\n")
    for event in events:
        print(_format_event(event))

    display = select_event(events, now, config.show_tomorrow)
    print(f"\nThe widget would show:\n  ▌{display.time_text}\n  ▌{display.title}")
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
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="float over the taskbar instead of living inside it",
    )
    args = parser.parse_args(argv)

    setup_logging(to_file=not args.dump)

    if args.dump:
        return dump()

    instance = SingleInstance()
    if instance.already_running:
        log.info("Another cal-widget is already running; exiting")
        return 0

    from cal_widget.app import run  # imported here so --dump doesn't load Qt

    log.info("cal-widget %s starting", __version__)
    return run(embed=not args.overlay)


if __name__ == "__main__":
    raise SystemExit(main())
