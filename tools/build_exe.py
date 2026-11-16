"""Build dist/cal-widget.exe with PyInstaller (run: python tools/build_exe.py).

The same script is used locally and by the GitHub Actions release job, so
both produce the same .exe. The result is a single windowed file: no console
window, and no Python installation needed on the user's machine.
credentials.json is deliberately NOT bundled; users supply their own.
"""

from __future__ import annotations

from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    PyInstaller.__main__.run(
        [
            str(ROOT / "src" / "cal_widget" / "__main__.py"),
            "--name=cal-widget",
            "--onefile",
            "--windowed",
            f"--icon={ROOT / 'assets' / 'icon.ico'}",
            f"--paths={ROOT / 'src'}",  # so "import cal_widget" works
            f"--distpath={ROOT / 'dist'}",
            f"--workpath={ROOT / 'build'}",
            f"--specpath={ROOT / 'build'}",  # keep the generated .spec out of the repo root
            "--noconfirm",
            "--clean",
        ]
    )


if __name__ == "__main__":
    main()
