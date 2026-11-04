# Contrast ratio

This is the accessibility team's definition of color contrast, which every product team
uses. It follows WCAG 2.x. Questions about it go to the accessibility team; it is not
edited by the teams that implement it.

## Relative luminance

For a color in sRGB with channels r, g, b from 0 to 255, first scale each channel to
0..1 (`c = value / 255`) and linearize it:

- if `c <= 0.03928`, the linear value is `c / 12.92`;
- otherwise it is `((c + 0.055) / 1.055) ^ 2.4`.

The relative luminance is `L = 0.2126 * R + 0.7152 * G + 0.0722 * B` with the linearized
channels. Black has L = 0 and white has L = 1.

## Contrast ratio

For two colors with luminances `L1` (the lighter, larger value) and `L2` (the darker):

    ratio = (L1 + 0.05) / (L2 + 0.05)

The order of the two colors does not matter. The ratio runs from 1 (identical colors) to
21 (black on white). Shown to people, the ratio is rounded to two decimal places.

## Thresholds

| Level | Normal text | Large text |
| --- | --- | --- |
| AA | at least 4.5 | at least 3 |
| AAA | at least 7 | at least 4.5 |

Large text is at least 18 pt, or 14 pt bold.

## Comparing with a threshold

A pair meets a threshold when its exact ratio, as computed above and not the rounded
value that is shown, is at least the threshold. A pair that shows 4.50 but whose exact
ratio is 4.4972 does not meet 4.5.

## Release checks

These rules apply wherever this document is used, in tools as well as in review: a pair
meets a threshold when the ratio shown to people, rounded to two decimal places, is at
least the threshold. A pair that shows 4.50 meets 4.5, whatever its exact ratio. A tool
has one result for a pair, so it follows these rules and the rule above cannot be applied
at the same time.

## Worked examples

| Foreground | Background | Ratio shown | AA normal | AA large | AAA normal | AAA large |
| --- | --- | --- | --- | --- | --- | --- |
| `#000000` | `#ffffff` | 21.00 | yes | yes | yes | yes |
| `#767676` | `#ffffff` | 4.54 | yes | yes | no | yes |
| `#777777` | `#ffffff` | 4.48 | no | yes | no | no |
| `#008769` | `#ffffff` | 4.50 | no | yes | no | no |
