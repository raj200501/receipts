import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { loadManifest, parseManifest } from "../src/manifest.ts";

function manifest(routes: unknown[], version: unknown = 3): string {
  return JSON.stringify({ version, generatedAt: "2026-10-01T02:00:00Z", routes });
}

const ORDERS = {
  name: "orders.get",
  method: "GET",
  pattern: "/v2/orders/:orderId",
  upstream: "http://orders.test.invalid:8080",
};

test("a manifest lists its routes in order", () => {
  const health = { name: "health", method: "GET", pattern: "/healthz", upstream: "https://h.test.invalid", strict: true };
  assert.deepEqual(parseManifest(manifest([health, ORDERS]), "m.json"), [health, ORDERS]);
});

test("strict is kept only when it is true", () => {
  const [route] = parseManifest(manifest([{ ...ORDERS, strict: false }]), "m.json");
  assert.equal("strict" in route, false);
});

test("route names must be unique", () => {
  assert.throws(() => parseManifest(manifest([ORDERS, { ...ORDERS, method: "POST" }]), "m.json"), {
    name: "ManifestError",
    message: 'm.json: route 2: duplicate route name "orders.get"',
  });
});

test("unknown methods are rejected with the route", () => {
  assert.throws(
    () => parseManifest(manifest([{ ...ORDERS, method: "HEAD" }]), "m.json"),
    /^ManifestError: m.json: route 1 \(orders.get\): unknown method "HEAD"$/,
  );
});

test("an invalid pattern names its route", () => {
  assert.throws(
    () => parseManifest(manifest([{ ...ORDERS, pattern: "/v2/orders/:" }]), "m.json"),
    /route 1 \(orders.get\): invalid pattern "\/v2\/orders\/:": bad parameter name ""/,
  );
});

test("the upstream must be an http or https URL", () => {
  assert.throws(
    () => parseManifest(manifest([{ ...ORDERS, upstream: "orders-api:8080" }]), "m.json"),
    /upstream must be an http:\/\/ or https:\/\/ URL/,
  );
});

test("only manifest version 3 is read", () => {
  assert.throws(() => parseManifest(manifest([ORDERS], 2), "m.json"), /version 2 is not supported/);
  assert.throws(() => parseManifest("{routes", "m.json"), /m.json: not valid JSON/);
});

test("loadManifest reads a file and reports one it cannot read", () => {
  const path = join(mkdtempSync(join(tmpdir(), "edge-")), "routes.json");
  writeFileSync(path, manifest([ORDERS]));
  assert.deepEqual(loadManifest(path), [ORDERS]);
  assert.throws(() => loadManifest(`${path}.missing`), /^ManifestError: cannot read /);
});
