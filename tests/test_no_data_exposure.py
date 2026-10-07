"""검수 기준 '점진 노출': 어떤 CLI 경로에서도 데이터 셀 값이 출력되지 않는다 ."""

from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from statop.cli import app

DATA = Path(__file__).parent / "data"

# 셀에만 존재하고 컬럼명에는 없는 센티널 값들
SENTINELS = ["SECRET_A", "값비밀", "987654.321", "PT000001", "siteA", "2024-01-01"]


@pytest.fixture()
def sentinel_csv(tmp_path):
    df = pd.DataFrame(
        {
            "colA": ["SECRET_A1", "SECRET_A2", "SECRET_A3", "SECRET_A4"],
            "colB": [987654.321, 987654.321, 987654.321, None],
            "colC": ["값비밀1", "값비밀2", None, "값비밀3"],
        }
    )
    p = tmp_path / "sentinel.csv"
    df.to_csv(p, index=False)
    return p


OPTION_COMBOS = [
    [],
    ["--sort", "missing"],
    ["--sort", "unique"],
    ["--sort", "name"],
    ["--grep", "col"],
    ["--limit", "2"],
    ["--limit", "999"],
    ["--grep", "col", "--sort", "missing", "--limit", "3"],
]


@pytest.mark.parametrize("opts", OPTION_COMBOS)
def test_no_cell_values_in_terminal(sentinel_csv, opts):
    result = CliRunner().invoke(app, ["columns", str(sentinel_csv), *opts])
    assert result.exit_code == 0
    assert "colA" in result.output  # 컬럼명은 보인다
    for s in SENTINELS:
        assert s not in result.output, f"데이터 셀 값 유출: {s!r} (opts={opts})"


def test_no_cell_values_in_out_file(sentinel_csv, tmp_path):
    out = tmp_path / "cols.tsv"
    result = CliRunner().invoke(app, ["columns", str(sentinel_csv), "--out", str(out)])
    assert result.exit_code == 0
    content = out.read_text()
    for s in SENTINELS:
        assert s not in content, f"--out 파일로 셀 값 유출: {s!r}"


def test_no_cell_values_on_synth(monkeypatch):
    """실데이터 규모(2,000컬럼)에서도 id·그룹·날짜 셀 값이 안 보인다."""
    result = CliRunner().invoke(
        app, ["columns", str(DATA / "synth_long.parquet"), "--sample-n", "3000", "--limit", "999"]
    )
    assert result.exit_code == 0
    for s in ["PT000001", "siteA", "siteB", "2024-01-01"]:
        assert s not in result.output


def test_api_responses_never_carry_data_cells(tmp_path, monkeypatch):
    """S079 — **렌더 경로 0**: 웹 화면은 API 응답만 그린다.

    응답에 셀 값이 없으면 화면에 나올 길이 없다. CLI 는 이미 위에서 훑었으므로,
    여기서는 웹이 실제로 부르는 GET 경로를 전부 돌려 **원자료 값이 한 칸도 섞이지
    않는지** 본다 ( 점진 노출).
    """
    import json

    import numpy as np
    import pandas as pd
    from fastapi.testclient import TestClient

    from statop.api.app import app
    from statop.shell.screen import Screen

    monkeypatch.setenv("STATOP_HOME", str(tmp_path / "home"))
    rng = np.random.default_rng(5)
    n = 60
    # 찾기 쉬운 **고유한 문자열**을 심는다 — 우연히 섞여도 눈에 띄게
    secrets = [f"ZZTOP{i:03d}" for i in range(n)]
    df = pd.DataFrame({"sid": secrets, "arm": ["case", "control"] * (n // 2),
                       "value": rng.normal(0, 1, n).round(3),
                       "prob": rng.random(n).round(4)})
    path = tmp_path / "secret.csv"
    df.to_csv(path, index=False)

    sc = Screen()
    sc.open_path(str(path))
    sc.toggle_page()
    sc.import_picked()
    session = str(sc.session_file)

    client = TestClient(app)
    routes = [
        ("/v1/datasets/columns", {"path": str(path), "sample_n": 60}),
        ("/v1/views/selected", {"session_file": session}),
        ("/v1/sessions/state", {"session_file": session}),
        ("/v1/semantic/types", {"session_file": session}),
        ("/v1/model/leak", {"session_file": session}),
        ("/v1/model/labels", {"session_file": session}),
        ("/v1/model/balance", {"session_file": session, "meta": "arm"}),
        ("/v1/model/prep", {"session_file": session}),
        ("/v1/model/eval", {"session_file": session}),
        ("/v1/model/specific", {"session_file": session}),
        ("/v1/model/repro", {"session_file": session}),
        ("/v1/model/triad", {"session_file": session}),
        ("/v1/find/questions", {}),
    ]
    seen = 0
    for route, params in routes:
        r = client.get(route, params=params)
        if r.status_code >= 500:
            raise AssertionError(f"{route}: {r.status_code} {r.text[:200]}")
        if r.status_code != 200:
            continue          # 전제가 없어 400 인 것은 정상 (구성 미확정 등)
        seen += 1
        body = json.dumps(r.json(), ensure_ascii=False)
        leaked = [s for s in secrets if s in body]
        assert not leaked, f"{route}: 데이터 셀 유출 {leaked[:3]}"
    assert seen >= 5, f"확인한 경로가 {seen}개뿐 — 검사가 비어 있다"
