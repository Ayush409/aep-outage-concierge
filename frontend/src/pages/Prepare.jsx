import { qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Band, ErrorBox, Kind, Loading, useFetch } from "../components/ui.jsx";

export default function Prepare() {
  const { scenario } = useApp();
  const { data: d, error } = useFetch(`/api/me/prepare${qs({ scenario })}`, [scenario]);
  if (error) return <div className="page"><ErrorBox error={error} /></div>;
  if (!d) return <div className="page"><Loading what="Tailoring your preparation plan" /></div>;
  const { plan } = d;
  const calm = d.band === "Low";
  return (
    <div className="page stack">
      <section className="card stack">
        <div className="row spread">
          <div className="row"><Band band={d.band} big /><h2 style={{ margin: 0 }}>{plan.headline}</h2></div>
          <Kind kind="action" />
        </div>
        <div className="secondary">{plan.intro}</div>
      </section>
      <div className={calm ? "grid" : "grid cols-3"} style={calm ? { maxWidth: 640 } : undefined}>
        {plan.sections.map((sec) => (
          <section key={sec.title} className="card stack">
            <h3>{sec.title}</h3>
            <ul style={{ margin: 0, paddingLeft: 18 }} className="stack">{sec.items.map((t) => <li key={t}>{t}</li>)}</ul>
          </section>
        ))}
      </div>
      <div className="emergency" role="alert" style={calm ? { fontWeight: 500 } : undefined}>
        <span aria-hidden="true">⚠</span><span>{d.emergency[0]}</span>
      </div>
      <div className="small muted">
        {plan.source === "claude" ? "Tailored by Claude to your risk band from AEP's approved safety tips. " : ""}
        Based on {d.scenario === "Live forecast (next 7 days)" ? "the live 7-day forecast" : `the ${d.scenario} simulation`},
        your risk band and the needs you chose to share. We never guess medical or personal details.
      </div>
    </div>
  );
}
