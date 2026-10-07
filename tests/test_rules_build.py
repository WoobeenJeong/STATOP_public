from pathlib import Path

import pytest
import yaml

from statop.rules.build import RULES_DIR, build_semantic_types


def test_build_semantic_types_roundtrip():
    path, items = build_semantic_types()
    assert path == RULES_DIR / "semantic_types.yaml"
    assert len(items) == 15
    ids = [i["id"] for i in items]
    assert ids == [f"S-T{n:02d}" for n in range(1, 16)]  # 누락·순서 뒤바뀜 없음
    # [0,1] 구분 4종이 모두 등록돼 있다 (DECISIONS )
    by_type = {i["id"]: i for i in items}
    assert "proportion" in by_type["S-T02"]["type"]
    assert by_type["S-T04"]["type"] == "probability"
    assert by_type["S-T14"]["type"] == "normalized score"
    assert by_type["S-T15"]["type"] == "expression index"
    # 컬럼명은 보조 신호로만 ()
    assert "보조" in by_type["S-T04"]["infer_basis"]

    loaded = yaml.safe_load(path.read_text())
    assert loaded == items  # 파일과 메모리 동일
    st01 = next(i for i in loaded if i["id"] == "S-T01")
    assert st01["type"] == "count"
    assert "이진 코드" in st01["trap"]  # 함정 문구 보존
    assert next(i for i in loaded if i["id"] == "S-T10")["trap"] is None  # "—" → None


def test_generated_file_marked_do_not_edit():
    path, _ = build_semantic_types()
    assert "수기 편집 금지" in path.read_text().splitlines()[0]


def test_rebuild_is_deterministic():
    p1, _ = build_semantic_types()
    first = p1.read_text()
    p2, _ = build_semantic_types()
    assert p2.read_text() == first  # 같은 md → 같은 yaml (diff 0)


def test_build_compat_rules():
    from statop.rules.build import build_compat_rules

    path, items = build_compat_rules()
    assert [i["id"] for i in items] == [f"S-R{n:02d}" for n in range(1, 15)]

    by_id = {i["id"]: i for i in items}
    # 판정 정규화: 빨강/노랑/회색(Gate) → red/yellow/gate
    assert by_id["S-R01"]["verdict"] == "red"     # fraction×fraction 상관
    assert by_id["S-R05"]["verdict"] == "yellow"
    assert by_id["S-R09"]["verdict"] == "gate"    # nominal 연속 처리 = 차단
    assert by_id["S-R10"]["verdict"] == "gate"
    # 원 표기 보존 (노랑 → Diagnostic 같은 부가 정보)
    assert "Diagnostic" in by_id["S-R05"]["verdict_raw"]
    # 모든 규칙에 배너 문구와 수정안이 있다 (S-R 관리 규칙)
    assert all(i["why"] and i["fix"] for i in items)
    assert yaml.safe_load(path.read_text()) == items


def test_unknown_verdict_fails_loudly(monkeypatch):
    """판정 열에 새 값이 생기면 조용히 통과하지 않는다."""
    import statop.rules.build as B
    from statop.rules.mdparse import Table

    fake = Table(section="9.2 연산 적합성", headers=[], rows=[{
        "ID": "S-RXX", "조합 (A × B, 연산)": "x", "판정": "보라",
        "왜 검증이 안 되는가 (배너 문구)": "w", "원클릭 수정": "f", "근거": "s"}])
    monkeypatch.setattr(B, "find_table", lambda *a, **k: fake)
    with pytest.raises(ValueError, match="알 수 없는 판정"):
        B.build_compat_rules()


def test_build_derive_functions():
    from statop.rules.build import build_derive_functions

    path, items = build_derive_functions()
    assert [i["id"] for i in items] == [f"F-{n:02d}" for n in range(1, 16)]

    by_id = {i["id"]: i for i in items}
    # scope 정규화: 행 단위 / 컬럼 스칼라 / 세트 / 그룹
    assert by_id["F-01"]["scope"] == "row"
    assert by_id["F-04"]["scope"] == "column_scalar"   # sum/mean/sd — UI에서 색 구분
    assert by_id["F-11"]["scope"] == "set"             # clr(set)
    assert by_id["F-14"]["scope"] == "group"           # delta(x, group)
    # 화이트리스트: 함수명이 쪼개져 들어간다
    assert "log(x+eps)" in by_id["F-01"]["functions"] and "log2" in by_id["F-01"]["functions"]
    # eps 규칙이 필요한 함수에 규칙이 붙어 있다 ( eps 차단의 원천)
    assert "추천 이하만 허용" in by_id["F-01"]["eps_rule"]
    assert by_id["F-01"]["result_type"] == "log-scale"
    assert yaml.safe_load(path.read_text()) == items


def test_unknown_scope_fails_loudly(monkeypatch):
    import statop.rules.build as B
    from statop.rules.mdparse import Table

    fake = Table(section="10. 파생 함수", headers=[], rows=[{
        "ID": "F-99", "함수/연산": "`x`", "형태": "우주 단위",
        "결과 의미 타입": "t", "eps 규칙": "—", "비고": "—"}])
    monkeypatch.setattr(B, "find_table", lambda *a, **k: fake)
    with pytest.raises(ValueError, match="알 수 없는 형태"):
        B.build_derive_functions()


def test_build_tests_questions_and_tests():
    from statop.rules.build import build_tests

    path, data = build_tests()
    q, t = data["questions"], data["tests"]
    assert [x["id"] for x in q] == [f"Q-{n:02d}" for n in range(1, 13)]  # 질문유형 12종
    assert len(t) == 70   # +T-1201~1204
    assert all(x["question"] in {y["id"] for y in q} for x in t)  # 미아 검정 없음

    by_id = {x["id"]: x for x in t}
    welch = by_id["T-101"]
    assert welch["name"] == "Welch t-test" and welch["question"] == "Q-01"
    # 3색 판정의 원천: 초록/회색 사유가 문장으로 있다
    assert "분산 다름" in welch["best_when"]
    assert "순위·범주" in welch["blocked_when"]
    # 절마다 다른 열 이름이 별칭으로 흡수됐는지 (2.10은 '방법', 2.8은 '모형')
    assert by_id["T-1001"]["name"].startswith("CLR")
    assert by_id["T-801"]["name"]
    assert yaml.safe_load(path.read_text()) == data


def test_duplicate_test_id_fails_loudly(monkeypatch):
    import statop.rules.build as B
    from statop.rules.mdparse import Table

    real_find = B.find_table
    rows = [{"ID": "T-999", "검정": "x"}, {"ID": "T-999", "검정": "y"}]
    fake = Table(section="2.1 Q-01 차이", headers=["ID", "검정"], rows=rows)
    monkeypatch.setattr(B, "parse_file", lambda *a, **k: [fake])
    monkeypatch.setattr(B, "find_table", lambda tables, sec: real_find(
        B.parse_file(B.SCHEMA_DIR / "registry-tests.md") if False else
        [Table(section="1. 질문 유형 (Q) — A1 선택지",
               headers=["ID", "질문 유형", "사용자 언어 예", "Prism 대응"],
               rows=[{"ID": "Q-01", "질문 유형": "차이", "사용자 언어 예": "-", "Prism 대응": "-"}])], sec))
    with pytest.raises(ValueError, match="중복"):
        B.build_tests()


def test_build_assumptions():
    from statop.rules.build import build_assumptions

    path, items = build_assumptions()
    assert [i["id"] for i in items] == [f"C-{n:02d}" for n in range(1, 16)]  # C-01~15
    by_id = {i["id"]: i for i in items}
    assert by_id["C-01"]["check"] == "정규성"
    assert "QQ plot" in by_id["C-01"]["plot"]          # A3가 그릴 plot
    assert "Welch" in by_id["C-02"]["on_violation"]     # 위배 시 대안 제시 (#4)
    assert all(i["on_violation"] for i in items)        # 위배 규칙은 전 항목 필수
    assert all(i["plot"] for i in items)                # plot/참조가 전 항목에 지정됨 (DECISIONS /02)
    # C-14는 타입을 재판정하지 않고 S-T 결과를 참조한다 (Single Source of Truth, )
    assert "S-T" in by_id["C-14"]["check"] or "S-T" in by_id["C-14"]["method"]
    assert "판단 실패" in by_id["C-06"]["on_violation"]  # p 정상·ε 이상 시 별도 처리 ()
    assert yaml.safe_load(path.read_text()) == items


def test_build_post_groups():
    from statop.rules.build import build_post

    path, items = build_post()
    kinds = {i["kind"] for i in items}
    assert kinds == {"effect_size", "posthoc", "correction", "interval"}
    assert len(items) == 19
    by_id = {i["id"]: i for i in items}
    assert "Cohen d" in by_id["P-201"]["name"]          # 효과크기 기본 동반
    assert by_id["P-221"]["kind"] == "correction"       # Holm = 다중검정 보정
    assert yaml.safe_load(path.read_text()) == items


def test_build_verdicts():
    from statop.rules.build import build_verdicts

    path, items = build_verdicts()
    assert [i["id"] for i in items] == [f"R-{n:02d}" for n in range(1, 17)]
    assert [i["priority"] for i in items] == list(range(1, 17))  # 위에서부터 우선순위

    by_id = {i["id"]: i for i in items}
    # 색↔검정 분해: 구분자가 "," 든 "/" 든 (R-01은 "초록 T-1101 / 노랑 T-121")
    assert by_id["R-01"]["verdicts"] == {"green": ["T-1101"], "yellow": ["T-121"]}
    assert by_id["R-04"]["verdicts"]["green"] == ["T-103/T-105"]   # 같은 색 안의 /는 유지
    assert by_id["R-06"]["verdicts"]["gray"] == ["T-102/T-121"]
    # 차단(Gate)은 정확히 2건 — 다중검정 미보정, 3-metric 미기입
    assert {i["id"] for i in items if "gate" in i["verdicts"]} == {"R-10", "R-15"}
    # 자동 이름 태그(3.6)가 판정에 붙어 있다
    assert by_id["R-03"]["short_tag"] == "outlier"
    assert yaml.safe_load(path.read_text()) == items


def test_unknown_verdict_color_fails_loudly(monkeypatch):
    import statop.rules.build as B
    from statop.rules.mdparse import Table

    fake = Table(section="5. 3색 판정 규칙", headers=[], rows=[{
        "ID": "R-99", "조건": "x", "판정": "보라 T-1", "대상": "-",
        "메시지 템플릿": "-", "short_tag": "-"}])
    monkeypatch.setattr(B, "find_table", lambda *a, **k: fake)
    with pytest.raises(ValueError, match="색 표기를 찾지 못함"):
        B.build_verdicts()


def test_build_guardrails():
    from statop.rules.build import build_guardrails

    path, d = build_guardrails()
    # 실행 순서는 7절 그대로: 손실 → SRM → 불균형 → 정의역
    assert d["execution_order"] == ["GR-03", "GR-02", "GR-04", "GR-01"]
    by_id = {g["id"]: g for g in d["guardrails"]}
    assert set(by_id) == {"GR-01", "GR-02", "GR-03", "GR-04"}

    # GR-01: 수학적 불가능값만 Gate, 나머지는 Diagnostic
    gr01 = by_id["GR-01"]
    gate_rows = [g for g in gr01["grades"] if g["tier"] == "gate"]
    assert len(gate_rows) == 1 and "불가능" in gate_rows[0]["situation"]
    # clip은 자동 적용 금지 (분포 왜곡 — 사용자 명시 선택만)
    assert {a["action"] for a in gr01["actions"] if not a["auto"]} == {"clip"}
    assert gr01["default_action"] == "flag"

    # GR-02 SRM: 기본 Gate, 임계 p<0.0005, 차원별 Bonferroni
    gr02 = by_id["GR-02"]
    assert gr02["tier"] == "gate"
    assert "0.0005" in gr02["threshold"]
    assert "Bonferroni" in gr02["dimensional"]

    # GR-03 손실은 완화 불가(override_floor=gate) — 편향적 손실은 항상 차단
    assert by_id["GR-03"]["override_floor"] == "gate"
    assert len(by_id["GR-03"]["checks"]) == 6 and len(by_id["GR-04"]["checks"]) == 5  # DL-09로 군별 손실률 추가
    assert yaml.safe_load(path.read_text()) == d


def test_guardrail_cause_trace_not_causal(monkeypatch):
    """: 실행 순서는 진단 순서 — 원인 '후보'와 반사실 확인, 미설명 분기가 있어야 한다."""
    from statop.rules.build import build_guardrails

    _, d = build_guardrails()
    gr02 = {g["id"]: g for g in d["guardrails"]}["GR-02"]
    assert "원인 후보" in gr02["cause_trace"]          # 인과 단정 금지
    assert "해소" in gr02["counterfactual"]            # 그 손실이 없었다면?
    assert "모집단 불균형" in gr02["unexplained_branch"]  # 손실로 설명 안 되는 경우
    # 원인 추적의 입력: 군별 손실률이 GR-03 검사에 있다
    gr03 = {g["id"]: g for g in d["guardrails"]}["GR-03"]
    assert any("군별 손실률" in c["check"] for c in gr03["checks"])


def test_build_scores():
    from statop.rules.build import build_scores

    path, d = build_scores()
    sc = d["scores"]
    assert len(sc) == 112   # +SC-DIST-18/19  −SC-GEN 12종 ()
    families = {x["family"] for x in sc}
    assert families == {"ERR", "CLS", "DIST", "DIV", "ENT", "INF", "BE", "NORM", "VAR", "CLN"}
    assert all(x["latex"] for x in sc)          # 전 점수에 수식/정의가 있다 (M3 렌더용)

    by_id = {x["id"]: x for x in sc}
    mae = by_id["SC-ERR-01"]
    assert mae["name"] == "MAE" and "MAE" in mae["latex"]
    # 3색 적합성: 입력 공간·분포에 대한 판정 조건
    assert mae["green"].startswith("ℝ") and mae["red"] == "순위·범주"
    assert by_id["SC-ERR-02"]["yellow"].startswith("중꼬리")   # RMSE는 outlier 지배

    # 미지정(회색)은 4번째 상태 — 빈칸을 "적합"으로 해석하지 않는다 ()
    assert [g["label"] for g in d["grades"]] == ["안됨", "별로", "문제없음", "미지정"]
    assert by_id["SC-ERR-01"]["coverage"] == "full" and by_id["SC-ERR-01"]["unspecified"] == []
    #  전에는 초록·빨강이 비어 partial 이었다 — 작성자 검토로 채워져 full 이 됐다
    sens = by_id["SC-CLS-01"]
    assert sens["coverage"] == "full" and sens["unspecified"] == []
    assert "임계값" in sens["green"]        # rule-vocab
    #  작성자 검토로 전건 해소 — 회색(판정 불가)이 하나도 남지 않았다
    assert sum(1 for x in sc if x["coverage"] != "full") == 0
    # 쓰기로 했으면 무엇을 함께 보고하나 — 12절에서 온다
    assert sum(1 for x in sc if x.get("recommend")) == 81
    # 근거는 정의·산술 수준이면 비운다 — 없는 근거를 있는 것처럼 보이게 하지 않는다
    assert sum(1 for x in sc if x.get("source")) == 45
    assert [a["axis"] for a in d["axes"]] == ["공간", "분포", "구조", "척도"]
    assert yaml.safe_load(path.read_text()) == d


def test_build_metric_roles():
    from statop.rules.build import build_metric_roles

    path, d = build_metric_roles()
    assert len(d["roles"]) == 3
    assert [r["role"].replace("*", "") for r in d["roles"]] == ["Goal", "Support", "Guardrail"]
    assert len(d["support_relations"]) == 18
    assert len(d["guardrail_relations"]) == 18
    assert len(d["triads"]) == 14

    # Support = 해석을 쉽게 하는 짝 (RMSE → MAE)
    s01 = d["support_relations"][0]
    assert s01["id"] == "MR-S01" and "RMSE" in s01["goal"] and "MAE" in s01["support"]
    assert "직관" in s01["why"]
    # Guardrail = trade-off 감시 (Sensitivity ↔ Specificity)
    g01 = d["guardrail_relations"][0]
    assert "Sensitivity" in g01["goal"] and "Specificity" in g01["guardrail"]
    assert g01["tradeoff"]
    # 트리아드: 상황별 Goal/Support/Guardrail 세트가 모두 채워져 있다
    assert all(t["goal"] and t["support"] and t["guardrail"] for t in d["triads"])
    assert yaml.safe_load(path.read_text()) == d


def test_build_errors():
    from statop.rules.build import build_errors

    path, d = build_errors()
    e = d["errors"]
    assert len(e) == 167
    assert [c["code"] for c in d["categories"]] == list("GDISNMHPEC")  # 확인 범주 10종
    assert {p["code"] for p in d["nan_policies"]} >= {"LW", "GW", "PW", "PR", "CW", "ML"}

    by_id = {x["id"]: x for x in e}
    # 헤더 없는 표에서도 검정 마커가 붙는다 (T-102는 헤더 없는 표)
    assert by_id["E-102-1"]["test"] == "T-102"
    assert by_id["E-101-1"]["test"] == "T-101" and by_id["E-101-1"]["nan_policy"] == "GW"
    assert by_id["E-101-1"]["categories"] == ["D", "N"]     # 분포·표본
    assert "T-103" in by_id["E-101-1"]["action"]            # 대응 검정 연결
    # 범용 오류는 검정에 매이지 않는다
    assert all(x["test"] is None for x in e if x["id"].startswith("E-X"))  # 범용은 검정에 안 매임
    assert "차이 없음" in by_id["E-X-1"]["error"]           # p>0.05 오해
    assert yaml.safe_load(path.read_text()) == d


def test_build_label_palette():
    from statop.rules.build import build_label_palette

    path, d = build_label_palette()
    a = d["anchors"]
    assert len(a) == 50
    assert all(len(x["color"]) == 7 and x["color"].startswith("#") for x in a)  # HEX 검증
    by_cat = {x["category"]: x for x in a}
    assert by_cat["liver"]["tcga"] == ["LIHC", "CHOL"]
    assert "hcc" in by_cat["liver"]["keywords"]
    # 매칭 규칙 순서가 우선순위 (TCGA → 최장 부분일치 → 축 우선 → 사용자 확인 → 미분류)
    assert d["match_rules"][0].startswith("TCGA")
    assert "미분류" in d["match_rules"][-1]
    # 정규화 규칙: 접미 제거 목록이 있다
    assert "carcinoma" in d["normalize"]["strip_suffixes"]
    # 키워드 충돌은 조용히 두지 않고 기록 (사용자 확인의 입력)
    assert {c["keyword"] for c in d["keyword_conflicts"]} == {"germ-cell"}
    assert set(d["keyword_conflicts"][0]["categories"]) == {"testis", "germ_cell"}
    assert yaml.safe_load(path.read_text()) == d

# ──  registry-models → models.yaml ────────────────────
def test_models_yaml_covers_every_mb_check():
    """v1 이 판정하는 체크가 하나도 빠지면 안 된다 — 빠진 체크는 '없는 위험'이 된다.

    MB-C34(모델 비교, )는 3.2 설정 절에 들어가 번호 순서가 아니다.
    """
    from statop.rules import build

    _, data = build.build_models()
    ids = [c["id"] for c in data["checks"]]
    # C30·C32·C33 은 학습 과정 안에서 일어난다 — 4.3/4.4(later)에 등록만 (·)
    assert sorted(ids) == [f"MB-C{i:02d}" for i in range(1, 35)
                           if i not in (30, 32, 33)]
    assert len(data["questions"]) == 8 and len(data["tiers"]) == 4
    assert all(c["grade"] and c["action"] for c in data["checks"])


def test_models_yaml_marks_v1_scope_not_symbols():
    """● ○ later 기호를 그대로 두면 코드가 기호를 읽게 된다."""
    from statop.rules import build

    _, data = build.build_models()
    assert {q["v1"] for q in data["questions"]} <= {"full", "partial", "later"}
    binary = next(q for q in data["questions"] if q["id"] == "MB-Q01")
    assert binary["v1"] == "full"
    later = [q for q in data["questions"] if q["v1"] == "later"]
    assert {q["id"] for q in later} >= {"MB-Q05", "MB-Q06", "MB-Q07"}
    # T2/T3 는 판정하지 않고 등록만 — 목록에서 사라지면 "빠뜨린 것"과 구별이 안 된다
    assert data["later"] and all(x["status"] == "later" for x in data["later"])
    # T1 은 2026-09-16 에 범위 밖으로 옮겼다 (GPU·딥러닝, debris/ 참조)
    assert {x["tier"] for x in data["later"]} == {"MB-M0", "MB-M1", "MB-M2", "MB-M3"}


def test_model_checks_are_grouped_by_the_module_b_stage():
    from statop.rules import build

    _, data = build.build_models()
    groups = {c["id"]: c["group"] for c in data["checks"]}
    assert groups["MB-C01"] == "data"          # B2 누수·중복
    assert groups["MB-C09"] == "config"        # B5 전처리
    assert groups["MB-C16"] == "evaluation"
    assert groups["MB-C25"] == "reproducibility"
    assert groups["MB-C28"] == "model_specific"
    assert next(c for c in data["checks"] if c["id"] == "MB-C28")["tier"] == "T0"


def test_validator_knows_model_ids():
    from statop.rules.validate import validate

    r = validate()
    assert r.known["model_checks"] == 31
    assert r.known["model_questions"] == 8 and r.known["model_tiers"] == 4
