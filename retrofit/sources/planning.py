"""planning.data.gov.uk read through Zetaris.

For each house the agent registers a Zetaris REST table whose endpoint asks planning.data
for every protected area, listed building and Article 4 direction that touches the
footprint, then reads it with Lightning SQL. If Zetaris cannot reach the endpoint the
same request goes direct, and the trace says so.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import requests
from shapely.geometry import Polygon

from ..config import USER_AGENT
from ..zetaris import Zetaris, ZetarisError

BASE = "https://www.planning.data.gov.uk/entity.json"
DATASETS = ["listed-building", "listed-building-outline", "conservation-area", "article-4-direction-area",
            "area-of-outstanding-natural-beauty", "national-park", "world-heritage-site", "scheduled-monument"]
KEEP = ("dataset", "name", "reference", "start-date", "end-date", "entity", "organisation-entity", "listed-building-grade")


def endpoint(coords: list[tuple[float, float]]) -> str:
    wkt = Polygon(coords).wkt
    q = [("geometry", wkt), ("geometry_relation", "intersects"), ("exclude_field", "geometry"), ("limit", "100")]
    q += [("dataset", d) for d in DATASETS]
    return BASE + "?" + urlencode(q)


def _clean(e: dict) -> dict:
    return {k: e.get(k) for k in KEEP}


def read(z: Zetaris, house: dict) -> dict:
    table = "pd_" + house["house_id"].replace("-", "_")
    url = endpoint(house["coords"])
    try:
        try:
            z.run(f'''CREATE LIGHTNING REST TABLE {table} FROM PLANNING_DATA REQUEST(
    endpoint "{url}",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
    user-agent "{USER_AGENT}"
) BODY ()''', purpose="Register planning.data for this footprint as a Zetaris REST table")
        except ZetarisError as e:
            if "exist" not in str(e).lower():
                raise
        res = z.run(f"SELECT to_json(e) AS entity FROM planning_data.{table} LATERAL VIEW explode(entities) AS e",
                    purpose="Read listed status, conservation area and Article 4 that touch the footprint")
        rows = [_clean(json.loads(r[0])) for r in res.rows]
        return {"via": "zetaris", "table": f"planning_data.{table}", "endpoint": url, "entities": rows}
    except ZetarisError as e:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=180)
        r.raise_for_status()
        rows = [_clean(x) for x in r.json().get("entities", [])]
        return {"via": "direct", "why": str(e)[:200], "endpoint": url, "entities": rows}
