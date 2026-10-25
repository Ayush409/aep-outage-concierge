import test from "node:test";
import assert from "node:assert/strict";
import { offlinePlan } from "./offlinePlan.js";

const status = { scenario: { name: "<script>alert(1)</script>", kind: "scenario" }, generated_at: 1,
  address: "Private address", restoration: { p10: 4, p90: 12 },
  checklist: [{ text: "Charge devices", group: "now", done: true }, { text: "Private needs guidance", group: "your_needs" }],
  preparation: { emergency: ["Emergency information"] } };
test("offline plan has no external resources and excludes personal details by default", () => {
  const html = offlinePlan(status);
  assert.ok(!html.includes("Private address"));
  assert.ok(!html.includes("Private needs guidance"));
  assert.ok(!html.includes("<script>"));
  assert.match(html, /&lt;script&gt;/);
  assert.ok(!/https?:\/\//.test(html));
  assert.match(html, /not a live outage update/);
  assert.match(html, /Practice simulation/);
});
test("personal details are included only with explicit options", () => {
  const html = offlinePlan(status, { includeAddress: true, includeNeeds: true });
  assert.match(html, /Private address/);
  assert.match(html, /Private needs guidance/);
});
