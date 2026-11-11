import assert from "node:assert/strict";
import { test } from "node:test";
import { toHex, toRgbString } from "../src/format.ts";

test("toHex pads each channel to two digits", () => {
  assert.equal(toHex({ r: 0, g: 5, b: 255 }), "#0005ff");
});

test("toHex writes lower case", () => {
  assert.equal(toHex({ r: 171, g: 205, b: 239 }), "#abcdef");
});

test("toRgbString writes the channels in order", () => {
  assert.equal(toRgbString({ r: 10, g: 20, b: 30 }), "rgb(10, 20, 30)");
});
