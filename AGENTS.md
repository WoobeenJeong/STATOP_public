# STATOP — 에이전트 안내

전체 설명은 README.md 를 보십시오.

## 4. 에이전트(Claude·ChatGPT)와 같이 쓰기

STATOP 은 **에이전트가 읽기 좋게** 만들어져 있습니다. 작업 폴더에서 에이전트에게
이렇게 알려 주면 바로 붙습니다.

```
이 저장소는 STATOP 이다. 통계 검증 도구이고 로컬에서 돈다.
- 설치: conda activate statop
- 규칙표: rules/*.yaml 이 무엇을 쓸 수 있고 왜 안 되는지를 정한다 (손으로 고치지 말 것,
  schema/registry-*.md 가 원본이고 python -m statop.rules.build 가 생성한다)
- 명령: statop --help 로 전체 목록. 흐름은 session new → select → types --confirm
  → analyze plan --apply → analyze run 순서다
- 원칙: 자료 칸은 저장하지 않는다. 세션에는 조작 기록만 남는다
```

**에이전트에게 맡기기 좋은 일**

| 하고 싶은 것 | 시키는 말 |
|---|---|
| 내 자료 훑어보기 | "`statop columns 내파일.csv` 돌리고 의미 타입이 이상한 컬럼만 짚어 줘" |
| 검정 고르기 | "`statop analyze plan --question Q-01 --y y --group g` 돌리고 ✅ 만 추려 줘" |
| 왜 안 되는지 | "빨강으로 나온 이유를 `rules/tests.yaml` 에서 찾아 근거째로 보여 줘" |
| 재현 가능하게 | "`statop report` 로 보고서 내고, 세션 json 의 조작 기록으로 재현 스크립트 만들어 줘" |

에이전트가 **자료를 직접 해석하게 두지 마세요.** STATOP 의 판정을 읽게 하고,
에이전트는 그 판정을 설명·정리하는 데 쓰는 쪽이 안전합니다. 판정의 근거는 전부
`rules/` 에 글로 적혀 있어서, 에이전트가 지어내지 않고 인용할 수 있습니다.

---

