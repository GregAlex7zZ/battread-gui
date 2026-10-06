# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build one windowed launcher and a piped worker sharing bundled dependencies.

Run with the build extra installed: python -m PyInstaller packaging/windows.spec.
Only explicit resources and module dependencies are collected, never workspace
inputs, tests or private notes. Generated distribution assets are kept in dist.
"""

from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
resources = root / "src/battread_gui/resources"
metadata = []
for package in ("battread", "battread-gui", "galvani", "NewareNDA"):
    metadata += copy_metadata(package)

analysis = Analysis(
    [str(root / "packaging/gui_entry.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(resources), "battread_gui/resources")] + metadata,
    hiddenimports=["battread_gui.worker", "galvani.BioLogic", "NewareNDA"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "ruff", "pyright", "tkinter", "matplotlib", "IPython", "jupyter"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
# PyArrow's package-data hook includes its public test acquisitions by default.
# They are unnecessary for local conversion and do not belong in the binary ZIP.
analysis.datas = [
    entry for entry in analysis.datas if "tests" not in Path(entry[0]).parts
]
gui = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name="battread", console=False, debug=False, strip=False, upx=False,
    icon=str(resources / "battread.ico"),
    version=str(root / "packaging/version_info.txt"),
)
# The worker uses the same import archive and runtime hooks, but a different
# final entry script. It lives in _internal alongside DLLs, so its own content
# directory is '.' instead of the launcher's default '_internal'.
worker_scripts = analysis.scripts[:-1] + [
    ("worker_entry", str(root / "packaging/worker_entry.py"), "PYSOURCE")
]
worker = EXE(
    archive, worker_scripts, [], exclude_binaries=True,
    name="battread-worker", console=True, debug=False, strip=False, upx=False,
    contents_directory=".",
)
bundle = COLLECT(
    gui, analysis.binaries, analysis.datas,
    [("battread-worker.exe", worker.name, "BINARY")],
    strip=False, upx=False, name="battread",
)
