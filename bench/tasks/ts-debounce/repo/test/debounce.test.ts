import assert from "node:assert/strict";
import { test } from "node:test";
import type { DebounceOptions } from "../src/debounce.ts";
import { debounce } from "../src/debounce.ts";
import { ManualScheduler } from "../src/scheduler.ts";

function recorder(wait: number, options: DebounceOptions = {}) {
  const scheduler = new ManualScheduler();
  const calls: Array<[number, string]> = [];
  const debounced = debounce((value: string) => calls.push([scheduler.now(), value]), wait, options, scheduler);
  return { scheduler, calls, debounced };
}

test("a single call runs once after the wait", () => {
  const { scheduler, calls, debounced } = recorder(200);
  debounced("a");
  scheduler.advance(199);
  assert.deepEqual(calls, []);
  scheduler.advance(1);
  assert.deepEqual(calls, [[200, "a"]]);
  scheduler.advance(1000);
  assert.deepEqual(calls, [[200, "a"]]);
});

test("every call starts the wait again", () => {
  const { scheduler, calls, debounced } = recorder(200);
  debounced("save");
  scheduler.advance(150);
  debounced("save");
  scheduler.advance(150);
  debounced("save");
  scheduler.advance(199);
  assert.deepEqual(calls, []);
  scheduler.advance(1);
  assert.deepEqual(calls, [[500, "save"]]);
});

test("calls further apart than the wait run once each", () => {
  const { scheduler, calls, debounced } = recorder(200);
  debounced("a");
  scheduler.advance(300);
  debounced("b");
  scheduler.advance(300);
  assert.deepEqual(calls, [
    [200, "a"],
    [500, "b"],
  ]);
});

test("leading runs the first call of a burst at once", () => {
  const { scheduler, calls, debounced } = recorder(200, { leading: true });
  debounced("a");
  assert.deepEqual(calls, [[0, "a"]]);
  scheduler.advance(1000);
  assert.deepEqual(calls, [[0, "a"]]);
});

test("with leading and without trailing only the first call of a burst runs", () => {
  const { scheduler, calls, debounced } = recorder(200, { leading: true, trailing: false });
  debounced("a");
  scheduler.advance(100);
  debounced("b");
  scheduler.advance(500);
  debounced("c");
  assert.deepEqual(calls, [
    [0, "a"],
    [600, "c"],
  ]);
});

test("maxWait ends a burst that goes on too long", () => {
  const { scheduler, calls, debounced } = recorder(200, { maxWait: 500 });
  for (let call = 0; call < 10; call += 1) {
    debounced("tick");
    scheduler.advance(100);
  }
  scheduler.advance(1000);
  assert.deepEqual(
    calls.map(([time]) => time),
    [500, 1000],
  );
});

test("cancel drops the waiting call", () => {
  const { scheduler, calls, debounced } = recorder(200);
  debounced("a");
  debounced.cancel();
  scheduler.advance(1000);
  assert.deepEqual(calls, []);
  assert.equal(debounced.pending(), false);
});

test("flush runs a waiting call at once and pending follows it", () => {
  const { scheduler, calls, debounced } = recorder(200);
  assert.equal(debounced.pending(), false);
  debounced("a");
  assert.equal(debounced.pending(), true);
  scheduler.advance(50);
  debounced.flush();
  assert.deepEqual(calls, [[50, "a"]]);
  assert.equal(debounced.pending(), false);
  scheduler.advance(1000);
  debounced.flush();
  assert.deepEqual(calls, [[50, "a"]]);
});

test("bad delays throw a RangeError", () => {
  const noop = () => {};
  assert.throws(() => debounce(noop, -1), RangeError);
  assert.throws(() => debounce(noop, Number.NaN), RangeError);
  assert.throws(() => debounce(noop, 300, { maxWait: 100 }), /maxWait \(100 ms\) must not be shorter than wait/);
});
