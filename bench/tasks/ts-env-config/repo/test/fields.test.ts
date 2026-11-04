import assert from "node:assert/strict";
import { test } from "node:test";
import { CoercionError } from "../src/coerce.ts";
import { duration, integer, list, oneOf, string, url } from "../src/fields.ts";

test("integer fields check their range", () => {
  const port = integer({ min: 1, max: 65535 });
  assert.equal(port.parse("443"), 443);
  assert.throws(() => port.parse("0"), { message: "expected an integer from 1 to 65535, got 0" });
  assert.throws(() => port.parse("70000"), CoercionError);
});

test("string fields check their length without showing the value", () => {
  const secret = string({ secret: true, minLength: 32 });
  assert.equal(secret.parse("x".repeat(32)), "x".repeat(32));
  assert.throws(() => secret.parse("hunter2"), {
    message: "expected at least 32 characters, got 7",
  });
});

test("oneOf accepts only its choices", () => {
  const level = oneOf(["debug", "info", "warn", "error"]);
  assert.equal(level.parse("warn"), "warn");
  assert.throws(() => level.parse("WARN"), {
    message: 'expected one of debug, info, warn, error, got "WARN"',
  });
});

test("fields carry their kind, description, and secret flag", () => {
  const timeout = duration({ description: "upstream time limit" });
  assert.equal(timeout.kind, "duration");
  assert.equal(timeout.description, "upstream time limit");
  assert.equal(timeout.secret, false);
  assert.equal(timeout.display(timeout.parse("90s")), "90s");
  assert.equal(list().display(["a", "b"]), "a,b");
  assert.equal(url({ secret: true }).secret, true);
});
