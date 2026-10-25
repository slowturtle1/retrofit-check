"""Copy chosen runs into samples/ so the app can replay them from a fresh clone (SAMPLE_MODE=true).

Run: .venv/bin/python scripts/make_samples.py
PICK names the samples; the run ids come from runs/a8-index.json (written by the live run script), or edit PICK.
Also writes input_examples/ (the request bodies) and output_examples/ (the saved answer JSON of those live runs).
Refuses to copy anything that looks like a secret.
"""

import glob
import json
import re
import shutil
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RUNS, OUT = ROOT / "runs", ROOT / "samples"
UA = {"User-Agent": "retrofit-check-hackathon/0.1 (Open Agent Hackathon 2026)"}

LIVE = json.loads((RUNS / "a8-index.json").read_text()) if (RUNS / "a8-index.json").exists() else {}
PICK = [
    # key, run id prefix, label, note
    ("dartmouth", LIVE.get("dartmouth", ""), "Dartmouth Park, NW5", "Conservation area corner house: panels allowed, the owner's electricity use remembered"),
    ("lady-somerset", LIVE.get("lady-somerset", ""), "Lady Somerset Road, NW5", "Same kind of street, outside the conservation area"),
    ("hampstead", LIVE.get("hampstead", ""), "Hampstead, NW3", "The agent catches an Article 4 that planning.data still lists"),
    ("downing", LIVE.get("downing", ""), "10 Downing Street", "Grade I listed: the agent stops early"),
    ("muswell", LIVE.get("muswell", ""), "Muswell Hill, N10", "The council has published no conservation area Article 4s: check with the council"),
    ("trees", LIVE.get("trees", ""), "Trees over the roof", "Noisy LIDAR and a small roof: probably not worth it"),
]
# Request bodies for input_examples/, and which saved live answers go to output_examples/.
INPUTS = {
    "dartmouth": {"way": 1106478076, "label": "Dartmouth Park, NW5", "elec_kwh": 3100},
    "hampstead": {"way": 110514126, "label": "Hampstead, NW3"},
    "downing": {"lat": 51.50348, "lon": -0.12770, "label": "10 Downing Street"},
    "muswell": {"way": 1068478521, "label": "Muswell Hill, N10"},
}
OUTPUTS = {"dartmouth-told": "dartmouth-session-1", "dartmouth": "dartmouth-session-2", "hampstead": "hampstead", "downing": "downing", "muswell": "muswell"}
SECRET = re.compile(r"(Bearer\s+\S+|nvapi-|AIza[0-9A-Za-z_-]{20,}|password\s+\"[^*\"])", re.I)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "areas").mkdir(exist_ok=True)
    index = []
    for key, prefix, label, note in PICK:
        files = sorted(glob.glob(str(RUNS / f"{prefix}*.json")))
        if not files:
            sys.exit(f"no run starting with {prefix}")
        text = Path(files[-1]).read_text()
        if SECRET.search(text):
            sys.exit(f"{files[-1]} looks like it contains a secret; not copied")
        run = json.loads(text)
        (OUT / f"{key}.json").write_text(json.dumps(run, indent=1))
        house = run["result"]["house"]
        index.append({"key": key, "label": label, "note": note, "file": f"{key}.json", "run_id": run["run_id"], "house_id": run["house_id"],
                      "way": int(run["house_id"].rsplit("-", 1)[1]) if run["house_id"].startswith("osm-way-") else None,
                      "lat": float(house["lat"]), "lon": float(house["lon"]),
                      "summary": [f"solar: {run['answer']['solar']['status_text']} · {run['answer']['solar']['recommendation']}"] if run.get("answer") else
                                 [f"{v['measure']}: {v['headline']}" for v in run["result"]["verdicts"]]})
        for area in run["result"].get("areas", []):
            ent = area.get("entity")
            if not ent:
                continue
            dst = OUT / "areas" / f"{ent}.geojson"
            src = RUNS / "areas" / f"{ent}.geojson"
            if src.exists():
                shutil.copy(src, dst)
            elif not dst.exists():
                r = requests.get(f"https://www.planning.data.gov.uk/entity/{ent}.geojson", headers=UA, timeout=120)
                r.raise_for_status()
                dst.write_text(r.text)
        print(f"{key:14} {run['run_id']}  {run['seconds']} s  " + "; ".join(index[-1]["summary"]))
    (OUT / "index.json").write_text(json.dumps(index, indent=1))
    examples()


def examples() -> None:
    """input_examples/: what to POST to /run. output_examples/: the answer JSON those live runs returned (never served at runtime)."""
    inp, out = ROOT / "input_examples", ROOT / "output_examples"
    inp.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    for key, body in INPUTS.items():
        (inp / f"{key}.json").write_text(json.dumps(body, indent=1) + "\n")
    for key, name in OUTPUTS.items():
        if not LIVE.get(key):
            continue
        files = sorted(glob.glob(str(RUNS / f"{LIVE[key]}*.json")))
        text = Path(files[-1]).read_text()
        if SECRET.search(text):
            sys.exit(f"{files[-1]} looks like it contains a secret; not copied")
        (out / f"{name}.json").write_text(json.dumps(json.loads(text)["answer"], indent=1) + "\n")
        print(f"output_examples/{name}.json  from run {LIVE[key]}")


if __name__ == "__main__":
    main()
