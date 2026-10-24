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
- If confidence is Low or the cause is unknown, say so honestly and say AEP crews are still working on it.
- SMS-style messages must be under 300 characters.
- Never give medical advice beyond "contact your provider or go to a hospital if your equipment needs power"."""

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
    pct = min(99, max(1, round(100 * ctx["p_out"])))
    s = (f"Your outage risk is {ctx['band']} (about {pct}% chance in this scenario). "
         f"The biggest reasons: {f}. ")
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
    safe = {k: ctx[k] for k in ("scenario_name", "band", "p_out", "confidence", "factors", "estimate_label",
                                "cause_plain", "fixed_plain", "delay_reason", "hazard", "declared_needs")
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
