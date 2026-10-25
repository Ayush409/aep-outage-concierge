import { useState } from "react";
import { Link } from "react-router-dom";
import { api, fmt } from "../api.js";
import { useApp } from "../App.jsx";

export const durationRange = (r) => r ? `${fmt.hours(r.p10)} – ${fmt.hours(r.p90)}` : "No duration range";
const STEPS = ["Before the storm", "Outage", "Updated estimate", "Restored"];

export function ChangeCard({ change }) {
  if (!change) return <div className="privacy-note"><b>What changed?</b><p className="small">During the walkthrough, change repair-access difficulty to compare real simulation results.</p></div>;
  return <section className="change-card stack" aria-label="What changed" aria-live="polite">
    <h3>{change.changed ? "Your outlook changed" : "Your outlook is unchanged"}</h3>
    <div className="change-comparison"><div><span className="small secondary">Earlier duration range</span><strong>{durationRange(change.before.range)}</strong></div>
      <div><span className="small secondary">Updated duration range</span><strong>{durationRange(change.after.range)}</strong></div></div>
    {change.before.range && change.after.range && <p className="small secondary">
      Typical modeled duration: {change.before.range.p50.toFixed(1)} hours before; {change.after.range.p50.toFixed(1)} hours now.
      {change.typical_hours_delta === 0 ? " The typical duration is unchanged." : " The wider range may stay the same even when the typical duration changes."}
      {" "}These are model comparisons, not promised restoration times.
    </p>}
    <p>{change.reason}</p><p><b>Your next step:</b> {change.next_action}</p>
  </section>;
}

export default function CustomerJourney({ status }) {
  const { scenario, journey, updateJourney, setScenario, journeyError } = useApp();
  const [access, setAccess] = useState(1.8);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const stage = journey?.stage ?? -1;
  async function advance(action) {
    setBusy(true); setError("");
    try {
      const next = await api("/api/me/journey", { method: "POST", body: { scenario, action, access_mult: access } });
      updateJourney(next);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  if (scenario === "live") return <section className="card journey-card stack">
    <h2>Try your household’s storm journey</h2><p>See how preparation, estimates, and alerts change through a practice storm.</p>
    <button className="primary" onClick={() => setScenario("snow_storm")}>Explore a snow-storm simulation</button>
  </section>;
  return <section className="card journey-card stack" aria-labelledby="journey-title">
    <div className="row spread"><h2 id="journey-title">Your storm journey</h2><span className="tag">Practice only · no texts sent</span></div>
    <ol className="journey-steps">{STEPS.map((label, i) => <li key={label} className={i <= stage ? "reached" : ""} aria-current={i === stage ? "step" : undefined}>
      <span>{i + 1}</span>{label}</li>)}</ol>
    <div aria-live="polite">
      {stage < 0 && <p>Walk through one household’s storm, then change an assumption and see what happens.</p>}
      {stage === 0 && <p>Review your preparation priorities. A pre-storm practice alert is added if you qualify and have in-app alerts enabled.</p>}
      {stage === 1 && <p>{status.event.timeline ? "Your home loses power in this simulated outcome. Review its estimated duration, then try changing repair-access difficulty."
        : "Your home keeps power in this map outcome. You can still explore how harder repairs affect other simulation runs."}</p>}
      {stage === 3 && <p>{status.event.timeline ? "Your home is restored in the practice journey. The map may show other neighborhoods still waiting."
        : "Your home kept power in this practice journey."}</p>}
    </div>
    {stage === 1 && <div className="experiment-panel stack">
      <label className="slider"><span>What if repairs are harder to access?</span><b>{access.toFixed(1)}×</b>
        <input type="range" min="0.5" max="2.5" step="0.1" value={access} onChange={(e) => setAccess(+e.target.value)} /></label>
      <p className="small secondary">1× is the original access assumption. Higher values increase the modeled share of difficult-access jobs. Storm and crew settings stay the same; a home’s result may not change.</p>
    </div>}
    <ChangeCard change={journey?.change} />
    <div className="row">
      {stage < 3 && <button className="primary" disabled={busy || !journey} onClick={() => advance(["start", "outage", "update", "restore"][stage + 1])}>
        {busy ? "Recalculating your journey…" : ["Start walkthrough", "Advance to outage", "Recalculate and compare", "Advance to restoration"][stage + 1]}</button>}
      {stage >= 0 && <button disabled={busy} onClick={() => advance("restart")}>Restart walkthrough</button>}
      <Link to="/alerts">View practice alerts</Link><Link to="/map">Explore the same outcome on the map</Link>
    </div>
    {(error || journeyError) && <div className="error" role="alert">{error || journeyError}</div>}
  </section>;
}
