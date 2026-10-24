import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { Loading } from "../components/ui.jsx";

const NEEDS = {
  medical_device: "Powered medical equipment", mobility: "Limited mobility",
  hearing_vision: "Deaf / hard of hearing / blind / low vision", critical_facility: "Critical facility",
};

export default function MyData() {
  const { refresh } = useApp();
  const nav = useNavigate();
  const [p, setP] = useState(null);
  const [phone, setPhone] = useState("");
  const [saved, setSaved] = useState("");
  useEffect(() => { api("/api/me/profile").then((d) => { setP(d); setPhone(d.phone || ""); }); }, []);
  if (!p) return <div className="page"><Loading /></div>;

  async function save(body) {
    const d = await api("/api/me/profile", { method: "PUT", body });
    setP(d);
    setSaved("Saved");
    setTimeout(() => setSaved(""), 1500);
  }
  async function del() {
    if (!window.confirm("Delete your account and all stored data? This can't be undone.")) return;
    await api("/api/me", { method: "DELETE" });
    await refresh();
    nav("/login");
  }

  return (
    <div className="page">
      <div className="grid cols-2">
        <section className="card stack">
          <h2>Your information</h2>
          <table><tbody>
            <tr><th>Name</th><td>{p.name}</td></tr>
            <tr><th>Email</th><td>{p.email}</td></tr>
            <tr><th>Address</th><td>{p.address} <span className="tag">encrypted</span></td></tr>
            <tr><th>ZIP</th><td>{p.zip} <span className="tag">encrypted</span></td></tr>
          </tbody></table>
          <label className="field"><span>Mobile number <span className="tag">encrypted</span></span>
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} type="tel" />
              <button onClick={() => save({ phone })}>Save</button>
            </div>
          </label>
          <div>
            <div className="small" style={{ fontWeight: 600 }}>Needs you've told us about <span className="tag">encrypted</span></div>
            {Object.entries(NEEDS).map(([k, l]) => (
              <label key={k} className="check"><input type="checkbox" checked={p.needs.includes(k)}
                onChange={(e) => save({ needs: e.target.checked ? [...p.needs, k] : p.needs.filter((n) => n !== k) })} />
                <span>{l}</span></label>
            ))}
          </div>
          {saved && <div role="status" className="small">{saved}</div>}
        </section>
        <section className="card stack">
          <h2>How we protect it</h2>
          <div><b>Encrypted before storage:</b> {p.stored.encrypted.join(", ")}.</div>
          <div><b>Stored as-is:</b> {p.stored.plain.join(", ")}. Passwords are stored only as a one-way hash.</div>
          <div><b>Never sent to the AI assistant:</b> {p.stored.never_shared_with_ai.join(", ")}. The assistant only sees
            your risk band, estimate numbers and the needs you chose to share.</div>
          <div><b>On maps:</b> other customers see outages by area (5+ customers), never your home.</div>
          <hr />
          <div className="row">
            <a href="/api/me/export"><button>Download my data</button></a>
            <button onClick={del} style={{ color: "var(--band-severe)" }}>Delete my account</button>
          </div>
        </section>
      </div>
    </div>
  );
}
