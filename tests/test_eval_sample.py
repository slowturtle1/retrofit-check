"""The frozen evaluation, solar only, on the local snapshot: Retrofit Check against Historic England, no services needed.

The live run (eval/run.py, results in eval/results.json) also scores Nemotron alone through Nightshift.
"""

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["LOG_STDOUT"] = "false"


def _eval_module():
    spec = importlib.util.spec_from_file_location("eval_run", ROOT / "eval" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SAMPLE = True
    return mod


def _score(system: str) -> dict:
    from retrofit.offline import houses
    ev = _eval_module()
    have = {h["house_id"] for h in houses()}
    cases = ev.load_cases()          # refuses to run if cases.json changed after it was frozen
    run = {"retrofit-check": ev.run_agent, "no-evaluator": ev.run_no_evaluator}[system]
    answers = {c["id"]: run(c) if c["id"] in have else {"skipped": "not in the sample snapshot"} for c in cases}
    return ev.score(cases, answers)


def test_retrofit_check_gets_every_snapshot_house_right():
    s = _score("retrofit-check")
    assert s["answers"] >= 14 and s["right"] == s["answers"] and s["confidently_wrong"] == 0
    assert s["flag_raised"] == s["flag_expected"] == 1


def test_without_the_evaluator_the_ended_article_4_is_missed():
    s = _score("no-evaluator")
    assert s["confidently_wrong"] >= 1 and s["right"] < s["answers"]
