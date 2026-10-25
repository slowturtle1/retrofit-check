"""Nemotron through Meterless Nightshift (OpenAI compatible). Every call keeps its compute receipt."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Callable

import requests

from ..config import env

APP = "retrofit-check"


def _base() -> str:
    base = env("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1").rstrip("/")
    for tail in ("/chat/completions", "/models", "/healthz"):
        if base.endswith(tail):
            base = base[: -len(tail)]
    return base if base.endswith("/v1") else base + "/v1"


class LLMError(RuntimeError):
    pass


# A hard wall clock limit per call: Nightshift can keep a request open long past the socket timeout
# (one call held 630 s with a 120 s read timeout). The run sets a deadline for all model work.
_POOL = ThreadPoolExecutor(4, thread_name_prefix="nightshift")
_local = threading.local()


def set_deadline(at: float | None) -> None:
    """Epoch seconds after which no model call starts or waits (Run.model_budget_s)."""
    _local.deadline = at


def _limit() -> float:
    limit = float(env("MODEL_TIMEOUT", "120"))
    at = getattr(_local, "deadline", None)
    if at is not None:
        limit = min(limit, at - time.time())
    if limit < 5:
        raise LLMError("out of time for the model")
    return limit


def chat(messages: list[dict], role: str, on_call: Callable[[dict], None] | None = None,
         model: str | None = None, max_tokens: int = 3000, temperature: float = 0.2, retries: int = 1) -> str:
    """One retry, then LLMError: the caller keeps the code's checked draft (a fallback, never a crash)."""
    for attempt in range(retries + 1):
        try:
            return _chat_once(messages, role if attempt == 0 else f"{role} (retry {attempt})", on_call, model, max_tokens, temperature,
                              "failed" if attempt == retries else "retrying")
        except LLMError as e:
            if attempt == retries or "out of time" in str(e):
                raise
            time.sleep(2 * (attempt + 1))
    raise LLMError("unreachable")


def _chat_once(messages, role, on_call, model, max_tokens, temperature, fail_status="failed") -> str:
    started = time.time()
    limit = _limit()
    try:
        if not env("METERLESS_RUNTIME_TOKEN", ""):
            raise requests.ConnectionError("Nightshift is not configured (no METERLESS_RUNTIME_TOKEN)")
        call = _POOL.submit(
            requests.post,
            _base() + "/chat/completions",
            headers={"Authorization": "Bearer " + env("METERLESS_RUNTIME_TOKEN"), "meterless-app": APP, "meterless-scope": "user"},
            json={"model": model or env("METERLESS_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b"), "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
            timeout=limit,
        )
        try:
            r = call.result(timeout=limit)
        except FutureTimeout:
            raise requests.Timeout(f"no reply within {limit:.0f} s") from None
        if r.status_code != 200:
            raise requests.HTTPError(f"{r.status_code}: {r.text[:200]}")
        body = r.json()
    except (requests.RequestException, ValueError) as e:
        if on_call:
            on_call({"role": role, "ok": False, "seconds": round(time.time() - started, 1), "error": str(e)[:200], "status": fail_status,
                     "model": model or env("METERLESS_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")})
        raise LLMError(str(e)) from e
    receipt = body.get("meterless") or {}
    text = (body["choices"][0]["message"].get("content") or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if on_call:
        on_call({"role": role, "ok": True, "seconds": round(time.time() - started, 1),
                 "model": body.get("model"), "routed_model": receipt.get("routed_model"),
                 "receipt_id": receipt.get("receipt_id"), "tokens": body.get("usage", {}).get("total_tokens")})
    return text


def chat_json(messages: list[dict], role: str, on_call=None, **kw) -> dict | list:
    """Ask for JSON; one repair attempt if the reply does not parse."""
    text = chat(messages, role, on_call, **kw)
    for attempt in range(2):
        m = re.search(r"\{.*\}|\[.*\]", text, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        if attempt == 0:
            text = chat(messages + [{"role": "assistant", "content": text},
                                    {"role": "user", "content": "That was not valid JSON. Reply with the JSON only."}], role + "_repair", on_call, **kw)
    raise LLMError(f"{role}: no valid JSON in reply")
