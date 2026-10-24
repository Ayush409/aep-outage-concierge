import { useState } from "react";
import { fmt, hourLabel, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Loading, Stat, useFetch } from "../components/ui.jsx";

const TYPE = { pole: "Pole", primary: "Primary wire", secondary: "Secondary wire", fuse: "Fuse / cutout",
  transformer: "Transformer", recloser: "Recloser", switch: "Switch" };

export default function Restoration() {
  const { scenario } = useApp();
  const q = scenario ? qs({ scenario }) : null;
  const jobs = useFetch(q && `/api/aep/jobs${q}`, [q]).data;
  const ov = useFetch(q && `/api/sim/overview${q}`, [q]).data;
  const [sel, setSel] = useState(null);
  const [filter, setFilter] = useState("all");
  const detail = useFetch(sel != null ? `/api/aep/jobs/${sel}${q}` : null, [sel, q]).data;

  if (!jobs || !ov) return <div className="page"><Loading what="Planning restoration" /></div>;
  const shown = jobs.filter((j) => filter === "all" || j.type === filter);
  const types = [...new Set(jobs.map((j) => j.type))];
  const s = ov.summary;

  return (
    <div className="page stack">
      <div className="grid cols-4">
        <Stat label="Repair jobs" value={fmt.n(s.jobs.p50)} />
        <Stat label="Person-hours (incl. ILM 4.5)" value={fmt.n(s.person_hours.p50)} />
        <Stat label="90% of customers restored" value={hourLabel(ov.start, s.hours_to_90pct.p50)}
          sub={`P10 ${hourLabel(ov.start, s.hours_to_90pct.p10)} - P90 ${hourLabel(ov.start, s.hours_to_90pct.p90)}`} />
        <Stat label="Last customer restored" value={hourLabel(ov.start, s.hours_to_all.p50)} />
      </div>
      <div className="sidebar-layout" style={{ gridTemplateColumns: "1fr minmax(320px, 460px)" }}>
        <section className="card stack" style={{ minWidth: 0 }}>
          <div className="row spread">
            <h2>Job order (median run)</h2>
            <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: "auto" }}>
              <option value="all">All damage types</option>
              {types.map((t) => <option key={t} value={t}>{TYPE[t] || t}</option>)}
            </select>
          </div>
          <div className="small muted">Crews take the job that restores the most customers per crew-hour first;
            life-support customers and hospital circuits get priority. Work pauses when gusts reach 30 mph.</div>
          <div style={{ maxHeight: 520, overflow: "auto" }}>
            <table>
              <thead><tr><th>Start</th><th>Damage</th><th className="num">Customers behind</th>
                <th className="num">Person-h</th><th>Flags</th><th>Done</th></tr></thead>
              <tbody>{shown.map((j) => (
                <tr key={j.job} className="click" onClick={() => setSel(j.job)}
                  style={sel === j.job ? { outline: "2px solid var(--accent)" } : undefined}>
                  <td className="small">{hourLabel(ov.start, j.start)}</td>
                  <td>{TYPE[j.type] || j.type}{j.drawing ? <span className="muted small"> - drawing {j.drawing}</span> : ""}</td>
                  <td className="num">{fmt.n(j.customers_behind)}{j.life_support_behind ? " ♥" : ""}</td>
                  <td className="num">{j.person_hours}</td>
                  <td className="small">{[j.access_issue && "access", j.special_equipment && "special equip."].filter(Boolean).join(", ")}</td>
                  <td className="small">{hourLabel(ov.start, j.finish)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="small muted">♥ = life-support premise behind this device. Showing the first {jobs.length} jobs.</div>
        </section>
        <section className="card stack" style={{ position: "sticky", top: 0 }}>
          <h2>Repair detail</h2>
          {sel == null ? <div className="muted">Select a job to see the structure, parts and hours.</div> :
            !detail ? <Loading /> : <JobDetail d={detail} start={ov.start} />}
        </section>
      </div>
    </div>
  );
}

function JobDetail({ d, start }) {
  const k = d.kit;
  return (
    <div className="stack">
      <div>
        <b>{TYPE[k.asset_type] || k.asset_type}</b>
        {k.drawing_title && <span className="secondary"> - {k.drawing_title}</span>}
      </div>
      <div className="small secondary">
        {d.asset.height_ft ? `${d.asset.height_ft} ft ${d.asset.material || ""} pole` : ""}
        {d.asset.install_year ? `, installed ${d.asset.install_year}` : ""}
        {d.asset.phases ? `, ${d.asset.phases}-phase` : ""}
        {d.asset.xfmr_kva || d.asset.kva ? `, ${d.asset.xfmr_kva || d.asset.kva} kVA transformer` : ""}
      </div>
      {k.drawing_page && (
        <img src={`/api/aep/drawing/${k.drawing_page}`} alt={`AEP structure drawing: ${k.drawing_title}`}
          style={{ width: "100%", borderRadius: 8, border: "1px solid var(--border)", background: "#fff" }} />
      )}
      <table>
        <thead><tr><th>Part replaced</th><th className="num">Qty</th><th className="num">Hours</th></tr></thead>
        <tbody>
          {k.lines.map((l, i) => (
            <tr key={i}><td>{l.part}{l.assumed && <span className="tag" style={{ marginLeft: 6 }}>assumption</span>}
              {l.note && <div className="small muted">{l.note}</div>}</td>
              <td className="num">{l.qty}</td><td className="num">{l.hours.toFixed(2)}</td></tr>
          ))}
          {k.adders.map((a) => (
            <tr key={a.name}><td>{a.name} <span className="tag">adder</span></td><td /><td className="num">{a.hours.toFixed(2)}</td></tr>
          ))}
          <tr><td><b>Direct labor (AEP workbook)</b></td><td /><td className="num"><b>{k.direct_hours}</b></td></tr>
          <tr><td>x Indirect labor multiplier (drive, safety, setup)</td><td /><td className="num">x {k.ilm}</td></tr>
          <tr><td><b>Person-hours</b></td><td /><td className="num"><b>{k.person_hours}</b></td></tr>
          <tr><td>Crew-hours (4-person crew, with this run's variation)</td><td /><td className="num">{d.crew_hours}</td></tr>
        </tbody>
      </table>
      <div className="small">Scheduled {hourLabel(start, d.start)} - done {hourLabel(start, d.finish)}</div>
      {k.shared_pole && <div className="small secondary">Shared pole: the telephone/cable company must move its lines
        after the new pole is set. That doesn't delay power, but extends the job.</div>}
    </div>
  );
}
