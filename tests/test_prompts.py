"""S160· — 프롬프트는 md 가 갖고, 입력은 요약치뿐이다."""

import numpy as np
import pandas as pd
import pytest

from statop.hypothesis import inputs, prompts


def test_prompts_come_from_the_md_not_the_code():
    """문구를 고치려면 md 를 고친다 — 코드에 박아 두면 사용자가 못 읽는다 ."""
    assert "rule engine has already computed" in prompts.system()
    for fam in ("analysis", "modeling"):
        body, task = prompts.template(fam)
        assert body and task
        assert "optimal" in task and "conservative" in task and "broad" in task
        assert '"proposals"' in task              # 출력 형식이 지시문에 박혀 있다
    with pytest.raises(ValueError):
        prompts.template("nope")


def test_prompt_body_is_not_cut_by_its_own_headings():
    """입력 템플릿 안에도 `## …` 줄이 있다 — 정규식으로 자르면 두 동강 난다."""
    body, _ = prompts.template("modeling")
    assert "## Modelling plan" in body and "## Not checked" in body
    assert "{gates}" in body and "{not_checked}" in body


def test_missing_field_fails_loudly():
    """자리를 빠뜨린 채 보내면 모델이 빈칸을 지어낸다 — 그 전에 터져야 한다."""
    with pytest.raises(KeyError):
        prompts.fill("analysis", {"question": "Q-01"})


@pytest.fixture
def model_session(tmp_path, monkeypatch):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    from statop.modeling.spec import ModelSpec, record
    from statop.shell.screen import Screen

    rng = np.random.default_rng(11)
    n = 120
    secrets = [f"WXYZ{i:04d}" for i in range(n)]
    df = pd.DataFrame({"sid": secrets, "x": rng.normal(0, 1, n).round(3),
                       "y": (rng.random(n) < 0.2).astype(int)})
    p = tmp_path / "m.csv"
    df.to_csv(p, index=False)
    sc = Screen()
    sc.open_path(str(p))
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)
    record(session, ModelSpec(question="MB-Q01", tier="MB-M0", validation="kfold",
                              k=5, label_column="y", positive_class="1",
                              model_family="penalized", metric="ROC-AUC", seed=3,
                              sets={"train": str(p)}))
    return session, secrets


def test_ask_needs_no_typing_once_the_type_is_decided(model_session):
    """유형이 정해져 있으면 [ask] 클릭 하나로 프롬프트가 완성된다."""
    session, _ = model_session
    family, prompt = inputs.build(session)
    assert family == "modeling"
    assert "MB-Q01" in prompt and "ROC-AUC" in prompt
    # 안 채운 자리가 없다 — 출력 예시의 중괄호와 섞이지 않게 **이름 있는 자리**만 본다
    import re

    leftover = set(re.findall(r"\{([a-z_]+)\}", prompt)) & prompts.fields("modeling")
    assert not leftover, f"안 채운 자리 {sorted(leftover)}"


def test_prompt_never_carries_raw_cells(model_session):
    """요약치만 — 원자료가 나가면 무저장 원칙이 무너진다 (요구사항3절)."""
    session, secrets = model_session
    _, prompt = inputs.build(session)
    leaked = [s for s in secrets if s in prompt]
    assert not leaked, f"원자료 유출 {leaked[:3]}"


def test_prompt_is_english_even_though_the_screen_is_korean(model_session):
    """판정 문구는 영문판을 쓴다 — 통계 용어가 한영 변환에서 흔들리지 않게."""
    session, _ = model_session
    _, prompt = inputs.build(session)
    assert "the classes are imbalanced" in prompt or "imbalanced" in prompt
    assert "클래스가 치우쳐" not in prompt          # 한국어 판정 문구가 새지 않는다
    # 그런데 규칙표 자체는 한국어다 — 시스템 프롬프트가 그 사실을 알려 준다
    assert "Korean rule table" in prompts.system()


def test_prompt_states_what_was_not_checked(model_session):
    """못 본 것을 근거로 읽으면 안 된다 — 입력에 '보지 않은 것'이 들어간다 ."""
    session, _ = model_session
    _, prompt = inputs.build(session)
    assert "## Not checked" in prompt
    # 시스템 프롬프트가 못박는다 — 못 본 것은 통과가 아니다
    sys_text = " ".join(prompts.system().split())
    assert "are unknown, not passed" in sys_text


def test_three_stances_are_parsed_and_broken_output_is_not_invented():
    from statop.hypothesis.qwen import _parse

    good = ('{"proposals":['
            '{"stance":"broad","hypothesis":"h3","test":"t3","limit":"l3"},'
            '{"stance":"optimal","hypothesis":"h1","test":"t1","limit":"l1"},'
            '{"stance":"conservative","hypothesis":"h2","test":"t2","limit":"l2"}]}')
    got = _parse(good)
    assert [p["stance"] for p in got] == list(prompts.STANCES)   # 순서를 고정한다
    assert got[0]["hypothesis"] == "h1" and got[0]["limit"] == "l1"

    # 형식이 깨지면 빈 목록 — 화면이 원문을 그대로 보여준다
    assert _parse("모델이 그냥 줄글로 답했다") == []
    assert _parse('{"proposals":[{"stance":"nope","hypothesis":"x"}]}') == []


# ──  모델 올리기 → ask 활성화 ────────────────────────────
def test_load_reports_why_it_cannot_load(monkeypatch):
    """주소가 없으면 조용히 실패하지 않는다 — 무엇이 없는지 말한다."""
    from statop.hypothesis import qwen

    monkeypatch.delenv(qwen.ENV_URL, raising=False)
    r = qwen.load()
    assert r["stage"] == "no_endpoint" and r["warmed"] is False
    assert r["detail"]


def test_load_skips_the_warmup_when_already_up(monkeypatch):
    """이미 올라와 있으면 다시 부르지 않는다 — 괜히 기다리게 하지 않는다."""
    from statop.hypothesis import qwen

    monkeypatch.setattr(qwen, "probe", lambda timeout=3.0: {
        "stage": "ready", "model": "qwen3", "loaded": True, "detail": "",
        "url": "http://x", "latency_ms": 5})
    r = qwen.load()
    assert r["warmed"] is True and r["took_ms"] == 0
    assert "qwen3" in r["detail"]


def test_ask_cli_prints_three_stances(monkeypatch, tmp_path):
    """입장마다 세 줄 — 화면이 제목을 지어내지 않고 메시지에서 가져온다."""
    from typer.testing import CliRunner

    from statop.cli import app
    from statop.hypothesis import qwen

    answer = qwen.QwenAnswer(
        proposals=[{"stance": s, "hypothesis": f"h-{s}", "test": f"t-{s}",
                    "limit": f"l-{s}"} for s in prompts.STANCES],
        raw="{}", model="qwen3", sent_log=str(tmp_path / "log.jsonl"))
    monkeypatch.setattr("statop.hypothesis.qwen.ask", lambda *a, **k: answer)

    r = CliRunner().invoke(app, ["ask", "--session", str(tmp_path / "s.json")])
    assert r.exit_code == 0, r.output
    for s in prompts.STANCES:
        assert f"h-{s}" in r.output and f"t-{s}" in r.output and f"l-{s}" in r.output
    assert "최적" in r.output and "보수적" in r.output and "넓게" in r.output


def test_ask_cli_shows_raw_when_the_format_breaks(monkeypatch, tmp_path):
    """형식이 깨지면 지어내지 않고 원문을 보여준다."""
    from typer.testing import CliRunner

    from statop.cli import app
    from statop.hypothesis import qwen

    monkeypatch.setattr("statop.hypothesis.qwen.ask", lambda *a, **k: qwen.QwenAnswer(
        proposals=[], raw="모델이 줄글로 답했다", model="qwen3",
        sent_log=str(tmp_path / "l.jsonl")))
    r = CliRunner().invoke(app, ["ask", "--session", str(tmp_path / "s.json")])
    assert r.exit_code == 0 and "모델이 줄글로 답했다" in r.output
