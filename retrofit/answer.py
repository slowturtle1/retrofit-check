"""The answer JSON (contract in schema.py) for one check, built from the verdict, the money and the texts.

Solar only in this version: heat pump and wall verdicts are still computed by rules.py, but not shown.
"""

from __future__ import annotations

from . import schema

GENERAL_LIMITS = [
    "Rules for England, demo data for London.",
    "Map drawings are indicative.",
    "Roof size and yield come from 1 m LIDAR and PVGIS: an installer's survey confirms them.",
    "Not legal or financial advice.",
]

LDC = "If you want it in writing, apply to the council for a lawful development certificate."

NEXT = {
    "needs_consent": "Talk to the council's conservation officer before you plan anything.",
    "needs_permission": "Ask the council about a planning application before you plan anything.",
    "check_with_council": "Ask the council which permitted development rights the Article 4 direction removes.",
}
NEXT_BY_RECOMMENDATION = {
    "Worth getting quotes": "Get quotes from two or three MCS certified installers.",
    "Ask the council first": "Ask the council's planning team before you get quotes.",
    "Probably not worth it for this house": "Ask one MCS certified installer to look at the roof only if you still want panels.",
}


def next_step(v: dict, recommendation: str | None) -> str:
    step = NEXT.get(v["status"]) or NEXT_BY_RECOMMENDATION.get(recommendation or "", "Ask the council's planning team.")
    return f"{step} {LDC}" if v["status"].startswith("allowed") else step


def limitations(v: dict, prices: dict, uncertain_text: dict) -> list[str]:
    out = [uncertain_text.get(u, u) for u in v["uncertain"]]
    if any(str(p.get("kind")) == "assumption" for k, p in prices.items() if k.startswith("self_use")):
        out.append("How much of the electricity you use at home is an estimate (a quarter to a half without a battery).")
    return out + GENERAL_LIMITS


def facts(v: dict, owner: dict) -> list[dict]:
    out = [{**f, "date": f.get("date")} for f in v["facts"]]
    if owner.get("elec_kwh"):
        out.append({"fact": "your electricity use", "value": f"{int(owner['elec_kwh']):,} kWh a year", "source": "you told us", "date": owner.get("elec_said_on")})
    return out


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
    def fact(key, label, value, source, date=None, from_owner=False):
        return {"key": key, "label": label, "value": value, "source": source, "date": date, "from_owner": from_owner}
    return [
        fact("listed", "Listed", ", ".join(f"Grade {a['grade']} listed" if a.get("grade") else "Listed" for a in listed[:1]) or "Not listed", "Historic England, via planning.data"),
        fact("conservation_area", "Conservation area", ", ".join(f"{a['name']} ({a['start_date'][:4]})" if a.get("start_date") else a["name"] for a in ca) or "None", "planning.data"),
        fact("article_4", "Article 4", "; ".join(f["value"].split(":")[0] for f in a4) or "None on file", "planning.data and the council"),
        fact("road_walls", "Walls facing a road", ", ".join(dict.fromkeys(f"{compass(w['facing_deg'])} to {w['highway_name']}" for w in roads)) or "None", "OpenStreetMap"),
        fact("roof", "Roof direction and slope", f"{best['facing']} slope, {best['pitch_deg']}°, about {best['area_m2']} m²" if best else "Not measured", "Environment Agency LIDAR"),
        fact("sun", "Sun on the roof", f"about {n['kwh_year']:,} kWh a year from {n['kwp']} kWp" if n.get("kwh_year") else "Not estimated", "PVGIS, EU Joint Research Centre"),
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
    return {
        "schema": schema.VERSION,
        "trace_id": rec["run_id"], "run_id": rec["run_id"], "mode": mode, "seconds": rec.get("seconds"),
        "question": schema.QUESTION,
        "house": {k: res["house"].get(k) for k in ("house_id", "label", "lat", "lon", "building", "footprint_m2", "source")},
        "solar": {
            "status": v["status"], "status_text": v["headline"], "recommendation": m.get("recommendation"),
            "confidence": schema.confidence(v),
            "limitations": limitations(v, res.get("prices") or {}, uncertain_text),
            "next_step": next_step(v, m.get("recommendation")),
            "facts": facts(v, owner),
            "rules": [{"id": k, **{f: res["rules"][k].get(f) for f in ("clause", "plain", "in_force", "amended_by", "source_url")}}
                      for k in v["rules"] + v["conditions"] if k in res["rules"]],
            "numbers": numbers,
            "lines": {k: t.get(k, "") for k in schema.LINES},
            "written_by": t.get("writer"), "checked_by": t.get("checked_by"),
            "uncertain": v["uncertain"],
        },
        "house_facts": house_facts(res, v),
        "owner": owner,
        "trace": {"events": len(events), "file": f"logs/trace-{rec['run_id']}.jsonl",
                  "agents": sorted({e.get("agent_name") for e in events if e.get("agent_name")}),
                  "zetaris_queries": sum(1 for e in events if e["type"] == "zetaris"),
                  "challenges": [e.get("text") for e in events if e["type"] == "challenge"],
                  "model_calls": [{k: e.get(k) for k in ("role", "ok", "routed_model", "receipt_id", "seconds")} for e in events if e["type"] == "model"]},
    }
