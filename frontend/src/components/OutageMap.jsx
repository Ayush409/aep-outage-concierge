import { useEffect, useMemo, useState } from "react";
import { PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { BAND_RGB, fmt, hourLabel, qs } from "../api.js";
import { useApp } from "../App.jsx";
import MapView, { squarePolygon } from "./MapView.jsx";
import { mapTimes, restorationHour } from "./timeline.js";
import RestorationSummary from "./RestorationSummary.jsx";
import { compassName, LAYERS, nowIndex, sample, weatherLayer } from "./weather.js";
import { Band, BandLegend, bandOutcomeText, Stat, TimeSlider, WeatherControls, useFetch } from "./ui.jsx";

const FAC = { hospital: [208, 59, 59], fire: [235, 104, 52], ems: [98, 80, 214] };

/**
 * The map used by both sides. Shared: weather layers, time slider, risk by area, predicted outage areas,
 * % without power by ZIP. AEP only (aep=true): outage pins on the protective devices, hospitals / fire / EMS,
 * % by circuit and expected-damage details. Customer only: their own home and risk band.
 */
export default function OutageMap({ aep = false }) {
  const { scenario, customerParams, customerRevision } = useApp();
  const q = qs(aep ? { scenario } : customerParams);
  const weather = useFetch(`/api/weather${qs({ scenario })}`, [scenario]).data;
  const cells = useFetch(`/api/sim/cells${q}`, [scenario]).data;
  const frames = useFetch(`/api/sim/frames${q}`, [scenario]).data;
  const overview = useFetch(`/api/sim/overview${q}`, [scenario]).data;
  const status = useFetch(aep ? null : `/api/me/status${q}`, [scenario, customerParams.access_mult, customerRevision]).data;
  const pins = useFetch(aep ? `/api/aep/pins${q}` : null, [scenario]).data;
  const fac = useFetch(aep ? "/api/aep/facilities" : null).data;
  const [layer, setLayer] = useState(aep ? null : "wind_gusts_10m");
  const [hour, setHour] = useState(0); // hours since the start of the window (= outage frame index)
  const [show, setShow] = useState({ risk: true, out: true, pins: true, fac: true });

  // Scenarios follow restoration frames; live mode retains the forecast window.
  const wxStep = weather && weather.time.length > 1 ? (new Date(weather.time[1]) - new Date(weather.time[0])) / 3.6e6 : 1;
  const nWx = weather?.time.length || 0;
  const times = useMemo(() => {
    if (!weather) return null;
    return mapTimes(weather.time, frames, scenario === "live");
  }, [weather, frames, scenario]);
  const evHour = Math.min(hour, Math.max((frames?.hours?.length || 1) - 1, 0));
  const wxIdx = Math.min(Math.floor(hour / wxStep), Math.max(nWx - 1, 0));
  const weatherAvailable = hour <= Math.round((nWx - 1) * wxStep);
  const restoredHour = restorationHour(frames?.total);

  // totals include small areas the map hides for privacy, so cards = ZIP / circuit table sums
  const frameTotal = (h) => frames?.total?.[h] ?? 0;
  const peak = useMemo(() => {
    if (!frames?.cells?.length) return null;
    let best = { h: 0, total: 0 };
    const end = frames.hours.length;
    for (let h = 0; h < end; h++) {
      const total = frameTotal(h);
      if (total > best.total) best = { h, total };
    }
    return best.total ? best : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frames, nWx, wxStep]);

  // live forecast opens at "now"; a storm simulation opens at its peak outage hour
  useEffect(() => {
    if (!weather || !times) return;
    if (scenario === "live") setHour(nowIndex({ time: times }));
    else setHour(peak?.h ?? 0);
  }, [weather, times, scenario, peak]);

  const [areaHour, setAreaHour] = useState(null);
  useEffect(() => {
    const t = setTimeout(() => setAreaHour(evHour), 250);
    return () => clearTimeout(t);
  }, [evHour]);
  const areas = useFetch(areaHour == null ? null
    : `${aep ? "/api/aep/areas" : "/api/sim/areas"}${qs({ ...(aep ? { scenario } : customerParams), hour: areaHour })}`, [scenario, areaHour, q]).data;

  const outCells = useMemo(() => {
    if (!frames?.cells?.length) return [];
    return frames.cells.map((c, i) => ({ ...c, out: frames.out[i][evHour] })).filter((c) => c.out >= 5);
  }, [frames, evHour]);
  // same hour rule as the frames: out during hour h if floor(out) <= h < ceil(restored)
  const pinState = (p) => (Math.floor(p.out_at) > evHour ? "pending" : Math.ceil(p.restored_at) <= evHour ? "restored"
    : "out");
  // pins are nested (a fuse inside an out recloser), so customer counts come from the map frames, never the pins
  const outNow = frameTotal(evHour);

  const layers = [
    show.risk && cells && new PolygonLayer({
      id: "risk", data: cells, getPolygon: (d) => squarePolygon(d.lon, d.lat), pickable: true, stroked: true,
      getFillColor: (d) => [...BAND_RGB[d.band], d.band === "Low" ? 0 : 50],
      getLineColor: (d) => [...BAND_RGB[d.band], d.band === "Low" ? 0 : 150], lineWidthMinPixels: 1,
    }),
    weatherLayer(weather, layer, wxIdx, !!layer && weatherAvailable),
    show.out && new ScatterplotLayer({
      id: "out", data: outCells, getPosition: (d) => [d.lon, d.lat], radiusUnits: "pixels",
      getRadius: (d) => 9 + Math.sqrt(d.out) * 0.9, getFillColor: [200, 16, 46, 210], stroked: true,
      getLineColor: [255, 255, 255], lineWidthMinPixels: 2, pickable: true, updateTriggers: { getRadius: evHour },
    }),
    show.out && new TextLayer({
      id: "out-label", data: outCells, getPosition: (d) => [d.lon, d.lat], getText: (d) => fmt.n(d.out), getSize: 12,
      fontWeight: 700, getColor: [255, 255, 255], fontFamily: "Inter, system-ui, sans-serif",
    }),
    aep && show.pins && pins && new ScatterplotLayer({
      id: "pins", data: pins, pickable: true, radiusUnits: "pixels", stroked: true, lineWidthMinPixels: 1,
      getPosition: (d) => [d.lon, d.lat], getRadius: (d) => 3 + Math.sqrt(d.customers) / 2.5,
      getFillColor: (d) => ({ out: [208, 59, 59, 230], restored: [12, 163, 12, 200], pending: [150, 150, 150, 120] })[pinState(d)],
      getLineColor: [255, 255, 255], updateTriggers: { getFillColor: evHour },
    }),
    aep && show.fac && fac && new ScatterplotLayer({
      id: "fac", data: fac, pickable: true, radiusUnits: "pixels", getRadius: 6, stroked: true,
      getPosition: (d) => [d.lon, d.lat], getFillColor: (d) => FAC[d.kind], getLineColor: [255, 255, 255],
      lineWidthMinPixels: 2,
    }),
    !aep && status?.home && new ScatterplotLayer({
      id: "home", data: [status.home], getPosition: (d) => [d.lon, d.lat], getRadius: 9, radiusUnits: "pixels",
      getFillColor: [11, 61, 145], stroked: true, getLineColor: [255, 255, 255], lineWidthMinPixels: 3,
    }),
  ];

  function wxLine(coordinate) {
    if (!weather || !layer || !coordinate || !weatherAvailable) return "";
    const [lon, lat] = coordinate;
    const v = Math.round(sample(weather, layer, wxIdx, lon, lat));
    const dir = LAYERS[layer].kind === "wind"
      ? ` from the ${compassName(sample(weather, "wind_direction_10m", wxIdx, lon, lat))}` : "";
    return `<br/><b>${LAYERS[layer].label}: ${v} ${LAYERS[layer].unit}</b>${dir}`;
  }

  function tooltip({ object, layer: l, coordinate }) {
    const tip = (html) => ({ html, className: "tooltip" });
    if (l?.id === "out" && object) return tip(`<b>${fmt.n(object.out)} customers</b> without power in this area`);
    if (l?.id === "pins" && object) {
      return tip(`<b>${object.kind} - ${fmt.n(object.customers)} customers</b><br/>Out ${fmt.hours(object.out_at)} into the ` +
        `event, restored at ${fmt.hours(object.restored_at)}` +
        (object.life_support ? `<br/>${object.life_support} life-support premise(s)` : ""));
    }
    if (l?.id === "fac" && object) return tip(`<b>${object.name}</b><br/>${object.kind.toUpperCase()}`);
    if (l?.id === "risk" && object) {
      const seen = aep ? bandOutcomeText(object.observed) : "Experimental planning indicator; not a validated probability.";
      const detail = aep ? `<br/>${fmt.pct(object.p_out)} of ${fmt.n(object.customers)} customers - expected damage ` +
        `${object.exp_damage}<br/>Gust ${object.gust} mph, ice ${object.ice} in` : "";
      return tip(`<b>${object.band} risk</b>${seen ? `<br/><span class="muted">${seen}</span>` : ""}${detail}<br/>` +
        `${object.factors.join("<br/>") || "No strong weather drivers"}${wxLine(coordinate)}`);
    }
    const w = wxLine(coordinate);
    return w ? tip(w.replace(/^<br\/>/, "")) : null;
  }

  const s = overview?.summary;
  const toggles = [["risk", "Risk by area"], ["out", "Areas without power (5+ customers)"],
    ...(aep ? [["pins", "Outage devices (red out, green restored)"], ["fac", "Hospitals / fire / EMS"]] : [])];

  return (
    <div className="page full">
      <MapView layers={layers} getTooltip={tooltip} zoom={10.2} focusZoom={10.6}
        focus={!aep && status?.home ? [status.home.lon, status.home.lat] : null}>
        <div className="map-panel tl stack" style={{ width: 340, maxHeight: "calc(100% - 40px)", overflow: "auto" }}>
          {!aep && status && (
            <div className="row"><span className="small secondary">Your risk</span><Band band={status.risk.band} />
              <span className="small muted">{status.premise.city} {status.premise.zip}</span></div>
          )}
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <Stat label="Out at this time" value={fmt.n(outNow)}
              sub={peak ? `peak ${fmt.n(peak.total)}` : "none"} />
            <Stat label="Outage at some point" value={fmt.n(frames?.customers_out)}
              sub={s ? `of ${fmt.n(s.total_customers)} - range ${fmt.n(s.customers_out.p10)}-${fmt.n(s.customers_out.p90)}`
                : ""} />
          </div>
          {times?.length > 0 && <TimeSlider times={times} hour={Math.min(hour, times.length - 1)} setHour={setHour} />}
          {peak && <button className="chip" onClick={() => setHour(peak.h)}>Jump to peak outage
            ({fmt.n(peak.total)} customers)</button>}
          {restoredHour !== null && <button className="chip" onClick={() => setHour(restoredHour)}>
            Jump to all customers restored</button>}
          {!aep && status && <RestorationSummary status={status} compact />}
          {aep && frames?.all_restored_hour != null && <div className="small">
            <b>All modeled customers restored:</b> {hourLabel(frames.start, frames.all_restored_hour)} (map run)
          </div>}
          {!weatherAvailable && <div className="small secondary">Restoration continues beyond the weather window. Weather overlays are unavailable for this time.</div>}
          <details open={aep}><summary>Weather layers &amp; map options</summary>
          <WeatherControls layer={layer} setLayer={setLayer} legendWeather={weather} legendHour={wxIdx} />
          {weather && weatherAvailable && layer && !aep && status?.home && (
            <div className="small secondary">At your home: <b>{Math.round(sample(weather, layer, wxIdx, status.home.lon,
              status.home.lat))} {LAYERS[layer].unit}</b></div>)}
          <div className="small stack">
            {toggles.map(([k, label]) => (
              <label key={k} className="check"><input type="checkbox" checked={show[k]}
                onChange={(e) => setShow({ ...show, [k]: e.target.checked })} /><span>{label}</span></label>
            ))}
            {show.risk && (aep ? <BandLegend /> : <div className="muted">Risk colors are experimental planning indicators, not measured outage probabilities.</div>)}
            {!aep && <div className="muted">Predicted from {scenario === "live" ? "the forecast" : "the simulation"}. Outages
              are shown by area (5+ customers), never by home. The blue dot is your home.</div>}
          </div>
          </details>
        </div>
        <div className="map-panel tr stack" style={{ width: 300, maxHeight: "calc(100% - 60px)", overflow: "auto" }}>
          <h3 style={{ margin: 0 }}>% without power</h3>
          <div className="small muted">{aep ? "At this time on the slider (typical simulated run, same as the map). AEP customers in this data set; areas under 5 customers hidden."
            : "Estimated outages at the selected time. Areas with fewer than 5 customers are hidden."}</div>
          <AreaTable title="ZIP code" rows={areas?.zip} highlight={!aep ? status?.premise?.zip : null} />
          {aep && <AreaTable title="Circuit" rows={areas?.circuit} />}
        </div>
      </MapView>
    </div>
  );
}

function AreaTable({ title, rows, highlight }) {
  if (!rows) return null;
  const top = rows.filter((r) => r.out > 0).slice(0, 8);
  const mine = highlight && rows.find((r) => r.id === highlight);
  return (
    <table>
      <thead><tr><th>{title}</th><th className="num">Out</th><th className="num">%</th></tr></thead>
      <tbody>
        {top.length === 0 && <tr><td colSpan={3} className="muted">None out</td></tr>}
        {top.map((r) => (
          <tr key={r.id} style={r.id === highlight ? { background: "var(--brand-soft)" } : undefined}>
            <td>{r.id}{r.id === highlight ? " (you)" : ""}</td>
            <td className="num">{fmt.n(r.out)} / {fmt.n(r.customers)}</td><td className="num"><b>{r.pct_out}%</b></td></tr>
        ))}
        {mine && !top.includes(mine) && (
          <tr style={{ background: "var(--brand-soft)" }}><td>{mine.id} (you)</td>
            <td className="num">{fmt.n(mine.out)} / {fmt.n(mine.customers)}</td><td className="num"><b>{mine.pct_out}%</b></td></tr>
        )}
      </tbody>
    </table>
  );
}
