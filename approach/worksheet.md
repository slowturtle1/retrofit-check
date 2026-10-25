# Use case worksheet and self score

The one page worksheet from section 21 of the HackOS guide "How to APPROACH Solutioning For Your Track", filled in for Retrofit Check, then the self score from section 13 with one piece of evidence per question, and the five statements from section 22. Filled in on 25 Oct 2026 for the solar MVP.

## Problem

| | |
|---|---|
| Selected track | Solving Fragmented Intelligence (Track 1) |
| Problem statement | We are building an agent that helps a homeowner in England decide whether to get quotes for solar panels by reconciling planning records, the council's Article 4 decisions, national rules, roof measurements and prices through Zetaris, producing one answer with a status, the reason, the rule and its date, rough money, a confidence level, its limits and one next step. |
| Target user | An owner occupier of a house in England who is thinking about solar panels |
| Decision supported | Get quotes now, ask the council first, or leave it (the panels are probably not worth it on this roof) |
| Final output | The solar answer: status, recommendation, reason with clause and in force date, roof yield, cost, yearly value and payback as ranges, confidence, limitations, next step, and the 7 facts about the house with their sources ([`retrofit/schema.py`](../retrofit/schema.py)) |

## Scope

| | |
|---|---|
| What we will build in 144 hours | The solar answer for any house in England in live mode, and for the sample houses with no keys in sample mode; the page with the map and the live trace; a JSON endpoint (`POST /run`); the owner's electricity use remembered in H-MEM; an evaluation on 15 London houses |
| What we will not build | Heat pump and outside wall insulation answers on screen (computed, not shown), flats, tenants, building regulations, income based grants, installer quotes, Article 4 contents for every council, change alerts ("watch this house") |
| Main demo scenario | House F in Dartmouth Park: allowed, worth getting quotes, with the owner's electricity use recalled from an earlier visit; then Hampstead, where planning.data and Camden disagree about an Article 4 and the agent follows Camden |
| Pre-existing components to declare | The vendored Meterless H-MEM reference engine, `smoke_test.py`, `tools/set_meterless_token.py`, `.gitignore`, the local Zetaris and Nightshift installs (README section 16) |

## Data

| | |
|---|---|
| Primary data source | planning.data.gov.uk (listing, conservation areas, Article 4), with Environment Agency LIDAR, PVGIS, OpenStreetMap, legislation.gov.uk, the MCS tables for solar power used at home, Ofgem and DESNZ ([`data/README.md`](../data/README.md)) |
| How it is registered in Zetaris | Postgres datasource `retrofit_pg` (11 tables) over JDBC; Lightning REST tables per house for planning.data and PVGIS, and per council for its Article 4 list |
| Static data size estimate | `samples/cache.sqlite` 53 KB; the whole checkout about 2 MB; the largest tracked file 97 KB |
| Runtime API required | Live mode: yes (planning.data, PVGIS, OpenStreetMap, LIDAR WCS, all keyless). Sample mode: no |
| Fallback sample mode | Yes: `SAMPLE_MODE=true` runs the real agent on a snapshot of the Zetaris tables |
| Licensing or sensitivity concerns | Open Government Licence, ODbL and PVGIS acknowledgement, all stated in `data/README.md`. Google 3D tiles are display only. Owner facts stay in the local H-MEM service; the owner facts in the samples are demo values |

## Sponsor technology

| Sponsor | Requirement | Where it fits in our build |
|---|---|---|
| Zetaris | Required: data layer | Every fact and rule is read through Zetaris; the evaluator registers new REST tables to test a challenge |
| Meterless Engine | Required: at least one in a working feature | H-MEM: the owner's yearly electricity use, recalled on the next visit, compared with the roof's yield, corrected by the owner; test `tests/test_memory_flow.py::test_electricity_use_is_remembered_compared_and_corrected` |
| Meterless Nightshift | Required: primary AI provider | Every model call, with a compute receipt in the trace (`retrofit/agent/llm.py`) |
| NVIDIA | Where it contributes, through Nightshift | Nemotron 3.5 Lightning reads the owner's note, rewrites the answer in plain words and acts as the critic; never decides the status |
| AI coding tool | Your choice | Claude Code; Cursor not used |

## Agents

| Agent | Role | Input | Output | Collaborates with |
|---|---|---|---|---|
| planner | Finds the house, decides what to measure, branches on listed status | Way id or a point, the owner's note | The plan, the owner's facts | memory, analyst |
| analyst | Reads every fact through Zetaris | House id, the plan | Facts with sources | evaluator (answers its challenges) |
| evaluator | Challenges the evidence | The first answer and its facts | Challenges, uncertainty flags | analyst (sends it back to Zetaris) |
| reporter | Writes the checked draft; Nemotron rewrites it | Verdict, facts, money | The answer text | critic |
| critic | Checks the rewrite in code, then with Nemotron | Draft and rewrite | Accept, or reasons to revise; can block | reporter |
| memory | H-MEM: keeps what the owner told us, with dates | Owner facts and corrections | Recalled facts with provenance | planner |

## Collaboration

- [x] Delegation: the planner sends the analyst to Zetaris and skips the roof survey for a listed building
- [x] Critique: the evaluator challenges the evidence and the money (it asks the MCS tables for all three occupancy types); the critic checks every rewrite
- [x] Revision loop: a rejected rewrite goes back to the reporter with the reasons, at most twice
- [x] Shared memory: H-MEM across sessions; one run state shared by all agents
- [x] Branching: listed building, missing council records, a roof with no sunny slope
- [x] Retry: a noisy LIDAR roof is measured again; each model call is retried
- [x] Escalation: "Check with the council" when the records cannot settle it; direct requests when Zetaris cannot reach a source
- [x] Confidence scoring: high, medium or low from the evidence checks (a fixed scale, not a probability)
- [x] Human in the loop: the owner corrects a fact (a private drive is not a road; a new electricity figure) and the answer changes

## Constraints

- [x] Runs from a clean setup with no manual steps (sample mode, README section 5)
- [ ] Runs quickly and predictably: sample mode yes; live mode depends on Nemotron through Nightshift (30 to 70 seconds per call during our build, with some 502 errors), so the page shows the checked draft first
- [x] Repository is light (about 2 MB)
- [x] No hardcoded outputs: sample mode computes every answer again from the snapshot
- [x] No committed API keys (`.env.example` holds placeholders only)
- [x] Logs show how the agent worked (`logs/trace-<run id>.jsonl` and stdout)
- [ ] Sample inputs and outputs included: `input_examples/` and `output_examples/` [lead: tick when they land]
- [x] Zetaris is the data layer, a Meterless Engine works in a feature, Nightshift is the AI provider, and NVIDIA use is documented

## Self score (section 13)

| Question | Score 0 to 2 | Evidence |
|---|---|---|
| Can we explain the problem clearly in 30 seconds? | 2 | The problem sentence in [README section 1](../README.md#1-problem) |
| Do we know who the user is? | 2 | An owner occupier of a house in England ([README section 1](../README.md#1-problem)) |
| Do we have accessible data we can serve through Zetaris? | 2 | Keyless open sources, all read through Zetaris ([`data/README.md`](../data/README.md)) |
| Can we build a working version in 144 hours? | 2 | It runs in live and sample mode; [`eval/README.md`](../eval/README.md) scores it on 15 houses |
| Can it run quickly and predictably? | 1 | Sample mode answers in under a second; live mode waits on Nemotron through Nightshift (30 to 70 seconds per call, some 502 errors), so the checked draft shows first ([README section 14](../README.md#14-limitations)) |
| Do Zetaris and a Meterless Engine have a real role in the build? | 2 | Every fact goes through Zetaris; H-MEM powers the electricity use feature with its own test ([README section 10](../README.md#10-sponsor-technology)) |
| Do agents interact more than once? | 2 | One or two evaluator challenges, each answered by an analyst requery, on every sample house except the listed one (which stops early), and up to two critic rounds per rewrite ([README section 9](../README.md#9-logs-and-traces), `logs/`) |
| Is there critique, validation, or retry? | 2 | Evaluator challenges, critic code checks and Nemotron check, LIDAR measured again ([README section 8](../README.md#8-failure-handling)) |
| Can we show useful output in a 1 to 4 minute demo? | 1 | The captioned demo mode ([`web/demo.js`](../web/demo.js), opened with `?demo=1`) and the video script exist; the video is not recorded yet. Becomes 2 once it is |
| Can we document limitations clearly? | 2 | [README section 14](../README.md#14-limitations) and the limits in [`eval/README.md`](../eval/README.md) |
| Total | 18 of 20 | Strong candidate (16 to 20) |

## Final recommendation (section 22)

| Statement | Yes or no | Evidence |
|---|---|---|
| We understand the problem and the user. | Yes | README section 1 |
| We can access the data reliably through Zetaris. | Yes, with a fallback | planning.data can be slow; the same request then goes direct and the trace says so (README section 8) |
| We can build a narrow working version in 144 hours, with Zetaris, a Meterless Engine and Nightshift integrated. | Yes | Solar only; README sections 5 and 10 |
| We can show agents doing real work. | Yes | The trace: challenges, requeries, critic rounds, with the agent named on every event |
| We can run it cleanly and explain it in a 1 to 4 minute demo. | Yes in sample mode; the video is still to be recorded | README section 5, the video script |
