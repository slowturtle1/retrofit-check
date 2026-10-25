"""One time Zetaris setup: register the cache database and the planning.data REST source.

Run: .venv/bin/python scripts/setup_zetaris.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrofit.config import env  # noqa: E402
from retrofit.zetaris import Zetaris, ZetarisError  # noqa: E402

TABLES = ["house", "house_wall", "roof_plane", "roof_survey", "pv_estimate", "designation", "article4_rule", "pd_rule", "grant_scheme", "price_fact", "self_use_share"]


def main() -> None:
    z = Zetaris(on_query=lambda e: print(("OK  " if not e["error"] else "ERR ") + e["sql"].splitlines()[0][:90], f"({e['seconds']} s)", e["error"] or ""))
    existing = {r[0].lower() for r in z.run("SHOW DATASOURCES").rows}
    if "retrofit_pg" not in existing:
        z.run(f'''CREATE DATASOURCE retrofit_pg DESCRIBE BY "Retrofit Check cache - houses, LIDAR roofs, PVGIS, rules" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://retrofit-db:5432/retrofit",
  username "retrofit",
  password "{env('RETROFIT_DB_PASSWORD')}",
  fetchsize "1000"
)''')
    z.run("REGISTER DATASOURCE TABLES FROM retrofit_pg")
    print(z.run("SHOW DATASOURCE TABLES retrofit_pg").rows)
    dbs = {r[0].lower() for r in z.run("SHOW LIGHTNING DATABASES").rows}
    if "planning_data" not in dbs:
        z.run('CREATE LIGHTNING DATABASE PLANNING_DATA DESCRIBE BY "planning.data.gov.uk entities - listed buildings, conservation areas, Article 4"')
    if "pvgis" not in dbs:
        z.run('CREATE LIGHTNING DATABASE PVGIS DESCRIBE BY "PVGIS 5.2 - EU JRC solar yield per roof plane"')
    print(z.run("SELECT rule_id, in_force FROM retrofit_pg.pd_rule LIMIT 3").rows)


if __name__ == "__main__":
    try:
        main()
    except ZetarisError as e:
        sys.exit(str(e))
