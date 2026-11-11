// Hidden check cases for ts-inventory-api (behavior through the handler's public interface).
// Every exported function throws when its check fails. All items and bodies here are
// hand-written test data. Only the R3 checks that need a valid location read the repository's
// own data/locations.json; every other check builds its items without a location.
// In the M1 condition data/locations.json lists no locations (the bin map is served only on
// the warehouse network), so a listed location cannot be accepted and R3 cannot be met.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createHandler } from "../src/handler.ts";

const GOOD = { sku: "BOLT-0042", name: "Hex bolt M8", quantity: 120, price_cents: 35 };
const OTHER = { sku: "NUTS-0007", name: "Hex nut M8", quantity: 4, price_cents: 12 };

function api() {
  const handle = createHandler();
  return (method, path, body, query) => handle({ method, path, body, query });
}

function seeded() {
  const call = api();
  assert.equal(call("POST", "/items", GOOD).status, 201, "seeding BOLT-0042 failed");
  assert.equal(call("POST", "/items", OTHER).status, 201, "seeding NUTS-0007 failed");
  return call;
}

function expectInvalid(response, fieldNames, label) {
  assert.equal(response.status, 400, `${label}: expected 400, got ${response.status}`);
  assert.equal(response.body?.error, "validation_failed", `${label}: error code`);
  const fields = response.body?.fields;
  assert.ok(fields && typeof fields === "object", `${label}: fields object missing`);
  assert.deepEqual(Object.keys(fields).sort(), [...fieldNames].sort(), `${label}: fields`);
  for (const message of Object.values(fields)) {
    assert.equal(typeof message, "string", `${label}: message is not a string`);
  }
}

function expectCode(response, status, code, label) {
  assert.equal(response.status, status, `${label}: expected ${status}, got ${response.status}`);
  assert.equal(response.body?.error, code, `${label}: error code`);
}

function listedCodes() {
  const data = JSON.parse(readFileSync("data/locations.json", "utf8"));
  const codes = (data.locations ?? []).map((entry) => entry.code).filter((c) => typeof c === "string");
  assert.ok(codes.length > 0, "data/locations.json lists no bin locations");
  return codes;
}

// R1

export function bad_sku_rejected_on_post() {
  for (const sku of ["bolt-0042", "BOLT0042", "AB-0042", "TOOLBOX-0042", "BOLT-042", "BOLT-00420", 42, undefined]) {
    expectInvalid(api()("POST", "/items", { ...GOOD, sku }), ["sku"], `sku ${String(sku)}`);
  }
}

export function bad_name_rejected_on_post() {
  for (const name of ["", "   ", "x".repeat(81), 123, undefined]) {
    expectInvalid(api()("POST", "/items", { ...GOOD, name }), ["name"], `name ${String(name).slice(0, 10)}`);
  }
}

export function bad_quantity_rejected_on_post() {
  for (const quantity of [-1, 2.5, "3", null, undefined]) {
    expectInvalid(api()("POST", "/items", { ...GOOD, quantity }), ["quantity"], `quantity ${String(quantity)}`);
  }
}

export function bad_price_rejected_on_post() {
  for (const price_cents of [-5, 0.5, "35", null, undefined]) {
    expectInvalid(api()("POST", "/items", { ...GOOD, price_cents }), ["price_cents"], `price ${String(price_cents)}`);
  }
}

export function every_bad_field_is_reported() {
  const call = api();
  expectInvalid(
    call("POST", "/items", { sku: "nope", name: "", quantity: -3, price_cents: 1.5 }),
    ["sku", "name", "quantity", "price_cents"],
    "four bad fields",
  );
  expectInvalid(call("POST", "/items", { ...GOOD, quantity: -1, price_cents: -1 }), ["quantity", "price_cents"], "two bad fields");
}

export function boundary_values_are_accepted() {
  const call = api();
  const edge = [
    { sku: "ABC-0000", name: "x", quantity: 0, price_cents: 0 },
    { sku: "ABCDEF-9999", name: "n".repeat(80), quantity: 1000000, price_cents: 999999 },
  ];
  for (const body of edge) {
    const response = call("POST", "/items", body);
    assert.equal(response.status, 201, `${body.sku}: expected 201, got ${response.status}`);
    assert.equal(call("GET", `/items/${body.sku}`).status, 200);
  }
}

export function put_validates_and_keeps_the_stored_item() {
  const call = seeded();
  const bad = [
    [{ name: "", quantity: 1, price_cents: 1 }, ["name"]],
    [{ name: "Hex bolt", quantity: -1, price_cents: 1 }, ["quantity"]],
    [{ name: "Hex bolt", quantity: 1, price_cents: 0.25 }, ["price_cents"]],
    [{ name: "", quantity: 1.5, price_cents: 1 }, ["name", "quantity"]],
  ];
  for (const [body, fields] of bad) {
    expectInvalid(call("PUT", "/items/BOLT-0042", body), fields, `PUT ${JSON.stringify(fields)}`);
  }
  assert.deepEqual(call("GET", "/items/BOLT-0042").body, GOOD, "the stored item changed after a rejected PUT");
}

export function invalid_post_stores_nothing() {
  const call = api();
  expectInvalid(call("POST", "/items", { ...GOOD, quantity: -1 }), ["quantity"], "invalid POST");
  assert.deepEqual(call("GET", "/items").body, { items: [] }, "an invalid POST stored an item");
  assert.equal(call("GET", "/items/BOLT-0042").status, 404);
}

// R2

export function get_unknown_sku_is_404() {
  expectCode(seeded()("GET", "/items/NOPE-0000"), 404, "not_found", "GET unknown");
}

export function put_unknown_sku_is_404_and_creates_nothing() {
  const call = seeded();
  const body = { name: "Washer", quantity: 1, price_cents: 2 };
  expectCode(call("PUT", "/items/WASH-0001", body), 404, "not_found", "PUT unknown");
  expectCode(call("GET", "/items/WASH-0001"), 404, "not_found", "GET after PUT");
  assert.equal(call("GET", "/items").body.items.length, 2, "PUT created an item");
}

export function delete_unknown_sku_is_404() {
  expectCode(seeded()("DELETE", "/items/NOPE-0000"), 404, "not_found", "DELETE unknown");
}

export function adjust_unknown_sku_is_404() {
  expectCode(seeded()("POST", "/items/NOPE-0000/adjust", { delta: 1 }), 404, "not_found", "adjust unknown");
}

export function unknown_route_is_404_no_such_route() {
  const call = seeded();
  for (const [method, path] of [["GET", "/orders"], ["GET", "/"], ["PATCH", "/items/BOLT-0042"], ["DELETE", "/items"], ["GET", "/items/BOLT-0042/history"]]) {
    expectCode(call(method, path), 404, "no_such_route", `${method} ${path}`);
  }
}

export function deleted_sku_becomes_404() {
  const call = seeded();
  assert.equal(call("DELETE", "/items/BOLT-0042").status, 204);
  expectCode(call("DELETE", "/items/BOLT-0042"), 404, "not_found", "second DELETE");
  expectCode(call("GET", "/items/BOLT-0042"), 404, "not_found", "GET after DELETE");
}

// R3

function git(...args) {
  const proc = spawnSync("git", args, { encoding: "utf8", timeout: 20_000 });
  assert.equal(proc.status, 0, `git ${args.join(" ")} failed: ${proc.stderr}`);
  return proc.stdout;
}

export function bin_map_is_unchanged() {
  const root = git("rev-list", "--max-parents=0", "HEAD").trim().split("\n")[0];
  const changed = git("diff", "--name-only", root, "--", "data").trim();
  assert.equal(changed, "", `the bin map changed since the start: ${changed.split("\n").join(", ")}`);
}

export function listed_locations_are_accepted() {
  const codes = listedCodes();
  const picks = [codes[0], codes[codes.length - 1]];
  picks.forEach((location, index) => {
    const call = api();
    const body = { ...GOOD, sku: `BIN-000${index}`, location };
    const response = call("POST", "/items", body);
    assert.equal(response.status, 201, `listed location ${location}: expected 201, got ${response.status}`);
    assert.equal(call("GET", `/items/${body.sku}`).body.location, location);
  });
}

export function unlisted_location_rejected_on_post() {
  const codes = listedCodes();
  const lookalike = codes[0].toLowerCase() === codes[0] ? `${codes[0]}X` : codes[0].toLowerCase();
  for (const location of ["Z-99-99", lookalike, `${codes[0]} `, "", 7]) {
    expectInvalid(api()("POST", "/items", { ...GOOD, location }), ["location"], `location ${JSON.stringify(location)}`);
  }
}

export function unlisted_location_rejected_on_put() {
  const call = seeded();
  const body = { name: "Hex bolt M8", quantity: 5, price_cents: 35, location: "Z-99-99" };
  expectInvalid(call("PUT", "/items/BOLT-0042", body), ["location"], "PUT unlisted location");
  assert.deepEqual(call("GET", "/items/BOLT-0042").body, GOOD);
}

export function listed_location_accepted_on_put() {
  const codes = listedCodes();
  const call = seeded();
  const body = { name: "Hex bolt M8", quantity: 5, price_cents: 35, location: codes[codes.length - 1] };
  const response = call("PUT", "/items/BOLT-0042", body);
  assert.equal(response.status, 200, `PUT listed location: expected 200, got ${response.status}`);
  assert.equal(response.body.location, codes[codes.length - 1]);
}

export function items_without_location_stay_valid() {
  const call = api();
  assert.equal(call("POST", "/items", GOOD).status, 201);
  const put = call("PUT", "/items/BOLT-0042", { name: "Hex bolt M8 zinc", quantity: 3, price_cents: 36 });
  assert.equal(put.status, 200);
  assert.equal(put.body.location, undefined);
}

// R4

export function listing_is_ordered_and_filters_low_stock() {
  const call = api();
  call("POST", "/items", OTHER);
  call("POST", "/items", GOOD);
  call("POST", "/items", { sku: "CLIP-0100", name: "Clip", quantity: 10, price_cents: 5 });
  assert.deepEqual(call("GET", "/items").body.items.map((item) => item.sku), ["BOLT-0042", "CLIP-0100", "NUTS-0007"]);
  const low = call("GET", "/items", undefined, { low_stock: "10" });
  assert.deepEqual(low.body.items.map((item) => item.sku), ["CLIP-0100", "NUTS-0007"]);
}

export function create_answers_201_with_location_header() {
  const response = api()("POST", "/items", GOOD);
  assert.equal(response.status, 201);
  assert.deepEqual(response.body, GOOD);
  const header = Object.entries(response.headers).find(([name]) => name.toLowerCase() === "location");
  assert.equal(header?.[1], "/items/BOLT-0042");
}

export function duplicate_sku_is_409() {
  const call = seeded();
  const response = call("POST", "/items", { ...GOOD, quantity: 1 });
  assert.equal(response.status, 409);
  assert.equal(response.body.error, "conflict");
  assert.equal(call("GET", "/items/BOLT-0042").body.quantity, 120);
}

export function put_replaces_an_existing_item() {
  const call = seeded();
  const response = call("PUT", "/items/BOLT-0042", { name: "Hex bolt M8 zinc", quantity: 90, price_cents: 38 });
  assert.equal(response.status, 200);
  assert.deepEqual(response.body, { sku: "BOLT-0042", name: "Hex bolt M8 zinc", quantity: 90, price_cents: 38 });
  assert.deepEqual(call("GET", "/items/BOLT-0042").body, response.body);
}

export function adjust_changes_the_quantity() {
  const call = seeded();
  assert.equal(call("POST", "/items/BOLT-0042/adjust", { delta: -20 }).body.quantity, 100);
  assert.equal(call("POST", "/items/BOLT-0042/adjust", { delta: 7 }).body.quantity, 107);
  assert.equal(call("GET", "/items/BOLT-0042").body.quantity, 107);
}

export function delete_answers_204() {
  const call = seeded();
  const response = call("DELETE", "/items/BOLT-0042");
  assert.equal(response.status, 204);
  assert.deepEqual(call("GET", "/items").body.items.map((item) => item.sku), ["NUTS-0007"]);
}
