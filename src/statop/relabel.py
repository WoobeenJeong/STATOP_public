"""개별 샘플 라벨 수정 (DECISIONS) — 허용하되 흔적을 지울 수 없게.

수준 매핑이 그룹 정의라면, 이것은 **데이터 수정**이다. 결과를 원하는 방향으로
바꿀 수 있으므로: 원본 불변 · 사유 필수 · 출력 강제 표시 · 비율 임계 경고.
"""

from dataclasses import dataclass
from pathlib import Path

WARN_RATIO = 0.01  # 전체의 1% 초과 수정이면 빨간 경고


@dataclass
class RelabelCheck:
    n: int  # 수정 건수
    n_rows: int  # 전체 행수(추정 가능)
    ratio: float
    over_threshold: bool


def apply_relabels(df, relabels: list[dict], key_column: str):
    """재생된 relabel 기록을 DataFrame에 덮어쓴다 (사본에만 — 원본 파일은 읽기 전용).

    표식 컬럼을 함께 붙인다 — 이 사본이 파일로 저장되면 표식이 따라간다 .
    """
    out = df.copy()
    if not relabels:
        return out
    out["_relabeled"] = False
    out["_relabel_from"] = None
    out["_relabel_note"] = None
    keys = out[key_column].astype(str)
    for r in relabels:
        hit = keys == str(r["key"])
        if not hit.any():
            continue
        out.loc[hit, r["column"]] = r["to"]
        out.loc[hit, "_relabeled"] = True
        out.loc[hit, "_relabel_from"] = r["from"]
        out.loc[hit, "_relabel_note"] = r["note"]
    return out


def check_ratio(n_relabels: int, n_rows: int) -> RelabelCheck:
    ratio = (n_relabels / n_rows) if n_rows else 0.0
    return RelabelCheck(n=n_relabels, n_rows=n_rows, ratio=ratio,
                        over_threshold=ratio > WARN_RATIO)


def find_row(path: str | Path, key_column: str, key: str, column: str,
             sample_n: int = 10_000) -> str | None:
    """수정 대상 행의 현재 값을 확인한다 — 없는 키면 None."""
    from statop.io.sample import sample_rows

    df = sample_rows(path, n=sample_n)
    if key_column not in df.columns or column not in df.columns:
        from statop.messages import msg

        missing = [c for c in (key_column, column) if c not in df.columns]
        raise ValueError(msg("select_err_missing", cols=", ".join(missing)))
    hit = df[df[key_column].astype(str) == str(key)]
    if hit.empty:
        return None
    return str(hit.iloc[0][column])
