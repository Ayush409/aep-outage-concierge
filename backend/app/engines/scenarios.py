"""Scenario catalogue: real local replays and "what if it hit Virginia" transpositions."""
import json

import numpy as np

from .data import WEATHER
from .weather import POINTS, Hourly, event, live

SCENARIOS = {
    "live": dict(
        name="Live forecast (next 7 days)", kind="live", hazard="auto", weather="live",
        summary="Open-Meteo forecast for the service area, updated every 30 minutes.",
    ),
    "feb_2025": dict(
        name="Feb 2025 ice + wind storm", kind="replay", hazard="ice", weather="feb_2025",
        damage_events=["feb_2025_ice", "feb_2025_wind"], date="Feb 10-19, 2025",
        summary="About 40 hours of freezing rain (Feb 11-13), then 55 mph gusts on soaked ground (Feb 16-17). "
                "1,254 real damage reports.",
    ),
    "helene_2024": dict(
        name="Hurricane Helene", kind="replay", hazard="tropical", weather="helene_2024",
        damage_events=["helene_2024", "helene_late_reports"], date="Sep 25 - Oct 1, 2024",
        summary="3.7 in of rain on saturated ground, gusts near 48-62 mph. 194 real damage reports.",
    ),
    "winter_2025_01": dict(
        name="January 2025 winter storm", kind="replay", hazard="ice", weather="winter_2025_01",
        damage_events=["winter_storm_2025_01"], date="Jan 4-8, 2025",
        summary="Snow, then mixed precipitation below freezing. 46 real damage reports.",
    ),
    "derecho_2012": dict(
        name="June 2012 derecho", kind="whatif", hazard="wind", weather="derecho_2012", date="Jun 29 - Jul 2, 2012",
        gust_peak_obs=81.0,
        summary="Really hit Roanoke: an 81 mph gust at Roanoke Regional Airport during a 100+ F heat wave. "
                "No AEP damage records exist for it, so damage is simulated.",
        notes=["Reanalysis weather smooths thunderstorm gusts (37 mph). Storm hours are scaled so the peak "
               "matches the 81 mph gust measured at Roanoke Regional Airport (SPC storm report)."],
    ),
    "texas_freeze_2021": dict(
        name="Texas deep freeze (Feb 2021) over Roanoke", kind="whatif", hazard="ice", weather="texas_freeze_2021",
        date="Feb 13-20, 2021", rules=["cold"],
        summary="Austin's Feb 2021 weather moved onto Roanoke: lows near 3 F, freezing rain and snow.",
        notes=["Texas outages were mostly caused by generation shortfalls. This simulates only what the "
               "weather would do to the local distribution grid."],
    ),
    "heat_dome_2021": dict(
        name="Pacific NW heat dome (Jun 2021) over Roanoke", kind="whatif", hazard="heat", weather="heat_dome_2021",
        date="Jun 25 - Jul 1, 2021", rules=["heat"],
        summary="Portland's June 2021 heat moved onto Roanoke: highs up to 118 F.",
    ),
    "tornado_2011": dict(
        name="April 2011 tornado outbreak over Roanoke", kind="whatif", hazard="tornado", weather="tornado_2011",
        date="Apr 26-29, 2011", rules=["tornado"],
        summary="The Alabama core of the 27 April 2011 outbreak, tracks moved so its centre sits on Roanoke.",
    ),
}


def weather_for(sid: str, gust_mult: float = 1.0) -> Hourly:
    sc = SCENARIOS[sid]
    h = live() if sc["weather"] == "live" else event(sc["weather"])
    if sc.get("gust_peak_obs"):
        h = h.scaled(1.0)
        g = h.f["wind_gusts_10m"]
        peak_t = int(np.argmax(g.max(axis=0)))
        factor = sc["gust_peak_obs"] / g[:, peak_t].max()
        win = slice(max(0, peak_t - 3), peak_t + 4)  # the convective line passes in a few hours
        h.f["wind_gusts_10m"][:, win] *= factor
        h.f["wind_speed_10m"][:, win] *= min(factor, 1.6)
    return h.scaled(gust_mult) if gust_mult != 1.0 else h


def tornado_tracks() -> list[dict]:
    return json.loads((WEATHER / "tornado_2011.json").read_text())


def catalogue() -> list[dict]:
    out = []
    for sid, sc in SCENARIOS.items():
        out.append(dict(id=sid, **{k: v for k, v in sc.items() if k not in ("weather",)}))
    return out


__all__ = ["SCENARIOS", "weather_for", "tornado_tracks", "catalogue", "POINTS"]
