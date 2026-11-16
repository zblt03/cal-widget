# cal-widget — conventions for Claude

iOS-lock-screen-style Google Calendar widget for the left side of the Windows 11 taskbar.
Owner: Nacho (GitHub `zblt03`), IB CS HL student. Code must be readable and explainable by a strong student:
clear module boundaries, type hints, docstrings, no clever tricks.

## Workflow
- Work phase by phase; at each ⏸ checkpoint stop and say exactly what to test. Wait for confirmation.
- Before marking a phase done: run tests (`.venv\Scripts\python -m pytest`), run the app if relevant, check `git status`.

## Git rules
- Commit and push after every working step. Conventional Commits in English (feat:, fix:, test:, docs:, refactor:, chore:, ci:).
- One logical change per commit; explain the *why* when not obvious.
- Run `git status` before every commit. `credentials.json` and `token.json` must NEVER be committed.
- Never force-push, rewrite history, or delete files without asking first.

## Conventions
- Python: the locally installed interpreter (3.14) — CI uses the same version. Type hints everywhere, docstrings on public functions.
- `logging`, never `print` — except the `--dump` CLI output.
- All code, comments, commits and docs in English.
- Dependencies limited to: PySide6, google-api-python-client, google-auth-oauthlib, google-auth-httplib2, pytest, pyinstaller (pinned in requirements.txt).
- Never log or print OAuth tokens. Scope is `calendar.readonly` only.
- Runtime files (token.json, events.cache.json, config.json, log) live in `%LOCALAPPDATA%\cal-widget\`, never in the repo.

## Layout
- `src/cal_widget/` — `__main__` (CLI/wiring), `paths`, `config`, `auth`, `calendar_client`, `events` (pure logic, no I/O), `taskbar` (Win32 via ctypes), `ui` (PySide6 view only: draws, emits signals), `app` (controller: state, background fetch thread, timers).
- `tests/` — pytest; `events.select_event` must stay pure and fully tested.

## Widget look
- Line 1: time range (13 px). Line 2: event title (12 px). Both regular weight — no bold (user's choice,
  overrides the brief's "bold time").
- Default mode: embedded *inside* the taskbar (SetParent into `Shell_TrayWnd`), painted opaquely on a
  colour key because Qt's per-pixel alpha stops repainting there. Never resize/move it through Qt once
  embedded; place it with Win32. `--overlay` (and automatic fallback) = topmost window over the taskbar.

## Display rules (select_event)
- Ignore all-day, cancelled, and declined events.
- Ongoing → most recently started; else next today; else tomorrow's first as `Tomorrow · HH:MM–HH:MM`; else "No events".
- 24-hour times, en dash (–) between times. Timezone-aware comparisons; user tz Europe/Madrid.
