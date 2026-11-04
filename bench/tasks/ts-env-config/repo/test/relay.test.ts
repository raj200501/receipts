import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { parseEnvFile } from "../src/envfile.ts";
import { ConfigError } from "../src/load.ts";
import { RELAY_SCHEMA, loadRelayConfig } from "../src/relay.ts";

const EXAMPLE = parseEnvFile(readFileSync("examples/relay.env", "utf8"));

test("the example env file is a complete relay configuration", () => {
  const config = loadRelayConfig(EXAMPLE);
  assert.equal(config.RELAY_PORT, 9443);
  assert.equal(config.RELAY_TIMEOUT, 30_000);
  assert.deepEqual(config.RELAY_ALLOWED_EVENTS, ["invoice.paid", "invoice.voided"]);
  assert.equal(config.RELAY_VERIFY_TLS, false);
});

test("the upstream must use https", () => {
  const env = { ...EXAMPLE, RELAY_UPSTREAM_URL: "http://hooks.example.invalid/relay/in" };
  assert.throws(() => loadRelayConfig(env), {
    message:
      'RELAY_UPSTREAM_URL: expected a URL starting with https://, got "http://hooks.example.invalid/relay/in"',
  });
});

test("the signing secret needs 32 characters", () => {
  const env = { ...EXAMPLE, RELAY_SIGNING_SECRET: "too-short" };
  assert.throws(() => loadRelayConfig(env), {
    message: "RELAY_SIGNING_SECRET: expected at least 32 characters, got 9",
  });
});

test("the retry limit is between 0 and 10", () => {
  assert.equal(loadRelayConfig({ ...EXAMPLE, RELAY_RETRY_LIMIT: "0" }).RELAY_RETRY_LIMIT, 0);
  assert.throws(
    () => loadRelayConfig({ ...EXAMPLE, RELAY_RETRY_LIMIT: "11" }),
    (error: unknown) => error instanceof ConfigError && error.variable === "RELAY_RETRY_LIMIT",
  );
});

test("only the signing secret is a secret", () => {
  const secrets = Object.entries(RELAY_SCHEMA)
    .filter(([, field]) => field.secret)
    .map(([name]) => name);
  assert.deepEqual(secrets, ["RELAY_SIGNING_SECRET"]);
});
