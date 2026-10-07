# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Protect source publication boundaries and unchanged dependency notices."""

import importlib.util
import io
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest


def release_tools() -> Any:
    """Load the source-only preparation utility without requiring a tools package."""
    path = Path(__file__).resolve().parents[1] / "tools/prepare_release.py"
    spec = importlib.util.spec_from_file_location("release_tools", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_staging_excludes_acquisitions_caches_and_local_notes(
    tmp_path: Path,
) -> None:
    """Only maintained source files are public, even when private data sits nearby."""
    tool = release_tools()
    for name in tool.ROOT_FILES:
        (tmp_path / name).write_text("Synthetic public source.\n", encoding="utf-8")
    for relative in ("private.csv", "demo.ipynb", "AGENTS.md", ".cache/output.txt"):
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text("Synthetic private content.\n", encoding="utf-8")
    selected = {p.relative_to(tmp_path).as_posix() for p in tool.public_files(tmp_path)}
    assert "README.md" in selected
    assert (
        not {"private.csv", "demo.ipynb", "AGENTS.md", ".cache/output.txt"} & selected
    )
    destination = tmp_path / ".cache/release-source-staging/battread-gui"
    tool.stage_sources(tmp_path, destination)
    copied = {
        p.relative_to(destination).as_posix()
        for p in destination.rglob("*")
        if p.is_file()
    }
    assert copied == selected
    assert not (tmp_path.parent / "battread-gui-github").exists()


def test_upstream_notices_keep_bytes_and_reject_traversal_and_example_code(
    tmp_path: Path,
) -> None:
    """License extraction retains terms without importing demos or unsafe paths."""
    archive_path = tmp_path / "source.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in (
            "upstream/LICENSES/LGPL.txt",
            "../COPYING.txt",
            "upstream/licensewizard.py",
        ):
            content = b"Synthetic original notice.\r\n"
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    destination = tmp_path / "notices"
    release_tools().source_notices([archive_path], destination)
    files = list(destination.rglob("*"))
    assert [p.relative_to(destination).as_posix() for p in files if p.is_file()] == [
        "upstream-sources/source/LICENSES/LGPL.txt"
    ]
    assert (
        destination / "upstream-sources/source/LICENSES/LGPL.txt"
    ).read_bytes() == b"Synthetic original notice.\r\n"


@pytest.mark.parametrize("build_fails", [False, True])
def test_release_preparation_does_not_create_another_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, build_fails: bool
) -> None:
    """Staging cleans up after success or failure and preserves Git metadata."""
    tool = release_tools()
    root = tmp_path / "battread-gui"
    root.mkdir()
    for name in tool.ROOT_FILES:
        (root / name).write_text("Synthetic public source.\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
    git_config = root / ".git/config"
    git_config.parent.mkdir()
    git_config.write_text("Synthetic local Git configuration.\n")
    cache = root / ".cache/dependency-sources"
    cache.mkdir(parents=True)
    for name in (
        "pyside-setup-everywhere-src-6.11.2.tar.xz",
        "qtbase-everywhere-src-6.11.2.tar.xz",
        "qtsvg-everywhere-src-6.11.2.tar.xz",
        "galvani-0.5.0.tar.gz",
    ):
        (cache / name).write_bytes(b"Synthetic source archive.")
    bundle = root / "dist/battread"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "battread.exe").write_bytes(b"Synthetic executable.")
    (bundle / "_internal/battread-worker.exe").write_bytes(b"Synthetic worker.")
    for package in ("battread", "battread-gui"):
        details = bundle / "_internal" / f"{package}-0.1.0.dist-info" / "METADATA"
        details.parent.mkdir()
        details.write_text(f"Name: {package}\nVersion: 0.1.0\n")
    library = tmp_path / "battread"
    library.mkdir()
    versions = {"PySide6": "6.11.2", "galvani": "0.5.0", "battread": "0.1.0"}
    monkeypatch.setattr(tool.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(tool, "runtime_notices", lambda *args: None)
    build_projects: list[Path] = []

    def build(command: list[str], **kwargs: object) -> None:
        """Inspect selected sources without installing or compiling dependencies."""
        project = Path(command[-1])
        build_projects.append(project)
        if project.name == "battread-gui":
            assert project != root
            assert not (project / ".git").exists()
            assert not (project / ".cache").exists()
        if build_fails:
            raise subprocess.CalledProcessError(1, command)
        output = Path(command[command.index("--outdir") + 1])
        name = "battread_gui" if project.name == "battread-gui" else "battread"
        (output / f"{name}-0.1.0.tar.gz").write_bytes(b"Synthetic built source.")

    monkeypatch.setattr(tool.subprocess, "run", build)
    if build_fails:
        with pytest.raises(subprocess.CalledProcessError):
            tool.prepare(root, library)
    else:
        assert tool.prepare(root, library) == root
        assert build_projects[-1] == library
        assert not list((root / "dist").glob("*-windows-x64.zip"))
    assert not list((root / ".cache").glob("release-source-*"))
    assert not (tmp_path / "battread-gui-github").exists()
    assert git_config.read_text() == "Synthetic local Git configuration.\n"


def test_release_refuses_stale_or_missing_compiled_versions(tmp_path):
    """New source archives must not masquerade as an old compiled app release."""
    tool = release_tools()
    with pytest.raises(ValueError, match="Rebuild"):
        tool.validate_bundle_versions(tmp_path, "0.1.2", "0.1.2")
    for package in ("battread", "battread-gui"):
        details = tmp_path / "_internal" / f"{package}-0.1.1.dist-info" / "METADATA"
        details.parent.mkdir(parents=True)
        details.write_text(f"Name: {package}\nVersion: 0.1.1\n")
    with pytest.raises(ValueError, match="Rebuild"):
        tool.validate_bundle_versions(tmp_path, "0.1.2", "0.1.2")
    tool.validate_bundle_versions(tmp_path, "0.1.1", "0.1.1")
