import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useApp } from "../App.jsx";

export default function PreparationChecklist({ status, compact = false }) {
  const { scenario } = useApp();
  const [tasks, setTasks] = useState(status.checklist || []);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => setTasks(status.checklist || []), [status]);
  const priorities = tasks.filter((t) => t.group !== "if_out").slice(0, 3);
  const rest = tasks.filter((t) => !priorities.some((p) => p.key === t.key));
  async function toggle(task) {
    setBusy(task.key); setError("");
    try {
      await api("/api/me/checklist", { method: "PUT", body: { scenario, task_key: task.key, done: !task.done } });
      setTasks((old) => old.map((t) => t.key === task.key ? { ...t, done: !t.done } : t));
    } catch (e) { setError(e.message); }
    finally { setBusy(null); }
  }
  const list = (items) => <ul className="prep-checklist">{items.map((t) => <li key={t.key}>
    <label className="check"><input type="checkbox" checked={t.done} disabled={!!busy} onChange={() => toggle(t)} />
      <span>{t.text}{t.group === "your_needs" && <span className="tag">Your declared needs</span>}</span></label>
  </li>)}</ul>;
  return <div className="stack">
    <div className="row spread"><h3>Your next actions</h3><span className="tag" role="status">{priorities.filter((t) => t.done).length} of {priorities.length} priorities completed</span></div>
    <p className="secondary small">Start here. Completing tasks records your preparation; it is not a safety rating.</p>
    {list(priorities)}
    {!compact && rest.length > 0 && <details><summary>More preparation and during-outage steps ({rest.length})</summary>{list(rest)}</details>}
    <div className="row prep-links">
      {compact && <Link to="/alerts">Open the full preparation checklist</Link>}
      <Link to="/ready">Save an outage-ready plan</Link>
    </div>
    {error && <div role="alert" className="error">{error}</div>}
  </div>;
}
