"""Render release notes as Markdown."""

from __future__ import annotations

from releasenotes.commits import Commit


def _line(commit: Commit) -> str:
    scope = f"**{commit.scope}:** " if commit.scope else ""
    return f"- {scope}{commit.description}"


def render_markdown(version: str, date: str, groups: dict[str, list[Commit]]) -> str:
    """The notes for one release: a heading, then one list per section.

    Args:
        version: Version number, without a leading ``v``.
        date: Release date as ``YYYY-MM-DD`` text.
        groups: Sections as returned by :func:`releasenotes.group_commits`.
    """
    out = [f"## {version} ({date})", ""]
    if not groups:
        out += ["No user-facing changes.", ""]
    for title, commits in groups.items():
        out += [f"### {title}", ""]
        out += [_line(commit) for commit in commits]
        out.append("")
    return "\n".join(out)
