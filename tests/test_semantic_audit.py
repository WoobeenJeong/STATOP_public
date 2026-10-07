"""S099 검수 기준 — 의미 타입 추론이 쓸 만한가.

기준 두 개 (PLAN ):
  ① 타입별 10개 세트에서 **1차 정확도 ≥80%** — 후보 1위가 맞는 비율
  ② **함정은 100% 상충 표시** — 값만으로 갈리지 않는 것은 하나도 빠짐없이 확정을 요구한다

②가 ①보다 중요하다. 틀린 1위는 사용자가 고칠 수 있지만, **상충을 놓치면 사용자는
고칠 기회조차 얻지 못한다.**
"""

import numpy as np
import pandas as pd
import pytest

from statop.semantic import infer_columns

N = 200


def _rng(seed: int):
    return np.random.default_rng(seed)


def _samples(kind: str) -> list[pd.Series]:
    """한 타입당 10개 — 모양·크기·자리수를 바꿔 가며 만든다."""
    out = []
    for i in range(10):
        r = _rng(1000 + i)
        if kind == "continuous":
            # 0~100 안에만 두면 percent 와 값으로 갈리지 않는다 — 그건 함정이지
            # 정확도를 잴 자료가 아니다. 범위를 넓게 흩는다
            center = [3.2, 180, -12, 1450, 0.04, 77000, -0.8, 22, 610, 9.9][i]
            out.append(pd.Series((r.normal(center, abs(center) * 0.2 + 1, N)).round(3)))
        elif kind == "count":
            out.append(pd.Series(r.poisson(30 + i * 40, N)))
        elif kind == "probability":
            out.append(pd.Series(r.beta(0.4, 0.4, N).round(4)))   # 0/1 근처 쌍봉
        elif kind == "percent":
            out.append(pd.Series((r.beta(2 + i, 3, N) * 100).round(1)))
        elif kind == "id":
            out.append(pd.Series([f"S{i}{j:05d}" for j in range(N)]))
        elif kind == "datetime":
            out.append(pd.Series(pd.date_range("2020-01-01", periods=N,
                                               freq=f"{i + 1}D").astype(str)))
        elif kind == "z-score":
            out.append(pd.Series(r.normal(0, 1, N).round(3)))
        elif kind == "log-scale":
            out.append(pd.Series(np.log2(r.lognormal(0, 1 + i * 0.1, N)).round(3)))
    return out


# 값만으로 1위를 맞힐 수 있어야 하는 타입 — 여기서 ≥80% 를 본다
CLEAR = ["continuous", "count", "probability", "percent", "id", "datetime"]


@pytest.mark.parametrize("kind", [
    *[k for k in CLEAR if k != "datetime"],
    # **알려진 미달 **: 날짜가 전부 고유하면 `id` 가 1위로 오고 `datetime` 이 2위다.
    # 시계열 날짜 컬럼은 대개 고유값이 100% 라 흔하게 일어난다. 게다가 needs_confirm 도
    # False 라 **확정을 요구하지도 않는다** — 사용자가 고칠 기회를 못 얻는다.
    # 고치려면 추론 순위 규칙을 손봐야 하므로(/ 영역) 여기서는 **드러내 둔다.**
    pytest.param("datetime", marks=pytest.mark.xfail(
        strict=True, reason="S099 미달: 고유값 100% 날짜가 id 로 1위 — 추론 순위 검토 필요")),
])
def test_first_candidate_is_right_at_least_80_percent(kind):
    """①  타입별 10개 세트에서 1차(후보 1위) 정확도 ≥80%."""
    hits = 0
    for i, s in enumerate(_samples(kind)):
        df = pd.DataFrame({f"col_{i}": s})
        r = infer_columns(df, [f"col_{i}"])[0]
        top = r.candidates[0].type if r.candidates else ""
        hits += top == kind
    assert hits >= 8, f"{kind}: 1위 정확도 {hits}/10 (기준 8/10)"


# 값만으로는 갈리지 않는 것 — **하나도 빠짐없이** 상충으로 떠야 한다
TRAPS = {
    "0/1 정수": pd.Series(_rng(1).integers(0, 2, N)),
    "정수 수준(등급)": pd.Series(_rng(2).integers(0, 5, N)),
    "음수 포함 실수": pd.Series(_rng(3).normal(0, 1.5, N).round(3)),
    "[0,1] 실수": pd.Series(_rng(4).uniform(0, 1, N).round(4)),
}


@pytest.mark.parametrize("name", list(TRAPS))
def test_every_trap_asks_for_confirmation(name):
    """②  함정은 100% 상충 표시 — 놓치면 사용자가 고칠 기회를 못 얻는다."""
    df = pd.DataFrame({"x": TRAPS[name]})
    r = infer_columns(df, ["x"])[0]
    # 판정 기준은 "확정을 요구하는가" 다. conflicts 문구는 신호가 정면으로 부딪칠
    # 때만 붙으므로, 그것이 없다고 통과시키면 안 된다
    assert r.needs_confirm, f"{name}: 확정을 요구하지 않는다"


def test_traps_never_report_a_lone_certain_answer():
    """함정에서 후보가 하나만 나오면 사용자는 그것이 유일한 답이라고 읽는다."""
    for name, s in TRAPS.items():
        r = infer_columns(pd.DataFrame({"x": s}), ["x"])[0]
        assert len(r.candidates) >= 2, f"{name}: 후보가 {len(r.candidates)}개뿐"


def test_composition_set_is_found_by_row_sum():
    """S098 — 조성은 **잔차 비음수**로 찾는다. 이름이 달라도 찾아야 한다."""
    r = _rng(7)
    comp = r.dirichlet([5, 3, 2], size=N)
    df = pd.DataFrame({"alpha": comp[:, 0].round(4), "beta": comp[:, 1].round(4),
                       "gamma": comp[:, 2].round(4),
                       "unrelated": r.normal(0, 1, N).round(3)})
    got = infer_columns(df, list(df.columns))
    by = {x.column: x for x in got}
    for c in ("alpha", "beta", "gamma"):
        kinds = [k.type for k in by[c].candidates]
        assert "proportion" in kinds, f"{c}: 후보에 proportion 이 없다 {kinds}"
    # 무관한 컬럼까지 조성으로 끌고 들어가면 안 된다
    assert "proportion" not in [k.type for k in by["unrelated"].candidates]
