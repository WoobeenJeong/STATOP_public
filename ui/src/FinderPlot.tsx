/** 고른 컬럼의 **모양**  — 값과 p 만으로는 알 수 없는 것.
 *
 * 001 의 cancer 군은 순위로 보면 아무것도 없고 그림으로 보면 V 자다. 그림이 없으면
 * "왜 거리상관만 유의한가"를 설명할 길이 없다.
 *
 * 연관이면 산점도(군이 있으면 색으로 나눈다), 차이면 군별 분포를 같은 축에 겹친다.
 * 색만으로 구분하지 않는다 — 모양·채움을 함께 바꾼다 (design-tokens 3절).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";

type Plot = Awaited<ReturnType<typeof api.explorePoints>>;

const W = 560, H = 260;
const PAD = { l: 56, r: 14, t: 14, b: 36 };
const SERIES = ["#2f6f6f", "#b26a17", "#4a4ab2", "#8a2f6f", "#3f7a2f", "#8a6f2f"];
const MARK = ["circle", "square", "triangle", "diamond"];

interface Props {
  sessionFile: string;
  question: string;
  columns: string[];
  colorBy?: string;               // 군으로 색을 나눌 컬럼 (확정된 라벨)
}

export default function FinderPlot({ sessionFile, question, columns, colorBy }: Props) {
  const [p, setP] = useState<Plot | null>(null);
  const [err, setErr] = useState("");
  const cv = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (columns.length < 1) { setP(null); return; }
    let live = true;
    api.explorePoints(sessionFile, question, columns, colorBy)
      .then((r) => { if (live) { setP(r); setErr(""); } })
      .catch((e) => { if (live) { setP(null); setErr(String(e instanceof Error ? e.message : e)); } });
    return () => { live = false; };
  }, [sessionFile, question, columns.join(","), colorBy]);

  const dark = useMemo(() => matchMedia("(prefers-color-scheme: dark)").matches, []);

  useEffect(() => {
    const c = cv.current;
    if (!c || !p) return;
    const g = c.getContext("2d");
    if (!g) return;
    const css = getComputedStyle(document.documentElement);
    const line = css.getPropertyValue("--border").trim();
    const faint = css.getPropertyValue("--text-faint").trim();
    const ink = css.getPropertyValue("--text").trim();
    g.clearRect(0, 0, W, H);
    g.font = "11px ui-monospace, monospace";
    g.strokeStyle = line;
    g.beginPath();
    g.moveTo(PAD.l, PAD.t); g.lineTo(PAD.l, H - PAD.b); g.lineTo(W - PAD.r, H - PAD.b);
    g.stroke();

    if (p.kind === "scatter") {
      const all = p.series.flatMap((s) => s.pts ?? []);
      if (!all.length) return;
      const xs = all.map((q) => q[0]), ys = all.map((q) => q[1]);
      const x0 = Math.min(...xs), x1 = Math.max(...xs);
      const y0 = Math.min(...ys), y1 = Math.max(...ys);
      const X = (v: number) => PAD.l + ((v - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
      const Y = (v: number) => H - PAD.b - ((v - y0) / (y1 - y0 || 1)) * (H - PAD.t - PAD.b);
      p.series.forEach((s, i) => {
        g.fillStyle = SERIES[i % SERIES.length];
        (s.pts ?? []).forEach(([x, y]) => mark(g, X(x), Y(y), MARK[i % MARK.length]));
      });
      g.fillStyle = faint;
      g.fillText(fmt(x0), PAD.l, H - PAD.b + 15);
      g.fillText(fmt(x1), W - PAD.r - 44, H - PAD.b + 15);
      g.fillText(fmt(y1), 4, PAD.t + 9);
      g.fillText(fmt(y0), 4, H - PAD.b);
      g.fillStyle = ink;
      g.fillText(p.x_label, W / 2 - 28, H - 6);
    } else {
      const top = Math.max(1, ...p.series.flatMap((s) => s.bins ?? []));
      const n = (p.series[0]?.bins ?? []).length || 1;
      const bw = (W - PAD.l - PAD.r) / n;
      p.series.forEach((s, i) => {
        g.fillStyle = SERIES[i % SERIES.length];
        g.globalAlpha = 0.55;
        (s.bins ?? []).forEach((b, j) => {
          const h = (b / top) * (H - PAD.t - PAD.b);
          g.fillRect(PAD.l + j * bw + (i * bw) / p.series.length + 1,
                     H - PAD.b - h, bw / p.series.length - 1.5, h);
        });
        g.globalAlpha = 1;
      });
      const e = p.edges ?? [];
      g.fillStyle = faint;
      if (e.length) {
        g.fillText(fmt(e[0]), PAD.l, H - PAD.b + 15);
        g.fillText(fmt(e[e.length - 1]), W - PAD.r - 44, H - PAD.b + 15);
      }
      g.fillText(String(top), 4, PAD.t + 9);
      g.fillStyle = ink;
      g.fillText(p.x_label, W / 2 - 28, H - 6);
    }

    // 범례 — 색과 모양을 함께
    let lx = PAD.l + 6;
    p.series.forEach((s, i) => {
      if (!s.name) return;
      g.fillStyle = SERIES[i % SERIES.length];
      mark(g, lx, PAD.t + 4, MARK[i % MARK.length]);
      g.fillStyle = ink;
      g.fillText(s.name + (s.n ? ` (${s.n})` : ""), lx + 9, PAD.t + 8);
      lx += 28 + (s.name.length + 6) * 6.2;
    });
  }, [p, dark]);

  if (err) return <div className="err">{err}</div>;
  if (!p) return null;

  return (
    <div className="fn-plot">
      <canvas ref={cv} width={W} height={H} />
      {p.kind === "groups" && (
        <div className="hint" style={{ margin: 0 }}>
          {p.series.map((s) => (
            <span key={s.name} style={{ marginRight: 14 }}>
              {s.name}: 중앙 {fmt(s.med ?? 0)} · 사분위 {fmt(s.q1 ?? 0)}–{fmt(s.q3 ?? 0)}
            </span>
          ))}
        </div>
      )}
      <div className="hint" style={{ margin: 0 }}>
        {p.n.toLocaleString()}행 · {p.kind === "scatter"
          ? `${p.x_label} × ${p.y_label}` : `${p.x_label} 을 군별로`}
        {p.color_by && ` · 색 = ${p.color_by}`}
      </div>
    </div>
  );
}

function mark(g: CanvasRenderingContext2D, x: number, y: number, kind: string) {
  const r = 3.2;
  g.beginPath();
  if (kind === "square") g.rect(x - r, y - r, r * 2, r * 2);
  else if (kind === "triangle") { g.moveTo(x, y - r); g.lineTo(x + r, y + r); g.lineTo(x - r, y + r); }
  else if (kind === "diamond") { g.moveTo(x, y - r); g.lineTo(x + r, y); g.lineTo(x, y + r); g.lineTo(x - r, y); }
  else g.arc(x, y, r, 0, Math.PI * 2);
  g.fill();
}
function fmt(v: number) {
  if (v !== 0 && Math.abs(v) < 1e-4) return v.toExponential(2);
  return Number(v.toPrecision(4)).toLocaleString("en-US", { maximumSignificantDigits: 4 });
}
