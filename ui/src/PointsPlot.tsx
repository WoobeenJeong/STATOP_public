/** 개별 점 그림  — 검정이 실제로 본 행을 하나씩 찍고, 클릭해서 뺀다.
 *
 * 통계량과 p만 보면 어떤 샘플이 결과를 끌고 있는지 알 수 없다. 점을 클릭하면 그
 * 샘플을 제외할 수 있고, 뺄 때는 사유를 적어야 한다 — 나중에 왜 뺐는지 답할 수 있어야 한다.
 *
 * 색은 층화 라벨(by)로 나눈다. 라벨을 지정하는 이유 중 하나다.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";

type Pts = Awaited<ReturnType<typeof api.points>>;

const W = 560;
const H = 260;
const PAD = { l: 52, r: 12, t: 12, b: 34 };
// 색만으로 구분하지 않는다 — 모양도 함께 바꾼다 (design-tokens 3절)
const SERIES = ["#2f6f6f", "#b26a17", "#4a4ab2", "#8a2f6f", "#3f7a2f", "#8a6f2f"];

interface Props {
  sessionFile: string;
  onChanged?: () => void;      // 제외/되돌리기 후 검정을 다시 돌리라고 알린다
  alternatives?: { id: string; name: string; why: string }[];
}

export default function PointsPlot({ sessionFile, onChanged,
                                     alternatives = [] }: Props) {
  const [p, setP] = useState<Pts | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const reasonBox = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setErr("");
    try {
      setP(await api.points(sessionFile));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
  }, [sessionFile]);

  useEffect(() => { void load(); }, [load]);

  const geom = useMemo(() => {
    if (!p || !p.y.length) return null;
    const ys = p.y;
    const ymin = Math.min(...ys), ymax = Math.max(...ys);
    const pad = (ymax - ymin) * 0.06 || 1;
    const lo = ymin - pad, hi = ymax + pad;
    const yPos = (v: number) =>
      PAD.t + (H - PAD.t - PAD.b) * (1 - (v - lo) / (hi - lo));

    // 범주형 x 는 군마다 한 줄로 흩뿌린다 (jitter) — 겹쳐 쌓이면 개수를 못 읽는다
    const levels = p.x_kind === "category"
      ? [...new Set(p.x.map(String))] : [];
    const band = (W - PAD.l - PAD.r) / Math.max(1, levels.length);
    const xNums = p.x_kind === "numeric" ? (p.x as number[]) : [];
    const xmin = xNums.length ? Math.min(...xNums) : 0;
    const xmax = xNums.length ? Math.max(...xNums) : 1;
    const xPos = (v: number | string, i: number) => {
      if (p.x_kind === "category") {
        const k = levels.indexOf(String(v));
        // 흩뿌림은 인덱스로 정한다 — 다시 그릴 때마다 점이 움직이면 클릭을 못 한다
        const j = ((Math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1;
        return PAD.l + band * (k + 0.2 + 0.6 * j);
      }
      const span = xmax - xmin || 1;
      return PAD.l + (W - PAD.l - PAD.r) * ((Number(v) - xmin) / span);
    };
    return { lo, hi, yPos, xPos, levels, band, xmin, xmax };
  }, [p]);

  const seriesOf = useMemo(() => {
    const levels = [...new Set(p?.group ?? [])];
    return (i: number) => {
      const g = p?.group?.[i];
      return g == null ? SERIES[0] : SERIES[levels.indexOf(g) % SERIES.length];
    };
  }, [p]);

  async function act(key: string, restore: boolean) {
    if (!p) return;
    if (!restore && !reason.trim()) {
      setErr("제외 사유를 먼저 적으세요 — 나중에 왜 뺐는지 설명할 수 있어야 합니다");
      reasonBox.current?.focus();
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await api.excludePoint(sessionFile, p.key_column, key, reason, restore);
      setReason("");
      setPicked(null);
      await load();
      onChanged?.();      // 제외도 값 변경이다 — 사본 저장 대상
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  if (err && !p) return <div className="err">{err}</div>;
  if (!p || !geom) return <div className="hint">점을 불러오는 중…</div>;

  const outKeys = new Set(p.outliers.map((o) => o.key));
  const byLevels = [...new Set(p.group)];

  return (
    <div className="pt-wrap">
      <div className="ttl" style={{ marginBottom: 4 }}>
        개별 점 — {p.y_label} (군: {p.x_label}) · {p.y.length}개
      </div>
      <div className="hint" style={{ marginTop: 0 }}>
        점을 클릭해 고른 뒤 사유를 적고 [제외]를 누르세요. 지목은 {p.key_column} 기준입니다.
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="pt-svg" role="img">
        <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={H - PAD.b} className="pt-axis" />
        <line x1={PAD.l} y1={H - PAD.b} x2={W - PAD.r} y2={H - PAD.b}
              className="pt-axis" />
        {[geom.hi, (geom.hi + geom.lo) / 2, geom.lo].map((v) => (
          <text key={v} x={PAD.l - 6} y={geom.yPos(v) + 4} className="pt-tick"
                textAnchor="end">{v.toPrecision(4)}</text>
        ))}
        {p.x_kind === "category"
          ? geom.levels.map((lv, k) => (
              <text key={lv} x={PAD.l + geom.band * (k + 0.5)} y={H - PAD.b + 16}
                    className="pt-tick" textAnchor="middle">{lv}</text>
            ))
          : [geom.xmin, geom.xmax].map((v, k) => (
              <text key={k} x={k ? W - PAD.r : PAD.l} y={H - PAD.b + 16}
                    className="pt-tick" textAnchor={k ? "end" : "start"}>
                {Number(v).toPrecision(4)}
              </text>
            ))}
        {p.y.map((yv, i) => {
          const key = p.keys[i];
          const isOut = outKeys.has(key);
          return (
            <circle key={i} cx={geom.xPos(p.x[i], i)} cy={geom.yPos(yv)}
                    r={picked === key ? 6 : isOut ? 4.5 : 3}
                    fill={seriesOf(i)}
                    className={`pt-dot${picked === key ? " on" : ""}${isOut ? " out" : ""}`}
                    onClick={() => setPicked(key === picked ? null : key)}>
              <title>{`${key}: ${p.x[i]}, ${yv.toPrecision(4)}`}</title>
            </circle>
          );
        })}
      </svg>

      {byLevels.length > 1 && (
        <div className="pt-legend">
          {byLevels.map((g, i) => (
            <span key={g}>
              <i style={{ background: SERIES[i % SERIES.length] }} />{p.by}={g}
            </span>
          ))}
        </div>
      )}

      <div className="row" style={{ marginTop: 8 }}>
        <span className="hint" style={{ margin: 0, minWidth: 140 }}>
          {picked ? `고른 점: ${picked}` : "고른 점 없음"}
        </span>
        <input ref={reasonBox} type="text" value={reason} disabled={busy}
               placeholder="제외 사유 (필수)" style={{ flex: 1 }}
               onChange={(e) => setReason(e.target.value)} />
        <button className="sm" disabled={busy || !picked}
                onClick={() => picked && act(picked, false)}>제외</button>
      </div>
      {err && <div className="err">{err}</div>}

      {/* 빼기 전에 대안을 먼저  — 제외는 마지막 수단이다 */}
      {alternatives.length > 0 && (
        <div className="pt-alts">
          <b>빼기 전에 권하는 대안</b>
          {alternatives.map((a) => (
            <div key={a.id}>· {a.id} {a.name} — {a.why}</div>
          ))}
        </div>
      )}

      {p.outliers.length > 0 && (
        <details open>
          <summary>▸ 눈에 띄는 점 {p.outliers.length}개</summary>
          <div className="inner">
            {p.outliers.map((o) => (
              <div key={o.key} className={picked === o.key ? "pt-row on" : "pt-row"}
                   onClick={() => setPicked(o.key)}>
                · {o.key} · {String(o.x)} · {o.y.toPrecision(4)} — {o.why}
              </div>
            ))}
          </div>
        </details>
      )}

      {p.excluded.length > 0 && (
        <div className="pt-excluded">
          <b>뺀 샘플 {p.excluded.length}개</b> — 검정·가설·보고서에 그대로 반영됩니다
          {p.excluded.map((e) => (
            <div key={e.key}>
              · {e.key} — {e.reason || "-"}{" "}
              <button className="sm" disabled={busy}
                      onClick={() => act(e.key, true)}>되돌리기</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
