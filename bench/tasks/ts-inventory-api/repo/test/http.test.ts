import assert from "node:assert/strict";
import { test } from "node:test";
import { empty, isRecord, json, problem } from "../src/http.ts";

test("json sets the content type and merges extra headers", () => {
  const response = json(201, { ok: true }, { location: "/items/A" });
  assert.equal(response.status, 201);
  assert.deepEqual(response.headers, { "content-type": "application/json", location: "/items/A" });
  assert.deepEqual(response.body, { ok: true });
});

test("empty has no body and no headers", () => {
  assert.deepEqual(empty(204), { status: 204, headers: {}, body: null });
});

test("problem builds an error object", () => {
  const response = problem(409, "conflict", { sku: "A" });
  assert.equal(response.status, 409);
  assert.deepEqual(response.body, { error: "conflict", sku: "A" });
});

test("isRecord accepts objects only", () => {
  assert.equal(isRecord({}), true);
  assert.equal(isRecord([]), false);
  assert.equal(isRecord(null), false);
  assert.equal(isRecord("x"), false);
});
