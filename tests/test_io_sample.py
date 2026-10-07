from pathlib import Path

import pandas as pd
import pytest

from statop.io.sample import sample_rows

DATA = Path(__file__).parent / "data"


def test_block_sample_beats_head_on_sorted_file():
    """정렬 편향 파일: 앞N행은 siteA 100%, 앞/중/뒤 샘플은 실제 비율(30%)에 근접해야 한다."""
    f = DATA / "synth_long.csv"
    head = pd.read_csv(f, nrows=3000)
    samp = sample_rows(f, n=3000)

    assert (head["site"] == "siteA").mean() == 1.0  # 편향 재현
    frac_a = (samp["site"] == "siteA").mean()
    assert abs(frac_a - 0.30) < 0.10


def test_sample_deterministic_and_sized():
    f = DATA / "synth_long.csv"
    a = sample_rows(f, n=900)
    b = sample_rows(f, n=900)
    assert len(a) == 900
    assert a.equals(b)  # 무작위 없음 — 같은 입력이면 같은 샘플
    assert list(a.columns)[:2] == ["patient_id", "site"]


def test_parquet_sample_same_shape_and_unbiased():
    """parquet도 같은 API로 동일 형태 + 앞/중/뒤 균형 샘플."""
    samp = sample_rows(DATA / "synth_long.parquet", n=3000)
    csv = sample_rows(DATA / "synth_long.csv", n=3000)
    assert list(samp.columns) == list(csv.columns)
    assert len(samp) == 3000
    assert abs((samp["site"] == "siteA").mean() - 0.30) < 0.10


@pytest.mark.parametrize("n_rows", [0, 1, 2, 5, 40])
def test_parquet_sample_smaller_than_request(tmp_path, n_rows):
    """행 수가 요청 샘플보다 적은 작은 parquet에서도 안전해야 한다 (빈 구간 버그 회귀)."""
    import pandas as pd

    p = tmp_path / f"a{n_rows}.parquet"
    pd.DataFrame({"id": [f"x{i}" for i in range(n_rows)],
                  "v": list(range(n_rows))}).to_parquet(p, index=False)
    got = sample_rows(p, n=10_000)
    assert len(got) == n_rows
    assert list(got.columns) == ["id", "v"]


def test_identical_rows_are_not_collapsed(tmp_path):
    """값이 같은 서로 다른 샘플을 지우면 안 된다 — 결측·저카디널리티에서 흔히 생긴다."""
    import pandas as pd

    p = tmp_path / "dup.csv"
    df = pd.DataFrame({"g": ["a"] * 60 + ["b"] * 60, "v": [1.0] * 120})
    df.to_csv(p, index=False)
    got = sample_rows(p, n=10_000)
    assert len(got) == 120
    assert got["g"].value_counts().to_dict() == {"a": 60, "b": 60}


def test_missing_rows_survive_sampling(tmp_path):
    """결측이 있는 행은 서로 구별되지 않아 예전에는 통째로 합쳐졌다."""
    import numpy as np
    import pandas as pd

    p = tmp_path / "na.csv"
    n = 200
    rng = np.random.default_rng(3)
    a = rng.normal(0, 1, n)
    a[rng.choice(n, 40, replace=False)] = np.nan
    pd.DataFrame({"a": a, "g": rng.choice(["x", "y"], n)}).to_csv(p, index=False)
    got = sample_rows(p, n=10_000)
    assert len(got) == n
    assert int(got["a"].isna().sum()) == 40
