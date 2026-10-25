"""Turns a simulation result into the JSON the dashboards need, with privacy rules applied.

Privacy rules (PLAN.md section 7):
- outage pins sit on the protective device, never on a home; aggregates under 5 customers are hidden
- hospitals / fire / EMS locations only in AEP views
- a customer only ever sees their own premise
"""
import json

import numpy as np
import pandas as pd

from . import risk
from .data import PROCESSED, grid
from .structures import repair_kit

MIN_CUSTOMERS = 5


def _r(x, n=1):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def hours_label(h: float) -> str:
    if h < 1:
        return f"{max(int(round(h * 60, -1)), 10)} min"
    if h < 48:
        return f"{h:.0f} h" if h >= 3 else f"{h:.1f} h"
    return f"{h / 24:.1f} days"


# ------------------------------------------------------------------ overview + cells
def overview(res: dict, aep: bool) -> dict:
    out = dict(scenario=res["scenario"], params=res["params"], summary=res["summary"], operations=res.get("operations"),
               confidence=res["confidence"], weather_hours=res["weather_hours"],
               start=res["time"][0], horizon_hours=len(res["time"]))
    out["curve"] = _curve(res)
    if aep:
        out["cost"] = res["cost"]
    else:
        out["cost"] = None
    return out


def _curve(res):
    runs = res["runs"]
    if not runs:
        return dict(hours=[], p10=[], p50=[], p90=[])
    H = len(runs[0]["curve"])
    last = max(int(max(r["rest_max"] for r in runs)) + 6, res["weather_hours"])
    last = min(last, H)
    m = np.stack([r["curve"][:last] for r in runs])
    step = max(1, last // 240)
    return dict(hours=list(range(0, last, step)),
                p10=np.percentile(m, 10, axis=0)[::step].round().tolist(),
                p50=np.percentile(m, 50, axis=0)[::step].round().tolist(),
                p90=np.percentile(m, 90, axis=0)[::step].round().tolist())


def cells(res: dict) -> list[dict]:
    g = grid()
    c = g.cells
    p_out = res["p_out"]
    cust = g.prem_customers
    w = np.bincount(g.prem_cell, weights=cust, minlength=len(c))
    pw = np.bincount(g.prem_cell, weights=cust * p_out, minlength=len(c))
    mean_p = np.where(w > 0, pw / np.maximum(w, 1), 0)
    contrib = res["contrib"]
    labels = risk.model().meta["labels"]
    peak = res["peak"]
    rows = []
    for i in range(len(c)):
        if w[i] < MIN_CUSTOMERS:
            continue
        top = np.argsort(-contrib[i])[:3]
        rows.append(dict(cell=int(c.index[i]), lon=_r(c.lon.iloc[i], 4), lat=_r(c.lat.iloc[i], 4),
                         customers=int(w[i]), p_out=_r(mean_p[i], 3), band=risk.band(mean_p[i]),
                         observed=risk.band_outcome(risk.band(mean_p[i])),
                         exp_damage=_r(res["lam"][i], 2), gust=_r(peak.gust_max.iloc[i]),
                         ice=_r(peak.frz.iloc[i], 2),
                         factors=[labels[k] for k in top if contrib[i, k] > 0.05]))
    return rows


def frames(res: dict, step: int = 1) -> dict:
    """Customers out per cell per hour (median run) + damage events, for the 3D replay."""
    g = grid()
    med = res["median"]
    H = res["weather_hours"] + 72
    if med is None:
        return dict(hours=[], cells=[], out=[], damage=[])
    out, st, rest = med["out"], med["st"], med["rest"]
    H = min(max(H, int(np.ceil(rest.max())) + 6), len(res["time"]))
    ncell = len(g.cells)
    m = np.zeros((ncell, H + 1))
    idx = np.nonzero(out)[0]
    cust = g.prem_customers
    np.add.at(m, (g.prem_cell[idx], np.clip(st[idx].astype(int), 0, H)), cust[idx])
    np.add.at(m, (g.prem_cell[idx], np.clip(np.ceil(rest[idx]).astype(int), 0, H)), -cust[idx])
    m = np.cumsum(m, axis=1)[:, :H:step]
    keep = np.nonzero(m.max(axis=1) >= MIN_CUSTOMERS)[0]
    a = g.assets
    dmg = [dict(t=_r(t), done=_r(f), lon=_r(a.lon.iloc[i], 4), lat=_r(a.lat.iloc[i], 4), type=a.asset_type.iloc[i])
           for i, t, f in zip(med["idx"], med["when"], med["finish"])]
    return dict(hours=list(range(0, H, step)), start=res["time"][0],
                cells=[dict(cell=int(g.cells.index[k]), lon=_r(g.cells.lon.iloc[k], 4), lat=_r(g.cells.lat.iloc[k], 4))
                       for k in keep],
                out=m[keep].round().astype(int).tolist(), damage=dmg)


# ------------------------------------------------------------------ AEP: pins, areas, jobs
def device_pins(res: dict) -> list[dict]:
    g = grid()
    med = res["median"]
    if med is None:
        return []
    d = g.dev
    hit = np.nonzero(med["dev_time"] > 0)[0]
    rows = []
    for j in hit:
        c = int(d.customers.iloc[j])
        if c < MIN_CUSTOMERS:
            continue
        rows.append(dict(device=int(j), kind=d.kind.iloc[j], lon=_r(d.lon.iloc[j], 5), lat=_r(d.lat.iloc[j], 5),
                         customers=c, out_at=_r(med["dev_start"][j]), restored_at=_r(med["dev_time"][j]),
                         life_support=int(g.dev_life_support[j])))
    return rows


def area_outages(res: dict, hour: float | None = None) -> dict:
    """% of AEP customers out by ZIP and circuit at a given hour (default: peak hour of median run)."""
    g = grid()
    med = res["median"]
    if med is None:
        return dict(hour=0, zip=[], circuit=[])
    if hour is None:
        hour = float(np.argmax(med["curve"]))
    out_now = med["out"] & (med["st"] <= hour) & (med["rest"] > hour)
    df = g.prem.assign(out=out_now * g.prem_customers)
    res_ = {}
    for key in ("zip", "circuit"):
        agg = df.groupby(key).agg(customers=("customers", "sum"), out=("out", "sum")).reset_index()
        agg["pct_out"] = (100 * agg.out / agg.customers).round(1)
        agg = agg[agg.customers >= MIN_CUSTOMERS].sort_values("pct_out", ascending=False)
        res_[key] = agg.rename(columns={key: "id"}).to_dict(orient="records")
    return dict(hour=hour, **res_)


def jobs(res: dict, limit: int = 400) -> list[dict]:
    g = grid()
    med = res["median"]
    if med is None:
        return []
    a = g.assets
    order = np.argsort(med["start"])
    rows = []
    for k in order[:limit]:
        i = int(med["idx"][k])
        iso = int(med["iso"][k])
        rows.append(dict(job=int(k), asset=i, type=a.asset_type.iloc[i], structure=a.structure.iloc[i]
                         if isinstance(a.structure.iloc[i], str) else None,
                         drawing=int(a.drawing_page.iloc[i]) if a.asset_type.iloc[i] == "pole" else None,
                         lon=_r(a.lon.iloc[i], 4), lat=_r(a.lat.iloc[i], 4), damaged_at=_r(med["when"][k]),
                         start=_r(med["start"][k]), finish=_r(med["finish"][k]), crew=int(med["crew"][k]),
                         person_hours=_r(med["person_h"][k]), access_issue=bool(med["acc"][k]),
                         special_equipment=bool(med["spec"][k]), customers_behind=int(g.dev_customers[iso]),
                         life_support_behind=int(g.dev_life_support[iso])))
    return rows


def job_detail(res: dict, job: int) -> dict:
    g = grid()
    med = res["median"]
    i = int(med["idx"][job])
    asset = g.assets.iloc[i].to_dict()
    asset = {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in asset.items()}
    dmg = dict(access_issue="Yes" if med["acc"][job] else "No",
               special_equipment="Other" if med["spec"][job] else "")
    kit = repair_kit(asset, dmg)
    return dict(asset={k: asset[k] for k in ("asset_type", "structure", "size_group", "height_ft", "material",
                                             "install_year", "phases", "xfmr_kva", "kva", "shared") if k in asset},
                kit=kit, crew_hours=_r(med["dur"][job], 2), start=_r(med["start"][job]),
                finish=_r(med["finish"][job]))


def facilities() -> list[dict]:
    return json.loads((PROCESSED / "facilities.json").read_text())


# ------------------------------------------------------------------ customer: own premise only
def premise_status(res: dict, pidx: int) -> dict:
    g = grid()
    pr = g.prem.iloc[pidx]
    p_out = float(res["p_out"][pidx])
    chain = g.chain_of(pidx)
    devs = chain.index.to_numpy()  # device row positions
    dev_ids = np.array([g.dev.index.get_loc(k) for k in devs]) if len(devs) else np.array([], int)
    runs = res["runs"]
    outs, starts, ends, causes = [], [], [], {}
    for r in runs:
        times = r["dev_time"][dev_ids] if len(dev_ids) else np.array([])
        if len(times) and times.max() > 0:
            st = float(np.min(r["dev_start"][dev_ids][times > 0]))
            en = float(times.max())
            outs.append(True)
            starts.append(st)
            ends.append(en)
            worst = int(dev_ids[int(np.argmax(times))])
            causes[worst] = causes.get(worst, 0) + 1
        else:
            outs.append(False)
    mc_out = float(np.mean(outs)) if outs else 0.0
    est = None
    if starts:
        dur = np.array(ends) - np.array(starts)
        est = dict(p10=_r(np.percentile(dur, 10)), p50=_r(np.percentile(dur, 50)), p90=_r(np.percentile(dur, 90)),
                   label=f"most likely {hours_label(np.percentile(dur, 25))}-{hours_label(np.percentile(dur, 75))}, "
                         f"could be up to {hours_label(np.percentile(dur, 90))}",
                   outage_start=_r(np.median(starts)), restored=_r(np.median(ends)))

    # what this event does: share of homes in the customer's ZIP that lose power (averaged over runs), and a
    # representative run for this home (median outage length among runs where it lost power)
    cust = g.prem_customers
    in_zip = (g.prem.zip == pr.zip).to_numpy()
    zip_total = max(float(cust[in_zip].sum()), 1.0)
    area_share = float(np.mean([cust[r["out"] & in_zip].sum() / zip_total for r in runs])) if runs else 0.0
    timeline = None
    if starts:
        out_runs = [r for r, o in zip(runs, outs) if o]
        dur = np.array(ends) - np.array(starts)
        k = int(np.argsort(dur)[len(dur) // 2])
        lost, back = starts[k], ends[k]
        assess = (res.get("operations") or {}).get("assess_hours", 2.0)
        hits = float(np.min(out_runs[k]["when"]))
        timeline = dict(storm_hits=_r(min(hits, lost)), power_lost=_r(lost), confirmed=_r(min(lost + assess, back)),
                        estimate_updated=_r(lost + 0.4 * (back - lost)) if back - lost > 4 else None,
                        restored=_r(back), hours_out=_r(back - lost))
    event = dict(area=f"ZIP {pr.zip}", area_share=_r(area_share, 3), home_share=_r(mc_out, 3), runs=len(runs),
                 timeline=timeline)

    # contributing factors (cell weather terms + topology exposure)
    m = risk.model()
    cpos = int(g.prem_cell[pidx])
    contrib = res["contrib"][cpos]
    labels = m.meta["labels"]
    peak = res["peak"].iloc[cpos]
    factors = []
    for k in np.argsort(-contrib)[:4]:
        if contrib[k] > 0.05:
            factors.append(dict(label=labels[k], weight=_r(contrib[k], 2)))
    dev_rate = res["dev_rate"][dev_ids] if len(dev_ids) else np.array([])
    exposure = []
    for j, rate in sorted(zip(dev_ids, dev_rate), key=lambda t: -t[1])[:3]:
        if rate <= 0:
            continue
        kind = g.dev.kind.iloc[j]
        exposure.append(dict(kind=kind, customers=int(g.dev.customers.iloc[j]), share=_r(rate, 3)))
    likely_cause = None
    if causes:
        j = max(causes, key=causes.get)
        kind = g.dev.kind.iloc[j]
        med = res["median"]
        types = []
        if med is not None:
            on = med["iso"] == j
            types = pd.Series(g.assets.asset_type.to_numpy()[med["idx"][on]]).value_counts().index.tolist()
        likely_cause = dict(device_kind=kind, customers_behind=int(g.dev.customers.iloc[j]),
                            share_of_runs=_r(causes[j] / max(sum(causes.values()), 1), 2), damage_types=types[:3])
    return dict(
        premise=dict(service=pr.service_kind, life_support=bool(pr.life_support), city=pr.city.title(),
                     zip=pr.zip, customers=int(pr.customers)),
        risk=dict(p_out=_r(p_out, 3), band=risk.band(p_out), observed=risk.band_outcome(risk.band(p_out)),
                  simulated_share=_r(mc_out, 2),
                  weather=dict(peak_gust=_r(peak.gust_max), ice_in=_r(peak.frz, 2), snow_in=_r(peak.snow, 1),
                               tmin=_r(peak.tmin), tmax=_r(peak.tmax)),
                  factors=factors, exposure=exposure),
        restoration=est, likely_cause=likely_cause, event=event,
        confidence=res["confidence"], scenario=res["scenario"], start=res["time"][0],
    )
