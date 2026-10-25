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
  const feed = useFetch("/api/aep/notifications", [tick]).data;
  const customers = useFetch("/api/aep/customers").data;
  useEffect(() => { api("/api/aep/settings").then(setSettings); }, []);

  async function save(body) {
    const s = await api("/api/aep/settings", { method: "PUT", body });
    setSettings(s);
  }
  async function send() {
    setBusy(true);
    try {
      setResult(await api(`/api/aep/alerts/send${qs({ scenario })}`, { method: "POST" }));
      setTick(tick + 1);
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
          <div className="small muted">Customers always see the live forecast. Storm drills send practice alerts so you
            can check wording, channels and escalations.</div>
          {result && <div className="small" role="status">Queued {result.messages} messages for {result.customers} customers;
            {" "}{result.escalations.length} escalation(s).</div>}
        </section>
        <section className="card stack">
          <h2>Escalation triggers</h2>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            <li>A customer with a declared medical need is expected to be out</li>
            <li>A hospital's circuit is out (restoration priority boost)</li>
            <li>Low-confidence prediction in a Severe area - verify with field reports</li>
            <li>Estimate slips by 2+ hours or 25% - customers get an "estimate updated" message</li>
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
