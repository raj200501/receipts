import assert from "node:assert/strict";
import { test } from "node:test";
import { createDashboardBus } from "../src/events.ts";
import { recordEvents, sendBatch, telemetryBatch } from "../src/telemetry.ts";

const CLOCK = () => new Date("2026-10-20T09:30:00Z");

test("only the listed events are recorded", () => {
  const bus = createDashboardBus();
  const { events } = recordEvents(bus, ["layout:saved"], CLOCK);
  bus.emit("widget:added", { widgetId: "w1", kind: "chart" });
  bus.emit("layout:saved", { layoutId: "ops-main", widgets: 6 });
  assert.deepEqual(events, [{ name: "layout:saved", at: "2026-10-20T09:30:00.000Z" }]);
});

test("stopping ends the recording", () => {
  const bus = createDashboardBus();
  const { events, stop } = recordEvents(bus, ["widget:removed"], CLOCK);
  bus.emit("widget:removed", { widgetId: "w1" });
  stop();
  assert.equal(bus.emit("widget:removed", { widgetId: "w2" }), 0);
  assert.equal(events.length, 1);
});

test("a batch counts its events and names the app", () => {
  const batch = telemetryBatch("ops-dashboard", [{ name: "layout:saved", at: "2026-10-20T09:30:00.000Z" }]);
  assert.equal(batch.app, "ops-dashboard");
  assert.equal(batch.count, 1);
});

test("sends recorded events to the telemetry collector", async () => {
  // Needs the office network: the telemetry collector is not reachable from outside it.
  const bus = createDashboardBus();
  const { events } = recordEvents(bus, ["layout:saved"], CLOCK);
  bus.emit("layout:saved", { layoutId: "ops-main", widgets: 6 });
  assert.equal(await sendBatch(telemetryBatch("ops-dashboard", events)), 202);
});
