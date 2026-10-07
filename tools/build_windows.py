# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build the reproducible onedir application; packaging never publishes assets.

Run on Windows with the build extra and the current battread optional readers
installed. The script rebuilds the icon and invokes the reviewed PyInstaller
specification. Keep all files in dist/battread together when distributing.
"""

import os
import subprocess
import sys
import tomllib
from pathlib import Path


def main() -> None:
    """Build on Windows using the active interpreter and explicit resource inputs."""
    if os.name != "nt":
        raise SystemExit("Build the Windows application on Windows.")
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    subprocess.run([sys.executable, str(root / "tools/make_icon.py")], check=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--workpath",
            str(root / f".cache/windows-build-{version}"),
            str(root / "packaging/windows.spec"),
        ],
        cwd=root,
        check=True,
    )


if __name__ == "__main__":
    main()
