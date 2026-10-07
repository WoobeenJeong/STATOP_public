"""파싱된 수식을 실제 값으로 계산한다 — 화이트리스트 함수만 실행한다.

`eval`을 쓰지 않는다. AST를 직접 순회하며 허용된 노드·함수만 처리한다.
"""

import ast

import numpy as np
import pandas as pd

from statop.derive.parser import CONSTANTS, EPS_NAME, Parsed


class EvalError(ValueError):
    pass


def _column_scalar(name: str, series: pd.Series) -> float:
    return {"sum": series.sum, "mean": series.mean, "sd": series.std,
            "median": series.median, "min": series.min, "max": series.max}[name]()


def evaluate(parsed: Parsed, df: pd.DataFrame, eps: float | None = None,
             composition: list[str] | None = None) -> pd.Series:
    """수식을 계산해 새 컬럼 값을 만든다.

    composition: clr/ilr처럼 세트 전체가 필요한 함수에 쓸 컬럼 목록 (M1-3).
    """
    from statop.messages import msg

    def ev(node: ast.AST):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id == EPS_NAME:
                if eps is None:
                    raise EvalError(msg("eps_required"))
                return eps
            if node.id in CONSTANTS and node.id not in df.columns:
                return CONSTANTS[node.id]
            if node.id in df.columns:
                return df[node.id]
            raise EvalError(msg("formula_unknown_column", cols=node.id))
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else +v
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            op = type(node.op)
            if op is ast.Add:
                return a + b
            if op is ast.Sub:
                return a - b
            if op is ast.Mult:
                return a * b
            if op is ast.Div:
                return a / b
            if op is ast.Pow:
                return a ** b
            raise EvalError(msg("formula_node_not_allowed", node=op.__name__, expr=parsed.expr))
        if isinstance(node, ast.Call):
            name = node.func.id
            args = [ev(a) for a in node.args]
            return _call(name, args, df, eps, composition, parsed)
        raise EvalError(msg("formula_node_not_allowed",
                            node=type(node).__name__, expr=parsed.expr))

    out = ev(parsed.tree)
    if np.isscalar(out):      # 전체가 스칼라면 모든 행에 같은 값
        return pd.Series([out] * len(df), index=df.index)
    return pd.Series(out, index=df.index)


def _call(name: str, args: list, df: pd.DataFrame, eps: float | None,
          composition: list[str] | None, parsed: Parsed):
    from statop.messages import msg

    a = args[0] if args else None
    if name in ("log", "ln"):
        return np.log(a)
    if name == "log2":
        return np.log2(a)
    if name == "log10":
        return np.log10(a)
    if name == "exp":
        return np.exp(a)
    if name == "abs":
        return np.abs(a)
    if name == "sqrt":
        return np.sqrt(a)
    if name == "arcsinh":
        # 0·음수에서 끊기지 않고, 큰 값에서는 log 처럼 거동한다 (S-R04 의 권고).
        # eps 를 더하지 않으므로 **더한 값에 따라 결과가 달라지는 문제가 없다**
        return np.arcsinh(a)
    if name == "pow":
        return a ** args[1]
    if name in ("round", "floor", "ceil", "trunc"):
        # 소수점 자리수 — round(x, 3) 처럼 둘째 인자로 자리수를 준다 (기본 0)
        nd = int(args[1]) if len(args) > 1 else 0
        f = 10.0 ** nd
        if name == "round":
            return np.round(a * f) / f
        if name == "floor":
            return np.floor(a * f) / f
        if name == "ceil":
            return np.ceil(a * f) / f
        return np.trunc(a * f) / f
    if name in ("floor_to", "round_to", "ceil_to"):
        # 구간화 — floor_to(age, 10) 이면 23→20, 39→30 (10대·20대…)
        if len(args) < 2:
            raise EvalError(msg("formula_needs_step", func=name))
        step = float(args[1])
        if step <= 0:
            raise EvalError(msg("formula_step_positive", func=name))
        q = a / step
        q = np.floor(q) if name == "floor_to" else (
            np.round(q) if name == "round_to" else np.ceil(q))
        return q * step
    if name == "bin":
        # bin(x, e1, e2, …) — 경계를 직접 준다. 값은 **그 구간의 시작값**이 된다
        edges = sorted(float(v) for v in args[1:])
        if len(edges) < 2:
            raise EvalError(msg("formula_needs_edges", func=name))
        idx = np.digitize(np.asarray(a, dtype="float64"), edges, right=False) - 1
        idx = np.clip(idx, 0, len(edges) - 2)
        return pd.Series(np.take(edges[:-1], idx),
                         index=a.index if isinstance(a, pd.Series) else None)
    if name == "logit":
        p = np.clip(a, eps if eps else 1e-12, 1 - (eps if eps else 1e-12))
        return np.log(p / (1 - p))
    if name in ("sum", "mean", "sd", "median", "min", "max"):
        if isinstance(a, pd.Series):
            return _column_scalar(name, a)
        return a
    if name == "zscore":
        return (a - a.mean()) / a.std()
    if name == "rank":
        return a.rank()
    if name == "alr":
        return np.log((args[0] + (eps or 0)) / (args[1] + (eps or 0)))
    if name in ("clr", "ilr"):
        if not composition:
            raise EvalError(msg("formula_needs_composition", func=name))
        block = df[composition].astype("float64")
        if eps:
            block = block + eps
        logs = np.log(block)
        centered = logs.sub(logs.mean(axis=1), axis=0)   # CLR: 기하평균으로 중심화
        col = parsed.columns[0] if parsed.columns else composition[0]
        if name == "clr":
            return centered[col]
        # ILR은 CLR을 직교기저로 사영 — v1은 첫 좌표만 (고급, 기본 숨김: F-13)
        return centered.iloc[:, 0] * np.sqrt(len(composition) / (len(composition) - 1))
    raise EvalError(msg("formula_func_not_allowed", func=name, allowed=""))


# 값을 되돌릴 수 없게 줄이는 함수 — 미리보기에서 손실을 수치로 보여준다
LOSSY_FUNCS = {"round", "floor", "ceil", "trunc", "floor_to", "round_to",
               "ceil_to", "bin"}


def preview(parsed: Parsed, df: pd.DataFrame, eps: float | None = None,
            composition: list[str] | None = None) -> dict:
    """커밋 전 미리보기 — 분포·결측·무한대 발생 수 (M1-2).

    `log(0)`·0 나눗셈으로 생기는 ±inf와 NaN을 **개수로** 보여준다.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        s = evaluate(parsed, df, eps=eps, composition=composition)
    arr = pd.to_numeric(s, errors="coerce")
    n_inf = int(np.isinf(arr).sum())
    n_nan = int(arr.isna().sum()) - int(np.isinf(arr).sum() * 0)
    finite = arr.replace([np.inf, -np.inf], np.nan).dropna()
    out = {
        "n": int(len(arr)),
        "n_inf": n_inf,
        "n_nan": int(arr.isna().sum()),
        "n_finite": int(len(finite)),
        "min": float(finite.min()) if len(finite) else None,
        "max": float(finite.max()) if len(finite) else None,
        "mean": float(finite.mean()) if len(finite) else None,
        "values": finite,
    }
    # 구간화·반올림은 값을 **되돌릴 수 없게** 줄인다. 몇 개가 몇 개로 줄었는지 보여야
    # "이렇게까지 뭉갤 생각은 아니었다"를 커밋 전에 알아챈다
    if set(parsed.functions) & LOSSY_FUNCS and parsed.columns:
        src = pd.to_numeric(df[parsed.columns[0]], errors="coerce").dropna()
        out["distinct_before"] = int(src.nunique())
        out["distinct_after"] = int(finite.nunique())
        out["levels"] = [float(v) for v in sorted(finite.unique())[:12]]
    return out
