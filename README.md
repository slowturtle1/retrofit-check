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

## Six sample houses

| House | Input | Output | What it shows |
|---|---|---|---|
| Dartmouth Park, NW5: corner house, not listed, Dartmouth Park Conservation Area since 1 Jun 1992 | OSM way 1106478076, gas boiler, 12,000 kWh of gas a year | Solar allowed (south slope 27°, 2.9 kWp, about 2,916 kWh a year; £4,600 to £6,100, pays back in 8 to 19 years): *Worth getting quotes*. Heat pump allowed if conditions are met, only on the east wall (the other two face roads), one unit; £3,600 to £8,100 after the £7,500 grant, saves £110 to £300 a year: *Worth it mainly if your boiler needs replacing soon* (about £1,900 more than a new gas boiler, back in about 9 years). Outside wall insulation **needs planning permission** (GPDO Part 1 Class A, A.2(a)); alternatives: inside insulation, £548 householder application: *Ask the council first* | The main case: two yes, one no, and why |
| Lady Somerset Road, NW5, about 600 m away | OSM way 1556408737 | All three allowed; walls only if the finish looks the same | Same kind of street outside the conservation area |
| Hampstead, NW3 | OSM way 110514126 | Solar allowed (about 4,696 kWh a year) | planning.data still lists Article 4 A4Ha1 (2010, covered roof solar) with no end date; Camden ended it on 9 Jun 2026. The agent shows both and follows the council |
| 10 Downing Street | a tap on the roof | All three need listed building consent (Grade I since 14 Jan 1970) | The planner stops early: no roof survey for a listed building |
| Muswell Hill, N10 (Haringey) | a tap on the roof | Answers marked uncertain | The evaluator finds Haringey has published no conservation area Article 4s, so a missing record proves nothing |
| Trees over the roof, NW5 | OSM way 827708528 | Solar *Probably not worth it for this house*: only about 0.9 kWp of usable roof | The evaluator finds half the roof reading is trees, measures again with a wider margin, and still marks the roof numbers rough |

All six run without keys in sample mode (see below); the recorded live runs are in [`samples/`](samples/).

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
| **NVIDIA Nemotron** | The model is pinned (`METERLESS_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b`); it reads the owner's note, rewrites explanations, and checks rewrites as the critic. Every call logs the model that answered from the Nightshift receipt | `retrofit/agent/llm.py`, `retrofit/agent/explain.py`, `retrofit/agent/run.py` |

## Run it

Needs Docker with Zetaris running locally, Meterless Nightshift with an NVIDIA key, Python 3.12+, Node 20+. Zetaris and Nightshift are set up as in the organisers' [Participant Setup Guide](https://docs.google.com/document/d/1_d3osxbXZRpp4Ln80w6Obc5xx06SmkIMrgp6BOj0Ofc/edit). Every sponsor call has a time limit (`ZETARIS_TIMEOUT`, `MODEL_TIMEOUT`) and a fallback: planning.data and PVGIS go direct if Zetaris cannot reach them, and the checked draft stays if Nightshift does not answer.

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
git clone https://github.com/slowturtle1/retrofit-check && cd retrofit-check
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SAMPLE_MODE=true .venv/bin/python -m retrofit.server      # http://localhost:5173
```

No `.env`, Zetaris, Nightshift, H-MEM or keys. The agent runs its real logic (planner, rules, evaluator challenges, money, the critic's code checks) on a snapshot of the Zetaris tables for the six sample houses in `samples/cache.sqlite`: the same SQL it sends to Zetaris, answered locally. Without Nightshift the explanations are the checked drafts from the rules. A house that is not in the snapshot gets a clear message; any house works in live mode. The map falls back to OpenStreetMap without a Google key.

Separately, `/?replay=<run id>` replays a recorded live run (with Nemotron's texts and receipts) from `samples/*.json`, labelled as a replay. The same replays are built into a static page in [`docs/`](docs/) (`scripts/build_static.py`) that needs no server: open it with `python3 -m http.server -d docs` or on GitHub Pages.

## Use it from code

```bash
curl -s -X POST http://localhost:5173/api/v1/check -H 'content-type: application/json' \
  -d '{"way": 1106478076, "heating": "gas", "gas_kwh": 12000}'
```

Input: an OpenStreetMap way id (`way`) or a point on the roof (`lat`, `lon`); optional `heating` (gas, oil, lpg, coal, electric, heat_pump), `gas_kwh` (a year, from the bill), `note` (free text the agent reads), `use_model` (true to have Nemotron rewrite the explanations; it can take minutes). Output: for each upgrade the status, recommendation, plain text, money ranges, rules with clause and date, facts with sources, uncertainty flags, and a trace summary (Zetaris queries, challenges, model calls with receipts). Errors come back as `{"error": {"code": ..., "message": ...}}` with a 4xx or 5xx status, never a stack trace. The page itself uses `POST /api/check` with a live event stream.

## Logs

Every run writes `logs/trace-<run id>.jsonl` (one JSON event per line: agent steps, decisions, challenges and re-checks, each Zetaris query with its purpose, row count and time, H-MEM reads and writes, each model call with the model that answered and its Nightshift receipt) and prints one line per event to stdout (`LOG_STDOUT=false` turns that off). The full record of each live run is saved in `runs/`.

## Tests

```bash
(cd hmem && npm install && npm run setup)        # once: fetches the Meterless H-MEM reference engine (Apache 2.0) into hmem/vendor
.venv/bin/python -m pytest tests                 # 22 tests: rules, critic, money, and the H-MEM feature
(cd hmem && npm run conformance)                 # Meterless H-MEM conformance suite on the vendored engine: 13/13
```

The two H-MEM tests in `tests/test_memory_flow.py` start the H-MEM service and check our own feature end to end: the owner says gas, then corrects it to oil with no gas grid connection, and the heat pump grant changes from £7,500 to £9,000 with the source "you"; and gas use given once is recalled on the next check without asking again. Without the setup step they are skipped with a message saying so.

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
