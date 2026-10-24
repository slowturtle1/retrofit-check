"""The law in code, checked on fixed facts. No network, no Zetaris: facts are a snapshot of what Zetaris returned for house D."""

import copy
import json
from datetime import date
from pathlib import Path

from retrofit import rules

HERE = Path(__file__).parent
D = json.loads((HERE / "house_d_facts.json").read_text())


def facts(**changes):
    f = copy.deepcopy(D)
    f.update(changes)
    return f


def status(result, measure):
    return next(v for v in result["verdicts"] if v["measure"] == measure)


def test_house_d_in_conservation_area():
    r = rules.evaluate(facts(), heating="gas", today=date(2026, 10, 24))
    assert status(r, "solar")["status"] == "allowed"
    assert "solar-ca-wall" in status(r, "solar")["conditions"]
    assert status(r, "heat_pump")["status"] == "allowed_with_conditions"
    assert status(r, "heat_pump")["grants"][0] == "bus-standard"
    wi = status(r, "wall_insulation")
    assert wi["status"] == "needs_permission" and wi["rules"] == ["ewi-art23"]
    assert "inside-insulation" in wi["alternatives"]


def test_detached_gets_two_units_terrace_gets_one():
    r = rules.evaluate(facts(), heating="gas")
    assert status(r, "heat_pump")["numbers"]["units_allowed"] == 2
    walls = copy.deepcopy(D["walls"])
    walls[3]["adjoins"] = "true"
    r = rules.evaluate(facts(walls=walls), heating="gas")
    assert status(r, "heat_pump")["numbers"]["units_allowed"] == 1


def test_listed_needs_consent_for_everything():
    des = D["designations"] + [{"dataset": "listed-building", "reference": "1210759", "name": "10, DOWNING STREET", "grade": "I", "start_date": "1970-01-14",
                                "end_date": None, "entity": 1, "removes_solar": None, "removes_ashp": None, "removes_walls": None,
                                "a4_summary": None, "a4_source": None, "a4_end_date": None}]
    r = rules.evaluate(facts(designations=des), heating="gas")
    assert {v["status"] for v in r["verdicts"]} == {"needs_consent"}


def test_outside_conservation_area_walls_allowed_if_they_look_the_same():
    des = [d for d in D["designations"] if d["dataset"] != "conservation-area"]
    r = rules.evaluate(facts(designations=des), heating="gas")
    wi = status(r, "wall_insulation")
    assert wi["status"] == "allowed_with_conditions" and wi["conditions"] == ["ewi-materials"]
    assert "ashp-front-upper" in status(r, "heat_pump")["conditions"]


def test_unknown_article_4_is_not_guessed():
    des = D["designations"] + [{"dataset": "article-4-direction-area", "reference": "X1", "name": "Somewhere", "grade": None, "start_date": "2020-01-01",
                                "end_date": None, "entity": 2, "removes_solar": None, "removes_ashp": None, "removes_walls": None,
                                "a4_summary": None, "a4_source": None, "a4_end_date": None}]
    r = rules.evaluate(facts(designations=des), heating="gas")
    assert status(r, "solar")["status"] == "check_with_council"
    assert "article4_unknown" in status(r, "solar")["uncertain"]


def test_every_wall_on_a_road_means_permission_for_a_heat_pump():
    walls = copy.deepcopy(D["walls"])
    for w in walls:
        w["fronts_highway"], w["highway_name"] = "true", "Some Road"
    r = rules.evaluate(facts(walls=walls), heating="gas")
    assert status(r, "heat_pump")["status"] == "needs_permission"


def test_9000_needs_no_gas_grid_not_just_oil():
    on_grid = rules.evaluate(facts(), heating="oil", off_gas_grid=False, today=date(2026, 10, 24))
    assert status(on_grid, "heat_pump")["grants"][0] == "bus-standard"


def test_off_gas_grid_oil_gets_9000_only_inside_the_window():
    inside = rules.evaluate(facts(), heating="oil", off_gas_grid=True, today=date(2026, 10, 24))
    after = rules.evaluate(facts(), heating="oil", off_gas_grid=True, today=date(2027, 4, 1))
    assert status(inside, "heat_pump")["grants"][0] == "bus-off-gas"
    assert status(after, "heat_pump")["grants"][0] == "bus-standard"


def test_homeowner_correction_turns_a_lane_into_a_usable_wall():
    before = rules.evaluate(facts(), heating="gas")
    assert "north east" in status(before, "heat_pump")["where"]["road_walls"]
    after = rules.evaluate(facts(), heating="gas", walls_not_road=["north east"], said_on="2026-10-24")
    hp = status(after, "heat_pump")
    assert "north east" not in hp["where"]["road_walls"] and "north east" in hp["where"]["ok_walls"]
    assert any(f["fact"] == "your correction" and f["source"] == "you, 2026-10-24" for f in hp["facts"])
