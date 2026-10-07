import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import statop
from statop.api.app import app

DATA = Path(__file__).parent / "data"
client = TestClient(app)


@pytest.fixture(autouse=True)
def statop_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("statop_home")
    monkeypatch.setenv("STATOP_HOME", str(home))
    return home


@pytest.fixture()
def small(tmp_path):
    """가벼운 csv — 단위 테스트는 무거운 파일을 건드리지 않는다."""
    p = tmp_path / "small.csv"
    p.write_text("patient_id,site,label\nPT0001,siteA,0\nPT0002,siteB,1\n")
    return p


def test_health():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["statop_version"] == statop.__version__
    assert len(body["rules_version"]) == 12


def test_create_session_and_register_dataset(small, tmp_path):
    other = tmp_path / "other.csv"
    other.write_text("a,b\n1,2\n")
    r = client.post("/v1/sessions", json={"data": str(small)})
    assert r.status_code == 200
    s = r.json()
    assert s["session_id"].startswith("s_")
    assert s["source_id"] == "d1"
    assert s["sources"][0]["hash"]["mode"] == "partial"
    assert "부분 해시" in s["notice"]
    assert "statop " not in s["notice"]           # 인터페이스 중립 (호출법은 껍데기가 덧붙임)

    # 같은 경로 재등록은 id 재사용, 다른 파일은 새 id
    r = client.post("/v1/datasets", json={"session_file": s["session_file"],
                                          "path": str(small)})
    assert r.json()["source_id"] == "d1"
    r = client.post("/v1/datasets", json={"session_file": s["session_file"],
                                          "path": str(other)})
    assert r.json()["source_id"] == "d2"
    doc = json.loads(Path(s["session_file"]).read_text())
    assert [x["id"] for x in doc["sources"]] == ["d1", "d2"]


def test_create_session_bad_paths():
    assert client.post("/v1/sessions", json={"project": "/no/such/dir"}).status_code == 400
    assert client.post("/v1/sessions", json={"data": "/no/such/file.csv"}).status_code == 404
