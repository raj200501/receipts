/** Blending colors. */

import { ColorError } from "./errors.ts";
import type { Rgb } from "./types.ts";

/**
 * Blend two colors channel by channel: amount 0 is `from`, 1 is `to`, and 0.5 is the
 * midpoint. Channels are rounded to whole numbers.
 */
export function mix(from: Rgb, to: Rgb, amount: number): Rgb {
  if (!(amount >= 0 && amount <= 1)) {
    throw new ColorError(`mix amount must be between 0 and 1, got ${amount}`);
  }
  const blend = (a: number, b: number) => Math.round(a + (b - a) * amount);
  return { r: blend(from.r, to.r), g: blend(from.g, to.g), b: blend(from.b, to.b) };
}
