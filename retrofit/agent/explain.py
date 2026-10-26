"""Turning verdicts into plain words, and checking those words before anyone sees them.

template(): deterministic text from the verdict alone. Always correct, used as the fallback
            and in sample mode.
write():    Nemotron writes the same fields in plain words, citing rule ids in [brackets].
critique(): code checks every number, status word and citation against the evidence, then
            Nemotron reads it as a sceptical planning officer. Failures go back to the writer.
"""

from __future__ import annotations

import json
import re
from datetime import date

from . import llm
from ..rules import compass

MEASURE_NAME = {"solar": "Solar panels", "heat_pump": "Heat pump", "wall_insulation": "Outside wall insulation"}
FIELDS = ("one", "why", "get", "cost")


def _d(iso: str | None) -> str:
    if not iso:
        return "unknown date"
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%-d %b %Y")
    except ValueError:
        return str(iso)


def _money(n) -> str:
    return f"£{int(n):,}"


def evidence(result: dict, v: dict) -> dict:
    """Everything the text for one verdict may rely on."""
    ids = set(v["rules"]) | set(v["conditions"]) | set(v["alternatives"]) | set(v["grants"])
    rules = {k: r for k, r in result["rules"].items() if k in ids}
    grants = {k: g for k, g in result["grants"].items() if k in ids}
    return {"measure": v["measure"], "status": v["status"], "headline": v["headline"], "facts": v["facts"],
            "numbers": v["numbers"], "where": v["where"], "uncertain": v["uncertain"],
            "rules": {k: {"clause": r["clause"], "plain": r["plain"], "in_force": r["in_force"], "amended_by": r["amended_by"]} for k, r in rules.items()},
            "grants": {k: {"plain": g["plain"], "amount_gbp": g["amount_gbp"], "valid_to": g["valid_to"]} for k, g in grants.items()}}


def evidence_text(result: dict, v: dict) -> str:
    """The same evidence as a short tagged list: small prompts keep Nemotron's thinking under Nightshift's time limit."""
    ev = evidence(result, v)
    lines = [f"Measure: {MEASURE_NAME[v['measure']]}", f"Status (decided, do not change): {v['headline']}", "Evidence:"]
    for f in v["facts"]:
        value = f["value"] if f["fact"] != "article-4" else f["value"].split(":")[0] + (": does not touch energy upgrades" if "basement" in f["value"].lower() or "launderette" in f["value"].lower() or "to residential" in f["value"].lower() or "to c3" in f["value"].lower() else "")
        lines.append(f"[fact:{f['fact']}] {value}")
    for k, r in ev["rules"].items():
        lines.append(f"[{k}] {r['plain']} ({r['clause']})")
    for k, g in ev["grants"].items():
        lines.append(f"[{k}] {g['plain']}")
    if v["numbers"]:
        lines.append("Numbers: " + ", ".join(f"{k} {val}" for k, val in v["numbers"].items()))
    lines.append("Uncertain: " + (", ".join(v["uncertain"]) or "nothing"))
    return "\n".join(lines)


def _true(x) -> bool:
    return str(x).lower() in ("true", "t", "1")


def _gbp(pair) -> str:
    return f"£{int(pair[0]):,} to £{int(pair[1]):,}"


def solar_lines(result: dict, v: dict) -> dict:
    return {k: t[:1].upper() + t[1:] for k, t in _solar_lines(result, v).items()}


def _solar_lines(result: dict, v: dict) -> dict:
    """The solar card, built from this house's facts: its name, listing, area, roads, roof, numbers and council.
    General law stays in the rules list (Sources) with its link; each line here applies it to this house."""
    n, m = v["numbers"] or {}, (result.get("money") or {}).get("solar") or {}
    label = "This house"
    council = result.get("council") or "the council"
    areas = result.get("areas") or []
    ca = next((a for a in areas if a["dataset"] == "conservation-area"), None)
    ca_name = f"{ca['name']} Conservation Area" + (f" ({ca['start_date'][:4]})" if ca.get("start_date") else "") if ca else None
    roads = list(dict.fromkeys(f"{compass(w['facing_deg'])} wall faces {w['highway_name']}" for w in result.get("walls") or []
                               if _true(w.get("fronts_highway")) and w.get("highway_name")))
    planes = result.get("planes") or []
    best = next((p for p in planes if p["facing"] == n.get("facing")), None)
    side = compass_name(n.get("facing"))
    slope = f"{side} roof slope" + (f" ({best['pitch_deg']}°)" if best else "")
    noise = (result.get("survey") or {}).get("noise_pct")
    a4 = [re.sub(r", from \d{4}-\d{2}-\d{2}\)", ")", f["value"]) for f in v["facts"] if f["fact"] == "article-4"]
    disagree = next((f["value"] for f in v["facts"] if f["fact"] == "sources disagree"), None)
    if disagree and (d := re.search(r"lists (\S+) with no end date; the council ended it on (\d{4}-\d{2}-\d{2})", disagree)):
        disagree = f"planning.data still lists Article 4 {d.group(1)}, but {council} ended it on {_d(d.group(2))}, so we follow {council}."
    unsure = set(v["uncertain"])

    if v["status"] == "needs_consent" and "listed_point_only" not in unsure:
        listing = next((a for a in areas if a["dataset"].startswith("listed")), {})
        grade = f"Grade {listing['grade']} listed" if listing.get("grade") else "Listed"
        since = f" since {_d(listing.get('start_date'))}" if listing.get("start_date") else ""
        entry = f" (list entry {listing['reference']})" if listing.get("reference") else ""
        kind = grade.replace(" listed", "") if listing.get("grade") else "listed"
        return {"one": f"{grade}{since}: panels need listed building consent first.",
                "why": (f"{label} has been {grade}{since}" if since else f"{label} is {grade}") + f", so panels are not permitted development here and {council} decides. "
                       "The roof was not measured, because consent comes first.",
                "get": f"Ask {council}'s conservation officer whether panels on a roof slope hidden from the street could get consent for this house{entry}.",
                "cost": f"No cost estimate until {council} gives listed building consent ({kind}{since}). Listed building consent is free to apply for."}
    where = v.get("where") or {}
    if v["status"] == "needs_permission":
        ref = (where.get("a4_solar") or ["An Article 4 direction"])[0]
        return {"one": f"{ref} removes the right to add panels here: you need planning permission.",
                "why": f"{label} is covered by {ref}, which takes away permitted development for solar panels, so {council} must approve them.",
                "get": f"Your {slope} could make about {n['kwh_year']:,} kWh a year if {council} approves." if n else f"Ask {council} before you plan panels.",
                "cost": f"A householder application to {council} costs £548. Cost of the panels is shown once permission is likely." }
    if v["status"] == "check_with_council" or unsure & {"article4_unknown", "article4_coverage_unknown", "listed_point_only", "listed_he_only"}:  # consent and permission returned above
        if "listed_he_only" in unsure:
            one, why = ("Historic England's map shows a listed outline over this house that planning.data does not, so panels may need listed building consent.",
                        f"If the house is listed, panels are not permitted development and {council} decides. "
                        "If the outline belongs to a building next door, panels on this roof are likely permitted development.")
        elif "article4_unknown" in unsure or v["status"] == "check_with_council":
            ref = (where.get("a4_unknown") or ["An Article 4 direction"])[0]
            one, why = (f"{ref} covers this house and we do not know what it removes.",
                        f"{council} has not published what {ref} takes away, so we will not guess whether panels need permission.")
        elif "article4_coverage_unknown" in unsure and not result.get("council"):
            one = f"We could not tell which council keeps the Article 4 record for {ca_name or 'this area'}, so we cannot rule one out."
            why = (f"No listing is on record for this house, and it sits in {ca_name}. " if ca_name else "No listing is on record for this house. ") + \
                  f"Panels on the {slope} would be permitted development unless an Article 4 direction removes that right."
        elif "article4_coverage_unknown" in unsure:
            one = f"{council} has not published Article 4 directions for {ca_name or 'its conservation areas'}, so we cannot rule one out."
            why = (f"No listing is on record for this house, and it sits in {ca_name}. " if ca_name else "No listing is on record for this house. ") + \
                  f"Panels on the {slope} would be permitted development unless an Article 4 direction removes that right, and {council} keeps that record itself."
        else:
            one, why = ("The listing near this house was found as a point only, so it may belong to the building next door.",
                        "If the house is listed, panels need listed building consent; if it is not, they are likely permitted development.")
        get = (f"Your {slope} could make about {n['kwh_year']:,} kWh a year from about {n['kwp']} kWp if {council} says yes." if n else
               f"No roof slope here faces between east and west, so panels would make little even if {council} says yes." if "no_sunny_roof" in unsure else
               f"Ask {council} first; the roof was not measured.")
        cost = (f"If {council} says yes: about {_gbp(m['cost'])} to install {n['kwp']} kWp, worth about {_gbp(m['value_year'])} a year."
                if m.get("cost") else f"Cost is shown once {council} confirms.")
        return {"one": one, "why": why, "get": get, "cost": cost}

    # Allowed under permitted development
    if not n:
        return {"one": f"Allowed, but no roof slope at {label} faces between east and west.",
                "why": "No listing is on record for this house" + (f", and it sits in {ca_name}" if ca_name else "") + ". Panels are allowed, but a roof facing north makes little.",
                "get": "Little direct sun on this roof.", "cost": f"No cost estimate for {label}: the roof gets too little sun."}
    one = f"Your {slope} has room for about {n['kwp']} kWp, about {n['kwh_year']:,} kWh a year."
    why = ["No listing is on record for this house" + (f", and it sits in {ca_name}." if ca_name else ", and it is not in a conservation area.")]
    if ca_name and roads:
        why.append(f"In a conservation area panels cannot go on a wall that faces a road: your {' and your '.join(roads)}. Roof slopes are fine, so the {side} slope can take them.")
    elif ca_name:
        why.append(f"In a conservation area panels cannot go on a wall that faces a road; roof slopes are fine, so the {side} slope can take them.")
    else:
        why.append(f"Panels on the {slope} are permitted development if they stay within 20 cm of the roof and below the ridge.")
    if disagree:
        why.append(disagree)
    elif a4 and ca_name:
        refs = "; ".join(re.sub(r"^(.*?) \((\S+?)\)$", lambda g: f"{g.group(1).lower()}, {g.group(2)}", x.split(":")[0]) for x in a4)
        why.append(f"The Article 4 direction on file here ({refs}) does not cover solar panels." if len(a4) == 1 else
                   f"The Article 4 directions on file here ({refs}) do not cover solar panels.")
    if "lidar_noisy" in unsure and noise is not None:
        why.append(f"The roof reading is rough ({noise}% of it is trees or chimneys), so an installer should measure it.")
    get = f"About {n['kwp']} kWp on the {side} slope, about {n['kwh_year']:,} kWh a year."
    su = m.get("self_use") or {}
    use = (f" for the {su['use_kwh']:,} kWh a year you use" if su.get("by_owner") else
           f" for a home using {su['use_kwh']:,} kWh a year (Ofgem's typical figure)" if su.get("use_kwh") else "")
    if m.get("payback_years"):
        cost = (f"For {n['kwp']} kWp: about {_gbp(m['cost'])} to install, worth about {_gbp(m['value_year'])} a year{use}, "
                f"so about {m['payback_years'][0]} to {m['payback_years'][1]} years to pay back. No VAT on panels until 31 Mar 2027.")
    elif m.get("cost"):
        cost = f"For {n['kwp']} kWp: about {_gbp(m['cost'])} to install. {m.get('why') or ''}".strip()
    else:
        cost = "No VAT on panels until 31 Mar 2027."
    return {"one": one, "why": " ".join(why), "get": get, "cost": cost}


def template(result: dict, v: dict) -> dict:
    if v["measure"] == "solar":
        return {**solar_lines(result, v), "writer": "template"}
    ev = evidence(result, v)
    area = " and ".join(a if "conservation area" in a.lower() or v["measure"] == "" else a + " Conservation Area" for a in result["protected"]) if result["protected"] else ""
    rules, grants, n = ev["rules"], ev["grants"], v["numbers"]
    cost = " ".join(g["plain"] for g in grants.values()) or "No grant found for this."
    m = v["measure"]
    if v["status"] == "needs_consent":
        listing = next((a for a in result.get("areas", []) if a["dataset"] == "listed-building"), None) or next((a for a in result.get("areas", []) if a["dataset"].startswith("listed")), {})
        grade = f"Grade {listing['grade']} listed" if listing.get("grade") else "Listed"
        since = f" since {_d(listing.get('start_date'))}" if listing.get("start_date") else ""
        what = {"solar": "Panels", "heat_pump": "A heat pump", "wall_insulation": "Outside wall insulation"}[m]
        one = f"{grade}{since}: {what.lower() if m != 'solar' else 'panels'} need listed building consent first." if m == "solar" else f"{grade}{since}: {what[0].lower() + what[1:]} needs listed building consent first."
        why = " ".join(r["plain"] for r in rules.values())
        get = "Talk to the council's conservation officer before you plan anything. Consent is free to apply for, and the council looks at how it changes the building."
    elif v["status"] == "check_with_council":
        one = "An Article 4 direction covers this house and we do not know what it removes."
        why = "Ask the council which permitted development rights it removes before you start."
        get = "We will not guess."
    elif m == "solar":
        one = f"Your {compass_name(n.get('facing'))} roof could make about {n['kwh_year']:,} kWh a year." if n else "Allowed, but your roof gets little direct sun."
        why = (f"Not listed{', and inside ' + area if area else ''}. " + " ".join(rules[k]["plain"] for k in v["conditions"] if k in rules)).strip()
        get = f"About {n['kwp']} kWp on the {compass_name(n.get('facing'))} slope: {n['kwh_year']:,} kWh a year." if n else "Little sun on this roof."
    elif m == "heat_pump":
        ok = ", ".join(sorted(set(v["where"].get("ok_walls", [])))) or "none"
        one = f"Allowed on a wall away from the road ({ok} side)." if v["status"] != "needs_permission" else "Every outside wall faces a road, so this needs planning permission."
        why = " ".join(rules[k]["plain"] for k in v["conditions"] if k in rules)
        get = f"Up to {n['units_allowed']} outdoor unit{'s' if n['units_allowed'] > 1 else ''}. Your installer sizes it with a heat loss survey."
    else:  # wall insulation
        if v["status"] == "needs_permission":
            one = f"Inside {area}, cladding the outside walls needs planning permission." if area else "Cladding the outside walls needs planning permission here."
            why = " ".join(rules[k]["plain"] for k in v["rules"] if k in rules)
            get = " ".join(rules[k]["plain"] if k in rules else grants[k]["plain"] for k in v["alternatives"] if k in rules or k in grants)
        else:
            one = "Allowed if the new finish looks like your walls do now."
            why = " ".join(rules[k]["plain"] for k in v["conditions"] if k in rules)
            get = "How much you save depends on your walls; an installer measures this."
    return {"one": one, "why": why, "get": get, "cost": cost, "writer": "template"}


def compass_name(facing: str | None) -> str:
    return {"N": "north", "NE": "north east", "E": "east", "SE": "south east", "S": "south", "SW": "south west", "W": "west", "NW": "north west"}.get(facing or "", "best")


WRITER = """You explain home energy rules to a homeowner in England, in plain British English.
You get one verdict and its evidence as a tagged list. The status is decided; never change it or soften it.
Write four short fields, each one or two sentences, no jargon, no legal Latin:
  one:  the answer in one line a homeowner understands
  why:  why, naming the place (for example the conservation area) and the rule
  get:  what they get or what they can do instead
  cost: help with cost, only from the grants given
Rules:
- Every sentence that states a rule or a fact ends with the evidence id in square brackets, for example [ewi-art23] or [fact:conservation-area]. Use only ids that appear in the evidence: rule ids, grant ids, or fact:<fact name>.
- Use only numbers, dates and amounts that appear in the evidence. Round nothing.
- If "uncertain" is not empty, say so plainly in "why".
Reply with JSON only: {"one": "...", "why": "...", "get": "...", "cost": "..."}"""

CRITIC = """You are a sceptical planning officer checking an explanation written for a homeowner.
You get the evidence (a tagged list) and the text. List every claim in the text that the evidence does not support,
every place where the text contradicts the status, and anything that would mislead a homeowner.
Do not complain about style. Reply with JSON only: {"ok": true|false, "problems": ["..."]}"""


def write(result: dict, v: dict, on_call, feedback: list[str] | None = None) -> dict:
    msgs = [{"role": "system", "content": WRITER}, {"role": "user", "content": evidence_text(result, v)}]
    if feedback:
        msgs.append({"role": "user", "content": "A reviewer rejected your last draft for these reasons. Fix them:\n- " + "\n- ".join(feedback)})
    out = llm.chat_json(msgs, f"writer:{v['measure']}", on_call)
    return {k: str(out.get(k, "")).strip() for k in FIELDS} | {"writer": "nemotron"}


NUM = re.compile(r"(?<![\w.])£?\d[\d,]*(?:\.\d+)?")
CITE = re.compile(r"\[([^\]]+)\]")


def allowed_numbers(result: dict, v: dict) -> set[str]:
    blob = json.dumps(evidence(result, v), default=str)
    found = {m.replace(",", "").lstrip("£") for m in NUM.findall(blob)}
    for iso in re.findall(r"\d{4}-\d{2}-\d{2}", blob):
        d = date.fromisoformat(iso)
        found |= {str(d.day), str(d.year)}
    return found | {"1", "2"}


def check(result: dict, v: dict, text: dict) -> list[str]:
    """Code checks; no model involved."""
    problems = []
    ev = evidence(result, v)
    ids = set(ev["rules"]) | set(ev["grants"]) | {"fact:" + f["fact"] for f in v["facts"]}
    nums = allowed_numbers(result, v)
    body = " ".join(text.get(k, "") for k in FIELDS)
    for k in FIELDS:
        if not text.get(k):
            problems.append(f"field {k} is empty")
    for c in CITE.findall(body):
        for one in re.split(r"\s*,\s*", c):
            if one and one not in ids:
                problems.append(f"cites [{one}], which is not in the evidence")
    for raw in NUM.findall(CITE.sub("", body)):
        n = raw.replace(",", "").lstrip("£")
        if n not in nums:
            problems.append(f"number {raw} does not appear in the evidence")
    low = CITE.sub("", text.get("one", "")).lower()
    if v["status"] in ("needs_permission", "needs_consent") and ("permission" not in low and "consent" not in low):
        problems.append("the one line answer does not say that permission or consent is needed")
    if v["status"] in ("allowed", "allowed_with_conditions") and re.search(r"\b(not allowed|needs (planning )?permission|forbidden)\b", low):
        problems.append("the one line answer contradicts an allowed status")
    if not CITE.search(text.get("why", "")):
        problems.append("why has no citation")
    return problems


def critique(result: dict, v: dict, text: dict, on_call) -> list[str]:
    problems = check(result, v, text)
    if problems:
        return problems
    out = llm.chat_json([{"role": "system", "content": CRITIC},
                         {"role": "user", "content": evidence_text(result, v) + "\n\nText to check:\n" + json.dumps(text, ensure_ascii=False)}],
                        f"critic:{v['measure']}", on_call)
    return [] if out.get("ok") else [str(p) for p in out.get("problems", [])][:5] or ["critic said not ok without reasons"]


def strip_citations(text: dict) -> dict:
    return {k: (re.sub(r"\s*\[[^\]]+\]", "", v).strip() if k in FIELDS else v) for k, v in text.items()}


# --- The live path: Nemotron rewrites the checked draft in plain words; code and a critic check it. ---
# (write/critique above ask the model to cite evidence itself; on Nightshift's 45 s budget that task
# makes Nemotron think too long, so the live run uses this smaller task.)

REWRITE = ("Say this more simply for a homeowner, in at most two sentences, keeping every fact, number, date, "
           "place name and condition. Add nothing new and no legal clause numbers. Reply with the sentences only: ")

CRITIC_REWRITE = ("Compare A and B. Does B keep every fact, number, date, place and condition of A, and add nothing? "
                  "Answer YES, or NO followed by the problem in one line.")


def rewrite(result: dict, v: dict, draft: dict, on_call, feedback: list[str] | None = None) -> dict:
    """Plain text, one field: a small task keeps Nemotron's thinking short enough for Nightshift."""
    body = REWRITE + draft["why"]
    if feedback:
        body += "\nA reviewer said: " + " ".join(feedback) + " Fix that."
    out = llm.chat([{"role": "user", "content": body}], f"writer:{v['measure']}", on_call, max_tokens=4000)
    out = out.strip().strip('"').strip()
    return {"one": draft["one"], "why": out}


def _nums(text: str) -> set[str]:
    return {m.replace(",", "").lstrip("£") for m in NUM.findall(text)}


def check_rewrite(result: dict, v: dict, draft: dict, text: dict) -> list[str]:
    """Code checks on a rewrite, no model involved."""
    problems = []
    for k in ("one", "why"):
        if not text.get(k):
            problems.append(f"'{k}' is empty")
    src = draft["one"] + " " + draft["why"]
    out = text.get("one", "") + " " + text.get("why", "")
    extra = _nums(out) - _nums(src) - allowed_numbers(result, v)
    if extra:
        problems.append("numbers not in the evidence: " + ", ".join(sorted(extra)))
    for place in result.get("protected", []):
        if place.lower() in src.lower() and place.lower() not in out.lower():
            problems.append(f"dropped the place name {place}")
    # Judge each field against the checked draft and the status the card shows: only what the rewrite changed can be wrong.
    from ..schema import open_flags
    shown = "check_with_council" if open_flags(v) else v["status"]
    refusal = r"\b(not allowed|needs? (planning )?permission|forbidden|cannot have)\b"
    for k in ("one", "why"):
        low, src_low = text.get(k, "").lower(), draft.get(k, "").lower()
        for word in ("permission", "consent"):
            if word in src_low and word not in low:
                problems.append(f"'{k}' no longer says {word} is needed")
        if shown in ("allowed", "allowed_with_conditions") and re.search(refusal, low) and not re.search(refusal, src_low):
            problems.append(f"'{k}' now contradicts an allowed status")
    if len(out) > 2 * len(src) + 80:
        problems.append("much longer than the original")
    return problems


def critic(result: dict, v: dict, text: dict, on_call) -> list[str]:
    draft = template(result, v)
    out = llm.chat([{"role": "user", "content": f"{CRITIC_REWRITE}\nA: {draft['why']}\nB: {text['why']}"}], f"critic:{v['measure']}", on_call, max_tokens=4000)
    head = out.strip().upper()
    if head.startswith("YES"):
        return []
    return [out.strip()[2:].strip(" :.-") or "critic said NO without a reason"] if head.startswith("NO") else [f"critic gave no clear YES or NO: {out[:120]}"]
