"""Scenario catalogue: generic storm types whose damage behaviour is learned from Feb 2025 + Helene."""
import json

import numpy as np

from .data import WEATHER
from .weather import POINTS, Hourly, display_event, display_live, event, grid_json, live

SCENARIOS = {
    "live": dict(
        name="Live forecast (next 7 days)", kind="live", hazard="auto", weather="live",
        summary="Open-Meteo forecast for the service area, updated every 30 minutes.",
    ),
    "derecho": dict(
        name="Derecho", kind="scenario", hazard="wind", weather="derecho_2012", gust_peak_obs=81.0,
        summary="A fast-moving line of severe thunderstorms with 60-80+ mph straight-line winds, in summer heat.",
        learned_from="Equipment, access and crew behaviour from the Feb 2025 wind-phase damage reports.",
        notes=["Weather pattern from a real derecho that crossed this area. Reanalysis smooths thunderstorm "
               "gusts, so storm hours are scaled to the 81 mph gust measured locally."],
    ),
    "tornado_outbreak": dict(
        name="Tornado outbreak", kind="scenario", hazard="tornado", weather="tornado_2011", rules=["tornado"],
        summary="Several tornado tracks (EF0-EF4) crossing the service area during a severe-weather day.",
        learned_from="Feb 2025 wind-phase damage behaviour; tornado paths use physics-based rules.",
        notes=["Tornado tracks come from a real outbreak elsewhere, shifted onto this area.",
               "Tornado damage needs a large mutual-aid call: defaults to 50 local + 150 mutual-aid crews."],
        default_crews=dict(crews=50, mutual_aid_crews=150),
    ),
    "snow_storm": dict(
        name="Snow storm", kind="scenario", hazard="snow", weather="snow_2009_12", snow_ice_equiv=0.08,
        summary="About a foot of heavy, wet snow near freezing - limbs and lines come down under the weight.",
        learned_from="Loading damage learned from the Feb 2025 ice storm, applied to wet snow (assumption).",
        notes=["No local snow-damage records exist. Wet snow is treated as 0.08 in of ice per inch of snow "
               "(assumption), using what the model learned from the Feb 2025 ice storm."],
    ),
    "arctic_cold": dict(
        name="Arctic cold event", kind="scenario", hazard="wind", weather="arctic_2022_12", rules=["cold"],
        summary="A flash freeze: temperatures crash from the 40s to near 0 F behind a windy arctic front.",
        learned_from="Feb 2025 wind-phase damage behaviour; heating overload uses physics-based rules.",
        notes=["Transformer overload in extreme cold uses physics-based rules (no local records)."],
    ),
}


def weather_for(sid: str, gust_mult: float = 1.0) -> Hourly:
    sc = SCENARIOS[sid]
    h = live() if sc["weather"] == "live" else event(sc["weather"])
    if sc.get("gust_peak_obs"):
        h = _scale_convective(h, sc["gust_peak_obs"])
    h = _consistent_speed(h)
    return h.scaled(gust_mult) if gust_mult != 1.0 else h


GUST_FACTOR = 1.6  # typical gust / sustained-wind ratio for strong synoptic winds


def _consistent_speed(h: Hourly) -> Hourly:
    """Reanalysis/forecast steady wind in this hilly terrain runs 2.5-3x below the gusts, while measured strong
    winds gust ~1.4-1.7x the steady speed. Use the larger of the data's steady wind and gust / 1.6, so wind
    speed tracks the gusts in every setting (calm hours keep the data's own value)."""
    h = h.scaled(1.0)
    h.f["wind_speed_10m"] = np.maximum(h.f["wind_speed_10m"], h.f["wind_gusts_10m"] / GUST_FACTOR)
    return h


def _scale_convective(h: Hourly, peak_obs: float) -> Hourly:
    """Reanalysis smooths thunderstorm gusts: scale the storm hours so the peak matches the measured gust."""
    h = h.scaled(1.0)
    g = h.f["wind_gusts_10m"]
    peak_t = int(np.argmax(g.max(axis=0)))
    factor = peak_obs / g[:, peak_t].max()
    win = slice(max(0, peak_t - 3), peak_t + 4)  # the convective line passes in a few hours
    h.f["wind_gusts_10m"][:, win] *= factor
    # sustained wind in a convective line runs ~70% of the gusts (gust factor ~1.4)
    h.f["wind_speed_10m"][:, win] = np.maximum(h.f["wind_speed_10m"][:, win], h.f["wind_gusts_10m"][:, win] / 1.4)
    return h


def display_weather(sid: str) -> dict:
    """Weather for the maps on the larger display grid, with the same convective correction as the model."""
    sc = SCENARIOS[sid]
    h, grid = display_live() if sc["weather"] == "live" else display_event(sc["weather"])
    if sc.get("gust_peak_obs"):
        h = _scale_convective(h, sc["gust_peak_obs"])
    h = _consistent_speed(h)
    return grid_json(h, grid, 1 if h.hours <= 240 else 2)


def tornado_tracks() -> list[dict]:
    return json.loads((WEATHER / "tornado_2011.json").read_text())


def default_crews(sid: str) -> dict:
    """Local + mutual-aid crews a scenario starts with (big events come with a bigger mutual-aid call)."""
    return dict(crews=20, mutual_aid_crews=40) | SCENARIOS[sid].get("default_crews", {})  # Feb 2025 calibration


def catalogue() -> list[dict]:
    out = []
    for sid, sc in SCENARIOS.items():
        out.append(dict(id=sid, **{k: v for k, v in sc.items() if k not in ("weather",)}))
    return out


__all__ = ["SCENARIOS", "weather_for", "tornado_tracks", "catalogue", "default_crews", "POINTS"]
