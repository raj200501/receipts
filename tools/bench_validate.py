"""Validate receipts-bench tasks in a sandbox and bank the result for gate G6.

    python tools/bench_validate.py                       # every task; writes the artifact
    python tools/bench_validate.py --task pilot-py-bizdays   # some tasks; writes nothing
    python tools/bench_validate.py --task pilot-py-bizdays --phase baseline   # one phase
    python tools/bench_validate.py --verify              # is the banked artifact current?
    python tools/bench_validate.py --capture-prior-work pilot-py-bizdays   # fill M4 outputs

Every task directory under ``bench/tasks/`` (one holding a ``task.toml``) is validated
with :func:`receipts.bench.validate.validate_path` (docs/BENCH.md lists every
expectation). No task command runs on the host: each one runs in a sandbox from
:func:`receipts.sandbox.select.make_sandbox`, bubblewrap first, then ``unshare -rn``.
Both see the host's ``/usr``, so Node 22 and git are available, and Python commands
get a read-only toolchain with pytest built once by
:func:`receipts.sandbox.toolchain.python_toolchain` from the pins in
:data:`receipts.bench.spec.TOOLCHAIN_PACKAGES` (under ``runs/``, which git ignores).
Each task's sandbox gets the address-space limit its language needs
(:data:`receipts.bench.spec.MEMORY_MB`: Node's TypeScript loader needs more than 12 GB).

A full run writes ``artifacts/bench/reference_validation.json`` (format in
:mod:`receipts.bench.artifact`) with provenance: git SHA, command, creation time, and the
environment the commands ran in (backend and tool versions, probed inside a sandbox).
A run limited with ``--task`` or ``--phase`` only prints its results, so the artifact
always covers every task and every phase. ``--capture-prior-work ID`` runs the steps of
that task's prior-work file in a sandbox on the starting repository and writes their
outputs into the file (for task authors; see docs/BENCH.md). Exit status: 0 when every
validated task is valid (with ``--phase``: when the selected phases hold), 1 when any is
not (or ``--verify`` finds the artifact out of date), 2 when the tool could not run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from receipts.bench.artifact import (
    ARTIFACT_PATH,
    build_artifact,
    check_artifact,
    load_artifact,
    validate_all,
    write_artifact,
)
from receipts.bench.priorwork import (
    PriorWorkError,
    dump_prior_work,
    prior_work_problems,
    rendered_chars,
)
from receipts.bench.spec import (
    MEMORY_MB,
    TOOLCHAIN_PACKAGES,
    TOOLCHAIN_PYTHON,
    TaskSpecError,
    load_task,
    task_dirs,
)
from receipts.bench.validate import (
    PHASES,
    PhaseError,
    SandboxFactory,
    TaskValidation,
    capture_prior_work,
)
from receipts.sandbox.api import Sandbox, SandboxPolicy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKENDS: tuple[str, ...] = ("bwrap", "unshare")
DEFAULT_TOOLCHAIN = Path("runs") / "toolchains" / f"bench-py{TOOLCHAIN_PYTHON.replace('.', '')}"
PROBE_CMD = "python3 --version; node --version; npm --version; git --version"

#: Makes a sandbox factory for an address-space limit (``SandboxPolicy.memory_mb``).
FactoryMaker = Callable[[int], SandboxFactory]

#: Builds the factory maker from the parsed arguments; returns it with a description of
#: the setup for the provenance. Tests pass their own.
FactoryBuilder = Callable[[argparse.Namespace], tuple[FactoryMaker, dict[str, Any]]]


class SetupError(RuntimeError):
    """The tool cannot run: no tasks, an unknown task id, or no working sandbox."""


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--tasks-dir", type=Path, default=ROOT / "bench" / "tasks")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--task", action="append", default=[], help="validate only this task")
    parser.add_argument("--jobs", type=int, default=1, help="tasks validated at once")
    parser.add_argument(
        "--phase", action="append", choices=PHASES, help="run only this validation phase"
    )
    parser.add_argument(
        "--backend",
        action="append",
        choices=("docker", "bwrap", "unshare"),
        help="sandbox backends in order of preference (default: bwrap, then unshare)",
    )
    parser.add_argument("--toolchain", type=Path, default=ROOT / DEFAULT_TOOLCHAIN)
    parser.add_argument(
        "--no-toolchain", action="store_true", help="use the sandbox PATH as it is (no pytest)"
    )
    parser.add_argument("--offline", action="store_true", help="build the toolchain offline")
    parser.add_argument("--out", type=Path, default=ROOT / ARTIFACT_PATH)
    parser.add_argument("--no-write", action="store_true", help="validate, write nothing")
    parser.add_argument(
        "--verify", action="store_true", help="check the banked artifact; run nothing"
    )
    parser.add_argument(
        "--capture-prior-work", metavar="ID", help="fill in the prior-work outputs of a task"
    )
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return args


def select_tasks(tasks_dir: Path, ids: Sequence[str]) -> list[Path]:
    """The task directories to validate: all of them, or the named ones.

    Raises:
        SetupError: No task exists, or a named task does not.
    """
    tasks = task_dirs(tasks_dir)
    if not tasks:
        raise SetupError(f"no tasks under {tasks_dir}")
    if not ids:
        return tasks
    by_name = {task.name: task for task in tasks}
    unknown = sorted(set(ids) - set(by_name))
    if unknown:
        raise SetupError(f"unknown task ids: {', '.join(unknown)}")
    return [by_name[name] for name in sorted(set(ids))]


def default_factory(args: argparse.Namespace) -> tuple[FactoryMaker, dict[str, Any]]:
    """Sandboxes from :func:`receipts.sandbox.select.make_sandbox`, with the toolchain.

    The returned maker builds a factory for one address-space limit; each task gets
    its :attr:`receipts.bench.spec.TaskSpec.memory_mb`.

    Raises:
        SetupError: The sandbox package is not available or the toolchain cannot be built.
    """
    try:
        from receipts.sandbox.select import make_sandbox
        from receipts.sandbox.toolchain import ToolchainError, python_toolchain, with_toolchain
    except ImportError as exc:
        raise SetupError(f"receipts.sandbox is not available: {exc}") from exc
    backends = tuple(args.backend or DEFAULT_BACKENDS)
    policy = SandboxPolicy()
    setup: dict[str, Any] = {"backends": list(backends), "memory_mb": dict(MEMORY_MB)}
    if not args.no_toolchain:
        try:
            toolchain = python_toolchain(
                args.toolchain, TOOLCHAIN_PACKAGES, python=TOOLCHAIN_PYTHON, offline=args.offline
            )
        except (ToolchainError, OSError) as exc:
            raise SetupError(f"cannot build the Python toolchain: {exc}") from exc
        policy = with_toolchain(policy, toolchain)
        setup["toolchain"] = {
            "python": TOOLCHAIN_PYTHON,
            "packages": list(toolchain.packages),
            "installed": list(toolchain.installed),
        }

    def maker(memory_mb: int) -> SandboxFactory:
        limited = replace(policy, memory_mb=memory_mb)

        def factory(workspace: Path) -> Sandbox:
            return make_sandbox(workspace, limited, prefer=backends)

        return factory

    return maker, setup


def probe_environment(factory: SandboxFactory) -> dict[str, Any]:
    """The backend and the tool versions that task commands see, from one sandbox run.

    Raises:
        SetupError: No sandbox could be made.
    """
    with tempfile.TemporaryDirectory(prefix="receipts-bench-probe-") as tmp:
        try:
            sandbox = factory(Path(tmp))
            outcome = sandbox.run(PROBE_CMD, timeout_s=60.0)
        except Exception as exc:  # any backend failure means the tool cannot run
            raise SetupError(f"no sandbox: {exc.__class__.__name__}: {exc}") from exc
    lines = (outcome.stdout + outcome.stderr).strip().splitlines()
    return {"backend": sandbox.backend, "versions": lines, "probe_exit_code": outcome.exit_code}


def git_state(root: Path) -> dict[str, Any]:
    """HEAD and whether the benchmark files differ from it (``unknown`` without git)."""

    def git(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *argv], capture_output=True, text=True, check=False
        )

    head = git("rev-parse", "HEAD")
    if head.returncode != 0:
        return {"git_sha": "unknown", "bench_dirty": None}
    status = git("status", "--porcelain", "--untracked-files=all", "--", "bench")
    dirty = status.returncode != 0 or bool(status.stdout.strip())
    return {"git_sha": head.stdout.strip(), "bench_dirty": dirty}


def provenance(
    argv: Sequence[str], project_root: Path, setup: dict[str, Any], probe: dict[str, Any]
) -> dict[str, Any]:
    """The artifact's provenance block."""
    return {
        **git_state(project_root),
        "command": shlex.join(["python", "tools/bench_validate.py", *argv]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "validator": "receipts.bench.validate.validate_task (2 repeats)",
        "environment": {
            "platform": platform.platform(),
            "host_python": platform.python_version(),
            "cpus": os.cpu_count(),
            "sandbox": probe,
            **setup,
        },
    }


def _report(result: TaskValidation) -> None:
    if result.valid:
        print(f"PASS {result.task_id} ({len(result.steps)} checks, {result.duration_s:.1f} s)")
        return
    problems = result.problems or ["validation incomplete"]
    print(f"FAIL {result.task_id}: " + " | ".join(problems[:3]), flush=True)


def verify(args: argparse.Namespace) -> int:
    """Check the banked artifact against the current task files."""
    try:
        data = load_artifact(args.out)
    except (OSError, ValueError) as exc:
        print(f"bench_validate: cannot read {args.out}: {exc}", file=sys.stderr)
        return 1
    problems = check_artifact(data, args.tasks_dir)
    for problem in problems:
        print(f"OUT OF DATE {problem}")
    print("artifact is current" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def capture(args: argparse.Namespace, maker: FactoryMaker) -> int:
    """Rewrite one task's prior-work file with outputs captured in a sandbox."""
    (task_dir,) = select_tasks(args.tasks_dir, [args.capture_prior_work])
    try:
        task = load_task(task_dir, args.project_root)
        captured = capture_prior_work(task, maker(task.memory_mb))
    except (TaskSpecError, PriorWorkError, PhaseError) as exc:
        print(f"bench_validate: cannot capture prior work: {exc}", file=sys.stderr)
        return 1
    dump_prior_work(captured, task.prior_work_path)
    print(f"wrote {task.prior_work_path} ({rendered_chars(captured)} rendered characters)")
    problems = prior_work_problems(captured)
    for problem in problems:
        print(f"bench_validate: {problem}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None, build_factory: FactoryBuilder | None = None) -> int:
    """Run the tool; see the module docstring."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(arguments)
    if args.verify:
        return verify(args)
    try:
        tasks = select_tasks(args.tasks_dir, args.task)
        maker, setup = (build_factory or default_factory)(args)
        probe = probe_environment(maker(max(MEMORY_MB.values())))
        if args.capture_prior_work:
            return capture(args, maker)
    except SetupError as exc:
        print(f"bench_validate: {exc}", file=sys.stderr)
        return 2
    results = validate_all(
        tasks,
        lambda task: maker(task.memory_mb),
        project_root=args.project_root,
        jobs=args.jobs,
        progress=_report,
        phases=args.phase,
    )
    valid = sum(1 for result in results if result.valid)
    print(f"{valid} of {len(results)} tasks valid")
    if args.phase:
        failed = sum(1 for result in results if result.problems)
        print(f"{len(results) - failed} of {len(results)} tasks hold in the selected phases")
    if args.task or args.phase or args.no_write:
        print("artifact not written (a run limited by --task, --phase, or --no-write)")
    else:
        data = build_artifact(results, provenance(arguments, args.project_root, setup, probe))
        write_artifact(data, args.out)
        print(f"wrote {args.out}")
    if args.phase:
        return 0 if all(not result.problems for result in results) else 1
    return 0 if valid == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
