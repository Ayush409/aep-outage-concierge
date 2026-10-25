import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { ErrorBox, Loading, useFetch } from "../components/ui.jsx";

// What each declared need actually changes (kept in sync with backend guidance.py and alert rules)
const NEEDS = {
  medical_device: {
    label: "Someone uses powered medical equipment",
    does: ["Storm alerts start one risk band earlier for you",
      "AEP operators get an escalation if you're expected to lose power",
      "Preparation tips add battery backup and when to go to a hospital or shelter"],
  },
  mobility: {
    label: "Someone has limited mobility",
    does: ["Preparation tips add arranging help in case you need to leave home"],
  },
  hearing_vision: {
    label: "Someone is deaf, hard of hearing, blind or low-vision",
    does: ["Preparation tips remind you to keep text alerts on as well as in-app, so alerts aren't missed"],
  },
  critical_facility: {
    label: "This address is a care home, school or other critical facility",
    does: ["Shown to AEP operators in their customer list, so they know the address serves a facility"],
  },
};

export default function MyData() {
  const { refresh, scenario } = useApp();
  const nav = useNavigate();
  const [p, setP] = useState(null);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const status = useFetch(`/api/me/status${qs({ scenario })}`, [scenario, p?.phone_verified]).data;
  useEffect(() => { api("/api/me/profile").then((d) => { setP(d); setPhone(d.phone || ""); }); }, []);
  if (!p) return <div className="page"><Loading /></div>;

  async function run(fn, ok) {
    setErr("");
    try {
      await fn();
      if (ok) { setMsg(ok); setTimeout(() => setMsg(""), 2500); }
    } catch (e) {
      setErr(e.message);
    }
  }
  const save = (body, ok = "Saved") => run(async () => setP(await api("/api/me/profile", { method: "PUT", body })), ok);
  const savePhone = () => run(async () => {
    const d = await api("/api/me/profile", { method: "PUT", body: { phone } });
    setP(d);
    setPhone(d.phone || "");
    setCodeSent(null);
  }, "Number saved - now verify it");
  const sendCode = () => run(async () => setCodeSent(await api("/api/me/phone/send-code", { method: "POST" })));
  const verify = () => run(async () => {
    setP(await api("/api/me/phone/verify", { method: "POST", body: { code } }));
    setCodeSent(null);
    setCode("");
  }, "Phone verified");
  async function del() {
    if (!window.confirm("Delete your account and all stored data? This can't be undone.")) return;
    await api("/api/me", { method: "DELETE" });
    await refresh();
    nav("/login");
  }

  const phoneChanged = phone !== (p.phone || "");
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

          <div className="stack">
            <div className="small" style={{ fontWeight: 600 }}>Mobile number for text alerts <span className="tag">encrypted</span></div>
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} type="tel" placeholder="540-555-0100"
                aria-label="Mobile number" />
              <button onClick={savePhone} disabled={!phoneChanged}>Save</button>
            </div>
            {p.phone && !phoneChanged && (p.phone_verified ? (
              <div className="small" style={{ color: "var(--band-low)", fontWeight: 600 }}>✓ Verified - text alerts can reach this number</div>
            ) : (
              <div className="stack">
                <div className="small">Not verified yet. We'll text a 6-digit code to prove the number works and is yours.
                  Text alerts are only sent to verified numbers.</div>
                <div className="row">
                  <button className="primary" onClick={sendCode}>{codeSent ? "Send a new code" : "Text me a code"}</button>
                  {codeSent && <>
                    <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                      inputMode="numeric" placeholder="123456" style={{ width: 110 }} aria-label="Verification code" />
                    <button onClick={verify} disabled={code.length !== 6}>Verify</button>
                  </>}
                </div>
                {codeSent?.simulated && <div className="small muted">Demo mode: no SMS service is connected, so the text
                  was written to the <Link to="/dev/mailbox" target="_blank">dev mailbox</Link> instead.</div>}
              </div>
            ))}
          </div>
          <ErrorBox error={err} />
          {msg && <div role="status" className="small">{msg}</div>}
        </section>

        <section className="card stack">
          <h2>Alert preferences</h2>
          {status && <div className="small">{status.alerts.reason}</div>}
          <label className="check"><input type="checkbox" checked={p.alerts_inapp}
            onChange={(e) => save({ alerts_inapp: e.target.checked })} /><span>In-app alerts</span></label>
          <label className="check"><input type="checkbox" checked={p.alerts_sms} disabled={!p.phone_verified}
            onChange={(e) => save({ alerts_sms: e.target.checked })} />
            <span>Text message alerts {p.phone_verified ? `to ${p.phone}` : "(verify a mobile number first)"}</span></label>
          {status && <>
            <div className="small" style={{ fontWeight: 600 }}>When we'd message you</div>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{status.alerts.timing.map((t) => <li key={t}>{t}</li>)}</ul>
          </>}
        </section>

        <section className="card stack">
          <h2>Needs you've told us about <span className="tag">encrypted</span></h2>
          <div className="small secondary">Optional. Only what you choose here is used - we never guess health or personal
            details from other data. Here is exactly what each one changes:</div>
          {Object.entries(NEEDS).map(([k, n]) => (
            <div key={k}>
              <label className="check"><input type="checkbox" checked={p.needs.includes(k)}
                onChange={(e) => save({ needs: e.target.checked ? [...p.needs, k] : p.needs.filter((x) => x !== k) })} />
                <span><b>{n.label}</b></span></label>
              <ul className="small secondary" style={{ margin: "2px 0 0", paddingLeft: 42 }}>
                {n.does.map((d) => <li key={d}>{d}</li>)}</ul>
            </div>
          ))}
          <div className="small muted">It does not guarantee faster restoration. AEP's own life-support records are what
            crews prioritize. The AI assistant only sees the category (e.g. "medical equipment"), never details.</div>
        </section>

        <section className="card stack">
          <h2>How we protect your data</h2>
          <div><b>Encrypted before storage:</b> {p.stored.encrypted.join(", ")}.</div>
          <div><b>Stored as-is:</b> {p.stored.plain.join(", ")}. Passwords are stored only as a one-way hash.</div>
          <div><b>Never sent to the AI assistant:</b> {p.stored.never_shared_with_ai.join(", ")}.</div>
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
