import { useEffect, useMemo, useState } from "react";
import { PolygonLayer, ScatterplotLayer } from "@deck.gl/layers";
import { BAND_RGB, fmt, qs } from "../api.js";
import { useApp } from "../App.jsx";
import MapView, { squarePolygon } from "../components/MapView.jsx";
import { nowIndex, sample, weatherLayer } from "../components/weather.js";
import { Band, BandLegend, bandOutcomeText, WeatherControls, useFetch } from "../components/ui.jsx";

export default function CustomerMap() {
  const { scenario } = useApp();
  const [layer, setLayer] = useState("wind_gusts_10m");
  const [hour, setHour] = useState(0);
  const [showRisk, setShowRisk] = useState(true);
  const [showOut, setShowOut] = useState(true);
  const weather = useFetch(scenario ? `/api/weather${qs({ scenario })}` : null, [scenario]).data;
  const cells = useFetch(scenario ? `/api/sim/cells${qs({ scenario })}` : null, [scenario]).data;
  const frames = useFetch(scenario ? `/api/sim/frames${qs({ scenario })}` : null, [scenario]).data;
  const status = useFetch(scenario ? `/api/me/status${qs({ scenario })}` : null, [scenario]).data;

  useEffect(() => {
    if (!weather) return;
    if (scenario === "live") setHour(nowIndex(weather));
    else {
      const g = weather.vars.wind_gusts_10m;
      let best = 0;
      let bv = -1;
      for (let t = 0; t < g[0].length; t++) {
        const m = Math.max(...g.map((s) => s[t]));
        if (m > bv) { bv = m; best = t; }
      }
      setHour(best);
    }
  }, [weather, scenario]);

  const outNow = useMemo(() => {
    if (!frames?.cells?.length) return [];
    const step = frames.hours[1] - frames.hours[0] || 1;
    const fi = Math.min(Math.round(hour / step), frames.hours.length - 1);
    return frames.cells.map((c, i) => ({ ...c, out: frames.out[i][fi] })).filter((c) => c.out >= 5);
  }, [frames, hour]);

  const layers = [
    weatherLayer(weather, layer, hour, !!layer),
    showRisk && cells && new PolygonLayer({
      id: "risk", data: cells, getPolygon: (d) => squarePolygon(d.lon, d.lat), pickable: true,
      getFillColor: (d) => [...BAND_RGB[d.band], d.band === "Low" ? 0 : 60], stroked: true,
      getLineColor: (d) => [...BAND_RGB[d.band], d.band === "Low" ? 0 : 160], lineWidthMinPixels: 1,
    }),
    showOut && new ScatterplotLayer({
      id: "out", data: outNow, getPosition: (d) => [d.lon, d.lat], getRadius: (d) => 120 + Math.sqrt(d.out) * 40,
      radiusUnits: "meters", getFillColor: [208, 59, 59, 150], stroked: true, getLineColor: [255, 255, 255],
      lineWidthMinPixels: 1.5, pickable: true, updateTriggers: { getRadius: hour },
    }),
    status?.home && new ScatterplotLayer({
      id: "home", data: [status.home], getPosition: (d) => [d.lon, d.lat], getRadius: 9, radiusUnits: "pixels",
      getFillColor: [11, 61, 145], stroked: true, getLineColor: [255, 255, 255], lineWidthMinPixels: 3,
    }),
  ];

  function tooltip({ object, layer: l, coordinate }) {
    if (!object && !coordinate) return null;
    if (l?.id === "risk") {
      const seen = bandOutcomeText(object.observed);
      return { html: `<b>${object.band} risk</b>${seen ? `<br/><span class="muted">${seen}</span>` : ""}<br/>` +
        `${object.factors.join("<br/>") || "No strong weather drivers"}`, className: "tooltip" };
    }
    if (l?.id === "out") return { html: `<b>${fmt.n(object.out)} customers out</b> in this area`, className: "tooltip" };
    return null;
  }

  return (
    <div className="page full">
      <MapView layers={layers} getTooltip={tooltip} focus={status?.home ? [status.home.lon, status.home.lat] : null}
        zoom={10.5}>
        <div className="map-panel tl stack">
          {status && <div className="row"><span className="small secondary">Your risk</span><Band band={status.risk.band} />
            <span className="small muted">{status.premise.city} {status.premise.zip}</span></div>}
          <WeatherControls layer={layer} setLayer={setLayer} weather={weather} hour={hour} setHour={setHour} />
          {weather && layer && <div className="small secondary">At your home: <b>
            {status?.home ? `${Math.round(sample(weather, layer, hour, status.home.lon, status.home.lat))}` : "-"}
          </b></div>}
        </div>
        <div className="map-panel bl stack small">
          <label className="check"><input type="checkbox" checked={showRisk} onChange={(e) => setShowRisk(e.target.checked)} />
            <span>Outage risk by area</span></label>
          {showRisk && <BandLegend />}
          <label className="check"><input type="checkbox" checked={showOut} onChange={(e) => setShowOut(e.target.checked)} />
            <span>Areas without power at this time (5+ customers)</span></label>
          <div className="muted">Outages are shown by area, never by individual home. The blue dot is your home.</div>
        </div>
      </MapView>
    </div>
  );
}
