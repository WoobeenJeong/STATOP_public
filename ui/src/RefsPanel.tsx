/** A6 논문 앵커  — 비슷한 질문·검정을 다룬 논문의 제목·PMID.
 *
 * 나가는 것은 **검정 이름·질문 유형·군 라벨**뿐이다. 원자료는 나가지 않는다.
 * v1 은 제목 수준이므로 내용이 맞는지는 사람이 확인한다.
 */

import { useState } from "react";
import { api, type Anchors } from "./api";

export default function RefsPanel({ sessionFile }: { sessionFile: string }) {
  const [a, setA] = useState<Anchors | null>(null);
  const [labels, setLabels] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run() {
    setBusy(true); setErr("");
    try {
      setA(await api.references(sessionFile, 5, labels));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="ttl">논문 앵커 (A6) — 비슷한 질문·검정을 다룬 논문</div>
      <div className="row">
        <button className="pri" disabled={busy} onClick={run}>
          {busy ? "찾는 중…" : "논문 찾기"}
        </button>
        <label className="hint" style={{ margin: 0 }}>
          <input type="checkbox" checked={labels}
                 onChange={(e) => setLabels(e.target.checked)} />
          {" "}군 라벨도 검색어에 넣기
        </label>
      </div>
      {err && <div className="err">{err}</div>}

      {a && (
        <>
          <div className="hint">{a.privacy}</div>
          {a.failed ? (
            <div className="warnbox">{a.failed}</div>
          ) : (
            <>
              <div className="hint" style={{ marginTop: 6 }}>
                검색어: <code>{a.query}</code>
              </div>
              {a.broadened_note && <div className="mid">{a.broadened_note}</div>}
              {a.none && <div className="warnbox">{a.none}</div>}
              {a.papers.map((p) => (
                <div key={p.pmid} className="rf-item">
                  <a href={p.url} target="_blank" rel="noreferrer">{p.title}</a>
                  <div className="hint" style={{ margin: 0 }}>
                    PMID {p.pmid} · {p.journal} {p.year}
                  </div>
                </div>
              ))}
              {a.papers.length > 0 && (
                <div className="hint">{a.title_only}</div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
