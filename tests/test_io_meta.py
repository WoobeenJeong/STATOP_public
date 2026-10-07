import time
from pathlib import Path

import pytest

from statop.io.meta import open_meta

DATA = Path(__file__).parent / "data"


@pytest.mark.parametrize("fmt", ["csv", "tsv", "parquet"])
def test_open_meta_long(fmt):
    m = open_meta(DATA / f"synth_long.{fmt}")
    assert m.fmt == fmt
    assert len(m.columns) == 2_000
    assert m.columns[:2] == ["patient_id", "site"]
    if fmt == "parquet":
        assert m.n_rows == 10_000
        assert m.dtypes["patient_id"] in ("string", "large_string")
    else:
        assert m.n_rows is None
        assert m.dtypes is None


def test_open_meta_under_one_second():
    t0 = time.time()
    open_meta(DATA / "synth_wide.csv")
    open_meta(DATA / "synth_wide.parquet")
    assert time.time() - t0 < 1.0


def test_unsupported_format(tmp_path):
    bad = tmp_path / "x.xlsx"
    bad.write_text("dummy")
    with pytest.raises(ValueError, match="unsupported format"):
        open_meta(bad)


@pytest.mark.parametrize("stem,true_n", [("synth_long", 10_000), ("synth_wide", 2_000)])
def test_estimate_rows_within_5pct(stem, true_n):
    from statop.io.meta import estimate_rows

    est = estimate_rows(DATA / f"{stem}.csv")
    assert abs(est - true_n) / true_n < 0.05
