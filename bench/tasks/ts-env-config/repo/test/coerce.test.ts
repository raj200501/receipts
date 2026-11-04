import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CoercionError,
  formatDuration,
  parseBoolean,
  parseDuration,
  parseInteger,
  parseList,
  parseUrl,
} from "../src/coerce.ts";

test("integers are whole decimal numbers", () => {
  assert.equal(parseInteger("8080"), 8080);
  assert.equal(parseInteger("-3"), -3);
  assert.equal(parseInteger("+7"), 7);
});

test("decimals and words are not integers", () => {
  assert.throws(() => parseInteger("1.5"), {
    name: "CoercionError",
    message: 'expected an integer, got "1.5"',
  });
  assert.throws(() => parseInteger("eighty"), CoercionError);
});

test("booleans accept the usual words in any case", () => {
  for (const word of ["true", "TRUE", "1", "yes", "On"]) {
    assert.equal(parseBoolean(word), true, word);
  }
  for (const word of ["false", "0", "no", "OFF"]) {
    assert.equal(parseBoolean(word), false, word);
  }
  assert.throws(() => parseBoolean("maybe"), { message: 'expected true or false, got "maybe"' });
});

test("durations are read as milliseconds", () => {
  assert.equal(parseDuration("250ms"), 250);
  assert.equal(parseDuration("30s"), 30_000);
  assert.equal(parseDuration("5m"), 300_000);
  assert.equal(parseDuration("1h"), 3_600_000);
  assert.throws(() => parseDuration("30"), /expected a duration such as 250ms/);
});

test("durations are shown in their largest whole unit", () => {
  assert.equal(formatDuration(4500), "4500ms");
  assert.equal(formatDuration(30_000), "30s");
  assert.equal(formatDuration(7_200_000), "2h");
  assert.equal(formatDuration(0), "0ms");
});

test("lists drop spaces and empty items", () => {
  assert.deepEqual(parseList(" invoice.paid, ,refund.issued ,"), ["invoice.paid", "refund.issued"]);
  assert.deepEqual(parseList("single"), ["single"]);
});

test("URLs must be absolute and are normalized", () => {
  assert.equal(parseUrl("HTTPS://Hooks.Example.invalid:443/in"), "https://hooks.example.invalid/in");
  assert.throws(() => parseUrl("/relative/path"), {
    message: 'expected an absolute URL, got "/relative/path"',
  });
});

test("URLs can be limited to some schemes", () => {
  assert.equal(
    parseUrl("https://hooks.example.invalid/in", ["https"]),
    "https://hooks.example.invalid/in",
  );
  assert.throws(() => parseUrl("http://hooks.example.invalid/in", ["https"]), {
    message: 'expected a URL starting with https://, got "http://hooks.example.invalid/in"',
  });
});
