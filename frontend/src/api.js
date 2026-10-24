// Thin fetch wrapper. Session is an HTTP-only cookie set by the backend.
export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail || res.statusText;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

export function qs(params) {
  const p = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => v !== undefined && v !== null && p.set(k, v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const BAND_COLOR = {
  Low: "var(--band-low)",
  Elevated: "var(--band-elevated)",
  High: "var(--band-high)",
  Severe: "var(--band-severe)",
};
export const BAND_RGB = { Low: [12, 163, 12], Elevated: [250, 178, 25], High: [236, 131, 90], Severe: [208, 59, 59] };
export const BANDS = ["Low", "Elevated", "High", "Severe"];

export const fmt = {
  n: (v) => (v == null ? "-" : Math.round(v).toLocaleString()),
  usd: (v) => {
    if (v == null) return "-";
    if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
    if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(0)}k`;
    return `$${Math.round(v)}`;
  },
  hours: (h) => {
    if (h == null) return "-";
    if (h < 1) return `${Math.max(10, Math.round((h * 60) / 10) * 10)} min`;
    if (h < 48) return `${h < 3 ? h.toFixed(1) : Math.round(h)} h`;
    return `${(h / 24).toFixed(1)} days`;
  },
  pct: (p) => (p == null ? "-" : `${Math.min(99, Math.max(1, Math.round(p * 100)))}%`),
};

export function hourLabel(start, h) {
  const d = new Date(new Date(start).getTime() + h * 3600 * 1000);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" });
}
