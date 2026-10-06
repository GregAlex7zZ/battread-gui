# Third-party notices

The application is GPL-3.0-or-later, copyright 2026 Alessandro Gregucci. Its
original icon is distributed under the same license. No dependency authorship
or ownership is claimed.

| Component | Purpose | License |
|---|---|---|
| battread | Scientific readers and canonical standardization | GPL-3.0-or-later |
| Qt for Python / PySide6 / Shiboken, The Qt Company and contributors | Desktop interface | LGPL-3.0 option; original notices retained |
| NumPy, pandas | Numeric and tabular processing | BSD notices and bundled-component licenses |
| Apache Arrow / PyArrow | Canonical Parquet staging and output | Apache-2.0 and bundled-component notices |
| psutil | Worker memory monitoring | BSD-3-Clause |
| Galvani, Chris Kerr and contributors | Bio-Logic field/header definitions | GPL-3.0-or-later |
| NewareNDA, Daniel Cogswell and contributors / SES AI Corporation | Experimental Neware binary readers | BSD-3-Clause |
| Python and standard-library contributors | Bundled interpreter | PSF and retained component notices |
| PyInstaller | Executable bootloader | GPL with the bootloader distribution exception |

Other runtime dependencies include python-dateutil, six, tzdata and xmltodict,
with their original license texts retained in the Windows release's `licenses/`
folder. The generated release inventory records exact versions. The NewareNDA
notice is also retained by battread's source distribution.

Qt libraries remain separate DLLs in the portable folder. Compatible modified
library versions may be substituted; no additional restriction on modification
or reverse engineering for that purpose is imposed. LGPL and GPL texts are
provided in `licenses/`. Publisher commercial-license notices are retained as
upstream material; this release uses the open-source licensing option.

Release assets provide the matching app/library sources and exact Qt/PySide and
Galvani source packages. `SOURCES.md` explains the source locations. Retain these
alongside the executable download. No third-party endorsement is implied.

References: [Qt licensing](https://doc.qt.io/qt-6/lgpl.html),
[PyInstaller exception](https://pyinstaller.org/en/stable/license.html),
[Galvani](https://github.com/echemdata/galvani),
[NewareNDA](https://github.com/d-cogswell/NewareNDA).

## Portable launcher

The single-file launcher uses the system's Windows .NET Framework to display
startup feedback before extraction; the framework is not redistributed here.
The source package documents rebuilding the folder application with persistent,
replaceable Qt libraries. The portable release adds no
restrictions on modifications permitted by the bundled licenses.
