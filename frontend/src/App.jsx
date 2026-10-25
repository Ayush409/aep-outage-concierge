import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api.js";
import { Login, Register, Forgot, Reset, Mailbox } from "./pages/Auth.jsx";
import CustomerMap from "./pages/CustomerMap.jsx";
import MyStatus from "./pages/MyStatus.jsx";
import Alerts from "./pages/Alerts.jsx";
import MyData from "./pages/MyData.jsx";
import Simulation from "./pages/Simulation.jsx";
import OpsMap from "./pages/OpsMap.jsx";
import Restoration from "./pages/Restoration.jsx";
import Impact from "./pages/Impact.jsx";
import Comms from "./pages/Comms.jsx";
import ModelAudit from "./pages/ModelAudit.jsx";
import ChatWidget from "./components/ChatWidget.jsx";
import { applyTheme, initialTheme } from "./theme.js";
import ReadyPlan from "./pages/ReadyPlan.jsx";

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

const CUSTOMER_TABS = [
  ["/status", "My Status"], ["/map", "Map"], ["/alerts", "Alerts"],
  ["/data", "My Data & Privacy"],
];
const GUEST_TABS = [["/map", "Outage Map"]];
const AEP_TABS = [
  ["/ops", "Ops Map"], ["/restoration", "Restoration Planner"], ["/impact", "Business Impact"],
  ["/comms", "Communications"], ["/simulation", "Simulation"], ["/model", "Model & Audit"],
];

export default function App() {
  const [theme, setTheme] = useState(initialTheme);
  const toggleTheme = () => setTheme((current) => {
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    return next;
  });
  const [user, setUser] = useState(undefined);
  const [scenarios, setScenarios] = useState([]);
  // one selection drives every tab: the live 7-day forecast (default) or a storm simulation
  const [scenario, setScenario] = useState("live");
  const [bandOutcomes, setBandOutcomes] = useState({});
  const [journeys, setJourneys] = useState({});
  const [customerRevision, setCustomerRevision] = useState(0);
  const [journeyError, setJourneyError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const me = await api("/api/auth/me");
      setUser(me);
      const sc = await api("/api/scenarios");
      setScenarios(sc.scenarios);
      setBandOutcomes(sc.band_outcomes || {});
    } catch {
      setUser(null);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    let active = true;
    setJourneyError("");
    if (user?.role === "customer") {
      api(`/api/me/journey?scenario=${encodeURIComponent(scenario)}`).then((j) => {
        if (active) setJourneys((old) => ({ ...old, [`${user.id}:${scenario}`]: j }));
      }).catch((e) => { if (active) setJourneyError(e.message); });
    }
    return () => { active = false; };
  }, [user?.id, scenario]);

  if (user === undefined) return <div className="auth"><div className="card">Loading...</div></div>;

  const home = user?.role === "aep" ? "/ops" : "/status";
  const journey = journeys[`${user?.id}:${scenario}`];
  const updateJourney = (next) => {
    setJourneys((old) => ({ ...old, [`${user.id}:${scenario}`]: next }));
    setCustomerRevision((n) => n + 1);
  };
  const customerParams = { scenario, access_mult: journey?.access_mult ?? 1 };
  const ctx = { user, refresh, scenarios, scenario, setScenario, bandOutcomes, theme, toggleTheme,
    journey, journeyError, updateJourney, customerParams, customerRevision };

  return (
    <Ctx.Provider value={ctx}>
      {!user && <div className="auth-theme-toggle"><ThemeToggle /></div>}
      <Routes>
        <Route path="/login" element={user ? <Navigate to={home} /> : <Login />} />
        <Route path="/register" element={user ? <Navigate to={home} /> : <Register />} />
        <Route path="/forgot" element={<Forgot />} />
        <Route path="/reset" element={<Reset />} />
        <Route path="/dev/mailbox" element={<Mailbox />} />
        {user ? (
          <Route path="*" element={<Shell />} />
        ) : (
          <Route path="*" element={<Navigate to="/login" />} />
        )}
      </Routes>
    </Ctx.Provider>
  );
}

function ThemeToggle() {
  const { theme, toggleTheme } = useApp();
  return <button className="theme-toggle" onClick={toggleTheme} aria-pressed={theme === "dark"}
    aria-label={`Dark mode: ${theme === "dark" ? "on" : "off"}. Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
    <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
    {theme === "dark" ? "Light mode" : "Dark mode"}
  </button>;
}

function Shell() {
  const { user, refresh, scenarios, scenario, setScenario } = useApp();
  const location = useLocation();
  const [toasts, setToasts] = useState([]);
  const first = useRef(true);
  // pop a toast whenever the forecast / simulation selection changes
  useEffect(() => {
    if (first.current) { first.current = false; return undefined; }
    const sc = scenarios.find((x) => x.id === scenario);
    const id = Date.now();
    const text = scenario === "live" ? "Back to the live 7-day forecast" : `Simulation: ${sc?.name} - every tab now shows this storm`;
    setToasts((t) => [...t, { id, text, sim: scenario !== "live" }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);  // each toast dismisses itself
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario]);

  // customers: running a simulation slides in that storm's alerts for their home, one after another
  const [popups, setPopups] = useState([]);
  useEffect(() => {
    setPopups([]);
    if (user.role !== "customer" || scenario === "live") return undefined;
    let alive = true;
    const timers = [];
    api(`/api/me/alerts/timeline?scenario=${encodeURIComponent(scenario)}`).then((r) => {
      if (!alive) return;
      r.alerts.forEach((n, i) => timers.push(setTimeout(() => setPopups((p) => [...p, { ...n, id: `${scenario}-${i}` }]),
        600 + i * 1400)));
    }).catch(() => {});
    return () => { alive = false; timers.forEach(clearTimeout); };
  }, [scenario, user.role]);
  const dismiss = (id) => {
    setPopups((p) => p.map((n) => (n.id === id ? { ...n, leaving: true } : n)));
    setTimeout(() => setPopups((p) => p.filter((n) => n.id !== id)), 260);
  };
  const nav = useNavigate();
  const aep = user.role === "aep";
  const guest = user.role === "guest"; // anonymous household: outage map only
  const tabs = aep ? AEP_TABS : guest ? GUEST_TABS : CUSTOMER_TABS;

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    await refresh();
    nav("/login");
  }

  return (
    <div className={`shell${aep ? " operator-shell" : ""}`}>
      <header className="topbar">
        <div className="logo"><span className="logo-mark" aria-hidden="true">⚡</span>AEP Outage Concierge<small>{aep ? "Operations" : guest ? "Anonymous" : "Customer"}</small></div>
        <nav className="tabs" aria-label="Sections">
          {tabs.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>
          ))}
        </nav>
        <div className="who">
          <ThemeToggle />
          <select className="mode-select" value={scenario} onChange={(e) => setScenario(e.target.value)}
            aria-label="Forecast or storm simulation">
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>{s.id === "live" ? "Live forecast - next 7 days" : `Simulation: ${s.name}`}</option>
            ))}
          </select>
          <span>{user.name}</span>
          <button className="ghost" onClick={logout}>{guest ? "Exit" : "Sign out"}</button>
        </div>
      </header>
      {scenario !== "live" && (
        <div className="sim-banner" role="status">
          <b>Simulation mode</b>
          <span>{scenarios.find((s) => s.id === scenario)?.summary}</span>
          <button className="chip" onClick={() => setScenario("live")}>Back to live forecast</button>
        </div>
      )}
      <div className="route-anim" key={location.pathname}>
        <Routes>
          {guest ? (
            <>
              <Route path="/map" element={<CustomerMap />} />
              <Route path="*" element={<Navigate to="/map" />} />
            </>
          ) : aep ? (
            <>
              <Route path="/ops" element={<OpsMap />} />
              <Route path="/restoration" element={<Restoration />} />
              <Route path="/impact" element={<Impact />} />
              <Route path="/comms" element={<Comms />} />
              <Route path="/simulation" element={<Simulation />} />
              <Route path="/model" element={<ModelAudit />} />
              <Route path="*" element={<Navigate to="/ops" />} />
            </>
          ) : (
            <>
              <Route path="/map" element={<CustomerMap />} />
              <Route path="/status" element={<MyStatus />} />
              <Route path="/prepare" element={<Navigate to="/alerts" replace />} />
              <Route path="/alerts" element={<Alerts />} />
              <Route path="/data" element={<MyData />} />
              <Route path="/ready" element={<ReadyPlan />} />
              <Route path="*" element={<Navigate to="/status" />} />
            </>
          )}
        </Routes>
      </div>
      {!guest && <ChatWidget key={user.role} aep={aep} />}
      {popups.length > 0 && (
        <div className="alert-popups" aria-live="polite" aria-label="Simulated alerts">
          {popups.length > 1 && <button className="ghost small dismiss-all" onClick={() => popups.forEach((n) => dismiss(n.id))}>
            Dismiss all</button>}
          {popups.map((n) => (
            <div key={n.id} className={`alert-popup ${n.kind}${n.leaving ? " leaving" : ""}`} role="status">
              <div className="row spread" style={{ alignItems: "flex-start", gap: 8 }}>
                <div>
                  <b>{n.title}</b>
                  <div className="small muted">{new Date(n.at).toLocaleString(undefined, { weekday: "short", month: "short",
                    day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" })} (simulated)</div>
                </div>
                <button className="ghost popup-close" onClick={() => dismiss(n.id)} aria-label={`Dismiss ${n.title}`}>✕</button>
              </div>
              <div className="small">{n.body.replace(/^\[Simulation\] /, "")}</div>
            </div>
          ))}
        </div>
      )}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast${t.sim ? " sim" : ""}`}>{t.text}</div>)}
      </div>
    </div>
  );
}
