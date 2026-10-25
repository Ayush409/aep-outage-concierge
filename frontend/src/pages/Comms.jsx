import { useEffect, useState } from "react";
import { api, BANDS, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Loading, useFetch } from "../components/ui.jsx";

export default function Comms() {
  const { scenarios, scenario } = useApp();  // follows the top-right toggle
  const [settings, setSettings] = useState(null);
  const [tick, setTick] = useState(0);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState("pre_storm");
  const [error, setError] = useState("");
  const feed = useFetch("/api/aep/notifications", [tick]).data;
  const customers = useFetch("/api/aep/customers").data;
  useEffect(() => { api("/api/aep/settings").then(setSettings); }, []);

  async function save(body) {
    const s = await api("/api/aep/settings", { method: "PUT", body });
    setSettings(s);
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
          <h2>Send alerts</h2>
          <div className="small">Based on: <b>{scenario === "live" ? "Live forecast"
            : `Storm drill - ${scenarios.find((s) => s.id === scenario)?.name}`}</b> (change it in the top-right menu)</div>
          <button className="primary" onClick={send} disabled={busy}>
            {busy ? "Evaluating customers..." : "Evaluate customers and send alerts"}</button>
          <label className="field"><span>Stage to send</span><select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="pre_storm">Before the storm</option><option value="outage_confirmed">Practice outage begins</option>
            <option value="estimate_updated">Changed estimate only</option><option value="restored">Practice restoration</option>
          </select></label>
          <div className="small muted">One stage at a time. History is retained and duplicates are skipped. Storm drills stay in-app. Live outage confirmations require a utility feed, which is not connected.</div>
          {error && <div role="alert" className="error">{error}</div>}
          {result && <div className="small" role="status">Queued {result.messages} messages for {result.customers} customers;
            {" "}{result.escalations.length} escalation(s).</div>}
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
        <h2>Notification log</h2>
        {!feed ? <Loading /> : feed.length === 0 ? <div className="muted">Nothing sent yet.</div> : (
          <div style={{ maxHeight: 420, overflow: "auto" }}>
            <table>
              <thead><tr><th>When</th><th>To</th><th>Type</th><th>Band</th><th>Channel</th><th>Message</th></tr></thead>
              <tbody>{feed.map((n) => (
                <tr key={n.id} style={n.escalation ? { background: "color-mix(in srgb, var(--band-severe) 10%, transparent)" } : undefined}>
                  <td className="small">{new Date(n.created * 1000).toLocaleTimeString()}</td>
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
