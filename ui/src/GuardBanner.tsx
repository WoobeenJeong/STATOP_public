/** 가드레일 배너 (M4, ).
 *
 * 차단이 있으면 **화면 맨 위**에 붙는다 — 스크롤해야 보이는 경고는 없는 것과 같다.
 * 등급도 판정도 서버가 정한다. 이 화면은 순서대로 그리기만 한다.
 */

import { useState } from "react";
import { api, type GuardFinding, type GuardReport, type GuardTier } from "./api";

const TIER_LABEL: Record<GuardTier, string> = {
  gate: "차단", diagnostic: "진단", info: "참고", ok: "걸린 것 없음",
};

interface Props {
  sessionFile: string;
  group?: string;
  meta?: string[];
  metrics?: string[];
}

export default function GuardBanner({ sessionFile, group, meta = [], metrics = [] }: Props) {
  const [rep, setRep] = useState<GuardReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);

  async function check() {
    setBusy(true);
    setErr("");
    try {
      const r = await api.guardRun(sessionFile, group, meta, metrics);
      setRep(r);
      setOpen(true);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  const byRule = (rule: string) => (rep?.findings ?? []).filter((f) => f.rule === rule);

  return (
    <>
      {/* 차단 요약 — 본문보다 앞에, 접을 수 없게 */}
      {rep?.headline && <div className="gd-headline">{rep.headline}</div>}

      <div className="card">
        <div className="ttl">
          가드레일(Guardrail)
          {rep && <span className={`gd-tier t-${rep.tier}`}>{TIER_LABEL[rep.tier]}</span>}
        </div>
        <div className="row">
          <button className="pri" disabled={busy} onClick={check}>
            {busy ? "검사 중…" : rep ? "다시 검사" : "검사하기"}
          </button>
          {rep && (
            <button className="sm" onClick={() => setOpen(!open)}>
              {open ? "접기" : `펼치기 (${rep.findings.length}건)`}
            </button>
          )}
          <span className="hint" style={{ margin: 0 }}>
            손실 → 배정 비율 → 관측 불균형 → 값 범위 순으로 봅니다
          </span>
        </div>
        {err && <div className="err">{err}</div>}

        {rep && open && (
          <>
            {rep.order.map((rule) => {
              const items = byRule(rule);
              if (!items.length) return null;
              return (
                <div className="gd-rule" key={rule}>
                  <div className="gd-rulename">{rule}</div>
                  {items.map((f: GuardFinding, i) => (
                    <div className={`gd-item t-${f.tier}`} key={i}>
                      <span className="gd-badge">{TIER_LABEL[f.tier]}</span>
                      <span className="gd-check">{f.check}</span>
                      <span className="gd-detail">{f.detail}</span>
                      {f.links.length > 0 && (
                        <span className="gd-links">연결: {f.links.join(", ")}</span>
                      )}
                    </div>
                  ))}
                </div>
              );
            })}

            {/* 원인 후보 — 단정하지 않는다는 사실을 제목에 박아 둔다 () */}
            {rep.cause_trace?.candidate != null && (
              <div className="gd-cause">
                <div className="gd-causehead">원인 후보 (단정이 아닙니다)</div>
                {rep.cause_trace.candidate === "loss" && (
                  <div>군별 손실률 차이가 큽니다 — 손실이 원인 후보입니다</div>
                )}
                {typeof rep.cause_trace.branch === "string" && (
                  <div>{rep.cause_trace.branch}</div>
                )}
              </div>
            )}

            {/* 검사하지 않은 것과 통과한 것은 다르다 */}
            {rep.skipped.length > 0 && (
              <details>
                <summary>▸ <b>검사하지 않은 것 {rep.skipped.length}건</b></summary>
                <div className="inner">
                  {rep.skipped.map((s, i) => (
                    <div key={i}>{s.rule} — {s.reason}</div>
                  ))}
                </div>
              </details>
            )}

            {rep.overrides.length > 0 && (
              <div className="gd-over">
                기본값이 아닌 설정이 적용되었습니다
                {rep.overrides.map((o, i) => (
                  <div key={i}>{o.rule}.{o.key} = {String(o.value)} (기본 {String(o.base)})</div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
