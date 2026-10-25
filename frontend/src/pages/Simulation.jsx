import { useEffect, useMemo, useRef, useState } from "react";
import { ColumnLayer, LineLayer, ScatterplotLayer } from "@deck.gl/layers";
import { fmt, hourLabel, qs } from "../api.js";
import { useApp } from "../App.jsx";
import MapView from "../components/MapView.jsx";
import { BOUNDS, sample } from "../components/weather.js";
import { ErrorBox, Loading, Stat, useFetch } from "../components/ui.jsx";
import { CostBars, OutageCurve } from "../components/charts.jsx";

const DEFAULTS = { crews: 20, mutual_aid_crews: 20, mutual_aid_day: 1, gust_mult: 1, access_mult: 1 };
const PLAY_MS = 8000;
const N_PARTICLES = 1400;

export default function Simulation() {
  const { scenarios, scenario, setScenario, user } = useApp();  // selection comes from the top-right toggle
  const aep = user.role === "aep";
  // each storm starts from its own crew defaults (e.g. a tornado outbreak comes with a big mutual-aid call)
  const defaults = useMemo(() => ({ ...DEFAULTS, ...(scenarios.find((x) => x.id === scenario)?.default_crews || {}) }),
    [scenarios, scenario]);
  const [draft, setDraft] = useState(defaults);
  const [params, setParams] = useState(defaults);
  useEffect(() => { setDraft(defaults); setParams(defaults); }, [defaults]);
  // re-run automatically shortly after a slider stops moving
  useEffect(() => {
    const t = setTimeout(() => setParams(draft), 600);
    return () => clearTimeout(t);
  }, [draft]);
  const q = scenario ? qs({ scenario, ...params }) : null;
  const ov = useFetch(q && `/api/sim/overview${q}`, [q]);
  const frames = useFetch(q && `/api/sim/frames${q}`, [q]).data;
  const weather = useFetch(scenario ? `/api/weather${qs({ scenario })}` : null, [scenario]).data;
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [played, setPlayed] = useState(false);
  const raf = useRef(0);

  const H = frames?.hours?.length ? frames.hours.length - 1 : 0;
  const wxStep = weather && weather.time.length > 1
    ? (new Date(weather.time[1]) - new Date(weather.time[0])) / 3.6e6 : 1;
  const wxIdx = Math.min(Math.floor(hour / wxStep), (weather?.time.length || 1) - 1);

  // reset when the scenario or inputs change
  useEffect(() => { setHour(0); setPlayed(false); setPlaying(false); }, [q]);

  function play() {
    cancelAnimationFrame(raf.current);
    setPlaying(true);
    const t0 = performance.now();
    const tick = (now) => {
      const f = Math.min((now - t0) / PLAY_MS, 1);
      setHour(f * H);
      if (f < 1) raf.current = requestAnimationFrame(tick);
      else { setPlaying(false); setPlayed(true); }
    };
    raf.current = requestAnimationFrame(tick);
  }
  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  // ---- wind particles (advected through the hourly wind field)
  const particles = useRef(null);
  if (!particles.current) particles.current = seedParticles();
  const trails = useMemo(() => {
    if (!weather) return [];
    const out = [];
    for (const p of particles.current) {
      const spd = sample(weather, "wind_speed_10m", wxIdx, p.x, p.y);
      const dir = sample(weather, "wind_direction_10m", wxIdx, p.x, p.y);
      const gust = sample(weather, "wind_gusts_10m", wxIdx, p.x, p.y);
      const rad = ((dir + 180) * Math.PI) / 180; // direction wind blows toward
      const k = 0.00006 * (spd + 4);
      const nx = p.x + Math.sin(rad) * k * 1.25;
      const ny = p.y + Math.cos(rad) * k;
      out.push({ from: [p.x, p.y], to: [nx, ny], gust });
      p.x = nx; p.y = ny; p.age += 1;
      if (p.age > p.life || nx < BOUNDS[0] || nx > BOUNDS[2] || ny < BOUNDS[1] || ny > BOUNDS[3]) Object.assign(p, newParticle());
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hour, weather]);

  const fi = Math.min(Math.round(hour), H);
  const columns = useMemo(() => (frames?.cells || []).map((c, i) => ({ ...c, out: frames.out[i][fi] }))
    .filter((c) => c.out > 0), [frames, fi]);
  const damage = useMemo(() => (frames?.damage || []).filter((d) => d.t <= hour), [frames, hour]);
  const outNow = columns.reduce((a, c) => a + c.out, 0);

  const layers = [
    // wind shown as moving streaks below (static arrows are on the 2D maps)
    new LineLayer({
      id: "wind", data: trails, getSourcePosition: (d) => d.from, getTargetPosition: (d) => d.to,
      getColor: (d) => (d.gust >= 30 ? [11, 61, 145, 230] : [11, 61, 145, 120]), getWidth: (d) => (d.gust >= 45 ? 2.5 : 1.5),
      widthUnits: "pixels",
    }),
    new ColumnLayer({
      id: "out", data: columns, diskResolution: 4, radius: 800, angle: 45, extruded: true, pickable: true,
      getPosition: (d) => [d.lon, d.lat], getElevation: (d) => Math.sqrt(d.out) * 260,
      getFillColor: (d) => (d.out > 500 ? [208, 59, 59, 230] : d.out > 100 ? [236, 131, 90, 230] : [250, 178, 25, 220]),
      updateTriggers: { getElevation: fi, getFillColor: fi },
    }),
    new ScatterplotLayer({
      id: "damage", data: damage, getPosition: (d) => [d.lon, d.lat], radiusUnits: "pixels", getRadius: 4,
      getFillColor: (d) => (d.done != null && d.done <= hour ? [12, 163, 12, 220] : [208, 59, 59, 255]),
      stroked: true, getLineColor: [255, 255, 255], lineWidthMinPixels: 1, updateTriggers: { getFillColor: hour },
    }),
  ];

  const s = ov.data?.summary;
  const sc = scenarios.find((x) => x.id === scenario);

  return (
    <div className="page sidebar-layout">
      <aside className="card stack" style={{ alignSelf: "start" }}>
        <h2>{scenario === "live" ? "Live forecast - next 7 days" : sc?.name || "Storm simulation"}</h2>
        {sc && <div className="small secondary">{sc.summary}</div>}
        {scenario === "live" && (
          <div className="small">Plays out what the coming week's forecast could do. Pick a storm in the top-right menu
            (or <button className="chip" onClick={() => setScenario("derecho")}>try a derecho</button>) to simulate it.</div>
        )}
        <hr />
        <div className="small" style={{ fontWeight: 600 }}>Change the inputs</div>
        <Slider label="Local crews" v={draft.crews} min={5} max={200} step={5} on={(v) => setDraft({ ...draft, crews: v })} />
        <Slider label="Mutual-aid crews" v={draft.mutual_aid_crews} min={0} max={200} step={5}
          on={(v) => setDraft({ ...draft, mutual_aid_crews: v })} />
        <Slider label="Mutual aid arrives (day)" v={draft.mutual_aid_day} min={0} max={5} step={0.5}
          on={(v) => setDraft({ ...draft, mutual_aid_day: v })} />
        <Slider label="Wind strength" v={draft.gust_mult} min={0.6} max={1.5} step={0.05} fmtv={(v) => `${Math.round(v * 100)}%`}
          on={(v) => setDraft({ ...draft, gust_mult: v })} />
        <Slider label="Access problems" v={draft.access_mult} min={0} max={3} step={0.25} fmtv={(v) => `${v}x`}
          on={(v) => setDraft({ ...draft, access_mult: v })} />
        <div className="row">
          <button onClick={() => setDraft(defaults)}>Reset</button>
          <span className="small muted" role="status">{ov.loading ? "Re-running..." : "Results update as you move a slider"}</span>
        </div>
        <div className="small muted">Bucket trucks stop at 30 mph gusts. Each run repeats 40 times with random job times
          to give ranges. More crews only help while jobs are waiting for a crew - watch "Waiting for a crew".</div>
      </aside>

      <div className="stack" style={{ minWidth: 0 }}>
        <div className="card" style={{ padding: 0, height: 480, position: "relative", overflow: "hidden" }}>
          <MapView layers={layers} terrain pitch={58} bearing={-18} zoom={9.9}
            getTooltip={({ object, layer }) => layer?.id === "out" && object
              ? { html: `<b>${fmt.n(object.out)}</b> customers out`, className: "tooltip" } : null}>
            <div className="map-panel tl small stack" style={{ minWidth: 220 }}>
              <b>{frames ? hourLabel(frames.start, hour) : "-"}</b>
              <div>Customers without power: <b>{fmt.n(outNow)}</b></div>
              <div className="muted">Blue streaks: wind (darker = gusts over 30 mph). Columns: customers out. Dots: damage (red = waiting, green = fixed).</div>
            </div>
            <div className="map-panel bl" style={{ right: 60, maxWidth: "none" }}>
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <button className="primary" onClick={play} disabled={!frames || playing}>
                  {playing ? "Playing..." : played ? "Replay" : "▶ Play storm"}</button>
                <input type="range" min={0} max={H} step={0.1} value={hour} aria-label="Simulation time"
                  onChange={(e) => { cancelAnimationFrame(raf.current); setPlaying(false); setHour(+e.target.value); }} />
              </div>
            </div>
          </MapView>
        </div>
        <ErrorBox error={ov.error} />
        {!s ? <Loading what="Running the simulation" /> : (
          <>
            <div className="grid cols-4">
              <Stat label="Customers who lose power" value={fmt.n(s.customers_out.p50)}
                sub={`range ${fmt.n(s.customers_out.p10)}-${fmt.n(s.customers_out.p90)} of ${fmt.n(s.total_customers)}`} />
              <Stat label="Most out at once" value={fmt.n(s.peak_out.p50)} />
              <Stat label="Typical outage length" value={fmt.hours(s.typical_outage_hours.p50)}
                sub={`median customer; 90% restored within ${fmt.hours(s.hours_onset_to_90pct.p50)} of the first outage`} />
              <Stat label="Waiting for a crew" value={fmt.hours(s.crew_wait_hours.p50)}
                sub={`median per job - ${fmt.n(s.jobs.p50)} jobs, ${fmt.n(s.person_hours.p50)} person-hours`} />
            </div>
            <details className="small confidence-line">
              <summary>Confidence: <b>{ov.data.confidence.level}</b>
                {ov.data.operations && <span className="muted"> - {ov.data.operations.label}</span>}
                {ov.data.confidence.notes.length > 0 && <span className="muted"> (why?)</span>}</summary>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {ov.data.confidence.notes.map((n) => <li key={n} className="secondary">{n}</li>)}</ul>
            </details>
            <div className={aep && ov.data.cost ? "grid cols-2" : "grid"}>
              <section className="card">
                <h3>Customers without power over time</h3>
                <OutageCurve curve={ov.data.curve} start={ov.data.start} />
              </section>
              {aep && ov.data.cost && (
                <section className="card stack">
                  <h3>Who pays</h3>
                  <CostBars height={150} rows={[{ name: sc?.name?.slice(0, 26) || "", lost_revenue: ov.data.cost.lost_revenue,
                    repair: ov.data.cost.repair.total_mid, customer_cost: ov.data.cost.customer_cost }]} />
                </section>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Slider({ label, v, min, max, step, on, fmtv = (x) => x }) {
  return (
    <label className="slider">
      <span className="small">{label}</span><b className="small">{fmtv(v)}</b>
      <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => on(+e.target.value)} />
    </label>
  );
}

function newParticle() {
  return { x: BOUNDS[0] + Math.random() * (BOUNDS[2] - BOUNDS[0]), y: BOUNDS[1] + Math.random() * (BOUNDS[3] - BOUNDS[1]),
    age: 0, life: 20 + Math.random() * 40 };
}
function seedParticles() { return Array.from({ length: N_PARTICLES }, newParticle); }
