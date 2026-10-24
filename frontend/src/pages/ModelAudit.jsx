import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BANDS, fmt } from "../api.js";
import { Loading, useFetch } from "../components/ui.jsx";

const NAMES = { feb_2025: "Feb 2025 ice + wind storm", helene_2024: "Hurricane Helene" };

export default function ModelAudit() {
  const m = useFetch("/api/aep/model").data;
  const audit = useFetch("/api/aep/audit").data;
  if (!m) return <div className="page"><Loading /></div>;
  return (
    <div className="page stack">
      <section className="card stack">
        <h2>Does the model work? Hold-out tests</h2>
        <div className="small secondary">Each test trains on every other day and event, then predicts the held-out storm
          it has never seen. Bands should rank risk: the higher the band, the more customers actually lost power.</div>
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
            .map((f) => f.label).join(", ")}. Wind calibration factor: {m.wind_calibration}.</div>
        </section>
        <section className="card stack">
          <h2>Assumptions and limits</h2>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{m.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
          <div className="small"><b>Severe days with no damage records</b> (treated as unlabeled): {m.excluded_days.length}
            {" "}days, e.g. {m.excluded_days.slice(-4).join(", ")}.</div>
          <div className="small"><b>Strongest weather in training:</b> gusts {fmt.n(m.train_range.gust_max)} mph, freezing rain
            {" "}{m.train_range.frz.toFixed(2)} in, low {fmt.n(m.train_range.tmin)} °F, high {fmt.n(m.train_range.tmax)} °F.
            Scenarios beyond this are flagged lower confidence.</div>
        </section>
      </div>
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
      <b>{name} (never seen in training)</b>
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
