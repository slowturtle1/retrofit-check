"""H-MEM in our own feature: the homeowner says gas, later corrects it to oil, and the answer follows.

Starts the H-MEM service (Meterless reference engine) on a spare port with throwaway state.
Skipped when Node or the vendored engine is missing.
"""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path

import pytest
import requests

from retrofit import rules

ROOT = Path(__file__).resolve().parent.parent
HMEM = ROOT / "hmem"
D = json.loads((Path(__file__).parent / "house_d_facts.json").read_text())


@pytest.fixture(scope="module")
def hmem_url():
    if not shutil.which("npx") or not (HMEM / "vendor/hmem/src/index.ts").exists():
        pytest.skip("H-MEM engine not set up. Run first: cd hmem && npm install && npm run setup")
    state = tempfile.mkdtemp(prefix="hmem-test-")
    port = "8799"
    proc = subprocess.Popen(["npx", "tsx", "server.ts"], cwd=HMEM, env={**os.environ, "HMEM_PORT": port, "HMEM_STATE": state},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if requests.get(url + "/health", timeout=1).ok:
                break
        except requests.RequestException:
            time.sleep(0.25)
    else:
        os.killpg(proc.pid, signal.SIGTERM)
        pytest.fail("H-MEM did not start")
    os.environ["HMEM_URL"] = url
    yield url
    os.killpg(proc.pid, signal.SIGTERM)  # npx starts node as a child; stop the whole group
    shutil.rmtree(state, ignore_errors=True)


def test_gas_then_oil_changes_the_answer_and_cites_the_owner(hmem_url):
    from retrofit.agent import memory

    house = "osm-way-test"
    memory.remember(house, "heating", "Heating: gas", "you told us")
    first = memory.recall(house)
    assert first[0]["content"] == "Heating: gas"

    second = memory.remember(house, "heating", "Heating: oil", "you told us")
    memory.remember(house, "off_gas_grid", "Off the gas grid: yes", "you told us")
    assert second["superseded"]["content"] == "Heating: gas"          # the old note is kept as history
    live = memory.recall(house)
    live = [m for m in memory.recall(house) if m["kind"] == "heating"]
    assert [m["content"] for m in live] == ["Heating: oil"]           # only the correction is used

    audit = requests.get(f"{hmem_url}/audit/{second['superseded']['id']}", timeout=5).json()["history"]
    assert any(e["action"] in ("update", "supersede", "updated") or "supersededBy" in json.dumps(e) for e in audit)

    said_on = live[0]["learnedAt"][:10]
    before = rules.evaluate(D, heating="gas", today=date(2026, 10, 24))
    after = rules.evaluate(D, heating="oil", off_gas_grid=True, today=date(2026, 10, 24))
    hp_before = next(v for v in before["verdicts"] if v["measure"] == "heat_pump")
    hp_after = next(v for v in after["verdicts"] if v["measure"] == "heat_pump")
    assert hp_before["grants"][0] == "bus-standard" and hp_after["grants"][0] == "bus-off-gas"
    assert {"fact": "current heating", "value": "oil", "source": "you"} in hp_after["facts"]
    assert {"fact": "gas grid", "value": "not connected", "source": "you"} in hp_after["facts"]
    assert said_on == date.today().isoformat()


def test_electricity_use_is_remembered_compared_and_corrected(hmem_url):
    """D4, the H-MEM feature. Session 1: the owner gives yearly electricity use and the solar card compares it with
    what the roof makes. Session 2: nothing typed; the agent recalls it with its date and does not ask again.
    Session 3: the owner corrects it; the old value is kept as history and the card changes."""
    from retrofit.agent import memory
    from retrofit.agent.run import Run

    way, house, today = 1106478076, "osm-way-1106478076", date.today()
    said = today.strftime("%-d %b %Y")

    first = Run(offline=True, use_memory=True).check(way=way, elec_kwh=3100)["answer"]
    assert first["solar"]["usage"]["text"] == f"Your roof could make about 94% of the 3,100 kWh you use a year (you told us, {said})."
    fact = next(f for f in first["house_facts"] if f["key"] == "electricity_use")
    assert fact["value"] == "3,100 kWh a year" and fact["source"] == "you told us" and fact["date"] == today.isoformat()

    run = Run(offline=True, use_memory=True)
    second = run.check(way=way)
    assert second["answer"]["solar"]["usage"] == first["solar"]["usage"]
    assert any(e["type"] == "memory_recall" and e["agent_name"] == "memory" and e["target_agent"] == "planner" for e in second["events"])
    assert any("No need to ask again" in (e.get("text") or "") for e in second["events"])

    run = Run(offline=True, use_memory=True)
    third = run.check(way=way, elec_kwh=4500)["answer"]
    assert third["solar"]["usage"]["share_pct"] == 65 and "4,500 kWh" in third["solar"]["usage"]["text"]
    assert any("keep the old note as history" in (e.get("text") or "") for e in run.events)
    live = [m for m in memory.recall(house) if m["kind"] == "elec_use"]
    assert [m["content"] for m in live] == ["Electricity use: 4500 kWh a year"]
