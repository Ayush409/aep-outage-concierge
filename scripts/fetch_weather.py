"""Fetch Open-Meteo archive weather and SPC tornado tracks.

Writes to data/processed/weather/:
  history.npz         hourly gust/temp/precip/rain/snow on the service-area grid, Oct 2022 -> now
  event_<id>.json     full hourly fields for each scenario window (transposed events are fetched
                      at their real location and re-centred on Roanoke)
  tornado_2011.json   SPC tracks for 27 Apr 2011, shifted onto the service area
  elevation.json      elevation of every grid cell and weather point

Run:  .venv/Scripts/python scripts/fetch_weather.py
"""
import csv
import io
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import PROCESSED  # noqa: E402

OUT = PROCESSED / "weather"
OUT.mkdir(exist_ok=True)
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# 0.1 deg grid over the service area (ERA5-Land resolution)
CENTER = (-79.95, 37.24)
GRID_LON = np.round(np.arange(-80.25, -79.64, 0.1), 2)
GRID_LAT = np.round(np.arange(37.0, 37.51, 0.1), 2)
GRID = [(lon, lat) for lat in GRID_LAT for lon in GRID_LON]

LONG_VARS = ["temperature_2m", "precipitation", "rain", "snowfall", "wind_gusts_10m"]
FULL_VARS = LONG_VARS + ["apparent_temperature", "relative_humidity_2m", "wind_speed_10m",
                         "wind_direction_10m"]
UNITS = dict(wind_speed_unit="mph", temperature_unit="fahrenheit", precipitation_unit="inch",
             timezone="America/New_York")

# Scenario windows. "origin" = real storm centre for transposed events (None = happened here).
EVENTS = {
    "feb_2025": dict(start="2025-02-10", end="2025-02-19", origin=None),
    "helene_2024": dict(start="2024-09-25", end="2024-10-01", origin=None),
    "winter_2025_01": dict(start="2025-01-04", end="2025-01-08", origin=None),
    "derecho_2012": dict(start="2012-06-29", end="2012-07-02", origin=None),
    "texas_freeze_2021": dict(start="2021-02-13", end="2021-02-20", origin=(-97.74, 30.27)),
    "heat_dome_2021": dict(start="2021-06-25", end="2021-07-01", origin=(-122.68, 45.52)),
    "tornado_2011": dict(start="2011-04-26", end="2011-04-29", origin=(-87.30, 33.40)),
    # weather patterns for the generic snow-storm and arctic-cold scenarios (real local events)
    "snow_2009_12": dict(start="2009-12-16", end="2009-12-21", origin=None),
    "arctic_2022_12": dict(start="2022-12-21", end="2022-12-27", origin=None),
}


def get(params, tries=6):
    for k in range(tries):
        try:
            r = httpx.get(ARCHIVE, params=params, timeout=180)
            if r.status_code == 429:
                time.sleep(30 * (k + 1))
                continue
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            print("  retry", k, e, flush=True)
            time.sleep(10 * (k + 1))
    raise RuntimeError("Open-Meteo request failed")


def fetch_history():
    path = OUT / "history.npz"
    if path.exists():
        print("history cached")
        return
    end = (date.today() - timedelta(days=6)).isoformat()
    arrays, times = [], None
    for i, (lon, lat) in enumerate(GRID):
        d = get(dict(latitude=lat, longitude=lon, start_date="2022-09-25", end_date=end,
                     hourly=",".join(LONG_VARS), **UNITS))
        h = d["hourly"]
        times = h["time"]
        arrays.append(np.array([[np.nan if v is None else v for v in h[k]] for k in LONG_VARS],
                               dtype=np.float32))
        print(f"  history point {i + 1}/{len(GRID)}", flush=True)
        time.sleep(8)  # stay under the per-minute quota
    np.savez_compressed(path, data=np.stack(arrays), vars=np.array(LONG_VARS), time=np.array(times),
                        lon=np.array([g[0] for g in GRID]), lat=np.array([g[1] for g in GRID]))
    print("history saved", np.stack(arrays).shape)


def fetch_event(eid, ev):
    path = OUT / f"event_{eid}.json"
    if path.exists():
        print("event cached", eid)
        return
    dx, dy = (ev["origin"][0] - CENTER[0], ev["origin"][1] - CENTER[1]) if ev["origin"] else (0, 0)
    src = [(round(lon + dx, 3), round(lat + dy, 3)) for lon, lat in GRID]
    d = get(dict(latitude=",".join(str(p[1]) for p in src), longitude=",".join(str(p[0]) for p in src),
                 start_date=ev["start"], end_date=ev["end"], hourly=",".join(FULL_VARS), **UNITS))
    d = d if isinstance(d, list) else [d]
    out = dict(id=eid, start=ev["start"], end=ev["end"], origin=ev["origin"], time=d[0]["hourly"]["time"],
               lon=[g[0] for g in GRID], lat=[g[1] for g in GRID],
               source_lon=[p[0] for p in src], source_lat=[p[1] for p in src],
               vars={k: [[None if v is None else round(v, 2) for v in loc["hourly"][k]] for loc in d]
                     for k in FULL_VARS})
    path.write_text(json.dumps(out))
    print("event saved", eid, len(out["time"]), "hours")
    time.sleep(10)


def fetch_elevation():
    """Elevation (m) of every grid cell centre and weather point (Open-Meteo elevation API, 90 m DEM).

    Used to correct each cell's temperature for freezing rain (engines/weather.py).
    """
    import pandas as pd

    if (OUT / "elevation.json").exists():
        print("elevation cached")
        return
    cells = pd.read_pickle(PROCESSED / "cells.pkl")

    def elev(lons, lats):
        out = []
        for i in range(0, len(lons), 100):
            for attempt in range(5):  # each coordinate counts against the per-minute quota
                r = httpx.get("https://api.open-meteo.com/v1/elevation", timeout=60, params=dict(
                    latitude=",".join(f"{x:.4f}" for x in lats[i:i + 100]),
                    longitude=",".join(f"{x:.4f}" for x in lons[i:i + 100])))
                if r.status_code != 429:
                    break
                time.sleep(30 * (attempt + 1))
            r.raise_for_status()
            time.sleep(2)
            out += r.json()["elevation"]
        return out

    ce = elev(cells.lon.tolist(), cells.lat.tolist())
    pe = elev([p[0] for p in GRID], [p[1] for p in GRID])
    (OUT / "elevation.json").write_text(json.dumps(dict(cells=dict(zip(map(str, cells.index), ce)), points=pe)))
    print("elevation", len(ce), "cells", len(pe), "points")


def fetch_tornado_tracks():
    path = OUT / "tornado_2011.json"
    if path.exists():
        return
    url = "https://www.spc.noaa.gov/wcm/data/1950-2023_actual_tornadoes.csv"
    txt = httpx.get(url, timeout=180, follow_redirects=True).text
    origin = EVENTS["tornado_2011"]["origin"]
    tracks = []
    for r in csv.DictReader(io.StringIO(txt)):
        if r["date"] not in ("2011-04-27", "2011-04-28"):
            continue
        slat, slon, elat, elon = (float(r[k]) for k in ("slat", "slon", "elat", "elon"))
        if elat == 0 or elon == 0:
            elat, elon = slat, slon
        # keep tracks within ~2.5 deg of the origin (the Alabama core of the outbreak)
        if abs(slon - origin[0]) > 2.5 or abs(slat - origin[1]) > 2.0:
            continue
        tracks.append(dict(time=r["time"], mag=int(r["mag"]), width_yd=float(r["wid"]), len_mi=float(r["len"]),
                           slon=slon - origin[0] + CENTER[0], slat=slat - origin[1] + CENTER[1],
                           elon=elon - origin[0] + CENTER[0], elat=elat - origin[1] + CENTER[1]))
    path.write_text(json.dumps(tracks))
    print("tornado tracks", len(tracks))


# Map display grid: covers the whole area customers can pan to (MapView MAX_BOUNDS), 0.1 deg spacing.
# The model keeps using the 7 x 6 service-area grid above; this one is only for drawing weather layers.
DISPLAY_LON = np.round(np.arange(-80.65, -79.24, 0.1), 2)
DISPLAY_LAT = np.round(np.arange(36.75, 37.76, 0.1), 2)
DISPLAY = [(lon, lat) for lat in DISPLAY_LAT for lon in DISPLAY_LON]


def fetch_event_display(eid, ev):
    path = OUT / f"display_{eid}.json"
    if path.exists():
        print("display cached", eid)
        return
    dx, dy = (ev["origin"][0] - CENTER[0], ev["origin"][1] - CENTER[1]) if ev["origin"] else (0, 0)
    src = [(round(lon + dx, 3), round(lat + dy, 3)) for lon, lat in DISPLAY]
    d = get(dict(latitude=",".join(str(p[1]) for p in src), longitude=",".join(str(p[0]) for p in src),
                 start_date=ev["start"], end_date=ev["end"], hourly=",".join(FULL_VARS), **UNITS))
    d = d if isinstance(d, list) else [d]
    out = dict(id=eid, time=d[0]["hourly"]["time"],
               grid=dict(nx=len(DISPLAY_LON), ny=len(DISPLAY_LAT), lon0=float(DISPLAY_LON[0]),
                         lat0=float(DISPLAY_LAT[0]), step=0.1),
               vars={k: [[None if v is None else round(v, 1) for v in loc["hourly"][k]] for loc in d]
                     for k in FULL_VARS})
    path.write_text(json.dumps(out))
    print("display saved", eid, len(DISPLAY), "points")
    time.sleep(75)  # each location counts against the per-minute quota


if __name__ == "__main__":
    fetch_elevation()
    fetch_tornado_tracks()
    for eid, ev in EVENTS.items():
        fetch_event(eid, ev)
    fetch_history()
    for eid, ev in EVENTS.items():
        fetch_event_display(eid, ev)
