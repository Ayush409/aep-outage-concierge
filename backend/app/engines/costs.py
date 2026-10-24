"""Business and customer impact of a simulated event. Every constant cites its source."""
import numpy as np

SOURCES = {
    "eia_res": dict(label="EIA 2024 Average Monthly Bill - Residential (Form 861, table 5A), Virginia",
                    url="https://www.eia.gov/electricity/sales_revenue_price/pdf/table_5A.pdf"),
    "eia_epm": dict(label="EIA Electric Power Monthly table 5.6.A (VA residential, Aug 2026 preliminary 17.64 c/kWh)",
                    url="https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a"),
    "bls": dict(label="BLS OEWS 49-9051 Electrical Power-Line Installers, national mean (May 2023)",
                url="https://www.bls.gov/oes/2023/may/oes499051.htm"),
    "fema": dict(label="FEMA Schedule of Equipment Rates 2025 (codes 8486-8489 aerial lift incl. truck; digger derrick)",
                 url="https://adeca.alabama.gov/wp-content/uploads/2025-FEMA-Schedule-of-Equipment-Rates.pdf"),
    "ice": dict(label="LBNL-6941E Updated Value of Service Reliability (2015), via Nexant/LBNL ICE summary, 2013$",
                url="https://eta-publications.lbl.gov/sites/default/files/nexant-smartgrid-customer-reliability-benefits-2015.pdf"),
    "workbook": dict(label="AEP Install_Labor_HackOHIO.xlsx (CU hours, ILM 4.5)", url=None),
    "assumption": dict(label="Team assumption - replace with AEP figures", url=None),
}

AVG_KWH_MONTH = 1032  # eia_res
PRICE_PER_KWH = 0.1441  # eia_res (2024 annual average)
AVG_KW = AVG_KWH_MONTH / 730.5
WAGE = 41.30  # bls
OVERTIME = 1.5  # assumption: storm work at time-and-a-half
BUCKET_TRUCK_HR = 70.0  # fema: midpoint of $62.86-78.43
DIGGER_DERRICK_HR = 47.61  # fema
CREW_SIZE = 4  # assumption pending AEP mentors
MUTUAL_AID_RATE_MULT = 1.5  # assumption: contractor / mutual-aid premium on labour
LODGING_PER_PERSON_DAY = 250.0  # assumption: lodging + meals
CPI_2013_TO_NOW = 1.38  # assumption: approx CPI-U change 2013 -> 2026

# LBNL residential cost per interruption event (2013$) by duration in hours (ice)
ICE_RES = [(0.083, 3.9), (0.5, 4.5), (1, 5.1), (4, 9.5), (8, 17.2), (16, 32.4)]

# Materials per damaged asset (low, high), USD - assumption, no public AEP prices
MATERIALS = {
    "pole": (1500, 3500), "primary": (200, 800), "secondary": (100, 400), "transformer": (2000, 5000),
    "fuse": (150, 400), "recloser": (15000, 30000), "switch": (1000, 3000),
}


def load_multiplier(temp_f: np.ndarray) -> np.ndarray:
    """Household load relative to average: more A/C above 75 F, more heating below 55 F (assumption)."""
    t = np.asarray(temp_f, dtype=float)
    return np.clip(1 + 0.03 * np.maximum(t - 75, 0) + 0.02 * np.maximum(55 - t, 0), 0.6, 3.0)


def ice_cost_per_customer(hours: np.ndarray) -> np.ndarray:
    """Residential cost per outage event, interpolated (and linearly extended past 16 h), in today's $."""
    h = np.asarray(hours, dtype=float)
    xs = np.array([x for x, _ in ICE_RES])
    ys = np.array([y for _, y in ICE_RES])
    slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    v = np.where(h <= xs[-1], np.interp(h, xs, ys), ys[-1] + slope * (h - xs[-1]))
    return np.where(h > 0, v, 0.0) * CPI_2013_TO_NOW


def summarize(person_hours, local_person_hours, pole_crew_hours, crew_hours, asset_counts: dict,
              out_curve: np.ndarray, temp_series: np.ndarray, outage_hours: np.ndarray,
              outage_customers: np.ndarray, mutual_aid_person_days: float) -> dict:
    """All monetary outputs for one simulated event (median run)."""
    aid_ph = max(person_hours - local_person_hours, 0)
    labor_local = local_person_hours * WAGE * OVERTIME
    labor_aid = aid_ph * WAGE * OVERTIME * MUTUAL_AID_RATE_MULT
    lodging = mutual_aid_person_days * LODGING_PER_PERSON_DAY
    equipment = crew_hours * BUCKET_TRUCK_HR + pole_crew_hours * DIGGER_DERRICK_HR
    mat_lo = sum(MATERIALS.get(k, (0, 0))[0] * n for k, n in asset_counts.items())
    mat_hi = sum(MATERIALS.get(k, (0, 0))[1] * n for k, n in asset_counts.items())
    n = len(out_curve)
    temp = np.resize(temp_series, n) if len(temp_series) else np.full(n, 65.0)
    kwh_lost = float(np.sum(out_curve * AVG_KW * load_multiplier(temp)))
    revenue = kwh_lost * PRICE_PER_KWH
    customer_cost = float(np.sum(ice_cost_per_customer(outage_hours) * outage_customers))
    repair_mid = labor_local + labor_aid + lodging + equipment + (mat_lo + mat_hi) / 2
    return dict(
        lost_revenue=round(revenue),
        kwh_not_served=round(kwh_lost),
        customer_hours=round(float(np.sum(out_curve))),
        repair=dict(labor_local=round(labor_local), labor_mutual_aid=round(labor_aid), lodging=round(lodging),
                    equipment=round(equipment), materials_low=round(mat_lo), materials_high=round(mat_hi),
                    total_mid=round(repair_mid)),
        customer_cost=round(customer_cost),
        person_hours=round(person_hours),
        crew_hours=round(crew_hours),
        formulas=dict(
            lost_revenue="customers out per hour x 1.41 kW avg load x temperature load factor x $0.1441/kWh",
            labor="person-hours (CU hours + access adders, x ILM 4.5) x $41.30 x 1.5 overtime; mutual aid x1.5",
            equipment="crew-hours x $70 bucket truck + pole-job crew-hours x $47.61 digger derrick",
            materials="damaged assets x low/high unit cost (assumption)",
            customer_cost="each customer's outage length -> LBNL residential cost per event x 1.38 (2013$ -> now)",
        ),
        sources=SOURCES,
    )
