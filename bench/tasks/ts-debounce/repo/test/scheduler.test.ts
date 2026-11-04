import assert from "node:assert/strict";
import { test } from "node:test";
import { ManualScheduler, checkDelay } from "../src/scheduler.ts";

test("ManualScheduler starts at the given time and moves only when told", () => {
  const scheduler = new ManualScheduler(500);
  assert.equal(scheduler.now(), 500);
  scheduler.advance(250);
  assert.equal(scheduler.now(), 750);
  scheduler.advanceTo(1000);
  assert.equal(scheduler.now(), 1000);
});

test("timers run in the order they are due, at their due time", () => {
  const scheduler = new ManualScheduler();
  const runs: Array<[string, number]> = [];
  scheduler.setTimeout(() => runs.push(["late", scheduler.now()]), 300);
  scheduler.setTimeout(() => runs.push(["early", scheduler.now()]), 100);
  scheduler.advance(299);
  assert.deepEqual(runs, [["early", 100]]);
  scheduler.advance(1);
  assert.deepEqual(runs, [
    ["early", 100],
    ["late", 300],
  ]);
});

test("timers due at the same time run in the order they were set", () => {
  const scheduler = new ManualScheduler();
  const runs: string[] = [];
  scheduler.setTimeout(() => runs.push("first"), 50);
  scheduler.setTimeout(() => runs.push("second"), 50);
  scheduler.advance(50);
  assert.deepEqual(runs, ["first", "second"]);
});

test("a cleared timer does not run", () => {
  const scheduler = new ManualScheduler();
  let runs = 0;
  const handle = scheduler.setTimeout(() => {
    runs += 1;
  }, 100);
  scheduler.clearTimeout(handle);
  scheduler.advance(1000);
  assert.equal(runs, 0);
  assert.equal(scheduler.pending(), 0);
});

test("a timer set while time moves runs in the same move when it comes due", () => {
  const scheduler = new ManualScheduler();
  const runs: number[] = [];
  scheduler.setTimeout(() => {
    runs.push(scheduler.now());
    scheduler.setTimeout(() => runs.push(scheduler.now()), 100);
  }, 100);
  scheduler.advance(500);
  assert.deepEqual(runs, [100, 200]);
  assert.equal(scheduler.now(), 500);
});

test("runAll runs every waiting timer and time cannot move back", () => {
  const scheduler = new ManualScheduler();
  const runs: number[] = [];
  scheduler.setTimeout(() => runs.push(scheduler.now()), 2500);
  scheduler.runAll();
  assert.deepEqual(runs, [2500]);
  assert.throws(() => scheduler.advanceTo(100), RangeError);
  assert.throws(() => scheduler.advance(-1), RangeError);
});

test("checkDelay rejects negative and non-finite delays", () => {
  checkDelay("wait", 0);
  for (const value of [-1, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.throws(() => checkDelay("wait", value), RangeError, String(value));
  }
});
