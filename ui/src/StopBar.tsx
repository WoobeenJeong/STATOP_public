/** [중지] — 지금 기다리는 요청을 전부 끊는다.
 *
 * 되돌리기가 아니다. 누른 작업을 취소하지 않고 **화면이 기다리는 것만 끊는다** —
 * 서버가 이미 시작한 계산은 그대로 끝난다. 무한정 기다리다 창을 닫는 일이
 * 없어야 한다는 것이 이 버튼의 전부다.
 *
 * 맨 위에 항상 있다. 멈춘 뒤에 찾아 헤매면 늦다.
 */

import { useEffect, useState } from "react";
import { abortAll, onInflight } from "./api";

export default function StopBar() {
  const [n, setN] = useState(0);
  const [stopped, setStopped] = useState(0);

  useEffect(() => onInflight(setN), []);

  // Esc 로도 끊긴다 — 마우스를 옮기는 것도 기다리는 시간이다
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && n > 0) setStopped(abortAll());
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [n]);

  return (
    <div className="stopbar">
      <button className={n > 0 ? "sm danger" : "sm"} disabled={n === 0}
              onClick={() => setStopped(abortAll())}>
        중지{n > 0 ? ` (${n})` : ""}
      </button>
      <span className="hint" style={{ margin: 0 }}>
        {n > 0
          ? "기다리는 중입니다 — [중지] 또는 Esc 로 끊을 수 있습니다"
          : stopped
            ? `${stopped}건 중지함 — 계산은 서버에서 끝나며, 다시 누르면 됩니다`
            : "진행 중인 작업 없음"}
      </span>
    </div>
  );
}
