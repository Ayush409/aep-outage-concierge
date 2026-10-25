import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useState } from "react";
import { BANDS, fmt } from "../api.js";
import { ErrorBox, Loading, useFetch } from "../components/ui.jsx";

const NAMES = { feb_2025_wind: "Feb 2025 wind phase", helene_2024: "Hurricane Helene" };
const HAZARD = { ice: "Ice (Feb 2025 freezing rain)", wind: "Wind (Feb 2025 wind phase)",
  tropical: "Rain + wind (Hurricane Helene)" };

export default function ModelAudit() {
  const modelFetch = useFetch("/api/aep/model");
  const m = modelFetch.data;
  const [tab, setTab] = useState("validation");
  const [query, setQuery] = useState("");
  const auditFetch = useFetch(tab === "audit" ? "/api/aep/audit" : null, [tab]);
  const audit = auditFetch.data;
  if (modelFetch.error) return <div className="page"><ErrorBox error={modelFetch.error} /></div>;
  if (!m) return <div className="page"><Loading /></div>;
  return (
    <div className="page stack">
      <div className="operator-heading"><h1>Model & Audit</h1><p>Evidence first: understand performance, inspect assumptions, and trace operator activity.</p></div>
      <section className="card model-verdict"><h2>Experimental — probabilities are not validated</h2>
        <p>Two storm periods support this prototype. Damage reports and network topology provide a proxy for affected customers, not meter-confirmed outage records. Use these results for scenario planning and human review.</p>
      </section>
      <nav className="operator-sections" aria-label="Model and audit sections">
        {[["validation", "Validation & experiments"], ["drivers", "Data & assumptions"], ["audit", "Activity log"]].map(([id, label]) =>
          <button key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}
      </nav>
      {tab === "validation" && <>
      <section className="card stack">
        <h2>Does the model work? Hold-out tests</h2>
        <div className="small secondary">The live model is trained on <b>both</b> storms. Each test below hides one storm
          (or phase), trains on the rest, and predicts what it hid - the honest way to see how it handles a storm it hasn't
          seen. With only one storm of each kind, these tests are hard: hiding one leaves the model no example of that
          hazard.</div>
        <div className="grid cols-2">
          {Object.entries(m.validation).map(([k, v]) => <Holdout key={k} name={NAMES[k] || k} v={v} />)}
        </div>
      </section>
      {m.review && <section className="card stack"><h2>Can a simpler model improve the estimates?</h2>
        <p>Reproducible experiments on the same two hold-outs. Lower Brier scores mean lower probability error against the topology proxy. The constant baseline uses only training-event prevalence.</p>
        <div className="table-scroll"><table><thead><tr><th>Experiment</th><th>Held-out event</th><th>Damage predicted / recorded</th><th>Brier score ↓</th><th>Constant baseline ↓</th><th>Ranking AUC ↑</th></tr></thead>
          <tbody>{m.review.experiments.flatMap(e => Object.entries(e.validation).map(([key, v]) => <tr key={`${e.id}-${key}`}>
            <td>{e.label}</td><td>{NAMES[key] || key}</td><td>{fmt.n(v.predicted_damage)} / {fmt.n(v.actual_damage)}</td>
            <td>{v.brier.toFixed(3)}</td><td>{v.baseline_brier.toFixed(3)}</td><td>{v.premise_auc.toFixed(3)}</td>
          </tr>))}</tbody></table></div>
        <div className="privacy-note"><b>Decision: keep candidates in evaluation</b><p>{m.review.conclusion}</p></div>
        <details><summary>What must improve before deployment?</summary><ul>{m.review.next_steps.map(t => <li key={t}>{t}</li>)}</ul></details>
      </section>}
      <section className="card stack"><h2>How to read the evidence</h2><div className="grid cols-3">
        <div><h3>Counts</h3><p>Expected damage and affected-customer counts test event magnitude. A good ranking does not guarantee accurate totals.</p></div>
        <div><h3>Calibration</h3><p>A 60% prediction should correspond to roughly 60% affected over comparable independent events. These tests do not establish that behavior.</p></div>
        <div><h3>Ranking</h3><p>AUC measures separation of affected and unaffected premises. Around 0.5 is chance ordering; it does not measure probability accuracy.</p></div>
      </div><p className="small secondary">Nearby premises share protective devices and weather. Large customer counts are not large numbers of independent storm observations. These are retrospective event hold-outs, not a chronological future-event test.</p></section>
      </>}
      {tab === "drivers" && <>
      <div className="grid cols-2">
        <section className="card stack">
          <h2>What drives the prediction</h2>
          <div className="small muted">Poisson damage-rate model per ~2 km cell per day, pole count as exposure; every term
            constrained to only add risk. Trained {m.trained_on} on {fmt.n(m.damage_records)} AEP damage records.</div>
          <table><thead><tr><th>Factor</th><th className="num">Weight</th></tr></thead>
            <tbody>{m.features.filter((f) => f.coef > 0).sort((a, b) => b.coef - a.coef).map((f) => (
              <tr key={f.name}><td>{f.label}</td><td className="num">{f.coef.toFixed(2)}</td></tr>))}</tbody></table>
          <div className="small muted">Zero-weight factors (dropped by the data): {m.features.filter((f) => f.coef === 0)
            .map((f) => f.label).join(", ")}.</div>
        </section>
        <section className="card stack">
          <h2>Assumptions and limits</h2>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{m.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
          <div className="small"><b>Excluded:</b> {fmt.n(m.excluded_records?.january)} January damage records.</div>
          <div className="small"><b>Strongest weather in training:</b> gusts {fmt.n(m.train_range.gust_max)} mph, freezing rain
            {" "}{m.train_range.frz.toFixed(2)} in, low {fmt.n(m.train_range.tmin)} °F, high {fmt.n(m.train_range.tmax)} °F.
            Scenarios beyond this are flagged lower confidence.</div>
        </section>
      </div>
      <section className="card stack">
        <h2>What the damage reports taught us, by hazard</h2>
        <div className="small muted">Applied to the simulation's storm types: which equipment breaks, how often crews hit
          access problems (backyard poles, blocked roads), and how often special equipment is needed.</div>
        <table>
          <thead><tr><th>Hazard (training storm)</th><th className="num">Reports</th><th className="num">Access problems</th>
            <th className="num">Special equipment</th><th>Most damaged</th></tr></thead>
          <tbody>{Object.entries(m.hazard_behaviour || {}).map(([k, b]) => (
            <tr key={k}><td>{HAZARD[k] || k}</td><td className="num">{fmt.n(b.records)}</td>
              <td className="num">{Math.round(b.access_rate * 100)}%</td>
              <td className="num">{Math.round(b.special_equipment_rate * 100)}%</td>
              <td className="small">{Object.entries(b.mix).sort((x, y) => y[1] - x[1]).slice(0, 3)
                .map(([t, v]) => `${t} ${Math.round(v * 100)}%`).join(", ")}</td></tr>))}</tbody>
        </table>
        <table>
          <thead><tr><th>Simulation storm type</th><th>Uses what was learned from</th></tr></thead>
          <tbody>{(m.scenarios || []).map((s) => <tr key={s.name}><td>{s.name}</td><td className="small">{s.learned_from}</td></tr>)}</tbody>
        </table>
      </section>
      </>}
      {tab === "audit" && <>
      <section className="card stack">
        <h2>Audit log</h2>
        <p className="secondary">Most recent 200 recorded actions. This is an application activity log, not a complete security-monitoring system.</p>
        <label>Filter by user, action, or detail<input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search the loaded activity" /></label>
        {auditFetch.error ? <ErrorBox error={auditFetch.error} /> : !audit ? <Loading /> : (
          <div className="audit-table table-scroll">
            <table><thead><tr><th>When</th><th>User</th><th>Action</th><th>Detail</th></tr></thead>
              <tbody>{audit.filter(a => `${a.email} ${a.action} ${a.detail}`.toLowerCase().includes(query.toLowerCase())).map((a) => <tr key={a.id}><td className="small">{new Date(a.ts * 1000).toLocaleString()}</td>
                <td>{a.email || "-"}</td><td>{a.action}</td><td className="small">{a.detail ? <details><summary>View details</summary><pre className="audit-json">{a.detail}</pre></details> : "—"}</td></tr>)}</tbody></table>
            {!audit.some(a => `${a.email} ${a.action} ${a.detail}`.toLowerCase().includes(query.toLowerCase())) && <p>No matching activity.</p>}
          </div>
        )}
      </section>
      </>}
    </div>
  );
}

function Holdout({ name, v }) {
  const rows = BANDS.filter((b) => v.reliability[b]).map((b) => ({
    band: b, predicted: +(v.reliability[b].predicted * 100).toFixed(1), actual: +(v.reliability[b].actual * 100).toFixed(1),
    customers: v.reliability[b].customers,
  }));
  return (
    <div className="card stack" style={{ boxShadow: "none" }}>
      <b>Hold-out test: {name}</b>
      {v.label && <div className="small secondary">{v.label}.</div>}
      <table><tbody>
        <tr><td>Damage reports: predicted vs actual</td><td className="num">{fmt.n(v.predicted_damage)} vs {fmt.n(v.actual_damage)}</td></tr>
        <tr><td>Customers affected: predicted vs topology proxy</td><td className="num">{fmt.n(v.predicted_customers_out)} vs {fmt.n(v.actual_customers_out)}</td></tr>
        <tr><td>Area ranking correlation</td><td className="num">{v.cell_rank_corr}</td></tr>
        <tr><td>Home-level AUC (0.5 = coin flip)</td><td className="num">{v.premise_auc}</td></tr>
      </tbody></table>
      <p className="small secondary">Each pair compares the mean prediction with the damage-derived affected share within that band. Bands can contain very different customer counts.</p>
      <ResponsiveContainer width="100%" height={230}>
        <BarChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: 0 }} barGap={2}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="band" stroke="var(--text-muted)" fontSize={11} tickLine={false} axisLine={false} />
          <YAxis domain={[0, 100]} unit="%" stroke="var(--text-muted)" fontSize={13} tickLine={false} axisLine={false} width={48} />
          <Tooltip contentStyle={{ background: "var(--surface-2)", border: "1px solid var(--border)", fontSize: 12 }}
            formatter={(val, k) => [`${val}%`, k === "predicted" ? "Predicted" : "Damage-derived proxy"]} />
          <Legend wrapperStyle={{ fontSize: 13 }} formatter={(k) => (k === "predicted" ? "Predicted" : "Damage-derived proxy")} />
          <Bar dataKey="predicted" fill="var(--series-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="actual" fill="var(--series-2)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
      <details><summary>Band counts and exact displayed percentages</summary><table><thead><tr><th>Band</th><th>Customers</th><th>Predicted</th><th>Proxy</th></tr></thead>
        <tbody>{rows.map(r => <tr key={r.band}><td>{r.band}</td><td>{fmt.n(r.customers)}</td><td>{r.predicted}%</td><td>{r.actual}%</td></tr>)}</tbody></table></details>
    </div>
  );
}
