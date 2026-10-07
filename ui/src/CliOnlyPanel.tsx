/** CLI 에서만 하는 작업 안내.
 *
 * 전치·사본 저장·무결성 검증용 파일 불러오기는 **원본 파일 경로를 직접 다루는** 일이다.
 * CLI 가 메인이고 파일을 쥐고 있으므로, 웹에서 반쯤 흉내 내면 어느 쪽이 진짜인지 갈린다.
 * 여기서는 무엇을 어디서 하는지만 정확히 알려준다.
 */

const ITEMS = [
  {
    title: "전치 (행/열 뒤집기)",
    why: "행·열을 뒤집으면 이후 모든 컬럼 판정이 달라집니다. 원본 옆에 새 파일로 만듭니다.",
    how: "터미널에서 statop → [전치] · 또는 statop transpose <파일>",
  },
  {
    title: "사본 저장 (가공 파일)",
    why: "결측 대치·행 제거·라벨 수정을 한 뒤에는 원본을 건드리지 않고 사본으로 남깁니다. "
      + "이후 작업은 그 사본을 기준으로 이어집니다.",
    how: "터미널에서 statop → [사본 저장] · 또는 statop export",
  },
  {
    title: "무결성 검증 (두 파일 대조)",
    why: "비교할 파일 경로를 하나 더 열어야 합니다. 파일을 여는 것도 대조 결과를 보는 것도 "
      + "터미널에서 합니다 — 웹에는 이 화면이 없습니다.",
    how: "터미널에서 statop → [무결성 검증] · 또는 statop integrity <파일A> <파일B>",
  },
];

export default function CliOnlyPanel() {
  return (
    <div className="card cli-only">
      <div className="ttl">터미널(CLI)에서 하는 작업</div>
      <div className="hint" style={{ marginTop: 0 }}>
        파일 자체를 만들거나 바꾸는 일은 CLI 가 맡습니다 — 어느 쪽이 진짜인지 갈리지 않게.
      </div>
      {ITEMS.map((x) => (
        <div className="cli-item" key={x.title}>
          <div><b>{x.title}</b></div>
          <div className="hint" style={{ margin: 0 }}>{x.why}</div>
          <div className="cli-how">{x.how}</div>
        </div>
      ))}
    </div>
  );
}
