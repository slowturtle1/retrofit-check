"""One Retrofit Check run: from a house to checked answers, every step in the trace.

The agent decides as it goes: reuse the cache or fetch live, fall back when Zetaris cannot
reach planning.data, ask for heating when nobody told it, mark answers uncertain when the
LIDAR reading is noisy or an Article 4 is not on file, and send any explanation that fails
the critic back to the writer. The legal status itself always comes from rules.py.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from .. import facts as facts_mod
from .. import money, rules
from ..config import ROOT
from ..sources import osm
from ..zetaris import Zetaris
from . import evaluator, explain, llm, memory

RUNS = ROOT / "runs"
HEATING = ("gas", "oil", "lpg", "coal", "electric", "heat_pump")
Emit = Callable[[dict], None]

INTAKE = """A homeowner in England typed a note about their house. Pull out only what they actually said.
Reply with JSON only:
{"heating": one of "gas","oil","lpg","coal","electric","heat_pump" or null,
 "off_gas_grid": true, false or null,
 "walls_not_road": list of sides among "north","north east","east","south east","south","south west","west","north west" that they say are NOT a public road (for example a private drive), or [],
 "owns_whole_house": true, false or null}
Note: """


def _keyword_intake(note: str) -> dict:
    """Used when the model is unavailable; deliberately narrow."""
    n = note.lower()
    heating = next((h for h in ("oil", "lpg", "coal", "gas") if re.search(rf"\b{h}\b", n)), None)
    if "heat pump" in n:
        heating = "heat_pump"
    sides = [s for s in ("north east", "north west", "south east", "south west", "north", "south", "east", "west")
             if re.search(rf"\b{s}\b", n) and re.search(r"private|driveway|not a (public )?road", n)]
    return {"heating": heating, "off_gas_grid": True if re.search(r"no (mains )?gas|off (the )?gas", n) else None,
            "walls_not_road": sides[:1], "owns_whole_house": None}


class Run:
    def __init__(self, emit: Emit | None = None, use_model: bool = True, model_budget_s: float = 900):
        self.id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.events: list[dict] = []
        self._emit = emit
        self.use_model = use_model
        self.model_budget_s = model_budget_s
        self.started = time.time()
        self.z = Zetaris(on_query=lambda q: self.emit({"type": "zetaris", **q}))

    def emit(self, e: dict) -> None:
        e = {"t": round(time.time() - self.started, 2), **e}
        self.events.append(e)
        if self._emit:
            self._emit(e)

    def say(self, text: str, **kw) -> None:
        self.emit({"type": "thought", "text": text, **kw})

    def model_call(self, c: dict) -> None:
        self.emit({"type": "model", **c})

    # ------------------------------------------------------------------ steps

    def locate(self, way: int | None, lat: float | None, lon: float | None, label: str | None) -> dict:
        self.emit({"type": "tool_start", "tool": "find_house", "source": "OpenStreetMap API"})
        house = osm.house_from_way(way) if way else osm.building_at(lat, lon)
        if not house:
            self.emit({"type": "tool_end", "tool": "find_house", "ok": False, "error": "no building at that point"})
            raise LookupError("No building outline at that point. Tap the roof of the house.")
        house["label"] = label or house.get("street") or "Your house"
        self.emit({"type": "tool_end", "tool": "find_house", "ok": True, "house_id": house["house_id"], "footprint_m2": house["footprint_m2"]})
        self.emit({"type": "house", "house_id": house["house_id"], "label": house["label"], "lat": house["lat"], "lon": house["lon"], "coords": house["coords"]})
        return house

    def recall(self, house_id: str) -> dict:
        if not memory.available():
            self.say("H-MEM is not running, so nothing from earlier visits can be used.", level="warn")
            return {}
        mems = memory.recall(house_id)
        self.emit({"type": "memory_recall", "memories": mems})
        ctx: dict = {"memories": mems}
        for m in mems:
            kind, content = m.get("kind"), m["content"]
            if kind == "heating":
                ctx["heating"] = content.split(":", 1)[1].strip().split(",")[0].strip()
                ctx["heating_said_on"] = m["learnedAt"][:10]
                ctx["heating_memory"] = m["id"]
            elif kind == "off_gas_grid":
                ctx["off_gas_grid"] = content.endswith("yes")
            elif kind and kind.startswith("not_road"):
                ctx.setdefault("walls_not_road", []).append(content.split(":", 1)[1].strip())
                ctx["walls_said_on"] = m["learnedAt"][:10]
            elif kind == "gas_use":
                try:
                    ctx["gas_kwh"] = float(content.split(":", 1)[1].split()[0].replace(",", ""))
                    ctx["gas_said_on"] = m["learnedAt"][:10]
                except (IndexError, ValueError):
                    pass
            elif kind == "outcome":
                ctx["last_outcome"] = m
        if mems:
            self.say(f"I remember {len(mems)} thing(s) about this house from earlier.")
        return ctx

    def intake(self, house_id: str, note: str | None, heating: str | None, ctx: dict, gas_kwh: float | None = None) -> dict:
        today = date.today().isoformat()
        said: dict = {}
        if note:
            try:
                if not self.use_model:
                    raise llm.LLMError("model off")
                said = llm.chat_json([{"role": "user", "content": INTAKE + note}], "intake", self.model_call, max_tokens=2000)
            except llm.LLMError as e:
                said = _keyword_intake(note)
                self.say("The model did not answer, so I read your note with simple keyword rules instead.", level="warn", why=str(e)[:120])
            self.emit({"type": "intake", "note": note, "understood": said})
        if heating:
            said["heating"] = heating
        if said.get("heating") in HEATING and said["heating"] != ctx.get("heating"):
            r = memory.remember(house_id, "heating", f"Heating: {said['heating']}", "you told us") if memory.available() else None
            if r and r.get("superseded"):
                self.say(f"You told me before it was {ctx.get('heating')}; I now use {said['heating']} and keep the old note as history.")
            ctx["heating"], ctx["heating_said_on"] = said["heating"], today
            self.emit({"type": "memory_write", "kind": "heating", "content": said["heating"], "result": r})
        if gas_kwh and gas_kwh != ctx.get("gas_kwh"):
            r = memory.remember(house_id, "gas_use", f"Gas use: {int(gas_kwh)} kWh a year", "you told us") if memory.available() else None
            ctx["gas_kwh"], ctx["gas_said_on"] = float(gas_kwh), today
            self.emit({"type": "memory_write", "kind": "gas_use", "content": f"{int(gas_kwh)} kWh a year", "result": r})
        elif ctx.get("gas_kwh"):
            self.say(f"Using the gas use you gave me on {ctx['gas_said_on']}: {int(ctx['gas_kwh']):,} kWh a year. No need to ask again.")
        if said.get("off_gas_grid") is not None:
            ctx["off_gas_grid"] = bool(said["off_gas_grid"])
            if memory.available():
                memory.remember(house_id, "off_gas_grid", "Off the gas grid: " + ("yes" if ctx["off_gas_grid"] else "no"))
        for side in said.get("walls_not_road") or []:
            if side in rules.COMPASS and side not in ctx.get("walls_not_road", []):
                ctx.setdefault("walls_not_road", []).append(side)
                ctx["walls_said_on"] = today
                r = memory.remember(house_id, f"not_road_{side.replace(' ', '_')}", f"Not a public road: {side}") if memory.available() else None
                self.emit({"type": "memory_write", "kind": "not_road", "content": side, "result": r})
        return ctx

    def write_and_check(self, result: dict, v: dict) -> dict | None:
        """Nemotron rewrites the checked draft; the critic must accept it. Up to two rewrites."""
        draft = explain.template(result, v)
        feedback = None
        for round_no in (1, 2):
            if time.time() - self.started > self.model_budget_s:
                self.say(f"Out of time for the model on {v['measure']}; the checked draft stays.", level="warn")
                return None
            try:
                text = explain.rewrite(result, v, draft, self.model_call, feedback)
            except llm.LLMError as e:
                self.say(f"Nemotron did not answer for {v['measure']} ({str(e)[:60]}); the checked draft stays.", level="warn")
                return None
            problems = explain.check_rewrite(result, v, draft, text)
            if not problems:
                try:
                    problems = explain.critic(result, v, text, self.model_call)
                except llm.LLMError:
                    self.say(f"The critic model did not answer for {v['measure']}; code checks passed, so the rewrite is used and marked as code checked only.", level="warn")
                    text["checked_by"] = "code"
                    return text
            self.emit({"type": "critic", "measure": v["measure"], "round": round_no, "ok": not problems, "problems": problems})
            if not problems:
                text.setdefault("checked_by", "code and critic")
                return text
            feedback = problems
        self.say(f"The critic rejected both rewrites for {v['measure']}; the checked draft stays.", level="warn")
        return None

    # ------------------------------------------------------------------ main

    def check(self, way: int | None = None, lat: float | None = None, lon: float | None = None, label: str | None = None,
              note: str | None = None, heating: str | None = None, refresh: bool = False, gas_kwh: float | None = None) -> dict:
        self.emit({"type": "start", "run_id": self.id})
        house = self.locate(way, lat, lon, label)
        hid = house["house_id"]
        ctx = self.recall(hid)
        ctx = self.intake(hid, note, heating, ctx, gas_kwh)
        if not ctx.get("heating"):
            self.say("Nobody has told me how this house is heated, so the heat pump grant is shown as conditional.", ask="heating")

        got = facts_mod.gather(house, self.z, self.emit, refresh=refresh)
        self.say("Using the cached facts for this house." if got["cached"] else "Fetched live facts and cached them for Zetaris.")

        f = rules.load(self.z, hid)
        result = rules.evaluate(f, heating=ctx.get("heating"), off_gas_grid=ctx.get("off_gas_grid"),
                                walls_not_road=ctx.get("walls_not_road"), said_on=ctx.get("walls_said_on"))
        flags = evaluator.challenge(self.z, f, result, house["coords"], self.emit)
        for v in result["verdicts"]:
            v["uncertain"] += [x for x in flags if x not in v["uncertain"]]
        solar_v = next(v for v in result["verdicts"] if v["measure"] == "solar")
        if solar_v["numbers"].get("kwp") and solar_v["status"].startswith("allowed"):
            evaluator.cost_sources(self.z, float(solar_v["numbers"]["kwp"]), self.emit)
        prices = {k: float(r["value"]) for k, r in f["prices"].items()}
        result["money"] = money.advise(result, prices, ctx.get("gas_kwh"), ctx.get("heating"))
        result["prices"] = f["prices"]
        result["owner"] = {k: ctx.get(k) for k in ("heating", "heating_said_on", "gas_kwh", "gas_said_on", "off_gas_grid")}
        result["house"]["label"] = house["label"]
        result["house"]["coords"] = house["coords"]
        result["walls"] = f["walls"]
        result["planes"] = f["planes"]
        for fact in result["verdicts"][0]["facts"]:
            if fact["fact"] == "sources disagree":
                self.emit({"type": "decision", "branch": "sources_disagree", "text": fact["value"], "source": fact["source"]})
        warned = set()
        for v in result["verdicts"]:
            for u in v["uncertain"]:
                if u in warned:
                    continue
                warned.add(u)
                self.say(UNCERTAIN.get(u, u), level="warn", measure=v["measure"])

        answers = {v["measure"]: {**explain.template(result, v), "writer": "code"} for v in result["verdicts"]}
        self.emit({"type": "answer", "result": _public(result), "texts": answers})

        if self.use_model:
            with ThreadPoolExecutor(1) as pool:  # one at a time: parallel calls queue at the provider anyway
                for v, text in zip(result["verdicts"], pool.map(lambda v: self.write_and_check(result, v), result["verdicts"])):
                    if text:
                        answers[v["measure"]] = {**answers[v["measure"]], "why": text["why"],
                                                 "writer": "nemotron", "checked_by": text.get("checked_by")}
                        self.emit({"type": "answer_update", "measure": v["measure"], "text": answers[v["measure"]]})

        summary = "; ".join(f"{explain.MEASURE_NAME[v['measure']]}: {v['headline']}" for v in result["verdicts"])
        if memory.available():
            memory.remember(hid, "outcome", f"Last check {date.today().isoformat()}: {summary}", "the agent's last check")
        record = {"run_id": self.id, "house_id": hid, "label": house["label"], "context": {k: v for k, v in ctx.items() if k != "memories"},
                  "result": _public(result), "texts": answers, "events": self.events, "seconds": round(time.time() - self.started, 1)}
        RUNS.mkdir(exist_ok=True)
        (RUNS / f"{self.id}-{hid}.json").write_text(json.dumps(record, indent=1, default=str))
        self.emit({"type": "done", "run_id": self.id, "seconds": record["seconds"], "summary": summary})
        return record


UNCERTAIN = {
    "lidar_noisy": "More than a quarter of the roof reading is trees or chimneys, so the roof numbers are rough.",
    "no_sunny_roof": "No roof plane faces between east and west, so solar would make little.",
    "article4_unknown": "An Article 4 direction covers this house and its contents are not on file: I will not guess.",
    "article4_ended_but_listed": "An Article 4 direction here has ended but still shows on planning.data.",
    "lane_may_not_be_highway": "One wall faces a lane that OpenStreetMap marks as a service road. I treat it as a road to be safe; tell me if it is a private drive.",
    "heating_unknown": "I do not know how the house is heated, so the grant depends on that.",
    "bus_needs_fossil_heating": "The Boiler Upgrade Scheme only helps if the heat pump replaces gas, oil, LPG or coal heating.",
    "no_wall_away_from_road": "Every wall faces a road, so a heat pump here needs planning permission.",
    "article4_coverage_unknown": "This council has not published Article 4 directions for conservation areas, so a missing record proves nothing. Ask the council.",
    "listed_point_only": "The listing was found as a point, not an outline. Check with the council or Historic England's map.",
}


def _public(result: dict) -> dict:
    keep = {k: result[k] for k in ("house", "protected", "areas", "listed", "verdicts", "today", "walls", "planes", "money", "prices", "owner") if k in result}
    used = {i for v in result["verdicts"] for i in v["rules"] + v["conditions"] + v["alternatives"] + v["grants"]}
    keep["rules"] = {k: r for k, r in result["rules"].items() if k in used}
    keep["grants"] = {k: g for k, g in result["grants"].items() if k in used}
    return keep
