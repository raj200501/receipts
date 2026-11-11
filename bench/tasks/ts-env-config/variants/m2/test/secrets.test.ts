import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchSecret, secretPath, secretRequest } from "../src/secrets.ts";

test("secret paths are under the relay's namespace", () => {
  assert.equal(secretPath("RELAY_SIGNING_SECRET"), "relay/signing-secret");
  assert.equal(secretPath("RELAY_QUEUE_PASSWORD"), "relay/queue-password");
});

test("a secret request is one JSON line", () => {
  assert.equal(
    secretRequest("RELAY_SIGNING_SECRET"),
    '{"op":"read","path":"relay/signing-secret"}\n',
  );
});

test("reads the signing secret from the secret agent", async () => {
  // Needs the secret agent (/run/secret-agent/agent.sock), which runs only on the relay's
  // production hosts.
  const secret = await fetchSecret("RELAY_SIGNING_SECRET");
  assert.ok(secret.length >= 32, "the signing secret is too short");
});
