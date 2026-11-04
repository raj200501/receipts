/** Conversion between sRGB and HSL (hue, saturation, lightness). */

import { ColorError } from "./errors.ts";
import type { Hsl, Rgb } from "./types.ts";

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

/**
 * The HSL form of a color: hue in degrees from 0 up to (not including) 360, saturation
 * and lightness in percent from 0 to 100, each rounded to one decimal place. Grays have
 * hue 0 and saturation 0.
 */
export function rgbToHsl(color: Rgb): Hsl {
  const r = color.r / 255;
  const g = color.g / 255;
  const b = color.b / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  const lightness = (max + min) / 2;
  if (delta === 0) {
    return { h: 0, s: 0, l: round1(lightness * 100) };
  }
  const saturation = delta / (1 - Math.abs(2 * lightness - 1));
  let hue: number;
  if (max === r) {
    hue = 60 * (((g - b) / delta + 6) % 6);
  } else if (max === g) {
    hue = 60 * ((b - r) / delta + 2);
  } else {
    hue = 60 * ((r - g) / delta + 4);
  }
  return { h: round1(hue) % 360, s: round1(saturation * 100), l: round1(lightness * 100) };
}

/**
 * The sRGB color for an HSL color, with whole-number channels. The hue is taken modulo
 * 360 (so -120 and 480 are 240 and 120); saturation and lightness must be from 0 to 100.
 */
export function hslToRgb(color: Hsl): Rgb {
  const { h, s, l } = color;
  if (![h, s, l].every(Number.isFinite)) {
    throw new ColorError("hsl values must be finite numbers");
  }
  if (s < 0 || s > 100 || l < 0 || l > 100) {
    throw new ColorError(`hsl saturation and lightness must be from 0 to 100, got ${s} and ${l}`);
  }
  const hue = (((h % 360) + 360) % 360) / 60;
  const sat = s / 100;
  const light = l / 100;
  const chroma = (1 - Math.abs(2 * light - 1)) * sat;
  const x = chroma * (1 - Math.abs((hue % 2) - 1));
  const m = light - chroma / 2;
  const sector: Array<[number, number, number]> = [
    [chroma, x, 0],
    [x, chroma, 0],
    [0, chroma, x],
    [0, x, chroma],
    [x, 0, chroma],
    [chroma, 0, x],
  ];
  const [r, g, b] = sector[Math.floor(hue)];
  const scale = (value: number) => Math.round((value + m) * 255);
  return { r: scale(r), g: scale(g), b: scale(b) };
}

/** `hsl(h, s%, l%)` with every part rounded to a whole number. */
export function formatHsl(color: Rgb): string {
  const { h, s, l } = rgbToHsl(color);
  return `hsl(${Math.round(h) % 360}, ${Math.round(s)}%, ${Math.round(l)}%)`;
}
