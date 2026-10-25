import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { OutageCurve } from "../components/charts.jsx";
import { fmt, hourLabel, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { ErrorBox, Loading, Stat, useFetch } from "../components/ui.jsx";

const TYPE = { pole: "Pole", primary: "Primary wire", secondary: "Secondary wire", fuse: "Fuse / cutout",
  transformer: "Transformer", recloser: "Recloser", switch: "Switch" };

export default function Restoration() {
  const { scenario } = useApp();
  const q = scenario ? qs({ scenario }) : null;
  const jobFetch = useFetch(q && `/api/aep/jobs${q}`, [q]);
  const overviewFetch = useFetch(q && `/api/sim/overview${q}`, [q]);
  const jobs = jobFetch.data;
  const ov = overviewFetch.data;
  const [sel, setSel] = useState(null);
  const [filter, setFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [asOf, setAsOf] = useState(null); // hours since ov.start; null = default (now for live, peak for a storm)
  const live = scenario === "live";
  const lastHour = Math.ceil(Math.max(0, ...(jobs || []).map((j) => j.finish))) + 1;
  const nowHour = ov ? (Date.now() - new Date(ov.start).getTime()) / 3.6e6 : 0;
  const peakHour = ov?.curve?.p50?.length ? ov.curve.hours[ov.curve.p50.indexOf(Math.max(...ov.curve.p50))] : 0;
  const t = asOf ?? (live ? nowHour : peakHour);
  const withStatus = (jobs || []).map((j) => ({ ...j, status: jobStatus(j, t) }));
  const counts = Object.fromEntries(STATUS.map(([k]) => [k, withStatus.filter((j) => j.status === k).length]));
  const shown = withStatus.filter((j) => (filter === "all" || j.type === filter)
    && (statusFilter === "all" || j.status === statusFilter));
  const selected = shown.find(j => j.job === sel) || shown[0];
  const detailFetch = useFetch(selected ? `/api/aep/jobs/${selected.job}${q}` : null, [selected?.job, q]);
  const detail = detailFetch.data;
  useEffect(() => { setSel(null); setFilter("all"); setStatusFilter("all"); setAsOf(null); }, [scenario]);

  if (jobFetch.error || overviewFetch.error) return <div className="page"><ErrorBox error={jobFetch.error || overviewFetch.error} /></div>;
  if (!jobs || !ov || jobFetch.loading || overviewFetch.loading) return <div className="page"><Loading what="Planning restoration" /></div>;
  const types = [...new Set(jobs.map((j) => j.type))];
  const s = ov.summary;

  return (
    <div className="page stack">
      <div className="operator-heading"><h1>Restoration Planner</h1><p>Turn modeled damage into a crew-ready review. Estimates are planning scenarios, not confirmed dispatch orders.</p></div>
      <div className="grid cols-4">
        <Stat label="Repair jobs" value={fmt.n(s.jobs.p50)} />
        <Stat label="Person-hours (incl. ILM 4.5)" value={fmt.n(s.person_hours.p50)} />
        <Stat label="90% of customers restored" value={hourLabel(ov.start, s.hours_to_90pct.p50)}
          sub={`P10 ${hourLabel(ov.start, s.hours_to_90pct.p10)} - P90 ${hourLabel(ov.start, s.hours_to_90pct.p90)}`} />
        <Stat label="Last customer restored" value={hourLabel(ov.start, s.hours_to_all.p50)}
          sub={`P10 ${hourLabel(ov.start, s.hours_to_all.p10)} - P90 ${hourLabel(ov.start, s.hours_to_all.p90)}`} />
      </div>
      <div className="grid planner-overview">
        <section className="card stack"><h2>Restoration trajectory</h2>
          <p className="small secondary">Customers without power over time. The shaded P10-P90 band shows variation across simulation runs; it is not a validated confidence interval.</p>
          <OutageCurve curve={ov.curve} start={ov.start} height={260} />
        </section>
        <section className="card stack"><h2>Constraints to review before dispatch</h2>
          <div className="planner-constraints">
            <div><b>{jobs.filter(j => j.access_issue).length}</b><span>Jobs with access issues</span></div>
            <div><b>{jobs.filter(j => j.special_equipment).length}</b><span>Special-equipment jobs</span></div>
            <div><b>{jobs.filter(j => j.life_support_behind > 0).length}</b><span>Jobs upstream of life-support premises</span></div>
          </div>
          <p className="small secondary">Counts cover the first {jobs.length} scheduled jobs in the representative run. Flags can overlap; downstream customers must not be summed across jobs.</p>
          <p><b>Crew assumptions:</b> {ov.params.crews} local crews + {ov.params.mutual_aid_crews} mutual-aid crews arriving on day {ov.params.mutual_aid_day}.</p>
          <p className="small">{ov.operations?.label || ov.operations?.mode || "Review weather holds, access, equipment and upstream dependencies before assigning work."}</p>
          <div className="row"><Link to="/simulation">Compare crew and access assumptions</Link><Link to="/impact">Review cost trade-offs</Link></div>
        </section>
      </div>
      <div className="sidebar-layout planner-layout">
        <section className="card stack" style={{ minWidth: 0 }}>
          <div className="row spread">
            <h2>Job order (median run)</h2>
            <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: "auto" }}
              aria-label="Damage type">
              <option value="all">All damage types</option>
              {types.map((t) => <option key={t} value={t}>{TYPE[t] || t}</option>)}
            </select>
          </div>
          <div className="stack" style={{ gap: 6 }}>
            <label className="small">
              <b>Status as of {new Date(new Date(ov.start).getTime() + t * 3.6e6).toLocaleString(undefined,
                { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" })}</b>
              {live && asOf == null && <span className="muted"> (now)</span>}
              <input type="range" min={0} max={Math.max(lastHour, Math.ceil(t) + 1)} step={1} value={Math.round(t)}
                onChange={(e) => setAsOf(+e.target.value)} aria-label="Status as of" style={{ width: "100%" }} />
            </label>
            <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
              <button className={`chip${statusFilter === "all" ? " active" : ""}`} onClick={() => setStatusFilter("all")}>
                All ({withStatus.length})</button>
              {STATUS.map(([k, label]) => (
                <button key={k} className={`chip job-status ${k}${statusFilter === k ? " active" : ""}`}
                  onClick={() => setStatusFilter(k)}>{label} ({counts[k]})</button>))}
              {(asOf != null) && <button className="chip" onClick={() => setAsOf(null)}>{live ? "Back to now" : "Back to peak"}</button>}
            </div>
          </div>
          <div className="small muted">Crews take the job that restores the most customers per crew-hour first;
            life-support customers and hospital circuits get priority. Work pauses when gusts reach 30 mph.</div>
          <div className="planner-job-table">
            <table>
              <thead><tr><th>Status</th><th>Start</th><th>Damage</th><th className="num">Customers behind</th>
                <th className="num">Person-h</th><th>Flags</th><th>Done</th></tr></thead>
              <tbody>{shown.map((j) => (
                <tr key={j.job} className="click" onClick={() => setSel(j.job)}
                  style={selected?.job === j.job ? { outline: "2px solid var(--accent)" } : undefined}>
                  <td><span className={`job-status ${j.status}`}>{STATUS_LABEL[j.status]}</span></td>
                  <td className="small">{hourLabel(ov.start, j.start)}</td>
                  <td><button className="job-select" aria-pressed={selected?.job === j.job} onClick={() => setSel(j.job)}>{TYPE[j.type] || j.type}</button>{j.drawing ? <span className="muted small"> - drawing {j.drawing}</span> : ""}</td>
                  <td className="num">{fmt.n(j.customers_behind)}{j.life_support_behind ? " ♥" : ""}</td>
                  <td className="num">{j.person_hours}</td>
                  <td className="small">{[j.access_issue && "access", j.special_equipment && "special equip."].filter(Boolean).join(", ")}</td>
                  <td className="small">{hourLabel(ov.start, j.finish)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="small muted">♥ = life-support premise behind this device. Done = repaired; In progress = crew
            on site; Needs repair = damage has happened, waiting for a crew; Upcoming = damage the model expects later.
            {" "}{jobs.length >= 3000 ? `Showing the first ${jobs.length} jobs.` : `${jobs.length} jobs in this run.`}</div>
        </section>
        <section className="card stack planner-detail">
          <h2>Repair detail</h2>
          {!selected ? <div className="muted">No scheduled jobs match this filter.</div> : <>
            <p><b>Job {selected.job + 1} · Crew {selected.crew + 1}</b> — {fmt.n(selected.customers_behind)} customers downstream.</p>
            <p className="small secondary">Downstream count is exposure, not the number guaranteed to regain power from this repair. Other damaged upstream devices may still block service.</p>
            {detailFetch.error ? <ErrorBox error={detailFetch.error} /> : !detail || detailFetch.loading ? <Loading /> : <JobDetail d={detail} start={ov.start} />}
          </>}
        </section>
      </div>
    </div>
  );
}

const STATUS = [["done", "Done"], ["in_progress", "In progress"], ["needs_repair", "Needs repair"],
  ["upcoming", "Upcoming"]];
const STATUS_LABEL = Object.fromEntries(STATUS);

/** Where a job stands at hour t (hours since the window start). */
function jobStatus(j, t) {
  if (j.finish <= t) return "done";
  if (j.start <= t) return "in_progress";
  if (j.damaged_at <= t) return "needs_repair";
  return "upcoming";
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
