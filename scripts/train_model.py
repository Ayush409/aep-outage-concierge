"""Train and validate the damage-rate model.

- Target: ARCOS damage records per grid cell per day (report date), Oct 2022 -> now.
- Features: archive weather on the cell's weather point + cell exposure (see engines/risk.py).
- Validation: hold out Feb 2025, train on everything else, predict it; then the same for Helene.
  Reports event totals, cell-level rank correlation, premise-level outage AUC and reliability by band.
- Final model is refit on all days and saved to data/processed/risk_model.json.

Run:  .venv/Scripts/python scripts/train_model.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from scipy.optimize import minimize
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.engines import risk  # noqa: E402
from app.engines.data import PROCESSED, grid  # noqa: E402
from app.engines.weather import history  # noqa: E402

HAZARD_EVENTS = {
    "ice": ["feb_2025_ice", "winter_storm_2025_01"],
    "wind": ["feb_2025_wind", "minor_wind_2025", "wind_2024_11", "wind_rain_2024_01", "storms_2024_04",
             "storms_2024_05"],
    "tropical": ["helene_2024", "helene_late_reports", "debby_remnants_2024_08"],
}
HOLDOUTS = {
    "feb_2025": ("2025-02-10", "2025-02-20", ["feb_2025_ice", "feb_2025_wind"]),
    "helene_2024": ("2024-09-25", "2024-10-03", ["helene_2024", "helene_late_reports"]),
    "winter_2025_01": ("2025-01-04", "2025-01-08", ["winter_storm_2025_01"]),
}
# Storms with enough records to calibrate the damage -> outage step: (events, hazard mix)
OUTAGE_CALIB = {
    "feb_2025": (["feb_2025_ice", "feb_2025_wind"], "ice"),
    "helene_2024": (["helene_2024", "helene_late_reports"], "tropical"),
    "winter_2025_01": (["winter_storm_2025_01"], "ice"),
    "minor_wind_2025": (["minor_wind_2025"], "wind"),
}


def log(*a):
    print("[train]", *a, flush=True)


class MonotonePoisson:
    """Poisson regression with an exposure offset where every hazard/exposure term is constrained >= 0.

    With only a handful of large storms, an unconstrained fit happily learns that stronger wind
    *reduces* damage. Physically every feature here can only add risk, so we bound them at zero.
    """

    def fit(self, X, y, offset, ridge=1e-3):
        n, k = X.shape

        def nll(beta):
            eta = beta[0] + X @ beta[1:] + offset
            mu = np.exp(np.minimum(eta, 30))
            val = mu.sum() - y @ eta + 0.5 * ridge * beta[1:] @ beta[1:]
            r = mu - y
            grad = np.concatenate([[r.sum()], X.T @ r + ridge * beta[1:]])
            return val, grad

        b0 = np.log(max(y.sum(), 1) / np.exp(offset).sum())
        x0 = np.concatenate([[b0], np.full(k, 0.1)])
        bounds = [(None, None)] + [(0, None)] * k
        r = minimize(nll, x0, jac=True, method="L-BFGS-B", bounds=bounds, options=dict(maxiter=5000))
        self.intercept_, self.coef_ = r.x[0], r.x[1:]
        return self


def main():
    g = grid()
    log("building daily features ...")
    f = risk.cell_day_features(history())
    f = f.dropna(subset=["gust_max"]).reset_index(drop=True)
    dmg = g.damage.copy()
    dmg["day"] = pd.to_datetime(dmg.report_date)
    cellpos = {c: i for i, c in enumerate(g.cell_ids)}
    dmg["cellpos"] = dmg.cell.map(cellpos)
    y_counts = dmg.groupby(["cellpos", "day"]).size()
    f["y"] = y_counts.reindex(pd.MultiIndex.from_arrays([f.cellpos, f.day])).fillna(0).to_numpy()
    # Data-quality rule: the ARCOS extract has no records for some clearly severe days (e.g. the
    # Jan 25-27 2026 ice storm). Days with severe area-wide weather but zero records are treated as
    # unlabeled (excluded), not as "no damage". Calm and moderate days stay in as negatives.
    area = f.groupby("day").agg(gust=("gust_max", "mean"), frz=("frz", "mean"), y=("y", "sum"))
    severe_unlabeled = area[((area.gust >= 45) | (area.frz >= 0.3)) & (area.y == 0)].index
    f = f[~f.day.isin(severe_unlabeled)].reset_index(drop=True)
    log("excluded severe days with no records:", len(severe_unlabeled),
        [str(d.date()) for d in severe_unlabeled[:12]])
    expo = risk.exposure(g.cells)[f.cellpos.to_numpy()]
    log("rows", len(f), "damage in window", int(f.y.sum()), "of", len(dmg))

    # "Past damage nearby" without leakage: each row's history excludes its own event, and in a
    # validation fold the held-out event is removed from everyone's history.
    ev_of_day = dmg.groupby("day").event.agg(lambda s: s.mode().iloc[0])
    f["event"] = ev_of_day.reindex(f.day).fillna("").to_numpy()
    ncell = len(g.cells)
    events = sorted(dmg.event.unique())
    cnt = np.zeros((ncell, len(events)))
    np.add.at(cnt, (dmg.cellpos.to_numpy(), dmg.event.map({e: i for i, e in enumerate(events)}).to_numpy()), 1)
    poles = g.cells.poles.to_numpy() + 1

    def hist_rows(exclude: list[str]):
        keep = np.array([e not in exclude for e in events])
        base = cnt[:, keep].sum(axis=1)
        own = np.zeros(len(f))
        ei = {e: i for i, e in enumerate(events)}
        has = f.event.ne("") & ~f.event.isin(exclude)
        own[has.to_numpy()] = cnt[f.cellpos[has].to_numpy(), f.event[has].map(ei).to_numpy()]
        return np.log1p(100 * np.maximum(base[f.cellpos.to_numpy()] - own, 0) / poles[f.cellpos.to_numpy()])

    def fit(mask, X):
        return MonotonePoisson().fit(X[mask], f.y.to_numpy()[mask], np.log(expo[mask]))

    def rate(m, X):
        return np.minimum(np.exp(m.intercept_ + X @ m.coef_), risk.RiskModel.MAX_DAILY_SHARE) * expo

    # Wind recalibration: many gusty days in the extract have no records, which drags the wind
    # response down (in-sample, wind events come out 3-8x low). Scale wind-driven days so the
    # training wind/tropical events match their observed totals (leaf-on factor applied first).
    wind_day = ((f.frz < 0.1) & (f.gust_max >= 30)).to_numpy()
    leaf_mult = np.where(f.day.dt.month.between(5, 10).to_numpy(), risk.LEAF_ON_FACTOR, 1.0)
    wind_ev_day = f.event.isin(HAZARD_EVENTS["wind"] + HAZARD_EVENTS["tropical"]).to_numpy()

    def wind_calibration(m, X, train_mask):
        sel = train_mask & wind_day & wind_ev_day
        return float(f.y.to_numpy()[sel].sum() / max((rate(m, X) * leaf_mult)[sel].sum(), 1e-9))

    def hazard_mixes(d):
        out = {hz: d[d.event.isin(evs)].asset_type.value_counts(normalize=True).round(4).to_dict()
               for hz, evs in HAZARD_EVENTS.items()}
        out["all"] = d.asset_type.value_counts(normalize=True).round(4).to_dict()
        return out

    mixes = hazard_mixes(dmg)

    def outage_step(exclude: list[str]):
        """Placement table + outage calibration fitted on real damage, leaving out `exclude` events."""
        d = dmg[~dmg.event.isin(exclude)]
        mx = hazard_mixes(d)
        placement = risk.fit_placement(d)
        events = []
        for evs, hz in OUTAGE_CALIB.values():
            if set(evs) & set(exclude):
                continue
            sub = d[d.event.isin(evs)]
            lam = np.bincount(sub.cellpos.astype(int), minlength=ncell).astype(float)
            events.append((lam, g.premises_out(sub.iso_dev.to_numpy()), mx[hz]))
        return dict(placement=placement, cluster_size=risk.fit_cluster_size(events, placement)), mx

    validation = {}
    for name, (a, b, evs) in HOLDOUTS.items():
        hold = (f.day >= a) & (f.day <= b)
        X = risk.design(f, g.cells, hist_rows(evs))
        m = fit(~hold.to_numpy(), X)
        c = wind_calibration(m, X, ~hold.to_numpy())
        lam_rows = (rate(m, X) * np.where(wind_day, c * leaf_mult, 1.0))[hold.to_numpy()]
        sub = f[hold].assign(lam=lam_rows)
        lam_cell = np.bincount(sub.cellpos, weights=sub.lam, minlength=len(g.cells))
        act_cell = np.bincount(sub.cellpos, weights=sub.y, minlength=len(g.cells))
        rho = spearmanr(lam_cell, act_cell).statistic
        # premise-level outage: predicted probability vs. downstream of a real damaged device
        outage, fold_mixes = outage_step(evs)
        mix = fold_mixes[OUTAGE_CALIB[name][1]]
        p_out = risk.premise_outage_prob(risk.device_rates(lam_cell, mix, placement=outage["placement"]),
                                         outage["cluster_size"])
        real = dmg[dmg.event.isin(evs)]
        actual_out = g.premises_out(real.iso_dev.to_numpy())
        auc = roc_auc_score(actual_out, p_out)
        cust = g.prem_customers
        bands = [risk.band(p) for p in p_out]
        rel = (pd.DataFrame(dict(band=bands, p=p_out, out=actual_out, w=cust))
               .groupby("band").apply(lambda d: pd.Series(dict(
                   customers=int(d.w.sum()), predicted=float(np.average(d.p, weights=d.w)),
                   actual=float(np.average(d.out, weights=d.w)))), include_groups=False))
        validation[name] = dict(
            trained_without=name, predicted_damage=round(float(lam_cell.sum()), 1),
            actual_damage=int(act_cell.sum()), cell_rank_corr=round(float(rho), 3),
            premise_auc=round(float(auc), 3),
            predicted_customers_out=int((p_out * cust).sum()), actual_customers_out=int(cust[actual_out].sum()),
            outage_cluster_size=outage["cluster_size"],
            reliability={k: {kk: round(v, 3) if isinstance(v, float) else v for kk, v in r.items()}
                         for k, r in rel.to_dict(orient="index").items()},
        )
        log(name, validation[name])

    # What customers are told: the share of customers in each band who actually lost power in past
    # storms, pooled over the hold-out tests (each storm predicted by a model that never saw it).
    band_outcomes = {}
    for b in risk.BAND_ORDER:
        rows = [(v["reliability"][b]["customers"], v["reliability"][b]["actual"], k)
                for k, v in validation.items() if b in v["reliability"]]
        n = sum(r[0] for r in rows)
        if n:
            band_outcomes[b] = dict(raw_share=round(sum(c * a for c, a, _ in rows) / n, 3), customers=int(n),
                                    storms=[k for c, _, k in rows if c > 0])
    # A higher band must never read as safer: pool adjacent bands that come out of order
    # (customer-weighted pool-adjacent-violators), so the shares rise with the band.
    blocks = [[b] for b in band_outcomes]

    def share(bl):
        return (sum(band_outcomes[b]["raw_share"] * band_outcomes[b]["customers"] for b in bl)
                / sum(band_outcomes[b]["customers"] for b in bl))

    i = 0
    while i < len(blocks) - 1:
        if share(blocks[i]) > share(blocks[i + 1]):
            blocks[i:i + 2] = [blocks[i] + blocks[i + 1]]
            i = max(i - 1, 0)
        else:
            i += 1
    for bl in blocks:
        for b in bl:
            band_outcomes[b]["share"] = round(share(bl), 3)
    log("band outcomes", band_outcomes)

    X = risk.design(f, g.cells, hist_rows([]))
    m = fit(np.ones(len(f), bool), X)
    c_wind = wind_calibration(m, X, np.ones(len(f), bool))
    log("wind calibration factor", round(c_wind, 2))
    outage, _ = outage_step([])
    log("outage step", {k: v for k, v in outage.items() if k != "placement"})
    rng = dict(gust_max=float(f.gust_max.max()), frz=float(f.frz.max()), snow=float(f.snow.max()),
               rain72=float(f.rain72.max()), tmin=float(f.tmin.min()), tmax=float(f.tmax.max()))
    out = dict(coef=m.coef_.round(5).tolist(), intercept=round(float(m.intercept_), 5),
               features=[k for k, _ in risk.FEATURES], labels=[l for _, l in risk.FEATURES],
               mixes=mixes, outage=outage, validation=validation, band_outcomes=band_outcomes, train_range=rng,
               trained_on=f"{f.day.min().date()} to {f.day.max().date()}", rows=int(len(f)),
               damage_records=int(f.y.sum()), wind_calibration=round(c_wind, 3), leaf_on_factor=risk.LEAF_ON_FACTOR, excluded_days=[str(d.date()) for d in severe_unlabeled])
    risk.MODEL_PATH.write_text(json.dumps(out, indent=1))
    log("coefficients", dict(zip(out["features"], out["coef"])), "intercept", out["intercept"])
    log("saved", risk.MODEL_PATH)


if __name__ == "__main__":
    main()
