import { BAND_COLOR, hourLabel } from "../api.js";

export function powerState(status, now = Date.now()) {
  const timeline = status.event.timeline;
  // Historical scenarios describe a modeled outcome, regardless of today's date.
  if (status.scenario.kind !== "live") {
    return timeline
      ? { title: "Your home in this simulation", color: BAND_COLOR[status.risk.band],
          detail: `In this simulation, your home loses power around ${hourLabel(status.start, timeline.power_lost)}.` }
      : { title: "Your home keeps power in this simulation", color: "var(--band-low)",
          detail: "This is the outcome shown on the map. Other simulation runs may have different results." };
  }
  const nowHour = (now - new Date(status.start).getTime()) / 3.6e6;
  if (timeline && nowHour >= timeline.power_lost && nowHour < timeline.restored) {
    return { title: "Outage predicted at this time", color: "var(--band-severe)",
      detail: "This is a forecast estimate. Check delivered alerts for outage updates." };
  }
  if (timeline && nowHour < timeline.power_lost) {
    return { title: "Outage possible", color: BAND_COLOR[status.risk.band],
      detail: `Your home could lose power around ${hourLabel(status.start, timeline.power_lost)} in the map’s simulated outcome.` };
  }
  if (timeline) {
    return { title: "Restoration predicted by now", color: "var(--band-low)",
      detail: "The map’s simulated outage has ended. This does not confirm your actual power status." };
  }
  return { title: "No outage in the map’s simulated outcome", color: "var(--band-low)",
    detail: "Your risk band includes other possible outcomes across the simulation runs." };
}
