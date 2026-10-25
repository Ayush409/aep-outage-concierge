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
  const { refresh, scenario, customerParams, customerRevision } = useApp();
  const nav = useNavigate();
  const [p, setP] = useState(null);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const status = useFetch(`/api/me/status${qs(customerParams)}`, [scenario, customerParams.access_mult, customerRevision, p?.phone_verified]).data;
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
    if (!window.confirm("Delete your account, profile, and linked notifications? Audit records and demo mailbox entries may remain. This can't be undone.")) return;
    await api("/api/me", { method: "DELETE" });
    await refresh();
    nav("/login");
  }

  const phoneChanged = phone !== (p.phone || "");
  return (
    <div className="page customer-readable privacy-page">
      <header className="privacy-heading">
        <h1>My Data &amp; Privacy</h1>
        <p className="secondary">Manage your alerts and personal information, and see how your data is used.</p>
      </header>
      <dl className="privacy-status" aria-label="Your current account settings">
        <div><dt>Mobile number</dt><dd>{p.phone_verified ? "Verified" : p.phone ? "Needs verification" : "Not added"}</dd></div>
        <div><dt>Text alerts</dt><dd>{!p.phone_verified ? "Verification required" : p.alerts_sms ? "On" : "Off"}</dd></div>
        <div><dt>In-app alerts</dt><dd>{p.alerts_inapp ? "On" : "Off"}</dd></div>
      </dl>
      <div className="privacy-layout">
        <div className="privacy-column" role="region" aria-label="Your settings">
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
          <p className="secondary">Choose how to receive storm and outage updates. You can change these preferences at any time.</p>
          {status && <div className="small">{status.alerts.reason}</div>}
          <label className="check"><input type="checkbox" checked={p.alerts_inapp}
            onChange={(e) => save({ alerts_inapp: e.target.checked })} /><span>In-app alerts</span></label>
          <label className="check"><input type="checkbox" checked={p.alerts_sms} disabled={!p.phone_verified}
            onChange={(e) => save({ alerts_sms: e.target.checked })} />
            <span>Text message alerts {p.phone_verified ? `to ${p.phone}` : "(verify a mobile number first)"}</span></label>
          {status && <>
            <div className="small" style={{ fontWeight: 600 }}>How updates work in this prototype</div>
            <p className="small secondary">Practice messages follow the storm journey in My Status: preparation, outage, a changed estimate, and restoration. They stay in-app and respect your preferences; some steps may not produce a message if your home keeps power or its estimate is unchanged.</p>
            <p className="small secondary">Live pre-storm alerts require an operator to send them. Automatic outage confirmations and restoration updates need a utility status feed, which is not connected yet.</p>
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
            crews prioritize. Guidance uses the categories you select. Anything you type in chat may also be sent to the AI provider.</div>
        </section>
        </div>
        <aside className="privacy-column" aria-label="Privacy summary and data controls">
        <section className="card stack">
          <h2>Your privacy at a glance</h2>
          <div><b>Encrypted before storage:</b> {p.stored.encrypted.join(", ")}.</div>
          <div><b>Stored as-is:</b> {p.stored.plain.join(", ")}. Passwords are stored only as a one-way hash.</div>
          <div><b>Excluded from automatic AI context:</b> {p.stored.never_shared_with_ai.join(", ")}. Personal information you type into chat can still be shared with the AI provider.</div>
          <div><b>On maps:</b> other customers see outages by area (5+ customers), never your home.</div>
        </section>
        <section className="card stack">
          <h2>Who can access your data</h2>
          <p>AEP operator accounts can view customer names, emails, ZIP codes, and declared needs to support outage planning. Access to the customer list is logged.</p>
          <h3>External services</h3>
          <ul className="privacy-list">
            <li><b>Address lookup:</b> your address and ZIP are sent to the US Census geocoder during registration.</li>
            <li><b>Text delivery:</b> when configured, Twilio receives your mobile number and the messages sent to it.</li>
            <li><b>AI assistance:</b> when available, Claude receives selected outage facts and declared needs for guidance, plus conversation messages when you use chat.</li>
          </ul>
          <details className="privacy-details">
            <summary>Chat history and browser storage</summary>
            <p>Chat history is held in browser memory and is not saved as message text in the app database. Closing the chat panel does not clear it. Refreshing the page or signing out clears the conversation from the interface.</p>
            <p>A session cookie keeps you signed in. Your light or dark mode preference is saved in this browser.</p>
          </details>
        </section>
        <section className="card stack">
            <h2>Your data controls</h2>
            <p>Download a JSON copy of your profile, alert preferences, declared needs, and notification history to review what is stored.</p>
            <p className="small secondary">Checklist completion and practice-journey progress are saved to your account and included in the download. An outage-ready HTML plan is saved only when you download it; remove that file from your device yourself.</p>
            <details className="privacy-details">
              <summary>What happens when you delete your account?</summary>
              <p>Deletion signs you out and removes your account, linked profile, checklist completion, practice journeys, customer notifications, dispatch records, reset tokens, and phone verification codes. Audit records and demo mailbox entries are not automatically removed. The app has no automatic retention schedule.</p>
              <p>Download your data first if you want to keep a copy. The download does not include audit records or demo mailbox entries.</p>
            </details>
            <Link to="/alerts">Review your notifications and preparation plan</Link>
          <hr />
          <div className="row">
            <a className="privacy-download" href="/api/me/export">Download my data</a>
            <button onClick={del} style={{ color: "var(--band-severe)" }}>Delete my account</button>
          </div>
        </section>
        </aside>
      </div>
    </div>
  );
}
