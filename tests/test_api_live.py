"""실서버(uvicorn) 통합 테스트 — parquet·대용량 경로는 여기서 검증한다.

TestClient(포털 스레드)에서는 pyarrow 반복 읽기가 불안정하므로, 실제 배포 형태와 같은
별도 프로세스 서버에 HTTP로 요청한다.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

DATA = Path(__file__).parent / "data"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _free_port()
    env = {**os.environ, "STATOP_HOME": str(tmp_path_factory.mktemp("statop_home"))}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "statop.api.app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):  # 기동 대기
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            raise RuntimeError("서버가 기동하지 않음")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_live_parquet_repeated_requests(server):
    """실데이터 parquet에 연속 요청 — 웹 UI가 필터를 바꿔가며 호출하는 상황."""
    path = str(DATA / "synth_long.parquet")
    for sort in ("missing", "unique", "name"):
        r = httpx.get(f"{server}/v1/datasets/columns",
                      params={"path": path, "sample_n": 3000, "sort": sort, "limit": 2},
                      timeout=120)
        assert r.status_code == 200
        b = r.json()
        assert b["columns"]["total"] == 2000
        assert b["rows"] == {"n": 10000, "estimated": False}
        assert len(b["items"]) == 2
        assert "PT000001" not in r.text and "siteA" not in r.text  # 데이터 셀 미노출
    assert httpx.get(f"{server}/health", timeout=5).json()["status"] == "ok"  # 서버 생존


def test_live_session_and_dataset_flow(server):
    path = str(DATA / "synth_long.parquet")
    s = httpx.post(f"{server}/v1/sessions", json={"data": path}, timeout=60).json()
    assert s["source_id"] == "d1"
    r = httpx.post(f"{server}/v1/datasets",
                   json={"session_file": s["session_file"],
                         "path": str(DATA / "synth_wide.parquet")}, timeout=60).json()
    assert r["source_id"] == "d2"


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    """작은 표 — 실데이터와 같은 성격(문자 id·그룹·수치·결측)."""
    import numpy as np
    import pandas as pd

    n = 40
    df = pd.DataFrame({
        "patient_id": [f"PT{i:04d}" for i in range(n)],
        "site": ["siteA"] * 12 + ["siteB"] * 14 + ["siteC"] * 14,
        "label": [0, 1] * (n // 2),
        "cont000": np.linspace(0, 1, n),
        "trap_binary_count": [0, 1] * (n // 2),
    })
    df.loc[:20, "cont000"] = None           # 결측 >30% → high
    df.loc[:5, "trap_binary_count"] = None  # 결측 ~15% → mid
    p = tmp_path_factory.mktemp("d") / "small.csv"
    df.to_csv(p, index=False)
    return p


def test_live_columns_shape_and_no_data_cells(server, small):
    r = httpx.get(f"{server}/v1/datasets/columns", params={"path": str(small), "limit": 3},
                  timeout=60)
    assert r.status_code == 200
    b = r.json()
    assert b["columns"]["total"] == 5 and b["columns"]["returned"] == 3
    assert b["rows"]["estimated"] is True and 30 < b["rows"]["n"] < 50   # csv는 행수 추정
    assert b["warnings"] == []
    assert b["items"][0]["column"] == "patient_id"
    assert set(b["items"][0]) == {"column", "dtype", "missing_rate", "n_unique", "missing_level"}
    assert "PT0001" not in r.text and "siteA" not in r.text   # 데이터 셀 미노출


def test_live_pagination_and_cache(server):
    """25개씩 페이지 + 프로파일 캐시 — 전체 기준 정렬은 유지되고 페이지 이동은 파일을 다시 읽지 않는다."""
    import time

    path = str(DATA / "synth_long.parquet")
    base = {"path": path, "sample_n": 3000, "sort": "missing"}

    p1 = httpx.get(f"{server}/v1/datasets/columns", params=base, timeout=180).json()
    assert p1["page"] == {"size": 25, "index": 1, "count": 80,
                          "has_prev": False, "has_next": True}
    assert len(p1["items"]) == 25

    t0 = time.time()
    p2 = httpx.get(f"{server}/v1/datasets/columns", params={**base, "offset": 25},
                   timeout=180).json()
    assert p2["cached"] is True and time.time() - t0 < 2.0   # 캐시 적중 — 파일 재읽기 없음
    assert p2["page"]["index"] == 2 and p2["page"]["has_prev"] is True
    # 전체 정렬 기준이 유지된다: 2쪽 첫 항목 ≤ 1쪽 마지막 항목
    assert p2["items"][0]["missing_rate"] <= p1["items"][-1]["missing_rate"]
    assert {i["column"] for i in p1["items"]} & {i["column"] for i in p2["items"]} == set()

    # 마지막 쪽 (80쪽 = offset 79*25)
    last = httpx.get(f"{server}/v1/datasets/columns", params={**base, "offset": 79 * 25},
                     timeout=180).json()
    assert last["page"]["index"] == 80 and last["page"]["has_next"] is False


def test_live_columns_grep_sort_offset(server, small):
    base = {"path": str(small)}
    b = httpx.get(f"{server}/v1/datasets/columns", params={**base, "grep": "^trap_"},
                  timeout=60).json()
    assert b["columns"]["matched"] == 1 and b["columns"]["total"] == 5
    assert b["page"]["count"] == 1

    b = httpx.get(f"{server}/v1/datasets/columns",
                  params={**base, "sort": "missing", "limit": 2}, timeout=60).json()
    rates = [i["missing_rate"] for i in b["items"]]
    assert rates == sorted(rates, reverse=True)
    assert b["items"][0]["missing_level"] == "high" and b["items"][1]["missing_level"] == "mid"

    b2 = httpx.get(f"{server}/v1/datasets/columns",
                   params={**base, "sort": "missing", "limit": 2, "offset": 2}, timeout=60).json()
    assert b2["items"][0]["column"] != b["items"][0]["column"]

    r = httpx.get(f"{server}/v1/datasets/columns", params={**base, "sort": "nope"}, timeout=60)
    assert r.status_code == 400


def test_live_columns_reflects_transposed_session(server, tmp_path_factory):
    import pandas as pd

    data = tmp_path_factory.mktemp("t") / "t.csv"
    pd.DataFrame({"id": ["a", "b"], "x": [1, 2], "y": [3, 4]}).to_csv(data, index=False)
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(data)}, timeout=60).json()

    import json

    from statop.session.core import append_op, load_session

    sf = Path(s["session_file"])          # 서버의 STATOP_HOME 아래 경로 — 그 파일에 직접 쓴다
    doc = load_session(sf)
    append_op(doc, "transpose", source="d1")
    sf.write_text(json.dumps(doc, ensure_ascii=False, indent=1))

    b = httpx.get(f"{server}/v1/datasets/columns",
                  params={"path": str(data), "session_file": s["session_file"]},
                  timeout=60).json()
    assert b["file"]["transposed"] is True
    assert [i["column"] for i in b["items"]] == ["column", "a", "b"]


def test_live_session_isolation_no_blocking(server):
    """: 한 세션의 무거운 요청이 도는 동안 다른 세션의 가벼운 요청이 막히지 않는다."""
    import threading
    import time

    heavy = {"done": None}

    def run_heavy():
        t0 = time.time()
        httpx.get(f"{server}/v1/datasets/columns",
                  params={"path": str(DATA / "synth_wide.parquet"), "sample_n": 3000},
                  timeout=300)
        heavy["done"] = time.time() - t0

    t = threading.Thread(target=run_heavy)
    t.start()
    time.sleep(1.0)                      # 무거운 작업이 도는 중
    t0 = time.time()
    r = httpx.get(f"{server}/health", timeout=30)   # 다른 세션의 가벼운 요청
    light = time.time() - t0
    assert r.status_code == 200
    assert light < 3.0, f"가벼운 요청이 {light:.1f}s 지연됨 — 격리 실패"
    t.join(timeout=300)
    assert heavy["done"] is not None


def test_live_main_source_switch(server, tmp_path_factory):
    """: 새 파일을 main으로 열면 대상만 바뀌고 세션은 유지된다."""
    import pandas as pd

    d = tmp_path_factory.mktemp("mainswitch")
    f1, f2 = d / "first.csv", d / "second.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(f1, index=False)
    pd.DataFrame({"x": [1, 2], "y": [3, 4], "z": [5, 6]}).to_csv(f2, index=False)

    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f1)}, timeout=60).json()
    assert s["sources"][0]["role"] == "main"

    r = httpx.post(f"{server}/v1/datasets",
                   json={"session_file": s["session_file"], "path": str(f2), "role": "main"},
                   timeout=60).json()
    assert r["main"] == r["source_id"] != "d1"
    roles = {x["id"]: x["role"] for x in r["sources"]}
    assert roles["d1"] == "aux"                 # 이전 main은 보조로 내려감

    bad = httpx.post(f"{server}/v1/datasets",
                     json={"session_file": s["session_file"], "path": str(f2), "role": "nope"},
                     timeout=60)
    assert bad.status_code == 400


def test_live_import_and_drop_columns(server, tmp_path_factory):
    """S080: 선택한 컬럼만 작업 영역에 남는다 (전체 목록은 더 이상 필요 없음)."""
    import pandas as pd

    d = tmp_path_factory.mktemp("imp")
    f = d / "t.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6], "d": [7, 8]}).to_csv(f, index=False)
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]

    r = httpx.post(f"{server}/v1/views/import",
                   json={"session_file": sf, "path": str(f), "cols": ["a", "c"]},
                   timeout=60).json()
    assert r["selected"] == ["a", "c"] and r["n_selected"] == 2

    # 현재 작업 영역 = 가져온 컬럼만
    v = httpx.get(f"{server}/v1/views/selected", params={"session_file": sf}, timeout=60).json()
    assert v["selected"] == ["a", "c"]

    # 제외(체크 해제)도 기록된다
    r = httpx.post(f"{server}/v1/views/drop", json={"session_file": sf, "cols": ["a"]},
                   timeout=60).json()
    assert r["selected"] == ["c"]

    # 없는 컬럼 / 빈 선택 / 가져온 적 없는 컬럼 제외는 거부
    assert httpx.post(f"{server}/v1/views/import",
                      json={"session_file": sf, "path": str(f), "cols": ["zz"]},
                      timeout=60).status_code == 400
    assert httpx.post(f"{server}/v1/views/import",
                      json={"session_file": sf, "path": str(f), "cols": []},
                      timeout=60).status_code == 400
    assert httpx.post(f"{server}/v1/views/drop", json={"session_file": sf, "cols": ["a"]},
                      timeout=60).status_code == 400

    # 세션 로그에 op가 남는다 (재생 가능)
    import json
    doc = json.loads(Path(sf).read_text())
    assert [o["op"] for o in doc["ops"]] == ["open", "select", "deselect"]


def test_live_path_check(server, tmp_path_factory):
    """S081: 저장·불러오기 입력창의 신호등 (초록/노랑/빨강)."""
    d = tmp_path_factory.mktemp("pc")
    g = httpx.get(f"{server}/v1/paths/check", params={"path": str(d)}, timeout=30).json()
    assert g["color"] == "green" and g["writable"] is True
    y = httpx.get(f"{server}/v1/paths/check", params={"path": str(d / "new" / "a.json")},
                  timeout=30).json()
    assert y["color"] == "yellow" and y["can_create"] is True
    r = httpx.get(f"{server}/v1/paths/check", params={"path": "/root/x.json"}, timeout=30).json()
    assert r["color"] == "red"
    assert httpx.get(f"{server}/v1/paths/check",
                     params={"path": str(d), "need": "nope"}, timeout=30).status_code == 400


def test_live_save_list_load_roundtrip(server, tmp_path_factory):
    """S081: 저장 → 목록 → 불러오기 왕복. 덮어쓰기는 409로 되물어야 한다 ."""
    import pandas as pd

    d = tmp_path_factory.mktemp("slr")
    f = d / "t.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(f, index=False)

    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": s["session_file"], "path": str(f), "cols": ["a"]},
               timeout=60)

    saved = httpx.post(f"{server}/v1/sessions/save",
                       json={"session_file": s["session_file"]}, timeout=60).json()
    assert saved["name"].endswith(".json")

    # 같은 시간대 재저장 → 409 (단순 저장으로는 덮어쓰지 않는다)
    again = httpx.post(f"{server}/v1/sessions/save",
                       json={"session_file": s["session_file"]}, timeout=60)
    assert again.status_code == 409
    ok = httpx.post(f"{server}/v1/sessions/save",
                    json={"session_file": s["session_file"], "overwrite": True}, timeout=60)
    assert ok.status_code == 200

    lst = httpx.get(f"{server}/v1/sessions/list", timeout=60).json()
    assert any(i["name"] == saved["name"] for i in lst["items"])
    entry = next(i for i in lst["items"] if i["name"] == saved["name"])
    assert entry["ops"] >= 2 and entry["source"] == str(f)

    loaded = httpx.post(f"{server}/v1/sessions/load", json={"saved": saved["saved"]},
                        timeout=60).json()
    assert loaded["session_id"] != s["session_id"]          # 새 세션으로 열린다
    assert list(loaded["selected"].values())[0] == ["a"]     # 선택 복원
    assert loaded["source_problems"] == []                   # 원본 그대로

    # 원본을 바꾸면 경고가 함께 온다 (S029와 같은 흐름)
    f.write_text("a,b\n1,2\n3,4\n5,6\n")
    loaded2 = httpx.post(f"{server}/v1/sessions/load", json={"saved": saved["saved"]},
                         timeout=60).json()
    assert len(loaded2["source_problems"]) == 1
    assert "해시가 다릅니다" in loaded2["source_problems"][0]["message"]


def test_live_hold_columns(server, tmp_path_factory):
    """M0-5 hold — 분석에서 빼되 작업 영역엔 남긴다."""
    import pandas as pd

    d = tmp_path_factory.mktemp("hold")
    f = d / "t.csv"
    pd.DataFrame({"pid": [1, 2], "a": [3, 4], "b": [5, 6]}).to_csv(f, index=False)
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f), "cols": ["pid", "a", "b"]}, timeout=60)

    r = httpx.post(f"{server}/v1/views/hold",
                   json={"session_file": sf, "cols": ["pid"]}, timeout=60).json()
    assert r["held"] == ["pid"] and r["analysis"] == ["a", "b"]

    v = httpx.get(f"{server}/v1/views/selected", params={"session_file": sf}, timeout=60).json()
    assert v["selected"] == ["pid", "a", "b"]      # 작업 영역엔 남아 있다
    assert v["n_analysis"] == 2

    off = httpx.post(f"{server}/v1/views/hold",
                     json={"session_file": sf, "cols": ["pid"], "hold": False}, timeout=60).json()
    assert off["held"] == [] and off["n_analysis"] == 3

    bad = httpx.post(f"{server}/v1/views/hold",
                     json={"session_file": sf, "cols": ["zz"]}, timeout=60)
    assert bad.status_code == 400


def test_live_label_levels_and_mapping(server):
    """: 수준 조회 → 매핑 확정 → 군 재구성이 기록된다."""
    demo = str(DATA / "labels_demo.csv")
    s = httpx.post(f"{server}/v1/sessions", json={"data": demo}, timeout=60).json()
    sf = s["session_file"]

    lv = httpx.get(f"{server}/v1/labels/levels",
                   params={"path": demo, "column": "diagnosis", "sample_n": 2000},
                   timeout=60).json()
    assert lv["n_levels"] == 3 and lv["regrouped"] is False
    assert [x["value"] for x in lv["levels"]] == ["control", "hct", "liver"]
    assert lv["levels"][2]["category"] == "liver"        # 라벨 사전에서 색·카테고리 배정

    m = httpx.post(f"{server}/v1/labels/map",
                   json={"session_file": sf, "column": "diagnosis",
                         "mapping": {"control": 0, "hct": 0, "liver": 1}}, timeout=60).json()
    assert m["n_groups"] == 2
    assert m["groups"][0]["values"] == ["control", "hct"]

    # 세션을 반영해 다시 조회하면 묶인 상태로 나온다
    lv2 = httpx.get(f"{server}/v1/labels/levels",
                    params={"path": demo, "column": "diagnosis", "session_file": sf,
                            "sample_n": 2000}, timeout=60).json()
    assert lv2["regrouped"] is True and len(lv2["groups"]) == 2
    assert lv2["groups"][0]["n"] == 800

    bad = httpx.get(f"{server}/v1/labels/levels",
                    params={"path": demo, "column": "nope"}, timeout=60)
    assert bad.status_code == 400


def test_live_relabel_requires_note_and_reports(server):
    """: 사유 없으면 거부, 수정하면 출력에 강제 표시."""
    demo = str(DATA / "labels_demo.csv")
    s = httpx.post(f"{server}/v1/sessions", json={"data": demo}, timeout=60).json()
    sf = s["session_file"]
    body = {"session_file": sf, "key_column": "patient_id", "key": "PT00417",
            "column": "diagnosis", "to": "liver"}

    assert httpx.post(f"{server}/v1/labels/relabel", json={**body, "note": " "},
                      timeout=60).status_code == 400
    assert httpx.post(f"{server}/v1/labels/relabel",
                      json={**body, "key": "PT99999", "note": "x"},
                      timeout=60).status_code == 404

    r = httpx.post(f"{server}/v1/labels/relabel",
                   json={**body, "note": "등록 시 입력 오류 — 병리 재확인"}, timeout=60).json()
    assert r["from"] == "hct" and r["to"] == "liver"
    assert r["n_relabels"] == 1 and r["over_threshold"] is False
    assert "개별 라벨 수정 1건" in r["notice"]

    lst = httpx.get(f"{server}/v1/labels/relabels", params={"session_file": sf},
                    timeout=60).json()
    assert lst["n"] == 1 and lst["items"][0]["note"]


def test_live_derive_preview_and_commit(server, tmp_path_factory):
    """M1-2 파생 컬럼 — 웹 편집기가 쓰는 경로 그대로 ."""
    import pandas as pd

    d = tmp_path_factory.mktemp("derive")
    f = d / "t.csv"
    pd.DataFrame({"frac": [0.1, 0.2, 0.3, 0.4], "size": [10, 20, 30, 40]}).to_csv(f, index=False)
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f), "cols": ["frac", "size"]}, timeout=60)

    r = httpx.post(f"{server}/v1/derive/preview",
                   json={"session_file": sf, "expr": "log2(frac / mean(size) + eps)"},
                   timeout=60)
    assert r.status_code == 200
    b = r.json()
    assert b["expr"] == "log2(frac / mean(size) + eps)"
    assert b["result_type"] == "log-scale"
    assert "".join(t["text"] for t in b["tokens"]) == b["expr"]   # 색칠이 식을 바꾸지 않는다
    roles = {t["text"]: t["role"] for t in b["tokens"] if t["role"] != "punct"}
    assert roles["mean"] == "column_scalar_func" and roles["log2"] == "row_func"
    assert b["latex"].startswith(r"\log_2")
    assert b["eps"]["auto"] is True and b["eps"]["recommended"] is not None
    assert b["preview"]["n"] == 4 and b["preview"]["n_inf"] == 0

    # 추천값을 넘는 eps는 미리보기에서부터 거부한다
    big = httpx.post(f"{server}/v1/derive/preview",
                     json={"session_file": sf, "expr": "log2(frac + eps)", "eps": 0.5},
                     timeout=60)
    assert big.status_code == 400 and "추천값" in big.json()["detail"]

    # eps를 안 밝히면 커밋되지 않는다 — 기록에 남아야 재현이 된다
    noeps = httpx.post(f"{server}/v1/derive/commit",
                       json={"session_file": sf, "expr": "log2(frac + eps)", "name": "lf"},
                       timeout=60)
    assert noeps.status_code == 400

    ok = httpx.post(f"{server}/v1/derive/commit",
                    json={"session_file": sf, "expr": "log2(frac + eps)",
                          "name": "lf", "eps": 1e-8}, timeout=60)
    assert ok.status_code == 200 and ok.json()["result_type"] == "log-scale"

    dup = httpx.post(f"{server}/v1/derive/commit",
                     json={"session_file": sf, "expr": "frac * 2", "name": "frac"}, timeout=60)
    assert dup.status_code == 400        # 기존 컬럼 이름은 덮어쓰지 않는다


def test_live_derive_rejects_arbitrary_code(server, tmp_path_factory):
    """화이트리스트 밖은 실행 경로가 없다 — 웹에서 들어와도 마찬가지."""
    import pandas as pd

    d = tmp_path_factory.mktemp("derive_safe")
    f = d / "t.csv"
    pd.DataFrame({"a": [1.0, 2.0]}).to_csv(f, index=False)
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f), "cols": ["a"]}, timeout=60)

    for expr in ["__import__('os').system('ls')", "a.__class__", "open('/etc/passwd')",
                 "[x for x in range(3)]", "lambda: 1"]:
        r = httpx.post(f"{server}/v1/derive/preview",
                       json={"session_file": sf, "expr": expr}, timeout=60)
        assert r.status_code == 400, expr


def test_live_derive_functions_keypad(server):
    """키패드 목록 — 허용 함수의 원본은 규칙 DB다."""
    r = httpx.get(f"{server}/v1/derive/functions", timeout=60).json()
    by_role = {g["role"]: g["functions"] for g in r["groups"]}
    assert "log2" in by_role["row_func"]
    assert "mean" in by_role["column_scalar_func"]
    assert "clr" in by_role["set_func"]
    assert r["scalar_note"]


def _compat_session(server, tmp_path_factory, name="compat"):
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp(name)
    f = d / "t.csv"
    rng = np.random.default_rng(17)
    n = 200
    comp = rng.dirichlet([4, 3, 2], size=n)
    pd.DataFrame({"pid": [f"P{i:03d}" for i in range(n)],
                  "fA": comp[:, 0], "fB": comp[:, 1], "fC": comp[:, 2],
                  "pct": rng.uniform(0, 100, n)}).to_csv(f, index=False)
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f),
                     "cols": ["pid", "fA", "fB", "fC", "pct"]}, timeout=60)
    return sf


def test_live_compat_defers_then_judges(server, tmp_path_factory):
    """S121 타이밍 — 확정 전에는 판정하지 않는다."""
    sf = _compat_session(server, tmp_path_factory)

    r = httpx.post(f"{server}/v1/compat/check",
                   json={"session_file": sf, "op": "correlate", "cols": ["fA", "fB"]},
                   timeout=60).json()
    assert r["blocked"] and r["verdict"] == "unconfirmed"
    assert {f["id"] for f in r["findings"]} == {"S-R14"}

    for c in ("fA", "fB", "fC"):
        httpx.post(f"{server}/v1/semantic/confirm",
                   json={"session_file": sf, "column": c, "type": "proportion"}, timeout=60)

    r2 = httpx.post(f"{server}/v1/compat/check",
                    json={"session_file": sf, "op": "correlate", "cols": ["fA", "fB"]},
                    timeout=60).json()
    assert r2["verdict"] == "red"
    f = next(x for x in r2["findings"] if x["id"] == "S-R01")
    assert f["fix_action"] == "clr" and f["composition"] == ["fA", "fB", "fC"]


def test_live_compat_set_summary_is_one_per_rule(server, tmp_path_factory):
    """ — 쌍마다 쏟지 않는다."""
    sf = _compat_session(server, tmp_path_factory, "compat_set")
    for c, t in (("fA", "proportion"), ("fB", "proportion"), ("fC", "proportion"),
                 ("pct", "percent"), ("pid", "id")):
        httpx.post(f"{server}/v1/semantic/confirm",
                   json={"session_file": sf, "column": c, "type": t}, timeout=60)

    r = httpx.post(f"{server}/v1/compat/check",
                   json={"session_file": sf, "op": "correlate"}, timeout=60).json()
    assert r["scope"] == "set" and r["verdict"] == "gate"
    seen = [f["id"] for f in r["findings"]]
    assert len(seen) == len(set(seen))            # 규칙당 1건
    assert seen[0] == "S-R10"                     # gate가 맨 앞 (9.3 순서)


def test_live_compat_fix_plan_then_apply(server, tmp_path_factory):
    """S122· — 계획은 기록을 남기지 않고, 적용하면 재판정까지 돌아온다."""
    sf = _compat_session(server, tmp_path_factory, "compat_fix")
    for c in ("fA", "fB", "fC"):
        httpx.post(f"{server}/v1/semantic/confirm",
                   json={"session_file": sf, "column": c, "type": "proportion"}, timeout=60)

    body = {"session_file": sf, "op": "correlate", "cols": ["fA", "fB"], "rule": "S-R01"}
    dry = httpx.post(f"{server}/v1/compat/fix", json=body, timeout=60).json()
    assert dry["applied"] is False and dry["needs_eps"] is True
    assert [d["name"] for d in dry["derives"]] == ["fA_clr", "fB_clr", "fC_clr"]

    noeps = httpx.post(f"{server}/v1/compat/fix", json={**body, "apply": True}, timeout=60)
    assert noeps.status_code == 400        # eps 없이는 기록하지 않는다

    ok = httpx.post(f"{server}/v1/compat/fix",
                    json={**body, "apply": True, "eps": 1e-8}, timeout=60).json()
    assert ok["applied"] and ok["rejudged"]["verdict"] == "green"

    v = httpx.get(f"{server}/v1/views/selected", params={"session_file": sf}, timeout=60).json()
    assert "fA_clr" in v["selected"] and "fA" in v["selected"]   # 원본은 남는다


def test_live_compat_asks_for_composition(server, tmp_path_factory):
    """S124 — 세트를 모르면 추측하지 않고 후보를 돌려준다."""
    import pandas as pd

    d = tmp_path_factory.mktemp("compat_ask")
    f = d / "t.csv"
    import numpy as np

    a = np.random.default_rng(4).uniform(0.05, 0.6, 100)
    pd.DataFrame({"a": a, "b": a * 0.5}).to_csv(f, index=False)   # 1로 닫히지 않는다
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f), "cols": ["a", "b"]}, timeout=60)
    for c in ("a", "b"):
        httpx.post(f"{server}/v1/semantic/confirm",
                   json={"session_file": sf, "column": c, "type": "proportion"}, timeout=60)

    r = httpx.post(f"{server}/v1/compat/fix",
                   json={"session_file": sf, "op": "compare", "cols": ["a", "b"],
                         "rule": "S-R02", "action": "clr"}, timeout=60).json()
    assert r["needs_composition"] and r["candidates"] == []
    assert not r["derives"]


def test_live_guard_run_and_limits(server, tmp_path_factory):
    """M4 — 손실이 편향되면 차단이 뜨고, headline이 채워진다."""
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("guard")
    f = d / "t.csv"
    rng = np.random.default_rng(9)
    n = 1000
    arm = rng.choice(["control", "case"], n)
    qc = np.where(arm == "case", rng.random(n) * 0.5, rng.random(n))
    pd.DataFrame({"arm": arm, "site": rng.choice(["A", "B"], n),
                  "qc": qc.round(3),
                  "vaf": np.clip(rng.beta(2, 8, n), 0, 1).round(4)}).to_csv(f, index=False)

    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f),
                     "cols": ["arm", "site", "qc", "vaf"]}, timeout=60)
    httpx.post(f"{server}/v1/semantic/confirm",
               json={"session_file": sf, "column": "vaf", "type": "proportion"}, timeout=60)

    # 손실이 없으면 손실 검사를 했다고 하지 않는다
    first = httpx.post(f"{server}/v1/guard/run",
                       json={"session_file": sf, "group": "arm"}, timeout=120).json()
    assert any(x["rule"] == "GR-03" for x in first["skipped"])

    assert first["order"] == ["GR-03", "GR-02", "GR-04", "GR-01"]

    # 정의역 밖 값이 있으면 손실 기록 없이도 차단이 뜬다 (GR-01)
    bad = d / "bad.csv"
    pd.DataFrame({"arm": arm[:100],
                  "vaf": np.r_[np.full(98, 0.3), [1.4, -0.2]]}).to_csv(bad, index=False)
    s2 = httpx.post(f"{server}/v1/sessions", json={"data": str(bad)}, timeout=60).json()
    sf2 = s2["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf2, "path": str(bad), "cols": ["arm", "vaf"]},
               timeout=60)
    httpx.post(f"{server}/v1/semantic/confirm",
               json={"session_file": sf2, "column": "vaf", "type": "proportion"},
               timeout=60)
    out = httpx.post(f"{server}/v1/guard/run",
                     json={"session_file": sf2, "group": "arm", "metrics": ["vaf"]},
                     timeout=120).json()
    assert out["tier"] == "gate" and out["headline"]
    gate = next(f for f in out["findings"] if f["tier"] == "gate")
    assert gate["rule"] == "GR-01" and gate["numbers"]["n"] == 2


def test_live_guard_limits_floor_is_enforced(server):
    """S131 — REST로도 완화 하한 아래는 거부된다. 우회 경로가 없어야 한다."""
    lim = httpx.get(f"{server}/v1/guard/limits", timeout=60).json()
    gr03 = next(r for r in lim["rules"] if r["rule"] == "GR-03")
    assert gr03["floor"] == "gate"

    bad = httpx.post(f"{server}/v1/guard/limits",
                     json={"rule": "GR-03", "tier": "off"}, timeout=60)
    assert bad.status_code == 400 and "gate" in bad.json()["detail"]

    ok = httpx.post(f"{server}/v1/guard/limits",
                    json={"rule": "GR-04", "key": "min_group_n", "value": 3},
                    timeout=60).json()
    assert next(x for x in ok["limits"] if x["key"] == "min_group_n")["overridden"]
    httpx.post(f"{server}/v1/guard/limits",
               json={"rule": "GR-04", "key": "min_group_n", "value": 10}, timeout=60)


def test_live_view_state_roundtrip(server, tmp_path_factory):
    """상태 저장 → 확인 → 반영의 왕복 (웹↔CLI 동기화 키)."""
    import pandas as pd

    d = tmp_path_factory.mktemp("view")
    f = d / "t.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(f, index=False)
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]

    st = httpx.get(f"{server}/v1/sessions/state",
                   params={"session_file": sf}, timeout=60).json()
    assert st["view"] is None and st["n_ops"] >= 0

    httpx.post(f"{server}/v1/sessions/view",
               json={"session_file": sf, "by": "web", "step": "columns",
                     "picked": ["a"]}, timeout=60)
    st2 = httpx.get(f"{server}/v1/sessions/state",
                    params={"session_file": sf}, timeout=60).json()
    assert st2["view"]["by"] == "web" and st2["view"]["picked"] == ["a"]


def test_live_ui_html_is_not_cached(server):
    """옛 빌드가 브라우저에 남으면 고쳐도 옛 화면을 본다 — HTML은 no-cache."""
    r = httpx.get(f"{server}/ui/", timeout=60)
    if r.status_code != 200:
        pytest.skip("ui/dist 없음")
    assert "no-cache" in r.headers.get("cache-control", "")


def test_live_distribution_of_derived_column(server, tmp_path_factory):
    """파생 컬럼 분포 — 파일에 없는 컬럼이라 세션 재계산이 필요하다 (사용자가 겪은 크래시)."""
    import pandas as pd

    d = tmp_path_factory.mktemp("distd")
    f = d / "t.csv"
    pd.DataFrame({"x": [0.1, 0.2, 0.3, 0.4] * 30}).to_csv(f, index=False)
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f), "cols": ["x"]}, timeout=60)
    httpx.post(f"{server}/v1/derive/commit",
               json={"session_file": sf, "expr": "log2(x + eps)", "name": "lx",
                     "eps": 1e-8}, timeout=60)

    # 세션 없이 부르면 파일에 없는 컬럼 — 400 이 맞다 (터지는 게 아니라)
    bad = httpx.post(f"{server}/v1/views/distribution",
                     json={"path": str(f), "cols": ["lx"]}, timeout=60)
    assert bad.status_code == 400

    ok = httpx.post(f"{server}/v1/views/distribution",
                    json={"path": str(f), "cols": ["lx"], "session_file": sf},
                    timeout=60).json()
    assert ok["items"][0]["column"] == "lx" and ok["items"][0]["kind"] == "numeric"


def test_live_analyze_flow(server, tmp_path_factory):
    """A1 → A2 → A3(캐시) → 실행 — 웹이 쓸 경로 그대로."""
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("an")
    f = d / "t.csv"
    rng = np.random.default_rng(2)
    pd.DataFrame({"arm": ["a"] * 60 + ["b"] * 60,
                  "y": np.r_[rng.normal(0, 1, 60), rng.normal(0.8, 1, 60)]}
                 ).to_csv(f, index=False)
    s = httpx.post(f"{server}/v1/sessions", json={"data": str(f)}, timeout=60).json()
    sf = s["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f), "cols": ["arm", "y"]}, timeout=60)
    for c, t in (("y", "continuous"), ("arm", "label")):
        httpx.post(f"{server}/v1/semantic/confirm",
                   json={"session_file": sf, "column": c, "type": t}, timeout=60)

    plan = httpx.post(f"{server}/v1/analyze/plan",
                      json={"session_file": sf, "question": "Q-01", "y": "y",
                            "group": "arm", "n_tests": 2, "apply": True},
                      timeout=120).json()
    assert plan["recorded"] and not plan["problems"]
    ids = {c["id"] for c in plan["candidates"]}
    assert "T-101" in ids

    c1 = httpx.get(f"{server}/v1/analyze/checks",
                   params={"session_file": sf}, timeout=120).json()
    assert c1["cached"] is False
    assert {x["id"] for x in c1["checks"]} >= {"C-01", "C-02"}
    c2 = httpx.get(f"{server}/v1/analyze/checks",
                   params={"session_file": sf}, timeout=120).json()
    assert c2["cached"] is True                    #  — 두 번째는 캐시

    r = httpx.post(f"{server}/v1/analyze/run",
                   json={"session_file": sf, "test": "T-101"}, timeout=120).json()
    assert r["p"] < 0.01 and r["effect"]["name"] == "Hedges g"
    assert any("보정" in n for n in r["notes"])


def test_live_derived_column_appears_in_type_inference(server, tmp_path_factory):
    """파생 컬럼을 만든 뒤 타입 추론을 다시 불러도 안 나오면 확정할 수가 없다."""
    import pandas as pd

    d = tmp_path_factory.mktemp("dv")
    f = d / "d.csv"
    pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0] * 30,
                  "b": [2.0, 4.0, 6.0, 8.0] * 30}).to_csv(f, index=False)
    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(f)},
                    timeout=60).json()["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f), "cols": ["a", "b"]}, timeout=60)

    def columns() -> set:
        r = httpx.get(f"{server}/v1/semantic/types",
                      params={"session_file": sf}, timeout=120).json()
        return {i["column"] for i in r["items"]}

    assert columns() == {"a", "b"}
    r = httpx.post(f"{server}/v1/derive/commit",
                   json={"session_file": sf, "expr": "a / b", "name": "ratio_ab"},
                   timeout=120)
    assert r.status_code == 200, r.text
    assert "ratio_ab" in columns()      # 다시 추론하면 새 컬럼이 들어와야 한다


def test_live_run_carries_assumptions_and_shared_headings(server, tmp_path_factory):
    """같은 기능은 TUI·웹이 같은 글자를 써야 한다 — 문구는 서버가 준다."""
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("as")
    f = d / "t.csv"
    rng = np.random.default_rng(5)
    pd.DataFrame({"arm": ["a"] * 60 + ["b"] * 60,
                  "y": np.r_[rng.normal(0, 1, 60), rng.normal(0.8, 1, 60)]}
                 ).to_csv(f, index=False)
    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(f)},
                    timeout=60).json()["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(f), "cols": ["arm", "y"]},
               timeout=60)
    for c, t in (("y", "continuous"), ("arm", "label")):
        httpx.post(f"{server}/v1/semantic/confirm",
                   json={"session_file": sf, "column": c, "type": t}, timeout=60)
    httpx.post(f"{server}/v1/analyze/plan",
               json={"session_file": sf, "question": "Q-01", "y": "y",
                     "group": "arm", "n_tests": 2, "apply": True}, timeout=120)

    r = httpx.post(f"{server}/v1/analyze/run",
                   json={"session_file": sf, "test": "T-101"}, timeout=120).json()
    ids = {a["id"] for a in r["assumptions"]}
    assert {"C-01", "C-15"} <= ids and "C-02" not in ids   # Welch: 등분산 아님
    assert r["assumptions_head"].startswith("이 검정이 요구하는 가정")

    m = httpx.get(f"{server}/v1/metrics", params={"session_file": sf},
                  timeout=120).json()
    # 화면이 제목을 지어내지 않게 서버가 준다
    assert m["head"]["support"].startswith("보조 지표 (Support)")
    assert m["head"]["guardrail"].startswith("가드레일 (Guardrail)")
    assert m["head"]["none"] and m["head"]["triad"]


def test_live_model_split_and_labels(server, tmp_path_factory, monkeypatch):
    """S186· REST — 웹 화면이 CLI·TUI 와 같은 판정을 받는지."""
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("mb")
    rng = np.random.default_rng(5)
    n = 600
    src = pd.DataFrame({"sid": [f"S{i:04d}" for i in range(n)],
                        "x1": rng.normal(0, 1, n),
                        "grp": rng.choice(["case", "control"], n)})
    src.to_csv(d / "source.csv", index=False)
    # 일부러 6:4 로 나눈다 (계획은 8:2)
    src.iloc[:360].to_csv(d / "train.csv", index=False)
    src.iloc[360:].to_csv(d / "test.csv", index=False)

    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(d / "source.csv")},
                    timeout=60).json()["session_file"]
    # 임시본 경로는 STATOP_HOME 에서 나온다 — 서버와 같은 곳에 써야 서버가 읽는다
    monkeypatch.setenv("STATOP_HOME", str(Path(sf).parents[2]))
    from statop.modeling.spec import ModelSpec, record

    record(sf, ModelSpec(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                         label_column="grp", positive_class="case",
                         sets={"train": str(d / "train.csv"),
                               "test": str(d / "test.csv")}))

    r = httpx.get(f"{server}/v1/model/split",
                  params={"session_file": sf, "key": "sid",
                          "expect": "train=8,test=2"}, timeout=120)
    assert r.status_code == 200, r.text
    r = r.json()
    by_id = [f for f in r["findings"] if f["id"] == "MB-C06"]
    assert by_id and by_id[0]["verdict"] == "fail" and by_id[0]["grade"] == "Gate"
    assert r["n_failed"] >= 1
    assert "S0000" not in str(r)          # 데이터 셀 미노출 (점진 노출)

    lab = httpx.get(f"{server}/v1/model/labels",
                    params={"session_file": sf}, timeout=120).json()
    flip = [f for f in lab["findings"] if f["verdict"] == "fail"]
    assert flip and any("case" in f["summary"] for f in flip)
    assert all(f["grade"] == "Diag" for f in lab["findings"])   # 막지는 않는다


def test_live_model_balance(server, tmp_path_factory, monkeypatch):
    """S188· REST — 웹이 CLI·TUI 와 같은 판정을 받는지. 전부 Diag."""
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("mb4")
    rng = np.random.default_rng(13)
    n = 800
    y = (rng.random(n) < 0.1).astype(int)
    df = pd.DataFrame({"sid": [f"S{i:04d}" for i in range(n)],
                       "x1": rng.normal(0, 1, n), "age": rng.normal(60, 8, n),
                       "site": np.where(y == 1, "B",
                                        np.where(rng.random(n) < 0.9, "A", "B")),
                       "y": y})
    df.to_csv(d / "source.csv", index=False)
    df.iloc[:600].to_csv(d / "train.csv", index=False)
    ext = df.iloc[600:].copy()
    ext["age"] += 12
    ext.to_csv(d / "ext.csv", index=False)

    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(d / "source.csv")},
                    timeout=60).json()["session_file"]
    monkeypatch.setenv("STATOP_HOME", str(Path(sf).parents[2]))
    from statop.modeling.spec import ModelSpec, record

    record(sf, ModelSpec(question="MB-Q01", tier="MB-M0", validation="kfold", k=5,
                         label_column="y",
                         sets={"train": str(d / "train.csv"),
                               "external": str(d / "ext.csv")}))

    r = httpx.get(f"{server}/v1/model/balance",
                  params={"session_file": sf, "meta": "site,age"}, timeout=120)
    assert r.status_code == 200, r.text
    b = r.json()
    assert all(f["grade"] == "Diag" for f in b["findings"])   # 막지 않는다
    joined = " ".join(f["summary"] for f in b["findings"])
    assert "MB-C12" in [f["id"] for f in b["findings"]]
    assert "site" in joined                                   # 숨은 불균형을 지목
    assert "S0000" not in str(b)                              # 데이터 셀 미노출


def test_live_columns_shows_the_pre_processing_origin(server, tmp_path_factory):
    """S172b — 가공 파일을 기준으로 작업하면 **원본이 어디였는지 잊는다.**

    다시 열거나 더 불러오려면 그 경로가 필요하므로, 경로가 드러나는 자리마다 함께 보인다.
    """
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("origin")
    raw = d / "raw.csv"
    rng = np.random.default_rng(2)
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(40)],
                  "v": rng.normal(0, 1, 40).round(3)}).to_csv(raw, index=False)

    # 원본에는 아무 말도 붙지 않는다
    r = httpx.get(f"{server}/v1/datasets/columns", params={"path": str(raw)},
                  timeout=60).json()
    assert r["file"]["origin"] == ""

    # 가공 파일에는 원본 경로가 붙는다
    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(raw)},
                    timeout=60).json()["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(raw), "cols": ["sid", "v"]},
               timeout=60)
    from statop.export import export_trimmed
    from statop.session.core import load_session, save_session

    doc = load_session(sf)
    out = export_trimmed(doc, d / "proc.csv")
    save_session(doc)

    r2 = httpx.get(f"{server}/v1/datasets/columns", params={"path": str(out.path)},
                   timeout=60).json()
    assert str(raw) in r2["file"]["origin"]
    assert "가공 전" in r2["file"]["origin"] or "before processing" in r2["file"]["origin"]


def test_root_takes_you_to_the_web_page(server):
    """`/` 가 맨 404 를 내면 "서버가 안 떴다"로 읽힌다 (실제로 그렇게 읽혔다)."""
    from statop.api.app import ui_built

    r = httpx.get(server + "/", follow_redirects=False)
    if ui_built():
        assert r.status_code in (301, 302, 307, 308)
        assert r.headers["location"].rstrip("/").endswith("/ui")
        assert httpx.get(server + "/", follow_redirects=True).status_code == 200
    else:
        # 빌드가 없으면 어디로 가야 하는지 말해 준다 — 빈 404 로 끝내지 않는다
        assert r.status_code == 200 and r.json()["detail"]


def test_a7_off_does_not_take_down_a1_to_a6(server, tmp_path_factory):
    """LLM 이 안 붙어 있으면 **A7 만** 비활성 — 나머지 분석은 그대로 돈다 .

    501 인 이유: "이 서버에 LLM 이 없다"는 서버 사정이다. 400 이면 화면이
    "내가 뭘 잘못 보냈나"로 읽고, 패널을 끌 근거로도 못 쓴다.
    """
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("a7")
    raw = d / "g.csv"
    rng = np.random.default_rng(5)
    n = 120
    g = rng.choice(["case", "control"], n)
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)], "arm": g,
                  "y": (rng.normal(0, 1, n) + (g == "case") * 0.7).round(3)}
                 ).to_csv(raw, index=False)

    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(raw)},
                    timeout=60).json()["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(raw),
                     "cols": ["sid", "arm", "y"]}, timeout=60)
    for col, typ in (("sid", "id"), ("arm", "label"), ("y", "continuous")):
        httpx.post(f"{server}/v1/semantic/confirm",
                   json={"session_file": sf, "column": col, "type": typ},
                   timeout=60)
    httpx.post(f"{server}/v1/analyze/plan",
               json={"session_file": sf, "question": "Q-01", "y": "y",
                     "group": "arm", "apply": True}, timeout=60)
    r = httpx.post(f"{server}/v1/analyze/run",
                   json={"session_file": sf, "test": "T-104"}, timeout=120)
    assert r.status_code == 200, r.text

    # A7 — 엔드포인트가 안 붙은 서버이므로 501
    st = httpx.get(f"{server}/v1/hypothesis/qwen/status",
                   params={"session_file": sf}, timeout=60).json()
    assert st["available"] is False and st["why"], st
    ask = httpx.post(f"{server}/v1/hypothesis/qwen",
                     json={"session_file": sf}, timeout=60)
    assert ask.status_code == 501, ask.text

    # A1~A6 — 같은 세션에서 전부 200
    for url, params in (("/v1/analyze/checks", {"session_file": sf}),
                        ("/v1/scores", {"session_file": sf}),
                        ("/v1/hypothesis", {"session_file": sf}),
                        ("/v1/robust", {"session_file": sf, "draws": 30}),
                        ("/v1/hypothesis/references", {"session_file": sf})):
        got = httpx.get(server + url, params=params, timeout=180)
        assert got.status_code == 200, f"{url} → {got.status_code} {got.text[:200]}"


def test_unconfirming_a_type_frees_it_again(server, tmp_path_factory):
    """웹에서도 확정을 되돌릴 수 있어야 한다 — CLI 와 같은 조작을 남긴다."""
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("unconf")
    raw = d / "u.csv"
    rng = np.random.default_rng(4)
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(60)],
                  "v": rng.normal(0, 1, 60).round(3)}).to_csv(raw, index=False)
    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(raw)},
                    timeout=60).json()["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(raw), "cols": ["sid", "v"]},
               timeout=60)
    httpx.post(f"{server}/v1/semantic/confirm",
               json={"session_file": sf, "column": "v", "type": "continuous"},
               timeout=60)

    def confirmed() -> dict:
        r = httpx.get(f"{server}/v1/semantic/types",
                      params={"session_file": sf}, timeout=120).json()
        return {i["column"]: i["confirmed"] for i in r["items"]}

    assert confirmed()["v"] == "continuous"
    r = httpx.post(f"{server}/v1/semantic/unconfirm",
                   json={"session_file": sf, "column": "v"}, timeout=60)
    assert r.status_code == 200, r.text
    assert confirmed()["v"] is None

    # 확정한 적 없는 것은 취소할 것도 없다 — 조용히 넘어가지 않는다
    again = httpx.post(f"{server}/v1/semantic/unconfirm",
                       json={"session_file": sf, "column": "v"}, timeout=60)
    assert again.status_code == 400


def test_a_long_distribution_does_not_freeze_the_server(server):
    """무거운 계산이 도는 동안에도 다른 클릭이 받아져야 한다.

    이 엔드포인트는 async 라, 계산을 그 자리에서 하면 이벤트 루프가 잡혀 **모든**
    요청이 줄을 선다 — 웹에서 기능이 통째로 멈춘 것으로 보인다.
    """
    import threading

    path = str(DATA / "synth_long.parquet")
    sf = httpx.post(f"{server}/v1/sessions", json={"data": path},
                    timeout=60).json()["session_file"]
    cols = httpx.get(f"{server}/v1/datasets/columns",
                     params={"path": path, "sample_n": 3000, "limit": 40},
                     timeout=180).json()["items"]
    names = [c["column"] for c in cols]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": path, "cols": names}, timeout=120)

    done = threading.Event()

    def heavy() -> None:
        try:
            httpx.post(f"{server}/v1/views/distribution",
                       json={"path": path, "cols": names, "session_file": sf,
                             "sample_n": 10_000}, timeout=180)
        finally:
            done.set()

    t = threading.Thread(target=heavy)
    t.start()
    try:
        time.sleep(0.05)
        for _ in range(5):          # 도는 동안 두드려 본다
            r = httpx.get(f"{server}/health", timeout=5)
            assert r.status_code == 200
            if done.is_set():
                break
    finally:
        t.join(timeout=180)


def test_the_web_gets_the_same_five_numbers_with_names(server, tmp_path_factory):
    """웹도 같은 글자를 본다 — 라벨을 화면이 지어내면 터미널과 말이 달라진다."""
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("five")
    raw = d / "q.csv"
    rng = np.random.default_rng(9)
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(200)],
                  "v": rng.normal(10, 3, 200).round(3)}).to_csv(raw, index=False)
    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(raw)},
                    timeout=60).json()["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(raw), "cols": ["sid", "v"]},
               timeout=60)
    r = httpx.post(f"{server}/v1/views/distribution",
                   json={"path": str(raw), "cols": ["v"], "session_file": sf},
                   timeout=60).json()["items"][0]

    labels = [x["label"] for x in r["stats"]]
    assert labels == ["최소", "Q1 (하위 25%)", "Q2 (중앙값)", "Q3 (상위 25%)", "최대",
                      "IQR (Q3−Q1)", "Q1−1.5×IQR", "Q3+1.5×IQR"]
    q = r["quartiles"]
    vals = {x["key"]: x["value"] for x in r["stats"]}
    assert vals["q_fence_hi"] == pytest.approx(q[3] + 1.5 * (q[3] - q[1]))
    assert r["fence_note"]


def test_the_scores_list_says_which_metric_is_the_goal(server, tmp_path_factory):
    """찾기와 목록이 한 카드가 되려면, 목록이 **지금 Goal 이 무엇인지** 알아야 한다."""
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("goal")
    raw = d / "g.csv"
    rng = np.random.default_rng(11)
    n = 80
    g = rng.choice(["a", "b"], n)
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(n)], "arm": g,
                  "v": (rng.normal(0, 1, n) + (g == "a") * 0.6).round(3)}
                 ).to_csv(raw, index=False)
    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(raw)},
                    timeout=60).json()["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(raw),
                     "cols": ["sid", "arm", "v"]}, timeout=60)
    for col, typ in (("sid", "id"), ("arm", "label"), ("v", "continuous")):
        httpx.post(f"{server}/v1/semantic/confirm",
                   json={"session_file": sf, "column": col, "type": typ}, timeout=60)

    first = httpx.get(f"{server}/v1/scores", params={"session_file": sf},
                      timeout=120).json()
    assert first["goal"] is None, "정한 적 없는데 Goal 이 있다"
    pick = next(s for s in first["scores"] if s["verdict"] != "red")

    httpx.post(f"{server}/v1/metrics/goal",
               json={"session_file": sf, "score": pick["id"]}, timeout=60)
    after = httpx.get(f"{server}/v1/scores", params={"session_file": sf},
                      timeout=120).json()
    assert after["goal"] and after["goal"]["score"] == pick["id"]

    # 언제든 다른 것으로 바꿀 수 있어야 한다
    other = next(s for s in after["scores"]
                 if s["verdict"] != "red" and s["id"] != pick["id"])
    httpx.post(f"{server}/v1/metrics/goal",
               json={"session_file": sf, "score": other["id"]}, timeout=60)
    again = httpx.get(f"{server}/v1/scores", params={"session_file": sf},
                      timeout=120).json()
    assert again["goal"]["score"] == other["id"]


def test_a_derived_log_column_offers_log_scale_first(server, tmp_path_factory):
    """값만 보면 log(x) 도 그냥 연속값이다 — **수식이 아는 것**을 웹도 써야 한다."""
    import numpy as np
    import pandas as pd

    d = tmp_path_factory.mktemp("lg")
    raw = d / "f.csv"
    rng = np.random.default_rng(6)
    pd.DataFrame({"sid": [f"S{i:03d}" for i in range(80)],
                  "frac_a": rng.random(80).round(4)}).to_csv(raw, index=False)
    sf = httpx.post(f"{server}/v1/sessions", json={"data": str(raw)},
                    timeout=60).json()["session_file"]
    httpx.post(f"{server}/v1/views/import",
               json={"session_file": sf, "path": str(raw), "cols": ["sid", "frac_a"]},
               timeout=60)
    httpx.post(f"{server}/v1/derive/commit",
               json={"session_file": sf, "expr": "log(frac_a + eps)", "name": "lg_a",
                     "eps": 1e-6}, timeout=60)

    items = httpx.get(f"{server}/v1/semantic/types", params={"session_file": sf},
                      timeout=180).json()["items"]
    lg = next(i for i in items if i["column"] == "lg_a")
    assert [c["type"] for c in lg["candidates"]][0] == "log-scale", lg["candidates"]
    assert lg["needs_confirm"], "수식에서 온 타입은 사람이 확정해야 한다"
    # 원본 컬럼은 그대로 — 수식 힌트가 남의 컬럼까지 바꾸면 안 된다
    frac = next(i for i in items if i["column"] == "frac_a")
    assert [c["type"] for c in frac["candidates"]][0] != "log-scale"
