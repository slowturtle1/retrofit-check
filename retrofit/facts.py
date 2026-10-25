"""Gather the facts about one house and cache them in the retrofit database.

Each step reports to the trace: what it asked, where, how long it took, what came back.
The agent reads everything back through Zetaris, never straight from this cache.
"""

from __future__ import annotations

import json
import time
from typing import Callable

import psycopg

from .config import db_dsn
from .sources import lidar, osm, planning, pvgis
from .zetaris import Zetaris

Step = Callable[[dict], None]
NOISE_LIMIT = 25  # percent of roof cells steeper than 65 degrees


def _timed(step: Step, name: str, source: str, fn, *args):
    started = time.time()
    step({"type": "tool_start", "tool": name, "source": source})
    try:
        out = fn(*args)
    except Exception as e:  # reported, then re-raised for the agent to handle
        step({"type": "tool_end", "tool": name, "ok": False, "seconds": round(time.time() - started, 1), "error": str(e)[:300]})
        raise
    step({"type": "tool_end", "tool": name, "ok": True, "seconds": round(time.time() - started, 1)})
    return out


def cached(house_id: str, z: Zetaris) -> bool:
    hid = house_id.replace("'", "")
    return bool(z.run(f"SELECT h.house_id FROM retrofit_pg.house h JOIN retrofit_pg.roof_survey r ON h.house_id = r.house_id WHERE h.house_id = '{hid}'",
                      purpose="Is this house already in the cache?").rows)


def gather(house: dict, z: Zetaris, step: Step, refresh: bool = False) -> dict:
    """house comes from osm.house_from_way or osm.building_at."""
    hid = house["house_id"]
    if cached(hid, z) and not refresh:
        step({"type": "note", "text": f"{hid} is already in the cache; reading it through Zetaris"})
        return {"house_id": hid, "cached": True}
    if getattr(z, "offline", False):
        raise LookupError(f"{hid} is not in the sample snapshot. Sample mode has data for the example houses only; run the live stack for any other house.")

    # Planning first: it decides how much else is worth measuring.
    pd = _timed(step, "planning_data", "planning.data.gov.uk via Zetaris REST table", planning.read, z, house)
    if pd["via"] == "direct":
        step({"type": "note", "text": "Zetaris could not reach planning.data in time; the same request went direct and is cached for Zetaris to read", "why": pd.get("why")})
    listed = [e for e in pd["entities"] if e["dataset"] in ("listed-building", "listed-building-outline")]
    walls = _timed(step, "osm_walls", "OpenStreetMap API", osm.walls, house)
    roof, pv = None, None
    if listed:
        step({"type": "decision", "text": "The building is listed, so panels need listed building consent whatever the roof is like. Skipping the LIDAR roof survey and PVGIS.", "branch": "listed_stop"})
    else:
        roof = _timed(step, "lidar_roof", "Environment Agency LIDAR DSM 1 m", lidar.measure, house["coords"])
        if roof["noise_pct"] > NOISE_LIMIT:
            step({"type": "challenge", "by": "evaluator", "about": "roof", "text": f"{roof['noise_pct']}% of the roof reading is trees, chimneys or dormers, above the {NOISE_LIMIT}% limit. Measure again with a wider 1.5 m margin inside the walls."})
            second = _timed(step, "lidar_roof", "Environment Agency LIDAR DSM 1 m, 1.5 m margin", lidar.measure, house["coords"], 1.5)
            better = second["noise_pct"] < roof["noise_pct"] and second["planes"]
            fixed = bool(better) and second["noise_pct"] <= NOISE_LIMIT
            step({"type": "requery", "by": "analyst", "about": "roof", "ok": fixed,
                  "text": f"Measured again: {second['noise_pct']}% noise. " + ("Accepted." if fixed else "Still above the limit: the roof numbers are marked as rough.")})
            if better:
                roof = second
        best = lidar.best_solar_plane(roof["planes"])
        pv = _timed(step, "pvgis", "PVGIS 5.2 via Zetaris REST table", pvgis.read, z, house, best) if best else None

    with psycopg.connect(db_dsn()) as c:
        c.execute("DELETE FROM house WHERE house_id = %s", (hid,))
        c.execute("INSERT INTO house (house_id, label, lat, lon, building, footprint_m2, footprint, source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                  (hid, house.get("label") or house.get("street") or "House", house["lat"], house["lon"], house.get("building"),
                   house["footprint_m2"], json.dumps({"type": "Polygon", "coordinates": [house["coords"]]}), house["source"]))
        for w in walls:
            c.execute("INSERT INTO house_wall VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                      (hid, w["wall_no"], w["facing_deg"], w["length_m"], w["fronts_highway"], w["highway_name"], w["distance_m"], w["adjoins"]))
        if roof:
            for p in roof["planes"]:
                c.execute("INSERT INTO roof_plane VALUES (%s,%s,%s,%s,%s)", (hid, p["facing"], p["azimuth_deg"], p["pitch_deg"], p["area_m2"]))
            c.execute("INSERT INTO roof_survey (house_id, noise_pct, flat_pct, eaves_m, ridge_m, method) VALUES (%s,%s,%s,%s,%s,%s)",
                      (hid, roof["noise_pct"], roof["flat_pct"], roof["eaves_m"], roof["ridge_m"], roof["method"]))
        else:
            c.execute("INSERT INTO roof_survey (house_id, noise_pct, flat_pct, method) VALUES (%s,0,0,%s)", (hid, "not measured: listed building"))
        if pv:
            c.execute("INSERT INTO pv_estimate (house_id, facing, kwp, kwh_year, params, source) VALUES (%s,%s,%s,%s,%s,%s)",
                      (hid, pv["facing"], pv["kwp"], pv["kwh_year"], pv["params"], pv["source"]))
        orgs = {}
        for e in pd["entities"]:
            c.execute("INSERT INTO designation VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                      (hid, e["dataset"], e["reference"], e["name"], e.get("listed-building-grade"), e.get("start-date") or None,
                       e.get("end-date") or None, e.get("entity"), str(e.get("organisation-entity") or "")))
            orgs[e["dataset"]] = orgs.get(e["dataset"], 0) + 1
    step({"type": "note", "text": f"Cached {hid}: {len(walls)} walls, {len(roof['planes']) if roof else 0} roof planes, {sum(orgs.values())} planning entries"})
    return {"house_id": hid, "cached": False, "planning_via": pd["via"]}
