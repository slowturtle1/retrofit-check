"""What the trace proves, over fresh sample mode runs of every house in samples/cache.sqlite.

Sample mode runs the real agent on a snapshot of the Zetaris tables, with the network blocked here,
so these tests need no Zetaris, Nightshift, H-MEM or keys. Contract: retrofit/schema.py.
"""

import json
import os
import re
import socket
from pathlib import Path

import pytest

from retrofit import schema
from retrofit.agent import explain, llm
from retrofit.agent.run import LOGS, Run
from retrofit.offline import houses

ROOT = Path(__file__).resolve().parent.parent
os.environ["LOG_STDOUT"] = "false"

# Which Zetaris read each fact comes from (purpose text in rules.load and the evaluator).
FACT_READS = {
    "listed": "Protected areas", "conservation-area": "Protected areas", "article-4": "Protected areas",
    "sources disagree": "Protected areas", "area-of-outstanding-natural-beauty": "Protected areas",
    "national-park": "Protected areas", "world-heritage-site": "Protected areas",
    "best roof plane": "Solar yield", "LIDAR noise": "LIDAR roof reading",
}
HOUSE_FACT_READS = {"listed": "Protected areas", "conservation_area": "Protected areas", "article_4": "Protected areas",
                    "road_walls": "walls face a road", "roof": "Roof planes", "sun": "Solar yield"}


def _no_network(*a, **k):
    raise OSError("network blocked in sample mode tests")


def _check(h: dict) -> dict:
    way = int(h["house_id"].rsplit("-", 1)[1]) if h["house_id"].startswith("osm-way-") else None
    return Run(offline=True).check(way=way, lat=None if way else h["lat"], lon=None if way else h["lon"], label=h["label"])


@pytest.fixture(scope="session")
def runs() -> dict:
    """One fresh sample mode run per cached house, keyed by label, with sockets blocked."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket.socket, "connect", _no_network)
        mp.setattr(socket, "create_connection", _no_network)
        out = {h["label"]: _check(h) for h in houses()}
    assert len(out) >= 6, "samples/cache.sqlite should hold at least the six sample houses"
    return out


def _by_label(runs, part):
    return next(r for k, r in runs.items() if part.lower() in k.lower())


def _first(events, pred):
    return next((i for i, e in enumerate(events) if pred(e)), None)


# ---------------------------------------------------------------- contract

def test_every_event_meets_the_contract(runs):
    bad = [(label, e["type"], p) for label, r in runs.items() for e in r["events"] for p in schema.check_event(e)]
    assert not bad, bad[:10]


def test_every_event_carries_the_run_as_trace_id(runs):
    for r in runs.values():
        assert {e["trace_id"] for e in r["events"]} == {r["run_id"]}
        assert all(re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$", e["ts"]) for e in r["events"])


def test_every_answer_meets_the_contract(runs):
    for label, r in runs.items():
        assert schema.check_answer(r["answer"]) == [], label
        for e in r["events"]:
            if e["type"] in ("answer", "answer_update"):
                assert schema.check_answer(e["answer"]) == [], (label, e["type"])


def test_the_answer_is_solar_only(runs):
    for label, r in runs.items():
        assert [v["measure"] for v in r["result"]["verdicts"]] == ["solar"], label
        assert set(r["texts"]) == {"solar"}, label


# ---------------------------------------------------------------- agents working together

def _handoffs(r):
    return [e for e in r["events"] if e["target_agent"] and e["target_agent"] != e["agent_name"]]


def test_at_least_two_named_agents_hand_off(runs):
    for label, r in runs.items():
        assert len({e["agent_name"] for e in r["events"]}) >= 2, label
        if any(e["type"] == "challenge" for e in r["events"]):
            assert _handoffs(r), label


@pytest.mark.pending("A4")
def test_the_listed_stop_names_who_it_hands_to(runs):
    r = _by_label(runs, "Downing")
    assert _handoffs(r), "the planner's listed_stop decision (and the answer) carry no target_agent"


def test_evaluator_and_analyst_talk_both_ways(runs):
    talked = 0
    for label, r in runs.items():
        pairs = {(e["agent_name"], e["target_agent"]) for e in r["events"] if e["target_agent"]}
        if any(e["type"] == "challenge" for e in r["events"]):
            assert {("evaluator", "analyst"), ("analyst", "evaluator")} <= pairs, label
            talked += 1
    assert talked >= 4


def test_every_challenge_is_followed_by_a_second_query(runs):
    for label, r in runs.items():
        ev = r["events"]
        for i, e in enumerate(ev):
            if e["type"] == "challenge":
                later = [x for x in ev[i + 1:] if x["type"] == "requery" and x.get("about") == e.get("about")]
                assert later, (label, e.get("about"))
                assert any(x["type"] == "zetaris" for x in ev[i + 1:ev.index(later[0])]), (label, "requery without a Zetaris read")


def test_every_fact_used_came_through_zetaris_first(runs):
    for label, r in runs.items():
        ev = r["events"]
        answer_at = _first(ev, lambda e: e["type"] == "answer")
        read = [e.get("purpose") or "" for e in ev[:answer_at] if e["type"] == "zetaris" and not e.get("error")]
        s = r["answer"]["solar"]
        for f in s["facts"]:
            if f["source"] in ("you told us", "you") or f["fact"] == "roof":
                continue
            assert f["fact"] in FACT_READS, f"{label}: fact {f['fact']!r} has no known Zetaris read; add it to FACT_READS"
            assert any(FACT_READS[f["fact"]].lower() in p.lower() for p in read), (label, f["fact"])
        for f in r["answer"]["house_facts"]:
            if f["key"] in HOUSE_FACT_READS:
                assert any(HOUSE_FACT_READS[f["key"]].lower() in p.lower() for p in read), (label, f["key"])


def test_listed_house_skips_the_roof_survey(runs):
    r = _by_label(runs, "Downing")
    branches = [e.get("branch") for e in r["events"] if e["type"] == "decision"]
    s = r["answer"]["solar"]
    assert "listed_stop" in branches
    assert s["status"] == "needs_consent" and not s["numbers"].get("kwp")


def test_sources_that_disagree_take_their_own_branch(runs):
    r = _by_label(runs, "Hampstead")
    assert any(e["type"] == "decision" and e.get("branch") == "sources_disagree" for e in r["events"])
    assert r["answer"]["solar"]["confidence"]["level"] != "high"


def test_unsure_data_says_check_with_the_council_never_allowed(runs):
    unsure = 0
    for label, r in runs.items():
        s = r["answer"]["solar"]
        if s["confidence"]["level"] == "low":
            unsure += 1
            assert s["status"] == "check_with_council" and s["status_text"] == "Check with the council", label
            assert s["recommendation"] == "Ask the council first", label
            assert not re.search(r"\ballowed\b", s["status_text"] + " " + s["lines"]["one"], re.I), label
    assert unsure >= 1, "Muswell Hill should be unsure (Haringey coverage)"


def test_answers_differ_across_houses(runs):
    ones = [r["answer"]["solar"]["lines"]["one"] for r in runs.values()]
    assert len(set(ones)) == len(ones), ones


def test_every_answer_has_evidence_confidence_limits_and_a_next_step(runs):
    for label, r in runs.items():
        s = r["answer"]["solar"]
        assert s["rules"], label
        assert all(f["source"] for f in s["facts"]), label
        assert s["confidence"]["text"] and s["limitations"] and s["next_step"], label
        assert any("not legal or financial advice" in x.lower() for x in s["limitations"]), label


def test_allowed_answers_name_the_certificate(runs):
    for label, r in runs.items():
        s = r["answer"]["solar"]
        if s["status"].startswith("allowed"):
            assert "lawful development certificate" in s["next_step"].lower(), label


def test_not_worth_it_never_shows_a_payback(runs):
    for label, r in runs.items():
        s = r["answer"]["solar"]
        if s["recommendation"] == "Probably not worth it for this house":
            assert not s["numbers"].get("payback_years"), label


def test_sample_mode_reads_the_snapshot_not_the_network(runs):
    for label, r in runs.items():
        z = [e for e in r["events"] if e["type"] == "zetaris"]
        assert len(z) >= 8 and all(e.get("source") == "local snapshot (sample mode)" for e in z), label


# ---------------------------------------------------------------- logs

def _logged_run(capfd, monkeypatch):
    monkeypatch.setenv("LOG_STDOUT", "true")
    rec = _check(next(h for h in houses() if "Dartmouth" in h["label"]))
    return rec, capfd.readouterr().out


def test_logs_are_written_to_logs_and_stdout(capfd, monkeypatch):
    rec, out = _logged_run(capfd, monkeypatch)
    lines = (LOGS / f"trace-{rec['run_id']}.jsonl").read_text().splitlines()
    assert len(lines) == len(rec["events"])
    assert {json.loads(x)["trace_id"] for x in lines} == {rec["run_id"]}
    assert out.count(f"[{rec['run_id']}]") == len(rec["events"])
    assert "zetaris" in out and "evaluator" in out


@pytest.mark.pending("A4")
def test_stdout_has_one_whole_line_per_event(capfd, monkeypatch):
    """The parallel Zetaris reads print from several threads; print() writes the text and the newline separately."""
    for _ in range(5):
        rec, out = _logged_run(capfd, monkeypatch)
        printed = [x for x in out.splitlines() if x.startswith(f"[{rec['run_id']}]")]
        assert len(printed) == len(rec["events"])


def test_recorded_live_runs_name_the_model_and_keep_a_receipt():
    calls = []
    for p in sorted((ROOT / "samples").glob("*.json")):
        d = json.loads(p.read_text())
        if isinstance(d, dict):
            calls += [(p.name, e) for e in d.get("events", []) if e.get("type") == "model"]
    assert calls, "no recorded live run with model calls in samples/"
    for name, e in calls:
        if e.get("ok"):
            assert "nemotron" in str(e.get("routed_model") or e.get("model")).lower() and e.get("receipt_id"), name
        else:
            assert e.get("error"), name


# ---------------------------------------------------------------- the critic and failures

@pytest.fixture
def dartmouth(runs):
    r = _by_label(runs, "Dartmouth")
    return r, r["result"]["verdicts"][0]


def test_the_critic_blocks_a_rewrite_that_adds_a_number(dartmouth, monkeypatch):
    rec, v = dartmouth
    monkeypatch.setattr(explain, "rewrite", lambda result, v, draft, on_call, feedback=None: {"one": draft["one"], "why": draft["why"] + " It saves £999 a year."})
    run = Run(offline=True)
    assert run.write_and_check(rec["result"], v) is None
    critic = [e for e in run.events if e["type"] == "critic"]
    assert len(critic) == 2 and all(e["agent_name"] == "critic" and e["status"] == "needs_revision" and e["target_agent"] == "reporter" for e in critic)
    assert critic[1]["retry_count"] == 1


@pytest.mark.pending("A5")
def test_a_blocked_rewrite_is_logged_as_blocked(dartmouth, monkeypatch):
    rec, v = dartmouth
    monkeypatch.setattr(explain, "rewrite", lambda result, v, draft, on_call, feedback=None: {"one": draft["one"], "why": draft["why"] + " It saves £999 a year."})
    run = Run(offline=True)
    run.write_and_check(rec["result"], v)
    assert any(e["agent_name"] == "critic" and e["status"] == "blocked" for e in run.events)


@pytest.mark.pending("A5")
def test_a_model_failure_is_logged_as_a_fallback(dartmouth, monkeypatch):
    rec, v = dartmouth
    def down(*a, **k):
        raise llm.LLMError("Nightshift unreachable")
    monkeypatch.setattr(explain, "rewrite", down)
    run = Run(offline=True)
    assert run.write_and_check(rec["result"], v) is None
    assert any(e["agent_name"] == "reporter" and e["status"] == "fallback" for e in run.events)


def test_an_unknown_house_gets_a_clear_message():
    run = Run(offline=True)
    with pytest.raises(LookupError, match="(?i)sample"):
        run.check(way=1)
    end = [e for e in run.events if e["type"] == "tool_end"]
    assert end and end[-1]["status"] == "failed" and end[-1]["output_summary"]
