# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disk-backed conversions that preserve battread's public merge semantics.

All inputs are standardized through iter_read(), then staged as canonical
Parquet. Only chunk buffers and small timing summaries stay in RAM. Timing
summaries preserve the exact first/last adjacent positive intervals, so calling
the public merge() on them establishes offsets without loading acquisitions.
"""

from __future__ import annotations

import math
import os
import tempfile
import warnings
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Any, cast

import battread
import numpy as np
import pandas as pd
import pyarrow as pa  # pyright: ignore[reportMissingTypeStubs]
import pyarrow.parquet as pq  # pyright: ignore[reportMissingTypeStubs]
from battread.exceptions import AmbiguousColumnError, IncompatibleDataError
from battread.warnings import MissingValueWarning
from numpy.typing import NDArray

from battread_gui.column_choices import Selectors, Units
from battread_gui.models import Job, OutputFormat, available_destination

ColumnResolver = Callable[[Path, Selectors, Units], tuple[Selectors, Units]]

# Arrow's runtime APIs have no complete typing stubs. Keep the untyped boundary
# inside serialization; all application plans and callbacks remain typed.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

Event = dict[str, Any]
Notify = Callable[[Event], None]
Check = Callable[[], None]
Point = tuple[int, float]
Pair = tuple[Point, Point]


@dataclass
class TimingSummary:
    """Constant-size timing evidence for a validated standardized acquisition.

    Call add() in chunk order, then frame() after iterator exhaustion. Original
    row positions preserve adjacency, including across chunks and NaN gaps.
    """

    rows: int = 0
    first: Point | None = None
    last: Point | None = None
    first_pair: Pair | None = None
    last_pair: Pair | None = None
    previous: float = math.nan

    def add(self, frame: pd.DataFrame) -> None:
        """Accumulate finite endpoints and adjacent intervals without storing rows."""
        values = cast(NDArray[np.float64], frame["time_s"].to_numpy(dtype="float64"))
        finite = np.flatnonzero(np.isfinite(values))
        if finite.size:
            first_index, last_index = int(finite[0]), int(finite[-1])
            if self.first is None:
                self.first = (self.rows + first_index, float(values[first_index]))
            self.last = (self.rows + last_index, float(values[last_index]))
        if values.size:
            left = np.concatenate(([self.previous], values[:-1]))
            positive = np.flatnonzero(
                np.isfinite(left) & np.isfinite(values) & (values > left)
            )
            if positive.size:
                for index in {int(positive[0]), int(positive[-1])}:
                    pair = (
                        (self.rows + index - 1, float(left[index])),
                        (self.rows + index, float(values[index])),
                    )
                    if self.first_pair is None or pair[0][0] < self.first_pair[0][0]:
                        self.first_pair = pair
                    if self.last_pair is None or pair[0][0] > self.last_pair[0][0]:
                        self.last_pair = pair
            self.previous = float(values[-1])
        self.rows += len(frame)

    def frame(self) -> pd.DataFrame:
        """Build a tiny canonical frame containing exactly the needed evidence.

        Insert NaN separators wherever original positions were not adjacent.
        Otherwise sampling could invent an interval across a missing-data gap.
        Synthetic separators are only metadata; they never enter actual output.
        """
        if self.first is None or self.last is None:
            raise ValueError("The acquisition has no finite canonical time.")
        points = dict((self.first, self.last))
        for pair in (self.first_pair, self.last_pair):
            if pair is not None:
                points.update(pair)
        times: list[float] = []
        previous_position: int | None = None
        for position, value in sorted(points.items()):
            if previous_position is not None and position != previous_position + 1:
                times.append(math.nan)
            times.append(value)
            previous_position = position
        return pd.DataFrame(
            {
                "time_s": times,
                "current_mA": np.zeros(len(times)),
                "voltage_V": np.zeros(len(times)),
            },
            dtype="float64",
        )


def merge_offsets(summaries: list[TimingSummary]) -> list[float]:
    """Ask public battread.merge() to determine scientifically identical offsets.

    The summaries preserve all boundary evidence consumed by that function.
    Its explicit failure when neither neighbor has an adjacent positive interval
    is propagated. Only synthetic-summary missing-value warnings are suppressed.
    """
    frames = [summary.frame() for summary in summaries]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MissingValueWarning)
        merged = battread.merge(frames)
    offsets: list[float] = []
    start = 0
    for frame in frames:
        offsets.append(float(merged["time_s"].iloc[start]))
        start += len(frame)
    return offsets


class Sink(AbstractContextManager["Sink"]):
    """Append standardized chunks to a private staged file, then close its footer.

    Use inside a context; publish separately only after full iterator exhaustion.
    CSV/TXT follow battread's canonical dialect and preserve NaN as blank cells.
    """

    def __init__(self, path: Path, format: OutputFormat) -> None:
        """Remember the temporary path and defer resource allocation until entry."""
        self.path = path
        self.format = format
        self.stream: IO[str] | None = None
        self.writer: Any = None
        self.first = True

    def __enter__(self) -> Sink:
        """Open a text stream; Parquet schema is established by the first chunk."""
        if self.format != "parquet":
            self.stream = self.path.open("w", encoding="utf-8", newline="")
        return self

    def append(self, frame: pd.DataFrame) -> None:
        """Write a single canonical fragment without an index or repeated header."""
        if self.format == "parquet":
            table = pa.Table.from_pandas(frame, preserve_index=False)
            if self.writer is None:
                self.writer = pq.ParquetWriter(self.path, table.schema)
            self.writer.write_table(table)
        else:
            if self.stream is None:
                raise RuntimeError("The output sink must be entered first.")
            frame.to_csv(
                self.stream,
                sep="," if self.format == "csv" else "\t",
                header=self.first,
                index=False,
            )
        self.first = False

    def __exit__(self, *exc_info: object) -> None:
        """Release handles both on success and on a processing exception."""
        if self.stream is not None:
            self.stream.close()
        if self.writer is not None:
            self.writer.close()


def checked_chunks(
    source: Path,
    chunk_size: int,
    check: Check,
    *,
    report_missing: bool = True,
    resolve: ColumnResolver | None = None,
) -> Iterator[pd.DataFrame]:
    """Read chunks while optionally deferring missing-value reports to a summary.

    Only MissingValueWarning is filtered. Parsing warnings, scientific failures,
    cancellation and missing rows are unchanged. Staged reads must not report the
    original missing cells a second time.
    """
    with warnings.catch_warnings():
        if not report_missing:
            warnings.simplefilter("ignore", MissingValueWarning)
        yield from _source_chunks(source, chunk_size, check, resolve)


def _source_chunks(
    source: Path, chunk_size: int, check: Check, resolve: ColumnResolver | None = None
) -> Iterator[pd.DataFrame]:
    """Read through the public API with cancellation checks and guaranteed cleanup.

    Use the installed library's streaming reader and verified format definitions;
    do not duplicate vendor decoding here. Select a unique Bio-Logic Ewe/V label
    explicitly, preserving normal recognition when it is absent and failures for
    duplicate labels. The optional resolver pauses only before any source rows
    are emitted, then retries with explicit positional mappings and units.
    Reject sources modified during the pause. Close every iterator on completion,
    retry or cancellation.
    """
    separator: str | None = None
    if source.suffix.lower() == ".txt":
        # Upstream delimiter detection may prefer whitespace when blank cells
        # occur. Only the exact canonical tab header establishes this dialect.
        with source.open("rb") as stream:
            if stream.readline(128).strip() == b"time_s\tcurrent_mA\tvoltage_V":
                separator = "\t"
    columns: Selectors = {}
    if source.suffix.lower() in {".mpr", ".mpt"}:
        check()
        details = battread.inspect(source)
        # The maintainer explicitly chose Ewe/V over its averaged alternative.
        # Apply this preference only to an exact, unique Bio-Logic label. Missing
        # labels keep normal recognition; duplicate labels still fail explicitly.
        if sum(match.source_column == "Ewe/V" for match in details.columns) == 1:
            columns["voltage"] = "Ewe/V"
    units: Units = {}
    initial_stat = source.stat()
    emitted = False
    while True:
        iterator = battread.iter_read(
            source, chunk_size=chunk_size, sep=separator, columns=columns, units=units
        )
        try:
            while True:
                check()
                try:
                    frame = next(iterator)
                except StopIteration:
                    return
                check()
                emitted = True
                yield frame
        except AmbiguousColumnError:
            # Column selection precedes measurements. Never restart a source
            # after emitting rows, which could duplicate a partially staged file.
            if resolve is None or emitted:
                raise
            columns, units = resolve(source, columns, units)
            current_stat = source.stat()
            if (
                current_stat.st_size,
                current_stat.st_mtime_ns,
                current_stat.st_ino,
            ) != (initial_stat.st_size, initial_stat.st_mtime_ns, initial_stat.st_ino):
                raise IncompatibleDataError(
                    "Source changed during column selection. Restart processing."
                ) from None
            check()
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()


def run_job(
    job: Job,
    workspace: Path,
    notify: Notify,
    check: Check,
    output_workspaces: Mapping[Path, Path] | None = None,
    resolve: ColumnResolver | None = None,
) -> None:
    """Standardize and write a validated job with bounded tabular buffers.

    workspace must be private. For destinations on multiple volumes, the parent
    supplies output_workspaces keyed by resolved destination folders and removes
    every root after worker exit. Progress percentages cover measurable
    writing rows; reading reports phase, file count and rows without pretending
    to know remaining work. Completed separate outputs survive later failures.
    """
    protected = {p.resolve() for p in job.inputs}
    destinations: list[Path] = []
    for requested in job.outputs:
        target = available_destination(requested, protected)
        destinations.append(target)
        protected.add(target.resolve())
    job = replace(job, outputs=tuple(destinations))
    job.validate()
    if not job.merge and len(job.inputs) > 1:
        # Independent files do not need to coexist on disk. Finish and release
        # each staged acquisition before reading the next one; a later failure
        # must not remove earlier successfully published results.
        for index, (source, target) in enumerate(
            zip(job.inputs, job.outputs, strict=True)
        ):
            check()

            def forward(event: Event, file_index: int = index) -> None:
                """Keep parent file counts without reporting premature completion."""
                if event.get("phase") == "Complete":
                    return
                adjusted = event.copy()
                if "file" in adjusted:
                    adjusted.update(file=file_index + 1, files=len(job.inputs))
                notify(adjusted)

            single = Job(
                (source,),
                (target,),
                False,
                job.format,
                job.memory_limit,
                job.chunk_size,
            )
            root = (
                output_workspaces[target.parent.resolve()]
                if output_workspaces is not None
                else workspace
            )
            with tempfile.TemporaryDirectory(prefix="file-", dir=root) as name:
                run_job(single, Path(name), forward, check, resolve=resolve)
        notify({"phase": "Complete", "percent": 100})
        return
    summaries: list[TimingSummary] = []
    stages: list[Path] = []
    for index, source in enumerate(job.inputs):
        check()
        stage = workspace / f"source-{index}.parquet"
        summary = TimingSummary()
        missing_counts: dict[str, int] = {}
        notify(
            {
                "phase": "Reading",
                "file": index + 1,
                "files": len(job.inputs),
                "source": str(source),
            }
        )
        with Sink(stage, "parquet") as sink:
            for frame in checked_chunks(
                source, job.chunk_size, check, report_missing=False, resolve=resolve
            ):
                for column in battread.CANONICAL_COLUMNS:
                    count = int(frame[column].isna().sum())
                    if count:
                        missing_counts[column] = missing_counts.get(column, 0) + count
                summary.add(frame)
                sink.append(frame)
                notify(
                    {
                        "phase": "Reading and standardizing",
                        "file": index + 1,
                        "files": len(job.inputs),
                        "rows": summary.rows,
                        "source": str(source),
                    }
                )
        if missing_counts:
            # Count actual standardized rows exactly once, independently of how
            # often readers validate chunks or the internal staging file.
            warnings.warn_explicit(
                MissingValueWarning(missing_counts),
                MissingValueWarning,
                filename=str(source),
                lineno=1,
            )
        summaries.append(summary)
        stages.append(stage)
    check()
    if job.merge:
        notify(
            {
                "phase": "Preparing merge",
                "source": "Merge inputs: " + "; ".join(str(p) for p in job.inputs),
            }
        )
    offsets = merge_offsets(summaries) if job.merge else [0.0] * len(stages)
    groups = (
        [list(range(len(stages)))] if job.merge else [[i] for i in range(len(stages))]
    )
    for output_index, indices in enumerate(groups):
        destination = job.outputs[output_index]
        temporary = workspace / f"result-{output_index}.{job.format}"
        total = sum(summaries[i].rows for i in indices)
        written = 0
        with Sink(temporary, job.format) as sink:
            for index in indices:
                for frame in checked_chunks(
                    stages[index], job.chunk_size, check, report_missing=False
                ):
                    # Each stage was already validated. Shift only time; all
                    # measured and missing current/voltage values are retained.
                    if offsets[index] != 0:
                        frame["time_s"] = frame["time_s"] + offsets[index]
                    sink.append(frame)
                    written += len(frame)
                    notify(
                        {
                            "phase": "Writing",
                            "percent": int(written * 100 / total),
                            "file": output_index + 1,
                            "files": len(job.outputs),
                            "rows": written,
                            "source": str(job.inputs[index]),
                        }
                    )
        check()
        # A hard link is atomic and cannot clobber an existing path. Both paths
        # are on the same volume. Never fall back to an unsafe rename on error.
        reserved = {
            p.resolve() for p in (*job.inputs, *job.outputs) if p != destination
        }
        requested_destination = destination
        while True:
            check()
            try:
                os.link(temporary, destination)
                break
            except FileExistsError:
                destination = available_destination(requested_destination, reserved)
        notify({"phase": "Saved", "output": str(destination)})
    notify({"phase": "Complete", "percent": 100})
