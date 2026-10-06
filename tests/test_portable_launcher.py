# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise the real launcher's bounded extraction with independent ZIP payloads."""

import os
import subprocess
import zipfile
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows .NET Framework launcher")
@pytest.mark.parametrize("member", ["battread/hello.txt", "../outside.txt"])
def test_launcher_extracts_only_inside_its_instance_root(
    tmp_path: Path, member: str
) -> None:
    """The actual C# extractor must stream valid content and reject parent traversal."""
    compiler = (
        Path(os.environ["SYSTEMROOT"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    )
    assert compiler.is_file()
    source = Path(__file__).resolve().parents[1] / "packaging/PortableLauncher.cs"
    payload = tmp_path / "payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, "synthetic content")
    library = tmp_path / "launcher.dll"
    result = subprocess.run(
        [
            str(compiler),
            "/nologo",
            "/target:library",
            "/reference:System.Windows.Forms.dll",
            "/reference:System.Drawing.dll",
            "/reference:System.IO.Compression.dll",
            f"/out:{library}",
            f"/resource:{payload},battread_payload",
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    harness = tmp_path / "Check.cs"
    harness.write_text(
        """// Invoke the real private extractor without starting a desktop window.
using System;
using System.IO;
using System.Reflection;
class Check {
    // Arguments: launcher assembly, new instance root, expected rejection.
    static int Main(string[] args) {
        Directory.CreateDirectory(args[1]);
        var method = Assembly.LoadFrom(args[0]).GetType("PortableLauncher")
            .GetMethod("ExtractPayload", BindingFlags.Static | BindingFlags.NonPublic);
        try {
            method.Invoke(null, new object[] { args[1] });
            return args[2] == "reject" ? 1 : 0;
        } catch (TargetInvocationException error) {
            return args[2] == "reject" && error.InnerException is IOException ? 0 : 2;
        }
    }
}
""",
        encoding="utf-8",
    )
    helper = tmp_path / "Check.exe"
    subprocess.run(
        [str(compiler), "/nologo", f"/out:{helper}", str(harness)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    destination = tmp_path / "instance"
    result = subprocess.run(
        [
            str(helper),
            str(library),
            str(destination),
            "reject" if member.startswith("..") else "accept",
        ],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert not (tmp_path / "outside.txt").exists()
    if not member.startswith(".."):
        assert (destination / member).read_text() == "synthetic content"
