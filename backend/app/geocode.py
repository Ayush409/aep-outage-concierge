"""Address -> nearest service point, with a ZIP cross-check.

Uses the US Census geocoder (free, no key). The raw address is used only for this lookup and is
then stored encrypted; the premise link is what the app uses afterwards.
"""
import json
from functools import lru_cache

import httpx
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape

from .engines.data import PROCESSED, grid

CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
MAX_SNAP_M = 400


@lru_cache(maxsize=1)
def _tree():
    g = grid()
    xy = np.column_stack([(g.prem.lon.to_numpy() + 80) * 88_700, (g.prem.lat.to_numpy() - 37.24) * 110_540])
    return cKDTree(xy)


@lru_cache(maxsize=1)
def _zcta():
    gj = json.loads((PROCESSED / "zcta.geojson").read_text())
    return [(f["properties"]["zip"], shape(f["geometry"])) for f in gj["features"]]


def zip_of(lon: float, lat: float) -> str | None:
    pt = Point(lon, lat)
    for z, geom in _zcta():
        if geom.contains(pt):
            return z
    return None


def snap(lon: float, lat: float) -> tuple[int | None, float]:
    d, k = _tree().query([(lon + 80) * 88_700, (lat - 37.24) * 110_540])
    return (int(k) if d <= MAX_SNAP_M else None), float(d)


def geocode(address: str, zip_code: str) -> dict:
    """Returns {ok, premise_idx?, reason?}. Never returns coordinates to the client."""
    try:
        r = httpx.get(CENSUS, timeout=20, params=dict(address=f"{address}, {zip_code}",
                                                      benchmark="Public_AR_Current", format="json"))
        r.raise_for_status()
        matches = r.json()["result"]["addressMatches"]
    except Exception:
        return dict(ok=False, reason="The address lookup service is unavailable. Try again, or pick your "
                                     "location on the map instead.")
    if not matches:
        return dict(ok=False, reason="We couldn't find that address. Check the spelling and ZIP code.")
    c = matches[0]["coordinates"]
    lon, lat = float(c["x"]), float(c["y"])
    return locate(lon, lat, zip_code)


def locate(lon: float, lat: float, zip_code: str | None) -> dict:
    z = zip_of(lon, lat)
    if zip_code and z and z != zip_code.strip()[:5]:
        return dict(ok=False, reason=f"That address is in ZIP {z}, not {zip_code}. Please check your ZIP code.")
    idx, dist = snap(lon, lat)
    if idx is None:
        return dict(ok=False, reason="That address is outside the area covered by this demo "
                                     "(Roanoke-area AEP circuits).")
    return dict(ok=True, premise_idx=idx, snap_m=round(dist), zip=z)
