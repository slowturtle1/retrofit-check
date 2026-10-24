"""Roof planes from Environment Agency LIDAR (composite DSM, 1 m, Open Government Licence).

Slope and aspect come from the height gradient inside the footprint, shrunk by 0.75 m so
walls and gutters do not count. Cells steeper than 65 degrees are trees, chimneys or dormer
sides and are reported as noise rather than roof.
"""

from __future__ import annotations

import io
import math

import numpy as np
import requests
import shapely
import tifffile
from pyproj import Transformer
from shapely.geometry import Polygon

from ..config import USER_AGENT

DSM = ("https://environment.data.gov.uk/spatialdata/lidar-composite-digital-surface-model-first-return-dsm-1m/wcs"
       "?service=WCS&version=2.0.1&request=GetCoverage"
       "&CoverageId=df4e3ec3-315e-48aa-aaaf-b5ae74d7b2bb__Lidar_Composite_Elevation_FZ_DSM_1m"
       "&format=image/tiff&subset=E({x0},{x1})&subset=N({y0},{y1})")
SECTORS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
METHOD = "EA LIDAR composite DSM 1 m, gradient inside footprint shrunk 0.75 m, planes = 45 degree sectors with 12 percent or more of cells"
_to27700 = Transformer.from_crs(4326, 27700, always_xy=True)


def measure(coords: list[tuple[float, float]], margin_m: float = 0.75) -> dict:
    poly = Polygon([_to27700.transform(lo, la) for lo, la in coords])
    inner = poly.buffer(-margin_m)
    x0, y0 = (math.floor(v) - 2 for v in poly.bounds[:2])
    x1, y1 = (math.ceil(v) + 2 for v in poly.bounds[2:])
    r = requests.get(DSM.format(x0=x0, x1=x1, y0=y0, y1=y1), headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    z = tifffile.imread(io.BytesIO(r.content)).astype(float)
    z[z < -100] = np.nan
    rows, cols = z.shape
    X = x0 + 0.5 + np.arange(cols)[None, :].repeat(rows, 0)
    Y = y1 - 0.5 - np.arange(rows)[:, None].repeat(cols, 1)
    inside = shapely.contains_xy(inner, X, Y) & ~np.isnan(z)
    n = int(inside.sum())
    if n < 10:
        raise ValueError("no LIDAR cells inside this footprint")
    drow, dcol = np.gradient(z)
    dz_e, dz_n = dcol, -drow
    slope = np.degrees(np.arctan(np.hypot(dz_e, dz_n)))
    aspect = (np.degrees(np.arctan2(-dz_e, -dz_n)) + 360) % 360
    s, a = slope[inside], aspect[inside]
    flat, noisy = s < 10, s > 65
    pitched = ~flat & ~noisy
    sector = ((a[pitched] + 22.5) // 45).astype(int) % 8
    planes = []
    for k in range(8):
        sel = sector == k
        if sel.sum() / n >= 0.12:
            rad = np.radians(a[pitched][sel])
            az = (math.degrees(math.atan2(np.sin(rad).mean(), np.cos(rad).mean())) + 360) % 360
            planes.append({"facing": SECTORS[k], "azimuth_deg": round(az), "pitch_deg": round(float(np.median(s[pitched][sel]))), "area_m2": int(sel.sum())})
    heights = z[inside]
    return {
        "planes": planes,
        "noise_pct": round(100 * float(noisy.mean())),
        "flat_pct": round(100 * float(flat.mean())),
        "eaves_m": round(float(np.nanpercentile(heights, 10)), 1),
        "ridge_m": round(float(np.nanpercentile(heights, 98)), 1),
        "method": METHOD.replace("shrunk 0.75 m", f"shrunk {margin_m} m"),
        "margin_m": margin_m,
    }


def best_solar_plane(planes: list[dict]) -> dict | None:
    """The plane facing between east and west through south with the most sun: area weighted by how far it turns from south.

    An east or west slope gets roughly 70% of what the same slope facing south gets, so a south slope wins a tie.
    """
    good = [p for p in planes if 90 <= p["azimuth_deg"] <= 270 and p["pitch_deg"] <= 60]
    return max(good, key=lambda p: p["area_m2"] * (1 - 0.3 * abs(p["azimuth_deg"] - 180) / 90)) if good else None
