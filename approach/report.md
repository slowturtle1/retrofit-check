# Approach scorecard

Commit 8c2581c (uncommitted changes), 26 Oct 2026 12:31 UTC, without Tier 4 (live). Source: `approach/requirements.yaml`, run with `make approach`.

**0 gaps in Tiers 1 to 3.** 10 not run, 19 manual (open), 1 manual (done), 1 n/a, 64 pass (of 95 requirements).

| Criterion | Points | Pass | Gaps (Tiers 1 to 3) | Manual open | Not run |
|---|---|---|---|---|---|
| Impact | 30 | 7 of 10 | 0 | 3 | 0 |
| Technical | 20 | 26 of 29 | 0 | 3 | 0 |
| Innovation | 15 | 11 of 12 | 0 | 0 | 1 |
| Demo | 15 | 0 of 8 | 0 | 6 | 2 |
| Product and UX | 10 | 8 of 10 | 0 | 2 | 0 |
| Sponsor technology | 10 | 7 of 14 | 0 | 2 | 4 |
| Gate (pass or fail) | gate | 6 of 12 | 0 | 3 | 3 |

Collaboration design checklist (guide section 9): 8 of 9 proven by a passing check.

## Impact (30 points)

| Id | Requirement | Tier | Status | Evidence or detail | Owner |
|---|---|---|---|---|---|
| I4 | The README, deck and demo name a real user, a real problem and the track it answers | manual | manual (open) | README header, deck slide 1, video segment 0:00 to 0:20 | C |
| I7 | The value can be explained in 30 seconds (red flag "you cannot explain the value clearly") | manual | manual (open) | video segment 0:00 to 0:20 and deck problem slide | C |
| I8 | The deck covers the problem and target users, the solution, and future enhancements (heat pump, outside walls, watch this house) | manual | manual (open) | deck v3 slides | C |
| I1 | The README states the problem in one sentence in the guide's format (We are building an agent that helps [user] solve [problem] by [capability] using [data], producing [output]) | 1 | pass | README.md matches 1 patterns | C |
| I10 | The self score (guide section 13) is at least 16 of 20, honest, with one evidence link per question | 1 | pass | 18 of 20, every question with evidence | C |
| I2 | The problem sentence is about the solar MVP (Is my house eligible for solar panels?) | 1 | pass | README.md matches 1 patterns | C |
| I3 | One user, one decision, one data slice, one strong output (homeowner in England, solar panels, one page answer) | 1 | pass | README.md matches 2 patterns | C |
| I5 | Track fit for Fragmented Intelligence: several small sources that disagree, registered in Zetaris, and the answer shows where they disagree | 2 | pass | 2 tests pass | A |
| I6 | Every answer leads to a decision the owner can act on (a recommendation and a next step) | 2 | pass | 1 tests pass | A |
| I9 | The decision worksheet (guide section 21) is filled in the repository | 1 | pass | all 15 fields of section 21 filled | C |

## Technical (20 points)

| Id | Requirement | Tier | Status | Evidence or detail | Owner |
|---|---|---|---|---|---|
| T25 | Data is allowed for prototype use and holds no sensitive personal data; owner facts in samples are demo values and say so | manual | manual (open) | licence column in data/README.md; owner facts labelled demo values | C |
| T26 | The README is honest; every capability claimed is in the code, data is described as live or cached, nothing is called production ready | manual | manual (open) | C7 pass over README, deck and form texts | C |
| T28 | Full validation from a fresh clone (Disqualification Checklist section 14), with Zetaris and Nightshift stopped and then running, twice on Monday | manual | manual (open) | B8 log, Mon 26 Oct about 14:00 and 17:00 | B |
| T1 | Runs from a fresh clone with an empty environment and no manual steps (sample mode, every cached house answers) | 2 | pass | fresh clone of HEAD, empty environment: 15 houses answered in 0.1 s (1 s with startup) | B |
| T10 | A model failure retries, then falls back with a logged reason (the checked draft stays) | 2 | pass | 1 tests pass | A |
| T11 | A programmatic way in (POST /run), structured input and output, no interactive input; the UI does not block it | 2 | pass | 3 tests pass | A |
| T12 | No hardcoded outputs; answers differ across inputs, nothing reads output_examples/ at runtime, no input maps to a saved output | 2 | pass | 1 tests pass; no agent code reads output_examples/ or saved runs (server.py serves labelled replays only) | A |
| T13 | Metamorphic: change one cached fact and the right answer changes (listed, a solar Article 4, a north roof, LIDAR noise, electricity use) | 2 | pass | 10 tests pass | B |
| T14 | Logs are generated during the run, saved to logs/ and printed to stdout, and match the input being processed | 2 | pass | 2 tests pass | A |
| T15 | Every trace event carries timestamp, trace_id, agent_name, action, input and output summary, target_agent, confidence, retry_count and status | 2 | pass | 2 tests pass | A |
| T16 | At least three sample inputs and their real saved outputs are in input_examples/ and output_examples/ | 1 | pass | 4 inputs, 5 saved outputs, every output passes the answer contract | A |
| T17 | The repository is light; no raw archives, model checkpoints, videos or large database files | 1 | pass | git objects 2.5 MB, largest tracked file samples/cache.sqlite (172 KB) | B |
| T18 | data/README.md documents every source with URL, licence, subset, record count, Zetaris registration, how to regenerate, and limits | 1 | pass | 14 source sections, seven fields each | C |
| T19 | The table counts stated in README.md and data/README.md match the database schema and the sample snapshot | 1 | pass | retrofit_pg has 11 tables (db/init), the sample snapshot 14 | C |
| T2 | SAMPLE_MODE=true runs without Zetaris, Nightshift or credentials, runs real agent logic on cached data (not a replay), and the README documents it | 2 | pass | 1 tests pass; README.md matches 2 patterns | C |
| T20 | The README covers setup, usage and dependencies, agent roles, examples and limitations, and how to set up Zetaris and Nightshift | 1 | pass | README.md matches 7 patterns | C |
| T21 | The README has exact commands, including a curl call on a file in input_examples/ | 1 | pass | README.md matches 2 patterns | C |
| T22 | The entry point exists and is documented (python -m retrofit.server, POST /run) | 1 | pass | README.md matches 2 patterns; retrofit/server.py, requirements.txt | C |
| T23 | Nothing installs or downloads after the app starts; sample mode makes no network call for the shipped houses | 2 | pass | 1 tests pass; no installs or downloads of packages in retrofit/ | A |
| T24 | No local GPU and no training at runtime (no torch, tensorflow or CUDA dependencies) | 1 | pass | no torch, tensorflow, jax or CUDA packages | B |
| T27 | The README states limitations honestly in its own section | 1 | pass | '14. Limitations': 13 points | C |
| T29 | Judges can use their own inputs: in sample mode any house in England is fetched from the public sources (no keys), kept on the machine and read back with the same SQL; OpenStreetMap down gives a 503 | 2 | pass | 9 tests pass | A |
| T3 | Judges can test their own inputs; the sample snapshot holds every sample house and every evaluation house (house D, the vicarage dropped on 25 Oct, excepted) | 1 | pass | 15 houses: all 6 sample houses and 14 evaluation houses (osm-way-460070558 left out on purpose) | A |
| T4 | Startup takes under 30 seconds | 2 | pass | 1 tests pass | B |
| T5 | Runs are bounded; the model budget is at most 300 s and each step is timed against the guide's budget (total 5 to 10 minutes) | 2 | pass | 3 tests pass | A |
| T6 | Every call to Zetaris, Nightshift, H-MEM and public APIs has a timeout | 1 | pass | 14 HTTP calls in retrofit/, every one with a timeout | A |
| T7 | Retries and agent turns are capped so a run cannot hang (model retries at most 2, at most two rewrites, no unbounded loops) | 1 | pass | model retries 1, rewrite rounds 1, 2, no unbounded loops | A |
| T8 | The agent still answers when Zetaris, Nightshift, OpenStreetMap or planning.data is down, with a fallback event, in bounded time | 2 | pass | 5 tests pass | A |
| T9 | Malformed input returns 400 with a validation message; an unknown house returns 404 with a clear message; no stack traces | 2 | pass | 8 tests pass | A |

## Innovation (15 points)

| Id | Requirement | Tier | Status | Evidence or detail | Owner |
|---|---|---|---|---|---|
| N7 | Agents write structured messages to shared memory (H-MEM, remembered with the date the owner said it) | 4 | not run | Tier 4: run make approach-live on this Mac | A |
| N1 | Agents interact more than once and in both directions; not a fixed one pass chain | 2 | pass | 3 tests pass | A |
| N10 | The final answer has traceable evidence (every rule with clause, in force date and URL; every fact names its source) | 2 | pass | 2 tests pass | A |
| N11 | The README shows the architecture as a diagram with the loops (Mermaid), not an ASCII chain | 1 | pass | Mermaid diagram with 5 labelled edges | C |
| N12 | The README has an agents table with a "can block or retry" column | 1 | pass | README.md matches 1 patterns | C |
| N2 | The planner delegates subtasks based on the input (a listed building skips the roof survey) | 2 | pass | 1 tests pass | A |
| N3 | A specialist agent uses data or tools (the analyst reads every fact through Zetaris) | 2 | pass | 1 tests pass | A |
| N4 | An evaluator critiques the specialist's output | 2 | pass | 1 tests pass | A |
| N5 | The agent revises after critique (every challenge is followed by a second Zetaris query) | 2 | pass | 1 tests pass | A |
| N6 | A critic flags unsupported claims and can block the writer (role authority) | 2 | pass | 7 tests pass | A |
| N8 | The workflow branches on confidence (unsure data gives Check with the council and Ask the council first) | 2 | pass | 2 tests pass | A |
| N9 | A fallback path activates when data or an API fails | 2 | pass | 2 tests pass | A |

## Demo (15 points)

| Id | Requirement | Tier | Status | Evidence or detail | Owner |
|---|---|---|---|---|---|
| D1 | The demo video is 1 to 4 minutes long | 4 | not run | Tier 4: run make approach-live on this Mac | her |
| D4 | The video script has six segments in 3:30 with her lines, a shot list, the demo path (Hampstead source conflict, house F electricity recall) and the recording checklist | 4 | not run | Tier 4: run make approach-live on this Mac | C |
| D2 | The video shows a real run, the main workflow, the key features, and Zetaris and Meterless in action (Zetaris queries, the H-MEM feature, Nightshift calls) | manual | manual (open) | video; script segments 0:50 to 2:50 | her |
| D3 | The video shows at least one collaboration moment in the logs (a challenge and second query, the critic blocking, a fallback) | manual | manual (open) | video segment 1:40 to 2:20 | her |
| D5 | Audio is clear and screen text is readable | manual | manual (open) | playback check before upload | her |
| D6 | The video link opens in a private browser window without asking for access | manual | manual (open) | private window test, Tue 27 Oct | her |
| D7 | The demo path is not hardcoded and works more than once (the captioned demo mode runs on a real sample mode run or a labelled replay) | manual | manual (open) | web/demo.js (?demo=1) | A |
| D8 | The deck covers the agent workflow or architecture and the technical stack | manual | manual (open) | deck v3 slides | C |

## Product and UX (10 points)

| Id | Requirement | Tier | Status | Evidence or detail | Owner |
|---|---|---|---|---|---|
| U8 | The page is intuitive and accessible (AA contrast in both themes, keyboard, labels, works at 360 px) | manual | manual (open) | accessibility pass on web/ | A |
| U9 | The deck shows real product screenshots | manual | manual (open) | deck v3 product slide | C |
| U1 | Every answer carries evidence, confidence, limitations and a next step | 2 | pass | 1 tests pass | A |
| U10 | Answers are right against an independent source (the frozen 15 house evaluation, solar only, Historic England) | 3 | pass | 2 tests pass; Retrofit Check 15 of 15, 0 confidently wrong; no-evaluator 13 of 15, nemotron-alone 9 of 15; cases hash unchanged | B |
| U2 | An unsure answer never says Allowed; it says Check with the council, with the reason on the card | 2 | pass | 2 tests pass | A |
| U3 | The output is not mostly generic text; no card line is identical on two houses with different facts, and every line holds a fact of its house | 3 | pass | 2 tests pass | A |
| U4 | Wording rules on every answer: the not advice line, money marked as an estimate, the certificate line on allowed answers, lines that start with a capital and have no nested brackets | 3 | pass | 5 tests pass | A |
| U5 | Every possible solar answer (status and recommendation) has a fixture and reads right | 3 | pass | 1 tests pass | B |
| U6 | Status and recommendation agree; no Probably not worth it next to a payback range | 2 | pass | 1 tests pass | A |
| U7 | The owner's yearly electricity use is compared with what the roof makes, says who said it and when, and a correction changes the card | 2 | pass | 2 tests pass | A |

## Sponsor technology (10 points)

| Id | Requirement | Tier | Status | Evidence or detail | Owner |
|---|---|---|---|---|---|
| S13 | The form texts explain each sponsor (Zetaris, Meterless, Cursor, NVIDIA) and finish with what was unique | 4 | not run | Tier 4: run make approach-live on this Mac | C |
| S2 | Zetaris answers live and the datasources are registered (retrofit_pg, PLANNING_DATA, PVGIS) | 4 | not run | Tier 4: run make approach-live on this Mac | A |
| S3 | A Meterless Engine (H-MEM) powers a real feature and its test passes (owner's electricity use remembered across sessions, correction supersedes) | 4 | not run | Tier 4: run make approach-live on this Mac | A |
| S4 | The H-MEM reference conformance suite passes (13 of 13) | 4 | not run | Tier 4: run make approach-live on this Mac | A |
| S11 | Cursor use is stated exactly as it happened, or as not used; never invented | manual | manual (open) | README sponsor section; her 20 minute Cursor task if she does it | C |
| S12 | The deck says how Zetaris and Meterless were used and what was unique about the sponsor use | manual | manual (open) | deck v3 stack slide | C |
| S14 | Colab links in the README if agents run in Google Colab | 1 | n/a | does not apply; nothing runs in Colab | B |
| S1 | Zetaris is the data layer and load bearing; every fact the agent uses comes through a Zetaris read first | 2 | pass | 1 tests pass | A |
| S10 | The README sponsor section covers: the Zetaris role, the H-MEM feature and its test, how the app connects to Nightshift, Nemotron, Cursor, and what was unique | 1 | pass | README.md matches 8 patterns | C |
| S5 | Meterless Nightshift is the primary AI provider; every model call goes through it and real requests pass | 2 | pass | 1 tests pass; retrofit/agent/llm.py is the only model client, pointed at Nightshift (METERLESS_BASE_URL) | A |
| S6 | NVIDIA Nemotron is pinned (not meterless/auto) and the model that answered is logged for every request | 1 | pass | pinned to nvidia/nemotron-3.5-lightning-30b-a3b in .env.example and retrofit/agent/llm.py | B |
| S7 | The models the README names match the models in the logs | 1 | pass | README names nvidia/nemotron-3.5-lightning-30b-a3b, the model in the recorded receipts | C |
| S8 | Each sponsor call has a timeout and a fallback; sponsor errors are logged clearly | 2 | pass | 1 tests pass | A |
| S9 | Sponsor settings come from environment variables | 1 | pass | Zetaris, Nightshift and H-MEM settings all come from environment variables | B |

## Gate (pass or fail)

| Id | Requirement | Tier | Status | Evidence or detail | Owner |
|---|---|---|---|---|---|
| G1 | The GitHub repository is public by the deadline, so judges open it without asking for access | 4 | not run | Tier 4: run make approach-live on this Mac | her |
| G4 | Pre-existing components are declared in the submission form (vendored H-MEM reference, smoke_test.py, tools/set_meterless_token.py) | 4 | not run | Tier 4: run make approach-live on this Mac | C |
| G7 | README, slide deck, form texts and video script name the same track | 4 | not run | Tier 4: run make approach-live on this Mac | C |
| G12 | No keys, tokens or personal data are visible in the demo video or the slide deck (Nightshift console, /config.js, terminal) | manual | manual (open) | frame by frame check of the video around any terminal; deck screenshots | her |
| G2 | All four components are submitted on HackOS (demo video, slide deck, public repository with README, sponsor technology explanation) | manual | manual (open) | HackOS submission form, Tue 27 Oct | her |
| G8 | Submitted on HackOS before 27 Oct 23:45 UTC, with hours to spare (target 18:00 UTC) | manual | manual (open) | HackOS submission timestamp | her |
| G5 | One account per person; the team roster is final (solo, 1 of 1) before the first submission is created; she is the primary contact | manual | manual (done) | HackOS team Buccies 1/1 since 25 Oct 16:50 GMT (Igor removed on her request) | her |
| G10 | No secret file is tracked (.env, *.pem, *.key, secrets/, credentials/), and .gitignore covers them | 1 | pass | no secret files tracked; .gitignore covers .env, .env.*, *.pem, *.key, secrets/, credentials/ | B |
| G11 | .env.example holds placeholders only | 1 | pass | every key, token and password is empty or a placeholder | B |
| G3 | Work from before 22 Oct 00:00 UTC is declared in the README | 1 | pass | README.md matches 3 patterns | C |
| G6 | The README names exactly one primary track (Track 1, Solving Fragmented Intelligence) | 1 | pass | README.md matches 1 patterns | C |
| G9 | No secret is anywhere in the git history (API keys, Nightshift token, NVIDIA key, private keys, passwords) | 1 | pass | 60 commits scanned, no secret found | B |

## Guide section 22: can we say yes to all five?

- Not yet: "We understand the problem and the user." (I1, I3, I4, I7; open: I4, I7)
- Not yet: "We can access the data reliably through Zetaris." (S1, S2, T8; open: S2)
- Not yet: "We can build a narrow working version in 144 hours, with Zetaris, a Meterless Engine and Nightshift integrated." (S1, S3, S5, T1; open: S3)
- Yes: "We can show agents doing real work." (N1, N2, N4, N5, N6, N8)
- Not yet: "We can run it cleanly and explain it in a 1 to 4 minute demo." (T1, T2, D1, D2; open: D1, D2)

## What judges should be able to say

- Not yet: "I understand the problem this solves and who it's for." (I1, I3, I4; open: I4)
- Not yet: "It clearly answers the track it was submitted to." (G6, G7, I5; open: G7)
- Yes: "I can run it without manual setup." (T1, T2, T20, T21)
- Not yet: "Zetaris and Meterless do real work in this build." (S1, S3, S5; open: S3)
- Yes: "The agents have distinct responsibilities." (N12, T15, N1)
- Yes: "The logs prove real collaboration, not a linear chain." (N1, N5, N6, T14)
- Yes: "The output is something the user could act on." (I6, U1, U2)
- Not yet: "The team made thoughtful trade-offs and was honest about limits." (T26, T27, U10; open: T26)
