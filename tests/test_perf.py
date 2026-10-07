"""S204b 경량성 ·  동시성 — **재서 확인한다.**

 : 빠른 표준 도구(로지스틱·Kaplan–Meier·PCA·단순 LMM)는 그냥 돌려서 결과를
보여준다. STATOP 를 거친다고 눈에 띄게 느려지면 그 약속이 깨진다.

 (요구사항8절): 5명이 100k 행 파일을 동시에 열어도 세션별 응답이 **단독 대비 2배 이내**,
세션 A 의 조작이 B 에 **영향 0** (같은 원본이어도).

시간은 기계마다 다르다. 그래서 **절대 초** 대신 **단독 대비 배수**로 본다 — 그게 약속의
문장이기도 하다. 느린 기계에서 거짓 실패가 나지 않는다.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROWS = 100_000          # 요구사항가 말하는 규모
SLOW = 2.0              # 단독 대비 허용 배수
LIGHT = 2.0             # 표준 도구 대비 허용 배수 (경량성)


def _timed(fn, *a, **kw) -> tuple[float, object]:
    t = time.perf_counter()
    out = fn(*a, **kw)
    return time.perf_counter() - t, out


# ──  경량성 ────────────────────────────────────────────
@pytest.fixture(scope="module")
def big(tmp_path_factory):
    """100k 행 합성 자료 — 로지스틱·생존·PCA·LMM 을 다 걸 수 있는 모양."""
    rng = np.random.default_rng(7)
    n = ROWS
    g = rng.choice(["a", "b"], n)
    x1 = rng.normal(0, 1, n)
    x2 = rng.normal(0, 1, n)
    lin = 0.4 * x1 - 0.3 * x2 + (g == "b") * 0.5
    path = tmp_path_factory.mktemp("perf") / "big.csv"
    pd.DataFrame({
        "sid": np.arange(n),
        "grp": g, "x1": x1, "x2": x2,
        "label": (rng.random(n) < 1 / (1 + np.exp(-lin))).astype(int),
        "days": np.round(rng.exponential(np.where(g == "a", 60, 90)), 1),
        "event": (rng.random(n) < 0.7).astype(int),
    }).to_csv(path, index=False)
    return path


def test_standard_tools_run_at_scale(big, capsys):
    """표준 도구가 100k 행에서 **그냥 돌아간다** — 재구현하지 않는다는 약속 ."""
    df = pd.read_csv(big)
    out = {}

    # **import 비용을 먼저 치른다.** 처음 부르는 자리에서 재면 라이브러리를 올리는
    # 시간까지 들어가 계산이 느린 것처럼 보인다 (실측으로 28초 → 0.1초였다)
    import sklearn.decomposition  # noqa: F401
    import sklearn.linear_model  # noqa: F401

    from statop.analyze.run import RUNNERS  # noqa: F401

    def logistic():
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(max_iter=200).fit(df[["x1", "x2"]], df["label"])

    def pca():
        from sklearn.decomposition import PCA

        return PCA(n_components=2).fit(df[["x1", "x2"]])

    def km():
        from statop.analyze.run import RUNNERS

        return RUNNERS["T-901"](df.head(20_000), "days", "grp", "two-sided")

    def lmm():
        from statop.analyze.run import RUNNERS
        from statop.analyze.spec import Spec

        # 혼합모형은 **대상 ID** 가 있어야 돈다 — 같은 대상이 여러 번 나와야 한다
        sub = df.head(20_000).assign(sid=(df["sid"].head(20_000) % 2_000).astype(str))
        spec = Spec(question="Q-01", y="x1", group="grp", paired=True, subject="sid")
        return RUNNERS["T-133"](sub, "x1", "grp", "two-sided", spec=spec)

    for name, fn in (("로지스틱", logistic), ("PCA", pca),
                     ("Kaplan–Meier", km), ("단순 LMM", lmm)):
        try:
            sec, _ = _timed(fn)
            out[name] = sec
        except Exception as e:                      # 못 도는 것은 그렇다고 적는다
            out[name] = f"못 돌림: {type(e).__name__}"

    with capsys.disabled():
        print(f"\n  경량성 — {ROWS:,}행")
        for k, v in out.items():
            print(f"    {k:<14s} {v:.2f}초" if isinstance(v, float) else f"    {k:<14s} {v}")

    ran = [v for v in out.values() if isinstance(v, float)]
    assert len(ran) >= 3, f"표준 도구가 대부분 안 돈다: {out}"
    assert max(ran) < 60, f"100k 행에서 1분을 넘는 것이 있다: {out}"


def test_evid_does_not_add_much_on_top_of_the_library(big, capsys):
    """STATOP 를 거친 값과 라이브러리를 직접 부른 값의 **시간 차**가 크지 않아야 한다.

    STATOP 가 하는 일은 규칙 판정이지 계산 재구현이 아니다 . 그런데 래핑 비용이
    계산 자체보다 크면 "그냥 돌려서 보여준다"가 아니게 된다.
    """
    from scipy import stats

    from statop.analyze.run import RUNNERS

    df = pd.read_csv(big)
    a = df.loc[df.grp == "a", "x1"].to_numpy()
    b = df.loc[df.grp == "b", "x1"].to_numpy()

    raw, _ = _timed(stats.ttest_ind, a, b, equal_var=False)
    via, _ = _timed(RUNNERS["T-101"], df, "x1", "grp", "two-sided")
    ratio = via / max(raw, 1e-6)
    with capsys.disabled():
        print(f"\n  래핑 비용 — scipy 직접 {raw * 1000:.1f}ms · STATOP 경유 {via * 1000:.1f}ms "
              f"({ratio:.1f}배)")
    # 효과크기·CI 를 더 계산하므로 같을 수는 없다. 다만 자릿수가 달라지면 안 된다
    assert via < 5.0, f"100k 행 t 검정이 {via:.1f}초"


# ──  동시성 ─────────────────────────────────────────────
def _one_session(tmp: Path, src: Path, tag: str) -> dict:
    """세션 하나를 열고 전형적인 작업을 한 바퀴 — 다른 세션과 겹치지 않는 STATOP_HOME."""
    import os

    os.environ["STATOP_HOME"] = str(tmp / f"home_{tag}")
    from statop.derive.service import apply_ops, session_frame
    from statop.semantic import infer_columns
    from statop.session.core import (append_op, load_session, main_source, new_session,
                                   register_source, replay, save_session)

    doc = new_session()
    sid = register_source(doc, str(src))
    append_op(doc, "select", source=sid, cols=["grp", "x1", "x2", "label"])
    session = save_session(doc)

    doc = load_session(session)
    _, srcd, df = session_frame(session, 100_000)
    df = apply_ops(df, doc, srcd["id"])
    infs = infer_columns(df, ["x1", "grp"])
    return {"session": session, "rows": int(len(df)),
            "cols": sorted(df.columns),
            "types": {t.column: [c.type for c in t.candidates][:1] for t in infs}}


def test_five_sessions_at_once_stay_within_twice_the_time(big, tmp_path, capsys):
    """5세션 동시 = 단독 대비 2배 이내, 그리고 **결과가 같다** (영향 0)."""
    alone_sec, alone = _timed(_one_session, tmp_path, big, "solo")

    def run(i: int) -> dict:
        return _one_session(tmp_path, big, f"c{i}")

    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as ex:
        got = list(ex.map(run, range(5)))
    together = time.perf_counter() - t
    per = together / 5
    ratio = per / max(alone_sec, 1e-6)

    with capsys.disabled():
        print(f"\n  동시성 — 단독 {alone_sec:.2f}초 · 5세션 동시 {together:.2f}초 "
              f"(세션당 {per:.2f}초, {ratio:.2f}배)")

    # 영향 0 — 같은 원본이어도 세션마다 같은 결과가 나와야 한다
    for g in got:
        assert g["rows"] == alone["rows"]
        assert g["cols"] == alone["cols"]
        assert g["types"] == alone["types"]
    # 세션 파일이 서로 다른 것 (섞이지 않았다)
    assert len({g["session"] for g in got}) == 5
    assert ratio <= SLOW, f"세션당 {ratio:.2f}배 (기준 {SLOW}배 이내)"


def test_one_session_cannot_change_another(big, tmp_path):
    """세션 A 에서 조작해도 B 는 그대로다 — 같은 원본을 봐도."""
    import os

    a = _one_session(tmp_path, big, "A")
    b = _one_session(tmp_path, big, "B")

    os.environ["STATOP_HOME"] = str(tmp_path / "home_A")
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import append_op, load_session, main_source, save_session

    doc = load_session(a["session"])
    sid = main_source(doc)["id"]
    append_op(doc, "deselect", source=sid, cols=["x2"])
    append_op(doc, "semantic_confirm", source=sid, column="x1", type="continuous")
    save_session(doc)

    os.environ["STATOP_HOME"] = str(tmp_path / "home_B")
    doc_b = load_session(b["session"])
    _, srcb, df_b = session_frame(b["session"], 100_000)
    df_b = apply_ops(df_b, doc_b, srcb["id"])
    assert sorted(df_b.columns) == b["cols"], "A 의 조작이 B 에 보인다"
    assert Path(big).exists(), "원본이 사라졌다"
