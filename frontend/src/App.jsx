import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
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
  ["/map", "Map"], ["/status", "My Status"], ["/prepare", "Prepare"], ["/alerts", "Alerts"],
  ["/simulation", "Simulation"], ["/data", "My Data & Privacy"],
];
const AEP_TABS = [
  ["/ops", "Ops Map"], ["/restoration", "Restoration Planner"], ["/impact", "Business Impact"],
  ["/comms", "Communications"], ["/simulation", "Simulation"], ["/model", "Model & Audit"],
];

export default function App() {
  const [user, setUser] = useState(undefined);
  const [scenarios, setScenarios] = useState([]);
  const [scenario, setScenario] = useState(null);
  const [active, setActive] = useState(null);
  const [bandOutcomes, setBandOutcomes] = useState({});

  const refresh = useCallback(async () => {
    try {
      const me = await api("/api/auth/me");
      setUser(me);
      const sc = await api("/api/scenarios");
      setScenarios(sc.scenarios);
      setBandOutcomes(sc.band_outcomes || {});
      setActive(sc.active);
      setScenario((s) => s || sc.active);
    } catch {
      setUser(null);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  if (user === undefined) return <div className="auth"><div className="card">Loading...</div></div>;

  const home = user?.role === "aep" ? "/ops" : "/status";
  const ctx = { user, refresh, scenarios, scenario, setScenario, active, setActive, bandOutcomes };

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
  const { user, scenarios, scenario, setScenario, active, refresh } = useApp();
  const nav = useNavigate();
  const aep = user.role === "aep";
  const tabs = aep ? AEP_TABS : CUSTOMER_TABS;
  const sc = scenarios.find((s) => s.id === scenario);

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    await refresh();
    nav("/login");
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="logo">AEP Outage Concierge<small>{aep ? "Operations" : "Customer"}</small></div>
        <nav className="tabs" aria-label="Sections">
          {tabs.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>
          ))}
        </nav>
        <div className="who">
          <span>{user.name}</span>
          <button className="ghost" onClick={logout}>Sign out</button>
        </div>
      </header>
      <div className="scenario-banner">
        <span className="muted">Viewing</span>
        <select value={scenario || ""} onChange={(e) => setScenario(e.target.value)} style={{ width: "auto" }}
          aria-label="Scenario">
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>{s.name}{s.id === active ? " (active event)" : ""}</option>
          ))}
        </select>
        {sc && <span className="tag">{sc.kind === "replay" ? "Real event replay" : sc.kind === "live" ? "Live" :
          "What-if simulation"}</span>}
        {sc?.date && <span className="muted small">{sc.date}</span>}
        <span className="muted small" style={{ flex: 1, minWidth: 200 }}>{sc?.summary}</span>
      </div>
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
            <Route path="/simulation" element={<Simulation />} />
            <Route path="/data" element={<MyData />} />
            <Route path="*" element={<Navigate to="/status" />} />
          </>
        )}
      </Routes>
    </div>
  );
}
