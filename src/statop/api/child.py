"""[웹에서 보기] 가 띄우는 서버 — **부모(터미널 화면)가 끝나면 같이 끝난다.**

웹은 보기 수단이다. 창을 닫았는데 서버만 남으면 포트를 물고 쌓인다 — 실측으로 4일간
5개가 쌓여 8000~8004 를 전부 막았고, 그 뒤로는 웹을 아예 못 띄웠다.

종료 훅만으로는 못 막는다: 터미널을 강제로 닫거나 SSH 가 끊기면 훅이 아예 안 돈다.
그래서 커널에 "부모가 죽으면 나도 죽여라"를 걸어 둔다.

`statop serve` 로 **사용자가 직접 띄운 서버는 여기를 쓰지 않는다** — 그건 일부러 띄운
것이라 띄운 사람이 끄는 것이 맞다.
"""

import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()

    from statop.api.workers import die_with_parent

    die_with_parent()

    import uvicorn

    uvicorn.run("statop.api.app:app", host=args.host, port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
