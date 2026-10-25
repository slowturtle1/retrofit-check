"""The programmatic way in: the server started the way a judge starts it, in sample mode, driven with plain HTTP."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

from retrofit import schema

ROOT = Path(__file__).resolve().parent.parent
F = 1106478076


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = {**os.environ, "SAMPLE_MODE": "true", "PORT": str(port), "HOST": "127.0.0.1", "LOG_STDOUT": "false", "GOOGLE_MAPS_API_KEY": ""}
    started = time.time()
    proc = subprocess.Popen([sys.executable, "-m", "retrofit.server"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    url = f"http://127.0.0.1:{port}"
    try:
        while time.time() - started < 60:
            if proc.poll() is not None:
                pytest.fail("server exited: " + proc.stderr.read().decode()[-400:])
            try:
                if requests.get(url + "/api/mode", timeout=1).ok:
                    break
            except requests.RequestException:
                time.sleep(0.2)
        yield {"url": url, "startup_s": time.time() - started}
    finally:
        proc.terminate()
        proc.wait(10)


def _post(server, path, body=None, data=None):
    return requests.post(server["url"] + path, json=body, data=data, headers={"content-type": "application/json"}, timeout=60)


def test_startup_under_30_seconds(server):
    assert server["startup_s"] < 30
    assert requests.get(server["url"] + "/api/mode", timeout=5).json()["sample"] is True


def test_run_returns_the_answer_contract(server):
    r = _post(server, "/run", {"way": F})
    assert r.status_code == 200
    a = r.json()
    assert schema.check_answer(a) == [] and a["mode"] == "sample"
    assert a["house"]["house_id"] == f"osm-way-{F}" and a["trace_id"]


def test_v1_check_matches_run(server):
    a, b = _post(server, "/run", {"way": F}).json(), _post(server, "/api/v1/check", {"way": F}).json()
    assert a["trace_id"] != b["trace_id"]
    for k in ("status", "recommendation", "lines", "numbers"):
        assert a["solar"][k] == b["solar"][k]


@pytest.mark.parametrize("body,data", [
    (None, "{"),                                   # not JSON
    ({"way": "abc"}, None),                        # wrong type
    ({}, None),                                    # no house at all
    ({"lat": 10.0, "lon": 0.0}, None),             # outside England
    ({"way": F, "elec_kwh": 0}, None),             # impossible electricity use
    ({"way": F, "elec_kwh": 200000}, None),
])
def test_malformed_input_gives_400(server, body, data):
    r = _post(server, "/run", body, data)
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "bad_request" and err["message"] and "Traceback" not in r.text


def test_unknown_house_gives_404_with_trace_id(server):
    r = _post(server, "/run", {"way": 1})
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found" and "sample" in err["message"].lower() and err.get("trace_id")


def test_owner_electricity_use_reaches_the_answer(server):
    a = _post(server, "/run", {"way": F, "elec_kwh": 3100}).json()
    u = a["solar"]["usage"]
    assert u and u["elec_kwh"] == 3100 and str(u["share_pct"]) in u["text"]
