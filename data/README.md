# Data sources

Every fact about the house and every rule reaches the agent through Zetaris. Live sources are registered as Zetaris REST tables, or cached in the `retrofit_pg` Postgres datasource, and the agent reads them back with Lightning SQL. The one exception is what the owner tells us: that lives in H-MEM, the Meterless memory engine, with the date they said it. In sample mode, with no Zetaris running, a house outside the snapshot is fetched straight from the same public sources and kept on this machine; the trace marks that as a fallback. Each fact in an answer names its source, and each rule names its legal clause and the date it applies from.

This version answers one question: is my house eligible for solar panels? The sources for the heat pump and outside wall insulation are still in the database and listed at the end, for the future enhancements.

## Tables

| Where | Tables | What is in them |
|---|---|---|
| `retrofit_pg` (Postgres container `retrofit-db`, registered in Zetaris) | 11: `house`, `house_wall`, `roof_plane`, `roof_survey`, `pv_estimate`, `designation`, `article4_rule`, `pd_rule`, `grant_scheme`, `price_fact`, `self_use_share` | The live cache. Created by `db/init/01_schema.sql`, seeded by `02_rules.sql`, `03_hampstead_article4.sql`, `04_prices.sql` and `05_self_use.sql`, filled per house while the agent works |
| `samples/cache.sqlite` (sample mode) | 14: the same 11 for the sample houses, plus `council_a4`, `listed_outline` and `he_listed` | A snapshot of what Zetaris returned, so sample mode runs the same SQL with no Zetaris. The three extra tables hold what the evaluator asks for: each council's Article 4 areas, planning.data's listed outlines, and Historic England's listed outlines |
| `runs/live-cache.sqlite` (sample mode, made on first use) | the same 14 | A copy of the snapshot that grows: any other house fetched straight from the public sources, read back with the same SQL. Not in the repository |

Record counts below were read on 25 Oct 2026: the live cache held 16 houses, the snapshot 15 (the 6 example houses and the evaluation houses; one live cache house is left out). `scripts/make_cache.py` prints the snapshot counts each time it runs.

## Sources behind the solar answer

### planning.data.gov.uk (MHCLG)

- **URL:** https://www.planning.data.gov.uk , API `https://www.planning.data.gov.uk/entity.json`
- **Licence:** mostly Open Government Licence v3.0; each dataset page states its own licence and attribution.
- **Subset:** entities that intersect the house footprint in eight datasets: listed buildings (points and outlines, with grade and date), conservation areas, Article 4 direction areas, National Landscapes, National Parks, World Heritage Sites, scheduled monuments. For the evaluator: every Article 4 area a council has published, and listed outlines touching the footprint. Council names outside London come from planning.data's organisation entries.
- **Record count:** live cache 42 rows in `designation` (13 conservation area, 23 Article 4, 2 listed building points, 4 listed outlines). Snapshot 40 rows in `designation` (12 conservation area, 22 Article 4, 2 listed building points, 4 listed outlines), 56 rows in `council_a4` (Camden 21, Westminster 10, Haringey 25), 2 in `listed_outline`.
- **Zetaris registration:** one REST table per house, `PLANNING_DATA.pd_<house>`, read with `LATERAL VIEW explode(entities)`; per council `PLANNING_DATA.a4_council_<org>`; per house `PLANNING_DATA.lbo_<house>` for listed outlines. A copy of each house's rows goes to `retrofit_pg.designation`.
- **How to regenerate:** run a check with `refresh=True` for that house (live stack). The snapshot: `.venv/bin/python scripts/make_cache.py`.
- **Limits:** councils publish unevenly. Haringey has published only employment area Article 4s, so a missing record there proves nothing, and the agent says so. planning.data can lag a council decision: it still lists Hampstead's A4Ha1 with no end date, while Camden ended it on 9 Jun 2026. If Zetaris cannot reach planning.data in time, the same request goes direct and the trace says so.

### Historic England, National Heritage List for England (listed building outlines)

- **URL:** https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/National_Heritage_List_for_England_NHLE_v02_VIEW/FeatureServer/3 (ArcGIS, no key)
- **Licence:** Open Government Licence; © Crown copyright, contains Ordnance Survey data © Crown copyright and database right (as stated on the layer).
- **Subset:** layer 3, "Listed Building polygons": the list entry, name and grade of every outline that touches the house footprint, taken about 1 m inward so a neighbour's outline on the party wall does not count. The ring has sharp corners and at most about 40 points: the service answers 404 to a query URL past about 2,000 characters. The layer holds 379,687 outlines (25 Oct 2026).
- **Record count:** snapshot 15 rows in `he_listed`, one per house; 3 of them carry an outline (10 Downing Street, Keats House and a listed house in Hampstead), the rest record "checked, none".
- **Zetaris registration:** one REST table per house and query, `PLANNING_DATA.he_<house>_v<hash of the query>`, so a changed footprint gets a new table and never an old one, read with `LATERAL VIEW explode(features)` when the evaluator challenges a "not listed" answer.
- **How to regenerate:** a live check registers it again; the snapshot: `scripts/make_cache.py`.
- **Limits:** an outline can belong to a building next door that shares the footprint edge. When Historic England shows an outline that planning.data does not, the answer says "Check with the council" rather than choosing. If the service does not answer, planning.data's answer stands and the trace says it is unchecked.

### OpenStreetMap

- **URL:** https://www.openstreetmap.org , API `https://api.openstreetmap.org/api/0.6`
- **Licence:** © OpenStreetMap contributors, ODbL 1.0.
- **Subset:** the house footprint, nearby roads and footpaths, neighbouring buildings.
- **Record count:** live cache 16 rows in `house`, 110 in `house_wall`. Snapshot 15 and 104.
- **Zetaris registration:** fetched in Python, walls and road facing computed, stored in `retrofit_pg.house` and `retrofit_pg.house_wall`, read back through Zetaris.
- **How to regenerate:** a check with `refresh=True`, or delete the house row from `retrofit_pg.house` (the cache tables cascade). Snapshot: `scripts/make_cache.py`.
- **Note:** an address search lands on a street point; the agent takes the nearest building within 20 m.
- **Limits:** "faces a road" is a geometric test: a ray from the middle of each wall reaches a road or footpath before another building. Lanes mapped as service roads count as roads until the owner says otherwise. A footprint drawn with a gap to the neighbour reads as detached. For solar this matters in a conservation area, where panels may not go on a wall that fronts a highway.

### Environment Agency LIDAR Composite DSM 1 m

- **URL:** https://environment.data.gov.uk/spatialdata/lidar-composite-digital-surface-model-first-return-dsm-1m/wcs (WCS, no key)
- **Licence:** Open Government Licence v3.0, © Environment Agency.
- **Subset:** the 1 m surface cells over the house footprint.
- **Record count:** live cache 31 rows in `roof_plane`, 16 in `roof_survey`. Snapshot 28 and 15.
- **Zetaris registration:** raster read in Python, roof planes (facing, pitch, area) and the share of noisy cells stored in `retrofit_pg.roof_plane` and `retrofit_pg.roof_survey`.
- **How to regenerate:** a check with `refresh=True`. Snapshot: `scripts/make_cache.py`.
- **Limits:** cells steeper than 65 degrees count as noise (trees, chimneys). Above 25% the agent measures again with a wider margin and marks the roof numbers as rough if it stays noisy. A listed building is not surveyed: consent is needed whatever the roof is like.

### PVGIS 5.2 (EU Joint Research Centre)

- **URL:** https://re.jrc.ec.europa.eu/pvg_tools/en/ , API `https://re.jrc.ec.europa.eu/api/v5_2/PVcalc`
- **Licence:** free reuse with acknowledgement, © European Union.
- **Subset:** yearly output of the best roof plane, for its pitch and facing, 14% system loss.
- **Record count:** live cache 12 rows in `pv_estimate`. Snapshot 11. The 4 listed buildings (10 Downing Street, Keats House, the Freud Museum and a listed house in Hampstead) have none: they are not surveyed.
- **Zetaris registration:** one REST table per request, `PVGIS.pv_<hash>`, read with Lightning SQL; cached in `retrofit_pg.pv_estimate`.
- **How to regenerate:** a check with `refresh=True`. Snapshot: `scripts/make_cache.py`.
- **Limits:** panel capacity uses 0.147 kWp per m² of roof plane, an estimate. Shading from nearby trees and buildings is not modelled. If Zetaris cannot reach PVGIS, the same request goes direct and the source line says so.

### legislation.gov.uk (the rules)

- **URL:** https://www.legislation.gov.uk/uksi/2015/596/schedule/2
- **Licence:** Crown copyright, Open Government Licence v3.0.
- **Subset:** GPDO 2015 Schedule 2 Part 14 Class A (A.2(c) pitched roof, A.2(e) wall facing a highway in a conservation area, A.2(g) listed building, A.3(ba) flat roof in a conservation area), article 2(3) land, Listed Buildings Act 1990 s.7.
- **Record count:** 13 rows in `pd_rule`, 4 of them for solar.
- **Zetaris registration:** curated rows in `retrofit_pg.pd_rule`, each with clause, plain wording, in force date, last amendment, URL and check date (24 Oct 2026).
- **How to regenerate:** edit `db/init/02_rules.sql`; a fresh `retrofit-db` volume seeds it on `docker compose up`.
- **Limits:** England only. The rows are our reading of the law, checked on 24 Oct 2026. The status is decided in code from these rows, and each answer lists the clause so a planning officer can check it.

### gov.uk and Ofgem (help with cost)

- **URL:** https://www.gov.uk/guidance/vat-on-energy-saving-materials-and-heating-equipment-notice-7086 , https://www.ofgem.gov.uk/environmental-and-social-schemes/smart-export-guarantee-seg
- **Licence:** Open Government Licence v3.0.
- **Subset:** zero VAT on installing solar panels in a home until 31 Mar 2027; the Smart Export Guarantee.
- **Record count:** 5 rows in `grant_scheme`, 2 of them for solar.
- **Zetaris registration:** curated rows in `retrofit_pg.grant_scheme`.
- **How to regenerate:** edit `db/init/02_rules.sql`.
- **Limits:** income based grants are only signposted, with no amount.

### Ofgem price cap, 1 Oct to 31 Dec 2026

- **URL:** https://www.ofgem.gov.uk/your-energy-supply/your-energy-bill/energy-price-cap-unit-rates-and-standing-charges
- **Licence:** Open Government Licence v3.0.
- **Subset:** electricity unit rate 26.32p/kWh.
- **Record count:** 1 row in `price_fact` used by solar (`elec_rate`).
- **Zetaris registration:** `retrofit_pg.price_fact`, kind `official`.
- **How to regenerate:** edit `db/init/04_prices.sql` when the cap changes on 1 Jan 2027.
- **Limits:** the cap is an average; the owner's own tariff may differ.

### DESNZ Solar PV cost data, published 28 May 2026 (MCS data)

- **URL:** https://www.gov.uk/government/statistics/solar-pv-cost-data
- **Licence:** Open Government Licence v3.0.
- **Subset:** 2025/26 installed cost of 0 to 4 kW systems: Great Britain median £1,595/kW, London mean £2,101/kW.
- **Record count:** 2 rows in `price_fact`.
- **Zetaris registration:** `retrofit_pg.price_fact`, kind `official`. The evaluator compares the two in Zetaris and the answer shows both as a range.
- **How to regenerate:** edit `db/init/04_prices.sql`.
- **Limits:** a range from national and London figures, not a quote.

### Which?, 24 Apr 2026 (export rates)

- **URL:** https://www.which.co.uk/news/article/smart-export-guarantee-rates-the-best-and-worst-seg-tariffs-for-solar-panel-owners-azICP0i78MD8
- **Licence:** quoted figures, linked.
- **Subset:** export rates of 6p/kWh open to everyone and 15p/kWh with the supplier's import tariff. Ofgem sets no rate, only that it is above zero.
- **Record count:** 2 rows in `price_fact`.
- **Zetaris registration:** `retrofit_pg.price_fact`, kind `consumer_survey`.
- **How to regenerate:** edit `db/init/04_prices.sql`.
- **Limits:** a consumer survey, not an official figure; the answer labels it.

### MCS MGD 003 look up tables (share of solar power used at home)

- **URL:** https://mcscertified.com/wp-content/uploads/2025/02/MGD003-LookupTables-FINAL.xlsx
- **Licence:** published by MCS for installers to use; figures quoted and linked.
- **Subset:** the "PV only" column (no battery), for three occupancy types (home all day, in half the day, out during the day), yearly electricity use from 1,500 to 5,999 kWh and yearly generation up to 5,999 kWh.
- **Record count:** 540 rows in `self_use_share` (180 per occupancy type), the same in the live cache and the snapshot.
- **Zetaris registration:** `retrofit_pg.self_use_share`. The evaluator asks Zetaris for the row that matches this roof's yield and this household's use, for all three occupancy types, and the answer uses the lowest and highest share.
- **How to regenerate:** edit `db/init/05_self_use.sql` (checked 25 Oct 2026).
- **Limits:** a yearly average without a battery. A household's own pattern can differ, and the answer says so. Outside the table (under 1,500 or over 5,999 kWh used, or over 5,999 kWh made) the share falls back to our estimate below.

### Ofgem Typical Domestic Consumption Value, from 1 Jul 2026

- **URL:** https://www.ofgem.gov.uk/sites/default/files/2026-06/Summary-of-changes-to-energy-price-cap-1-July-to-30-September-2026-revised-TDCV.pdf
- **Licence:** Open Government Licence v3.0.
- **Subset:** the medium value for electricity: 2,500 kWh a year.
- **Record count:** 1 row in `price_fact` (`typical_elec_use`).
- **Zetaris registration:** `retrofit_pg.price_fact`, kind `official`.
- **How to regenerate:** edit `db/init/05_self_use.sql`.
- **Limits:** used only when the owner has not given their own yearly use; the answer says which one it used.

### How long panels last

- **URL:** https://www.basingstoke.gov.uk/solar-panels
- **Licence:** council website; quoted and linked.
- **Subset:** "Solar panels should last for about 25 years".
- **Record count:** 1 row in `price_fact` (`pv_life_years`).
- **Zetaris registration:** `retrofit_pg.price_fact`, kind `council`.
- **How to regenerate:** edit `db/init/05_self_use.sql`.
- **Limits:** one council's guidance, not a warranty. The recommendation says "Worth getting quotes" only when the typical payback fits within these 25 years.

### Our estimate when the MCS tables do not cover the house

- **URL:** none.
- **Licence:** ours.
- **Subset:** 25% to 50% of the solar electricity used at home without a battery.
- **Record count:** 2 rows in `price_fact` (`self_use_low`, `self_use_high`).
- **Zetaris registration:** `retrofit_pg.price_fact`, kind `assumption`.
- **How to regenerate:** edit `db/init/04_prices.sql`.
- **Limits:** an estimate, used only outside the MCS tables or when Zetaris cannot answer, and the answer says so.

### Council Article 4 pages (Camden, Westminster)

- **URL:** https://www.camden.gov.uk/article-4-directions-other-development- , https://www.camden.gov.uk/article-4-directions-land-use-classes , Camden's decision of 27 May 2025 (https://camden.moderngov.co.uk/documents/s125901/SMD%20Report%2027May25.pdf)
- **Licence:** council websites; summarised and linked.
- **Subset:** what each Article 4 direction near the demo houses removes, and its end date if the council ended it.
- **Record count:** 9 rows in `article4_rule`.
- **Zetaris registration:** curated rows in `retrofit_pg.article4_rule`, joined in Zetaris to the live planning.data designations.
- **How to regenerate:** edit `db/init/02_rules.sql` and `db/init/03_hampstead_article4.sql`.
- **Limits:** contents are on file only for the directions around the demo houses. Anywhere else the agent says "check with the council" rather than guess.

### The owner (H-MEM)

- **URL:** none: what the owner types, kept by the Meterless H-MEM reference engine (`hmem/`).
- **Licence:** the owner's own data; the engine is Apache 2.0.
- **Subset:** the owner's yearly electricity use from their bill, and corrections such as "the side lane is our private drive". The yearly use replaces Ofgem's typical value in the MCS look up.
- **Record count:** per house, as the owner adds them.
- **Zetaris registration:** none. H-MEM keeps it with provenance and the date; the answer cites it as "you told us" with that date.
- **How to regenerate:** not needed; a correction from the owner supersedes the old note and keeps it as history.
- **Limits:** we do not check what the owner tells us. Sample mode does not use H-MEM.

## Display only (not in Zetaris, no facts derived)

| Source | What for | Licence |
|---|---|---|
| Google Photorealistic 3D Tiles | The 3D picture of the street | Google Maps Platform terms; attribution on the map. Optional: without a key the map is OpenStreetMap |
| postcodes.io, Nominatim | Moving the camera to a typed postcode or street | ONS Postcode Directory (OGL); © OpenStreetMap contributors |

## Kept for future enhancements (heat pump, outside wall insulation)

These rows are still in `retrofit_pg` and read by the code, but this version does not show the heat pump or outside wall answers.

| Source | Rows |
|---|---|
| legislation.gov.uk: GPDO Part 14 Class G (air source heat pumps), Part 1 Class A (cladding), TCPA 1990 s.55 | 9 rows in `pd_rule` |
| gov.uk Boiler Upgrade Scheme (£7,500; £9,000 off the gas grid from 21 Jul 2026 to 31 Mar 2027), householder application fee £548 | 3 rows in `grant_scheme` |
| [DESNZ Boiler Upgrade Scheme statistics](https://www.gov.uk/government/statistics/boiler-upgrade-scheme-statistics-august-2026), August 2026, table Q1.1A: installed cost lower quartile £11,128, median £12,908, upper quartile £15,627 | 3 rows in `price_fact` |
| Ofgem price cap: gas 7.97p/kWh, gas standing charge 29.68p a day | 2 rows in `price_fact` |
| [Energy Saving Trust](https://energysavingtrust.org.uk/advice/boilers/), 20 May 2026: new gas boiler £3,500; [MCS](https://mcscertified.com/technology/air-source-heat-pump/): heat pump life up to 20 years | 2 rows in `price_fact`, kind `advice_body` |
| Our assumptions: boiler efficiency 85%, heat pump seasonal efficiency 2.8 to 3.5 | 3 rows in `price_fact`, kind `assumption` |

## Zetaris objects

`scripts/setup_zetaris.py` creates them once:

- `retrofit_pg`: JDBC datasource for the `retrofit-db` Postgres container on the `zetaris_default` Docker network (`docker-compose.yml`), with all 11 tables registered.
- `PLANNING_DATA` and `PVGIS`: Lightning databases that hold the REST tables the agent registers while it works.

```bash
docker compose --env-file .env up -d          # creates and seeds retrofit-db from db/init/
.venv/bin/python scripts/setup_zetaris.py     # registers it in Zetaris
.venv/bin/python scripts/make_cache.py        # rebuilds samples/cache.sqlite from the live cache
```

## Scope

England only, houses only. Flats, tenants, building regulations and income based grants are out of scope. Money is a range, not a quote. Nothing here is legal or financial advice.
