"""지표 찾기  — **질문 → 컬럼 → 무엇을 쓸까** 순서로 들어간다.

분석(A1~A3)은 "이 설계로 간다"를 **기록**하는 자리다. 여기는 그 전에 둘러보는
자리다 — 기록하지 않는다. 컬럼 두 개를 정해 놓고 "이 둘이 관계가 있나"를 보려는데,
지표 목록이 세션 전체 기준으로만 깔려 있으면 볼 방도가 없었다.

세 가지를 지킨다:
- **쓸 수 없다고 판정돼도 계산은 된다.** 값을 숨기면 "왜 안 되는데"로 끝난다.
  대신 왜 그렇게 판정했는지와 고치는 법을 같이 낸다
- **누를 때만 계산한다.** 목록에 뜬 것을 전부 미리 돌리면 화면이 멈춘다
- **여러 번 쟀으면 그 수를 센다.** 보정은 `padjust` 가 한다 (C-15)
"""

from dataclasses import dataclass, field

from statop.messages import msg


# 근거 칸의 이름 — 규칙표 컬럼과 1:1. 껍데기가 지어내지 않는다
RULE_KEYS = ("design", "assumptions", "best_when", "blocked_when", "caution",
             "effect_size", "alternatives", "post")


def rule_labels() -> list:
    """[(키, 사람이 읽는 이름)] — CLI·TUI·웹이 같은 목록을 쓴다."""
    return [(k, msg("rule_" + k)) for k in RULE_KEYS]


@dataclass
class Found:
    question: str
    question_name: str
    columns: list = field(default_factory=list)
    candidates: list = field(default_factory=list)   # [{id, name, verdict, why, reasons}]
    problems: list = field(default_factory=list)     # 설계 자체가 안 되는 이유
    note: str = ""
    rule_labels: list = field(default_factory=list)  # 근거 칸 이름 (껍데기 공용)
    color_columns: list = field(default_factory=list)  # 색으로 나눌 수 있는 군 컬럼
    second_role: str = ""                            # 둘째 컬럼이 무엇의 자리인가
    second_columns: list = field(default_factory=list)  # 그 자리에 올 수 있는 컬럼


def _tests() -> list:
    """검정 규칙표 — 근거를 그대로 보여주기 위해 읽는다."""
    import yaml

    from statop.rules.build import RULES_DIR

    return yaml.safe_load((RULES_DIR / "tests.yaml").read_text(encoding="utf-8"))["tests"]


def _spec_for(question: str, columns: list):  # noqa: ANN202
    """질문 유형과 컬럼으로 **기록하지 않는** 설계를 만든다.

    질문마다 컬럼이 무엇의 자리인지 다르다 — 연관은 두 변수(y, by), 차이는 값과 군이다.
    """
    from statop.analyze.spec import Spec

    cols = list(columns)
    y = cols[0] if cols else ""
    second = cols[1] if len(cols) > 1 else None
    if question == "Q-09":                    # 생존 — 두 번째는 사건 여부다
        return Spec(question=question, y=y, event=second)
    # 나머지는 **두 번째가 group 자리**다. 연관에서도 검정 함수는 그 자리에서
    # 두 번째 변수를 받는다 (`_pearson(df, y, group, ...)`) — 분석 화면과 같은 규칙
    return Spec(question=question, y=y, group=second)


# 색으로 나눌 수 있는 것 — **군을 가리키는 컬럼**만이다. 연속값을 색에 넣으면
# 점 하나마다 다른 색이 되어 그림이 못 쓰게 된다
GROUPY = ("label", "nominal code", "ordinal code")
COLOR_MAX_LEVELS = 8
NUMERIC_TYPES = ("continuous", "count", "proportion", "composition set",
                 "ordinal code", "ratio", "concentration")
# 둘째 컬럼이 **무엇의 자리인가** — 질문마다 다르다. 적어 두지 않으면 화면이
# "컬럼을 더 고르세요"까지만 말하고 무엇을 고를지는 못 말한다
SECOND_ROLE = {"Q-03": "value", "Q-06": "value", "Q-08": "value", "Q-09": "event"}


def second_role(question: str) -> str:
    """둘째 컬럼의 자리 — 군(group) · 값(value) · 사건(event)."""
    return SECOND_ROLE.get(question, "group")


def second_columns(session_file: str, question: str, columns: list,
                   sample_n: int = 10_000) -> list:
    """둘째 자리에 **올 수 있는** 컬럼 — 고르라고만 하고 무엇을 고를지 안 알려주면 막힌다."""
    import pandas as pd

    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    role = second_role(question)
    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    types = replay(doc)["semantic_types"].get(src["id"], {})
    out = []
    for c in df.columns:
        if c in columns:
            continue
        t = (types.get(c) or {}).get("type") if isinstance(types.get(c), dict) else types.get(c)
        numeric = pd.api.types.is_numeric_dtype(df[c])
        k = int(df[c].nunique(dropna=True))
        if role == "value":
            if numeric and t != "id" and k > 2:
                out.append(c)
        elif role == "event":
            if k == 2:                       # 사건은 있었나/없었나 둘뿐이다
                out.append(c)
        elif (t in GROUPY or not numeric) and t not in ("id", "datetime") and 2 <= k <= 12:
            out.append(c)
    return out


def color_columns(session_file: str, question: str, columns: list,
                  sample_n: int = 10_000) -> list:
    """색으로 나눌 만한 군 컬럼.

    **고른 컬럼도 뺄 이유가 없다** — 차이를 볼 때 군은 분석 컬럼이면서 동시에
    색으로 보고 싶은 것이다. 다만 둘째가 값 자리인 질문(연관·예측)에서는
    그 값을 색에 넣어 봐야 점마다 다른 색이 되므로 뺀다.
    """
    import pandas as pd

    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    types = replay(doc)["semantic_types"].get(src["id"], {})
    y = columns[0] if columns else ""
    out = []
    for c in df.columns:
        if c == y:                       # 보려는 값 자체를 색으로 나누지는 않는다
            continue
        t = (types.get(c) or {}).get("type") if isinstance(types.get(c), dict) else types.get(c)
        numeric = pd.api.types.is_numeric_dtype(df[c])
        if t not in GROUPY and (numeric or t in ("id", "datetime")):
            continue
        k = int(df[c].nunique(dropna=True))
        if 2 <= k <= COLOR_MAX_LEVELS:
            out.append(c)
    return out


def find(session_file: str, question: str, columns: list,
         sample_n: int = 10_000) -> Found:
    """이 질문·이 컬럼에 쓸 수 있는 것들 — **값은 아직 계산하지 않는다.**"""
    from statop.analyze.candidates import shortlist
    from statop.analyze.spec import build, questions

    qs = {q["id"]: q for q in questions()}
    if question not in qs:
        raise ValueError(msg("explore_bad_question", q=question,
                             allowed=", ".join(qs)))
    # **둘째 컬럼이 없으면 아무것도 못 돌린다.** 그런데도 목록을 내밀고 있었고,
    # 누르면 검정 함수가 군을 못 찾아 터졌다 (12종 전부 같은 증상). 여기서 막고
    # 무엇을 더 골라야 하는지를 **고를 수 있는 목록으로** 낸다
    if len(columns) < 2:
        role = second_role(question)
        cands = second_columns(session_file, question, columns, sample_n)
        return Found(question=question,
                     question_name=qs[question].get("question", question),
                     columns=list(columns), candidates=[],
                     problems=[msg("explore_need_second_" + role)],
                     note=msg("explore_not_recorded"), rule_labels=rule_labels(),
                     second_role=role, second_columns=cands)

    spec = _spec_for(question, columns)
    res = build(session_file, spec, sample_n=sample_n)
    rules = {t["id"]: t for t in _tests()}
    cands = [{"id": c.id, "name": c.name, "verdict": c.color,
              # **근거는 규칙표 그대로** 붙인다 — 화면이 지어내지 않게
              "rule": {k: rules.get(c.id, {}).get(k) or ""
                       for k in ("section", *RULE_KEYS)},
              "reasons": list(c.reasons or []), "assumptions": c.assumptions,
              "effect_size": c.effect_size, "design": c.design,
              # 실행 함수가 없으면 **값을 구할 수 없다** — 누를 수 있는 것처럼 두지 않는다
              "runnable": bool(c.runnable)}
             for c in shortlist(res)] if not res.problems else []
    return Found(question=question, question_name=qs[question].get("question", question),
                 columns=list(columns), candidates=cands,
                 problems=list(res.problems), note=msg("explore_not_recorded"),
                 rule_labels=rule_labels(),
                 second_role=second_role(question),
                 color_columns=color_columns(session_file, question, columns, sample_n))


# 양측 α=.05, 목표 검정력 .8 — 두 수를 한 곳에 둔다
ALPHA, TARGET = 0.05, 0.80
# 목표 검정력은 **옮길 수 있다.** 80% 는 관습일 뿐이라 자리를 옮겨 보고 나서
# "그럼 95% 로 보면 얼마가 필요한가"를 같은 화면에서 답할 수 있어야 한다
TARGET_MIN, TARGET_MAX = 0.50, 0.99
# 이 선과 **같은 척도**인 효과크기만 올린다 — τ·dCor 은 다른 자로 잰 값이다
R_LIKE = ("r", "rho", "bicor", "partial r")


def _zsum(target: float = TARGET) -> float:
    """z(1-α/2) + z(목표 검정력) — 선의 위치를 정하는 유일한 수."""
    from scipy.stats import norm

    return float(norm.isf(ALPHA / 2) + norm.ppf(clamp_target(target)))


def clamp_target(target: float) -> float:
    """목표 검정력을 쓸 수 있는 범위로 — 1.0 은 어떤 n 으로도 닿지 않는다."""
    return min(TARGET_MAX, max(TARGET_MIN, float(target)))


def min_r(n: int, target: float = TARGET) -> float:
    """이 n 으로 목표 검정력만큼 잡히는 **가장 작은 |상관|** (Fisher z)."""
    import numpy as np

    return float(np.tanh(_zsum(target) / np.sqrt(max(1, n - 3))))


def n_for_r(r: float, target: float = TARGET) -> int:
    """이 크기의 상관을 목표 검정력으로 잡으려면 몇 개가 필요한가 — min_r 의 역산."""
    import numpy as np

    a = abs(float(r))
    if a <= 1e-6 or a >= 0.999:
        return 0
    return int(np.ceil(3 + (_zsum(target) / np.arctanh(a)) ** 2))


def n_for_d(d: float, target: float = TARGET) -> int:
    """이 효과크기를 목표 검정력으로 잡으려면 **군당 몇 개**가 필요한가 (두 군 합계)."""
    from statsmodels.stats.power import TTestIndPower

    a = abs(float(d))
    if a <= 1e-6:
        return 0
    try:
        per = TTestIndPower().solve_power(effect_size=a, nobs1=None, ratio=1.0,
                                          alpha=ALPHA, power=clamp_target(target))
    except (ValueError, RuntimeError):
        return 0
    import math

    return 0 if not math.isfinite(per) else int(math.ceil(per) * 2)


def power(session_file: str, question: str, columns: list,
          effects: list | None = None, sample_n: int = 10_000,
          target: float = TARGET) -> dict:
    """이 표본으로 **얼마나 작은 관계까지** 잡을 수 있나 (C-09 와 같은 생각).

    관측 효과로 계산한 사후검정력은 p 값의 재표현일 뿐이다. 대신 두 가지를 말한다:
    ① 지금 n 으로는 이 크기 이상만 잡는다  ② 재 본 값이 그 선의 어느 쪽에 있는가.

    `effects` 를 주면 잰 값마다 "잡을 수 있는 크기인가 · 아니면 몇 개가 필요한가"를
    붙여 돌려준다 — 판단은 여기서 하고 껍데기는 그리기만 한다 .

    `target` 은 **화면에서 옮긴다.** 80% 는 관습이고, 95% 로 옮겼을 때 선이 어디로
    가는지를 같은 자리에서 봐야 "표본이 모자란다"는 말이 숫자가 된다.
    """
    from statop.derive.service import apply_ops, session_frame

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return {}
    sub = df[cols].dropna()
    n = int(len(sub))
    target = clamp_target(target)
    pw = f"{target * 100:g}"
    out = {"n": n, "alpha": ALPHA, "target": target, "kind": "",
           "target_min": TARGET_MIN, "target_max": TARGET_MAX,
           # 설명을 늘 깔지 않는다 — 해당되는 줄에만 그 이유가 붙는다
           "note": msg("power_note_alpha", pw=pw),
           "band": msg("power_band"), "rows": [], "ladder": []}
    if n < 5:
        return out

    if question == "Q-03":
        out["kind"] = "corr"
        out["cut"] = min_r(n, target)
        out["head"] = msg("power_head_corr", n=n, r=out["cut"], pw=pw)
        # 더 모으면 어디까지 내려가나 — 지금 n 을 포함해 몇 점만
        for k in sorted({n, n * 2, n * 4, max(100, n * 2), 200, 500}):
            if 5 < k <= 2000:
                out["ladder"].append({"n": int(k), "cut": min_r(int(k), target)})
        out["ladder"].sort(key=lambda d: d["n"])
    elif question == "Q-01" and len(cols) > 1:
        from statop.analyze.checks import power_check

        chk = power_check(sub, cols[0], cols[1], ALPHA, target)
        if chk.verdict == "skipped":
            return out
        out["kind"] = "diff"
        out["cut"] = float(chk.numbers["min_detectable_d"])
        out["head"] = msg("power_head_diff", n=n, d=out["cut"], pw=pw)
    else:
        return out

    for e in (effects or []):
        v = e.get("value")
        if v is None:
            continue
        a = abs(float(v))
        # **척도가 다르면 같은 선에 얹지 않는다.** τ 는 r 보다 작게 나오고 dCor 은
        # 늘 양수다 — 그대로 비교하면 "못 잡는 크기"라고 잘못 말하게 된다
        # (robust.py 가 검정을 바꿀 때 효과 크기를 비교하지 않는 것과 같은 이유)
        if out["kind"] == "corr" and e.get("effect_name") not in R_LIKE:
            out["rows"].append({"id": e.get("id", ""), "name": e.get("name", ""),
                                "value": float(v), "comparable": False,
                                "line": msg("power_not_comparable",
                                            eff=(e.get("effect_name")
                                                 or msg("power_this_value")))})
            continue
        near = out["cut"] * 0.8 <= a <= out["cut"] * 1.25
        row = {"id": e.get("id", ""), "name": e.get("name", ""), "value": float(v),
               "catchable": a >= out["cut"], "edge": bool(near), "comparable": True}
        if row["catchable"]:
            row["line"] = msg("power_row_edge") if near else msg("power_row_ok")
        elif out["kind"] == "corr":
            need = n_for_r(a, target)
            row["needed_n"] = need
            row["line"] = (msg("power_row_short", need=f"{need:,}", n=n, pw=pw) if need
                           else msg("power_need_huge"))
        else:
            # 차이도 **몇 개가 필요한지 풀 수 있다** — "아주 많이"로 뭉개지 않는다
            need = n_for_d(a, target)
            row["needed_n"] = need
            row["line"] = (msg("power_row_short", need=f"{need:,}", n=n, pw=pw) if need
                           else msg("power_need_huge"))
        out["rows"].append(row)
    return out


def points(session_file: str, question: str, columns: list,
           color_by: str | None = None, sample_n: int = 10_000) -> dict:
    """고른 두 컬럼을 **그림으로 볼 재료** — 점 하나하나와 군 이름.

    값과 p 만 보면 어떤 모양인지 알 수 없다. 001 의 cancer 군은 순위로는 안 보이고
    그림으로는 한눈에 보이는 V 자다 — 그림이 없으면 "왜 거리상관만 유의한가"를
    설명할 길이 없다 ( 과 같은 이유, 다만 여기는 기록하지 않는다).
    """
    import numpy as np
    import pandas as pd

    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    spec = _spec_for(question, columns)
    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    types = replay(doc)["semantic_types"].get(src["id"], {})

    xcol, ycol = (columns + [None, None])[:2]
    need = [c for c in (xcol, ycol, color_by) if c and c in df.columns]
    sub = df[list(dict.fromkeys(need))].dropna()

    x = pd.to_numeric(sub[xcol], errors="coerce") if xcol in sub else None
    y = pd.to_numeric(sub[ycol], errors="coerce") if ycol and ycol in sub else None
    kind = "scatter" if (x is not None and y is not None
                         and x.notna().all() and y.notna().all()) else "groups"

    out = {"kind": kind, "x_label": xcol or "", "y_label": ycol or "",
           "color_by": color_by or "", "n": int(len(sub)), "series": []}
    if kind == "scatter":
        if color_by and color_by in sub:
            for lv in dict.fromkeys(sub[color_by].astype(str)):
                m = sub[color_by].astype(str) == lv
                out["series"].append({"name": str(lv),
                                      "pts": [[float(a), float(b)] for a, b
                                              in zip(x[m], y[m])]})
        else:
            out["series"].append({"name": "", "pts": [[float(a), float(b)]
                                                      for a, b in zip(x, y)]})
        return out

    # 군별 분포 — 같은 축에 히스토그램을 겹친다
    if ycol and ycol in sub:
        vals = pd.to_numeric(sub[xcol], errors="coerce")
        labels = sub[ycol].astype(str)
    else:
        vals, labels = pd.to_numeric(sub[xcol], errors="coerce"), None
    ok = vals.notna()
    vals = vals[ok]
    if labels is not None:
        labels = labels[ok]
    lo, hi = float(vals.min()), float(vals.max())
    edges = np.linspace(lo, hi, 21)
    out["edges"] = [float(e) for e in edges]
    out["y_label"], out["x_label"] = ycol or "", xcol
    groups = dict.fromkeys(labels) if labels is not None else {"": None}
    for lv in groups:
        v = vals[labels == lv] if labels is not None else vals
        counts, _ = np.histogram(v.to_numpy(dtype="float64"), bins=edges)
        q = np.percentile(v, [25, 50, 75]) if len(v) else [0, 0, 0]
        out["series"].append({"name": str(lv), "n": int(len(v)),
                              "bins": [int(c) for c in counts],
                              "q1": float(q[0]), "med": float(q[1]), "q3": float(q[2]),
                              "min": float(v.min()), "max": float(v.max())})
    assert spec is not None and types is not None
    return out


def run(session_file: str, question: str, columns: list, test_id: str,
        sample_n: int = 10_000) -> dict:
    """**누른 검정 하나만** 돌린다 — 기록하지 않는다.

    쓸 수 없다고 판정된 조합도 돌린다. 값을 보고 나서 판단하라고 3색을 함께 낸다.
    """
    from statop.analyze.run import apply_label_maps, run_on
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    spec = _spec_for(question, columns)
    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    df = apply_label_maps(df, spec, replay(doc)["label_maps"].get(src["id"], {}))

    out = run_on(df, spec, test_id)
    eff = out.effect or {}
    res = {"test": out.id, "name": out.name,
           "effect_name": eff.get("name", ""), "effect": eff.get("value"),
           "p": out.p, "n": out.n, "statistic": out.statistic,
           "direction": out.direction, "notes": list(out.notes or []),
           "columns": list(columns), "question": question,
           "recorded": False}
    # **재고 나면 어디를 볼까**를 같이 낸다  — 값·p·검정력이 각각 다른 자리에
    # 흩어져 있으면 "그래서 뭘 하라고"가 남는다
    try:
        res["next"] = next_steps(session_file, question, columns, test_id, res, sample_n)
    except (ValueError, KeyError, TypeError):
        res["next"] = {}
    return res


# ── 재고 나면 어디를 봐야 하나  ──────────────────────
# 값과 p 와 검정력이 각각 다른 자리에 흩어져 있으면 "그래서 뭘 하라고"가 남는다.
# **잰 직후 한자리에서** 결론 한 줄과 다음에 볼 것을 낸다. 지어내지 않는다 —
# 전부 이 자료에서 잰 것이고, 기록도 하지 않는다.
SKEW_HIGH = 0.8          # 이보다 치우치면 로그를 권할 만하다
SKEW_OK = 0.5            # 변환 뒤 이 아래로 내려와야 "펴졌다"고 말한다
SMALL_EFFECT = 0.5       # |d| 가 이보다 작으면 "작다"
GROUP_MIN = 15           # 군이 이보다 작으면 그 군의 상관은 말하지 않는다
DCOR_GAP = 0.15          # 거리상관이 |r| 를 이만큼 앞서면 직선이 아니라고 본다


def next_steps(session_file: str, question: str, columns: list, test_id: str,
               result: dict, sample_n: int = 10_000, target: float = TARGET) -> dict:
    """이 결과를 보고 **다음에 무엇을 볼까** — 자료에서 잰 것만 낸다.

    세 갈래다. ① 효과가 작거나 경계면 표본이 얼마나 필요한가 ② 같은 군을 **다른
    컬럼**으로 보면 더 갈리는 것이 있는가 ③ 그 컬럼이 치우쳐 있으면 **무엇으로 펴는가**.

    ②는 탐색이다 — 여러 번 재는 것이므로 그 사실을 같이 말한다 (C-15).
    """
    import numpy as np
    import pandas as pd
    from scipy import stats

    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import replay

    out = {"head": "", "lines": [], "steps": [], "scan": []}
    if question not in ("Q-01", "Q-03") or len(columns) < 2:
        return out
    if question == "Q-03":
        return _steps_assoc(session_file, columns, test_id, result, sample_n, target)
    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    types = replay(doc)["semantic_types"].get(src["id"], {})
    y, group = columns[0], columns[1]
    if y not in df.columns or group not in df.columns:
        return out

    sub = df[[y, group]].dropna()
    levels = list(dict.fromkeys(sub[group].astype(str)))
    if len(levels) != 2:
        return out
    a = pd.to_numeric(sub[sub[group].astype(str) == levels[0]][y], errors="coerce").dropna()
    b = pd.to_numeric(sub[sub[group].astype(str) == levels[1]][y], errors="coerce").dropna()
    if len(a) < 3 or len(b) < 3:
        return out

    def hedges(x, z):  # noqa: ANN001, ANN202
        s = np.sqrt((x.var(ddof=1) + z.var(ddof=1)) / 2)
        return float((x.mean() - z.mean()) / s) if s else 0.0

    d_now = hedges(a, b)
    p_now = result.get("p")
    sig = p_now is not None and p_now < ALPHA
    out["head"] = msg("step_head", y=y, group=group,
                      name=result.get("name", test_id))
    out["lines"].append(msg("step_now_sig" if sig else "step_now_ns",
                            d=abs(d_now), p=("%.4g" % p_now) if p_now is not None else "-"))
    if sig and abs(d_now) < SMALL_EFFECT:
        out["lines"].append(msg("step_small_effect", d=abs(d_now)))

    # ② 같은 군을 다른 수치 컬럼으로 — 더 갈리는 것이 있나
    scan = []
    for c in df.columns:
        if c in (y, group):
            continue
        t = (types.get(c) or {}).get("type") if isinstance(types.get(c), dict) else types.get(c)
        if t in ("id", "datetime") or t in GROUPY:
            continue
        v = pd.to_numeric(df[c], errors="coerce")
        if not pd.api.types.is_numeric_dtype(v) or v.nunique(dropna=True) <= 2:
            continue
        s2 = pd.DataFrame({"v": v, "g": df[group].astype(str)}).dropna()
        x = s2[s2.g == levels[0]]["v"]
        z = s2[s2.g == levels[1]]["v"]
        if len(x) < 3 or len(z) < 3:
            continue
        d2 = hedges(x, z)
        p2 = float(stats.ttest_ind(x, z, equal_var=False).pvalue)
        row = {"column": c, "effect": d2, "p": p2, "skew": float(stats.skew(v.dropna()))}
        # ③ 치우쳤으면 **무엇으로 펴는지**를 실제로 재 본다
        if abs(row["skew"]) >= SKEW_HIGH and (v.dropna() > 0).all():
            lg = np.log(v.dropna())
            row["log_skew"] = float(stats.skew(lg))
            row["log_helps"] = abs(row["log_skew"]) <= SKEW_OK
        scan.append(row)
    scan.sort(key=lambda r: -abs(r["effect"]))
    out["scan"] = scan[:5]

    best = scan[0] if scan else None
    if best and abs(best["effect"]) > abs(d_now) * 1.5:
        out["steps"].append({
            "kind": "other_column", "column": best["column"],
            "text": msg("step_other_column", col=best["column"],
                        d=abs(best["effect"]), d0=abs(d_now))})
        if best.get("log_helps"):
            out["steps"].append({
                "kind": "derive", "column": best["column"],
                "expr": f"ln({best['column']})",
                "text": msg("step_derive_log", col=best["column"],
                            s0=abs(best["skew"]), s1=abs(best["log_skew"]))})
    if scan:
        out["lines"].append(msg("step_scan_note", n=len(scan)))

    # ① 지금 크기를 잡으려면 몇 개가 필요한가 — 검정력 쪽과 같은 수를 쓴다
    if not sig:
        from statop.analyze.checks import power_check

        chk = power_check(sub, y, group, ALPHA, clamp_target(target))
        if chk.verdict != "skipped":
            cut = float(chk.numbers["min_detectable_d"])
            if abs(d_now) < cut:
                out["steps"].append({"kind": "more_n",
                                     "text": msg("step_more_n", d=abs(d_now), cut=cut)})
    return out


def _steps_assoc(session_file: str, columns: list, test_id: str, result: dict,
                 sample_n: int, target: float) -> dict:
    """연관에서 다음에 볼 것 — **군마다 다른가**와 **직선이 아닌가**를 잰다.

    001 의 자료가 그렇다. 전체로 보면 희미한데 한 군만 V 자다. 상관계수로는 안 보이고
    거리상관으로는 보인다 — 그래서 "군마다 상관이 다른가"와 "군 안에서 직선이 아닌가"를
    **따로** 잰다. 둘 다 재 보기 전에는 말하지 않는다.
    """
    import numpy as np
    import pandas as pd

    from statop.derive.service import apply_ops, session_frame

    out = {"head": "", "lines": [], "steps": [], "scan": []}
    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    x, y = columns[0], columns[1]
    sub = df[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
    n = len(sub)
    if n < 5:
        return out
    r_all = float(np.corrcoef(sub[x], sub[y])[0, 1])
    p_now = result.get("p")
    sig = p_now is not None and p_now < ALPHA
    out["head"] = msg("step_head_assoc", x=x, y=y, name=result.get("name", test_id))
    out["lines"].append(msg("step_now_sig_assoc" if sig else "step_now_ns_assoc",
                            v=abs(result.get("effect") or 0.0),
                            eff=result.get("effect_name", ""),
                            p=("%.4g" % p_now) if p_now is not None else "-"))

    def dcor_of(s):  # noqa: ANN001, ANN202
        from statop.analyze.run import run_on

        try:
            d = run_on(s, _spec_for("Q-03", columns), "T-304")
            return float((d.effect or {}).get("value") or 0.0)
        except (ValueError, KeyError, TypeError):
            return 0.0

    # ① 군마다 — 상관이 다른가(Fisher z)와 **그 안에서 직선이 아닌가**는 다른 질문이다
    split, bent = None, None
    for c in color_columns(session_file, "Q-03", columns, sample_n):
        lv = df[c].astype(str).reindex(sub.index)
        rows = []
        for level in dict.fromkeys(lv.dropna()):
            s2 = sub[lv == level]
            if len(s2) < GROUP_MIN:
                continue
            r2 = float(np.corrcoef(s2[x], s2[y])[0, 1])
            rows.append({"level": level, "r": r2, "n": int(len(s2)),
                         "dcor": dcor_of(s2) if len(s2) <= 2000 else 0.0})
        if len(rows) < 2:
            continue
        out["scan"].append({"column": c, "overall": r_all, "groups": rows})
        # 상관이 서로 다른가 — 보기에 달라 보여도 n 이 작으면 그 차이는 못 가른다
        for i, u in enumerate(rows):
            for v2 in rows[i + 1:]:
                z = abs(np.arctanh(u["r"]) - np.arctanh(v2["r"])) / np.sqrt(
                    1 / (u["n"] - 3) + 1 / (v2["n"] - 3))
                if z >= 1.96 and split is None:
                    split = (c, u, v2)
        # 그 군 안에서 직선이 아닌가 — 거리상관이 |r| 보다 크게 앞서면 모양이 다르다
        for u in rows:
            if u["dcor"] - abs(u["r"]) >= DCOR_GAP and bent is None:
                bent = (c, u)
    if split:
        c, u, v2 = split
        out["steps"].append({"kind": "color_split", "column": c,
                             "text": msg("step_color_split", col=c, a=u["level"],
                                         ra=u["r"], b=v2["level"], rb=v2["r"], r=r_all)})
    if bent:
        c, u = bent
        out["steps"].append({"kind": "bent_group", "column": c, "level": u["level"],
                             "text": msg("step_bent_group", col=c, level=u["level"],
                                         dcor=u["dcor"], r=abs(u["r"]), n=u["n"])})

    # ② 전체로 봐도 직선이 아닌가
    if n <= 5000 and not bent:
        d = dcor_of(sub)
        if d - abs(r_all) >= DCOR_GAP:
            out["steps"].append({"kind": "nonlinear",
                                 "text": msg("step_nonlinear", dcor=d, r=abs(r_all))})

    # ③ 지금 크기를 잡으려면
    if not sig and result.get("effect_name") in R_LIKE:
        cut = min_r(n, clamp_target(target))
        v = abs(result.get("effect") or 0.0)
        if v < cut:
            out["steps"].append({"kind": "more_n",
                                 "text": msg("step_more_n_assoc", v=v, cut=cut,
                                             need=f"{n_for_r(v, clamp_target(target)):,}")})
    return out
