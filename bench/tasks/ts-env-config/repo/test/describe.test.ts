import assert from "node:assert/strict";
import { test } from "node:test";
import { MASK, configJson, describeConfig } from "../src/describe.ts";
import { duration, integer, list, string } from "../src/fields.ts";

const SCHEMA = {
  PORT: integer(),
  TOKEN: string({ secret: true }),
  TIMEOUT: duration(),
  EVENTS: list(),
};

const CONFIG = { PORT: 8080, TOKEN: "do-not-print-me", TIMEOUT: 90_000, EVENTS: ["a", "b"] };

test("the report has one NAME=value line per setting", () => {
  assert.deepEqual(describeConfig(SCHEMA, CONFIG), [
    "PORT=8080",
    `TOKEN=${MASK}`,
    "TIMEOUT=90s",
    "EVENTS=a,b",
  ]);
});

test("secrets never appear in the report", () => {
  const text = describeConfig(SCHEMA, CONFIG).join("\n");
  assert.ok(!text.includes("do-not-print-me"), text);
});

test("the JSON form names each kind and masks secrets", () => {
  assert.deepEqual(configJson(SCHEMA, CONFIG), {
    PORT: { kind: "integer", value: 8080 },
    TOKEN: { kind: "string", value: MASK },
    TIMEOUT: { kind: "duration", value: 90_000 },
    EVENTS: { kind: "list", value: ["a", "b"] },
  });
});
