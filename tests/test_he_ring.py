"""The footprint sent to Historic England: about 1 m inside the house, and short enough for a GET URL.
Historic England answers 404 past about 2,000 characters; Zetaris reads it as a REST table, so the query is a GET.
"""

import json
from urllib.parse import urlencode

from shapely.geometry import Polygon

from retrofit import offline
from retrofit.agent.evaluator import HE_LISTED, inner_ring


def _url(ring: list) -> str:
    geom = {"rings": [[[round(x, 7), round(y, 7)] for x, y in ring]], "spatialReference": {"wkid": 4326}}
    return HE_LISTED + "?" + urlencode({"geometry": json.dumps(geom, separators=(",", ":")), "geometryType": "esriGeometryPolygon", "inSR": 4326,
                                        "spatialRel": "esriSpatialRelIntersects", "outFields": "ListEntry,Name,Grade", "returnGeometry": "false", "f": "json"})


def test_every_snapshot_footprint_fits_a_get_url_and_stays_inside_the_house():
    houses = offline.houses()
    assert len(houses) >= 15
    for h in houses:
        ring = inner_ring(h["coords"])
        assert len(_url(ring)) < 2000, (h["house_id"], len(ring))
        house, inner = Polygon(h["coords"]), Polygon(ring)
        assert house.contains(inner), h["house_id"]
        assert inner.area > 0.5 * house.area, h["house_id"]


def test_hampstead_keeps_its_corners_without_extra_points():
    h = next(x for x in offline.houses() if x["house_id"] == "osm-way-110514126")
    assert len(inner_ring(h["coords"])) <= len(h["coords"]) + 1
