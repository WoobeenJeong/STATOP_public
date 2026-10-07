"""/: 사용자 문장은 전부 messages/*.yaml — 코드에 한국어 하드코딩 금지."""

import ast
import re
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from statop.cli import app

SRC = Path(__file__).parent.parent / "src" / "statop"
HANGUL = re.compile(r"[가-힣]")


def _docstring_positions(tree):
    spots = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                spots.add(id(body[0].value))
    return spots


# 규칙 DB(scores.yaml·tests.yaml …)는 한국어로 쓰여 있다. 그것을 **매칭하는 어휘**는
# 사용자에게 보이는 문장이 아니다. 파일이나 함수 통째로 빼면 그 안의 진짜 출력 문구까지
# 숨으므로, 그 줄에 표식을 단 경우만 예외로 둔다.
RULE_VOCAB_MARK = "# rule-vocab"


def _marked_lines(path) -> set[int]:  # noqa: ANN001
    return {i for i, line in enumerate(path.read_text().splitlines(), 1)
            if RULE_VOCAB_MARK in line}


def test_no_hardcoded_korean_strings():
    """docstring(=--help 텍스트, v1 한국어 고정)과 typer.Option help= 제외한
    모든 문자열 상수에 한국어가 없어야 한다 — 출력·에러는 msg() 경유."""
    offenders = []
    for py in SRC.rglob("*.py"):
        if "messages" in py.parts:
            continue
        if py.name == "build.py":
            continue  # md 표의 '열 이름'을 키로 쓰는 변환기 — 사용자 문장이 아니라 문서 스키마
        if py.name == "qwen.py":
            continue  # LLM 프롬프트 템플릿 — 사용자 화면 문장이 아니라 모델에게 주는 지시문.
            #           한국어 답을 받으려면 지시도 한국어가 명확하다 (모델 단일 용도)
        tree = ast.parse(py.read_text())
        docs = _docstring_positions(tree)
        # 규칙 DB 는 한국어로 쓰여 있다. 그것을 **매칭하는 어휘**는 사용자 문장이 아니라
        # 규칙 스키마와 짝이 되는 검색어다. 파일 통째로 빼면 그 파일의 진짜 출력 문구까지
        # 숨으므로, 아래 상수 안쪽만 예외로 둔다
        marked = _marked_lines(py)
        helps = set()
        for node in ast.walk(tree):  # typer.Option/Argument(help=...) 는 --help 텍스트로 예외
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "help" and isinstance(kw.value, ast.Constant):
                        helps.add(id(kw.value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docs and id(node) not in helps
                    and node.lineno not in marked
                    and HANGUL.search(node.value)):
                offenders.append(f"{py.name}:{node.lineno} {node.value[:40]!r}")
    assert not offenders, "한국어 하드코딩 발견:\n" + "\n".join(offenders)


def test_ko_en_key_parity():
    ko = yaml.safe_load((SRC / "messages" / "ko.yaml").read_text())
    en = yaml.safe_load((SRC / "messages" / "en.yaml").read_text())
    assert set(ko) == set(en), f"키 불일치: {set(ko) ^ set(en)}"


def test_lang_en_output(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.setenv("STATOP_HOME", str(tmp_path_factory.mktemp("statop_home")))
    p = tmp_path / "s.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(p, index=False)
    r = CliRunner().invoke(app, ["--lang", "en", "columns", str(p)])
    assert r.exit_code == 0
    assert "Rows:" in r.output and not HANGUL.search(r.output.split("column ")[0].split("\n")[1])

    r_ko = CliRunner().invoke(app, ["--lang", "ko", "columns", str(p)])
    assert "행수:" in r_ko.output


def test_message_files_parse():
    """따옴표·콜론 때문에 yaml이 깨지면 전 기능이 죽는다 — 파싱 자체를 검사한다."""
    for lang in ("ko", "en"):
        data = yaml.safe_load((SRC / "messages" / f"{lang}.yaml").read_text())
        assert isinstance(data, dict) and len(data) > 50
        assert all(isinstance(v, str) for v in data.values())


def test_message_placeholders_match_between_languages():
    """{n}·{path} 같은 자리표시자가 ko/en에서 일치해야 한다 — 한쪽만 고치면 런타임에 터진다."""
    import re

    ko = yaml.safe_load((SRC / "messages" / "ko.yaml").read_text())
    en = yaml.safe_load((SRC / "messages" / "en.yaml").read_text())
    ph = lambda s: {m.split(":")[0] for m in re.findall(r"\{([^}]*)\}", s)}
    bad = [k for k in ko if ph(ko[k]) != ph(en[k])]
    assert not bad, f"자리표시자 불일치: {bad}"
