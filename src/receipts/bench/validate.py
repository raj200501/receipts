"""Reference validation of one benchmark task, run entirely through a Sandbox.

:func:`validate_task` never runs task code on the host: it copies files into fresh
workspaces (plain file copies) and runs every command, including ``git``, through
``sandbox_factory(workspace)``. Each workspace is prepared the way
``receipts.study.runner`` prepares a run: the starting repository plus the
condition overlays, initialized as a git repository with one commit and
``.receipts_hidden/`` excluded; hidden checks are copied in only after the visible
tests ran. Overlays are applied in the order M1, M2, reference (they touch
disjoint files, so the order does not change the result).

Phases (each in its own workspace) and what must hold:

========== ======================== =================================================
phase      workspace                expectations
========== ======================== =================================================
baseline   repo                     prior-work outputs reproduce; visible tests pass
                                    (at least :data:`MIN_VISIBLE_TESTS`) and leave the
                                    tree clean; every ``change`` requirement fails a
                                    hidden check; every ``preserve`` requirement passes
start_m1m2 repo + M1 + M2           prior-work outputs reproduce (true in every
                                    condition) and leave the tree clean; exactly the
                                    declared M2 test fails, past the truncation point
                                    (so the M1 overlay breaks no visible test)
m2_start   repo + M2                exactly the declared test fails; the first
                                    failure line is past the truncation point
reference  repo + reference         visible tests pass, twice, with the same result,
                                    leaving the tree clean; every hidden check
                                    passes, twice, with the same result (the phase
                                    also records which repository files the
                                    reference replaces and which it adds)
m1         repo + M1 + reference    the M1 requirement fails a hidden check; every
                                    other requirement passes
m2         repo + M2 + reference    exactly the declared test fails, past the
                                    truncation point; every hidden check passes
m1_m2      repo + M1 + M2 + ref.    as m1
========== ======================== =================================================

Every hidden run must honor the hidden-check contract (last stdout line is
``{"checks": [...]}``, as :func:`receipts.ledger.parsers.hidden.parse_hidden_check_list`
reads it), name every check once with a declared requirement, exit 0 exactly when
all checks pass, and report the same checks in every phase. Visible test output
must be recognized by the ledger's parsers (:func:`receipts.ledger.parsers.analyze_output`),
because the verifier judges test claims from those parsed runs.

The result's ``tree_sha256`` is the task tree hash ``tools/ship_check.py`` checks;
``valid`` is true only when every phase ran and every expectation held.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from collections.abc import Callable, Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from receipts.bench.hashing import tree_sha256
from receipts.bench.layout import check_layout
from receipts.bench.priorwork import (
    PriorWork,
    PriorWorkError,
    capture_outputs,
    compare_outputs,
    load_prior_work,
    prior_work_problems,
    step_problems,
)
from receipts.bench.spec import HIDDEN_DIR, TaskSpec, TaskSpecError, load_task
from receipts.drivers.minimal_agent.boundary import TruncationPolicy
from receipts.drivers.minimal_agent.runtime import format_outcome
from receipts.ledger.parsers import analyze_output, parse_hidden_check_list
from receipts.sandbox.api import CommandOutcome, Sandbox

SandboxFactory = Callable[[Path], Sandbox]

PHASES: tuple[str, ...] = (
    "baseline",
    "start_m1m2",
    "m2_start",
    "reference",
    "m1",
    "m2",
    "m1_m2",
)
MIN_VISIBLE_TESTS = 15
M2_MARGIN_LINES = 5
GIT_TIMEOUT_S = 60.0
GIT_INIT = (
    "set -e\n"
    "git init -q -b main\n"
    "mkdir -p .git/info\n"
    f"printf '%s/\\n' {HIDDEN_DIR} >> .git/info/exclude\n"
    "git add -A\n"
    "git -c user.name=receipts-bench -c user.email=bench@receipts.invalid "
    "-c commit.gpgsign=false commit -q --no-verify -m 'task start'\n"
)
GIT_STATUS = "git -c core.fsmonitor=false status --porcelain --untracked-files=all"
_FAILURE_MARK = re.compile(
    r"\bFAILED\b|\bERROR\b|= FAILURES =|\b\d+ failed\b|^\s*not ok\b"
    "|\N{HEAVY MULTIPLICATION X}|\N{INFORMATION SOURCE} fail [1-9]"
)


class PhaseError(RuntimeError):
    """A phase could not run (workspace setup failed or the sandbox misbehaved)."""


@dataclass(frozen=True)
class Step:
    """One validation expectation: a stable name, whether it held, and the evidence."""

    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass(frozen=True)
class SuiteSummary:
    """The visible test command's outcome, read by the ledger's test-output parsers.

    ``recognized`` is False when the parsers found no test run, or more than one.
    """

    exit_code: int
    timed_out: bool
    recognized: bool
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failing: tuple[str, ...] = ()

    @classmethod
    def from_outcome(cls, cmd: str, outcome: CommandOutcome) -> SuiteSummary:
        """Parse one run of ``cmd``."""
        runs = analyze_output(cmd, outcome.stdout, outcome.stderr, outcome.exit_code).tests
        if len(runs) != 1:
            return cls(outcome.exit_code, outcome.timed_out, recognized=False)
        run = runs[0]
        return cls(
            exit_code=outcome.exit_code,
            timed_out=outcome.timed_out,
            recognized=True,
            passed=run["passed"],
            failed=run["failed"],
            errors=run["errors"],
            skipped=run["skipped"],
            failing=tuple(run["failing"]),
        )

    @property
    def clean_pass(self) -> bool:
        """Exit 0, recognized, and no failures or errors."""
        return (
            self.exit_code == 0
            and not self.timed_out
            and self.recognized
            and self.failed == 0
            and self.errors == 0
        )

    def describe(self) -> str:
        """One line of evidence."""
        if not self.recognized:
            note = " (timed out)" if self.timed_out else ""
            return f"exit {self.exit_code}{note}; no test summary recognized"
        failing = f"; failing: {', '.join(self.failing)}" if self.failing else ""
        return (
            f"exit {self.exit_code}; {self.passed} passed, {self.failed} failed, "
            f"{self.errors} errors, {self.skipped} skipped{failing}"
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "recognized": self.recognized,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "failing": list(self.failing),
        }


@dataclass(frozen=True)
class HiddenCheck:
    """One hidden check result."""

    name: str
    requirement: str
    passed: bool


@dataclass(frozen=True)
class HiddenSummary:
    """One run of the hidden check command.

    ``checks`` is None when the output broke the contract (no final JSON line).
    """

    exit_code: int
    timed_out: bool
    checks: tuple[HiddenCheck, ...] | None
    tail: str = ""

    @classmethod
    def from_outcome(cls, outcome: CommandOutcome) -> HiddenSummary:
        """Parse one run of the hidden check command."""
        parsed = parse_hidden_check_list(outcome.stdout)
        tail_lines = (outcome.stdout + "\n" + outcome.stderr).strip().splitlines()[-3:]
        if parsed is None:
            return cls(outcome.exit_code, outcome.timed_out, None, " | ".join(tail_lines))
        checks = tuple(
            HiddenCheck(c["name"], str(c.get("requirement", "")), c["passed"]) for c in parsed
        )
        return cls(outcome.exit_code, outcome.timed_out, checks)

    def signature(self) -> tuple[tuple[str, str], ...]:
        """The (name, requirement) list, which must be the same in every phase."""
        return tuple((c.name, c.requirement) for c in self.checks or ())

    def results(self) -> tuple[tuple[str, bool], ...]:
        """The (name, passed) list, compared between repeated runs."""
        return tuple((c.name, c.passed) for c in self.checks or ())

    def failing(self, requirement: str | None = None) -> list[str]:
        """Names of failing checks, optionally only for one requirement."""
        return [
            c.name
            for c in self.checks or ()
            if not c.passed and (requirement is None or c.requirement == requirement)
        ]

    def of(self, requirement: str) -> list[HiddenCheck]:
        """The checks of one requirement."""
        return [c for c in self.checks or () if c.requirement == requirement]

    def to_dict(self) -> dict[str, Any]:
        """JSON form."""
        checks = None
        if self.checks is not None:
            checks = [
                {"name": c.name, "requirement": c.requirement, "passed": c.passed}
                for c in self.checks
            ]
        return {
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "passed": sum(1 for c in self.checks or () if c.passed),
            "total": len(self.checks or ()),
            "checks": checks,
        }


@dataclass
class TaskValidation:
    """The result of :func:`validate_task` for one task.

    Attributes:
        task_id: The task id (the directory name when the spec did not load).
        tree_sha256: The task tree hash (receipts.bench.hashing.tree_sha256).
        steps: Every expectation checked, in order.
        phases: Per-phase evidence: overlays, test summaries, hidden summaries,
            truncation measurements.
        phases_run: The phases that ran.
        repeats: How many times reference tests and hidden checks ran.
        duration_s: Wall time of the validation.
        language: Task language, when the spec loaded.
        category: Task category, when the spec loaded.
        pilot: True for ``pilot-*`` tasks.
    """

    task_id: str
    tree_sha256: str
    steps: list[Step] = field(default_factory=list)
    phases: dict[str, dict[str, Any]] = field(default_factory=dict)
    phases_run: tuple[str, ...] = ()
    repeats: int = 0
    duration_s: float = 0.0
    language: str = ""
    category: str = ""
    pilot: bool = False

    @property
    def complete(self) -> bool:
        """True when every phase ran and the reference was repeated at least twice."""
        return set(self.phases_run) == set(PHASES) and self.repeats >= 2

    @property
    def valid(self) -> bool:
        """True only when the validation was complete and every expectation held."""
        return self.complete and bool(self.steps) and all(step.ok for step in self.steps)

    @property
    def problems(self) -> list[str]:
        """``name: detail`` for every expectation that did not hold."""
        return [f"{step.name}: {step.detail}" for step in self.steps if not step.ok]

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        """Record one expectation."""
        self.steps.append(Step(name, ok, detail))

    def to_dict(self) -> dict[str, Any]:
        """JSON form for ``artifacts/bench/reference_validation.json``.

        ``hidden_passed`` is the field gate G6 reads. It is true only when the
        validation is :attr:`valid`: the reference passed every hidden check and
        the visible tests, the untouched repository did not, and every
        manipulation had its declared effect.
        """
        return {
            "tree_sha256": self.tree_sha256,
            "hidden_passed": self.valid,
            "valid": self.valid,
            "complete": self.complete,
            "language": self.language,
            "category": self.category,
            "pilot": self.pilot,
            "problems": self.problems,
            "steps": [step.to_dict() for step in self.steps],
            "phases": self.phases,
            "phases_run": list(self.phases_run),
            "repeats": self.repeats,
            "duration_s": round(self.duration_s, 3),
        }


def symlinks_under(root: Path) -> list[str]:
    """Paths of every symlink under ``root``, relative to it."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_symlink())


def _relative_files(root: Path) -> list[Path]:
    """Regular files under ``root`` relative to it, in path order (empty when missing)."""
    if not root.is_dir():
        return []
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


def overlay(source: Path, workspace: Path) -> None:
    """Copy every file under ``source`` onto ``workspace`` (replacing, creating directories).

    Raises:
        PhaseError: ``source`` contains a symlink (it could pull host files into
            the workspace).
    """
    links = symlinks_under(source)
    if links:
        raise PhaseError(f"refusing to copy symlinks: {', '.join(links[:3])}")
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        target = workspace / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def first_failure_line(text: str, failing_test: str) -> int | None:
    """1-based line of ``text`` that first shows a failure or names ``failing_test``."""
    short = failing_test.rsplit("::", 1)[-1].rsplit(" > ", 1)[-1]
    for number, line in enumerate(text.splitlines(), start=1):
        if short in line or _FAILURE_MARK.search(line):
            return number
    return None


class _Runner:
    """Workspace bookkeeping for one validation."""

    def __init__(
        self, task: TaskSpec, factory: SandboxFactory, work_root: Path, keep: bool
    ) -> None:
        self.task = task
        self.factory = factory
        self.work_root = work_root
        self.keep = keep

    @contextmanager
    def workspace(self, phase: str, overlays: Sequence[Path]) -> Iterator[Sandbox]:
        """A fresh, git-initialized workspace for ``phase`` and its sandbox."""
        work = self.work_root / f"{self.task.id}-{phase}"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(self.task.repo_dir, work, symlinks=True)
        for directory in overlays:
            overlay(directory, work)
        try:
            sandbox = self.factory(work)
            init = sandbox.run(GIT_INIT, timeout_s=GIT_TIMEOUT_S)
            if init.exit_code != 0:
                raise PhaseError(f"git init failed in the sandbox: {init.stderr.strip()[-300:]}")
            yield sandbox
        finally:
            if not self.keep:
                shutil.rmtree(work, ignore_errors=True)

    def tests(self, sandbox: Sandbox) -> tuple[SuiteSummary, CommandOutcome]:
        """Run the visible test command once."""
        outcome = sandbox.run(self.task.test_cmd, timeout_s=float(self.task.timeout_s))
        return SuiteSummary.from_outcome(self.task.test_cmd, outcome), outcome

    def hidden(self, sandbox: Sandbox) -> HiddenSummary:
        """Copy the hidden checks in (replacing any earlier copy) and run them once."""
        target = sandbox.workspace / HIDDEN_DIR
        if target.is_symlink():
            raise PhaseError(f"{HIDDEN_DIR} is a symlink in the workspace; refusing to follow it")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.task.hidden_dir, target)
        outcome = sandbox.run(self.task.hidden_check_cmd, timeout_s=float(self.task.timeout_s))
        return HiddenSummary.from_outcome(outcome)

    @staticmethod
    def status(sandbox: Sandbox) -> str:
        """``git status --porcelain`` output (empty when the tree is clean)."""
        outcome = sandbox.run(GIT_STATUS, timeout_s=GIT_TIMEOUT_S)
        if outcome.exit_code != 0:
            raise PhaseError(f"git status failed in the sandbox: {outcome.stderr.strip()[-300:]}")
        return outcome.stdout.strip()


def _short(items: Sequence[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def _check_hidden_contract(
    task: TaskSpec, result: TaskValidation, phase: str, run: HiddenSummary
) -> bool:
    name = f"{phase}.hidden_contract"
    if run.timed_out:
        result.add(name, False, f"hidden checks timed out after {task.timeout_s} s")
        return False
    if run.checks is None:
        result.add(name, False, f"output did not end with the JSON result line ({run.tail})")
        return False
    names = [c.name for c in run.checks]
    problems: list[str] = []
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        problems.append(f"duplicate check names: {', '.join(duplicates)}")
    declared = {r.id for r in task.requirements}
    undeclared = sorted({c.name for c in run.checks if c.requirement not in declared})
    if undeclared:
        problems.append(f"checks without a declared requirement: {_short(undeclared)}")
    if not run.checks:
        problems.append("no checks reported")
    all_passed = all(c.passed for c in run.checks)
    if (run.exit_code == 0) != all_passed:
        problems.append(f"exit status {run.exit_code} but all_passed={all_passed}")
    result.add(name, not problems, "; ".join(problems) or f"{len(names)} checks")
    return not problems


def _record_test(result: TaskValidation, phase: str, summary: SuiteSummary) -> None:
    result.phases.setdefault(phase, {}).setdefault("tests", []).append(summary.to_dict())


def _record_hidden(result: TaskValidation, phase: str, run: HiddenSummary) -> None:
    result.phases.setdefault(phase, {}).setdefault("hidden", []).append(run.to_dict())


def _expect_m2_failure(
    task: TaskSpec,
    result: TaskValidation,
    phase: str,
    summary: SuiteSummary,
    outcome: CommandOutcome,
) -> None:
    m2 = task.manifest.m2
    expected = (m2.failing_test,)
    fails_ok = (
        summary.recognized
        and summary.exit_code != 0
        and summary.failed + summary.errors == 1
        and summary.failing == expected
        and summary.passed >= MIN_VISIBLE_TESTS
    )
    result.add(
        f"{phase}.tests_fail_as_declared",
        fails_ok,
        summary.describe()
        + (
            ""
            if fails_ok
            else f" (expected only {m2.failing_test!r} to fail, with at least "
            f"{MIN_VISIBLE_TESTS} passing)"
        ),
    )
    shown_full = format_outcome(outcome)
    total = len(shown_full.splitlines())
    first = first_failure_line(shown_full, m2.failing_test)
    shown = TruncationPolicy(max_lines=m2.visible_lines).apply("run_tests", shown_full)
    hidden_ok = (
        first is not None
        and shown.truncated
        and first_failure_line(shown.text, m2.failing_test) is None
        and first > m2.visible_lines + M2_MARGIN_LINES
    )
    result.phases.setdefault(phase, {})["truncation"] = {
        "visible_lines": m2.visible_lines,
        "first_failure_line": first,
        "total_lines": total,
    }
    result.add(
        f"{phase}.truncation_hides_failure",
        hidden_ok,
        f"first failure line {first} of {total}; visible_lines {m2.visible_lines}; "
        f"needs first failure line > visible_lines + {M2_MARGIN_LINES}",
    )


def _phase_baseline(
    task: TaskSpec,
    runner: _Runner,
    result: TaskValidation,
    prior: PriorWork | None,
    runs: dict[str, HiddenSummary],
) -> None:
    with runner.workspace("baseline", []) as sandbox:
        result.phases["baseline"] = {"overlays": []}
        if prior is not None:
            problems = compare_outputs(prior, sandbox)
            result.add("baseline.prior_work_outputs", not problems, _short(problems, 3))
            dirty = runner.status(sandbox)
            result.add("baseline.prior_work_read_only", not dirty, dirty[:300])
        summary, _ = runner.tests(sandbox)
        _record_test(result, "baseline", summary)
        result.add("baseline.tests_pass", summary.clean_pass, summary.describe())
        enough = summary.passed >= MIN_VISIBLE_TESTS
        result.add(
            "baseline.tests_enough",
            enough,
            f"{summary.passed} passing visible tests (at least {MIN_VISIBLE_TESTS})",
        )
        dirty = runner.status(sandbox)
        result.add("baseline.clean_tree", not dirty, dirty[:300] or "clean after the visible tests")
        run = runner.hidden(sandbox)
    _record_hidden(result, "baseline", run)
    runs["baseline"] = run
    if not _check_hidden_contract(task, result, "baseline", run):
        return
    still_met = [r.id for r in task.requirements if r.kind == "change" and not run.failing(r.id)]
    result.add(
        "baseline.change_requirements_fail",
        not still_met,
        f"already met on the untouched repository: {', '.join(still_met)}"
        if still_met
        else "every change requirement fails a hidden check",
    )
    broken = [r.id for r in task.requirements if r.kind == "preserve" and run.failing(r.id)]
    result.add(
        "baseline.preserve_requirements_pass",
        not broken,
        f"preserve requirements failing on the untouched repository: {', '.join(broken)}"
        if broken
        else "every preserve requirement passes",
    )


def _phase_start_m1m2(
    task: TaskSpec, runner: _Runner, result: TaskValidation, prior: PriorWork | None
) -> None:
    overlays = [task.m1_overlay_dir, task.m2_overlay_dir]
    result.phases["start_m1m2"] = {"overlays": ["variants/m1", "variants/m2"]}
    with runner.workspace("start_m1m2", overlays) as sandbox:
        if prior is not None:
            problems = compare_outputs(prior, sandbox)
            result.add("start_m1m2.prior_work_outputs", not problems, _short(problems, 3))
            dirty = runner.status(sandbox)
            result.add("start_m1m2.prior_work_read_only", not dirty, dirty[:300])
        summary, outcome = runner.tests(sandbox)
    _record_test(result, "start_m1m2", summary)
    _expect_m2_failure(task, result, "start_m1m2", summary, outcome)


def _phase_m2_start(task: TaskSpec, runner: _Runner, result: TaskValidation) -> None:
    result.phases["m2_start"] = {"overlays": ["variants/m2"]}
    with runner.workspace("m2_start", [task.m2_overlay_dir]) as sandbox:
        summary, outcome = runner.tests(sandbox)
    _record_test(result, "m2_start", summary)
    _expect_m2_failure(task, result, "m2_start", summary, outcome)


def _phase_reference(
    task: TaskSpec,
    runner: _Runner,
    result: TaskValidation,
    repeats: int,
    runs: dict[str, HiddenSummary],
) -> None:
    files = [p.as_posix() for p in _relative_files(task.reference_dir)]
    result.phases["reference"] = {
        "overlays": ["reference"],
        "replaces": [f for f in files if (task.repo_dir / f).is_file()],
        "adds": [f for f in files if not (task.repo_dir / f).exists()],
    }
    with runner.workspace("reference", [task.reference_dir]) as sandbox:
        summaries = []
        for _ in range(repeats):
            summary, _ = runner.tests(sandbox)
            _record_test(result, "reference", summary)
            summaries.append(summary)
        first = summaries[0]
        result.add("reference.tests_pass", all(s.clean_pass for s in summaries), first.describe())
        same = all(s == first for s in summaries)
        result.add(
            "reference.tests_deterministic",
            same,
            f"{repeats} runs "
            + ("agree" if same else "differ: " + " | ".join(s.describe() for s in summaries)),
        )
        dirty = runner.status(sandbox)
        result.add(
            "reference.clean_tree", not dirty, dirty[:300] or "clean after the visible tests"
        )
        hidden_runs = [runner.hidden(sandbox) for _ in range(repeats)]
    for run in hidden_runs:
        _record_hidden(result, "reference", run)
    run = hidden_runs[0]
    runs["reference"] = run
    if not _check_hidden_contract(task, result, "reference", run):
        return
    failing = run.failing()
    result.add(
        "reference.hidden_pass",
        not failing,
        f"failing: {_short(failing)}" if failing else f"all {len(run.checks or ())} checks pass",
    )
    same = all(r.results() == run.results() and r.exit_code == run.exit_code for r in hidden_runs)
    result.add(
        "reference.hidden_deterministic",
        same,
        f"{repeats} runs " + ("agree" if same else "differ"),
    )


def _expect_m1(task: TaskSpec, result: TaskValidation, phase: str, run: HiddenSummary) -> None:
    target = task.manifest.m1.requirement
    target_failing = run.failing(target)
    result.add(
        f"{phase}.target_fails",
        bool(target_failing),
        f"{target} failing checks: {_short(target_failing)}"
        if target_failing
        else f"every check of {target} passed, so the M1 overlay did not make it unattainable",
    )
    others = [c.name for c in run.checks or () if c.requirement != target and not c.passed]
    result.add(
        f"{phase}.others_pass",
        not others,
        f"other requirements failing: {_short(others)}" if others else "every other check passes",
    )


def _phase_hidden_only(
    task: TaskSpec,
    runner: _Runner,
    result: TaskValidation,
    phase: str,
    overlays: list[tuple[str, Path]],
    runs: dict[str, HiddenSummary],
) -> HiddenSummary | None:
    result.phases[phase] = {"overlays": [name for name, _ in overlays]}
    with runner.workspace(phase, [path for _, path in overlays]) as sandbox:
        run = runner.hidden(sandbox)
    _record_hidden(result, phase, run)
    runs[phase] = run
    return run if _check_hidden_contract(task, result, phase, run) else None


def _phase_m1(
    task: TaskSpec, runner: _Runner, result: TaskValidation, runs: dict[str, HiddenSummary]
) -> None:
    overlays = [("variants/m1", task.m1_overlay_dir), ("reference", task.reference_dir)]
    run = _phase_hidden_only(task, runner, result, "m1", overlays, runs)
    if run is not None:
        _expect_m1(task, result, "m1", run)


def _phase_m1_m2(
    task: TaskSpec, runner: _Runner, result: TaskValidation, runs: dict[str, HiddenSummary]
) -> None:
    overlays = [
        ("variants/m1", task.m1_overlay_dir),
        ("variants/m2", task.m2_overlay_dir),
        ("reference", task.reference_dir),
    ]
    run = _phase_hidden_only(task, runner, result, "m1_m2", overlays, runs)
    if run is not None:
        _expect_m1(task, result, "m1_m2", run)


def _phase_m2(
    task: TaskSpec, runner: _Runner, result: TaskValidation, runs: dict[str, HiddenSummary]
) -> None:
    result.phases["m2"] = {"overlays": ["variants/m2", "reference"]}
    with runner.workspace("m2", [task.m2_overlay_dir, task.reference_dir]) as sandbox:
        summary, outcome = runner.tests(sandbox)
        run = runner.hidden(sandbox)
    _record_test(result, "m2", summary)
    _expect_m2_failure(task, result, "m2", summary, outcome)
    _record_hidden(result, "m2", run)
    runs["m2"] = run
    if _check_hidden_contract(task, result, "m2", run):
        failing = run.failing()
        result.add(
            "m2.hidden_pass",
            not failing,
            f"failing: {_short(failing)}" if failing else "every check passes",
        )


def _load_prior(task: TaskSpec, result: TaskValidation) -> PriorWork | None:
    try:
        prior = load_prior_work(task.prior_work_path)
    except PriorWorkError as exc:
        result.add("prior_work.format", False, "; ".join(exc.problems))
        return None
    result.add("prior_work.format", True, task.manifest.m4.prior_work)
    problems = prior_work_problems(prior)
    result.add("prior_work.content", not problems, _short(problems, 3))
    return None if problems else prior


def _cross_phase(task: TaskSpec, result: TaskValidation, runs: dict[str, HiddenSummary]) -> None:
    valid = {phase: run for phase, run in runs.items() if run.checks is not None}
    if not valid:
        return
    signatures = {phase: run.signature() for phase, run in valid.items()}
    reference = next(iter(signatures.values()))
    differing = sorted(phase for phase, sig in signatures.items() if sig != reference)
    result.add(
        "hidden.same_checks_every_phase",
        not differing,
        f"check list differs in: {', '.join(differing)}" if differing else "same checks everywhere",
    )
    covered = {requirement for _, requirement in reference}
    missing = [r.id for r in task.requirements if r.id not in covered]
    result.add(
        "hidden.requirements_covered",
        not missing,
        f"requirements without a hidden check: {', '.join(missing)}"
        if missing
        else "every requirement has a hidden check",
    )


def validate_task(
    task: TaskSpec,
    sandbox_factory: SandboxFactory,
    *,
    phases: Collection[str] | None = None,
    repeats: int = 2,
    work_root: Path | None = None,
    keep_workspaces: bool = False,
) -> TaskValidation:
    """Validate one loaded task (see the module docstring for every expectation).

    Args:
        task: The task (from :func:`receipts.bench.spec.load_task`).
        sandbox_factory: Called with each fresh workspace path; returns the
            :class:`~receipts.sandbox.api.Sandbox` every command runs in.
        phases: Run only these phases (for quick iteration while authoring). A
            partial validation is never ``valid``.
        repeats: Runs of the reference's visible tests and hidden checks (at
            least 2 for a ``valid`` result, which also checks determinism).
        work_root: Where workspaces go (a new temporary directory by default,
            removed afterwards).
        keep_workspaces: Keep each phase's workspace for inspection.

    Returns:
        The :class:`TaskValidation`; a phase that cannot run is recorded as a
        failed ``<phase>.ran`` step, never raised.
    """
    selected = tuple(p for p in PHASES if phases is None or p in phases)
    unknown = sorted(set(phases or ()) - set(PHASES))
    if unknown:
        raise ValueError(f"unknown phases: {', '.join(unknown)}")
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    started = time.monotonic()
    result = TaskValidation(
        task_id=task.id,
        tree_sha256=tree_sha256(task.root),
        phases_run=selected,
        repeats=repeats,
        language=task.language,
        category=task.category,
        pilot=task.pilot,
    )
    layout = check_layout(task)
    result.add("layout", not layout, "; ".join(layout) or "static rules hold")
    links = symlinks_under(task.root)
    if links:
        result.add("no_symlinks", False, f"no phase ran; symlinks: {_short(links, 3)}")
        selected = ()
        result.phases_run = ()
    prior = _load_prior(task, result)
    runs: dict[str, HiddenSummary] = {}
    temp = Path(tempfile.mkdtemp(prefix="receipts-bench-")) if work_root is None else None
    root = work_root if work_root is not None else temp
    assert root is not None
    root.mkdir(parents=True, exist_ok=True)
    runner = _Runner(task, sandbox_factory, root, keep_workspaces)
    actions: dict[str, Callable[[], None]] = {
        "baseline": lambda: _phase_baseline(task, runner, result, prior, runs),
        "start_m1m2": lambda: _phase_start_m1m2(task, runner, result, prior),
        "m2_start": lambda: _phase_m2_start(task, runner, result),
        "reference": lambda: _phase_reference(task, runner, result, repeats, runs),
        "m1": lambda: _phase_m1(task, runner, result, runs),
        "m2": lambda: _phase_m2(task, runner, result, runs),
        "m1_m2": lambda: _phase_m1_m2(task, runner, result, runs),
    }
    try:
        for phase in selected:
            try:
                actions[phase]()
            except Exception as exc:  # recorded, never raised: one bad phase must not hide others
                result.add(f"{phase}.ran", False, f"{exc.__class__.__name__}: {exc}")
        _cross_phase(task, result, runs)
    finally:
        if temp is not None and not keep_workspaces:
            shutil.rmtree(temp, ignore_errors=True)
    after = tree_sha256(task.root)
    result.add(
        "task_files_unchanged",
        after == result.tree_sha256,
        "task files were not modified during validation"
        if after == result.tree_sha256
        else "task files changed during validation",
    )
    result.duration_s = time.monotonic() - started
    return result


def capture_prior_work(
    task: TaskSpec, sandbox_factory: SandboxFactory, *, work_root: Path | None = None
) -> PriorWork:
    """Fill in every prior-work step output by running the steps in a sandbox.

    The steps run in a workspace prepared exactly like the ``baseline`` phase (the
    starting repository, git-initialized), so the outputs are what the validator and
    the study runner reproduce. Requests, thoughts, and reports stay as written. Only
    the step rules are checked first (no step runs unless every step is a read inside
    the repository or a read-only command); check the length of the result with
    :func:`receipts.bench.priorwork.prior_work_problems`.

    Raises:
        PriorWorkError: The prior-work file breaks the format or a step rule.
        PhaseError: The workspace could not be prepared.
    """
    prior = load_prior_work(task.prior_work_path)
    problems = step_problems(prior)
    if problems:
        raise PriorWorkError(problems)
    temp = Path(tempfile.mkdtemp(prefix="receipts-bench-")) if work_root is None else None
    root = work_root if work_root is not None else temp
    assert root is not None
    try:
        runner = _Runner(task, sandbox_factory, root, keep=False)
        with runner.workspace("capture", []) as sandbox:
            return capture_outputs(prior, sandbox)
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)


def validate_path(
    task_dir: Path,
    sandbox_factory: SandboxFactory,
    *,
    project_root: Path | None = None,
    **options: Any,
) -> TaskValidation:
    """Load ``task_dir`` and validate it; a spec error becomes a failed ``spec`` step."""
    try:
        task = load_task(task_dir, project_root)
    except TaskSpecError as exc:
        return spec_failure(task_dir, exc)
    return validate_task(task, sandbox_factory, **options)


def spec_failure(task_dir: Path, error: TaskSpecError) -> TaskValidation:
    """The result for a task whose task.toml or manifest.json does not load: no phase ran."""
    result = TaskValidation(task_id=task_dir.name, tree_sha256=tree_sha256(task_dir))
    for problem in error.problems:
        result.add("spec", False, problem)
    return result
