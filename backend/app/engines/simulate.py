"""Scenario simulation: damage -> outages (topology) -> crew scheduling -> restoration ranges -> costs.

One call to run() produces everything the dashboards and the 3D replay need. Results are cached
by scenario + slider values.
"""
import heapq
import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from . import costs, risk
from .data import PROCESSED, grid
from .scenarios import SCENARIOS, tornado_tracks, weather_for
from .structures import kit_direct_hours, labor
from .weather import cell_to_point

WIND_STOP = 30.0  # mph gust: no bucket work (team-confirmed limit 28-30 mph)
WIND_CAUTION = 28.0  # mph gust: reduced productivity
SHIFT = (6, 22)  # crews work 16 h shifts
ASSESS_DELAY = 2.0  # hours from damage to a job being assessed and released (storm mode)
NORMAL_OPS_ASSESS = 1.0  # isolated faults: trouble crew dispatched within the hour
STORM_MODE_JOBS = 25  # expected damage jobs above which AEP switches to storm shifts
HORIZON_DAYS = 21
# fallbacks if the model has no learned hazard behaviour (share of jobs with access issues / special equipment)
ACCESS_RATE = 0.32
SPECIAL_EQ_RATE = 0.17


@dataclass(frozen=True)
class Params:
    scenario: str = "feb_2025"
    crews: int = 20  # 45 + 45 matched the real Feb 2025 repair times (1,254 jobs); smaller storms need fewer
    mutual_aid_crews: int = 20
    mutual_aid_day: float = 1.0
    gust_mult: float = 1.0
    access_mult: float = 1.0
    runs: int = 40
    seed: int = 7


# ------------------------------------------------------------------ static helpers
@lru_cache(maxsize=1)
def asset_hours() -> np.ndarray:
    """Direct repair hours (no adders) for every asset, from the structure kits."""
    a = grid().assets
    cols = ["asset_type", "structure", "size_group", "height_ft", "xfmr_kva", "phases", "aep_constr", "kva",
            "drawing_page"]
    out = np.zeros(len(a))
    for _, idx in a.groupby(cols, dropna=False).groups.items():
        row = a.loc[idx[0], cols].to_dict()
        row = {c: (None if (isinstance(v, float) and math.isnan(v)) else v) for c, v in row.items()}
        out[np.asarray(idx)] = kit_direct_hours(row)
    return out


@lru_cache(maxsize=1)
def _assets_by_device() -> tuple[np.ndarray, np.ndarray]:
    """Asset indices sorted by isolating device; assets of device d are order[start[d]:start[d + 1]]."""
    g = grid()
    iso = g.assets.iso_dev.to_numpy()
    order = np.argsort(iso, kind="stable")
    start = np.searchsorted(iso[order], np.arange(g.n_dev + 1))
    return order, start


@lru_cache(maxsize=1)
def _facility_cells() -> set:
    """Grid cells containing a hospital (their circuits get restoration priority)."""
    import json
    g = grid()
    fac = json.loads((PROCESSED / "facilities.json").read_text())
    cells = set()
    for f in fac:
        if f["kind"] == "hospital":
            ix = int(math.floor((f["lon"] + 80.26) / 0.02))
            iy = int(math.floor((f["lat"] - 36.99) / 0.02))
            cid = iy * 1000 + ix
            pos = np.where(g.cell_ids == cid)[0]
            if len(pos):
                cells.add(int(pos[0]))
    return cells


# which training hazard's damage behaviour each storm type borrows
LEARNED_FROM = {"ice": "ice", "snow": "ice", "wind": "wind", "tornado": "wind", "tropical": "tropical"}


def _learned_hazard(sc: dict, peak: pd.DataFrame) -> str:
    hz = sc["hazard"]
    if hz == "auto":
        hz = "ice" if peak.frz.max() > 0.1 else ("tropical" if peak.rain72.max() > 2 else "wind")
    return LEARNED_FROM.get(hz, "wind")


def _hazard_mix(sc: dict, peak: pd.DataFrame) -> dict:
    mixes = risk.model().meta["mixes"]
    return mixes.get(_learned_hazard(sc, peak), mixes["all"])


def _hazard_behaviour(sc: dict, peak: pd.DataFrame) -> dict:
    """Access-problem and special-equipment rates learned from that hazard's real damage reports."""
    b = risk.model().meta.get("hazard_behaviour", {}).get(_learned_hazard(sc, peak), {})
    return dict(access_rate=b.get("access_rate", ACCESS_RATE),
                special_equipment_rate=b.get("special_equipment_rate", SPECIAL_EQ_RATE))


# ------------------------------------------------------------------ hazard rules (lower confidence)
def _rule_rates(sc: dict, hourly, n_assets: int):
    """Extra per-asset damage rate + preferred hour, for hazards outside the training data."""
    g = grid()
    a = g.assets
    rate = np.zeros(n_assets)
    when = np.full(n_assets, -1.0)
    rules = sc.get("rules", [])
    pt = cell_to_point()
    acell = np.maximum(g.asset_cell, 0)
    temp = hourly.f["temperature_2m"]  # (points, hours)
    is_x = (a.asset_type == "transformer").to_numpy()
    kva = np.maximum(a.kva.fillna(25).to_numpy(), 10)
    cust = a.customers.fillna(1).to_numpy()
    if "heat" in rules or "cold" in rules:
        t_x = temp[pt[acell[is_x]]]  # (transformers, hours)
        if "heat" in rules:
            load_kw = 4.0  # assumption: peak household demand in extreme heat
            stress = np.maximum(t_x - 95, 0) / 10
            k = 0.0008  # tuned so a 115 F multi-day heat wave fails a few % of transformers
        else:
            load_kw = 5.0  # assumption: electric heat at single-digit temperatures
            stress = np.maximum(10 - t_x, 0) / 10
            k = 0.0006
        ratio = np.maximum(cust[is_x] * load_kw / kva[is_x], 0.2)
        dose = stress.sum(axis=1) * ratio
        rate[is_x] += np.minimum(k * dose, 0.5)
        when[is_x] = np.argmax(stress, axis=1)
    if "tornado" in rules:
        tracks = tornado_tracks()
        xy = np.column_stack([(a.lon.to_numpy() + 80) * 88_700, (a.lat.to_numpy() - 37.24) * 110_540])
        p_ef = {0: 0.15, 1: 0.4, 2: 0.7, 3: 0.9, 4: 0.97, 5: 0.99}
        start = pd.Timestamp(hourly.time.iloc[0])
        overhead = a.asset_type.isin(["pole", "primary", "secondary", "transformer", "fuse", "recloser",
                                      "switch"]).to_numpy()
        for tr in tracks:
            p0 = np.array([(tr["slon"] + 80) * 88_700, (tr["slat"] - 37.24) * 110_540])
            p1 = np.array([(tr["elon"] + 80) * 88_700, (tr["elat"] - 37.24) * 110_540])
            half = max(tr["width_yd"] * 0.9144 / 2, 40.0)
            seg = p1 - p0
            L2 = float(seg @ seg) or 1.0
            tt = np.clip(((xy - p0) @ seg) / L2, 0, 1)
            d = np.hypot(*(xy - (p0 + tt[:, None] * seg)).T)
            hit = (d <= half) & overhead
            if not hit.any():
                continue
            p = p_ef.get(tr["mag"], 0.5)
            rate[hit] += -math.log(1 - p)
            hh, mm = int(tr["time"][:2]), int(tr["time"][3:5])
            t_hit = (pd.Timestamp("2011-04-27") + pd.Timedelta(hours=hh + 1, minutes=mm) - start)  # CST -> EDT
            when[hit] = t_hit.total_seconds() / 3600
    return rate, when


# ------------------------------------------------------------------ scheduling
def _calendar(hourly, horizon: int, storm_mode: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Crew working capacity per hour. Storm mode: 16 h shifts. Normal ops: 24/7 trouble crews.
    Bucket work stops in high wind either way."""
    gmax = np.median(hourly.f["wind_gusts_10m"], axis=0)  # typical gust across the area, not the worst ridgetop
    hours = pd.date_range(hourly.time.iloc[0], periods=horizon, freq="h")
    cap = np.where((hours.hour >= SHIFT[0]) & (hours.hour < SHIFT[1]), 1.0, 0.0) if storm_mode         else np.ones(horizon)
    g = np.zeros(horizon)
    g[: len(gmax)] = gmax[:horizon]
    cap = np.where(g >= WIND_STOP, 0.0, np.where(g >= WIND_CAUTION, 0.5 * cap, cap))
    return cap, np.concatenate([[0.0], np.cumsum(cap)])


def _finish(start: float, dur: float, cap, cum) -> float:
    k0 = int(start)
    if k0 >= len(cap):
        return start + dur * 24 / 16
    c = cum[k0] + cap[k0] * (start - k0) + dur
    k = int(np.searchsorted(cum, c))
    if k >= len(cum):
        return len(cap) + (c - cum[-1]) * 24 / 16
    return (k - 1) + (c - cum[k - 1]) / max(cap[k - 1], 1e-9)


def _schedule(release, dur, prio, n_local, n_aid, aid_start, cap, cum):
    order = np.argsort(release, kind="stable")
    crews = [(0.0, i) for i in range(n_local)] + [(aid_start, n_local + i) for i in range(n_aid)]
    heapq.heapify(crews)
    avail = []
    start = np.zeros(len(dur))
    finish = np.zeros(len(dur))
    crew_of = np.zeros(len(dur), int)
    r = 0
    done = 0
    while done < len(dur):
        t, c = heapq.heappop(crews)
        while r < len(order) and release[order[r]] <= t:
            j = order[r]
            heapq.heappush(avail, (-prio[j], j))
            r += 1
        if not avail:
            t = release[order[r]]
            while r < len(order) and release[order[r]] <= t:
                j = order[r]
                heapq.heappush(avail, (-prio[j], j))
                r += 1
        _, j = heapq.heappop(avail)
        start[j] = t
        finish[j] = _finish(t, dur[j], cap, cum)
        crew_of[j] = c
        heapq.heappush(crews, (finish[j], c))
        done += 1
    return start, finish, crew_of


# ------------------------------------------------------------------ main entry
@lru_cache(maxsize=48)
def run(p: Params) -> dict:
    g = grid()
    sc = SCENARIOS[p.scenario]
    rng = np.random.default_rng(p.seed)
    hourly = weather_for(p.scenario, p.gust_mult)
    T = hourly.hours
    H = T + 24 * HORIZON_DAYS
    lam, peak, contrib = risk.expected_damage(hourly, snow_ice_equiv=sc.get("snow_ice_equiv", 0.0))
    behave = _hazard_behaviour(sc, peak)
    mix = _hazard_mix(sc, peak)
    rule_rate, rule_when = _rule_rates(sc, hourly, len(g.assets))
    dev_storm = risk.device_rates(lam, mix)
    dev_rule = risk.device_rates(np.zeros_like(lam), mix, rule_rate)  # rule damage is not clustered
    dev_rate = dev_storm + dev_rule
    p_out = risk.premise_outage_prob(dev_storm, independent_rate=dev_rule)

    # hourly hazard intensity per cell (to time damage within the event)
    inten = hourly.hazard_intensity()[cell_to_point()]  # (cells, hours)
    inten_cdf = np.cumsum(inten, axis=1)
    inten_cdf /= inten_cdf[:, -1:]

    def sample_hours(cells):
        u = rng.random(len(cells))
        return np.array([np.searchsorted(inten_cdf[c], uu) for c, uu in zip(cells, u)], float) + rng.random(len(cells))

    hours_a = asset_hours()
    iso_all = g.assets.iso_dev.to_numpy()
    atype_all = g.assets.asset_type.to_numpy()
    lab = labor()
    fac_cells = _facility_cells()
    storm_mode = lam.sum() + (1 - np.exp(-rule_rate)).sum() >= STORM_MODE_JOBS
    assess = ASSESS_DELAY if storm_mode else NORMAL_OPS_ASSESS
    cap, cum = _calendar(hourly, H, storm_mode)
    t0 = pd.Timestamp(hourly.time.iloc[0])

    # ---- damage source
    real = None
    if sc["kind"] == "replay":
        real = g.damage[g.damage.event.isin(sc["damage_events"])].reset_index(drop=True)
        day = pd.to_datetime(real.report_date)
        lo = ((day - pd.Timedelta(days=1)) - t0).dt.total_seconds().to_numpy() / 3600
        hi = ((day + pd.Timedelta(hours=18)) - t0).dt.total_seconds().to_numpy() / 3600

    tcode = pd.Categorical(atype_all, categories=risk.ASSET_TYPES).codes
    mix_vec = np.array([mix.get(t, 0) for t in risk.ASSET_TYPES])
    prop = risk.asset_propensity()
    kclus = risk.cluster_size()
    iso_order, iso_start = _assets_by_device()

    def sample_damage():
        """Returns (asset idx, damage hour, access flag, special-equipment flag)."""
        if real is not None:
            idx = real.asset.to_numpy()
            when = np.empty(len(real))
            for k in range(len(real)):
                c = max(g.asset_cell[idx[k]], 0)
                a_, b_ = int(np.clip(lo[k], 0, T - 1)), int(np.clip(hi[k], 1, T))
                w = inten[c, a_:b_] if b_ > a_ else np.ones(1)
                when[k] = a_ + rng.choice(len(w), p=w / w.sum()) + rng.random()
            acc = (real.access_issue == "Yes").to_numpy()
            spec = real.special_equipment.fillna("").ne("").to_numpy()
            return idx, when, acc, spec
        # damage arrives in clusters on one device (mean kclus reports each), seeded by placement propensity
        n_c = rng.poisson(lam / kclus)
        picks = []
        for c in np.nonzero(n_c)[0]:
            present = [k for k, t in enumerate(risk.ASSET_TYPES) if (c, t) in g.assets_by_cell_type and mix_vec[k] > 0]
            if not present:
                continue
            w = mix_vec[present] / mix_vec[present].sum()
            types = rng.choice(present, size=n_c[c], p=w)
            for k in types:
                pool = g.assets_by_cell_type[(c, risk.ASSET_TYPES[k])]
                pw = prop[pool]
                seed = pool[rng.choice(len(pool), p=pw / pw.sum())]
                picks.append(seed)
                extra = rng.poisson(kclus - 1)
                d = iso_all[seed]
                if extra and d >= 0:
                    same = iso_order[iso_start[d]:iso_start[d + 1]]
                    picks.extend(same[rng.integers(len(same), size=extra)])
        idx = np.array(picks, dtype=int)
        when = sample_hours(np.maximum(g.asset_cell[idx], 0)) if len(idx) else np.zeros(0)
        if rule_rate.any():
            hit = np.nonzero(rng.random(len(rule_rate)) < 1 - np.exp(-rule_rate))[0]
            idx = np.concatenate([idx, hit])
            when = np.concatenate([when, np.maximum(rule_when[hit], 0) + rng.random(len(hit)) * 2])
        idx, first = np.unique(idx, return_index=True)
        when = when[first]
        acc = rng.random(len(idx)) < min(behave["access_rate"] * p.access_mult, 1.0)
        spec = rng.random(len(idx)) < behave["special_equipment_rate"]
        return idx, when, acc, spec

    runs = []
    for _ in range(p.runs):
        idx, when, acc, spec = sample_damage()
        if len(idx) == 0:
            runs.append(None)
            continue
        iso = iso_all[idx]
        direct = hours_a[idx] + acc * lab.adders["restricted_access"] + spec * lab.adders["specialized_handling"]
        person_h = direct * lab.ilm
        noise = rng.lognormal(-0.06, 0.35, len(idx))
        dur = person_h / costs.CREW_SIZE * noise
        release = when + assess
        cust = g.dev_customers[np.maximum(iso, 0)]
        boost = 200 * g.dev_life_support[np.maximum(iso, 0)] + np.array(
            [2000 if g.asset_cell[i] in fac_cells else 0 for i in idx])
        prio = (cust + boost + 1) / dur
        start, finish, crew_of = _schedule(release, dur, prio, p.crews, p.mutual_aid_crews,
                                           24 * p.mutual_aid_day, cap, cum)
        dev_time = np.zeros(g.n_dev, np.float32)
        np.maximum.at(dev_time, iso, finish)
        dev_start = np.full(g.n_dev, np.inf, np.float32)
        np.minimum.at(dev_start, iso, when)
        runs.append(dict(idx=idx, when=when, acc=acc, spec=spec, iso=iso, person_h=person_h, dur=dur,
                         start=start, finish=finish, crew=crew_of, dev_time=dev_time, dev_start=dev_start))
    for r in runs:
        if r is not None:
            r["assess"] = assess
    res = _summarize(p, sc, hourly, lam, peak, contrib, dev_rate, p_out, runs, H, rule_rate)
    res["operations"] = dict(storm_mode=bool(storm_mode), assess_hours=assess,
                             label="Storm mode: 16-hour crew shifts" if storm_mode else
                             "Normal operations: 24/7 trouble crews for isolated outages")
    return res


def _premise_times(run_):
    g = grid()
    rest = g.restore_times(run_["dev_time"].astype(float))
    st = np.full(g.n_prem, np.inf)
    np.minimum.at(st, g.chain_p, run_["dev_start"][g.chain_d].astype(float))
    out = rest > 0
    st[~out] = 0
    return out, st, rest


def _summarize(p, sc, hourly, lam, peak, contrib, dev_rate, p_out, runs, H, rule_rate):
    g = grid()
    cust = g.prem_customers
    valid = [r for r in runs if r is not None]
    per_run = []
    for r in valid:
        out, st, rest = _premise_times(r)
        hrs = np.maximum(rest - st, 0)[out]
        curve = np.zeros(H + 1)
        np.add.at(curve, np.clip(st[out].astype(int), 0, H), cust[out])
        np.add.at(curve, np.clip(np.ceil(rest[out]).astype(int), 0, H), -cust[out])
        curve = np.cumsum(curve)[:H]
        r.update(out=out, st=st, rest=rest, curve=curve)
        total_out = int(cust[out].sum())
        cum_restored = np.cumsum(np.bincount(np.clip(np.ceil(rest[out]).astype(int), 0, H), weights=cust[out],
                                             minlength=H + 1))
        t90 = float(np.searchsorted(cum_restored, 0.9 * total_out)) if total_out else 0.0
        onset = float(st[out].min()) if total_out else 0.0
        wait = r["start"] - (r["when"] + r.get("assess", ASSESS_DELAY))  # time a released job waits for a crew
        per_run.append(dict(customers_out=total_out, peak_out=float(curve.max()), customer_hours=float(curve.sum()),
                            t_all=float(rest.max()), t90=t90, jobs=len(r["idx"]),
                            person_hours=float(r["person_h"].sum()), median_hours=float(np.median(hrs)) if len(hrs) else 0,
                            t90_after_onset=max(t90 - onset, 0.0), crew_wait=float(np.median(np.maximum(wait, 0)))))
    stats = pd.DataFrame(per_run) if per_run else pd.DataFrame(
        [dict(customers_out=0, peak_out=0, customer_hours=0, t_all=0, t90=0, jobs=0, person_hours=0, median_hours=0,
              t90_after_onset=0, crew_wait=0)])
    med_i = int(np.argsort(stats.customer_hours.to_numpy())[len(stats) // 2]) if valid else -1
    med = valid[med_i] if valid else None

    def q(col):
        v = stats[col].to_numpy()
        return dict(p10=round(float(np.percentile(v, 10)), 1), p50=round(float(np.percentile(v, 50)), 1),
                    p90=round(float(np.percentile(v, 90)), 1))

    # ---- costs on the median run
    cost = None
    if med is not None:
        n_local = p.crews
        local = med["crew"] < n_local
        ph = med["person_h"]
        pole = grid().assets.asset_type.to_numpy()[med["idx"]] == "pole"
        aid_jobs = ~local
        aid_days = 0.0
        if aid_jobs.any():
            aid_days = p.mutual_aid_crews * costs.CREW_SIZE * max(
                math.ceil((med["finish"][aid_jobs].max() - 24 * p.mutual_aid_day) / 24), 1)
        counts = pd.Series(grid().assets.asset_type.to_numpy()[med["idx"]]).value_counts().to_dict()
        out, st, rest = med["out"], med["st"], med["rest"]
        temp_series = hourly.f["temperature_2m"].mean(axis=0)
        cost = costs.summarize(
            person_hours=float(ph.sum()), local_person_hours=float(ph[local].sum()),
            pole_crew_hours=float(med["dur"][pole].sum()), crew_hours=float(med["dur"].sum()), asset_counts=counts,
            out_curve=med["curve"], temp_series=temp_series, outage_hours=np.maximum(rest - st, 0)[out],
            outage_customers=cust[out], mutual_aid_person_days=aid_days)

    # ---- confidence
    m = risk.model()
    rng_ = m.train_range
    notes = list(sc.get("notes", []))
    level = "High"
    if peak.gust_max.max() > rng_.get("gust_max", 99) * 1.1 or peak.frz.max() > rng_.get("frz", 9) * 1.1:
        level = "Medium"
        notes.append("Weather is stronger than anything in the training data, so the model is extrapolating.")
    if sc.get("rules"):
        level = "Low" if rule_rate.sum() > lam.sum() else "Medium"
        notes.append("Part of the damage comes from physics-based rules (" + ", ".join(sc["rules"]) +
                     ") because no local records exist for this hazard.")
    if sc.get("snow_ice_equiv"):
        level = "Medium" if level == "High" else level
    if sc.get("gust_peak_obs"):
        level = "Medium" if level == "High" else level
    if sc["kind"] == "replay":
        notes.insert(0, "Damage locations and types are AEP's real ARCOS records; restoration times are simulated.")
    if sc["kind"] == "live" and lam.sum() < 1:
        notes.append("No damaging weather in the forecast.")

    return dict(params=p.__dict__, scenario=dict(id=p.scenario, **{k: v for k, v in sc.items() if k != "weather"}),
                time=[t.isoformat() for t in pd.date_range(hourly.time.iloc[0], periods=H, freq="h")],
                weather_hours=hourly.hours, hourly=hourly, lam=lam, peak=peak, contrib=contrib,
                dev_rate=dev_rate, p_out=p_out, runs=valid, median=med, stats=stats, cost=cost,
                summary=dict(customers_out=q("customers_out"), peak_out=q("peak_out"),
                             customer_hours=q("customer_hours"), hours_to_90pct=q("t90"), hours_to_all=q("t_all"),
                             jobs=q("jobs"), person_hours=q("person_hours"),
                             hours_onset_to_90pct=q("t90_after_onset"), crew_wait_hours=q("crew_wait"),
                             typical_outage_hours=q("median_hours"),
                             expected_damage=round(float(lam.sum() + (1 - np.exp(-rule_rate)).sum()), 1),
                             expected_customers_out=int((p_out * cust).sum()),
                             total_customers=int(cust.sum())),
                confidence=dict(level=level, notes=notes))
