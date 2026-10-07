/** 이 표본으로 **무엇이 잡히나**  — 검정력을 결과 옆에 붙인다.
 *
 * 작은 표본에서 "유의하지 않다"는 "관계가 없다"가 아니다. 그런데 p 만 보면 그렇게
 * 읽힌다. 그래서 **잡히는 가장 작은 크기**를 선으로 긋고, 방금 잰 값이 그 선의 어느
 * 쪽에 있는지 같은 자리에서 보인다.
 *
 * 선은 상관계수(r·ρ) 척도다. τ·dCor 은 다른 자로 잰 값이라 **선에 얹지 않는다** —
 * 효과크기의 종류가 다르면 크기를 비교하지 않는다는 원칙과 같다 (robust.py).
 *
 * 목표 검정력은 **끌어서 옮긴다.** 80% 는 관습일 뿐이고, 95% 로 옮겼을 때 선이
 * 어디로 가는지를 같은 자리에서 봐야 "표본이 모자란다"가 숫자가 된다.
 */

import { useEffect, useState } from "react";
import { api } from "./api";

type Pow = Awaited<ReturnType<typeof api.explorePower>>;

interface Props {
  sessionFile: string;
  question: string;
  columns: string[];
  colorBy?: string;
  focus: string | null;                  // 선 위에 올릴 지표 **하나**
  onFocus: (id: string) => void;
  effects: { id: string; name: string; value: number | null; p?: number | null;
             effect_name: string }[];
}

export default function PowerCard({ sessionFile, question, columns, colorBy,
                                    focus, onFocus, effects }: Props) {
  // **한 번에 하나만.** 여럿을 겹쳐 놓으면 어느 값이 어느 지표인지 알 수 없고,
  // 새로 재면 앞의 것 위에 덧씌워진다
  const shown = effects.find((e) => e.id === focus) ?? effects[effects.length - 1];
  const [p, setP] = useState<Pow | null>(null);
  const [target, setTarget] = useState(80);        // 옮겨 가며 보는 목표 검정력 (%)
  const [typed, setTyped] = useState("");          // 쳐 넣는 중인 값 (엔터로 적용)

  /** 친 값을 적용한다 — 범위 밖이면 가까운 쪽으로 당긴다 (100% 는 닿지 않는다) */
  function applyTyped() {
    const v = Number(typed);
    if (typed !== "" && Number.isFinite(v)) setTarget(Math.min(99, Math.max(50, Math.round(v))));
    setTyped("");
  }

  useEffect(() => {
    if (columns.length < 2) { setP(null); return; }
    let live = true;
    // 끄는 동안 매 칸마다 쏘지 않는다 — 손을 멈추면 그때 다시 잰다
    const t = window.setTimeout(() => {
        api.explorePower(sessionFile, question, columns, shown ? [shown] : [], target / 100)
        .then((r) => { if (live) setP(r.head ? r : null); })
        .catch(() => { if (live) setP(null); });
    }, 120);
    return () => { live = false; window.clearTimeout(t); };
  }, [sessionFile, question, columns.join(","), JSON.stringify(shown), target]);

  if (!p || !p.cut) return null;
  const onLine = (p.rows ?? []).filter((r) => r.comparable !== false);
  const off = (p.rows ?? []).filter((r) => r.comparable === false);
  // 축은 0~1 (상관) 또는 잰 값이 넘으면 그만큼
  const top = Math.max(1, p.cut * 1.2, ...onLine.map((r) => Math.abs(r.value) * 1.2));
  const at = (v: number) => Math.min(100, (v / top) * 100);
  const pct = (v: number) => `${at(v)}%`;
  // 가까이 선 값끼리 글자가 겹친다 — 겹치는 것만 한 줄씩 내려 세운다
  const lanes: number[] = [];
  const laneOf = new Map<string, number>();
  [...onLine].sort((a, b) => Math.abs(a.value) - Math.abs(b.value)).forEach((r) => {
    const x = at(Math.abs(r.value));
    let i = lanes.findIndex((last) => x - last >= 11);
    if (i < 0) i = lanes.length;
    lanes[i] = x;
    laneOf.set(r.id, i);
  });
  const rows = Math.max(1, lanes.length);

  return (
    <div className="pw">
      <div className="pw-head">{p.head}
        <span className="hint" style={{ margin: 0 }}> · {p.note}</span></div>

      {/* 무엇을 보고 있는지 — 컬럼과 지표를 적지 않으면 값만 떠 있게 된다 */}
      <div className="hint" style={{ margin: 0 }}>
        고른 컬럼 <b>{columns.join(" × ")}</b>{colorBy && <> · 색 = {colorBy}</>}
        {shown && <> · 지금 보는 지표 <b>{shown.name}</b>
          {shown.value != null && <> ({shown.effect_name} {shown.value.toPrecision(4)}
            {shown.p != null && <> · p {shown.p.toPrecision(3)}</>})</>}</>}
      </div>
      {effects.length > 1 && (
        <div className="row" style={{ marginTop: 0 }}>
          <span className="hint" style={{ margin: 0 }}>바꿔 보기</span>
          {effects.map((e) => (
            <button key={e.id} className={`sm${e.id === shown?.id ? " on" : ""}`}
                    onClick={() => onFocus(e.id)}>{e.name}</button>
          ))}
          <span className="hint" style={{ margin: 0 }}>
            한 번에 하나씩 봅니다 — 잰 값은 그대로 남습니다</span>
        </div>
      )}

      {/* 목표를 끌거나 **쳐 넣는다** — 95 를 정확히 맞추려고 끌어 맞출 일이 아니다 */}
      <div className="pw-aim">
        <span className="hint" style={{ margin: 0 }}>목표 검정력</span>
        <input type="range" min={50} max={99} step={1} value={target}
               aria-label="목표 검정력 끌기"
               onChange={(e) => { setTyped(""); setTarget(Number(e.target.value)); }} />
        <input className="pw-aimin" type="number" min={50} max={99}
               aria-label="목표 검정력 입력"
               value={typed === "" ? target : typed}
               onChange={(e) => setTyped(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") applyTyped(); }}
               onBlur={applyTyped} />
        <span className="hint" style={{ margin: 0 }}>% · 엔터</span>
        <span className="hint" style={{ margin: 0 }}>
          더 확실히 잡으려 할수록 필요한 크기가 커집니다</span>
      </div>

      {/* 잡히는 영역과 못 잡는 영역을 한 줄로 — 잰 값이 어디에 서 있는지 */}
      <div className="pw-axis" style={{ height: 26 + (rows - 1) * 15 }}>
        <div className="pw-dead" style={{ width: pct(p.cut) }} title={p.band} />
        <div className="pw-cut" style={{ left: pct(p.cut) }} />
        {onLine.map((r) => (
          <div key={r.id} className={`pw-mark${r.catchable ? " ok" : ""}`}
               style={{ left: pct(Math.abs(r.value)),
                        top: 2 + (laneOf.get(r.id) ?? 0) * 15 }}
               title={`${r.name} ${r.value.toFixed(4)}`}>
            <i />{Math.abs(r.value).toFixed(2)}
          </div>
        ))}
      </div>
      <div className="pw-scale">
        <span>0</span><span className="pw-cutlab" style={{ left: pct(p.cut) }}>
          {p.cut.toFixed(2)}</span><span>{top.toFixed(1)}</span>
      </div>
      <div className="hint" style={{ margin: 0 }}>
        <span className="pw-swatch" /> {p.band}
      </div>

      {onLine.map((r) => (
        <div key={r.id} className={`pw-row${r.catchable ? "" : " short"}`}>
          <b>{r.name}</b> {r.value.toFixed(4)} — {r.line}
        </div>
      ))}
      {off.length > 0 && (
        <div className="pw-off">
          {off.map((r) => (
            <div key={r.id} className="hint" style={{ margin: 0 }}>
              <b>{r.name}</b> {r.value.toFixed(4)} — {r.line}
            </div>
          ))}
        </div>
      )}

      {(p.ladder ?? []).length > 1 && (
        <details className="pw-more">
          <summary>표본을 더 모으면</summary>
          <table><thead><tr><th>n</th><th>잡히는 가장 작은 |상관|</th></tr></thead>
            <tbody>{p.ladder!.map((x) => (
              <tr key={x.n} className={x.n === p.n ? "mid" : ""}>
                <td className="num">{x.n.toLocaleString()}</td>
                <td className="num">{x.cut.toFixed(3)}</td></tr>
            ))}</tbody></table>
        </details>
      )}

      <div className="hint" style={{ margin: 0 }}>{p.why}</div>
      <div className="hint" style={{ margin: 0 }}>{p.scale_note}</div>
    </div>
  );
}
