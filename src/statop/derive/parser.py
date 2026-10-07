"""M1-2 수식 파서 — 화이트리스트(F-01~14)만 허용한다. 임의 코드 실행 불가.

LaTeX와 일반 표기를 **같은 AST**로 읽는다 — 렌더와 계산이 어긋나지 않아야 하기 때문
(요구사항검수 기준: "렌더와 계산식 불일치 0").

지원 형태:
  일반  log2(frac + abs(size / sum(size)) + eps)
  LaTeX \\log_2\\left(\\texttt{frac} + \\lvert\\frac{\\texttt{size}}{\\sum_i \\texttt{size}}\\rvert + \\varepsilon\\right)
"""

import ast
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# 행 단위 함수 — 각 행에 적용
ROW_FUNCS = {"log", "log2", "log10", "ln", "abs", "sqrt", "pow", "exp",
             "arcsinh",
             "logit", "rank_row",
             # 자리수·구간 (나이 23→20 처럼 값을 묶거나 소수점을 줄인다).
             # 값을 줄이는 연산이라 되돌릴 수 없다 — 미리보기에서 몇 개로 줄었는지 보여준다
             "round", "floor", "ceil", "trunc",
             "floor_to", "round_to", "ceil_to", "bin"}
# 컬럼 스칼라 — 컬럼 전체를 하나의 수로 (UI에서 색을 달리 표시, F-04)
COLUMN_FUNCS = {"sum", "mean", "sd", "median", "min", "max", "zscore", "rank"}
# 세트 함수 — 조성 전체가 필요 (F-11~13)
SET_FUNCS = {"clr", "ilr"}
# 두 컬럼 함수
PAIR_FUNCS = {"alr"}

ALL_FUNCS = ROW_FUNCS | COLUMN_FUNCS | SET_FUNCS | PAIR_FUNCS
EPS_NAME = "eps"
# 수학 상수 — 엔트로피처럼 공식에 그대로 들어가는 식이 있다. 3.141592653589793 을
# 손으로 적게 하면 자릿수에서 틀리고, 틀려도 식만 봐서는 안 보인다
import math as _math  # noqa: E402

CONSTANTS = {"pi": _math.pi, "e": _math.e}


@dataclass
class Parsed:
    expr: str                       # 정규화된 일반 표기
    columns: list[str] = field(default_factory=list)   # 쓰인 컬럼
    functions: list[str] = field(default_factory=list)  # 쓰인 함수
    uses_eps: bool = False
    scopes: set[str] = field(default_factory=set)      # row / column_scalar / set / pair
    tree: ast.Expression | None = None


class FormulaError(ValueError):
    """수식이 허용 문법을 벗어남 — 조용히 넘어가지 않는다."""


# ── LaTeX → 일반 표기 ────────────────────────────────────────
_LATEX_STEPS: list[tuple[str, str]] = [
    (r"\\left", ""), (r"\\right", ""),
    (r"\\varepsilon|\\epsilon", EPS_NAME),
    (r"\\texttt\{([^}]*)\}", r"\1"),
    (r"\\mathrm\{([^}]*)\}", r"\1"),
    (r"\\operatorname\{([^}]*)\}", r"\1"),
    (r"\\log_2", "log2"), (r"\\log_\{2\}", "log2"),
    (r"\\log_\{?10\}?", "log10"),
    (r"\\ln", "ln"), (r"\\log", "log"), (r"\\exp", "exp"),
    (r"\\lvert([^|]*)\\rvert", r"abs(\1)"),
    (r"\\\|([^|]*)\\\|", r"abs(\1)"),
    (r"\\sum_\{?i\}?\s*", "sum "),      # 컬럼 합 — sum(col)로 이어진다
    (r"\\sum_\{?j\\in\s*set\}?\s*", "setsum "),
    (r"\\cdot|\\times", "*"), (r"\\div", "/"),
    (r"\\,|\\;|\\!|\\quad|\\qquad", " "),
    (r"\\_", "_"),      # \texttt{frac\_A} — 우리가 렌더한 식을 되붙여넣어도 열려야 한다
    # 남은 중괄호는 묶음일 뿐이다. 괄호로 바꾸지 않으면 파이썬이 집합 리터럴로 읽는다
    (r"\^\s*\{([^{}]*)\}", r"**(\1)"),
    (r"\{([^{}]*)\}", r"(\1)"),
]


def _brace_group(s: str, i: int) -> tuple[str, int]:
    """s[i]가 '{'일 때 짝이 맞는 '}'까지의 안쪽 내용과 그 다음 위치를 돌려준다."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    raise FormulaError(s)


def _expand_braced(src: str) -> str:
    """\\frac·\\sqrt를 괄호 균형을 세어 펼친다 — 중첩된 중괄호를 정규식으로는 못 센다."""
    for name, arity in (("frac", 2), ("sqrt", 1)):
        cmd = "\\" + name
        while (at := src.find(cmd)) >= 0:
            i = at + len(cmd)
            while i < len(src) and src[i] == " ":
                i += 1
            if i >= len(src) or src[i] != "{":
                raise FormulaError(src)
            args = []
            for _ in range(arity):
                if i >= len(src) or src[i] != "{":
                    raise FormulaError(src)
                inner, i = _brace_group(src, i)
                args.append(_expand_braced(inner))
            repl = f"(({args[0]})/({args[1]}))" if arity == 2 else f"sqrt({args[0]})"
            src = src[:at] + repl + src[i:]
    return src


def latex_to_plain(src: str) -> str:
    """LaTeX를 일반 표기로. 남은 백슬래시 명령이 있으면 실패한다(조용히 버리지 않는다)."""
    out = src.strip()
    if out.startswith("$") and out.endswith("$"):
        out = out[1:-1]
    out = _expand_braced(out)
    for pat, rep in _LATEX_STEPS:
        prev = None
        while prev != out:          # \frac 중첩 등은 반복 적용
            prev = out
            out = re.sub(pat, rep, out)
    out = re.sub(r"\s*sum\s+(\w+)", r"sum(\1)", out)       # "sum x" → sum(x)
    out = re.sub(r"\s*setsum\s+(\w+)", r"setsum(\1)", out)
    leftover = re.findall(r"\\[a-zA-Z]+", out)
    if leftover:
        from statop.messages import msg

        raise FormulaError(msg("formula_latex_unsupported", items=", ".join(sorted(set(leftover)))))
    return re.sub(r"\s+", " ", out).strip()


# ── 파싱·검증 ────────────────────────────────────────────────
_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name,
                  ast.Constant, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div,
                  ast.Pow, ast.USub, ast.UAdd, ast.Tuple)


@lru_cache(maxsize=1)
def _rule_functions() -> set[str]:
    """rules/derive_functions.yaml에 등록된 함수 이름 — 규칙 DB가 원본이다."""
    import yaml

    path = Path(__file__).resolve().parents[3] / "rules" / "derive_functions.yaml"
    names: set[str] = set()
    for item in yaml.safe_load(path.read_text()):
        for f in item["functions"]:
            m = re.match(r"[a-zA-Z_]\w*", f.strip(" `"))
            if m:
                names.add(m.group())
    return names


def parse(src: str, columns: list[str] | None = None) -> Parsed:
    """수식을 읽고 검증한다. 허용 함수·컬럼만 통과."""
    from statop.messages import msg

    plain = latex_to_plain(src) if "\\" in src or "$" in src else src.strip()
    if not plain:
        raise FormulaError(msg("formula_empty"))
    plain = plain.replace("−", "-").replace("×", "*").replace("÷", "/")

    try:
        tree = ast.parse(plain, mode="eval")
    except SyntaxError as e:
        raise FormulaError(msg("formula_syntax", expr=plain, err=str(e.msg)))

    used_cols, used_funcs, scopes = [], [], set()
    uses_eps = False
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise FormulaError(msg("formula_node_not_allowed",
                                   node=type(node).__name__, expr=plain))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FormulaError(msg("formula_call_not_allowed", expr=plain))
            fname = node.func.id
            if fname == "setsum":
                fname, scope = "sum", "set"
            elif fname in ROW_FUNCS:
                scope = "row"
            elif fname in COLUMN_FUNCS:
                scope = "column_scalar"
            elif fname in SET_FUNCS:
                scope = "set"
            elif fname in PAIR_FUNCS:
                scope = "pair"
            else:
                raise FormulaError(msg("formula_func_not_allowed", func=fname,
                                       allowed=", ".join(sorted(ALL_FUNCS))))
            used_funcs.append(fname)
            scopes.add(scope)
        elif isinstance(node, ast.Name):
            if node.id == EPS_NAME:
                uses_eps = True
            elif node.id in CONSTANTS:
                pass
            elif node.id in ALL_FUNCS or node.id == "setsum":
                pass
            else:
                used_cols.append(node.id)

    if columns is not None:
        unknown = [c for c in dict.fromkeys(used_cols) if c not in columns]
        if unknown:
            raise FormulaError(msg("formula_unknown_column", cols=", ".join(unknown)))

    return Parsed(expr=plain, columns=list(dict.fromkeys(used_cols)),
                  functions=list(dict.fromkeys(used_funcs)), uses_eps=uses_eps,
                  scopes=scopes, tree=tree)


def slots(parsed: Parsed) -> list[str]:
    """재사용을 위한 입력 슬롯 이름 — 저장된 수식을 다른 컬럼에 적용할 때 쓴다 (M1-2)."""
    return parsed.columns


# 토큰 역할 — 화면에서 색을 나눈다 (F-04). 컬럼 스칼라는 행마다 값이 달라지지 않으므로
# 행 단위 함수와 섞어 읽으면 "왜 상수가 나오지" 하는 오해가 생긴다.
ROLE_COLUMN = "column"
ROLE_ROW_FUNC = "row_func"
ROLE_SCALAR_FUNC = "column_scalar_func"
ROLE_SET_FUNC = "set_func"
ROLE_PAIR_FUNC = "pair_func"
ROLE_EPS = "eps"
ROLE_CONST = "const"
ROLE_NUMBER = "number"
ROLE_PUNCT = "punct"

_FUNC_ROLE = [(ROW_FUNCS, ROLE_ROW_FUNC), (COLUMN_FUNCS, ROLE_SCALAR_FUNC),
              (SET_FUNCS, ROLE_SET_FUNC), (PAIR_FUNCS, ROLE_PAIR_FUNC)]


def tokens(parsed: Parsed) -> list[dict]:
    """정규화된 수식을 역할이 붙은 토큰으로 쪼갠다 (F-04 색 구분).

    파싱된 식만 받는다 — 검증을 통과하지 않은 문자열에 색을 입히면
    화면과 계산이 어긋난다.
    """
    import io
    import tokenize as tk

    out: list[dict] = []
    src = parsed.expr
    prev_end = 0
    for t in tk.generate_tokens(io.StringIO(src).readline):
        if t.type in (tk.ENDMARKER, tk.NEWLINE, tk.NL, tk.INDENT, tk.DEDENT):
            continue
        start = t.start[1]
        if start > prev_end:                       # 원문 공백을 그대로 보존
            out.append({"text": src[prev_end:start], "role": ROLE_PUNCT})
        role = ROLE_PUNCT
        if t.type == tk.NUMBER:
            role = ROLE_NUMBER
        elif t.type == tk.NAME:
            if t.string == EPS_NAME:
                role = ROLE_EPS
            elif t.string in CONSTANTS:
                role = ROLE_CONST
            elif t.string == "setsum":
                role = ROLE_SET_FUNC
            else:
                role = ROLE_COLUMN
                for names, r in _FUNC_ROLE:
                    if t.string in names:
                        role = r
                        break
        out.append({"text": t.string, "role": role})
        prev_end = t.end[1]
    return out


# ── AST → LaTeX ──────────────────────────────────────────────
# 입력 문자열이 아니라 **계산되는 트리**에서 만든다 — 그래야 화면에 보이는 식과
# 실제로 계산되는 식이 어긋날 수 없다 (요구사항검수 기준: 렌더와 계산식 불일치 0).
_LATEX_FUNC = {"log2": r"\log_2", "log10": r"\log_{10}", "log": r"\log",
               "ln": r"\ln", "exp": r"\exp", "sqrt": None, "abs": None,
               "arcsinh": r"\operatorname{arcsinh}",
               "logit": r"\operatorname{logit}", "clr": r"\operatorname{clr}",
               "ilr": r"\operatorname{ilr}", "alr": r"\operatorname{alr}",
               "sum": r"\sum", "mean": r"\operatorname{mean}",
               "sd": r"\operatorname{sd}", "median": r"\operatorname{median}",
               "min": r"\min", "max": r"\max",
               "zscore": r"\operatorname{zscore}", "rank": r"\operatorname{rank}",
               "rank\\_row": r"\operatorname{rank_{row}}"}


def to_latex(parsed: Parsed) -> str:
    """파싱된 수식을 LaTeX로. 검증을 통과한 트리만 받는다."""
    import ast as _ast

    def esc(name: str) -> str:
        return r"\texttt{" + name.replace("_", r"\_") + "}"

    def walk(node, parent_prec: int = 0) -> str:
        if isinstance(node, _ast.Expression):
            return walk(node.body)
        if isinstance(node, _ast.Constant):
            return f"{node.value:g}" if isinstance(node.value, float) else str(node.value)
        if isinstance(node, _ast.Name):
            return r"\varepsilon" if node.id == EPS_NAME else esc(node.id)
        if isinstance(node, _ast.UnaryOp):
            return ("-" if isinstance(node.op, _ast.USub) else "+") + walk(node.operand, 3)
        if isinstance(node, _ast.BinOp):
            op = type(node.op)
            if op is _ast.Div:      # 분수는 괄호가 필요 없다
                return r"\frac{" + walk(node.left) + "}{" + walk(node.right) + "}"
            if op is _ast.Pow:
                return "{" + walk(node.left, 4) + "}^{" + walk(node.right) + "}"
            sym, prec = {_ast.Add: ("+", 1), _ast.Sub: ("-", 1),
                         _ast.Mult: (r"\cdot", 2)}[op]
            body = f"{walk(node.left, prec)} {sym} {walk(node.right, prec + 1)}"
            return rf"\left({body}\right)" if prec < parent_prec else body
        if isinstance(node, _ast.Call):
            name = node.func.id
            args = [walk(a) for a in node.args]
            if name == "sqrt":
                return r"\sqrt{" + args[0] + "}"
            if name == "abs":
                return r"\lvert " + args[0] + r" \rvert"
            if name == "pow":
                return "{" + args[0] + "}^{" + args[1] + "}"
            if name == "setsum":
                return r"\sum_{j \in set} " + args[0]
            if name == "sum":
                return r"\sum_i " + args[0]
            head = _LATEX_FUNC.get(name, r"\operatorname{" + name + "}")
            return head + r"\left(" + ", ".join(args) + r"\right)"
        raise FormulaError(node.__class__.__name__)

    return walk(parsed.tree)
