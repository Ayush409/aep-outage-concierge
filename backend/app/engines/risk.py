"""Damage-rate model: expected damage per grid cell per day, from weather + grid exposure.

Poisson regression with pole count as exposure, trained on the ARCOS damage records
(scripts/train_model.py). Every term is additive on the log scale, so each prediction
comes with readable contributing factors.
"""
import json
from functools import lru_cache

import numpy as np
import pandas as pd

from .data import PROCESSED, grid

MODEL_PATH = PROCESSED / "risk_model.json"

FEATURES = [
    ("wind_30", "Wind gusts above 30 mph"),
    ("wind_45", "Wind gusts above 45 mph"),
    ("wind_hours", "Hours of 40+ mph gusts"),
    ("ice", "Freezing rain (ice on lines and trees)"),
    ("snow", "Snow load"),
    ("soil", "Soaked ground (trees uproot more easily)"),
    ("wind_soil", "Wind on soaked ground"),
    ("pole_age", "Older poles in the area"),
    ("overhead", "Share of overhead lines"),
    ("wind_overhead", "Wind on overhead lines"),
    ("history", "Past storm damage nearby (trees, terrain)"),
]


@lru_cache(maxsize=1)
def history_density() -> np.ndarray:
    """log(1 + damage records per 100 poles) per cell, from all ARCOS records."""
    g = grid()
    pos = {c: i for i, c in enumerate(g.cell_ids)}
    n = np.bincount(g.damage.cell.map(pos).to_numpy(), minlength=len(g.cells))
    return np.log1p(100 * n / (g.cells.poles.to_numpy() + 1))


def design(feats: pd.DataFrame, cells: pd.DataFrame, hist: np.ndarray | None = None) -> np.ndarray:
    """feats has one row per (cell, day) with weather columns + 'cellpos'.

    hist: per-row history feature (training passes a leave-event-out version); default = all records.
    """
    c = cells.iloc[feats.cellpos.to_numpy()]
    if hist is None:
        hist = history_density()[feats.cellpos.to_numpy()]
    g = feats.gust_max.to_numpy()
    w30 = np.maximum(g - 30, 0) / 10
    w45 = np.maximum(g - 45, 0) / 10
    oh = c.overhead_share.to_numpy()
    soil = np.minimum(feats.rain72.to_numpy(), 6) / 2
    # ice enters linearly (exponential fragility on the log scale): 0.8 in -> tens, 1.3 in -> hundreds
    X = np.column_stack([
        w30, w45, np.log1p(feats.gust_h40.to_numpy()), np.minimum(feats.frz.to_numpy(), 3.0),
        np.log1p(feats.snow.to_numpy()), soil, w30 * soil, (c.pole_age.to_numpy() - 50) / 20, oh, w30 * oh,
        hist,
    ])
    return X


def cell_day_features(daily_points: pd.DataFrame) -> pd.DataFrame:
    """Expand per-point daily features to per-cell rows."""
    from .weather import cell_to_point

    pt = cell_to_point()
    g = grid()
    ncell = len(g.cells)
    days = daily_points.day.unique()
    by_point = daily_points.set_index(["point", "day"])
    idx = pd.MultiIndex.from_arrays([np.repeat(pt, len(days)), np.tile(days, ncell)])
    f = by_point.reindex(idx).reset_index(drop=True)
    f["cellpos"] = np.repeat(np.arange(ncell), len(days))
    f["day"] = np.tile(days, ncell)
    return f


class RiskModel:
    def __init__(self, coef, intercept, meta):
        self.coef = np.asarray(coef)
        self.intercept = float(intercept)
        self.meta = meta

    MAX_DAILY_SHARE = 0.15  # physical cap: at most ~15% of a cell's poles damaged in one day

    def rate(self, X: np.ndarray, exposure: np.ndarray) -> np.ndarray:
        return np.minimum(np.exp(self.intercept + X @ self.coef), self.MAX_DAILY_SHARE) * exposure

    def contributions(self, X: np.ndarray) -> np.ndarray:
        return X * self.coef

    @property
    def train_range(self) -> dict:
        return self.meta.get("train_range", {})


@lru_cache(maxsize=1)
def model() -> RiskModel:
    d = json.loads(MODEL_PATH.read_text())
    return RiskModel(d["coef"], d["intercept"], d)


# Leaf-on (May-Oct) wind multiplier. Tested 2.0: the Helene hold-out then over-predicted 2.6x,
# so the data does not support it; kept at 1.0 (mechanism left in for experimentation).
LEAF_ON_FACTOR = 1.0


def wind_adjustment(f: pd.DataFrame, m: "RiskModel") -> np.ndarray:
    """Wind-driven days (little ice): in-sample wind calibration x leaf-on factor in May-Oct."""
    wind_day = (f.frz.to_numpy() < 0.1) & (f.gust_max.to_numpy() >= 30)
    leaf_on = pd.to_datetime(f.day).dt.month.between(5, 10).to_numpy()
    c = m.meta.get("wind_calibration", 1.0)
    return np.where(wind_day, c * np.where(leaf_on, LEAF_ON_FACTOR, 1.0), 1.0)


def exposure(cells: pd.DataFrame) -> np.ndarray:
    return cells.poles.to_numpy() + 1.0


def expected_damage(hourly) -> tuple[np.ndarray, pd.DataFrame, np.ndarray]:
    """Expected damage count per cell summed over the window, plus per-cell factor contributions.

    Returns (lambda per cell, feature frame, contributions per cell [peak day]).
    """
    g = grid()
    f = cell_day_features(hourly.daily_features())
    X = design(f, g.cells)
    m = model()
    lam_rows = m.rate(X, exposure(g.cells)[f.cellpos.to_numpy()]) * wind_adjustment(f, m)
    lam = np.bincount(f.cellpos, weights=lam_rows, minlength=len(g.cells))
    # contributions on each cell's highest-risk day
    f["lam"] = lam_rows
    peak = f.loc[f.groupby("cellpos").lam.idxmax()].sort_values("cellpos")
    contrib = m.contributions(X[peak.index.to_numpy()])
    return lam, peak.reset_index(drop=True), contrib


ASSET_TYPES = ["pole", "primary", "secondary", "transformer", "fuse", "recloser", "switch"]


@lru_cache(maxsize=1)
def _asset_index():
    g = grid()
    a = g.assets
    tcode = pd.Categorical(a.asset_type, categories=ASSET_TYPES).codes
    cellpos = g.asset_cell
    ok = cellpos >= 0
    n_ct = np.zeros((len(g.cells), len(ASSET_TYPES)))
    np.add.at(n_ct, (cellpos[ok], tcode[ok]), 1)
    return tcode, cellpos, ok, n_ct


def asset_weights(mix: dict) -> np.ndarray:
    """Share of a cell's expected damage that lands on each asset, given an asset-type mix."""
    tcode, cellpos, ok, n_ct = _asset_index()
    m = np.array([mix.get(t, 0.0) for t in ASSET_TYPES])
    present = (n_ct > 0) * m  # mix restricted to types present in the cell
    norm = present.sum(axis=1)
    norm[norm == 0] = 1.0
    w = np.zeros(len(tcode))
    w[ok] = m[tcode[ok]] / np.maximum(n_ct[cellpos[ok], tcode[ok]], 1) / norm[cellpos[ok]]
    return w


def device_rates(lam_cells: np.ndarray, mix: dict, extra_asset_rate: np.ndarray | None = None) -> np.ndarray:
    """Expected number of damaged assets isolated by each device."""
    g = grid()
    _, cellpos, ok, _ = _asset_index()
    lam_a = np.zeros(len(cellpos))
    lam_a[ok] = lam_cells[cellpos[ok]] * asset_weights(mix)[ok]
    if extra_asset_rate is not None:
        lam_a = lam_a + extra_asset_rate
    iso = g.assets.iso_dev.to_numpy()
    good = iso >= 0
    return np.bincount(iso[good], weights=lam_a[good], minlength=g.n_dev)


def premise_outage_prob(dev_rate: np.ndarray) -> np.ndarray:
    """P(premise loses power) = 1 - exp(-sum of damage rates on its upstream devices)."""
    g = grid()
    s = np.bincount(g.chain_p, weights=dev_rate[g.chain_d], minlength=g.n_prem)
    return 1.0 - np.exp(-s)


def band(p: float) -> str:
    if p >= 0.60:
        return "Severe"
    if p >= 0.35:
        return "High"
    if p >= 0.15:
        return "Elevated"
    return "Low"


BAND_ORDER = ["Low", "Elevated", "High", "Severe"]
