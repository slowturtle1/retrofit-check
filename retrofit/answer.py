"""The answer JSON (contract in schema.py) for one check, built from the verdict, the money and the texts.

Solar only in this version: heat pump and wall verdicts are still computed by rules.py, but not shown.
"""

from __future__ import annotations

import re
from datetime import date

from . import schema
from .rules import HEADLINES

GENERAL_LIMITS = [
    "Rules for England, demo data for London.",
    "Map drawings are indicative.",
    "Roof size and yield come from 1 m LIDAR and PVGIS: an installer's survey confirms them.",
    "Not legal or financial advice.",
]

LDC = "If you want it in writing, apply to {council} for a lawful development certificate."

NEXT = {
    "needs_consent": "Talk to {council}'s conservation officer before you plan anything.",
    "needs_permission": "Ask {council} about a planning application before you plan anything.",
    "check_with_council": "Ask {council}'s planning team whether an Article 4 direction removes the right to add solar panels here.",
}
NEXT_BY_RECOMMENDATION = {
    "Worth getting quotes": "Get quotes from two or three MCS certified installers.",
    "Ask the council first": "Ask {council}'s planning team before you get quotes.",
    "Probably not worth it for this house": "Ask one MCS certified installer to look at the roof only if you still want panels.",
}


def shown_status(v: dict) -> str:
    """D3: when the legal answer itself is open, the card says so and never says allowed."""
    return "check_with_council" if schema.open_flags(v) else v["status"]


def next_step(v: dict, recommendation: str | None, council: str | None = None) -> str:
    status = shown_status(v)
    if {"listed_point_only", "listed_he_only"} & schema.open_flags(v):
        return f"Check Historic England's map, or ask {council or 'the council'}, whether the listing covers this building before you plan panels."
    step = NEXT.get(status) or NEXT_BY_RECOMMENDATION.get(recommendation or "", "Ask {council}'s planning team.")
    step = step.format(council=council or "the council")
    return f"{step} {LDC.format(council=council or 'the council')}" if status.startswith("allowed") else step


def confidence_text(res: dict, v: dict, level: str) -> str:
    """One line for the card: the level and the reason, in this house's terms."""
    council = res.get("council") or "the council"
    noise = (res.get("survey") or {}).get("noise_pct")
    u = set(v["uncertain"])
    if level == "low":
        if "article4_coverage_unknown" in u:
            return f"Low: {council} has not published its conservation area Article 4 directions, so one could exist."
        if "listed_point_only" in u:
            return "Low: the listing was found as a point only, so it may belong to the building next door."
        if "listed_he_only" in u:
            return "Low: Historic England's map shows a listed outline here that planning.data does not."
        return "Low: an Article 4 direction covers this house and what it removes is not on file."
    if level == "medium":
        if "lidar_noisy" in u:
            return f"Medium: the rules are clear, but the roof reading is rough ({noise}% trees or chimneys)."
        if "no_sunny_roof" in u:
            return "Medium: the rules are clear, but no roof slope faces between east and west."
        return f"Medium: planning.data and {council} disagree about an Article 4 direction; we follow {council}."
    if v["status"] == "needs_consent":
        return "High: the listing is on Historic England's register with an outline that covers this building."
    clean = f", and the roof reading is clean ({noise}% trees or chimneys)" if noise is not None else ""
    return f"High: the listing, conservation area and Article 4 records agree{clean}."


def limitations(v: dict, prices: dict, uncertain_text: dict, money: dict | None = None) -> list[str]:
    out = [uncertain_text.get(u, u) for u in v["uncertain"]]
    su = (money or {}).get("self_use") or {}
    if (money or {}).get("value_year") and su.get("source", "").startswith("MCS"):
        who = "you told us" if su.get("by_owner") else "a typical home, Ofgem"
        out.append(f"The share of solar power used at home follows the MCS tables for {su['use_kwh']:,} kWh a year ({who}); your own pattern may differ." +
                   (" That use or this roof's yield is outside the tables, so the nearest band is used." if su.get("nearest_band") else ""))
    elif (money or {}).get("value_year"):
        out.append("How much of the solar power you use at home is an estimate (a quarter to a half without a battery).")
    return out + GENERAL_LIMITS


def facts(v: dict, owner: dict) -> list[dict]:
    out = [{**f, "date": f.get("date")} for f in v["facts"]]
    if owner.get("elec_kwh"):
        out.append({"fact": "your electricity use", "value": f"{int(owner['elec_kwh']):,} kWh a year", "source": "you told us", "date": owner.get("elec_said_on")})
    return out


def usage(v: dict, owner: dict) -> dict | None:
    """D4: the owner's yearly electricity use (from H-MEM) against what the roof makes."""
    kwh, roof = owner.get("elec_kwh"), (v["numbers"] or {}).get("kwh_year")
    if not kwh or not roof:
        return None
    pct = round(100 * float(roof) / float(kwh))
    said = owner.get("elec_said_on")
    when = date.fromisoformat(said[:10]).strftime("%-d %b %Y") if said else "date unknown"
    return {"elec_kwh": int(kwh), "said_on": said, "roof_kwh": int(roof), "share_pct": pct,
            "text": f"Your roof could make about {pct}% of the {int(kwh):,} kWh you use a year (you told us, {when})."}


def _true(x) -> bool:
    return str(x).lower() in ("true", "t", "1")


def house_facts(res: dict, v: dict) -> list[dict]:
    """Your house: 7 facts, in a fixed order. The owner's facts carry the date they told us."""
    from .rules import compass
    areas, owner = res.get("areas") or [], res.get("owner") or {}
    listed = [a for a in areas if a["dataset"].startswith("listed")]
    ca = [a for a in areas if a["dataset"] == "conservation-area"]
    a4 = [f for f in v["facts"] if f["fact"] == "article-4"]
    roads = [w for w in res.get("walls") or [] if _true(w.get("fronts_highway"))]
    planes = sorted(res.get("planes") or [], key=lambda p: -float(p["area_m2"]))
    best = next((p for p in planes if p["facing"] == (v["numbers"] or {}).get("facing")), planes[0] if planes else None)
    n = v["numbers"] or {}
    day = lambda x: str(x)[:10] if x else None  # noqa: E731  the date each source was read
    read, measured = day(res["house"].get("fetched_at")), day((res.get("survey") or {}).get("measured_at"))
    pv_read = day(res.get("pv_fetched_at")) or measured
    side = {"N": "north", "NE": "north east", "E": "east", "SE": "south east", "S": "south", "SW": "south west", "W": "west", "NW": "north west"}
    a4_text = [re.sub(r", from (\d{4}-\d{2}-\d{2})\)", lambda m: f", from {date.fromisoformat(m.group(1)).strftime('%-d %b %Y')})", f["value"].split(":")[0]) for f in a4]

    def fact(key, label, value, source, when=None, from_owner=False):
        return {"key": key, "label": label, "value": value, "source": source, "date": when, "from_owner": from_owner}
    return [
        fact("listed", "Listed", (", ".join(f"Grade {a['grade']} listed" if a.get("grade") else "Listed" for a in listed[:1]) +
                                  (" (found as a point only, may be next door)" if "listed_point_only" in v["uncertain"] else "")) if listed else
             ("Not on planning.data, but Historic England shows a listed outline here" if "listed_he_only" in v["uncertain"] else "Not listed"),
             "Historic England, list entry on the building in OpenStreetMap" if "OpenStreetMap" in next((f["source"] for f in v["facts"] if f["fact"] == "listed"), "")
             else "Historic England, via planning.data", read),
        fact("conservation_area", "Conservation area", ", ".join(f"{a['name']} ({a['start_date'][:4]})" if a.get("start_date") else a["name"] for a in ca) or "None", "planning.data", read),
        fact("article_4", "Article 4", "; ".join(a4_text) or "None on file", "planning.data and the council", read),
        fact("road_walls", "Walls facing a road", ", ".join(dict.fromkeys(f"{compass(w['facing_deg'])} to {w['highway_name']}" for w in roads)) or "None", "OpenStreetMap", read),
        fact("roof", "Roof direction and slope", f"{side.get(best['facing'], best['facing'])} slope, {best['pitch_deg']}°, about {best['area_m2']} m²" if best else "Not measured",
             "Environment Agency LIDAR", measured if best else None),
        fact("sun", "Sun on the roof", f"about {n['kwh_year']:,} kWh a year from {n['kwp']} kWp" if n.get("kwh_year") else "Not estimated", "PVGIS, EU Joint Research Centre",
             pv_read if n.get("kwh_year") else None),
        fact("electricity_use", "Your electricity use", f"{int(owner['elec_kwh']):,} kWh a year" if owner.get("elec_kwh") else None,
             "you told us" if owner.get("elec_kwh") else "not given yet", owner.get("elec_said_on"), True),
    ]


def build(rec: dict, mode: str, uncertain_text: dict) -> dict:
    res, texts = rec["result"], rec["texts"]
    v = next(x for x in res["verdicts"] if x["measure"] == "solar")
    m = res.get("money", {}).get("solar", {})
    t = texts.get("solar", {})
    owner = res.get("owner") or {}
    numbers = dict(v["numbers"])
    for k, out in (("cost", "cost_gbp"), ("value_year", "value_gbp_year"), ("payback_years", "payback_years")):
        if m.get(k):
            numbers[out] = list(m[k])
    events = rec.get("events", [])
    conf = schema.confidence(v)
    return {
        "schema": schema.VERSION,
        "trace_id": rec["run_id"], "run_id": rec["run_id"], "mode": mode, "seconds": rec.get("seconds"),
        "question": schema.QUESTION,
        "house": {k: res["house"].get(k) for k in ("house_id", "label", "lat", "lon", "building", "footprint_m2", "source")},
        "solar": {
            "status": shown_status(v), "status_text": HEADLINES[shown_status(v)], "rules_status": v["status"],
            "recommendation": m.get("recommendation"),
            "confidence": {**conf, "text": confidence_text(res, v, conf["level"])},
            "limitations": limitations(v, res.get("prices") or {}, uncertain_text, m),
            "next_step": next_step(v, m.get("recommendation"), res.get("council")),
            "facts": facts(v, owner),
            "rules": [{"id": k, **{f: res["rules"][k].get(f) for f in ("clause", "plain", "in_force", "amended_by", "source_url")}}
                      for k in v["rules"] + v["conditions"] if k in res["rules"]],
            "numbers": numbers,
            "usage": usage(v, owner),
            "lines": {k: t.get(k, "") for k in schema.LINES},
            "written_by": t.get("writer"), "checked_by": t.get("checked_by"),
            "uncertain": v["uncertain"],
        },
        "house_facts": house_facts(res, v),
        "owner": owner,
        "trace": {"events": len(events), "file": f"logs/trace-{rec['run_id']}.jsonl",
                  "timings": rec.get("timings") or {}, "fallbacks": rec.get("fallbacks") or [],
                  "agents": sorted({e.get("agent_name") for e in events if e.get("agent_name")}),
                  "zetaris_queries": sum(1 for e in events if e["type"] == "zetaris"),
                  "challenges": [e.get("text") for e in events if e["type"] == "challenge"],
                  "model_calls": [{k: e.get(k) for k in ("role", "ok", "routed_model", "receipt_id", "seconds")} for e in events if e["type"] == "model"]},
    }
