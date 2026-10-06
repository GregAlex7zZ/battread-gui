# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Confirm vendor text profiles pass unchanged through GUI orchestration."""

from pathlib import Path

import battread
import pytest
from battread.exceptions import AmbiguousColumnError

from battread_gui.models import Job
from battread_gui.processing import run_job


def test_accessory_mpr_uses_bounded_reader(
    tmp_path: Path, accessory_mpr: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GUI staging preserves canonical values without the full-memory constructor."""
    from galvani import BioLogic

    def forbidden(*args: object, **kwargs: object) -> None:
        """Make any regression to Galvani's full-source allocation path fail."""
        raise AssertionError("The GUI must use bounded MPR ingestion.")

    monkeypatch.setattr(BioLogic, "MPRfile", forbidden)
    output = tmp_path / "canonical.parquet"
    work = tmp_path / "work"
    work.mkdir()
    run_job(
        Job((accessory_mpr,), (output,), False, "parquet", 1024**3, 1),
        work,
        dict,
        check_no_cancel,
    )
    frame = battread.read(output)
    assert frame.time_s.tolist() == [0.0, 1.0]
    assert frame.current_mA.tolist() == [-2.0, 3.0]
    assert frame.voltage_V.tolist() == [3.5, 3.5]
    assert battread.is_standardized(frame)


def test_biologic_duplicate_voltage_is_not_arbitrarily_selected(tmp_path: Path) -> None:
    """The explicit label preference cannot choose between duplicate Ewe/V columns."""
    source = tmp_path / "duplicate.mpt"
    source.write_text(
        "EC-Lab ASCII FILE\nNb header lines : 3\ntime/s\tI/mA\tEwe/V\tEwe/V\n"
        "10\t-2\t3.5\t9\n",
        encoding="utf-8",
    )
    output = tmp_path / "canonical.csv"
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(AmbiguousColumnError):
        run_job(
            Job((source,), (output,), False, "csv", 1024**3, 1),
            work,
            dict,
            check_no_cancel,
        )
    assert not output.exists()


def test_biologic_binary_voltage_preference(tmp_path: Path) -> None:
    """The same explicit policy applies to binary MPR through the public API."""
    import struct

    def module(name: bytes, version: int, payload: bytes) -> bytes:
        """Encode a synthetic legacy module header independently of the decoder."""
        return (
            b"MODULE"
            + struct.pack("<10s25sII8s", name, name, len(payload), version, b"01/01/24")
            + payload
        )

    header = struct.pack("<IB4H", 2, 4, 4, 8, 6, 77).ljust(405, b"\x00")
    records = struct.pack("<dfff", 10, -2, 3.5, 9) + struct.pack("<dfff", 11, 3, 3.5, 9)
    source = tmp_path / "voltage.mpr"
    source.write_bytes(
        b"BIO-LOGIC MODULAR FILE\x1a".ljust(48)
        + b"\x00" * 4
        + module(b"VMP Set   ", 0, b"")
        + module(b"VMP data  ", 2, header + records)
    )
    output = tmp_path / "canonical.csv"
    work = tmp_path / "work"
    work.mkdir()
    run_job(
        Job((source,), (output,), False, "csv", 1024**3, 1), work, dict, check_no_cancel
    )
    assert battread.read(output).voltage_V.tolist() == [3.5, 3.5]


@pytest.mark.parametrize("header", ["Ewe/V\t<Ewe>/V", "<Ewe>/V\tEwe/V"])
def test_biologic_explicit_voltage_preference(tmp_path: Path, header: str) -> None:
    """The app's explicit policy selects Ewe/V regardless of column order.

    Library callers without a selector still receive an ambiguity error. The
    conflicting synthetic values ensure this test does not assume equivalence.
    """
    source = tmp_path / "voltage.mpt"
    cells = "3.5\t9" if header.startswith("Ewe/V") else "9\t3.5"
    source.write_text(
        f"EC-Lab ASCII FILE\nNb header lines : 3\ntime/s\tI/mA\t{header}\n"
        f"10\t-2\t{cells}\n11\t3\t{cells}\n",
        encoding="utf-8",
    )
    with pytest.raises(AmbiguousColumnError):
        battread.read(source)
    output = tmp_path / "canonical.csv"
    work = tmp_path / "work"
    work.mkdir()
    run_job(
        Job((source,), (output,), False, "csv", 1024**3, 1), work, dict, check_no_cancel
    )
    frame = battread.read(output)
    assert frame.voltage_V.tolist() == [3.5, 3.5]
    assert frame.current_mA.tolist() == [-2, 3]


def test_biologic_average_only_retains_recognition(tmp_path: Path) -> None:
    """A missing Ewe/V label must not prevent a uniquely recognized average."""
    source = tmp_path / "average.mpt"
    source.write_text(
        "EC-Lab ASCII FILE\nNb header lines : 3\ntime/s\tI/mA\t<Ewe>/V\n"
        "10\t-2\t3.5\n11\t3\t3.6\n",
        encoding="utf-8",
    )
    output = tmp_path / "canonical.csv"
    work = tmp_path / "work"
    work.mkdir()
    run_job(
        Job((source,), (output,), False, "csv", 1024**3, 1), work, dict, check_no_cancel
    )
    assert battread.read(output).voltage_V.tolist() == [3.5, 3.6]


def check_no_cancel() -> None:
    """Allow ordinary synthetic conversions to finish without interruption."""


def test_neware_csv_uses_total_time(tmp_path):
    """Step Time resets must not replace recognized Neware Total Time durations."""
    source = tmp_path / "synthetic-neware.csv"
    source.write_text(
        "DataPoint,Step Type,Time,Total Time,Current(mA),Voltage(V),"
        "Capacity(mAh),Energy(Wh),Date,Power(W)\n"
        "1,Rest,00:00:00,25:00:00,0,3,0,0,2025-01-01,0\n"
        "2,Charge,00:00:01,25:00:02.5,-1,3,0,0,2025-01-01,0\n"
        "3,Rest,00:00:00,25:00:03,0,3,0,0,2025-01-01,0\n",
        encoding="utf-8",
    )
    output = tmp_path / "canonical.parquet"
    work = tmp_path / "work"
    work.mkdir()
    run_job(
        Job((source,), (output,), False, "parquet", 1024**3, 1),
        work,
        dict,
        check_no_cancel,
    )
    frame = battread.read(output)
    assert frame.time_s.tolist() == [0, 2.5, 3]
    assert frame.current_mA.tolist() == [0, -1, 0]


def test_biologic_measured_current_precedes_dq(tmp_path):
    """The GUI must keep measured sign rather than reconstructing conflicting dq."""
    source = tmp_path / "synthetic-biologic.mpt"
    source.write_text(
        "EC-Lab ASCII FILE\nNb header lines : 3\n"
        "time/s\tI/mA\tEwe/V\tdq/mA.h\n"
        "10\t-2\t3.5\t0\n11\t-3\t3.6\t1\n12\t4\t3.7\t1\n",
        encoding="utf-8",
    )
    output = tmp_path / "canonical.csv"
    work = tmp_path / "work"
    work.mkdir()
    run_job(
        Job((source,), (output,), False, "csv", 1024**3, 1),
        work,
        dict,
        check_no_cancel,
    )
    frame = battread.read(output)
    assert frame.time_s.tolist() == [0, 1, 2]
    assert frame.current_mA.tolist() == [-2, -3, 4]
