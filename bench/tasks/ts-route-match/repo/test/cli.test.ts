import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { main } from "../src/cli.ts";

const ROUTES = [
  { name: "customers.get", method: "GET", pattern: "/v2/customers/:customerId", upstream: "http://crm.test.invalid:8080" },
  { name: "customers.update", method: "PATCH", pattern: "/v2/customers/:customerId", upstream: "http://crm.test.invalid:8080" },
  { name: "orders.list", method: "GET", pattern: "/v2/orders", upstream: "http://orders.test.invalid:8080" },
  { name: "health", method: "GET", pattern: "/healthz", upstream: "http://health.test.invalid", strict: true },
];

function manifestFile(routes: unknown[] = ROUTES): string {
  const path = join(mkdtempSync(join(tmpdir(), "edge-")), "routes.json");
  writeFileSync(path, JSON.stringify({ version: 3, routes }));
  return path;
}

function run(argv: string[]): { status: number; out: string; err: string } {
  let out = "";
  let err = "";
  const status = main(argv, {
    out: (text) => {
      out += text;
    },
    err: (text) => {
      err += text;
    },
  });
  return { status, out, err };
}

test("match prints the route, its upstream, and the params", () => {
  const { status, out } = run(["match", "GET", "/v2/customers/C-77", "--manifest", manifestFile()]);
  assert.equal(status, 0);
  assert.equal(
    out,
    "route:    customers.get\nupstream: http://crm.test.invalid:8080\nparams:   customerId=C-77\n",
  );
});

test("a route without parameters prints (none)", () => {
  const { out } = run(["match", "get", "/v2/orders", "--manifest", manifestFile()]);
  assert.match(out, /^route: {4}orders.list\n/);
  assert.match(out, /params: {3}\(none\)\n$/);
});

test("no route is a 404 with exit status 1", () => {
  const { status, out } = run(["match", "GET", "/v2/invoices", "--manifest", manifestFile()]);
  assert.equal(status, 1);
  assert.equal(out, "404 no route for GET /v2/invoices\n");
});

test("a wrong method is a 405 with exit status 1", () => {
  const { status, out } = run(["match", "DELETE", "/v2/customers/C-77", "--manifest", manifestFile()]);
  assert.equal(status, 1);
  assert.equal(out, "405 DELETE is not allowed for /v2/customers/C-77 (allow: GET, HEAD, PATCH)\n");
});

test("routes lists the manifest in order", () => {
  const { status, out } = run(["routes", "--manifest", manifestFile()]);
  assert.equal(status, 0);
  assert.equal(
    out,
    [
      "GET    /v2/customers/:customerId  customers.get",
      "PATCH  /v2/customers/:customerId  customers.update",
      "GET    /v2/orders                 orders.list",
      "GET    /healthz                   health (strict)",
      "",
    ].join("\n"),
  );
});

test("a manifest that cannot be read stops edge with status 2", () => {
  const missing = join(tmpdir(), "does-not-exist", "routes.json");
  const { status, out, err } = run(["routes", "--manifest", missing]);
  assert.equal(status, 2);
  assert.equal(out, "");
  assert.equal(err, `edge: cannot read ${missing}\n`);
});

test("a bad manifest or target stops edge with status 2", () => {
  const bad = manifestFile([{ name: "x", method: "FETCH", pattern: "/x", upstream: "http://x.test.invalid" }]);
  assert.match(run(["routes", "--manifest", bad]).err, /^edge: .*route 1 \(x\): unknown method "FETCH"\n$/);
  const target = run(["match", "GET", "v2/orders", "--manifest", manifestFile()]);
  assert.equal(target.status, 2);
  assert.match(target.err, /^edge: the request target must start with \//);
});

test("an unknown method or wrong arguments stop edge with status 2", () => {
  assert.equal(run(["match", "FETCH", "/v2/orders", "--manifest", manifestFile()]).status, 2);
  const usage = run(["match", "GET"]);
  assert.equal(usage.status, 2);
  assert.match(usage.err, /^usage: edge match METHOD TARGET/);
});
