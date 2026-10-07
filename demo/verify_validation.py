"""검증 데이터가 **실제로 걸리는지** 확인한다 — `make_validation.py` 의 짝.

합성 데이터는 만들어 두면 낡는다. 규칙을 고치거나 범위를 줄이면 어제 걸리던 것이
오늘은 안 걸릴 수 있고, **안 걸리는데 걸린다고 믿는 것이 가장 나쁘다.** 그래서
"이 파일은 이것이 걸려야 한다"를 코드로 적어 두고 그대로 확인한다.

각 항목은 (파일, 무엇을 확인하나, 확인 함수) 세 쪽이다. 확인 함수는 걸린 근거를
문자열로 돌려주고, 못 걸리면 빈 문자열을 돌린다 — 그 근거가 화면에 그대로 나온다.

사용법:  python demo/verify_validation.py [데이터디렉터리]
"""

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"


def _session(path: str, home: Path):
    """세션 하나 — 열고 전체 컬럼을 가져온 상태."""
    os.environ["STATOP_HOME"] = str(home)
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    return str(sc.session_file)


def _confirm(session: str, column: str, kind: str) -> None:
    from statop.session.core import append_op, load_session, main_source, save_session

    doc = load_session(session)
    append_op(doc, "semantic_confirm", source=main_source(doc)["id"],
              column=column, type=kind)
    save_session(doc)


# ── 01 의미 타입 함정 ───────────────────────────────────────
def check_types(d: Path, home: Path) -> str:
    from statop.semantic import infer_columns

    df = pd.read_csv(d / "01_simulate_types.csv")
    traps = ["trap_binary_count", "grade_code", "log2_ratio"]
    got = {r.column: r for r in infer_columns(df, traps)}
    hit = [c for c in traps if got[c].conflicts]
    return f"함정 {len(hit)}/3 상충 표시 — {', '.join(hit)}" if len(hit) == 3 else ""


# ── 02 결측 ─────────────────────────────────────────────────
def check_missing(d: Path, home: Path) -> str:
    from statop.missing import report

    r = report(pd.read_csv(d / "02_simulate_missing.csv"))
    panel = [p for p in r.patterns
             if set(p["columns"]) == {"panel_x", "panel_y", "panel_z"}]
    by = {c.column: c for c in r.columns}
    if panel and by["zero_filled"].suspect_zero_filled and by["sparse_col"].high:
        return (f"동시결측 {panel[0]['n']}행 · 0채움의심 "
                f"(0 비율 {by['zero_filled'].zero_ratio:.0%}) · "
                f"sparse {by['sparse_col'].ratio:.0%}")
    return ""


# ── 03 조성 상관 (S-R01) ────────────────────────────────────
def check_correlation(d: Path, home: Path) -> str:
    from statop.compat import composition_groups, judge_pair

    df = pd.read_csv(d / "03_simulate_correlation.csv")
    types = {c: "proportion" for c in ("comp_a", "comp_b", "comp_c", "comp_d")}
    types["pct_scale"] = "percent"
    groups = composition_groups(df, list(types), types)
    r1 = judge_pair("correlate", "comp_a", "comp_b", types, df, groups)
    r2 = judge_pair("correlate", "comp_a", "pct_scale", types, df, groups)
    ids = {f.id for f in r1.findings} | {f.id for f in r2.findings}
    return f"적합성 {', '.join(sorted(ids))}" if {"S-R01", "S-R07"} <= ids else ""


# ── 04 가정 위배 세 분기 ────────────────────────────────────
def check_groupdiff(d: Path, home: Path) -> str:
    from scipy import stats

    df = pd.read_csv(d / "04_simulate_groupdiff.csv")
    norm_p = stats.shapiro(df["y_normal"].head(300)).pvalue
    skew = float(stats.skew(df["y_skewed"]))
    out_p = stats.shapiro(df["y_outlier"].head(300)).pvalue
    out_skew = abs(float(stats.skew(df["y_outlier"])))
    lev = stats.levene(df[df.arm == "case"]["y_hetero"],
                       df[df.arm == "control"]["y_hetero"]).pvalue
    tiny = int((df.arm3 == "C").sum())
    ok = (norm_p > 0.05 and skew > 2 and out_p < 0.01 and out_skew < 1
          and lev < 1e-10 and tiny < 10)
    return (f"정규 p={norm_p:.2f} · 왜도 {skew:+.1f} · outlier p={out_p:.0e}(왜도 "
            f"{out_skew:.1f}) · 등분산 p={lev:.0e} · C군 n={tiny}") if ok else ""


# ── 05 그룹 구조 ────────────────────────────────────────────
def check_repeated(d: Path, home: Path) -> str:
    from statop.groups import detect

    df = pd.read_csv(d / "05_simulate_repeated.csv")
    subj = [g for g in detect(df) if g.column == "subject_id"]
    if subj and abs(subj[0].mean_per_group - 3.0) < 0.01:
        return (f"subject_id {subj[0].n_levels}수준 · "
                f"그룹당 {subj[0].mean_per_group:.1f} · 식별자 아님"
                if not subj[0].is_identifier else "")
    return ""


# ── 06 생존 ─────────────────────────────────────────────────
def check_survival(d: Path, home: Path) -> str:
    df = pd.read_csv(d / "06_simulate_survival.csv")
    med = df.groupby("arm")["time_days"].median()
    n_ev = int(df.event.sum())
    if med["case"] < med["control"] and 0 < n_ev < len(df):
        return (f"사건 {n_ev}·절단 {len(df) - n_ev} · 중앙 case {med['case']:.0f}일 "
                f"< control {med['control']:.0f}일")
    return ""


# ── 07 심슨의 역설 ──────────────────────────────────────────
def check_simpson(d: Path, home: Path) -> str:
    df = pd.read_csv(d / "07_simulate_simpson.csv")
    whole = df.groupby("arm").outcome.mean()
    per = df.groupby(["stratum", "arm"]).outcome.mean().unstack()
    flipped = (whole["case"] < whole["control"]
               and (per["case"] > per["control"]).all())
    return (f"전체 case {whole['case']:.0%} < control {whole['control']:.0%} "
            f"인데 층별로는 전부 case 우세") if flipped else ""


# ── 08 가드레일 ─────────────────────────────────────────────
def check_guardrail(d: Path, home: Path) -> str:
    from statop.guard import checks as gc

    df = pd.read_csv(d / "08_simulate_guardrail.csv")
    types = {"prob_bad": "probability", "count_bad": "count", "pct_bad": "percent"}
    dom = [s for s in gc.out_of_range(df, types) if s.check == "impossible"]
    srm = gc.srm(df.arm.value_counts().to_dict(), {"control": 1, "case": 1})
    smd = gc.smd_imbalance(df, "arm", ["site"])
    if len(dom) == 3 and srm.hit and smd:
        return (f"GR-01 {len(dom)}컬럼 차단 · GR-02 p={srm.numbers['p']:.0e} · "
                f"GR-04 SMD {smd[0].numbers['smd']:.2f}")
    return ""


# ── 09 정렬 편향 ────────────────────────────────────────────
def check_sortbias(d: Path, home: Path) -> str:
    from statop.io.sample import sample_rows

    p = d / "09_simulate_sortbias.csv"
    head = pd.read_csv(p, nrows=133)
    blk = sample_rows(str(p), n=133)
    whole = pd.read_csv(p)
    f = lambda x: (x.arm == "case").mean()  # noqa: E731
    if f(head) == 0 and abs(f(blk) - f(whole)) < 0.05:
        return f"앞133행 {f(head):.0%} vs 앞/중/뒤 {f(blk):.0%} (전체 {f(whole):.0%})"
    return ""


# ── 10 라벨 팔레트 ──────────────────────────────────────────
def check_labels(d: Path, home: Path) -> str:
    from statop.labels import levels_of

    lv = {x.value: x for x in levels_of(str(d / "10_simulate_labels.csv"),
                                        "tumor_type")}
    same = lv["LUAD"].color == lv["lung adenocarcinoma"].color
    if same and lv["germ-cell"].ambiguous and lv["unknown_x"].category is None:
        return "TCGA=자유문자열 같은 색 · germ-cell 모호 · unknown 미매칭"
    return ""


# ── 11~15 모듈 B ────────────────────────────────────────────
def _model_session(d: Path, home: Path, **kw):
    from statop.modeling.spec import ModelSpec, record

    session = _session(d / "11_simulate_model_source.csv", home / "mb")
    base = dict(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                label_column="label", positive_class="1",
                group_column="patient_id", time_column="enroll_date",
                sets={"train": str(d / "12_simulate_model_train.csv"),
                      "test": str(d / "13_simulate_model_test.csv"),
                      "external": str(d / "14_simulate_model_external.csv")},
                seed=42)
    record(session, ModelSpec(**{**base, **kw}))
    from statop.modeling.spec import current

    return session, current(session)


def check_leak(d: Path, home: Path) -> str:
    from statop.modeling.leak import run_all

    session, spec = _model_session(d, home)
    bad = {f.id for f in run_all(spec) if f.verdict == "fail"}
    want = {"MB-C01", "MB-C02", "MB-C03", "MB-C05"}
    return f"Gate {', '.join(sorted(bad))}" if want <= bad else ""


def check_split(d: Path, home: Path) -> str:
    from statop.modeling.split_audit import run_all

    session, spec = _model_session(d, home)
    out = run_all(spec, str(d / "11_simulate_model_source.csv"), "sample_id",
                  {"train": 8, "test": 2})
    bad = [f for f in out if f.verdict == "fail"]
    shift = [f for f in bad if "kinds" in f.numbers]
    if {"MB-C06", "MB-C07"} <= {f.id for f in bad} and shift:
        return f"MB-C06 비율 · MB-C07 손실 + 분포 변형 {list(shift[0].numbers['kinds'])}"
    return ""


def check_balance(d: Path, home: Path) -> str:
    from statop.modeling.balance import run_all

    session, spec = _model_session(d, home)
    out = run_all(spec, ["site", "age_years"])
    bad = [f for f in out if f.verdict == "fail"]
    short = [f for f in bad if "site" in f.summary]
    ext = [f for f in bad if "columns" in f.numbers
           and "age_years" in f.numbers.get("columns", {})]
    if short and ext and any(f.id == "MB-C12" for f in bad):
        return "MB-C08 지름길(site) · MB-C12 가중 미기록 · 개발vs외부(age_years)"
    return ""


def check_prep(d: Path, home: Path) -> str:
    from statop.modeling.prep import run_all

    session, spec = _model_session(d, home, model_family="distance",
                                   reduction="PCA")
    out = {f.id: f for f in run_all(spec)}
    c10, c11 = out.get("MB-C10"), out.get("MB-C11")
    if (c10 and c10.verdict == "fail" and c11 and c11.verdict == "fail"
            and "age_years" in c11.summary):
        return (f"MB-C10 척도 {c10.numbers['max_ratio']:.0f}배 · "
                f"MB-C11 age_years 분산 "
                f"{c11.numbers['variance_share']['age_years']:.0%}")
    return ""


def check_eval(d: Path, home: Path) -> str:
    """15번 — 예측 확률. **타입 확정 전에는 열리지 않아야 한다.**"""
    from statop.modeling.evaluate import run_all
    from statop.modeling.spec import current

    session, spec = _model_session(
        d, home, score_column="pred_prob",
        sets={"train": str(d / "12_simulate_model_train.csv"),
              "test": str(d / "15_simulate_model_predictions.csv")})
    before = run_all(spec, session)
    if not all(f.verdict == "skipped" for f in before[:4]):
        return ""                      # 확정 전에 열리면 문지기가 새는 것이다
    _confirm(session, "pred_prob", "probability")
    out = {f.id: f for f in run_all(current(session), session)}
    c16, c18 = out.get("MB-C16"), out.get("MB-C18")
    if (c16 and c16.verdict == "fail" and c18 and c18.verdict == "fail"):
        return (f"확정 전 skipped ✓ · ROC {c16.numbers['roc_auc']:.3f} vs "
                f"PR {c16.numbers['pr_auc']:.3f} · 양성 {c16.numbers['n_positive']}개 "
                f"검정력 {c16.numbers['power']:.0%} · 0.5에서 양성 재현율 0%")
    return ""


def check_specific(d: Path, home: Path) -> str:
    """S194 — 완전분리·VIF·조기중단·중요도 (T0)."""
    from statop.modeling.specific import run_all

    session, spec = _model_session(d, home, model_family="linear",
                                   importance="gini")
    out = {f.id: f for f in run_all(spec)}
    c28, c29, c31 = (out.get(k) for k in ("MB-C28", "MB-C29", "MB-C31"))
    if all(f and f.verdict == "fail" for f in (c28, c29, c31)):
        vif = max(c29.numbers["vif"].values())
        pair = c31.numbers["pairs"][0]
        return (f"C28 {c28.numbers['columns'][0]['column']} 완전분리(정규화 없음) · "
                f"C29 VIF {vif:.0f} · C31 {pair['a']}↔{pair['b']} r={pair['r']:.2f}"
                f" ({c31.numbers['kind']})")
    return ""


def check_repro(d: Path, home: Path) -> str:
    from statop.modeling.repro import metric_change, reproducibility, seed_script
    from statop.modeling.spec import ModelSpec, record

    session, spec = _model_session(d, home, metric="ROC-AUC", seed=None)
    changed = ModelSpec(**{**spec.as_dict(), "metric": "PR-AUC"})
    record(session, changed)
    c21 = metric_change(changed, session)
    c25 = reproducibility(spec, session)[0]
    code = seed_script(spec, session)
    compile(code, "seed.py", "exec")
    if c21.verdict == "fail" and c25.verdict == "fail" and "SEED" in code:
        return "MB-C21 지표 변경(Gate) · MB-C25 seed 없음(Gate) · seed 스크립트 실행가능"
    return ""


def check_report(d: Path, home: Path) -> str:
    """S194b· — 트리아드 추천 + B6 한 장 출력 + 재현 명령."""
    from statop.modeling.report import collect, to_markdown

    session, spec = _model_session(d, home, score_column="pred_prob",
                                   metric="ROC-AUC", model_family="penalized",
                                   sets={"train": str(d / "12_simulate_model_train.csv"),
                                         "test": str(d / "15_simulate_model_predictions.csv")})
    rep = collect(session, source_path=str(d / "11_simulate_model_source.csv"),
                  key="sample_id", expected_ratio={"train": 8, "test": 2})
    md = to_markdown(rep)
    ok = (rep.triad and "불균형" in rep.triad["question"]
          and "--metric ROC-AUC" in rep.snippet
          and "학습 전 방향만" in md and "S0000" not in md)
    if ok:
        return (f"트리아드 {rep.triad['goal']}/{rep.triad['support']} · "
                f"차단 {len(rep.gates)}·진단 {len(rep.diagnostics)}·미확인 "
                f"{len(rep.skipped)} · 재현 명령 {len(rep.snippet.splitlines())}줄")
    return ""


CHECKS = [
    ("01 의미 타입 함정", "0/1 정수·정수 수준·음수 log 가 상충으로 뜨는가", check_types),
    ("02 결측 패턴", "동시결측·0채움 의심·30% 초과", check_missing),
    ("03 조성 상관", "S-R01 CLR 수정 · S-R07 척도 혼재", check_correlation),
    ("04 가정 위배", "정규/왜도/outlier/등분산 네 분기가 갈리는가", check_groupdiff),
    ("05 그룹 구조", "subject 당 3회가 값만으로 감지되는가", check_repeated),
    ("06 생존", "사건·중도절단·군별 중앙시간", check_survival),
    ("07 심슨의 역설", "전체와 층별의 방향이 반대인가", check_simpson),
    ("08 가드레일", "GR-01 정의역 · GR-02 SRM · GR-04 SMD", check_guardrail),
    ("09 정렬 편향", "앞N행과 앞/중/뒤 샘플이 다르게 나오는가", check_sortbias),
    ("10 라벨 팔레트", "TCGA=자유문자열 동일 색 · 충돌 키워드", check_labels),
    ("11~14 누수", "MB-C01/02/03/05 네 Gate 가 전부 걸리는가", check_leak),
    ("11~14 비율·손실", "MB-C06 비율 · MB-C07 분포 변형", check_split),
    ("11~14 균형·분포", "MB-C08 지름길 · C12 가중 · 개발vs외부", check_balance),
    ("11~14 전처리", "MB-C10 척도 · MB-C11 분산 몫 지목", check_prep),
    ("15 평가", "타입 확정 전 skipped · ROC/PR 괴리 · 소수 클래스 붕괴", check_eval),
    ("11~14 모델특유", "MB-C28 완전분리 · C29 VIF · C31 중요도", check_specific),
    ("11~14 재현성", "MB-C21 지표 변경 · MB-C25 seed (둘 다 Gate)", check_repro),
    ("11~15 B6 출력", "트리아드 추천 · 한 장 보고 · 재현 명령", check_report),
]


def main() -> None:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else DATA)
    print(f"검증 데이터 확인 {len(CHECKS)}건 → {d}", flush=True)
    home = Path(tempfile.mkdtemp(prefix="statop_verify_"))
    ok = 0
    for i, (name, what, fn) in enumerate(CHECKS, 1):
        try:
            why = fn(d, home)
        except Exception as e:                      # noqa: BLE001
            why = ""
            what = f"{what}  [오류: {type(e).__name__} {e}]"
        mark = "✅" if why else "❌"
        ok += bool(why)
        print(f"[{i}/{len(CHECKS)}] {mark} {name:<16s} {why or what}", flush=True)
    print(f"\n{ok}/{len(CHECKS)} 확인됨", flush=True)
    if ok != len(CHECKS):
        sys.exit(1)


if __name__ == "__main__":
    main()
