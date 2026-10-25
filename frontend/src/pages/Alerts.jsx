import { Link } from "react-router-dom";
import { BAND_COLOR, fmt, hourLabel, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Band, ErrorBox, Kind, Loading, useFetch } from "../components/ui.jsx";

const KIND = { pre_storm: "Storm alert", outage_confirmed: "Outage confirmed", estimate_updated: "Estimate updated",
  restored: "Power restored" };
const STATUS_KINDS = ["outage_confirmed", "estimate_updated", "restored"];

/** Where this home stands right now on the forecast timeline. */
function powerState(s) {
  const nowH = (Date.now() - new Date(s.start).getTime()) / 3.6e6;
  const r = s.restoration;
  if (r && nowH >= r.outage_start && nowH < r.restored) {
    return { key: "out", title: "Power predicted out now", color: "var(--band-severe)",
      detail: `Estimated back around ${hourLabel(s.start, r.restored)} (${r.label}).` };
  }
  if (r && nowH < r.outage_start) {
    return { key: "risk", title: "Power on - outage possible", color: BAND_COLOR[s.risk.band],
      detail: `The forecast puts an outage at risk around ${hourLabel(s.start, r.outage_start)}. If it happens, ` +
        `restoration is ${r.label}.` };
  }
  if (r && nowH >= r.restored) {
    return { key: "restored", title: "Power restored", color: "var(--band-low)",
      detail: `The predicted outage ended around ${hourLabel(s.start, r.restored)}.` };
  }
  return { key: "on", title: "Power on", color: "var(--band-low)",
    detail: "No outage is expected at your home in the next 7 days." };
}

export default function Alerts() {
  const { scenario } = useApp();
  const st = useFetch(`/api/me/status${qs({ scenario })}`, [scenario]);
  const feed = useFetch("/api/me/alerts").data;
  const s = st.data;
  if (st.error) return <div className="page"><ErrorBox error={st.error} /></div>;
  if (!s) return <div className="page"><Loading what="Checking your power" /></div>;

  const state = powerState(s);
  const msgs = s.communications.messages;
  // drills (practice alerts for a storm scenario) never count as this home's real status
  const statusFeed = (feed || []).filter((n) => STATUS_KINDS.includes(n.kind) && n.scenario === "live");
  const p = s.preparation;

  return (
    <div className="page stack">
      <section className="card stack" aria-labelledby="pw-h">
        <div className="row spread"><h2 id="pw-h">Your power right now</h2><Kind kind="estimate" /></div>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <span aria-hidden="true" style={{ width: 14, height: 14, borderRadius: "50%", background: state.color,
            marginTop: 6, flex: "none" }} />
          <div className="stack" style={{ gap: 4 }}>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{state.title}</div>
            <div className="secondary">{state.detail}</div>
            <div className="row small"><span className="muted">Outage risk this week</span><Band band={s.risk.band} />
              <span className="muted">Confidence: {s.confidence.level}</span></div>
          </div>
        </div>
        <div className="small muted">Based on the live 7-day forecast. AEP will message you if an outage is confirmed.</div>
      </section>

      <div className="grid cols-2">
        <section className="card stack" aria-labelledby="os-h">
          <div className="row spread"><h2 id="os-h">Outage status updates</h2><Kind kind="confirmed" /></div>
          {statusFeed.length ? statusFeed.slice(0, 6).map((n) => (
            <div key={n.id} className="card" style={{ boxShadow: "none" }}>
              <div className="row spread small"><b>{KIND[n.kind]}</b>
                <span className="muted">{new Date(n.created * 1000).toLocaleString()} - {n.channel}</span></div>
              <div className="small secondary">{n.body}</div>
            </div>
          )) : (
            <div className="stack">
              <div className="secondary small">No outage updates yet. If your power goes out you'll get these, in this order:</div>
              {STATUS_KINDS.map((k) => (
                <div key={k} className="card" style={{ boxShadow: "none" }}>
                  <div className="small"><b>{KIND[k]}</b> <span className="muted">(example for this week's forecast)</span></div>
                  <div className="small secondary">{msgs[k]}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card stack" aria-labelledby="ps-h">
          <div className="row spread"><h2 id="ps-h">Stay prepared and stay safe</h2><Kind kind="action" /></div>
          <div className="emergency" role="alert"><span aria-hidden="true">⚠</span><span>{p.emergency[0]}</span></div>
          <div className="card" style={{ boxShadow: "none" }}>
            <div className="small"><b>{KIND.pre_storm}</b></div>
            <div className="small secondary">{msgs.pre_storm}</div>
          </div>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {[...p.now.slice(0, 3), ...p.if_out.slice(0, 2)].map((t) => <li key={t}>{t}</li>)}
          </ul>
          <Link to="/prepare" className="small">All preparation and safety steps</Link>
        </section>
      </div>

      <section className="card stack" aria-labelledby="hist-h">
        <h2 id="hist-h">Past notifications</h2>
        {!feed ? <Loading /> : feed.length === 0 ? (
          <div className="muted">No notifications yet. Manage how you're alerted in <Link to="/data">My Data & Privacy</Link>.</div>
        ) : (
          <table>
            <thead><tr><th>When</th><th>Type</th><th>Channel</th><th>Message</th></tr></thead>
            <tbody>{feed.map((n) => (
              <tr key={n.id}><td className="small">{new Date(n.created * 1000).toLocaleString()}</td>
                <td>{KIND[n.kind] || n.title}{n.scenario !== "live" && <span className="tag" style={{ marginLeft: 6 }}>Storm drill</span>}</td>
                <td className="small">{n.channel}</td><td className="small">{n.body}</td></tr>
            ))}</tbody>
          </table>
        )}
        <div className="small muted">{fmt.n(feed?.length || 0)} notification(s). Alert channels and phone verification are in{" "}
          <Link to="/data">My Data & Privacy</Link>.</div>
      </section>
    </div>
  );
}
