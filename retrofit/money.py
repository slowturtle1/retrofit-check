"""Rough money and a next step for each upgrade. Ranges only, from dated rows in retrofit_pg.price_fact (read through Zetaris).

Recommendations, so the owner can decide what to do next (never "buy"):
  "Worth getting quotes" · "Ask the council first" · "Probably not worth it for this house" · "Can't tell yet: add your gas use"
"""

from __future__ import annotations

WORTH = "Worth getting quotes"
COUNCIL = "Ask the council first"
NOT_WORTH = "Probably not worth it for this house"
BOILER_SOON = "Worth it mainly if your boiler needs replacing soon"
ADD_GAS = "Can't tell yet: add your gas use"

UNSURE = {"article4_unknown", "article4_coverage_unknown", "listed_point_only", "listed_he_only", "no_wall_away_from_road"}
PV_LIFE_YEARS = 25         # used when price_fact has no pv_life_years row; worth quotes if a typical payback fits in the panels' life
MIN_KWH_PER_KWP = 700      # below this the roof gets too little sun
MIN_KWP = 1.5              # smaller systems carry the same fixed costs (scaffold, inverter) for little output


def _r(x: float, step: int = 10) -> int:
    return int(round(x / step) * step)


def solar(v: dict, p: dict) -> dict:
    n = v.get("numbers") or {}
    if v["status"] not in ("allowed", "allowed_with_conditions"):
        return {"recommendation": COUNCIL}
    if not n.get("kwp"):
        if set(v["uncertain"]) & UNSURE:   # the legal answer is open: that comes first, whatever the roof
            return {"recommendation": COUNCIL, "why": "No roof slope faces between east and west."}
        return {"recommendation": NOT_WORTH, "why": "No roof slope faces between east and west."}
    kwp, kwh = float(n["kwp"]), float(n["kwh_year"])
    cost = (_r(kwp * p["solar_cost_gb_median"], 100), _r(kwp * p["solar_cost_london_mean"], 100))
    rate = p["elec_rate"] / 100
    value = (_r(kwh * (p["self_use_low"] * rate + (1 - p["self_use_low"]) * p["seg_low"] / 100)),
             _r(kwh * (p["self_use_high"] * rate + (1 - p["self_use_high"]) * p["seg_high"] / 100)))
    payback = (round(cost[0] / value[1]), round(cost[1] / value[0]))
    weak = kwh / kwp < MIN_KWH_PER_KWP or (payback[0] + payback[1]) / 2 > p.get("pv_life_years", PV_LIFE_YEARS) or kwp < MIN_KWP
    why = None
    if kwp < MIN_KWP:
        why = f"Only about {kwp} kWp of usable roof: fixed costs such as scaffolding make a system this small poor value."
        payback = None   # the per kW cost series leave out those fixed costs, so a payback here would flatter it
    elif "lidar_noisy" in v["uncertain"]:
        why = "The roof reading is rough (trees or chimneys); an installer's survey will confirm the space."
    rec = COUNCIL if set(v["uncertain"]) & UNSURE else NOT_WORTH if weak else WORTH
    return {"recommendation": rec, "why": why, "cost": cost, "value_year": value, "payback_years": payback,
            "uses": ["solar_cost_gb_median", "solar_cost_london_mean", "elec_rate", "seg_low", "seg_high", "self_use_low", "self_use_high", "pv_life_years"],
            "note": "MCS certified installer needed for export payments."}


def heat_pump(v: dict, p: dict, grant_gbp: int | None, gas_kwh: float | None, heating: str | None) -> dict:
    if v["status"] not in ("allowed", "allowed_with_conditions") or set(v["uncertain"]) & UNSURE:
        return {"recommendation": COUNCIL}
    grant = grant_gbp or 0
    cost = (_r(p["ashp_cost_lq"] - grant, 100), _r(p["ashp_cost_uq"] - grant, 100))
    out = {"cost_before_grant": (_r(p["ashp_cost_lq"], 100), _r(p["ashp_cost_uq"], 100)), "grant": grant, "cost": cost,
           "median_after_grant": _r(p["ashp_cost_median"] - grant, 100),
           "uses": ["ashp_cost_lq", "ashp_cost_median", "ashp_cost_uq"], "note": "The MCS installer applies for the grant and takes it off the bill."}
    if heating in (None, "gas") and not gas_kwh:
        return {**out, "recommendation": ADD_GAS, "saving_year": None}
    if heating != "gas":
        return {**out, "recommendation": WORTH if heating in ("oil", "lpg", "coal", "electric") else ADD_GAS, "saving_year": None,
                "why": "Running cost saving not estimated: only gas and electricity prices are on file."}
    heat = gas_kwh * p["boiler_eff"]
    gas_cost = gas_kwh * p["gas_rate"] / 100 + 365 * p["gas_standing"] / 100   # gas meter can go once the boiler does
    saving = (_r(gas_cost - heat / p["scop_low"] * p["elec_rate"] / 100), _r(gas_cost - heat / p["scop_high"] * p["elec_rate"] / 100))
    out["note"] += " The saving assumes you also close the gas supply, so the gas standing charge goes."
    out.update(saving_year=saving, gas_kwh=int(gas_kwh),
               uses=out["uses"] + ["gas_rate", "gas_standing", "elec_rate", "boiler_eff", "scop_low", "scop_high", "ashp_life_years", "gas_boiler_cost"])
    if saving[1] <= 0:
        out["recommendation"] = NOT_WORTH
        out["why"] = "At today's prices the running cost would not fall."
        return out
    life, typical_saving = p["ashp_life_years"], (saving[0] + saving[1]) / 2
    out["payback_years"] = (round(cost[0] / saving[1]), round(cost[1] / max(saving[0], 1)))
    if typical_saving > 0 and out["median_after_grant"] / typical_saving <= life:
        out["recommendation"] = WORTH
        return out
    # Not within the pump's life on its own: compare with the boiler you would buy anyway.
    extra = _r(out["median_after_grant"] - p["gas_boiler_cost"], 100)
    out["extra_over_boiler"] = extra
    out["extra_payback_years"] = round(max(extra, 0) / typical_saving) if typical_saving > 0 else None
    if typical_saving > 0 and max(extra, 0) / typical_saving <= life:
        out["recommendation"] = BOILER_SOON
        out["why"] = (f"On its own it would take longer than a heat pump lasts (up to {life:.0f} years) to pay back. "
                      f"If your boiler needs replacing anyway, a typical heat pump costs about £{extra:,} more than a new gas boiler, "
                      f"which the saving pays back in about {out['extra_payback_years']} years.")
    else:
        out["recommendation"] = NOT_WORTH
        out["why"] = "Even against a new gas boiler, the saving would not pay back within a heat pump's life."
    return out


def wall_insulation(v: dict) -> dict:
    if v["status"] != "allowed_with_conditions" or set(v["uncertain"]) & UNSURE:
        return {"recommendation": COUNCIL}
    return {"recommendation": WORTH, "note": "Keep the finish looking like your walls do now."}


def advise(result: dict, prices: dict, gas_kwh: float | None, heating: str | None) -> dict:
    out = {}
    for v in result["verdicts"]:
        if v["measure"] == "solar":
            out["solar"] = solar(v, prices)
        elif v["measure"] == "heat_pump":
            g = result["grants"].get(v["grants"][0]) if v["grants"] and v["grants"][0].startswith("bus") else None
            out["heat_pump"] = heat_pump(v, prices, int(g["amount_gbp"]) if g else None, gas_kwh, heating)
        else:
            out["wall_insulation"] = wall_insulation(v)
    return out
