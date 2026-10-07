# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Responsive Qt Widgets window for local conversion and ordered merging.

QProcess keeps parsing outside the GUI process. A timer observes worker memory,
while newline-delimited events update status without blocking the event loop.
The window receives only progress, metadata and bounded column-choice previews.
"""

from __future__ import annotations

import json
import tempfile
import time
from functools import partial
from pathlib import Path
from typing import Any

import psutil
from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QIcon,
    QPalette,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from battread_gui.column_dialog import ColumnChoiceDialog
from battread_gui.memory import MemoryGuard
from battread_gui.models import (
    Job,
    OutputFormat,
    available_destination,
    output_filename,
)
from battread_gui.runtime import worker_command

STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #222222; }
QMainWindow, QDialog { background: #f2f2f2; }
QMenuBar { background: #f2f2f2; color: #222222; }
QMenuBar::item { padding: 6px 12px; background: transparent; }
QMenuBar::item:selected { background: #dddddd; }
QMenuBar::item:disabled { color: #888888; }
QPushButton { background: #fafafa; border: 1px solid #bbbbbb;
              border-radius: 4px; padding: 7px 13px; }
QPushButton:hover { background: #e5e5e5; border-color: #888888; }
QPushButton:pressed { background: #d5d5d5; }
QPushButton:disabled { color: #888888; background: #eeeeee; }
QPushButton#primary { background: #dddddd; font-weight: 600; }
QPushButton#primary:hover { background: #cccccc; }
QPushButton#removeFile { padding: 1px; border: none; background: transparent; }
QPushButton#removeFile:hover { background: #dddddd; }
QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QTextBrowser {
    background: #ffffff; color: #222222; border: 1px solid #bbbbbb;
    border-radius: 4px; padding: 5px; selection-background-color: #d5d5d5;
    selection-color: #111111; alternate-background-color: #f5f5f5;
}
QTextBrowser { background: #ffffff; color: #222222; }
QHeaderView::section { background: #e9e9e9; color: #222222; padding: 7px;
                      border: none; font-weight: 600; }
QProgressBar { border: none; border-radius: 4px; background: #dddddd;
               min-height: 9px; max-height: 9px; }
QProgressBar::chunk { background: #777777; border-radius: 4px; }
QLabel#muted { color: #666666; }
QLineEdit:disabled { background: #eeeeee; color: #666666; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #666666;
                       border-radius: 2px; background: white; }
QCheckBox::indicator:checked { background: #555555; image: url("__CHECK__"); }
QCheckBox::indicator:hover { border: 1px solid #222222; }
"""


def configure_style(app: QApplication) -> None:
    """Apply a complete neutral light palette, including dialogs on dark Windows.

    A stylesheet alone leaves unstyled text views inheriting the OS dark palette.
    Explicit base/text and link colors prevent the unreadable mixed-theme Help.
    """
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f2f2f2",
        QPalette.ColorRole.WindowText: "#222222",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f5f5f5",
        QPalette.ColorRole.Text: "#222222",
        QPalette.ColorRole.Button: "#eeeeee",
        QPalette.ColorRole.ButtonText: "#222222",
        QPalette.ColorRole.Highlight: "#d5d5d5",
        QPalette.ColorRole.HighlightedText: "#111111",
        QPalette.ColorRole.Link: "#222222",
        QPalette.ColorRole.LinkVisited: "#444444",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#222222",
        QPalette.ColorRole.PlaceholderText: "#777777",
        QPalette.ColorRole.Accent: "#777777",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#777777")
    )
    app.setPalette(palette)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "resources/battread.ico")))
    check_icon = Path(__file__).parent / "resources" / "check.svg"
    app.setStyleSheet(STYLE.replace("__CHECK__", check_icon.as_posix()))


HELP = """<h2>Using battread</h2>
<p>1. Use <b>Add files</b> in the menu bar. Click the X beside a file to remove
it, or use <b>Remove all</b> to clear the list.</p>
<p>2. Files are processed separately by default. Enable <b>Merge files</b>
to join acquisitions; select a row and use Move up / Move down to set order.</p>
<p>3. Choose CSV, tab-separated TXT or Parquet. By default each output is saved
beside its input; a merge uses the first input's folder. Uncheck <b>Save in the same
folder</b> to choose a different folder.</p>
<p>4. Keep names, or uncheck that option and edit the complete output filename,
including its extension. The selected format sets the extension without duplicating
it. The merged output filename is always directly editable. If an automatic name
would replace an input, the displayed name adds <b>_standardized</b> to protect it.</p>
<p>5. Click <b>Process</b>. Existing files are never overwritten. Name conflicts
are resolved automatically as name (2).csv, name (3).csv, and so on.</p>
<h3>Message colors</h3>
<p><span style="color:#a65b00"><b>Orange â€” warning:</b></span> a non-blocking
data-quality issue. Processing continues; inspect the affected data before use.
Missing scientific values remain missing; success does not resolve the warning.</p>
<p><span style="color:#16723c"><b>Green â€” saved:</b></span> the output was saved
successfully. <span style="color:#b42318"><b>Red â€” error:</b></span> processing
cannot continue. Previously saved separate outputs remain available.</p>
<p>Selected file size is measured from file metadata before processing. It is
not a prediction of peak RAM or output/temporary disk requirements.</p>
<h3>Scientific behavior</h3>
<p>Outputs contain time_s, current_mA and voltage_V. Time starts at zero.
Measured current and its sign take precedence over reconstruction. Every CSV
with Time and Total Time uses Total Time; declared units are preserved and a
bare paired Total Time means seconds. Missing rows are never silently removed.</p>
<h3>Choose column</h3>
<p>For remaining ambiguities, the worker pauses. Choose a candidate and its source
unit, review the sample values and evidence, then press Continue. Column numbers
distinguish identical labels. Cancel stops processing. A choice applies only to
that file in this job; already saved separate files are not repeated. A changed
source requires restarting. Binary previews may be unavailable, and choosing a
capacity column does not establish unknown counter semantics.</p>
<p>Merge follows the public battread.merge timing rules. If neither neighboring
acquisition contains an adjacent positive interval, the join fails.</p>
<h3>Progress and memory</h3>
<p>Reading shows phase, file number and rows processed. Writing shows a measured
percentage for the current output. Remaining time is not guessed.</p>
<p>The worker processes files sequentially with temporary Parquet on the output
volume. Allow disk space for standardized inputs and staged outputs. Cancel
stops the worker; already saved separate results remain valid.</p>
<p>Windows enforces a committed-memory allocation cap on the worker. The app also
monitors physical memory and stops when system reserves run low. The budget is
90% of initially available RAM, without a fixed maximum. These safeguards cannot control
other applications or guarantee that the whole computer never runs low on RAM.
The current battread MPR adapter reads bounded binary batches. Unsupported
binary field definitions still fail explicitly; they are never guessed.</p>
<p>Bio-Logic requires the optional biologic dependency. Neware binary NDA/NDAX
support requires its extra and remains experimental. Neware CSV needs no binary
vendor dependency. This application works locally and uploads no data.</p>
<p>For Bio-Logic MPR/MPT, this app explicitly selects the unique Ewe/V column
when present, including when &lt;Ewe&gt;/V is also present. These columns are
not assumed equivalent. If Ewe/V is absent, normal battread recognition applies;
duplicate Ewe/V labels still require clarification.</p>
<p>Scientific readers are provided by
<a href="https://github.com/GregAlex7zZ/battread">battread on GitHub</a>.</p>
"""


class MainWindow(QMainWindow):
    """Own editable file plans and one isolated processing worker at a time.

    No scientific reading happens on the GUI thread. The parent owns the worker
    workspace, including cancellation markers, and cleans it after process exit.
    """

    def __init__(self) -> None:
        """Build the first-version window, controls and asynchronous signal wiring."""
        super().__init__()
        self.setWindowTitle("battread")
        self.resize(900, 640)
        self.setMinimumSize(740, 570)
        self.paths: list[Path] = []
        self.process = QProcess(self)
        self.process.started.connect(self.worker_started)
        self.process.readyReadStandardOutput.connect(self.read_events)
        self.process.readyReadStandardError.connect(self.read_diagnostics)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.monitor)
        self.workspace: tempfile.TemporaryDirectory[str] | None = None
        self.extra_workspaces: list[tempfile.TemporaryDirectory[str]] = []
        self.guard: MemoryGuard | None = None
        self.buffer = ""
        self.stop_reason = ""
        self.last_phase = ""
        self.started_at = 0.0
        self.memory_limit = 0
        self.reserve = 0
        self.saved = 0
        self.last_event: dict[str, Any] = {}
        self.column_dialog: ColumnChoiceDialog | None = None
        self.close_when_done = False
        self.merge_name_custom = False

        self.add_action = QAction("Add files", self)
        self.add_action.setShortcut("Ctrl+O")
        self.add_action.triggered.connect(self.add_files)
        self.clear_action = QAction("Remove all", self)
        self.clear_action.triggered.connect(self.remove_all)
        help_action = QAction("Help", self)
        help_action.triggered.connect(self.show_help)
        self.menuBar().addAction(self.add_action)
        self.menuBar().addAction(self.clear_action)
        self.menuBar().addAction(help_action)
        about_action = QAction("About / License", self)
        about_action.triggered.connect(self.show_about)
        self.menuBar().addAction(about_action)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        self.root_layout = layout
        layout.setContentsMargins(16, 10, 16, 16)
        layout.setSpacing(12)

        self.settings = QWidget()
        settings_layout = QVBoxLayout(self.settings)
        self.settings_layout = settings_layout
        # Hidden merge controls change the required height. Propagate the real
        # minimum so a small window cannot squeeze rows into neighboring controls.
        settings_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(12)
        buttons = QVBoxLayout()
        buttons.addStretch()
        self.up = QPushButton("â†‘  Move up")
        self.down = QPushButton("â†“  Move down")
        self.up.clicked.connect(self.move_up)
        self.down.clicked.connect(self.move_down)
        buttons.addWidget(self.up)
        buttons.addWidget(self.down)
        buttons.addStretch()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["File", "Save as", ""])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(2, 36)
        self.table.setMinimumHeight(165)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        file_row = QHBoxLayout()
        file_row.addWidget(self.table, 1)
        file_row.addLayout(buttons)
        settings_layout.addLayout(file_row)
        modes = QHBoxLayout()
        self.merge_box = QCheckBox("Merge files")
        self.merge_box.toggled.connect(self.update_mode)
        self.keep_names = QCheckBox("Keep names")
        self.keep_names.setChecked(True)
        self.keep_names.toggled.connect(self.update_mode)
        modes.addWidget(self.merge_box)
        self.same_folder = QCheckBox("Save in the same folder")
        self.same_folder.setChecked(True)
        self.same_folder.toggled.connect(self.update_destination)
        modes.addWidget(self.same_folder)
        modes.addStretch()
        modes.addWidget(self.keep_names)
        settings_layout.addLayout(modes)

        self.merge_row = QWidget()
        merge_layout = QHBoxLayout(self.merge_row)
        merge_layout.setContentsMargins(0, 0, 0, 0)
        merge_layout.addWidget(QLabel("File name"))
        self.merge_name = QLineEdit()
        self.merge_name.textEdited.connect(self.mark_merge_name_custom)
        merge_layout.addWidget(self.merge_name)
        settings_layout.addWidget(self.merge_row)
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Folder"))
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Choose a folder for standardized files")
        output_row.addWidget(self.folder, 1)
        self.browse = QPushButton("Browseâ€¦")
        self.browse.clicked.connect(self.choose_folder)
        output_row.addWidget(self.browse)
        self.format_box = QComboBox()
        self.format_box.addItems(["CSV", "TXT", "Parquet"])
        output_row.addWidget(self.format_box)
        settings_layout.addLayout(output_row)
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        settings_layout.addWidget(self.size_label)
        self.folder.textChanged.connect(self.refresh_names)
        self.folder.textChanged.connect(self.update_preview)
        self.merge_name.textChanged.connect(self.update_preview)
        self.format_box.currentTextChanged.connect(self.update_mode)
        self.table.itemChanged.connect(self.update_preview)
        layout.addWidget(self.settings, 1)

        self.status = QLabel("Ready â€” add files to begin.")
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumBlockCount(500)
        self.details.setMaximumHeight(110)
        layout.addWidget(self.details)
        footer = QHBoxLayout()
        self.memory_label = QLabel()
        self.memory_label.setObjectName("muted")
        footer.addWidget(self.memory_label, 1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        footer.addWidget(self.cancel_button)
        self.start_button = QPushButton("Process")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start)
        footer.addWidget(self.start_button)
        layout.addLayout(footer)
        self.update_mode()
        self.update_destination()

    def show_help(self) -> None:
        """Display English workflow instructions and explicit scientific limitations."""
        dialog = self.help_dialog()
        dialog.exec()

    def show_about(self) -> None:
        """Show authorship, AI disclosure and the complete GPL license locally."""
        self.about_dialog().exec()

    def about_dialog(self) -> QDialog:
        """Build a readable About/License dialog with the library's repository link."""
        dialog = QDialog(self)
        dialog.setWindowTitle("About / License")
        dialog.resize(650, 560)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        about = QTextBrowser()
        about.setOpenExternalLinks(True)
        about.setHtml(
            "<h2>battread GUI</h2><p>Copyright Â© 2026 Alessandro Gregucci.</p>"
            "<p>Licensed under GNU GPL version 3 or later, as is battread.</p>"
            '<p><a href="https://github.com/GregAlex7zZ/battread/blob/main/AUTHORS.md">'
            "Authorship</a></p>"
            '<p>Scientific library: <a href="https://github.com/GregAlex7zZ/battread">'
            "github.com/GregAlex7zZ/battread</a></p>"
            "<p>Third-party dependencies retain their own authorship and license "
            "terms. This software is provided without warranty, as described "
            "in the license.</p>"
        )
        tabs.addTab(about, "About")
        license_text = QTextBrowser()
        license_text.setPlainText(
            (Path(__file__).parent / "resources" / "GPL-3.0.txt").read_text(
                encoding="utf-8"
            )
        )
        tabs.addTab(license_text, "License")
        layout.addWidget(tabs)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        return dialog

    def help_dialog(self) -> QDialog:
        """Build the scrollable guide for display and contrast regression tests."""
        dialog = QDialog(self)
        dialog.setWindowTitle("battread help")
        dialog.resize(650, 620)
        layout = QVBoxLayout(dialog)
        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setHtml(HELP)
        layout.addWidget(text)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        return dialog

    def add_files(self) -> None:
        """Append unique user-selected files without reading their scientific data."""
        names, _ = QFileDialog.getOpenFileNames(
            self,
            "Add cycling data",
            "",
            "Cycling data (*.mpr *.mpt *.nda *.ndax *.csv *.txt *.parquet);;"
            "All files (*)",
        )
        self.append_files([Path(name) for name in names])

    def append_files(self, paths: list[Path]) -> None:
        """Populate input rows without opening their scientific contents."""
        for path in paths:
            path = path.resolve()
            if path in self.paths:
                continue
            self.paths.append(path)
            row = self.table.rowCount()
            self.table.insertRow(row)
            source = QTableWidgetItem(path.name)
            source.setToolTip(str(path))
            source.setFlags(source.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, source)
            self.table.setItem(row, 1, QTableWidgetItem(path.stem))
            self.set_remove_button(row)
        self.update_mode()

    def set_remove_button(self, row: int) -> None:
        """Bind the row's X to its input identity, avoiding stale reordered indices."""
        button = QPushButton("Ã—")  # noqa: RUF001 - conventional close glyph.
        button.setObjectName("removeFile")
        button.setToolTip("Remove this file")
        button.setAccessibleName(f"Remove {self.paths[row].name}")
        button.clicked.connect(partial(self.remove_file, self.paths[row]))
        self.table.setCellWidget(row, 2, button)

    def remove_file(self, path: Path, checked: bool = False) -> None:
        """Remove exactly the file whose X was clicked, even after reordering."""
        if path in self.paths:
            row = self.paths.index(path)
            self.paths.pop(row)
            self.table.removeRow(row)
            self.update_mode()

    def remove_all(self) -> None:
        """Clear the plan from the menu bar without touching files on disk."""
        self.paths.clear()
        self.table.setRowCount(0)
        self.merge_name_custom = False
        self.update_mode()

    def move_up(self) -> None:
        """Move the selected acquisition one position earlier in merge order."""
        self.move_selected(-1)

    def move_down(self) -> None:
        """Move the selected acquisition one position later in merge order."""
        self.move_selected(1)

    def move_selected(self, direction: int) -> None:
        """Swap adjacent rows and names together, preserving selection."""
        row = self.table.currentRow()
        other = row + direction
        if row < 0 or not 0 <= other < len(self.paths):
            return
        self.paths[row], self.paths[other] = self.paths[other], self.paths[row]
        for column in range(2):
            item = self.table.takeItem(row, column)
            neighbor = self.table.takeItem(other, column)
            self.table.setItem(row, column, neighbor)
            self.table.setItem(other, column, item)
        self.table.selectRow(other)
        for index in (row, other):
            self.set_remove_button(index)
        self.update_mode()

    def mark_merge_name_custom(self, text: str) -> None:
        """Preserve a manually edited merge name when inputs or mode change."""
        self.merge_name_custom = bool(text)

    def update_mode(self) -> None:
        """Show ordering for merge and enable names when explicitly editable."""
        merging = self.merge_box.isChecked()
        original = self.keep_names.isChecked()
        self.up.setVisible(merging)
        self.down.setVisible(merging)
        self.merge_row.setVisible(merging)
        self.merge_name.setEnabled(True)
        self.keep_names.setVisible(not merging)
        self.table.setColumnHidden(1, merging)
        for row in range(len(self.paths)):
            item = self.table.item(row, 1)
            assert item is not None  # Every input row owns its output-name cell.
            if original:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.start_button.setEnabled(bool(self.paths))
        self.status.clear()
        self.status.hide()
        self.update_preview()
        self.update_destination()
        self.update_size()
        self.fit_controls()

    def update_size(self) -> None:
        """Measure selected file bytes from metadata without reading their contents."""
        total = 0
        unavailable = 0
        for path in self.paths:
            try:
                total += path.stat().st_size
            except OSError:
                unavailable += 1
        if not self.paths:
            self.size_label.clear()
            return
        size = float(total)
        unit = "B"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                break
            size /= 1024
        message = f"{len(self.paths)} file(s) Â· {size:.1f} {unit}"
        if unavailable:
            message += f" Â· size unavailable for {unavailable} file(s)"
        self.size_label.setText(message)

    def fit_controls(self) -> None:
        """Grow the window's minimum height to prevent expanded controls overlapping."""
        self.settings_layout.activate()
        self.root_layout.activate()
        required = (
            self.root_layout.minimumSize().height() + self.menuBar().sizeHint().height()
        )
        self.setMinimumHeight(max(570, required))

    def update_destination(self) -> None:
        """Expose an optional common folder; the default follows source locations."""
        automatic = self.same_folder.isChecked()
        self.folder.setEnabled(not automatic)
        self.browse.setEnabled(not automatic)
        if automatic:
            if not self.paths:
                self.folder.clear()
            elif self.merge_box.isChecked() or len({p.parent for p in self.paths}) == 1:
                self.folder.setText(str(self.paths[0].parent))
            else:
                self.folder.setText("Each input file's folder")
        elif self.folder.text() == "Each input file's folder":
            self.folder.setText(str(self.paths[0].parent) if self.paths else "")
        self.refresh_names()
        self.update_preview()

    def refresh_names(self) -> None:
        """Set automatic names, adding a visible suffix only to protect an input.

        CSV-to-CSV beside its source would otherwise replace that source. Custom
        names remain untouched and still undergo strict conflict validation.
        """
        extension = self.format_box.currentText().lower()
        for row, path in enumerate(self.paths):
            item = self.table.item(row, 1)
            if item is not None and self.keep_names.isChecked():
                destination = self.output_folder(row) / f"{path.stem}.{extension}"
                name = path.stem
                if destination.resolve() in self.paths:
                    name += "_standardized"
                item.setText(f"{name}.{extension}")
            elif item is not None:
                item.setText(output_filename(item.text(), extension))
        if not self.paths:
            self.merge_name.clear()
        elif not self.merge_name_custom:
            path = self.paths[0]
            destination = self.output_folder(0) / f"{path.stem}.{extension}"
            name = path.stem
            if destination.resolve() in self.paths:
                name += "_standardized"
            self.merge_name.setText(f"{name}.{extension}")
        else:
            self.merge_name.setText(output_filename(self.merge_name.text(), extension))

    def output_folder(self, index: int) -> Path:
        """Resolve a destination folder without treating its display hint as a path."""
        if self.same_folder.isChecked():
            return self.paths[0 if self.merge_box.isChecked() else index].parent
        return Path(self.folder.text())

    def update_preview(self) -> None:
        """Expose complete destinations in tooltips without explanatory labels.

        This performs no filesystem access; final safety checks belong to
        make_job(). Filenames remain visible in their editable fields.
        """
        if not self.paths:
            self.table.setToolTip("")
            self.merge_name.setToolTip("")
            return
        # Qt emits cell-change signals while a row is still being populated or
        # swapped. Wait for its name cell before rebuilding the complete plan.
        if any(self.table.item(i, 1) is None for i in range(self.table.rowCount())):
            return
        names = (
            [self.merge_name.text()]
            if self.merge_box.isChecked()
            else [self.output_name(i) for i in range(self.table.rowCount())]
        )
        extension = self.format_box.currentText().lower()
        filenames = [output_filename(name, extension) for name in names]
        destinations = "\n".join(
            str(self.output_folder(i) / name) for i, name in enumerate(filenames)
        )
        self.table.setToolTip(destinations)
        self.merge_name.setToolTip(destinations)

    def choose_folder(self) -> None:
        """Choose an existing local destination directory without creating outputs."""
        name = QFileDialog.getExistingDirectory(
            self, "Output folder", self.folder.text()
        )
        if name:
            self.folder.setText(name)

    def make_job(self) -> Job:
        """Resolve the current controls into a validated immutable destination plan."""
        from typing import cast

        from battread_gui.models import validate_name

        if not self.same_folder.isChecked() and not self.folder.text().strip():
            raise ValueError("Choose an output folder.")
        format = cast(OutputFormat, self.format_box.currentText().lower())
        names = (
            [self.merge_name.text()]
            if self.merge_box.isChecked()
            else [self.output_name(i) for i in range(len(self.paths))]
        )
        requested = tuple(
            self.output_folder(i) / validate_name(output_filename(name, format))
            for i, name in enumerate(names)
        )
        reserved = {p.resolve() for p in self.paths}
        planned: list[Path] = []
        for path in requested:
            target = available_destination(path, reserved)
            planned.append(target)
            reserved.add(target.resolve())
        outputs = tuple(planned)
        memory = psutil.virtual_memory()
        if memory.available < 256 * 1024**2:
            raise ValueError(
                "Insufficient free memory. Close other applications first."
            )
        # This is a provisional safety policy, not a throughput/peak prediction.
        budget = int(memory.available * 0.90)
        job = Job(
            tuple(self.paths), outputs, self.merge_box.isChecked(), format, budget
        )
        job.validate()
        return job

    def output_name(self, row: int) -> str:
        """Read a populated name cell, making the table's row invariant explicit."""
        item = self.table.item(row, 1)
        if item is None:
            raise ValueError("An input row has no output name.")
        return item.text()

    def start(self) -> None:
        """Validate destinations, create a private workspace and launch the worker."""
        try:
            job = self.make_job()
            if job.merge:
                self.merge_name.setText(job.outputs[0].name)
            else:
                for row, target in enumerate(job.outputs):
                    item = self.table.item(row, 1)
                    assert item is not None
                    item.setText(target.name)
            self.workspace = tempfile.TemporaryDirectory(
                prefix=".battread-work-", dir=job.outputs[0].parent
            )
            staging = {str(job.outputs[0].parent.resolve()): self.workspace.name}
            for target in job.outputs:
                parent = str(target.parent.resolve())
                if parent not in staging:
                    temporary = tempfile.TemporaryDirectory(
                        prefix=".battread-work-", dir=target.parent
                    )
                    self.extra_workspaces.append(temporary)
                    staging[parent] = temporary.name
            payload = {
                "inputs": [str(p) for p in job.inputs],
                "outputs": [str(p) for p in job.outputs],
                "merge": job.merge,
                "format": job.format,
                "memory_limit": job.memory_limit,
                "chunk_size": job.chunk_size,
                "output_workspaces": staging,
            }
            (Path(self.workspace.name) / "job.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except (ValueError, OSError) as error:
            for temporary in self.extra_workspaces:
                temporary.cleanup()
            self.extra_workspaces.clear()
            if self.workspace is not None:
                self.workspace.cleanup()
                self.workspace = None
            self.append_message(str(error), "#b42318")
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #b42318;")
            self.status.show()
            QMessageBox.critical(self, "Cannot start", str(error))
            return
        self.settings.setEnabled(False)
        self.add_action.setEnabled(False)
        self.clear_action.setEnabled(False)
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.buffer = ""
        self.stop_reason = ""
        self.last_event = {}
        self.saved = 0
        self.details.clear()
        self.started_at = time.monotonic()
        self.memory_limit = job.memory_limit
        # The budget is 90% of initial free RAM; its remaining 10% is the live
        # system reserve. A fixed reserve would override that policy on small
        # free-memory amounts and prevent use of the requested percentage.
        self.reserve = max(1, job.memory_limit // 9)
        self.progress.setRange(0, 0)
        self.status.setText("Starting workerâ€¦")
        self.status.setStyleSheet("color: #222222;")
        self.status.show()
        executable, arguments = worker_command(self.workspace.name)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("OPENBLAS_NUM_THREADS", "1")
        self.process.setProcessEnvironment(environment)
        self.process.start(executable, arguments)
        self.timer.start()

    def worker_started(self) -> None:
        """Protect the spawned worker before authorizing heavy scientific imports."""
        try:
            self.guard = MemoryGuard(self.process.processId(), self.memory_limit)
        except OSError as error:
            self.stop_reason = f"Could not establish the worker memory limit: {error}"
            self.append_message(self.stop_reason, "#b42318")
            self.process.kill()
            return
        self.process.write(b"ready\n")
        self.process.closeWriteChannel()

    def read_events(self) -> None:
        """Decode complete JSON lines, retaining partial messages between signals."""
        self.buffer += bytes(self.process.readAllStandardOutput().data()).decode(
            "utf-8"
        )
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            try:
                event = json.loads(line)
            except ValueError:
                self.details.appendPlainText("Unexpected worker output was received.")
                continue
            self.handle_event(event)

    def handle_event(self, event: dict[str, Any]) -> None:
        """Render progress and preserve warnings/errors in a bounded local log."""
        self.last_event = event
        phase = str(event.get("phase", "Processing"))
        if phase == "Column choice":
            self.show_column_choice(event)
            return
        if phase in {"Warning", "Error", "Cancelled"}:
            color = "#b42318" if phase == "Error" else "#a65b00"
            self.append_message(str(event.get("message", phase)), color)
            if phase == "Error":
                self.stop_reason = str(event.get("message", "Processing failed."))
            return
        if phase == "Saved":
            self.saved += 1
            self.append_message(f"Saved: {event['output']}", "#16723c")
        percentage = event.get("percent")
        if percentage is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(percentage))
        self.last_phase = phase
        detail = ""
        if "file" in event:
            detail += f" Â· file {event['file']} of {event['files']}"
        if "rows" in event:
            detail += f" Â· {int(event['rows']):,} rows"
        if percentage is not None:
            detail += f" Â· {percentage}%"
        self.status.setText(phase + detail)

    def show_column_choice(self, event: dict[str, Any]) -> None:
        """Open a nonblocking dialog while the worker waits in its private workspace."""
        if self.workspace is None or self.stop_reason:
            return
        if self.column_dialog is not None:
            self.stop_reason = "Overlapping column selection requests."
            self.cancel()
            return
        dialog = ColumnChoiceDialog(event, self)
        self.column_dialog = dialog
        self.status.setText("Waiting for a column choice...")
        self.append_message(
            f"{Path(event['source']).name}: choose the {event['quantity']} column.",
            "#a65b00",
        )

        def reply(result: int) -> None:
            """Publish an atomic reply or cancel; preview values remain in memory."""
            if self.column_dialog is not dialog:
                dialog.deleteLater()
                return
            self.column_dialog = None
            if result != QDialog.DialogCode.Accepted:
                if not self.stop_reason:
                    self.cancel()
            elif self.workspace is not None and not self.stop_reason:
                root = Path(self.workspace.name)
                target = root / f"column-choice-{int(event['request_id'])}.json"
                temporary = target.with_suffix(".tmp")
                try:
                    temporary.write_text(
                        json.dumps(dialog.selection()), encoding="utf-8"
                    )
                    temporary.replace(target)
                    self.status.setText("Continuing processing...")
                except OSError as error:
                    self.cancel()
                    self.stop_reason = f"Could not apply column choice: {error}"
                    self.append_message(self.stop_reason, "#b42318")
            dialog.deleteLater()

        dialog.finished.connect(reply)
        dialog.show()

    def append_message(self, text: str, color: str = "#222222") -> None:
        """Append diagnostic text in a semantic color without interpreting HTML.

        The document's block limit bounds log memory. Formatting is explicit for
        each entry, so an error cannot recolor a later successful save.
        """
        cursor = self.details.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.details.document().isEmpty():
            cursor.insertBlock()
        format = QTextCharFormat()
        format.setForeground(QColor(color))
        cursor.insertText(text, format)
        self.details.setTextCursor(cursor)

    def read_diagnostics(self) -> None:
        """Keep backend stderr visible locally without exporting private diagnostics."""
        value = bytes(self.process.readAllStandardError().data()).decode(
            "utf-8", errors="replace"
        )
        if value.strip():
            self.details.appendPlainText(value.strip())

    def monitor(self) -> None:
        """Keep elapsed/memory feedback live and respond to system pressure.

        Windows independently caps committed allocations via MemoryGuard. This
        timer samples RSS/free physical memory, which are different quantities.
        """
        pid = self.process.processId()
        if not pid:
            return
        try:
            used = psutil.Process(pid).memory_info().rss
        except psutil.Error:
            return
        elapsed = int(time.monotonic() - self.started_at)
        self.memory_label.setText(
            f"Elapsed {elapsed // 60}:{elapsed % 60:02d} Â· "
            f"Worker {used / 1024**2:.0f} / {self.memory_limit / 1024**2:.0f} MB"
        )
        if not self.stop_reason and (
            used > self.memory_limit or psutil.virtual_memory().available < self.reserve
        ):
            self.stop_reason = (
                "Stopped to protect available memory. No partial output saved."
            )
            self.append_message(self.stop_reason, "#b42318")
            self.process.kill()

    def cancel(self) -> None:
        """Request cancellation, then kill only if a blocked reader does not respond."""
        if self.workspace is None:
            return
        self.stop_reason = "Cancelled. Already saved outputs are retained."
        (Path(self.workspace.name) / "cancel").touch()
        self.cancel_button.setEnabled(False)
        if self.column_dialog is not None:
            self.column_dialog.reject()
        self.status.setText("Cancellingâ€¦")
        QTimer.singleShot(3000, self.kill_if_running)

    def kill_if_running(self) -> None:
        """Release a vendor backend that cannot observe cooperative cancellation."""
        if (
            self.process.state() != QProcess.ProcessState.NotRunning
            and self.stop_reason
        ):
            self.process.kill()

    def process_error(self, error: QProcess.ProcessError) -> None:
        """Recover control after failure to spawn; crash cleanup happens on finished."""
        if error == QProcess.ProcessError.FailedToStart:
            self.stop_reason = "Could not start the processing worker."
            self.finished(1, QProcess.ExitStatus.CrashExit)

    def finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        """Drain events, clean temporary files and make the window usable again."""
        self.read_events()
        self.read_diagnostics()
        if self.column_dialog is not None:
            dialog = self.column_dialog
            self.column_dialog = None
            dialog.reject()
        self.timer.stop()
        if self.guard is not None:
            self.guard.close()
            self.guard = None
        if self.workspace is not None:
            self.workspace.cleanup()
            self.workspace = None
        for temporary in self.extra_workspaces:
            temporary.cleanup()
        self.extra_workspaces.clear()
        self.settings.setEnabled(True)
        self.add_action.setEnabled(True)
        self.clear_action.setEnabled(True)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 100)
        if self.stop_reason:
            self.status.setText(self.stop_reason)
            self.status.setStyleSheet(
                "color: #a65b00;"
                if self.stop_reason.startswith("Cancelled")
                else "color: #b42318;"
            )
            self.progress.setValue(0)
        elif exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            self.progress.setValue(100)
            self.status.setText(f"Complete â€” {self.saved} output file(s) saved.")
            self.status.setStyleSheet("color: #16723c;")
        else:
            self.progress.setValue(0)
            self.status.setText("Processing failed. See details below.")
            self.status.setStyleSheet("color: #b42318;")
        if self.close_when_done:
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Prevent abandoning a running worker; allow closing after cancellation."""
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.close_when_done = True
            self.cancel()
            event.ignore()
            return
        event.accept()


def main() -> None:
    """Run the English desktop application in the current Python environment."""
    from battread_gui.startup import main as launch

    launch()
