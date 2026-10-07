/** Ask Qwen — 버튼 한 번으로 가설 1안/2안을 받는다 .
 *
 * 대화가 아니다. 세션에 기록된 사실(타입·검정 결과·주의사항)만 담아 보내고, 무엇이
 * 전송되는지 먼저 볼 수 있다. 모델은 상주하지 않으므로 **지금 어느 단계인지**와
 * **얼마나 기다리는지**를 항상 보여준다 — 아무 반응 없이 기다리게 두지 않는다.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

type Status = Awaited<ReturnType<typeof api.qwenStatus>>;
type Answer = Awaited<ReturnType<typeof api.askQwen>>;

const STAGE_ICON: Record<string, string> = {
  ready: "●", model_missing: "◐", unreachable: "○", no_endpoint: "○",
};

export default function AskQwen({ sessionFile }: { sessionFile: string }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asking, setAsking] = useState(false);
  // 모델은 상주하지 않는다 — 올렸는지와 얼마나 걸렸는지를 화면이 기억한다
  const [loading, setLoading] = useState(false);
  const [loadNote, setLoadNote] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState("");
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.qwenStatus(sessionFile));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
  }, [sessionFile]);

  useEffect(() => { void refresh(); }, [refresh]);

  // 기다리는 동안 초를 센다 — 멈춘 것처럼 보이면 사용자가 창을 닫는다
  useEffect(() => {
    if (!asking) { if (timer.current) window.clearInterval(timer.current); return; }
    setElapsed(0);
    timer.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [asking]);

  async function run(dryRun: boolean) {
    setErr("");
    setAnswer(null);
    setAsking(!dryRun);
    try {
      setAnswer(await api.askQwen(sessionFile, dryRun));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setAsking(false);
      void refresh();
    }
  }

  async function doLoad() {
    setLoading(true);
    try {
      const r = await api.loadQwen();
      setLoadNote(r.detail);
      await refresh();
    } catch (e) {
      setLoadNote(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  const ready = status?.stage === "ready";
  const expect = status?.wait?.seconds ?? null;

  // LLM 이 안 붙어 있으면 **이 카드만** 접는다 — A1~A6 는 그대로 돈다 (요구사항).
  // 회색으로 끄기만 하면 무엇을 하면 되는지 알 수 없으니 이유도 같이 보인다
  if (status && status.available === false) {
    return (
      <div className="card a7-off">
        <div className="ttl">Ask Qwen — 지금은 쓸 수 없습니다</div>
        <div className="hint" style={{ marginTop: 0 }}>{status.why}</div>
        <div className="hint">{status.optional_note}</div>
        <button className="sm" onClick={() => void refresh()}>다시 확인</button>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="ttl">Ask Qwen — 가설 3종 (최적·보수적·넓게)</div>
      <div className="hint" style={{ marginTop: 0 }}>
        세션에 기록된 사실만 보냅니다. 판정은 규칙이 하고, Qwen 은 읽는 법만 제안합니다.
        모델은 상주하지 않으므로 먼저 한 번 올려야 합니다.
      </div>

      <div className="qw-status">
        <span className={`qw-dot s-${status?.stage ?? "no_endpoint"}`}>
          {STAGE_ICON[status?.stage ?? "no_endpoint"]}
        </span>
        <b>{status?.stage_label ?? "확인 중…"}</b>
        <span className="hint" style={{ margin: 0 }}>{status?.detail}</span>
        <button className="sm" onClick={() => void refresh()}>다시 확인</button>
      </div>
      <div className="hint" style={{ margin: 0 }}>{status?.wait_label}</div>
      {loadNote && <div className={ready ? "okbox" : "warnbox"}>{loadNote}</div>}

      <div className="row" style={{ marginTop: 8 }}>
        <button className="sm" disabled={loading || asking}
                onClick={() => void doLoad()}>
          {loading ? "올리는 중…" : "모델 불러오기"}
        </button>
        <button className="sm" disabled={asking} onClick={() => void run(true)}>
          보낼 내용 먼저 보기
        </button>
        <button className="pri" disabled={!ready || asking}
                onClick={() => void run(false)}
                title={ready ? "" : "모델을 먼저 불러오세요"}>
          {asking ? "묻는 중…" : "가설 받기"}
        </button>
      </div>

      {asking && (
        <div className="qw-wait">
          Qwen 에게 묻는 중… {elapsed}초 경과
          {expect != null && ` · 이 세션 평균 ${expect}초`}
          <div className="qw-bar">
            <span style={{ width: expect
              ? `${Math.min(100, (elapsed / expect) * 100)}%` : "40%" }} />
          </div>
          {expect != null && elapsed > expect * 2 && (
            <div>평소보다 오래 걸리고 있습니다 — 모델을 새로 올리는 중일 수 있습니다</div>
          )}
        </div>
      )}

      {err && <div className="err">{err}</div>}

      {answer?.dry_run && (
        <div className="qw-dry">
          <b>보낼 내용 (아직 보내지 않았습니다)</b>
          <pre>{answer.would_send}</pre>
          <div className="hint" style={{ margin: 0 }}>{answer.note}</div>
        </div>
      )}

      {answer && !answer.dry_run && (
        <div className="qw-answer">
          {/* 입장마다 세 줄 — 제목은 서버가 준다 (화면이 지어내지 않게) */}
          {(answer.proposals ?? []).map((p) => (
            <div className={`an-prop st-${p.stance}`} key={p.stance}>
              <b>{answer.labels?.[p.stance] ?? p.stance}</b>
              <div>{p.hypothesis}</div>
              {p.test && (
                <div className="hint" style={{ margin: 0 }}>
                  {answer.labels?.test}: {p.test}
                </div>
              )}
              {p.limit && (
                <div className="hint" style={{ margin: 0 }}>
                  {answer.labels?.limit}: {p.limit}
                </div>
              )}
            </div>
          ))}
          {!answer.proposals?.length && (
            <div className="err">형식이 맞지 않아 원문을 그대로 보여줍니다: {answer.raw}</div>
          )}
          <div className="hint" style={{ margin: 0 }}>
            모델 {answer.model} · 전송 기록 {answer.sent_log}
          </div>
        </div>
      )}
    </div>
  );
}
