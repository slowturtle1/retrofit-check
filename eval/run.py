"""Step 2 of the evaluation: run three systems on the frozen cases and score the solar answer.

Systems
  retrofit-check    the agent as shipped (rules + evaluator), live: Zetaris, planning.data, OSM, LIDAR
  no-evaluator      the same rules on the same planning.data facts, but trusting planning.data as it is:
                    no council decisions on Article 4 end dates, no evaluator challenges
  nemotron-alone    Nemotron through Nightshift, given only the street, postcode district and borough

The solar status the owner sees is scored by route: allowed (with or without conditions) / permission / consent.
"Check with the council" counts as right where the case expects the owner to ask the council, otherwise as
deferred (not right, not wrong). Confidently wrong = wrong and no uncertainty flag on that answer.
Since 25 Oct the MVP answers solar only, so 15 answers are scored (until then 45: three upgrades per house).

Run: .venv/bin/python eval/run.py [--systems retrofit-check,no-evaluator,nemotron-alone] [--sample]
     --sample runs the first two systems on the local snapshot (samples/cache.sqlite), no services needed.
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
MEASURES = ("solar",)
ROUTE = {"allowed": "allowed", "allowed_with_conditions": "allowed", "needs_permission": "permission",
         "needs_consent": "consent", "check_with_council": "council"}
COUNCIL_FLAGS = {"article4_coverage_unknown", "article4_unknown"}

PROMPT = ("A homeowner owns a house on {street}, London {district} ({borough}). In England, are solar panels on the roof "
          "allowed under permitted development, do they need planning permission, or do they need listed building consent? "
          "Reply with exactly one line and nothing else:\nsolar=allowed|permission|consent")


def load_cases() -> list[dict]:
    d = json.loads((HERE / "cases.json").read_text())
    body = json.dumps(d["cases"], indent=1, sort_keys=True)
    if hashlib.sha256(body.encode()).hexdigest() != d["sha256"]:
        sys.exit("cases.json was changed after it was frozen")
    return d["cases"]


def from_result(result: dict) -> dict:
    out = {}
    for v in result["verdicts"]:
        if v["measure"] in MEASURES:
            out[v["measure"]] = {"route": ROUTE[v["status"]], "flags": sorted(v["uncertain"])}
    return out


SAMPLE = False   # --sample: the local snapshot instead of Zetaris


def run_agent(case: dict) -> dict:
    """What the owner sees: the shown status (Check with the council when the data is unsure), not the rules status."""
    r = Run(use_model=False, use_memory=False, offline=SAMPLE).check(way=case["way"], lat=None if case["way"] else case["lat"],
                                                                     lon=None if case["way"] else case["lon"], label=case["note"])
    s = r["answer"]["solar"]
    return {"solar": {"route": ROUTE[s["status"]], "rules_route": ROUTE[s["rules_status"]], "flags": sorted(s["uncertain"])},
            "_mode": r["answer"]["mode"], "_fallbacks": r.get("fallbacks", []), "_trace_id": r["answer"]["trace_id"]}


def run_no_evaluator(case: dict) -> dict:
    """Same rules, same Zetaris facts, but planning.data taken at face value and no challenges."""
    if SAMPLE:
        from retrofit.offline import OfflineZetaris
        z = OfflineZetaris()
    else:
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
    for m, key in (("solar", "solar"),):
        hit = re.search(rf"{key}\s*=\s*(allowed|permission|consent)", text, re.I)
        out[m] = {"route": hit.group(1).lower() if hit else "no answer", "flags": []}
    out["_asked"] = where
    return out


def score(cases: list[dict], answers: dict) -> dict:
    s = {"right": 0, "wrong": 0, "deferred": 0, "confidently_wrong": 0, "flag_expected": 0, "flag_raised": 0, "per_case": []}
    for c in cases:
        a = answers.get(c["id"])
        row = {"id": c["id"], "group": c["group"]}
        if a and "skipped" in a:
            row["skipped"] = a["skipped"]
            s["per_case"].append(row)
            s["skipped"] = s.get("skipped", 0) + 1
            continue
        if not a or "error" in a:
            row["error"] = (a or {}).get("error", "not run")
            s["per_case"].append(row)
            s["wrong"] += len(MEASURES)
            continue
        for m in MEASURES:
            got, want = a[m]["route"], c["expected"][m]
            row[m] = f"{got} (want {want})"
            if got == "council" and c["expected"]["flag_council"]:
                s["right"] += 1                 # the expected answer here is: ask the council
            elif got == "council":
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
    s["answers"] = (len(cases) - s.get("skipped", 0)) * len(MEASURES)
    return s


def summary(name: str, r: dict) -> dict:
    sc = r["score"]
    return {"measures": list(MEASURES), "right": sc["right"], "of": sc["answers"], "wrong": sc["wrong"], "deferred": sc["deferred"],
            "confident_wrong": sc["confidently_wrong"], "council_flag": f"{sc['flag_raised']}/{sc['flag_expected']}", "skipped": sc.get("skipped", 0),
            "mode": r.get("mode"), "run_at": r.get("run_at")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="retrofit-check,no-evaluator,nemotron-alone")
    ap.add_argument("--sample", action="store_true", help="run on the local snapshot (no Zetaris, Nightshift or network)")
    args = ap.parse_args()
    global SAMPLE
    SAMPLE = args.sample
    cases = load_cases()
    systems = {"retrofit-check": run_agent, "no-evaluator": run_no_evaluator, "nemotron-alone": run_nemotron}
    results_file = HERE / ("results-sample.json" if SAMPLE else "results.json")
    results = json.loads(results_file.read_text()) if results_file.exists() else {}
    results = {k: v for k, v in results.items() if k == "summary" or v.get("measures") == list(MEASURES)}   # older three upgrade runs are in git history
    for name in args.systems.split(","):
        if SAMPLE and name == "nemotron-alone":
            continue   # needs Nightshift
        answers = {}
        in_snapshot = {h["house_id"] for h in __import__("retrofit.offline", fromlist=["houses"]).houses()} if SAMPLE else None
        for c in cases:
            t = time.time()
            if in_snapshot is not None and c["id"] not in in_snapshot:
                answers[c["id"]] = {"skipped": "not in the sample snapshot"}
                print(f"{name:15} {c['id']:24} skipped: not in the sample snapshot", flush=True)
                continue
            try:
                answers[c["id"]] = systems[name](c)
            except Exception as e:  # noqa: BLE001  recorded, scored as wrong
                answers[c["id"]] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            print(f"{name:15} {c['id']:24} {time.time() - t:5.1f}s", {m: answers[c['id']].get(m, {}).get('route') for m in MEASURES} if "error" not in answers[c["id"]] else answers[c["id"]]["error"], flush=True)
        modes = {a.get("_mode") for a in answers.values() if isinstance(a, dict) and a.get("_mode")}
        results[name] = {"measures": list(MEASURES), "answers": answers, "score": score(cases, answers), "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "mode": "sample" if SAMPLE else ("live" if modes <= {"live"} else "mixed"),
                         "fallbacks": sorted({f for a in answers.values() if isinstance(a, dict) for f in a.get("_fallbacks", [])})}
        results["summary"] = {k: summary(k, v) for k, v in results.items() if k != "summary"}
        results_file.write_text(json.dumps(results, indent=1))
    for name, r in results.items():
        if name == "summary":
            continue
        sc = r["score"]
        print(f"{name:15} right {sc['right']}/{sc['answers']}  wrong {sc['wrong']}  deferred {sc['deferred']}  confidently wrong {sc['confidently_wrong']}  council flag {sc['flag_raised']}/{sc['flag_expected']}"
              + (f"  skipped {sc['skipped']}" if sc.get("skipped") else ""))


if __name__ == "__main__":
    main()
