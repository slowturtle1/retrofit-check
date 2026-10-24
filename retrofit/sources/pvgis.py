"""PVGIS (EU Joint Research Centre): yearly output of a roof plane. Keyless."""

from __future__ import annotations

import requests

from ..config import USER_AGENT

URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
KWP_PER_M2 = 0.147  # typical 2026 panels with gaps and edge clearance; an estimate, labelled as such


def estimate(lat: float, lon: float, plane: dict) -> dict:
    kwp = round(plane["area_m2"] * KWP_PER_M2, 1)
    params = {"lat": round(lat, 6), "lon": round(lon, 6), "peakpower": kwp, "loss": 14,
              "angle": plane["pitch_deg"], "aspect": plane["azimuth_deg"] - 180, "outputformat": "json"}
    r = requests.get(URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=90)
    r.raise_for_status()
    kwh = round(r.json()["outputs"]["totals"]["fixed"]["E_y"])
    return {"facing": plane["facing"], "kwp": kwp, "kwh_year": kwh,
            "params": f"PVGIS 5.2 PVcalc angle {params['angle']} aspect {params['aspect']} loss 14 kWp {kwp}",
            "source": "PVGIS 5.2, EU Joint Research Centre"}


def read(z, house: dict, plane: dict) -> dict:
    """The same PVGIS request registered as a Zetaris REST table and read with Lightning SQL; direct if Zetaris fails."""
    import hashlib
    from urllib.parse import urlencode

    from ..zetaris import ZetarisError

    kwp = round(plane["area_m2"] * KWP_PER_M2, 1)
    params = {"lat": round(house["lat"], 6), "lon": round(house["lon"], 6), "peakpower": kwp, "loss": 14,
              "angle": plane["pitch_deg"], "aspect": plane["azimuth_deg"] - 180, "outputformat": "json"}
    url = URL + "?" + urlencode(params)
    table = "pv_" + hashlib.sha1(url.encode()).hexdigest()[:12]
    try:
        try:
            z.run(f'''CREATE LIGHTNING REST TABLE {table} FROM PVGIS REQUEST(
    endpoint "{url}",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
    user-agent "{USER_AGENT}"
) BODY ()''', purpose="Register PVGIS for the best roof plane as a Zetaris REST table")
        except ZetarisError as e:
            if "exist" not in str(e).lower():
                raise
        rows = z.run(f"SELECT outputs.totals.fixed.E_y AS kwh_year FROM pvgis.{table}", purpose="Read the yearly solar output").rows
        kwh, via = round(float(rows[0][0])), "zetaris"
    except (ZetarisError, IndexError, ValueError):
        kwh, via = estimate(house["lat"], house["lon"], plane)["kwh_year"], "direct"
    return {"facing": plane["facing"], "kwp": kwp, "kwh_year": kwh, "via": via,
            "params": f"PVGIS 5.2 PVcalc angle {params['angle']} aspect {params['aspect']} loss 14 kWp {kwp}",
            "source": "PVGIS 5.2, EU Joint Research Centre" + (" via Zetaris" if via == "zetaris" else "")}
