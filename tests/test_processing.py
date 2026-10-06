# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Protect streaming equivalence, missing-row preservation and safe publication."""

import battread
import numpy as np
import pandas as pd
import pytest

from battread_gui.models import CancelledError, Job, validate_name
from battread_gui.processing import (
    TimingSummary,
    merge_offsets,
    run_job,
)


def canonical(times: list[float]) -> pd.DataFrame:
    """Construct synthetic measured values whose sign and row identity must survive."""
    return pd.DataFrame(
        {
            "time_s": times,
            "current_mA": np.arange(len(times), dtype=float) - 2,
            "voltage_V": np.full(len(times), 3.7),
        },
        dtype="float64",
    )


def noop() -> None:
    """Provide the no-cancellation callback for ordinary processing tests."""


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 50])
@pytest.mark.parametrize(
    "times",
    [
        [[0, 2, 4], [0, 1, 5], [0, 3]],
        [[0], [0, 2]],
        [[0, 0], [0, 2, 7]],
        [[np.nan, 0, 2, np.nan, 9], [0, np.nan, 4, 8, np.nan]],
        [[0, np.nan, 5], [0, 3, np.nan, 8]],
    ],
)
def test_summary_offsets_match_public_merge(times, chunk_size):
    """Sampling timing metadata must never invent intervals across missing gaps."""
    frames = [canonical(t) for t in times]
    summaries = []
    for frame in frames:
        summary = TimingSummary()
        for start in range(0, len(frame), chunk_size):
            summary.add(frame.iloc[start : start + chunk_size])
        summaries.append(summary)
    offsets = merge_offsets(summaries)
    shifted = []
    for frame, offset in zip(frames, offsets, strict=True):
        copy = frame.copy()
        copy["time_s"] += offset
        shifted.append(copy)
    pd.testing.assert_frame_equal(
        pd.concat(shifted, ignore_index=True), battread.merge(frames)
    )


def test_summary_rejects_missing_join_interval():
    """No adjacency in either source must fail just as the public merge does."""
    summaries = []
    for frame in [canonical([0, np.nan, 2]), canonical([0, np.nan, 3])]:
        summary = TimingSummary()
        summary.add(frame)
        summaries.append(summary)
    with pytest.raises(battread.exceptions.IncompatibleDataError):
        merge_offsets(summaries)


@pytest.mark.parametrize("format", ["csv", "txt", "parquet"])
@pytest.mark.parametrize("merge", [False, True])
def test_processing_round_trip(tmp_path, format, merge):
    """Every format retains ordering, NaNs and measured signs at small chunk sizes."""
    frames = [canonical([0, 2, 4]), canonical([0, 3, 6])]
    frames[0].loc[1, "current_mA"] = np.nan
    sources = tuple(tmp_path / f"input-{i}.parquet" for i in range(2))
    for frame, source in zip(frames, sources, strict=True):
        battread.write(frame, source)
    output_count = 1 if merge else 2
    outputs = tuple(tmp_path / f"output-{i}.{format}" for i in range(output_count))
    workspace = tmp_path / "work"
    workspace.mkdir()
    job = Job(sources, outputs, merge, format, 1024**3, chunk_size=1)
    events = []
    run_job(job, workspace, events.append, noop)
    expected = [battread.merge(frames)] if merge else frames
    for target, frame in zip(outputs, expected, strict=True):
        pd.testing.assert_frame_equal(
            battread.read(target, sep="\t" if format == "txt" else None), frame
        )
    assert events[-1]["phase"] == "Complete"
    assert len([event for event in events if event["phase"] == "Saved"]) == output_count
    assert any(event.get("percent") == 100 for event in events)


def test_cancel_never_publishes_partial_output(tmp_path):
    """Cancellation during staging leaves no incomplete final destination."""
    source = tmp_path / "input.parquet"
    battread.write(canonical([0, 1, 2]), source)
    output = tmp_path / "output.csv"
    workspace = tmp_path / "work"
    workspace.mkdir()
    calls = 0

    def cancel() -> None:
        """Interrupt after processing starts to exercise exception cleanup."""
        nonlocal calls
        calls += 1
        if calls > 3:
            raise CancelledError()

    with pytest.raises(CancelledError):
        run_job(
            Job((source,), (output,), False, "csv", 1024**3, 1), workspace, dict, cancel
        )
    assert not output.exists()
    # Closing all handles is essential for Windows workspace cleanup.
    for path in workspace.iterdir():
        path.unlink()


def test_output_race_does_not_overwrite(tmp_path):
    """A competing file created after preflight must remain untouched."""
    source = tmp_path / "input.parquet"
    battread.write(canonical([0, 1, 2]), source)
    output = tmp_path / "output.csv"
    workspace = tmp_path / "work"
    workspace.mkdir()

    def race(event) -> None:
        """Create an unrelated destination immediately before publication."""
        if event.get("phase") == "Writing":
            output.write_text("unrelated", encoding="utf-8")

    run_job(Job((source,), (output,), False, "csv", 1024**3), workspace, race, noop)
    assert output.read_text() == "unrelated"
    pd.testing.assert_frame_equal(
        battread.read(tmp_path / "output (2).csv"), canonical([0, 1, 2])
    )


@pytest.mark.parametrize(
    "name", ["", "..", "../escape", "CON", "COM1", "a.", "a ", "a:b"]
)
def test_invalid_windows_names(name):
    """Output names cannot escape their folder or refer to Windows devices."""
    with pytest.raises(ValueError):
        validate_name(name)


def test_destination_conflicts(tmp_path):
    """A conversion must reject replacement of its own input before reading."""
    source = tmp_path / "input.csv"
    source.touch()
    with pytest.raises(ValueError, match="input file"):
        Job((source,), (source,), False, "csv", 1024**3).validate()


def test_invalid_scientific_input(tmp_path):
    """Non-monotonic input fails through battread and does not publish output."""
    source = tmp_path / "input.csv"
    canonical([0, 2, 1]).to_csv(source, index=False)
    output = tmp_path / "out.csv"
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(battread.exceptions.NonMonotonicTimeError):
        run_job(Job((source,), (output,), False, "csv", 1024**3, 1), work, dict, noop)
    assert not output.exists()


def test_many_chunk_summary_has_constant_size():
    """Large acquisitions retain a bounded summary instead of per-row metadata."""
    summary = TimingSummary()
    for index in range(100):
        summary.add(canonical([index * 2, index * 2 + 1]))
    assert len(summary.frame()) <= 11
    assert summary.rows == 200


def test_canonical_txt_with_empty_cells_is_reusable(tmp_path):
    """Exact canonical TXT headers establish tabs without collapsing missing cells."""
    frame = canonical([0, 1, 2])
    frame.loc[1, "current_mA"] = np.nan
    source = tmp_path / "input.txt"
    battread.write(frame, source)
    output = tmp_path / "output.parquet"
    work = tmp_path / "work"
    work.mkdir()
    run_job(Job((source,), (output,), False, "parquet", 1024**3, 1), work, dict, noop)
    pd.testing.assert_frame_equal(battread.read(output), frame)


def test_separate_mode_keeps_completed_outputs_after_later_failure(tmp_path):
    """Independent processing releases staging and retains prior valid results."""
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    canonical([0, 1, 2]).to_csv(first, index=False)
    canonical([0, 2, 1]).to_csv(second, index=False)
    outputs = (tmp_path / "one.parquet", tmp_path / "two.parquet")
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(battread.exceptions.NonMonotonicTimeError):
        run_job(
            Job((first, second), outputs, False, "parquet", 1024**3, 1),
            work,
            dict,
            noop,
        )
    assert battread.read(outputs[0]).equals(canonical([0, 1, 2]))
    assert not outputs[1].exists()
    assert not list(work.iterdir())
