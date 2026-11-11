import assert from "node:assert/strict";
import { test } from "node:test";
import { Emitter } from "../src/emitter.ts";
import { DASHBOARD_EVENTS, createDashboardBus } from "../src/events.ts";
import { forward } from "../src/forward.ts";
import { WaitTimeoutError, waitFor } from "../src/wait.ts";

type Events = { saved: { id: string }; loaded: number };

test("waitFor resolves with the payload of the next emit", async () => {
  const bus = new Emitter<Events>();
  const next = waitFor(bus, "saved", 1000);
  bus.emit("saved", { id: "ops-main" });
  assert.deepEqual(await next, { id: "ops-main" });
});

test("waitFor removes its listener after the event came", async () => {
  const bus = new Emitter<Events>();
  const next = waitFor(bus, "loaded", 1000);
  assert.equal(bus.emit("loaded", 1), 1);
  await next;
  assert.equal(bus.emit("loaded", 2), 0);
});

test("waitFor rejects with WaitTimeoutError and removes its listener", async () => {
  const bus = new Emitter<Events>();
  await assert.rejects(waitFor(bus, "loaded", 20), {
    name: "WaitTimeoutError",
    message: 'no "loaded" event within 20 ms',
  });
  assert.equal(bus.emit("loaded", 1), 0);
  assert.ok(new WaitTimeoutError("x", 1) instanceof Error);
});

test("forward re-emits the listed events on the other bus", () => {
  const plugin = new Emitter<Events>();
  const dashboard = new Emitter<Events>();
  const seen: string[] = [];
  dashboard.on("saved", ({ id }) => seen.push(`saved ${id}`));
  dashboard.on("loaded", (rows) => seen.push(`loaded ${rows}`));
  forward(plugin, dashboard, ["saved", "saved"]);
  plugin.emit("saved", { id: "a" });
  plugin.emit("loaded", 3);
  assert.deepEqual(seen, ["saved a"]);
});

test("the function forward returns stops forwarding", () => {
  const plugin = new Emitter<Events>();
  const dashboard = new Emitter<Events>();
  let count = 0;
  dashboard.on("loaded", () => {
    count += 1;
  });
  const stop = forward(plugin, dashboard, ["loaded"]);
  plugin.emit("loaded", 1);
  stop();
  assert.equal(plugin.emit("loaded", 2), 0);
  assert.equal(count, 1);
});

test("the dashboard bus carries the dashboard events", () => {
  const bus = createDashboardBus();
  const kinds: string[] = [];
  bus.on("widget:added", ({ kind }) => kinds.push(kind));
  bus.emit("widget:added", { widgetId: "w1", kind: "chart" });
  assert.deepEqual(kinds, ["chart"]);
  assert.deepEqual(DASHBOARD_EVENTS, [
    "widget:added",
    "widget:removed",
    "layout:saved",
    "data:refreshed",
  ]);
});
