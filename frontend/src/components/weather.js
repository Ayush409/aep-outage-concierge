// Weather grid (7 x 6 points at 0.1 deg) -> map layers.
// Wind: direction arrows colored by meaningful thresholds. Temperature / feels like / humidity: a strong color
// ramp stretched over the values present right now, plus the actual numbers printed at each grid point.
import { BitmapLayer, LineLayer, TextLayer } from "@deck.gl/layers";

// The API says which grid it sent (the map display grid covers everything customers can pan to).
const MODEL_GRID = { nx: 7, ny: 6, lon0: -80.25, lat0: 37.0, step: 0.1 };
export const gridOf = (weather) => weather?.grid || MODEL_GRID;
export function boundsOf(weather) {
  const g = gridOf(weather);
  const h = g.step / 2;
  return [g.lon0 - h, g.lat0 - h, g.lon0 + (g.nx - 1) * g.step + h, g.lat0 + (g.ny - 1) * g.step + h];
}
// service area (where the 3D simulation's wind streaks live)
export const BOUNDS = boundsOf({ grid: MODEL_GRID });

// Temperature: one fixed scale from -40 F to 120 F (same color = same temperature, every hour and storm),
// anchored at meaningful temperatures so nearby values still separate. Humidity: sequential blue.
export const TEMP_STOPS = [
  [-40, "#3b0f70"], [-20, "#2c2f8f"], [0, "#1c5cab"], [20, "#3987e5"], [32, "#9ec5f4"], [45, "#d6ecd2"],
  [60, "#f6e8a6"], [75, "#f4b25e"], [90, "#e34948"], [105, "#a32a2a"], [120, "#5c0a0a"],
];
export const TEMP_TICKS = [-40, 0, 32, 60, 90, 120];
function stopsToRamp(stops) {
  const out = [];
  for (let t = stops[0][0]; t <= stops[stops.length - 1][0]; t += 1) {
    const i = Math.max(stops.findIndex(([v]) => v >= t), 1);
    const [t0, c0] = stops[i - 1];
    const [t1, c1] = stops[i];
    const f = (t - t0) / (t1 - t0);
    const a = hex(c0);
    const b = hex(c1);
    out.push(`#${a.map((v, k) => Math.round(v + (b[k] - v) * f).toString(16).padStart(2, "0")).join("")}`);
  }
  return out;
}
const BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];

// gust thresholds: what each gust means for the grid and for crews
export const WIND_BANDS = [
  { max: 20, color: [12, 163, 12], label: "Under 20 mph", note: "light" },
  { max: 28, color: [230, 160, 0], label: "20-28 mph", note: "breezy" },
  { max: 45, color: [236, 110, 60], label: "28-45 mph", note: "bucket trucks slow at 28, stop at 30" },
  { max: Infinity, color: [208, 40, 40], label: "45+ mph", note: "damaging" },
];
// sustained-wind thresholds (steady wind runs 2-3x lower than gusts): NWS wind advisory 31+, high wind warning 40+
export const SPEED_BANDS = [
  { max: 15, color: [12, 163, 12], label: "Under 15 mph", note: "light" },
  { max: 30, color: [230, 160, 0], label: "15-30 mph", note: "breezy" },
  { max: 40, color: [236, 110, 60], label: "30-40 mph", note: "strong - wind advisory" },
  { max: Infinity, color: [208, 40, 40], label: "40+ mph", note: "damaging - high wind warning" },
];

export const LAYERS = {
  wind_gusts_10m: { label: "Wind gusts", unit: "mph", kind: "wind", bands: WIND_BANDS, full: 60 },
  wind_speed_10m: { label: "Wind speed", unit: "mph", kind: "wind", bands: SPEED_BANDS, full: 45 },
  temperature_2m: { label: "Temperature", unit: "°F", kind: "field", stops: TEMP_STOPS, fixed: [-40, 120],
    ticks: TEMP_TICKS },
  apparent_temperature: { label: "Feels like", unit: "°F", kind: "field", stops: TEMP_STOPS, fixed: [-40, 120],
    ticks: TEMP_TICKS },
  // fixed 0-100% so the same blue always means the same humidity
  relative_humidity_2m: { label: "Humidity", unit: "%", kind: "field", fixed: [0, 100], ticks: [0, 25, 50, 75, 100],
    stops: BLUE.map((c, i) => [Math.round((100 * i) / (BLUE.length - 1)), c]) },
};

function hex(h) {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}

for (const spec of Object.values(LAYERS)) if (spec.stops) spec.ramp = stopsToRamp(spec.stops);

export function rampColor(ramp, t) {
  const x = Math.min(Math.max(t, 0), 1) * (ramp.length - 1);
  const i = Math.min(Math.floor(x), ramp.length - 2);
  const a = hex(ramp[i]);
  const b = hex(ramp[i + 1]);
  const f = x - i;
  return a.map((v, k) => Math.round(v + (b[k] - v) * f));
}

export function rampCss(ramp, stops) {
  if (stops) {
    const lo = stops[0][0];
    const span = stops[stops.length - 1][0] - lo;
    return `linear-gradient(90deg, ${stops.map(([v, c]) => `${c} ${((100 * (v - lo)) / span).toFixed(1)}%`).join(", ")})`;
  }
  return `linear-gradient(90deg, ${ramp.join(", ")})`;
}

export function windColor(speed, bands = WIND_BANDS) {
  return bands.find((b) => speed < b.max).color;
}

function hourValues(weather, key, hourIdx) {
  return weather.vars[key].map((series) => series[Math.min(hourIdx, series.length - 1)]);
}

/** Color range for a field layer at this hour: the values present now, widened to a minimum span. */
export function fieldRange(weather, key, hourIdx) {
  const spec = LAYERS[key];
  if (spec.fixed) return spec.fixed;
  const vals = hourValues(weather, key, hourIdx);
  let lo = Math.floor(Math.min(...vals));
  let hi = Math.ceil(Math.max(...vals));
  if (hi - lo < spec.minSpan) {
    const mid = (hi + lo) / 2;
    lo = Math.round(mid - spec.minSpan / 2);
    hi = Math.round(mid + spec.minSpan / 2);
  }
  if (spec.lo != null) lo = Math.max(lo, spec.lo);
  if (spec.hi != null) hi = Math.min(hi, spec.hi);
  return [lo, hi];
}

function gridImage(values, ramp, lo, hi, g) {
  const { nx: NX, ny: NY } = g;
  const W = NX * 20;
  const H = NY * 20;
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(W, H);
  for (let py = 0; py < H; py++) {
    const gy = ((H - 1 - py) / (H - 1)) * NY - 0.5; // image rows go north -> south
    for (let px = 0; px < W; px++) {
      const gx = (px / (W - 1)) * NX - 0.5;
      const x0 = Math.max(0, Math.min(NX - 2, Math.floor(gx)));
      const y0 = Math.max(0, Math.min(NY - 2, Math.floor(gy)));
      const fx = Math.max(0, Math.min(1, gx - x0));
      const fy = Math.max(0, Math.min(1, gy - y0));
      const v = values[y0 * NX + x0] * (1 - fx) * (1 - fy) + values[y0 * NX + x0 + 1] * fx * (1 - fy) +
        values[(y0 + 1) * NX + x0] * (1 - fx) * fy + values[(y0 + 1) * NX + x0 + 1] * fx * fy;
      const [r, g, b] = rampColor(ramp, (v - lo) / Math.max(hi - lo, 1e-6));
      const k = (py * W + px) * 4;
      img.data[k] = r;
      img.data[k + 1] = g;
      img.data[k + 2] = b;
      img.data[k + 3] = 185;
    }
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

/** Wind as arrows on a fine grid: direction = where the wind blows to, length + color = speed. */
function windArrows(weather, key, hourIdx, id) {
  const spacing = 0.04;
  const lines = [];
  const B = boundsOf(weather);
  for (let lat = B[1] + spacing / 2; lat < B[3]; lat += spacing) {
    for (let lon = B[0] + spacing / 2; lon < B[2]; lon += spacing) {
      const spd = sample(weather, key, hourIdx, lon, lat);
      const [u, v] = windVector(weather, hourIdx, lon, lat); // unit vector the wind blows toward
      const len = spacing * (0.2 + (Math.min(spd, LAYERS[key].full) / LAYERS[key].full) * 0.35);
      const dx = (u * len) / Math.cos((lat * Math.PI) / 180);
      const dy = v * len;
      const tail = [lon - dx / 2, lat - dy / 2];
      const head = [lon + dx / 2, lat + dy / 2];
      const color = windColor(spd, LAYERS[key].bands);
      const hl = 0.35; // arrowhead size relative to shaft
      const back = [head[0] - dx * hl, head[1] - dy * hl];
      const px = (-dy * hl * 0.6) / Math.cos((lat * Math.PI) / 180);
      const py = dx * hl * 0.6 * Math.cos((lat * Math.PI) / 180);
      lines.push({ s: tail, t: head, color, spd });
      lines.push({ s: head, t: [back[0] + px, back[1] + py], color, spd });
      lines.push({ s: head, t: [back[0] - px, back[1] - py], color, spd });
    }
  }
  return new LineLayer({
    id, data: lines, getSourcePosition: (d) => d.s, getTargetPosition: (d) => d.t,
    getColor: (d) => [...d.color, 235], getWidth: (d) => (d.color !== LAYERS[key].bands[0].color ? 1.8 : 1.3),
    widthUnits: "pixels",
  });
}

/** Unit vector (east, north) the wind blows toward, interpolated through u/v so directions blend correctly. */
function windVector(weather, hourIdx, lon, lat) {
  const { nx: NX, ny: NY, lon0: LON0, lat0: LAT0, step: STEP } = gridOf(weather);
  const gx = Math.max(0, Math.min(NX - 1.0001, (lon - LON0) / STEP));
  const gy = Math.max(0, Math.min(NY - 1.0001, (lat - LAT0) / STEP));
  const x0 = Math.floor(gx);
  const y0 = Math.floor(gy);
  const fx = gx - x0;
  const fy = gy - y0;
  const spd = weather.vars.wind_speed_10m;
  const dir = weather.vars.wind_direction_10m;
  const h = Math.min(hourIdx, dir[0].length - 1);
  let u = 0;
  let v = 0;
  for (const [ix, iy, w] of [[x0, y0, (1 - fx) * (1 - fy)], [x0 + 1, y0, fx * (1 - fy)], [x0, y0 + 1, (1 - fx) * fy],
    [x0 + 1, y0 + 1, fx * fy]]) {
    const k = iy * NX + ix;
    const to = ((dir[k][h] + 180) * Math.PI) / 180; // meteorological "from" -> "toward"
    const s = Math.max(spd[k][h], 0.1);
    u += w * s * Math.sin(to);
    v += w * s * Math.cos(to);
  }
  const n = Math.hypot(u, v) || 1;
  return [u / n, v / n];
}

/** Layers for the chosen weather variable (an array; deck.gl flattens nested layer arrays). */
export function weatherLayer(weather, key, hourIdx, visible = true) {
  if (!weather || !key || !visible) return null;
  const spec = LAYERS[key];
  const id = `wx-${key}`;
  if (spec.kind === "wind") return windArrows(weather, key, hourIdx, id);
  const [lo, hi] = fieldRange(weather, key, hourIdx);
  const vals = hourValues(weather, key, hourIdx);
  const g = gridOf(weather);
  const pts = vals.map((v, i) => ({ v, lon: g.lon0 + (i % g.nx) * g.step, lat: g.lat0 + Math.floor(i / g.nx) * g.step }));
  return [
    new BitmapLayer({ id, bounds: boundsOf(weather), image: gridImage(vals, spec.ramp, lo, hi, g), opacity: 0.75 }),
    new TextLayer({
      id: `${id}-values`, data: pts, getPosition: (d) => [d.lon, d.lat], getText: (d) => `${Math.round(d.v)}`,
      getSize: 13, fontWeight: 700, getColor: [20, 20, 20], background: true, getBackgroundColor: [255, 255, 255, 215],
      backgroundPadding: [3, 1], fontFamily: "Inter, system-ui, sans-serif",
    }),
  ];
}

/** Bilinear sample of a weather variable at lon/lat (for particles and tooltips). */
export function sample(weather, key, hourIdx, lon, lat) {
  const { nx: NX, ny: NY, lon0: LON0, lat0: LAT0, step: STEP } = gridOf(weather);
  const gx = Math.max(0, Math.min(NX - 1.0001, (lon - LON0) / STEP));
  const gy = Math.max(0, Math.min(NY - 1.0001, (lat - LAT0) / STEP));
  const x0 = Math.floor(gx);
  const y0 = Math.floor(gy);
  const fx = gx - x0;
  const fy = gy - y0;
  const s = weather.vars[key];
  const h = Math.min(hourIdx, s[0].length - 1);
  const v = (ix, iy) => s[iy * NX + ix][h];
  return v(x0, y0) * (1 - fx) * (1 - fy) + v(x0 + 1, y0) * fx * (1 - fy) + v(x0, y0 + 1) * (1 - fx) * fy +
    v(x0 + 1, y0 + 1) * fx * fy;
}

export function nowIndex(weather) {
  const now = Date.now();
  const i = weather.time.findIndex((t) => new Date(t).getTime() > now);
  return Math.max(0, i < 0 ? weather.time.length - 1 : i - 1);
}

export function compassName(deg) {
  return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(((deg % 360) + 360) % 360 / 45) % 8];
}
