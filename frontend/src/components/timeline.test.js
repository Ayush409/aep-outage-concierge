import assert from "node:assert/strict";
import test from "node:test";
import { mapTimes, restorationHour } from "./timeline.js";
import { powerState } from "./powerState.js";

const weather = ["2011-04-27T00:00:00Z", "2011-05-05T00:00:00Z"];
const frames = { start: weather[0], hours: Array.from({ length: 70 }, (_, h) => h) };

test("scenario ends after restoration even when weather extends for several more days", () => {
  const times = mapTimes(weather, frames, false);
  assert.equal(times.length, 70);
  assert.equal(times.at(-1), "2011-04-29T21:00:00.000Z");
});

test("live map retains the forecast window and extends for longer repairs", () => {
  assert.equal(mapTimes(weather, frames, true).length, 193);
  const longFrames = { ...frames, hours: Array.from({ length: 401 }, (_, h) => h) };
  assert.equal(mapTimes(weather, longFrames, true).length, 401);
  assert.equal(mapTimes(weather, longFrames, false).length, 401);
});

test("no-outage scenarios retain a usable weather timeline", () => {
  assert.equal(mapTimes(weather, { hours: [] }, false).length, 193);
  assert.deepEqual(mapTimes([], null), []);
});

test("full restoration follows the last outage, including later recurrences", () => {
  assert.equal(restorationHour([0, 5, 0, 3, 0, 0]), 4);
  assert.equal(restorationHour([0, 3]), null);
  assert.equal(restorationHour([0, 0]), null);
});

const status = {
  start: weather[0], scenario: { kind: "scenario" }, risk: { band: "High" },
  event: { timeline: { power_lost: 5, restored: 68 } },
  // Deliberately different: clock times must use the map outcome, not these medians.
  restoration: { outage_start: 2, restored: 48 },
};

test("historical simulations do not become current restored-power claims", () => {
  const before = powerState(status, Date.parse("2010-01-01"));
  const after = powerState(status, Date.parse("2026-01-01"));
  assert.deepEqual(before, after);
  assert.equal(after.title, "Your home in this simulation");
});

test("a home can stay on in the map outcome despite risk in other runs", () => {
  const state = powerState({ ...status, event: { timeline: null } });
  assert.match(state.title, /keeps power in this simulation/);
});

test("live outlook uses the map's restoration time and does not confirm power", () => {
  const live = { ...status, scenario: { kind: "live" } };
  const atHour = (h) => Date.parse(status.start) + h * 3.6e6;
  assert.equal(powerState(live, atHour(3)).title, "Outage possible");
  assert.equal(powerState(live, atHour(60)).title, "Outage predicted at this time");
  assert.equal(powerState(live, atHour(68)).title, "Restoration predicted by now");
});
