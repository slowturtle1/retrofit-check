"""OpenStreetMap: the house footprint and which of its walls face a road.

Uses the main OSM API (Overpass mirrors time out too often for a live demo).
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import requests
from shapely.geometry import LineString, Point, Polygon

from ..config import USER_AGENT

API = "https://api.openstreetmap.org/api/0.6"
R = 6378137.0
# Legally a footpath is a highway too; private driveways are not.
ROAD = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street",
        "service", "pedestrian", "footway", "path", "cycleway", "steps"}


def _get(path: str, **params) -> requests.Response:
    r = requests.get(f"{API}/{path}", params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    return r


def _area(lat: float, lon: float, half_m: float) -> tuple[dict, dict]:
    """Nodes and ways in a small box around a point."""
    dlat = half_m / R * 180 / math.pi
    dlon = dlat / math.cos(math.radians(lat))
    root = ET.fromstring(_get("map", bbox=f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}").content)
    nodes = {n.get("id"): (float(n.get("lon")), float(n.get("lat"))) for n in root.iter("node")}
    ways = {}
    for w in root.iter("way"):
        refs = [nd.get("ref") for nd in w.iter("nd")]
        if all(r in nodes for r in refs):
            ways[w.get("id")] = {"coords": [nodes[r] for r in refs], "tags": {t.get("k"): t.get("v") for t in w.iter("tag")}}
    return nodes, ways


def _local(origin: tuple[float, float]):
    k = math.cos(math.radians(origin[1]))
    to = lambda p: ((p[0] - origin[0]) * math.pi / 180 * R * k, (p[1] - origin[1]) * math.pi / 180 * R)  # noqa: E731
    return to


def building_at(lat: float, lon: float) -> dict | None:
    """The OSM building that contains a point (a tap on the 3D map)."""
    nodes, ways = _area(lat, lon, 40)
    pt = Point(lon, lat)
    rel = _relation_at(lat, lon, pt)
    if rel:
        return house_from_relation(rel)
    hits = [(wid, w) for wid, w in ways.items() if "building" in w["tags"] and len(w["coords"]) >= 4 and Polygon(w["coords"]).contains(pt)]
    if not hits:
        return None
    wid, w = min(hits, key=lambda h: Polygon(h[1]["coords"]).area)
    return house_from_way(int(wid))


def _relation_at(lat: float, lon: float, pt: Point) -> int | None:
    dlat = 40 / R * 180 / math.pi
    dlon = dlat / math.cos(math.radians(lat))
    root = ET.fromstring(_get("map", bbox=f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}").content)
    nodes = {n.get("id"): (float(n.get("lon")), float(n.get("lat"))) for n in root.iter("node")}
    ways = {w.get("id"): [nodes.get(nd.get("ref")) for nd in w.iter("nd")] for w in root.iter("way")}
    for r in root.iter("relation"):
        tags = {t.get("k"): t.get("v") for t in r.iter("tag")}
        if tags.get("type") != "multipolygon" or "building" not in tags:
            continue
        for m in r.iter("member"):
            ring = ways.get(m.get("ref"))
            if m.get("role") == "outer" and ring and None not in ring and len(ring) >= 4 and Polygon(ring).contains(pt):
                return int(r.get("id"))
    return None


def house_from_relation(rel_id: int) -> dict:
    """A building mapped as a multipolygon (e.g. with a courtyard): the outer ring is the footprint."""
    root = ET.fromstring(_get(f"relation/{rel_id}/full").content)
    nodes = {n.get("id"): (float(n.get("lon")), float(n.get("lat"))) for n in root.iter("node")}
    ways = {w.get("id"): [nodes[nd.get("ref")] for nd in w.iter("nd")] for w in root.iter("way")}
    rel = next(root.iter("relation"))
    outer = [m.get("ref") for m in rel.iter("member") if m.get("type") == "way" and m.get("role") == "outer"]
    if len(outer) != 1:
        raise ValueError(f"relation {rel_id} has {len(outer)} outer ways; only one is supported")
    tags = {t.get("k"): t.get("v") for t in rel.iter("tag")}
    return _house(f"osm-relation-{rel_id}", ways[outer[0]], tags, f"OpenStreetMap relation {rel_id}", way_id=int(outer[0]))


def house_from_way(way_id: int) -> dict:
    root = ET.fromstring(_get(f"way/{way_id}/full").content)
    nodes = {n.get("id"): (float(n.get("lon")), float(n.get("lat"))) for n in root.iter("node")}
    way = next(root.iter("way"))
    coords = [nodes[nd.get("ref")] for nd in way.iter("nd")]
    tags = {t.get("k"): t.get("v") for t in way.iter("tag")}
    return _house(f"osm-way-{way_id}", coords, tags, f"OpenStreetMap way {way_id}", way_id=way_id)


def _house(house_id: str, coords: list, tags: dict, source: str, way_id: int) -> dict:
    poly = Polygon(coords)
    c = poly.centroid
    to = _local((c.x, c.y))
    area_m2 = Polygon([to(p) for p in coords]).area
    return {
        "house_id": house_id,
        "osm_way": way_id,
        "lat": c.y,
        "lon": c.x,
        "building": tags.get("building"),
        "street": tags.get("addr:street"),
        "footprint_m2": round(area_m2),
        "coords": coords,
        "source": source,
        "name": tags.get("name"),
    }


def walls(house: dict, reach_m: float = 30.0) -> list[dict]:
    """Each footprint edge, its outward direction, and whether a road lies in front of it.

    A ray from the middle of the wall goes outward; the wall fronts a highway if the ray
    reaches a road before it reaches another building.
    """
    _, ways = _area(house["lat"], house["lon"], 80)
    to = _local((house["lon"], house["lat"]))
    pts = [to(p) for p in house["coords"]]
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    poly = Polygon(pts)
    ccw = poly.exterior.is_ccw
    roads, others = [], []
    for wid, w in ways.items():
        line = [to(p) for p in w["coords"]]
        if len(line) < 2:
            continue
        hw = w["tags"].get("highway")
        if hw in ROAD and w["tags"].get("service") != "driveway" and w["tags"].get("access") != "private":
            roads.append((LineString(line), w["tags"].get("name") or hw))
        elif "building" in w["tags"] and wid != str(house.get("osm_way")) and len(line) >= 4:
            others.append(Polygon(line))
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1.0:
            continue
        nx, ny = (dy / length, -dx / length) if ccw else (-dy / length, dx / length)  # outward normal
        mid = ((a[0] + b[0]) / 2 + nx * 0.3, (a[1] + b[1]) / 2 + ny * 0.3)
        ray = LineString([mid, (mid[0] + nx * reach_m, mid[1] + ny * reach_m)])
        block = min((Point(mid).distance(o) for o in others if ray.intersects(o)), default=None)
        hit = min(((Point(mid).distance(ray.intersection(r)), name) for r, name in roads if ray.intersects(r)), default=None)
        fronts = hit is not None and (block is None or hit[0] < block)
        out.append({
            "wall_no": i,
            "facing_deg": round((math.degrees(math.atan2(nx, ny)) + 360) % 360),
            "length_m": round(length, 1),
            "fronts_highway": fronts,
            "highway_name": hit[1] if fronts else None,
            "distance_m": round(hit[0], 1) if fronts else None,
            "adjoins": block is not None and block < 1.0,  # a party wall with the house next door
        })
    return out
