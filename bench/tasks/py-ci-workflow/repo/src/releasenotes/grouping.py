"""Group commits into the sections of the release notes."""

from __future__ import annotations

from collections.abc import Iterable

from releasenotes.commits import Commit

#: Section title for each commit type that appears in the notes, in notes order.
SECTIONS: dict[str, str] = {
    "feat": "Features",
    "fix": "Bug fixes",
    "perf": "Performance",
    "docs": "Documentation",
}


def group_commits(commits: Iterable[Commit]) -> dict[str, list[Commit]]:
    """Commits per section title, in notes order, without empty sections.

    Types that are not in :data:`SECTIONS` (refactor, test, build, ci, chore) are left out
    unless the commit is breaking; a breaking commit of any type goes to "Breaking changes",
    which comes first.
    """
    groups: dict[str, list[Commit]] = {}
    commit_list = list(commits)
    breaking = [c for c in commit_list if c.breaking]
    if breaking:
        groups["Breaking changes"] = breaking
    for commit_type, title in SECTIONS.items():
        found = [c for c in commit_list if c.type == commit_type and not c.breaking]
        if found:
            groups[title] = found
    return groups
