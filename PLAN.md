# AI Outage Concierge — Build Plan

HackOHI/O 2026, AEP track. **Hacking ends Sunday 10:00 AM** (3-minute video due via the Discord Google form).

**Pitch:** a storm is coming to Roanoke, VA. Customers see their outage risk, how long restoration could take, what to do, and get alerts. AEP sees risk, damage, % out by ZIP/circuit, crew effort, and business cost. Judges can drop famous storms onto Virginia and watch it play out in 3D.

---

## 1. Scope at a glance

| Area | What it does | Priority |
|---|---|---|
| Data prep | Shapefiles + topology + labor sheet → clean SQLite tables / GeoJSON | P0 |
| Risk engine | Weather + grid features → outage probability → risk band + confidence + top factors | P0 |
| Restoration engine | Damage → labor hours × ILM → crews → Monte Carlo range, step restoration order | P0 |
| Simulation tab | Event picker, 3D replay (5–10 s), sliders, results | P0 |
| Customer view | Map, my status, prepare, alerts, my data | P1 |
| AEP view | Ops map, restoration planner, business impact, communications, audit | P1 |
| Auth | Login, sign up, forgot password, roles, mock accounts | P1 |
| Business impact | Publicly sourced revenue / crew / equipment / parts / customer-cost numbers | P1 |
| AI text layer | LLM writes explanations + messages from engine output only | P1 |
| Polish + video | Script, record, edit | P0 (last 3 h) |

If time runs out, **data prep + engines + Simulation tab alone meet the challenge's minimum demo.**

---

## 2. Stack

- **Backend:** Python, FastAPI, SQLite (single `.db` file) via SQLAlchemy.
- **Data prep:** geopandas, shapely, pyproj, pandas, openpyxl (one-time scripts, `scripts/`).
- **Frontend:** React + Vite, MapLibre GL (3D terrain), deck.gl (wind particles, extruded hex columns, device pins).
- **Weather:** Open-Meteo Forecast API (live) and Historical/Archive API (events, back to 1940). No key needed.
- **Severe weather:** SPC convective outlooks (current + archive) for thunderstorm/tornado risk.
- **AI layer:** Claude API (`claude-sonnet-5-5`) for plain-language explanations and messages.
- **SMS:** Twilio trial (or SMS preview screen if no account). In-app notification feed always.

---

## 3. Data prep (P0, do first)

All in `scripts/`, outputs to `data/processed/` (git-ignored).

1. Extract the zips (see `data/README.md`). Reproject the Web Mercator layers (ambulance, fire, hospitals) to WGS84.
2. **Customers:** keep `premise_nu`, `circuit_id`, transformer id, `kind_of_se` (OH/UG), lat/lon, `critical_c` (LS = life support). Drop empty fields.
3. **Topology:** parse `matched_upstream.txt` into
   - `premise_upstream(premise, hop, device_type, device_id, location)`
   - a device tree (`device → children`, `device → downstream premise count`).
   117,595 of 117,642 customers join on `premise_nu`.
4. **Damage (ARCOS, 1,659 rows):** tag each record by event:
   - `helene_2024` = 2024-09-26 … 09-30 (≈174 records)
   - `feb_2025` = 2025-02-12 … 02-18 (≈1,254 records)
   - `minor_wind_2025` = small clusters after Feb 2025, each on a 44–53 mph gust day: Mar 5–6 (4), Mar 16–17 (7), May 13–17 (6), May 31 (11), Oct 20 (5), Dec 19 (10). Extra training points for moderate wind.
   - Smaller named events (each confirmed against the weather archive): `winter_storm_2025_01` (Jan 6–7, 46), `helene_late_reports` (Oct 1–2 2024, 20, calm weather so likely delayed Helene finds), `storms_2024_04` (17), `storms_2024_05` (13), `wind_rain_2024_01` (11), `debby_remnants_2024_08` (11), `wind_2024_11` (8).
   - `background` = everything else (62 scattered records 2022–2026)
   - Tagged export already exists: `data/processed/damage_records.csv` (script `scripts/export_damage.py`).
   - Also pull **high-gust days with no damage** from the archive as negatives, so the model learns that 45 mph alone usually isn't enough.

   **Repair dates:** `Repaired_D − Report_Tim` for Feb 2025 has median 1 day, P90 3 days, but 49 records exceed 30 days (e.g. 23 closed on 2025-12-29). Treat > 14 days as paperwork closure, not restoration; drop them from duration calibration. 31 post-Feb records are still `Repaired = No`.

   Snap each damage point to the nearest grid device (pole/span/fuse/recloser/transformer) and mark which premises sat downstream, so we know **who lost power**.
5. **Grid features per premise / per hex cell (H3 res 8):** OH vs UG share, number of upstream protective devices, distance to circuit breaker, pole density, pole age where available (`*_phase_da` install dates on transformers/switches), historical damage density (excluding the event being tested), terrain elevation/slope.
6. **Labor table** from `Install_Labor_HackOHIO.xlsx`:
   - damage type → install + removal hours (pole by size, transformer by kVA, recloser, crossarm, connectors…)
   - access adders (+0.5 h restricted/backyard, +1.312 h remote, +1.5 h/ft³ hand dig, +4 h/ft³ rock)
   - **ILM = 4.5** (drive, safety, setup)
   - Map ARCOS `Asset_Type` / `Special_Eq` / `Access_Iss` onto these.
7. **ZIP:** download Census TIGER/Line ZCTA polygons (Virginia). Point-in-polygon each premise → `zip`. Used for the AEP "% of ZIP out" view and for validating customer-entered ZIPs.

---

## 4. Risk model (P0)

**Goal:** P(premise / cell loses power during event) → band.

| Band | Probability |
|---|---|
| Low | 1–15% |
| Elevated | 15–35% |
| High | 35–60% |
| Severe | 60–100% |

**Inputs**
- Weather (Open-Meteo, hourly, per cell): peak wind gust, sustained wind, precipitation, snowfall, derived freezing rain (rain while temp ≤ 0 °C), temperature min/max, soil moisture (saturated soil → tree fall).
- SPC outlook category (convective events only).
- Grid features from §3.5.

**Model:** transparent logistic regression / gradient-boosted model with monotonic constraints, so every prediction comes with **top contributing factors** ("gusts 58 mph, mostly overhead lines, 4 upstream devices").

**Training and validation (Helene + Feb 2025)**
1. Pull Open-Meteo archive weather for both event windows over the service area.
2. Label = premise lost power (downstream of a damaged device) during the event; `background` periods = low-risk negatives.
3. **Train on Feb 2025, test on Helene** (then the reverse). Report reliability (predicted vs. actual rate per band) and AUC. Show this chart to judges.
4. Refit on both, **freeze the model**, and use it for all what-if scenarios.

**Confidence indicator:** High / Medium / Low, based on
- how close the scenario's weather is to the training data (out-of-distribution check);
- forecast lead time (live mode);
- data gaps (missing topology, unknown OH/UG).

**What the training events cover (from the Open-Meteo archive, Roanoke point):**
- **Helene 2024:** wind + heavy rain. ~3.7 in rain Sep 24–27 (saturated soil), peak gust ~48 mph on Sep 27. SPC logged 5 Virginia tornadoes on Sep 27 (Pittsylvania ×4, one 3 mi SW of Bedford), all **just outside** the service area (east edge ≈ −79.65°), so no tornado ground truth. No heat afterwards: highs 72–80 °F, then a dry spell (no rain Oct 5–20).
- **Feb 2025: ice first, then wind.** Feb 11–13: ~40 h of rain at 30–32 °F (≈1.5 in liquid, freezing rain) plus ~3 in snow; damage reports peak Feb 13–14 (892 records) as the ice ends and 33 mph gusts hit loaded trees and lines. Feb 16–17: gusts 55 and 40 mph on saturated soil; second, smaller wave of reports on Feb 17. Split this event into `feb_2025_ice` (Feb 12–15) and `feb_2025_wind` (Feb 16–18) features so the model learns both hazards.

Hazards still outside the training data get **physics-based rules on top, flagged as lower confidence**:
- **Ice / freeze (partly trained):** Feb 2025 ice calibrates the ice-accretion response; rules extend it past what was observed (radial ice ≥ ~0.25 in → scattered, ≥ ~0.5 in → widespread; verify sources). Extreme cold load / generation shortfall (Texas 2021) stays rule-based.
- **Heat:** transformer overload risk from temperature + kVA rating (from `Transformer_Clip`).
- **Tornado:** SPC probability × path-width damage footprint.

**Fallback:** if confidence is Low or data is missing, say so plainly: "We can't make a reliable prediction for your location right now. Here's what we know, and AEP crews are monitoring."

---

## 5. Restoration-time engine (P0)

1. **Damage set:** real (replay events) or simulated (model draws damage per asset from risk probabilities).
2. **Hours per job** = Σ(install + removal hours by asset) + access adders, **× ILM 4.5**.
   Steps 1–2 are driven by the **structure drawings → repair kits** below.
3. **Crews:** slider (default from a stated assumption; mutual-aid crews arrive on day 2+).
4. **Step restoration:** prioritise jobs by customers restored per crew-hour using the device tree. A broken recloser (thousands of premises) goes before a single service drop. Critical facilities and life-support customers get a priority boost.
5. **Work stoppages:** no bucket work while gusts exceed the safe-operating limit (**28–30 mph gusts, confirmed by the team**: caution from 28 mph, full stop at 30 mph); access issues and special equipment (`Backyard Bucket`, `Track Hoe`…) add delay.
6. **Monte Carlo (≈500 runs)** on job hours, travel, and crew arrival → **P10 / P50 / P90** per premise. Display: "Most likely 6–14 hours; could be up to 2 days".
7. **Delay explanations** are generated from whatever moved the range: wind hold, access, special equipment, upstream damage, crew count.

### Structure drawings → repair kits (`docs/structure_drawings.pdf`, 9 AEP standard drawings)

| Page | Structure | Key parts (AEP D.S. number) |
|---|---|---|
| 1 | Three-phase transformer bank (crossarm) | 3 transformers (1000-x), cutouts + fuse links (61-x, 1001-x), current-limiting fuses, arresters (62), cluster bracket (51/52), hot line taps (75-A), twisted secondary (502), grounding (65) |
| 2 | Single-phase transformer pole | transformer, cutout + fuse link, arrester + bracket, hot line tap, secondary risers, grounding |
| 3 | Single-phase deadend | primary deadend (31-x), guying (400), neutral deadend (501-B), connector (70-x) |
| 4 | Single-phase angle / tap deadend | deadends both ways, guy, grounding, connectors (70-x, 74) |
| 5 | Single-phase tangent ("Pin Top") | pin + insulator (30-x), wire ties (40-x), neutral (500) |
| 6 | Three-phase tap off crossarm | 2 crossarms, pin insulators, deadends, guy, grounding, connectors |
| 7 | Three-phase crossarm with pole-top pin, single-phase tap dead-ended below | crossarm, pin insulators + bracket (30-A, 32-D), tie wire (40-x), primary deadend, neutral assembly (501-x), 2 guys, connectors (70-x, 74) |
| 8 | Three-phase deadend, 35 kV | double crossarm (20-x), 3 deadends, guy, neutral deadend |
| 9 | Three-phase tangent, 35 kV fiberglass crossarm | crossarm (26-x), crossarm pins, pole-top pin, insulators, ties |

**Which drawing applies to a damaged pole (inferred from GIS):**
- phases + construction from `Primary_ExportFeatures` (`OH MV 1/3 Phase`, `Pin Top` vs `TC Typical CrossArm`, 12.47 vs 34.5 kV → 35 kV drawings)
- number of primary segments ending at the pole: 1 = deadend, 2 straight = tangent, 2 bent = angle, 3+ = tap/junction (the labor sheet's junction-pole adder)
- transformer at the location (`Transformer_Clip`) → page 1 or 2, with kVA from `*_phase_sp` ("25 kVA XFR PL")
- pole height → labor size group (25–35 ft small, 40–55 medium, 60+ large); material and install year (some date to the 1940s) also raise failure probability in the risk model.

**Shared poles:** pages 5 and 9 show telephone/cable lines attached below the power lines (D.S. 1821). `Pole_Clip` owners include Verizon and Roanoke & Botetourt Telephone. After a pole is replaced, the telephone and cable companies must move their own lines over, so add a "shared pole" delay to the job (it doesn't block restoring power, but it extends the job and clean-up).

**Damage → parts → hours:** each damage type picks the parts that fail, then sums install + removal hours from the workbook, adds access adders, × ILM 4.5.

| Damage (ARCOS) | Likely parts replaced | Workbook groups |
|---|---|---|
| Pole down / broken | whole structure kit for that drawing (pole, crossarm, insulators, deadends, guy + anchor, grounding, connectors; transformer equipment moved over or replaced) | POL, ARM, INS/PIN, DEC, GYF, ANC, GND, CNC (+ transformer by kVA) |
| Pole leaning | straighten, retension guy | Structural Realignment adder (0.544 h), GYF |
| Primary / secondary wire down | splice + reties, broken insulators/pins, sometimes crossarm | CNC, INS, PIN, ARM, DEC |
| Fuse bank "damaged switch" | refuse, or replace cutout | XCO (no hours in workbook → assumption) |
| Transformer | transformer by kVA, cutout, arrester, connections | transformer table, EQL, XCO, GND, CNC |
| Recloser | recloser + leads + bracket | REC, EQL, BKT |

**Worked example (from the workbook):** a broken 40 ft three-phase crossarm deadend pole (page 8 style) = pole 3.43 + crossarm 0.59 + 4 deadends 0.69 + guy 0.53 + anchor 0.52 + grounding 0.68 + 4 connectors 1.04 ≈ **7.5 h**, + backyard access 0.5 → 8.0 h, **× ILM 4.5 ≈ 36 h**. If those are person-hours, a 4-person crew needs ≈ 9 h on site (confirm with mentors).

**Hazard decides the failure mode** (probabilities come from the real damage mix per tagged event in `damage_records.csv`): ice → wire + crossarm + pole breaks (Feb 2025: 44% primary, 22% pole, 17% fuse); wind → wire down + leaning poles; tornado → poles snapped, whole kits; heat → transformer failures.

**In the app:** clicking a damaged device in the 3D replay or the AEP map opens its structure drawing with the failed parts highlighted, the parts list, and the hours breakdown. Customers get the plain-language version: "the pole carrying your line's transformer broke; crews are replacing the pole, crossarm and fuse equipment."

**Root cause explanation:** walk the premise's upstream chain to the first damaged device. "A fuse protecting your street was damaged. Once the main line repair upstream is done, your area is next." If no damaged device is identified: "We don't have a confirmed cause yet. The most likely cause is X. Crews are investigating."

**After restoration:** a short summary of what happened, why, what was fixed, and how long it took.

---

## 6. What-if scenarios ("What if it hit Virginia?")

| Scenario | Source | Type |
|---|---|---|
| Hurricane Helene 2024 | Real local event | Replay with real damage, validated |
| Feb 2025 storm | Real local event | Replay with real damage, validated |
| June 2012 derecho | Hit Roanoke in reality; weather archive only | What-if (no damage records) |
| Texas deep freeze, Feb 2021 | Transposed from Texas | What-if, ice/cold rules |
| Pacific NW heat dome, Jun 2021 | Transposed from Portland/Seattle | What-if, heat rules |
| April 2011 tornado outbreak | Transposed from Alabama | What-if, tornado footprint |

**Transposition method:** fetch Open-Meteo archive hourly data on a grid (~10×10 points) around the event's real center, compute each point's offset from center, re-center the grid on Roanoke, keep timing and intensity. Terrain effects aren't modelled; we state that as an assumption.

**3D replay (5–10 s):** MapLibre 3D terrain + deck.gl.
- wind particles animate from the hourly wind field
- hex columns rise with risk; colour by band
- device pins flip red as simulated damage hits, then green as crews restore
- timeline scrubber + play button; can also be screen-recorded for the video

**Results panel after the replay:** customers out (peak and over time), % out by ZIP/circuit, P10/P50/P90 restoration, crew-hours, business impact, messages that would have been sent.

**Sliders judges can move:** crews available, gust multiplier, access issues on/off, mutual-aid arrival day, alert threshold.

---

## 7. App structure

### Auth (P1)
- Login, Sign up, **Forgot password** (real reset token; "email" delivered to a dev mailbox page instead of a real inbox).
- **Roles:** `customer`, `aep_operator`. **Every AEP API route checks the role server-side.** Hiding tabs isn't enough; a customer calling `/api/aep/*` gets 403.
- Seeded mock accounts (credentials kept in `scripts/seed_accounts.py`, not in the README):
  - several customers (one overhead rural, one underground suburban, one life-support flagged)
  - two AEP operators

### Customer sign-up flow
1. Account details → 2. **Address + ZIP** (customer-entered) → 3. geocode → snap to nearest service point; reject if the ZIP doesn't match the geocoded point or the point is outside the service area → 4. optional declared needs (medical device, accessibility, critical facility). Never inferred. → 5. alert preferences (SMS / in-app).

### Customer tabs
**Map** (weather layers: temperature, feels like, gusts, wind speed, humidity; own risk) · **My Status** (risk → outage → restoration → summary) · **Prepare** (safety + tailored tips; emergencies labelled clearly) · **Alerts** (feed + preferences) · **Simulation** (customer version, no AEP-only numbers) · **My Data & Privacy** (see/export/delete own data, what's stored and why).

### AEP tabs (AEP login only)
**Ops Map** (risk heat map, device pins with customer counts, damage, % out by ZIP and circuit) · **Restoration Planner** (crews, damage, access → estimate and job order) · **Business Impact** · **Communications** (customer alert threshold, message queue, escalation triggers; AEP receives **all** alerts regardless of band) · **Simulation** (full version) · **Model & Audit** (validation chart, assumptions, access log).

### Map privacy rules
- Outage reports are pinned to the **protective device they're downstream of** (fuse/recloser/breaker), never to a home.
- Hide any aggregate covering fewer than 5 customers.
- Hospitals / fire / EMS shown only in the AEP view; customers see "critical facility nearby" wording, not locations.
- A logged-in customer sees only **their own** premise highlighted.

---

## 8. Alerts and communications

| Recipient | Rule |
|---|---|
| AEP operators | Every alert, every band |
| Customers | Only when risk ≥ AEP-set threshold (default: Elevated), and opted in |
| Life-support / declared medical | One band lower than the general threshold + escalation to AEP if outage > 2 h (assumption) |

**Messages (all four required):** pre-storm, outage confirmed, estimate updated (sent when P50 moves more than ±25% or 2 h), restoration complete (with summary). Channels: SMS + in-app.

**Escalation triggers to AEP:** life-support customer out, critical facility circuit out, estimate slipping repeatedly, low-confidence prediction in a Severe band area.

---

## 9. Business impact (publicly sourced, every number cites its source)

| Metric | Formula | Public source |
|---|---|---|
| Lost revenue | customers out × hours × avg load × rate | EIA (VA residential price, avg monthly use); Appalachian Power tariffs |
| Crew labour cost | crew-hours (from §5) × loaded wage | BLS OEWS, VA electrical power-line installers |
| Equipment cost | equipment-hours × hourly rate | FEMA Schedule of Equipment Rates (bucket truck, digger derrick…) |
| Parts / materials | damaged items × unit cost range | Published industry ranges (shown as a range) |
| Mutual-aid premium | extra crews × days × rate | Stated assumption |
| Customer / societal cost | outage duration × customer type | LBNL ICE Calculator |
| Sanity check | — | Appalachian Power storm-cost recovery filings with the VA SCC (Helene) |

**Numbers found so far (Oct 24, 2026):**
- **EIA 2024 (Form 861, table 5A), Virginia residential:** 1,032 kWh/month avg, 14.41 ¢/kWh, $148.77 avg bill. EIA Electric Power Monthly: VA residential 17.64 ¢/kWh in Aug 2026 (preliminary).
  → **lost revenue ≈ $0.20–0.25 per customer-hour out** (1,032 / 730 h = 1.41 kW avg load). Part of the bill is fixed charges and fuel pass-through, so the true margin lost is lower.
- **FEMA 2025 Schedule of Equipment Rates** (fema.gov blocks direct download; same schedule via adeca.alabama.gov): aerial lifts incl. truck, 80–120 ft, codes 8486–8489, **$62.86–78.43/h**; hydraulic digger derrick **$47.61/h**. The PDF's text columns are misaligned, so verify these rows by eye before the demo.
- **BLS OEWS 49-9051 (line installers):** national mean $41.30/h (May 2023). The Virginia May 2025 figure needs pulling by hand from bls.gov (blocks scripts). Storm work assumed at 1.5× overtime.
- **LBNL ICE Calculator:** interactive tool (icecalculator.com); pull residential / small C&I / large C&I cost-per-event values by hand.
- **Materials:** no public source yet. Look for published pole / transformer unit cost ranges.

**First estimate, Feb 2025 ice + wind (1,254 real damage jobs)**, using the repair-kit hours (§5), access adders, ILM 4.5, 4-person crews:
- ≈ 2,880 direct h + 200 h access adders → **≈ 13,900 person-hours ≈ 3,460 crew-hours**
- labor ≈ **$0.86M** (at $41.30 × 1.5) + equipment ≈ **$0.33M** → **≈ $1.2M before materials and mutual aid**
- lost revenue for comparison: 10,000 customers × 24 h ≈ $49k; 30,000 × 48 h ≈ $293k. The real customer-hours come from the topology trace in phase 1.
- Kit hours not in the workbook (fuse refuse 0.5 h, switch 1 h, capacitor 2 h) are assumptions.

Expected insight for judges: lost sales are small; **restoration and societal costs dominate**.

### Impact changes per scenario (recomputed on every simulation run)

The Feb 2025 balance is not a constant. Each run recomputes all three costs from that scenario's damage, duration and weather:

| Driver | Moves | How it's modelled |
|---|---|---|
| Damage count + mix (from hazard → repair kits, §5) | Repair cost | Σ kit hours × ILM × wage/equipment rates |
| Customer-hours out (topology trace × restoration timeline) | Lost revenue, customer cost | Revenue ∝ customer-hours; repair cost mostly isn't (a pole costs the same on day 1 or day 3) |
| **Temperature during the outage** | Revenue per customer-hour | Not a flat $0.20: scale average load by heating/cooling degree-hours from the scenario's Open-Meteo temperature (cold snap / heat wave hours worth more) |
| **Event size** | Repair cost (nonlinear) | When jobs exceed local crew capacity, add mutual-aid crews at a premium rate + lodging/travel per crew-day (stated assumption) |
| Outage danger (extreme heat/cold) | Customer cost | ICE cost per customer-hour, with a hazard multiplier and life-support flags in the explanation |

**Expected pattern (to be confirmed by the engine, not hard-coded):** tornado = most repair-heavy (narrow path, rebuilt poles); derecho = everything high (wide tree damage + heat); Texas freeze = revenue + customer cost approach or pass repair (long, cold, high-load outages); heat dome = little physical damage, but costly and dangerous outage hours, and total sales may even rise from demand. Headline for judges: **"the type of storm changes who pays."**

**UI:**
- One **stacked bar per scenario**: lost revenue / repair cost (labor, equipment, materials, mutual aid) / customer cost. Show all scenarios side by side in the Simulation results.
- **Crew-count trade-off curve:** x = crews available, y = cost. Repair cost rises with crews (overtime, mutual aid); customer-hours, lost revenue and customer cost fall. Total cost is U-shaped; mark the minimum. Moving the crew slider moves a dot along the curve.
- Every number has a hover showing its formula and source.

Operational conditions panel: crew-hours, work stopped by wind, overtime hours, access-limited jobs, special equipment needed.

---

## 10. Data security (customer address = safety risk)

- **Passwords:** bcrypt hashes only.
- **Address, ZIP, phone (confirmed), and declared needs:** encrypted at the field level in SQLite (Fernet/AES; key in an environment variable, never in the repo). Only the geocoded premise link is stored in plaintext.
- `.db` file and `.env` are **git-ignored**.
- Sessions: HTTP-only cookies / short-lived JWT; HTTPS when deployed.
- LLM gets **only** engine outputs and band-level facts. No names, addresses, phone numbers, or exact coordinates.
- Audit log of every AEP access to customer-level data.

---

## 11. Responsible AI (show this in the video)

- Every screen separates **Confirmed** (AEP data) / **Model estimate** / **What you should do**.
- Bands + confidence + top factors + assumptions + "what could change this".
- The LLM only phrases things. Every number comes from the engines; the prompt forbids inventing numbers and requires the low-confidence fallback text.
- Validation chart (train on one event, test on the other) is visible in Model & Audit.

---

## 12. Build order

| Phase | Work | Done when |
|---|---|---|
| 1 | Data prep (§3) | Tables + GeoJSON load; premise → upstream chain query works |
| 2 | Risk model + validation (§4) | Bands per premise for Helene and Feb 2025; validation chart |
| 3 | Restoration engine (§5) | P10/P50/P90 + job order + delay reasons for any damage set |
| 4 | Simulation tab + 3D replay (§6) | Pick event → 5–10 s animation → results; sliders work |
| 5 | Auth, roles, sign-up/geocode (§7) | Mock logins; AEP routes return 403 for customers |
| 6 | Customer + AEP tabs (§7–9) | All tabs show real engine output |
| 7 | LLM text + messages (§8, §11) | Four message types generated with guardrails |
| 8 | Polish, video, submit | Video uploaded before Sunday 10:00 AM |

**Parallel workstreams**
- **A. Data + models:** phases 1–3
- **B. Frontend map + 3D replay:** phase 4 (start on raw GeoJSON while A works)
- **C. Backend API + auth + DB:** phase 5
- **D. Business-impact sourcing + messages + video script:** §9, §8, then phase 8

---

## 13. Open questions (ask AEP mentors)

- ~~Safe wind limit for bucket work~~ → answered: 28–30 mph.
- Typical crew count for these circuits; when mutual aid arrives.
- Archive data says Feb 2025 was freezing rain (Feb 11–13) then high wind (Feb 16–17). Does that match what crews saw, and how much ice accumulated?
- Is a ~5-customer minimum for map aggregates acceptable to them?
- Are workbook hours **person-hours** or crew-hours, and is ILM 4.5 applied before dividing by crew size? Typical storm crew size?
- Cutouts / fuse links (XCO) have no hours in the workbook. What's a typical refuse vs. cutout replacement time?
- Do ARCOS "Damaged Wire" records usually mean a splice/retie, or a full span replacement?
