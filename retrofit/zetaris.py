"""Zetaris over its REST API. Every statement the agent runs goes through here and is logged to the trace."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from .config import env

SECRET = re.compile(r'(password\s+)"[^"]*"', re.I)


class ZetarisError(RuntimeError):
    pass


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
            r = requests.post(
                env("ZETARIS_REST_URL").rstrip("/") + "/sql-editor/sqls/run",
                headers={
                    "Authorization": "Bearer " + env("ZETARIS_API_KEY"),
                    "X-Org-ID": env("ZETARIS_ORG_ID"),
                    "X-Request-ID": str(uuid.uuid4()),
                },
                json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit},
                timeout=float(env("ZETARIS_TIMEOUT", "90")),
            )
        except requests.RequestException as e:
            self._record(sql, purpose, started, error=str(e))
            raise ZetarisError(f"Zetaris unreachable: {e}") from e
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or "headers" not in body:
            msg = body.get("message") or body.get("error") or r.text[:300]
            self._record(sql, purpose, started, error=msg)
            raise ZetarisError(f"Zetaris {r.status_code}: {msg}")
        res = Result(body.get("headers", []), body.get("data", []), round(time.time() - started, 2))
        self._record(sql, purpose, started, rows=len(res.rows))
        return res

    def _record(self, sql: str, purpose: str, started: float, rows: int | None = None, error: str | None = None) -> None:
        entry = {"sql": SECRET.sub(r'\1"***"', sql.strip()), "purpose": purpose, "seconds": round(time.time() - started, 2), "rows": rows, "error": error}
        self.log.append(entry)
        if self.on_query:
            self.on_query(entry)
