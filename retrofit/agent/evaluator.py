"""The evaluator attacks the evidence behind a first answer; the analyst goes back to Zetaris to settle each challenge.

A challenge is resolved when a new query backs the finding. If it does not, the finding stays but is
marked uncertain and the homeowner is told to ask the council. Every challenge and re-query is in the trace.
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable
from urllib.parse import urlencode

from ..config import USER_AGENT
from ..sources.planning import BASE
from ..zetaris import Zetaris, ZetarisError

Emit = Callable[[dict], None]
# Historic England's own listed building outlines (NHLE). planning.data holds most listings as points only, so a
# terrace listed as one entry can be missed on the house's own footprint.
HE_LISTED = ("https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/"
             "National_Heritage_List_for_England_NHLE_v02_VIEW/FeatureServer/3/query")
# planning.data organisation entities for the London councils we have looked at; others show as "council <id>"
COUNCILS = {"90": "Camden", "387": "Westminster", "175": "Haringey", "366": "Waltham Forest", "329": "Southwark", "192": "Lambeth",
            "163": "Hackney", "42": "Brent", "198": "Lewisham", "182": "Kensington and Chelsea", "350": "Tower Hamlets", "48": "Barnet",
            "126": "Enfield", "167": "Hillingdon", "188": "Kingston upon Thames", "170": "Hounslow", "41": "Barking and Dagenham"}


_NAMES: dict[str, str] = {}


def council(org: str) -> str:
    """Short council name; outside the list, planning.data's own name for the organisation entity, else "the council"."""
    if org in COUNCILS:
        return COUNCILS[org]
    if org not in _NAMES:
        import re

        import requests
        try:
            r = requests.get(f"https://www.planning.data.gov.uk/entity/{int(org)}.json", headers={"User-Agent": USER_AGENT}, timeout=10)
            name = r.json().get("name") if r.ok else None
        except (requests.RequestException, ValueError):
            name = None
        _NAMES[org] = re.sub(r"^(London Borough of|Royal Borough of|City of) | (City|Borough|District|County|Metropolitan Borough|Metropolitan District) Council$| Council$", "",
                             name).strip() if name else "the council"
    return _NAMES[org]


def _rest(z: Zetaris, table: str, db: str, url: str, purpose: str) -> None:
    try:
        z.run(f'''CREATE LIGHTNING REST TABLE {table} FROM {db} REQUEST(
    endpoint "{url}",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
    user-agent "{USER_AGENT}"
) BODY ()''', purpose=purpose)
    except ZetarisError as e:
        if "exist" not in str(e).lower():
            raise


def council_publishes_ca_article4(z: Zetaris, org: str) -> tuple[int, int]:
    """How many Article 4 areas this council has on planning.data, and how many are about conservation areas."""
    url = BASE + "?" + urlencode([("dataset", "article-4-direction-area"), ("organisation_entity", org), ("exclude_field", "geometry"), ("limit", "500")])
    table = f"a4_council_{org}"
    _rest(z, table, "PLANNING_DATA", url, f"Register every Article 4 area {council(org)} has published")
    rows = z.run(f"""SELECT count(e.reference) AS n,
       sum(CASE WHEN lower(e.name) LIKE '%conservation area%' OR lower(e.name) LIKE '%various properties%' THEN 1 ELSE 0 END) AS ca
FROM planning_data.{table} LATERAL VIEW explode(entities) AS e""", purpose=f"Does {council(org)} publish conservation area Article 4s at all?").rows
    return int(rows[0][0] or 0), int(rows[0][1] or 0)


def inner_ring(coords: list) -> list:
    """The footprint about 1 m inward, so an outline that only touches a party wall (the neighbour's listing) does not count.
    Sharp corners and at most about 40 points: rounded corners added up to 16 points each, and Historic England answers
    404 to a query URL past about 2,000 characters (Hampstead's 19 point house became 109 points, 3,829 characters).
    Simplifying by less than the 1 m keeps the ring inside the house."""
    from shapely.geometry import Polygon
    inner = Polygon(coords).buffer(-0.00001, join_style="mitre")
    if inner.geom_type != "Polygon" or inner.is_empty:
        return coords
    for tol in (0.000003, 0.000006, 0.000009):   # about 0.3, 0.6 and 0.9 m
        if len(inner.exterior.coords) <= 40:
            break
        inner = inner.simplify(tol, preserve_topology=True)
    return [list(p) for p in inner.exterior.coords]


def he_listed(z: Zetaris, house_id: str, coords: list) -> list[dict]:
    """Historic England listed building outlines inside the footprint, read through Zetaris as a REST table."""
    geom = {"rings": [[[round(x, 7), round(y, 7)] for x, y in inner_ring(coords)]], "spatialReference": {"wkid": 4326}}
    url = HE_LISTED + "?" + urlencode({"geometry": json.dumps(geom, separators=(",", ":")), "geometryType": "esriGeometryPolygon", "inSR": 4326,
                                       "spatialRel": "esriSpatialRelIntersects", "outFields": "ListEntry,Name,Grade", "returnGeometry": "false", "f": "json"})
    # The query's own hash in the name: a table registered with an older query (a longer ring that Historic England
    # refused) is never reused for a new one. Sample mode reads the house key without it (offline.REWRITES).
    table = "he_" + house_id.replace("-", "_") + "_v" + hashlib.sha1(url.encode()).hexdigest()[:6]
    _rest(z, table, "PLANNING_DATA", url, "Register Historic England's listed building outlines for this footprint")
    try:
        return z.run(f"SELECT f.attributes.ListEntry AS entry, f.attributes.Name AS name, f.attributes.Grade AS grade FROM planning_data.{table} LATERAL VIEW explode(features) AS f",
                     purpose="Cross check the listing against Historic England's own outlines").dicts()
    except ZetarisError as e:
        # No outline here: Historic England answers "features": [], and Zetaris types an empty list as array<string>,
        # so the attributes cannot be read. Count the outlines instead; none means checked, nothing on this footprint.
        if "INVALID_EXTRACT_BASE_FIELD_TYPE" not in str(e):
            raise
        rows = z.run(f"SELECT size(features) AS n FROM planning_data.{table}", purpose="Count Historic England's outlines on this footprint").rows
        if rows and int(rows[0][0] or 0) == 0:
            return []
        raise


def listed_outline(z: Zetaris, house_id: str, coords: list) -> int:
    from shapely.geometry import Polygon
    url = BASE + "?" + urlencode([("geometry", Polygon(coords).wkt), ("geometry_relation", "intersects"), ("dataset", "listed-building-outline"),
                                  ("exclude_field", "geometry"), ("limit", "20")])
    table = "lbo_" + house_id.replace("-", "_")
    _rest(z, table, "PLANNING_DATA", url, "Register listed building outlines that touch the footprint")
    return len(z.run(f"SELECT e.reference FROM planning_data.{table} LATERAL VIEW explode(entities) AS e", purpose="Check the listing again against the building outline").rows)


def challenge(z: Zetaris, f: dict, result: dict, coords: list, emit: Emit) -> list[str]:
    """Returns uncertainty flags to add to every verdict."""
    flags: list[str] = []
    des = f["designations"]
    in_ca = [d for d in des if d["dataset"] == "conservation-area"]
    a4 = [d for d in des if d["dataset"] == "article-4-direction-area"]
    energy_a4 = [d for d in a4 if d.get("removes_solar") in (True, "true") or d.get("removes_ashp") in (True, "true")]

    listed = [d for d in des if d["dataset"] in ("listed-building", "listed-building-outline")]

    # 1. No Article 4 on record is not proof that none exists. (Skipped for a listed building: consent is needed anyway.)
    if in_ca and not energy_a4 and not listed:
        org = str(in_ca[0].get("organisation") or "")
        emit({"type": "challenge", "by": "evaluator", "about": "article-4",
              "text": f"No Article 4 that touches energy upgrades is on record for this house. Councils publish unevenly, so that alone is not proof. Does {council(org)} publish conservation area Article 4s at all?"})
        if not org:
            emit({"type": "requery", "by": "analyst", "about": "article-4", "ok": False,
                  "text": "planning.data names no council for this conservation area, so its Article 4 record could not be checked: marked uncertain."})
            return flags + ["article4_coverage_unknown"] + _listed_flags(z, f, des, coords, emit)
        try:
            n, ca = council_publishes_ca_article4(z, org)
            ok = ca > 0
            emit({"type": "requery", "by": "analyst", "about": "article-4", "ok": ok,
                  "text": f"{council(org)} has {n} Article 4 areas on planning.data, {ca} of them for conservation areas or named properties. " +
                          ("It does publish them, and none covers this house for energy upgrades: the finding stands." if ok else
                           "It publishes none for conservation areas, so a missing record proves nothing: marked uncertain.")})
            if not ok:
                flags.append("article4_coverage_unknown")
        except ZetarisError as e:
            emit({"type": "requery", "by": "analyst", "about": "article-4", "ok": False, "text": f"Could not ask Zetaris again ({str(e)[:80]}): marked uncertain."})
            flags.append("article4_coverage_unknown")

    return flags + _listed_flags(z, f, des, coords, emit) + _he_flags(z, f, des, coords, emit)


def _he_flags(z: Zetaris, f: dict, des: list, coords: list, emit: Emit) -> list[str]:
    """3. No listing on planning.data is not proof: ask Historic England's own outlines."""
    if any(d["dataset"] in ("listed-building", "listed-building-outline") for d in des):
        return []
    emit({"type": "challenge", "by": "evaluator", "about": "listed",
          "text": "planning.data shows no listing on this footprint, but it holds most listings as points, so a terrace listed as one entry can be missed. Check Historic England's own outlines."})
    try:
        rows = [r for r in he_listed(z, f["house"]["house_id"], coords) if r.get("entry")]
    except ZetarisError as e:
        emit({"type": "requery", "by": "analyst", "about": "listed", "ok": False,
              "text": f"Could not ask Historic England ({str(e)[:80]}): planning.data's answer stands, unchecked."})
        return []
    if not rows:
        emit({"type": "requery", "by": "analyst", "about": "listed", "ok": True,
              "text": "No Historic England listed outline lies on this footprint either. Its outlines are not complete, so this lowers the doubt "
                      "but does not prove the house is unlisted; the answer says to check the listing before applying."})
        return []
    r = rows[0]
    emit({"type": "requery", "by": "analyst", "about": "listed", "ok": False,
          "text": f"Historic England's outline for list entry {r['entry']} ({r.get('name')}, Grade {r.get('grade')}) covers this footprint, "
                  "though planning.data shows no listing here: marked uncertain."})
    return ["listed_he_only"]


def _listed_flags(z: Zetaris, f: dict, des: list, coords: list, emit: Emit) -> list[str]:
    flags: list[str] = []
    # 2. A listing point without an outline may belong to the building next door.
    points = [d for d in des if d["dataset"] == "listed-building" and d.get("organisation") != "historic-england"]
    outlines = [d for d in des if d["dataset"] == "listed-building-outline"]
    if points and not outlines:
        emit({"type": "challenge", "by": "evaluator", "about": "listed",
              "text": f"The listing ({points[0]['reference']}) was found as a point only. A point can sit on the neighbour's side of a party wall. Check against the building outline."})
        try:
            n = listed_outline(z, f["house"]["house_id"], coords)
            emit({"type": "requery", "by": "analyst", "about": "listed", "ok": n > 0,
                  "text": "A listed outline covers this footprint: the listing stands." if n else "No listed outline touches this footprint: treated as listed to be safe, marked uncertain."})
            if not n:
                flags.append("listed_point_only")
        except ZetarisError as e:
            emit({"type": "requery", "by": "analyst", "about": "listed", "ok": False, "text": f"Could not ask again ({str(e)[:80]}): marked uncertain."})
            flags.append("listed_point_only")
    return flags


def cost_sources(z: Zetaris, kwp: float, emit: Emit) -> None:
    """Two official cost series disagree for solar; ask Zetaris for both and keep the range."""
    emit({"type": "challenge", "by": "evaluator", "about": "solar cost",
          "text": "One cost figure would hide how much prices vary. Check the national median against the London average before quoting a cost."})
    rows = z.run("SELECT fact_id, value, plain, valid_from, valid_to FROM retrofit_pg.price_fact WHERE fact_id IN ('solar_cost_gb_median', 'solar_cost_london_mean')",
                 purpose="Compare the two official solar cost series").dicts()
    v = {r["fact_id"]: float(r["value"]) for r in rows}
    lo, hi = v.get("solar_cost_gb_median"), v.get("solar_cost_london_mean")
    if lo and hi:
        emit({"type": "requery", "by": "analyst", "about": "solar cost", "ok": True,
              "text": f"National median £{lo:,.0f} per kW, London average £{hi:,.0f} per kW ({(hi / lo - 1) * 100:.0f}% apart). Showing £{round(kwp * lo, -2):,.0f} to £{round(kwp * hi, -2):,.0f} with both sources."})


def self_use(z: Zetaris, gen_kwh: float, use_kwh: float, said_by_owner: bool, emit: Emit) -> dict | None:
    """How much of the roof's output the home uses itself depends on who is home in the day: ask MCS for all three types."""
    who = "the owner's" if said_by_owner else "a typical"
    asked_use, asked_gen = use_kwh, gen_kwh
    use_kwh, gen_kwh = min(max(use_kwh, 1500), 5999), min(max(gen_kwh, 0), 5999)   # the MCS tables' range: use the nearest band
    emit({"type": "challenge", "by": "evaluator", "about": "self use",
          "text": f"One share of solar power used at home would hide that it depends on who is home in the day. Ask the MCS tables for all three occupancy types, for this roof and {who} yearly use."})
    try:
        rows = z.run(f"""SELECT archetype, share FROM retrofit_pg.self_use_share
WHERE use_from <= {int(use_kwh)} AND use_to >= {int(use_kwh)} AND gen_from <= {int(gen_kwh)} AND gen_to >= {int(gen_kwh)}""",
                     purpose="MCS share of solar power used at home, for this roof and this household").dicts()
    except ZetarisError as e:
        emit({"type": "requery", "by": "analyst", "about": "self use", "ok": False, "text": f"Could not ask Zetaris ({str(e)[:80]}): the share stays an estimate."})
        return None
    if not rows:
        emit({"type": "requery", "by": "analyst", "about": "self use", "ok": False,
              "text": f"The MCS tables cover 1,500 to 5,999 kWh used and up to 5,999 kWh made; {int(use_kwh):,} kWh used and {int(gen_kwh):,} kWh made is outside them, so the share stays an estimate."})
        return None
    s = {r["archetype"]: float(r["share"]) for r in rows}
    lo, hi = min(s.values()), max(s.values())
    clamped = (use_kwh, gen_kwh) != (asked_use, asked_gen)
    emit({"type": "requery", "by": "analyst", "about": "self use", "ok": True,
          "text": "MCS MGD 003 for " + f"{int(gen_kwh):,} kWh made and {int(use_kwh):,} kWh used: " +
                  ", ".join(f"{k.lower()} {round(v * 100)}%" for k, v in sorted(s.items(), key=lambda kv: kv[1])) + f". Using {round(lo * 100)}% to {round(hi * 100)}%." +
                  (f" ({int(asked_use):,} kWh used and {int(asked_gen):,} kWh made is outside the tables, so the nearest band is used.)" if clamped else "")})
    return {"low": lo, "high": hi, "use_kwh": int(asked_use), "by_owner": said_by_owner, "source": "MCS MGD 003 look up tables", "nearest_band": clamped}
