"""M0-6b 결측 처리 (registry-errors 1.1) — 실행은 NA 제거와 허용 목록 대치뿐."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.missing import (ALLOWED_METHODS, HIGH_MISSING, check_method, drop_na, impute,
                          report)

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("h")))


@pytest.fixture()
def df():
    rng = np.random.default_rng(0)
    n = 200
    d = pd.DataFrame({"a": rng.normal(10, 2, n), "b": rng.normal(5, 1, n),
                      "grp": ["x", "y"] * (n // 2), "z": rng.normal(0, 1, n)})
    d.loc[:20, "a"] = np.nan
    d.loc[:20, "b"] = np.nan      # a와 함께 빈다
    d.loc[50:80, "b"] = np.nan
    return d


def test_report_counts_patterns_and_complete_rows(df):
    r = report(df)
    assert r.n_rows == 200 and r.complete_rows == 200 - 21 - 31
    by = {c.column: c for c in r.columns}
    assert by["a"].n_missing == 21 and by["z"].n_missing == 0
    assert by["b"].ratio > HIGH_MISSING is False or by["b"].ratio == pytest.approx(0.26)
    # 함께 비는 조합이 드러난다
    combos = {tuple(p["columns"]): p["n"] for p in r.patterns}
    assert combos[("a", "b")] == 21 and combos[("b",)] == 31


def test_report_flags_high_missing_and_zero_filled():
    d = pd.DataFrame({"hi": [np.nan] * 40 + [1.0] * 60,
                      "zf": [0.0] * 70 + [np.nan] * 10 + [2.0] * 20})
    by = {c.column: c for c in report(d).columns}
    assert by["hi"].high is True                      # 40% > 30% → 제거 제안
    assert by["zf"].suspect_zero_filled is True       # 0이 과반인데 결측도 있음


def test_drop_na_row_and_column(df):
    assert len(drop_na(df, ["a"])) == 179
    assert "b" not in drop_na(df, ["b"], how="column").columns
    with pytest.raises(ValueError, match="row 또는 column"):
        drop_na(df, how="both")


@pytest.mark.parametrize("method", ["zero", "mean", "median", "mode", "knn", "mice"])
def test_allowed_methods_fill(df, method):
    out, info = impute(df, method, ["a", "b"], seed=0)
    assert info["n_filled"] > 0 and info["n_remaining"] == 0
    assert out[["a", "b"]].isna().sum().sum() == 0
    assert df[["a", "b"]].isna().sum().sum() > 0      # 원본 프레임은 그대로


def test_heavy_estimators_rejected(df):
    for bad in ("random_forest", "mlp", "gan", "xgboost"):
        with pytest.raises(ValueError, match="지원하지 않는"):
            check_method(bad, df, ["a"])
    assert set(ALLOWED_METHODS) == {"zero", "mean", "median", "mode", "group_mean",
                                    "group_median", "knn", "mice"}


def test_mean_warns_above_threshold_and_zero_on_fraction(df):
    assert check_method("mean", df, ["z"]) == []             # 결측 0% → 경고 없음
    for col in ("a", "b"):                                    # 10.5%·26% → 둘 다 임계 초과
        warns = check_method("mean", df, [col])
        assert warns and "분산 축소" in warns[0]

    frac = pd.DataFrame({"p": [0.1, 0.5, np.nan, 0.9]})
    w = check_method("zero", frac, ["p"])
    assert w and "비율·확률의 의미" in w[0]


def test_group_imputation_requires_group(df):
    with pytest.raises(ValueError, match="그룹 컬럼"):
        check_method("group_mean", df, ["a"])
    _, info = impute(df, "group_mean", ["a"], group_by="grp")
    assert info["params"]["group_by"] == "grp" and info["n_filled"] == 21


def test_mice_records_seed_and_estimator(df):
    _, info = impute(df, "mice", ["a", "b"], seed=42)
    assert info["seed"] == 42                                 # 재현성
    assert info["params"]["estimator"] == "BayesianRidge"     # 추정기 고정


def test_knn_limits():
    wide = pd.DataFrame(np.random.default_rng(0).normal(size=(10, 250)))
    wide.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="KNN"):
        check_method("knn", wide, [0])


def _session(runner, path) -> str:
    from statop.store import tmp_dir

    runner.invoke(app, ["session", "new", "--data", str(path)])
    return str(next(tmp_dir().glob("session_*.json")))


def test_cli_show_drop_impute_records(tmp_path):
    p = tmp_path / "m.csv"
    d = pd.DataFrame({"a": [1.0, 2.0, np.nan, 4.0], "b": [1.0, np.nan, np.nan, 4.0]})
    d.to_csv(p, index=False)

    runner = CliRunner()
    sess = _session(runner, p)
    show = runner.invoke(app, ["missing", "show", "--session", sess])
    assert show.exit_code == 0 and "완전한 행 2개" in show.output

    pre = runner.invoke(app, ["missing", "drop", "--session", sess, "--cols", "a"])
    assert "4행 → 3행" in pre.output
    assert not any(o["op"] == "missing_drop" for o in json.loads(Path(sess).read_text())["ops"])

    ap = runner.invoke(app, ["missing", "drop", "--session", sess, "--cols", "a", "--apply"])
    assert ap.exit_code == 0 and "op 기록" in ap.output

    im = runner.invoke(app, ["missing", "impute", "--session", sess, "--method", "median",
                             "--cols", "b", "--apply"])
    assert im.exit_code == 0 and "대치: median" in im.output
    ops = [o["op"] for o in json.loads(Path(sess).read_text())["ops"]]
    assert "missing_drop" in ops and "impute" in ops

    bad = runner.invoke(app, ["missing", "impute", "--session", sess,
                              "--method", "random_forest", "--cols", "b"])
    assert bad.exit_code != 0
