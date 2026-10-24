"""Sample mode data layer: the same SQL the agent sends to Zetaris, answered from a local snapshot.

samples/cache.sqlite holds a copy of the retrofit_pg tables for the sample houses, plus the planning.data
lists the evaluator asks Zetaris for (each council's Article 4 areas, listed outlines). The agent code does
not change: OfflineZetaris has Zetaris's interface, rewrites the Lightning SQL to plain SQLite and returns
every value as text, as Zetaris does. Built by scripts/make_cache.py from a live run.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import ROOT
from .zetaris import Result, ZetarisError

CACHE = ROOT / "samples" / "cache.sqlite"

REWRITES = [
    (re.compile(r"FROM planning_data\.a4_council_(\w+) LATERAL VIEW explode\(entities\) AS e", re.I), r"FROM council_a4 AS e WHERE e.org = '\1'"),
    (re.compile(r"FROM planning_data\.lbo_(\w+) LATERAL VIEW explode\(entities\) AS e", re.I), r"FROM listed_outline AS e WHERE e.house_key = '\1'"),
    (re.compile(r"\bretrofit_pg\."), ""),
]


def _text(v: Any) -> Any:
    return None if v is None else str(v)


@dataclass
class OfflineZetaris:
    on_query: Callable[[dict], None] | None = None
    log: list[dict] = field(default_factory=list)
    offline: bool = True

    def run(self, sql: str, limit: int = 500, purpose: str = "") -> Result:
        started = time.time()
        if re.match(r"\s*CREATE LIGHTNING", sql, re.I):
            return self._done(sql, purpose, started, Result([], [], 0.0), note="registration skipped: answered from the local snapshot")
        if not CACHE.exists():
            raise ZetarisError("samples/cache.sqlite is missing; run scripts/make_cache.py")
        q = sql
        for pat, rep in REWRITES:
            q = pat.sub(rep, q)
        if re.search(r"\b(planning_data|pvgis)\.", q, re.I):
            self._done(sql, purpose, started, None, error="not in the sample snapshot")
            raise ZetarisError("this request is not in the sample snapshot")
        con = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
        try:
            cur = con.execute(q)
            headers = [d[0] for d in cur.description or []]
            rows = [[_text(v) for v in r] for r in cur.fetchmany(limit)]
        except sqlite3.Error as e:
            self._done(sql, purpose, started, None, error=str(e))
            raise ZetarisError(f"snapshot query failed: {e}") from e
        finally:
            con.close()
        return self._done(sql, purpose, started, Result(headers, rows, round(time.time() - started, 3)))

    def _done(self, sql, purpose, started, res, error=None, note=None):
        entry = {"sql": sql.strip(), "purpose": purpose, "seconds": round(time.time() - started, 3),
                 "rows": len(res.rows) if res else None, "error": error, "source": "local snapshot (sample mode)"}
        if note:
            entry["note"] = note
        self.log.append(entry)
        if self.on_query:
            self.on_query(entry)
        return res


def houses() -> list[dict]:
    """Cached houses with their footprints, for finding a house by way id or by a tap on the map."""
    import json
    if not CACHE.exists():
        return []
    con = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT house_id, label, lat, lon, building, footprint_m2, footprint, source FROM house").fetchall()
    finally:
        con.close()
    return [{"house_id": r[0], "label": r[1], "lat": r[2], "lon": r[3], "building": r[4], "footprint_m2": r[5],
             "coords": json.loads(r[6])["coordinates"][0], "source": r[7]} for r in rows]
