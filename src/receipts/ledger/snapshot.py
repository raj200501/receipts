"""Post-run snapshot: ground truth taken inside the sandbox after the agent stops.

:func:`take_snapshot` runs three steps, each through the given
:class:`~receipts.sandbox.api.Sandbox`, and records them with source
``"snapshot"``:

1. **Diff.** ``git diff --numstat -M`` and ``--name-status -M`` against the base
   commit, computed from a temporary index built with ``git add -A`` so that
   untracked (not ignored) files appear as added and deleted files as deleted.
   The workspace's own index is never touched. Old and new contents of changed
   manifests are read (``git show`` and ``cat`` in the sandbox, so a symlink
   cannot reach host files) to list dependency changes. One ``diff`` event.
2. **Test rerun.** ``test_cmd`` runs again; its ``command`` event and every
   derived ``test_run`` (and lint or type-check run) are recorded.
3. **Hidden checks** (optional). ``hidden_check_cmd`` runs; its ``command``
   event is recorded without derived runs (its log text is not the task's test
   suite), and its last stdout line becomes one ``hidden_check`` event.

The git plumbing commands of step 1 are bookkeeping and are not recorded as
``command`` events. A failing step does not stop the later ones; what went
wrong is listed in :attr:`SnapshotResult.problems`. Call this before
``run_end``, which must stay the last event.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from receipts.ledger.events import DependencyChange, DiffFile
from receipts.ledger.parsers.git import parse_git_diff
from receipts.ledger.parsers.hidden import parse_hidden_check_list
from receipts.ledger.parsers.manifests import dependency_changes, is_manifest
from receipts.ledger.recorder import Recorder
from receipts.sandbox.api import CommandOutcome, Sandbox

SEPARATOR = "--receipts-name-status--"
INDEX_NAME = "receipts-snapshot.index"
_REVISION = re.compile(r"[0-9A-Za-z][0-9A-Za-z._/@{}^~-]*")


@dataclass(frozen=True)
class SnapshotResult:
    """Sequence numbers of the events :func:`take_snapshot` wrote, and any problems.

    Attributes:
        diff_seq: The ``diff`` event, or None if the diff could not be taken.
        test_command_seq: The ``command`` event of the test rerun.
        test_run_seqs: ``test_run`` events derived from the rerun (empty when its
            output held no recognizable test summary).
        hidden_command_seq: The hidden check ``command`` event, if one ran.
        hidden_check_seq: The ``hidden_check`` event, or None if no hidden check
            command was given or its output broke the contract.
        problems: One plain sentence per step that did not fully succeed.
    """

    diff_seq: int | None
    test_command_seq: int
    test_run_seqs: tuple[int, ...]
    hidden_command_seq: int | None
    hidden_check_seq: int | None
    problems: tuple[str, ...]


def diff_script(base_commit: str) -> str:
    """The bash script that prints numstat, :data:`SEPARATOR`, then name-status output."""
    base = shlex.quote(base_commit)
    git = "git -c core.quotePath=false diff --cached --no-ext-diff --no-color -M"
    return (
        "set -eu\n"
        f'idx="$(git rev-parse --git-path {INDEX_NAME})"\n'
        "trap 'rm -f \"$idx\"' EXIT\n"
        'rm -f "$idx"\n'
        'export GIT_INDEX_FILE="$idx"\n'
        "git -c core.fsmonitor=false add -A -- .\n"
        f"{git} --numstat {base} --\n"
        f"echo {SEPARATOR}\n"
        f"{git} --name-status {base} --\n"
    )


def _describe(outcome: CommandOutcome) -> str:
    detail = outcome.stderr.strip().splitlines()
    tail = f": {detail[-1]}" if detail else ""
    return f"exit {outcome.exit_code}{' (timed out)' if outcome.timed_out else ''}{tail}"


def _read(sandbox: Sandbox, cmd: str, what: str, problems: list[str]) -> str | None:
    """Stdout of ``cmd``, or None (with a problem noted) if it failed or was cut."""
    outcome = sandbox.run(cmd)
    if outcome.exit_code != 0 or outcome.timed_out:
        problems.append(f"could not read {what} ({_describe(outcome)})")
        return None
    if outcome.stdout_truncated:
        problems.append(f"{what} was truncated by the sandbox; dependency changes skipped")
        return None
    return outcome.stdout


def _dependency_changes(
    sandbox: Sandbox, base_commit: str, files: list[DiffFile], problems: list[str]
) -> list[DependencyChange]:
    changes: list[DependencyChange] = []
    for entry in files:
        path = entry["path"]
        old_path = entry.get("old_path", path)
        # A rename out of a manifest name counts as deleting it, into one as adding it.
        had_old = entry["status"] != "A" and is_manifest(old_path)
        has_new = entry["status"] != "D" and is_manifest(path)
        if not (had_old or has_new):
            continue
        old_text: str | None = None
        new_text: str | None = None
        if had_old:
            spec = shlex.quote(f"{base_commit}:{old_path}")
            old_text = _read(sandbox, f"git show {spec}", f"{old_path} at {base_commit}", problems)
            if old_text is None:
                continue
        if has_new:
            new_text = _read(sandbox, f"cat -- {shlex.quote(path)}", path, problems)
            if new_text is None:
                continue
        changes.extend(dependency_changes(path if has_new else old_path, old_text, new_text))
    return changes


def take_snapshot(
    sandbox: Sandbox,
    recorder: Recorder,
    base_commit: str,
    test_cmd: str,
    hidden_check_cmd: str | None = None,
) -> SnapshotResult:
    """Record the post-run diff, a test rerun, and hidden checks (see the module docstring).

    Raises:
        ValueError: ``base_commit`` is not a plain git revision (it must start
            with a letter or digit, so it can never be read as an option).
    """
    if not _REVISION.fullmatch(base_commit):
        raise ValueError(f"not a git revision: {base_commit!r}")
    problems: list[str] = []

    diff_seq: int | None = None
    outcome = sandbox.run(diff_script(base_commit))
    numstat, sep, name_status = outcome.stdout.partition(f"{SEPARATOR}\n")
    if outcome.exit_code != 0 or outcome.timed_out or not sep:
        problems.append(f"git diff against {base_commit} failed ({_describe(outcome)})")
    else:
        if outcome.stdout_truncated:
            problems.append(
                "git diff output was truncated by the sandbox; the file list is partial"
            )
        files = parse_git_diff(numstat, name_status)
        deps = _dependency_changes(sandbox, base_commit, files, problems)
        diff_seq = recorder.record_diff(base_commit, files, deps, source="snapshot")

    test_seq = recorder.record_command(sandbox.run(test_cmd), None, "snapshot")
    test_runs = tuple(
        event.seq for event in recorder.writer.events[test_seq + 1 :] if event.kind == "test_run"
    )
    if not test_runs:
        problems.append(f"no test summary recognized in the output of {test_cmd!r}")

    hidden_command_seq: int | None = None
    hidden_check_seq: int | None = None
    if hidden_check_cmd is not None:
        hidden = sandbox.run(hidden_check_cmd)
        hidden_command_seq = recorder.record_command(hidden, None, "snapshot", derive=False)
        checks = parse_hidden_check_list(hidden.stdout)
        if checks is None:
            problems.append(
                "hidden check output did not end with a JSON line of the form "
                f'{{"checks": [...]}} ({_describe(hidden)})'
            )
        else:
            hidden_check_seq = recorder.record_hidden_checks(checks, source="snapshot")

    return SnapshotResult(
        diff_seq=diff_seq,
        test_command_seq=test_seq,
        test_run_seqs=test_runs,
        hidden_command_seq=hidden_command_seq,
        hidden_check_seq=hidden_check_seq,
        problems=tuple(problems),
    )
