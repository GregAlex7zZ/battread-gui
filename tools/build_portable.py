# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Embed the reviewed folder in a small Windows desktop launcher.

Run after build_windows.py and prepare_release.py. The .NET Framework compiler
builds a launcher whose first window precedes background extraction. Only the
licensed folder release is embedded; no workspace inputs are selected.
"""

import os
import subprocess
from pathlib import Path


def main() -> None:
    """Compress the reviewed app and compile its windowed single-file launcher."""
    if os.name != "nt":
        raise SystemExit("Build the Windows application on Windows.")
    from prepare_release import zip_tree

    root = Path(__file__).resolve().parents[1]
    bundle = root / "dist/battread"
    if not (bundle / "SOURCES.md").is_file():
        raise SystemExit("Run build_windows.py and prepare_release.py first.")
    compiler = (
        Path(os.environ["SYSTEMROOT"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    )
    if not compiler.is_file():
        raise SystemExit("The Windows .NET Framework C# compiler is required.")
    payload = root / ".cache/portable-payload.zip"
    payload.parent.mkdir(exist_ok=True)
    zip_tree(bundle, payload)
    subprocess.run(
        [
            str(compiler),
            "/nologo",
            "/target:winexe",
            "/platform:x64",
            "/optimize+",
            "/reference:System.Windows.Forms.dll",
            "/reference:System.Drawing.dll",
            "/reference:System.IO.Compression.dll",
            f"/resource:{payload},battread_payload",
            f"/win32icon:{root / 'src/battread_gui/resources/battread.ico'}",
            f"/out:{root / 'dist/battread-gui-0.1.0-windows-x64-portable.exe'}",
            str(root / "packaging/PortableLauncher.cs"),
        ],
        cwd=root,
        check=True,
    )


if __name__ == "__main__":
    main()
