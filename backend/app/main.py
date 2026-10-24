"""AI Outage Concierge API.

Run (from repo root):  .venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
"""
import json
import time
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

from . import ai, db, geocode, guidance
from .config import DEV_MODE, SESSION_HOURS, TWILIO_FROM, TWILIO_SID, TWILIO_TOKEN
from .engines import risk, simulate, views
from .engines.data import PROCESSED, grid
from .engines.scenarios import SCENARIOS, catalogue, weather_for
from .security import (COOKIE, check_password, current_user, decrypt, encrypt, hash_password, hash_token,
                       make_session, new_reset_token, require_aep, require_customer)

app = FastAPI(title="AEP AI Outage Concierge")
ROOT = Path(__file__).resolve().parents[2]
DRAWINGS = PROCESSED / "drawings"


@app.on_event("startup")
def _startup():
    db.init()
    grid()
    simulate.asset_hours()


# ------------------------------------------------------------------ helpers
def params(scenario: str | None = None, crews: int = 45, mutual_aid_crews: int = 45, mutual_aid_day: float = 1.0,
           gust_mult: float = 1.0, access_mult: float = 1.0) -> simulate.Params:
    sid = scenario or db.get_setting("active_scenario")
    if sid not in SCENARIOS:
        raise HTTPException(404, "Unknown scenario")
    return simulate.Params(scenario=sid, crews=int(np.clip(crews, 1, 400)),
                           mutual_aid_crews=int(np.clip(mutual_aid_crews, 0, 400)),
                           mutual_aid_day=float(np.clip(mutual_aid_day, 0, 10)),
                           gust_mult=round(float(np.clip(gust_mult, 0.5, 1.6)), 2),
                           access_mult=round(float(np.clip(access_mult, 0, 3)), 2))


def sim(p: simulate.Params) -> dict:
    try:
        return simulate.run(p)
    except FileNotFoundError:
        raise HTTPException(503, "Weather data for this scenario is not available")


def _premise_idx(premise: str) -> int:
    idx = grid().prem_index.get(premise)
    if idx is None:
        raise HTTPException(404, "Premise not found")
    return idx


def _profile(user_id: int) -> dict:
    with db.tx() as con:
        row = con.execute("SELECT * FROM customer_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Profile missing")
    p = dict(row)
    p["needs"] = json.loads(decrypt(p["needs_enc"]) or "[]") if p["needs_enc"] else []
    return p


def _set_cookie(resp: Response, token: str):
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=SESSION_HOURS * 3600)


DEVICE_PLAIN = {
    "fuse": "the fuse that protects your street",
    "recloser": "a main-line protective device (recloser)",
    "breaker": "the substation breaker for your whole circuit",
    "transformer": "the transformer that serves your home and a few neighbors",
    "sectionalizer": "a line sectionalizer",
    "step": "a step-down transformer on your line",
}
DAMAGE_PLAIN = {"pole": "a broken utility pole", "primary": "a downed power line", "secondary": "a downed line near homes",
                "fuse": "a blown fuse", "transformer": "a damaged transformer", "recloser": "a damaged recloser",
                "switch": "a damaged switch"}
FIX_PLAIN = {"pole": "replaced the pole and re-hung the lines", "primary": "cleared trees and spliced the line",
             "secondary": "repaired the low-voltage line", "fuse": "replaced the fuse",
             "transformer": "replaced the transformer", "recloser": "replaced the recloser", "switch": "repaired the switch"}


def _cause_text(lc: dict | None) -> tuple[str | None, str | None]:
    if not lc:
        return None, None
    dmg = " and ".join(DAMAGE_PLAIN.get(t, t) for t in lc["damage_types"][:2]) or "storm damage"
    where = DEVICE_PLAIN.get(lc["device_kind"], "equipment on your line")
    n = lc["customers_behind"]
    cause = f"{dmg}, which took out {where} (about {n:,} customers share it)"
    fixed = "; ".join(FIX_PLAIN.get(t, "repaired the damage") for t in lc["damage_types"][:2]) or None
    return cause, fixed


def customer_view(res: dict, pidx: int, needs: list[str], prefs: dict | None = None) -> dict:
    st = views.premise_status(res, pidx)
    sc = res["scenario"]
    cause, fixed = _cause_text(st["likely_cause"])
    est = st["restoration"]
    hazard = sc.get("hazard", "wind")
    factors = [f["label"] for f in st["risk"]["factors"]]
    if st["premise"]["service"] == "Overhead":
        factors.append("Your home is served by an overhead line")
    if st["risk"]["exposure"]:
        e = st["risk"]["exposure"][0]
        factors.append(f"Your power passes through {DEVICE_PLAIN.get(e['kind'], e['kind'])} serving "
                       f"{e['customers']:,} customers")
    delay = None
    if est:
        delay = ("high winds keep bucket trucks grounded above 30 mph" if hazard in ("wind", "tropical", "tornado")
                 else "ice and downed trees make roads slow and work hazardous" if hazard == "ice"
                 else "crews are working through damage in order of customers restored")
    ctx = dict(scenario_name=sc["name"], band=st["risk"]["band"], p_out=st["risk"]["p_out"],
               confidence=st["confidence"]["level"], factors=factors[:5],
               estimate_label=est["label"] if est else None, cause_plain=cause, fixed_plain=fixed,
               delay_reason=delay, hazard=hazard, declared_needs=needs)
    comms = ai.communications(ctx)
    prefs = prefs or dict(alerts_sms=1, alerts_inapp=1, phone=None)
    elig = guidance.alert_eligibility(st["risk"]["band"], db.get_setting("customer_alert_threshold"), needs,
                                      db.get_setting("life_support_one_band_lower") == "1",
                                      bool(prefs["alerts_sms"]), bool(prefs["alerts_inapp"]), bool(prefs.get("phone")))
    prep = guidance.preparation(st["risk"]["band"], hazard if "rules" not in sc else sc["rules"][0],
                                est["p50"] if est else None, st["risk"]["weather"], needs, st["premise"]["service"])
    return dict(**st, factors_plain=factors[:5], cause_plain=cause, fixed_plain=fixed, delay_reason=delay,
                communications=comms, alerts=elig, preparation=prep)


# ------------------------------------------------------------------ auth
class Register(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=EMAIL, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    address: str = Field(min_length=5, max_length=200)
    zip: str = Field(pattern=r"^\d{5}$")
    phone: str | None = Field(default=None, max_length=20)
    needs: list[str] = []
    alerts_sms: bool = True
    alerts_inapp: bool = True


class Login(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=120)
    password: str


class Forgot(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=120)


class Reset(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


ALLOWED_NEEDS = {"medical_device", "life_support", "mobility", "hearing_vision", "critical_facility"}


@app.post("/api/auth/register")
def register(body: Register, resp: Response):
    needs = [n for n in body.needs if n in ALLOWED_NEEDS]
    loc = geocode.geocode(body.address, body.zip)
    if not loc["ok"]:
        raise HTTPException(422, loc["reason"])
    premise = grid().prem.premise.iloc[loc["premise_idx"]]
    with db.tx() as con:
        if con.execute("SELECT 1 FROM users WHERE email = ?", (body.email.lower(),)).fetchone():
            raise HTTPException(409, "An account with that email already exists")
        cur = con.execute("INSERT INTO users(email, name, pw_hash, role, created) VALUES (?,?,?,?,?)",
                          (body.email.lower(), body.name, hash_password(body.password), "customer", time.time()))
        uid = cur.lastrowid
        con.execute("INSERT INTO customer_profiles(user_id, premise, address_enc, zip_enc, phone_enc, needs_enc, "
                    "alerts_sms, alerts_inapp) VALUES (?,?,?,?,?,?,?,?)",
                    (uid, premise, encrypt(body.address), encrypt(body.zip), encrypt(body.phone),
                     encrypt(json.dumps(needs)), int(body.alerts_sms), int(body.alerts_inapp)))
    db.audit(uid, "register")
    _set_cookie(resp, make_session(uid, "customer"))
    return dict(ok=True, role="customer")


@app.post("/api/auth/login")
def login(body: Login, resp: Response):
    with db.tx() as con:
        row = con.execute("SELECT id, pw_hash, role FROM users WHERE email = ?", (body.email.lower(),)).fetchone()
    if row is None or not check_password(body.password, row["pw_hash"]):
        raise HTTPException(401, "Email or password is incorrect")
    db.audit(row["id"], "login")
    _set_cookie(resp, make_session(row["id"], row["role"]))
    return dict(ok=True, role=row["role"])


@app.post("/api/auth/logout")
def logout(resp: Response):
    resp.delete_cookie(COOKIE)
    return dict(ok=True)


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return user


@app.post("/api/auth/forgot")
def forgot(body: Forgot):
    with db.tx() as con:
        row = con.execute("SELECT id, name FROM users WHERE email = ?", (body.email.lower(),)).fetchone()
        if row:
            token, h = new_reset_token()
            con.execute("INSERT INTO reset_tokens(token_hash, user_id, expires) VALUES (?,?,?)",
                        (h, row["id"], time.time() + 3600))
            con.execute("INSERT INTO mailbox(to_email, subject, body, created) VALUES (?,?,?,?)",
                        (body.email.lower(), "Reset your AEP Outage Concierge password",
                         f"Hi {row['name']},\n\nUse this link within 1 hour to choose a new password:\n"
                         f"/reset?token={token}\n\nIf you didn't ask for this, ignore this email.", time.time()))
    # same answer whether or not the account exists (no account enumeration)
    return dict(ok=True, message="If that email has an account, we've sent a reset link.")


@app.post("/api/auth/reset")
def reset(body: Reset):
    h = hash_token(body.token)
    with db.tx() as con:
        row = con.execute("SELECT user_id, expires, used FROM reset_tokens WHERE token_hash = ?", (h,)).fetchone()
        if row is None or row["used"] or row["expires"] < time.time():
            raise HTTPException(400, "This reset link is invalid or has expired")
        con.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_password(body.password), row["user_id"]))
        con.execute("UPDATE reset_tokens SET used = 1 WHERE token_hash = ?", (h,))
    db.audit(row["user_id"], "password_reset")
    return dict(ok=True)


@app.get("/api/dev/mailbox")
def mailbox():
    if not DEV_MODE:
        raise HTTPException(404)
    with db.tx() as con:
        rows = con.execute("SELECT * FROM mailbox ORDER BY id DESC LIMIT 20").fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ shared (any signed-in user)
@app.get("/api/scenarios")
def scenarios(user=Depends(current_user)):
    return dict(active=db.get_setting("active_scenario"), scenarios=catalogue())


@app.get("/api/weather")
def weather(scenario: str = "live", user=Depends(current_user)):
    if scenario not in SCENARIOS:
        raise HTTPException(404)
    h = weather_for(scenario)
    step = 1 if h.hours <= 240 else 2
    return h.to_json(step)


@app.get("/api/sim/overview")
def sim_overview(p: simulate.Params = Depends(params), user=Depends(current_user)):
    return views.overview(sim(p), aep=user["role"] == "aep")


@app.get("/api/sim/cells")
def sim_cells(p: simulate.Params = Depends(params), user=Depends(current_user)):
    return views.cells(sim(p))


@app.get("/api/sim/frames")
def sim_frames(p: simulate.Params = Depends(params), user=Depends(current_user)):
    fr = views.frames(sim(p), step=1)
    if user["role"] != "aep":
        fr["damage"] = [dict(t=d["t"], done=d["done"], lon=round(d["lon"], 3), lat=round(d["lat"], 3), type=d["type"])
                        for d in fr["damage"]]  # ~100 m precision for customers (equipment, not homes)
    return fr


# ------------------------------------------------------------------ customer
@app.get("/api/me/status")
def my_status(p: simulate.Params = Depends(params), user=Depends(require_customer)):
    prof = _profile(user["id"])
    prefs = dict(alerts_sms=prof["alerts_sms"], alerts_inapp=prof["alerts_inapp"], phone=prof["phone_enc"])
    out = customer_view(sim(p), _premise_idx(prof["premise"]), prof["needs"], prefs)
    pidx = _premise_idx(prof["premise"])
    pr = grid().prem.iloc[pidx]
    out["home"] = dict(lon=round(float(pr.lon), 4), lat=round(float(pr.lat), 4))  # own premise only
    return out


@app.get("/api/me/profile")
def my_profile(user=Depends(require_customer)):
    p = _profile(user["id"])
    return dict(name=user["name"], email=user["email"], address=decrypt(p["address_enc"]), zip=decrypt(p["zip_enc"]),
                phone=decrypt(p["phone_enc"]), needs=p["needs"], alerts_sms=bool(p["alerts_sms"]),
                alerts_inapp=bool(p["alerts_inapp"]),
                stored=dict(encrypted=["address", "ZIP code", "phone", "declared needs"],
                            plain=["name", "email", "anonymized premise link", "alert preferences"],
                            never_shared_with_ai=["name", "email", "address", "phone", "exact location"]))


class Prefs(BaseModel):
    phone: str | None = None
    needs: list[str] | None = None
    alerts_sms: bool | None = None
    alerts_inapp: bool | None = None


@app.put("/api/me/profile")
def update_profile(body: Prefs, user=Depends(require_customer)):
    sets, vals = [], []
    if body.phone is not None:
        sets.append("phone_enc = ?"), vals.append(encrypt(body.phone or None))
    if body.needs is not None:
        sets.append("needs_enc = ?"), vals.append(encrypt(json.dumps([n for n in body.needs if n in ALLOWED_NEEDS])))
    if body.alerts_sms is not None:
        sets.append("alerts_sms = ?"), vals.append(int(body.alerts_sms))
    if body.alerts_inapp is not None:
        sets.append("alerts_inapp = ?"), vals.append(int(body.alerts_inapp))
    if sets:
        with db.tx() as con:
            con.execute(f"UPDATE customer_profiles SET {', '.join(sets)} WHERE user_id = ?", (*vals, user["id"]))
    return my_profile(user)


@app.get("/api/me/export")
def export_me(user=Depends(require_customer)):
    data = my_profile(user)
    with db.tx() as con:
        data["notifications"] = [dict(r) for r in con.execute(
            "SELECT scenario, kind, channel, title, body, created FROM notifications WHERE user_id = ?",
            (user["id"],)).fetchall()]
    return JSONResponse(data, headers={"Content-Disposition": "attachment; filename=my-aep-data.json"})


@app.delete("/api/me")
def delete_me(resp: Response, user=Depends(require_customer)):
    with db.tx() as con:
        con.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    db.audit(None, "account_deleted")
    resp.delete_cookie(COOKIE)
    return dict(ok=True)


@app.get("/api/me/alerts")
def my_alerts(user=Depends(require_customer)):
    with db.tx() as con:
        rows = con.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 50",
                           (user["id"],)).fetchall()
        con.execute("UPDATE notifications SET read = 1 WHERE user_id = ?", (user["id"],))
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ AEP (role enforced server-side)
@app.get("/api/aep/pins")
def aep_pins(p: simulate.Params = Depends(params), user=Depends(require_aep)):
    return views.device_pins(sim(p))


@app.get("/api/aep/areas")
def aep_areas(hour: float | None = None, p: simulate.Params = Depends(params), user=Depends(require_aep)):
    return views.area_outages(sim(p), hour)


@app.get("/api/aep/jobs")
def aep_jobs(p: simulate.Params = Depends(params), user=Depends(require_aep)):
    return views.jobs(sim(p))


@app.get("/api/aep/jobs/{job}")
def aep_job(job: int, p: simulate.Params = Depends(params), user=Depends(require_aep)):
    res = sim(p)
    if res["median"] is None or not 0 <= job < len(res["median"]["idx"]):
        raise HTTPException(404)
    return views.job_detail(res, job)


@app.get("/api/aep/drawing/{page}")
def aep_drawing(page: int, user=Depends(require_aep)):
    f = DRAWINGS / f"page{page}.png"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/api/aep/facilities")
def aep_facilities(user=Depends(require_aep)):
    return views.facilities()


@app.get("/api/aep/customers")
def aep_customers(user=Depends(require_aep)):
    """Registered demo customers (decrypted for operators only; every call is audited)."""
    db.audit(user["id"], "view_customer_list")
    with db.tx() as con:
        rows = con.execute("SELECT u.id, u.name, u.email, c.premise, c.zip_enc, c.needs_enc FROM users u "
                           "JOIN customer_profiles c ON c.user_id = u.id").fetchall()
    return [dict(id=r["id"], name=r["name"], email=r["email"], zip=decrypt(r["zip_enc"]),
                 needs=json.loads(decrypt(r["needs_enc"]) or "[]")) for r in rows]


@app.get("/api/aep/impact")
def aep_impact(p: simulate.Params = Depends(params), user=Depends(require_aep)):
    return views.overview(sim(p), aep=True)["cost"]


@app.get("/api/aep/compare")
def aep_compare(user=Depends(require_aep)):
    """Stacked cost bars for every non-live scenario at default settings."""
    out = []
    for sid, sc in SCENARIOS.items():
        if sid == "live":
            continue
        res = sim(simulate.Params(scenario=sid))
        c = res["cost"]
        if c is None:
            out.append(dict(id=sid, name=sc["name"], lost_revenue=0, repair=0, customer_cost=0, customers_out=0))
            continue
        out.append(dict(id=sid, name=sc["name"], kind=sc["kind"], lost_revenue=c["lost_revenue"],
                        repair=c["repair"]["total_mid"], customer_cost=c["customer_cost"],
                        customers_out=res["summary"]["customers_out"]["p50"],
                        confidence=res["confidence"]["level"]))
    return out


@app.get("/api/aep/crew-curve")
def aep_crew_curve(scenario: str | None = None, user=Depends(require_aep)):
    """Total cost vs crews: repair rises with crews, customer cost + lost revenue fall."""
    sid = scenario or db.get_setting("active_scenario")
    rows = []
    for crews in (10, 20, 30, 45, 60, 90, 120, 160):
        res = sim(simulate.Params(scenario=sid, crews=crews, mutual_aid_crews=crews, runs=12))
        c = res["cost"]
        if c is None:
            continue
        repair = c["repair"]["labor_local"] + c["repair"]["labor_mutual_aid"] + c["repair"]["lodging"] + \
            c["repair"]["equipment"]
        # standby cost: crews are paid for their shifts even when idle (assumption: 16 h/day while restoring)
        days = max(res["summary"]["hours_to_all"]["p50"] / 24, 0.5)
        standby = 2 * crews * 4 * 16 * days * 41.30 * 1.5
        repair = max(repair, standby)
        rows.append(dict(crews=crews * 2, repair=round(repair), lost_revenue=c["lost_revenue"],
                         customer_cost=c["customer_cost"], total=round(repair + c["lost_revenue"] + c["customer_cost"]),
                         hours_to_90=res["summary"]["hours_to_90pct"]["p50"]))
    return dict(scenario=sid, rows=rows)


class SettingsBody(BaseModel):
    customer_alert_threshold: str | None = None
    active_scenario: str | None = None
    life_support_one_band_lower: bool | None = None


@app.get("/api/aep/settings")
def aep_settings(user=Depends(require_aep)):
    return {k: db.get_setting(k) for k in db.DEFAULT_SETTINGS}


@app.put("/api/aep/settings")
def aep_set(body: SettingsBody, user=Depends(require_aep)):
    if body.customer_alert_threshold:
        if body.customer_alert_threshold not in risk.BAND_ORDER:
            raise HTTPException(422, "Unknown band")
        db.set_setting("customer_alert_threshold", body.customer_alert_threshold)
    if body.active_scenario:
        if body.active_scenario not in SCENARIOS:
            raise HTTPException(422, "Unknown scenario")
        db.set_setting("active_scenario", body.active_scenario)
    if body.life_support_one_band_lower is not None:
        db.set_setting("life_support_one_band_lower", "1" if body.life_support_one_band_lower else "0")
    db.audit(user["id"], "settings_changed", body.model_dump(exclude_none=True))
    return aep_settings(user)


def _send_sms(phone: str, text: str) -> str:
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        return "SMS (simulated)"
    import httpx
    try:
        r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
                       auth=(TWILIO_SID, TWILIO_TOKEN), data=dict(From=TWILIO_FROM, To=phone, Body=text[:320]),
                       timeout=20)
        return "SMS" if r.status_code < 300 else "SMS (failed)"
    except Exception:
        return "SMS (failed)"


@app.post("/api/aep/alerts/send")
def aep_send_alerts(p: simulate.Params = Depends(params), user=Depends(require_aep)):
    """Evaluate every registered customer for the scenario and queue their messages."""
    res = sim(p)
    sid = p.scenario
    now = time.time()
    sent, ops = 0, []
    with db.tx() as con:
        con.execute("DELETE FROM notifications WHERE scenario = ?", (sid,))
        custs = con.execute("SELECT u.id, c.* FROM users u JOIN customer_profiles c ON c.user_id = u.id").fetchall()
    for c in custs:
        needs = json.loads(decrypt(c["needs_enc"]) or "[]") if c["needs_enc"] else []
        phone = decrypt(c["phone_enc"])
        prefs = dict(alerts_sms=c["alerts_sms"], alerts_inapp=c["alerts_inapp"], phone=phone)
        v = customer_view(res, _premise_idx(c["premise"]), needs, prefs)
        band = v["risk"]["band"]
        msgs = v["communications"]["messages"]
        kinds = ["pre_storm"] + (["outage_confirmed", "estimate_updated", "restored"] if v["restoration"] else [])
        rows = []
        for k in kinds:
            title = dict(pre_storm="Storm alert", outage_confirmed="Outage confirmed",
                         estimate_updated="Estimate updated", restored="Power restored")[k]
            if v["alerts"]["eligible"] or k != "pre_storm":
                for ch in v["alerts"]["channels"] or ["in-app"]:
                    channel = _send_sms(phone, msgs[k]) if ch == "SMS" else "in-app"
                    rows.append((c["user_id"], sid, k, band, channel, title, msgs[k], now, 0))
        esc = []
        if v["restoration"] and ("medical_device" in needs or "life_support" in needs):
            esc.append(f"Customer with declared medical need expected out {v['restoration']['label']}")
        if v["confidence"]["level"] == "Low" and band == "Severe":
            esc.append("Low-confidence prediction in a Severe area - verify with field reports")
        with db.tx() as con:
            con.executemany("INSERT INTO notifications(user_id, scenario, kind, band, channel, title, body, created, "
                            "escalation) VALUES (?,?,?,?,?,?,?,?,?)", rows)
            for e in esc:
                con.execute("INSERT INTO notifications(user_id, scenario, kind, band, channel, title, body, created, "
                            "escalation) VALUES (NULL,?,?,?,?,?,?,?,1)",
                            (sid, "escalation", band, "ops", "Escalation", e, now))
        sent += len(rows)
        ops += esc
    # operations feed: AEP gets every band
    s = res["summary"]
    with db.tx() as con:
        con.execute("INSERT INTO notifications(user_id, scenario, kind, band, channel, title, body, created) "
                    "VALUES (NULL,?,?,?,?,?,?,?)",
                    (sid, "ops_summary", None, "ops", f"{SCENARIOS[sid]['name']}: impact estimate",
                     f"Expected customers out {s['expected_customers_out']:,} of {s['total_customers']:,}; "
                     f"90% restored by hour {s['hours_to_90pct']['p50']:.0f} (P90 {s['hours_to_90pct']['p90']:.0f}). "
                     f"Confidence {res['confidence']['level']}.", now))
    db.audit(user["id"], "alerts_sent", dict(scenario=sid, messages=sent, escalations=len(ops)))
    return dict(messages=sent, customers=len(custs), escalations=ops)


@app.get("/api/aep/notifications")
def aep_notifications(user=Depends(require_aep)):
    with db.tx() as con:
        rows = con.execute("SELECT n.*, u.name AS customer FROM notifications n LEFT JOIN users u ON u.id = n.user_id "
                           "ORDER BY n.id DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/aep/model")
def aep_model(user=Depends(require_aep)):
    m = risk.model().meta
    return dict(features=[dict(name=n, label=l, coef=c) for n, l, c in zip(m["features"], m["labels"], m["coef"])],
                intercept=m["intercept"], validation=m["validation"], train_range=m["train_range"],
                trained_on=m["trained_on"], damage_records=m["damage_records"], excluded_days=m["excluded_days"],
                wind_calibration=m.get("wind_calibration"), mixes=m["mixes"],
                assumptions=[
                    "Damage records come from AEP's ARCOS extract; severe-weather days with no records are treated as "
                    "unlabeled because the extract appears to cover selected events only.",
                    "Wind-driven days are scaled by an in-sample calibration factor so real wind events match.",
                    "Weather is ERA5-based reanalysis on a ~10 km grid; it smooths thunderstorm gusts.",
                    "Outages are traced through AEP's premise-to-device topology; damage isolates the nearest "
                    "protective device (lateral fuse, or recloser/breaker on backbone lines).",
                    "Repair hours come from AEP's labor workbook x ILM 4.5; crews of 4; 16-hour shifts; bucket work "
                    "stops at 30 mph gusts and slows from 28 mph.",
                    "Crew defaults (45 local + 45 mutual aid from day 1) reproduce the real Feb 2025 repair times.",
                ])


@app.get("/api/aep/audit")
def aep_audit(user=Depends(require_aep)):
    with db.tx() as con:
        rows = con.execute("SELECT a.*, u.email FROM audit a LEFT JOIN users u ON u.id = a.user_id "
                           "ORDER BY a.id DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ frontend (production build)
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
