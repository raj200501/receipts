/** Reading colors from text. */

import { ColorError } from "./errors.ts";
import { hslToRgb } from "./hsl.ts";
import type { Rgb } from "./types.ts";

const HEX = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
const RGB = /^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/;
const HSL = /^hsl\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)%\s*,\s*(\d+(?:\.\d+)?)%\s*\)$/;

function channel(text: string, original: string): number {
  const value = Number(text);
  if (value > 255) {
    throw new ColorError(`"${original}": channel ${value} is above 255`);
  }
  return value;
}

/**
 * Read `#rgb`, `#rrggbb`, `rgb(r, g, b)`, or `hsl(h, s%, l%)` (surrounding spaces are
 * ignored). The hue of an hsl() color is taken modulo 360; saturation and lightness are
 * percentages from 0 to 100.
 */
export function parseColor(text: string): Rgb {
  const trimmed = text.trim();
  const hex = HEX.exec(trimmed);
  if (hex !== null) {
    const digits =
      hex[1].length === 3
        ? [...hex[1]].map((digit) => digit + digit).join("")
        : hex[1];
    return {
      r: Number.parseInt(digits.slice(0, 2), 16),
      g: Number.parseInt(digits.slice(2, 4), 16),
      b: Number.parseInt(digits.slice(4, 6), 16),
    };
  }
  const rgb = RGB.exec(trimmed);
  if (rgb !== null) {
    return {
      r: channel(rgb[1], trimmed),
      g: channel(rgb[2], trimmed),
      b: channel(rgb[3], trimmed),
    };
  }
  const hsl = HSL.exec(trimmed);
  if (hsl !== null) {
    return hslToRgb({ h: Number(hsl[1]), s: Number(hsl[2]), l: Number(hsl[3]) });
  }
  throw new ColorError(
    `"${text}" is not a color (use #rgb, #rrggbb, rgb(r, g, b), or hsl(h, s%, l%))`,
  );
}
