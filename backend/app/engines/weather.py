"""Weather on the service-area grid: archive history, scenario events and the live forecast.

The same daily feature builder is used for training, scenario replays and live forecasts.
"""
import json
import time
from functools import lru_cache

import httpx
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .data import WEATHER, grid

FULL_VARS = ["temperature_2m", "precipitation", "rain", "snowfall", "wind_gusts_10m", "apparent_temperature",
             "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m"]
GRID_LON = np.round(np.arange(-80.25, -79.64, 0.1), 2)
GRID_LAT = np.round(np.arange(37.0, 37.51, 0.1), 2)
POINTS = np.array([(lon, lat) for lat in GRID_LAT for lon in GRID_LON])
FREEZE_F = 32.5
LAPSE_F_PER_M = 0.0117  # standard atmosphere: 6.5 C per km


@lru_cache(maxsize=1)
def cell_to_point() -> np.ndarray:
    """Nearest 0.1-degree weather point for every grid cell."""
    g = grid()
    tree = cKDTree(POINTS)
    _, k = tree.query(np.column_stack([g.cells.lon, g.cells.lat]))
    return k


@lru_cache(maxsize=1)
def cell_elevation() -> np.ndarray:
    """Elevation (m) of every grid cell centre; NaN without elevation.json."""
    path = WEATHER / "elevation.json"
    g = grid()
    if not path.exists():
        return np.full(len(g.cells), np.nan)
    e = json.loads(path.read_text())["cells"]
    return np.array([e.get(str(int(c)), np.nan) for c in g.cell_ids], dtype=float)


@lru_cache(maxsize=1)
def cell_elevation_offset() -> np.ndarray:
    """Metres each grid cell sits above (+) or below (-) its weather point (0 without elevation.json).

    Weather points are ~10 km apart, but Roanoke's ridges sit 300-700 m above the valley floor. Ice
    storms hinge on a few degrees: the Feb 2025 ice damage per pole was ~20x higher above 600 m.
    """
    path = WEATHER / "elevation.json"
    if not path.exists():
        return np.zeros(len(grid().cells))
    pe = np.asarray(json.loads(path.read_text())["points"], dtype=float)
    dz = cell_elevation() - pe[cell_to_point()]
    return np.where(np.isfinite(dz), dz, 0.0)


class Hourly:
    """Hourly fields on the weather points: arrays shaped (points, hours)."""

    def __init__(self, times, fields: dict):
        self.time = pd.to_datetime(pd.Series(times))
        self.f = {k: np.asarray(v, dtype=float) for k, v in fields.items()}
        for k in FULL_VARS:
            if k not in self.f:
                self.f[k] = np.full((len(POINTS), len(self.time)), np.nan)
        for k, v in self.f.items():
            if np.isnan(v).any():  # fill gaps along time
                df = pd.DataFrame(v.T).ffill().bfill().fillna(0)
                self.f[k] = df.to_numpy().T

    @property
    def hours(self):
        return len(self.time)

    def scaled(self, gust_mult: float = 1.0):
        h = Hourly(self.time, {k: v.copy() for k, v in self.f.items()})
        if gust_mult != 1.0:
            h.f["wind_gusts_10m"] *= gust_mult
            h.f["wind_speed_10m"] *= gust_mult
        return h

    def daily_features(self) -> pd.DataFrame:
        """Per (point, day) features with the lag windows used by the damage model."""
        t = self.time.dt.floor("D")
        days = pd.Index(sorted(t.unique()))
        di = days.get_indexer(t)
        nd, npnt = len(days), len(POINTS)
        temp, rain = self.f["temperature_2m"], self.f["rain"]
        frz_h = np.where(temp <= FREEZE_F, rain, 0.0)

        def agg(values, fn):
            out = np.zeros((npnt, nd))
            for d in range(nd):
                sel = di == d
                out[:, d] = fn(values[:, sel], axis=1) if sel.any() else 0.0
            return out

        gmax = agg(self.f["wind_gusts_10m"], np.max)
        g40 = agg((self.f["wind_gusts_10m"] >= 40).astype(float), np.sum)
        frz = agg(frz_h, np.sum)
        snow = agg(self.f["snowfall"], np.sum)
        prec = agg(self.f["precipitation"], np.sum)
        tmax = agg(temp, np.max)
        tmin = agg(temp, np.min)

        def roll(a, w, fn):
            out = np.zeros_like(a)
            for d in range(nd):
                out[:, d] = fn(a[:, max(0, d - w + 1): d + 1], axis=1)
            return out

        feats = dict(
            gust_max=roll(gmax, 2, np.max), gust_h40=roll(g40, 2, np.sum), frz=roll(frz, 3, np.sum),
            snow=roll(snow, 3, np.sum), rain72=roll(prec, 4, np.sum), tmax=roll(tmax, 2, np.max),
            tmin=roll(tmin, 2, np.min),
        )
        rows = []
        for p in range(npnt):
            rows.append(pd.DataFrame({k: v[p] for k, v in feats.items()}).assign(point=p, day=days))
        return pd.concat(rows, ignore_index=True)

    def cell_freezing_rain(self) -> np.ndarray:
        """Freezing rain per (cell, day), 3-day sum like daily_features' frz, with each cell's
        temperature corrected for its elevation above or below its weather point."""
        t = self.time.dt.floor("D")
        di = pd.Index(sorted(t.unique())).get_indexer(t)
        starts = np.r_[0, np.nonzero(np.diff(di))[0] + 1]
        pt, dz = cell_to_point(), cell_elevation_offset()
        temp, rain = self.f["temperature_2m"], self.f["rain"]
        daily = np.zeros((len(pt), len(starts)))
        for lo in range(0, len(pt), 64):  # chunks keep the (cells, hours) arrays small
            sl = slice(lo, lo + 64)
            tc = temp[pt[sl]] - LAPSE_F_PER_M * dz[sl, None]
            daily[sl] = np.add.reduceat(np.where(tc <= FREEZE_F, rain[pt[sl]], 0.0), starts, axis=1)
        cs = np.concatenate([np.zeros((len(pt), 1)), np.cumsum(daily, axis=1)], axis=1)
        lag = np.maximum(np.arange(daily.shape[1]) - 2, 0)
        return cs[:, 1:] - cs[:, lag]

    def hazard_intensity(self) -> np.ndarray:
        """Hourly damage-driving intensity per point, used to time damage within an event."""
        g = self.f["wind_gusts_10m"]
        frz = np.where(self.f["temperature_2m"] <= FREEZE_F, self.f["rain"], 0.0)
        return np.maximum(g - 28, 0) / 10 + 8 * frz + 1e-3

    def max_gust_series(self) -> np.ndarray:
        return self.f["wind_gusts_10m"].max(axis=0)

    def to_json(self, step: int = 1) -> dict:
        idx = np.arange(0, self.hours, step)
        return dict(time=iso_local(self.time.iloc[idx]),
                    lon=POINTS[:, 0].tolist(), lat=POINTS[:, 1].tolist(),
                    vars={k: np.round(self.f[k][:, idx], 1).tolist() for k in FULL_VARS})


@lru_cache(maxsize=1)
def history() -> Hourly:
    z = np.load(WEATHER / "history.npz", allow_pickle=False)
    vars_ = [str(v) for v in z["vars"]]
    data = z["data"]
    return Hourly(z["time"], {v: data[:, i, :] for i, v in enumerate(vars_)})


@lru_cache(maxsize=16)
def event(eid: str) -> Hourly:
    d = json.loads((WEATHER / f"event_{eid}.json").read_text())
    return Hourly(d["time"], d["vars"])


def event_meta(eid: str) -> dict:
    d = json.loads((WEATHER / f"event_{eid}.json").read_text())
    return {k: d[k] for k in ("id", "start", "end", "origin", "source_lon", "source_lat")}


LOCAL_TZ = "America/New_York"  # weather is fetched in the service area's local time


def iso_local(times) -> list[str]:
    """ISO strings with the Eastern offset (e.g. -04:00), so each browser converts them to its own time zone."""
    idx = pd.DatetimeIndex(pd.to_datetime(list(times)))
    if idx.tz is None:
        try:
            idx = idx.tz_localize(LOCAL_TZ, ambiguous="infer", nonexistent="shift_forward")
        except Exception:  # repeated fall-back hour that cannot be inferred: treat it as standard time
            idx = idx.tz_localize(LOCAL_TZ, ambiguous=False, nonexistent="shift_forward")
    return [t.isoformat() for t in idx]


_live = {"t": 0.0, "h": None}


def live() -> Hourly:
    """Open-Meteo forecast (1 past day + 7 days), cached for 30 minutes."""
    if _live["h"] is not None and time.time() - _live["t"] < 1800:
        return _live["h"]
    cache = WEATHER / "live.json"
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=60, params=dict(
            latitude=",".join(str(p[1]) for p in POINTS), longitude=",".join(str(p[0]) for p in POINTS),
            hourly=",".join(FULL_VARS), past_days=1, forecast_days=7, wind_speed_unit="mph",
            temperature_unit="fahrenheit", precipitation_unit="inch", timezone="America/New_York"))
        r.raise_for_status()
        locs = r.json()
        locs = locs if isinstance(locs, list) else [locs]
        payload = dict(time=locs[0]["hourly"]["time"],
                       vars={k: [loc["hourly"][k] for loc in locs] for k in FULL_VARS})
        cache.write_text(json.dumps(payload))
    except Exception:
        if not cache.exists():
            raise
        payload = json.loads(cache.read_text())
    h = Hourly(payload["time"], {k: np.array(v, dtype=float) for k, v in payload["vars"].items()})
    _live.update(t=time.time(), h=h)
    return h


# ------------------------------------------------------------------ map display grid
# Larger grid used only for drawing weather on the maps (covers everything customers can pan to).
DISPLAY_GRID = dict(nx=15, ny=11, lon0=-80.65, lat0=36.75, step=0.1)
MODEL_GRID = dict(nx=len(GRID_LON), ny=len(GRID_LAT), lon0=float(GRID_LON[0]), lat0=float(GRID_LAT[0]), step=0.1)
_live_display = {"t": 0.0, "h": None}


def display_points(grid: dict) -> list[tuple[float, float]]:
    return [(round(grid["lon0"] + i * grid["step"], 2), round(grid["lat0"] + j * grid["step"], 2))
            for j in range(grid["ny"]) for i in range(grid["nx"])]


_display_cache: dict = {}


def display_event(eid: str):
    """(Hourly, grid) for a scenario's weather on the display grid; falls back to the model grid.

    Only the full display grid is cached, so a display file that arrives later is picked up without a restart.
    """
    if eid in _display_cache:
        return _display_cache[eid]
    path = WEATHER / f"display_{eid}.json"
    if not path.exists():
        return event(eid), MODEL_GRID
    d = json.loads(path.read_text())
    _display_cache[eid] = (Hourly(d["time"], d["vars"]), d["grid"])
    return _display_cache[eid]


def display_live():
    """Live forecast on the display grid (cached 30 min); falls back to the model-grid forecast."""
    if _live_display["h"] is not None and time.time() - _live_display["t"] < 1800:
        return _live_display["h"]
    pts = display_points(DISPLAY_GRID)
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=90, params=dict(
            latitude=",".join(str(p[1]) for p in pts), longitude=",".join(str(p[0]) for p in pts),
            hourly=",".join(FULL_VARS), past_days=1, forecast_days=7, wind_speed_unit="mph",
            temperature_unit="fahrenheit", precipitation_unit="inch", timezone="America/New_York"))
        r.raise_for_status()
        locs = r.json()
        locs = locs if isinstance(locs, list) else [locs]
        h = Hourly(locs[0]["hourly"]["time"], {k: np.array([loc["hourly"][k] for loc in locs], dtype=float)
                                               for k in FULL_VARS})
        out = (h, DISPLAY_GRID)
    except Exception:
        out = (live(), MODEL_GRID)
    _live_display.update(t=time.time(), h=out)
    return out


def grid_json(h: "Hourly", grid: dict, step: int = 1) -> dict:
    idx = np.arange(0, h.hours, step)
    return dict(time=iso_local(h.time.iloc[idx]), grid=grid,
                vars={k: np.round(h.f[k][:, idx], 1).tolist() for k in FULL_VARS})
