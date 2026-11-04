import assert from "node:assert/strict";
import { test } from "node:test";
import { Emitter } from "../src/emitter.ts";

type Events = {
  saved: { id: string };
  loaded: number;
};

test("listeners are called with the payload in the order they were added", () => {
  const bus = new Emitter<Events>();
  const calls: string[] = [];
  bus.on("saved", ({ id }) => calls.push(`first ${id}`));
  bus.on("saved", ({ id }) => calls.push(`second ${id}`));
  bus.emit("saved", { id: "ops-main" });
  assert.deepEqual(calls, ["first ops-main", "second ops-main"]);
});

test("emit returns how many listeners it called", () => {
  const bus = new Emitter<Events>();
  assert.equal(bus.emit("loaded", 1), 0);
  bus.on("loaded", () => {});
  bus.on("loaded", () => {});
  assert.equal(bus.emit("loaded", 2), 2);
});

test("events have their own listeners", () => {
  const bus = new Emitter<Events>();
  const loaded: number[] = [];
  bus.on("loaded", (rows) => loaded.push(rows));
  assert.equal(bus.emit("saved", { id: "x" }), 0);
  bus.emit("loaded", 42);
  assert.deepEqual(loaded, [42]);
});

test("the function on returns removes the listener", () => {
  const bus = new Emitter<Events>();
  const calls: number[] = [];
  const stop = bus.on("loaded", (rows) => calls.push(rows));
  bus.emit("loaded", 1);
  stop();
  bus.emit("loaded", 2);
  assert.deepEqual(calls, [1]);
});

test("removing a listener twice changes nothing", () => {
  const bus = new Emitter<Events>();
  const calls: string[] = [];
  const stop = bus.on("loaded", () => calls.push("a"));
  bus.on("loaded", () => calls.push("b"));
  stop();
  stop();
  assert.equal(bus.emit("loaded", 1), 1);
  assert.deepEqual(calls, ["b"]);
});

test("a function added twice is called twice", () => {
  const bus = new Emitter<Events>();
  let count = 0;
  const listener = () => {
    count += 1;
  };
  bus.on("loaded", listener);
  const second = bus.on("loaded", listener);
  assert.equal(bus.emit("loaded", 1), 2);
  second();
  assert.equal(bus.emit("loaded", 1), 1);
  assert.equal(count, 3);
});

test("a listener added during an emit is first called by the next emit", () => {
  const bus = new Emitter<Events>();
  const calls: string[] = [];
  bus.on("loaded", () => {
    calls.push("outer");
    if (calls.length === 1) {
      bus.on("loaded", () => calls.push("inner"));
    }
  });
  assert.equal(bus.emit("loaded", 1), 1);
  assert.equal(bus.emit("loaded", 2), 2);
  assert.deepEqual(calls, ["outer", "outer", "inner"]);
});

test("a listener removed during an emit is not called later in that emit", () => {
  const bus = new Emitter<Events>();
  const calls: string[] = [];
  let stopSecond = () => {};
  bus.on("loaded", () => {
    calls.push("first");
    stopSecond();
  });
  stopSecond = bus.on("loaded", () => calls.push("second"));
  assert.equal(bus.emit("loaded", 1), 1);
  assert.deepEqual(calls, ["first"]);
});

test("a listener can emit another event", () => {
  const bus = new Emitter<Events>();
  const calls: string[] = [];
  bus.on("saved", ({ id }) => {
    calls.push(`saved ${id}`);
    bus.emit("loaded", 3);
  });
  bus.on("loaded", (rows) => calls.push(`loaded ${rows}`));
  bus.emit("saved", { id: "a" });
  assert.deepEqual(calls, ["saved a", "loaded 3"]);
});
