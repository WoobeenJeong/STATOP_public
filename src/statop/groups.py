"""M0-7 그룹 구조 감지 — 반복측정·환자 ID·batch·기관 후보를 찾는다.

왜 필요한가: 관측이 서로 독립이 아니면(같은 환자를 여러 번 측정, 같은 batch에서 처리)
독립 표본 검정이 성립하지 않는다(C-05). 여기서 **후보를 제시하고 사용자가 확정**한다 —
자동 판정하지 않는 이유는 컬럼 이름만으로는 확신할 수 없기 때문이다.

감지 신호(이름이 아니라 값의 구조):
- 고유값 비율이 1에 가까움 → id (그룹 구조가 아니라 식별자)
- 값이 반복됨 + 그룹당 관측 수가 2 이상 → 반복측정·군집 후보
- 소수의 수준이 전체에 퍼짐 → batch·기관 후보
컬럼명 패턴(patient, subject, batch, site…)은 **보조 신호**로만 쓴다 (과 같은 원칙).
"""

import re
from dataclasses import dataclass

# 보조 신호: 이름 패턴 — 가중치가 낮다. 값 구조가 우선
# 경계(\b)를 쓴다 — 부분 문자열 오탐 방지 (예: "label"이 "lab"에 걸리면 안 됨)
NAME_HINTS = {
    "subject": r"\b(patient|subject|animal|donor)\b|(^|_)(pid|sid|sample|case)(_?id)?$",
    "batch": r"\b(batch|plate|run|lane|chip|slide|flowcell)\b",
    "site": r"\b(site|center|centre|hospital|institution|clinic|lab)\b",
    "time": r"\b(visit|timepoint|week|day|cycle|session)\b|(^|_)time(point)?$",
}

MIN_REPEAT = 2        # 그룹당 평균 관측이 이 값 이상이면 반복 구조로 본다
ID_UNIQUE_RATIO = 0.9  # 고유값 비율이 이보다 크면 식별자
MAX_LEVELS_FOR_GROUP = 0.5  # 수준 수가 행의 절반을 넘으면 그룹으로 보기 어렵다


@dataclass
class GroupCandidate:
    column: str
    n_levels: int
    unique_ratio: float
    mean_per_group: float       # 그룹당 평균 관측 수 (2 이상이면 반복)
    max_per_group: int
    balanced: bool              # 그룹 크기가 고른가
    kind: str                   # subject | batch | site | time | unknown
    is_identifier: bool         # 사실상 id (그룹 구조 아님)
    name_hint: bool             # 이름 패턴이 맞았는가 (보조 신호)
    reason: str                 # 왜 후보로 올렸는지 — 사용자가 판단할 근거


def _kind_from_name(column: str) -> tuple[str, bool]:
    low = column.lower()
    for kind, pat in NAME_HINTS.items():
        if re.search(pat, low):
            return kind, True
    return "unknown", False


def detect(df, min_repeat: float = MIN_REPEAT) -> list[GroupCandidate]:
    """반복·군집 구조 후보를 찾아 근거와 함께 반환한다 (확정은 사용자 몫)."""
    from statop.messages import msg

    n = len(df)
    out: list[GroupCandidate] = []
    for col in df.columns:
        s = df[col].dropna()
        if s.empty:
            continue
        # 연속형 실수는 그룹이 될 수 없다 (정수·문자·범주만 후보)
        if s.dtype.kind == "f" and (s % 1 != 0).any():
            continue
        counts = s.value_counts()
        n_levels = int(len(counts))
        unique_ratio = n_levels / len(s)
        mean_per = float(len(s) / n_levels)
        kind, name_hint = _kind_from_name(col)

        is_id = unique_ratio >= ID_UNIQUE_RATIO
        if is_id:
            # 식별자는 그룹 구조가 아니다 — 다만 hold 제안 대상이라 목록에는 남긴다
            out.append(GroupCandidate(
                column=col, n_levels=n_levels, unique_ratio=unique_ratio,
                mean_per_group=mean_per, max_per_group=int(counts.max()),
                balanced=True, kind=kind if name_hint else "unknown",
                is_identifier=True, name_hint=name_hint,
                reason=msg("group_reason_id", ratio=unique_ratio)))
            continue

        if mean_per < min_repeat or unique_ratio > MAX_LEVELS_FOR_GROUP:
            continue  # 반복이 없으면 군집 구조로 볼 근거가 없다

        cv = float(counts.std() / counts.mean()) if counts.mean() else 0.0
        out.append(GroupCandidate(
            column=col, n_levels=n_levels, unique_ratio=unique_ratio,
            mean_per_group=mean_per, max_per_group=int(counts.max()),
            balanced=cv < 0.5, kind=kind, is_identifier=False, name_hint=name_hint,
            reason=msg("group_reason_repeat", levels=n_levels, mean=mean_per)))

    # 반복이 강한 순 → 이름 힌트가 있는 순
    out.sort(key=lambda g: (g.is_identifier, -g.mean_per_group, not g.name_hint))
    return out


def compose(df, selected: list[str], held: list[str] | None = None) -> dict:
    """M0-2b 구성 요약 — 가져온 컬럼만 대상으로 한 눈에 보는 상태.

    데이터 셀은 넣지 않는다(점진 노출). 숫자·구조만.
    """
    held = held or []
    analysis = [c for c in selected if c not in held]
    kinds = {"numeric": 0, "categorical": 0, "datetime": 0}
    for c in analysis:
        if c not in df.columns:
            continue
        k = df[c].dtype.kind
        if k in "ifb":
            kinds["numeric"] += 1
        elif k == "M":
            kinds["datetime"] += 1
        else:
            kinds["categorical"] += 1
    miss = df[analysis].isna() if analysis else df.iloc[:, :0]
    return {
        "n_rows": len(df),
        "n_selected": len(selected),
        "n_analysis": len(analysis),
        "n_held": len(held),
        "kinds": kinds,
        "complete_rows": int((~miss.any(axis=1)).sum()) if analysis else len(df),
        "any_missing": int(miss.any(axis=1).sum()) if analysis else 0,
    }
