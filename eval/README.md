# Evaluation

A small labelled test: 15 real London houses, expected answers written and frozen before any system ran, three systems compared.

## Method

1. **Cases** (`label.py` → `cases.json`, frozen with a SHA-256 hash; `run.py` refuses to score if the file changed). Fifteen houses chosen to cover the situations a homeowner meets: four in Dartmouth Park Conservation Area (Camden), four on Lady Somerset Road nearby, two in Hampstead where an old Article 4 once covered roof solar, four listed buildings (a Hampstead house, Keats House, the Freud Museum, 10 Downing Street) and one in Muswell Hill (Haringey).
2. **Ground truth from a second source.** The agent reads planning.data; the expected answers come from **Historic England**: the National Heritage List for England for listing (a listed polygon touching the footprint, or a listed point within 10 m on the same street) and Historic England's conservation areas dataset. Article 4 facts come from Camden's own decision (27 May 2025). Two labelling corrections were made before any system ran, and both are in `label.py`: NHLE points sit slightly outside building outlines, so points within 10 m count; a point within 10 m on another street (68 and 70 Highgate Road, next to a Lady Somerset Road house) belongs to a neighbour and is not counted.
3. **Expected answers** follow the GPDO as a homeowner meets it: listed → listed building consent for all three; in a conservation area → solar and heat pump allowed, outside wall insulation needs planning permission; otherwise all three allowed. In a council that publishes no conservation area Article 4s (Haringey), the answer should also say "ask the council".
4. **Scoring** is by route: allowed (with or without conditions), planning permission, or listed building consent. "Check with your council" counts as deferred. *Confidently wrong* means wrong with no uncertainty flag on that answer.

## Systems

| System | What it is |
|---|---|
| **Retrofit Check** | The agent as shipped: rules plus the evaluator's challenges, live through Zetaris |
| **No evaluator** | The same rules on the same Zetaris facts, but planning.data taken at face value (no council end dates for Article 4, no challenges) |
| **Nemotron alone** | Nemotron through Meterless Nightshift, given only the street, postcode district and borough |

## Results (25 Oct 2026)

| System | Right | Wrong | Confidently wrong | "Ask the council" where needed |
|---|---|---|---|---|
| Retrofit Check | 45 / 45 | 0 | 0 | 1 / 1 |
| No evaluator | 43 / 45 | 2 | 2 | 0 / 1 |
| Nemotron alone | 28 / 45 | 17 (8 answered wrongly, 9 not answered) | 8 | 0 / 1 |

- **No evaluator** says both Hampstead houses need planning permission for solar, because planning.data still lists the 2010 Article 4 with no end date; Camden ended it on 9 Jun 2026. It also answers Muswell Hill with no warning, although Haringey has published no conservation area Article 4s.
- **Nemotron alone** answered 12 of the 15 houses (Nightshift returned 502 for three) and got 28 of those 36 answers right. It said Keats House and the Freud Museum, both listed, could take panels and a heat pump without consent, and it treated two houses outside the conservation area as if they were inside it. It never said "ask the council". The same model is useful in the agent for plain language; it is not a source of facts.
- Per case answers: `results.json`.

## Limits

- Fifteen houses is small, and the expected answers are decided by designations. The hard, site specific part (which walls face a road, so where a heat pump may go) is not scored.
- Historic England's conservation area data is "indicative"; the definitive boundary is the council's. Where the two disagree near an edge, a house can be scored against the wrong boundary.
- The labelling rule and the agent's rules share the same reading of the GPDO; what the test checks is whether the facts behind each answer are right and whether conflicts and gaps in the data are caught.

Run again: `.venv/bin/python eval/run.py` (needs the live stack; Nemotron alone needs Nightshift).
