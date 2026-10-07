# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regress explicit choices, bounded previews and real worker pause/resume."""

from pathlib import Path

import battread
import pytest
from PySide6.QtWidgets import QDialogButtonBox
from test_app import wait_until

from battread_gui.app import MainWindow
from battread_gui.column_choices import apply_choice, choice_request
from battread_gui.column_dialog import ColumnChoiceDialog


def ambiguous_csv(path: Path, duplicate_voltage: bool = False) -> None:
    """Write independent measured alternatives with identical source labels."""
    voltage = "Voltage(V),Voltage(V)" if duplicate_voltage else "voltage_V"
    first = "3.5,4.1" if duplicate_voltage else "3.5"
    second = "3.6,4.2" if duplicate_voltage else "3.6"
    path.write_text(
        f"time_s,Current(mA),Current(mA),{voltage}\n10,-1,2,{first}\n12,-3,4,{second}\n"
    )


def test_choice_candidates_preserve_positions_and_samples(tmp_path):
    """Identically named candidates remain distinct and preview text is bounded."""
    source = tmp_path / "ambiguous.csv"
    ambiguous_csv(source)
    request = choice_request(source, {}, {})
    assert request["quantity"] == "current"
    assert [item["position"] for item in request["candidates"]] == [1, 2]
    assert request["candidates"][1]["samples"] == ["2", "4"]
    columns, units = apply_choice(request, {"position": 2, "unit": "mA"}, {}, {})
    result = battread.read(source, columns=columns, units=units)
    assert result.current_mA.tolist() == [2, 4]
    for reply in (
        {"position": 99, "unit": "mA"},
        {"position": True, "unit": "mA"},
        {"position": 2, "unit": ""},
    ):
        with pytest.raises(ValueError):
            apply_choice(request, reply, {}, {})
    with pytest.raises(battread.exceptions.InvalidUnitError):
        apply_choice(request, {"position": 2, "unit": "V"}, {}, {})


def test_dialog_requires_explicit_candidate_and_retains_private_preview(app, tmp_path):
    """Continue stays disabled until a position is chosen; a known unit is displayed."""
    source = tmp_path / "ambiguous.csv"
    ambiguous_csv(source)
    dialog = ColumnChoiceDialog(choice_request(source, {}, {}))
    try:
        button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert not button.isEnabled()
        dialog.column.setCurrentIndex(2)
        assert button.isEnabled()
        assert "2, 4" in dialog.preview.toPlainText()
        assert dialog.selection() == {"position": 2, "unit": "mA"}
    finally:
        dialog.close()


def test_real_worker_resumes_multiple_ambiguities_without_duplicating_rows(
    app, tmp_path
):
    """Two replies resume the same worker and preserve the measurement rows."""
    source = tmp_path / "ambiguous.csv"
    ambiguous_csv(source, duplicate_voltage=True)
    window = MainWindow()
    try:
        window.append_files([source])
        window.start()
        for quantity in ("voltage", "current"):
            wait_until(app, lambda: window.column_dialog is not None)
            dialog = window.column_dialog
            assert dialog is not None and dialog.request["quantity"] == quantity
            assert window.workspace is not None
            dialog.column.setCurrentIndex(2)
            dialog.accept()
            assert window.column_dialog is None
        wait_until(app, lambda: window.workspace is None)
        assert window.saved == 1, window.details.toPlainText()
        result = battread.read(tmp_path / "ambiguous_standardized.csv")
        assert result.time_s.tolist() == [0, 2]
        assert result.current_mA.tolist() == [2, 4]
        assert result.voltage_V.tolist() == [4.1, 4.2]
        assert "Examples:" not in window.details.toPlainText()
        assert not list(tmp_path.glob(".battread-work-*"))
    finally:
        window.close()


def test_cancel_during_column_choice_cleans_workspace(app, tmp_path):
    """Rejecting the prompt cooperatively cancels and publishes no partial output."""
    source = tmp_path / "ambiguous.csv"
    ambiguous_csv(source)
    window = MainWindow()
    try:
        window.append_files([source])
        window.start()
        wait_until(app, lambda: window.column_dialog is not None)
        window.column_dialog.reject()
        wait_until(app, lambda: window.workspace is None)
        assert "Cancelled" in window.status.text()
        assert not (tmp_path / "ambiguous_standardized.csv").exists()
        assert not list(tmp_path.glob(".battread-work-*"))
    finally:
        window.close()


def test_separate_outputs_are_not_reprocessed_after_a_choice(app, tmp_path):
    """An already saved first file survives while the second waits for user input."""
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    first.write_text("time_s,current_mA,voltage_V\n0,-1,3.5\n1,2,3.6\n")
    ambiguous_csv(second)
    window = MainWindow()
    try:
        window.append_files([first, second])
        window.start()
        wait_until(app, lambda: window.column_dialog is not None)
        assert window.saved == 1
        first_output = tmp_path / "first_standardized.csv"
        original = first_output.read_bytes()
        window.column_dialog.column.setCurrentIndex(2)
        window.column_dialog.accept()
        wait_until(app, lambda: window.workspace is None)
        assert window.saved == 2
        assert first_output.read_bytes() == original
        assert not (tmp_path / "first_standardized (2).csv").exists()
    finally:
        window.close()


def test_source_change_during_choice_is_not_silently_reprocessed(tmp_path):
    """A stale positional choice must not be applied to a modified acquisition."""
    from battread_gui.processing import checked_chunks

    source = tmp_path / "changed.csv"
    ambiguous_csv(source)

    def choose(path, columns, units):
        """Simulate editing the source while a real column request is pending."""
        path.write_text(path.read_text() + "14,-5,6,3.7\n")
        return {"current": 2}, {"current": "mA"}

    with pytest.raises(
        battread.exceptions.IncompatibleDataError, match="Source changed"
    ):
        list(checked_chunks(source, 1, lambda: None, resolve=choose))


def test_cancel_during_merge_choice_preserves_no_partial_merged_output(app, tmp_path):
    """Cancel a later choice without publishing an incomplete merged file."""
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    first.write_text("time_s,current_mA,voltage_V\n0,-1,3.5\n1,2,3.6\n")
    ambiguous_csv(second)
    window = MainWindow()
    try:
        window.append_files([first, second])
        window.merge_box.setChecked(True)
        window.merge_name.setText("combined.csv")
        window.start()
        wait_until(app, lambda: window.column_dialog is not None)
        assert window.saved == 0
        window.cancel()
        wait_until(app, lambda: window.workspace is None)
        assert not (tmp_path / "combined.csv").exists()
        assert not list(tmp_path.glob(".battread-work-*"))
    finally:
        window.close()
