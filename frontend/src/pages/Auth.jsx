import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { useApp } from "../App.jsx";

function AuthCard({ title, subtitle, children }) {
  return (
    <div className="auth">
      <div className="card stack">
        <div>
          <div className="muted small" style={{ fontWeight: 600 }}>AEP OUTAGE CONCIERGE</div>
          <h1>{title}</h1>
          {subtitle && <div className="secondary">{subtitle}</div>}
        </div>
        {children}
      </div>
    </div>
  );
}

export function Login() {
  const { refresh } = useApp();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const r = await api("/api/auth/login", { method: "POST", body: { email, password } });
      await refresh();
      nav(r.role === "aep" ? "/ops" : "/status");
    } catch (ex) {
      setErr(ex.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Sign in" subtitle="Storm outage risk, restoration estimates and alerts for your home.">
      <form className="stack" onSubmit={submit}>
        <label className="field"><span>Email</span>
          <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="field"><span>Password</span>
          <input type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {err && <div className="error" role="alert">{err}</div>}
        <button className="primary" disabled={busy}>{busy ? "Signing in..." : "Sign in"}</button>
      </form>
      <div className="row spread small">
        <Link to="/forgot">Forgot password?</Link>
        <span>New customer? <Link to="/register">Create an account</Link></span>
      </div>
      <div className="muted small">AEP operators sign in here too - you'll be taken to the operations dashboard.
        Demo accounts are listed in <code>scripts/seed_accounts.py</code>.</div>
    </AuthCard>
  );
}

const NEEDS = [
  ["medical_device", "Someone in my home uses powered medical equipment"],
  ["mobility", "Someone in my home has limited mobility"],
  ["hearing_vision", "Someone in my home is deaf, hard of hearing, blind or low-vision"],
  ["critical_facility", "This address is a care home, school, or other critical facility"],
];

export function Register() {
  const { refresh } = useApp();
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [f, setF] = useState({
    name: "", email: "", password: "", address: "", zip: "", phone: "", needs: [], alerts_sms: true, alerts_inapp: true,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function submit(e) {
    e.preventDefault();
    if (step < 2) return setStep(step + 1);
    setBusy(true);
    setErr("");
    try {
      await api("/api/auth/register", { method: "POST", body: { ...f, phone: f.phone || null } });
      await refresh();
      nav("/status");
    } catch (ex) {
      setErr(ex.message);
      if (ex.status === 422 && /address|ZIP|area/i.test(ex.message)) setStep(1);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Create your account" subtitle={["Your account", "Your home", "Alerts & needs"][step]}>
      <div className="steps">{[0, 1, 2].map((i) => <i key={i} className={i <= step ? "on" : ""} />)}</div>
      <form className="stack" onSubmit={submit}>
        {step === 0 && (
          <>
            <label className="field"><span>Full name</span><input value={f.name} onChange={set("name")} required /></label>
            <label className="field"><span>Email</span>
              <input type="email" value={f.email} onChange={set("email")} required autoComplete="username" /></label>
            <label className="field"><span>Password (8+ characters)</span>
              <input type="password" minLength={8} value={f.password} onChange={set("password")} required
                autoComplete="new-password" /></label>
          </>
        )}
        {step === 1 && (
          <>
            <label className="field"><span>Street address</span>
              <input value={f.address} onChange={set("address")} required placeholder="123 Main St, Roanoke, VA" />
            </label>
            <label className="field"><span>ZIP code</span>
              <input value={f.zip} onChange={set("zip")} required pattern="\d{5}" inputMode="numeric" maxLength={5} />
            </label>
            <label className="field"><span>Mobile number for text alerts (optional)</span>
              <input value={f.phone} onChange={set("phone")} type="tel" placeholder="+1 540 555 0100" /></label>
            <div className="muted small">Your address, ZIP and phone are encrypted before they're stored. We use your
              address once to find the power line that serves you; it is never sent to our AI assistant.</div>
          </>
        )}
        {step === 2 && (
          <>
            <div className="secondary small">Optional. Telling us helps us tailor safety advice and alert you
              earlier. We never guess this from other data.</div>
            {NEEDS.map(([k, label]) => (
              <label key={k} className="check">
                <input type="checkbox" checked={f.needs.includes(k)}
                  onChange={(e) => setF({ ...f, needs: e.target.checked ? [...f.needs, k] : f.needs.filter((n) => n !== k) })} />
                <span>{label}</span>
              </label>
            ))}
            <hr />
            <label className="check"><input type="checkbox" checked={f.alerts_inapp} onChange={set("alerts_inapp")} />
              <span>In-app alerts</span></label>
            <label className="check"><input type="checkbox" checked={f.alerts_sms} onChange={set("alerts_sms")} />
              <span>Text message alerts{f.phone ? "" : " (add a mobile number to enable)"}</span></label>
          </>
        )}
        {err && <div className="error" role="alert">{err}</div>}
        <div className="row spread">
          {step > 0 ? <button type="button" onClick={() => setStep(step - 1)}>Back</button> : <span />}
          <button className="primary" disabled={busy}>{step < 2 ? "Continue" : busy ? "Finding your line..." : "Create account"}</button>
        </div>
      </form>
      <div className="small">Already have an account? <Link to="/login">Sign in</Link></div>
    </AuthCard>
  );
}

export function Forgot() {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState("");
  async function submit(e) {
    e.preventDefault();
    const r = await api("/api/auth/forgot", { method: "POST", body: { email } });
    setMsg(r.message);
  }
  return (
    <AuthCard title="Reset your password" subtitle="We'll email you a link to choose a new password.">
      <form className="stack" onSubmit={submit}>
        <label className="field"><span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <button className="primary">Send reset link</button>
      </form>
      {msg && <div role="status">{msg} <span className="muted small">(Demo: emails go to the{" "}
        <Link to="/dev/mailbox">dev mailbox</Link>.)</span></div>}
      <Link to="/login" className="small">Back to sign in</Link>
    </AuthCard>
  );
}

export function Reset() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);
  async function submit(e) {
    e.preventDefault();
    try {
      await api("/api/auth/reset", { method: "POST", body: { token: params.get("token") || "", password: pw } });
      setDone(true);
      setTimeout(() => nav("/login"), 1500);
    } catch (ex) {
      setErr(ex.message);
    }
  }
  return (
    <AuthCard title="Choose a new password">
      {done ? <div role="status">Password updated. Taking you to sign in...</div> : (
        <form className="stack" onSubmit={submit}>
          <label className="field"><span>New password (8+ characters)</span>
            <input type="password" minLength={8} value={pw} onChange={(e) => setPw(e.target.value)} required
              autoComplete="new-password" /></label>
          {err && <div className="error" role="alert">{err}</div>}
          <button className="primary">Update password</button>
        </form>
      )}
    </AuthCard>
  );
}

export function Mailbox() {
  const [mail, setMail] = useState(null);
  useEffect(() => { api("/api/dev/mailbox").then(setMail).catch(() => setMail([])); }, []);
  return (
    <AuthCard title="Dev mailbox" subtitle="Emails the demo would have sent (no real email service is connected).">
      {!mail ? "Loading..." : mail.length === 0 ? <div className="muted">No emails yet.</div> : mail.map((m) => (
        <div key={m.id} className="card stack" style={{ boxShadow: "none" }}>
          <div className="small muted">To {m.to_email} - {new Date(m.created * 1000).toLocaleString()}</div>
          <b>{m.subject}</b>
          <div style={{ whiteSpace: "pre-wrap" }}>
            {m.body.split(/(\/reset\?token=\S+)/).map((part, i) =>
              part.startsWith("/reset?token=") ? <Link key={i} to={part}>{part.slice(0, 40)}...</Link> : part)}
          </div>
        </div>
      ))}
      <Link to="/login" className="small">Back to sign in</Link>
    </AuthCard>
  );
}
