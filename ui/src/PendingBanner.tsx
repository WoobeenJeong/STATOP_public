/** 저장하지 않은 값 변경 배너 — 웹에서 결측을 채우거나 행을 뺀 뒤의 다음 단계를 강제한다.
 *
 * 웹은 파일을 만들지 않는다. 그래서 값을 바꾼 상태로 두면 **원본과 다른 데이터로 일하는 중**
 * 인데 그 사실이 아무데도 남지 않는다. 순서를 눈에 보이게 고정한다:
 *   ① 웹→CLI 반영  ② CLI에서도 [웹→CLI 반영]  ③ CLI에서 [사본 저장]
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

interface Props {
  sessionFile: string;
  reloadKey?: number;      // 결측 대치·제거 뒤 다시 확인하라는 신호
}

export default function PendingBanner({ sessionFile, reloadKey = 0 }: Props) {
  const [info, setInfo] = useState<Awaited<ReturnType<typeof api.pending>> | null>(null);

  const load = useCallback(async () => {
    try {
      setInfo(await api.pending(sessionFile));
    } catch { /* 배너는 부가 정보 — 실패해도 화면을 막지 않는다 */ }
  }, [sessionFile]);

  useEffect(() => { void load(); }, [load, reloadKey]);

  if (!info?.needs_export) return null;
  const detail = Object.entries(info.counts)
    .map(([k, n]) => `${info.labels[k] ?? k} ${n}건`).join(" · ");

  return (
    <div className="pending">
      <b>저장하지 않은 값 변경 {info.total}건</b> — {detail}
      <div>
        지금은 <b>원본과 다른 데이터</b>로 보고 있습니다. 웹은 파일을 만들지 않으므로,
        아래 순서로 사본을 남겨야 이 상태가 보존됩니다.
      </div>
      <ol className="pending-steps">
        <li>이 화면에서 <b>[웹→CLI 반영]</b></li>
        <li>터미널에서도 <b>[웹→CLI 반영]</b> (두 번 확인)</li>
        <li>터미널에서 <b>[사본 저장]</b> — 원본은 그대로 두고 사본이 다음 기준이 됩니다</li>
      </ol>
    </div>
  );
}
