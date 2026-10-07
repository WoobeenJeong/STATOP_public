"""M0-6 행 필터 — 조건식으로 행을 제외한다. 제외 사유는 출력에 항상 첨부된다.

임의 코드 실행을 막기 위해 **제한된 식**만 받는다 (pandas.query 화이트리스트).
"""

import re
from dataclasses import dataclass

# 허용 문법: 컬럼명·숫자·문자열·비교/논리 연산·괄호·in. 그 외는 전부 거부한다.
# (정규식 안의 주석은 영어로 — 하드코딩 스캔이 사용자 문장과 구분하지 못하므로)
_ALLOWED = re.compile(
    r"""^(?:
        [\w.]+                      # column name or number
      | '[^']*' | "[^"]*"          # string literal
      | [<>=!]=? | <= | >=          # comparison
      | \band\b | \bor\b | \bnot\b | \bin\b
      | [()\[\],\s&|~+\-*/]
      )+$""",
    re.X,
)
_FORBIDDEN = re.compile(r"(__|import|eval|exec|open|lambda|@)")


@dataclass
class FilterResult:
    kept: int
    removed: int
    total: int
    ratio_removed: float


def validate_expr(expr: str) -> None:
    """식이 안전한지 검사한다 — 통과 못 하면 시끄럽게 실패한다."""
    from statop.messages import msg

    if not expr.strip():
        raise ValueError(msg("filter_empty"))
    if _FORBIDDEN.search(expr) or not _ALLOWED.match(expr):
        raise ValueError(msg("filter_unsafe", expr=expr))


def apply_filter(df, expr: str, keep: bool = True):
    """조건에 맞는 행만 남긴다(keep=True) 또는 제외한다(keep=False)."""
    from statop.messages import msg

    validate_expr(expr)
    try:
        mask = df.eval(expr)
    except Exception as e:  # 컬럼 오타·타입 불일치 등
        raise ValueError(msg("filter_bad_expr", expr=expr, err=str(e)[:80]))
    if mask.dtype != bool:
        raise ValueError(msg("filter_not_boolean", expr=expr))
    return df[mask] if keep else df[~mask]


def preview(df, expr: str, keep: bool = True) -> FilterResult:
    """실행 전에 몇 행이 남고 빠지는지 — 누르기 전에 결과를 본다."""
    out = apply_filter(df, expr, keep=keep)
    total = len(df)
    return FilterResult(kept=len(out), removed=total - len(out), total=total,
                        ratio_removed=(total - len(out)) / total if total else 0.0)
