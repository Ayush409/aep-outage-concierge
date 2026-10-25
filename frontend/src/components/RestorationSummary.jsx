import { fmt, hourLabel } from "../api.js";

/** The same hourly outcome used by map playback; ranges remain in My Status. */
export default function RestorationSummary({ status, compact = false }) {
  const { event, start, restoration } = status;
  const home = event.timeline;
  return (
    <div className={`stack${compact ? " small" : ""}`}>
      <div className="restoration-range"><span className="small secondary">If your home loses power</span>
        <strong>{restoration ? `${fmt.hours(restoration.p10)} – ${fmt.hours(restoration.p90)}` : "No duration range available"}</strong>
        <span className="small secondary">{restoration ? "Modeled outage-duration range across runs. Actual restoration may differ." : "No home outage was modeled in the sampled runs."}</span>
      </div>
      <details><summary>Example outcome shown on the map</summary>
      <div><b>Your home restored in this example:</b>{" "}
        {home ? hourLabel(start, home.restored) : "Your home stays on in the map’s simulated outcome."}</div>
      <div><b>All modeled customers restored:</b>{" "}
        {event.all_restored_hour != null ? hourLabel(start, event.all_restored_hour) : "No outages in the map’s simulated outcome."}</div>
      <div className="small muted">One simulated outcome, shared with the map. Your home may regain power before other areas. Estimates vary across runs.</div>
      </details>
    </div>
  );
}
