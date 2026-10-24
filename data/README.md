# Data sources

Every fact the agent uses comes from one of the sources below. All of them reach the agent through Zetaris: live sources are registered as Zetaris REST tables or cached in the `retrofit_pg` Postgres datasource, and the agent reads them back with Lightning SQL. Each fact in an answer names its source, and each rule names its legal clause and the date it applies from.

| Source | What we use | How it gets to Zetaris | Licence and attribution |
|---|---|---|---|
| [planning.data.gov.uk](https://www.planning.data.gov.uk) (MHCLG) | Listed buildings (points and outlines, with grade and date), conservation areas, National Landscapes, National Parks, World Heritage Sites, Article 4 direction areas, all intersecting the house footprint | A Zetaris REST table per house (`PLANNING_DATA.pd_<house>`), read with `LATERAL VIEW explode(entities)`; copy cached in `retrofit_pg.designation` | Mostly Open Government Licence v3.0; each dataset page states its own licence and attribution |
| [OpenStreetMap](https://www.openstreetmap.org) via the OSM API | House footprint, nearby roads and footpaths, neighbouring buildings | Fetched with the OSM API, walls and road facing computed in Python, stored in `retrofit_pg.house` and `retrofit_pg.house_wall` | © OpenStreetMap contributors, ODbL 1.0 |
| [Environment Agency LIDAR Composite DSM 1 m](https://environment.data.gov.uk/spatialdata/lidar-composite-digital-surface-model-first-return-dsm-1m/wcs?service=WCS&request=GetCapabilities) (WCS) | Roof planes: facing, pitch, area; share of noisy cells (trees, chimneys) | Raster read in Python, planes stored in `retrofit_pg.roof_plane` and `retrofit_pg.roof_survey` | Open Government Licence v3.0, © Environment Agency |
| [PVGIS 5.2](https://re.jrc.ec.europa.eu/pvg_tools/en/) (EU Joint Research Centre) | Yearly solar output of the best roof plane | A Zetaris REST table per request (`PVGIS.pv_<hash>`), cached in `retrofit_pg.pv_estimate` | Free reuse with acknowledgement, © European Union |
| [legislation.gov.uk](https://www.legislation.gov.uk/uksi/2015/596/schedule/2) | GPDO 2015 Schedule 2 Part 1 Class A and Part 14 Classes A and G, with amendment dates; Listed Buildings Act 1990 s.7; TCPA 1990 s.55 | Curated rows in `retrofit_pg.pd_rule` (`db/init/02_rules.sql`), each with clause, plain wording, in force date, last amendment, URL and check date | Crown copyright, Open Government Licence v3.0 |
| gov.uk and Ofgem | Boiler Upgrade Scheme £7,500 and £9,000 (off gas grid, 21 Jul 2026 to 31 Mar 2027), zero VAT to 31 Mar 2027, Smart Export Guarantee, householder application fee £548 | Curated rows in `retrofit_pg.grant_scheme` | Open Government Licence v3.0 (the fee comes from a council fee table, linked) |
| [Ofgem price cap](https://www.ofgem.gov.uk/your-energy-supply/your-energy-bill/energy-price-cap-unit-rates-and-standing-charges), 1 Oct to 31 Dec 2026 | Electricity 26.32p/kWh (no VAT on electricity Oct 2026 to Mar 2027), gas 7.97p/kWh, gas standing charge 29.68p a day | Curated rows in `retrofit_pg.price_fact` | Open Government Licence v3.0 |
| [DESNZ Solar PV cost data](https://www.gov.uk/government/statistics/solar-pv-cost-data), published 28 May 2026 (MCS data) | 2025/26 installed cost of 0 to 4 kW systems: Great Britain median £1,595/kW, London mean £2,101/kW | `retrofit_pg.price_fact` | Open Government Licence v3.0 |
| [DESNZ Boiler Upgrade Scheme statistics](https://www.gov.uk/government/statistics/boiler-upgrade-scheme-statistics-august-2026), August 2026, table Q1.1A | Air to water heat pump installed cost Apr to Jun 2026: lower quartile £11,128, median £12,908, upper quartile £15,627 (before the grant) | `retrofit_pg.price_fact` | Open Government Licence v3.0 |
| [Which?](https://www.which.co.uk/news/article/smart-export-guarantee-rates-the-best-and-worst-seg-tariffs-for-solar-panel-owners-azICP0i78MD8), 24 Apr 2026 | Export rates: 6p/kWh open to everyone, 15p/kWh with the supplier's import tariff (Ofgem sets no rate, only that it is above zero) | `retrofit_pg.price_fact` | Quoted figures, linked |
| [Energy Saving Trust](https://energysavingtrust.org.uk/advice/boilers/), updated 20 May 2026 | Typical cost of replacing an old gas boiler with an A rated one: £3,500 (GB) | `retrofit_pg.price_fact`, kind `advice_body` | Quoted figure, linked |
| [MCS](https://mcscertified.com/technology/air-source-heat-pump/) | "On average, an air source heat pump lasts up to 20 years" | `retrofit_pg.price_fact`, kind `advice_body` | Quoted figure, linked |
| Assumptions (ours) | Share of solar used at home 25 to 50%, gas boiler efficiency 85%, heat pump seasonal efficiency 2.8 to 3.5 | `retrofit_pg.price_fact`, kind `assumption` | Shown as assumptions on the page |
| Council Article 4 pages (Camden, Westminster) | What each Article 4 direction near the demo houses removes | Curated rows in `retrofit_pg.article4_rule` | Council websites; summarised, linked |
| Google Photorealistic 3D Tiles | The 3D picture of the street, nothing else | Not in Zetaris: display only in the browser | Google Maps Platform terms; no data is derived from the tiles; attribution shown on the map |
| postcodes.io, Nominatim | Moving the camera to a typed postcode or street | Browser only | ONS Postcode Directory (OGL); © OpenStreetMap contributors |

## Zetaris objects

`scripts/setup_zetaris.py` creates them once:

- `retrofit_pg`: JDBC datasource for the `retrofit-db` Postgres container on the `zetaris_default` Docker network (`docker-compose.yml`), with all nine tables registered.
- `PLANNING_DATA` and `PVGIS`: Lightning databases that hold the per house REST tables the agent registers while it works.

## Regenerate

```bash
docker compose --env-file .env up -d          # creates and seeds retrofit-db from db/init/
.venv/bin/python scripts/setup_zetaris.py     # registers it in Zetaris
```

To refresh one house, run a check with `refresh=True` (or delete its row from `retrofit_pg.house`; the cache tables cascade).

## Subset and limits

- England only, houses only. Flats, tenants, building regulations and income based grants are out of scope.
- Article 4 contents are on file only for the directions around the demo houses. Anywhere else the agent says "check with your council" rather than guess. planning.data is incomplete for some councils: Haringey, for example, has published only its employment area directions, so a missing Article 4 there is not proof that none exists.
- "Faces a road" is a geometric test: a ray from the middle of each wall reaches a road or footpath before another building. Lanes mapped as service roads count as roads until the owner says otherwise.
- Party walls and detached houses come from OpenStreetMap footprints. A footprint drawn with a gap to the neighbour reads as detached.
- LIDAR roofs: cells steeper than 65 degrees are reported as noise; above 25% the agent measures again with a wider margin and marks the result as rough if it stays noisy. Panel capacity uses 0.147 kWp per m² of roof plane, an estimate.
- Money is a range, not a quote: national and London costs, current price cap, two export rates, stated assumptions. The heat pump saving assumes the gas supply is closed afterwards.
- The status of each upgrade is decided in code from these rules. Nothing here is legal advice; the answer lists the clause so a planning officer can check it.
