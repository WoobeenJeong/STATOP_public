"""B2 코드 정적 감지  — split 이전 전처리·피처선택 (MB-C04, MB-C09). 둘 다 Gate.

세트 파일만 봐서는 잡을 수 없는 누수가 있다. **표준화를 전체 데이터로 한 번 fit 하고
그다음에 train/test 를 나누면**, test 의 평균·분산이 이미 train 쪽 값에 스며든다.
피처 선택도 같다 — 전체를 보고 고른 피처는 test 를 보고 고른 피처다.
파일에는 흔적이 남지 않고 **코드의 순서**에만 남는다.

그래서 여기서는 학습 코드를 **읽기만 한다**. 실행하지 않는다 (남의 코드를 돌리지 않는다).
파이썬 구문 트리에서 "나누는 줄"과 "학습(fit)하는 줄"의 순서를 본다.

**정적 감지의 한계를 그대로 말한다.** 여기서 못 찾았다는 것은 "이 코드에서 보이는
범위에서 못 찾았다"는 뜻이지 누수가 없다는 증명이 아니다. Pipeline 안에 넣은 전처리는
fold 안에서 fit 되므로 통과로 본다.
"""

import ast

from statop.messages import msg
from statop.modeling.leak import LeakFinding, grade_of, skip

# 표준화·정규화 (MB-C09) — fold 밖에서 fit 하면 test 의 분포가 train 에 새어든다
SCALERS = {
    "StandardScaler", "MinMaxScaler", "RobustScaler", "MaxAbsScaler",
    "Normalizer", "PowerTransformer", "QuantileTransformer",
}
# 그 밖의 split 이전 전처리·피처선택 (MB-C04)
SELECTORS = {
    "SelectKBest", "SelectPercentile", "SelectFromModel", "RFE", "RFECV",
    "VarianceThreshold", "SequentialFeatureSelector",
    "PCA", "TruncatedSVD", "FactorAnalysis", "NMF", "KernelPCA",
    "SimpleImputer", "KNNImputer", "IterativeImputer",
    "SMOTE", "ADASYN", "RandomOverSampler", "RandomUnderSampler",
}
# 나누는 곳 — 이 줄을 기준으로 앞/뒤가 갈린다
SPLITTERS = {
    "train_test_split", "KFold", "StratifiedKFold", "GroupKFold",
    "StratifiedGroupKFold", "TimeSeriesSplit", "ShuffleSplit",
    "GroupShuffleSplit", "LeaveOneOut", "LeaveOneGroupOut", "cross_val_score",
    "cross_validate", "cross_val_predict", "GridSearchCV", "RandomizedSearchCV",
}
# fold 안에서 fit 되므로 통과 — 전처리를 여기 넣는 것이 정답이다
PIPELINES = {"Pipeline", "make_pipeline", "ColumnTransformer", "make_column_transformer"}
FIT_METHODS = {"fit", "fit_transform", "fit_resample", "fit_sample"}


def _called_name(node: ast.AST) -> str:
    """Call 의 함수 이름 — `sklearn.decomposition.PCA(...)` 도 `PCA` 로."""
    f = node.func if isinstance(node, ast.Call) else node
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


class _Scan(ast.NodeVisitor):
    """변수 → 만든 클래스, fit 호출 줄, 나누는 줄, Pipeline 에 들어간 변수."""

    def __init__(self) -> None:
        self.made: dict[str, tuple[str, int]] = {}   # var → (class, lineno)
        self.fits: list[tuple[str, str, str, int]] = []  # (var, class, method, lineno)
        self.split_lines: list[tuple[str, int]] = []     # (splitter, lineno)
        self.in_pipeline: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            cls = _called_name(node.value)
            if cls in SCALERS | SELECTORS:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.made[t.id] = (cls, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _called_name(node)
        if name in SPLITTERS:
            self.split_lines.append((name, node.lineno))
        if name in PIPELINES:
            self._mark_pipeline(node)
        if name in FIT_METHODS and isinstance(node.func, ast.Attribute):
            recv = node.func.value
            if isinstance(recv, ast.Name):
                cls = self.made.get(recv.id, ("", 0))[0]
                if cls:
                    self.fits.append((recv.id, cls, name, node.lineno))
            elif isinstance(recv, ast.Call):
                # StandardScaler().fit_transform(X) — 변수에 담지 않고 바로 쓴 경우
                cls = _called_name(recv)
                if cls in SCALERS | SELECTORS:
                    self.fits.append(("", cls, name, node.lineno))
        self.generic_visit(node)

    def _mark_pipeline(self, node: ast.Call) -> None:
        """Pipeline 에 들어간 것은 fold 안에서 fit 된다 — 이름이든 인라인 생성이든."""
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                self.in_pipeline.add(sub.id)
            elif isinstance(sub, ast.Call):
                cls = _called_name(sub)
                if cls in SCALERS | SELECTORS:
                    self.in_pipeline.add(cls)


def _finding(check_id: str, hits: list, note_lines: list) -> LeakFinding:
    grade = grade_of(check_id)
    if not hits:
        return LeakFinding(id=check_id, grade=grade, verdict="pass",
                           summary=msg(f"mb_{check_id[3:].lower()}_pass"),
                           detail=note_lines)
    detail = [msg("mb_code_hit", line=ln, cls=cls, method=method)
              for _, cls, method, ln in hits] + note_lines
    return LeakFinding(id=check_id, grade=grade, verdict="fail",
                       summary=msg(f"mb_{check_id[3:].lower()}_fail", n=len(hits)),
                       detail=detail, numbers={"n": len(hits)},
                       action=msg(f"mb_{check_id[3:].lower()}_action"))


def audit_code(path: str) -> list[LeakFinding]:
    """학습 코드 한 파일을 읽어 split 이전 fit 을 찾는다 (MB-C04, MB-C09)."""
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        why = msg("mb_code_missing", path=path)
        return [skip("MB-C04", why), skip("MB-C09", why)]
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except SyntaxError as e:
        why = msg("mb_code_unparsable", detail=f"{e.msg} (line {e.lineno})")
        return [skip("MB-C04", why), skip("MB-C09", why)]

    scan = _Scan()
    scan.visit(tree)

    if not scan.split_lines:
        why = msg("mb_code_no_split")
        return [skip("MB-C04", why), skip("MB-C09", why)]

    split_name, split_line = min(scan.split_lines, key=lambda x: x[1])
    note = [msg("mb_code_split_at", line=split_line, name=split_name),
            msg("mb_code_limit")]
    if scan.in_pipeline:
        note.append(msg("mb_code_pipeline", n=len(scan.in_pipeline & (
            set(scan.made) | SCALERS | SELECTORS))))

    early = [h for h in scan.fits
             if h[3] < split_line and h[0] not in scan.in_pipeline
             and h[1] not in scan.in_pipeline]
    return [_finding("MB-C04", [h for h in early if h[1] in SELECTORS], note),
            _finding("MB-C09", [h for h in early if h[1] in SCALERS], note)]
