"""Claude writes the plain-language explanation and the four customer messages.

Guardrails:
- Claude only receives engine outputs (numbers, bands, factor labels). No names, addresses,
  phone numbers or exact coordinates are ever sent.
- The prompt forbids inventing numbers; output is schema-constrained JSON.
- Any failure (no credentials, refusal, network) falls back to the deterministic templates.
"""
import hashlib
import json
import threading
import logging
from functools import lru_cache
from pathlib import Path

import anthropic

from .config import AI_ENABLED, ANTHROPIC_MODEL
from .experience import LIMITATION
from .guidance import template_messages

log = logging.getLogger("ai")

SYSTEM = """You write outage communications for AEP customers during storms.
Rules:
- Risk bands are experimental planning indicators, not validated probabilities. Never infer that an outage is likely or certain from a band alone.
- Use ONLY the facts in the JSON you are given. Never invent numbers, times, places, or causes.
- Plain language a 12-year-old understands. Short sentences. No jargon (say "the fuse that protects your street", not "lateral fuse").
- Always keep model estimates clearly labelled as estimates, separate from confirmed facts.
- area_lost_share is the share of homes in the customer's area (e.g. a ZIP code) that lose power in this event;
  home_lost_share is how often this home lost power across the simulated runs. Describe them exactly that way.
- If is_simulation is true, this is a simulated storm, not a real forecast: say "in this simulated <storm>".
- If confidence is Low or the cause is unknown, say so honestly and say AEP crews are still working on it. When you
  explain why confidence is lower, use only confidence_reason - never invent a reason.
- The explanation is read BEFORE the storm: describe the risk and what would happen IF the power goes out. Never say
  the power is out in the explanation or the pre_storm message.
- Only the outage_confirmed, estimate_updated and restored messages may describe an outage as happening.
- SMS-style messages must be under 300 characters.
- Mention medical equipment only if declared_needs includes "medical_device" or "life_support", and then only
  "contact your provider or go to a hospital if your equipment needs power"."""

SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "pre_storm": {"type": "string"},
        "outage_confirmed": {"type": "string"},
        "estimate_updated": {"type": "string"},
        "restored": {"type": "string"},
    },
    "required": ["explanation", "pre_storm", "outage_confirmed", "estimate_updated", "restored"],
    "additionalProperties": False,
}


@lru_cache(maxsize=1)
def _client():
    if not AI_ENABLED:
        raise RuntimeError("AI disabled; use local templates")
    return anthropic.Anthropic(max_retries=1, timeout=60.0)


def _fallback_explanation(ctx: dict) -> str:
    f = ", ".join(ctx.get("factors") or []) or "the forecast weather"
    s = f"Your outage risk is {ctx['band']}. "
    if ctx.get("area_lost_share") is not None:
        pct = min(99, max(1, round(100 * ctx["area_lost_share"])))
        s += f"About {pct}% of homes in {ctx['area']} lose power in this event. "
    s += f"The biggest reasons: {f}. "
    if ctx.get("estimate_label"):
        s += f"If your power goes out, restoration is {ctx['estimate_label']} (a model estimate). "
    s += f"Confidence: {ctx['confidence']}."
    return s


_DISK = Path(__file__).resolve().parents[1] / "cache" / "ai_cache.json"
_disk_lock = threading.Lock()


def _disk_cached(kind: str, prompt: str, ctx_json: str, make) -> str:
    """Claude outputs saved to backend/cache (gitignored). Same model + prompt + inputs -> same text, no API call."""
    key = hashlib.sha256(f"{kind}|{ANTHROPIC_MODEL}|{prompt}|{ctx_json}".encode()).hexdigest()
    with _disk_lock:
        try:
            store = json.loads(_DISK.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            store = {}
        if key in store:
            return store[key]
    text = make()
    with _disk_lock:
        try:
            store = json.loads(_DISK.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            store = {}
        store[key] = text
        _DISK.parent.mkdir(parents=True, exist_ok=True)
        _DISK.write_text(json.dumps(store), encoding="utf-8")
    return text


@lru_cache(maxsize=256)
def _generate(ctx_json: str) -> str:
    return _disk_cached("comms", SYSTEM, ctx_json, lambda: _call_comms(ctx_json))


def _call_comms(ctx_json: str) -> str:
    resp = _client().beta.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4000,
        system=SYSTEM,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": "Facts (JSON):\n" + ctx_json +
                   "\n\nWrite: a 2-4 sentence explanation of the risk and estimate, then the four messages."}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("refusal")
    return next(b.text for b in resp.content if b.type == "text")


def communications(ctx: dict) -> dict:
    """Returns {explanation, messages{...}, source: 'claude' | 'template'}."""
    safe = {k: ctx[k] for k in ("scenario_name", "is_simulation", "band", "area", "area_lost_share",
                                "home_lost_share", "confidence",
                                "confidence_reason", "factors", "estimate_label", "cause_plain", "fixed_plain",
                                "delay_reason", "hazard", "declared_needs")
            if k in ctx}
    try:
        data = json.loads(_generate(json.dumps(safe, sort_keys=True)))
        return dict(explanation=data.pop("explanation"), messages=data, source="claude")
    except (anthropic.APIError, anthropic.AuthenticationError, RuntimeError, StopIteration, ValueError,
            TypeError) as e:
        log.info("AI layer unavailable (%s); using templates", type(e).__name__)
    except Exception as e:  # missing credentials raise at client construction / request time
        log.info("AI layer unavailable (%s); using templates", e)
    return dict(explanation=_fallback_explanation(ctx), messages=template_messages(ctx), source="template")


# ------------------------------------------------------------------ preparation plan, scaled to the risk band
PREP_SYSTEM = """You tailor storm-preparation guidance for one AEP customer.
Rules:
- Use ONLY the tips in the JSON "tips" lists. You may shorten, merge, reorder and rephrase them in plain language,
  but never add new safety, medical, or equipment advice, and never invent numbers or times.
- Scale the length and tone to the risk band:
  * Low: calm, reassuring, no urgency. One section with at most 3 everyday-readiness items.
  * Elevated: practical. Up to 2 sections, at most 6 items total.
  * High: clear and direct. Up to 3 sections, at most 9 items total; say why acting now matters.
  * Severe: urgent but calm. All relevant tips, grouped into up to 4 sections; lead with the most time-sensitive.
- Always include every tip from "your_needs" (declared needs) in its own section if any exist.
- Headline is one short sentence. Intro is 1-2 sentences that mention the band and, if given, the outage estimate.
- Call the storm by scenario_name (e.g. "Arctic cold event", "Live forecast") - don't rename it from the weather."""

PREP_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "intro": {"type": "string"},
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "items"], "additionalProperties": False}},
    },
    "required": ["headline", "intro", "sections"],
    "additionalProperties": False,
}

PREP_LIMITS = {"Low": (2, 0, 0), "Elevated": (4, 2, 0), "High": (6, 4, 0), "Severe": (99, 99, 0)}


@lru_cache(maxsize=256)
def _generate_prep(ctx_json: str) -> str:
    return _disk_cached("prep", PREP_SYSTEM, ctx_json, lambda: _call_prep(ctx_json))


def _call_prep(ctx_json: str) -> str:
    resp = _client().beta.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4000,
        system=PREP_SYSTEM + "\n" + LIMITATION + " Never equate a risk band with an outage being likely or certain.",
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": PREP_SCHEMA}},
        messages=[{"role": "user", "content": "Customer context and approved tips (JSON):\n" + ctx_json}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("refusal")
    return next(b.text for b in resp.content if b.type == "text")


def _fallback_prep(ctx: dict) -> dict:
    """Same band scaling without the AI: fewer, calmer items at low risk."""
    tips, band = ctx["tips"], ctx["band"]
    n_now, n_out, _ = PREP_LIMITS.get(band, PREP_LIMITS["Elevated"])
    sections = [dict(title="Good to have ready" if band == "Low" else "Do now", items=tips["now"][:n_now])]
    if n_out:
        sections.append(dict(title="If your power goes out", items=tips["if_out"][:n_out]))
    if tips["your_needs"]:
        sections.append(dict(title="For the needs you told us about", items=tips["your_needs"]))
    headline = {"Low": "Keep your essentials ready.",
                "Elevated": "A few simple steps will help if the power goes out.",
                "High": "Review your storm plan and essential supplies.",
                "Severe": "Prepare for a possible extended outage."}.get(band, "Be prepared.")
    intro = f"Your risk band is {band}."
    if ctx.get("estimate_label"):
        intro += f" If your power goes out, restoration is {ctx['estimate_label']} (a model estimate)."
    return dict(headline=headline, intro=intro, sections=[s for s in sections if s["items"]])


def preparation_plan(ctx: dict) -> dict:
    """{headline, intro, sections[{title, items}], source}. Only approved tips; length scaled to the band."""
    safe = {k: ctx[k] for k in ("scenario_name", "band", "hazard", "estimate_label", "weather", "declared_needs", "tips")
            if k in ctx}
    try:
        data = json.loads(_generate_prep(json.dumps(safe, sort_keys=True)))
        return dict(**data, source="claude")
    except Exception as e:  # no credentials, refusal, network: band-scaled templates
        log.info("AI prep unavailable (%s); using templates", type(e).__name__)
        return dict(**_fallback_prep(ctx), source="template")


# ------------------------------------------------------------------ "Ask the Concierge" chat
CHAT_SYSTEM = """You are the AEP Outage Concierge, a friendly assistant that helps one AEP customer understand storm-related
power outages for their home. Answer using ONLY the FACTS JSON below (this customer's model results for the selected
forecast or storm simulation).

Rules:
- Never invent numbers, times, causes or places. If the facts don't cover something, say you don't know and point the
  customer to AEP (aep.com, the AEP app, or 1-800-956-4237).
- Keep estimates labelled as estimates. "home_lost_share" is how often this home lost power across simulated runs;
  "area_lost_share" is the share of homes in their area that lose power. Never call either a guarantee.
- If is_simulation is true, make clear this is a simulated storm, not a real forecast.
- SAFETY FIRST: if the customer mentions a downed line, sparks, fire, a gas smell, or a medical emergency, start with:
  "If this is an emergency, call 911 now. Stay at least 35 feet away from downed lines." For downed lines, also say to
  report them to AEP at 1-800-956-4237.
- Only mention medical equipment advice if declared_needs includes it, or if the customer asks about it - and then
  only "contact your provider or go to a hospital if your equipment needs power".
- You cannot report an outage, change account settings, or see other customers. Say how they can do it instead
  (report outages to AEP; alert settings are in My Data & Privacy in this app).
- Stay on topic: power outages, storms, restoration, preparation, safety and alerts. Politely decline anything else.
- Plain language a 12-year-old understands. Short answers: 2-5 sentences, or a short list for steps.
"""

OPS_CHAT_SYSTEM = """You are the AEP Operations Copilot, an assistant for AEP storm-response operators and planners.
Answer using ONLY the FACTS JSON below (model results for the selected forecast or storm simulation at the current
crew settings).

Rules:
- Never invent numbers, times, places, circuits or costs. If the facts don't cover something, say so and point to the
  right tab in this app (Ops Map, Simulation, Restoration Jobs, Business Impact, Communications, Model Audit, Settings).
- Model outputs come from Monte Carlo runs: give the typical (p50) value and the p10-p90 range when it matters, and
  say they are model estimates. Mention the confidence level when the question depends on it.
- If is_simulation is true, say it is a simulated storm, not a live forecast.
- Values in "hours" are hours after window_start; prefer the *_at fields for clock times when they are given.
- crew_what_if holds quick 12-run re-simulations of the same storm with half, current and double crews: use it for
  "are crews enough / what if we add or cut crews" questions. Crew sliders are on the Simulation tab; the total-cost vs
  crews curve is on Business Impact.
- You may recommend actions (staging crews, requesting mutual aid, prioritising circuits or life-support customers,
  sending alerts) but explain the reason from the facts and leave the decision to the operator. You cannot change
  settings, dispatch crews or send messages yourself.
- Customer privacy: talk about areas, circuits and counts only. Never name customers or give addresses.
- Stay on topic: storm risk, outages, restoration, crews, costs, customer communications and the model. Politely
  decline anything else.
- Be concise and operational: a one-sentence answer first, then at most 5 short one-line bullets.
"""

MAX_TURNS = 12


def _clean_history(history: list[dict]) -> list[dict]:
    """Keep the last turns, user/assistant only, alternating, ending with the user's message."""
    msgs = [dict(role=m["role"], content=str(m["content"])[:1500]) for m in history
            if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()]
    msgs = msgs[-MAX_TURNS:]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    out = []
    for m in msgs:  # merge accidental repeats of the same role
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n" + m["content"]
        else:
            out.append(m)
    return out


def _fallback_chat(facts: dict, question: str) -> str:
    q = question.lower()
    if any(w in q for w in ("down", "spark", "fire", "gas", "emergency", "911", "hurt")):
        return ("If this is an emergency, call 911 now. Stay at least 35 feet away from downed lines and anything "
                "touching them, and report them to AEP at 1-800-956-4237.")
    est = facts.get("restoration")
    if any(w in q for w in ("how long", "restor", "back on", "when will")):
        return (f"If your power goes out, restoration is {est['label']} (a model estimate)."
                if est else "In most simulated runs your power stays on, so there's no restoration estimate.")
    if any(w in q for w in ("prepare", "ready", "do i", "should i", "safe")):
        return "Here's what to do now: " + " ".join(facts["preparation"]["now"][:3])
    if "alert" in q or "text" in q or "notif" in q:
        return facts["alerts"]["reason"]
    if any(w in q for w in ("why", "cause")):
        return "The main reasons: " + "; ".join(facts["factors"][:3]) + "."
    pct = round(100 * (facts.get("area_lost_share") or 0))
    return (f"Your outage risk band is {facts['band']}. About {pct}% of homes in {facts['area']} lose power in this "
            f"{'simulated storm' if facts['is_simulation'] else 'forecast'}. Ask me how long restoration could take, "
            "how to prepare, or about alerts.")


def _fallback_ops_chat(facts: dict, question: str) -> str:
    q = question.lower()
    s = facts["summary"]
    if any(w in q for w in ("cost", "revenue", "dollar", "$", "impact")) and facts.get("cost"):
        c = facts["cost"]
        return (f"Estimated lost revenue ${c['lost_revenue']:,}, repair about ${c['repair']['total_mid']:,} and "
                f"customer cost ${c['customer_cost']:,}. See Business Impact for the breakdown.")
    if any(w in q for w in ("zip", "circuit", "worst", "where", "area")):
        z = ", ".join(f"{a['id']} ({a['pct_out']}%)" for a in facts["worst_zips"][:3]) or "none"
        return f"At the peak hour the hardest-hit ZIPs are {z}. The Ops Map shows every ZIP and circuit."
    if any(w in q for w in ("crew", "mutual", "restor", "how long")):
        return (f"With {facts['crews']['local']} local and {facts['crews']['mutual_aid']} mutual-aid crews, 90% of "
                f"customers are restored in about {s['hours_to_90pct']['p50']} h (p10-p90 "
                f"{s['hours_to_90pct']['p10']}-{s['hours_to_90pct']['p90']} h).")
    return (f"{facts['scenario']}: about {s['customers_out']['p50']:,.0f} customers out (p10-p90 "
            f"{s['customers_out']['p10']:,.0f}-{s['customers_out']['p90']:,.0f}), roughly {s['jobs']['p50']:.0f} "
            "repair jobs. Ask about crews, costs, the worst areas or life-support customers.")


def chat(facts: dict, history: list[dict], ops: bool = False) -> dict:
    """{reply, source}. Claude answers from this customer's facts only; template fallback otherwise."""
    msgs = _clean_history(history)
    if not msgs or msgs[-1]["role"] != "user":
        return dict(reply="Ask me anything about the storm, outages, crews or costs." if ops else
                    "Ask me anything about your power, a storm, or how to prepare.", source="template")
    try:
        resp = _client().beta.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2000,
            system=(OPS_CHAT_SYSTEM if ops else CHAT_SYSTEM + "\n" + LIMITATION) + "\nFACTS (JSON):\n" + json.dumps(facts, sort_keys=True, default=str),
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            messages=msgs,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("refusal")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            raise RuntimeError("empty")
        return dict(reply=text, source="claude")
    except Exception as e:  # no credentials, refusal, network
        log.info("AI chat unavailable (%s); using templates", type(e).__name__)
        fb = _fallback_ops_chat if ops else _fallback_chat
        return dict(reply=fb(facts, msgs[-1]["content"]), source="template")
