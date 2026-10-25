"""Step 1 of the evaluation: write the expected answers BEFORE running any system, and freeze them.

Ground truth comes from Historic England, not from planning.data (which the agent reads):
- listed: the National Heritage List for England (NHLE): a listed building polygon touching the footprint, or a listed
  building point within 10 m of it whose address is on the same street (NHLE points are approximate and often fall
  just outside the building outline; a point on another street belongs to a neighbour and is recorded, not counted)
- conservation area: Historic England's national conservation areas dataset
Article 4 facts come from the councils' own documents (Camden decision of 27 May 2025 for Hampstead).

Labelling procedure (the law as a homeowner meets it, GPDO 2015 Schedule 2):
- listed                         → solar consent, heat pump consent, walls consent
- conservation area, not listed  → solar allowed, heat pump allowed*, walls permission (Part 1 Class A, A.2(a))
- neither                        → solar allowed, heat pump allowed*, walls allowed (if the finish matches)
- a council that publishes no conservation area Article 4s → the answer should carry an "ask the council" flag
* heat pump siting rules depend on which walls face a road; the evaluation scores only the route
  (allowed / permission / consent) that the designations decide.

Run: .venv/bin/python eval/label.py   → eval/cases.json (with a hash; do not edit after running the systems)
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrofit.config import USER_AGENT  # noqa: E402
from retrofit.sources import osm  # noqa: E402

HE = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services"
OUT = Path(__file__).parent / "cases.json"

# Chosen to cover each situation; houses are referred to by OSM id and street only.
CASES = [
    # (osm way or None, lat, lon, group, note)
    (1106478076, None, None, "camden-ca", "Dartmouth Park CA, corner house"),
    (369932335, None, None, "camden-ca", "Dartmouth Park CA, end of terrace"),
    (460070558, None, None, "camden-ca", "Dartmouth Park CA, detached"),
    (849743972, None, None, "camden-ca", "Dartmouth Park CA, semi"),
    (1556408737, None, None, "no-ca", "Lady Somerset Road"),
    (1556408744, None, None, "no-ca", "Lady Somerset Road"),
    (1556408762, None, None, "no-ca", "Lady Somerset Road"),
    (1556408735, None, None, "no-ca", "Lady Somerset Road"),
    (110514126, None, None, "hampstead-a4-ended", "Hampstead CA, old Article 4 covered roof solar"),
    (110502216, None, None, "hampstead-a4-ended", "Hampstead CA, old Article 4 covered roof solar"),
    (1011719614, None, None, "listed", "Hampstead, listed house"),
    (65272940, None, None, "listed", "Keats House"),
    (103107384, None, None, "listed", "Freud Museum"),
    (None, 51.50348, -0.12770, "listed", "10 Downing Street"),
    (None, 51.5905, -0.1452, "haringey-ca", "Muswell Hill CA"),
    (None, 51.5905, -0.1448, "haringey-ca", "Muswell Hill CA"),
]


def he_query(layer_url: str, coords: list, within_m: float = 0) -> list[dict]:
    geom = {"rings": [[list(p) for p in coords]], "spatialReference": {"wkid": 4326}}
    extra = {"distance": within_m, "units": "esriSRUnit_Meter"} if within_m else {}
    r = requests.post(layer_url + "/query", data={"geometry": json.dumps(geom), "geometryType": "esriGeometryPolygon", "inSR": 4326,
                                                  "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "false", "f": "json", **extra},
                      headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    return [f["attributes"] for f in r.json().get("features", [])]


def expected(listed: bool, in_ca: bool, group: str) -> dict:
    if listed:
        return {"solar": "consent", "heat_pump": "consent", "wall_insulation": "consent", "flag_council": False}
    if in_ca:
        return {"solar": "allowed", "heat_pump": "allowed", "wall_insulation": "permission", "flag_council": group == "haringey-ca"}
    return {"solar": "allowed", "heat_pump": "allowed", "wall_insulation": "allowed", "flag_council": False}


def main() -> None:
    cases = []
    for way, lat, lon, group, note in CASES:
        h = osm.house_from_way(way) if way else osm.building_at(lat, lon)
        if not h:
            print("no building at", lat, lon, "- skipped")
            continue
        coords = h["coords"]
        lb_poly = he_query(f"{HE}/National_Heritage_List_for_England_NHLE_v02_VIEW/FeatureServer/3", coords)
        lb_pt = he_query(f"{HE}/National_Heritage_List_for_England_NHLE_v02_VIEW/FeatureServer/0", coords, within_m=10)  # NHLE points are approximate
        ca = he_query(f"{HE}/Conservation_Areas/FeatureServer/0", coords)
        street = (h.get("street") or "").upper()
        own_pt = [a for a in lb_pt if not street or street in str(a.get("Name", "")).upper()]
        other_pt = [a for a in lb_pt if a not in own_pt]
        listed = bool(lb_poly or own_pt)
        grades = sorted({str(a.get("Grade") or a.get("GRADE") or "") for a in lb_poly + own_pt} - {""})
        ca_names = sorted({str(a.get("NAME") or a.get("Name") or a.get("name") or "") for a in ca} - {""})
        cases.append({"id": h["house_id"], "way": way, "lat": round(h["lat"], 6), "lon": round(h["lon"], 6), "street": h.get("street"), "group": group, "note": note,
                      "truth": {"listed": listed, "grades": grades, "conservation_areas": ca_names, "source": "Historic England NHLE and Conservation Areas, queried " + time.strftime("%Y-%m-%d"),
                                "ignored_nearby_listings": [f"{a.get('Name')} ({a.get('ListEntry')})" for a in other_pt]},
                      "expected": expected(listed, bool(ca), group)})
        print(f"{h['house_id']:24} {group:20} listed={listed} {grades} CA={ca_names}")
        time.sleep(0.3)
    body = json.dumps(cases, indent=1, sort_keys=True)
    OUT.write_text(json.dumps({"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sha256": hashlib.sha256(body.encode()).hexdigest(), "cases": cases}, indent=1))
    print("frozen", OUT, len(cases), "cases")


if __name__ == "__main__":
    main()
