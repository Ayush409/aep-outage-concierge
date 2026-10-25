"""AI Outage Concierge API.

Run (from repo root):  .venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
"""
import json
import secrets
import time
from datetime import datetime, timedelta
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
from .engines.scenarios import SCENARIOS, catalogue, default_crews, display_weather
from .security import (COOKIE, check_password, current_user, decrypt, encrypt, hash_password, hash_token,
                       make_session, new_reset_token, require_aep, require_customer)

app = FastAPI(title="AEP AI Outage Concierge")
ROOT = Path(__file__).resolve().parents[2]
DRAWINGS = PROCESSED / "drawings"


@app.on_event("startup")
def _startup():
    db.init()
    # customers always see the live forecast; storm scenarios are only picked in the Simulation tab
    db.set_setting("active_scenario", "live")
    grid()
    simulate.asset_hours()


# ------------------------------------------------------------------ helpers
def params(scenario: str | None = None, crews: int | None = None, mutual_aid_crews: int | None = None,
           mutual_aid_day: float = 1.0, gust_mult: float = 1.0, access_mult: float = 1.0,
           snow_mult: float = 1.0) -> simulate.Params:
    sid = scenario or db.get_setting("active_scenario")
    if sid not in SCENARIOS:
        raise HTTPException(404, "Unknown scenario")
    inputs = SCENARIOS[sid].get("weather_inputs", [])  # snowfall only where the storm offers it
    snow_mult = round(float(np.clip(snow_mult, 0.5, 2.0)), 2) if "snow" in inputs else 1.0
    d = default_crews(sid)
    crews = d["crews"] if crews is None else crews
    mutual_aid_crews = d["mutual_aid_crews"] if mutual_aid_crews is None else mutual_aid_crews
    return simulate.Params(scenario=sid, crews=int(np.clip(crews, 1, 400)),
                           mutual_aid_crews=int(np.clip(mutual_aid_crews, 0, 400)),
                           mutual_aid_day=float(np.clip(mutual_aid_day, 0, 10)),
                           gust_mult=round(float(np.clip(gust_mult, 0.5, 1.6)), 2),
                           access_mult=round(float(np.clip(access_mult, 0, 3)), 2),
                           snow_mult=snow_mult)


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
    ev = st["event"]
    ctx = dict(scenario_name=sc["name"], band=st["risk"]["band"], is_simulation=sc["kind"] != "live",
               area=ev["area"], area_lost_share=ev["area_share"], home_lost_share=ev["home_share"],
               confidence=st["confidence"]["level"],
               confidence_reason=" ".join(st["confidence"]["notes"]) or "Within the range of storms the model was trained on.",
               factors=factors[:5],
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
    return dict(active=db.get_setting("active_scenario"), scenarios=catalogue(),
                band_outcomes={b: dict(share=o["share"], storms=len(o["storms"]))
                               for b, o in risk.band_outcomes().items()})


@app.get("/api/weather")
def weather(scenario: str = "live", user=Depends(current_user)):
    if scenario not in SCENARIOS:
        raise HTTPException(404)
    return display_weather(scenario)


@app.get("/api/sim/overview")
def sim_overview(p: simulate.Params = Depends(params), user=Depends(current_user)):
    return views.overview(sim(p), aep=user["role"] == "aep")


@app.get("/api/sim/cells")
def sim_cells(p: simulate.Params = Depends(params), user=Depends(current_user)):
    return views.cells(sim(p))


@app.get("/api/sim/areas")
def sim_areas(hour: float | None = None, p: simulate.Params = Depends(params), user=Depends(current_user)):
    """% without power by ZIP for any signed-in user (circuits are internal: AEP route only)."""
    a = views.area_outages(sim(p), hour)
    return dict(hour=a["hour"], zip=a["zip"])


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
    prefs = dict(alerts_sms=prof["alerts_sms"], alerts_inapp=prof["alerts_inapp"],
                 phone=prof["phone_enc"] if prof["phone_verified"] else None)
    out = customer_view(sim(p), _premise_idx(prof["premise"]), prof["needs"], prefs)
    pidx = _premise_idx(prof["premise"])
    pr = grid().prem.iloc[pidx]
    out["home"] = dict(lon=round(float(pr.lon), 4), lat=round(float(pr.lat), 4))  # own premise only
    out["address"] = decrypt(prof["address_enc"])  # the customer's own address, shown only to them
    return out


class ChatBody(BaseModel):
    messages: list[dict] = Field(max_length=40)
    scenario: str | None = None


def _when(start: str, hours: float | None) -> str | None:
    if hours is None:
        return None
    t = datetime.fromisoformat(start) + timedelta(hours=float(hours))
    return t.strftime("%a %b %d, %I %p").replace(" 0", " ")


@app.post("/api/me/chat")
def my_chat(body: ChatBody, user=Depends(require_customer)):
    """Ask the Concierge: Claude answers from this customer's own model results (no name, address or phone)."""
    p = params(scenario=body.scenario)
    prof = _profile(user["id"])
    res = sim(p)
    v = customer_view(res, _premise_idx(prof["premise"]), prof["needs"],
                      dict(alerts_sms=prof["alerts_sms"], alerts_inapp=prof["alerts_inapp"],
                           phone=prof["phone_enc"] if prof["phone_verified"] else None))
    ev, est, start = v["event"], v["restoration"], v["start"]
    t = ev["timeline"]
    facts = dict(
        scenario=v["scenario"]["name"], is_simulation=v["scenario"]["kind"] != "live",
        now=datetime.now().strftime("%a %b %d, %I %p").replace(" 0", " ") if v["scenario"]["kind"] == "live" else None,
        band=v["risk"]["band"], area=ev["area"], area_lost_share=ev["area_share"], home_lost_share=ev["home_share"],
        simulated_runs=ev["runs"], confidence=v["confidence"]["level"], confidence_notes=v["confidence"]["notes"],
        factors=v["factors_plain"], service=v["premise"]["service"], peak_weather=v["risk"]["weather"],
        restoration=dict(label=est["label"], typical_hours=est["p50"], short_hours=est["p10"], long_hours=est["p90"])
        if est else None,
        typical_run_timeline={k: _when(start, t[k]) for k in ("storm_hits", "power_lost", "confirmed",
                                                               "estimate_updated", "restored")} | {"hours_out": t["hours_out"]}
        if t else None,
        likely_cause=v["cause_plain"], what_crews_fix=v["fixed_plain"], delay_reason=v["delay_reason"],
        preparation={k: v["preparation"][k] for k in ("emergency", "now", "if_out", "your_needs")},
        alerts=dict(eligible=v["alerts"]["eligible"], reason=v["alerts"]["reason"], channels=v["alerts"]["channels"],
                    timing=v["alerts"]["timing"]),
        declared_needs=prof["needs"],
    )
    out = ai.chat(facts, body.messages)
    db.audit(user["id"], "chat", dict(scenario=p.scenario, source=out["source"]))  # no message content stored
    return out


@app.get("/api/me/prepare")
def my_prepare(p: simulate.Params = Depends(params), user=Depends(require_customer)):
    """Preparation guidance scaled to this home's risk band (Claude picks and words from approved tips)."""
    prof = _profile(user["id"])
    res = sim(p)
    st = views.premise_status(res, _premise_idx(prof["premise"]))
    sc = res["scenario"]
    hazard = sc["rules"][0] if sc.get("rules") else sc.get("hazard", "wind")
    est = st["restoration"]
    band = st["risk"]["band"]
    tips = guidance.preparation(band, hazard, est["p50"] if est else None, st["risk"]["weather"], prof["needs"],
                                st["premise"]["service"])
    plan = ai.preparation_plan(dict(scenario_name=sc["name"], band=band, hazard=hazard,
                                    estimate_label=est["label"] if est else None,
                                    weather=st["risk"]["weather"], declared_needs=prof["needs"],
                                    tips={k: tips[k] for k in ("now", "if_out", "your_needs")}))
    return dict(band=band, scenario=sc["name"], emergency=tips["emergency"], plan=plan,
                estimate=est["label"] if est else None)


@app.get("/api/me/profile")
def my_profile(user=Depends(require_customer)):
    p = _profile(user["id"])
    return dict(name=user["name"], email=user["email"], address=decrypt(p["address_enc"]), zip=decrypt(p["zip_enc"]),
                phone=decrypt(p["phone_enc"]), phone_verified=bool(p["phone_verified"]), needs=p["needs"],
                alerts_sms=bool(p["alerts_sms"]), alerts_inapp=bool(p["alerts_inapp"]),
                sms_live=bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM),
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
        phone = normalize_phone(body.phone) if body.phone else None
        if body.phone and not phone:
            raise HTTPException(422, "Enter a US mobile number, e.g. 540-555-0100")
        sets.append("phone_enc = ?"), vals.append(encrypt(phone))
        sets.append("phone_verified = ?"), vals.append(0)  # a new number must be verified again
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


def normalize_phone(raw: str) -> str | None:
    """US numbers to E.164 (+1XXXXXXXXXX); other countries if given with a leading +."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.strip().startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) == 11 and digits[0] == "1" and digits[1] not in "01":
        return "+" + digits
    return None


class PhoneCode(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


@app.post("/api/me/phone/send-code")
def phone_send_code(user=Depends(require_customer)):
    """Text a 6-digit code to the saved number. Twilio if configured, otherwise simulated (dev mailbox)."""
    p = _profile(user["id"])
    phone = decrypt(p["phone_enc"])
    if not phone:
        raise HTTPException(422, "Save a mobile number first")
    code = f"{secrets.randbelow(10 ** 6):06d}"
    with db.tx() as con:
        con.execute("INSERT INTO phone_codes(user_id, code_hash, expires, attempts) VALUES (?,?,?,0) "
                    "ON CONFLICT(user_id) DO UPDATE SET code_hash = excluded.code_hash, expires = excluded.expires, "
                    "attempts = 0", (user["id"], hash_token(code), time.time() + 600))
    text = f"AEP Outage Concierge: your verification code is {code}. It expires in 10 minutes."
    channel = _send_sms(phone, text)
    if channel != "SMS":  # simulated or failed: show it in the dev mailbox so the flow can still be tested
        with db.tx() as con:
            con.execute("INSERT INTO mailbox(to_email, subject, body, created) VALUES (?,?,?,?)",
                        (f"SMS to {phone}", "Phone verification code", text, time.time()))
    db.audit(user["id"], "phone_code_sent", dict(channel=channel))
    return dict(channel=channel, simulated=channel != "SMS")


@app.post("/api/me/phone/verify")
def phone_verify(body: PhoneCode, user=Depends(require_customer)):
    with db.tx() as con:
        row = con.execute("SELECT * FROM phone_codes WHERE user_id = ?", (user["id"],)).fetchone()
        if row is None or row["expires"] < time.time():
            raise HTTPException(400, "The code has expired. Send a new one.")
        if row["attempts"] >= 5:
            raise HTTPException(429, "Too many tries. Send a new code.")
        if hash_token(body.code) != row["code_hash"]:
            con.execute("UPDATE phone_codes SET attempts = attempts + 1 WHERE user_id = ?", (user["id"],))
            raise HTTPException(400, "That code doesn't match.")
        con.execute("UPDATE customer_profiles SET phone_verified = 1 WHERE user_id = ?", (user["id"],))
        con.execute("DELETE FROM phone_codes WHERE user_id = ?", (user["id"],))
    db.audit(user["id"], "phone_verified")
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


@app.post("/api/aep/chat")
def aep_chat(body: ChatBody, user=Depends(require_aep)):
    """Operations Copilot: Claude answers from the operator's model results (areas, circuits and counts - no names)."""
    p = params(scenario=body.scenario)
    res = sim(p)
    o = views.overview(res, aep=True)
    sc = SCENARIOS[p.scenario]
    start, curve = o["start"], o["curve"]
    peak = max(range(len(curve["p50"])), key=lambda i: curve["p50"][i]) if curve["p50"] else None
    areas = views.area_outages(res)
    jl = views.jobs(res)
    by_type: dict[str, int] = {}
    for j in jl:
        by_type[j["type"]] = by_type.get(j["type"], 0) + 1
    biggest = sorted(jl, key=lambda j: -j["customers_behind"])[:8]
    prem = grid().prem
    plon, plat = prem.lon.to_numpy(), prem.lat.to_numpy()

    def _where(j):  # circuit / ZIP of the nearest premise (assets carry no circuit id)
        k = int(np.argmin((plon - j["lon"]) ** 2 + (plat - j["lat"]) ** 2))
        return dict(circuit=str(prem.circuit.iloc[k]), zip=str(prem.zip.iloc[k]))

    what_if = []
    for f in (0.5, 1, 2):  # quick 12-run crew what-ifs (same storm)
        lc, ma = max(1, round(p.crews * f)), round(p.mutual_aid_crews * f)
        s_ = sim(simulate.Params(scenario=p.scenario, crews=lc, mutual_aid_crews=ma,
                                 mutual_aid_day=p.mutual_aid_day, gust_mult=p.gust_mult, access_mult=p.access_mult,
                                 snow_mult=p.snow_mult, runs=12))["summary"]
        what_if.append(dict(local_crews=lc, mutual_aid_crews=ma, hours_to_90pct=s_["hours_to_90pct"],
                            hours_to_all=s_["hours_to_all"], crew_wait_hours=s_["crew_wait_hours"]))
    with db.tx() as con:
        esc = [r["body"] for r in con.execute("SELECT body FROM notifications WHERE scenario = ? AND escalation = 1 "
                                              "ORDER BY id DESC LIMIT 10", (p.scenario,)).fetchall()]
    c = o["cost"]
    facts = dict(
        scenario=sc["name"], is_simulation=sc["kind"] != "live", window_start=_when(start, 0),
        now=datetime.now().strftime("%a %b %d, %I %p").replace(" 0", " ") if sc["kind"] == "live" else None,
        learned_from=sc.get("learned_from"), scenario_notes=sc.get("notes"),
        crews=dict(local=p.crews, mutual_aid=p.mutual_aid_crews, mutual_aid_arrives_day=p.mutual_aid_day,
                   note="Scenario default crews. Operators can try other numbers with the Simulation tab sliders."),
        crew_what_if=what_if,
        operations=o["operations"], confidence=o["confidence"], summary=o["summary"],
        peak=dict(hour=curve["hours"][peak], at=_when(start, curve["hours"][peak]),
                  customers_out_p10=curve["p10"][peak], customers_out_p50=curve["p50"][peak],
                  customers_out_p90=curve["p90"][peak]) if peak is not None else None,
        worst_zips_at_peak=areas["zip"][:8], worst_circuits_at_peak=areas["circuit"][:8],
        jobs_typical_run=dict(count=len(jl), by_type=by_type, access_issues=sum(j["access_issue"] for j in jl),
                              special_equipment=sum(j["special_equipment"] for j in jl),
                              life_support_customers_behind=sum(j["life_support_behind"] for j in jl),
                              biggest=[dict(type=j["type"], **_where(j), customers_behind=j["customers_behind"],
                                            life_support_behind=j["life_support_behind"],
                                            repair_starts_at=_when(start, j["start"]),
                                            repair_done_at=_when(start, j["finish"]),
                                            access_issue=j["access_issue"]) for j in biggest]),
        cost=dict(lost_revenue=c["lost_revenue"], repair=c["repair"], customer_cost=c["customer_cost"],
                  customer_hours=c["customer_hours"], kwh_not_served=c["kwh_not_served"],
                  formulas=c["formulas"]) if c else None,
        settings={k: db.get_setting(k) for k in db.DEFAULT_SETTINGS},
        recent_escalations=esc,
    )
    facts["worst_zips"] = facts.pop("worst_zips_at_peak")
    facts["worst_circuits"] = facts.pop("worst_circuits_at_peak")
    out = ai.chat(facts, body.messages, ops=True)
    db.audit(user["id"], "ops_chat", dict(scenario=p.scenario, source=out["source"]))  # no message content stored
    return out


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
        res = sim(simulate.Params(scenario=sid, **default_crews(sid)))
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
        phone = decrypt(c["phone_enc"]) if c["phone_verified"] else None  # texts only to verified numbers
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
                trained_on=m["trained_on"], damage_records=m["damage_records"],
                training_storms=m.get("training_storms", []), hazard_behaviour=m.get("hazard_behaviour", {}),
                excluded_records=m.get("excluded_records", {}), mixes=m["mixes"],
                scenarios=[dict(name=s["name"], learned_from=s.get("learned_from")) for s in SCENARIOS.values()
                           if s.get("learned_from")],
                assumptions=[
                    "Trained only on the two well-recorded local storms - Feb 2025 (freezing rain, then wind) and "
                    "Hurricane Helene (rain + wind) - with about a month of surrounding days so the model also sees "
                    "calm weather. January damage records are excluded.",
                    "Each storm type in the simulation borrows what the damage reports showed for the closest training "
                    "hazard: which equipment breaks, how often crews hit access problems, and special equipment needs.",
                    "With only one storm of each kind, the model cannot fully separate ice from heavy rain; hold-out "
                    "tests that hide one storm show this, so treat other storm types as indicative.",
                    "Weather is ERA5-based reanalysis on a ~10 km grid; it smooths thunderstorm gusts. Each ~2 km "
                    "area's temperature is corrected for its elevation (6.5 C per km) when deciding where rain "
                    "freezes, since ridges ice up while the valley stays above freezing.",
                    "Outages are traced through AEP's premise-to-device topology; damage isolates the nearest "
                    "protective device (lateral fuse, or recloser/breaker on backbone lines).",
                    "Within an area, damage is placed where real ARCOS damage lands (far less on substation backbone "
                    "and secondary poles) and arrives in clusters of "
                    f"{m.get('outage', {}).get('cluster_size', 1.0):.2f} reports per device, fitted so real storms' "
                    "damage reproduces the customers who lost power.",
                    "Repair hours come from AEP's labor workbook x ILM 4.5; crews of 4; 16-hour shifts; bucket work "
                    "stops at 30 mph gusts and slows from 28 mph.",
                    "Crew defaults (20 local + 40 mutual aid from day 1) best match the real Feb 2025 repair dates "
                    "(the only storm with usable repair dates).",
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
