# battread GUI

A Windows desktop app for converting local electrochemical cycling files with
[battread](https://github.com/GregAlex7zZ/battread).

## Use the Windows app

Download the **portable EXE** from Releases and open it. No installation or
Python is required. A "Starting battread..." panel appears while the app extracts
its libraries into a temporary folder. They are removed on normal exit. Allow
enough space on the temporary drive; startup speed depends on disk and antivirus.
The app works locally and uploads no files.

The portable launcher uses the .NET Framework included with Windows 10/11.

Alternatively, extract the Windows ZIP and open `battread.exe`. Keep `_internal`
beside it. This version avoids extraction on each launch and allows replacement
of compatible Qt DLLs, including modified builds.

1. Choose **Add files**.
2. Leave files separate, or enable **Merge files** and choose their order.
3. Keep the original names or edit **Save as**; choose the destination folder.
4. Click **Process**. Existing output names receive `(2)`, `(3)`, etc.

Orange messages are non-blocking warnings, green messages confirm saved files,
and red messages indicate errors. Review warnings and compare converted data
with the original measurements. Help explains the available options.

Original files are not changed. Temporary standardized files are created in the
output folder and cleaned after completion, cancellation or handled failures.
A crash or power loss can leave a `.battread-work-*` folder; remove it only when
the app is closed. Allow enough disk space, especially for merge.

## Formats and memory

Supported inputs include Bio-Logic MPR/MPT, Neware CSV, generic CSV/TXT and
canonical Parquet/CSV/TXT. NDA/NDAX readers are included but remain experimental.
Output formats are Parquet, CSV and TXT.

MPR uses the current bounded reader. Files are processed sequentially in an
isolated worker, with a budget of 90% of initially free RAM and no fixed ceiling.
This reduces full-file memory copies; it does not guarantee a strict machine-wide
RAM limit or universal format compatibility.

For Bio-Logic, the app explicitly selects a unique `Ewe/V` when present, including
when `<Ewe>/V` is also present. They are not assumed equivalent. Other ambiguities
still fail. Neware CSV uses recognized Total Time, not resetting step time.

## Run or build from source

Use Python 3.11+ on Windows. Install the current library and this app:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "battread[all] @ git+https://github.com/GregAlex7zZ/battread.git"
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
.\.venv\Scripts\pythonw.exe -m battread_gui
```

For local development, an editable sibling battread checkout can replace the Git
install. Library fixes then reach new workers automatically. Restart the app
after updating its own source.

Build with `python tools/build_windows.py`. See `packaging/README.md` for preparing
release assets and preserving license/source files. The executable is unsigned;
Windows may request confirmation when opening a downloaded copy.

## License

Copyright (C) 2026 Alessandro Gregucci. GPL-3.0-or-later, see [LICENSE](LICENSE)
and [AUTHORS.md](AUTHORS.md). Dependencies retain their own licenses and
attributions: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Provided as is, without warranty, subject to the license and applicable law.
Users must independently verify converted data before relying on scientific
results. See [CONTRIBUTING.md](CONTRIBUTING.md) and [future work](TODO.md).
