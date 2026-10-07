/** 강건성 — 지금 낸 결론이 얼마나 버티나.
 *
 * 문서에 "이 지표는 강건하다/아니다"를 등급으로 적으면 어떤 자료에서는 맞고 어떤
 * 자료에서는 틀린다. 같은 '불균형'이라도 극단이냐 경계선이냐가 전혀 다르기 때문이다.
 * 그래서 등급 대신 **이 자료에서 직접 흔들어 보고** 결과가 어디까지 움직이는지 보인다.
 */

import { useState } from "react";
import { api, type Robust } from "./api";

function Row({ s, fallback }: { s: Robust["outliers"][0]; fallback: string }) {
  if (s.failed) {
    return <div className="mid">{s.label}: {s.failed}</div>;
  }
  return (
    <div className={s.flipped ? "high" : ""}>
      {s.label}: {s.effect_name || fallback}={s.effect?.toPrecision(4)}
      {s.p !== null && ` · p=${s.p.toPrecision(3)}`}
      {s.flipped && " ← 방향 뒤집힘"}
    </div>
  );
}

export default function RobustPanel({ sessionFile }: { sessionFile: string }) {
  const [r, setR] = useState<Robust | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run() {
    setBusy(true); setErr("");
    try {
      setR(await api.robust(sessionFile));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="ttl">강건성 — 지금 결론이 얼마나 버티나</div>
      <div className="row">
        <button className="pri" disabled={busy} onClick={run}>
          {busy ? "흔들어 보는 중…" : "흔들어 보기"}
        </button>
        <span className="hint" style={{ margin: 0 }}>
          표본·이상치·고른 검정을 바꿔 결과가 어디까지 움직이는지 봅니다
        </span>
      </div>
      {err && <div className="err">{err}</div>}

      {r && (
        <>
          <div className="hint">{r.base}</div>

          <div className="rb-sec">
            <b>{r.heads.boot}</b>
            <div>{r.band}</div>
          </div>

          <div className="rb-sec">
            <b>{r.heads.outlier}</b>
            {r.outliers.map((s) => (
              <Row key={s.label} s={s} fallback={r.effect_name} />
            ))}
            <div className="hint" style={{ marginTop: 2 }}>{r.caveat}</div>
          </div>

          <div className="rb-sec">
            <b>{r.heads.choice}</b>
            {r.choices.map((s) => (
              <Row key={s.label} s={s} fallback={r.effect_name} />
            ))}
          </div>

          <div className="rb-sec">
            <b>{r.heads.read}</b>
            {r.verdict.map((v) => (
              <div key={v} className="rb-read">{v}</div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
