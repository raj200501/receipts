import assert from "node:assert/strict";
import { test } from "node:test";
import { ManualScheduler } from "../src/scheduler.ts";
import { throttle } from "../src/throttle.ts";

function recorder(interval: number, trailing?: boolean) {
  const scheduler = new ManualScheduler();
  const calls: Array<[number, number]> = [];
  const throttled = throttle(
    (position: number) => calls.push([scheduler.now(), position]),
    interval,
    trailing === undefined ? {} : { trailing },
    scheduler,
  );
  return { scheduler, calls, throttled };
}

test("a call outside an interval runs at once", () => {
  const { calls, throttled } = recorder(100);
  throttled(10);
  assert.deepEqual(calls, [[0, 10]]);
});

test("the last call of an interval runs when the interval ends", () => {
  const { scheduler, calls, throttled } = recorder(100);
  throttled(10);
  scheduler.advance(30);
  throttled(20);
  scheduler.advance(30);
  throttled(30);
  scheduler.advance(40);
  assert.deepEqual(calls, [
    [0, 10],
    [100, 30],
  ]);
  scheduler.advance(50);
  throttled(40);
  scheduler.advance(50);
  assert.deepEqual(calls, [
    [0, 10],
    [100, 30],
    [200, 40],
  ]);
});

test("without trailing, calls during an interval are dropped", () => {
  const { scheduler, calls, throttled } = recorder(100, false);
  throttled(10);
  scheduler.advance(50);
  throttled(20);
  scheduler.advance(100);
  throttled(30);
  assert.deepEqual(calls, [
    [0, 10],
    [150, 30],
  ]);
});

test("cancel drops a held-back call and ends the interval", () => {
  const { scheduler, calls, throttled } = recorder(100);
  throttled(10);
  throttled(20);
  throttled.cancel();
  scheduler.advance(500);
  throttled(30);
  assert.deepEqual(calls, [
    [0, 10],
    [500, 30],
  ]);
});
