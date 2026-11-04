"""Plain-text output: the summary table, and the listing of the most common values."""

from __future__ import annotations

from collections.abc import Sequence

from csvsummary.stats import ColumnStats

EMPTY_VALUE = "(empty)"
NUMBER_WIDTH = 10


def _mean(stats: ColumnStats) -> str:
    return "" if stats.mean is None else f"{stats.mean:.2f}"


def one_line(value: str) -> str:
    """``value`` for a listing: each line break inside it shown as the two characters ``\\n``.

    docs/FORMAT.md requires every listed value to stay on one line.
    """
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def render_summary(rows: int, columns: Sequence[ColumnStats]) -> str:
    """The row and column counts, a blank line, then one aligned line per column."""
    width = max([len("column"), *(len(stats.name) for stats in columns)])
    cells = [("column", "filled", "distinct", "min", "max", "mean")]
    cells.extend(
        (s.name, str(s.filled), str(s.distinct), s.minimum, s.maximum, _mean(s)) for s in columns
    )
    lines = [f"rows: {rows}", f"columns: {len(columns)}", ""]
    for name, filled, distinct, low, high, mean in cells:
        line = (
            f"{name:<{width}}  {filled:>6}  {distinct:>8}  "
            f"{low:<{NUMBER_WIDTH}}  {high:<{NUMBER_WIDTH}}  {mean}"
        )
        lines.append(line.rstrip())
    return "\n".join(lines) + "\n"


def render_top(pairs: Sequence[tuple[str, int]]) -> str:
    """One line per value: its count in six characters, two spaces, then the value."""
    return "".join(f"{count:>6}  {one_line(value) or EMPTY_VALUE}\n" for value, count in pairs)
