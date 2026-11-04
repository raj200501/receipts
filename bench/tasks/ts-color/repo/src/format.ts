/** Writing colors as text. */

import type { Rgb } from "./types.ts";

function hex2(value: number): string {
  return value.toString(16).padStart(2, "0");
}

/** `#rrggbb` in lower case. */
export function toHex(color: Rgb): string {
  return `#${hex2(color.r)}${hex2(color.g)}${hex2(color.b)}`;
}

/** `rgb(r, g, b)`. */
export function toRgbString(color: Rgb): string {
  return `rgb(${color.r}, ${color.g}, ${color.b})`;
}
