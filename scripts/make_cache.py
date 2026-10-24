"""Build samples/cache.sqlite: the Zetaris data the agent needs for the sample houses, so sample mode
can run the real agent logic with no Zetaris, Nightshift or keys.

Run (with the live stack up): .venv/bin/python scripts/make_cache.py
"""

import json
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrofit.config import USER_AGENT, db_dsn  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "cache.sqlite"
HOUSE_TABLES = ["house", "house_wall", "roof_plane", "roof_survey", "pv_estimate", "designation"]
ALL_TABLES = ["article4_rule", "pd_rule", "grant_scheme", "price_fact"]


def cell(v):
    if isinstance(v, bool):
        return "true" if v else "false"      # Zetaris returns booleans as text
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    if isinstance(v, Decimal):
        return float(v)
    return v


def main() -> None:
    index = json.loads((ROOT / "samples" / "index.json").read_text())
    house_ids = sorted({json.loads((ROOT / "samples" / x["file"]).read_text())["house_id"] for x in index})
    OUT.unlink(missing_ok=True)
    out = sqlite3.connect(OUT)
    with psycopg.connect(db_dsn()) as pg:
        for t in HOUSE_TABLES + ALL_TABLES:
            cur = pg.execute(f"SELECT * FROM {t}" + (" WHERE house_id = ANY(%s)" if t in HOUSE_TABLES else ""), (house_ids,) if t in HOUSE_TABLES else None)
            cols = [d.name for d in cur.description]
            out.execute(f"CREATE TABLE {t} ({', '.join(cols)})")
            rows = [[cell(v) for v in r] for r in cur.fetchall()]
            out.executemany(f"INSERT INTO {t} VALUES ({', '.join('?' * len(cols))})", rows)
            print(f"{t:14} {len(rows)} rows")
        orgs = sorted({r[0] for r in pg.execute("SELECT DISTINCT organisation FROM designation WHERE house_id = ANY(%s) AND dataset = 'conservation-area'", (house_ids,)).fetchall() if r[0]})
    # What the evaluator asks Zetaris about each council: the Article 4 areas it has published.
    out.execute("CREATE TABLE council_a4 (org, name, reference)")
    for org in orgs:
        r = requests.get("https://www.planning.data.gov.uk/entity.json", params={"dataset": "article-4-direction-area", "organisation_entity": org,
                         "exclude_field": "geometry", "limit": 500}, headers={"User-Agent": USER_AGENT}, timeout=120)
        r.raise_for_status()
        ents = r.json().get("entities", [])
        out.executemany("INSERT INTO council_a4 VALUES (?, ?, ?)", [(org, e.get("name"), e.get("reference")) for e in ents])
        print(f"council {org}: {len(ents)} Article 4 areas")
    out.execute("CREATE TABLE listed_outline (house_key, reference)")
    out.commit()
    out.close()
    print(OUT, f"{OUT.stat().st_size // 1024} KB, houses: {', '.join(house_ids)}")


if __name__ == "__main__":
    main()
