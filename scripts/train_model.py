"""Train and validate the damage-rate model on the two well-recorded local storms.

- Training storms: Feb 2025 (ice phase Feb 11-15, wind phase Feb 16-18) and Hurricane Helene
  (rain + wind, Sep 25 - Oct 2 2024). Each window includes a few calm lead-in/trailing days.
- Target: ARCOS damage records per grid cell per day (report date). January records are excluded.
- Features: Open-Meteo archive weather on the cell's weather point + cell exposure (engines/risk.py).
- Per-hazard behaviour learned from the damage reports (what breaks, access problems, special
  equipment) is saved for the simulation to apply to other storm types.
- Validation (only two storms exist): train on Feb 2025 -> predict Helene; train on Feb ice +
  Helene -> predict the Feb wind phase. The Feb ice phase is the only ice event, so it can't be held out.
- Final model is fit on both storms and saved to data/processed/risk_model.json.

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

# Training windows (inclusive)
WINDOWS = {
    "feb_2025": ("2025-02-01", "2025-03-03"),
    "helene_2024": ("2024-09-08", "2024-10-20"),
}
HAZARD_EVENTS = {  # what each hazard looks like in the damage reports
    "ice": ["feb_2025_ice"],
    "wind": ["feb_2025_wind"],
    "tropical": ["helene_2024", "helene_late_reports"],
}
TRAIN_EVENTS = sum(HAZARD_EVENTS.values(), [])
# hold-out tests: name -> (days held out, damage events held out, label for the UI)
HOLDOUTS = {
    "helene_2024": (("2024-09-08", "2024-10-20"), ["helene_2024", "helene_late_reports"],
                    "Trained on Feb 2025 (ice + wind) only, then predicted Hurricane Helene (rain + wind)"),
    "feb_2025_wind": (("2025-02-16", "2025-03-03"), ["feb_2025_wind"],
                      "Trained on the Feb 2025 ice phase + Helene, then predicted the Feb 2025 wind phase"),
}
# damage -> outage calibration storms: (events, hazard mix)
OUTAGE_CALIB = {
    "feb_2025_ice": (["feb_2025_ice"], "ice"),
    "feb_2025_wind": (["feb_2025_wind"], "wind"),
    "helene_2024": (["helene_2024", "helene_late_reports"], "tropical"),
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
    in_window = np.zeros(len(f), bool)
    for a, b in WINDOWS.values():
        in_window |= ((f.day >= a) & (f.day <= b)).to_numpy()
    f = f[in_window].reset_index(drop=True)
    dmg = g.damage.copy()
    dmg["day"] = pd.to_datetime(dmg.report_date)
    jan = dmg.day.dt.month == 1
    log("dropping January damage records:", int(jan.sum()))
    all_dmg = dmg[~jan].copy()  # every non-January record (for the "past damage nearby" prior)
    dmg = all_dmg[all_dmg.event.isin(TRAIN_EVENTS)].copy()
    cellpos = {c: i for i, c in enumerate(g.cell_ids)}
    dmg["cellpos"] = dmg.cell.map(cellpos)
    all_dmg["cellpos"] = all_dmg.cell.map(cellpos)
    y_counts = dmg.groupby(["cellpos", "day"]).size()
    f["y"] = y_counts.reindex(pd.MultiIndex.from_arrays([f.cellpos, f.day])).fillna(0).to_numpy()
    expo = risk.exposure(g.cells)[f.cellpos.to_numpy()]
    log("rows", len(f), "damage in window", int(f.y.sum()), "of", len(dmg))

    # "Past damage nearby" without leakage: each row's history excludes its own event, and in a
    # validation fold the held-out event is removed from everyone's history.
    ev_of_day = dmg.groupby("day").event.agg(lambda s: s.mode().iloc[0])
    f["event"] = ev_of_day.reindex(f.day).fillna("").to_numpy()
    ncell = len(g.cells)
    events = sorted(all_dmg.event.unique())
    cnt = np.zeros((ncell, len(events)))
    np.add.at(cnt, (all_dmg.cellpos.to_numpy(),
                    all_dmg.event.map({e: i for i, e in enumerate(events)}).to_numpy()), 1)
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

    def hazard_mixes(d):
        out = {hz: d[d.event.isin(evs)].asset_type.value_counts(normalize=True).round(4).to_dict()
               for hz, evs in HAZARD_EVENTS.items()}
        out["all"] = d.asset_type.value_counts(normalize=True).round(4).to_dict()
        return out

    mixes = hazard_mixes(dmg)

    # what each hazard does, learned from its damage reports (applied to other storm types)
    behaviour = {}
    for hz, evs in HAZARD_EVENTS.items():
        sub = dmg[dmg.event.isin(evs)]
        rd = sub.repair_days.dropna()
        rd = rd[(rd >= 0) & (rd <= 14)]
        behaviour[hz] = dict(records=int(len(sub)), access_rate=round(float((sub.access_issue == "Yes").mean()), 3),
                             special_equipment_rate=round(float(sub.special_equipment.fillna("").ne("").mean()), 3),
                             median_repair_days=float(rd.median()) if len(rd) else None, mix=mixes[hz])
    log("hazard behaviour", {k: {kk: vv for kk, vv in v.items() if kk != "mix"} for k, v in behaviour.items()})

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
    for name, ((a, b), evs, label) in HOLDOUTS.items():
        hold = (f.day >= a) & (f.day <= b)
        X = risk.design(f, g.cells, hist_rows(evs))
        m = fit(~hold.to_numpy(), X)
        lam_rows = rate(m, X)[hold.to_numpy()]
        sub = f[hold].assign(lam=lam_rows)
        lam_cell = np.bincount(sub.cellpos, weights=sub.lam, minlength=len(g.cells))
        act_cell = np.bincount(sub.cellpos, weights=sub.y, minlength=len(g.cells))
        rho = spearmanr(lam_cell, act_cell).statistic
        # premise-level outage: predicted probability vs. downstream of a real damaged device
        outage, fold_mixes = outage_step(evs)
        mix = fold_mixes.get(OUTAGE_CALIB[name][1]) or fold_mixes["all"]  # no leak of the held-out mix
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
            trained_without=name, label=label, predicted_damage=round(float(lam_cell.sum()), 1),
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
    outage, _ = outage_step([])
    log("outage step", {k: v for k, v in outage.items() if k != "placement"})
    rng = dict(gust_max=float(f.gust_max.max()), frz=float(f.frz.max()), snow=float(f.snow.max()),
               rain72=float(f.rain72.max()), tmin=float(f.tmin.min()), tmax=float(f.tmax.max()))
    out = dict(coef=m.coef_.round(5).tolist(), intercept=round(float(m.intercept_), 5),
               features=[k for k, _ in risk.FEATURES], labels=[l for _, l in risk.FEATURES],
               mixes=mixes, outage=outage, validation=validation, band_outcomes=band_outcomes, train_range=rng,
               trained_on="Feb 1 - Mar 3, 2025 and Sep 8 - Oct 20, 2024", training_storms=list(WINDOWS),
               rows=int(len(f)), damage_records=int(f.y.sum()), hazard_behaviour=behaviour,
               excluded_records=dict(january=int(jan.sum())))
    risk.MODEL_PATH.write_text(json.dumps(out, indent=1))
    log("coefficients", dict(zip(out["features"], out["coef"])), "intercept", out["intercept"])
    log("saved", risk.MODEL_PATH)


if __name__ == "__main__":
    main()
