"""M3 점수(지표) 목록 —  3색 필터 ·  수식·대입식 ·  분포 의존 분기.

`rules/scores.yaml` 122종을 **지금 데이터에 대보고** 4등급으로 나눈다:
안됨(빨강) / 별로(노랑) / 문제없음(초록) / **미지정(회색)**.

미지정은 "적합하다"가 아니라 **"판정할 근거가 아직 없다"** 이다 (grades 정의). 규칙 DB의
해당 칸이 비어 있거나(unspecified) 데이터에서 확인할 수 없으면 초록으로 올리지 않는다 —
회색으로 두고 무엇이 없어 판정을 못 했는지 말한다.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from statop.messages import msg

GREEN, YELLOW, RED, UNSET = "green", "yellow", "red", "unset"
ORDER = {GREEN: 0, YELLOW: 1, UNSET: 2, RED: 3}

# `input` 칸의 표현 → 이 지표가 요구하는 데이터 모양. 규칙 DB 문구를 그대로 읽는다.
_NEEDS = [
    ("simplex", ("심플렉스", "조성")),  # rule-vocab
    ("unit", ("[0,1]", "확률", "비율")),  # rule-vocab
    ("positive", ("ℝ⁺",)),
    ("count", ("카운트",)),  # rule-vocab
    ("binary", ("이진", "라벨")),  # rule-vocab
    ("angle", ("각도", "주기")),  # rule-vocab
    ("vector", ("ℝ^d", "임베딩", "좌표")),  # rule-vocab
    ("distribution", ("확률분포",)),  # rule-vocab
    ("continuous", ("연속", "ℝ", "점수", "예측값")),  # rule-vocab
]

# "두 연속 컬럼" 처럼 **개수**를 말하는 표현 — 컬럼 하나로는 만족되지 않는다
_COUNT_WORDS = {"두": 2, "2": 2, "세": 3, "3": 3}  # rule-vocab

# 의미 타입 → 그 컬럼이 만족하는 모양
_TYPE_SHAPES = {
    "proportion": {"unit", "positive", "continuous", "simplex"},
    "probability": {"unit", "positive", "continuous", "distribution"},
    "percent": {"positive", "continuous"},
    "count": {"count", "positive"},
    "continuous": {"continuous"},
    "log-scale": {"continuous"},
    "clr": {"continuous"},
    "z-score": {"continuous"},
    "ordinal code": {"count", "binary"},
    "nominal code": {"binary"},
    "label": {"binary"},
    "datetime": set(),
    "id": set(),
}


@dataclass
class ScoreEntry:
    id: str
    name: str
    family: str
    section: str
    latex: str = ""
    input: str = ""
    verdict: str = UNSET
    why: str = ""
    substituted: str = ""          #  대입식 — 실제 컬럼 이름을 넣은 형태
    columns: list = field(default_factory=list)
    note: str = ""
    coverage: str = "none"
    #  대안 묶음 축 — "왜 이것 대신 저것인가"에 답하는 네 칸
    purpose: str = ""
    purpose_name: str = ""
    measures: str = ""
    scale: str = ""
    shaken_by: str = ""            # 무엇에 흔들리나 (등급은 두지 않는다)
    #  작성자 검토 — 쓰기로 했으면 무엇을 함께 보고하나 / 무엇을 근거로 하나
    recommend: str = ""
    source: str = ""


@lru_cache(maxsize=1)
def _db() -> dict:
    import yaml

    from statop.rules.build import RULES_DIR

    return yaml.safe_load((RULES_DIR / "scores.yaml").read_text(encoding="utf-8"))


def _requirements(input_text: str) -> list[set[str]]:
    """`input` 을 '+' 로 나눠 **각 자리마다** 요구 모양을 낸다.

    "점수 + 이진" 은 컬럼 하나로 만족되지 않는다 — 연속 점수 하나와 이진 라벨 하나가
    따로 있어야 한다. 하나로 묶어 보면 라벨 컬럼만 있어도 ROC-AUC 가 초록이 된다.
    """
    parts = [p for p in re.split(r"[+＋]", input_text or "") if p.strip()]
    out: list[set[str]] = []
    for part in parts:
        need = {k for k, words in _NEEDS if any(w in part for w in words)}
        if not need:
            continue
        # "두 연속 컬럼" 은 같은 모양의 컬럼이 **둘** 필요하다는 뜻이다
        n = next((v for w, v in _COUNT_WORDS.items()
                  if re.search(rf"{w}\s*(개|연속|컬럼|변수)", part)), 1)  # rule-vocab
        out += [need] * n
    return out


def _assign(reqs: list[set[str]], cols: list[str],
            shapes: dict[str, set[str]]) -> list[str]:
    """요구 자리마다 서로 **다른** 컬럼을 하나씩 배정한다. 못 채우면 빈 목록."""
    used, picked = set(), []
    for need in reqs:
        hit = next((c for c in cols if c not in used and need <= shapes[c]), None)
        if hit is None:
            return []
        used.add(hit)
        picked.append(hit)
    return picked


def _shapes_of(df: pd.DataFrame, col: str, semantic: str | None) -> set[str]:
    """이 컬럼이 만족하는 모양 — 확정된 의미 타입이 우선, 없으면 값에서 본다."""
    if semantic in _TYPE_SHAPES:
        return set(_TYPE_SHAPES[semantic])
    if col not in df.columns:
        return set()
    v = pd.to_numeric(df[col], errors="coerce").dropna()
    if v.empty:
        return {"binary"} if df[col].nunique() <= 2 else set()
    out = {"continuous"}
    if (v >= 0).all():
        out.add("positive")
    if v.between(0, 1).all():
        out.add("unit")
    if np.allclose(v, np.round(v)) and (v >= 0).all():
        out.add("count")
    if v.nunique() <= 2:
        out.add("binary")
    return out


def catalog(session_file: str, sample_n: int = 10_000,
            family: str | None = None) -> list[ScoreEntry]:
    """122종을 지금 데이터에 대본다 . 판정 못 하면 초록이 아니라 회색이다."""
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import load_session, main_source, replay

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    st = replay(doc)
    types = st["semantic_types"].get(src["id"], {})
    cols = [c for c in st["selected"].get(src["id"], list(df.columns))
            if c in df.columns and types.get(c) != "id"]
    shapes = {c: _shapes_of(df, c, types.get(c)) for c in cols}

    out = []
    for s in _db()["scores"]:
        if family and s["family"] != family:
            continue
        e = ScoreEntry(id=s["id"], name=s["name"], family=s["family"],
                       section=s.get("section", ""), latex=s.get("latex") or "",
                       input=s.get("input") or "", note=s.get("note") or "",
                       coverage=s.get("coverage") or "none",
                       purpose=s.get("purpose") or "",
                       measures=s.get("measures") or "",
                       scale=s.get("scale") or "",
                       shaken_by=s.get("shaken_by") or "",
                       recommend=s.get("recommend") or "",
                       source=s.get("source") or "")
        e.purpose_name = _purpose_names().get(e.purpose, "")
        reqs = _requirements(e.input)
        fit = _assign(reqs, cols, shapes)
        e.columns = fit
        flat = set().union(*reqs) if reqs else set()
        if not reqs:
            # 무엇이 필요한지 규칙 DB에 안 적혀 있다 — 적합하다고 말할 근거가 없다
            e.verdict, e.why = UNSET, msg("scores_unset_no_input")
        elif fit:
            e.verdict, e.why = GREEN, msg("scores_fit", cols=", ".join(fit))
        elif any(flat & shapes[c] for c in cols):
            e.verdict = YELLOW
            e.why = msg("scores_partial", need=", ".join(sorted(flat)))
        else:
            e.verdict = RED
            e.why = msg("scores_no_fit", need=", ".join(sorted(flat)))
        # 규칙 DB 가 그 등급 칸을 비워 뒀으면 판정을 밀어붙이지 않는다 ( 공백)
        if s.get("unspecified") and e.verdict in (GREEN, YELLOW):
            missing = ", ".join(s["unspecified"])
            e.why += "  " + msg("scores_unspecified_cell", cells=missing)
        e.substituted = substitute(e, fit)
        out.append(e)
    out.sort(key=lambda x: (ORDER[x.verdict], x.id))
    return out


@lru_cache(maxsize=1)
def _purpose_names() -> dict:
    return {g["id"]: g["name"] for g in _db()["purposes"]}


@dataclass
class PurposeGroup:
    """같은 목적의 지표 묶음 . **고르는 것은 사용자다** — 도구는 늘어놓기만 한다."""

    id: str
    name: str
    entries: list = field(default_factory=list)


def groups(session_file: str, sample_n: int = 10_000,
           family: str | None = None) -> list[PurposeGroup]:
    """묶음별로 모은 목록. 같은 것을 재는 대안이 무엇인지 한 자리에서 보인다 .

    묶음 안은 판정 순서로 세운다. **어느 것이 더 강건한지는 여기서 정하지 않는다** —
    그건 자료에 따라 달라서 `statop robust` 가 그 자료에서 직접 잰다.
    """
    entries = catalog(session_file, sample_n, family)
    names = _purpose_names()
    out: dict[str, PurposeGroup] = {}
    for e in entries:
        g = out.setdefault(e.purpose, PurposeGroup(id=e.purpose,
                                                   name=names.get(e.purpose, "")))
        g.entries.append(e)
    for g in out.values():
        g.entries.sort(key=lambda x: (ORDER[x.verdict], x.id))
    return sorted(out.values(), key=lambda g: g.id)


def substitute(entry: ScoreEntry, columns: list[str]) -> str:
    """S168 대입식 — 수식의 변수 자리에 **이 데이터의 컬럼 이름**을 넣어 보여준다.

    값을 넣지는 않는다. 어떤 컬럼이 어느 자리에 들어가는지가 먼저 맞아야 한다.
    """
    if not columns:
        return ""

    def name(col: str) -> str:
        # 컬럼 이름의 _ 는 LaTeX 에서 아래첨자다 — 그대로 두면 수식이 깨진다
        return r"\mathrm{" + col.replace("_", r"\_") + "}"

    first = name(columns[0])
    second = name(columns[1]) if len(columns) > 1 else first
    tex = entry.latex
    # 긴 패턴부터 — \hat y_i 를 먼저 바꿔야 y_i 가 그 안을 건드리지 않는다
    for pat, rep in ((r"\\hat\s*y_i", second + "_i"), (r"\\hat\s*y", second),
                     (r"\by_i\b", first + "_i"), (r"\by\b", first),
                     (r"\bx_i\b", first + "_i"), (r"\bx\b", first),
                     (r"\bp_j\b", first + "_j")):
        tex = re.sub(pat, lambda _m, r=rep: r, tex)
    return tex


# ──  분포 의존 항목 분기 (엔트로피) ─────────────────────
# 연속 분포의 엔트로피는 **분포마다 공식이 다르다**. 아무 공식이나 쓰면 값이 뜻을 잃는다.
_ENTROPY_BRANCH = [
    # ① 공간이 정해 주는 것부터 — 조성·[0,1]·각도는 다른 후보가 아예 성립하지 않는다
    ("SC-ENT-07", lambda d: d["simplex"]),
    ("SC-ENT-03", lambda d: d["unit"]),
    ("SC-ENT-10", lambda d: d["angle"]),
    # ② 정규가 맞으면 정규다. 정규 자료도 log 를 씌우면 대칭이라 로그정규를 먼저 물으면
    #    정규 자료가 로그정규로 새 버린다
    ("SC-ENT-01", lambda d: d["normal"]),
    # ③ 양수 계열 — 지수(CV≈1)가 감마·Student t 보다 좁은 조건이므로 먼저 본다
    ("SC-ENT-06", lambda d: d["positive"] and d["skewed"] and d["log_normal"]),
    ("SC-ENT-05", lambda d: d["positive"] and d["exponential"]),
    ("SC-ENT-04", lambda d: d["positive"] and d["skewed"]),
    # ④ 중꼬리 — 분산이 발산하는 Cauchy 를 Student t 보다 먼저
    ("SC-ENT-08", lambda d: d["heavy_tail"] and d["sd_vs_iqr"] > 5),
    ("SC-ENT-09", lambda d: d["heavy_tail"]),
    # ⑤ 분포를 모르면 추정으로. 표본이 모자라면 이산화가 마지막
    ("SC-ENT-11", lambda d: d["n"] >= 100),
    ("SC-ENT-12", lambda _d: True),
]


@dataclass
class EntropyChoice:
    column: str
    picked: str = ""
    name: str = ""
    latex: str = ""
    why: str = ""
    facts: dict = field(default_factory=dict)
    rejected: list = field(default_factory=list)   # [{id, name, why}]


def entropy_branch(session_file: str, column: str,
                   sample_n: int = 10_000) -> EntropyChoice:
    """이 컬럼의 엔트로피를 어느 공식으로 재야 하는지 고른다 .

    고른 이유와 **버린 이유**를 함께 돌려준다 — 왜 정규 공식을 못 쓰는지가 결론의 절반이다.
    """
    from scipy import stats

    from statop.derive.service import apply_ops, session_frame
    from statop.semantic import composition_set
    from statop.session.core import load_session, main_source, replay

    doc, src, df = session_frame(session_file, sample_n)
    df = apply_ops(df, doc, src["id"])
    if column not in df.columns:
        raise ValueError(msg("select_err_missing", cols=column))
    types = replay(doc)["semantic_types"].get(src["id"], {})
    v = pd.to_numeric(df[column], errors="coerce").dropna().to_numpy("float64")
    if v.size < 8:
        raise ValueError(msg("run_need_numeric", cols=column))

    t = types.get(column)
    if t in ("count", "ordinal code", "nominal code", "label"):
        # 연속 분포의 미분 엔트로피는 이산 컬럼에 쓰는 것이 아니다 (4.3절)
        raise ValueError(msg("scores_ent_discrete", col=column, type=t))
    pos = bool((v > 0).all())
    facts = {
        "n": int(v.size),
        "simplex": t == "proportion" and len(composition_set(df, column)) >= 2,
        "unit": bool((v >= 0).all() and (v <= 1).all()) or t in ("probability",),
        "angle": t == "datetime" or bool(re.search(r"angle|phase|각도|위상|hour|시각",  # rule-vocab
                                                   column, re.I)),
        "positive": pos,
        "skewed": abs(float(stats.skew(v))) > 1.0,
        "kurtosis": float(stats.kurtosis(v, fisher=True)),
        "heavy_tail": float(stats.kurtosis(v, fisher=True)) > 3.0,
        "normal": bool(stats.shapiro(v[:5000]).pvalue > 0.05) if v.size <= 5000
        else abs(float(stats.skew(v))) < 0.5,
        # 로그정규와 지수는 원자료만 보면 둘 다 "양수·오른쪽 꼬리"라 구별되지 않는다.
        # log 를 씌워 보면 갈린다: 로그정규는 대칭이 되고, 지수는 왼쪽으로 치우친다
        "log_skew": float(stats.skew(np.log(v[v > 0]))) if pos else float("nan"),
        "log_normal": pos and abs(float(stats.skew(np.log(v[v > 0])))) < 0.5,
        "exponential": pos and abs(float(v.std(ddof=1) / (v.mean() or 1)) - 1.0) < 0.2
        and float(stats.skew(np.log(v[v > 0]))) < -0.7,
        # Cauchy 는 분산이 정의되지 않는다 — 표본 SD 가 IQR 기반 산포보다 터무니없이 커진다
        "sd_vs_iqr": float(v.std(ddof=1) /
                           ((np.percentile(v, 75) - np.percentile(v, 25)) / 1.349
                            or 1e-12)),
    }

    entries = {s["id"]: s for s in _db()["scores"] if s["family"] == "ENT"}
    out = EntropyChoice(column=column, facts=facts)
    for sid, cond in _ENTROPY_BRANCH:
        e = entries.get(sid)
        if e is None:
            continue
        if cond(facts):
            out.picked, out.name, out.latex = sid, e["name"], e.get("latex") or ""
            out.why = msg("scores_ent_picked", name=e["name"],
                          green=e.get("green") or "-")
            break
        out.rejected.append({"id": sid, "name": e["name"],
                             "why": e.get("red") or msg("scores_ent_cond_unmet")})
    return out
