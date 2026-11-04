import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { main } from "../src/cli.ts";
import type { Env } from "../src/types.ts";

function run(argv: string[], env: Env = {}): { status: number; out: string; err: string } {
  let out = "";
  let err = "";
  const status = main(argv, env, {
    out: (text) => {
      out += text;
    },
    err: (text) => {
      err += text;
    },
  });
  return { status, out, err };
}

function envFile(text: string): string {
  const path = join(mkdtempSync(join(tmpdir(), "envcheck-")), "relay.env");
  writeFileSync(path, text);
  return path;
}

const COMPLETE = [
  "RELAY_PORT=9443",
  "RELAY_UPSTREAM_URL=https://hooks.example.invalid/relay/in",
  "RELAY_SIGNING_SECRET=test-signing-secret-0123456789abcdef",
  "RELAY_LOG_LEVEL=info",
  "RELAY_TIMEOUT=10s",
  "RELAY_RETRY_LIMIT=2",
  "RELAY_ALLOWED_EVENTS=invoice.paid,refund.issued",
  "RELAY_QUEUE_URL=amqp://localhost:5672/dead",
  "RELAY_VERIFY_TLS=yes",
];

test("envcheck prints the settings with the secret masked", () => {
  const { status, out, err } = run(["--env-file", envFile(`${COMPLETE.join("\n")}\n`)]);
  assert.equal(status, 0, err);
  assert.equal(
    out,
    [
      "RELAY_PORT=9443",
      "RELAY_UPSTREAM_URL=https://hooks.example.invalid/relay/in",
      "RELAY_SIGNING_SECRET=****",
      "RELAY_LOG_LEVEL=info",
      "RELAY_TIMEOUT=10s",
      "RELAY_RETRY_LIMIT=2",
      "RELAY_ALLOWED_EVENTS=invoice.paid,refund.issued",
      "RELAY_QUEUE_URL=amqp://localhost:5672/dead",
      "RELAY_VERIFY_TLS=true",
      "",
    ].join("\n"),
  );
});

test("envcheck --json prints the kind and value of each setting", () => {
  const { status, out } = run(["--json", "--env-file", envFile(COMPLETE.join("\n"))]);
  assert.equal(status, 0);
  const settings = JSON.parse(out);
  assert.deepEqual(settings.RELAY_PORT, { kind: "integer", value: 9443 });
  assert.deepEqual(settings.RELAY_SIGNING_SECRET, { kind: "string", value: "****" });
  assert.deepEqual(Object.keys(settings).length, 9);
});

test("without --env-file envcheck checks its own environment", () => {
  const env = Object.fromEntries(COMPLETE.map((line) => line.split("=", 2)));
  const { status, out } = run([], env);
  assert.equal(status, 0);
  assert.match(out, /^RELAY_PORT=9443\n/);
});

test("a missing setting exits with status 2", () => {
  const lines = COMPLETE.filter((line) => !line.startsWith("RELAY_SIGNING_SECRET="));
  const { status, out, err } = run(["--env-file", envFile(lines.join("\n"))]);
  assert.equal(status, 2);
  assert.equal(out, "");
  assert.equal(err, "envcheck: RELAY_SIGNING_SECRET: not set\n");
});

test("an env file that cannot be read exits with status 2", () => {
  const missing = join(tmpdir(), "envcheck-does-not-exist", "relay.env");
  const { status, err } = run(["--env-file", missing]);
  assert.equal(status, 2);
  assert.equal(err, `envcheck: cannot read ${missing}\n`);
});

test("a malformed env file names the file and the line", () => {
  const path = envFile("RELAY_PORT=9443\nRELAY_LOG_LEVEL\n");
  const { status, err } = run(["--env-file", path]);
  assert.equal(status, 2);
  assert.equal(err, `envcheck: ${path}: line 2: expected NAME=value\n`);
});

test("unknown options print the usage", () => {
  const { status, err } = run(["--verbose"]);
  assert.equal(status, 2);
  assert.match(err, /usage: envcheck \[--env-file FILE\] \[--json\]\n$/);
});
