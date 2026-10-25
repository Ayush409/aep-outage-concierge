export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function offlinePlan(status, { includeAddress = false, includeNeeds = false } = {}) {
  const e = escapeHtml;
  const tasks = (status.checklist || []).filter((t) => includeNeeds || t.group !== "your_needs");
  const range = status.restoration ? `${status.restoration.p10}–${status.restoration.p90} hours` : "No duration range available";
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your saved outage plan</title><style>body{font:18px/1.6 system-ui,sans-serif;color:#202020;background:#fff;max-width:800px;margin:auto;padding:24px}h1,h2{line-height:1.2}aside{border:2px solid #a00;padding:16px}li{margin:12px 0}small{color:#555}section{border-top:1px solid #ddd;margin-top:24px;padding-top:16px}@media print{body{font-size:14px}}</style>
<h1>Your saved outage plan</h1><aside><b>Saved information — not a live outage update.</b><br>Calculated ${e(new Date(status.generated_at * 1000).toLocaleString())}. Reconnect to the app for current estimates.</aside>
<p>${e(status.scenario.name)} · ${status.scenario.kind === "live" ? "Forecast-based plan" : "Practice simulation"}</p>
${includeAddress ? `<p><b>Address:</b> ${e(status.address)}</p>` : ""}
<p><b>Modeled outage-duration range:</b> ${e(range)}. Actual restoration may differ.</p>
<p>Experimental model with limited validation. This plan does not confirm an outage or guarantee safety.</p>
<section><h2>Preparation checklist</h2><ul>${tasks.map((t) => `<li>${t.done ? "Completed: " : "To do: "}${e(t.text)}</li>`).join("")}</ul></section>
<section><h2>Emergency information</h2>${status.preparation.emergency.map((t) => `<p>${e(t)}</p>`).join("")}</section>
<section><h2>Using this plan</h2><p>This file opens without internet. It does not refresh or send alerts. Saved copies remain on your device until you delete them.</p></section></html>`;
}
