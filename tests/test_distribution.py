"""M0-3 분포 미리보기 — 숫자는 코어가, 그림은 껍데기가."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from statop.io.distribution import MAX_LEVELS, describe_series, distributions
from statop.render.spark import bar, format_distribution, sparkline

DATA = Path(__file__).parent / "data"


def test_numeric_summary_catches_skew_and_outliers():
    rng = np.random.default_rng(0)
    s = pd.Series(np.concatenate([rng.normal(10, 1, 500), [200.0, 250.0]]))  # 소수 극단값
    d = describe_series(s, "x")
    assert d.kind == "numeric" and d.n == 502
    assert d.skewness > 1                       # 오른쪽 꼬리
    assert d.outlier_rate_iqr > 0               # IQR 기준으로 잡힘
    assert len(d.bins) == len(d.edges) - 1
    assert d.quartiles[0] <= d.quartiles[2] <= d.quartiles[4]


def test_outlier_criteria_can_disagree():
    """IQR과 MAD는 분포에 따라 다른 답을 준다 — 둘 다 제시하는 이유 (C-03)."""
    d = describe_series(pd.Series(np.random.default_rng(1).lognormal(2, 1, 2000)), "x")
    assert d.outlier_rate_iqr != d.outlier_rate_mad


def test_missing_and_zero_signals():
    s = pd.Series([0.0] * 60 + [1.0] * 20 + [None] * 20)
    d = describe_series(s, "z")
    assert d.n == 80 and d.n_missing == 20
    assert d.zeros_rate == pytest.approx(0.75)   # 영과잉 신호 (C-10)
    assert d.negative is False


def test_categorical_levels_truncated():
    s = pd.Series([f"lv{i%30}" for i in range(300)])
    d = describe_series(s, "c")
    assert d.kind == "categorical" and d.n_levels == 30
    assert d.truncated is True
    assert len(d.levels) == MAX_LEVELS + 1        # 상위 + "그 외"
    assert d.levels[-1]["value"].startswith("…")  # 나머지는 한 줄로 묶는다


def test_distributions_on_real_file_and_unknown_column():
    items = distributions(DATA / "synth_long.parquet", ["site", "cont000"], sample_n=3000)
    assert [i["column"] for i in items] == ["site", "cont000"]
    assert items[0]["kind"] == "categorical" and items[1]["kind"] == "numeric"
    with pytest.raises(ValueError, match="없는 컬럼"):
        distributions(DATA / "synth_long.parquet", ["nope"], sample_n=1000)


def test_sparkline_and_bar_shapes():
    assert len(sparkline([1, 5, 9], width=24)) == 3      # 구간이 적으면 그대로
    assert len(sparkline(list(range(100)), width=20)) == 20  # 많으면 합쳐서 폭 맞춤
    assert sparkline([]) == ""
    assert bar(0.5, width=10) == "█████·····"


def test_format_distribution_is_compact():
    """과한 정보 대신 압축 — 문제 신호가 있을 때만 한 줄 추가 ."""
    quiet = describe_series(pd.Series(np.random.default_rng(2).normal(0, 1, 500)), "q").as_dict()
    noisy = describe_series(pd.Series(np.random.default_rng(3).lognormal(0, 1.5, 500)), "n").as_dict()
    # 막대 + 다섯 수 + 울타리. 다섯 수를 한 줄에 다 넣으면 150자가 넘어 터미널에서
    # 줄이 접힌다 — 두 줄로 나누되 그 이상은 늘리지 않는다
    # 막대 + 다섯 수 + IQR·울타리 + 울타리 설명. 한 줄에 몰면 150자가 넘어 접힌다
    assert len(format_distribution(quiet)) == 4
    assert len(format_distribution(noisy)) == 5          # + 신호 줄
    assert "왜도" in format_distribution(noisy)[4]
    # 그림이 다섯 수를 이미 적는 자리에서는 막대 + 신호 줄만
    assert len(format_distribution(quiet, with_stats=False)) == 1
    # 음수 자체는 신호가 아니다 — 타입을 전제로 C-14가 판정한다
    assert not any("음수" in ln for ln in format_distribution(quiet))
