"""Sample mode data layer: the same SQL the agent sends to Zetaris, answered from a local snapshot.

samples/cache.sqlite holds a copy of the retrofit_pg tables for the sample houses, plus the planning.data
lists the evaluator asks Zetaris for (each council's Article 4 areas, listed outlines). The agent code does
not change: OfflineZetaris has Zetaris's interface, rewrites the Lightning SQL to plain SQLite and returns
every value as text, as Zetaris does. Built by scripts/make_cache.py from a live run.

Any other house: with DIRECT_SOURCES on (the default), the agent fetches it from the same public sources
(OpenStreetMap, planning.data, EA LIDAR, PVGIS, no keys) and stores it in runs/live-cache.sqlite, a copy of the
snapshot that grows; every later read for that house is the same SQL. The trace says Zetaris was not used.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import ROOT
from .zetaris import Result, ZetarisError

CACHE = ROOT / "samples" / "cache.sqlite"
LIVE = ROOT / "runs" / "live-cache.sqlite"
_WRITE = threading.Lock()


def direct_allowed() -> bool:
    return os.environ.get("DIRECT_SOURCES", "true").lower() in ("1", "true", "yes")


def db_path():
    """The growing copy once a new house was fetched, else the shipped snapshot. A broken copy is dropped."""
    if LIVE.exists() and CACHE.exists() and LIVE.stat().st_mtime < CACHE.stat().st_mtime:
        LIVE.unlink(missing_ok=True)   # a newer snapshot came with the repo: start the copy again
    if LIVE.exists():
        try:
            con = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True)
            try:
                con.execute("SELECT count(*) FROM house").fetchone()
            finally:
                con.close()
        except sqlite3.DatabaseError:
            LIVE.unlink(missing_ok=True)
    return LIVE if LIVE.exists() else CACHE


def _live() -> sqlite3.Connection:
    if not LIVE.exists():
        LIVE.parent.mkdir(exist_ok=True)
        tmp = LIVE.with_suffix(f".tmp{os.getpid()}")
        shutil.copy(CACHE, tmp)
        os.replace(tmp, LIVE)   # readers see the old file or the whole copy, never half of it
    return sqlite3.connect(LIVE)

REWRITES = [
    (re.compile(r"FROM planning_data\.a4_council_(\w+) LATERAL VIEW explode\(entities\) AS e", re.I), r"FROM council_a4 AS e WHERE e.org = '\1'"),
    (re.compile(r"FROM planning_data\.lbo_(\w+) LATERAL VIEW explode\(entities\) AS e", re.I), r"FROM listed_outline AS e WHERE e.house_key = '\1'"),
    (re.compile(r"FROM planning_data\.he_(\w+) LATERAL VIEW explode\(features\) AS f", re.I), r"FROM he_listed AS f WHERE f.house_key = '\1' AND f.ListEntry IS NOT NULL"),
    (re.compile(r"\bf\.attributes\.(\w+)"), r"f.\1"),
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
        if direct_allowed():
            if m := re.search(r"FROM council_a4 AS e WHERE e.org = '(\w+)'", q):
                _ensure_council(m.group(1))
            if m := re.search(r"FROM listed_outline AS e WHERE e.house_key = '(\w+)'", q):
                _ensure_outline(m.group(1))
        if m := re.search(r"FROM he_listed AS f WHERE f.house_key = '(\w+)'", q):
            if direct_allowed():
                _ensure_he(m.group(1))
            if not _has("he_listed", "house_key", m.group(1)):   # never checked is not the same as checked, none
                self._done(sql, purpose, started, None, error="Historic England was not asked for this house")
                raise ZetarisError("Historic England was not asked for this house")
        if re.search(r"\b(planning_data|pvgis)\.", q, re.I):
            self._done(sql, purpose, started, None, error="not in the sample snapshot")
            raise ZetarisError("this request is not in the sample snapshot")
        con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
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
    con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT house_id, label, lat, lon, building, footprint_m2, footprint, source FROM house").fetchall()
    finally:
        con.close()
    return [{"house_id": r[0], "label": r[1], "lat": r[2], "lon": r[3], "building": r[4], "footprint_m2": r[5],
             "coords": json.loads(r[6])["coordinates"][0], "source": r[7]} for r in rows]


# ---- direct from the public sources, for houses the snapshot does not hold

def _get(params: dict) -> list[dict]:
    import requests

    from .config import USER_AGENT
    from .sources.planning import BASE
    r = requests.get(BASE, params=params, headers={"User-Agent": USER_AGENT}, timeout=float(os.environ.get("PLANNING_TIMEOUT", "60")))
    r.raise_for_status()
    return r.json().get("entities", [])


def _has(table: str, col: str, key: str) -> bool:
    con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    try:
        return bool(con.execute(f"SELECT 1 FROM {table} WHERE {col} = ? LIMIT 1", (key,)).fetchone())
    finally:
        con.close()


def _ensure_council(org: str) -> None:
    """The Article 4 areas a council has published, as the evaluator asks Zetaris for them."""
    if _has("council_a4", "org", org):
        return
    try:
        ents = _get({"dataset": "article-4-direction-area", "organisation_entity": org, "exclude_field": "geometry", "limit": 500})
    except Exception as e:  # noqa: BLE001  the evaluator then marks the answer uncertain
        raise ZetarisError(f"planning.data did not answer: {e}") from e
    with _WRITE, _live() as con:
        con.executemany("INSERT INTO council_a4 VALUES (?, ?, ?)", [(org, e.get("name"), e.get("reference")) for e in ents] or [(org, None, None)])


def _ensure_outline(house_key: str) -> None:
    """Listed outlines that touch a fetched house's footprint (the snapshot already holds its own houses' answers)."""
    from shapely.geometry import Polygon
    hid = re.sub(r"^osm_(way|relation)_", r"osm-\1-", house_key)
    if _has("listed_outline", "house_key", house_key):
        return
    snap = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
    try:
        if snap.execute("SELECT 1 FROM house WHERE house_id = ?", (hid,)).fetchone():
            return   # the shipped snapshot already holds what planning.data said for its own houses
    finally:
        snap.close()
    con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT footprint FROM house WHERE house_id = ?", (hid,)).fetchone()
    finally:
        con.close()
    if not row:
        return
    try:
        ents = _get({"geometry": Polygon(json.loads(row[0])["coordinates"][0]).wkt, "geometry_relation": "intersects",
                     "dataset": "listed-building-outline", "exclude_field": "geometry", "limit": 20})
    except Exception as e:  # noqa: BLE001
        raise ZetarisError(f"planning.data did not answer: {e}") from e
    with _WRITE, _live() as con:
        con.executemany("INSERT INTO listed_outline VALUES (?, ?)", [(house_key, e.get("reference")) for e in ents])


def he_rows(coords: list) -> list[tuple]:
    """Historic England listed outlines touching a footprint, straight from its ArcGIS service."""
    import requests

    from .agent.evaluator import HE_LISTED, inner_ring
    from .config import USER_AGENT
    geom = {"rings": [[[round(x, 7), round(y, 7)] for x, y in inner_ring(coords)]], "spatialReference": {"wkid": 4326}}
    r = requests.post(HE_LISTED, data={"geometry": json.dumps(geom), "geometryType": "esriGeometryPolygon", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                                       "outFields": "ListEntry,Name,Grade", "returnGeometry": "false", "f": "json"},
                      headers={"User-Agent": USER_AGENT}, timeout=float(os.environ.get("PLANNING_TIMEOUT", "60")))
    r.raise_for_status()
    return [(f["attributes"].get("ListEntry"), f["attributes"].get("Name"), f["attributes"].get("Grade")) for f in r.json().get("features", [])]


def _ensure_he(house_key: str) -> None:
    """One row per outline, or one empty row meaning "checked, none", for a house fetched on this machine."""
    con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    try:
        if con.execute("SELECT 1 FROM he_listed WHERE house_key = ? LIMIT 1", (house_key,)).fetchone():
            return
        hid = re.sub(r"^osm_(way|relation)_", r"osm-\1-", house_key)
        row = con.execute("SELECT footprint FROM house WHERE house_id = ?", (hid,)).fetchone()
    finally:
        con.close()
    if not row:
        raise ZetarisError("Historic England was not asked: this house is not stored on this machine")
    try:
        found = he_rows(json.loads(row[0])["coordinates"][0])
    except Exception as e:  # noqa: BLE001  the evaluator says the check could not run
        raise ZetarisError(f"Historic England did not answer: {e}") from e
    with _WRITE, _live() as c:
        c.executemany("INSERT INTO he_listed VALUES (?, ?, ?, ?)", [(house_key, *x) for x in found] or [(house_key, None, None, None)])


def store_house(house: dict, walls: list, roof: dict | None, pv: dict | None, entities: list) -> None:
    """The rows facts.gather writes to retrofit_pg, written to the local copy instead (same tables, same columns)."""
    from datetime import date
    hid, today = house["house_id"], date.today().isoformat()
    with _WRITE, _live() as c:
        for t in ("house", "house_wall", "roof_plane", "roof_survey", "pv_estimate", "designation"):
            c.execute(f"DELETE FROM {t} WHERE house_id = ?", (hid,))
        c.execute("INSERT INTO house (house_id, label, lat, lon, building, footprint_m2, footprint, source, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (hid, house.get("label") or house.get("street") or "House", house["lat"], house["lon"], house.get("building"), house["footprint_m2"],
                   json.dumps({"type": "Polygon", "coordinates": [house["coords"]]}), house["source"], today))
        for w in walls:
            c.execute("INSERT INTO house_wall VALUES (?,?,?,?,?,?,?,?)", (hid, w["wall_no"], w["facing_deg"], w["length_m"],
                      "true" if w["fronts_highway"] else "false", w["highway_name"], w["distance_m"], "true" if w["adjoins"] else "false"))
        if roof:
            for p in roof["planes"]:
                c.execute("INSERT INTO roof_plane VALUES (?,?,?,?,?)", (hid, p["facing"], p["azimuth_deg"], p["pitch_deg"], p["area_m2"]))
            c.execute("INSERT INTO roof_survey VALUES (?,?,?,?,?,?,?)", (hid, roof["noise_pct"], roof["flat_pct"], roof["eaves_m"], roof["ridge_m"], roof["method"], today))
        else:
            c.execute("INSERT INTO roof_survey VALUES (?,?,?,?,?,?,?)", (hid, 0, 0, None, None, "not measured: listed building", today))
        if pv:
            c.execute("INSERT INTO pv_estimate VALUES (?,?,?,?,?,?,?)", (hid, pv["facing"], pv["kwp"], pv["kwh_year"], pv["params"], pv["source"], today))
        for e in entities:
            c.execute("INSERT INTO designation VALUES (?,?,?,?,?,?,?,?,?)", (hid, e["dataset"], e["reference"], e["name"], e.get("listed-building-grade"),
                      e.get("start-date") or None, e.get("end-date") or None, e.get("entity"), str(e.get("organisation-entity") or "")))
