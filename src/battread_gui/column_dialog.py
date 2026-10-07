# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Nonblocking, monochrome dialog for one explicit scientific column choice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class ColumnChoiceDialog(QDialog):
    """Show candidate examples and confirm a position plus source unit."""

    def __init__(self, request: dict[str, Any], parent: QWidget | None = None) -> None:
        """Construct a modeless request with no automatically confirmed selection."""
        super().__init__(parent)
        self.request = request
        self.setWindowTitle("Choose column")
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setText(
            f"{Path(request['source']).name}\nChoose the {request['quantity']} column."
        )
        layout.addWidget(label)
        self.column = QComboBox()
        self.column.addItem("Select a column", None)
        for candidate in request["candidates"]:
            self.column.addItem(
                f"{candidate['label']} (column {candidate['position'] + 1})",
                candidate["position"],
            )
        layout.addWidget(self.column)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        layout.addWidget(QLabel("Source unit"))
        self.unit = QComboBox()
        self.unit.addItem("Select a unit", "")
        supported = {
            "time": ("s", "ms", "min", "h"),
            "current": ("mA", "A", "uA"),
            "voltage": ("V", "mV"),
            "capacity": ("mAh", "Ah", "C"),
        }
        for unit in supported[str(request["quantity"])]:
            self.unit.addItem(unit, unit)
        layout.addWidget(self.unit)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continue")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.column.currentIndexChanged.connect(self.update_preview)
        self.unit.currentIndexChanged.connect(self.update_enabled)
        self.update_enabled()

    def update_preview(self) -> None:
        """Show only the chosen candidate's bounded samples and recognition evidence."""
        index = self.column.currentIndex() - 1
        if index < 0:
            self.preview.clear()
            self.unit.setCurrentIndex(0)
        else:
            candidate = self.request["candidates"][index]
            examples = candidate.get("samples", [])
            self.preview.setPlainText(
                "Examples: "
                + (", ".join(examples) if examples else "Preview unavailable")
                + "\n\n"
                + "\n".join(candidate.get("evidence", []))
            )
            source_unit = candidate.get("unit")
            unit_index = self.unit.findData(source_unit)
            if isinstance(source_unit, str) and source_unit and unit_index < 0:
                self.unit.addItem(source_unit, source_unit)
                unit_index = self.unit.count() - 1
            self.unit.setCurrentIndex(max(0, unit_index))
        self.update_enabled()

    def update_enabled(self) -> None:
        """Require both a deliberate column choice and a known source unit."""
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.column.currentIndex() > 0 and bool(self.unit.currentData())
        )

    def selection(self) -> dict[str, Any]:
        """Return the positional mapping confirmed by Continue for the worker."""
        return {"position": self.column.currentData(), "unit": self.unit.currentData()}
