"""Zetaris over its REST API. Every statement the agent runs goes through here and is logged to the trace."""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from .config import env

SECRET = re.compile(r'(password\s+)"[^"]*"', re.I)


class ZetarisError(RuntimeError):
    def __init__(self, msg: str, unreachable: bool = False):
        super().__init__(msg)
        self.unreachable = unreachable   # Zetaris itself did not answer (down, not configured), not a bad query


@dataclass
class Result:
    headers: list[str]
    rows: list[list[Any]]
    seconds: float

    def dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.headers, r)) for r in self.rows]


@dataclass
class Zetaris:
    on_query: Callable[[dict], None] | None = None
    log: list[dict] = field(default_factory=list)

    def run(self, sql: str, limit: int = 500, purpose: str = "") -> Result:
        started = time.time()
        try:
            url, headers = env("ZETARIS_REST_URL").rstrip("/") + "/sql-editor/sqls/run", {
                "Authorization": "Bearer " + env("ZETARIS_API_KEY"), "X-Org-ID": env("ZETARIS_ORG_ID"), "X-Request-ID": str(uuid.uuid4())}
        except RuntimeError as e:   # no .env: a fresh clone
            self._record(sql, purpose, started, error=str(e))
            raise ZetarisError(f"Zetaris is not configured: {e}", unreachable=True) from e
        try:
            r = requests.post(
                url,
                headers=headers,
                json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit},
                timeout=float(env("ZETARIS_TIMEOUT", "90")),
            )
        except requests.RequestException as e:
            self._record(sql, purpose, started, error=str(e))
            raise ZetarisError(f"Zetaris unreachable: {e}", unreachable=True) from e
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or "headers" not in body:
            msg = body.get("message") or body.get("error") or r.text[:300]
            self._record(sql, purpose, started, error=msg)
            raise ZetarisError(f"Zetaris {r.status_code}: {msg}", unreachable=r.status_code >= 500 or not body)
        res = Result(body.get("headers", []), body.get("data", []), round(time.time() - started, 2))
        self._record(sql, purpose, started, rows=len(res.rows))
        return res

    def _record(self, sql: str, purpose: str, started: float, rows: int | None = None, error: str | None = None) -> None:
        entry = {"sql": SECRET.sub(r'\1"***"', sql.strip()), "purpose": purpose, "seconds": round(time.time() - started, 2), "rows": rows, "error": error}
        self.log.append(entry)
        if self.on_query:
            self.on_query(entry)


class FallbackZetaris:
    """Live Zetaris first. If Zetaris itself does not answer, the rest of the run reads the same tables from the
    local snapshot (samples/cache.sqlite), says so once in the trace, and the answer is marked as a fallback."""

    def __init__(self, on_query: Callable[[dict], None] | None = None, on_fallback: Callable[[str], None] | None = None):
        self.live = Zetaris(on_query=on_query)
        self.on_query, self.on_fallback = on_query, on_fallback
        self.snapshot = None
        self._lock = threading.Lock()   # rules.load reads in parallel: switch once, report once

    @property
    def offline(self) -> bool:
        return self.snapshot is not None

    def run(self, sql: str, limit: int = 500, purpose: str = "") -> Result:
        if self.snapshot is None:
            try:
                return self.live.run(sql, limit, purpose)
            except ZetarisError as e:
                if not e.unreachable:
                    raise
                from .offline import OfflineZetaris
                with self._lock:
                    first = self.snapshot is None
                    if first:
                        self.snapshot = OfflineZetaris(on_query=self.on_query)
                if first and self.on_fallback:
                    self.on_fallback(str(e)[:200])
        return self.snapshot.run(sql, limit, purpose)
