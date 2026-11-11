import assert from "node:assert/strict";
import { test } from "node:test";
import { boolean, duration, integer, list, string } from "../src/fields.ts";
import { ConfigError, loadConfig, rawValue } from "../src/load.ts";

const SCHEMA = {
  API_PORT: integer({ min: 1, max: 65535 }),
  API_TOKEN: string({ secret: true }),
  API_DEBUG: boolean(),
  API_TIMEOUT: duration(),
  API_TAGS: list(),
};

const ENV = {
  API_PORT: "8080",
  API_TOKEN: "local-token",
  API_DEBUG: "no",
  API_TIMEOUT: "2s",
  API_TAGS: "blue,green",
};

test("loadConfig returns typed values", () => {
  assert.deepEqual(loadConfig(SCHEMA, ENV), {
    API_PORT: 8080,
    API_TOKEN: "local-token",
    API_DEBUG: false,
    API_TIMEOUT: 2000,
    API_TAGS: ["blue", "green"],
  });
});

test("values are trimmed and an empty value counts as not set", () => {
  assert.equal(rawValue({ A: "  8080 " }, "A"), "8080");
  assert.equal(rawValue({ A: "   " }, "A"), undefined);
  assert.equal(loadConfig(SCHEMA, { ...ENV, API_PORT: " 9090 " }).API_PORT, 9090);
  assert.throws(() => loadConfig(SCHEMA, { ...ENV, API_TOKEN: "" }), {
    message: "API_TOKEN: not set",
  });
});

test("a missing variable is named in the error", () => {
  const { API_DEBUG, ...rest } = ENV;
  assert.equal(API_DEBUG, "no");
  assert.throws(
    () => loadConfig(SCHEMA, rest),
    (error: unknown) => error instanceof ConfigError && error.variable === "API_DEBUG",
  );
});

test("a value that cannot be read names the variable and the reason", () => {
  assert.throws(() => loadConfig(SCHEMA, { ...ENV, API_TIMEOUT: "2 seconds" }), {
    name: "ConfigError",
    message: 'API_TIMEOUT: expected a duration such as 250ms, 30s, or 5m, got "2 seconds"',
  });
});

test("variables outside the schema are ignored", () => {
  const config = loadConfig(SCHEMA, { ...ENV, HOME: "/home/relay", PATH: "/usr/bin" });
  assert.deepEqual(Object.keys(config), Object.keys(SCHEMA));
});
