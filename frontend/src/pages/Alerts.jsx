import { useState } from "react";
import { api, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Loading, useFetch } from "../components/ui.jsx";

const KIND = { pre_storm: "Storm alert", outage_confirmed: "Outage confirmed", estimate_updated: "Estimate updated",
  restored: "Power restored" };

export default function Alerts() {
  const { scenario } = useApp();
  const status = useFetch(scenario ? `/api/me/status${qs({ scenario })}` : null, [scenario]).data;
  const [tick, setTick] = useState(0);
  const feed = useFetch("/api/me/alerts", [tick]).data;
  const prof = useFetch("/api/me/profile", [tick]).data;

  async function toggle(k, v) {
    await api("/api/me/profile", { method: "PUT", body: { [k]: v } });
    setTick(tick + 1);
  }

  return (
    <div className="page">
      <div className="grid cols-2">
        <section className="card stack">
          <h2>Do I qualify for outage alerts?</h2>
          {!status ? <Loading /> : (
            <>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{status.alerts.eligible ? "Yes" : "Not yet"}</div>
              <div>{status.alerts.reason}</div>
              <div className="small"><b>When we'd message you</b></div>
              <ul style={{ margin: 0, paddingLeft: 18 }} className="small">{status.alerts.timing.map((t) => <li key={t}>{t}</li>)}</ul>
            </>
          )}
          {prof && (
            <>
              <hr />
              <label className="check"><input type="checkbox" checked={prof.alerts_inapp}
                onChange={(e) => toggle("alerts_inapp", e.target.checked)} /><span>In-app alerts</span></label>
              <label className="check"><input type="checkbox" checked={prof.alerts_sms} disabled={!prof.phone}
                onChange={(e) => toggle("alerts_sms", e.target.checked)} />
                <span>Text messages {prof.phone ? `to ${prof.phone}` : "(add a mobile number in My Data)"}</span></label>
            </>
          )}
        </section>
        <section className="card stack">
          <h2>Message preview for this storm</h2>
          {!status ? <Loading /> : Object.entries(status.communications.messages).map(([k, m]) => (
            <div key={k} className="card" style={{ boxShadow: "none" }}>
              <div className="small" style={{ fontWeight: 600 }}>{KIND[k]}</div>
              <div className="small secondary">{m}</div>
            </div>
          ))}
        </section>
      </div>
      <section className="card stack" style={{ marginTop: 16 }}>
        <h2>Your notifications</h2>
        {!feed ? <Loading /> : feed.length === 0 ? (
          <div className="muted">No notifications yet. They appear when AEP sends alerts for an event.</div>
        ) : (
          <table>
            <thead><tr><th>When</th><th>Type</th><th>Channel</th><th>Message</th></tr></thead>
            <tbody>{feed.map((n) => (
              <tr key={n.id}><td className="small">{new Date(n.created * 1000).toLocaleString()}</td>
                <td>{KIND[n.kind] || n.title}</td><td className="small">{n.channel}</td><td>{n.body}</td></tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </div>
  );
}
