/** 모델링 감사 (모듈 B) — 학습 결과를 믿어도 되는가.
 *
 * 모듈 A(가설검정)와 **별개**다. 여기서 보는 것은 성능 숫자가 의미를 갖기 위한 전제다.
 * 구성(B1)을 먼저 확정해야 돌아간다.
 *
 * 다섯 갈래. 앞의 셋은 Gate(막는다), 뒤의 둘은 Diag(막지 않고 크기를 말한다):
 * ① 세트 파일을 보는 누수 검사 (~) — 중복·그룹 교차·시간 누수·라벨 대리변수
 * ② 세트가 만들어진 과정  — 분할 비율·원본에서의 손실
 * ③ 학습 코드를 읽는 검사  — 나누기 전에 학습한 전처리·피처선택
 * ④ 라벨 인코딩 방향  — 어느 수준이 1인가
 * ⑤ 균형·분포  — 클래스 비율·지름길 학습·개발 vs 외부 분포
 * ⑥ 전처리·평가  — 표준화·EPV·모델 비교 · ROC/PR·보정·클래스별 성능
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

// 검사 묶음의 공통 모양. split 만 **무엇을 키로 썼는지**를 함께 돌려준다
type Leak = Awaited<ReturnType<typeof api.modelLeak>>
          & { key?: string; key_note?: string };

const ICON: Record<string, string> = { fail: "⛔", pass: "✅", skipped: "○" };
// Gate 만 막는다. Diag 는 얼마나 문제인지 말하고 통과시킨다 (CLI·TUI 와 같은 규칙)
const isGate = (grade: string) => grade.split("/")[0] === "Gate";

function Findings({ data }: { data: Leak }) {
  return (
    <>
      {data.findings.map((f, i) => {
        const gate = isGate(f.grade);
        const icon = f.verdict === "fail" ? (gate ? "⛔" : "⚠") : ICON[f.verdict];
        return (
          <div className={`lk-item v-${f.verdict}${!gate ? " lk-diag" : ""}`}
               key={`${f.id}-${i}`}>
            <div>
              {icon} <b>{f.id}</b> {f.summary}
              <span className="hint"> · {f.grade}</span>
            </div>
            {f.detail.map((d, j) => (
              <div className="hint" style={{ margin: 0 }} key={j}>{d}</div>
            ))}
            {f.action && <div className="lk-action">→ {f.action}</div>}
          </div>
        );
      })}
    </>
  );
}

/** 한 검사 묶음 — 불러오기·에러·표시를 한 자리에 모은다 */
function useAudit(run: () => Promise<Leak>) {
  const [data, setData] = useState<Leak | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const go = useCallback(async () => {
    setBusy(true);
    try {
      setData(await run());
      setErr("");
    } catch (e) {
      setData(null);
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }, [run]);
  return { data, err, busy, go };
}

export default function ModelLeak({ sessionFile }: { sessionFile: string }) {
  //  — 키·기대비율은 선택이다. 없으면 그 검사만 건너뛴다(통과가 아니다)
  const [key, setKey] = useState("");
  const [expect, setExpect] = useState("");
  const [path, setPath] = useState("");   //  — 코드는 읽기만 한다
  //  — 라벨과의 연관을 볼 메타 (기관·배치·나이). 비우면 hold 한 컬럼을 쓴다
  const [meta, setMeta] = useState("");
  //  — 학습을 돌리지 않으므로 모델 구성은 사용자가 적어 준다 (한 줄에 하나)
  const [models, setModels] = useState("");

  // 판정이 지목한 컬럼 — 어느 컬럼인지 사용자가 다시 칠 일이 아니다
  const [shift, setShift] = useState<Awaited<
    ReturnType<typeof api.modelShift>> | null>(null);

  const leak = useAudit(useCallback(() => api.modelLeak(sessionFile), [sessionFile]));
  const split = useAudit(useCallback(
    () => api.modelSplit(sessionFile, key, expect), [sessionFile, key, expect]));
  const labels = useAudit(useCallback(
    () => api.modelLabels(sessionFile), [sessionFile]));
  const code = useAudit(useCallback(() => api.modelCode(path.trim()), [path]));
  const balance = useAudit(useCallback(
    () => api.modelBalance(sessionFile, meta), [sessionFile, meta]));
  const prep = useAudit(useCallback(() => api.modelPrep(sessionFile), [sessionFile]));
  const evalu = useAudit(useCallback(() => api.modelEval(sessionFile), [sessionFile]));
  const repro = useAudit(useCallback(() => api.modelRepro(sessionFile), [sessionFile]));
  const [seedCode, setSeedCode] = useState("");   // MB-C25 고정 코드 (누를 때만)
  const cmp = useAudit(useCallback(() => api.modelCompare(models), [models]));

  useEffect(() => { void leak.go(); }, [leak.go]);
  useEffect(() => { void labels.go(); }, [labels.go]);

  const failed = [leak, split, labels, code, balance, prep, cmp, evalu, repro]
    .reduce((n, a) => n + (a.data?.n_failed ?? 0), 0);
  // 분포가 달라졌다고 지목된 컬럼은 판정이 이미 안다 (MB-C07 의 kinds) —
  // 사용자가 컬럼 이름을 다시 칠 일이 아니다
  const shiftedCols = (split.data?.findings ?? [])
    .flatMap((f) => Object.keys(
      (f.numbers?.kinds as Record<string, string> | undefined) ?? {}));

  return (
    <details className="card">
      <summary>
        <b>모델링 감사 (모듈 B)</b>
        <span className="hint"> — 학습은 실행하지 않습니다</span>
        {failed > 0 && <span className="lk-badge">⛔ {failed}</span>}
      </summary>

      {/* 세트가 만들어진 과정  */}
      <div className="row">
        <input type="text" value={key} style={{ flex: 1 }} disabled={split.busy}
               placeholder="키 컬럼 — 비우면 확정한 행 식별자를 씁니다"
               onChange={(e) => setKey(e.target.value)} />
        <input type="text" value={expect} style={{ flex: 1 }} disabled={split.busy}
               placeholder="기대 비율 — 예: train=8,test=2"
               onChange={(e) => setExpect(e.target.value)} />
        <button className="sm" disabled={split.busy} onClick={() => void split.go()}>
          {split.busy ? "검사 중…" : "비율·손실 검사"}
        </button>
      </div>
      {split.err && <div className="err">{split.err}</div>}
      {split.data && (
        <>
          <div className="hint" style={{ margin: 0 }}>{split.data.head}</div>
          {!key && <div className="hint" style={{ marginTop: 0 }}>{split.data.key_note}</div>}
          <Findings data={split.data} />
        </>
      )}
      {shiftedCols.length > 0 && (
        <div className="row">
          <button className="sm" onClick={() => {
            void api.modelShift(sessionFile, key || (split.data?.key ?? ""),
                                shiftedCols.join(","))
              .then(setShift).catch(() => setShift(null));
          }}>분포 비교 ({shiftedCols.join(", ")})</button>
        </div>
      )}
      {shift?.views.map((v) => (
        <pre className="mb-shift" key={v.column}>{v.lines.join("\n")}</pre>
      ))}

      {/* 누수 4종 (~) */}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="sm" disabled={leak.busy} onClick={() => void leak.go()}>
          {leak.busy ? "검사 중…" : "누수 다시 검사"}
        </button>
        {leak.data && <span className="hint" style={{ margin: 0 }}>{leak.data.head}</span>}
      </div>
      {leak.err && <div className="err">{leak.err}</div>}
      {leak.data && <Findings data={leak.data} />}

      {/* 라벨 인코딩 방향  — 고치는 것은 라벨 매핑 화면이다 */}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="sm" disabled={labels.busy} onClick={() => void labels.go()}>
          {labels.busy ? "검사 중…" : "라벨 방향 다시 검사"}
        </button>
        {labels.data && (
          <span className="hint" style={{ margin: 0 }}>{labels.data.head}</span>
        )}
      </div>
      {labels.err && <div className="err">{labels.err}</div>}
      {labels.data && <Findings data={labels.data} />}

      {/* · — 클래스 비율·숨은 불균형·세트 간 분포. 전부 Diag */}
      <div className="row" style={{ marginTop: 12 }}>
        <input type="text" value={meta} style={{ flex: 1 }} disabled={balance.busy}
               placeholder="메타 컬럼 (기관·배치·나이) — 비우면 hold 한 컬럼"
               onChange={(e) => setMeta(e.target.value)} />
        <button className="sm" disabled={balance.busy} onClick={() => void balance.go()}>
          {balance.busy ? "검사 중…" : "균형·분포 검사"}
        </button>
      </div>
      {balance.err && <div className="err">{balance.err}</div>}
      {balance.data && (
        <>
          <div className="hint" style={{ margin: 0 }}>{balance.data.head}</div>
          <Findings data={balance.data} />
        </>
      )}

      {/* · — 표준화·차원축소·EPV. 어느 컬럼이 척도를 끌고 가는지 지목한다 */}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="sm" disabled={prep.busy} onClick={() => void prep.go()}>
          {prep.busy ? "검사 중…" : "전처리·모델 적합 검사"}
        </button>
        {prep.data && <span className="hint" style={{ margin: 0 }}>{prep.data.head}</span>}
      </div>
      {prep.err && <div className="err">{prep.err}</div>}
      {prep.data && <Findings data={prep.data} />}

      {/*  — 예측을 본다. probability 로 확정된 컬럼이 있어야 열린다 */}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="sm" disabled={evalu.busy} onClick={() => void evalu.go()}>
          {evalu.busy ? "검사 중…" : "평가 감사"}
        </button>
        {evalu.data && (
          <span className="hint" style={{ margin: 0 }}>{evalu.data.head}</span>
        )}
      </div>
      {evalu.err && <div className="err">{evalu.err}</div>}
      {evalu.data && <Findings data={evalu.data} />}

      {/*  — 견줄 수 없는 모델쌍을 지목한다 */}
      <div className="row" style={{ marginTop: 12 }}>
        <input type="text" value={models} style={{ flex: 1 }} disabled={cmp.busy}
               placeholder='모델 (세미콜론 구분) — "m1: age+sex [n=480] [y=death]; m2: age+sex+stage [n=480] [y=death]"'
               onChange={(e) => setModels(e.target.value)} />
        <button className="sm" disabled={cmp.busy || !models.trim()}
                onClick={() => void cmp.go()}>
          {cmp.busy ? "검사 중…" : "모델 비교 확인"}
        </button>
      </div>
      {cmp.err && <div className="err">{cmp.err}</div>}
      {cmp.data && <Findings data={cmp.data} />}

      {/* · — 지표를 바꿨는가 · 같은 결과가 다시 나오는가 */}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="sm" disabled={repro.busy} onClick={() => void repro.go()}>
          {repro.busy ? "검사 중…" : "지표 변경·재현성 검사"}
        </button>
        <button className="sm" onClick={() => {
          void api.modelSeed(sessionFile).then((r) => setSeedCode(r.code))
            .catch(() => setSeedCode(""));
        }}>seed 고정 코드</button>
        {repro.data && (
          <span className="hint" style={{ margin: 0 }}>{repro.data.head}</span>
        )}
      </div>
      {repro.err && <div className="err">{repro.err}</div>}
      {repro.data && <Findings data={repro.data} />}
      {seedCode && <pre className="mb-shift">{seedCode}</pre>}

      {/*  — 코드는 읽기만 한다 */}
      <div className="row" style={{ marginTop: 12 }}>
        <input type="text" value={path} style={{ flex: 1 }} disabled={code.busy}
               placeholder="학습 코드 파일 경로 (.py) — 읽기만 합니다"
               onChange={(e) => setPath(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") void code.go(); }} />
        <button className="sm" disabled={code.busy || !path.trim()}
                onClick={() => void code.go()}>
          {code.busy ? "검사 중…" : "코드 검사"}
        </button>
      </div>
      {code.err && <div className="err">{code.err}</div>}
      {code.data && (
        <>
          <div className="hint" style={{ margin: 0 }}>{code.data.head}</div>
          <Findings data={code.data} />
        </>
      )}
    </details>
  );
}
