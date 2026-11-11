"""``receipts wrap``: annotate any agent CLI's final report with receipts verdicts.

    python -m receipts.hook.wrap --workspace DIR --test-cmd "pytest -q" \\
        [--report-file PATH] [--ledger PATH] -- <agent command ...>

Other agent CLIs have no hook interface receipts can rely on, so the wrapper records
what it can observe from outside: the workspace state before the agent runs, and
afterwards a snapshot (the diff against that state and a rerun of the tests inside the
sandbox). The final report is the file at ``--report-file`` if given, else the agent's
stdout. The report's claims are checked against that ledger and an annotation block is
printed after the report. The ledger's ``run_start`` records that the agent's commands
were not recorded, so claims about individual commands the agent ran are unverifiable
here, never contradicted.

The agent command itself runs as the user's own process, exactly as it would without
the wrapper; only the test rerun goes through the receipts sandbox.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from receipts.claims.extract import extract_claims
from receipts.ledger.events import Ledger, LedgerWriter
from receipts.ledger.recorder import Recorder
from receipts.ledger.snapshot import take_snapshot
from receipts.sandbox.api import Sandbox
from receipts.verify import Label, RunVerification, verify_run

MARK = {
    Label.SUPPORTED: "ok",
    Label.CONTRADICTED: "CONTRADICTED",
    Label.UNVERIFIABLE: "unverifiable",
}


# Git for the start state ignores the user's global and system configuration (as the
# sandbox's git does), so ``.gitignore`` decides what the start state holds exactly as
# it decides what the post-run diff holds; the identity only names the start commit.
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "receipts wrap",
    "GIT_AUTHOR_EMAIL": "receipts-wrap@localhost.invalid",
    "GIT_COMMITTER_NAME": "receipts wrap",
    "GIT_COMMITTER_EMAIL": "receipts-wrap@localhost.invalid",
}


def _git(workspace: Path, *args: str, index: Path | None = None) -> str:
    env = {**os.environ, **_GIT_ENV}
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout.strip()


def start_state(workspace: Path) -> str:
    """A commit capturing the workspace before the agent runs, without changing it.

    The post-run diff stages the whole working tree, untracked files included, and
    compares it with this commit, so the start state is staged the same way: ``git add
    -A`` into a temporary index, then ``write-tree`` and ``commit-tree``. A file that was
    untracked before the run is therefore not reported as added by the agent. The
    working tree, the real index, the refs, and the stash list are untouched. With
    nothing uncommitted, HEAD itself is the start state.
    """
    head = _git(workspace, "rev-parse", "HEAD")
    with tempfile.TemporaryDirectory(prefix="receipts-wrap-") as tmp:
        index = Path(tmp) / "index"
        _git(workspace, "-c", "core.fsmonitor=false", "add", "-A", "--", ".", index=index)
        tree = _git(workspace, "write-tree", index=index)
    if tree == _git(workspace, "rev-parse", "HEAD^{tree}"):
        return head
    return _git(workspace, "commit-tree", tree, "-p", head, "-m", "receipts wrap: start state")


@dataclass(frozen=True)
class WrapResult:
    """What the wrapper observed and concluded."""

    exit_code: int
    report: str
    verification: RunVerification
    annotation: str


def annotate(verification: RunVerification) -> str:
    """The annotation block printed after the report."""
    lines = ["", "---- receipts ----"]
    for claim, verdict in zip(verification.claims, verification.verdicts, strict=True):
        lines.append(f"[{MARK[verdict.label]}] {claim.text.strip()}: {verdict.reason}")
    if not verification.claims:
        lines.append("no checkable claims found in the report")
    for omission in verification.omissions:
        lines.append(f"[not mentioned] {omission.detail}")
    counts = verification.counts()
    lines.append(
        f"{counts['supported']} supported, {counts['contradicted']} contradicted, "
        f"{counts['unverifiable']} unverifiable"
    )
    return "\n".join(lines) + "\n"


def wrap(
    command: Sequence[str],
    workspace: Path,
    test_cmd: str,
    ledger_path: Path,
    sandbox: Sandbox,
    *,
    report_file: Path | None = None,
    runner: Callable[[Sequence[str], Path], tuple[int, str]] | None = None,
) -> WrapResult:
    """Run ``command`` in ``workspace``, then check its final report."""
    base = start_state(workspace)
    run = runner or _run_agent
    code, stdout = run(command, workspace)
    report = report_file.read_text(encoding="utf-8") if report_file else stdout
    if ledger_path.exists():
        ledger_path.unlink()
    recorder = Recorder(LedgerWriter(ledger_path), workspace=workspace)
    recorder.record_run_start(
        run_id=ledger_path.stem,
        task_id=workspace.name,
        agent=Path(command[0]).name if command else "unknown",
        model="unknown",
        config_id="wrap",
        workspace=str(workspace),
        base_commit=base,
        records_agent_commands=False,
    )
    take_snapshot(sandbox, recorder, base, test_cmd)
    recorder.record_run_end(report, 0, "finished" if code == 0 else f"exit {code}")
    claims = extract_claims(report)
    verification = verify_run(claims, Ledger.load(ledger_path), report=report)
    return WrapResult(code, report, verification, annotate(verification))


def _run_agent(command: Sequence[str], workspace: Path) -> tuple[int, str]:
    proc = subprocess.run(list(command), cwd=workspace, capture_output=True, text=True, check=False)
    sys.stderr.write(proc.stderr)
    return proc.returncode, proc.stdout


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point; exits with the agent's own exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--test-cmd", required=True)
    parser.add_argument("--report-file", type=Path, default=None)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = [c for c in args.command if c != "--"]
    if not command:
        parser.error("give the agent command after --")
    from receipts.sandbox.api import SandboxPolicy
    from receipts.sandbox.select import make_sandbox

    workspace = args.workspace.resolve()
    ledger = args.ledger or workspace.parent / f".receipts-{workspace.name}.jsonl"
    result = wrap(
        command,
        workspace,
        args.test_cmd,
        ledger,
        make_sandbox(workspace, SandboxPolicy()),
        report_file=args.report_file,
    )
    sys.stdout.write(result.report)
    sys.stdout.write(result.annotation)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
