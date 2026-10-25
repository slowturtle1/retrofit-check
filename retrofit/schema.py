"""The two contracts other code and the tests build on: one trace event, and the answer JSON.

Trace event: every event the agent emits carries the fields in EVENT_FIELDS. `type` stays for the
page; the rest says which agent acted, on what, for whom, and how it went. `trace_id` is the run id.

Answer: one JSON object per check (ANSWER_FIELDS), solar only in this version. The recommendation
and status come from code (rules.py, money.py); the text lines may come from Nemotron after the critic.
Confidence is a fixed scale from the evidence checks, not a measured probability.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

VERSION = "1"
AGENTS = ("planner", "analyst", "evaluator", "reporter", "critic", "memory")
STATUSES = ("success", "retrying", "needs_revision", "blocked", "fallback", "failed")
EVENT_FIELDS = ("ts", "trace_id", "run_id", "t", "type", "agent_name", "action", "input_summary", "output_summary",
                "target_agent", "confidence", "retry_count", "status")

ANSWER_FIELDS = ("schema", "trace_id", "run_id", "mode", "seconds", "question", "house", "house_facts", "solar", "owner", "trace")
HOUSE_FACTS = ("listed", "conservation_area", "article_4", "road_walls", "roof", "sun", "electricity_use")   # fixed order
SOLAR_FIELDS = ("status", "status_text", "recommendation", "confidence", "limitations", "next_step", "facts", "rules",
                "numbers", "usage", "lines", "written_by", "checked_by", "uncertain")
LINES = ("one", "why", "get", "cost")
QUESTION = "Is my house eligible for solar panels?"

# One level per fixed score, so the page and the tests agree on the words.
CONFIDENCE = {"high": 0.9, "medium": 0.6, "low": 0.3}
UNSURE = {"article4_unknown", "article4_coverage_unknown", "listed_point_only"}   # the legal answer itself is open
ROUGH = {"lidar_noisy", "no_sunny_roof", "article4_ended_but_listed"}             # the answer stands, a number or a source is weak


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _short(x, n: int = 160) -> str | None:
    return None if x in (None, "", [], {}) else str(x)[:n]


def _model_agent(role: str) -> str:
    return "critic" if role.startswith("critic") else "reporter" if role.startswith("writer") else "planner"


def _retry(role: str) -> int:
    m = re.search(r"retry (\d+)", role or "")
    return int(m.group(1)) if m else (1 if (role or "").endswith("_repair") else 0)


def _defaults(e: dict) -> dict:
    """What each event type means in contract terms. An emitter may set any field itself."""
    t, ok = e["type"], e.get("ok", True) is not False
    if t == "start":
        return dict(agent_name="planner", action="start_run", output_summary="run started")
    if t in ("tool_start", "tool_end"):
        done = t == "tool_end"
        return dict(agent_name="analyst", action=e.get("tool", "tool") + (":end" if done else ":start"), input_summary=_short(e.get("source")),
                    output_summary=_short(e.get("error") or (f"{e['seconds']} s" if done and "seconds" in e else None)),
                    status="success" if ok else "failed")
    if t == "house":
        return dict(agent_name="analyst", action="found_house", output_summary=_short(f"{e.get('house_id')} {e.get('label')}"))
    if t == "memory_recall":
        return dict(agent_name="memory", action="recall", target_agent="planner", output_summary=f"{len(e.get('memories') or [])} memories")
    if t == "memory_write":
        return dict(agent_name="memory", action="remember", input_summary=_short(e.get("kind")), output_summary=_short(e.get("content")))
    if t == "intake":
        return dict(agent_name="planner", action="read_owner_note", input_summary=_short(e.get("note")), output_summary=_short(e.get("understood")))
    if t == "zetaris":
        return dict(agent_name="analyst", action="zetaris_query", input_summary=_short(e.get("purpose") or e.get("sql")),
                    output_summary=_short(f"error: {e['error']}" if e.get("error") else f"{e.get('rows')} rows in {e.get('seconds')} s"),
                    status="failed" if e.get("error") else "success")
    if t == "challenge":
        return dict(agent_name="evaluator", action="challenge", target_agent="analyst", input_summary=_short(e.get("about")),
                    output_summary=_short(e.get("text")), status="needs_revision")
    if t == "requery":
        return dict(agent_name="analyst", action="requery", target_agent="evaluator", input_summary=_short(e.get("about")),
                    output_summary=_short(e.get("text")), status="success" if ok else "fallback")
    if t == "decision":
        return dict(agent_name="planner", action=e.get("branch") or "decide", output_summary=_short(e.get("text")))
    if t == "critic":
        return dict(agent_name="critic", action="review_text", target_agent="reporter", input_summary=_short(e.get("measure")),
                    output_summary=_short("; ".join(e.get("problems") or []) or "accepted"), retry_count=max(int(e.get("round", 1)) - 1, 0),
                    status="success" if ok else "needs_revision")
    if t == "model":
        role = e.get("role") or ""
        return dict(agent_name=_model_agent(role), action="model_call", input_summary=_short(role),
                    output_summary=_short(e.get("error") or f"{e.get('routed_model') or e.get('model')} receipt {e.get('receipt_id')}"),
                    retry_count=_retry(role), status="success" if ok else "failed")
    if t in ("answer", "answer_update"):
        a = e.get("answer") or {}
        s = a.get("solar") or {}
        return dict(agent_name="reporter", action="write_answer" if t == "answer" else "rewrite_answer",
                    output_summary=_short(" | ".join(x for x in (s.get("status_text"), s.get("recommendation")) if x)),
                    confidence=(s.get("confidence") or {}).get("score"))
    if t == "done":
        return dict(agent_name="planner", action="finish", output_summary=_short(e.get("summary")))
    if t == "error":
        return dict(agent_name="planner", action=e.get("code") or "error", output_summary=_short(e.get("text")), status="failed")
    return dict(agent_name=e.get("agent") or "planner", action=t, output_summary=_short(e.get("text")),
                status="fallback" if e.get("fallback") else "success")


def event(e: dict, run_id: str) -> dict:
    """Fill the contract fields on one event; fields the emitter set win."""
    d = {"ts": now_iso(), "trace_id": run_id, "run_id": run_id, "input_summary": None, "output_summary": None,
         "target_agent": None, "confidence": None, "retry_count": 0, "status": "success"}
    d.update(_defaults(e))
    if e.get("agent"):
        d["agent_name"] = e["agent"]
    return {**d, **{k: v for k, v in e.items() if k != "agent"}}


def check_event(e: dict) -> list[str]:
    """Contract problems in one event (empty list = fine). Used by tests."""
    out = [f"missing {k}" for k in EVENT_FIELDS if k not in e]
    if e.get("agent_name") not in AGENTS:
        out.append(f"agent_name {e.get('agent_name')!r} not in {AGENTS}")
    if e.get("status") not in STATUSES:
        out.append(f"status {e.get('status')!r} not in {STATUSES}")
    if e.get("target_agent") is not None and e["target_agent"] not in AGENTS:
        out.append(f"target_agent {e['target_agent']!r} not in {AGENTS}")
    c = e.get("confidence")
    if c is not None and not (isinstance(c, (int, float)) and 0 <= c <= 1):
        out.append(f"confidence {c!r} not between 0 and 1")
    if not isinstance(e.get("retry_count"), int) or e["retry_count"] < 0:
        out.append(f"retry_count {e.get('retry_count')!r} not a whole number")
    return out


def confidence(v: dict) -> dict:
    """high: rules and facts agree and nothing is rough; medium: the answer stands but a number or source is weak;
    low: the legal answer itself is open (unknown Article 4, council coverage, listing found as a point only)."""
    unsure = set(v["uncertain"]) & UNSURE or v["status"] == "check_with_council"
    rough = set(v["uncertain"]) & ROUGH or any(f["fact"] == "sources disagree" for f in v["facts"])
    level = "low" if unsure else "medium" if rough else "high"
    return {"score": CONFIDENCE[level], "level": level, "because": sorted(set(v["uncertain"])) or ["sources agree"]}


def check_answer(a: dict) -> list[str]:
    """Contract problems in one answer (empty list = fine). Used by tests and by /api/v1/check."""
    out = [f"missing {k}" for k in ANSWER_FIELDS if k not in a]
    s = a.get("solar") or {}
    out += [f"solar: missing {k}" for k in SOLAR_FIELDS if k not in s]
    out += [f"solar.lines: missing {k}" for k in LINES if k not in (s.get("lines") or {})]
    for f in s.get("facts") or []:
        out += [f"fact {f.get('fact')!r}: missing {k}" for k in ("fact", "value", "source", "date") if k not in f]
    for r in s.get("rules") or []:
        out += [f"rule {r.get('id')!r}: missing {k}" for k in ("id", "clause", "in_force", "source_url") if not r.get(k)]
    if (s.get("confidence") or {}).get("level") not in CONFIDENCE:
        out.append("solar.confidence.level not high, medium or low")
    if [f.get("key") for f in a.get("house_facts") or []] != list(HOUSE_FACTS):
        out.append(f"house_facts keys not {HOUSE_FACTS}")
    if s and not s.get("next_step"):
        out.append("solar.next_step empty")
    return out
