"""파생 컬럼 공용 로직 — CLI·REST·셸이 같은 판정을 쓴다.

판정(eps 허용 범위·결과 의미 타입·3색)은 여기 한 곳에만 있다. 껍데기는 문장을 고르고
색을 입힐 뿐, 무엇이 허용되는지는 결정하지 않는다.
"""

from dataclasses import dataclass, field

from statop.derive.parser import Parsed


@dataclass
class Prepared:
    """미리보기에 필요한 것을 한 번에 — 껍데기가 다시 계산할 일이 없게."""

    parsed: Parsed
    tokens: list[dict] = field(default_factory=list)
    eps_used: float | None = None
    eps_advice: object | None = None
    eps_auto: bool = False           # 사용자가 안 줘서 추천값으로 미리 계산했는가
    preview: dict = field(default_factory=dict)
    result_type: str = "continuous"
    alternative: str = ""            # eps 말고 먼저 볼 것이 있으면 (S-R04)


HELPERS = "statop_helpers"          # 파생 계산에만 쓰고 화면에는 안 나가는 컬럼
DERIVE_FAILED = "statop_derive_failed"


def _needed_by_derived(doc, source_id: str, have: list) -> list:
    """파생 수식이 쓰는 원본 컬럼 중 **선택에서 빠진 것**.

    선택에서 뺐다고 파생 컬럼이 사라지면 안 된다 — 기록에는 남아 있는데 값만 없는
    상태가 되고, 그러면 화면이 "있는데 비어 있는" 컬럼을 보여 준다 (실제로 났다).
    """
    import re

    from statop.session.core import replay

    need = set()
    for d in replay(doc)["derived"]:
        if d.get("source") not in (None, source_id):
            continue
        # 수식의 식별자를 전부 후보로 본다 — 파서는 컬럼 목록을 요구하므로 여기서는 못 쓴다
        need |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", d.get("expr", "")))
    return [c for c in have if c in need]


def session_frame(session_file: str, sample_n: int = 10_000):
    """세션의 메인 파일에서 (선택 컬럼이 있으면 그것만) 샘플을 읽는다.

    **파생 수식이 쓰는 원본은 선택에서 빠졌어도 함께 읽는다.** 그러지 않으면 원본을
    제외한 순간 파생 컬럼이 계산 불가가 된다. 그 컬럼들은 `df.attrs[HELPERS]` 에
    적어 두고 `apply_ops` 가 파생을 다 붙인 뒤 떨어낸다 — 화면에는 안 나간다.
    """
    from statop.io.sample import sample_rows
    from statop.messages import msg
    from statop.session.core import load_session, main_source, replay

    doc = load_session(session_file)
    src = main_source(doc)
    if src is None:
        raise ValueError(msg("select_err_empty"))
    df = sample_rows(src["path"], n=sample_n)
    sel = replay(doc)["selected"].get(src["id"], [])
    helper_df = None
    if sel:
        keep = [c for c in sel if c in df.columns]
        helpers = [c for c in _needed_by_derived(doc, src["id"], list(df.columns))
                   if c not in keep]
        # **돌려주는 프레임에는 넣지 않는다.** 넣으면 apply_ops 를 안 부르는 화면에서
        # "뺐는데 왜 보이나"가 된다 (실제로 groups 화면에서 그렇게 됐다)
        helper_df = df[helpers].copy() if helpers else None
        df = df[keep]
    df.attrs[HELPERS] = helper_df
    return doc, src, df


def with_derived(df, doc, source_id: str):
    """세션에 기록된 파생 컬럼을 재계산해 붙인다 — 기록만으로 재현이 원칙이다.

    파생 컬럼은 파일에 없으므로, 이걸 안 붙이면 타입 추론·분포·2차 수식에서
    파생 컬럼이 통째로 빠진다.
    """
    from statop.derive.evaluate import evaluate
    from statop.derive.parser import parse
    from statop.session.core import replay

    for d in replay(doc)["derived"]:
        if d.get("source") != source_id or d["name"] in df.columns:
            continue
        try:
            p = parse(d["expr"], list(df.columns))
        except Exception:
            continue      # 원본이 바뀌어 컬럼이 사라진 경우 — 그 파생만 빼고 진행
        df = df.assign(**{d["name"]: evaluate(p, df, eps=d.get("eps"),
                                              composition=d.get("composition"))})
    return df


def with_missing(df, doc, source_id: str):
    """세션에 기록된 결측 제거·대치를 순서대로 다시 적용한다.

    이걸 안 하면 CLI/웹에서 대치해 둔 것이 분석에서는 없던 일이 된다 — 같은 세션인데
    화면마다 결측 수가 달라지는 것이 가장 나쁘다.
    """
    from statop.missing import drop_na, impute
    from statop.session.core import replay

    for m in sorted(replay(doc)["missing_ops"], key=lambda o: o["seq"]):
        if m.get("source") not in (None, source_id):
            continue
        cols = [c for c in (m.get("cols") or []) if c in df.columns]
        if m["op"] == "missing_drop":
            df = drop_na(df, cols or None, how=m.get("how", "row"))
        elif m["op"] == "impute" and cols:
            df, _ = impute(df, m["method"], cols, group_by=m.get("group_by"),
                           seed=m.get("seed") or 0)
    return df


def with_excluded(df, doc, source_id: str):
    """제외한 개별 샘플을 뺀다 — 그림에서 찍어 뺀 점이 검정에서도 빠져야 한다.

    원본 파일은 건드리지 않는다. 무엇을 왜 뺐는지는 세션에 남아 출력에 따라다닌다.
    """
    from statop.session.core import replay

    for e in replay(doc)["excluded"]:
        if e.get("source") not in (None, source_id):
            continue
        col = e["key_column"]
        if col in df.columns:
            df = df[df[col].astype(str) != str(e["key"])]
    return df


def apply_ops(df, doc, source_id: str, use_exclusions: bool = True):
    """세션에 기록된 조작을 **기록한 순서 그대로** 다시 입힌다.

    종류별로 몰아서 적용하면 안 된다 — 대치 뒤에 만든 파생 컬럼이 대치 전 값으로
    계산되고, 제외 전후에 따라 중앙값도 달라진다. 사용자가 한 순서가 곧 의미다.

    분석·가정검사·분포·리포트·화면이 **모두 이 한 줄**을 쓴다. 한 곳이라도 빠지면
    같은 세션인데 화면마다 행 수가 달라진다.

    use_exclusions=False 는 "제외 전" 값을 구할 때만 쓴다 ( 전/후 병기).
    """
    from statop.missing import drop_na, impute
    from statop.session.core import replay

    # 파생 수식이 쓰는 원본이 선택에서 빠졌어도 계산은 되어야 한다 — session_frame 이
    # 따로 챙겨 둔 컬럼을 여기서만 잠깐 붙였다가 끝에 떼어 낸다
    import pandas as pd

    helper_df = df.attrs.get(HELPERS)
    helper_cols: list = []
    if helper_df is not None and len(helper_df.columns):
        helper_cols = [c for c in helper_df.columns if c not in df.columns]
        if helper_cols:
            df = pd.concat([df, helper_df[helper_cols]], axis=1)

    st = replay(doc)
    steps: list[tuple[int, str, dict]] = []
    steps += [(d["seq"], "derive", d) for d in st["derived"]
              if d.get("source") in (None, source_id)]
    steps += [(m["seq"], m["op"], m) for m in st["missing_ops"]
              if m.get("source") in (None, source_id)]
    if use_exclusions:
        steps += [(e["seq"], "exclude", e) for e in st["excluded"]
                  if e.get("source") in (None, source_id)]

    for _, kind, op in sorted(steps, key=lambda x: x[0]):
        if kind == "derive":
            df = _one_derived(df, op)
        elif kind == "missing_drop":
            cols = [c for c in (op.get("cols") or []) if c in df.columns]
            df = drop_na(df, cols or None, how=op.get("how", "row"))
        elif kind == "impute":
            cols = [c for c in (op.get("cols") or []) if c in df.columns]
            if cols:
                df, _ = impute(df, op["method"], cols, group_by=op.get("group_by"),
                               seed=op.get("seed") or 0)
        elif kind == "exclude" and op["key_column"] in df.columns:
            df = df[df[op["key_column"]].astype(str) != str(op["key"])]

    # 파생을 다 붙였으니 도우미 컬럼은 떼어 낸다
    failed = df.attrs.get(DERIVE_FAILED) or []
    drop = [c for c in helper_cols if c in df.columns]
    if drop:
        df = df.drop(columns=drop)
    df.attrs[HELPERS] = None
    df.attrs[DERIVE_FAILED] = failed
    return df


def _one_derived(df, d: dict):
    """파생 컬럼 하나를 그 시점의 프레임에 붙인다."""
    from statop.derive.evaluate import evaluate
    from statop.derive.parser import parse

    if d["name"] in df.columns:
        return df
    try:
        p = parse(d["expr"], list(df.columns))
    except Exception as e:
        # 원본 파일이 바뀌어 수식이 쓰는 컬럼이 아예 없어진 경우다. 조용히 빼면
        # "있는데 값이 없는 컬럼"이 되므로, 왜 못 만들었는지를 프레임에 적어 둔다
        failed = list(df.attrs.get(DERIVE_FAILED) or [])
        failed.append({"name": d["name"], "expr": d["expr"], "why": str(e)})
        df.attrs[DERIVE_FAILED] = failed
        return df
    return df.assign(**{d["name"]: evaluate(p, df, eps=d.get("eps"),
                                            composition=d.get("composition"))})


def result_type(parsed: Parsed) -> str:
    """수식에서 결과 의미 타입을 유도한다 (rules/derive_functions.yaml의 result_type)."""
    fns = set(parsed.functions)
    if fns & {"log", "ln", "log2", "log10", "logit", "alr", "arcsinh"}:
        return "log-scale"
    if "clr" in fns or "ilr" in fns:
        return "clr"
    if "zscore" in fns:
        return "z-score"
    if "rank" in fns:
        return "ordinal code"
    # 구간화한 값은 더 이상 연속이 아니다 — 순서 있는 구간이다.
    # 타입이 바뀌어야 뒤따르는 검정 후보와 적합성 판정이 맞는다
    if fns & {"floor_to", "round_to", "ceil_to", "bin"}:
        return "ordinal code"
    return "continuous"


def needs_eps(parsed: Parsed) -> bool:
    """eps 판단이 필요한 수식인가 — log 계열은 0을 만나면 -inf가 되므로 함께 본다."""
    return parsed.uses_eps or bool(
        set(parsed.functions) & {"log", "ln", "log2", "log10"})


def prepare(df, expr: str, eps: float | None = None,
            composition: list[str] | None = None) -> Prepared:
    """수식을 파싱·검증하고 eps 추천과 미리보기까지 만든다.

    추천값을 넘는 eps는 여기서 거부한다 — 커밋 직전이 아니라 미리보기 단계에서 막아야
    큰 eps로 계산된 그림을 보고 판단하는 일이 없다.
    """
    from statop.derive.eps import advise, validate
    from statop.derive.evaluate import preview
    from statop.derive.parser import parse, tokens

    parsed = parse(expr, list(df.columns))
    out = Prepared(parsed=parsed, tokens=tokens(parsed), eps_used=eps,
                   result_type=result_type(parsed))

    if needs_eps(parsed):
        target = df[parsed.columns[0]] if parsed.columns else df.iloc[:, 0]
        adv = advise(target)
        out.eps_advice = adv
        # 0 이 있으면 **eps 를 권하기 전에** 0 에서 정의되는 변환을 먼저 보인다 (S-R04).
        # eps 는 더한 값에 따라 결과가 달라지고, 검출 한계 아래 값이 상수로 눌린다
        import numpy as _np

        if (_np.asarray(target, dtype="float64") == 0).any():
            from statop.messages import msg as _msg

            col = parsed.columns[0] if parsed.columns else "x"
            out.alternative = _msg("derive_prefer_arcsinh", col=col)
        if eps is None and parsed.uses_eps and adv.recommended is not None:
            # 값을 보고 정해야 하므로 추천값으로 미리 계산해 보여준다 (커밋하려면 명시 필요)
            out.eps_used = adv.recommended
            out.eps_auto = True
        if eps is not None:
            validate(eps, adv)

    out.preview = preview(parsed, df, eps=out.eps_used, composition=composition)
    return out


def commit(doc, source_id: str, df, prep: Prepared, name: str, eps: float | None,
           composition: list[str] | None = None, as_type: str | None = None,
           from_formula: str | None = None) -> dict:
    """파생 컬럼을 세션에 기록한다. 수식과 eps가 함께 남아 재생 가능해야 한다."""
    from statop.messages import msg
    from statop.session.core import append_op, save_session

    if prep.parsed.uses_eps and eps is None:
        # 추천값으로 미리보기는 되지만 커밋은 명시해야 한다 — 기록에 남아야 하므로
        raise ValueError(msg("eps_explicit_required"))
    if name in df.columns:
        raise ValueError(msg("derive_name_exists", name=name))

    extra = {"from_formula": from_formula} if from_formula else {}
    entry = append_op(doc, "derive", source=source_id, name=name, expr=prep.parsed.expr,
                      eps=eps, composition=composition,
                      result_type=as_type or prep.result_type, **extra)
    save_session(doc)
    return entry
