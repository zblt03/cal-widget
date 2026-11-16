"""Build dist/cal-widget.exe with PyInstaller (run: python tools/build_exe.py).

The same script is used locally and by the GitHub Actions release job, so
both produce the same .exe. The result is a single windowed file: no console
window, and no Python installation needed on the user's machine.

Shared OAuth client: if the environment variable ``CAL_WIDGET_CLIENT_JSON``
holds the JSON of a Google OAuth client of type "Desktop app", it is packed
into the exe so users can sign in without any Google Cloud setup. Google
treats the secret of a desktop client as non-confidential, but it is still
kept out of the repository: CI fills the variable from a GitHub secret.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build"
BUNDLED_CLIENT_NAME = "bundled_client.json"  # must match cal_widget.paths

log = logging.getLogger("build_exe")


def write_bundled_client() -> Path | None:
    """Write the shared OAuth client from the environment to build/, if provided."""
    raw = os.environ.get("CAL_WIDGET_CLIENT_JSON", "").strip()
    if not raw:
        log.warning("CAL_WIDGET_CLIENT_JSON is not set: users will need their own credentials.json")
        return None
    data = json.loads(raw)
    if "installed" not in data:
        # A "Web application" client would fail at sign-in; stop the build instead.
        raise SystemExit("CAL_WIDGET_CLIENT_JSON must be an OAuth client of type 'Desktop app'")
    BUILD_DIR.mkdir(exist_ok=True)
    path = BUILD_DIR / BUNDLED_CLIENT_NAME  # build/ is git-ignored
    path.write_text(json.dumps(data), encoding="utf-8")
    log.info("Bundling the shared OAuth client")
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = [
        str(ROOT / "src" / "cal_widget" / "__main__.py"),
        "--name=cal-widget",
        "--onefile",
        "--windowed",
        f"--icon={ROOT / 'assets' / 'icon.ico'}",
        f"--paths={ROOT / 'src'}",  # so "import cal_widget" works
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={BUILD_DIR}",
        f"--specpath={BUILD_DIR}",  # keep the generated .spec out of the repo root
        "--noconfirm",
        "--clean",
    ]
    client = write_bundled_client()
    if client is not None:
        args.append(f"--add-data={client};.")  # unpacked next to the code at run time
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
