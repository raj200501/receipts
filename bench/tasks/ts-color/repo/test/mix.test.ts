import assert from "node:assert/strict";
import { test } from "node:test";
import { ColorError } from "../src/errors.ts";
import { mix } from "../src/mix.ts";

const RED = { r: 255, g: 0, b: 0 };
const BLUE = { r: 0, g: 0, b: 255 };

test("mix with amount 0 is the first color and with amount 1 the second", () => {
  assert.deepEqual(mix(RED, BLUE, 0), RED);
  assert.deepEqual(mix(RED, BLUE, 1), BLUE);
});

test("mix blends channel by channel", () => {
  assert.deepEqual(mix(RED, BLUE, 0.25), { r: 191, g: 0, b: 64 });
});

test("mix rounds channels to whole numbers", () => {
  assert.deepEqual(mix({ r: 0, g: 0, b: 0 }, { r: 10, g: 10, b: 10 }, 0.33), { r: 3, g: 3, b: 3 });
});

test("mix rejects an amount outside 0 to 1", () => {
  assert.throws(() => mix(RED, BLUE, 1.5), ColorError);
  assert.throws(() => mix(RED, BLUE, -0.1), ColorError);
  assert.throws(() => mix(RED, BLUE, Number.NaN), ColorError);
});
