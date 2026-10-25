"""Live mode with the sponsor services and public sources down: the agent still answers, says why, and stops in time.

Every service points at a dead local port, so nothing here touches the network or a real Zetaris,
Nightshift or H-MEM, even on a machine with a filled .env. OpenStreetMap is replaced in each test.
"""

import os
import socket
import time

import pytest
import requests

from retrofit import schema
from retrofit.agent import run as run_mod
from retrofit.agent.run import Run, SourceUnavailable
from retrofit.offline import houses
from retrofit.sources import osm, planning
from retrofit.zetaris import Result, ZetarisError

DEAD = "http://127.0.0.1:9"
F = 1106478076
LOCAL = ("127.0.0.1", "localhost", "::1")
_connect = socket.socket.connect


def _local_only(sock, address):
    if isinstance(address, tuple) and address[0] not in LOCAL:
        raise OSError(f"network blocked in tests: {address[0]}")
    return _connect(sock, address)


@pytest.fixture
def dead(monkeypatch):
    """Zetaris, Nightshift, H-MEM and planning.data on a dead port; anything off this machine blocked."""
    for k, v in {"ZETARIS_REST_URL": DEAD + "/api/v1.0", "ZETARIS_API_KEY": "test", "ZETARIS_ORG_ID": "1", "ZETARIS_TIMEOUT": "2",
                 "METERLESS_BASE_URL": DEAD + "/v1", "METERLESS_RUNTIME_TOKEN": "test", "MODEL_TIMEOUT": "2",
                 "HMEM_URL": DEAD, "PLANNING_TIMEOUT": "2", "LOG_STDOUT": "false"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(planning, "BASE", DEAD + "/entity.json")
    monkeypatch.setattr(socket.socket, "connect", _local_only)
    monkeypatch.setattr(run_mod.time, "sleep", lambda s: None)   # model retry pauses; the retries still happen


def _snapshot_house(way):
    return next(dict(h, osm_way=way) for h in houses() if h["house_id"] == f"osm-way-{way}")


@pytest.fixture
def osm_up(monkeypatch):
    monkeypatch.setattr(osm, "house_from_way", _snapshot_house)


@pytest.fixture
def osm_down(monkeypatch):
    def down(*a, **k):
        raise requests.ConnectionError("OpenStreetMap API unreachable")
    monkeypatch.setattr(osm, "house_from_way", down)
    monkeypatch.setattr(osm, "building_at", down)


def _timed_check(run: Run, **kw) -> tuple[dict, float]:
    t = time.time()
    rec = run.check(**kw)
    return rec, time.time() - t


def test_zetaris_down_still_answers_with_a_fallback(dead, osm_up):
    rec, secs = _timed_check(Run(use_model=False, use_memory=False), way=F)
    fb = [e for e in rec["events"] if e["type"] == "fallback" and e.get("about") == "zetaris"]
    assert len(fb) == 1 and fb[0]["status"] == "fallback" and fb[0]["agent_name"] == "analyst"
    assert schema.check_answer(rec["answer"]) == []
    assert rec["answer"]["solar"]["status"] == "allowed" and rec["answer"]["mode"] == "live"
    assert "zetaris" in rec["fallbacks"] and secs < 30


def test_nightshift_down_falls_back_to_the_checked_draft(dead, osm_up):
    rec, secs = _timed_check(Run(use_model=True, use_memory=False), way=F)
    model = [e for e in rec["events"] if e["type"] == "model"]
    assert model and all(not e["ok"] and e.get("error") for e in model)
    assert [e["status"] for e in model][-1] == "failed" and any(e["retry_count"] > 0 for e in model)
    assert any(e["agent_name"] == "reporter" and e["status"] == "fallback" for e in rec["events"] if e["type"] == "thought")
    assert rec["answer"]["solar"]["written_by"] == "code"
    assert schema.check_answer(rec["answer"]) == [] and secs < 60


def test_openstreetmap_down_uses_the_snapshot_outline(dead, osm_down):
    rec, secs = _timed_check(Run(use_model=False, use_memory=False), way=F)
    fb = [e for e in rec["events"] if e["type"] == "fallback" and e.get("about") == "openstreetmap"]
    assert fb and fb[0]["status"] == "fallback"
    assert rec["answer"]["house"]["house_id"] == f"osm-way-{F}" and schema.check_answer(rec["answer"]) == []
    assert secs < 30


def test_openstreetmap_down_for_a_new_house_is_a_clear_error(dead, osm_down):
    run = Run(use_model=False, use_memory=False)
    with pytest.raises(SourceUnavailable, match="OpenStreetMap"):
        run.check(way=1)
    assert any(e["type"] == "fallback" and e["status"] == "failed" for e in run.events)


class _ZetarisWithoutPlanning:
    """Zetaris answers, but its planning.data REST table cannot be built (the endpoint is down)."""
    offline = False

    def __init__(self, on_query=None, on_fallback=None):
        self.on_query = on_query

    def run(self, sql, limit=500, purpose=""):
        if self.on_query:
            self.on_query({"sql": sql, "purpose": purpose, "seconds": 0.0, "rows": None if "planning_data" in sql.lower() else 0,
                           "error": "endpoint did not answer" if "planning_data" in sql.lower() else None})
        if "planning_data" in sql.lower() or "create lightning" in sql.lower():
            raise ZetarisError("REST endpoint did not answer")
        return Result([], [], 0.0)


def _new_house(way):
    h = _snapshot_house(F)
    return dict(h, house_id=f"osm-way-{way}", osm_way=way)


def test_planning_data_down_for_a_new_house_gives_503(dead, monkeypatch):
    from retrofit import server
    monkeypatch.setattr(run_mod, "FallbackZetaris", _ZetarisWithoutPlanning)
    monkeypatch.setattr(osm, "house_from_way", _new_house)
    monkeypatch.setattr(server, "SAMPLE", False)
    run = Run(use_model=False, use_memory=False)
    with pytest.raises(SourceUnavailable):
        run.check(way=2)
    assert any(e["type"] == "error" and e.get("code") == "source_unavailable" and e["status"] == "failed" for e in run.events)
    t = time.time()
    resp = server.check_sync(server.CheckSyncIn(way=2))
    body = __import__("json").loads(resp.body)
    assert resp.status_code == 503 and body["error"]["code"] == "source_unavailable"
    assert body["error"]["message"] and body["error"]["trace_id"] and "Traceback" not in resp.body.decode()
    assert time.time() - t < 30


def test_sponsor_errors_are_logged_with_the_cause(dead, osm_up):
    rec = Run(use_model=True, use_memory=False).check(way=F)
    zfb = next(e for e in rec["events"] if e["type"] == "fallback" and e.get("about") == "zetaris")
    assert "zetaris" in (zfb.get("why") or "").lower() and zfb["output_summary"]
    failed = [e for e in rec["events"] if e["type"] == "model" and not e["ok"]]
    assert failed and all(e.get("error") and e["output_summary"] for e in failed)
    assert set(rec["answer"]["trace"].get("timings") or rec["timings"])
