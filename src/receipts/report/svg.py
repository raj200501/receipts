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


TERMINAL_STYLE = """<style>
svg { --bg: #f6f8fa; --fg: #1f2328; --muted: #59636e; --ok: #1a7f37; --bad: #cf222e;
      --warn: #9a6700; --edge: #d1d9e0; }
@media (prefers-color-scheme: dark) {
  svg { --bg: #151b23; --fg: #e6edf3; --muted: #9198a1; --ok: #3fb950; --bad: #f85149;
        --warn: #d29922; --edge: #3d444d; }
}
rect.panel { fill: var(--bg); stroke: var(--edge); }
text { fill: var(--fg); font: 12.5px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
       white-space: pre; }
.muted { fill: var(--muted); } .ok { fill: var(--ok); } .bad { fill: var(--bad); }
.warn { fill: var(--warn); } .title { font-weight: 600; }
</style>"""


def _line_class(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("[SUPPORTED"):
        return "ok"
    if stripped.startswith(("[CONTRADICTED", "[NOT MENTIONED")):
        return "bad"
    if stripped.startswith("[UNVERIFIABLE"):
        return "warn"
    if stripped.startswith(("Summary:", "===")):
        return "title"
    if line.startswith("    "):
        return "muted"
    return ""


def text_panel(lines: Sequence[str], *, title: str, width: int = 860, wrap: int = 108) -> str:
    """A terminal-style panel of monospace lines (long lines wrapped), as an SVG string.

    Lines that start with a verdict tag are colored by verdict, so the panel reads like
    the console output it reproduces, in both GitHub themes.
    """
    import textwrap

    if not lines:
        raise ValueError("a panel needs at least one line")
    rows: list[tuple[str, str]] = []
    for line in lines:
        indent = len(line) - len(line.lstrip())
        pieces = textwrap.wrap(
            line.strip(), wrap - indent, subsequent_indent="  ", break_long_words=True
        ) or [""]
        cls = _line_class(line)
        rows.extend((" " * indent + piece, cls) for piece in pieces)
    step, top = 17, 44
    height = top + step * len(rows) + 16
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{escape(title)}">',
        TERMINAL_STYLE,
        f'<rect class="panel" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8"/>',
        f'<text class="title" x="16" y="26">{escape(title)}</text>',
    ]
    for i, (text, cls) in enumerate(rows):
        attr = f' class="{cls}"' if cls else ""
        y = top + step * (i + 1) - 4
        parts.append(f'<text{attr} x="16" y="{y}" xml:space="preserve">{escape(text)}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
