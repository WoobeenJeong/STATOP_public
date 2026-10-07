"""검정에 실제로 쓰인 개별 점 — 그림에 찍고, 하나를 골라 뺄 수 있게 .

통계량과 p만 주면 어떤 샘플이 결과를 끌고 있는지 알 수 없다. 여기서는 **검정이 본
것과 같은 행**을 돌려준다 — 파생·결측·제외가 모두 반영된 뒤의 행이다.

행을 지목하는 방식은 relabel 과 같다: (key_column, key). id 로 확정된 컬럼이 있으면
그것을, 없으면 행 번호를 쓴다 — 무엇으로 지목했는지 항상 함께 돌려준다.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from statop.messages import msg

ROW_INDEX = "_row"          # id 컬럼이 없을 때 쓰는 가짜 키 컬럼 이름


@dataclass
class Points:
    x: list = field(default_factory=list)          # 군 이름 또는 숫자
    y: list = field(default_factory=list)
    keys: list = field(default_factory=list)       # 각 점을 지목하는 값
    key_column: str = ROW_INDEX
    group: list = field(default_factory=list)      # 층화 라벨 (색 구분용)
    by: str | None = None
    x_kind: str = "numeric"                        # numeric | category
    x_label: str = ""
    y_label: str = ""
    excluded: list = field(default_factory=list)   # 이미 뺀 점 [{key, reason}]
    outliers: list = field(default_factory=list)   # 눈에 띄는 점 [{key, x, y, why}]


def key_column_for(types: dict[str, str], columns: list[str]) -> str | None:
    """행을 지목할 컬럼 — id 로 확정된 것 중 첫 번째."""
    return next((c for c in columns if types.get(c) == "id"), None)


def _outliers(values: np.ndarray, keys: list, xs: list, limit: int = 8) -> list[dict]:
    """IQR 기준 바깥 점. 많으면 가장 먼 것부터 — 목록이 길면 아무도 안 본다."""
    if values.size < 4:
        return []
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    if iqr <= 0:
        return []
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    idx = np.where((values < lo) | (values > hi))[0]
    far = sorted(idx, key=lambda i: -max(lo - values[i], values[i] - hi))
    return [{"key": keys[i], "x": xs[i], "y": float(values[i]),
             "why": msg("points_outlier_iqr",
                        side=msg("points_side_low") if values[i] < lo
                        else msg("points_side_high"), lo=float(lo), hi=float(hi))}
            for i in far[:limit]]


def collect(session_file: str, sample_n: int = 10_000) -> Points:
    """현재 질문 설계(A1)가 쓰는 x·y 로 개별 점을 모은다."""
    from statop.analyze.spec import current
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import load_session, main_source, replay

    spec = current(session_file)
    if spec is None:
        raise ValueError(msg("a3_need_spec"))
    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    types = st["semantic_types"].get(src["id"], {})

    kc = key_column_for(types, list(df.columns))
    frame = df if kc else df.assign(**{ROW_INDEX: df.index.astype(str)})
    kc = kc or ROW_INDEX

    cols = [c for c in (spec.y, spec.group, spec.by, kc) if c and c in frame.columns]
    sub = frame[list(dict.fromkeys(cols))].dropna(subset=[spec.y])
    if spec.group and spec.group in sub.columns:
        sub = sub.dropna(subset=[spec.group])

    y = pd.to_numeric(sub[spec.y], errors="coerce")
    sub = sub[y.notna()]
    y = y[y.notna()]

    out = Points(y=[float(v) for v in y], keys=[str(v) for v in sub[kc]],
                 key_column=kc, y_label=spec.y,
                 x_label=spec.group or msg("points_x_index"), by=spec.by)
    if spec.group and spec.group in sub.columns:
        xnum = pd.to_numeric(sub[spec.group], errors="coerce")
        if xnum.notna().all():
            out.x, out.x_kind = [float(v) for v in xnum], "numeric"
        else:
            out.x, out.x_kind = [str(v) for v in sub[spec.group]], "category"
    else:
        out.x, out.x_kind = list(range(len(sub))), "numeric"
    if spec.by and spec.by in sub.columns:
        out.group = [str(v) for v in sub[spec.by]]

    out.excluded = [{"key": str(e["key"]), "reason": e.get("note", "")}
                    for e in st["excluded"] if e["key_column"] == kc]
    # 범주형 x 면 군 안에서, 연속이면 전체에서 바깥 점을 찾는다
    if out.x_kind == "category":
        arr = np.asarray(out.y, dtype="float64")
        for lv in dict.fromkeys(out.x):
            m = [i for i, v in enumerate(out.x) if v == lv]
            out.outliers += _outliers(arr[m], [out.keys[i] for i in m],
                                      [out.x[i] for i in m])
    else:
        out.outliers = _outliers(np.asarray(out.y, dtype="float64"), out.keys, out.x)
    return out


def exclude(session_file: str, key_column: str, key: str, note: str) -> dict:
    """개별 샘플을 뺀다. 사유 없이는 뺄 수 없다 — 나중에 왜 뺐는지 물으면 답이 있어야 한다."""
    from statop.session.core import append_op, load_session, main_source, save_session

    if not note.strip():
        raise ValueError(msg("points_note_required"))
    doc = load_session(session_file)
    src = main_source(doc)
    entry = append_op(doc, "exclude_row", source=src["id"], key_column=key_column,
                      key=str(key), note=note.strip())
    save_session(doc)
    return entry


def include(session_file: str, key_column: str, key: str) -> dict:
    """뺐던 샘플을 되돌린다."""
    from statop.session.core import append_op, load_session, main_source, save_session

    doc = load_session(session_file)
    src = main_source(doc)
    entry = append_op(doc, "include_row", source=src["id"], key_column=key_column,
                      key=str(key))
    save_session(doc)
    return entry


# ──  A4 제약 ────────────────────────────────────────────
EXCLUDE_RED = 0.10          # 이 비율을 넘게 빼면 빨강 — 분석이 아니라 표본을 고른 것이다

# 이상점 때문에 빼려는 것이라면, 빼기 전에 이상점에 둔한 검정을 먼저 권한다.
# 무엇을 권할지는 "지금 무엇을 하려는가"(질문 유형)에 달려 있다.
ROBUST_ALTERNATIVES = {
    "Q-01": ["T-103", "T-104", "T-105"],
    "Q-03": ["T-302", "T-305"],
    "Q-05": ["T-501", "T-503"],
    "Q-07": ["T-701"],
    "Q-08": ["T-806"],
    "Q-11": ["T-1104"],
}


@dataclass
class ExcludeStatus:
    n_excluded: int = 0
    n_total: int = 0
    ratio: float = 0.0
    verdict: str = "green"                      # green | yellow | red
    alternatives: list = field(default_factory=list)   # [{id, name, why}]


def status(session_file: str, sample_n: int = 10_000) -> ExcludeStatus:
    """얼마나 뺐는가 — 10%를 넘으면 빨강. 빼기 전에 권할 대안도 함께."""
    from statop.analyze.spec import current
    from statop.derive.service import session_frame, with_derived, with_missing
    from statop.session.core import load_session, main_source, replay

    doc, src, df = session_frame(session_file, sample_n)
    base = with_missing(with_derived(df, doc, src["id"]), doc, src["id"])
    ex = [e for e in replay(doc)["excluded"] if e.get("source") in (None, src["id"])]
    total = len(base) or 1
    ratio = len(ex) / total
    out = ExcludeStatus(n_excluded=len(ex), n_total=len(base), ratio=ratio,
                        verdict="red" if ratio > EXCLUDE_RED
                        else "yellow" if ex else "green")

    spec = current(session_file)
    if spec is not None:
        from statop.analyze.candidates import _rules

        names = {t["id"]: t["name"] for t in _rules()["tests"]}
        out.alternatives = [
            {"id": tid, "name": names.get(tid, tid), "why": msg("points_alt_why")}
            for tid in ROBUST_ALTERNATIVES.get(spec.question, [])]
    return out


def both_ways(session_file: str, test_id: str, sample_n: int = 10_000) -> dict:
    """제외 전/후를 함께 계산한다 .

    제외 후 값만 내보내면 "불편한 점을 빼면 유의해진다"를 숨길 수 있다. 제외가 있으면
    전·후를 **항상 나란히** 돌려주고, 어느 쪽도 단독으로는 쓰지 않는다.
    """
    from statop.analyze.run import run_test

    from statop.analyze.checks import multiplicity
    from statop.analyze.spec import current

    after = run_test(session_file, test_id, sample_n)
    st = status(session_file, sample_n)
    # 유의 여부는 같은 보정 α로 판단해야 한다 — 계획 검정 수는 제외와 무관하다
    spec = current(session_file)
    adj = multiplicity(spec.n_tests if spec else 1).numbers["alpha_adjusted"]
    if not st.n_excluded:
        return {"after": after, "before": None, "status": st, "flipped": False,
                "alpha": adj}

    before = run_test(session_file, test_id, sample_n, use_exclusions=False,
                      record=False)
    flipped = (before.p is not None and after.p is not None
               and (before.p < adj) != (after.p < adj))
    return {"after": after, "before": before, "status": st, "flipped": flipped,
            "alpha": adj}



