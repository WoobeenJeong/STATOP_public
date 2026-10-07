"""registry-*.md → rules/*.yaml 변환기 . yaml은 산출물이며 수기 편집 금지.

각 변환 함수는 md 표의 열 이름을 yaml 필드로 매핑한다. 열 이름이 바뀌면 여기서
KeyError로 시끄럽게 실패한다 — md와 코드가 조용히 갈라지지 않게 하기 위함.
"""

import re
from pathlib import Path

import yaml

from statop.rules.mdparse import find_table, parse_file, parse_tables

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schema"
RULES_DIR = Path(__file__).resolve().parents[3] / "rules"

_HEADER = ("# 자동 생성 파일 — schema/{src} 에서 생성됨. 수기 편집 금지 (statop rules build).\n"
           "# rules_version: {version}\n")


def _strip_emphasis(obj):
    """모든 문자열에서 md 강조(`**`)를 벗긴다.

    md 는 **사람이 읽는 사양서**라 강조가 필요하고, yaml 값은 **화면에 그대로 나가는
    문장**이라 필요 없다. 빌더마다 챙기면 한 군데씩 빠지므로(실제로 빠졌다) 내보내는
    자리에서 한 번에 처리한다. 수식 필드(latex·expr 등)에는 `**` 가 쓰이지 않는다 —
    LaTeX 는 `^`, 파생 수식은 `pow` 를 쓴다.
    """
    if isinstance(obj, str):
        return obj.replace("**", "")
    if isinstance(obj, list):
        return [_strip_emphasis(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_emphasis(v) for k, v in obj.items()}
    return obj


def _dump(items, out_name: str, src: str) -> tuple[Path, object]:
    """yaml 을 쓰고 **쓴 것과 같은 값**을 함께 돌려준다.

    강조를 벗긴 뒤 쓰므로, 반환값도 벗긴 것이어야 파일과 메모리가 갈라지지 않는다
    (갈라져서 롤트립 테스트가 잡아냈다).
    """
    items = _strip_emphasis(items)
    RULES_DIR.mkdir(exist_ok=True)
    path = RULES_DIR / out_name
    path.write_text(_HEADER.format(src=src, version=rules_version()) + yaml.safe_dump(
        items, allow_unicode=True, sort_keys=False, width=100))
    return path, items


# 전체 재생성 대상 — 이름 → 빌더. 새 변환기를 추가하면 여기에 등록한다.
def all_builders() -> dict:
    return {
        "semantic_types.yaml": build_semantic_types,
        "compat_rules.yaml": build_compat_rules,
        "derive_functions.yaml": build_derive_functions,
        "models.yaml": build_models,
        "tests.yaml": build_tests,
        "assumptions.yaml": build_assumptions,
        "post.yaml": build_post,
        "verdicts.yaml": build_verdicts,
        "guardrails.yaml": build_guardrails,
        "scores.yaml": build_scores,
        "metric_roles.yaml": build_metric_roles,
        "errors.yaml": build_errors,
        "label_palette.yaml": build_label_palette,
    }


def rules_version() -> str:
    """규칙 DB 버전 해시 : schema/registry-*.md + design-tokens.md 내용의 sha256 앞 12자리.

    출력물(리포트·세션 로그)에 기록해 "어느 규칙으로 판정했는가"를 나중에 추적한다.
    md가 단일 진실이므로 md를 해싱한다 — yaml은 산출물이라 재생성하면 같아진다.
    """
    import hashlib

    h = hashlib.sha256()
    for path in sorted(SCHEMA_DIR.glob("*.md")):
        if path.name.startswith(("registry-", "design-tokens")):
            h.update(path.name.encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:12]


def build_all() -> dict[str, Path]:
    """모든 yaml을 재생성한다."""
    return {name: fn()[0] for name, fn in all_builders().items()}


def _strip_header(text: str | None) -> str | None:
    """버전 헤더를 제외한 본문만 — 버전은 전역이라 md 어디를 고쳐도 모든 파일이 바뀐다."""
    if text is None:
        return None
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))


def check_all() -> tuple[list[str], list[str]]:
    """현재 yaml이 md와 일치하는지 확인한다 → (내용이 바뀐 파일, 버전만 바뀐 파일).

    md를 고치고 재생성을 잊으면 규칙 엔진이 낡은 규칙으로 판정한다 — 그것을 막는 검사.
    어느 규칙이 실제로 바뀌었는지 가려지지 않도록 버전 헤더 변경과 본문 변경을 나눈다.
    """
    content_stale, version_stale = [], []
    for name, fn in all_builders().items():
        path = RULES_DIR / name
        before = path.read_text() if path.exists() else None
        fn()  # 재생성 (내용이 같으면 동일 파일)
        after = path.read_text()
        if after != before:
            if _strip_header(after) != _strip_header(before):
                content_stale.append(name)
            else:
                version_stale.append(name)
            if before is not None:
                path.write_text(before)  # check는 확인만 — 원래 내용 복구
    return content_stale, version_stale


def _clean(v: str) -> str | None:
    """빈 셀·플레이스홀더(—)를 None으로 정규화한다."""
    return None if v.strip() in ("", "—", "-") else v.strip()


def build_compat_rules() -> tuple[Path, list[dict]]:
    """S-R01~14 (registry-tests 9.2) → rules/compat_rules.yaml

    verdict(빨강/노랑/회색)를 기계 값으로 정규화한다. 9.3 판정 순서가 이 값을 쓴다.
    미래 확장(severity_axes 등)은 필드 추가로 흡수 — 로더는 미지 필드를 보존한다.
    """
    src = "registry-tests.md"
    t = find_table(parse_file(SCHEMA_DIR / src), "9.2 연산 적합성")
    verdict_map = {"빨강": "red", "노랑": "yellow", "회색": "gate", "회색(Gate)": "gate"}
    items = []
    for r in t.rows:
        raw = r["판정"].strip()
        verdict = next((v for k, v in verdict_map.items() if raw.startswith(k)), None)
        if verdict is None:
            raise ValueError(f"{r['ID']}: 알 수 없는 판정 값 {raw!r}")
        items.append({
            "id": r["ID"],
            "combination": r["조합 (A × B, 연산)"],
            "verdict": verdict,
            "verdict_raw": raw,          # "노랑 → Diagnostic" 같은 부가 표기 보존
            "why": r["왜 검증이 안 되는가 (배너 문구)"],
            "fix": _clean(r["원클릭 수정"]),
            "sources": _clean(r["근거"]),
        })
    return _dump(items, "compat_rules.yaml", src)


# T 표는 절마다 열 구성이 다르다(검정/방법/모형, best_when (초록) 등). 별칭으로 흡수한다.
_T_ALIASES = {
    "name": ("검정", "검정/지표", "방법", "모형"),
    "design": ("design", "결과 척도"),
    "assumptions": ("assumptions",),
    "best_when": ("best_when (초록)", "best_when"),
    "blocked_when": ("blocked_when (회색)", "blocked_when"),
    "caution": ("caution (노랑)", "caution"),
    "alternatives": ("alternatives",),
    "post": ("post",),
    "effect_size": ("effect_size",),
    "sources": ("sources", "비고"),
}


def build_tests() -> tuple[Path, dict]:
    """Q-01~11 (1절) + T 검정 전체 (2절) → rules/tests.yaml

    A2 3색 후보 판정의 원천. 각 검정의 best_when(초록)/blocked_when(회색)/caution(노랑)이
    등급 사유가 되고, question(Q-ID)으로 A1 선택과 연결된다.
    """
    src = "registry-tests.md"
    tables = parse_file(SCHEMA_DIR / src)

    q_table = find_table(tables, "1. 질문 유형")
    questions = [
        {"id": r["ID"], "question": r["질문 유형"], "user_words": _clean(r["사용자 언어 예"]),
         "prism": _clean(r["Prism 대응"])}
        for r in q_table.rows
    ]
    q_ids = {q["id"] for q in questions}

    tests = []
    for t in tables:
        if not (t.rows and t.rows[0].get("ID", "").startswith("T-")):
            continue
        qid = t.section.split()[1]  # "2.1 Q-01 차이" → "Q-01"
        if qid not in q_ids:
            raise ValueError(f"섹션 {t.section!r}에서 알 수 없는 질문 유형 {qid!r}")
        for r in t.rows:
            item = {"id": r["ID"], "question": qid, "section": t.section}
            for field, aliases in _T_ALIASES.items():
                col = next((a for a in aliases if a in r), None)
                item[field] = _clean(r[col]) if col else None
            tests.append(item)

    dup = [i for i in {t["id"] for t in tests} if sum(x["id"] == i for x in tests) > 1]
    if dup:
        raise ValueError(f"검정 ID 중복: {sorted(dup)}")
    return _dump({"questions": questions, "tests": tests}, "tests.yaml", src)


def build_assumptions() -> tuple[Path, list[dict]]:
    """C-01~15 (registry-tests 3절) → rules/assumptions.yaml

    A3 가정 진단의 원천: 검정마다 어떤 가정을 확인해야 하고, 어떤 plot·방법으로 보며,
    위배 시 무엇을 권고하는지(#4 "어떤 데이터를 더 모아야 하는지" 포함).
    """
    src = "registry-tests.md"
    t = find_table(parse_file(SCHEMA_DIR / src), "3. 사전검사")
    items = [
        {
            "id": r["ID"],
            "check": r["검사"],
            "method": _clean(r["방법 (n에 따라)"]),
            "plot": _clean(r["plot"]),
            "linked_tests": _clean(r["연결 검정"]),
            "on_violation": _clean(r['위배 시 규칙 (#4 "어떤 데이터를 더")']),
        }
        for r in t.rows
    ]
    return _dump(items, "assumptions.yaml", src)


def build_post() -> tuple[Path, list[dict]]:
    """P-2xx (registry-tests 4절) → rules/post.yaml

    검정 뒤에 기본 동반되는 것들: 효과크기(4.1) · 사후검정(4.2) · 다중검정 보정(4.3) ·
    구간추정/재표본(4.4). "점추정만 보고"를 막는 내부 사례 #7의 근거.
    """
    src = "registry-tests.md"
    tables = parse_file(SCHEMA_DIR / src)
    groups = {
        "effect_size": "4.1 효과크기",
        "posthoc": "4.2 다중비교 사후검정",
        "correction": "4.3 다중검정 보정",
        "interval": "4.4 구간추정",
    }
    items = []
    for kind, section in groups.items():
        for r in find_table(tables, section).rows:
            items.append({
                "id": r["ID"],
                "kind": kind,
                "name": _clean(r.get("항목") or r.get("방법")),
                "applies_to": _clean(r["적용"]),
                "note": _clean(r.get("비고", "")),
            })
    dup = [i for i in {x["id"] for x in items} if sum(y["id"] == i for y in items) > 1]
    if dup:
        raise ValueError(f"P 항목 ID 중복: {sorted(dup)}")
    return _dump(items, "post.yaml", src)


def build_verdicts() -> tuple[Path, list[dict]]:
    """R-01~16 (registry-tests 5절) → rules/verdicts.yaml

    A2 3색 판정 엔진의 조건식. 위에서부터 우선순위. 조건은 C 결과와 A1 입력만 사용(LLM 없음).
    판정 열은 "초록 T-103/T-105, 노랑 T-101"처럼 색↔검정이 묶여 있어 색별로 분해한다.
    임계값(n<15 등)은 **기본값**이며 절대 기준이 아니다 (DECISIONS ) — 엔진은 이 값을
    출발점으로 쓰되 판정 문구는 데이터 구성(군 간 n 격차·분산 이질성)을 함께 말해야 한다.
    """
    src = "registry-tests.md"
    t = find_table(parse_file(SCHEMA_DIR / src), "5. 3색 판정 규칙")
    color_map = {"초록": "green", "노랑": "yellow", "회색": "gray",
                 "Gate": "gate", "Diagnostic": "diagnostic", "red": "red"}
    items = []
    for order, r in enumerate(t.rows, start=1):
        raw = r["판정"]
        # 구분자가 ","와 "/"로 섞여 있으므로(예: "초록 T-1101 / 노랑 T-121")
        # 색 키워드가 나타나는 위치로 잘라낸다.
        marks = sorted(
            (m.start(), m.group()) for k in color_map
            for m in re.finditer(re.escape(k), raw)
        )
        if not marks:
            raise ValueError(f"{r['ID']}: 판정에서 색 표기를 찾지 못함 {raw!r}")
        targets: dict[str, list[str]] = {}
        for idx, (pos, key) in enumerate(marks):
            end = marks[idx + 1][0] if idx + 1 < len(marks) else len(raw)
            body = raw[pos + len(key) : end].strip(" :,/")
            targets.setdefault(color_map[key], []).append(body)
        items.append({
            "id": r["ID"],
            "priority": order,                      # 위에서부터 우선순위 (5절 서문)
            "condition": r["조건"],
            "verdicts": {k: [v for v in vs if v] for k, vs in targets.items()},
            "verdict_raw": raw,
            "applies_to": _clean(r["대상"]),
            "message": _clean(r["메시지 템플릿"]),
            "short_tag": _clean(r["short_tag"]),     # 3.6 자동 이름 태그
        })
    return _dump(items, "verdicts.yaml", src)


def build_guardrails() -> tuple[Path, dict]:
    """GR-01~04 (registry-guardrails) → rules/guardrails.yaml

    검정·점수 앞단에서 자동 실행되는 무결성 검사. 각 GR의 등급(gate/diagnostic)과
    override_floor(완화 가능 하한)를 기계 값으로 고정한다 — 수학적 불가능값·편향적 손실·
    SRM 원판정은 override로도 완화되지 않는다(7절).

    md가 절마다 표 구성이 달라(등급표·액션표·필드표·검사표) 절별로 매핑한다.
    실행 순서(7절)는 코드가 아니라 여기 order 필드로 고정한다.
    """
    src = "registry-guardrails.md"
    tables = parse_file(SCHEMA_DIR / src)
    tier_map = {"Gate(차단)": "gate", "Gate": "gate", "Diagnostic(경고)": "diagnostic",
                "Diagnostic": "diagnostic"}

    def _tier(v: str) -> str:
        key = v.replace("**", "").strip()
        for k, t in tier_map.items():
            if key.startswith(k):
                return t
        raise ValueError(f"알 수 없는 등급 표기: {v!r}")

    gr01 = {
        "id": "GR-01", "name": "out_of_range", "order": 4,
        "grades": [
            {"situation": r["상황"], "tier": _tier(r["등급"]), "example": r["예"]}
            for r in find_table(tables, "2.2 등급").rows
        ],
        "actions": [
            {"action": r["액션"], "desc": r["설명"],
             "auto": not r["설명"].startswith("경계로")}  # clip은 자동 적용 금지(2.4 단서)
            for r in find_table(tables, "2.4 out-of-range 액션").rows
        ],
        "default_action": "flag",
        "override_floor": "diagnostic",  # 수학적 불가능값(Gate)은 완화 불가
    }

    fields = {r["필드"]: r["base"] for r in find_table(tables, "3. 표본 비율 불일치").rows}
    gr02 = {
        "id": "GR-02", "name": "srm", "order": 2,
        "tier": _tier(fields["등급"]),
        "check": fields["검사식"],
        "expected_ratio": fields["기대 비율"],
        "threshold": fields["임계"],
        "dimensional": fields["차원 검사"],
        "override_floor": "diagnostic" if "Diagnostic" in fields["override_floor"] else "gate",
        # 원인 추적 (): 실행 순서는 진단 순서일 뿐 인과가 아니다
        "cause_trace": fields["원인 추적"],
        "counterfactual": fields["반사실 확인"],
        "unexplained_branch": fields["미설명 분기"],
    }

    def _checks(section: str) -> list[dict]:
        return [
            {"check": r["검사"], "definition": r["정의"], "tier_raw": r["등급"],
             "tier": "gate" if "Gate" in r["등급"] else "diagnostic"}
            for r in find_table(tables, section).rows
        ]

    gr03 = {"id": "GR-03", "name": "data_loss_join", "order": 1,
            "checks": _checks("4. 데이터 손실"), "override_floor": "gate"}
    gr04 = {"id": "GR-04", "name": "metric_observation_imbalance", "order": 3,
            "checks": _checks("5. 지표 관측 불균형"), "override_floor": "diagnostic"}

    data = {"execution_order": ["GR-03", "GR-02", "GR-04", "GR-01"],  # 7절
            "guardrails": sorted([gr01, gr02, gr03, gr04], key=lambda g: g["order"])}
    return _dump(data, "guardrails.yaml", src)


# 점수 표는 절마다 열 이름이 다르다(점수/분포·공간/변환, LaTeX/정의, 입력/입력 공간/입력 파일).
_SC_ALIASES = {
    "name": ("점수", "분포/공간", "변환"),
    "latex": ("LaTeX", "미분 엔트로피 LaTeX", "정의/LaTeX", "정의"),
    "input": ("입력", "입력 공간", "입력 파일"),
    "green": ("문제없음",),
    "yellow": ("별로",),
    "red": ("안됨",),
    "result_type": ("결과 타입",),
    "note": ("비고",),
}


def build_scores() -> tuple[Path, dict]:
    """SC-* (registry-scores) → rules/scores.yaml

    M3 원클릭 계산 목록. 각 점수의 **3색 적합성**(문제없음/별로/안됨)이 입력 의미 타입·분포에
    대한 판정 조건이며, LaTeX 수식은 UI 렌더와 M1-2 편집기 이관에 쓰인다.
    "안됨"도 실행은 되고 빨간 배너 + 원클릭 변환이 붙는다(0절).
    (지표 대안 묶음·robustness 등급)는 필드 추가로 덧댈 자리.
    """
    src = "registry-scores.md"
    tables = parse_file(SCHEMA_DIR / src)
    items = []
    for t in tables:
        if not (t.rows and t.rows[0].get("ID", "").startswith("SC-")):
            continue
        # 11·12절은 점수 목록이 아니라 ID 로 붙는 덧붙임 표다
        if "purpose" in t.headers or "권고" in t.headers:
            continue
        family = t.rows[0]["ID"].split("-")[1]  # SC-ERR-01 → ERR
        for r in t.rows:
            item = {"id": r["ID"], "family": family, "section": t.section}
            for field, aliases in _SC_ALIASES.items():
                col = next((a for a in aliases if a in r), None)
                item[field] = _clean(r[col]) if col else None
            # 미지정(회색): 조건이 비어 있으면 "적합"이 아니라 "판정 불가"다 ()
            item["unspecified"] = [c for c in ("green", "yellow", "red") if not item[c]]
            item["coverage"] = "full" if not item["unspecified"] else (
                "none" if len(item["unspecified"]) == 3 else "partial")
            items.append(item)
    dup = [i for i in {x["id"] for x in items} if sum(y["id"] == i for y in items) > 1]
    if dup:
        raise ValueError(f"점수 ID 중복: {sorted(dup)}")

    # 0절은 같은 섹션에 표가 2개(3단계 표기 / 판정 축)라 find_table 대신 직접 고른다
    sec0 = [t for t in tables if t.section.startswith("0. 적합성")]
    if len(sec0) != 2:
        raise ValueError(f"0절 표가 2개가 아님: {len(sec0)}")
    grades = [{"label": r["표기"].replace("**", ""), "meaning": r["의미"], "color": r["UI"]}
              for r in sec0[0].rows]
    axes = [{"axis": r["축"], "values": r["값"]} for r in sec0[1].rows]

    #  대안 묶음 축 — 11절은 ID로 점수 표들에 붙는다. 기존 표를 넓히지 않고
    # 따로 둔 이유는, 8열 표에 4열을 더 얹으면 손으로 고칠 수 없게 되기 때문이다
    axis_tbl = next((t for t in tables if "purpose" in t.headers), None)
    if axis_tbl is None:
        raise ValueError("registry-scores.md 에 11. 대안 묶음 축 표가 없다")
    by_id = {i["id"]: i for i in items}
    groups: dict[str, dict] = {}
    for r in axis_tbl.rows:
        sid = r["ID"]
        if sid not in by_id:
            raise ValueError(f"11절이 없는 점수를 가리킨다: {sid}")
        # 등급(A/B/C)은 두지 않는다 — "강건하다"는 무엇에 대해·얼마나 벗어났을 때를
        # 말하지 않으면 성립하지 않는다. 흔들림은 `statop robust` 가 이 자료에서 직접 잰다
        shaken = _clean(r["흔들림"])
        if not shaken:
            raise ValueError(f"{sid} 흔들림 칸이 비어 있다")
        by_id[sid].update(purpose=r["purpose"], measures=_clean(r["measures"]),
                          scale=_clean(r["scale"]), shaken_by=shaken)
        groups.setdefault(r["purpose"], {"id": r["purpose"],
                                         "name": _clean(r["purpose 이름"]),
                                         "members": []})["members"].append(sid)
    blank = [i["id"] for i in items if not i.get("purpose")]
    if blank:
        raise ValueError(f"묶음이 없는 점수: {sorted(blank)}")

    #  작성자 검토 결과 — 12절이 3색·권고·근거를 ID 로 붙인다. 계열 표마다 열 구성이
    # 달라(엔트로피엔 '별로'가 없고 정규화·임상엔 3색 칸이 없다) 그쪽을 넓히지 않았다
    rev = next((t for t in tables if "권고" in t.headers), None)
    if rev is None:
        raise ValueError("registry-scores.md 에 12. 적합성 판정과 권고 표가 없다")
    for r in rev.rows:
        sid = r["ID"]
        if sid not in by_id:
            raise ValueError(f"12절이 없는 점수를 가리킨다: {sid}")
        it = by_id[sid]
        for field, col in (("green", "문제없음"), ("yellow", "별로"), ("red", "안됨")):
            val = _clean(r.get(col))
            if val:
                it[field] = val
        it["recommend"] = _clean(r.get("권고"))
        src = _clean(r.get("근거"))
        # 정의·산술 수준이면 비운다 — 없는 근거를 있는 것처럼 보이게 하지 않는다
        it["source"] = "" if src in ("", "—", "-") else src
        it["unspecified"] = [c for c in ("green", "yellow", "red") if not it[c]]
        it["coverage"] = "full" if not it["unspecified"] else (
            "none" if len(it["unspecified"]) == 3 else "partial")

    data = {"grades": grades, "axes": axes,
            "purposes": sorted(groups.values(), key=lambda g: g["id"]),
            "scores": items}
    return _dump(data, "scores.yaml", src)


def build_metric_roles() -> tuple[Path, dict]:
    """MR-* (registry-metric-roles) → rules/metric_roles.yaml

    Goal 하나를 고르면 무엇을 함께 봐야 하는지의 관계표.
    - Support: Goal이 "얼마나"를 말해주지 않을 때 해석을 채우는 짝 (RMSE→MAE 등)
    - Guardrail: Goal을 올리면 대가로 나빠질 수 있는 trade-off 지표 (sens↔spec 등)
    추천 조회 순서는 사용자 저장분 → 내장 트리아드 → 관계 목록 (요구사항).
    """
    src = "registry-metric-roles.md"
    tables = parse_file(SCHEMA_DIR / src)

    roles = [{"role": r["역할"], "definition": r["정의"], "complexity": r["복잡도"],
              "example": r["예"]} for r in find_table(tables, "0. 세 역할의 정의").rows]
    support = [{"id": r["MR"], "goal": r["Goal"], "support": r["추천 Support"],
                "why": r["왜 (Support가 채우는 해석)"]}
               for r in find_table(tables, "1. Support 관계").rows]
    guardrail = [{"id": r["MR"], "goal": r["Goal"], "guardrail": r["추천 Guardrail"],
                  "tradeoff": r["trade-off 내용"]}
                 for r in find_table(tables, "2. Guardrail 관계").rows]
    triads = [{"id": r["MR"], "situation": r["상황"], "goal": r["Goal"],
               "support": r["Support"], "guardrail": r["Guardrail"]}
              for r in find_table(tables, "3. bio/의학 특화 트리아드").rows]

    data = {"roles": roles, "support_relations": support,
            "guardrail_relations": guardrail, "triads": triads}
    return _dump(data, "metric_roles.yaml", src)


def build_models() -> tuple[Path, dict]:
    """MB-* (registry-models) → rules/models.yaml

    모듈 B는 **감사 전용**이다 — 학습을 실행하지 않고 config·예측·로그만 본다.
    v1 판정 범위는 MB-M0/M1 × MB-C01~33이고, 4절 T2/T3는 `status: later`로 **등록만** 한다
    (판정 로직 없이 목록에 두어야 "빠뜨린 것"과 "아직 안 하는 것"이 구별된다).
    """
    src = "registry-models.md"
    tables = parse_file(SCHEMA_DIR / src)

    def v1_flag(mark: str) -> str:
        # ● 판정함 / ○ 일부(평가만) / later 등록만 — 기호를 그대로 두면 코드가 기호를 읽게 된다
        m = (mark or "").strip()
        return "full" if m.startswith("●") else ("partial" if m.startswith("○")
                                                 else "later")

    questions = [{"id": r["ID"], "question": r["질문"], "output": r["결과"],
                  "v1": v1_flag(r["v1"])}
                 for r in find_table(tables, "1. 모델링 질문").rows]
    tiers = [{"id": r["ID"], "tier": r["티어"], "examples": r["예"],
              "v1": v1_flag(r["v1"]), "audit_input": r["감사 입력"]}
             for r in find_table(tables, "2. 모델 티어").rows]

    checks = []
    for section, group in (("3.1 데이터 무결성", "data"), ("3.2 설정", "config"),
                           ("3.3 평가", "evaluation"), ("3.4 재현성", "reproducibility"),
                           ("3.5 모델특유", "model_specific")):
        for r in find_table(tables, section).rows:
            checks.append({
                "id": r["ID"], "group": group, "check": r["체크"],
                "grade": r["등급"], "tier": r.get("티어"),
                "detect": r.get("감지") or r.get("감지/연결"),
                "action": r["대응"], "status": "v1",
            })

    later = []
    for section, tier in (("4.1 T2 파인튜닝", "MB-M2"), ("4.2 T3 아키텍처", "MB-M3"),
                          ("4.3 학습곡선 로그", "MB-M1"),
                          ("4.4 학습 루프", "MB-M0")):
        for r in find_table(tables, section).rows:
            later.append({"check": r["후보 체크"], "target": r["대상"],
                          "kind": r["성격"], "tier": tier, "status": "later"})

    triads = [{"question": r["MB-Q"], "goal": r["Goal"], "support": r["Support"],
               "guardrail": r["Guardrail"]}
              for r in find_table(tables, "5. MB-Q별 3-metric 트리아드").rows]

    # 3.6 모델×전처리 — MB-C10/C11 이 "모델×전처리 규칙"이라고만 가리키던 표
    preprocessing = [{"family": r["계열"], "examples": r["예"],
                      "scaling": {"필요": "required", "조건부": "depends"}.get(
                          r["표준화"].strip(), "optional"),
                      "why": r["왜"]}
                     for r in find_table(tables, "3.6 모델×전처리").rows]
    # 3.7 모델 비교 — 비교 가능 여부는 모델쌍의 관계가 정한다 (, )
    comparison = [{"condition": r["조건"], "comparable": r["비교 가능"],
                   "allowed": [x.strip() for x in r["쓸 수 있는 것"].split(",")
                               if x.strip() and x.strip() != "—"],
                   "why": r["왜"]}
                  for r in find_table(tables, "3.7 모델 비교").rows]

    data = {"questions": questions, "tiers": tiers, "checks": checks,
            "later": later, "triads": triads,
            "preprocessing": preprocessing, "comparison": comparison}
    return _dump(data, "models.yaml", src)


def build_errors() -> tuple[Path, dict]:
    """E-* (registry-errors) → rules/errors.yaml

    검정별로 "이 검정에서 실제로 나는 오류"를 범주(G/D/I/S/N/M/H/P/E/C)·감지원천·대응과 함께
    묶은 목록. A2 판정과 A3 진단이 사유 문장을 여기서 가져온다.

    md 구조 주의: 검정별 표에 **헤더가 없다**(첫 표에만 있음). 검정 마커
    "**T-101 Welch t-test** · NaN: GW" 를 추적하며 `| E-...` 행을 표준 5열로 읽는다.
    """
    src = "registry-errors.md"
    text = (SCHEMA_DIR / src).read_text()
    tables = parse_tables(text)

    categories = [
        {"code": r["코드"].replace("**", "").split()[0], "name": r["범주"],
         "checks": r["확인 내용"], "source": r["자동 감지 원천"]}
        for r in find_table(tables, "0. 확인 범주").rows
    ]
    nan_policies = [
        {"code": r["코드"].replace("**", ""), "method": r["방식"], "meaning": r["의미"],
         "applies_to": r["적용 검정"]}
        for r in find_table(tables, "1.2 검정별 NaN").rows
    ]

    # 검정별 오류: 마커 줄 + 헤더 없는 표
    marker = re.compile(r"^\*\*(T-[\w–-]+)\s+(.+?)\*\*(?:\s*·\s*NaN:\s*(\w+))?\s*$")
    section = test_id = test_name = nan = None
    errors = []
    for line in text.splitlines():
        if line.startswith("#"):  # 어느 수준 헤딩이든 검정 마커를 초기화 (3절 E-X가 앞 검정에 붙지 않게)
            section = line.lstrip("#").strip()
            test_id = test_name = nan = None
            continue
        m = marker.match(line.strip())
        if m:
            test_id, test_name, nan = m.group(1), m.group(2), m.group(3)
            continue
        if line.lstrip().startswith("| E-"):
            cells = [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", line.strip())]
            cells = [c for c in cells if c != ""]
            cells += [""] * (5 - len(cells))
            eid, desc, cats, detect, action = cells[:5]
            errors.append({
                "id": eid,
                "test": test_id,               # E-X-* 는 None (범용 오류)
                "test_name": test_name if test_id else None,
                "nan_policy": nan if test_id else None,
                "section": section,
                "error": desc,
                "categories": [c.strip() for c in cats.split(",") if c.strip() and c.strip() != "—"],
                "detect": _clean(detect),
                "action": _clean(action),
            })

    dup = [i for i in {e["id"] for e in errors} if sum(x["id"] == i for x in errors) > 1]
    if dup:
        raise ValueError(f"오류 ID 중복: {sorted(dup)}")
    known = {c["code"] for c in categories}
    bad = {c for e in errors for c in e["categories"]} - known
    if bad:
        raise ValueError(f"알 수 없는 오류 범주: {sorted(bad)}")

    data = {"categories": categories, "nan_policies": nan_policies, "errors": errors}
    return _dump(data, "errors.yaml", src)


def build_label_palette() -> tuple[Path, dict]:
    """design-tokens 7절 → rules/label_palette.yaml

    라벨 문자열(예: "HCC_tumor")을 카테고리·색으로 자동 매핑하는 사전.
    부분일치 + TCGA 코드 + 정규화 규칙. 무매칭은 회색 "미분류"로 두고 사용자 지정을 학습한다.
    """
    src = "design-tokens.md"
    tables = parse_file(SCHEMA_DIR / src)

    def _anchor_rows(section: str) -> list[dict]:
        rows = []
        for r in find_table(tables, section).rows:
            keywords = [k.strip() for k in r["키워드/약어(부분일치)"].split(",") if k.strip()]
            tcga = [t.strip() for t in r.get("TCGA", "").split(",") if t.strip() and t.strip() != "—"]
            rows.append({
                "category": r["카테고리"],
                "tcga": tcga,
                "keywords": keywords,
                "color": r["앵커색"],
                "family": _clean(r.get("계열", "")),
            })
        return rows

    anchors = _anchor_rows("7.3 암종 앵커 사전")
    bad = [a for a in anchors if not re.fullmatch(r"#[0-9A-Fa-f]{6}", a["color"])]
    if bad:
        raise ValueError(f"앵커색이 HEX가 아님: {[a['category'] for a in bad]}")
    dup = [c for c in {a["category"] for a in anchors}
           if sum(x["category"] == c for x in anchors) > 1]
    if dup:
        raise ValueError(f"카테고리 중복: {sorted(dup)}")

    # 같은 키워드가 여러 카테고리에 있으면 매칭이 모호해진다 → 조용히 두지 않고 기록
    # (7.2-4 "다중 일치 시 … 모호하면 사용자 확인"의 입력)
    kw_owners: dict[str, list[str]] = {}
    for a in anchors:
        for k in a["keywords"]:
            kw_owners.setdefault(k, []).append(a["category"])
    conflicts = [{"keyword": k, "categories": v} for k, v in kw_owners.items() if len(v) > 1]

    data = {
        "keyword_conflicts": conflicts,
        "normalize": {  # 7.2-1
            "lowercase": True,
            "strip_separators": list("-_./ "),
            "strip_suffixes": ["cancer", "ca", "tumor", "carcinoma", "adeno", "tissue", "cells", "ep"],
        },
        "match_rules": [  # 7.2-2~5 (순서가 곧 우선순위)
            "TCGA 코드 정확 일치",
            "키워드 부분일치 — 가장 긴 일치 우선",
            "다중 일치 시 상태축(암종) > 조직축",
            "그래도 모호하면 사용자 확인(노랑)",
            "무매칭은 회색 '미분류' — 사용자 지정 시 palette.json에 학습",
        ],
        "anchors": anchors,
    }
    return _dump(data, "label_palette.yaml", src)


def build_derive_functions() -> tuple[Path, list[dict]]:
    """F-01~14 (registry-tests 10) → rules/derive_functions.yaml

    수식 파서의 화이트리스트 원천. scope(행 단위/컬럼 스칼라/세트)를 정규화해
    M1-2 빌더가 UI에서 색을 구분하고, 파서가 허용 함수를 판정할 수 있게 한다.
    """
    src = "registry-tests.md"
    t = find_table(parse_file(SCHEMA_DIR / src), "10. 파생 함수")
    scope_map = {"행 단위": "row", "컬럼 스칼라": "column_scalar", "컬럼": "column_scalar",
                 "비율화": "row", "세트": "set", "두 컬럼": "row", "그룹 기준": "group"}
    items = []
    for r in t.rows:
        raw_scope = r["형태"].replace("*", "").strip()
        scope = next((v for k, v in scope_map.items() if raw_scope.startswith(k)), None)
        if scope is None:
            raise ValueError(f"{r['ID']}: 알 수 없는 형태 값 {raw_scope!r}")
        items.append({
            "id": r["ID"],
            "functions": [f.strip(" `") for f in r["함수/연산"].split(",")],
            "scope": scope,
            "scope_raw": raw_scope,
            "result_type": _clean(r["결과 의미 타입"]),
            "eps_rule": _clean(r["eps 규칙"]),
            "note": _clean(r["비고"]),
        })
    return _dump(items, "derive_functions.yaml", src)


def build_semantic_types() -> tuple[Path, list[dict]]:
    """S-T01~13 (registry-tests 9.1) → rules/semantic_types.yaml"""
    src = "registry-tests.md"
    t = find_table(parse_file(SCHEMA_DIR / src), "9.1 의미 타입")
    items = [
        {
            "id": r["ID"],
            "type": r["타입"],
            "infer_basis": r["추론 근거 (자동)"],
            "trap": None if r["함정 (노랑 → 사용자 확정)"] in ("", "—") else r["함정 (노랑 → 사용자 확정)"],
            "allowed_ops": r["기본 허용 연산"],
        }
        for r in t.rows
    ]
    return _dump(items, "semantic_types.yaml", src)
