# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Protect source publication boundaries and unchanged dependency notices."""

import importlib.util
import io
import tarfile
from pathlib import Path
from typing import Any


def release_tools() -> Any:
    """Load the source-only preparation utility without requiring a tools package."""
    path = Path(__file__).resolve().parents[1] / "tools/prepare_release.py"
    spec = importlib.util.spec_from_file_location("release_tools", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_checkout_excludes_acquisitions_caches_and_local_notes(
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
