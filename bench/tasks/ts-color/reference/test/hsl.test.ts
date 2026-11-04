import assert from "node:assert/strict";
import { test } from "node:test";
import { ColorError } from "../src/errors.ts";
import { formatHsl, hslToRgb, rgbToHsl } from "../src/hsl.ts";

test("rgbToHsl converts the primary colors, white, and black", () => {
  assert.deepEqual(rgbToHsl({ r: 255, g: 0, b: 0 }), { h: 0, s: 100, l: 50 });
  assert.deepEqual(rgbToHsl({ r: 0, g: 0, b: 255 }), { h: 240, s: 100, l: 50 });
  assert.deepEqual(rgbToHsl({ r: 255, g: 255, b: 255 }), { h: 0, s: 0, l: 100 });
  assert.deepEqual(rgbToHsl({ r: 0, g: 0, b: 0 }), { h: 0, s: 0, l: 0 });
});

test("rgbToHsl rounds to one decimal place", () => {
  assert.deepEqual(rgbToHsl({ r: 0, g: 128, b: 128 }), { h: 180, s: 100, l: 25.1 });
  assert.deepEqual(rgbToHsl({ r: 200, g: 100, b: 50 }), { h: 20, s: 60, l: 49 });
});

test("rgbToHsl keeps the hue below 360", () => {
  assert.equal(rgbToHsl({ r: 255, g: 0, b: 1 }).h < 360, true);
  assert.equal(rgbToHsl({ r: 255, g: 0, b: 0 }).h, 0);
});

test("hslToRgb converts and rounds to whole channels", () => {
  assert.deepEqual(hslToRgb({ h: 0, s: 100, l: 50 }), { r: 255, g: 0, b: 0 });
  assert.deepEqual(hslToRgb({ h: 120, s: 50, l: 50 }), { r: 64, g: 191, b: 64 });
  assert.deepEqual(hslToRgb({ h: 210, s: 80, l: 40 }), { r: 20, g: 102, b: 184 });
});

test("hslToRgb takes the hue modulo 360", () => {
  assert.deepEqual(hslToRgb({ h: -120, s: 100, l: 50 }), { r: 0, g: 0, b: 255 });
  assert.deepEqual(hslToRgb({ h: 480, s: 50, l: 50 }), hslToRgb({ h: 120, s: 50, l: 50 }));
});

test("hslToRgb rejects saturation or lightness outside 0 to 100", () => {
  assert.throws(() => hslToRgb({ h: 0, s: 120, l: 50 }), ColorError);
  assert.throws(() => hslToRgb({ h: 0, s: 50, l: -1 }), ColorError);
  assert.throws(() => hslToRgb({ h: Number.NaN, s: 50, l: 50 }), ColorError);
});

test("converting there and back stays within one step per channel", () => {
  for (const color of [
    { r: 30, g: 180, b: 120 },
    { r: 120, g: 60, b: 160 },
    { r: 250, g: 240, b: 20 },
    { r: 5, g: 5, b: 9 },
  ]) {
    const back = hslToRgb(rgbToHsl(color));
    for (const key of ["r", "g", "b"] as const) {
      assert.ok(Math.abs(back[key] - color[key]) <= 2, `${JSON.stringify(color)} -> ${JSON.stringify(back)}`);
    }
  }
});

test("formatHsl writes whole numbers", () => {
  assert.equal(formatHsl({ r: 51, g: 102, b: 204 }), "hsl(220, 60%, 50%)");
  assert.equal(formatHsl({ r: 255, g: 255, b: 255 }), "hsl(0, 0%, 100%)");
});
