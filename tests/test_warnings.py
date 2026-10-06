"""Regression tests for accurate per-input warnings without staging duplicates."""

import warnings

import battread
import numpy as np
import pandas as pd
import pytest
from battread.warnings import MissingValueWarning
from test_processing import canonical, noop

from battread_gui.models import Job
from battread_gui.processing import run_job


@pytest.mark.parametrize("chunk_size", [1, 2, 10])
def test_missing_warning_is_one_accurate_summary_per_input(tmp_path, chunk_size):
    """Repeated validation must not duplicate warnings or count the same row twice."""
    frame = canonical([0, 1, 2, 3])
    frame.loc[[0, 2], "current_mA"] = np.nan
    source = tmp_path / "synthetic.csv"
    frame.to_csv(source, index=False)
    target = tmp_path / "output.parquet"
    work = tmp_path / "work"
    work.mkdir()
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        run_job(
            Job((source,), (target,), False, "parquet", 1024**3, chunk_size),
            work,
            dict,
            noop,
        )
    missing = [w for w in captured if isinstance(w.message, MissingValueWarning)]
    assert len(missing) == 1
    assert missing[0].message.affected_counts == {"current_mA": 2}
    assert missing[0].filename == str(source)
    pd.testing.assert_frame_equal(battread.read(target), frame)
