"""Step 2 of the evaluation: run three systems on the frozen cases and score them.

Systems
  retrofit-check    the agent as shipped (rules + evaluator), live: Zetaris, planning.data, OSM, LIDAR
  no-evaluator      the same rules on the same planning.data facts, but trusting planning.data as it is:
                    no council decisions on Article 4 end dates, no evaluator challenges
  nemotron-alone    Nemotron through Nightshift, given only the street, postcode district and borough

A status is scored by route: allowed (with or without conditions) / permission / consent.
"check with your council" counts as deferred: not right, not wrong.
Confidently wrong = wrong and no uncertainty flag on that answer.

Run: .venv/bin/python eval/run.py [--systems retrofit-check,no-evaluator,nemotron-alone]
"""

import argparse
import copy
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrofit import rules  # noqa: E402
from retrofit.agent import llm  # noqa: E402
from retrofit.agent.evaluator import challenge  # noqa: E402
from retrofit.agent.run import Run  # noqa: E402
from retrofit.zetaris import Zetaris  # noqa: E402

HERE = Path(__file__).parent
MEASURES = ("solar", "heat_pump", "wall_insulation")
ROUTE = {"allowed": "allowed", "allowed_with_conditions": "allowed", "needs_permission": "permission",
         "needs_consent": "consent", "check_with_council": "council"}
COUNCIL_FLAGS = {"article4_coverage_unknown", "article4_unknown"}

PROMPT = ("A homeowner owns a house on {street}, London {district} ({borough}). In England, for each of: solar panels on the roof, "
          "an air source heat pump, and external wall insulation, is it allowed under permitted development, does it need planning "
          "permission, or does it need listed building consent? Reply with exactly three lines and nothing else:\n"
          "solar=allowed|permission|consent\nheat_pump=allowed|permission|consent\nwalls=allowed|permission|consent")


def load_cases() -> list[dict]:
    d = json.loads((HERE / "cases.json").read_text())
    body = json.dumps(d["cases"], indent=1, sort_keys=True)
    if hashlib.sha256(body.encode()).hexdigest() != d["sha256"]:
        sys.exit("cases.json was changed after it was frozen")
    return d["cases"]


def from_result(result: dict) -> dict:
    out = {}
    for v in result["verdicts"]:
        out[v["measure"]] = {"route": ROUTE[v["status"]], "flags": sorted(v["uncertain"])}
    return out


def run_agent(case: dict) -> dict:
    r = Run(use_model=False).check(way=case["way"], lat=None if case["way"] else case["lat"], lon=None if case["way"] else case["lon"], label=case["note"])
    return from_result(r["result"])


def run_no_evaluator(case: dict) -> dict:
    """Same rules, same Zetaris facts, but planning.data taken at face value and no challenges."""
    z = Zetaris()
    f = rules.load(z, case["id"])
    f = copy.deepcopy(f)
    for d in f["designations"]:
        if d["dataset"] == "article-4-direction-area":
            d["a4_end_date"] = d.get("end_date") or None     # ignore the council's own end date
    return from_result(rules.evaluate(f, heating="gas"))


def ask_streets(case: dict) -> dict:
    import requests
    r = requests.get("https://nominatim.openstreetmap.org/reverse", params={"lat": case["lat"], "lon": case["lon"], "format": "jsonv2", "zoom": 17},
                     headers={"User-Agent": "retrofit-check-hackathon/0.1 (evaluation)"}, timeout=30)
    a = r.json().get("address", {}) if r.ok else {}
    time.sleep(1.1)
    return {"street": case.get("street") or a.get("road") or "a residential street", "district": (a.get("postcode") or "").split(" ")[0],
            "borough": a.get("city_district") or a.get("borough") or a.get("suburb") or ""}


def run_nemotron(case: dict) -> dict:
    where = ask_streets(case)
    text = llm.chat([{"role": "user", "content": PROMPT.format(**where)}], "eval:nemotron-alone", max_tokens=4000, retries=2)
    out = {}
    for m, key in (("solar", "solar"), ("heat_pump", "heat_pump"), ("wall_insulation", "walls")):
        hit = re.search(rf"{key}\s*=\s*(allowed|permission|consent)", text, re.I)
        out[m] = {"route": hit.group(1).lower() if hit else "no answer", "flags": []}
    out["_asked"] = where
    return out


def score(cases: list[dict], answers: dict) -> dict:
    s = {"right": 0, "wrong": 0, "deferred": 0, "confidently_wrong": 0, "flag_expected": 0, "flag_raised": 0, "per_case": []}
    for c in cases:
        a = answers.get(c["id"])
        row = {"id": c["id"], "group": c["group"]}
        if not a or "error" in a:
            row["error"] = (a or {}).get("error", "not run")
            s["per_case"].append(row)
            s["wrong"] += 3
            continue
        for m in MEASURES:
            got, want = a[m]["route"], c["expected"][m]
            row[m] = f"{got} (want {want})"
            if got == "council":
                s["deferred"] += 1
            elif got == want:
                s["right"] += 1
            else:
                s["wrong"] += 1
                if not a[m]["flags"]:
                    s["confidently_wrong"] += 1
        if c["expected"]["flag_council"]:
            s["flag_expected"] += 1
            if any(set(a[m]["flags"]) & COUNCIL_FLAGS or a[m]["route"] == "council" for m in MEASURES):
                s["flag_raised"] += 1
        s["per_case"].append(row)
    s["answers"] = len(cases) * 3
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="retrofit-check,no-evaluator,nemotron-alone")
    args = ap.parse_args()
    cases = load_cases()
    systems = {"retrofit-check": run_agent, "no-evaluator": run_no_evaluator, "nemotron-alone": run_nemotron}
    results_file = HERE / "results.json"
    results = json.loads(results_file.read_text()) if results_file.exists() else {}
    for name in args.systems.split(","):
        answers = {}
        for c in cases:
            t = time.time()
            try:
                answers[c["id"]] = systems[name](c)
            except Exception as e:  # noqa: BLE001  recorded, scored as wrong
                answers[c["id"]] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            print(f"{name:15} {c['id']:24} {time.time() - t:5.1f}s", {m: answers[c['id']].get(m, {}).get('route') for m in MEASURES} if "error" not in answers[c["id"]] else answers[c["id"]]["error"], flush=True)
        results[name] = {"answers": answers, "score": score(cases, answers), "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        results_file.write_text(json.dumps(results, indent=1))
    for name, r in results.items():
        sc = r["score"]
        print(f"{name:15} right {sc['right']}/{sc['answers']}  wrong {sc['wrong']}  deferred {sc['deferred']}  confidently wrong {sc['confidently_wrong']}  council flag {sc['flag_raised']}/{sc['flag_expected']}")


if __name__ == "__main__":
    main()
