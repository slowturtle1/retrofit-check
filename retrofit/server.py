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
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT, USER_AGENT, env

from .agent import memory
from .agent.run import RUNS, Run

SAMPLE = os.environ.get("SAMPLE_MODE", "").lower() in ("1", "true", "yes")
SAMPLES = ROOT / "samples"

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


class CheckSyncIn(CheckIn):
    use_model: bool = False   # the model step can take minutes; callers opt in


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/config.js")
def config_js():
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    return Response(f"window.GOOGLE_MAPS_API_KEY = {json.dumps(key)};\n", media_type="application/javascript", headers={"Cache-Control": "no-store"})


def _unused_sample_for(body) -> Path | None:
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
        from .offline import houses
        cached = {h["house_id"] for h in houses()}
        return [x for x in json.loads((SAMPLES / "index.json").read_text()) if x.get("house_id") in cached or not x.get("house_id")]
    return EXAMPLES


@app.get("/api/mode")
def mode():
    return {"sample": SAMPLE}


@app.post("/api/check")
def start_check(body: CheckIn):
    if not body.way and (body.lat is None or body.lon is None):
        raise HTTPException(400, "give an OSM way or a point")
    q: queue.Queue = queue.Queue()
    run = Run(emit=q.put, use_model=body.use_model and not SAMPLE, offline=SAMPLE)
    live[run.id] = {"queue": q, "events": run.events}

    def work():
        try:
            run.check(way=body.way, lat=body.lat, lon=body.lon, label=body.label, note=body.note, heating=body.heating, gas_kwh=body.gas_kwh)
        except LookupError as e:
            run.emit({"type": "error", "code": "not_found", "text": str(e)[:300]})
        except Exception as e:  # shown in the trace; the page stays usable
            run.emit({"type": "error", "code": "failed", "text": str(e)[:300]})
        finally:
            q.put(None)

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": run.id}


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.post("/api/v1/check")
@app.post("/run")
def check_sync(body: CheckSyncIn):
    """Programmatic entry: JSON in, JSON out. The model step is off unless use_model is true (it can take minutes)."""
    if not body.way and (body.lat is None or body.lon is None):
        return _err(400, "bad_request", "Give an OpenStreetMap way id ('way') or a point ('lat' and 'lon').")
    run = Run(use_model=body.use_model and not SAMPLE, offline=SAMPLE)
    try:
        rec = run.check(way=body.way, lat=body.lat, lon=body.lon, label=body.label, note=body.note, heating=body.heating, gas_kwh=body.gas_kwh)
    except LookupError as e:
        return _err(404, "not_found", str(e))
    except Exception as e:  # noqa: BLE001  structured, no stack trace
        return _err(502, "upstream_failed", f"{type(e).__name__}: {str(e)[:300]}")
    return rec["answer"]


@app.exception_handler(RequestValidationError)
def _bad_input(request, exc):
    first = exc.errors()[0] if exc.errors() else {}
    return _err(400, "bad_request", f"{first.get('msg', 'invalid input')} at {'.'.join(str(x) for x in first.get('loc', []))}")


@app.exception_handler(Exception)
def _any_error(request, exc):  # never a stack trace to the client
    return _err(500, "internal_error", f"{type(exc).__name__}: {str(exc)[:200]}")


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


@app.get("/api/samples")
def samples_index():
    return json.loads((SAMPLES / "index.json").read_text())


@app.get("/api/runs/{name}")
def run_file(name: str):
    """A recorded run: a sample by key ("dartmouth"), or any saved run by id or id prefix."""
    n = Path(name).name
    for p in (SAMPLES / f"{n}.json", RUNS / f"{n}.json"):
        if p.exists():
            return JSONResponse(json.loads(p.read_text()))
    matches = sorted(RUNS.glob(f"{n}*.json"))
    if not matches:
        raise HTTPException(404, "no such run")
    return JSONResponse(json.loads(matches[0].read_text()))


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
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5173")), log_level="warning")
