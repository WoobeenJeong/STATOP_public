"""S062 참조 무결성 검사 — 규칙이 서로를 올바르게 가리키는지."""

from statop.rules.validate import Issue, validate


def test_no_broken_references():
    rep = validate()
    assert rep.ok, "끊어진 참조:\n" + "\n".join(
        f"{i.where} → {i.detail}" for i in rep.issues)


def test_known_id_counts():
    rep = validate()
    assert rep.known["tests"] == 70   # +T-1201~1204
    assert rep.known["assumptions"] == 15
    assert rep.known["semantic_types"] == 15
    assert rep.known["scores"] == 112   # −SC-GEN 12종 ()
    assert rep.known["errors"] == 167
    assert rep.known["model_checks"] == 31          #  registry-models
    assert sum(rep.known.values()) == 502   # −SC-GEN 12종 ()


def test_validator_detects_broken_ref(monkeypatch):
    """음성 대조: 없는 ID를 가리키면 반드시 잡아야 한다."""
    import statop.rules.validate as V

    real = V.build.build_compat_rules

    def fake():
        path, items = real()
        items = [dict(x) for x in items]
        items[0]["fix"] = "존재하지 않는 T-999 로 교체"
        return path, items

    monkeypatch.setattr(V.build, "build_compat_rules", fake)
    rep = V.validate()
    assert not rep.ok
    assert any(i.detail == "T-999" and i.kind == "broken_ref" for i in rep.issues)


def test_rules_cli_build_and_check(tmp_path_factory, monkeypatch):
    from typer.testing import CliRunner

    from statop.cli import app

    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("h")))
    runner = CliRunner()

    r = runner.invoke(app, ["rules", "build"])
    assert r.exit_code == 0 and "13개 파일" in r.output

    r = runner.invoke(app, ["rules", "check"])
    assert r.exit_code == 0
    assert "yaml이 md와 일치합니다" in r.output
    assert "끊어진 참조 없음" in r.output
    assert "합 502" in r.output


def test_rules_check_detects_stale(tmp_path_factory, monkeypatch):
    """md를 고치고 재생성을 잊으면 check가 빨갛게 알린다."""
    from typer.testing import CliRunner

    from statop.cli import app
    from statop.rules.build import RULES_DIR, build_all

    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("h")))
    build_all()
    target = RULES_DIR / "semantic_types.yaml"
    original = target.read_text()
    target.write_text(original.replace("count", "COUNT_TAMPERED", 1))  # yaml만 손댄 상태
    try:
        r = CliRunner().invoke(app, ["rules", "check"])
        assert r.exit_code == 1
        assert "semantic_types.yaml" in r.output and "재생성이 필요합니다" in r.output
    finally:
        target.write_text(original)


def test_rules_version_is_content_hash(tmp_path_factory, monkeypatch):
    """S064: 규칙 DB 버전은 md 내용의 해시 — md가 바뀌면 버전도 바뀐다."""
    from statop.rules.build import SCHEMA_DIR, rules_version

    v1 = rules_version()
    assert len(v1) == 12

    target = SCHEMA_DIR / "registry-guardrails.md"
    original = target.read_text()
    try:
        target.write_text(original + "\n<!-- test -->\n")
        assert rules_version() != v1          # md 변경 → 버전 변경
    finally:
        target.write_text(original)
    assert rules_version() == v1               # 원복 → 같은 버전 (결정론적)


def test_session_records_rules_version(tmp_path_factory, monkeypatch):
    from statop.rules.build import rules_version
    from statop.session.core import new_session

    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("h")))
    doc = new_session()
    assert doc["rules_db_version"] == rules_version()  # 어느 규칙으로 판정했는지 추적


def test_check_separates_content_and_version_change():
    """S065: 내용 변경과 버전 헤더 변경을 구분해 보고한다 (어느 규칙이 바뀌었는지 가려지지 않게)."""
    from statop.rules.build import SCHEMA_DIR, build_all, check_all

    build_all()
    target = SCHEMA_DIR / "registry-guardrails.md"
    original = target.read_text()
    try:
        # 표가 아닌 줄만 추가 → 규칙 내용은 그대로, 버전만 바뀜
        target.write_text(original + "\n주석 한 줄\n")
        content, version = check_all()
        assert content == [] and len(version) == 13   # models.yaml 추가

        # 규칙 표의 셀을 고침 → 내용 변경으로 잡혀야 한다
        target.write_text(original.replace("조인 키 결측·타입 불일치·중복 키",
                                           "조인 키 결측·타입 불일치·중복 키·추가", 1))
        content, version = check_all()
        assert "guardrails.yaml" in content
    finally:
        target.write_text(original)
        build_all()
