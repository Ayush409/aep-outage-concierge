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
    ("ice", "Ice or heavy wet snow on lines and trees"),
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
    """log(1 + damage records per 100 poles) per cell, from ARCOS records (January records excluded)."""
    g = grid()
    pos = {c: i for i, c in enumerate(g.cell_ids)}
    d = g.damage[pd.to_datetime(g.damage.report_date).dt.month != 1]
    n = np.bincount(d.cell.map(pos).to_numpy(), minlength=len(g.cells))
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


def cell_day_features(hourly) -> pd.DataFrame:
    """Expand per-point daily features to per-cell rows; freezing rain is elevation-corrected per cell."""
    from .weather import cell_to_point

    daily_points = hourly.daily_features()
    pt = cell_to_point()
    g = grid()
    ncell = len(g.cells)
    days = daily_points.day.unique()
    by_point = daily_points.set_index(["point", "day"])
    idx = pd.MultiIndex.from_arrays([np.repeat(pt, len(days)), np.tile(days, ncell)])
    f = by_point.reindex(idx).reset_index(drop=True)
    f["cellpos"] = np.repeat(np.arange(ncell), len(days))
    f["day"] = np.tile(days, ncell)
    f["frz"] = hourly.cell_freezing_rain().reshape(-1)
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


def expected_damage(hourly, snow_ice_equiv: float = 0.0) -> tuple[np.ndarray, pd.DataFrame, np.ndarray]:
    """Expected damage count per cell summed over the window, plus per-cell factor contributions.

    snow_ice_equiv: inches of ice-equivalent load per inch of wet snow (snow-storm assumption that
    reuses what the model learned from freezing rain).
    Returns (lambda per cell, feature frame, contributions per cell [peak day]).
    """
    g = grid()
    f = cell_day_features(hourly)
    if snow_ice_equiv:
        # Only snow that falls at 30-35 F is wet enough to stick to lines and limbs; colder, dry snow does not
        # accrete (it still counts through the ordinary snow-load term). Judged hour by hour, not by the day's range.
        hf = hourly.f
        wet_snow = np.where((hf["temperature_2m"] >= 30) & (hf["temperature_2m"] <= 35), hf["snowfall"], 0.0)
        from .weather import Hourly
        wet = cell_day_features(Hourly(hourly.time, {**hf, "snowfall": wet_snow})).snow.to_numpy()
        f["frz"] = f.frz.to_numpy() + snow_ice_equiv * wet
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


@lru_cache(maxsize=1)
def placement_keys() -> np.ndarray:
    """'asset_type|kind of isolating device' per asset (e.g. 'primary|breaker' = backbone near the substation)."""
    g = grid()
    iso = g.assets.iso_dev.to_numpy()
    kind = np.where(iso >= 0, g.dev.kind.to_numpy()[np.maximum(iso, 0)], "none")
    return g.assets.asset_type.to_numpy().astype(object) + "|" + kind


def fit_placement(damage: pd.DataFrame) -> dict:
    """Relative damage propensity per placement key vs. its asset type, from real ARCOS records.

    Real damage lands far less on breaker-protected backbone and on secondary-side poles than a uniform
    pick would put there. Smoothed towards 1.0 (the type average) so sparse keys stay neutral.
    """
    g = grid()
    keys = pd.Series(placement_keys())
    iso = damage.iso_dev.to_numpy()
    kind = np.where(iso >= 0, g.dev.kind.to_numpy()[np.maximum(iso, 0)], "none")
    dkeys = pd.Series(damage.asset_type.to_numpy().astype(object) + "|" + kind)
    n = keys.value_counts()
    m = dkeys.value_counts().reindex(n.index).fillna(0)
    t = n.index.str.split("|").str[0]
    type_rate = (m.groupby(t).sum() / n.groupby(t).sum()).reindex(t).to_numpy()
    rel = (m.to_numpy() + 1) / (n.to_numpy() * type_rate + 1)
    return {k: round(float(v), 4) for k, v in zip(n.index, rel)}


@lru_cache(maxsize=4)
def _propensity_cached(items: tuple) -> np.ndarray:
    table = dict(items)
    return np.array([table.get(k, 1.0) for k in placement_keys()])


def asset_propensity(table: dict | None = None) -> np.ndarray:
    """Per-asset placement propensity (1.0 everywhere if the model has no placement table)."""
    if table is None:
        table = model().meta.get("outage", {}).get("placement", {})
    return _propensity_cached(tuple(sorted(table.items())))


def asset_weights(mix: dict, placement: dict | None = None) -> np.ndarray:
    """Share of a cell's expected damage that lands on each asset, given an asset-type mix.

    Within a type, assets are weighted by their placement propensity instead of uniformly.
    """
    tcode, cellpos, ok, _ = _asset_index()
    prop = asset_propensity(placement)
    m = np.array([mix.get(t, 0.0) for t in ASSET_TYPES])
    n_ct = np.zeros((len(grid().cells), len(ASSET_TYPES)))
    np.add.at(n_ct, (cellpos[ok], tcode[ok]), prop[ok])
    present = (n_ct > 0) * m  # mix restricted to types present in the cell
    norm = present.sum(axis=1)
    norm[norm == 0] = 1.0
    w = np.zeros(len(tcode))
    w[ok] = m[tcode[ok]] * prop[ok] / np.maximum(n_ct[cellpos[ok], tcode[ok]], 1e-12) / norm[cellpos[ok]]
    return w


def device_rates(lam_cells: np.ndarray, mix: dict, extra_asset_rate: np.ndarray | None = None,
                 placement: dict | None = None) -> np.ndarray:
    """Expected number of damaged assets isolated by each device."""
    g = grid()
    _, cellpos, ok, _ = _asset_index()
    lam_a = np.zeros(len(cellpos))
    lam_a[ok] = lam_cells[cellpos[ok]] * asset_weights(mix, placement)[ok]
    if extra_asset_rate is not None:
        lam_a = lam_a + extra_asset_rate
    iso = g.assets.iso_dev.to_numpy()
    good = iso >= 0
    return np.bincount(iso[good], weights=lam_a[good], minlength=g.n_dev)


def upstream_rate(dev_rate: np.ndarray) -> np.ndarray:
    """Sum of expected damage on the devices feeding each premise."""
    g = grid()
    return np.bincount(g.chain_p, weights=dev_rate[g.chain_d], minlength=g.n_prem)


def cluster_size() -> float:
    return float(model().meta.get("outage", {}).get("cluster_size", 1.0))


def premise_outage_prob(dev_rate: np.ndarray, k: float | None = None,
                        independent_rate: np.ndarray | None = None) -> np.ndarray:
    """P(premise loses power) = 1 - exp(-s / k), s = expected storm damage on its upstream devices.

    Real damage clusters: several reports often sit behind one fuse, and only the first one cuts power.
    Damage arrives as Poisson clusters of mean size k on a device (k = 1 is independent damage); the
    simulation's Monte Carlo draws clusters the same way, so both agree. k is fitted on replayed
    storms in scripts/train_model.py. independent_rate (per device) is added unclustered, e.g. the
    heat/cold transformer rules, which fail units independently.
    """
    k = cluster_size() if k is None else k
    s = upstream_rate(dev_rate) / k
    if independent_rate is not None:
        s = s + upstream_rate(independent_rate)
    return 1.0 - np.exp(-s)


def fit_cluster_size(events: list[tuple[np.ndarray, np.ndarray, dict]], placement: dict) -> float:
    """Fit k on real storms: events = [(real damage count per cell, actual premises out, hazard mix)].

    Uses real damage counts as input, so this calibrates only the damage -> outage step (not the
    damage model): expected customers out should match the customers behind the real damage, in
    every storm (squared log ratio, larger storms weighted more).
    """
    from scipy.optimize import minimize_scalar

    cust = grid().prem_customers
    data = [(upstream_rate(device_rates(lam, mix, placement=placement)), cust[act].sum()) for lam, act, mix in events]

    def loss(k):
        return sum(np.log(np.sum(cust * (1 - np.exp(-s / k))) / out) ** 2 * np.log(out) for s, out in data)

    return round(float(minimize_scalar(loss, bounds=(1.0, 10.0), method="bounded").x), 3)


def band(p: float) -> str:
    if p >= 0.60:
        return "Severe"
    if p >= 0.35:
        return "High"
    if p >= 0.15:
        return "Elevated"
    return "Low"


BAND_ORDER = ["Low", "Elevated", "High", "Severe"]


def band_outcomes() -> dict:
    """{band: {share, customers, storms}}: share of customers in that band who actually lost power in
    past storms the model had not seen (scripts/train_model.py). This, not p_out, is what customers see:
    the bands rank risk, but the raw probability is overconfident."""
    return model().meta.get("band_outcomes", {})


def band_outcome(b: str) -> dict | None:
    o = band_outcomes().get(b)
    return dict(share=o["share"], storms=len(o["storms"])) if o else None
