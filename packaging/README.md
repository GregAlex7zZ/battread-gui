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
Use `battread-gui` as the only working repository, alongside `battread`.
Release preparation stages selected sources temporarily under `.cache` and
removes that staging directory automatically; it does not create a second repo.

Then run `python tools/build_portable.py` and `python tools/prepare_release.py`
again to include the single-file portable EXE in the checksums and updated source
assets. The wrapper embeds the complete reviewed folder, including licenses.
The lightweight Windows .NET Framework launcher paints its startup notice before
extracting the payload in a background task. It waits for a marker from the desktop
window before closing the splash, then waits until the app exits before cleanup.
The bundled worker remains separate inside the temporary folder; no console
window is shown. The launcher uses the .NET Framework supplied with Windows 10/11.
Its C# source and the build recipe are included in the app source archive.

Upload the portable EXE, app source archive, matching battread source archive,
dependency-source archive and checksum file as GitHub Release assets. Source
code goes in the repository; executables and build caches do not. Keep matching
source assets available for each binary release. Code signing and a separate
clean-machine Windows trial remain future validation work.

The folder build is a local packaging intermediate; do not attach its ZIP to the
release. Users download one portable EXE. Keep source packages and checksums
beside that executable.
