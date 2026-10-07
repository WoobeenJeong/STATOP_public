"""M1-2 파생 컬럼 — 화이트리스트 수식·eps 규칙·미리보기."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app
from statop.derive.eps import advise, validate
from statop.derive.evaluate import evaluate, preview
from statop.derive.parser import ALL_FUNCS, FormulaError, latex_to_plain, parse


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("h")))


@pytest.fixture()
def df():
    rng = np.random.default_rng(0)
    n = 500
    comp = rng.dirichlet([2, 3, 5], n)
    d = pd.DataFrame({"frac": comp[:, 0], "b": comp[:, 1], "c": comp[:, 2],
                      "size": rng.poisson(5, n).astype(float),
                      "p": rng.beta(2, 2, n)})
    d.loc[:20, "size"] = 0.0          # log(0) 유발
    return d


# ── 파서 ────────────────────────────────────────────────────
def test_latex_and_plain_give_same_result(df):
    latex = r"\log_2\left(\texttt{frac} + \varepsilon\right)"
    plain = "log2(frac + eps)"
    a, b = parse(latex, list(df.columns)), parse(plain, list(df.columns))
    assert a.columns == b.columns and a.functions == b.functions
    adv = advise(df["frac"])
    va = evaluate(a, df, eps=adv.recommended)
    vb = evaluate(b, df, eps=adv.recommended)
    assert np.allclose(va, vb)        # 렌더와 계산이 어긋나면 안 된다


def test_latex_frac_and_abs():
    assert latex_to_plain(r"\frac{\texttt{a}}{\texttt{b}}") == "((a)/(b))"
    assert "abs(" in latex_to_plain(r"\lvert \texttt{a} \rvert")


def test_unsupported_latex_fails_loudly():
    with pytest.raises(FormulaError, match="LaTeX"):
        parse(r"\int_0^1 \texttt{a}\,dx")


@pytest.mark.parametrize("bad", ["__import__('os')", "a.to_csv()", "eval(a)", "foo(a)",
                                 "a if b else 1", "lambda x: x", "[a for a in b]", ""])
def test_dangerous_expressions_blocked(bad, df):
    with pytest.raises(FormulaError):
        parse(bad, list(df.columns))


def test_unknown_column_rejected(df):
    with pytest.raises(FormulaError, match="없는 컬럼"):
        parse("zzz + 1", list(df.columns))


def test_scopes_distinguish_row_and_column(df):
    p = parse("frac / sum(frac)", list(df.columns))
    assert p.scopes == {"column_scalar"}          # sum은 컬럼 스칼라
    assert parse("log2(frac)", list(df.columns)).scopes == {"row"}
    assert parse("clr(frac)", list(df.columns)).scopes == {"set"}


def test_allowed_functions_match_rule_db():
    """허용 함수는 규칙 DB(F-01~14)에서 온다."""
    assert {"log", "log2", "logit", "clr", "alr", "zscore", "rank"} <= ALL_FUNCS
    assert "eval" not in ALL_FUNCS and "exec" not in ALL_FUNCS


# ── eps (F-01, 10.1) ────────────────────────────────────────
def test_eps_recommendation_follows_rule():
    """추천 = 10^(floor(log10(min_positive)) - 2)"""
    a = advise(np.array([0.0, 3.7e-6, 1.0]))
    assert a.needed is True and a.min_positive == pytest.approx(3.7e-6)
    assert a.recommended == pytest.approx(1e-8)
    assert a.candidates[:2] == [pytest.approx(1e-8), pytest.approx(1e-9)]


def test_eps_above_recommendation_rejected():
    a = advise(np.array([0.0, 3.7e-6, 1.0]))
    validate(1e-8, a)                  # 추천값은 통과
    validate(1e-12, a)                 # 더 작은 값도 통과
    with pytest.raises(ValueError, match="추천값"):
        validate(1e-6, a)              # 초과는 차단 — 커밋되는 경로가 없어야 한다


def test_eps_not_needed_without_zeros():
    a = advise(np.array([0.5, 1.0, 2.0]))
    assert a.needed is False and a.n_zeros == 0


# ── 계산·미리보기 ────────────────────────────────────────────
def test_log_zero_produces_inf_and_is_counted(df):
    n_zero = int((df["size"] == 0).sum())     # 주입한 0 + 우연히 생긴 0
    pv = preview(parse("log(size)", list(df.columns)), df)
    assert pv["n_inf"] == n_zero       # log(0)이 숫자로 드러난다
    assert pv["n_finite"] == len(df) - n_zero


def test_ratio_normalization_sums_to_one(df):
    v = evaluate(parse("frac / sum(frac)", list(df.columns)), df)
    assert float(v.sum()) == pytest.approx(1.0)


def test_clr_centers_by_row_geometric_mean(df):
    v = evaluate(parse("clr(frac)", list(df.columns)), df, composition=["frac", "b", "c"])
    logs = np.log(df[["frac", "b", "c"]])
    expected = logs["frac"] - logs.mean(axis=1)
    assert np.allclose(v, expected)


def test_clr_without_composition_fails(df):
    with pytest.raises(Exception, match="조성"):
        evaluate(parse("clr(frac)", list(df.columns)), df)


def test_logit_matches_definition(df):
    v = evaluate(parse("logit(p)", list(df.columns)), df)
    assert np.allclose(v, np.log(df["p"] / (1 - df["p"])), atol=1e-9)


# ── CLI ─────────────────────────────────────────────────────
def _session(runner, path) -> str:
    from statop.store import tmp_dir

    runner.invoke(app, ["session", "new", "--data", str(path)])
    return str(next(tmp_dir().glob("session_*.json")))


def test_cli_preview_then_commit(tmp_path, df):
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    runner = CliRunner()
    sess = _session(runner, p)
    runner.invoke(app, ["select", str(p), "--cols", "frac,size,p", "--session", sess])

    pre = runner.invoke(app, ["derive", "--session", sess, "--expr", "log2(frac + eps)"])
    assert pre.exit_code == 0
    assert "추천값" in pre.output and "미리 계산" in pre.output
    assert not any(o["op"] == "derive" for o in json.loads(Path(sess).read_text())["ops"])

    # 커밋하려면 eps를 명시해야 한다 (기록에 남아야 하므로)
    no_eps = runner.invoke(app, ["derive", "--session", sess, "--expr", "log2(frac + eps)",
                                 "--name", "lf"])
    assert no_eps.exit_code != 0

    ok = runner.invoke(app, ["derive", "--session", sess, "--expr", "log2(frac + eps)",
                             "--eps", "1e-8", "--name", "lf"])
    assert ok.exit_code == 0 and "log-scale" in ok.output
    op = next(o for o in json.loads(Path(sess).read_text())["ops"] if o["op"] == "derive")
    assert op["name"] == "lf" and op["eps"] == 1e-8 and op["result_type"] == "log-scale"


def test_cli_blocks_large_eps(tmp_path, df):
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    runner = CliRunner()
    sess = _session(runner, p)
    runner.invoke(app, ["select", str(p), "--cols", "frac", "--session", sess])
    r = runner.invoke(app, ["derive", "--session", sess, "--expr", "log2(frac + eps)",
                            "--eps", "0.01", "--name", "x"])
    assert r.exit_code != 0 and "왜곡" in r.output


def test_cli_warns_about_inf(tmp_path, df):
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    runner = CliRunner()
    sess = _session(runner, p)
    runner.invoke(app, ["select", str(p), "--cols", "size", "--session", sess])
    r = runner.invoke(app, ["derive", "--session", sess, "--expr", "log(size)"])
    assert "±inf" in r.output and "log(0)" in r.output


# ── 커스텀 수식 라이브러리 (M1-2, 요구사항.6b ②) ────────────────
def test_formula_save_load_remove(tmp_path):
    from statop.derive.library import Formula, load, remove, save

    lib = tmp_path / "formulas.json"
    f = Formula(name="Lorentzian_Entropy", expr="log2(frac + eps)", slots=["frac"],
                result_type="log-scale")
    save(f, lib)
    items = load(lib)
    assert "Lorentzian_Entropy" in items and items["Lorentzian_Entropy"].created

    with pytest.raises(FileExistsError, match="이미 있습니다"):
        save(f, lib)
    save(f, lib, overwrite=True)          # 명시하면 덮어쓰기

    remove("Lorentzian_Entropy", lib)
    assert load(lib) == {}
    with pytest.raises(KeyError):
        remove("nope", lib)


def test_bind_replaces_slots_safely():
    """짧은 슬롯 이름이 긴 이름의 일부일 때도 깨지지 않아야 한다."""
    from statop.derive.library import Formula, bind

    f = Formula(name="f", expr="a + ab", slots=["a", "ab"])
    assert bind(f, {"a": "X", "ab": "Y"}) == "X + Y"
    with pytest.raises(KeyError, match="슬롯"):
        bind(f, {"a": "X"})


def test_applicability_three_colors():
    from statop.derive.library import Formula, applicability

    f = Formula(name="f", expr="frac * 2", slots=["frac"])
    # 타입 미확정 → 노랑
    assert applicability(f, {}, {"frac": "c"})["verdict"] == "yellow"
    # proportion → S-R01/02가 걸려 빨강
    red = applicability(f, {"c": "proportion"}, {"frac": "c"})
    assert red["verdict"] == "red" and {r["id"] for r in red["risks"]} == {"S-R01", "S-R02"}
    # 등록 규칙 없는 타입 → 초록
    assert applicability(f, {"c": "continuous"}, {"frac": "c"})["verdict"] == "green"


def test_applicability_counts_mitigation():
    """권고 변환을 이미 적용한 수식은 그 규칙을 해소로 본다 — 고쳤는데 빨간불이면 안 된다."""
    from statop.derive.library import Formula, applicability

    f = Formula(name="f", expr="log2(frac + eps)", slots=["frac"])
    r = applicability(f, {"c": "proportion"}, {"frac": "c"}, functions={"log2"})
    mitigated = {x["id"] for x in r["risks"] if x["mitigated"]}
    assert "S-R02" in mitigated            # log/logit 변환을 권하는 규칙
    assert r["n_mitigated"] == 1

    clr = applicability(f, {"c": "proportion"}, {"frac": "c"}, functions={"clr"})
    assert {x["id"] for x in clr["risks"] if x["mitigated"]} == {"S-R01", "S-R02"}
    assert clr["verdict"] == "yellow"       # 전부 해소되면 빨강에서 내려온다


def test_cli_formula_roundtrip(tmp_path, df):
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)
    runner = CliRunner()
    sess = _session(runner, p)
    runner.invoke(app, ["select", str(p), "--cols", "frac,b,p", "--session", sess])

    save = runner.invoke(app, ["formula", "save", "--name", "MyLog",
                               "--expr", "log2(frac + eps)", "--session", sess,
                               "--result-type", "log-scale"])
    assert save.exit_code == 0 and "MyLog" in save.output

    lst = runner.invoke(app, ["formula", "list"])
    assert "MyLog" in lst.output and "log-scale" in lst.output

    # 같은 이름 재저장은 거부
    assert runner.invoke(app, ["formula", "save", "--name", "MyLog",
                               "--expr", "log2(b + eps)"]).exit_code == 1

    # 다른 컬럼에 재사용 → 새 컬럼
    ap = runner.invoke(app, ["formula", "apply", "--name", "MyLog", "--session", sess,
                             "--map", "frac=b", "--eps", "1e-8", "--out", "log_b"])
    assert ap.exit_code == 0
    assert "frac→b" in ap.output and "log_b" in ap.output
    op = next(o for o in json.loads(Path(sess).read_text())["ops"]
              if o["op"] == "derive" and o["name"] == "log_b")
    assert op["from_formula"] == "MyLog" and op["eps"] == 1e-8

    rm = runner.invoke(app, ["formula", "remove", "MyLog"])
    assert rm.exit_code == 0
    assert runner.invoke(app, ["formula", "apply", "--name", "MyLog", "--session", sess,
                               "--map", "frac=b"]).exit_code != 0


# ── 토큰 역할 · LaTeX 렌더  ──────────────────────
def test_tokens_roles_and_roundtrip():
    """토큰을 이어붙이면 원래 수식이 되어야 한다 — 아니면 화면과 계산이 어긋난다."""
    from statop.derive.parser import parse, tokens

    p = parse("log2(frac / mean(size) + eps) * 2", ["frac", "size"])
    ts = tokens(p)
    assert "".join(t["text"] for t in ts) == p.expr

    role = {t["text"]: t["role"] for t in ts if t["role"] != "punct"}
    assert role["log2"] == "row_func"
    assert role["mean"] == "column_scalar_func"    # 행마다 변하지 않는다
    assert role["frac"] == "column" and role["size"] == "column"
    assert role["eps"] == "eps" and role["2"] == "number"


@pytest.mark.parametrize("expr", [
    "log2(frac + eps)",
    "frac / mean(size)",
    "sqrt(abs(frac - mean(frac)))",
    "pow(frac, 2) + 1",
    "frac ** 2 / sd(frac)",
    "clr(frac)",
    "alr(frac, size)",
    "(frac + size) * (frac - size)",
    "log2(frac + abs(size / sum(size)) + eps)",
])
def test_latex_render_is_a_fixpoint(expr):
    """렌더한 LaTeX를 다시 읽어도 같은 식이어야 한다 (렌더-계산 불일치 0).

    사용자가 화면의 수식을 복사해 되붙여넣는 경로가 실제로 있다.
    """
    from statop.derive.parser import parse, to_latex

    cols = ["frac", "size"]
    first = to_latex(parse(expr, cols))
    again = to_latex(parse(first, cols))
    assert first == again


def test_latex_handles_nested_braces():
    """\\frac 안에 \\frac이 들어가도 열려야 한다 — 정규식으로는 중첩을 못 센다."""
    from statop.derive.parser import parse

    p = parse(r"\frac{\frac{\texttt{frac}}{\texttt{size}}}{2}", ["frac", "size"])
    assert p.expr == "((((frac)/(size)))/(2))"
    assert p.columns == ["frac", "size"]


def test_latex_underscore_escape_roundtrips():
    """\\texttt{a\\_b} 같은 이스케이프를 되돌리지 않으면 컬럼명을 못 찾는다."""
    from statop.derive.parser import parse

    p = parse(r"\log_2\left(\texttt{frac\_A} + \varepsilon\right)", ["frac_A"])
    assert p.expr == "log2(frac_A + eps)"


def test_service_prepare_blocks_large_eps(df):
    """미리보기 단계에서 막는다 — 큰 eps로 계산된 그림을 보고 판단하면 안 된다."""
    from statop.derive.service import prepare

    with pytest.raises(ValueError, match="추천값"):
        prepare(df, "log2(frac + eps)", eps=0.5)


# ── 구간화·자리수 (나이 23→20, 소수점 n째자리) ──────────────
@pytest.mark.parametrize(("expr", "want"), [
    ("floor_to(age, 10)", [20.0, 30.0, 10.0, 10.0, 60.0, 0.0]),
    ("round_to(age, 10)", [20.0, 40.0, 10.0, 20.0, 70.0, 0.0]),
    ("ceil_to(age, 10)", [30.0, 40.0, 10.0, 20.0, 70.0, 10.0]),
    ("bin(age, 0, 20, 40, 65)", [20.0, 20.0, 0.0, 0.0, 40.0, 0.0]),
])
def test_binning_collapses_to_the_interval_start(expr, want):
    df = pd.DataFrame({"age": [23.0, 39.0, 10.0, 19.0, 67.0, 5.0]})
    got = evaluate(parse(expr, ["age"]), df)
    assert list(got) == want


@pytest.mark.parametrize(("expr", "want"), [
    ("round(v, 3)", [0.123, 0.988]),
    ("trunc(v, 2)", [0.12, 0.98]),
    ("floor(v, 1)", [0.1, 0.9]),
    ("ceil(v, 1)", [0.2, 1.0]),
])
def test_decimal_places(expr, want):
    df = pd.DataFrame({"v": [0.12345, 0.98765]})
    got = evaluate(parse(expr, ["v"]), df)
    assert [round(x, 6) for x in got] == want


def test_binning_changes_the_semantic_type_to_ordinal():
    """구간화한 값은 연속이 아니다 — 타입이 안 바뀌면 뒤따르는 검정 후보가 틀린다."""
    from statop.derive.service import result_type

    assert result_type(parse("floor_to(age, 10)", ["age"])) == "ordinal code"
    assert result_type(parse("bin(age, 0, 40)", ["age"])) == "ordinal code"
    assert result_type(parse("round(age, 2)", ["age"])) == "continuous"


def test_preview_reports_how_much_was_collapsed():
    """되돌릴 수 없는 손실이다 — 커밋 전에 몇 개가 몇 개로 줄었는지 보여야 한다."""
    from statop.derive.evaluate import preview

    rng = np.random.default_rng(0)
    df = pd.DataFrame({"age": rng.integers(18, 80, 300).astype(float)})
    p = preview(parse("floor_to(age, 10)", ["age"]), df)
    assert p["distinct_before"] > 50 and p["distinct_after"] == 7
    assert p["levels"] == [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0]
    # 손실이 없는 식에는 이 항목이 붙지 않는다 — 늘 뜨는 경고는 읽히지 않는다
    assert "distinct_before" not in preview(parse("age * 2", ["age"]), df)


def test_binning_needs_a_step():
    df = pd.DataFrame({"age": [23.0, 39.0]})
    for expr in ("floor_to(age)", "bin(age, 10)"):
        with pytest.raises(Exception):
            evaluate(parse(expr, ["age"]), df)


def test_keypad_offers_binning_without_typing():
    """함수 이름을 외워 타자칠 필요가 없어야 한다 — 키패드에 있어야 한다."""
    from statop.derive.parser import ROW_FUNCS

    assert {"floor_to", "round_to", "ceil_to", "bin", "round", "trunc"} <= ROW_FUNCS


# ── 조작은 기록한 순서대로 재생된다 ────────────────────────
@pytest.fixture
def ordered_session(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(0)
    n = 100
    v = rng.normal(10, 2, n)
    v[:12] = np.nan
    p = tmp_path / "orig.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)],
                  "arm": rng.choice(["a", "b"], n), "v": v}).to_csv(p, index=False)

    def make(*ops):
        from statop.session.core import append_op, load_session, main_source, save_session
        from statop.shell.screen import Screen

        sc = Screen()
        sc.open_path(str(p))
        sc.toggle_page()
        sc.import_picked()
        doc = load_session(sc.session_file)
        src = main_source(doc)
        for kind in ops:
            if kind == "impute":
                append_op(doc, "impute", source=src["id"], method="median",
                          cols=["v"], group_by=None, seed=0, params={}, n_filled=12)
            elif kind == "derive":
                append_op(doc, "derive", source=src["id"], name="v2", expr="v * 2",
                          eps=None, composition=None, result_type="continuous")
            elif kind == "exclude":
                append_op(doc, "exclude_row", source=src["id"], key_column="sid",
                          key="S005", note="장비 오류")
        save_session(doc)
        return str(sc.session_file)

    return make


def _frame(session: str):
    from statop.derive.service import apply_ops, session_frame

    doc, src, df = session_frame(session, 10_000)
    return apply_ops(df, doc, src["id"])


def test_derive_after_impute_uses_the_filled_values(ordered_session):
    """대치 뒤에 만든 파생 컬럼이 대치 전 값으로 계산되면 사용자가 본 것과 달라진다."""
    f = _frame(ordered_session("impute", "derive"))
    assert f["v"].isna().sum() == 0
    assert np.allclose(f["v2"], f["v"] * 2)


def test_derive_before_impute_keeps_the_gaps(ordered_session):
    """순서가 곧 의미다 — 먼저 만든 파생은 대치 전 값을 담는다."""
    f = _frame(ordered_session("derive", "impute"))
    assert f["v"].isna().sum() == 0
    assert f["v2"].isna().sum() == 12


def test_exported_copy_matches_what_the_analysis_sees(ordered_session, tmp_path):
    """사본이 분석과 다르면 그 사본으로 낸 결과는 재현되지 않는다."""
    from statop.export import export_trimmed
    from statop.session.core import load_session, save_session

    session = ordered_session("impute", "exclude", "derive")
    seen = _frame(session)
    doc = load_session(session)
    out = tmp_path / "copy.csv"
    export_trimmed(doc, out_path=str(out))
    save_session(doc)

    copy = pd.read_csv(out)
    assert len(copy) == len(seen) == 99
    assert list(copy.columns) == ["sid", "arm", "v", "v2"]    # 중복 컬럼 없음
    assert copy["v"].isna().sum() == 0
    assert np.allclose(copy["v2"], copy["v"] * 2)
    assert "S005" not in set(copy["sid"])


def test_copy_save_can_become_the_new_main(ordered_session, tmp_path):
    """이후 작업이 사본 기준으로 이어져야 한다 — 원본은 그대로 남는다."""
    from statop.export import export_trimmed
    from statop.session.core import load_session, main_source, save_session

    session = ordered_session("impute")
    doc = load_session(session)
    origin = main_source(doc)["path"]
    out = tmp_path / "copy.csv"
    export_trimmed(doc, out_path=str(out), use_as_main=True)
    save_session(doc)

    doc = load_session(session)
    assert main_source(doc)["path"] == str(out.resolve())
    assert pd.read_csv(origin)["v"].isna().sum() == 12     # 원본 불변


def test_pending_changes_tracks_what_is_unsaved(ordered_session, tmp_path):
    """값을 바꾸고 저장하지 않으면 원본과 다른 데이터로 일하는 중이다."""
    from statop.export import export_trimmed, pending_changes
    from statop.session.core import load_session, save_session

    session = ordered_session("impute", "exclude")
    doc = load_session(session)
    before = pending_changes(doc)
    assert before["needs_export"] and before["counts"] == {"impute": 1,
                                                          "exclude_row": 1}
    export_trimmed(doc, out_path=str(tmp_path / "c.csv"))
    save_session(doc)
    assert pending_changes(load_session(session))["needs_export"] is False


# ── F-15 arcsinh (S-R04) ────────────────────────────────────
def test_arcsinh_survives_zeros_where_log_does_not():
    """0 이 섞인 자료에서 log 는 -inf 를 내고 arcsinh 는 내지 않는다.

    이것이 F-15 를 넣은 이유 전부다 — S-R04 가 권하는 변환을 도구가 못 하면
    규칙이 거짓말이 된다.
    """
    import numpy as np

    from statop.derive.service import prepare

    df = pd.DataFrame({"cnt": [0.0, 0.0, 1.0, 5.0, 100.0]})
    lg = prepare(df, "log(cnt)", eps=None)
    assert lg.preview["n_inf"] == 2

    asn = prepare(df, "arcsinh(cnt)", eps=None)
    assert asn.preview["n_inf"] == 0 and asn.preview["n_nan"] == 0
    assert asn.parsed.uses_eps is False          # eps 를 요구하지 않는다
    assert asn.result_type == "log-scale"
    # 큰 값에서는 log 처럼 거동한다 — arcsinh(x) → log(2x)
    assert np.isclose(np.arcsinh(100.0), np.log(200.0), atol=1e-4)


def test_zeros_point_to_arcsinh_before_eps():
    """eps 를 고르기 전에 0 에서 정의되는 변환을 먼저 보여 준다 (S-R04)."""
    from statop.derive.service import prepare

    zeros = prepare(pd.DataFrame({"cnt": [0.0, 1.0, 5.0]}), "log(cnt)", eps=None)
    assert "arcsinh(cnt)" in zeros.alternative

    # 0 이 없으면 eps 문제도 없다 — 굳이 대안을 들이밀지 않는다
    positive = prepare(pd.DataFrame({"cnt": [1.0, 5.0, 9.0]}), "log(cnt)", eps=None)
    assert positive.alternative == ""


# ── 원본을 선택에서 빼도 파생은 살아 있어야 한다 ──────────────
@pytest.fixture
def session_with_derived(tmp_path, monkeypatch):
    """파생 컬럼 하나를 만들어 둔 세션."""
    import numpy as np

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(1)
    n = 200
    path = tmp_path / "d.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)],
                  "cnt": rng.poisson(5, n),
                  "other": rng.normal(0, 1, n)}).to_csv(path, index=False)

    from statop.derive.service import commit, prepare, session_frame
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    doc, src, df = session_frame(str(sc.session_file))
    commit(doc, src["id"], df, prepare(df, "log(cnt + 1)"), "lg", eps=None)
    return str(sc.session_file), str(path)


def test_derived_survives_deselecting_its_source(session_with_derived):
    """원본을 빼도 파생 컬럼은 값이 있어야 한다.

    선택 컬럼만 읽으면 수식이 쓸 원본이 없어 계산이 조용히 실패하고, 기록에는 남아
    있는데 값만 없는 컬럼이 된다 (실제로 났다).
    """
    from statop.derive.service import apply_ops, session_frame
    from statop.session.core import append_op, load_session, main_source, save_session

    session, _ = session_with_derived
    doc = load_session(session)
    sid = main_source(doc)["id"]
    append_op(doc, "deselect", source=sid, cols=["cnt"])
    save_session(doc)

    doc, src, df = session_frame(session)
    df = apply_ops(df, doc, src["id"])
    assert "lg" in df.columns
    assert df["lg"].notna().all()          # 값이 비어 있으면 안 된다
    assert "cnt" not in df.columns         # 뺀 컬럼이 화면에 다시 나와도 안 된다


def test_helper_column_never_leaks_to_a_screen(session_with_derived):
    """파생 계산용으로 읽은 원본이 화면에 보이면 '뺐는데 왜 보이나'가 된다."""
    from statop.derive.service import session_frame
    from statop.session.core import append_op, load_session, main_source, save_session

    session, _ = session_with_derived
    doc = load_session(session)
    sid = main_source(doc)["id"]
    append_op(doc, "deselect", source=sid, cols=["cnt"])
    save_session(doc)

    # apply_ops 를 부르지 않는 화면(groups·compose 등)이 보는 프레임
    _, _, df = session_frame(session)
    assert "cnt" not in df.columns


def test_compose_does_not_crash_when_a_derived_column_exists(session_with_derived):
    """선택 목록에는 파생 이름도 들어 있다 — 안 붙이면 그 이름으로 찾다 죽는다."""
    from typer.testing import CliRunner

    from statop.cli import app

    session, _ = session_with_derived
    r = CliRunner().invoke(app, ["compose", "--session", session])
    assert r.exit_code == 0, r.output
    assert "구성 요약" in r.output      # rule-vocab


def test_pi_and_e_are_constants_not_columns():
    """상수를 손으로 적게 하면 자릿수에서 틀리고, 틀려도 식만 봐서는 안 보인다."""
    import numpy as np
    import pandas as pd

    from statop.derive.evaluate import evaluate
    from statop.derive.parser import parse, tokens

    df = pd.DataFrame({"width": [1.0, 2.0, 4.0]})
    v = np.asarray(evaluate(parse("0.5 * ln(2 * pi * e * pow(width, 2))", ["width"]), df))
    assert np.allclose(v, 0.5 * np.log(2 * np.pi * np.e * df.width ** 2))

    # 컬럼으로 세지 않는다 — 안 그러면 "pi 라는 컬럼이 없다"고 막는다
    p = parse("pi * width", ["width"])
    assert p.columns == ["width"]
    assert any(t["role"] == "const" for t in tokens(p)), "상수를 컬럼 색으로 칠하면 안 된다"

    # 같은 이름의 컬럼이 있으면 **컬럼이 이긴다** — 남의 자료 이름을 빼앗지 않는다
    d2 = pd.DataFrame({"e": [10.0, 20.0]})
    assert np.allclose(np.asarray(evaluate(parse("e * 2", ["e"]), d2)), [20.0, 40.0])


def test_round_is_on_the_keypad_path():
    """round 는 규칙표에 있었는데 자판에 없었다 — 있는 것을 쓰게 한다."""
    import numpy as np
    import pandas as pd

    from statop.derive.evaluate import evaluate
    from statop.derive.parser import ROW_FUNCS, parse

    assert "round" in ROW_FUNCS
    df = pd.DataFrame({"x": [1.234, 5.678]})
    assert np.allclose(np.asarray(evaluate(parse("round(x, 1)", ["x"]), df)), [1.2, 5.7])
