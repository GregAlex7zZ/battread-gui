# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise actual widget plans and a real QProcess without private input data."""

import time

import battread
from PySide6.QtCore import QPoint, QProcess
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QTextBrowser
from test_processing import canonical

from battread_gui.app import MainWindow, configure_style


def wait_until(app, predicate, timeout=20):
    """Pump Qt events with a deadline so subprocess tests cannot hang forever."""
    deadline = time.monotonic() + timeout
    while not predicate():
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for the worker.")
        time.sleep(0.01)


def test_order_and_names(app, tmp_path, capsys):
    """File order and custom names move together; merge uses the first base name."""
    window = MainWindow()
    paths = [tmp_path / "first.csv", tmp_path / "second.csv"]
    for path in paths:
        path.touch()
    window.append_files(paths + paths)
    assert len(window.paths) == 2
    assert not window.merge_box.isChecked()
    window.merge_box.setChecked(True)
    window.table.selectRow(1)
    window.move_up()
    assert window.paths == list(reversed(paths))
    assert window.merge_name.text() == "second_standardized.csv"
    window.keep_names.setChecked(False)
    window.merge_name.setText("combined")
    window.folder.setText(str(tmp_path))
    assert window.make_job().outputs[0].name == "combined.csv"
    window.merge_box.setChecked(False)
    window.table.item(0, 1).setText("custom")
    window.move_down()
    assert window.table.item(1, 1).text() == "custom.csv"
    window.close()
    assert "Traceback" not in capsys.readouterr().err


def test_real_worker_keeps_ui_responsive(app, tmp_path):
    """A real separate process completes conversion and releases its workspace."""
    source = tmp_path / "source.parquet"
    frame = canonical([0, 1, 2])
    battread.write(frame, source)
    window = MainWindow()
    window.append_files([source])
    window.folder.setText(str(tmp_path))
    window.start()
    assert not window.settings.isEnabled()
    assert window.cancel_button.isEnabled()
    wait_until(app, lambda: window.workspace is None)
    assert window.settings.isEnabled()
    assert window.saved == 1
    assert window.progress.value() == 100
    pd_frame = battread.read(tmp_path / "source.csv")
    assert pd_frame.equals(frame)
    assert not list(tmp_path.glob(".battread-work-*"))
    window.close()


def test_real_worker_converts_updated_mpr_reader(app, tmp_path, accessory_mpr):
    """The GUI worker inherits accessory-field support and explicit Ewe/V selection."""
    window = MainWindow()
    try:
        window.append_files([accessory_mpr])
        window.start()
        wait_until(app, lambda: window.workspace is None)
        assert window.saved == 1, window.details.toPlainText()
        frame = battread.read(tmp_path / "accessory.csv")
        assert frame.time_s.tolist() == [0.0, 1.0]
        assert frame.current_mA.tolist() == [-2.0, 3.0]
        assert frame.voltage_V.tolist() == [3.5, 3.5]
        assert "MissingValueWarning" not in window.details.toPlainText()
        assert not list(tmp_path.glob(".battread-work-*"))
    finally:
        window.close()


def test_cancel_worker_and_cleanup(app, tmp_path):
    """Immediate cancellation stops even a worker still importing dependencies."""
    source = tmp_path / "source.parquet"
    battread.write(canonical([0, 1, 2]), source)
    window = MainWindow()
    window.append_files([source])
    window.folder.setText(str(tmp_path))
    window.start()
    window.cancel()
    wait_until(app, lambda: window.workspace is None)
    assert "Cancelled" in window.status.text()
    assert not (tmp_path / "source.csv").exists()
    assert window.process.state() == QProcess.ProcessState.NotRunning
    assert not list(tmp_path.glob(".battread-work-*"))
    window.close()


def test_row_remove_button_after_reordering(app, tmp_path):
    """The X must remove its current file, not an index captured before a move."""
    window = MainWindow()
    paths = [tmp_path / "a.csv", tmp_path / "b.csv", tmp_path / "c.csv"]
    window.append_files(paths)
    assert window.windowTitle() == "battread"
    assert [a.text() for a in window.menuBar().actions()] == [
        "Add files",
        "Remove all",
        "Help",
        "About / License",
    ]
    window.merge_box.setChecked(True)
    window.table.selectRow(2)
    window.move_up()
    button = window.table.cellWidget(1, 2)
    assert isinstance(button, QPushButton)
    button.click()
    assert window.paths == paths[:2]
    window.clear_action.trigger()
    assert not window.paths
    assert window.table.rowCount() == 0
    assert not window.start_button.isEnabled()
    window.close()


def test_merge_name_directly_editable_and_preserved(app, tmp_path):
    """Editing the merge field needs no checkbox and survives a reordered first file."""
    window = MainWindow()
    window.append_files([tmp_path / "first.mpt", tmp_path / "second.mpt"])
    window.merge_box.setChecked(True)
    assert window.keep_names.isChecked()
    assert window.merge_name.isEnabled()
    window.merge_name.selectAll()
    QTest.keyClicks(window.merge_name, "my-merge")
    window.table.selectRow(1)
    window.move_up()
    assert window.merge_name.text() == "my-merge.csv"
    window.close()


def test_source_folders_default_and_custom_destination(app, tmp_path):
    """Default folders follow sources and an explicit choice overrides them."""
    first_dir, second_dir, chosen = [
        tmp_path / n for n in ("first", "second", "chosen")
    ]
    for directory in (first_dir, second_dir, chosen):
        directory.mkdir()
    paths = [first_dir / "one.parquet", second_dir / "two.parquet"]
    for path in paths:
        battread.write(canonical([0, 1, 2]), path)
    window = MainWindow()
    window.append_files(paths)
    assert window.same_folder.isChecked()
    assert not window.folder.isEnabled()
    assert [p.parent for p in window.make_job().outputs] == [first_dir, second_dir]
    window.merge_box.setChecked(True)
    assert window.make_job().outputs[0].parent == first_dir
    window.table.selectRow(1)
    window.move_up()
    assert window.make_job().outputs[0].parent == second_dir
    window.same_folder.setChecked(False)
    window.folder.setText(str(chosen))
    assert window.folder.isEnabled()
    assert window.make_job().outputs[0].parent == chosen
    window.close()


def test_multiple_source_folder_worker_cleans_all_staging(app, tmp_path):
    """A real worker writes to both source folders and removes every workspace."""
    paths = []
    for name in ("a", "b"):
        directory = tmp_path / name
        directory.mkdir()
        source = directory / "input.parquet"
        battread.write(canonical([0, 1, 2]), source)
        paths.append(source)
    window = MainWindow()
    window.append_files(paths)
    window.start()
    wait_until(app, lambda: window.workspace is None)
    assert window.saved == 2
    for source in paths:
        assert battread.read(source.with_suffix(".csv")).equals(canonical([0, 1, 2]))
        assert not list(source.parent.glob(".battread-work-*"))
    assert not window.extra_workspaces
    window.close()


def test_help_contrast_with_dark_system_palette(app):
    """Help must have dark text on white even when Qt starts with a dark OS palette."""
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Base, QColor("#000000"))
    dark.setColor(QPalette.ColorRole.Text, QColor("#0000ff"))
    app.setPalette(dark)
    configure_style(app)
    window = MainWindow()
    dialog = window.help_dialog()
    dialog.show()
    app.processEvents()
    browser = dialog.findChild(QTextBrowser)
    assert browser is not None
    assert browser.palette().color(QPalette.ColorRole.Base).name() == "#ffffff"
    assert browser.palette().color(QPalette.ColorRole.Text).name() == "#222222"
    assert browser.palette().color(QPalette.ColorRole.Link).name() == "#222222"
    dialog.close()
    window.close()


def test_same_folder_csv_keeps_original_safe(app, tmp_path):
    """Default CSV-to-CSV names get a visible suffix instead of replacing originals."""
    source = tmp_path / "acquisition.csv"
    canonical([0, 1, 2]).to_csv(source, index=False)
    original = source.read_bytes()
    window = MainWindow()
    window.append_files([source])
    assert window.make_job().outputs[0].name == "acquisition_standardized.csv"
    assert "acquisition_standardized.csv" in window.table.toolTip()
    window.start()
    wait_until(app, lambda: window.workspace is None)
    assert window.saved == 1
    assert source.read_bytes() == original
    window.close()


def test_merge_controls_do_not_overlap_file_table(app, tmp_path):
    """Opening merge controls must grow the minimum layout rather than overlap rows."""
    window = MainWindow()
    window.append_files([tmp_path / "example.mpt"])
    window.show()
    window.merge_box.setChecked(True)
    app.processEvents()
    assert window.table.geometry().bottom() < window.merge_box.geometry().top()
    folder_bottom = window.folder.mapTo(
        window.centralWidget(), QPoint(0, window.folder.height())
    ).y()
    assert folder_bottom < window.progress.geometry().top()
    window.close()


def test_full_output_filename_and_vertical_order_buttons(app, tmp_path):
    """Full filenames must not gain doubled extensions; arrows sit beside the list."""
    source = tmp_path / "sample.mpt"
    source.touch()
    window = MainWindow()
    window.append_files([source])
    assert window.table.item(0, 1).text() == "sample.csv"
    window.keep_names.setChecked(False)
    window.table.item(0, 1).setText("renamed.csv")
    assert window.make_job().outputs[0].name == "renamed.csv"
    window.format_box.setCurrentText("Parquet")
    assert window.table.item(0, 1).text() == "renamed.parquet"
    assert window.make_job().outputs[0].name == "renamed.parquet"
    window.merge_box.setChecked(True)
    window.show()
    app.processEvents()
    assert window.up.geometry().left() > window.table.geometry().right()
    assert window.up.geometry().top() < window.down.geometry().top()
    window.close()


def test_worker_errors_and_warnings_identify_the_input(app, tmp_path):
    """Real worker logs must identify the acquisition, not internal source files."""
    missing = tmp_path / "missing-current.csv"
    frame = canonical([0, 1, 2])
    frame.loc[1, "current_mA"] = float("nan")
    frame.to_csv(missing, index=False)
    window = MainWindow()
    window.append_files([missing])
    window.start()
    wait_until(app, lambda: window.workspace is None)
    log = window.details.toPlainText()
    assert log.count("MissingValueWarning") == 1
    assert str(missing) in log
    window.remove_all()
    invalid = tmp_path / "bad-time.csv"
    canonical([0, 2, 1]).to_csv(invalid, index=False)
    window.append_files([invalid])
    window.start()
    wait_until(app, lambda: window.workspace is None)
    assert str(invalid) in window.details.toPlainText()
    assert "NonMonotonicTimeError" in window.details.toPlainText()
    window.close()


def test_interface_symbols_are_not_mojibake(app, tmp_path):
    """Check displayed controls and Help after a regression in UTF-8 decoding."""
    window = MainWindow()
    try:
        window.append_files([tmp_path / "sample.csv"])
        button = window.table.cellWidget(0, 2)
        assert isinstance(button, QPushButton)
        assert button.text() == "\u00d7"
        assert window.up.text() == "\u2191  Move up"
        assert window.down.text() == "\u2193  Move down"
        assert window.browse.text() == "Browse\u2026"
        dialog = window.help_dialog()
        try:
            browser = dialog.findChild(QTextBrowser)
            assert browser is not None
            text = browser.toPlainText()
            assert "Orange \u2014 warning:" in text
            assert "Green \u2014 saved:" in text
            assert "Red \u2014 error:" in text
        finally:
            dialog.close()
    finally:
        window.close()
