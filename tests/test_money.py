"""Rough money and the next step for each upgrade, from fixed facts and the dated price rows."""

import json
from datetime import date
from pathlib import Path

from retrofit import money, rules

HERE = Path(__file__).parent
D = json.loads((HERE / "house_d_facts.json").read_text())
SNAP = json.loads((HERE / "rules_snapshot.json").read_text())
PRICES = {"gas_boiler_cost": 3500, "ashp_life_years": 20, "elec_rate": 26.32, "gas_rate": 7.97, "gas_standing": 29.68, "seg_low": 6, "seg_high": 15,
          "solar_cost_gb_median": 1595.06, "solar_cost_london_mean": 2101.01, "ashp_cost_lq": 11128, "ashp_cost_median": 12908,
          "ashp_cost_uq": 15627, "self_use_low": 0.25, "self_use_high": 0.5, "boiler_eff": 0.85, "scop_low": 2.8, "scop_high": 3.5}


def advise(heating="gas", gas_kwh=None, **kw):
    r = rules.evaluate(D, heating=heating, today=date(2026, 10, 24), **kw)
    r["grants"] = SNAP["grants"]
    return money.advise(r, PRICES, gas_kwh, heating)


def test_solar_full_answer_for_house_d():
    s = advise()["solar"]
    assert s["recommendation"] == money.WORTH
    assert s["cost"] == (5100, 6700)            # 3.2 kWp at the national median and the London average
    assert s["value_year"][0] < s["value_year"][1]
    assert 5 <= s["payback_years"][0] < s["payback_years"][1] <= 25


def test_heat_pump_needs_gas_use_before_a_saving():
    hp = advise()["heat_pump"]
    assert hp["recommendation"] == money.ADD_GAS and hp["saving_year"] is None
    assert hp["cost"] == (3600, 8100)           # BUS quartiles minus the £7,500 grant


def test_heat_pump_with_ordinary_gas_use_is_worth_it_mainly_when_the_boiler_is_due():
    hp = advise(gas_kwh=12000)["heat_pump"]
    assert hp["saving_year"][0] < hp["saving_year"][1]
    assert hp["recommendation"] == money.BOILER_SOON
    assert hp["extra_over_boiler"] == 1900 and hp["extra_payback_years"] <= 20


def test_heat_pump_with_high_gas_use_pays_back_within_its_life():
    hp = advise(gas_kwh=40000)["heat_pump"]
    assert hp["recommendation"] == money.WORTH
    assert hp["median_after_grant"] / ((hp["saving_year"][0] + hp["saving_year"][1]) / 2) <= 20


def test_outside_wall_insulation_in_a_conservation_area_asks_the_council():
    assert advise()["wall_insulation"]["recommendation"] == money.COUNCIL


def test_a_tiny_roof_is_not_worth_it():
    import copy
    f = copy.deepcopy(D)
    f["pv"] = {"facing": "SE", "kwp": "0.9", "kwh_year": "878", "params": "", "source": "PVGIS"}
    r = rules.evaluate(f, heating="gas", today=date(2026, 10, 24))
    r["grants"] = SNAP["grants"]
    s = money.advise(r, PRICES, None, "gas")["solar"]
    assert s["recommendation"] == money.NOT_WORTH and "0.9 kWp" in s["why"]
