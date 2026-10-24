import { fmt, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { CostBars, CrewCurve } from "../components/charts.jsx";
import { Loading, Stat, useFetch } from "../components/ui.jsx";

export default function Impact() {
  const { scenario } = useApp();
  const q = scenario ? qs({ scenario }) : null;
  const c = useFetch(q && `/api/aep/impact${q}`, [q]).data;
  const compare = useFetch("/api/aep/compare").data;
  const curve = useFetch(q && `/api/aep/crew-curve${q}`, [q]).data;

  return (
    <div className="page stack">
      {!c ? <Loading what="Costing the event" /> : (
        <>
          <div className="grid cols-4">
            <Stat label="Lost revenue (AEP)" value={fmt.usd(c.lost_revenue)} sub={`${fmt.n(c.kwh_not_served)} kWh not sold`} />
            <Stat label="Repair cost (AEP, midpoint)" value={fmt.usd(c.repair.total_mid)}
              sub={`materials ${fmt.usd(c.repair.materials_low)}-${fmt.usd(c.repair.materials_high)}`} />
            <Stat label="Cost to customers" value={fmt.usd(c.customer_cost)} sub="LBNL interruption cost" />
            <Stat label="Customer-hours without power" value={fmt.n(c.customer_hours)} />
          </div>
          <div className="grid cols-2">
            <section className="card stack">
              <h2>Repair cost breakdown</h2>
              <table><tbody>
                {[["Local crew labor", c.repair.labor_local], ["Mutual-aid labor", c.repair.labor_mutual_aid],
                  ["Mutual-aid lodging & meals", c.repair.lodging], ["Trucks & equipment", c.repair.equipment],
                  ["Materials (low)", c.repair.materials_low], ["Materials (high)", c.repair.materials_high]].map(([l, v]) => (
                  <tr key={l}><td>{l}</td><td className="num">{fmt.usd(v)}</td></tr>))}
                <tr><td>Crew operations</td><td className="num">{fmt.n(c.person_hours)} person-h / {fmt.n(c.crew_hours)} crew-h</td></tr>
              </tbody></table>
            </section>
            <section className="card stack">
              <h2>How each number is calculated</h2>
              {Object.entries(c.formulas).map(([k, f]) => (
                <div key={k} className="small"><b>{k.replace("_", " ")}:</b> {f}</div>))}
              <hr />
              <div className="small" style={{ fontWeight: 600 }}>Sources</div>
              {Object.values(c.sources).map((s) => (
                <div key={s.label} className="small">{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.label}</a> :
                  s.label}</div>))}
            </section>
          </div>
        </>
      )}
      <section className="card stack">
        <h2>The type of storm changes who pays</h2>
        <div className="small muted">Every scenario at default crews. Lost sales are small; repair and customer costs dominate.</div>
        {!compare ? <Loading what="Running every scenario" /> : <CostBars rows={compare} />}
      </section>
      <section className="card stack">
        <h2>How many crews? The cost trade-off</h2>
        <div className="small muted">More crews cost AEP more (overtime, mutual aid, standby) but cut customer-hours without
          power. The total is lowest in the middle.</div>
        {!curve ? <Loading what="Simulating crew levels" /> : <CrewCurve rows={curve.rows} />}
      </section>
    </div>
  );
}
