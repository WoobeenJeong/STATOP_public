"""모듈 B — 모델링 감사 (Phase 15).

모듈 A 와 **별개 모듈**이다. 같은 세션을 쓰더라도 op 와 화면이 섞이면 안 된다.
"""

import json

import numpy as np
import pandas as pd
import pytest

from statop.modeling.spec import ModelSpec, build, checks, questions, record, tiers


@pytest.fixture
def sets(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(0)
    out = {}
    for name, n in (("train", 400), ("test", 100)):
        p = tmp_path / f"{name}.csv"
        pd.DataFrame({"pid": [f"P{i:04d}" for i in range(n)],
                      "x1": rng.normal(0, 1, n),
                      "y": rng.integers(0, 2, n),
                      "score": rng.random(n)}).to_csv(p, index=False)
        out[name] = str(p)
    return out


def _spec(sets, **kw):
    base = dict(question="MB-Q01", tier="MB-M0", validation="group_kfold", k=5,
                group_column="pid", label_column="y", score_column="score",
                seed=42, sets=sets)
    return ModelSpec(**{**base, **kw})


def test_rule_db_is_the_source_of_questions_and_checks():
    assert len(questions()) == 8 and len(tiers()) == 4
    # MB-C34(모델 비교, )는 3.2 설정 절에 들어가 번호 순서가 아니다
    assert {c["id"] for c in checks()} == {f"MB-C{i:02d}" for i in range(1, 35)
                                       if i not in (30, 32, 33)}
    assert {c["id"] for c in checks("data")} >= {"MB-C01", "MB-C02", "MB-C03"}


def test_valid_configuration_passes_with_a_summary(sets):
    res = build(_spec(sets))
    assert res.problems == [] and res.v1_supported is True
    assert res.n_rows == {"train": 400, "test": 100}
    assert any("MB-Q01" in n for n in res.notes)
    assert any("감사 입력" in n for n in res.notes)     # 무엇이 더 필요한지 말한다


def test_group_column_with_plain_kfold_is_flagged(sets):
    """같은 대상이 train/test 를 넘나들면 누수다 (MB-C02)."""
    res = build(_spec(sets, validation="kfold"))
    assert any("GroupKFold" in n for n in res.notes)


def test_missing_seed_is_surfaced_early(sets):
    """재현성은 B5 에서 Gate 다 — B1 에서 미리 알려야 나중에 막히지 않는다 (MB-C25)."""
    assert any("seed" in n for n in build(_spec(sets, seed=None)).notes)
    assert not any("seed" in n for n in build(_spec(sets)).notes)


def test_out_of_v1_scope_is_refused_before_running(sets):
    """판정하지 않는 조합을 돌려놓고 빈 결과를 주면 안 된다."""
    res = build(_spec(sets, question="MB-Q06", tier="MB-M2"))
    assert res.v1_supported is False
    assert any("판정하지 않습니다" in p for p in res.problems)


@pytest.mark.parametrize(("kw", "needle"), [
    ({"question": "MB-Q99"}, "모델링 질문"),
    ({"tier": "MB-M9"}, "모델 티어"),
    ({"validation": "magic"}, "검증 방식"),
    ({"validation": "kfold", "k": None}, "분할 수"),
    ({"validation": "group_kfold", "group_column": None}, "그룹 컬럼"),
    ({"validation": "time_split", "time_column": None}, "시간 컬럼"),
    ({"label_column": None}, "라벨 컬럼"),
])
def test_bad_configuration_is_refused(sets, kw, needle):
    res = build(_spec(sets, **kw))
    assert any(needle in p for p in res.problems), res.problems


def test_missing_set_file_is_reported(sets, tmp_path):
    res = build(_spec({**sets, "external": str(tmp_path / "nope.csv")}))
    assert any("external" in p for p in res.problems)


def test_module_b_spec_is_stored_apart_from_module_a(sets, tmp_path):
    """모듈 A 의 analysis_spec 과 섞이면 어느 모듈의 전제인지 알 수 없다."""
    from statop.analyze.spec import Spec
    from statop.analyze.spec import record as record_a
    from statop.session.core import load_session, replay
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(sets["train"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)

    record_a(session, Spec(question="Q-01", y="x1", group="y"))
    record(session, _spec(sets))

    st = replay(load_session(session))
    assert len(st["model_specs"]) == 1 and len(st["analysis_spec"] if
                                               "analysis_spec" in st else st["specs"]) >= 1
    assert st["model_specs"][0]["question"] == "MB-Q01"
    assert st["model_specs"][0]["validation"] == "group_kfold"


def test_current_reads_back_the_last_configuration(sets, tmp_path):
    from statop.modeling.spec import current
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(sets["train"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)

    assert current(session) is None
    record(session, _spec(sets))
    record(session, _spec(sets, k=10))
    got = current(session)
    assert got is not None and got.k == 10 and got.question == "MB-Q01"


def test_model_cli_lists_and_plans(sets):
    from typer.testing import CliRunner

    from statop.cli import app

    runner = CliRunner()
    r = runner.invoke(app, ["model", "questions"])
    assert r.exit_code == 0 and "MB-Q01" in r.output and "MB-M0" in r.output

    r = runner.invoke(app, ["model", "checks", "--group", "data"])
    assert r.exit_code == 0 and "MB-C01" in r.output and "Gate" in r.output

    r = runner.invoke(app, ["model", "plan", "--question", "MB-Q01",
                            "--tier", "MB-M0", "--label", "y",
                            "--validation", "kfold", "--k", "5",
                            "--train", sets["train"], "--test", sets["test"]])
    assert r.exit_code == 0 and "MB-Q01" in r.output


# ── B2 누수·중복 (~) — 전부 Gate ───────────────────
@pytest.fixture
def split_sets(tmp_path):
    """환자 1명당 2샘플 · 시간 순 · 라벨 대리변수를 심은 자료."""
    rng = np.random.default_rng(0)
    n = 400
    base = pd.DataFrame({
        "pid": [f"P{i // 2:04d}" for i in range(n)],
        "t": pd.date_range("2024-01-01", periods=n, freq="D"),
        "x1": rng.normal(0, 1, n), "x2": rng.normal(0, 1, n),
        "y": rng.integers(0, 2, n)})
    base["proxy"] = base["y"] * 10 + rng.normal(0, 0.01, n)

    def write(name: str, frame: pd.DataFrame) -> str:
        p = tmp_path / f"{name}.csv"
        frame.to_csv(p, index=False)
        return str(p)

    clean = {"train": write("train", base.iloc[:300]),
             "test": write("test", base.iloc[300:])}
    shuffled = base.sample(frac=1, random_state=0)
    messy = {"train": write("btrain", shuffled.iloc[:300]),
             "test": write("btest", pd.concat([shuffled.iloc[300:],
                                               shuffled.iloc[:20]]))}
    near = base.iloc[:10].copy()
    near[["x1", "x2"]] += 1e-5
    return {"base": base, "clean": clean, "messy": messy, "write": write,
            "near": write("tnear", pd.concat([base.iloc[300:], near]))}


def _spec_for(sets, **kw):
    base = dict(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                group_column="pid", time_column="t", label_column="y", sets=sets)
    return ModelSpec(**{**base, **kw})


def test_clean_split_has_no_duplicates(split_sets):
    """우연히 가까운 점을 중복으로 세면 멀쩡한 split 이 막힌다."""
    from statop.modeling.leak import duplicate_rows

    f = duplicate_rows(_spec_for(split_sets["clean"]))
    assert f.verdict == "pass" and f.grade == "Gate"


@pytest.mark.parametrize("kind", ["exact", "near"])
def test_duplicates_across_sets_are_caught(split_sets, kind):
    from statop.modeling.leak import duplicate_rows

    base = split_sets["base"]
    extra = base.iloc[:10].copy()
    if kind == "near":
        extra[["x1", "x2"]] += 1e-5
    sets = {**split_sets["clean"],
            "test": split_sets["write"](f"t_{kind}",
                                        pd.concat([base.iloc[300:], extra]))}
    f = duplicate_rows(_spec_for(sets))
    assert f.verdict == "fail"
    assert f.numbers["test"][kind] == 10


def test_group_crossing_is_caught_and_named(split_sets):
    from statop.modeling.leak import group_crossing

    assert group_crossing(_spec_for(split_sets["clean"])).verdict == "pass"
    f = group_crossing(_spec_for(split_sets["messy"]))
    assert f.verdict == "fail" and "pid" in f.summary
    assert f.numbers["test"]["crossed"] > 50
    assert "GroupKFold" in f.action


def test_time_overlap_is_caught(split_sets):
    from statop.modeling.leak import time_leak

    assert time_leak(_spec_for(split_sets["clean"])).verdict == "pass"
    assert time_leak(_spec_for(split_sets["messy"])).verdict == "fail"


def test_label_proxy_is_caught(split_sets):
    """라벨을 거의 그대로 담은 피처가 있으면 모델이 할 일이 없다."""
    from statop.modeling.leak import label_proxy

    f = label_proxy(_spec_for(split_sets["clean"]))
    assert f.verdict == "fail" and any("proxy" in d for d in f.detail)
    assert f.numbers["proxy"] >= 0.98 and f.numbers["x1"] < 0.9


def test_missing_setup_is_skipped_not_passed(split_sets):
    """확인할 수 없는 것을 '통과'로 두면 없는 안전을 믿게 된다."""
    from statop.modeling.leak import group_crossing, time_leak

    assert group_crossing(_spec_for(split_sets["clean"],
                                    group_column=None)).verdict == "skipped"
    assert time_leak(_spec_for(split_sets["clean"],
                               time_column=None)).verdict == "skipped"


def test_leak_cli_blocks_on_gate(split_sets, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from statop.cli import app
    from statop.modeling.spec import record
    from statop.shell.screen import Screen

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    sc = Screen()
    sc.open_path(split_sets["messy"]["train"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    record(session, _spec_for(split_sets["messy"]))

    r = CliRunner().invoke(app, ["model", "leak", "--session", session])
    assert r.exit_code == 1                       # Gate 는 막는다
    assert "MB-C01" in r.output and "MB-C02" in r.output
    assert "Gate" in r.output or "믿을 수 없습니다" in r.output


# ──  코드 정적 감지 (MB-C04, MB-C09) ──────────────────────

LEAKY = """
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import SelectKBest
from sklearn.model_selection import train_test_split

df = pd.read_csv("d.csv")
X, y = df.drop(columns=["y"]), df["y"]
sc = StandardScaler()
X = sc.fit_transform(X)
sel = SelectKBest(k=10)
X = sel.fit_transform(X, y)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3)
"""

CLEAN = """
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import SelectKBest
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

df = pd.read_csv("d.csv")
X, y = df.drop(columns=["y"]), df["y"]
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3)
pipe = Pipeline([("sc", StandardScaler()), ("sel", SelectKBest(k=10)),
                 ("clf", LogisticRegression())])
pipe.fit(Xtr, ytr)
"""


def _audit(tmp_path, src, name="m.py"):
    from statop.modeling.code_audit import audit_code

    p = tmp_path / name
    p.write_text(src, encoding="utf-8")
    return {f.id: f for f in audit_code(str(p))}


def test_code_catches_fit_before_split(tmp_path):
    """나누기 전 fit 은 표준화(MB-C09)와 피처선택(MB-C04) 양쪽에서 잡힌다."""
    out = _audit(tmp_path, LEAKY)
    assert out["MB-C09"].verdict == "fail"
    assert out["MB-C04"].verdict == "fail"
    # 몇 줄인지 말해야 고칠 수 있다
    assert any("StandardScaler" in d for d in out["MB-C09"].detail)
    assert any("SelectKBest" in d for d in out["MB-C04"].detail)


def test_code_pipeline_is_pass(tmp_path):
    """Pipeline 안의 전처리는 fold 안에서 fit 된다 — 통과."""
    out = _audit(tmp_path, CLEAN)
    assert out["MB-C09"].verdict == "pass"
    assert out["MB-C04"].verdict == "pass"


def test_code_inline_call_caught(tmp_path):
    """변수에 담지 않고 바로 쓴 경우도 잡는다."""
    src = ("from sklearn.preprocessing import MinMaxScaler\n"
           "from sklearn.model_selection import KFold\n"
           "X = MinMaxScaler().fit_transform(X)\n"
           "cv = KFold(5)\n")
    assert _audit(tmp_path, src)["MB-C09"].verdict == "fail"


def test_code_no_split_is_skipped(tmp_path):
    """나누는 곳이 없으면 앞뒤를 가릴 수 없다 — pass 가 아니라 skipped."""
    out = _audit(tmp_path, "from sklearn.preprocessing import StandardScaler\n"
                           "X = StandardScaler().fit_transform(X)\n")
    assert out["MB-C09"].verdict == "skipped"
    assert out["MB-C04"].verdict == "skipped"


def test_code_missing_and_broken(tmp_path):
    from statop.modeling.code_audit import audit_code

    assert all(f.verdict == "skipped" for f in audit_code(str(tmp_path / "없다.py")))
    bad = tmp_path / "bad.py"
    bad.write_text("def f(:\n", encoding="utf-8")
    assert all(f.verdict == "skipped" for f in audit_code(str(bad)))


def test_code_reports_split_line_and_limit(tmp_path):
    """어디서 나눴는지와 '이게 증명은 아니다'를 항상 함께 말한다."""
    out = _audit(tmp_path, CLEAN)
    joined = " ".join(out["MB-C09"].detail)
    assert "train_test_split" in joined
    assert len(out["MB-C09"].detail) >= 2


# ──  세트 비율·손실 (MB-C06 / MB-C07) ────────────────────
@pytest.fixture
def source_sets(tmp_path, monkeypatch):
    """원본 1,000행 → sid 로 대조 가능한 split 여러 벌."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(7)
    n = 1000
    src = pd.DataFrame({"sid": [f"S{i:04d}" for i in range(n)],
                        "pid": [f"P{i:04d}" for i in range(n)],
                        "x1": rng.normal(0, 1, n),
                        "y": rng.integers(0, 2, n)})

    def write(name: str, frame: pd.DataFrame) -> str:
        p = tmp_path / f"{name}.csv"
        frame.to_csv(p, index=False)
        return str(p)

    return {"src": src, "path": write("source", src), "write": write}


def _split(src, write, n_train, name="a"):
    return {"train": write(f"{name}_train", src.iloc[:n_train]),
            "test": write(f"{name}_test", src.iloc[n_train:])}


def test_c06_split_ratio_matches_and_mismatches_the_plan(source_sets):
    """계획한 8:2 대로 나뉘었는가 — 맞으면 통과, 6:4 면 걸린다."""
    from statop.modeling.split_audit import set_ratio

    src, write = source_sets["src"], source_sets["write"]
    plan = {"train": 8, "test": 2}
    ok = set_ratio(_spec_for(_split(src, write, 800, "ok")), plan)
    assert ok[0].id == "MB-C06" and ok[0].verdict == "pass"

    bad = set_ratio(_spec_for(_split(src, write, 600, "bad")), plan)
    assert bad[0].verdict == "fail" and bad[0].grade == "Gate"
    assert "600" in bad[0].summary and bad[0].action


def test_c06_without_a_planned_ratio_is_skipped_not_passed(source_sets):
    """균등으로 가정하면 8:2 분할이 전부 '이상'이 된다 — 검사하지 않는다."""
    from statop.modeling.split_audit import set_ratio

    out = set_ratio(_spec_for(_split(source_sets["src"], source_sets["write"], 800)))
    assert out[0].verdict == "skipped"


def test_c06_catches_a_set_whose_class_ratio_differs(source_sets):
    """한 세트에만 클래스가 몰리면 층화가 안 걸린 것이다."""
    from statop.modeling.split_audit import set_ratio

    src, write = source_sets["src"], source_sets["write"]
    skewed = pd.concat([src[src.y == 1].iloc[:250], src[src.y == 0].iloc[:50]])
    sets = {"train": write("s_train", src.iloc[400:]),
            "test": write("s_test", skewed)}
    out = set_ratio(_spec_for(sets), {"train": 6, "test": 3})
    strat = [f for f in out if "per_set" in f.numbers]
    assert len(strat) == 1 and strat[0].verdict == "fail"     # 컬럼마다 쏟지 않는다
    assert "test" in strat[0].numbers["failed"]
    # 임계는 세트 수로 나눠 도구 스스로 다중비교 오류를 범하지 않는다
    assert strat[0].numbers["p_threshold_adjusted"] < 0.0005
    # 두 축 — 세트별과 개발/외부
    body = " ".join(strat[0].detail)
    assert "세트별" in body and "개발/외부" in body
    # 일부러 그룹을 external 로 뺀 설계일 수 있다는 것을 함께 말한다
    assert "재확인" in body


def test_c07_loss_funnel_and_biased_loss(source_sets):
    """y==1 행만 골라 뺀 split — 무작위 손실이 아니다."""
    from statop.modeling.split_audit import source_loss

    src, write = source_sets["src"], source_sets["write"]
    kept = pd.concat([src[src.y == 0], src[src.y == 1].iloc[:50]])
    sets = {"train": write("l_train", kept.iloc[:400]),
            "test": write("l_test", kept.iloc[400:])}
    out = source_loss(_spec_for(sets), source_sets["path"], "sid")
    kinds = {f.verdict for f in out}
    assert "fail" in kinds
    joined = " ".join(f.summary for f in out)
    assert "y" in joined            # 어느 컬럼과 연관됐는지 지목한다


def test_c07_clean_split_loses_nothing(source_sets):
    from statop.modeling.split_audit import source_loss

    src, write = source_sets["src"], source_sets["write"]
    out = source_loss(_spec_for(_split(src, write, 800, "c")),
                      source_sets["path"], "sid")
    assert all(f.verdict != "fail" for f in out)
    assert any(f.verdict == "pass" for f in out)


@pytest.mark.parametrize("key,needle", [(None, "키"), ("nope", "nope"), ("y", "중복")])
def test_c07_unmatchable_rows_are_skipped_not_passed(source_sets, key, needle):
    """맞출 수 없는데 맞춘 척하면 없는 손실을 만든다 — pass 가 아니라 skipped."""
    from statop.modeling.split_audit import source_loss

    src, write = source_sets["src"], source_sets["write"]
    out = source_loss(_spec_for(_split(src, write, 800, "u")),
                      source_sets["path"], key)
    assert [f.verdict for f in out] == ["skipped"]
    assert needle in out[0].summary


def test_split_cli_blocks_on_gate(source_sets, tmp_path):
    from typer.testing import CliRunner

    from statop.cli import app
    from statop.shell.screen import Screen

    src, write = source_sets["src"], source_sets["write"]
    sc = Screen()
    sc.open_path(source_sets["path"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    record(session, _spec_for(_split(src, write, 600, "cli"), group_column=None,
                              time_column=None, validation="kfold", k=5))

    r = CliRunner().invoke(app, ["model", "split", "--session", session,
                                 "--expect", "train=8,test=2", "--key", "sid"])
    assert r.exit_code == 1 and "MB-C06" in r.output


# ──  라벨 인코딩 방향 (MB-C13) ───────────────────────────
@pytest.fixture
def labelled(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(3)
    n = 300
    df = pd.DataFrame({"sid": [f"S{i:04d}" for i in range(n)],
                       "x1": rng.normal(0, 1, n),
                       "grp": rng.choice(["case", "control"], n)})
    paths = {}
    for name, part in (("train", df.iloc[:200]), ("test", df.iloc[200:])):
        p = tmp_path / f"lab_{name}.csv"
        part.to_csv(p, index=False)
        paths[name] = str(p)
    return {"sets": paths, "df": df, "tmp": tmp_path}


def _lab_session(labelled):
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(labelled["sets"]["train"])
    sc.toggle_page()
    sc.import_picked()
    return str(sc.session_file)


def test_c13_alphabetical_encoding_flips_the_positive_class(labelled):
    """case < control 이라 매핑이 없으면 case 가 0 이 된다 — 방향이 뒤집힌다."""
    from statop.modeling.label_audit import label_audit

    session = _lab_session(labelled)
    spec = _spec_for(labelled["sets"], label_column="grp", positive_class="case",
                     group_column=None, time_column=None)
    out = label_audit(spec, session)
    flipped = [f for f in out if f.verdict == "fail"]
    assert flipped and "case" in flipped[0].summary
    # 도구는 학습 코드를 보지 않았다 — 단정이 아니라 '가능성'으로 말한다
    assert "가능성" in flipped[0].summary
    assert flipped[0].numbers["codes"]["case"] == 0
    assert flipped[0].numbers["recorded"] is False
    # 어떤 클래스가 몇 번인지 표로 보여준다
    assert any("case=0" in d and "control=1" in d for d in flipped[0].detail)


def test_c13_recorded_mapping_with_positive_high_passes(labelled):
    from statop.modeling.label_audit import label_audit
    from statop.session.core import append_op, load_session, main_source, save_session

    session = _lab_session(labelled)
    doc = load_session(session)
    append_op(doc, "label_map", source=main_source(doc)["id"], column="grp",
              mapping={"control": 0, "case": 1})
    save_session(doc)
    spec = _spec_for(labelled["sets"], label_column="grp", positive_class="case",
                     group_column=None, time_column=None)
    out = label_audit(spec, session)
    assert all(f.verdict == "pass" for f in out)


def test_c13_shows_class_ratio_per_set(labelled):
    """요구사항 — 라벨을 정한 뒤 세트별 비율을 다시 보여준다."""
    from statop.modeling.label_audit import label_audit

    spec = _spec_for(labelled["sets"], label_column="grp", positive_class="case",
                     group_column=None, time_column=None)
    out = label_audit(spec, _lab_session(labelled))
    assert set(out[0].numbers) == {"train", "test"}
    assert all("case" in v for v in out[0].numbers.values())


def test_c07_shift_view_overlays_before_and_after(source_sets):
    """'유의하다'만으로는 어느 쪽이 얼마나 달라졌는지 알 수 없다 — 겹쳐 본다."""
    from statop.modeling.split_audit import shift_view

    src, write = source_sets["src"], source_sets["write"]
    kept = pd.concat([src[src.y == 0], src[src.y == 1].iloc[:50]])
    sets = {"train": write("v_train", kept.iloc[:400]),
            "test": write("v_test", kept.iloc[400:])}
    v = shift_view(_spec_for(sets), source_sets["path"], "sid", "y")
    assert v["info"]["kind"] == "categorical"
    body = "\n".join(v["lines"])
    assert "정리 전" in body and "정리 후" in body
    # 줄어든 쪽(1)이 비율로 드러나야 한다
    assert v["info"]["before"]["1"] > v["info"]["after"]["1"]

    num = shift_view(_spec_for(sets), source_sets["path"], "sid", "x1")
    assert num["info"]["kind"] == "numeric"
    assert any("─" in ln for ln in num["lines"])        # 축이 있다 ()


def test_c06_ignores_sets_absent_from_the_plan(source_sets):
    """계획에 없는 external 을 계획 위반으로 세면 안 된다 (0 으로 나누기도 한다)."""
    from statop.modeling.split_audit import set_ratio

    src, write = source_sets["src"], source_sets["write"]
    sets = {"train": write("e_train", src.iloc[:800]),
            "test": write("e_test", src.iloc[800:900]),
            "external": write("e_ext", src.iloc[900:])}
    out = set_ratio(_spec_for(sets), {"train": 8, "test": 1})
    assert out[0].verdict == "pass"
    assert any("external" in d for d in out[0].detail)


def test_c06_shows_both_axes_including_dev_vs_external(source_sets):
    """세트별과 개발/외부 — 두 축으로 봐야 '밖으로 뺀 쪽'의 구성이 비교된다."""
    from statop.modeling.split_audit import set_ratio

    src, write = source_sets["src"], source_sets["write"]
    sets = {"train": write("x_train", src.iloc[:600]),
            "test": write("x_test", src.iloc[600:800]),
            "external": write("x_ext", src.iloc[800:])}
    strat = [f for f in set_ratio(_spec_for(sets)) if "per_set" in f.numbers][0]
    assert set(strat.numbers["per_set"]) == {"train", "test", "external"}
    assert set(strat.numbers["dev_ext"]) == {"dev", "ext"}


# ── · 균형·분포 (MB-C08 / MB-C12) ────────────────────
@pytest.fixture
def balance_sets(tmp_path, monkeypatch):
    """소수 클래스 10% · site 가 라벨을 예측 · external 만 age 가 높은 자료."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(13)
    n = 800
    y = (rng.random(n) < 0.1).astype(int)          # 1 이 10%
    df = pd.DataFrame({
        "sid": [f"S{i:04d}" for i in range(n)],
        "x1": rng.normal(0, 1, n),
        "age": rng.normal(60, 8, n),
        # site 가 라벨과 강하게 붙어 있다 — 모델이 라벨 대신 이걸 외운다
        "site": np.where(y == 1, "B", np.where(rng.random(n) < 0.9, "A", "B")),
        "y": y})

    def write(name, frame):  # noqa: ANN001, ANN202
        p = tmp_path / f"b_{name}.csv"
        frame.to_csv(p, index=False)
        return str(p)

    ext = df.iloc[600:].copy()
    ext["age"] += 12                                # 외부만 분포가 다르다
    return {"df": df, "write": write,
            "sets": {"train": write("train", df.iloc[:600]),
                     "external": write("ext", ext)}}


def _bspec(sets, **kw):
    base = dict(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                label_column="y", sets=sets)
    return ModelSpec(**{**base, **kw})


def test_c08_catches_class_imbalance_and_says_why(balance_sets):
    from statop.modeling.balance import class_balance

    out = class_balance(_bspec(balance_sets["sets"]))
    c08 = [f for f in out if f.id == "MB-C08"][0]
    assert c08.verdict == "fail" and c08.grade == "Diag"     # 막지는 않는다
    assert c08.numbers["minority"] == "1"
    assert any("정확도" in d for d in c08.detail)            # 왜 문제인지 말한다


def test_c12_flags_missing_weighting_and_accepts_recorded(balance_sets):
    """도구는 학습 코드를 읽지 않는다 — 했는지가 아니라 적혀 있는지를 본다."""
    from statop.modeling.balance import class_balance

    out = class_balance(_bspec(balance_sets["sets"]))
    c12 = [f for f in out if f.id == "MB-C12"][0]
    assert c12.verdict == "fail"

    ok = class_balance(_bspec(balance_sets["sets"], class_weight="balanced"))
    assert [f for f in ok if f.id == "MB-C12"][0].verdict == "pass"


def test_c08_hidden_imbalance_names_the_meta_column(balance_sets):
    from statop.modeling.balance import hidden_imbalance

    f = hidden_imbalance(_bspec(balance_sets["sets"]), ["site", "age"])
    assert f.verdict == "fail" and "site" in f.summary
    assert any("일반화 성능 저하" in d for d in f.detail)
    # SMD 큰 순 — site(2.5) 가 우연 수준(0.13)짜리 age 보다 먼저 온다
    assert f.detail[0].startswith("site") and f.numbers["site"]["smd"] > 1
    # 우연 수준 이하는 그렇다고 적는다 (임계는 규칙 DB 것이라 바꾸지 않는다)
    assert any("우연만으로도" in d for d in f.detail)


def test_c08_multiclass_is_skipped_not_passed(balance_sets, tmp_path):
    """3군 이상 SMD 는 정의가 갈린다 — 못 보는 것을 통과라고 하지 않는다."""
    from statop.modeling.balance import hidden_imbalance

    df = balance_sets["df"].copy()
    df["y3"] = np.resize([0, 1, 2], len(df))
    sets = {"train": balance_sets["write"]("m3", df)}
    f = hidden_imbalance(_bspec(sets, label_column="y3"), ["site"])
    assert f.verdict == "skipped" and "3군" in f.summary


def test_set_shift_finds_the_feature_that_moved(balance_sets):
    """개발과 외부의 분포가 다르면 외부 성능 저하의 원인을 가릴 수 없다 ."""
    from statop.modeling.balance import set_shift

    f = set_shift(_bspec(balance_sets["sets"]))
    assert f.verdict == "fail"
    assert "age" in f.numbers["columns"] and "x1" not in f.numbers["columns"]
    assert f.numbers["n_dev"] == 600 and f.numbers["n_ext"] == 200


def test_set_shift_without_external_is_skipped(balance_sets):
    from statop.modeling.balance import set_shift

    sets = {"train": balance_sets["sets"]["train"]}
    assert set_shift(_bspec(sets)).verdict == "skipped"


def test_balance_cli_reports_diag_without_blocking(balance_sets):
    """Diag 는 막지 않는다 — 종료코드 0 ()."""
    from typer.testing import CliRunner

    from statop.cli import app
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(balance_sets["sets"]["train"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    record(session, _bspec(balance_sets["sets"]))

    r = CliRunner().invoke(app, ["model", "balance", "--session", session,
                                 "--meta", "site,age"])
    assert r.exit_code == 0, r.output
    assert "MB-C08" in r.output and "MB-C12" in r.output
    assert "진단" in r.output


def test_c08_handles_sets_with_overlapping_index(balance_sets):
    """세트를 따로 읽으면 인덱스가 0부터 겹친다 — 합칠 때 새로 매기지 않으면 터진다."""
    from statop.modeling.balance import class_balance, hidden_imbalance

    sets = {"train": balance_sets["sets"]["train"],
            "test": balance_sets["write"]("dup", balance_sets["df"].iloc[600:])}
    spec = _bspec(sets)
    assert hidden_imbalance(spec, ["site"]).verdict in {"fail", "pass"}
    assert class_balance(spec)[0].verdict in {"fail", "pass"}


def test_c13_absent_level_is_reported(tmp_path, monkeypatch):
    """external 에 양성이 하나도 없으면 '같은 수준'이라고 말하면 안 된다."""
    import pandas as pd

    from statop.modeling.label_audit import label_audit

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    df = pd.DataFrame({"sid": [f"S{i:03d}" for i in range(100)],
                       "grp": ["case"] * 30 + ["control"] * 70})
    tr = tmp_path / "tr.csv"
    ex = tmp_path / "ex.csv"
    df.to_csv(tr, index=False)
    df[df.grp == "control"].to_csv(ex, index=False)      # external 은 한 종류뿐
    f = label_audit(_spec_for({"train": str(tr), "external": str(ex)},
                              label_column="grp", positive_class="case",
                              group_column=None, time_column=None))[0]
    assert f.verdict == "fail" and "case" in f.summary


def test_shortcut_risk_appears_in_metric_recommendations(balance_sets, tmp_path):
    """지름길 학습 위험은 지표를 고르는 자리에서 보여야 한다 (사용자 요청, MB-C08)."""
    from statop.analyze.metrics import suggest
    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec
    from statop.analyze.spec import record as record_a
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(balance_sets["sets"]["train"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    sc.toggle_hold("site")                       # 메타는 hold 한 컬럼이다 (요구사항)
    record(session, _bspec(balance_sets["sets"]))

    # 모듈 A 쪽에서 검정을 하나 돌려야 지표 패널이 열린다
    record_a(session, Spec(question="Q-01", y="x1", group="y"))
    run_test(session, "T-101")

    panel = suggest(session)
    guard = [g for g in panel.guardrail if g.id == "MB-C08"]
    assert guard, [g.id for g in panel.guardrail]
    assert "site" in guard[0].name
    assert guard[0] is panel.guardrail[0]        # 맨 앞에 — 묻히면 안 본다


# ── ·· 전처리·모델 비교 ────────────────────────
@pytest.fixture
def prep_sets(tmp_path, monkeypatch):
    """척도가 크게 벌어진 자료 — age(SD 8) vs marker(SD 0.1) 는 800배."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(21)
    n = 400
    df = pd.DataFrame({"sid": [f"S{i:04d}" for i in range(n)],
                       "age_years": rng.normal(60, 8, n).round(1),
                       "marker": rng.normal(0, 0.01, n).round(5),
                       "score2": rng.normal(0, 1, n).round(3),
                       "y": (rng.random(n) < 0.3).astype(int)})
    p = tmp_path / "prep.csv"
    df.to_csv(p, index=False)
    return {"sets": {"train": str(p)}, "df": df}


def _pspec(sets, **kw):
    base = dict(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                label_column="y", sets=sets)
    return ModelSpec(**{**base, **kw})


def test_rule_table_for_preprocessing_comes_from_md():
    """MB-C10 이 가리키던 '모델×전처리 규칙' 표가 실제로 규칙 DB 에 있다 ."""
    from statop.modeling.prep import families, family_of

    fams = {f["family"]: f["scaling"] for f in families()}
    assert fams["distance"] == "required" and fams["tree"] == "optional"
    # 목적·구조에 따라 갈리는 계열은 세 번째 상태를 갖는다 (필요/불필요로 가르지 않는다)
    assert fams["projection"] == "depends" and fams["neural"] == "depends"
    assert all("**" not in f["why"] for f in families())   # md 강조는 화면에 안 나간다
    assert family_of("nope") is None            # 모르는 계열은 지어내지 않는다


@pytest.mark.parametrize(("family", "verdict"), [
    ("distance", "fail"), ("penalized", "fail"),
    ("projection", "fail"), ("neural", "fail"),          # 조건부 — 기록만 청한다
    ("tree", "pass"), ("linear", "pass"), ("naive_bayes", "pass"),
])
def test_c10_follows_the_rule_table(prep_sets, family, verdict):
    from statop.modeling.prep import scaling_needed

    f = scaling_needed(_pspec(prep_sets["sets"], model_family=family))
    assert f.verdict == verdict and f.grade == "Diag"


@pytest.mark.parametrize("family", ["projection", "neural"])
def test_c10_conditional_families_only_ask_for_a_record(prep_sets, family):
    """어느 쪽이 옳다고 말하지 않는다 — 목적·구조에 따라 갈리므로 기록만 청한다."""
    from statop.modeling.prep import scaling_needed

    f = scaling_needed(_pspec(prep_sets["sets"], model_family=family))
    assert f.numbers["scaling_rule"] == "depends"
    assert "목적" in f.summary and "필요한데" not in f.summary
    # 어느 쪽을 택했든 기록만 되어 있으면 통과
    ok = scaling_needed(_pspec(prep_sets["sets"], model_family=family,
                               scaling="standard"))
    assert ok.verdict == "pass"


def test_c10_names_the_columns_that_carry_the_scale(prep_sets):
    """'표준화하세요'만 말하면 무엇을 볼지 모른다 — 컬럼과 배수를 지목한다 ."""
    from statop.modeling.prep import scaling_needed

    f = scaling_needed(_pspec(prep_sets["sets"], model_family="distance"))
    assert f.numbers["max_ratio"] > 100
    assert list(f.numbers["columns"])[0] == "age_years"      # 큰 순
    assert any("age_years" in d for d in f.detail)


def test_c10_recorded_scaling_passes(prep_sets):
    """했는지가 아니라 적혀 있는지를 본다 — 학습 코드를 읽지 않는다."""
    from statop.modeling.prep import scaling_needed

    f = scaling_needed(_pspec(prep_sets["sets"], model_family="distance",
                              scaling="standard"))
    assert f.verdict == "pass" and "standard" in f.summary


def test_c11_points_at_the_column_that_takes_the_first_axis(prep_sets):
    """S190b — PCA 는 분산 최대 방향을 찾으므로 분산 큰 컬럼이 첫 축을 가져간다."""
    from statop.modeling.prep import projection_scaling

    f = projection_scaling(_pspec(prep_sets["sets"], model_family="projection",
                                  reduction="PCA"))
    assert f.verdict == "fail" and "age_years" in f.summary
    assert f.numbers["variance_share"]["age_years"] > 0.9
    assert projection_scaling(_pspec(prep_sets["sets"])).verdict == "skipped"


def test_c15_epv_uses_the_rarer_class(prep_sets):
    """많은 쪽으로 세면 낙관적이 된다 — 드문 쪽이 사건이다."""
    from statop.modeling.prep import events_per_variable

    f = events_per_variable(_pspec(prep_sets["sets"], model_family="penalized"))
    n_events = int(prep_sets["df"].y.value_counts().min())
    assert f.numbers["events"] == n_events and f.numbers["variables"] == 3
    assert f.verdict == "pass"                      # 사건 ~120 / 변수 3 → EPV 40
    # 트리 계열은 EPV 대상이 아니다
    assert events_per_variable(
        _pspec(prep_sets["sets"], model_family="tree")).verdict == "skipped"


def test_c15_low_epv_is_reported_with_room(tmp_path, monkeypatch):
    from statop.modeling.prep import events_per_variable

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(3)
    n = 120
    df = pd.DataFrame({f"x{i}": rng.normal(0, 1, n) for i in range(12)})
    df["y"] = (rng.random(n) < 0.15).astype(int)     # 사건 ~18 / 변수 12 → EPV 1.5
    p = tmp_path / "epv.csv"
    df.to_csv(p, index=False)
    f = events_per_variable(_pspec({"train": str(p)}, model_family="penalized"))
    assert f.verdict == "fail" and f.numbers["epv"] < 10
    assert any("변수는" in d for d in f.detail)      # 몇 개까지 가능한지 알려준다


@pytest.mark.parametrize(("a", "b", "cond"), [
    ("m1: age+sex [n=100]", "m2: age+sex+stage [n=100]", "same_n_nested"),
    ("m1: age+sex [n=100]", "m2: age+stage [n=100]", "same_n_non_nested"),
    ("m1: age [n=100]", "m2: age [n=80]", "different_n"),
    ("m1: age [n=100] [y=death]", "m2: age [n=100] [y=relapse]", "different_outcome"),
    ("m1: age [family=binomial]", "m2: age [family=gaussian]", "different_family"),
])
def test_c34_classifies_each_model_pair(a, b, cond):
    """어느 쌍이 왜 안 되는지 지목해야 고칠 수 있다 ."""
    from statop.modeling.compare import Model, classify

    assert classify(Model.parse(a), Model.parse(b)) == cond


def test_c34_names_the_pairs_and_how_far_apart(tmp_path):
    """막지 않는다 (Diag). 대신 행이 얼마나 다른지를 숫자로 보인다."""
    from statop.modeling.compare import Model, audit

    models = [Model.parse(t) for t in (
        "m1: age+sex [n=480] [y=death]",
        "m2: age+sex+stage [n=480] [y=death]",
        "m3: age+stage [n=412] [y=death]")]
    f = audit(models)
    assert f.verdict == "fail" and f.id == "MB-C34" and f.grade == "Diag"
    assert "m1 vs m3" in f.summary and "m2 vs m3" in f.summary
    assert "m1 vs m2" not in f.summary                       # 되는 쌍은 지목하지 않는다
    assert any("LRT" in d for d in f.detail)                 # 되는 쌍에는 방법을 적는다
    # 행 수가 다르면 몇 행 차이인지 — 480 vs 478 과 480 vs 412 는 다른 이야기다
    assert any("68행 차이" in d for d in f.detail)
    gap = next(p["n_gap"] for p in f.numbers["pairs"] if p["pair"] == "m1 vs m3")
    assert gap["diff"] == 68 and 0.13 < gap["ratio"] < 0.15
    assert audit(models[:1]).verdict == "skipped"


def test_c34_different_row_counts_are_caution_not_blocked():
    """행 수가 다른 것은 '불가'가 아니라 '직접 비교 주의'다 (사용자 확정)."""
    from statop.modeling.compare import Model, compare_pair

    p = compare_pair(Model.parse("m1: age [n=100]"), Model.parse("m2: age [n=80]"))
    assert p["comparable"] == "주의" and p["allowed"]        # 쓸 수 있는 길이 있다


def test_prep_and_compare_cli(prep_sets):
    from typer.testing import CliRunner

    from statop.cli import app
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(prep_sets["sets"]["train"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    record(session, _pspec(prep_sets["sets"], model_family="distance"))

    r = CliRunner().invoke(app, ["model", "prep", "--session", session])
    assert r.exit_code == 0 and "MB-C10" in r.output and "age_years" in r.output

    r = CliRunner().invoke(app, ["model", "compare",
                                 "-m", "m1: age [n=100]", "-m", "m2: age [n=80]"])
    assert r.exit_code == 0 and "MB-C34" in r.output


# ──  평가 감사 (MB-C16~C20 · C22 · C23) ──────────────────
@pytest.fixture
def eval_sets(tmp_path, monkeypatch):
    """예측이 담긴 test — 순위는 맞지만 0.5 에서 양성을 하나도 못 잡는다."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(31)
    n = 400
    label = (rng.random(n) < 0.06).astype(int)          # 양성 6%
    signal = rng.normal(0, 1, n) + label * 1.8
    prob = (1 / (1 + np.exp(-signal))) * 0.4            # 전부 0.5 아래로 눌림
    df = pd.DataFrame({"sid": [f"S{i:04d}" for i in range(n)],
                       "pred_prob": prob.round(4), "label": label})
    p = tmp_path / "pred.csv"
    df.to_csv(p, index=False)
    return {"sets": {"test": str(p)}, "path": str(p), "df": df}


def _eval_session(eval_sets, confirm=True, **kw):
    """세션 + 구성 + (선택) pred_prob 을 probability 로 확정."""
    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(eval_sets["path"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    if confirm:
        doc = load_session(session)
        append_op(doc, "semantic_confirm", source=main_source(doc)["id"],
                  column="pred_prob", type="probability")
        save_session(doc)
    spec = ModelSpec(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                     label_column="label", positive_class="1",
                     score_column="pred_prob", sets=eval_sets["sets"], **kw)
    record(session, spec)
    return session, spec


def test_eval_needs_a_confirmed_probability_column(eval_sets):
    """[0,1] 이라고 다 확률이 아니다 — 확정 전에는 판정하지 않는다 (pass 아님)."""
    from statop.modeling.evaluate import run_all

    session, spec = _eval_session(eval_sets, confirm=False)
    out = run_all(spec, session)
    assert all(f.verdict == "skipped" for f in out[:5])
    assert "probability" in out[0].summary


def test_c16_shows_roc_and_pr_together_when_rare(eval_sets):
    """양성이 드물면 ROC 는 높게 나온다 — PR 과 기저율을 같이 봐야 한다."""
    from statop.modeling.evaluate import metric_pair

    session, spec = _eval_session(eval_sets)
    f = metric_pair(spec, session)
    assert f.verdict == "fail"
    assert f.numbers["roc_auc"] > f.numbers["pr_auc"]     # 갈린다
    assert f.numbers["base_rate"] < 0.2
    assert "PR-AUC" in " ".join(f.detail)


def test_c18_and_c20_report_the_assumed_threshold(eval_sets):
    """임계값이 없으면 0.5 를 가정하고 **가정이라고 적는다**."""
    from statop.modeling.evaluate import class_performance

    session, spec = _eval_session(eval_sets)
    c20, c18 = class_performance(spec, session)
    assert c20.id == "MB-C20" and c20.verdict == "fail"
    assert c20.numbers["assumed"] == 0.5
    assert c18.id == "MB-C18" and c18.verdict == "fail"   # 양성 재현율 0
    assert any("가정" in d for d in c18.detail)
    pos = next(r for r in c18.numbers["classes"] if r["n"] < 100)
    assert pos["recall"] == 0.0

    # 임계값을 기록하면 MB-C20 은 통과하고, 그 임계값으로 다시 본다
    session2, spec2 = _eval_session(eval_sets, threshold=0.05)
    c20b, c18b = class_performance(spec2, session2)
    assert c20b.verdict == "pass" and c18b.numbers["threshold"] == 0.05


def test_c19_calibration_skips_thin_bins(eval_sets):
    """2개짜리 구간이 100% 인 것은 잡음이지 보정 문제가 아니다."""
    from statop.modeling.evaluate import ECE_MIN_BIN, calibration

    session, spec = _eval_session(eval_sets)
    f = calibration(spec, session)
    assert 0 <= f.numbers["ece"] <= 1
    shown = [b for b in f.numbers["bins"] if b["n"] >= ECE_MIN_BIN]
    if shown:
        assert any("가장 벌어진" in d for d in f.detail)


def test_c22_fold_spread_reports_the_worst_fold(eval_sets):
    from statop.modeling.evaluate import fold_spread

    _, spec = _eval_session(eval_sets)
    assert fold_spread(spec).verdict == "skipped"          # 없으면 건너뛴다

    _, wide = _eval_session(eval_sets, fold_scores=[0.88, 0.85, 0.62, 0.90, 0.87])
    f = fold_spread(wide)
    assert f.verdict == "fail" and f.numbers["worst"] == 0.62
    _, tight = _eval_session(eval_sets, fold_scores=[0.84, 0.85, 0.86, 0.85, 0.84])
    assert fold_spread(tight).verdict == "pass"


def test_c23_counts_test_set_revisions(eval_sets):
    """같은 test 로 구성을 몇 번 고쳤는지만 센다 — 아는 만큼만 말한다."""
    from statop.modeling.evaluate import test_reuse

    session, spec = _eval_session(eval_sets)
    assert test_reuse(spec, session).verdict == "pass"

    record(session, spec)              # 같은 test 로 구성을 한 번 더 고친다
    f = test_reuse(spec, session)
    assert f.verdict == "fail" and f.numbers["revisions"] == 2
    assert any("세션에 남은" in d for d in f.detail)      # 한계를 밝힌다


def test_eval_cli_runs_after_type_confirmation(eval_sets):
    from typer.testing import CliRunner

    from statop.cli import app

    session, _ = _eval_session(eval_sets)
    r = CliRunner().invoke(app, ["model", "eval", "--session", session])
    assert r.exit_code == 0, r.output
    assert "MB-C16" in r.output and "MB-C18" in r.output


def test_c16_power_is_not_computed_from_the_observed_auc(eval_sets):
    """관측 효과로 구한 사후 검정력은 p 값을 다시 쓴 것일 뿐이다 — 기준값으로 잰다."""
    from statop.modeling.evaluate import POWER_REF_AUC, auc_power, metric_pair

    session, spec = _eval_session(eval_sets)
    f = metric_pair(spec, session)
    assert f.numbers["power_ref"] == POWER_REF_AUC
    # 같은 n 이면 관측 AUC 가 무엇이든 검정력은 같다 (기준값만 본다)
    assert f.numbers["power"] == auc_power(f.numbers["n_positive"],
                                           f.numbers["n_negative"])
    # 양성이 늘면 검정력도 는다 (단조)
    assert auc_power(16, 320) < auc_power(40, 800) <= 1.0
    assert auc_power(1, 10) == 0.0                 # 잴 수 없으면 0, 지어내지 않는다
    assert "검정력" in f.summary and str(f.numbers["n_positive"]) in f.summary


# ── · 지표 변경·재현성 (MB-C21 · C25~C27) ────────────
def _repro_session(eval_sets, **kw):
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(eval_sets["path"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    base = dict(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                label_column="label", sets=eval_sets["sets"])
    record(session, ModelSpec(**{**base, **kw}))
    return session, base


def test_c21_blocks_metric_change_without_a_reason(eval_sets):
    """지표를 바꾸면 이전 보고와 같은 축이 아니다 — 사유가 있어야 한다 (Gate, 내부 #10)."""
    from statop.modeling.repro import metric_change

    session, base = _repro_session(eval_sets, metric="ROC-AUC")
    first = ModelSpec(**{**base, "metric": "ROC-AUC"})
    assert metric_change(first, session).verdict == "pass"

    changed = ModelSpec(**{**base, "metric": "PR-AUC"})
    record(session, changed)
    f = metric_change(changed, session)
    assert f.verdict == "fail" and f.grade == "Gate"
    assert "ROC-AUC" in f.summary and "PR-AUC" in f.summary

    # 사유를 적으면 통과하고, 이전 지표를 함께 보고하라고 말한다
    with_reason = ModelSpec(**{**base, "metric": "PR-AUC",
                               "metric_change_reason": "불균형이라 PR 로 전환"})
    record(session, with_reason)
    ok = metric_change(with_reason, session)
    assert ok.verdict == "pass" and any("이전 지표" in d for d in ok.detail)


def test_c21_skipped_when_no_metric_recorded(eval_sets):
    from statop.modeling.repro import metric_change

    session, base = _repro_session(eval_sets)
    assert metric_change(ModelSpec(**base), session).verdict == "skipped"


def test_c25_seed_is_a_gate(eval_sets):
    from statop.modeling.repro import reproducibility

    session, base = _repro_session(eval_sets)
    c25 = reproducibility(ModelSpec(**base), session)[0]
    assert c25.id == "MB-C25" and c25.verdict == "fail" and c25.grade == "Gate"
    ok = reproducibility(ModelSpec(**{**base, "seed": 7}), session)[0]
    assert ok.verdict == "pass" and ok.numbers["seed"] == 7


def test_scope_is_what_evid_runs_not_what_the_user_trains():
    """STATOP 는 모델을 돌리지 않는다 — MLP 계획에도 **조언**은 한다 ().

    경계는 "GPU 냐"가 아니라 "STATOP 가 그것을 돌려야 하느냐"다. 설정·데이터만 보면
    되는 것은 모델 종류와 무관하게 판정하고, **학습 중에만 보이는 것**만 로그를
    받아야 하므로 등록만 해 둔다.
    """
    from statop.modeling.prep import family_of
    from statop.modeling.spec import checks, tiers

    ids = {c["id"] for c in checks()}
    assert "MB-C27" in ids                              # 설정을 읽는 데 GPU 는 필요 없다
    assert family_of("neural") is not None              # 전처리 권고도 마찬가지
    t1 = next(t for t in tiers() if t["id"] == "MB-M1")
    assert t1["v1"] == "full"                           # MLP 계획에 대한 조언은 v1
    # 학습곡선 로그가 있어야 판정되는 것만 등록으로 남는다
    # 학습 루프·학습곡선 안에서 일어나는 일은 학습하는 쪽에서 판단한다 ()
    assert not ({"MB-C30", "MB-C32", "MB-C33"} & ids)


def test_seed_script_does_not_invent_training_code(eval_sets, tmp_path):
    """seed 를 어디에 심는지만 적는다 — 학습 코드를 지어내면 틀린 코드를 주게 된다."""
    from statop.modeling.repro import seed_script

    session, base = _repro_session(eval_sets, seed=42, k=7)
    code = seed_script(ModelSpec(**{**base, "seed": 42, "k": 7}), session)
    assert "SEED = 42" in code and "np.random.seed(SEED)" in code
    assert "n_splits=7" in code
    assert "fit(" not in code and "model" not in code.lower().split("#")[0]
    compile(code, "seed.py", "exec")            # 그대로 돌아가는 파이썬이어야 한다

    # seed 가 없으면 예시값을 넣되 **예시라고 적는다**
    noseed = seed_script(ModelSpec(**base), session)
    assert "SEED = 0" in noseed and "예시" in noseed


def test_repro_cli_and_seed_file(eval_sets, tmp_path):
    from typer.testing import CliRunner

    from statop.cli import app

    session, _ = _repro_session(eval_sets, metric="ROC-AUC")
    r = CliRunner().invoke(app, ["model", "repro", "--session", session])
    assert r.exit_code == 1 and "MB-C25" in r.output      # seed 없음 → Gate

    out = tmp_path / "seed_x.py"
    r = CliRunner().invoke(app, ["model", "seed", "--session", session,
                                 "--out", str(out)])
    assert r.exit_code == 0 and out.exists()
    compile(out.read_text(encoding="utf-8"), str(out), "exec")


def test_families_cli_shows_all_three_states(prep_sets):
    """조건부를 '불필요'로 뭉뚱그리면 규칙표가 거짓말이 된다."""
    from typer.testing import CliRunner

    from statop.cli import app

    r = CliRunner().invoke(app, ["model", "families"])
    assert r.exit_code == 0
    assert "조건부" in r.output and "필요" in r.output and "불필요" in r.output
    line = next(ln for ln in r.output.splitlines() if "projection" in ln)
    assert "조건부" in line


# ──  모델특유 (MB-C28~C31, T0) ───────────────────────────
@pytest.fixture
def specific_sets(tmp_path, monkeypatch):
    """완전분리 1건 + 겹치는 변수 1쌍을 심은 자료."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(41)
    n = 300
    y = (rng.random(n) < 0.35).astype(int)
    a = rng.normal(0, 1, n)
    df = pd.DataFrame({"sid": [f"S{i:04d}" for i in range(n)],
                       "clean": rng.normal(0, 1, n).round(3),
                       "twin_a": a.round(3),
                       "twin_b": (a * 3 + rng.normal(0, 0.02, n)).round(3),
                       "splitter": (y * 50 + rng.normal(0, 0.5, n)).round(3),
                       "y": y})
    p = tmp_path / "spec.csv"
    df.to_csv(p, index=False)
    return {"sets": {"train": str(p)}, "df": df}


def _sspec(sets, **kw):
    base = dict(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                label_column="y", positive_class="1", sets=sets)
    return ModelSpec(**{**base, **kw})


def test_c28_finds_the_separating_variable_without_fitting(specific_sets):
    """적합하지 않고 값의 범위만 본다 — 어느 변수 때문인지 바로 지목한다."""
    from statop.modeling.specific import separation

    f = separation(_sspec(specific_sets["sets"], model_family="linear"))
    assert f.verdict == "fail"
    cols = [h["column"] for h in f.numbers["columns"]]
    assert cols == ["splitter"]                     # 겹치지 않는 것만
    assert f.numbers["columns"][0]["kind"] == "complete"
    # 계수를 적합하지 않는 계열은 대상이 아니다
    assert separation(_sspec(specific_sets["sets"],
                             model_family="tree")).verdict == "skipped"


def test_c28_says_different_things_per_family(specific_sets):
    """한 문장으로 뭉뚱그리면 벌점 계열에서 틀린 말이 된다 — 계열별로 가른다."""
    from statop.modeling.specific import separation

    plain = separation(_sspec(specific_sets["sets"], model_family="linear"))
    pen = separation(_sspec(specific_sets["sets"], model_family="penalized"))
    assert plain.verdict == pen.verdict == "fail"
    assert plain.numbers["penalized"] is False and pen.numbers["penalized"] is True
    # 정규화가 없을 때만 "발산" 을 말한다
    assert any("발산할 수 있습니다" in d for d in plain.detail)
    assert not any("발산할 수 있습니다" in d for d in pen.detail)
    assert any("규제" in d and "억제" in d for d in pen.detail)
    assert plain.action != pen.action


def test_c29_reuses_c07_and_names_the_pair(specific_sets):
    """판정은 C-07 을 그대로 부른다 — 규칙 하나, 임계 하나."""
    from statop.modeling.specific import VIF_LIMIT, collinearity

    f = collinearity(_sspec(specific_sets["sets"], model_family="linear"))
    assert f.verdict == "fail"
    bad = {c for c, v in f.numbers["vif"].items() if v >= VIF_LIMIT}
    assert bad == {"twin_a", "twin_b"}              # 겹치는 쌍만
    assert f.numbers["vif"]["clean"] < VIF_LIMIT


def test_c31_points_at_the_pair_not_the_ranking(specific_sets):
    """어느 변수가 중요한지가 아니라 어느 쌍이 서로를 가리는지를 지목한다 ."""
    from statop.modeling.specific import importance_stability

    sets = specific_sets["sets"]
    assert importance_stability(_sspec(sets)).verdict == "skipped"  # 보고 안 함
    f = importance_stability(_sspec(sets, importance="gini"))
    assert f.verdict == "fail" and f.grade == "Judg"
    pair = f.numbers["pairs"][0]
    assert {pair["a"], pair["b"]} == {"twin_a", "twin_b"} and pair["r"] > 0.99


@pytest.mark.parametrize(("how", "kind", "needle"), [
    ("gini", "impurity", "나뉘어 실립니다"),
    ("permutation", "permutation", "둘 다 낮게"),
    ("shap", "unknown", "어느 방식인지"),
])
def test_c31_splits_impurity_from_permutation(specific_sets, how, kind, needle):
    """상관이 높을 때 **어긋나는 방향이 서로 반대다** — 같은 조치를 주면 자기모순이 된다."""
    from statop.modeling.specific import importance_stability

    f = importance_stability(_sspec(specific_sets["sets"], importance=how))
    assert f.numbers["kind"] == kind
    assert any(needle in d for d in f.detail)
    # 이미 permutation 을 쓴 사람에게 "permutation 으로 재라"고 하지 않는다
    if kind == "permutation":
        assert "grouped" in f.action


def test_specific_cli_shows_grades_and_scope(specific_sets):
    """Diag ⚠ · Judg ⓘ 구별 + 학습 과정을 보지 않는다는 사실 표기."""
    from typer.testing import CliRunner

    from statop.cli import app
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(specific_sets["sets"]["train"])
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    record(session, _sspec(specific_sets["sets"], model_family="linear",
                           importance="gini"))

    r = CliRunner().invoke(app, ["model", "specific", "--session", session])
    assert r.exit_code == 0                      # 여기엔 Gate 가 없다
    assert "⚠" in r.output and "ⓘ" in r.output   # Diag 와 Judg 가 구별된다
    # **무엇을 보지 않는지**도 화면에 있어야 한다 — 없는 검사를 있다고 믿지 않게
    assert "학습 전 방향만" in r.output and "편향" in r.output


# ── · 트리아드 · B6 출력 ───────────────────────────
def test_triad_picks_the_imbalanced_row_from_the_rule_table(eval_sets):
    """같은 MB-Q01 이라도 균형이냐 불균형이냐에 따라 표의 다른 줄이 걸린다."""
    from statop.modeling.triad import pick, recommend

    session, spec = _eval_session(eval_sets, metric="ROC-AUC")
    f = recommend(spec)
    assert f.id == "MB-C24" and f.verdict == "fail"
    assert "불균형" in f.numbers["question"]        # 양성 6% → 불균형 줄
    assert f.numbers["goal"] == "PR-AUC"
    assert f.numbers["class_ratio"] > 1.5
    # 규칙표에 없는 조합은 지어내지 않는다
    assert pick("MB-Q99", False) is None


def test_triad_passes_when_the_reported_metric_is_the_goal(eval_sets):
    from statop.modeling.triad import recommend

    _, spec = _eval_session(eval_sets, metric="PR-AUC")
    assert recommend(spec).verdict == "pass"


def test_triad_without_a_recorded_metric_still_recommends(eval_sets):
    """무엇을 보고했는지 몰라도 무엇을 세울지는 말해 준다."""
    from statop.modeling.triad import recommend

    _, spec = _eval_session(eval_sets)
    f = recommend(spec)
    assert f.verdict == "fail" and f.numbers["reported"] is None
    assert any("Guardrail" in d for d in f.detail)


def test_b6_report_gathers_everything_and_reproduces(eval_sets, tmp_path):
    """감사를 나눠 돌고 나면 한눈에 볼 자리가 없다 — 한 장으로 모은다."""
    from statop.modeling.report import collect, to_json, to_markdown

    session, _ = _eval_session(eval_sets, metric="ROC-AUC", seed=7)
    rep = collect(session, key="sid")
    ids = {f.id for f in rep.findings}
    # 여덟 갈래가 전부 들어간다 (누수·비율·균형·전처리·평가·모델특유·재현성·트리아드)
    assert {"MB-C01", "MB-C06", "MB-C08", "MB-C10", "MB-C16",
            "MB-C28", "MB-C25", "MB-C24"} <= ids
    assert rep.triad and rep.triad["goal"] == "PR-AUC"

    md = to_markdown(rep)
    assert "## 권하는 3-metric" in md and "## 재현 명령" in md
    # **무엇을 보지 않는지**가 보고서에도 있어야 한다
    assert "학습 전 방향만" in md
    assert "S0000" not in md                     # 데이터 셀 미노출 (점진 노출)

    # 재현 명령은 구성에 적어 둔 값을 전부 되살린다 — 빠지면 다른 결과가 나온다
    assert "--metric ROC-AUC" in rep.snippet and "--seed 7" in rep.snippet
    assert "--label label" in rep.snippet and "statop model eval" in rep.snippet
    json.loads(to_json(rep))                     # 그대로 파싱되는 json


def test_b6_report_cli_writes_md_and_json(eval_sets, tmp_path):
    from typer.testing import CliRunner

    from statop.cli import app

    session, _ = _eval_session(eval_sets, metric="ROC-AUC")
    for ext in ("md", "json"):
        out = tmp_path / f"audit.{ext}"
        r = CliRunner().invoke(app, ["model", "report", "--session", session,
                                     "--out", str(out)])
        assert r.exit_code in (0, 1) and out.exists(), r.output
    json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))


def test_eval_says_what_to_do_when_the_score_column_is_not_in_main(eval_sets,
                                                                   tmp_path):
    """"확정하세요"만 말하면 막다른 길이 된다 — 예측이 세트 파일에만 있을 때."""
    import pandas as pd

    from statop.modeling.evaluate import probability_column
    from statop.modeling.spec import ModelSpec, record
    from statop.shell.screen import Screen

    main = tmp_path / "main_no_prob.csv"
    pd.DataFrame({"sid": ["S1", "S2"], "label": [0, 1]}).to_csv(main, index=False)
    sc = Screen()
    sc.open_path(str(main))
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    spec = ModelSpec(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                     label_column="label", score_column="pred_prob",
                     sets=eval_sets["sets"])
    record(session, spec)
    col, why = probability_column(spec, session)
    assert col is None and "분석 대상 파일에 없어" in why


# ── 행 키는 이미 확정한 것을 쓴다 ( 사용성) ──────────────
def _session_with_id(tmp_path, monkeypatch, path, id_cols=("pid",)):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    from statop.session.core import (append_op, new_session, register_source,
                                   save_session)

    doc = new_session()
    sid = register_source(doc, str(path))
    for c in id_cols:
        append_op(doc, "semantic_confirm", source=sid, column=c, type="id")
    return save_session(doc)


def test_the_row_key_comes_from_the_confirmed_identifier(tmp_path, monkeypatch, sets):
    """의미 타입에서 행 식별자를 이미 확정했다 — 감사 화면에서 또 칠 일이 아니다."""
    from statop.modeling.split_audit import key_from_session

    s = _session_with_id(tmp_path, monkeypatch, sets["train"])
    assert key_from_session(s) == "pid"


def test_two_identifiers_are_not_guessed(tmp_path, monkeypatch, sets):
    """둘이면 사람이 고른다 — 골라서 쓰면 틀린 짝으로 없는 손실을 만들어낸다."""
    from statop.modeling.split_audit import key_from_session

    s = _session_with_id(tmp_path, monkeypatch, sets["train"], ("pid", "score"))
    assert key_from_session(s) == ""


def test_the_screen_says_which_key_it_will_use(tmp_path, monkeypatch, sets):
    """비워 두고 눌렀을 때 조용히 건너뛰면 검사한 줄 안다 — 무엇으로 맞추는지 적는다."""
    from statop.modeling.spec import ModelSpec, record
    from statop.shell.screen import Screen

    s = _session_with_id(tmp_path, monkeypatch, sets["train"])
    record(s, _spec(sets))
    sc = Screen()
    sc.session_file = s
    assert sc.open_model()
    assert any("pid" in n for n in sc.mb_notes), sc.mb_notes
    assert sc.model_key("") == "pid"
    assert sc.model_key("  other ") == "other"     # 친 것이 우선이다
