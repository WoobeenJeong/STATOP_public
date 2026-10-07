/** Q-12 표본 크기·대표성  — "몇 행이면 전체를 닮는가".
 *
 * 다른 패널과 답의 종류가 다르다. 여기서 나오는 것은 p 값이 아니라 **n** 이다.
 * 곡선은 **누를 때만** 그린다 — 기본은 숫자다.
 */

import { useState } from "react";
import { api, type Represent, type RepresentCheck,
         type RepresentSpread } from "./api";

const W = 520;
const H = 190;
const PAD = { l: 46, r: 10, t: 10, b: 28 };

/** 거리 곡선 — 세로축은 거리(작을수록 전체를 닮음), 가로축은 n (로그) */
function Curve({ c, threshold }: { c: Represent["curves"][0]; threshold: number }) {
  const pts = c.points;
  if (pts.length < 2) return null;
  const xs = pts.map((p) => Math.log10(Math.max(1, p.n)));
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y1 = Math.max(threshold, ...pts.map((p) => p.hi)) * 1.1;
  const px = (i: number) =>
    PAD.l + ((xs[i] - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
  const py = (v: number) => H - PAD.b - (v / (y1 || 1)) * (H - PAD.t - PAD.b);

  return (
    <svg width={W} height={H} role="img"
         aria-label={`${c.column} 의 거리 곡선`}>
      {/* 임계선 — 관행일 뿐이므로 점선으로만 긋는다 */}
      <line x1={PAD.l} x2={W - PAD.r} y1={py(threshold)} y2={py(threshold)}
            stroke="currentColor" strokeDasharray="4 3" opacity={0.45} />
      <text x={W - PAD.r} y={py(threshold) - 4} textAnchor="end"
            fontSize={10} fill="currentColor" opacity={0.6}>{threshold}</text>
      {/* 반복들의 최소~최대 — 평균만 그리면 그 n 의 운이 안 보인다 */}
      {pts.map((p, i) => (
        <line key={`s${p.n}`} x1={px(i)} x2={px(i)} y1={py(p.lo)} y2={py(p.hi)}
              stroke="currentColor" opacity={0.3} />
      ))}
      <polyline fill="none" stroke="currentColor" strokeWidth={1.6}
                points={pts.map((p, i) => `${px(i)},${py(p.mean)}`).join(" ")} />
      {pts.map((p, i) => (
        <circle key={p.n} cx={px(i)} cy={py(p.mean)} r={2.5} fill="currentColor">
          <title>{`n=${p.n.toLocaleString()} · 거리 ${p.mean.toFixed(4)}`}</title>
        </circle>
      ))}
      {[pts[0], pts[pts.length - 1]].map((p, k) => (
        <text key={`x${k}`} x={px(k === 0 ? 0 : pts.length - 1)} y={H - 10}
              textAnchor={k === 0 ? "start" : "end"} fontSize={10}
              fill="currentColor" opacity={0.7}>{p.n.toLocaleString()}</text>
      ))}
      <text x={6} y={PAD.t + 8} fontSize={10} fill="currentColor" opacity={0.7}>
        거리
      </text>
    </svg>
  );
}

/** 한 n 에서 다시 뽑을 때마다 나온 거리들 — 어디에 선을 그을지는 여기서 정한다 */
function SpreadBars({ sp, threshold }:
                    { sp: RepresentSpread["spreads"][0]; threshold: number }) {
  const top = Math.max(1, ...sp.bins.map((b) => b[2]));
  return (
    <div className="rp-spread">
      <div><b>{sp.summary}</b></div>
      {sp.bins.map(([lo, hi, c]) => (
        <div key={lo} className="rp-bar">
          <span className="rp-range">{lo.toFixed(4)}~{hi.toFixed(4)}</span>
          <span className="rp-fill" style={{ width: `${(100 * c) / top}%` }} />
          <span className="hint" style={{ margin: 0 }}>{c}</span>
        </div>
      ))}
      <div className="hint" style={{ marginTop: 2 }}>
        {sp.suggest}
        {sp.q.p95 >= threshold && " ⚠"}
      </div>
    </div>
  );
}

export default function RepresentPanel({ sessionFile }: { sessionFile: string }) {
  const [rep, setRep] = useState<Represent | null>(null);
  const [chk, setChk] = useState<RepresentCheck | null>(null);
  const [sp, setSp] = useState<RepresentSpread | null>(null);
  const [metric, setMetric] = useState("ks");
  const [threshold, setThreshold] = useState(0.05);
  const [plot, setPlot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run() {
    setBusy(true); setErr(""); setChk(null); setPlot(null); setSp(null);
    try {
      setRep(await api.represent(sessionFile, { metric, threshold }));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function seeSpread(n: number) {
    setBusy(true); setErr("");
    try {
      setSp(await api.representSpread(sessionFile, n, metric, threshold));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function check(n: number) {
    setBusy(true); setErr("");
    try {
      setChk(await api.representCheck(sessionFile, n));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="ttl">표본 크기·대표성 (Q-12) — 몇 행이면 전체를 닮는가</div>
      <div className="row">
        <select value={metric} onChange={(e) => setMetric(e.target.value)}>
          <option value="ks">KS distance (연속, 0~1 무단위)</option>
          <option value="wasserstein">1-Wasserstein distance (연속, 원 단위)</option>
        </select>
        <label className="hint" style={{ margin: 0 }}>
          충분하다고 볼 거리{" "}
          <input type="number" step="0.01" min="0.001" max="0.5" value={threshold}
                 style={{ width: 70 }}
                 onChange={(e) => setThreshold(Number(e.target.value))} />
        </label>
        <button className="pri" disabled={busy} onClick={run}>
          {busy ? "재는 중…" : "곡선 내기"}
        </button>
      </div>
      {err && <div className="err">{err}</div>}

      {rep && (
        <>
          <div className="hint">{rep.repeats_note}</div>
          {rep.skipped_note && <div className="hint">{rep.skipped_note}</div>}
          <table>
            <thead>
              <tr><th>컬럼</th><th>거리</th><th>충분한 n</th><th></th></tr>
            </thead>
            <tbody>
              {rep.curves.map((c) => (
                <tr key={c.column}>
                  <td><b>{c.column}</b>{" "}
                    <span className="hint" style={{ margin: 0 }}>{c.kind}</span></td>
                  <td className="hint" style={{ margin: 0 }}>{c.metric_name}</td>
                  <td className={c.enough_n === null ? "high" : ""}>
                    {c.enough_n === null
                      ? `끝까지 ${rep.threshold} 아래로 안 내려옴`
                      : c.enough_n.toLocaleString()}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {/* 그림은 누를 때만 (사용자 결정) */}
                    <button className="sm"
                            onClick={() => setPlot(plot === c.column ? null : c.column)}>
                      {plot === c.column ? "접기" : "곡선"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {plot && (
            <Curve c={rep.curves.find((c) => c.column === plot)!}
                   threshold={rep.threshold} />
          )}

          {rep.enough_n !== null && (
            <div className="okbox">
              <b>n≈{rep.enough_n.toLocaleString()}</b>{" "}
              (전체 {rep.total_rows.toLocaleString()}행의{" "}
              {((100 * rep.enough_n) / rep.total_rows).toFixed(1)}%)
              <div className="hint" style={{ marginTop: 4 }}>
                필요한 n 을 정하는 것은 {rep.limiting.join(", ")} 입니다
              </div>
              <div style={{ marginTop: 6 }}><b>{rep.hypothesis}</b></div>
              <div className="hint" style={{ marginTop: 2 }}>{rep.hypothesis_how}</div>
              <button className="sm" style={{ marginTop: 6 }} disabled={busy}
                      onClick={() => check(rep.enough_n!)}>고른 n 검증</button>{" "}
              <button className="sm" disabled={busy}
                      onClick={() => seeSpread(rep.enough_n!)}>거리 분포 보기</button>
            </div>
          )}
          {rep.unit_bound && <div className="warnbox">{rep.unit_bound}</div>}
          <div className="hint">{rep.threshold_note}</div>
          {sp && (
            <div className="sc-ent">
              <b>{sp.head}</b>
              <div className="hint" style={{ marginTop: 2 }}>{sp.why}</div>
              {sp.spreads.map((x) => (
                <SpreadBars key={x.column} sp={x} threshold={rep.threshold} />
              ))}
            </div>
          )}
        </>
      )}

      {chk && (
        <div className="sc-ent">
          <div className="hint" style={{ marginTop: 0 }}>{chk.not_full_note}</div>
          {chk.rows.map((h) => (
            <div key={h.column}
                 className={h.p !== null && h.p < 0.05 ? "mid" : ""}>{h.line}</div>
          ))}
          <div className="hint">{chk.p_note}</div>
        </div>
      )}
    </div>
  );
}
