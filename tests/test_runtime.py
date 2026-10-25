"""Runs stay bounded: the model has a time budget, every step is timed, and each step fits the guide's runtime budget."""

import inspect
import os
import time

from retrofit.agent import explain
from retrofit.agent.run import Run
from retrofit.offline import houses

os.environ["LOG_STDOUT"] = "false"
F = 1106478076
# APPROACH guide section 11, in seconds: data load 30 to 90, planning 30 to 60, analysis 1 to 4 min,
# critique 1 to 3 min, output 30 to 90, total 5 to 10 min. Upper ends, per step of our trace.
BUDGET = {"find_house": 90, "memory": 30, "facts": 90, "rules": 60, "evaluator": 240, "reporter": 90, "writer_and_critic": 180}
TOTAL = 600


def test_model_budget_is_at_most_300_s(monkeypatch):
    assert inspect.signature(Run).parameters["model_budget_s"].default <= 300
    monkeypatch.setattr(explain, "rewrite", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called after the budget")))
    run = Run(offline=True, model_budget_s=0)
    rec = run.check(way=F)
    assert run.write_and_check(rec["result"], rec["result"]["verdicts"][0]) is None
    assert any(e["status"] == "fallback" and "time" in (e.get("text") or "").lower() for e in run.events)


def test_every_step_is_timed_and_within_budget():
    rec = Run(offline=True).check(way=F)
    t = rec["answer"]["trace"]["timings"]
    assert {"find_house", "memory", "facts", "rules", "evaluator", "reporter"} <= set(t), t
    over = {k: v for k, v in t.items() if v > BUDGET.get(k, TOTAL)}
    assert not over, over
    assert sum(t.values()) <= TOTAL and rec["seconds"] <= TOTAL
    done = next(e for e in rec["events"] if e["type"] == "done")
    assert done["timings"] == rec["timings"]


def test_every_sample_house_answers_in_seconds():
    for h in houses():
        way = int(h["house_id"].rsplit("-", 1)[1]) if h["house_id"].startswith("osm-way-") else None
        started = time.time()
        Run(offline=True).check(way=way, lat=None if way else h["lat"], lon=None if way else h["lon"])
        assert time.time() - started < 10, h["label"]
