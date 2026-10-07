# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build bounded, explainable column-choice requests using battread's public API.

Requests contain metadata and at most five short preview cells per candidate.
Preview text never establishes a scientific meaning and is never logged or saved.
Binary readers provide metadata without attempting a second vendor decoder.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, cast

import battread
from battread.exceptions import AmbiguousColumnError, MissingColumnError
from battread.recognition import resolve_quantity
from battread.recognition.models import InspectionResult, KnownQuantity

Selectors = dict[str, str | int]
Units = dict[str, str]


def text_samples(source: Path, details: InspectionResult) -> dict[int, list[str]]:
    """Read a 64 KiB text prefix for display only; incomplete previews are optional."""
    if source.suffix.lower() not in {".csv", ".txt", ".mpt"}:
        return {}
    if details.delimiter not in {",", ";", "\t"} or not details.encoding:
        return {}
    try:
        with source.open("rb") as stream:
            text = stream.read(65_536).decode(details.encoding, errors="replace")
        labels = [str(match.source_column) for match in details.columns]
        rows = csv.reader(io.StringIO(text), delimiter=details.delimiter)
        for row in rows:
            if row == labels:
                break
        else:
            return {}
        samples: dict[int, list[str]] = {}
        for _, row in zip(range(5), rows, strict=False):
            for position, cell in enumerate(row[: len(labels)]):
                samples.setdefault(position, []).append(cell[:120])
        return samples
    except (OSError, UnicodeError, csv.Error):
        return {}


def choice_request(source: Path, columns: Selectors, units: Units) -> dict[str, Any]:
    """Describe the next unresolved quantity, retaining exact duplicate positions."""
    details = battread.inspect(source, columns=columns, units=units)
    quantities: tuple[KnownQuantity, ...] = ("time", "voltage", "current", "capacity")
    for quantity in quantities:
        try:
            resolve_quantity(details.columns, quantity)
        except MissingColumnError:
            continue
        except AmbiguousColumnError:
            samples = text_samples(source, details)
            candidates = [
                {
                    "position": match.source_position,
                    "label": str(match.source_column),
                    "unit": match.unit,
                    "evidence": list(match.evidence),
                    "samples": samples.get(match.source_position, []),
                }
                for match in details.columns
                if match.quantity == quantity
                and match.state in {"resolved", "ambiguous", "explicit"}
            ]
            return {
                "source": str(source),
                "quantity": quantity,
                "candidates": candidates,
            }
    raise AmbiguousColumnError("No safely selectable candidate group was found.")


def apply_choice(
    request: dict[str, Any], response: dict[str, Any], columns: Selectors, units: Units
) -> tuple[Selectors, Units]:
    """Validate a reply against the offered positions and compatible physical units."""
    from battread.normalization.units import conversion_factor

    position = response.get("position")
    if type(position) is not int or position not in {
        item["position"] for item in request["candidates"]
    }:
        raise ValueError("Choose one of the offered source columns.")
    unit = response.get("unit")
    if not isinstance(unit, str) or not unit:
        raise ValueError("Choose the source unit explicitly.")
    quantity = str(request["quantity"])
    conversion_factor(cast(KnownQuantity, quantity), unit)
    selected, scales = columns.copy(), units.copy()
    selected[quantity], scales[quantity] = position, unit
    if selected == columns and scales == units:
        raise ValueError("The choice did not resolve the ambiguity.")
    return selected, scales
