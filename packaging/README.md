# Windows packaging

Use Windows x64, the tested build requirements and the current battread source.
Install both optional vendor readers for a complete package. Run:

```powershell
python tools/build_windows.py
```

`dist/battread/battread.exe` is windowed. Its piped worker is under `_internal`;
both use the same bundled libraries. No Python installation is required at run
time. Do not distribute just the EXE or remove its `_internal` directory.
Onedir packaging avoids repeated extraction at startup and allows Qt DLL replacement.

The source repository contains build specifications and the editable SVG icon.
The multi-size ICO can be rebuilt with `python tools/make_icon.py`.

Before a release, run source tests and static checks, then frozen-worker
conversion/merge/error/cancellation checks and the executable startup check.
Check the exact bundled files, original license texts and source packages.
Prepare release assets with `python tools/prepare_release.py`; it requires the
exact upstream source packages under `.cache/dependency-sources` and collects
licenses from those sources and the installed runtime distributions.

Upload the Windows ZIP, app source archive, matching battread source archive,
dependency-source archive and checksum file as GitHub Release assets. Source
code goes in the repository; executables and build caches do not. Keep matching
source assets available for each binary release. Code signing and a separate
clean-machine Windows trial remain future validation work.
