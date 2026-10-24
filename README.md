# Retrofit Check

**Which energy upgrades is my house eligible for?** Know what's possible, what it costs and what to do next, for your house.

We are building an agent that helps a homeowner in England find out which energy upgrades their house is eligible for, by reconciling planning records, national rules, roof measurements and grant rules through Zetaris, and producing one page with a status, reason, source and rule date for solar panels, a heat pump and outside wall insulation.

Open Agent Hackathon 2026, Track 1: Solving Fragmented Intelligence. Team Buccies.

## What it does

Type a postcode, tap your house on the 3D map. For each of the three upgrades the card shows a status, one line and a next step: **Worth getting quotes**, **Worth it mainly if your boiler needs replacing soon**, **Ask the council first**, **Probably not worth it for this house**, or **Can't tell yet: add your gas use**. On tap:

- the status in full: *Allowed under permitted development*, *Allowed under permitted development, if conditions are met*, *Needs planning permission*, *Needs listed building consent*, or *Check with your council*
- why, in plain words, with the clause and the date the rule applies from
- what you get (roof yield in kWh a year) or what you can do instead
- help with cost (Boiler Upgrade Scheme, zero VAT, Smart Export Guarantee)
- rough money, as ranges labelled "estimate, not financial advice": solar install cost, yearly value and payback; heat pump cost before and after the grant, and the yearly saving once you give your gas use (asked once, remembered)
- the reason drawn on the map: the sunny roof slope, the walls that face a road, the conservation area edge (all marked *indicative*)

The model never decides legality. The rules do. The agents plan, challenge the evidence and explain.

## Five sample houses

| House | Input | Output | What it shows |
|---|---|---|---|
| Dartmouth Park, NW5: corner house, not listed, Dartmouth Park Conservation Area since 1 Jun 1992 | OSM way 1106478076, gas boiler, 12,000 kWh of gas a year | Solar allowed (south slope 27°, 2.9 kWp, about 2,916 kWh a year; £4,600 to £6,100, pays back in 8 to 19 years): *Worth getting quotes*. Heat pump allowed if conditions are met, only on the east wall (the other two face roads), one unit; £3,600 to £8,100 after the £7,500 grant, saves £110 to £300 a year: *Worth it mainly if your boiler needs replacing soon* (about £1,900 more than a new gas boiler, back in about 9 years). Outside wall insulation **needs planning permission** (GPDO Part 1 Class A, A.2(a)); alternatives: inside insulation, £548 householder application: *Ask the council first* | The main case: two yes, one no, and why |
| Lady Somerset Road, NW5, about 600 m away | OSM way 1556408737 | All three allowed; walls only if the finish looks the same | Same kind of street outside the conservation area |
| Hampstead, NW3 | OSM way 110514126 | Solar allowed (about 4,696 kWh a year) | planning.data still lists Article 4 A4Ha1 (2010, covered roof solar) with no end date; Camden ended it on 9 Jun 2026. The agent shows both and follows the council |
| 10 Downing Street | a tap on the roof | All three need listed building consent (Grade I since 14 Jan 1970) | The planner stops early: no roof survey for a listed building |
| Muswell Hill, N10 (Haringey) | a tap on the roof | Answers marked uncertain | The evaluator finds Haringey has published no conservation area Article 4s, so a missing record proves nothing |

The recorded runs are in [`samples/`](samples/) and replay without any keys (see *Sample mode*).

## How the agents work

```
homeowner ─► planner ─► analyst (Zetaris) ─► rules (code) ─► evaluator ─► analyst again ─► reporter (Nemotron) ─► critic ─► page
                │                                              │  challenges the evidence          │ rewrites in plain words   │ code checks + Nemotron
                └─ H-MEM: what you told us before               └─ asks Zetaris again                └─ back to the reporter if rejected
```

- **Planner** (`retrofit/agent/run.py`, `retrofit/facts.py`): finds the building in OpenStreetMap, recalls what the owner said before (H-MEM), reads planning first, then decides what else is worth measuring. A listed building stops here: consent is needed whatever the roof is like.
- **Analyst**: every fact goes through Zetaris. planning.data and PVGIS are registered as Zetaris REST tables per house; OpenStreetMap walls and LIDAR roof planes are cached in a Postgres datasource and read back with Lightning SQL, together with the dated rules and the grants.
- **Rules** (`retrofit/rules.py`): GPDO 2015 Part 1 Class A and Part 14 Classes A and G, listed building consent, Article 4 contents, Boiler Upgrade Scheme dates. Plain code, unit tested.
- **Evaluator** (`retrofit/agent/evaluator.py`, plus the roof check in `facts.py`): attacks the evidence and sends the analyst back to Zetaris.
  - *No Article 4 on record is not proof*: does this council publish conservation area Article 4s at all? Camden does (11 of 21), Haringey does not (0 of 25), so in Haringey the answer is marked uncertain.
  - *A listing point can sit on the neighbour*: check against the listed outline.
  - *LIDAR noise above 25%*: measure again with a wider margin; if still noisy, the roof numbers are marked rough.
  - *Sources disagree*: planning.data against the council's own decision, both shown.
  - *One cost figure hides the spread*: the national median and the London average solar cost (both DESNZ, from MCS data) are compared and shown as a range.
- **Reporter and critic** (`retrofit/agent/explain.py`): the reporter starts from a draft written from the evidence, and Nemotron rewrites it in plain words. The critic first checks in code (no new numbers, place names kept, status not softened or reversed), then asks Nemotron whether anything was changed, added or dropped. A rejected rewrite goes back with the reasons, at most twice; otherwise the checked draft stays.
- **Money** (`retrofit/money.py`): ranges from dated rows in `retrofit_pg.price_fact`, read through Zetaris: Ofgem price cap for Oct to Dec 2026, DESNZ solar PV costs 2025/26, Boiler Upgrade Scheme installation costs Apr to Jun 2026, export rates reported by Which? in Apr 2026, a typical gas boiler replacement (£3,500, Energy Saving Trust, May 2026) and heat pump life (up to 20 years, MCS). A heat pump is "Worth getting quotes" only if it pays back within its life; otherwise the agent compares it with the new gas boiler you would buy anyway. Assumptions (share of solar used at home, boiler and heat pump efficiency) are stored and shown as assumptions.
- **Memory** (`hmem/`): H-MEM remembers what the owner tells us (heating, gas use, gas grid, "the side lane is our private drive") with provenance, so the next check cites it as *you, date* and does not ask again. A correction supersedes the old note and keeps it as history.

Every step, Zetaris query (with its SQL), model call (with its Nightshift receipt), challenge and memory read or write appears in the trace under the map, and is saved to `runs/`.

## Sponsor technology

| | How we use it | Where |
|---|---|---|
| **Zetaris** (data layer) | Postgres datasource `retrofit_pg` over JDBC; Lightning REST tables for planning.data (per footprint, per council) and PVGIS; `LATERAL VIEW explode` over the JSON; a join between live planning designations and our Article 4 table; 8 reads in parallel per check | `retrofit/zetaris.py`, `retrofit/sources/planning.py`, `retrofit/sources/pvgis.py`, `retrofit/rules.py`, `retrofit/agent/evaluator.py`, `scripts/setup_zetaris.py` |
| **Meterless Nightshift** (AI provider) | Every model call goes to the local runtime, with `meterless-app` and `meterless-scope` headers; the compute receipt (`receipt_id`, routed model) is logged for each call | `retrofit/agent/llm.py` |
| **Meterless H-MEM** (engine) | The Meterless reference implementation, unchanged, behind a small HTTP service; homeowner facts with provenance, supersede on correction, feedback, audit | `hmem/server.ts`, `retrofit/agent/memory.py`, `tests/test_memory_flow.py` |
| **NVIDIA Nemotron** | Nemotron 3.5 Lightning 30B (routed by Nightshift) reads the owner's note, rewrites explanations, and checks rewrites as the critic | `retrofit/agent/explain.py`, `retrofit/agent/run.py` |

## Run it

Needs Docker with Zetaris running locally, Meterless Nightshift with an NVIDIA key, Python 3.12+, Node 20+.

```bash
cp .env.example .env                      # fill in Zetaris key, Nightshift token, a database password, optional Google key
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
docker compose --env-file .env up -d      # cache database on the Zetaris network
.venv/bin/python scripts/setup_zetaris.py # register it in Zetaris
(cd hmem && npm install && npm run setup && npm start &)   # H-MEM on :8790
.venv/bin/python -m retrofit.server       # http://localhost:5173
```

The Google key is optional and only draws the 3D city. Without it the map falls back to OpenStreetMap.

## Sample mode (no keys)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SAMPLE_MODE=true .venv/bin/python -m retrofit.server      # http://localhost:5173
```

No Zetaris, Nightshift, H-MEM or keys: the five sample houses replay their recorded runs, trace included, on an OpenStreetMap base map. `/?replay=<run id>` replays any saved run.

## Tests

```bash
.venv/bin/python -m pytest tests                 # rules, critic, money, H-MEM: gas then oil, off the gas grid, gas use asked once
(cd hmem && npm run conformance)                 # Meterless H-MEM conformance suite on the vendored engine: 13/13
```

## Limits, honestly

- Rules for England; demo data checked for London. Local data quality varies; see [`data/README.md`](data/README.md).
- Houses only. Flats, tenants, building regulations and income based grants are out of scope.
- Article 4 contents are on file only around the sample houses; anywhere else the agent says to check with the council.
- "Faces a road" and "shares a wall" come from OpenStreetMap geometry and can be wrong; the owner can correct them and the agent remembers.
- Nightshift routed every call to Nemotron 3.5 Lightning during our build, and calls took 30 to 70 seconds, with some 502s. The page shows the checked draft at once and swaps in Nemotron's text when it passes the critic; the trace records every failure.
- Not legal advice. For certainty: a Lawful Development Certificate, or ask the council.

## Work from before the hackathon

- `hmem/vendor/` (fetched by `npm run setup`, not committed): the Meterless H-MEM reference implementation and conformance suite, Apache 2.0, used unchanged.
- `smoke_test.py`: the organisers' setup check from the Participant Setup Guide, adapted on 21 Oct 2026 to send the Meterless headers.
- `tools/set_meterless_token.py` (21 Oct 2026): a setup helper that writes the Nightshift token into `.env`.
- Everything else was written during the build window (from 22 Oct 2026).

## Data

Sources, licences and limits: [`data/README.md`](data/README.md).
