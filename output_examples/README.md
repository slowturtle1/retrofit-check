# Output examples

Saved answers from live runs on 25 Oct 2026: Zetaris, Nemotron through Meterless Nightshift, and H-MEM all running. The app never returns these files; they show what real runs returned. Each one is the answer JSON (schema in `retrofit/schema.py`) for the request of the same name in `input_examples/`.

- `dartmouth-session-1.json`: house F in Dartmouth Park. The owner gives a yearly electricity use of 3,100 kWh (a demo value, not a real bill).
- `dartmouth-session-2.json`: the same house, next visit, nothing typed. H-MEM recalls the 3,100 kWh with its date and the card uses it.
- `hampstead.json`: planning.data still lists an Article 4 that Camden ended on 9 Jun 2026; the evaluator follows the council.
- `downing.json`: Grade I listed, so the agent stops before the roof survey: listed building consent first.
- `muswell.json`: Haringey has published no conservation area Article 4s, so the answer is "Check with the council".

Each answer carries its `trace_id`; the full trace of that run was written to `logs/trace-<trace_id>.jsonl` on the machine that ran it (logs are not committed).
