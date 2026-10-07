"""A7 가설 (기계 기본 + Qwen 플러그) 회귀.

기계 가설은 세션 기록에서만 나온다 — 기록에 없는 것을 말하면 실패해야 한다.
Qwen 은 고정 템플릿 단발 질의이고, 사설망 밖으로는 기본 거부다.
"""

import json
import os

import numpy as np
import pandas as pd
import pytest

from statop.analyze.run import run_test
from statop.analyze.spec import Spec, record
from statop.hypothesis.mech import build_report
from statop.hypothesis.qwen import (QwenError, _host_is_private, _parse, ask,
                                  build_prompt, check_ready)


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STATOP_QWEN_URL", raising=False)
    rng = np.random.default_rng(7)
    n = 300
    comp = rng.dirichlet([4, 3, 2], size=n)
    df = pd.DataFrame({"arm": rng.choice(["control", "case"], n),
                       "frac_A": comp[:, 0], "frac_B": comp[:, 1],
                       "frac_C": comp[:, 2]})
    p = tmp_path / "d.csv"
    df.to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    doc = load_session(s)
    src = main_source(doc)
    for c in ("frac_A", "frac_B", "frac_C"):
        append_op(doc, "semantic_confirm", source=src["id"], column=c, type="proportion")
    append_op(doc, "semantic_confirm", source=src["id"], column="arm", type="label")
    save_session(doc)
    return s


def _clr_corr(session):
    """사용자 시나리오: CLR 변환된 두 성분의 상관을 실행해 둔다."""
    from typer.testing import CliRunner

    from statop.cli import app

    runner = CliRunner()
    r = runner.invoke(app, ["compat", "fix", "--session", session, "--op", "correlate",
                            "--cols", "frac_A,frac_B", "--rule", "S-R01",
                            "--eps", "1e-8", "--apply"])
    assert r.exit_code == 0
    record(session, Spec(question="Q-03", y="frac_A_clr", group="frac_B_clr",
                         n_tests=2))
    run_test(session, "T-302")
    return session


# ── 기계 가설 ────────────────────────────────────────────────
def test_hypothesis_requires_an_executed_test(session):
    record(session, Spec(question="Q-01", y="frac_A", group="arm"))
    with pytest.raises(ValueError, match="analyze run"):
        build_report(session)


def test_clr_correlation_scenario(session):
    """CLR 상관 — 1안/2안 + CLR 배수 금지 주의 + 보조지표 + 인과 주의."""
    _clr_corr(session)
    rep = build_report(session)

    assert len(rep.proposals) == 2
    assert "연관" in rep.proposals[0].statement
    assert "rho" in rep.proposals[0].statement          # 효과크기·CI 가 문장에
    assert rep.proposals[0].direction                    # 방향이 붙는다

    joined = " ".join(rep.cautions)
    assert "CLR" in joined and "배수" in joined          # 사용자가 예시로 든 주의
    assert "eps=1e-08" in joined
    assert "인과" in joined
    assert "0.025" in joined                             # 보정 α (2개 계획)

    comp = " ".join(rep.companions)
    assert "Pearson" in comp                             # ρ의 보조지표 해석
    assert "cosine" in comp


def test_difference_scenario_directions(session):
    record(session, Spec(question="Q-01", y="frac_A", group="arm"))
    run_test(session, "T-101")
    rep = build_report(session)
    assert "차이" in rep.proposals[0].statement
    assert any(g in (rep.proposals[0].direction or "") for g in ("case", "control"))
    assert any("rank-biserial" in c for c in rep.companions)   # g의 보조지표


def test_hypothesis_uses_last_matching_result(session):
    """같은 설계로 두 번 돌리면 마지막 실행이 근거가 된다."""
    record(session, Spec(question="Q-01", y="frac_A", group="arm"))
    run_test(session, "T-103")
    run_test(session, "T-101")
    rep = build_report(session)
    assert rep.basis["test"] == "T-101"
    assert any("Mann–Whitney" in c for c in rep.companions)    # 앞서 돌린 것은 보조로


# ── Qwen 플러그 ──────────────────────────────────────────────
def test_qwen_refuses_without_endpoint(session, monkeypatch):
    monkeypatch.delenv("STATOP_QWEN_URL", raising=False)
    ok, info = check_ready()
    assert not ok and "STATOP_QWEN_URL" in info
    with pytest.raises(QwenError):
        ask(session)


def test_qwen_refuses_public_addresses(monkeypatch):
    """외부 유출 방지 — 사설망 밖은 명시 허용 없이 거부한다."""
    assert _host_is_private("http://127.0.0.1:8001/v1")
    assert _host_is_private("http://10.2.3.4:8001/v1")
    assert not _host_is_private("http://api.example.com/v1")

    monkeypatch.setenv("STATOP_QWEN_URL", "http://api.example.com/v1")
    monkeypatch.delenv("STATOP_QWEN_ALLOW_REMOTE", raising=False)
    ok, info = check_ready()
    assert not ok and "거부" in info

    monkeypatch.setenv("STATOP_QWEN_ALLOW_REMOTE", "1")
    ok, _ = check_ready()
    assert ok


def test_prompt_contains_summary_not_raw_cells(session):
    """전송 내용에 원자료(셀 값)가 없어야 한다 — 요약·판정·기계 가설만."""
    _clr_corr(session)
    user, _ = build_prompt(session, "상관이 과대해 보임")
    assert "T-302" in user and "clr(frac_A)" in user
    # 프롬프트는 영문이다 (registry-prompts 0절) — 통계 용어가 한영 변환에서 흔들리지 않게
    assert "Guardrail findings" in user and "Not checked" in user
    assert "Propose three readings" in user
    assert "상관이 과대해 보임" in user
    # 데이터 셀이 새는 흔적이 없어야: 값 나열 패턴 (소수 5자리 연쇄) 이 없다
    import re

    assert not re.search(r"\d\.\d{5,},\s*\d\.\d{5,}", user)


def test_qwen_roundtrip_with_local_server(session, monkeypatch, tmp_path):
    """mock 서버로 왕복 — thinking 끔, 1안/2안 파싱, 전송 로그."""
    import http.server
    import socketserver
    import threading

    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            got.update(body)
            out = {"choices": [{"message": {"content": json.dumps({
                "proposals": [
                    {"stance": "optimal", "hypothesis": "s1", "test": "t1",
                     "limit": "l1"},
                    {"stance": "conservative", "hypothesis": "s2", "test": "t2",
                     "limit": "l2"},
                    {"stance": "broad", "hypothesis": "s3", "test": "t3",
                     "limit": "l3"}]})}}]}
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):  # noqa: ANN002
            pass

    _clr_corr(session)
    with socketserver.TCPServer(("127.0.0.1", 0), H) as srv:
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        monkeypatch.setenv("STATOP_QWEN_URL", f"http://127.0.0.1:{port}/v1")
        ans = ask(session, "의견")
        srv.shutdown()

    assert [p["hypothesis"] for p in ans.proposals] == ["s1", "s2", "s3"]
    assert [p["stance"] for p in ans.proposals] == ["optimal", "conservative", "broad"]
    assert got["chat_template_kwargs"]["enable_thinking"] is False   # 사고 모드 끔
    assert got["max_tokens"] <= 1000                                  # 무겁지 않게
    sent = open(ans.sent_log, encoding="utf-8").read()
    assert "T-302" in sent                                            # 나간 것이 로그에


def test_parse_survives_broken_output():
    assert _parse("아무 JSON 아님") == []
    # 코드펜스로 감싸 와도 꺼낸다. 빠진 줄은 **지어내지 않고 빈 문자열**로 둔다
    assert _parse('```json\n{"proposals": [{"stance":"optimal","hypothesis":"s"}]}\n```') \
        == [{"stance": "optimal", "hypothesis": "s", "test": "", "limit": ""}]
    # 같은 입장이 여러 번 와도 **입장마다 하나씩**만 남는다 (세 줄 × 세 입장)
    many = [{"stance": "optimal", "hypothesis": f"h{i}"} for i in range(5)]
    assert [p["hypothesis"] for p in _parse(json.dumps({"proposals": many}))] == ["h0"]
    # 알 수 없는 입장 이름은 버린다 — 지어내지 않는다
    assert _parse(json.dumps({"proposals": [{"stance": "x", "hypothesis": "a"}]})) == []


# ── 리포트 (~157) ────────────────────────────────────────
def test_report_all_formats(session, tmp_path):
    from statop.report import collect, write

    _clr_corr(session)
    data = collect(session)
    assert data.spec and data.test_results and data.hypothesis
    assert data.derived and data.types["frac_A_clr"] == "clr"

    for fmt in ("md", "json", "html"):
        p = write(session, str(tmp_path / f"r.{fmt}"))
        text = p.read_text()
        assert "T-302" in text
        assert "CLR" in text                       # 주의사항이 리포트에도
    md = (tmp_path / "r.md").read_text()
    assert md.startswith("# STATOP 리포트")
    assert "부분 해시" in md                        # 상시 고지
    assert "clr(frac_A)" in md                     # 파생 수식이 재현 가능하게

    j = json.loads((tmp_path / "r.json").read_text())
    assert j["session_id"].startswith("s_")
    assert j["hypothesis"]["proposals"][0]["statement"]

    html = (tmp_path / "r.html").read_text()
    assert html.startswith("<!doctype html>") and "<table>" in html


def test_report_without_analysis_still_works(session, tmp_path):
    """분석 전 세션도 리포트는 된다 — 조작 이력·타입까지만 담고, 없는 건 없다."""
    from statop.report import collect, write

    data = collect(session)
    assert data.spec is None and data.hypothesis is None
    md = write(session, str(tmp_path / "early.md")).read_text()
    assert "조작 이력" in md and "가설" not in md


def test_report_guardrail_skips_continuous_x(session, tmp_path):
    """Q-03 의 연속 x 를 군으로 세면 '최소 군 n=1' 헛경고가 난다."""
    from statop.report import collect

    _clr_corr(session)
    g = collect(session).guardrail
    assert g is not None
    assert not any(f["check"] in ("tiny_group", "small_group")
                   for f in g["findings"])


def test_report_rejects_unknown_format(session, tmp_path):
    from statop.report import write

    with pytest.raises(ValueError, match="md|json|html"):
        write(session, str(tmp_path / "r.pdf"))


def test_session_option_defaults_to_most_recent(session, monkeypatch, tmp_path):
    """--session 생략 = 최근 작업 세션. $S 가 비어 다음 옵션이 먹히는 사고를 없앤다."""
    from typer.testing import CliRunner

    from statop.cli import app

    _clr_corr(session)
    runner = CliRunner()
    r = runner.invoke(app, ["hypothesis"])            # 세션 없이
    assert r.exit_code == 0
    assert "최근 작업 세션 자동 선택" in r.output
    assert "1안" in r.output

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "none"))
    r2 = runner.invoke(app, ["hypothesis"])
    # 명령어 글자로 잠그지 않는다 — 틀 안에서 줄이 접히면 테두리가 글자 사이에 낀다.
    # 확인할 것은 **무엇을 알렸는가**다
    from statop.messages import msg

    assert r2.exit_code != 0
    assert msg("session_none_active").split("—")[0].strip() in " ".join(r2.output.split())


# ── 넓어진 검정 종류에 문장이 따라붙는가 ────────────────────
@pytest.fixture
def session_reg(tmp_path, monkeypatch):
    """연속 y와 연속 x가 있는 표 — 회귀·추세·일치도 문장을 보기 위한 것."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STATOP_QWEN_URL", raising=False)
    rng = np.random.default_rng(5)
    n = 300
    age = rng.normal(60, 10, n)
    df = pd.DataFrame({"age": age,
                       "vaf": np.clip(0.2 + 0.01 * (age - 60)
                                      + rng.normal(0, 0.05, n), 0.001, 0.999),
                       "arm": rng.choice(["control", "case"], n)})
    p = tmp_path / "r.csv"
    df.to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    doc = load_session(s)
    src = main_source(doc)
    for col, t in (("age", "continuous"), ("vaf", "proportion"), ("arm", "label")):
        append_op(doc, "semantic_confirm", source=src["id"], column=col, type=t)
    save_session(doc)
    return s


def _run_and_report(session, question, y, group, test_id):
    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec, record
    from statop.hypothesis.mech import build_report

    record(session, Spec(question=question, y=y, group=group))
    run_test(session, test_id)
    return build_report(session)


def test_regression_is_not_phrased_as_a_group_difference(session_reg):
    """회귀를 '군 간 차이'로 쓰면 틀린 말이다 — Q-08은 변화로 서술해야 한다."""
    rep = _run_and_report(session_reg, "Q-08", "vaf", "age", "T-802")
    first = rep.proposals[0].statement
    assert "군 간" not in first
    assert "변한다" in first or "유의하지 않다" in first
    assert rep.proposals[1].direction and "클수록" in rep.proposals[1].direction


def test_raw_unit_effect_does_not_claim_a_magnitude_band(session_reg):
    """slope 는 대·중·소 기준이 없다 — 빈 등급으로 '가  수준' 같은 문장이 나오면 안 된다."""
    rep = _run_and_report(session_reg, "Q-08", "vaf", "age", "T-802")
    interp = rep.proposals[0].interpretation
    assert "원단위" in interp
    for h in rep.proposals:
        assert "가  수준" not in h.interpretation and "  " not in h.statement


def test_ratio_effects_use_one_as_the_reference(session_reg):
    """OR·IRR·HR 은 1이 기준이다. 0과 비교하면 늘 '양의 방향'이 되어 틀린다."""
    from statop.hypothesis.mech import _direction_text
    from statop.analyze.spec import Spec

    spec = Spec(question="Q-08", y="vaf", group="age")
    below = {"effect": {"name": "HR (age)", "value": 0.6}, "n": {"rows": 100}}
    above = {"effect": {"name": "OR (age)", "value": 1.8}, "n": {"rows": 100}}
    assert _direction_text(spec, below)[0] == "negative"
    assert _direction_text(spec, above)[0] == "positive"


def test_agreement_question_gets_agreement_wording(session_reg):
    rep = _run_and_report(session_reg, "Q-06", "vaf", "age", "T-601")
    assert "일치" in rep.proposals[0].statement
    assert "치우침" in rep.proposals[1].interpretation or \
           "LoA" in rep.proposals[1].interpretation


def test_distribution_question_says_shape_not_location(session_reg):
    rep = _run_and_report(session_reg, "Q-07", "vaf", "arm", "T-701")
    assert "분포" in rep.proposals[0].statement
    assert "중앙값" in rep.proposals[1].interpretation


# ── 심슨의 역설이 가설 문장까지 바꿔야 한다 ─────────────────
@pytest.fixture
def session_simpson(tmp_path, monkeypatch):
    """각 site 안에서는 A가 높지만 전체로는 B가 높은 자료."""
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STATOP_QWEN_URL", raising=False)
    rng = np.random.default_rng(4)
    rows = []
    for site, (na, nb, ma, mb) in {"S1": (220, 30, 5.6, 5.0),
                                   "S2": (30, 220, 8.6, 8.0)}.items():
        rows += [{"site": site, "arm": "A", "y": v} for v in rng.normal(ma, 1, na)]
        rows += [{"site": site, "arm": "B", "y": v} for v in rng.normal(mb, 1, nb)]
    p = tmp_path / "s.csv"
    pd.DataFrame(rows).to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    doc = load_session(s)
    src = main_source(doc)
    for c, t in (("y", "continuous"), ("arm", "label"), ("site", "label")):
        append_op(doc, "semantic_confirm", source=src["id"], column=c, type=t)
    save_session(doc)
    return s


def test_hypothesis_does_not_assert_a_direction_that_every_stratum_reverses(session_simpson):
    """보고서에 그대로 옮겨 적힐 문장이다 — 전체 방향만 단언하면 틀린 말이 된다."""
    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec, record
    from statop.hypothesis.mech import build_report

    record(session_simpson, Spec(question="Q-01", y="y", group="arm", by="site"))
    run_test(session_simpson, "T-101")
    rep = build_report(session_simpson)

    p2 = rep.proposals[1].statement
    assert "전체로는" in p2 and "반대" in p2
    assert rep.cautions and "심슨" in rep.cautions[0]     # 주의사항 맨 앞
    assert "S1" in rep.cautions[0] and "S2" in rep.cautions[0]


def test_no_simpson_wording_when_strata_agree(session_simpson):
    """방향이 일치하면 경고를 달면 안 된다 — 늘 뜨는 경고는 읽히지 않는다."""
    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec, record
    from statop.hypothesis.mech import build_report

    record(session_simpson, Spec(question="Q-01", y="y", group="site", by="arm"))
    run_test(session_simpson, "T-101")
    rep = build_report(session_simpson)
    assert not any("심슨" in c for c in rep.cautions)
    assert "전체로는" not in rep.proposals[1].statement


def test_flip_detection_survives_the_session_roundtrip(session_simpson):
    """검정 실행 때 계산한 뒤집힘이 세션에 남아 가설에서 다시 읽혀야 한다."""
    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec, record
    from statop.hypothesis.mech import strata_flips
    from statop.session.core import load_session, replay

    record(session_simpson, Spec(question="Q-01", y="y", group="arm", by="site"))
    run_test(session_simpson, "T-101")
    saved = replay(load_session(session_simpson))["test_results"][-1]
    assert saved["by"] == "site"
    assert sorted(strata_flips(saved)) == ["S1", "S2"]


# ──  재작성 ·  재현 스니펫 ──────────────────────────
def _analyzed(session: str, *, exclude_key: str | None = None):
    from statop.analyze.points import exclude
    from statop.analyze.run import run_test
    from statop.analyze.spec import Spec, record

    record(session, Spec(question="Q-01", y="frac_A", group="arm", n_tests=3))
    if exclude_key:
        exclude(session, "sid", exclude_key, "장비 오류")
    return run_test(session, "T-101")


@pytest.fixture
def session_a5(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STATOP_QWEN_URL", raising=False)
    rng = np.random.default_rng(7)
    n = 150
    comp = rng.dirichlet([4, 3, 2], size=n)
    arm = np.array(["ctrl"] * 75 + ["treat"] * 75)
    comp[arm == "treat", 0] += 0.06
    comp = comp / comp.sum(axis=1, keepdims=True)
    p = tmp_path / "m.csv"
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)], "arm": arm,
                  "frac_A": comp[:, 0], "frac_B": comp[:, 1],
                  "frac_C": comp[:, 2]}).to_csv(p, index=False)

    from statop.session.core import append_op, load_session, main_source, save_session
    from statop.shell.screen import Screen

    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    s = str(sc.session_file)
    doc = load_session(s)
    src = main_source(doc)
    for c, t in (("sid", "id"), ("arm", "label"), ("frac_A", "proportion"),
                 ("frac_B", "proportion"), ("frac_C", "proportion")):
        append_op(doc, "semantic_confirm", source=src["id"], column=c, type=t)
    save_session(doc)
    return s


def test_rewrite_weaves_goal_support_and_guardrail(session_a5):
    from statop.hypothesis.rewrite import build

    _analyzed(session_a5, exclude_key="S001")
    r = build(session_a5)
    assert "보조 지표" in r.statement and "가드레일" in r.statement
    assert r.support and r.guardrail
    assert any("MR-G16" in g for g in r.guardrail)      # 조성이면 심플렉스가 걸린다
    assert any("MR-G14" in g for g in r.guardrail)      # 뺐으면 제외 비율이 걸린다


def test_snippet_starts_a_session_and_records_the_exclusion(session_a5):
    """주석으로만 적으면 이 스니펫을 돌린 사람은 다른 행 수로 다른 값을 얻는다."""
    from statop.hypothesis.rewrite import build

    _analyzed(session_a5, exclude_key="S001")
    snip = build(session_a5).snippet
    assert snip.splitlines()[1].startswith("statop session new --data")
    assert "statop exclude --key-column sid --key S001" in snip
    assert "statop analyze plan --question Q-01 --y frac_A --group arm" in snip
    assert "--n-tests 3" in snip
    assert "statop analyze run --test T-101" in snip
    for line in snip.splitlines():
        assert not line.startswith("statop open ")     # open 은 세션을 만들지 않는다


def test_snippet_reproduces_the_same_numbers(session_a5, tmp_path, monkeypatch):
    """스니펫의 존재 이유는 재현이다 — 값이 다르면 안 주느니만 못하다."""
    import subprocess

    from statop.hypothesis.rewrite import build

    original = _analyzed(session_a5, exclude_key="S001")
    script = tmp_path / "snippet.sh"
    script.write_text("set -e\n" + build(session_a5).snippet, encoding="utf-8")

    fresh = tmp_path / "home_b"
    env = {**os.environ, "STATOP_HOME": str(fresh)}
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]

    monkeypatch.setenv("STATOP_HOME", str(fresh))
    from statop.session.core import load_session, replay
    from statop.store import tmp_dir

    made = sorted(tmp_dir().glob("session_*.json"))
    assert made
    st = replay(load_session(str(made[-1])))
    got = st["test_results"][-1]
    assert got["statistic"] == pytest.approx(original.statistic, rel=1e-12)
    assert got["p"] == pytest.approx(original.p, rel=1e-12)
    assert [(e["key"], e["note"]) for e in st["excluded"]] == [("S001", "장비 오류")]


# ──  병기 선택 저장 ( 경계) ────────────────────────
def test_saved_choice_cannot_invent_a_relation(tmp_path):
    """관계 자체는 base 고정이다 — 새로 만들 수 있으면 무엇으로 재는지가 흔들린다."""
    from statop.analyze.metrics import save_choice

    store = tmp_path / "roles.json"
    with pytest.raises(ValueError) as e:
        save_choice("T-101", ["MR-S99"], [], path=store)
    assert "" in str(e.value)
    assert not store.exists()


def test_saved_choice_marks_what_to_report(session_a5, tmp_path):
    from statop.analyze.metrics import apply_choices, goal_key, save_choice, suggest

    _analyzed(session_a5)
    store = tmp_path / "roles.json"
    panel = suggest(session_a5)
    save_choice(goal_key(panel), ["MR-S15"], ["MR-G06"], "보고 기준", path=store)

    marked = apply_choices(suggest(session_a5), path=store)
    assert marked.support[0].id == "MR-S15" and marked.support[0].chosen
    assert marked.guardrail[0].id == "MR-G06" and marked.guardrail[0].chosen
    # 고르지 않은 것도 목록에서 사라지지 않는다 — 없앤 채 두면 놓친다
    assert len(marked.guardrail) > 1
