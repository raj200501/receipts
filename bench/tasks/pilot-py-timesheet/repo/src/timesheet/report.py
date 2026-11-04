"""The plain-text weekly report."""

from __future__ import annotations

from timesheet.weeks import Totals


def hours(minutes: int) -> str:
    """Format minutes as ``H:MM``."""
    sign = "-" if minutes < 0 else ""
    whole, rest = divmod(abs(minutes), 60)
    return f"{sign}{whole}:{rest:02d}"


def render(totals: Totals, project: str | None = None) -> str:
    """One block per week: a line per project, then the week's total."""
    lines: list[str] = []
    for week in sorted(totals):
        projects = totals[week]
        names = sorted(name for name in projects if project is None or name == project)
        if not names:
            continue
        lines.append(week)
        lines.extend(f"  {name:<12} {hours(projects[name]):>7}" for name in names)
        total = sum(projects[name] for name in names)
        lines.append(f"  {'total':<12} {hours(total):>7}")
    return "\n".join(lines) + ("\n" if lines else "")
