/** 가드레일 한계값 설정 .
 *
 * 임계값은 조정할 수 있지만 **완화 하한(floor) 아래로는 못 내린다** — 서버가 거부한다.
 * 조정한 값은 기준값과 나란히 보여서, 지금 보고 있는 판정이 기본 기준인지 내가 푼
 * 기준인지 헷갈리지 않게 한다.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

type Limits = Awaited<ReturnType<typeof api.guardLimits>>;

const TIERS = ["gate", "diagnostic", "info", "off"] as const;
const TIER_LABEL: Record<string, string> = {
  gate: "차단(Gate)", diagnostic: "진단(Diagnostic)", info: "정보(Info)", off: "끔",
};

export default function GuardLimits() {
  const [data, setData] = useState<Limits | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setData(await api.guardLimits());
      setErr("");
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function apply(rule: string, body: { tier?: string; key?: string;
                                             value?: unknown }) {
    setBusy(true);
    try {
      await api.setGuardLimit({ rule, ...body });
      setErr("");
      await load();
    } catch (e) {
      // floor 위반은 서버가 막는다 — 그 이유를 그대로 보여준다
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <div className="card hint">{err || "한계값을 불러오는 중…"}</div>;

  return (
    <details className="card">
      <summary>
        <b>가드레일 한계값</b>
        <span className="hint"> — 조정할 수 있지만 하한 아래로는 내려가지 않습니다</span>
      </summary>
      {err && <div className="err">{err}</div>}

      {data.rules.map((r) => (
        <div className="gl-rule" key={r.rule}>
          <div className="row">
            <b>{r.rule}</b>
            <select value={r.base_tier} disabled={busy}
                    onChange={(e) => apply(r.rule, { tier: e.target.value })}>
              {TIERS.map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}
            </select>
            {r.floor && (
              <span className="hint" style={{ margin: 0 }}>
                하한 {TIER_LABEL[r.floor] ?? r.floor} — 이 아래로는 못 낮춥니다
              </span>
            )}
          </div>
          {r.limits.map((l) => {
            const k = `${r.rule}:${l.key}`;
            return (
              <div className="row gl-limit" key={k}>
                <span className="col" style={{ minWidth: 160 }}>{l.key}</span>
                <input type="text" style={{ width: 110 }} disabled={busy}
                       value={draft[k] ?? String(l.value)}
                       onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
                <button className="sm" disabled={busy}
                        onClick={() => apply(r.rule, { key: l.key,
                                                       value: draft[k] ?? l.value })}>
                  적용
                </button>
                <span className="hint" style={{ margin: 0 }}>
                  기준값 {String(l.base)}
                  {l.overridden && " · 지금은 조정된 값입니다"}
                </span>
              </div>
            );
          })}
        </div>
      ))}
      <div className="hint">조정 기록: {data.overrides_path}</div>
    </details>
  );
}
