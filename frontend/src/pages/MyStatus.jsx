import { Link } from "react-router-dom";
import { BAND_COLOR, fmt, hourLabel, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Band, Confidence, ErrorBox, Kind, Loading, Ring, useFetch } from "../components/ui.jsx";

export default function MyStatus() {
  const { scenario } = useApp();
  const { data: s, error, loading } = useFetch(scenario ? `/api/me/status${qs({ scenario })}` : null, [scenario]);
  if (error) return <div className="page"><ErrorBox error={error} /></div>;
  if (loading || !s) return <div className="page"><Loading what="Checking your line" /></div>;

  const est = s.restoration;
  const sim = s.scenario.kind !== "live";
  const ev = s.event;
  const low = s.confidence.level === "Low";
  const msgs = s.communications.messages;
  const stages = [
    ["Before the storm", "pre_storm", true],
    ["Outage confirmed", "outage_confirmed", !!est],
    ["Estimate updated", "estimate_updated", !!est],
    ["Power restored", "restored", !!est],
  ];

  return (
    <div className="page">
      <div className="grid cols-2">
        <section className="card stack" aria-labelledby="risk-h">
          <div className="row spread">
            <h2 id="risk-h">{sim ? `Your power during the simulated ${s.scenario.name.toLowerCase()}` : "Your power outlook - next 7 days"}</h2>
            <Kind kind="estimate" />
          </div>
          <div className="row" style={{ gap: 20, flexWrap: "nowrap", alignItems: "center" }}>
            <Ring value={ev.area_share} color={BAND_COLOR[s.risk.band]} caption={`of ${ev.area}`} />
            <div className="stack" style={{ gap: 6 }}>
              <div className="row"><span className="small secondary">Your risk band</span><Band band={s.risk.band} big /></div>
              <div><b>{fmt.pct(ev.area_share)}</b> of homes in {ev.area} {sim ? "lose" : "could lose"} power
                {sim ? " in this storm." : " in the next 7 days."}</div>
              <div className="small secondary">Your home lost power in <b>{Math.round(ev.home_share * ev.runs)}</b> of{" "}
                {ev.runs} simulated runs ({fmt.pct(ev.home_share)}).</div>
            </div>
          </div>
          {sim && (ev.timeline ? <PowerTimeline t={ev.timeline} start={s.start} /> : (
            <div className="card" style={{ boxShadow: "none" }}>Your home kept power in every simulated run of this storm.</div>
          ))}
          <div className="secondary">{s.communications.explanation}</div>
          <div>
            <div className="small" style={{ fontWeight: 600 }}>Main reasons</div>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {s.factors_plain.map((f) => <li key={f}>{f}</li>)}
            </ul>
          </div>
          <div className="small muted">Peak conditions near you: gusts {fmt.n(s.risk.weather.peak_gust)} mph
            {s.risk.weather.ice_in > 0.05 ? `, ice ${s.risk.weather.ice_in} in` : ""}
            , temperatures {fmt.n(s.risk.weather.tmin)}-{fmt.n(s.risk.weather.tmax)} °F</div>
          <Confidence c={s.confidence} />
          {low && <div className="emergency" style={{ borderColor: "var(--band-high)" }}>
            We can't make a reliable prediction for this kind of storm. Treat this as a rough guide, follow the
            preparation steps, and watch for confirmed updates from AEP.</div>}
        </section>

        <section className="card stack" aria-labelledby="rest-h">
          <div className="row spread"><h2 id="rest-h">How long could restoration take?</h2><Kind kind="estimate" /></div>
          {est ? (
            <>
              <div className="stat"><div className="v">{fmt.hours(est.p10)} - {fmt.hours(est.p90)}</div>
                <div className="l">likely range if your power goes out (most likely about {fmt.hours(est.p50)})</div></div>
              <div><b>Likely cause:</b> {s.cause_plain || "Not identified yet - AEP crews are still assessing damage."}</div>
              {s.delay_reason && <div><b>What could make it longer:</b> {s.delay_reason}; access problems
                (backyard poles, blocked roads) and extra damage found on site.</div>}
              <div className="small muted">Simulated outage window: {hourLabel(s.start, est.outage_start)} to about{" "}
                {hourLabel(s.start, est.restored)}. This is a model estimate, not confirmed AEP restoration information.</div>
            </>
          ) : (
            <div className="secondary">In most simulated runs your line stays on, so there's no restoration estimate.
              If your power does go out, report it and we'll estimate once crews assess the damage.</div>
          )}
          <hr />
          <div className="row spread"><b>Confirmed by AEP</b><Kind kind="confirmed" /></div>
          <div className="small secondary">{s.scenario.kind === "replay"
            ? "Damage locations in this replay are AEP's real damage reports. Restoration times are simulated."
            : "No confirmed outage information for this scenario - it is a simulation."}</div>
        </section>
      </div>

      <section className="card stack" style={{ marginTop: 16 }} aria-labelledby="tl-h">
        <div className="row spread"><h2 id="tl-h">Your storm timeline and messages</h2>
          <span className="small muted">{s.communications.source === "claude" ? "Written by Claude from model facts" :
            "Standard message templates"}</span></div>
        <div className="timeline">
          {stages.map(([title, key, on]) => (
            <div key={key} className={`step${on ? " done" : ""}`}>
              <div style={{ fontWeight: 600 }}>{title}</div>
              <div className="small secondary" style={{ marginTop: 4 }}>{on ? msgs[key] : "Not expected in this scenario."}</div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid cols-3" style={{ marginTop: 16 }}>
        <section className="card stack">
          <div className="row spread"><h3>Alerts</h3><Kind kind="confirmed" /></div>
          <div>{s.alerts.reason}</div>
          {s.alerts.eligible && <div className="small">Channels: {s.alerts.channels.join(", ") || "none selected"}</div>}
          <Link to="/alerts">Manage alerts</Link>
        </section>
        <section className="card stack">
          <div className="row spread"><h3>What you should do</h3><Kind kind="action" /></div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>{s.preparation.now.slice(0, 3).map((t) => <li key={t}>{t}</li>)}</ul>
          <Link to="/prepare">See all preparation steps</Link>
        </section>
        <section className="card stack">
          <h3>Your service</h3>
          <div><b>{s.address || `${s.premise.city}, VA ${s.premise.zip}`}</b></div>
          {s.premise.life_support && <div className="small">AEP has a life-support record for this address.</div>}
          <div className="small muted">We show your own address only. Outages elsewhere are shown by area.</div>
        </section>
      </div>
    </div>
  );
}


/** A typical simulated run for this home: storm hits -> power lost -> outage confirmed -> restored. */
function PowerTimeline({ t, start }) {
  const steps = [
    ["Storm damage begins nearby", t.storm_hits, "var(--band-elevated)"],
    ["Your power goes out", t.power_lost, "var(--band-severe)"],
    ["AEP confirms your outage", t.confirmed, "var(--accent)", "You get an \"Outage confirmed\" alert with an estimate"],
    t.estimate_updated != null && ["Estimate updated", t.estimate_updated, "var(--accent)", "Crews have assessed the damage"],
    ["Power restored", t.restored, "var(--band-low)", `Out for about ${fmt.hours(t.hours_out)}`],
  ].filter(Boolean);
  return (
    <div className="stack" style={{ gap: 0 }}>
      <div className="small muted" style={{ marginBottom: 6 }}>A typical simulated run for your home</div>
      <ol className="power-timeline">
        {steps.map(([label, h, color, note], i) => (
          <li key={label} style={{ animationDelay: `${0.1 + i * 0.12}s` }}>
            <span className="dot" style={{ background: color }} aria-hidden="true" />
            <div><b>{label}</b><div className="small secondary">{hourLabel(start, h)}{note ? ` - ${note}` : ""}</div></div>
          </li>
        ))}
      </ol>
    </div>
  );
}
