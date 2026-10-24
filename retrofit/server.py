"""Local web app: the 3D page, a live trace over server-sent events, and saved runs for replay.

Run: .venv/bin/python -m retrofit.server   (http://localhost:5173, the only origin the Google key allows)
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT, USER_AGENT, env

SAMPLE = os.environ.get("SAMPLE_MODE", "").lower() in ("1", "true", "yes")
SAMPLES = ROOT / "samples"
if not SAMPLE:
    from .agent import memory
    from .agent.run import RUNS, Run
else:
    RUNS = SAMPLES

WEB = ROOT / "web"
AREAS = ROOT / "runs" / "areas"
app = FastAPI(title="Retrofit Check")
live: dict[str, dict] = {}

EXAMPLES = [
    {"key": "dartmouth", "label": "Dartmouth Park, NW5", "way": 1106478076, "note": "Ordinary house in a conservation area"},
    {"key": "lady-somerset", "label": "Lady Somerset Road, NW5", "way": 1556408737, "note": "Same kind of street, outside the conservation area"},
    {"key": "hampstead", "label": "Hampstead, NW3", "way": 110514126, "note": "An Article 4 that planning.data still lists"},
    {"key": "downing", "label": "10 Downing Street", "way": None, "lat": 51.50348, "lon": -0.12770, "note": "Grade I listed"},
]


class CheckIn(BaseModel):
    way: int | None = None
    lat: float | None = None
    lon: float | None = None
    label: str | None = None
    note: str | None = None
    heating: str | None = None
    gas_kwh: float | None = None
    use_model: bool = True


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/config.js")
def config_js():
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    return Response(f"window.GOOGLE_MAPS_API_KEY = {json.dumps(key)};\n", media_type="application/javascript", headers={"Cache-Control": "no-store"})


def _sample_for(body) -> Path | None:
    """Sample mode: the recorded run for the house that was asked for."""
    index = json.loads((SAMPLES / "index.json").read_text())
    for x in index:
        if body.way and x.get("way") == body.way:
            return SAMPLES / x["file"]
        if body.lat is not None and x.get("lat") is not None and abs(x["lat"] - body.lat) < 0.0004 and abs(x["lon"] - body.lon) < 0.0006:
            return SAMPLES / x["file"]
    return None


@app.get("/api/examples")
def examples():
    if SAMPLE:
        return [{k: x.get(k) for k in ("key", "label", "way", "lat", "lon", "note")} for x in json.loads((SAMPLES / "index.json").read_text())]
    return EXAMPLES


@app.get("/api/mode")
def mode():
    return {"sample": SAMPLE}


@app.post("/api/check")
def start_check(body: CheckIn):
    if not body.way and (body.lat is None or body.lon is None):
        raise HTTPException(400, "give an OSM way or a point")
    if SAMPLE:
        f = _sample_for(body)
        if not f:
            raise HTTPException(404, "Sample mode has only the recorded houses. Pick one of the examples.")
        rec = json.loads(f.read_text())
        run_id = "sample-" + uuid.uuid4().hex[:6]
        q: queue.Queue = queue.Queue()
        live[run_id] = {"queue": q}

        def play():
            prev = 0.0
            q.put({"t": 0, "type": "note", "text": f"Sample mode: replaying recorded run {rec['run_id']} (no Zetaris, Nightshift or keys needed)"})
            for e in rec["events"]:
                time.sleep(min(0.8, max(0.03, float(e.get("t", 0)) - prev)))
                prev = float(e.get("t", 0))
                q.put(e)
            q.put(None)

        threading.Thread(target=play, daemon=True).start()
        return {"run_id": run_id}
    q = queue.Queue()
    run = Run(emit=q.put, use_model=body.use_model)
    live[run.id] = {"queue": q, "events": run.events}

    def work():
        try:
            run.check(way=body.way, lat=body.lat, lon=body.lon, label=body.label, note=body.note, heating=body.heating, gas_kwh=body.gas_kwh)
        except Exception as e:  # shown in the trace; the page stays usable
            run.emit({"type": "error", "text": str(e)[:300]})
        finally:
            q.put(None)

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": run.id}


@app.get("/api/runs/{run_id}/events")
def events(run_id: str):
    if run_id not in live:
        raise HTTPException(404, "no live run with that id")
    q = live[run_id]["queue"]

    def stream():
        while True:
            e = q.get()
            if e is None:
                yield "event: end\ndata: {}\n\n"
                live.pop(run_id, None)
                return
            yield f"data: {json.dumps(e, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/runs")
def runs():
    out = []
    for p in sorted(RUNS.glob("*.json"), reverse=True):
        try:
            r = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        out.append({"file": p.stem, "run_id": r["run_id"], "label": r["label"], "seconds": r["seconds"],
                    "summary": "; ".join(f"{v['measure']}: {v['headline']}" for v in r["result"]["verdicts"]),
                    "model_texts": sum(1 for t in r["texts"].values() if t.get("writer") == "nemotron")})
    return out


@app.get("/api/runs/{name}")
def run_file(name: str):
    p = RUNS / f"{Path(name).name}.json"
    if not p.exists():
        matches = list(RUNS.glob(f"{Path(name).name}*.json"))
        if not matches:
            raise HTTPException(404, "no such run")
        p = matches[0]
    return JSONResponse(json.loads(p.read_text()))


@app.get("/api/area/{entity}")
def area(entity: int):
    """A protected area for the map: the area itself and a thin band along its edge (planning.data, cached)."""
    from pyproj import Transformer
    from shapely.geometry import mapping, shape
    from shapely.ops import transform

    AREAS.mkdir(parents=True, exist_ok=True)
    f = AREAS / f"{entity}.geojson"
    if SAMPLE and (SAMPLES / "areas" / f"{entity}.geojson").exists():
        f = SAMPLES / "areas" / f"{entity}.geojson"
    if not f.exists():
        r = requests.get(f"https://www.planning.data.gov.uk/entity/{entity}.geojson", headers={"User-Agent": USER_AGENT}, timeout=120)
        r.raise_for_status()
        f.write_text(r.text)
    gj = json.loads(f.read_text())
    geom = shape(gj["geometry"] if "geometry" in gj else gj["features"][0]["geometry"])
    to = Transformer.from_crs(4326, 27700, always_xy=True).transform
    back = Transformer.from_crs(27700, 4326, always_xy=True).transform
    m = transform(to, geom).simplify(0.8)
    band = m.difference(m.buffer(-2.5))
    props = gj.get("properties", {})
    return {"name": props.get("name"), "fill": mapping(transform(back, m)), "edge": mapping(transform(back, band))}


class FeedbackIn(BaseModel):
    memory_id: str
    kind: str


@app.post("/api/feedback")
def feedback(body: FeedbackIn):
    if SAMPLE:
        raise HTTPException(400, "feedback needs the live H-MEM service")
    if body.kind not in ("helpful", "not_helpful", "wrong"):
        raise HTTPException(400, "kind must be helpful, not_helpful or wrong")
    return memory.feedback(body.memory_id, body.kind)


app.mount("/static", StaticFiles(directory=WEB), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "5173")), log_level="warning")
