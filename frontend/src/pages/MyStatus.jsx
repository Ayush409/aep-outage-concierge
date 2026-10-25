import { Link } from "react-router-dom";
import { fmt, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Band, ErrorBox, Loading, useFetch } from "../components/ui.jsx";
import RestorationSummary from "../components/RestorationSummary.jsx";
import CustomerJourney from "../components/CustomerJourney.jsx";
import PreparationChecklist from "../components/PreparationChecklist.jsx";

export default function MyStatus() {
  const { customerParams, customerRevision, journey, journeyError } = useApp();
  const { data: s, error, loading } = useFetch(journey ? `/api/me/status${qs(customerParams)}` : null,
    [customerParams.scenario, customerParams.access_mult, customerRevision]);
  if (error || journeyError) return <div className="page"><ErrorBox error={error || journeyError} /></div>;
  if (loading || !s) return <div className="page"><Loading what="Building your household outlook" /></div>;
  const simulated = s.scenario.kind !== "live";
  return <div className="page customer-readable stack customer-home">
    <header className="privacy-heading">
      <h1>Your outlook. Your next step.</h1>
      <p className="secondary">{simulated ? `Practice storm: ${s.scenario.name}` : "Your household?s forecast-based storm plan"}</p>
      <span className="small muted">Calculated {new Date(s.generated_at * 1000).toLocaleString()}. Model estimates; no live utility confirmation feed.</span>
    </header>
    <div className="grid cols-2 customer-content-grid">
      <section className="card stack">
        <div className="row spread"><h2>Your outlook</h2><span className="tag estimate">Experimental estimate</span></div>
        <div className="row"><Band band={s.risk.band} big /><span>storm planning indicator</span></div>
        <p className="secondary">This band helps prioritize preparation. It is not a validated probability that your home will lose power.</p>
        <RestorationSummary status={s} />
        <details><summary>Why this estimate has limited confidence</summary>
          <ul>{s.confidence.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          <h3>Main factors for your home</h3><ul>{s.factors_plain.map((f) => <li key={f}>{f}</li>)}</ul>
          <p className="small">Your home loses power in {Math.round(s.event.home_share * s.event.runs)} of {s.event.runs} model runs. This describes the simulation, not measured real-world odds.</p>
        </details>
        <Link to="/map">See your home and surrounding outages</Link>
      </section>
      <section className="card"><PreparationChecklist status={s} compact /></section>
    </div>
    <CustomerJourney key={customerParams.scenario} status={s} />
    <section className="card stack">
      <div className="row spread"><h2>Stay informed</h2><Link to="/alerts">Open Alerts &amp; preparation</Link></div>
      <p>{s.alerts.reason}</p>
      <p className="small secondary">{s.alerts.channels.length ? `Selected channels: ${s.alerts.channels.join(", ")}.` : "No alert channels are enabled."} Practice walkthrough messages stay in-app.</p>
      <Link to="/data">Manage your needs, alert preferences, and privacy</Link>
    </section>
  </div>;
}
