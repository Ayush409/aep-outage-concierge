import { useEffect, useState } from "react";
import { api, BANDS, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Loading, useFetch } from "../components/ui.jsx";

export default function Comms() {
  const { scenarios, scenario } = useApp();  // follows the top-right toggle
  const [settings, setSettings] = useState(null);
  const [tick, setTick] = useState(0);
  // the log is generated from the selected simulation (and re-generated when the alert rules change)
  const timeline = useFetch(`/api/aep/alerts/timeline${qs({ scenario })}`, [scenario, tick]).data;
  const feed = timeline?.alerts;
  const customers = useFetch("/api/aep/customers").data;
  useEffect(() => { api("/api/aep/settings").then(setSettings); }, []);

  async function save(body) {
    const s = await api("/api/aep/settings", { method: "PUT", body });
    setSettings(s);
    setTick((t) => t + 1);
  }
  async function send() {
    setBusy(true);
    setError("");
    try {
      setResult(await api(`/api/aep/alerts/send${qs({ scenario, kind })}`, { method: "POST" }));
      setTick(tick + 1);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!settings) return <div className="page"><Loading /></div>;
  return (
    <div className="page stack">
      <div className="grid cols-3">
        <section className="card stack">
          <h2>Customer alert rules</h2>
          <label className="field"><span>Send customer alerts from this risk band</span>
            <select value={settings.customer_alert_threshold}
              onChange={(e) => save({ customer_alert_threshold: e.target.value })}>
              {BANDS.map((b) => <option key={b}>{b}</option>)}
            </select></label>
          <label className="check"><input type="checkbox" checked={settings.life_support_one_band_lower === "1"}
            onChange={(e) => save({ life_support_one_band_lower: e.target.checked })} />
            <span>Customers who declared a medical need get alerts one band earlier</span></label>
          <div className="small muted">AEP operators receive every alert regardless of band.</div>
        </section>
        <section className="card stack">
          <h2>Automatic alerts</h2>
          <div className="small">Following: <b>{scenario === "live" ? "Live forecast"
            : `Simulation - ${scenarios.find((s) => s.id === scenario)?.name}`}</b> (change it in the top-right menu)</div>
          <div className="small secondary">Alerts go out on their own as the {scenario === "live" ? "forecast" : "simulated storm"}
            {" "}unfolds - no manual sending. {scenario === "live" ? "The live forecast only sends pre-storm alerts; outage stages need a real utility feed, which is not connected."
              : "Storm drills are simulated: in-app practice messages only, never texts."}</div>
          {timeline && <div className="planner-constraints">
            {[["pre_storm", "Pre-storm"], ["outage_confirmed", "Outage"], ["estimate_updated", "Updates"], ["restored", "Restored"],
              ["escalation", "Escalations"]].map(([k, l]) => (
              <div key={k}><b>{timeline.alerts.filter((n) => n.kind === k).length}</b><span>{l}</span></div>))}
          </div>}
        </section>
        <section className="card stack">
          <h2>Escalation triggers</h2>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            <li>A customer with a declared medical need is expected to be out</li>
            <li>A hospital's circuit is out (restoration priority boost)</li>
            <li>Low-confidence prediction in a Severe area - verify with field reports</li>
            <li>Review changes in restoration estimates before sending the update stage. Identical snapshots are skipped; this prototype does not monitor live estimate changes automatically.</li>
          </ul>
        </section>
      </div>
      <section className="card stack">
        <h2>Notification log - {scenario === "live" ? "live forecast" : scenarios.find((s) => s.id === scenario)?.name}</h2>
        <div className="small muted">Simulated: generated from this {scenario === "live" ? "forecast" : "storm"} and
          stamped with the time each alert would go out (shown in your time zone).</div>
        {!feed ? <Loading /> : feed.length === 0 ? <div className="muted">No alerts for this {scenario === "live"
          ? "forecast - no customer reaches the alert band" : "storm"}.</div> : (
          <div style={{ maxHeight: 420, overflow: "auto" }}>
            <table>
              <thead><tr><th>Simulated time</th><th>To</th><th>Type</th><th>Band</th><th>Channel</th><th>Message</th></tr></thead>
              <tbody>{feed.map((n, i) => (
                <tr key={i} style={n.escalation ? { background: "color-mix(in srgb, var(--band-severe) 10%, transparent)" } : undefined}>
                  <td className="small" style={{ whiteSpace: "nowrap" }}>{new Date(n.at).toLocaleString(undefined,
                    { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" })}</td>
                  <td>{n.customer || "AEP operations"}</td><td>{n.escalation ? "⚠ Escalation" : n.title}</td>
                  <td>{n.band || "-"}</td><td className="small">{n.channel}</td><td className="small">{n.body}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </section>
      <section className="card stack">
        <h2>Registered customers</h2>
        <div className="small muted">Decrypted for operators only; every view is written to the audit log.</div>
        {!customers ? <Loading /> : (
          <table><thead><tr><th>Name</th><th>Email</th><th>ZIP</th><th>Declared needs</th></tr></thead>
            <tbody>{customers.map((c) => <tr key={c.id}><td>{c.name}</td><td>{c.email}</td><td>{c.zip}</td>
              <td>{c.needs.join(", ") || "-"}</td></tr>)}</tbody></table>
        )}
      </section>
    </div>
  );
}
