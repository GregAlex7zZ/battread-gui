# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Protect automatic naming, readable feedback and source metadata presentation."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QTextBrowser

from battread_gui.app import HELP, MainWindow
from battread_gui.models import available_destination


def test_numbered_names_preserve_existing_files(tmp_path):
    """Choose consecutive suffixes while protecting files and planned destinations."""
    first = tmp_path / "result.csv"
    second = tmp_path / "result (2).csv"
    first.write_text("original")
    second.write_text("other")
    assert available_destination(first).name == "result (3).csv"
    assert available_destination(second).name == "result (3).csv"
    assert (
        available_destination(first, {(tmp_path / "result (3).csv").resolve()}).name
        == "result (4).csv"
    )
    assert first.read_text() == "original"
    assert second.read_text() == "other"


def test_message_colors_are_independent_and_text_is_literal(app):
    """Warnings, saves and errors keep distinct colors without interpreting markup."""
    window = MainWindow()
    for phase, message, expected in (
        ("Warning", "warning <tag>", "#a65b00"),
        ("Saved", "saved.csv", "#16723c"),
        ("Error", "blocking error", "#b42318"),
    ):
        event = {"phase": phase, "message": message, "output": message}
        window.handle_event(event)
        cursor = window.details.document().find(message)
        assert not cursor.isNull()
        assert cursor.charFormat().foreground().color().name() == expected
    assert "<tag>" in window.details.toPlainText()
    assert "Orange" in HELP and "Green" in HELP and "Red" in HELP
    window.close()


@pytest.mark.parametrize("available_gib", [1, 8, 20])
def test_size_before_processing_and_memory_budget(
    app, tmp_path, monkeypatch, available_gib
):
    """Input weight is exact metadata; RAM policy is a separate available-memory cap."""
    source = tmp_path / "example.mpt"
    source.write_bytes(b"x" * 2048)
    window = MainWindow()
    window.append_files([source])
    assert "2.0 KB" in window.size_label.text()
    monkeypatch.setattr(
        "battread_gui.app.psutil.virtual_memory",
        lambda: SimpleNamespace(available=available_gib * 1024**3, total=32 * 1024**3),
    )
    assert window.make_job().memory_limit == int(available_gib * 1024**3 * 0.90)
    window.remove_all()
    assert window.size_label.text() == ""
    window.close()


def test_about_contains_author_license_authorship_and_link(app):
    """The local About dialog must expose provenance and the complete GPL text."""
    window = MainWindow()
    dialog = window.about_dialog()
    browsers = dialog.findChildren(QTextBrowser)
    combined = "\n".join(browser.toPlainText() for browser in browsers)
    assert "Alessandro Gregucci" in combined
    assert "Authorship" in combined
    assert any("AUTHORS.md" in browser.toHtml() for browser in browsers)
    assert "GNU GENERAL PUBLIC LICENSE" in combined
    assert "github.com/GregAlex7zZ/battread" in combined
    assert any(browser.openExternalLinks() for browser in browsers)
    dialog.close()
    window.close()


def test_save_as_is_editable_when_names_unlocked(app, tmp_path):
    """A real keyboard edit must persist in Save as after unchecking Keep names."""
    source = tmp_path / "example.mpt"
    source.touch()
    window = MainWindow()
    window.append_files([source])
    window.show()
    window.keep_names.setChecked(False)
    window.table.setCurrentCell(0, 1)
    QTest.keyClick(window.table, Qt.Key.Key_F2)
    app.processEvents()
    editor = window.table.findChild(QLineEdit)
    assert editor is not None
    editor.selectAll()
    QTest.keyClicks(editor, "renamed.csv")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    app.processEvents()
    assert window.make_job().outputs[0].name == "renamed.csv"
    window.close()
