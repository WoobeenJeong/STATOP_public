/** 의미 타입 확정 패널 (M1-1) — CLI의 [타입 확정] 화면과 같은 REST를 쓴다.
 *
 * 순위만 보여주고 점수는 보여주지 않는다 (). 추론에 없던 타입도 고를 수 있고,
 * 확정하면 그 타입으로 계산할 때의 위험(S-R 규칙)을 그 자리에서 알린다 (요구사항-7).
 */

import { useState } from "react";
import { api, wasAborted } from "./api";

type Row = {
  column: string; shape_label: string;
  confirmed: string | null; needs_confirm: boolean;
  confirm_reason: string | null; conflicts: string[];
  candidates: { rank: number; type: string; evidence: string[] }[];
};

type Dist = {
  kind: "numeric" | "categorical";
  bins?: number[]; edges?: number[];
  levels?: { value: string; n: number; ratio: number }[];
  // 다섯 수·IQR·울타리 — 이름과 값을 **서버가** 만든다 (터미널과 같은 글자)
  stats?: { key: string; label: string; value: number; text: string }[];
  fence_note?: string;
};

interface Props {
  sessionFile: string;
  path: string;
  onConfirmedChange?: (n: number) => void;   // 확정 수 — 아래 패널을 열지 정한다
}

export default function TypesPanel({ sessionFile, path,
                                     onConfirmedChange }: Props) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [known, setKnown] = useState<string[]>([]);
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [dist, setDist] = useState<{ col: string; d: Dist } | null>(null);
  // label 확정 직후의 코드 매핑 — CLI 의 라벨 매핑 화면과 같은 op 를 남긴다
  const [mapCol, setMapCol] = useState("");
  const [mapRows, setMapRows] = useState<{ value: string; n: number; ratio: number;
                                           code: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [distBusy, setDistBusy] = useState("");   // 분포를 불러오는 중인 컬럼
  const [err, setErr] = useState("");

  /** 중지로 끊긴 것은 오류가 아니다 — 무엇을 잘못한 것처럼 보이면 안 된다 */
  function fail(e: unknown): void {
    setErr(wasAborted(e) ? "" : String(e instanceof Error ? e.message : e));
    if (wasAborted(e)) setNote("중지했습니다 — 다시 누르시면 됩니다");
  }

  async function load() {
    setBusy(true);
    setErr("");
    try {
      const r = await api.semanticTypes(sessionFile);
      setRows(r.items);
      setKnown(r.known_types);
      setNote(`확정 ${r.n_confirmed}개 · 미확정 ${r.n_pending}개`);
      onConfirmedChange?.(r.n_confirmed);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(row: Row) {
    const type = choice[row.column] ?? row.confirmed ?? row.candidates[0]?.type;
    if (!type) return;
    setBusy(true);
    try {
      const r = await api.semanticConfirm(sessionFile, row.column, type);
      const ids = r.risks.map((x) => x.id).join(", ");
      setNote(`확정: ${row.column} = ${type}` + (ids ? ` — 계산 위험: ${ids}` : ""));
      if (type === "label") {
        // label 확정 → 바로 코드 매핑 (CLI 와 같은 한 흐름)
        const lv = await api.labelLevels(path, row.column, sessionFile);
        setMapCol(row.column);
        setMapRows(lv.levels);
      }
      await load();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function saveMapping() {
    if (!mapCol) return;
    setBusy(true);
    try {
      const mapping = Object.fromEntries(mapRows.map((r) => [r.value, r.code]));
      await api.labelMap(sessionFile, mapCol, mapping);
      const groups = new Map<number, string[]>();
      mapRows.forEach((r) => groups.set(r.code, [...(groups.get(r.code) ?? []), r.value]));
      setNote(`매핑 저장됨: ${mapCol} — ` + [...groups.entries()]
        .map(([c, vs]) => `${c}=${vs.join("+")}`).join(" · "));
      setMapCol("");
      setMapRows([]);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function showDist(col: string) {
    if (dist?.col === col) {          // 다시 누르면 접는다
      setDist(null);
      return;
    }
    setDistBusy(col);
    try {
      const r = await api.distribution(path, [col], sessionFile);
      setDist({ col, d: r.items[0] as Dist });
    } catch (e) {
      fail(e);
    } finally {
      setDistBusy("");
    }
  }

  /** 확정 취소 — 잘못 확정했을 때 되돌릴 길 */
  async function unconfirm(row: Row) {
    setBusy(true);
    try {
      const r = await api.semanticUnconfirm(sessionFile, row.column);
      setNote(r.notice);
      await load();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="ttl">의미 타입 확정</div>
      <div className="row">
        <button className="pri" disabled={busy} onClick={load}>
          {busy ? "추론 중…" : rows ? "다시 추론" : "타입 추론"}
        </button>
        <span className="hint" style={{ margin: 0 }}>
          {note || "저장 타입(float64)이 아니라 값이 실제로 무엇인지(비율·확률·카운트…)를 확정합니다"}
        </span>
      </div>
      {err && <div className="err">{err}</div>}

      {rows && (
        <table>
          <thead>
            <tr><th></th><th>컬럼</th><th>분포</th><th>타입</th><th style={{ width: 140 }}></th></tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const current = choice[r.column] ?? r.confirmed ?? r.candidates[0]?.type ?? "";
              const inferred = new Set(r.candidates.map((c) => c.type));
              return (
                <tr key={r.column} className={r.needs_confirm ? "mid" : ""}>
                  <td className="flag">{r.confirmed ? "✔" : r.needs_confirm ? "→" : ""}</td>
                  <td className="col">
                    {/* 이름이 길면 어느 컬럼을 고르는지 알 수 없다 — 끊지 않고 줄바꿈 */}
                    <span className="col-name" title={r.column}>{r.column}</span>
                    {/* 근거는 순위·이유만 — 점수를 보이면 숫자를 믿고 확정을 건너뛴다 */}
                    {(r.candidates.find((c) => c.type === current)?.evidence ?? [])
                      .slice(0, 2).map((ev, i) => (
                        <div className="ty-ev" key={i}>· {ev}</div>
                      ))}
                    {r.confirm_reason && !r.confirmed && (
                      <div className="ty-need">→ {r.confirm_reason}</div>
                    )}
                  </td>
                  <td className="hint" style={{ margin: 0 }}>{r.shape_label}</td>
                  <td>
                    <select value={current} disabled={busy}
                            onChange={(e) => setChoice({ ...choice, [r.column]: e.target.value })}>
                      {/* 추론 후보 먼저, 나머지 전부 뒤에 — 없던 타입도 막지 않는다 */}
                      {r.candidates.map((c) => (
                        <option key={c.type} value={c.type}>
                          {c.rank}. {c.type}
                        </option>
                      ))}
                      {known.filter((k) => !inferred.has(k)).map((k) => (
                        <option key={k} value={k}>{k} (추론 밖)</option>
                      ))}
                    </select>
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button className="sm" disabled={busy} onClick={() => confirm(r)}>
                      {r.confirmed ? "다시 확정" : "확정"}
                    </button>{" "}
                    {r.confirmed && (
                      <>
                        <button className="sm" disabled={busy}
                                onClick={() => unconfirm(r)}>확정 취소</button>{" "}
                      </>
                    )}
                    <button className="sm" disabled={distBusy === r.column}
                            onClick={() => showDist(r.column)}>
                      {distBusy === r.column ? "여는 중…" : "분포"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {mapCol && (
        <div className="ty-dist">
          <div className="ttl" style={{ marginBottom: 6 }}>
            라벨 매핑 — {mapCol}
            <span className="hint"> 같은 코드는 같은 군으로 묶입니다</span>
          </div>
          {mapRows.map((r, i) => (
            <div className="ty-level" key={r.value}>
              <span className="col">{r.value}</span>
              <select value={r.code} disabled={busy}
                      onChange={(e) => {
                        const next = [...mapRows];
                        next[i] = { ...r, code: Number(e.target.value) };
                        setMapRows(next);
                      }}>
                {mapRows.map((_, c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <span className="hint" style={{ margin: 0 }}>
                {(r.ratio * 100).toFixed(1)}% ({r.n.toLocaleString()})
              </span>
            </div>
          ))}
          {new Set(mapRows.map((r) => r.code)).size < mapRows.length && (
            <div className="ty-need">
              ⚠ {mapRows.length}수준 → {new Set(mapRows.map((r) => r.code)).size}군으로 묶임
            </div>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            <button className="pri" disabled={busy} onClick={saveMapping}>매핑 저장</button>
            <button className="sm" disabled={busy}
                    onClick={() => { setMapCol(""); setMapRows([]); }}>건너뛰기</button>
          </div>
        </div>
      )}

      {dist && (
        <div className="ty-dist">
          <div className="ttl" style={{ marginBottom: 6 }}>{dist.col}</div>
          {dist.d.kind === "numeric" && dist.d.bins ? (
            (() => {
              // 축이 없으면 그림이 어느 범위인지 말해주지 않는다 — CLI와 같은 규칙()
              const bins = dist.d.bins!;
              const edges = dist.d.edges ?? [];
              const mx = Math.max(...bins, 1);
              const lo = edges[0], hi = edges[edges.length - 1];
              return (
                <div className="ty-plot">
                  <div className="ty-yaxis">
                    <span>{mx.toLocaleString()}</span>
                    <span>0</span>
                  </div>
                  <div className="ty-plotbody">
                    <div className="ty-hist">
                      {bins.map((b, i) => (
                        <div className="ty-bar" key={i}
                             style={{ height: `${Math.max(2, (b / mx) * 100)}%` }}
                             title={`${edges[i]?.toPrecision(4)} ~ ${edges[i + 1]?.toPrecision(4)}: ${b}`} />
                      ))}
                    </div>
                    <div className="ty-xaxis">
                      <span>{lo?.toPrecision(4)}</span>
                      <span>{lo != null && hi != null
                        ? ((lo + hi) / 2).toPrecision(4) : ""}</span>
                      <span>{hi?.toPrecision(4)}</span>
                    </div>
                  </div>
                </div>
              );
            })()
          ) : (
            (dist.d.levels ?? []).slice(0, 8).map((lv) => (
              <div className="ty-level" key={lv.value}>
                <span className="col">{lv.value}</span>
                <span className="ty-lvbar" style={{ width: `${lv.ratio * 100}%` }} />
                <span className="hint" style={{ margin: 0 }}>
                  {(lv.ratio * 100).toFixed(1)}% ({lv.n.toLocaleString()})
                </span>
              </div>
            ))
          )}

          {/* 다섯 수 + IQR + 울타리 — 이름과 값을 함께. 그림만 보면 상자의 끝이
              얼마인지 알 수 없고, 울타리는 아예 계산해야 했다 */}
          {(dist.d.stats?.length ?? 0) > 0 && (
            <>
              <div className="ty-fives">
                {dist.d.stats!.map((x) => (
                  <span key={x.key}>
                    <i>{x.label}</i>{x.text}
                  </span>
                ))}
              </div>
              {dist.d.fence_note && <div className="hint">{dist.d.fence_note}</div>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
