"""Preparation guidance, alert eligibility and template messages.

Rules here are deterministic; the AI layer (ai.py) may rephrase messages but never changes facts.
Declared needs come only from what the customer chose to tell us - nothing is inferred.
"""
from .engines.risk import BAND_ORDER

EMERGENCY = ("EMERGENCY: Stay at least 35 feet away from downed power lines and anything touching them. "
             "Call 911, then report it to AEP at 1-800-956-4237.")


def band_index(b: str) -> int:
    return BAND_ORDER.index(b) if b in BAND_ORDER else 0


def effective_threshold(threshold: str, needs: list[str], one_lower: bool) -> str:
    i = band_index(threshold)
    if one_lower and ("medical_device" in needs or "life_support" in needs):
        i = max(i - 1, 0)
    return BAND_ORDER[i]


def alert_eligibility(band: str, threshold: str, needs: list[str], one_lower: bool, sms: bool, inapp: bool,
                      has_phone: bool) -> dict:
    eff = effective_threshold(threshold, needs, one_lower)
    eligible = band_index(band) >= band_index(eff)
    channels = []
    if eligible and inapp:
        channels.append("in-app")
    if eligible and sms and has_phone:
        channels.append("SMS")
    reason = (f"Your risk band ({band}) meets the alert level AEP set ({eff})." if eligible else
              f"Your risk band ({band}) is below the alert level AEP set ({eff}). You'll still see updates here.")
    if eff != threshold:
        reason += " Because you told us about a medical need, you get alerts one level earlier."
    return dict(eligible=eligible, threshold=threshold, your_threshold=eff, channels=channels, reason=reason,
                timing=["Pre-storm: about 24 hours before damaging weather is forecast to start",
                        "Outage confirmed: as soon as a device on your line is reported out",
                        "Estimate updated: when the likely restoration time moves by 2+ hours or 25%",
                        "Restored: when crews close the last job on your line"])


def preparation(band: str, hazard: str, est_hours: float | None, weather: dict, needs: list[str],
                service: str) -> dict:
    """Customer actions grouped by urgency. Emergencies are labelled explicitly."""
    tips = {"emergency": [EMERGENCY], "now": [], "if_out": [], "your_needs": []}
    i = band_index(band)
    long_out = (est_hours or 0) >= 24
    tips["now"].append("Charge phones, power banks and any battery-powered medical equipment.")
    if i >= 1:
        tips["now"] += ["Find flashlights and fresh batteries; avoid candles.",
                        "Keep 1 gallon of water per person per day for 3 days."]
    if i >= 2 or long_out:
        tips["now"] += ["Freeze water bottles to keep food cold longer; set fridge and freezer to coldest.",
                        "Fill your car's gas tank and get some cash - pumps and card readers need power."]
    if hazard in ("ice", "cold") or (weather.get("tmin") is not None and weather["tmin"] <= 32):
        tips["now"].append("Plan a warm place to go: a friend's home or a public warming center.")
        tips["if_out"].append("Close off unused rooms and layer clothing; never use an oven or grill to heat your home.")
    if hazard == "heat" or (weather.get("tmax") is not None and weather["tmax"] >= 92):
        tips["now"].append("Plan where to cool off (library, cooling center) if the power goes out in the heat.")
        tips["if_out"].append("Drink water often, stay on the lowest floor, and check on older neighbors.")
    tips["if_out"] += [
        "Report your outage to AEP (app, aep.com, or 1-800-956-4237) - don't assume a neighbor has.",
        "Unplug sensitive electronics to protect them when power returns.",
        "Keep fridge and freezer closed: food stays cold about 4 hours (fridge) and 48 hours (full freezer).",
        "Generators only outdoors, 20+ feet from windows and doors - carbon monoxide is deadly.",
    ]
    if long_out:
        tips["if_out"].append("If the outage may last more than a day, throw out perishable food kept above 40 F for 2+ hours.")
    if service == "Overhead":
        tips["now"].append("Your service line is overhead: note where it attaches so you can report damage to it.")
    if "medical_device" in needs or "life_support" in needs:
        tips["your_needs"] += [
            "Make sure your medical device has backup batteries or a plan for where to plug in.",
            "If your life depends on powered equipment, have a plan to go to a hospital or shelter early - "
            "AEP cannot guarantee priority restoration.",
            "Register as a medical-certificate customer with AEP if you haven't already."]
    if "mobility" in needs:
        tips["your_needs"].append("Arrange help from a neighbor or family member in case you need to leave home.")
    if "hearing_vision" in needs:
        tips["your_needs"].append("We'll send alerts by text as well as in the app so you don't miss them.")
    return tips


def template_messages(ctx: dict) -> dict:
    """Plain-language messages for the four required moments (used when the AI layer is unavailable)."""
    band = ctx["band"]
    est = ctx.get("estimate_label") or "we'll share an estimate soon"
    cause = ctx.get("cause_plain") or "storm damage on a line that serves your area"
    return {
        "pre_storm": (f"AEP storm alert: {ctx['scenario_name']} may affect your area. Your outage risk is {band} "
                      f"({ctx['confidence']} confidence). Charge devices and check your supplies. "
                      "Stay 35 ft from downed lines. Details in the AEP app."),
        "outage_confirmed": (f"AEP: We know your power is out. Likely cause: {cause}. Estimated restoration: {est}. "
                             "This is a model estimate, not a promise; we'll update you if it changes."),
        "estimate_updated": (f"AEP update: your restoration estimate changed. New estimate: {est}. "
                             f"Main reason: {ctx.get('delay_reason') or 'crews found more damage than first reported'}."),
        "restored": (f"AEP: Power is restored. What happened: {cause}. What crews fixed: "
                     f"{ctx.get('fixed_plain') or 'the damaged equipment on your line'}. "
                     "If you're still out, report it - there may be a separate problem at your home."),
    }
