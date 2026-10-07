from pathlib import Path

from statop.io.profile import profile_columns

DATA = Path(__file__).parent / "data"


def test_profile_columns_stats():
    prof = profile_columns(DATA / "synth_long.parquet", sample_n=3000).set_index("column")
    assert len(prof) == 2_000
    assert prof.loc["patient_id", "n_unique"] == 3000  # id: 전부 고유
    assert prof.loc["site", "n_unique"] == 3
    assert prof.loc["patient_id", "missing_rate"] == 0.0
    # 주입한 최대 결측률(30%, site 의존은 그 이상)이 샘플에서 관측돼야 함
    assert 0.25 < prof["missing_rate"].max() < 0.45
    assert prof["estimated"].all()  # 3000 < 10000행 → 추정치 플래그


def test_profile_returns_stats_not_data():
    """프로파일 결과에 데이터 셀이 섞여 나오지 않는다 (점진 노출의 씨앗)."""
    prof = profile_columns(DATA / "synth_long.parquet", sample_n=3000)
    assert set(prof.columns) == {"column", "dtype", "missing_rate", "n_unique", "estimated", "sample_rows"}
