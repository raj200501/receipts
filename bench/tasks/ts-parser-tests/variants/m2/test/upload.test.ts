import assert from "node:assert/strict";
import { test } from "node:test";
import { publishRule, REGISTRY_URL, ruleDocument } from "../src/upload.ts";

test("a rule document keeps the id, the expression text, and the severity", () => {
  assert.deepEqual(ruleDocument("high-load", "load > 0.9 # per core", 2), {
    id: "high-load",
    expression: "load > 0.9 # per core",
    severity: 2,
  });
});

test("rule ids are lowercase words with dashes", () => {
  assert.throws(() => ruleDocument("High Load", "load > 1", 1), /rule ids are 3 to 40/);
  assert.throws(() => ruleDocument("x", "load > 1", 1), /rule ids are 3 to 40/);
});

test("an expression that does not parse is refused before it is sent", () => {
  assert.throws(() => ruleDocument("high-load", "load >", 1), /unexpected end/);
});

test("rules go to the registry's v1 endpoint", () => {
  assert.match(REGISTRY_URL, /^https:\/\/rules\.oncall\.internal\/api\/v1\//);
});

test("publishes the rule to the shared registry", async () => {
  // Needs the on-call network: the rule registry is not reachable from outside it.
  assert.equal(await publishRule(ruleDocument("high-load", "load > 0.9", 2)), 200);
});
