"""The law, applied in code. The model never decides a status; it explains these.

Everything is read through Zetaris: the cached house facts, the planning designations,
what each Article 4 direction removes, the dated rules and the grants.
Every verdict lists the rule rows and the facts it used, so the critic can check each claim.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from .zetaris import Zetaris

ART23 = {"conservation-area", "area-of-outstanding-natural-beauty", "national-park", "world-heritage-site"}
LISTED = {"listed-building", "listed-building-outline"}
REPLACEABLE = {"gas", "oil", "lpg", "coal", "electric"}   # what the Boiler Upgrade Scheme helps you replace
OFF_GRID_FUELS = {"oil", "lpg", "coal", "electric"}       # a gas boiler means the house is on the grid
COMPASS = ["north", "north east", "east", "south east", "south", "south west", "west", "north west"]


def compass(deg) -> str:
    return COMPASS[int(((float(deg) % 360) + 22.5) // 45) % 8]


@dataclass
class Verdict:
    measure: str
    status: str            # allowed | allowed_with_conditions | needs_permission | needs_consent | check_with_council
    headline: str
    rules: list[str] = field(default_factory=list)          # pd_rule ids
    facts: list[dict] = field(default_factory=list)         # {fact, value, source}
    conditions: list[str] = field(default_factory=list)     # pd_rule ids that are conditions to follow
    alternatives: list[str] = field(default_factory=list)   # pd_rule or grant ids
    grants: list[str] = field(default_factory=list)
    numbers: dict = field(default_factory=dict)
    where: dict = field(default_factory=dict)               # for the map: roof plane, ok walls, blocked walls
    uncertain: list[str] = field(default_factory=list)


def q(z: Zetaris, sql: str, purpose: str) -> list[dict]:
    return z.run(sql, purpose=purpose).dicts()


def load(z: Zetaris, house_id: str) -> dict:
    """Eight reads through Zetaris, sent together so a slow query does not hold up the rest."""
    from concurrent.futures import ThreadPoolExecutor

    hid = house_id.replace("'", "")
    asks = {
        "house": (f"SELECT house_id, label, lat, lon, building, footprint_m2, source, fetched_at FROM retrofit_pg.house WHERE house_id = '{hid}'", "The house: footprint from OpenStreetMap"),
        "walls": (f"SELECT wall_no, facing_deg, length_m, fronts_highway, highway_name, distance_m, adjoins FROM retrofit_pg.house_wall WHERE house_id = '{hid}' ORDER BY wall_no", "Which walls face a road"),
        "planes": (f"SELECT facing, azimuth_deg, pitch_deg, area_m2 FROM retrofit_pg.roof_plane WHERE house_id = '{hid}' ORDER BY area_m2 DESC", "Roof planes measured from LIDAR"),
        "survey": (f"SELECT noise_pct, flat_pct, eaves_m, ridge_m, method, measured_at FROM retrofit_pg.roof_survey WHERE house_id = '{hid}'", "How clean the LIDAR roof reading is"),
        "pv": (f"SELECT facing, kwp, kwh_year, params, source, fetched_at FROM retrofit_pg.pv_estimate WHERE house_id = '{hid}'", "Solar yield from PVGIS"),
        "designations": (f"""SELECT d.dataset, d.reference, d.name, d.grade, d.start_date, d.end_date, d.entity, d.organisation,
       a.removes_solar, a.removes_ashp, a.removes_walls, a.summary AS a4_summary, a.source_url AS a4_source, a.end_date AS a4_end_date
FROM retrofit_pg.designation d
LEFT JOIN retrofit_pg.article4_rule a ON a.reference = d.reference
WHERE d.house_id = '{hid}'""", "Protected areas, listing and Article 4, joined to what each Article 4 removes"),
        "rules": ("SELECT rule_id, measure, clause, plain, applies_when, effect, in_force, amended_by, source_url, checked_on FROM retrofit_pg.pd_rule", "The dated rules"),
        "grants": ("SELECT scheme_id, measure, amount_gbp, plain, condition, valid_from, valid_to, source_url, checked_on FROM retrofit_pg.grant_scheme", "Help with cost"),
        "prices": ("SELECT fact_id, value, unit, plain, kind, valid_from, valid_to, source_url, checked_on FROM retrofit_pg.price_fact", "Dated prices and costs for rough money"),
    }
    with ThreadPoolExecutor(len(asks)) as pool:
        got = dict(zip(asks, pool.map(lambda kv: q(z, *kv), asks.values())))
    return {
        "house": got["house"][0],
        "walls": got["walls"],
        "planes": got["planes"],
        "survey": got["survey"][0],
        "pv": (got["pv"] or [None])[0],
        "designations": got["designations"],
        "rules": {r["rule_id"]: r for r in got["rules"]},
        "grants": {g["scheme_id"]: g for g in got["grants"]},
        "prices": {r["fact_id"]: r for r in got["prices"]},
    }


def _true(v) -> bool:
    return str(v).lower() in ("true", "t", "1")


def evaluate(f: dict, heating: str | None = None, off_gas_grid: bool | None = None, today: date | None = None,
             walls_not_road: list[str] | None = None, said_on: str | None = None) -> dict:
    """walls_not_road: compass sides the homeowner told us are not a road (for example a private drive)."""
    today = today or date.today()
    des = f["designations"]
    corrected = []
    for w in f["walls"]:
        if walls_not_road and _true(w["fronts_highway"]) and compass(w["facing_deg"]) in walls_not_road:
            w["fronts_highway"] = "false"
            corrected.append(f"{compass(w['facing_deg'])} wall: {w['highway_name']} is not a public road")
    listed = [d for d in des if d["dataset"] in LISTED]
    protected = [d for d in des if d["dataset"] in ART23]
    a4 = [d for d in des if d["dataset"] == "article-4-direction-area"]
    a4_unknown = [d for d in a4 if d["removes_solar"] is None]
    ended = lambda d: bool(d.get("a4_end_date")) and str(d["a4_end_date"])[:10] <= today.isoformat()  # noqa: E731
    a4_ended = [d for d in a4 if ended(d)]
    a4_live = [d for d in a4 if d["removes_solar"] is not None and not ended(d)]
    disagree = [d for d in a4_ended if not d.get("end_date")]
    walls = f["walls"]
    front = [w for w in walls if _true(w["fronts_highway"])]
    shares_wall = any(_true(w["adjoins"]) for w in walls) or (f["house"].get("building") in ("terrace", "semidetached_house"))
    ok_walls = [w for w in walls if not _true(w["fronts_highway"]) and not _true(w["adjoins"])]
    pv = f["pv"]
    survey = f["survey"]

    by_entry = any(d.get("organisation") == "historic-england" for d in listed)   # confirmed by list entry (facts._listed_by_tag)
    base_facts = [{"fact": "listed", "value": ", ".join(f"{d['name']} (grade {d['grade'] or '?'}, {d['start_date']})" for d in listed) or "no",
                   "source": "Historic England list entry, tagged on the building in OpenStreetMap" if by_entry else "planning.data listed-building"}]
    for d in protected:
        base_facts.append({"fact": d["dataset"], "value": f"{d['name']} ({d['reference']}, since {d['start_date'] or 'unknown date'})", "source": "planning.data " + d["dataset"]})
    for d in a4:
        what = "content not on file" if d["removes_solar"] is None else (d["a4_summary"] or "")
        since = f", from {d['start_date']}" if d.get("start_date") else ""
        base_facts.append({"fact": "article-4", "value": f"{d['name']} ({d['reference']}{since}): {what}", "source": d.get("a4_source") or "planning.data article-4-direction-area"})

    for d in disagree:
        base_facts.append({"fact": "sources disagree", "value": f"planning.data still lists {d['reference']} with no end date; the council ended it on {d['a4_end_date']}. Using the council's decision.",
                           "source": d.get("a4_source") or "council"})
    uncertain_common = []
    if a4_unknown:
        uncertain_common.append("article4_unknown")
    if a4_ended:
        uncertain_common.append("article4_ended_but_listed")

    out = []

    # Solar panels
    v = Verdict("solar", "allowed", "", facts=list(base_facts))
    if listed:
        v.status, v.rules = "needs_consent", ["solar-listed"]
    elif any(_true(d["removes_solar"]) for d in a4_live):
        v.status, v.rules = "needs_permission", ["article-4"]
    elif a4_unknown:
        v.status = "check_with_council"
    else:
        v.conditions = ["solar-pitched"] + (["solar-ca-wall"] if protected else [])
        if protected and int(survey["flat_pct"]) > 50:
            v.conditions.append("solar-flat-art23")
    if pv:
        v.numbers = {"kwp": float(pv["kwp"]), "kwh_year": int(pv["kwh_year"]), "facing": pv["facing"]}
        v.facts.append({"fact": "best roof plane", "value": f"{pv['facing']}, {pv['kwp']} kWp, about {pv['kwh_year']} kWh a year", "source": pv["source"] + "; roof from EA LIDAR"})
        v.where["roof_facing"] = pv["facing"]
    elif listed:
        v.facts.append({"fact": "roof", "value": "not measured: consent is needed whatever the roof is like", "source": "agent decision"})
    else:
        v.uncertain.append("no_sunny_roof")
    if int(survey["noise_pct"]) > 25:
        v.uncertain.append("lidar_noisy")
    if not listed:
        v.facts.append({"fact": "LIDAR noise", "value": f"{survey['noise_pct']}% of roof cells (trees, chimneys)", "source": "EA LIDAR DSM 1 m"})
    v.grants = ["vat-zero", "seg"]
    v.uncertain += uncertain_common
    v.where["a4_solar"] = [f"{d['name']} ({d['reference']})" for d in a4_live if _true(d["removes_solar"])]
    v.where["a4_unknown"] = [f"{d['name']} ({d['reference']})" for d in a4_unknown]
    out.append(v)

    # Air source heat pump
    v = Verdict("heat_pump", "allowed_with_conditions", "", facts=list(base_facts))
    if listed:
        v.status, v.rules = "needs_consent", ["ashp-listed"]
    elif any(_true(d["removes_ashp"]) for d in a4_live):
        v.status, v.rules = "needs_permission", ["article-4"]
    elif a4_unknown:
        v.status = "check_with_council"
    else:
        v.conditions = ["ashp-units"] + (["ashp-ca-front"] if protected else ["ashp-front-upper"])
        if protected and not ok_walls:
            v.status = "needs_permission"
            v.uncertain.append("no_wall_away_from_road")
    v.numbers = {"units_allowed": 1 if shares_wall else 2}
    v.where = {"ok_walls": [compass(w["facing_deg"]) for w in ok_walls], "road_walls": [compass(w["facing_deg"]) for w in front]}
    v.facts.append({"fact": "walls facing a road", "value": ", ".join(f"{compass(w['facing_deg'])} wall to {w['highway_name']}" for w in front) or "none", "source": "OpenStreetMap roads and footprint"})
    for c in corrected:
        v.facts.append({"fact": "your correction", "value": c, "source": f"you, {said_on or today.isoformat()}"})
    v.facts.append({"fact": "shares a wall with a neighbour", "value": "yes" if shares_wall else "no", "source": "OpenStreetMap footprints"})
    if any((w["highway_name"] or "") in ("service", "footway", "path") for w in front):
        v.uncertain.append("lane_may_not_be_highway")
    if heating:
        v.facts.append({"fact": "current heating", "value": heating, "source": "you"})
    if off_gas_grid:
        v.facts.append({"fact": "gas grid", "value": "not connected", "source": "you"})
    if off_gas_grid and heating in OFF_GRID_FUELS and date(2026, 7, 21) <= today <= date(2027, 3, 31):
        v.grants = ["bus-off-gas", "vat-zero"]
    elif heating in REPLACEABLE:
        v.grants = ["bus-standard", "vat-zero"]
    else:
        v.grants = ["vat-zero"]
        v.uncertain.append("heating_unknown" if not heating else "bus_needs_fossil_heating")
    v.uncertain += uncertain_common
    out.append(v)

    # Outside wall insulation
    v = Verdict("wall_insulation", "allowed_with_conditions", "", facts=list(base_facts))
    if listed:
        v.status, v.rules = "needs_consent", ["ewi-listed"]
    elif protected:
        v.status, v.rules = "needs_permission", ["ewi-art23"]
        v.alternatives = ["inside-insulation", "householder-fee"]
    elif any(_true(d["removes_walls"]) for d in a4_live):
        v.status, v.rules = "needs_permission", ["article-4"]
        v.alternatives = ["inside-insulation", "householder-fee"]
    elif a4_unknown:
        v.status = "check_with_council"
    else:
        v.conditions = ["ewi-materials"]
    v.grants = ["vat-zero"]
    v.uncertain += uncertain_common
    out.append(v)

    for x in out:
        x.headline = HEADLINES[x.status]
    return {
        "house": f["house"],
        "protected": [d["name"] for d in protected],
        "areas": [{"name": d["name"], "dataset": d["dataset"], "reference": d["reference"], "entity": d["entity"], "start_date": d["start_date"], "grade": d["grade"]} for d in des if d["dataset"] != "article-4-direction-area"],
        "listed": bool(listed),
        "verdicts": [asdict(x) for x in out],
        "rules": f["rules"],
        "grants": f["grants"],
        "today": today.isoformat(),
    }


HEADLINES = {
    "allowed": "Allowed under permitted development",
    "allowed_with_conditions": "Allowed under permitted development, if conditions are met",
    "needs_permission": "Needs planning permission",
    "needs_consent": "Needs listed building consent",
    "check_with_council": "Check with the council",
}
