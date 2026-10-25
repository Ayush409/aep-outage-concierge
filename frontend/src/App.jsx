import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api.js";
import { Login, Register, Forgot, Reset, Mailbox } from "./pages/Auth.jsx";
import CustomerMap from "./pages/CustomerMap.jsx";
import MyStatus from "./pages/MyStatus.jsx";
import Prepare from "./pages/Prepare.jsx";
import Alerts from "./pages/Alerts.jsx";
import MyData from "./pages/MyData.jsx";
import Simulation from "./pages/Simulation.jsx";
import OpsMap from "./pages/OpsMap.jsx";
import Restoration from "./pages/Restoration.jsx";
import Impact from "./pages/Impact.jsx";
import Comms from "./pages/Comms.jsx";
import ModelAudit from "./pages/ModelAudit.jsx";

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

const CUSTOMER_TABS = [
  ["/status", "My Status"], ["/map", "Map"], ["/prepare", "Prepare"], ["/alerts", "Alerts"],
  ["/data", "My Data & Privacy"],
];
const AEP_TABS = [
  ["/ops", "Ops Map"], ["/restoration", "Restoration Planner"], ["/impact", "Business Impact"],
  ["/comms", "Communications"], ["/simulation", "Simulation"], ["/model", "Model & Audit"],
];

export default function App() {
  const [user, setUser] = useState(undefined);
  const [scenarios, setScenarios] = useState([]);
  // one selection drives every tab: the live 7-day forecast (default) or a storm simulation
  const [scenario, setScenario] = useState("live");
  const [bandOutcomes, setBandOutcomes] = useState({});

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

  if (user === undefined) return <div className="auth"><div className="card">Loading...</div></div>;

  const home = user?.role === "aep" ? "/ops" : "/status";
  const ctx = { user, refresh, scenarios, scenario, setScenario, bandOutcomes };

  return (
    <Ctx.Provider value={ctx}>
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
  const nav = useNavigate();
  const aep = user.role === "aep";
  const tabs = aep ? AEP_TABS : CUSTOMER_TABS;

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    await refresh();
    nav("/login");
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="logo"><span className="logo-mark" aria-hidden="true">⚡</span>AEP Outage Concierge<small>{aep ? "Operations" : "Customer"}</small></div>
        <nav className="tabs" aria-label="Sections">
          {tabs.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>
          ))}
        </nav>
        <div className="who">
          <select className="mode-select" value={scenario} onChange={(e) => setScenario(e.target.value)}
            aria-label="Forecast or storm simulation">
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>{s.id === "live" ? "Live forecast - next 7 days" : `Simulation: ${s.name}`}</option>
            ))}
          </select>
          <span>{user.name}</span>
          <button className="ghost" onClick={logout}>Sign out</button>
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
          {aep ? (
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
              <Route path="/prepare" element={<Prepare />} />
              <Route path="/alerts" element={<Alerts />} />
              <Route path="/data" element={<MyData />} />
              <Route path="*" element={<Navigate to="/status" />} />
            </>
          )}
        </Routes>
      </div>
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast${t.sim ? " sim" : ""}`}>{t.text}</div>)}
      </div>
    </div>
  );
}
