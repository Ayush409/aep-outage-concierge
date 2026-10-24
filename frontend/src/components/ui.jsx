import { useEffect, useState } from "react";
import { api, BAND_COLOR, BANDS, fmt, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { LAYERS, rampCss } from "./weather.js";

export function Band({ band, big }) {
  return (
    <span className={`band${big ? " big" : ""}`}>
      <i style={{ background: BAND_COLOR[band] }} aria-hidden="true" />{band}
    </span>
  );
}

/** "In N past storms, about X% of homes in this band lost power" - what the band has meant in practice. */
export function bandOutcomeText(o) {
  if (!o) return null;
  return `In ${o.storms} past storm${o.storms === 1 ? "" : "s"}, about ${fmt.pct(o.share)} of homes in this band lost power`;
}

export function BandLegend() {
  const { bandOutcomes } = useApp();
  return (
    <div className="stack" style={{ gap: 4 }}>
      <div className="row small" aria-label="Risk bands">
        {BANDS.map((b) => (
          <span key={b} className="row" style={{ gap: 4 }} title={bandOutcomeText(bandOutcomes?.[b]) || undefined}>
            <i style={{ width: 10, height: 10, borderRadius: 3, background: BAND_COLOR[b], display: "inline-block" }} />
            {b} {bandOutcomes?.[b] && <span className="muted">~{fmt.pct(bandOutcomes[b].share)}</span>}
          </span>
        ))}
      </div>
      <div className="small muted">% = homes in that band that lost power in past storms</div>
    </div>
  );
}

export function Stat({ label, value, sub }) {
  return (
    <div className="card stat">
      <div className="l">{label}</div>
      <div className="v">{value}</div>
      {sub && <div className="s">{sub}</div>}
    </div>
  );
}

export function Kind({ kind }) {
  const map = { confirmed: "Confirmed", estimate: "Model estimate", action: "What you should do" };
  return <span className={`tag ${kind}`}>{map[kind]}</span>;
}

export function Confidence({ c }) {
  if (!c) return null;
  return (
    <div className="stack small">
      <div><b>Confidence: {c.level}</b></div>
      {c.notes?.map((n, i) => <div key={i} className="secondary">{n}</div>)}
    </div>
  );
}

export function Loading({ what = "Loading" }) {
  return <div className="muted" role="status">{what}...</div>;
}

export function ErrorBox({ error }) {
  return error ? <div className="error" role="alert">{error}</div> : null;
}

/** Fetch JSON and re-fetch when deps change. */
export function useFetch(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    let live = true;
    if (!path) return undefined;
    setState((s) => ({ ...s, loading: true }));
    api(path).then((data) => live && setState({ data, error: null, loading: false }))
      .catch((e) => live && setState({ data: null, error: e.message, loading: false }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  return state;
}

export function simPath(base, scenario, params) {
  return scenario ? `${base}${qs({ scenario, ...params })}` : null;
}

export function WeatherControls({ layer, setLayer, weather, hour, setHour }) {
  const spec = layer ? LAYERS[layer] : null;
  return (
    <div className="stack">
      <div className="small" style={{ fontWeight: 600 }}>Weather layer</div>
      <div className="chips" role="group" aria-label="Weather layer">
        <button className={`chip${!layer ? " on" : ""}`} onClick={() => setLayer(null)}>Off</button>
        {Object.entries(LAYERS).map(([k, v]) => (
          <button key={k} className={`chip${layer === k ? " on" : ""}`} onClick={() => setLayer(k)}>{v.label}</button>
        ))}
      </div>
      {spec && (
        <div className="legend-row">
          <span>{spec.min}</span>
          <span className="ramp" style={{ background: rampCss(spec.ramp) }} />
          <span>{spec.max} {spec.unit}</span>
        </div>
      )}
      {weather && (
        <div className="slider">
          <span className="small">Time</span>
          <b className="small">{new Date(weather.time[hour]).toLocaleString(undefined,
            { weekday: "short", month: "short", day: "numeric", hour: "numeric" })}</b>
          <input type="range" min={0} max={weather.time.length - 1} value={hour}
            onChange={(e) => setHour(+e.target.value)} aria-label="Forecast hour" />
        </div>
      )}
    </div>
  );
}
