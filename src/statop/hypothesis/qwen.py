"""Qwen 플러그 (~) — 원할 때만 버튼으로 부르는 단발 질의.

대화가 아니다. 템플릿은 여기 고정돼 있고, 세션 기록(타입·문제·검정 결과·기계 가설)을
채워 한 번 던지고 1안/2안을 받아온다. 사용 모델은 Qwen3 중형 instruct(8B~14B,
Apache 2.0) 하나뿐이다.

무겁지 않게: 이 프로세스는 모델을 로드하지 않는다. GPU 노드에 떠 있는
OpenAI 호환 서버(vLLM `vllm serve Qwen/Qwen3-8B` / llama.cpp server / ollama)를
호출만 한다 — 로딩 비용은 서버가 한 번 치르고, CLI는 몇 초짜리 HTTP 요청이다.

외부 유출 금지: 기본은 localhost/사설망 주소만 허용한다. 전송한 내용은
세션 옆에 로그로 남는다 ( — 무엇이 나갔는지 항상 확인 가능).
"""

import ipaddress
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from statop.messages import msg

DEFAULT_MODEL = "Qwen/Qwen3-8B"       # 8B~14B급 instruct — STATOP_QWEN_MODEL 로 교체
ENV_URL = "STATOP_QWEN_URL"             # 예: http://gpu-node:8001/v1
ENV_MODEL = "STATOP_QWEN_MODEL"
ENV_ALLOW_REMOTE = "STATOP_QWEN_ALLOW_REMOTE"   # "1" 이면 사설망 밖도 허용 (기본 거부)

TIMEOUT_S = 120
MAX_TOKENS = 900


class QwenError(RuntimeError):
    pass


@dataclass
class QwenAnswer:
    proposals: list[dict] = field(default_factory=list)   # [{title, statement, rationale}]
    raw: str = ""
    model: str = ""
    sent_log: str = ""                # 무엇을 보냈는지 기록된 파일


def endpoint() -> str | None:
    return os.environ.get(ENV_URL) or None


def _host_is_private(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        # 호스트명 — 사내 DNS 인지 알 수 없다. 명시 허용 없이는 거부한다
        return False


def check_ready() -> tuple[bool, str]:
    """부를 수 있는 상태인지 — 안 되면 **무엇을 하면 되는지**를 돌려준다."""
    url = endpoint()
    if not url:
        return False, msg("qwen_no_endpoint", env=ENV_URL)
    if not _host_is_private(url) and os.environ.get(ENV_ALLOW_REMOTE) != "1":
        return False, msg("qwen_remote_refused", url=url, env=ENV_ALLOW_REMOTE)
    return True, url


# ── 고정 템플릿 — LLM 과 '소통'하지 않는다. 이 틀만 채워 던진다 ─
def build_prompt(session_file: str, opinion: str = "") -> tuple[str, dict]:
    """무엇이 나가는지 미리 보여 주기 위한 앞면 — 실제 조립은 `inputs.build` 이 한다.

    프롬프트 문구는 `내부 규칙 명세` 가 갖는다 (, ).
    """
    from statop.hypothesis import inputs

    family, user = inputs.build(session_file, opinion)
    return user, {"family": family}


def _log_sent(session_file: str, payload: dict) -> str:
    """무엇이 나갔는지 파일로 — 외부 유출이 없다는 걸 사후에도 확인할 수 있게."""
    p = Path(session_file).with_suffix(".qwen_sent.jsonl")
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return str(p)


def ask(session_file: str, opinion: str = "",
        timeout: int = TIMEOUT_S) -> QwenAnswer:
    """단발 질의 — 서버가 없으면 즉시 실패하고 이유를 말한다 (조용히 기다리지 않는다)."""
    ok, info = check_ready()
    if not ok:
        raise QwenError(info)
    url = info.rstrip("/")
    model = os.environ.get(ENV_MODEL, DEFAULT_MODEL)
    from statop.hypothesis import inputs, prompts

    family, user = inputs.build(session_file, opinion)

    body = {
        "model": model,
        "messages": [{"role": "system", "content": prompts.system()},
                     {"role": "user", "content": user}],
        "temperature": 0.3,
        "max_tokens": MAX_TOKENS,
        # Qwen3 의 사고 모드는 끈다 — 단발 질의에 로딩·토큰만 늘린다
        "chat_template_kwargs": {"enable_thinking": False},
    }
    sent_log = _log_sent(session_file, {"url": url, "model": model,
                                        "family": family, "user": user})

    import time

    started = time.perf_counter()
    req = urllib.request.Request(
        url + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001 — 네트워크·서버 오류는 그대로 보여준다
        raise QwenError(msg("qwen_call_failed", url=url, err=f"{type(e).__name__}: {e}"))

    took_ms = int((time.perf_counter() - started) * 1000)
    # 걸린 시간을 남긴다 — 다음 번에 "얼마나 기다려야 하는지"를 지어내지 않고 말하려면 필요하다
    from statop.session.core import append_op, load_session, save_session

    try:
        doc = load_session(session_file)
        append_op(doc, "qwen_ask", model=model, took_ms=took_ms, sent_log=sent_log)
        save_session(doc)
    except (ValueError, OSError, KeyError):
        pass          # 기록 실패가 답변을 막을 이유는 없다

    raw = data["choices"][0]["message"]["content"]
    return QwenAnswer(proposals=_parse(raw), raw=raw, model=model, sent_log=sent_log)


def _parse(raw: str) -> list[dict]:
    """모델 출력에서 JSON 을 꺼낸다 — 형식이 깨지면 원문을 그대로 보여준다 (지어내지 않는다)."""
    text = raw.strip()
    if "```" in text:
        parts = [p for p in text.split("```") if "{" in p]
        if parts:
            text = parts[0].removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    # 세 입장이 **각각 세 줄**로 온다 (registry-prompts 2·3절). 하나라도 빠지면
    # 그 자리를 지어내지 않고 그대로 비운다 — 화면이 원문을 함께 띄운다
    from statop.hypothesis.prompts import STANCES

    by = {}
    for p in obj.get("proposals", []):
        if isinstance(p, dict) and p.get("hypothesis"):
            st = str(p.get("stance", "")).strip().lower()
            if st in STANCES and st not in by:
                by[st] = {"stance": st, "hypothesis": str(p["hypothesis"]),
                          "test": str(p.get("test", "")),
                          "limit": str(p.get("limit", ""))}
    return [by[s] for s in STANCES if s in by]


# ── 준비 상태 확인 (버튼이 무엇을 기다리는지 보여주기 위한 것) ─
def probe(timeout: float = 3.0) -> dict:
    """서버가 떠 있는지·모델이 올라왔는지 한 번에 본다.

    Qwen 은 상주하지 않고 필요할 때만 부른다. 첫 호출은 모델을 올리느라 오래 걸릴 수
    있으므로, 버튼을 누르기 전에 **지금 어느 단계인지**를 보여줄 수 있어야 한다.
    """
    import time

    ok, info = check_ready()
    out = {"stage": "no_endpoint", "detail": info, "url": endpoint(),
           "model": os.environ.get(ENV_MODEL, DEFAULT_MODEL),
           "loaded": False, "latency_ms": None}
    if not ok:
        return out

    import httpx

    started = time.perf_counter()
    try:
        r = httpx.get(f"{info.rstrip('/')}/models", timeout=timeout)
    except httpx.HTTPError as e:
        out["stage"] = "unreachable"
        out["detail"] = msg("qwen_unreachable", url=info, err=type(e).__name__)
        return out
    out["latency_ms"] = int((time.perf_counter() - started) * 1000)
    if r.status_code != 200:
        out["stage"] = "unreachable"
        out["detail"] = msg("qwen_bad_status", code=r.status_code)
        return out

    names = [m.get("id", "") for m in (r.json().get("data") or [])]
    out["served"] = names
    want = out["model"].split("/")[-1].casefold()
    out["loaded"] = any(want in n.casefold() for n in names)
    out["stage"] = "ready" if out["loaded"] else "model_missing"
    out["detail"] = (msg("qwen_ready", model=out["model"], ms=out["latency_ms"])
                     if out["loaded"]
                     else msg("qwen_model_missing", model=out["model"],
                              served=", ".join(names) or "-"))
    return out


def load(timeout: int = 180) -> dict:
    """모델을 **올려 둔다** — 상주시키지 않고 필요할 때만 부르기 때문에 필요한 단계다.

    OpenAI 호환 서버는 첫 요청에서 모델을 올린다. 그래서 아주 짧은 요청을 한 번 보내
    올라올 때까지 기다리고, **얼마나 걸렸는지**를 돌려준다 — 그래야 다음 번 대기를
    지어내지 않고 말할 수 있다.
    """
    import time

    before = probe(timeout=5.0)
    if before["stage"] == "no_endpoint":
        return {**before, "warmed": False}
    if before["stage"] == "ready":
        return {**before, "warmed": True, "took_ms": 0,
                "detail": msg("qwen_already_loaded", model=before["model"])}

    url = (endpoint() or "").rstrip("/")
    model = os.environ.get(ENV_MODEL, DEFAULT_MODEL)
    body = {"model": model, "messages": [{"role": "user", "content": "ok"}],
            "max_tokens": 1, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False}}
    started = time.perf_counter()
    req = urllib.request.Request(
        url + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            pass
    except Exception as e:  # noqa: BLE001 — 실패 이유를 그대로 보여준다
        return {**before, "warmed": False,
                "detail": msg("qwen_load_failed", url=url,
                              err=f"{type(e).__name__}: {e}")}
    took = int((time.perf_counter() - started) * 1000)
    after = probe(timeout=5.0)
    return {**after, "warmed": after["stage"] == "ready", "took_ms": took,
            "detail": msg("qwen_loaded", model=model, s=took / 1000)
            if after["stage"] == "ready" else after["detail"]}


def estimate_wait(session_file: str) -> dict:
    """응답까지 얼마나 걸릴지 — 같은 세션에서 이전에 걸린 시간을 근거로 한다.

    기록이 없으면 추정하지 않는다. 지어낸 숫자를 보여주면 그 숫자를 믿는다.
    """
    from statop.session.core import load_session

    try:
        doc = load_session(session_file)
    except (ValueError, OSError, KeyError):
        return {"samples": 0, "seconds": None}
    took = [o["took_ms"] for o in doc.get("ops", [])
            if o["op"] == "qwen_ask" and o.get("took_ms")]
    if not took:
        return {"samples": 0, "seconds": None}
    return {"samples": len(took), "seconds": round(sum(took) / len(took) / 1000, 1),
            "last_seconds": round(took[-1] / 1000, 1)}
