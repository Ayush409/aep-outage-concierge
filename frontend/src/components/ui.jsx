import { useEffect, useState } from "react";
import { api, BAND_COLOR, BANDS, fmt, qs } from "../api.js";
import { useApp } from "../App.jsx";
import { fieldRange, LAYERS, rampCss, WIND_BANDS } from "./weather.js";

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
  return `Exploratory pooled topology proxy from ${o.storms} hold-out event(s): ${fmt.pct(o.share)}. Not a validated outage probability.`;
}

export function BandLegend() {
  const { bandOutcomes } = useApp();
  return (
    <div className="stack" style={{ gap: 4 }}>
      <div className="row small" aria-label="Risk bands">
        {BANDS.map((b) => (
          <span key={b} className="row" style={{ gap: 4 }} title={bandOutcomeText(bandOutcomes?.[b]) || undefined}>
            <i style={{ width: 10, height: 10, borderRadius: 3, background: BAND_COLOR[b], display: "inline-block" }} />
            {b}
          </span>
        ))}
      </div>
      <div className="small muted">Experimental planning bands. Hold-out tests do not validate them as outage probabilities.</div>
    </div>
  );
}

/** delta: optional { text, tone: "good" | "bad" | "same" } - change since the previous run */
export function Stat({ label, value, sub, delta }) {
  return (
    <div className="card stat">
      <div className="l">{label}</div>
      <div className="v">{value}</div>
      {delta && <div className={`delta ${delta.tone}`}>{delta.text}</div>}
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

export function WeatherControls({ layer, setLayer, weather, hour, setHour, legendWeather, legendHour }) {
  const weatherSrc = weather || legendWeather;
  const wxHour = weather ? hour : legendHour ?? 0;
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
      {spec?.kind === "wind" && (
        <div className="stack" style={{ gap: 3 }}>
          {(spec.bands || WIND_BANDS).map((b) => (
            <div key={b.label} className="legend-row">
              <span aria-hidden="true" style={{ color: `rgb(${b.color.join(",")})`, fontWeight: 700 }}>➜</span>
              <b>{b.label}</b><span className="muted">{b.note}</span>
            </div>
          ))}
          <div className="small muted">Arrows point where the wind is blowing; longer = stronger.
            {layer === "wind_speed_10m" && " Steady wind is the forecast value or gust ÷ 1.6, whichever is higher."}</div>
        </div>
      )}
      {spec?.kind === "field" && (() => {
        const [lo, hi] = weatherSrc ? fieldRange(weatherSrc, layer, wxHour) : [null, null];
        return (
          <div className="stack" style={{ gap: 3 }}>
            {spec.fixed ? (
              <div style={{ width: 240 }}>
                <span className="ramp" style={{ display: "block", width: "100%", background: rampCss(null, spec.stops) }} />
                <div style={{ position: "relative", height: 14 }} className="small">
                  {spec.ticks.map((t) => (
                    <span key={t} style={{ position: "absolute", transform: "translateX(-50%)",
                      left: `${(100 * (t - spec.fixed[0])) / (spec.fixed[1] - spec.fixed[0])}%` }}>{t}</span>
                  ))}
                </div>
              </div>
            ) : (
              <div className="legend-row">
                <span>{lo ?? ""}</span>
                <span className="ramp" style={{ background: rampCss(spec.ramp) }} />
                <span>{hi ?? ""} {spec.unit}</span>
              </div>
            )}
            <div className="small muted">{spec.fixed ? `Fixed scale, ${spec.fixed[0]} to ${spec.fixed[1]} ${spec.unit}`
              : "Colors stretch over the values right now"};
              numbers on the map are exact.</div>
          </div>
        );
      })()}
      {weather && <TimeSlider times={weather.time} hour={hour} setHour={setHour} />}
    </div>
  );
}


function relTime(ms) {
  const h = Math.round(ms / 3.6e6);
  if (h === 0) return "now";
  const a = Math.abs(h);
  const txt = a < 24 ? `${a} h` : `${Math.floor(a / 24)} day${a >= 48 ? "s" : ""}${a % 24 ? ` ${a % 24} h` : ""}`;
  return h < 0 ? `${txt} ago` : `in ${txt}`;
}

/** Hour slider with day markers; for the live forecast also a "Now" marker, greyed past and "Forecast" ahead. */
export function TimeSlider({ times, hour, setHour }) {
  const n = times.length;
  const ms = times.map((t) => new Date(t).getTime());
  const now = Date.now();
  const live = now >= ms[0] && now <= ms[n - 1] + 3.6e6;
  const nowIdx = live ? Math.max(0, ms.findIndex((t) => t > now) - 1) : null;
  const pct = (i) => `${(100 * i) / Math.max(n - 1, 1)}%`;
  const allDays = ms.map((t, i) => [t, i]).filter(([t]) => new Date(t).getHours() === 0);
  const days = allDays.filter((_, i) => i % Math.max(1, Math.ceil(allDays.length / 4)) === 0);
  const sel = new Date(ms[hour]);
  return (
    <div className="stack" style={{ gap: 4 }}>
      <div className="row spread small">
        <span>Time</span>
        <span>
          <b>{sel.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric" })}</b>
          {live && <span className="muted"> ({relTime(ms[hour] - now)})</span>}
        </span>
      </div>
      <div style={{ position: "relative", paddingTop: 2 }}>
        {live && (
          <>
            <div aria-hidden="true" style={{ position: "absolute", left: 0, width: pct(nowIdx), top: 6, height: 8,
              background: "var(--border)", borderRadius: 4, opacity: 0.9 }} />
            <div aria-hidden="true" style={{ position: "absolute", left: pct(nowIdx), top: 0, bottom: 0, width: 2,
              background: "var(--band-severe)", transform: "translateX(-1px)" }} />
          </>
        )}
        <input className="time-range" type="range" min={0} max={n - 1} step={1} value={hour} onChange={(e) => setHour(+e.target.value)}
          aria-label="Map timeline hour" aria-valuetext={sel.toLocaleString()} style={{ position: "relative", width: "100%" }} />
        <div aria-hidden="true" style={{ position: "relative", height: 14 }} className="small muted">
          {days.map(([t, i]) => (
            <span key={i} style={{ position: "absolute", left: pct(i), transform: i < n * .1 ? "none" : i > n * .9 ? "translateX(-100%)" : "translateX(-50%)", whiteSpace: "nowrap",
              fontSize: 11 }}>
              <span style={{ display: "block", width: 1, height: 4, background: "var(--text-muted)", margin: "0 auto" }} />
              {new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </span>
          ))}
        </div>
      </div>
      <div className="row spread small muted">
        <span>{new Date(ms[0]).toLocaleDateString()}</span>
        <span>{new Date(ms[n - 1]).toLocaleDateString()}</span>
      </div>
      {live && (
        <div className="row spread small">
          <span className="muted">◀ Past</span>
          <button className="chip" onClick={() => setHour(nowIdx)} style={{ color: "var(--band-severe)", fontWeight: 600 }}>
            ● Now</button>
          <span className="muted">Forecast ▶</span>
        </div>
      )}
    </div>
  );
}

/** Animated percentage ring (value 0-1); the arc draws in on mount and when the value changes. */
export function Ring({ value, color, size = 132, stroke = 12, caption }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setShown(value || 0), 60);
    return () => clearTimeout(t);
  }, [value]);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="ring" style={{ width: size, height: size }} role="img"
      aria-label={`${fmt.pct(value)}${caption ? ` ${caption}` : ""}`}>
      <svg width={size} height={size}>
        <circle className="track" cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} />
        <circle className="arc" cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(Math.max(shown, 0), 1))} />
      </svg>
      <div className="center"><div><b>{fmt.pct(value)}</b>{caption && <><br /><span>{caption}</span></>}</div></div>
    </div>
  );
}
