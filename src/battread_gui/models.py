# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Validate destination plans before a worker touches scientific input files."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

OutputFormat = Literal["csv", "txt", "parquet"]


def available_destination(path: Path, reserved: set[Path] | None = None) -> Path:
    """Choose an unused output name, adding (2), (3), etc. without overwriting.

    Reserved resolved paths protect other planned outputs and inputs. Final
    publication must still use a no-clobber operation to handle creation races.
    """
    protected: set[Path] = reserved if reserved is not None else set()
    candidate = path
    number = 2
    stem = path.stem
    match = re.fullmatch(r"(.+) \((\d+)\)", stem)
    if match is not None and int(match.group(2)) >= 2:
        stem = match.group(1)
        number = int(match.group(2)) + 1
    while (
        candidate.exists() or candidate.is_symlink() or candidate.resolve() in protected
    ):
        candidate = path.with_name(f"{stem} ({number}){path.suffix}")
        number += 1
    return candidate


def output_filename(name: str, format: str) -> str:
    """Use the selected format on a complete filename without duplicating suffixes.

    Also accept an extension-free user entry for convenience. An existing known
    output extension is replaced when the format changes; validation stays at
    the job boundary so partially typed names do not interrupt editing.
    """
    suffix = Path(name).suffix
    if suffix.lower() in {".csv", ".txt", ".parquet"}:
        name = name[: -len(suffix)]
    return f"{name}.{format}"


class CancelledError(Exception):
    """Signal cooperative cancellation before another chunk or publication."""


@dataclass(frozen=True)
class Job:
    """Immutable conversion plan, serialized locally for the isolated worker.

    Inputs remain in acquisition order. Separate mode requires one destination
    per input; merge requires one destination. The byte budget caps committed
    allocations on Windows and also limits sampled RSS. No output may exist.
    """

    inputs: tuple[Path, ...]
    outputs: tuple[Path, ...]
    merge: bool
    format: OutputFormat
    memory_limit: int
    chunk_size: int = 50_000

    def validate(self) -> None:
        """Reject invalid plans, aliases, unsafe names and overwrite conflicts.

        Raise ValueError with an English explanation. This check is repeated by
        the worker; final publication also checks races without overwriting.
        """
        if not self.inputs:
            raise ValueError("Add at least one input file.")
        if self.format not in {"csv", "txt", "parquet"}:
            raise ValueError("Choose CSV, TXT or Parquet.")
        if self.chunk_size <= 0 or self.memory_limit <= 0:
            raise ValueError("Chunk size and memory budget must be positive.")
        expected = 1 if self.merge else len(self.inputs)
        if len(self.outputs) != expected:
            raise ValueError("The number of output paths does not match the mode.")
        sources = {p.resolve() for p in self.inputs}
        if len(sources) != len(self.inputs):
            raise ValueError("The same input file was selected more than once.")
        destinations: set[Path] = set()
        for source in self.inputs:
            if not source.is_file():
                raise ValueError(f"Input file does not exist: {source.name}")
        for output in self.outputs:
            target = output.resolve()
            if target in sources:
                raise ValueError("An output path would replace an input file.")
            if target in destinations:
                raise ValueError("Two outputs have the same destination name.")
            destinations.add(target)
            if not output.parent.is_dir():
                raise ValueError("Choose an existing output directory.")
            if output.exists():
                raise ValueError(f"Output already exists: {output.name}")
            if output.suffix.lower() != f".{self.format}":
                raise ValueError("Output extension does not match the chosen format.")
            validate_name(output.stem)


def validate_name(name: str) -> str:
    """Return a Windows-safe base name or raise ValueError; never repair silently.

    The UI appends the selected extension. Reserved device names, path traversal,
    separators and trailing spaces/dots would create surprising destinations.
    """
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10))
    if (
        not name
        or name in {".", ".."}
        or name.endswith((" ", "."))
        or any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name)
        or name.split(".")[0].upper() in reserved
        or len(name) > 180
    ):
        raise ValueError(f"Invalid output base name: {name!r}")
    return name
