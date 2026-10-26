# Evaluation

A small labelled test: 15 real London houses, expected answers written and frozen before any system ran, three systems compared.

## Method

1. **Cases** (`label.py` → `cases.json`, frozen with a SHA-256 hash; `run.py` refuses to score if the file changed). Fifteen houses chosen to cover the situations a homeowner meets: four in Dartmouth Park Conservation Area (Camden), four on Lady Somerset Road nearby, two in Hampstead where an old Article 4 once covered roof solar, four listed buildings (a Hampstead house, Keats House, the Freud Museum, 10 Downing Street) and one in Muswell Hill (Haringey).
2. **Ground truth from a second source.** The agent reads planning.data; the expected answers come from **Historic England**: the National Heritage List for England for listing (a listed polygon touching the footprint, or a listed point within 10 m on the same street) and Historic England's conservation areas dataset. Article 4 facts come from Camden's own decision (27 May 2025). Two labelling corrections were made before any system ran, and both are in `label.py`: NHLE points sit slightly outside building outlines, so points within 10 m count; a point within 10 m on another street (68 and 70 Highgate Road, next to a Lady Somerset Road house) belongs to a neighbour and is not counted.
3. **Expected answers** follow the GPDO as a homeowner meets it: listed → listed building consent for all three; in a conservation area → solar and heat pump allowed, outside wall insulation needs planning permission; otherwise all three allowed. In a council that publishes no conservation area Article 4s (Haringey), the answer should also say "ask the council".
4. **Scoring** is by route, on the status the owner sees: allowed (with or without conditions), planning permission, or listed building consent. "Check with the council" counts as right where the case expects the owner to ask the council, and as deferred anywhere else. *Confidently wrong* means a wrong answer given with no uncertainty flag; no answer at all counts as wrong, not as confidently wrong.

## Systems

| System | What it is |
|---|---|
| **Retrofit Check** | The agent as shipped: rules plus the evaluator's challenges, live through Zetaris |
| **No evaluator** | The same rules on the same Zetaris facts, but planning.data taken at face value (no council end dates for Article 4, no challenges) |
| **Nemotron alone** | Nemotron through Meterless Nightshift, given only the street, postcode district and borough |

## Results (25 Oct 2026, solar only)

Since 25 Oct the app answers one question, whether a house can have solar panels, so the evaluation scores the solar answer the owner sees: 15 answers. The cases and their hash are unchanged.

| System | Right | Wrong | Confidently wrong | No answer | "Ask the council" where needed |
|---|---|---|---|---|---|
| Retrofit Check | 15 / 15 | 0 | 0 | 0 | 1 / 1 |
| No evaluator | 13 / 15 | 2 | 2 | 0 | 0 / 1 |
| Nemotron alone | 9 / 15 | 6 | 2 | 4 | 0 / 1 |

- **Retrofit Check** answers Muswell Hill with "Check with the council": Haringey has published no conservation area Article 4 directions, so a missing record proves nothing. That is the expected answer for this case, so it counts as right. All 15 ran live through Zetaris, with no fallback.
- **No evaluator** says both Hampstead houses need planning permission for solar, because planning.data still lists the 2010 Article 4 (A4Ha1) with no end date; Camden ended it on 9 Jun 2026. It also answers Muswell Hill with no warning.
- **Nemotron alone** said Keats House, a listed building, could take panels without consent, and said one Hampstead house needs planning permission. It gave no usable answer for four houses (three replies without the answer line, one Nightshift 502). It never said "ask the council".
- The same scores on the local snapshot, with no services: `.venv/bin/python eval/run.py --sample` (Retrofit Check 14 of 14, no evaluator 12 of 14; house D, the vicarage dropped as an example on 25 Oct, is not in the snapshot). `tests/test_eval_sample.py` runs this in CI.
- Per case answers: `results.json` (live) and `results-sample.json` (snapshot).

Until 25 Oct the evaluation scored all three upgrades (45 answers): Retrofit Check 45 of 45, no evaluator 43 of 45, Nemotron alone 28 of 45. Those runs are in the git history of `results.json`.

## Limits

- Fifteen houses is small, and the expected answers are decided by designations. The site specific part (which roof slope faces a road in a conservation area, and how much the roof makes) is not scored.
- Historic England's conservation area data is "indicative"; the definitive boundary is the council's. Where the two disagree near an edge, a house can be scored against the wrong boundary.
- Since 26 Oct the agent also checks Historic England's listed building outlines, the same service the ground truth uses for listing, so the listing half of the comparison is no longer independent; the Article 4 and conservation area halves still are.
- The labelling rule and the agent's rules share the same reading of the GPDO; what the test checks is whether the facts behind each answer are right and whether conflicts and gaps in the data are caught.

Run again: `.venv/bin/python eval/run.py` (needs the live stack; Nemotron alone needs Nightshift). Score stored answers again without running: `--rescore`.
