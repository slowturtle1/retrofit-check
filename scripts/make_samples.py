"""Copy chosen runs into samples/ so the app can replay them from a fresh clone (SAMPLE_MODE=true).

Run: .venv/bin/python scripts/make_samples.py
Edit PICK to choose runs (a run id prefix from runs/). Refuses to copy anything that looks like a secret.
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

PICK = [
    # key, run id prefix, label, note
    ("dartmouth", "20261024T210630-78b45f", "Dartmouth Park, NW5", "Conservation area: solar yes, heat pump yes, outside wall insulation needs permission"),
    ("lady-somerset", "20261024T210645-da730a", "Lady Somerset Road, NW5", "Same kind of street, outside the conservation area"),
    ("hampstead", "20261024T210646-9e02f1", "Hampstead, NW3", "The agent catches an Article 4 that planning.data still lists"),
    ("downing", "20261024T210648-cacb2b", "10 Downing Street", "Grade I listed: the agent stops early"),
    ("muswell", "20261024T210655-28584e", "Muswell Hill, N10", "The council has published no conservation area Article 4s: answers marked uncertain"),
    ("trees", "20261024T210650-1ecca3", "Trees over the roof", "Noisy LIDAR: the agent measures again"),
]
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
                      "summary": [f"{v['measure']}: {v['headline']}" for v in run["result"]["verdicts"]]})
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


if __name__ == "__main__":
    main()
