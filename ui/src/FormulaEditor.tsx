/** 수식 편집기 (M1-2, ) — KaTeX 렌더 · 컬럼 칩 · 키패드.
 *
 * 무엇이 허용되는지는 서버가 정한다. 이 화면은 색을 입히고 커서를 옮길 뿐이다.
 * 렌더에 쓰는 LaTeX도 서버가 **계산되는 트리에서** 만들어 보내므로,
 * 화면에 보이는 식과 실제 계산되는 식이 어긋날 수 없다.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { api, type DerivePreview, type TokenRole } from "./api";

// 역할 → 화면 표시. 색만으로 구분하지 않는다 — 점선 밑줄·범례를 함께 쓴다 (design-tokens 3절)
const ROLE_LABEL: Record<string, string> = {
  binning: "구간·자리수",
  column: "컬럼",
  row_func: "행 단위 함수",
  column_scalar_func: "컬럼 스칼라",
  set_func: "세트 함수",
  pair_func: "두 컬럼 함수",
  eps: "eps",
};

const LEGEND: TokenRole[] = ["column", "row_func", "column_scalar_func", "set_func", "eps"];

interface Props {
  sessionFile: string;
  columns: string[];          // 가져온 분석 컬럼 — 칩으로 꽂는다
  onCommitted?: (name: string) => void;
  suggested?: { expr: string; name: string } | null;   // 지표 찾기가 권한 식
}

export default function FormulaEditor({ sessionFile, columns, onCommitted,
                                        suggested }: Props) {
  const [expr, setExpr] = useState("");
  const [name, setName] = useState("");
  const [eps, setEps] = useState<number | null>(null);
  const [pv, setPv] = useState<DerivePreview | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  // 권한 식이 오면 칸에 꽂는다 — 적어 두고 사용자가 옮겨 적게 하지 않는다
  useEffect(() => {
    if (suggested) { setExpr(suggested.expr); setName(suggested.name); }
  }, [suggested]);
  const [committed, setCommitted] = useState("");
  const [keypad, setKeypad] = useState<{ role: TokenRole | "binning";
                                        functions: string[] }[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const math = useRef<HTMLDivElement>(null);

  useEffect(() => { api.deriveFunctions().then((r) => setKeypad(r.groups)).catch(() => {}); }, []);

  /** 비면 그 자리에서 지운다 — effect에서 지우면 렌더가 한 번 더 돈다 */
  function changeExpr(next: string) {
    setExpr(next);
    if (!next.trim()) { setPv(null); setErr(""); }
  }

  // 타자마다 서버를 때리지 않는다 — 멈춘 뒤에 한 번 (컬럼이 수천이면 파싱도 비용이다)
  useEffect(() => {
    if (!expr.trim()) return;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        setPv(await api.derivePreview(sessionFile, expr, eps));
        setErr("");
      } catch (e) {
        setPv(null);
        setErr(String(e instanceof Error ? e.message : e));
      } finally {
        setBusy(false);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [expr, eps, sessionFile]);

  useEffect(() => {
    if (!math.current) return;
    if (!pv) { math.current.innerHTML = ""; return; }
    // throwOnError: 서버가 만든 LaTeX가 안 그려지면 조용히 넘어가지 않고 드러낸다
    try {
      katex.render(pv.latex, math.current, { displayMode: true, throwOnError: true });
    } catch {
      math.current.textContent = pv.expr;
    }
  }, [pv]);

  /** 커서 위치에 끼워 넣는다 — 끝에 붙이면 괄호 안에 컬럼을 넣을 수가 없다 */
  const insert = useCallback((text: string, caretBack = 0) => {
    const el = input.current;
    const at = el ? (el.selectionStart ?? expr.length) : expr.length;
    const end = el ? (el.selectionEnd ?? at) : at;
    const next = expr.slice(0, at) + text + expr.slice(end);
    setExpr(next);
    requestAnimationFrame(() => {
      el?.focus();
      const pos = at + text.length - caretBack;
      el?.setSelectionRange(pos, pos);
    });
  }, [expr]);

  async function commit() {
    if (!name.trim() || !pv) return;
    setBusy(true);
    try {
      const r = await api.deriveCommit(sessionFile, expr, name.trim(), eps);
      setCommitted(`${r.name} (${r.result_type})`);
      setExpr(""); setName(""); setEps(null); setPv(null);
      onCommitted?.(r.name);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  const hasScalar = pv?.tokens.some((t) => t.role === "column_scalar_func");
  const epsNeeded = pv?.uses_eps ?? false;
  const rec = pv?.eps?.recommended ?? null;

  // 버튼을 회색으로만 두지 않는다 — 무엇을 하면 눌리는지 옆에 적는다
  const blocked = busy ? "확인하는 중입니다"
    : !expr.trim() ? "식을 먼저 쓰세요"
    : !pv ? "식에 오류가 있습니다"
    : !name.trim() ? "새 컬럼 이름을 쓰세요"
    : epsNeeded && eps === null ? "eps를 고르면 저장할 수 있습니다"
    : "";

  return (
    <div className="card" id="fx">
      <div className="ttl">파생 컬럼 만들기</div>

      <div className="row">
        <input ref={input} type="text" value={expr} spellCheck={false}
               className="fx-input" placeholder="log2(frac_A + eps)"
               onChange={(e) => changeExpr(e.target.value)} />
        <button className="sm" disabled={!expr} onClick={() => changeExpr("")}>
          지우기
        </button>
      </div>

      {/* 컬럼 칩 — 이름을 외워 타자칠 필요가 없게 */}
      {columns.length > 0 && (
        <div className="fx-chips">
          {columns.map((c) => (
            <button key={c} className="fx-chip" onClick={() => insert(c)}>{c}</button>
          ))}
        </div>
      )}

      {/* 키패드 — 역할별로 묶는다. 어떤 함수가 컬럼 스칼라인지 여기서 이미 보인다 */}
      <div className="fx-pad">
        {keypad.filter((g) => g.functions.length).map((g) => (
          <div className="fx-padrow" key={g.role}>
            <span className={`fx-tag r-${g.role}`}>{ROLE_LABEL[g.role]}</span>
            {g.functions.map((f) => (
              <button key={f} className={`fx-key r-${g.role}`}
                      onClick={() => insert(`${f}()`, 1)}>{f}</button>
            ))}
          </div>
        ))}
        <div className="fx-padrow">
          <span className="fx-tag">연산</span>
          {["+", "-", "*", "/", "**"].map((o) => (
            <button key={o} className="fx-key" onClick={() => insert(` ${o} `)}>{o}</button>
          ))}
          <button className="fx-key" onClick={() => insert("()", 1)}>( )</button>
          <button className="fx-key r-eps" onClick={() => insert("eps")}>eps</button>
          {/* 상수 — 3.141592653589793 을 손으로 적으면 자릿수에서 틀린다 */}
          <button className="fx-key r-const" onClick={() => insert("pi")}>pi</button>
          <button className="fx-key r-const" onClick={() => insert("e")}>e</button>
        </div>
      </div>

      {err && <div className="err">{err}</div>}

      {pv && (
        <>
          {/* 렌더 — 서버가 계산 트리에서 만든 LaTeX 그대로 */}
          <div className="fx-math" ref={math} />

          {/* 색 구분  — 어디가 행마다 변하고 어디가 한 수로 줄어드는지 */}
          <div className="fx-tokens">
            {pv.tokens.map((t, i) => (
              <span key={i} className={`r-${t.role}`}>{t.text}</span>
            ))}
          </div>
          <div className="fx-legend">
            {LEGEND.map((r) => (
              <span key={r}><i className={`r-${r}`} />{ROLE_LABEL[r]}</span>
            ))}
          </div>
          {hasScalar && (
            <div className="fx-note">
              점선 밑줄이 그어진 부분은 컬럼 전체를 하나의 수로 줄인 값입니다 —
              행마다 달라지지 않습니다.
            </div>
          )}

          {/* eps 를 고르기 **전에** 읽혀야 하므로 eps 칸 위에 둔다 (S-R04 → F-15) */}
          {pv.alternative && <div className="hint fx-alt">{pv.alternative}</div>}

          {epsNeeded && (
            <div className="row fx-eps">
              <span className="fx-tag r-eps">eps</span>
              {(pv.eps?.candidates ?? []).map((c) => (
                <button key={c} className={`sm${eps === c ? " on" : ""}`}
                        onClick={() => setEps(c)}>{c.toExponential(0)}</button>
              ))}
              {rec !== null && (
                <span className="hint" style={{ margin: 0 }}>
                  추천 {rec.toExponential(0)} 이하만 허용 · 최소 양수 {pv.eps?.min_positive?.toPrecision(3)}
                </span>
              )}
            </div>
          )}
          {pv.eps?.auto && (
            <div className="fx-note">
              추천값으로 미리 계산해 보여주는 중입니다. 저장하려면 eps를 직접 고르세요 —
              기록에 남아야 나중에 같은 결과를 재현할 수 있습니다.
            </div>
          )}

          {pv.preview.distinct_before != null && (
            <div className="fx-lossy">
              <b>값이 뭉개집니다</b> — 고유값 {pv.preview.distinct_before}개 →{" "}
              {pv.preview.distinct_after}개. 되돌릴 수 없습니다.
              {pv.preview.levels && (
                <div>생기는 값: {pv.preview.levels.map((v) => v).join(", ")}
                  {(pv.preview.distinct_after ?? 0) > pv.preview.levels.length && " …"}
                </div>
              )}
            </div>
          )}

          <div className="fx-stats">
            <span>n {pv.preview.n.toLocaleString()}</span>
            <span>유한 {pv.preview.n_finite.toLocaleString()}</span>
            <span className={pv.preview.n_nan ? "bad" : ""}>NaN {pv.preview.n_nan.toLocaleString()}</span>
            <span className={pv.preview.n_inf ? "bad" : ""}>±inf {pv.preview.n_inf.toLocaleString()}</span>
            {pv.preview.n_finite > 0 && (
              <span>
                {pv.preview.min?.toPrecision(4)} ~ {pv.preview.max?.toPrecision(4)}
              </span>
            )}
            <span className="fx-rtype">{pv.result_type}</span>
          </div>

        </>
      )}

      {/* 이름칸과 만들기 버튼은 **항상 보인다.** 미리보기 안에 두면 식을 고치는
          도중(괄호를 아직 안 닫은 순간)마다 버튼이 사라져 고장난 것처럼 보인다 */}
      <div className="row" style={{ marginTop: 12 }}>
        <input type="text" value={name} placeholder="새 컬럼 이름" spellCheck={false}
               style={{ minWidth: 160 }} onChange={(e) => setName(e.target.value)} />
        <button className="pri" disabled={busy || !pv || !name.trim() || (epsNeeded && eps === null)}
                onClick={commit}>
          파생 컬럼 만들기
        </button>
        {blocked && <span className="hint" style={{ margin: 0 }}>{blocked}</span>}
      </div>

      {committed && <div className="fx-done">파생 컬럼 생성: {committed}</div>}
    </div>
  );
}
