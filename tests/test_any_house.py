"""Judges type their own address: in sample mode a house the snapshot does not hold is fetched from the public
sources (OpenStreetMap, planning.data, EA LIDAR, PVGIS, Historic England), kept in the local copy of the snapshot,
and read back with the same SQL.

Every source is replaced with fixed data here, and conftest blocks the network, so nothing leaves this machine.
"""

import json
import os

import pytest
import requests

from retrofit import offline, schema
from retrofit.agent.run import Run, SourceUnavailable
from retrofit.sources import lidar, osm, planning, pvgis

os.environ["LOG_STDOUT"] = "false"
NEW = 990000001
HID = f"osm-way-{NEW}"
F = "osm-way-1106478076"
# A made up house next to house F (Dartmouth Park, Camden), so the council and its Article 4 list are known
COORDS = [(-0.14212, 51.56032), (-0.14196, 51.56032), (-0.14196, 51.56042), (-0.14212, 51.56042), (-0.14212, 51.56032)]
WALLS = [{"wall_no": 0, "facing_deg": 0, "length_m": 11.0, "fronts_highway": False, "highway_name": None, "distance_m": None, "adjoins": True},
         {"wall_no": 1, "facing_deg": 90, "length_m": 7.0, "fronts_highway": False, "highway_name": None, "distance_m": None, "adjoins": False},
         {"wall_no": 2, "facing_deg": 180, "length_m": 11.0, "fronts_highway": True, "highway_name": "Test Road", "distance_m": 6.0, "adjoins": False},
         {"wall_no": 3, "facing_deg": 270, "length_m": 7.0, "fronts_highway": False, "highway_name": None, "distance_m": None, "adjoins": True}]
ROOF = {"planes": [{"facing": "S", "azimuth_deg": 182, "pitch_deg": 30, "area_m2": 24}, {"facing": "N", "azimuth_deg": 2, "pitch_deg": 30, "area_m2": 24}],
        "noise_pct": 10, "flat_pct": 0, "eaves_m": 6.1, "ridge_m": 9.4, "method": "test roof", "margin_m": 0.75}
PLANNING = [{"dataset": "conservation-area", "name": "Dartmouth Park", "reference": "CA9", "start-date": "1992-06-01", "end-date": "",
             "entity": "44009622", "organisation-entity": "90", "listed-building-grade": ""}]


class _Resp:
    def __init__(self, body):
        self.body, self.ok, self.status_code = body, True, 200

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """Fixed answers from every public source, a fresh local copy of the snapshot, and a count of the calls."""
    calls = []
    monkeypatch.setattr(offline, "LIVE", tmp_path / "live-cache.sqlite")

    def house_from_way(way):
        calls.append("osm")
        return osm._house(f"osm-way-{way}", COORDS, {"building": "house", "addr:street": "Test Road"}, f"OpenStreetMap way {way}", way_id=way)

    def http_get(url, params=None, **k):
        calls.append("planning.data")
        if "geometry=" in url:                     # the footprint query planning.read sends direct
            return _Resp({"entities": PLANNING})
        return _Resp({"entities": []})             # listed outlines, council lists: none

    def walls(house):
        calls.append("osm walls")
        return [dict(w) for w in WALLS]

    def measure(coords, margin_m=0.75):
        calls.append("lidar")
        return json.loads(json.dumps(ROOF))

    def estimate(lat, lon, plane):
        calls.append("pvgis")
        kwp = round(plane["area_m2"] * pvgis.KWP_PER_M2, 1)
        return {"facing": plane["facing"], "kwp": kwp, "kwh_year": 3300, "params": "test", "source": "PVGIS 5.2, EU Joint Research Centre"}

    def he_rows(coords):
        calls.append("historic england")
        return []

    monkeypatch.setattr(osm, "house_from_way", house_from_way)
    monkeypatch.setattr(osm, "walls", walls)
    monkeypatch.setattr(planning.requests, "get", http_get)
    monkeypatch.setattr(lidar, "measure", measure)
    monkeypatch.setattr(pvgis, "estimate", estimate)
    monkeypatch.setattr(offline, "he_rows", he_rows)
    return calls


def test_a_new_house_is_fetched_from_the_public_sources(sources):
    run = Run(offline=True)
    rec = run.check(way=NEW)
    a = rec["answer"]
    assert schema.check_answer(a) == []
    assert a["house"]["house_id"] == HID and a["mode"] == "sample"
    fb = [e for e in run.events if e["type"] == "fallback" and e.get("about") == "direct sources"]
    assert len(fb) == 1 and fb[0]["status"] == "fallback" and fb[0]["agent_name"] == "analyst"
    assert "direct_sources" in a["trace"]["fallbacks"]
    assert {"osm", "planning.data", "osm walls", "lidar", "pvgis"} <= set(sources)
    s = a["solar"]
    assert s["status"] == "allowed" and s["numbers"]["kwh_year"] == 3300 and "Dartmouth Park" in s["lines"]["why"]
    assert offline.LIVE.exists() and HID in {h["house_id"] for h in offline.houses()}


def test_a_second_check_reads_the_stored_house_with_no_source_calls(sources):
    first = Run(offline=True).check(way=NEW)["answer"]["solar"]
    sources.clear()
    run = Run(offline=True)
    second = run.check(way=NEW)["answer"]["solar"]
    assert sources == []
    assert not any(e["type"] == "fallback" and e.get("about") == "direct sources" for e in run.events)
    assert (second["status"], second["recommendation"], second["numbers"]) == (first["status"], first["recommendation"], first["numbers"])


def test_the_shipped_snapshot_is_not_changed(sources):
    before = offline.CACHE.read_bytes()
    Run(offline=True).check(way=NEW)
    assert offline.CACHE.read_bytes() == before


def test_openstreetmap_down_for_a_new_house_gives_503(sources, monkeypatch):
    from retrofit import server

    def down(*a, **k):
        raise requests.ConnectionError("OpenStreetMap API unreachable")
    monkeypatch.setattr(osm, "house_from_way", down)
    with pytest.raises(SourceUnavailable, match="OpenStreetMap"):
        Run(offline=True).check(way=NEW)
    monkeypatch.setattr(server, "SAMPLE", True)
    resp = server.check_sync(server.CheckSyncIn(way=NEW))
    body = json.loads(resp.body)
    assert resp.status_code == 503 and body["error"]["code"] == "source_unavailable" and body["error"]["trace_id"]


def test_direct_sources_off_keeps_the_snapshot_only_answer(sources, monkeypatch):
    monkeypatch.setenv("DIRECT_SOURCES", "false")
    with pytest.raises(LookupError, match="example houses only"):
        Run(offline=True).check(way=NEW)
    assert sources == [] and not offline.LIVE.exists()


def test_historic_england_listing_on_a_new_house_says_check_with_the_council(sources, monkeypatch):
    monkeypatch.setattr(offline, "he_rows", lambda coords: [("1999998", "Test House", "II")])
    run = Run(offline=True)
    s = run.check(way=NEW)["answer"]["solar"]
    assert any(e["type"] == "challenge" and e.get("about") == "listed" for e in run.events)
    assert "listed_he_only" in s["uncertain"] and s["status"] == "check_with_council" and s["confidence"]["level"] == "low"


def test_an_address_on_the_street_takes_the_nearest_building(monkeypatch):
    """A search lands on the road in front of the house; the nearest building within 20 m is the answer."""
    ways = {"111": {"coords": COORDS, "tags": {"building": "house"}},
            "222": {"coords": [(x + 0.0012, y) for x, y in COORDS], "tags": {"building": "house"}}}
    monkeypatch.setattr(osm, "_area", lambda lat, lon, half: ({}, ways))
    monkeypatch.setattr(osm, "_relation_at", lambda lat, lon, pt: None)
    monkeypatch.setattr(osm, "house_from_way", lambda wid: {"house_id": f"osm-way-{wid}"})
    assert osm.building_at(51.56028, -0.14204)["house_id"] == "osm-way-111"      # about 5 m south of the footprint
    assert osm.building_at(51.56070, -0.14204) is None                          # about 30 m clear of every building


def test_a_terrace_listed_as_one_entry_is_found_through_its_list_entry_tag(sources, monkeypatch):
    """1 Royal Crescent, Bath: planning.data keeps Nos. 1-30 as one point that misses this house; OpenStreetMap tags it with the entry."""
    tags = {"building": "yes", "addr:street": "Test Road", "ref:GB:nhle": "1999997"}
    monkeypatch.setattr(osm, "house_from_way", lambda way: osm._house(f"osm-way-{way}", COORDS, tags, f"OpenStreetMap way {way}", way_id=way))
    asked = []
    monkeypatch.setattr(offline, "he_entry", lambda e: asked.append(e) or {"entry": e, "name": "Nos. 1-30, TEST CRESCENT", "grade": "I", "since": "1950-06-12"})
    run = Run(offline=True)
    a = run.check(way=NEW)["answer"]
    assert asked == ["1999997"]
    assert a["solar"]["status"] == "needs_consent"
    listed = next(f for f in a["house_facts"] if f["key"] == "listed")
    assert listed["value"].startswith("Grade I listed") and "OpenStreetMap" in listed["source"]
    assert "listed_point_only" not in a["solar"]["uncertain"]
    said = [e["text"] for e in run.events if e.get("about") == "listed"]
    assert any("list entry 1999997" in t for t in said) and any("confirms" in t for t in said)


def test_a_list_entry_tag_historic_england_does_not_hold_is_not_used(sources, monkeypatch):
    tags = {"building": "yes", "addr:street": "Test Road", "ref:GB:nhle": "1999996"}
    monkeypatch.setattr(osm, "house_from_way", lambda way: osm._house(f"osm-way-{way}", COORDS, tags, f"OpenStreetMap way {way}", way_id=way))
    monkeypatch.setattr(offline, "he_entry", lambda e: None)
    a = Run(offline=True).check(way=NEW)["answer"]
    assert a["solar"]["status"] == "allowed"
    assert next(f for f in a["house_facts"] if f["key"] == "listed")["value"] == "Not listed"
