import { qs } from "../api.js";
import { useApp } from "../App.jsx";
import { Band, ErrorBox, Kind, Loading, useFetch } from "../components/ui.jsx";

export default function Prepare() {
  const { scenario } = useApp();
  const { data: s, error } = useFetch(scenario ? `/api/me/status${qs({ scenario })}` : null, [scenario]);
  if (error) return <div className="page"><ErrorBox error={error} /></div>;
  if (!s) return <div className="page"><Loading /></div>;
  const p = s.preparation;
  return (
    <div className="page stack">
      <div className="emergency" role="alert">
        <span aria-hidden="true">⚠</span><span>{p.emergency[0]}</span>
      </div>
      <div className="row"><span>Tailored for</span><Band band={s.risk.band} />
        <span className="muted small">{s.scenario.name}{s.restoration ? `, possible outage of ${s.restoration.label}` : ""}</span>
      </div>
      <div className="grid cols-3">
        <Section title="Do now" items={p.now} />
        <Section title="If your power goes out" items={p.if_out} />
        {p.your_needs.length > 0 && <Section title="For the needs you told us about" items={p.your_needs} />}
      </div>
      <div className="small muted">Advice is based on your risk band, the expected outage length and the needs you chose to
        share in My Data. We never guess medical or personal details.</div>
    </div>
  );
}

function Section({ title, items }) {
  return (
    <section className="card stack">
      <div className="row spread"><h3>{title}</h3><Kind kind="action" /></div>
      <ul style={{ margin: 0, paddingLeft: 18 }} className="stack">{items.map((t) => <li key={t}>{t}</li>)}</ul>
    </section>
  );
}
