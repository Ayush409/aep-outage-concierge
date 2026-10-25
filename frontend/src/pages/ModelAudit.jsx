import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BANDS, fmt } from "../api.js";
import { Loading, useFetch } from "../components/ui.jsx";

const NAMES = { feb_2025_wind: "Feb 2025 wind phase", helene_2024: "Hurricane Helene" };
const HAZARD = { ice: "Ice (Feb 2025 freezing rain)", wind: "Wind (Feb 2025 wind phase)",
  tropical: "Rain + wind (Hurricane Helene)" };

export default function ModelAudit() {
  const m = useFetch("/api/aep/model").data;
  const audit = useFetch("/api/aep/audit").data;
  if (!m) return <div className="page"><Loading /></div>;
  return (
    <div className="page stack">
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
      <section className="card stack">
        <h2>Audit log</h2>
        {!audit ? <Loading /> : (
          <div style={{ maxHeight: 300, overflow: "auto" }}>
            <table><thead><tr><th>When</th><th>User</th><th>Action</th><th>Detail</th></tr></thead>
              <tbody>{audit.map((a) => <tr key={a.id}><td className="small">{new Date(a.ts * 1000).toLocaleString()}</td>
                <td>{a.email || "-"}</td><td>{a.action}</td><td className="small">{a.detail}</td></tr>)}</tbody></table>
          </div>
        )}
      </section>
    </div>
  );
}

function Holdout({ name, v }) {
  const rows = BANDS.filter((b) => v.reliability[b]).map((b) => ({
    band: b, predicted: Math.round(v.reliability[b].predicted * 100), actual: Math.round(v.reliability[b].actual * 100),
    customers: v.reliability[b].customers,
  }));
  return (
    <div className="card stack" style={{ boxShadow: "none" }}>
      <b>Hold-out test: {name}</b>
      {v.label && <div className="small secondary">{v.label}.</div>}
      <table><tbody>
        <tr><td>Damage reports: predicted vs actual</td><td className="num">{fmt.n(v.predicted_damage)} vs {fmt.n(v.actual_damage)}</td></tr>
        <tr><td>Customers out: predicted vs behind real damage</td><td className="num">{fmt.n(v.predicted_customers_out)} vs {fmt.n(v.actual_customers_out)}</td></tr>
        <tr><td>Area ranking correlation</td><td className="num">{v.cell_rank_corr}</td></tr>
        <tr><td>Home-level AUC (0.5 = coin flip)</td><td className="num">{v.premise_auc}</td></tr>
      </tbody></table>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: 0 }} barGap={2}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="band" stroke="var(--text-muted)" fontSize={11} tickLine={false} axisLine={false} />
          <YAxis unit="%" stroke="var(--text-muted)" fontSize={11} tickLine={false} axisLine={false} width={40} />
          <Tooltip contentStyle={{ background: "var(--surface-2)", border: "1px solid var(--border)", fontSize: 12 }}
            formatter={(val, k) => [`${val}%`, k === "predicted" ? "Predicted" : "Actually lost power"]} />
          <Legend wrapperStyle={{ fontSize: 12 }} formatter={(k) => (k === "predicted" ? "Predicted" : "Actually lost power")} />
          <Bar dataKey="predicted" fill="var(--series-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="actual" fill="var(--series-2)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
