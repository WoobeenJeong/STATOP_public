"""무결성 검증(Integrity) — 두 파일의 전체 해시 대조 + 다르면 어디가 얼마나 다른지 요약 .

부분 해시(빠른 확인)의 짝: 여기는 파일 전체를 읽으므로 느리지만 정확하다.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

CHUNK = 4 * 1024 * 1024

_TABULAR = {".csv", ".tsv", ".parquet"}


def full_hash(path: str | Path) -> str:
    """파일 전체의 sha256."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class FileDiff:
    identical: bool
    size_a: int
    size_b: int
    chunks_total: int  # 큰 쪽 기준 4MB 구간 수
    chunks_differ: int
    first_diff_offset: int | None  # 첫 차이 바이트 위치 (구간 단위 정밀도 아님 — 바이트 단위)
    table_diff: dict | None  # 표 형식일 때: 행수·컬럼 차이


def compare_files(a: str | Path, b: str | Path) -> FileDiff:
    """두 파일을 구간(4MB) 단위로 전체 대조한다."""
    a, b = Path(a), Path(b)
    size_a, size_b = a.stat().st_size, b.stat().st_size

    chunks_total = 0
    chunks_differ = 0
    first_diff = None
    offset = 0
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            ca, cb = fa.read(CHUNK), fb.read(CHUNK)
            if not ca and not cb:
                break
            chunks_total += 1
            if ca != cb:
                chunks_differ += 1
                if first_diff is None:
                    n = min(len(ca), len(cb))
                    i = next((i for i in range(n) if ca[i] != cb[i]), n)
                    first_diff = offset + i
            offset += max(len(ca), len(cb))

    identical = size_a == size_b and chunks_differ == 0

    table_diff = None
    if not identical and a.suffix.lower() in _TABULAR and b.suffix.lower() in _TABULAR:
        from statop.io.meta import estimate_rows, open_meta

        try:
            ma, mb = open_meta(a), open_meta(b)
        except Exception as e:  # 한쪽이 표로 읽히지 않음 — 손상 자체가 진단 정보
            return FileDiff(identical, size_a, size_b, chunks_total, chunks_differ,
                            first_diff, {"unreadable": str(e)})
        rows_a = ma.n_rows if ma.n_rows is not None else estimate_rows(a)
        rows_b = mb.n_rows if mb.n_rows is not None else estimate_rows(b)
        set_a, set_b = set(ma.columns), set(mb.columns)
        table_diff = {
            "rows_a": rows_a,
            "rows_b": rows_b,
            "rows_estimated": ma.n_rows is None or mb.n_rows is None,
            "cols_only_a": sorted(set_a - set_b),
            "cols_only_b": sorted(set_b - set_a),
            "n_cols_a": len(ma.columns),
            "n_cols_b": len(mb.columns),
        }
    return FileDiff(identical, size_a, size_b, chunks_total, chunks_differ, first_diff, table_diff)


# ──  표 상세 대조 (Table diff) ──────────────────────────
# 전체 읽기다. 파일 두 개를 통째로 메모리에 올리므로 **명시 호출 전용**이며,
# 자동으로 돌지 않는다 (불러오기·저장 경로에서는 부분 해시만 본다).
MAX_SHOWN = 5          # 5행 요약 규칙 — 목록이 길면 아무도 안 본다


@dataclass
class TableDiff:
    identical: bool
    key: str
    rows_a: int = 0
    rows_b: int = 0
    rows_added: list = field(default_factory=list)      # b 에만 있는 키
    rows_removed: list = field(default_factory=list)    # a 에만 있는 키
    cols_added: list = field(default_factory=list)
    cols_removed: list = field(default_factory=list)
    cells_changed: int = 0
    changed_by_column: dict = field(default_factory=dict)
    examples: list = field(default_factory=list)        # --show-values 일 때만 채운다
    duplicate_keys: dict = field(default_factory=dict)  # a/b 각각의 중복 키 수
    note: str = ""
    # 컬럼 하나하나가 **얼마나** 다른지 . 개수만으로는 "397행 중 2행"인지
    # "397행 중 397행"인지 알 수 없다 — 둘은 전혀 다른 이야기다
    columns: list = field(default_factory=list)
    same_columns: list = field(default_factory=list)    # 대조했고 **전부 같았던** 컬럼
    unmatched: list = field(default_factory=list)       # 짝이 없어 대조 못 한 것 + 사유


def _read_table(path: Path, columns: list[str] | None = None):  # noqa: ANN202
    import pandas as pd

    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path, columns=columns)
    sep = "\t" if suffix in (".tsv", ".tab") else ","
    return pd.read_csv(path, sep=sep, usecols=columns)


def _column_row(col: str, other: str, ia, ib, mask) -> dict:  # noqa: ANN001
    """한 컬럼의 차이 요약 — 몇 행이 다른지, 숫자면 **얼마나** 다른지.

    숫자가 아닌 컬럼에 크기를 붙이지 않는다 — `COAD → UNKNOWN` 의 크기는 없다.
    """
    import numpy as np
    import pandas as pd

    n, n_diff = int(len(mask)), int(mask.sum())
    row = {"column": col, "matched_to": other if other != col else "",
           "n": n, "n_diff": n_diff,
           "ratio": (n_diff / n) if n else 0.0,
           "kind": "other", "median_abs": None, "max_abs": None, "example": None}
    if not n_diff:
        return row

    k = mask.index[mask]
    row["example"] = {"key": str(k[0]), "from": _cell(ia.at[k[0], col]),
                      "to": _cell(ib.at[k[0], other])}
    na = pd.to_numeric(ia.loc[k, col], errors="coerce")
    nb = pd.to_numeric(ib.loc[k, other], errors="coerce")
    d = (nb - na).abs().dropna()
    if len(d) == len(k) and len(d):
        row["kind"] = "numeric"
        row["median_abs"] = float(np.median(d))
        row["max_abs"] = float(d.max())
    return row


def compare_tables(a: str | Path, b: str | Path, key: str | None = None,
                   columns: list[str] | None = None,
                   show_values: bool = False,
                   pairs: dict | None = None) -> TableDiff:
    """두 표를 **키 컬럼 기준으로** 맞춰 행·컬럼·셀 차이를 낸다 .

    키를 안 주면 첫 컬럼을 쓴다. 키가 중복되면 행을 1:1로 맞출 수 없으므로 그 사실을
    먼저 알리고 셀 대조는 하지 않는다 — 억지로 맞추면 없는 차이를 만들어 낸다.

    columns 를 주면 그 컬럼만 읽어 비교한다 ("이 컬럼들만 같으면 된다").

    pairs 는 **이름이 다른 같은 컬럼**을 이어 준다 ({A의 이름: B의 이름}).
    `log2_frac_v1` 과 `log2_frac_v2` 처럼 판본만 다른 경우, 짝을 지어 주지 않으면
    "한쪽에만 있는 컬럼" 둘로 갈려 대조에서 통째로 빠진다.
    """
    import pandas as pd

    from statop.messages import msg

    pa, pb = Path(a), Path(b)
    need_a = need_b = None
    if columns:
        need_a = list(dict.fromkeys([key, *columns])) if key else list(columns)
        # **B 에서는 B 의 이름으로 읽어야 한다.** 짝지어 둔 컬럼은 이름이 다르므로
        # A 의 이름 그대로 읽으려다 "컬럼이 없다"로 터졌다 (실제로 났다)
        need_b = list(dict.fromkeys((pairs or {}).get(c, c) for c in need_a))
    da, db = _read_table(pa, need_a), _read_table(pb, need_b)

    key = key or (need[0] if need else str(da.columns[0]))
    for frame, name in ((da, pa.name), (db, pb.name)):
        if key not in frame.columns:
            raise ValueError(msg("tablediff_no_key", key=key, file=name))

    out = TableDiff(identical=False, key=key, rows_a=len(da), rows_b=len(db))
    # 짝지어 준 이름은 "한쪽에만 있는 컬럼"이 아니다
    pairs = {k: v for k, v in (pairs or {}).items()
             if k in da.columns and v in db.columns}
    paired_b = set(pairs.values())
    out.cols_added = [c for c in db.columns
                      if c not in set(da.columns) and c not in paired_b]
    out.cols_removed = [c for c in da.columns
                        if c not in set(db.columns) and c not in pairs]

    ka, kb = da[key].astype(str), db[key].astype(str)
    dup_a, dup_b = int(ka.duplicated().sum()), int(kb.duplicated().sum())
    sa, sb = set(ka), set(kb)
    out.rows_added = sorted(sb - sa)
    out.rows_removed = sorted(sa - sb)

    if dup_a or dup_b:
        # 키가 중복이면 어느 행이 어느 행의 짝인지 정할 수 없다
        out.duplicate_keys = {pa.name: dup_a, pb.name: dup_b}
        out.note = msg("tablediff_dup_key", key=key, a=dup_a, b=dup_b)
        out.identical = False
        return out

    # A 의 컬럼 → B 의 컬럼. 이름이 같으면 그대로, 짝지어 준 것은 그쪽으로
    mapped = {c: (pairs.get(c) or c) for c in da.columns if c != key}
    mapped = {a_: b_ for a_, b_ in mapped.items() if b_ in set(db.columns)}
    for c in da.columns:
        if c != key and c not in mapped:
            out.unmatched.append({"column": c, "side": "a",
                                  "why": msg("tablediff_only_a", file=pb.name)})
    for c in db.columns:
        if c != key and c not in set(mapped.values()):
            out.unmatched.append({"column": c, "side": "b",
                                  "why": msg("tablediff_only_b", file=pa.name)})

    common = sorted(sa & sb)
    if common and mapped:
        ia = da.set_index(ka).loc[common, list(mapped)]
        ib = db.set_index(kb).loc[common, list(mapped.values())]
        by_col = {}
        for a_, b_ in mapped.items():
            # NaN == NaN 을 같음으로 본다 — 결측을 차이로 세면 전부 다르다고 나온다
            va, vb = ia[a_], ib[b_]
            mask = ~((va.to_numpy() == vb.to_numpy()) | (va.isna() & vb.isna()).to_numpy())
            mask = pd.Series(mask, index=ia.index)
            row = _column_row(a_, b_, ia, ib, mask)
            out.columns.append(row)
            if row["n_diff"]:
                by_col[a_] = row["n_diff"]
            else:
                out.same_columns.append(a_)
            if show_values and row["n_diff"]:
                for k in mask.index[mask][:MAX_SHOWN]:
                    out.examples.append({"key": str(k), "column": a_,
                                         "from": _cell(ia.at[k, a_]),
                                         "to": _cell(ib.at[k, b_])})
        out.cells_changed = int(sum(by_col.values()))
        out.changed_by_column = dict(sorted(by_col.items(), key=lambda kv: -kv[1]))
        out.columns.sort(key=lambda r: (-r["n_diff"], r["column"]))
    out.identical = not (out.rows_added or out.rows_removed or out.cols_added
                         or out.cols_removed or out.cells_changed)
    del pd
    return out


def column_view(a: str | Path, b: str | Path, key: str, column: str,
                pairs: dict | None = None, width: int = 40) -> dict:
    """한 컬럼을 **A 와 B 로 겹쳐 본다** — 얼마나 다른지 글자만으로는 알 수 없다.

    "바뀐 셀 2개"까지는 알겠는데 **어디가 어떻게** 옮겨갔는지가 없었다. 개형을 겹치고,
    평균·중앙·최소·최대·IQR 을 나란히 놓고, 분포 거리까지 같이 낸다.

    그림은 여기서 문자열로 만든다 — CLI·TUI 가 같은 그림을 본다 .
    """
    import numpy as np
    import pandas as pd

    from statop.messages import msg
    from statop.render.chart import strip_plot
    from statop.render.spark import bar

    pairs = pairs or {}
    other = pairs.get(column, column)
    da = _read_table(Path(a), [key, column])
    db = _read_table(Path(b), list(dict.fromkeys([key, other])))
    ia = da.set_index(da[key].astype(str))[column]
    ib = db.set_index(db[key].astype(str))[other]
    common = sorted(set(ia.index) & set(ib.index))
    va, vb = ia.loc[common], ib.loc[common]

    head = [msg("colview_head", col=(msg("colview_paired", col=column, other=other)
                                     if other != column else column),
                n=f"{len(common):,}")]
    la, lb = msg("colview_a"), msg("colview_b")
    same = ((va.to_numpy() == vb.to_numpy()) | (va.isna() & vb.isna()).to_numpy())
    n_diff = int((~same).sum())
    if not n_diff:
        return {"column": column, "kind": "same", "n": len(common), "n_diff": 0,
                "lines": head + ["  " + msg("colview_same")]}

    na, nb = pd.to_numeric(va, errors="coerce"), pd.to_numeric(vb, errors="coerce")
    numeric = not (na.isna().any() or nb.isna().any())

    def fmt(v: float) -> str:
        if v and abs(v) < 1e-4:
            return f"{v:.2e}"
        return f"{v:,.4g}"

    def stats(x) -> dict:  # noqa: ANN001
        q1, q3 = np.percentile(x, [25, 75])
        return {"mean": float(np.mean(x)), "med": float(np.median(x)),
                "mn": float(np.min(x)), "mx": float(np.max(x)), "iqr": float(q3 - q1)}

    def stat_block(x, y, title: str = "") -> list[str]:  # noqa: ANN001
        sa, sb = stats(x), stats(y)
        out = ([f"  {title}"] if title else []) + ["  " + msg("colview_stat_head")]
        for who, st in ((la, sa), (lb, sb)):
            out.append("  " + msg("colview_stat_row", who=who, **{k: fmt(v)
                                                                  for k, v in st.items()}))
        out.append("  " + msg("colview_stat_diff", who=msg("colview_diff_label"),
                              **{k: fmt(sb[k] - sa[k]) for k in sa}))
        return out

    lines = list(head)
    if numeric:
        lines += strip_plot({la: na.tolist(), lb: nb.tolist()}, width)
        lines += [""] + stat_block(na.to_numpy(), nb.to_numpy())
        # **다른 행만** 따로 — 전체로 보면 두 값이 섞여 차이가 묻힌다
        m = ~same
        lines += [""] + stat_block(na.to_numpy()[m], nb.to_numpy()[m],
                                   msg("colview_only_diff", n=n_diff))
        from scipy.stats import ks_2samp, wasserstein_distance

        lines += ["", "  " + msg("colview_dist_head"),
                  "    " + msg("colview_ks",
                               v=float(ks_2samp(na, nb,
                                                 method="asymp").statistic)),
                  "    " + msg("colview_w1",
                               v=float(wasserstein_distance(na, nb)))]
    else:
        pa = va.astype(str).value_counts(normalize=True)
        pb = vb.astype(str).value_counts(normalize=True)
        keys = pa.index.union(pb.index)
        lines += ["  " + msg("colview_not_numeric"), "",
                  "  " + msg("colview_levels_head")]
        for lv in sorted(keys, key=lambda k: -pa.get(k, 0.0)):
            ra, rb = float(pa.get(lv, 0.0)), float(pb.get(lv, 0.0))
            lines.append(f"  {str(lv)[:18]:<18s} {bar(ra, width // 2)} {ra:>6.1%}  {la}")
            lines.append(f"  {'':<18s} {bar(rb, width // 2)} {rb:>6.1%}  {lb}")
        tv = float(0.5 * np.abs(pa.reindex(keys, fill_value=0.0).to_numpy()
                                - pb.reindex(keys, fill_value=0.0).to_numpy()).sum())
        lines += ["", "  " + msg("colview_dist_head"), "    " + msg("colview_tv", v=tv)]

    return {"column": column, "matched_to": other if other != column else "",
            "kind": "numeric" if numeric else "categorical",
            "n": len(common), "n_diff": n_diff, "lines": lines}


def _cell(v) -> str:  # noqa: ANN001
    import pandas as pd

    return "" if pd.isna(v) else str(v)
