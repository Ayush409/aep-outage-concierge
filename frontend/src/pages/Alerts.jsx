import { Link } from "react-router-dom";
import { fmt, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Band, ErrorBox, Kind, Loading, useFetch } from "../components/ui.jsx";
import Prepare from "./Prepare.jsx";
import RestorationSummary from "../components/RestorationSummary.jsx";
import { powerState } from "../components/powerState.js";

const KIND = { pre_storm: "Storm alert", outage_confirmed: "Outage confirmed", estimate_updated: "Estimate updated",
  restored: "Power restored" };
const STATUS_KINDS = ["outage_confirmed", "estimate_updated", "restored"];

export default function Alerts() {
  const { scenario, customerParams, customerRevision, journey, journeyError } = useApp();
  const st = useFetch(journey ? `/api/me/status${qs(customerParams)}` : null, [scenario, customerParams.access_mult, customerRevision]);
  const feed = useFetch("/api/me/alerts", [customerRevision]).data;
  const s = st.data;
  if (st.error || journeyError) return <div className="page"><ErrorBox error={st.error || journeyError} /></div>;
  if (!s || st.loading) return <div className="page"><Loading what="Checking your power" /></div>;

  const state = powerState(s);
  const simulated = s.scenario.kind !== "live";
  const msgs = s.communications.messages;
  // drills (practice alerts for a storm scenario) never count as this home's real status
  const statusFeed = (feed || []).filter((n) => (simulated || STATUS_KINDS.includes(n.kind)) && n.scenario === scenario);

  return (
    <div className="page stack customer-readable">
      <section className="card stack" aria-labelledby="pw-h">
        <div className="row spread"><h2 id="pw-h">{simulated ? "Your simulated power outlook" : "Your power outlook"}</h2><Kind kind="estimate" /></div>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <span aria-hidden="true" style={{ width: 14, height: 14, borderRadius: "50%", background: state.color,
            marginTop: 6, flex: "none" }} />
          <div className="stack" style={{ gap: 4 }}>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{state.title}</div>
            <div className="secondary">{state.detail}</div>
            <div className="row small"><span className="muted">{simulated ? "Risk in this simulation" : "Outage risk this week"}</span><Band band={s.risk.band} />
              <span className="muted">Confidence: {s.confidence.level}</span></div>
          </div>
        </div>
        <RestorationSummary status={s} />
        <div className="small muted">{simulated ? "Historical storm simulation; these are modeled dates, not current outage updates."
          : "Based on the live 7-day forecast. These estimates do not confirm an outage."}</div>
      </section>

      <div className="grid alerts-content-grid">
        <section className="card stack" aria-labelledby="os-h">
          <div className="row spread"><h2 id="os-h">{simulated ? "Practice messages delivered so far" : "Outage status updates"}</h2><Kind kind={simulated ? "estimate" : "confirmed"} /></div>
          {statusFeed.length ? statusFeed.slice(0, 6).map((n) => (
            <div key={n.id} className="card" style={{ boxShadow: "none" }}>
              <div className="row spread small"><b>{simulated ? n.title : KIND[n.kind]}</b>
                <span className="muted">{new Date(n.created * 1000).toLocaleString()} - {n.channel}</span></div>
              <div className="small secondary">{n.body}</div>
            </div>
          )) : (
            <div className="stack">
              <div className="secondary small">{simulated ? "Advance the storm journey in My Status to receive eligible practice messages one stage at a time."
                : "No outage updates yet. Preview the messages you may receive if your power goes out:"}</div>
              {!simulated && STATUS_KINDS.map((k) => (
                <div key={k} className="card" style={{ boxShadow: "none" }}>
                  <details>
                    <summary>{KIND[k]}</summary>
                    <div className="small secondary">{msgs[k]}</div>
                  </details>
                </div>
              ))}
            </div>
          )}
          <div className="privacy-note">
            <b>Keep your updates within reach</b>
            <p><Link to="/data">Choose how to receive alerts</Link>. Your notification history appears below.</p>
          </div>
        </section>

        <section className="card stack" aria-labelledby="ps-h">
          <div className="row spread"><h2 id="ps-h">Stay prepared and stay safe</h2><Kind kind="action" /></div>
          <Prepare embedded status={s} />
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
