"""프로세스 풀에서 실행되는 무거운 작업들 .

프로세스 간 전달을 위해 **최상위 함수 + 기본 타입**만 쓴다 (DataFrame을 직접 돌려보내면
직렬화 비용이 크므로, 여기서 표시용 자료구조까지 만들어 반환한다).
"""

from pathlib import Path


def profile_task(path: str, sample_n: int, transposed: bool) -> dict:
    """컬럼 프로파일을 계산해 표시용 dict로 반환한다 (데이터 셀 없음)."""
    from statop.io.meta import estimate_rows, open_meta
    from statop.io.profile import profile_columns, profile_frame

    p = Path(path)
    meta = open_meta(p)
    if transposed:
        from statop.io.transpose import transpose_table

        t = transpose_table(p)
        prof = profile_frame(t)
        n_rows, rows_estimated = t.shape[0], False
    else:
        prof = profile_columns(p, sample_n=sample_n)
        if meta.n_rows is not None:
            n_rows, rows_estimated = meta.n_rows, False
        else:
            n_rows, rows_estimated = estimate_rows(p), True

    return {
        "fmt": meta.fmt,
        "size_mb": p.stat().st_size / 1e6,
        "n_rows": n_rows,
        "rows_estimated": rows_estimated,
        "sample_rows": int(prof["sample_rows"].iloc[0]) if len(prof) else 0,
        "sample_estimated": bool(prof["estimated"].iloc[0]) if len(prof) else False,
        "records": prof[["column", "dtype", "missing_rate", "n_unique"]].to_dict("records"),
    }


def distribution_task(path: str, columns: list[str], sample_n: int) -> list[dict]:
    """선택 컬럼의 분포 요약 (M0-3). 클릭할 때만 호출된다."""
    from statop.io.distribution import distributions

    return distributions(path, columns, sample_n=sample_n)
