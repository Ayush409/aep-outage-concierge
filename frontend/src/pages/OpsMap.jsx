import { useEffect, useMemo, useState } from "react";
import { PolygonLayer, ScatterplotLayer } from "@deck.gl/layers";
import { BAND_RGB, fmt, hourLabel, qs } from "../api.js";
import { useApp } from "../App.jsx";
import MapView, { squarePolygon } from "../components/MapView.jsx";
import { weatherLayer } from "../components/weather.js";
import { BandLegend, Stat, WeatherControls, useFetch } from "../components/ui.jsx";

const FAC = { hospital: [208, 59, 59], fire: [235, 104, 52], ems: [98, 80, 214] };

export default function OpsMap() {
  const { scenario } = useApp();
  const q = scenario ? qs({ scenario }) : null;
  const cells = useFetch(q && `/api/sim/cells${q}`, [q]).data;
  const pins = useFetch(q && `/api/aep/pins${q}`, [q]).data;
  const frames = useFetch(q && `/api/sim/frames${q}`, [q]).data;
  const overview = useFetch(q && `/api/sim/overview${q}`, [q]).data;
  const fac = useFetch("/api/aep/facilities").data;
  const weather = useFetch(scenario ? `/api/weather${qs({ scenario })}` : null, [scenario]).data;
  const [hour, setHour] = useState(0);
  const [wxLayer, setWxLayer] = useState(null);
  const [show, setShow] = useState({ risk: true, pins: true, fac: true });
  const [areaHour, setAreaHour] = useState(null);
  const areas = useFetch(q && `/api/aep/areas${qs({ scenario, hour: areaHour ?? undefined })}`, [q, areaHour]).data;

  // start at the peak outage hour
  useEffect(() => {
    if (!overview?.curve?.hours?.length) return;
    const i = overview.curve.p50.indexOf(Math.max(...overview.curve.p50));
    setHour(overview.curve.hours[i]);
  }, [overview]);
  useEffect(() => {
    const t = setTimeout(() => setAreaHour(Math.round(hour)), 250);
    return () => clearTimeout(t);
  }, [hour]);

  const maxH = frames?.hours?.length ? frames.hours.length - 1 : 0;
  const wxStep = weather && weather.time.length > 1 ? (new Date(weather.time[1]) - new Date(weather.time[0])) / 3.6e6 : 1;
  const wxIdx = Math.min(Math.floor(hour / wxStep), (weather?.time.length || 1) - 1);
  const state = (p) => (p.out_at > hour ? "pending" : p.restored_at <= hour ? "restored" : "out");
  const outNow = useMemo(() => (pins || []).filter((p) => state(p) === "out").reduce((a, p) => a + p.customers, 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pins, hour]);

  const layers = [
    weatherLayer(weather, wxLayer, wxIdx, !!wxLayer),
    show.risk && cells && new PolygonLayer({
      id: "risk", data: cells, getPolygon: (d) => squarePolygon(d.lon, d.lat), stroked: true, pickable: true,
      getLineColor: (d) => [...BAND_RGB[d.band], d.band === "Low" ? 0 : 150], lineWidthMinPixels: 1,
      getFillColor: (d) => [...BAND_RGB[d.band], d.band === "Low" ? 0 : 45],
    }),
    show.pins && pins && new ScatterplotLayer({
      id: "pins", data: pins, pickable: true, radiusUnits: "pixels", stroked: true, lineWidthMinPixels: 1,
      getPosition: (d) => [d.lon, d.lat], getRadius: (d) => 3 + Math.sqrt(d.customers) / 2.5,
      getFillColor: (d) => ({ out: [208, 59, 59, 230], restored: [12, 163, 12, 200], pending: [150, 150, 150, 120] })[state(d)],
      getLineColor: [255, 255, 255], updateTriggers: { getFillColor: hour },
    }),
    show.fac && fac && new ScatterplotLayer({
      id: "fac", data: fac, pickable: true, radiusUnits: "pixels", getRadius: 6, stroked: true,
      getPosition: (d) => [d.lon, d.lat], getFillColor: (d) => FAC[d.kind], getLineColor: [255, 255, 255],
      lineWidthMinPixels: 2,
    }),
  ];

  function tooltip({ object, layer }) {
    if (!object) return null;
    if (layer.id === "pins") {
      return { className: "tooltip", html: `<b>${object.kind} - ${fmt.n(object.customers)} customers</b><br/>` +
        `Out ${hourLabel(frames?.start, object.out_at)}<br/>Restored ${hourLabel(frames?.start, object.restored_at)}` +
        (object.life_support ? `<br/>${object.life_support} life-support premise(s)` : "") };
    }
    if (layer.id === "fac") return { className: "tooltip", html: `<b>${object.name}</b><br/>${object.kind.toUpperCase()}` };
    if (layer.id === "risk") {
      return { className: "tooltip", html: `<b>${object.band}</b> - ${fmt.pct(object.p_out)} of ${fmt.n(object.customers)} ` +
        `customers<br/>Expected damage ${object.exp_damage}<br/>Gust ${object.gust} mph, ice ${object.ice} in<br/>` +
        `${object.factors.join("<br/>")}` };
    }
    return null;
  }

  const s = overview?.summary;
  return (
    <div className="page full">
      <MapView layers={layers} getTooltip={tooltip}>
        <div className="map-panel tl stack" style={{ width: 340 }}>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <Stat label="Out at this hour" value={fmt.n(outNow)} />
            <Stat label="Expected out (event)" value={fmt.n(s?.expected_customers_out)}
              sub={s ? `of ${fmt.n(s.total_customers)}` : ""} />
          </div>
          {frames && (
            <div className="slider">
              <span className="small">Event time</span><b className="small">{hourLabel(frames.start, hour)}</b>
              <input type="range" min={0} max={maxH} value={hour} onChange={(e) => setHour(+e.target.value)}
                aria-label="Event hour" />
            </div>
          )}
          <WeatherControls layer={wxLayer} setLayer={setWxLayer} />
          <div className="small stack">
            {[["risk", "Risk by area"], ["pins", "Outage devices (red out, green restored)"], ["fac", "Hospitals / fire / EMS"]]
              .map(([k, l]) => (
                <label key={k} className="check"><input type="checkbox" checked={show[k]}
                  onChange={(e) => setShow({ ...show, [k]: e.target.checked })} /><span>{l}</span></label>
              ))}
            <BandLegend />
          </div>
        </div>
        <div className="map-panel tr stack" style={{ width: 300, maxHeight: "calc(100% - 60px)", overflow: "auto" }}>
          <h3 style={{ margin: 0 }}>% without power</h3>
          <div className="small muted">At {frames ? hourLabel(frames.start, areas?.hour ?? hour) : "-"} (AEP customers in this
            data set; areas under 5 customers hidden)</div>
          <AreaTable title="ZIP code" rows={areas?.zip} />
          <AreaTable title="Circuit" rows={areas?.circuit} />
        </div>
      </MapView>
    </div>
  );
}

function AreaTable({ title, rows }) {
  if (!rows) return null;
  const top = rows.filter((r) => r.out > 0).slice(0, 8);
  return (
    <table>
      <thead><tr><th>{title}</th><th className="num">Out</th><th className="num">%</th></tr></thead>
      <tbody>
        {top.length === 0 && <tr><td colSpan={3} className="muted">None out</td></tr>}
        {top.map((r) => (
          <tr key={r.id}><td>{r.id}</td><td className="num">{fmt.n(r.out)} / {fmt.n(r.customers)}</td>
            <td className="num"><b>{r.pct_out}%</b></td></tr>
        ))}
      </tbody>
    </table>
  );
}
