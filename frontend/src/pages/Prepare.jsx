import { qs } from "../api.js";
import { useApp } from "../App.jsx";
import { ErrorBox, Loading, useFetch } from "../components/ui.jsx";
import PreparationChecklist from "../components/PreparationChecklist.jsx";

export default function Prepare({ embedded = false, status }) {
  const { customerParams, customerRevision, journey } = useApp();
  const fetched = useFetch(!status && journey ? `/api/me/status${qs(customerParams)}` : null,
    [customerParams.scenario, customerParams.access_mult, customerRevision]);
  const s = status || fetched.data;
  if (fetched.error) return <ErrorBox error={fetched.error} />;
  if (!s) return <Loading what="Loading your preparation plan" />;
  return <div className={embedded ? "stack" : "page stack customer-readable"}>
    <PreparationChecklist status={s} />
    <div className="emergency"><span>{s.preparation.emergency[0]}</span></div>
    <p className="small secondary">Based on the modeled storm conditions and the needs you chose to share.</p>
  </div>;
}
