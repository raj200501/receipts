"""Dependency-free SVG figures with intervals, generated only from artifact data.

Colors are CSS custom properties with light defaults and a dark-mode override, so a
figure reads in both GitHub themes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

STYLE = """<style>
svg { --fg: #1f2328; --muted: #59636e; --grid: #d1d9e0; --bar: #3b6ea8; --bar2: #c56a2d; }
@media (prefers-color-scheme: dark) {
  svg { --fg: #e6edf3; --muted: #9198a1; --grid: #3d444d; --bar: #6ea3df; --bar2: #e39a62; }
}
text { fill: var(--fg); font: 12px -apple-system, Segoe UI, Helvetica, Arial, sans-serif; }
.muted { fill: var(--muted); } .grid { stroke: var(--grid); stroke-width: 1; }
.bar { fill: var(--bar); } .bar2 { fill: var(--bar2); }
.ci { stroke: var(--fg); stroke-width: 1.5; }
</style>"""


@dataclass(frozen=True)
class Bar:
    """One bar: a proportion with its interval."""

    label: str
    value: float
    low: float
    high: float
    series: int = 0  # 0 or 1, for two-color grouped charts


def bar_chart(
    bars: Sequence[Bar],
    *,
    title: str,
    y_label: str,
    width: int = 640,
    height: int = 320,
    y_max: float = 1.0,
) -> str:
    """A vertical bar chart of proportions with interval whiskers, as an SVG string."""
    if not bars:
        raise ValueError("a chart needs at least one bar")
    left, right, top, bottom = 56, 16, 36, 64
    plot_w, plot_h = width - left - right, height - top - bottom
    slot = plot_w / len(bars)
    bar_w = slot * 0.6

    def y(v: float) -> float:
        return top + plot_h * (1 - min(max(v, 0.0), y_max) / y_max)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{escape(title)}">',
        STYLE,
        f'<text x="{left}" y="20">{escape(title)}</text>',
    ]
    for i in range(5):
        tick = y_max * i / 4
        ty = y(tick)
        parts.append(
            f'<line class="grid" x1="{left}" x2="{width - right}" y1="{ty:.1f}" y2="{ty:.1f}"/>'
        )
        parts.append(
            f'<text class="muted" x="{left - 6}" y="{ty + 4:.1f}" text-anchor="end">'
            f"{tick:.2f}</text>"
        )
    parts.append(
        f'<text class="muted" transform="translate(14 {top + plot_h / 2:.1f}) rotate(-90)" '
        f'text-anchor="middle">{escape(y_label)}</text>'
    )
    for i, bar in enumerate(bars):
        x = left + i * slot + (slot - bar_w) / 2
        cls = "bar2" if bar.series else "bar"
        parts.append(
            f'<rect class="{cls}" x="{x:.1f}" y="{y(bar.value):.1f}" width="{bar_w:.1f}" '
            f'height="{y(0) - y(bar.value):.1f}"><title>{escape(bar.label)}: {bar.value:.3f} '
            f"[{bar.low:.3f}, {bar.high:.3f}]</title></rect>"
        )
        cx = x + bar_w / 2
        parts.append(
            f'<line class="ci" x1="{cx:.1f}" x2="{cx:.1f}" '
            f'y1="{y(bar.low):.1f}" y2="{y(bar.high):.1f}"/>'
        )
        for edge in (bar.low, bar.high):
            parts.append(
                f'<line class="ci" x1="{cx - 5:.1f}" x2="{cx + 5:.1f}" '
                f'y1="{y(edge):.1f}" y2="{y(edge):.1f}"/>'
            )
        parts.append(
            f'<text x="{cx:.1f}" y="{height - bottom + 16}" text-anchor="middle">'
            f"{escape(bar.label)}</text>"
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
