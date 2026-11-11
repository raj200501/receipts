import assert from "node:assert/strict";
import { test } from "node:test";
import { Emitter } from "../src/emitter.ts";
import { EmitError } from "../src/errors.ts";

type Events = { refreshed: string };

test("the other listeners are still called when one throws", () => {
  const bus = new Emitter<Events>();
  const calls: string[] = [];
  bus.on("refreshed", () => {
    throw new Error("widget crashed");
  });
  bus.on("refreshed", (source) => calls.push(source));
  assert.throws(() => bus.emit("refreshed", "billing"), EmitError);
  assert.deepEqual(calls, ["billing"]);
});

test("the EmitError holds every error in order", () => {
  const bus = new Emitter<Events>();
  const first = new Error("first");
  bus.on("refreshed", () => {
    throw first;
  });
  bus.on("refreshed", () => {});
  bus.on("refreshed", () => {
    throw "second";
  });
  assert.throws(
    () => bus.emit("refreshed", "x"),
    (error: unknown) => {
      assert.ok(error instanceof EmitError);
      assert.equal(error.event, "refreshed");
      assert.deepEqual(error.errors, [first, "second"]);
      return true;
    },
  );
});

test("the message names the event and the errors", () => {
  assert.equal(
    new EmitError("refreshed", [new Error("boom")]).message,
    '1 listener of "refreshed" failed: boom',
  );
  assert.equal(
    new EmitError("saved", [new Error("a"), "b"]).message,
    '2 listeners of "saved" failed: a; b',
  );
});

test("an emit without errors does not throw", () => {
  const bus = new Emitter<Events>();
  bus.on("refreshed", () => {});
  assert.doesNotThrow(() => bus.emit("refreshed", "x"));
});
