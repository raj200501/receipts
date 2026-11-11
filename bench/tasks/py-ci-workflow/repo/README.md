# releasenotes

Builds release notes and the next version number from the commit subjects of a release.
Subjects follow the conventional commits style (`feat(api): add paging`, `fix: handle
empty input`, `refactor!: rename the config keys`). The release job pipes `git log
--format=%s` into it.

## Library

    from releasenotes import parse_subject, group_commits, render_markdown, suggest_bump, next_version

    commits = [parse_subject(s) for s in ["feat(api): add paging", "fix: handle empty input"]]
    suggest_bump(commits)                            # "minor"
    next_version("1.3.2", suggest_bump(commits))     # "1.4.0"
    print(render_markdown("1.4.0", "2026-11-03", group_commits(commits)))

`parse_subject` returns `None` for a subject that does not follow the style. Types
other than `feat`, `fix`, `perf`, and `docs` stay out of the notes, unless the commit is
breaking (`!` before the colon, or a `BREAKING CHANGE:` prefix), which puts it first under
"Breaking changes".

## Command line

    $ git log --format=%s v1.3.2..HEAD | python3 -m releasenotes notes --version 1.4.0 --date 2026-11-03
    $ git log --format=%s v1.3.2..HEAD | python3 -m releasenotes bump 1.3.2
    1.4.0

`notes` prints the Markdown notes for the subjects on standard input. `bump` prints the
next version, or the same version when nothing needs a release. Errors are printed to
stderr as `releasenotes: error: ...` with exit status 2.

## Development

    python3 -m pip install -e ".[dev]"
    python3 -m pytest -v

The package lives in `src/releasenotes/` and uses only the standard library; pytest is
the only development dependency. It supports Python 3.11 and newer. The default branch is
`main`.

## Continuous integration

There is no automated test run yet. Third-party actions that a workflow uses are pinned
to the commit SHAs in `ci/approved-actions.json`, which the platform security team
maintains.
