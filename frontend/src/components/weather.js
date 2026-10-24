// Weather grid (7 x 6 points at 0.1 deg) -> smooth image for a deck.gl BitmapLayer.
import { BitmapLayer } from "@deck.gl/layers";

export const NX = 7;
export const NY = 6;
export const LON0 = -80.25;
export const LAT0 = 37.0;
export const STEP = 0.1;
export const BOUNDS = [LON0 - 0.05, LAT0 - 0.05, LON0 + (NX - 1) * STEP + 0.05, LAT0 + (NY - 1) * STEP + 0.05];

// sequential blue (reference ramp) and diverging blue <-> red with gray midpoint
const BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const DIVERGING = ["#184f95", "#3987e5", "#9ec5f4", "#f0efec", "#f3a3a2", "#e34948", "#a32a2a"];

export const LAYERS = {
  temperature_2m: { label: "Temperature", unit: "°F", ramp: DIVERGING, min: 0, max: 110 },
  apparent_temperature: { label: "Feels like", unit: "°F", ramp: DIVERGING, min: 0, max: 115 },
  wind_gusts_10m: { label: "Wind gusts", unit: "mph", ramp: BLUE, min: 0, max: 70 },
  wind_speed_10m: { label: "Wind speed", unit: "mph", ramp: BLUE, min: 0, max: 40 },
  relative_humidity_2m: { label: "Humidity", unit: "%", ramp: BLUE, min: 0, max: 100 },
};

function hex(h) {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}

export function rampColor(ramp, t) {
  const x = Math.min(Math.max(t, 0), 1) * (ramp.length - 1);
  const i = Math.min(Math.floor(x), ramp.length - 2);
  const a = hex(ramp[i]);
  const b = hex(ramp[i + 1]);
  const f = x - i;
  return a.map((v, k) => Math.round(v + (b[k] - v) * f));
}

export function rampCss(ramp) {
  return `linear-gradient(90deg, ${ramp.join(", ")})`;
}

/** values: array of 42 numbers (lat-major). Returns an ImageData-backed canvas. */
export function gridImage(values, key) {
  const spec = LAYERS[key];
  const W = 140;
  const H = 120;
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(W, H);
  for (let py = 0; py < H; py++) {
    // image rows go north -> south
    const gy = ((H - 1 - py) / (H - 1)) * (NY - 1 + 1) - 0.5;
    for (let px = 0; px < W; px++) {
      const gx = (px / (W - 1)) * (NX - 1 + 1) - 0.5;
      const x0 = Math.max(0, Math.min(NX - 2, Math.floor(gx)));
      const y0 = Math.max(0, Math.min(NY - 2, Math.floor(gy)));
      const fx = Math.max(0, Math.min(1, gx - x0));
      const fy = Math.max(0, Math.min(1, gy - y0));
      const v00 = values[y0 * NX + x0];
      const v10 = values[y0 * NX + x0 + 1];
      const v01 = values[(y0 + 1) * NX + x0];
      const v11 = values[(y0 + 1) * NX + x0 + 1];
      const v = v00 * (1 - fx) * (1 - fy) + v10 * fx * (1 - fy) + v01 * (1 - fx) * fy + v11 * fx * fy;
      const [r, g, b] = rampColor(spec.ramp, (v - spec.min) / (spec.max - spec.min));
      const k = (py * W + px) * 4;
      img.data[k] = r;
      img.data[k + 1] = g;
      img.data[k + 2] = b;
      img.data[k + 3] = 120;
    }
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

export function weatherLayer(weather, key, hourIdx, visible = true) {
  if (!weather || !key) return null;
  const vals = weather.vars[key].map((series) => series[Math.min(hourIdx, series.length - 1)]);
  return new BitmapLayer({
    id: `wx-${key}`,
    bounds: BOUNDS,
    image: gridImage(vals, key),
    visible,
    opacity: 0.6,
    updateTriggers: { image: [key, hourIdx] },
  });
}

/** Bilinear sample of a weather variable at lon/lat (for particles and tooltips). */
export function sample(weather, key, hourIdx, lon, lat) {
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
