# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prepare reviewed source and Windows release assets without uploading anything.

Run after build_windows.py with exact upstream source archives in the private
dependency-sources cache. Source archives use an explicit allowlist. Binary
assets, runtime notices and corresponding source packages belong in Releases,
not in Git. No workspace acquisitions or saved notebook outputs are selected.
"""

import argparse
import hashlib
import importlib.metadata as metadata
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

RUNTIME_PACKAGES = (
    "battread",
    "battread-gui",
    "PySide6",
    "PySide6_Essentials",
    "shiboken6",
    "numpy",
    "pandas",
    "pyarrow",
    "psutil",
    "galvani",
    "NewareNDA",
    "python-dateutil",
    "six",
    "tzdata",
    "xmltodict",
    "PyInstaller",
)
ROOT_FILES = (
    "README.md",
    "LICENSE",
    "AUTHORS.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    "TODO.md",
    "pyproject.toml",
    ".gitignore",
    "requirements-build.txt",
    ".gitattributes",
    "launch.bat",
    "run.ps1",
)


def public_files(root: Path) -> list[Path]:
    """Select maintained code, original resources and notices, never arbitrary data."""
    files = {root / name for name in ROOT_FILES}
    for pattern in (
        "src/**/*.py",
        "tests/*.py",
        "tools/*.py",
        "packaging/*.py",
        "packaging/*.spec",
        "packaging/*.cs",
        "packaging/*.md",
        "packaging/version_info.txt",
        ".github/workflows/*.yml",
        "licenses/*.txt",
        "src/battread_gui/resources/*.svg",
        "src/battread_gui/resources/*.ico",
        "src/battread_gui/resources/GPL-3.0.txt",
    ):
        files.update(root.glob(pattern))
    if any(
        not path.is_file() or not path.resolve().is_relative_to(root) for path in files
    ):
        raise ValueError(
            "A required publication file is missing or outside the project."
        )
    return sorted(files)


def source_notices(archives: list[Path], destination: Path) -> None:
    """Copy upstream license/copyright texts using bounded sequential archive reads.

    Original paths and bytes are retained. No archive path is extracted blindly;
    parent traversal and non-regular members are rejected or ignored.
    """
    for archive_path in archives:
        label = archive_path.name.removesuffix(".tar.xz").removesuffix(".tar.gz")
        with tarfile.open(archive_path, "r|*") as archive:
            for member in archive:
                archive_path_parts = Path(member.name).parts
                parts = archive_path_parts[1:]
                if (
                    not member.isfile()
                    or not parts
                    or Path(member.name).is_absolute()
                    or ".." in archive_path_parts
                ):
                    continue
                if Path(parts[-1]).suffix.lower() in {
                    ".py",
                    ".c",
                    ".cc",
                    ".cpp",
                    ".h",
                    ".hpp",
                    ".ui",
                    ".qrc",
                }:
                    continue
                name = parts[-1].lower()
                if not any(
                    word in name
                    for word in ("license", "copying", "copyright", "notice")
                ) and not any(part.lower() == "licenses" for part in parts):
                    continue
                target = destination / "upstream-sources" / label / Path(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Missing upstream notice contents.")
                with stream, target.open("wb") as output:
                    shutil.copyfileobj(stream, output)


def runtime_notices(root: Path, bundle: Path, archives: list[Path]) -> None:
    """Retain installed runtime notices, Python terms and exact version provenance."""
    destination = bundle / "licenses"
    destination.mkdir(exist_ok=True)
    for path in (root / "licenses").glob("*.txt"):
        shutil.copyfile(path, destination / path.name)
    rows = ["# Bundled components", "", "| Component | Version |", "|---|---|"]
    for name in RUNTIME_PACKAGES:
        distribution = metadata.distribution(name)
        rows.append(f"| {name} | {distribution.version} |")
        for relative in distribution.files or ():
            parts = Path(str(relative)).parts
            if ".." in parts:
                continue
            basename = parts[-1].lower()
            if not any(
                word in basename
                for word in ("license", "copying", "notice", "copyright")
            ) and not any(part.lower() == "licenses" for part in parts):
                continue
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                target = destination / name / Path(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    shutil.copyfile(
        Path(sys.base_prefix) / "LICENSE.txt", destination / "Python-LICENSE.txt"
    )
    source_notices(archives, destination)
    (bundle / "BUNDLED_COMPONENTS.md").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    for name in ("LICENSE", "AUTHORS.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(root / name, bundle / name)
    # Editable-install metadata can contain machine-specific project paths.
    # Runtime version lookup needs METADATA, not direct_url.json or RECORD.
    for path in (bundle / "_internal").glob("*.dist-info/direct_url.json"):
        path.unlink()


def zip_tree(source: Path, destination: Path) -> None:
    """Write the complete portable folder without including external files."""
    with zipfile.ZipFile(
        destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                if not path.resolve().is_relative_to(source):
                    raise ValueError("Release content resolves outside its folder.")
                archive.write(path, source.name / path.relative_to(source))


def stage_sources(root: Path, destination: Path) -> None:
    """Stage reviewed sources without creating a second working checkout.

    The caller supplies a temporary directory and owns its cleanup. Git metadata,
    environments, caches and private acquisitions are never selected.
    """
    for path in public_files(root):
        target = destination / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def prepare(root: Path, library_source: Path) -> Path:
    """Build release assets from the working repositories, preserving private work.

    GUI sources are staged through the explicit allowlist in a temporary cache
    directory. No permanent second checkout is created or synchronized. The
    library uses its own source-distribution allowlist. Nothing is uploaded.
    """
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    qt_version = metadata.version("PySide6")
    dependency_source = root / ".cache/dependency-sources"
    names = [
        f"pyside-setup-everywhere-src-{qt_version}.tar.xz",
        f"qtbase-everywhere-src-{qt_version}.tar.xz",
        f"qtsvg-everywhere-src-{qt_version}.tar.xz",
        f"galvani-{metadata.version('galvani')}.tar.gz",
    ]
    archives = [dependency_source / name for name in names]
    if not all(path.is_file() for path in archives):
        raise FileNotFoundError("Exact dependency source archives are required.")
    bundle = root / "dist/battread"
    if (
        not (bundle / "battread.exe").is_file()
        or not (bundle / "_internal/battread-worker.exe").is_file()
    ):
        raise FileNotFoundError("Build the Windows application first.")
    runtime_notices(root, bundle, archives)
    (bundle / "README.md").write_text(
        "# battread GUI\n\nExtract the complete folder and run battread.exe. "
        "Keep _internal beside it. Python is not required.\n\n"
        "Use Help for conversion, merging, warnings and memory guidance. "
        "Original inputs are never changed.\n\n"
        "See LICENSE, THIRD_PARTY_NOTICES.md, licenses/ and SOURCES.md.\n",
        encoding="utf-8",
    )
    dist = root / "dist"
    with tempfile.TemporaryDirectory(
        prefix="release-source-", dir=root / ".cache"
    ) as temporary:
        staged = Path(temporary) / "battread-gui"
        stage_sources(root, staged)
        for project in (staged, library_source):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--sdist",
                    "--no-isolation",
                    "--outdir",
                    str(dist),
                    str(project),
                ],
                check=True,
            )
    library_version = metadata.version("battread")
    dependency_zip = dist / f"battread-gui-{version}-dependency-sources.zip"
    with zipfile.ZipFile(dependency_zip, "w", zipfile.ZIP_STORED) as archive:
        for path in archives:
            archive.write(path, path.name)
    (bundle / "SOURCES.md").write_text(
        "# Matching source packages\n\n"
        f"This release uses battread-gui {version} "
        f"and battread {library_version}.\n"
        "Publish these source assets beside the portable executable:\n\n"
        f"- battread_gui-{version}.tar.gz: app source and build recipes.\n"
        f"- battread-{library_version}.tar.gz: library source and notices.\n"
        f"- {dependency_zip.name}: exact unmodified Qt/PySide/Galvani sources.\n\n"
        "Qt/PySide source origin: https://download.qt.io/official_releases/QtForPython/pyside6/\n"
        "Qt module source origin: https://download.qt.io/official_releases/qt/\n"
        "Galvani source origin: https://pypi.org/project/galvani/\n\n"
        "Retain source access alongside each binary release. Qt DLLs are dynamically "
        "loaded; compatible modified replacements may be used. See build instructions "
        "and license texts in the source archives.\n",
        encoding="utf-8",
    )
    assets = [
        dependency_zip,
        dist / f"battread_gui-{version}.tar.gz",
        dist / f"battread-{library_version}.tar.gz",
    ]
    portable = dist / f"battread-gui-{version}-windows-x64-portable.exe"
    if portable.is_file():
        assets.append(portable)
    lines = []
    for path in assets:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(f"{digest}  {path.name}")
    (dist / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def main() -> None:
    """Parse the library-source location and report prepared paths, never upload."""
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-source", type=Path, default=root.parent / "battread")
    args = parser.parse_args()
    repository = prepare(root, args.library_source.resolve())
    print(f"Source repository: {repository}")
    print(f"Release assets: {root / 'dist'}")


if __name__ == "__main__":
    main()
