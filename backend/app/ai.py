"""Claude writes the plain-language explanation and the four customer messages.

Guardrails:
- Claude only receives engine outputs (numbers, bands, factor labels). No names, addresses,
  phone numbers or exact coordinates are ever sent.
- The prompt forbids inventing numbers; output is schema-constrained JSON.
- Any failure (no credentials, refusal, network) falls back to the deterministic templates.
"""
import json
import logging
from functools import lru_cache

import anthropic

from .config import ANTHROPIC_MODEL
from .guidance import template_messages

log = logging.getLogger("ai")

SYSTEM = """You write outage communications for AEP customers during storms.
Rules:
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


@lru_cache(maxsize=256)
def _generate(ctx_json: str) -> str:
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
    resp = _client().beta.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4000,
        system=PREP_SYSTEM,
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
    headline = {"Low": "No action needed right now - just the basics.",
                "Elevated": "A few simple steps will help if the power goes out.",
                "High": "Get ready now - an outage is likely.",
                "Severe": "Prepare now - an outage is very likely and may be long."}.get(band, "Be prepared.")
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
