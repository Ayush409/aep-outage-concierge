import { useState } from "react";
import { Link } from "react-router-dom";
import { qs } from "../api.js";
import { useApp } from "../App.jsx";
import { ErrorBox, Loading, useFetch } from "../components/ui.jsx";
import { offlinePlan } from "../components/offlinePlan.js";

export default function ReadyPlan() {
  const { customerParams, customerRevision, journey, journeyError } = useApp();
  const { data: s, error, loading } = useFetch(journey ? `/api/me/status${qs(customerParams)}` : null,
    [customerParams.scenario, customerParams.access_mult, customerRevision]);
  const [includeAddress, setIncludeAddress] = useState(false);
  const [includeNeeds, setIncludeNeeds] = useState(false);
  const [saved, setSaved] = useState(false);
  if (error || journeyError) return <div className="page"><ErrorBox error={error || journeyError} /></div>;
  if (!s || loading) return <div className="page"><Loading what="Preparing your downloadable plan" /></div>;
  function download() {
    const url = URL.createObjectURL(new Blob([offlinePlan(s, { includeAddress, includeNeeds })], { type: "text/html;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = "my-outage-plan.html"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); setSaved(true);
  }
  return <div className="page customer-readable stack ready-page">
    <Link to="/status">Back to your outlook</Link>
    <section className="card stack"><h1>Keep your plan within reach</h1>
      <p>Download a lightweight page you can open without internet or print. It includes your checklist, saved estimate, and emergency information.</p>
      <div className="privacy-note"><b>Saved information, not live updates</b><p>Calculated {new Date(s.generated_at * 1000).toLocaleString()} for {s.scenario.name}. Reconnect for current estimates.</p></div>
      <label className="check"><input type="checkbox" checked={includeAddress} onChange={(e) => setIncludeAddress(e.target.checked)} /><span>Include my address in the saved file</span></label>
      <label className="check"><input type="checkbox" checked={includeNeeds} onChange={(e) => setIncludeNeeds(e.target.checked)} /><span>Include personalized guidance for my declared needs</span></label>
      <p className="small secondary">These options start off. Downloaded files stay on your device until you remove them, even if you delete your account.</p>
      <button className="primary" onClick={download}>Download outage-ready plan</button>
      {saved && <div role="status">Download started. Open the saved HTML file while online to make sure you can find it later.</div>}
    </section>
    <section className="card stack"><h2>Included preparation steps</h2>
      <ul>{s.checklist.filter((t) => includeNeeds || t.group !== "your_needs").map((t) => <li key={t.key}>{t.done ? "Completed: " : ""}{t.text}</li>)}</ul>
    </section>
  </div>;
}
