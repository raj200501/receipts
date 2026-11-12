"""Execute a study plan with local models: smoke runs, pilots, and preregistered studies.

    python tools/run_study.py --plan artifacts/studies/<study>/plan.json [--limit N]

Runs are grouped by model; for each model one pinned, hash-verified local model server
is started (llama.cpp's ``llama-server`` by default, DECISIONS D30), and every run goes
through :mod:`receipts.study.runner` with the sandbox chosen by
:func:`receipts.sandbox.select.make_sandbox`. Each run's artifacts land in
``artifacts/studies/<study>/runs/<run_id>/``; a run that already has ``run.json`` is
never re-run, so the command is safe to restart. Start long plans in the background with
``nohup``; the PID is written to ``runs/<study>/pid`` (section 8, usage hygiene).

The agent's sandbox hides this checkout (the benchmark's hidden checks and reference
solutions, the instrument, ``private/``, other runs' files) whatever code the session
imports (DECISIONS D67): :func:`study_sandbox` names it as a hidden path, and
:func:`checkout_hiding` refuses a sandbox whose commands could reach it, once before any
model server starts (:func:`preflight`, exit status 2) and again before each run; the run
record says how it was hidden (``provenance.sandbox``). A session that imports a code
snapshot (``runs/code/<sha>/src``) starts only when the snapshot's files are ``src/`` of
the commit it names (:func:`snapshot_differences`).

Each model server gives every one of its ``--parallel`` slots (at least one) the pinned
model's context window (``LocalModel.n_ctx``) unless ``--n-ctx`` asks for another one
(:func:`served_model`). A server starts only on a port nothing answers on, and before
each run the session confirms that the server is its own process serving what it was
started with (:meth:`LocalServer.confirm_serving`: for llama.cpp, the window per slot,
the slots, and the model file of ``GET /props``); a server that fails is a refusal
(:class:`ServerMismatchError`). The run record's ``provenance.model_server`` holds the
window per slot, the slots, whether the window is the pinned one, and what the live
server reported (:func:`server_record`). A SIGTERM stops the session as an exception
would: no new attempt starts, the attempts already running end, and the model server is
stopped.

Plan amendments (DECISIONS D71, ``tools/amend_plan.py``): a run an amendment replaced is
excluded, whatever the failure log holds, and never attempted again. The run it added
needs the server its amendment names (at least so many tokens per slot, above the
pinned window, on one slot, from llama.cpp), and every other run is served only with the
pinned window (:func:`window_refusal`). A session therefore attempts only the pending
runs its server serves and refuses the others, which wait for a session started with the
right ``--n-ctx`` and ``--parallel``; when it can serve none of them it exits with status
2 before any server starts. The added run's replies are cached in a directory of its own
(:func:`response_cache`), never served from the cache that holds the replies other runs
got on the pinned window, and its record carries its amendment and that cache
(``provenance.plan_amendment``, ``provenance.response_cache``).

Infrastructure failures (prereg/0001-e1-main-study.md section 10, prereg 0002 section
6): an exception raised in ``execute_run`` (a model server, sandbox, or workspace error,
never agent behavior) leaves the run unbanked, and the failed attempt is appended to
``runs/<study>/failures.jsonl`` with the run id, its attempt number, its start and
failure times, and the error. The run is queued again with its planned spec (the same
seed) behind the runs already queued, for at most ``MAX_ATTEMPTS`` (three) attempts in
all. Attempts are counted from the failure log, so the cap holds across restarts: a run
with three logged failures is excluded, never attempted again, and reported as
excluded. Errors outside ``execute_run`` (loading the task, the toolchain, or the model
server) would fail every attempt alike; they stop the session and are not logged as
attempts.

Stop rule: after ``STOP_AFTER_FAILURES`` failed attempts in a row with no run banked in
between, the failure is taken to be systematic (a dead model server, a broken sandbox,
a full disk) and no further attempt starts, so that retries do not use up the attempts
of every remaining run. The session then exits with status 1; the runs that are neither
banked nor excluded wait for a restart once the cause is fixed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import traceback
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from receipts.bench.hashing import tree_sha256
from receipts.bench.spec import TOOLCHAIN_PACKAGES, TOOLCHAIN_PYTHON
from receipts.client.backends import LocalOpenAIBackend
from receipts.client.models import LOCAL_MODELS
from receipts.client.server import LocalModel, LocalServer, ServerStateError
from receipts.client.wrapper import ModelClient
from receipts.sandbox.api import HidesPaths, Sandbox, SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.bwrap import default_hidden_paths, project_root
from receipts.sandbox.select import make_sandbox
from receipts.sandbox.toolchain import Toolchain, python_toolchain, with_toolchain
from receipts.study.plan import Plan, amendment_cache, check_amendments, load_plan
from receipts.study.runner import RunRecord, execute_run
from receipts.study.spec import RunSpec
from receipts.study.tasks import load_run_task

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
"""Git-ignored session state: ``runs/<study>/`` holds the pid file, logs, and failure log."""
FAILURES = "failures.jsonl"
MAX_ATTEMPTS = 3
"""Attempts per run: the first and up to two retries with the same seed."""
STOP_AFTER_FAILURES = 4
"""Failed attempts in a row, with no run banked in between, that stop a session. It is
above ``MAX_ATTEMPTS``, so one run that fails all its attempts in a row cannot stop a
session alone."""
_FAILURES_LOCK = threading.RLock()


def git_sha() -> str:
    """HEAD of this repository (recorded in every run's provenance)."""
    return subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def dirty_files() -> list[str]:
    """Files with uncommitted changes, untracked files included (recorded per run;
    confirmatory runs need none): an untracked module under src/ can change what runs."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(line[3:] for line in out.splitlines() if line.strip())


SNAPSHOT_MARKER = "SNAPSHOT_OF"
"""The file beside a code snapshot's ``src/`` that names the commit it was taken from."""

#: A full commit id as git prints it (SHA-1, or SHA-256 in a repository that uses it).
FULL_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

#: One entry of a ``src/`` tree: ``("file", bytes, executable)`` or ``("symlink",
#: target, False)``; anything else is ``("other", b"", False)``.
TreeEntry = tuple[str, bytes, bool]


def _git_output(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)


def _archived_tree(archive: bytes) -> dict[str, TreeEntry]:
    entries: dict[str, TreeEntry] = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if member.isdir():
                continue
            if member.issym():
                entries[member.name] = ("symlink", member.linkname.encode(), False)
            elif member.isfile():
                handle = tar.extractfile(member)
                data = b"" if handle is None else handle.read()
                entries[member.name] = ("file", data, bool(member.mode & 0o100))
            else:
                entries[member.name] = ("other", b"", False)
    return entries


def _is_bytecode_cache(rel: Path) -> bool:
    return "__pycache__" in rel.parts[:-1] and rel.suffix == ".pyc"


def _disk_tree(snapshot: Path) -> dict[str, TreeEntry]:
    entries: dict[str, TreeEntry] = {}
    for top, dirs, files in os.walk(snapshot / "src"):
        for name in [*dirs, *files]:
            path = Path(top) / name
            rel = path.relative_to(snapshot)
            if path.is_symlink():
                entries[rel.as_posix()] = ("symlink", str(path.readlink()).encode(), False)
            elif path.is_dir() or _is_bytecode_cache(rel):
                continue
            elif path.is_file():
                executable = bool(path.stat().st_mode & 0o100)
                entries[rel.as_posix()] = ("file", path.read_bytes(), executable)
            else:
                entries[rel.as_posix()] = ("other", b"", False)
    return entries


def snapshot_differences(snapshot: Path, sha: str) -> list[str]:
    """How ``snapshot/src`` differs from the ``src/`` tree of commit ``sha`` (empty: none).

    The commit's tree is read with ``git archive <sha> src``, as
    ``tools/snapshot_code.sh`` extracts it, and compared with the files on disk: the
    same paths, each a regular file with the same bytes and executable bit, or a
    symlink with the same target. The bytecode caches that importing the snapshot
    writes (``*.pyc`` files in ``__pycache__`` directories) are skipped, and directories
    count only through the files they hold. ``sha`` must be the full id of a commit in
    this repository (:data:`ROOT`).
    """
    if not FULL_COMMIT.fullmatch(sha):
        return [f"{SNAPSHOT_MARKER} holds {sha!r}, not a full commit id"]
    resolved = _git_output("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    if resolved.returncode != 0 or resolved.stdout.decode().strip() != sha:
        return [f"commit {sha} is not in the repository at {ROOT}"]
    archive = _git_output("archive", "--format=tar", sha, "src")
    if archive.returncode != 0:
        reason = archive.stderr.decode(errors="replace").strip()
        return [f"git archive {sha} src failed: {reason}"]
    if not (snapshot / "src").is_dir():
        return [f"{snapshot / 'src'} is not a directory"]
    expected, found = _archived_tree(archive.stdout), _disk_tree(snapshot)
    differences = [f"{name} is missing" for name in sorted(expected.keys() - found.keys())]
    extra = sorted(found.keys() - expected.keys())
    differences += [f"{name} is not in commit {sha}" for name in extra]
    for name in sorted(expected.keys() & found.keys()):
        (kind, data, executable), (disk_kind, disk_data, disk_executable) = (
            expected[name],
            found[name],
        )
        if kind != disk_kind:
            differences.append(f"{name} is a {disk_kind} here and a {kind} in the commit")
        elif data != disk_data:
            differences.append(f"{name} differs from the commit")
        elif executable != disk_executable:
            differences.append(f"{name} has a different executable bit")
    return differences


def code_state() -> dict[str, Any]:
    """Which code this session runs: the working tree, or a checked snapshot of one commit.

    ``tools/snapshot_code.sh <sha>`` extracts a commit's ``src/`` under
    ``runs/code/<sha>/`` with a ``SNAPSHOT_OF`` marker; running with ``PYTHONPATH``
    pointing at it imports that exact code while other work edits the working tree. A
    snapshot is used only when its files are the ``src/`` tree of the commit its marker
    names (:func:`snapshot_differences`), so ``snapshot_of`` is checked, not declared;
    the record then says ``snapshot_verified``.

    Raises:
        SystemExit: receipts is imported from a directory that is neither this
            checkout's ``src/`` nor a snapshot's, or the snapshot differs from its
            commit.
    """
    import receipts

    src = Path(receipts.__file__).resolve().parents[1]
    if src == (ROOT / "src").resolve():
        return {"code": "working tree", "uncommitted_at_start": dirty_files()}
    marker = src.parent / SNAPSHOT_MARKER
    if src.name != "src" or not marker.is_file():
        raise SystemExit(f"receipts imported from {src}, which is not a recorded snapshot")
    sha = marker.read_text(encoding="utf-8").strip()
    differences = snapshot_differences(src.parent, sha)
    if differences:
        listed = "; ".join(differences[:5])
        more = f"; and {len(differences) - 5} more" if len(differences) > 5 else ""
        raise SystemExit(
            f"refusing the code snapshot {src.parent}: it is not src/ of commit {sha} "
            f"({listed}{more})"
        )
    return {"code": "snapshot", "snapshot_of": sha, "snapshot_verified": True}


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class InfrastructureError(Exception):
    """An exception raised in ``execute_run``: the attempt failed and the run is unbanked.

    Attributes:
        error: ``"<exception type>: <message>"`` of the original exception.
        trace: The end of its traceback (at most 4000 characters).
    """

    def __init__(self, error: str, trace: str) -> None:
        super().__init__(error)
        self.error = error
        self.trace = trace


def failure_counts(state: Path) -> dict[str, int]:
    """Logged failed attempts per run id in ``state/failures.jsonl`` (empty when absent).

    Every line counts as one failed attempt of its run, whatever its other keys (lines
    written before attempt numbers were recorded count too); blank lines are skipped.

    Raises:
        ValueError: A line is not a JSON object with a non-empty text ``run_id``, so the
            attempts of some run cannot be counted.
    """
    path = state / FAILURES
    counts: dict[str, int] = {}
    with _FAILURES_LOCK:
        if not path.is_file():
            return counts
        text = path.read_text(encoding="utf-8")
    for number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path} line {number} is not JSON ({exc.msg}), so attempts cannot be counted"
            ) from exc
        run_id = entry.get("run_id") if isinstance(entry, dict) else None
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"{path} line {number} names no run_id, so attempts cannot be counted")
        counts[run_id] = counts.get(run_id, 0) + 1
    return counts


def log_failure(state: Path, run_id: str, started: str, failure: InfrastructureError) -> int:
    """Append one failed attempt to ``state/failures.jsonl`` and return its attempt number.

    The number is one more than the failures already logged for the run: an unbanked run
    has failed every earlier attempt. The entry holds ``run_id``, ``attempt``,
    ``started`` (the attempt's start), ``time`` (when it failed), ``error``, and
    ``trace``.
    """
    with _FAILURES_LOCK:
        attempt = failure_counts(state).get(run_id, 0) + 1
        entry = {
            "run_id": run_id,
            "attempt": attempt,
            "started": started,
            "time": _now(),
            "error": failure.error,
            "trace": failure.trace,
        }
        state.mkdir(parents=True, exist_ok=True)
        with (state / FAILURES).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    return attempt


def _banked(artifacts: Path, run_id: str) -> bool:
    return (artifacts / run_id / "run.json").is_file()


def _is_excluded(plan: Plan, run_id: str, counts: Mapping[str, int]) -> bool:
    return counts.get(run_id, 0) >= MAX_ATTEMPTS or run_id in plan.replaced()


def excluded(plan: Plan, artifacts: Path, counts: Mapping[str, int]) -> list[str]:
    """Unbanked runs with ``MAX_ATTEMPTS`` logged failures, and unbanked runs a plan
    amendment replaced (DECISIONS D71) whatever the failure log holds, in execution order.

    They are never attempted again; the analyses count them as excluded.
    """
    return [
        r.run_id
        for r in plan.ordered()
        if not _banked(artifacts, r.run_id) and _is_excluded(plan, r.run_id, counts)
    ]


def pending(plan: Plan, artifacts: Path, counts: Mapping[str, int]) -> list[str]:
    """Run ids of the plan that are neither banked nor excluded, in execution order."""
    return [
        r.run_id
        for r in plan.ordered()
        if not _banked(artifacts, r.run_id) and not _is_excluded(plan, r.run_id, counts)
    ]


class ServerMismatchError(RuntimeError):
    """The model server does not serve what a planned run needs (DECISIONS D71): another
    window per slot or slot count, a server that is not this session's own, or, for a
    run a plan amendment added, a response cache shared with other runs.

    Like :class:`CheckoutExposedError` it is a refusal, never an infrastructure
    failure: the run does not start, the session stops, and no attempt is logged.
    """


def pinned_windows() -> dict[str, int]:
    """The pinned window per slot of every pinned local model, by model name."""
    return {name: model.n_ctx for name, model in LOCAL_MODELS.items()}


def window_refusal(
    plan: Plan, spec: RunSpec, n_ctx: int | None, slots: int, *, engine: str = "llama.cpp"
) -> str | None:
    """Why a model server with ``n_ctx`` tokens of context per slot (None: the pinned
    window of the run's model) on ``slots`` slots, run by ``engine``, must not serve
    ``spec``; None when it may.

    A run that a plan amendment added needs the server the amendment names
    (:class:`receipts.study.plan.ServerRequirement`): llama.cpp, whose server reports
    the window per slot and the slots it serves, with a window raised from the pinned
    window of the run's model. Every other run is served only with the pinned window, so
    a raised window serves the runs that need it and no other.
    """
    amendment = plan.amendment(spec.run_id)
    if amendment is None and n_ctx is None:
        return None
    model = plan.arm(spec.config_id).model
    pinned = LOCAL_MODELS.get(model)
    if pinned is None:
        return f"{model} is not a pinned local model"
    window = pinned.n_ctx if n_ctx is None else n_ctx
    if amendment is None:
        if window == pinned.n_ctx:
            return None
        return (
            f"its plan sets no server requirement, so it is served only with the pinned "
            f"window of {pinned.n_ctx} tokens per slot, not {window}"
        )
    problems = amendment.server.problems(window, slots)
    if amendment.server.pinned_n_ctx_per_slot != pinned.n_ctx:
        problems.append(
            f"its amendment raises a pinned window of {amendment.server.pinned_n_ctx_per_slot} "
            f"tokens per slot, and {model} has the pinned window {pinned.n_ctx}"
        )
    if engine != "llama.cpp":
        problems.append(
            f"it needs the llama.cpp engine, whose server reports the window per slot and the "
            f"slots it serves, not {engine}"
        )
    if not problems:
        return None
    return (
        f"{'; '.join(problems)} (plan amendment {amendment.decision} in place of "
        f"{amendment.replaces}: {amendment.server.describe()})"
    )


def response_cache(plan: Plan, spec: RunSpec) -> Path:
    """Where the model responses of ``spec`` are cached: the shared ``runs/cache`` for a
    run planned from the start, and a directory of its own,
    ``runs/<study>/cache/<run id>`` (:func:`receipts.study.plan.amendment_cache`), for a
    run a plan amendment added. The shared cache holds the replies that other runs got
    on the server with the pinned window, the excluded run's among them, and its keys do
    not cover the server's window, so the added run would otherwise replay the replies it
    was planned to make again on a larger window (DECISIONS D71)."""
    if plan.amendment(spec.run_id) is None:
        return RUNS / "cache"
    return RUNS / plan.study / "cache" / spec.run_id


#: Subject runs use only a backend that confines writes (bubblewrap, D33); the unconfined
#: ``unshare`` fallback is never used for an agent. Same pinned toolchain as
#: tools/bench_validate.py, so runs see the environment the tasks were validated in.
BACKENDS: tuple[str, ...] = ("bwrap",)
TOOLCHAIN_DIR = RUNS / "toolchains" / f"bench-py{TOOLCHAIN_PYTHON.replace('.', '')}"
_TOOLCHAIN_LOCK = threading.Lock()
_TOOLCHAIN: list[Toolchain] = []


def toolchain() -> Toolchain:
    """The pinned read-only Python toolchain (built once, then reused)."""
    with _TOOLCHAIN_LOCK:
        if not _TOOLCHAIN:
            _TOOLCHAIN.append(
                python_toolchain(TOOLCHAIN_DIR, TOOLCHAIN_PACKAGES, python=TOOLCHAIN_PYTHON)
            )
        return _TOOLCHAIN[0]


class CheckoutExposedError(RuntimeError):
    """The sandbox a study run would use lets its commands reach the checkout.

    The run must not start. This is never an infrastructure failure: it would fail
    every attempt alike, so it stops the session and no attempt is logged.
    """


def checkouts() -> tuple[Path, ...]:
    """The checkouts a study run's sandbox must hide, resolved.

    This checkout (:data:`ROOT`: the benchmark's hidden checks and reference solutions,
    the instrument, ``private/``, and every run's files) and, when the imported package
    lies in another one (the main checkout around a worktree, for example), that one
    too (:func:`receipts.sandbox.bwrap.project_root`). Named here, they are hidden
    whatever code the session imports, a code snapshot under ``runs/code/`` included.
    """
    found = {ROOT.resolve(): None}
    outer = project_root()
    if outer is not None:
        found[outer.resolve()] = None
    return tuple(found)


def hidden_paths() -> tuple[Path, ...]:
    """What a study run's bubblewrap sandbox hides: the default hidden paths with this
    checkout named (``default_hidden_paths(project=ROOT)``) and every :func:`checkouts`."""
    return tuple(dict.fromkeys([*default_hidden_paths(project=ROOT), *checkouts()]))


def study_sandbox(work: Path, policy: SandboxPolicy) -> Sandbox:
    """The sandbox of one study run on workspace ``work``: a backend of :data:`BACKENDS`
    that hides :func:`hidden_paths`; ``policy.readonly_paths`` (the toolchain) and the
    workspace stay reachable even inside the hidden checkout."""
    return make_sandbox(work, policy, prefer=BACKENDS, hide_paths=hidden_paths())


def _relative_to_root(path: Path) -> str:
    return path.relative_to(ROOT.resolve()).as_posix() if path.is_relative_to(ROOT) else str(path)


def checkout_hiding(box: Sandbox) -> dict[str, Any]:
    """Check that no command in ``box`` can reach a checkout; the run record's account.

    Two checks, before any agent command runs: the sandbox's own layout must hide every
    one of :func:`checkouts` (a backend that cannot say what it hides is refused), and a
    command run inside it must not find any checkout's ``pyproject.toml``. A Docker
    sandbox passes when neither its workspace nor a read-only path is a checkout or lies
    above one, since a container sees no other host path. The read-only paths and the
    workspace inside a checkout (the toolchain under ``runs/toolchains``, the run's
    workspace under ``runs/work``) stay reachable and are listed.

    Returns:
        ``{"backend": ..., "checkout_hidden": True, "shown_in_checkout": [...]}``, the
        last relative to :data:`ROOT` and sorted.

    Raises:
        CheckoutExposedError: A checkout is within reach of the sandbox's commands.
    """
    roots = checkouts()
    if not isinstance(box, HidesPaths):
        raise CheckoutExposedError(
            f"the {box.backend} sandbox cannot say which host paths it hides, so it may "
            f"show the checkout {roots[0]}"
        )
    reached = [str(root) for root in roots if not box.hides(root)]
    if reached:
        raise CheckoutExposedError(
            f"the {box.backend} sandbox lets commands reach the checkout {', '.join(reached)}"
        )
    markers = [root / "pyproject.toml" for root in roots if (root / "pyproject.toml").is_file()]
    if markers:
        probe = " && ".join(f"test ! -e {shlex.quote(str(marker))}" for marker in markers)
        outcome = box.run(probe, timeout_s=60.0)
        if outcome.exit_code != 0:
            raise CheckoutExposedError(
                f"a command in the {box.backend} sandbox finds "
                f"{' or '.join(map(str, markers))} (probe exit {outcome.exit_code})"
            )
    shown = {_relative_to_root(path) for root in roots for path in box.shown_within(root)}
    return {"backend": box.backend, "checkout_hidden": True, "shown_in_checkout": sorted(shown)}


def preflight(study: str) -> dict[str, Any]:
    """Check, before any model server starts, that a run of ``study`` would get a
    sandbox that hides the checkout (:func:`checkout_hiding`).

    The sandbox is built as for a run (:func:`study_sandbox`, the toolchain read-only)
    on an empty workspace beside the runs' workspaces, ``runs/work/<study>/``, which is
    removed afterwards.

    Raises:
        CheckoutExposedError: The sandbox shows the checkout.
        SandboxUnavailableError: No sandbox backend works here.
    """
    policy = with_toolchain(SandboxPolicy(), toolchain())
    work_root = RUNS / "work" / study
    work_root.mkdir(parents=True, exist_ok=True)
    probe = Path(tempfile.mkdtemp(prefix=".preflight-", dir=work_root))
    try:
        return checkout_hiding(study_sandbox(probe, policy))
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def served_model(pinned: LocalModel, n_ctx: int | None) -> LocalModel:
    """The model a session serves: ``pinned`` itself, or a copy whose context window per
    slot is ``n_ctx`` tokens (``--n-ctx``; DECISIONS D71). ``pinned`` is unchanged.

    Raises:
        ValueError: ``n_ctx`` is not a positive number of tokens.
    """
    if n_ctx is None or n_ctx == pinned.n_ctx:
        return pinned
    if n_ctx < 1:
        raise ValueError(f"a context window must be a positive number of tokens, not {n_ctx}")
    return replace(pinned, n_ctx=n_ctx)


def server_record(server: LocalServer, reported: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The model server's provenance for a run record (``provenance.model_server``).

    It is :meth:`LocalServer.provenance` (with the window per slot and the slots) plus
    the pinned window per slot of the served model (``n_ctx_per_slot_default``, from
    :data:`LOCAL_MODELS`) and whether the server served it
    (``n_ctx_per_slot_is_default``), so a run made with another window says so, and
    ``reported``, what the live server reported serving before the run
    (:meth:`LocalServer.confirm_serving`), when it reported anything.
    """
    record = dict(server.provenance())
    pinned = LOCAL_MODELS[server.model.name].n_ctx
    record["n_ctx_per_slot_default"] = pinned
    record["n_ctx_per_slot_is_default"] = server.model.n_ctx == pinned
    if reported is not None:
        record["reported"] = dict(reported)
    return record


def one_run(
    plan: Plan,
    spec: RunSpec,
    client: ModelClient,
    artifacts: Path,
    sha: str,
    server: LocalServer,
    code: Mapping[str, Any] | None = None,
) -> RunRecord:
    """Make one attempt at one planned run and bank it.

    The server must serve the run (:func:`window_refusal`): a run a plan amendment added
    gets the window and slots its amendment requires, any other run the pinned window.
    The live server must then confirm that it is this session's own and serves that
    window and those slots (:meth:`LocalServer.confirm_serving`); what it reports is
    banked in ``provenance["model_server"]["reported"]``. A run an amendment added must
    get its replies through ``client`` from its own response cache
    (:func:`response_cache`), and its record carries the amendment and that cache
    (``provenance["plan_amendment"]``, ``provenance["response_cache"]``). The run's
    sandbox hides the checkout (:func:`study_sandbox`) and is checked before the run
    starts (:func:`checkout_hiding`); its record is banked as ``provenance["sandbox"]``.

    Raises:
        InfrastructureError: ``execute_run`` raised, so the run is left unbanked.
            Errors before it (the arm, the task files, the toolchain, the task tree hash)
            propagate unchanged: they would fail every attempt alike.
        ServerMismatchError: The server does not serve the run, is not confirmed, or the
            run would be served from a shared cache; raised before anything else, it
            stops the session and is never logged as an attempt.
        CheckoutExposedError: The run's sandbox shows the checkout; it propagates
            unchanged too, so it stops the session and is never logged as an attempt.
    """
    refusal = window_refusal(
        plan, spec, server.model.n_ctx, server.parallel, engine=str(server.engine)
    )
    if refusal is not None:
        raise ServerMismatchError(f"{spec.run_id}: {refusal}")
    try:
        reported = server.confirm_serving()
    except ServerStateError as exc:
        raise ServerMismatchError(f"{spec.run_id}: {exc}") from exc
    amendment = plan.amendment(spec.run_id)
    if amendment is not None:
        if reported is None:
            raise ServerMismatchError(
                f"{spec.run_id}: its server does not report the window per slot and the "
                "slots it serves"
            )
        own = response_cache(plan, spec)
        if Path(client.cache_dir) != own:
            raise ServerMismatchError(
                f"{spec.run_id}: its replies would come from the response cache "
                f"{client.cache_dir}, not its own {own}"
            )
    task_dir = ROOT / "bench" / "tasks" / spec.task_id
    arm = plan.arm(spec.config_id)
    task = load_run_task(task_dir)
    chain = toolchain()
    policy = with_toolchain(
        SandboxPolicy(timeout_s=task.command_timeout_s, memory_mb=task.memory_mb), chain
    )
    added: dict[str, Any] = (
        {}
        if amendment is None
        else {
            "plan_amendment": amendment.to_json(),
            "response_cache": amendment_cache(plan.study, spec.run_id),
        }
    )
    extra = {
        "toolchain_installed": list(chain.installed),
        "task_tree_sha256": tree_sha256(task_dir),
        **added,
        **dict(code or {}),
    }
    try:
        record = execute_run(
            spec,
            task,
            arm,
            client,
            study=plan.text,
            artifacts_dir=artifacts,
            work_root=RUNS / "work" / plan.study,
            sandbox_factory=lambda work: study_sandbox(work, policy),
            sandbox_check=checkout_hiding,
            git_sha=sha,
            server_provenance=server_record(server, reported),
            extra_provenance=extra,
        )
    except CheckoutExposedError:
        raise  # a refusal, not an infrastructure failure: the session stops, unlogged
    except Exception as exc:  # infrastructure failure: the run stays unbanked
        raise InfrastructureError(
            f"{type(exc).__name__}: {exc}", traceback.format_exc()[-4000:]
        ) from exc
    print(
        f"done {spec.run_id}: {record.stop_reason} after {record.turns} turns; "
        f"false_success={record.false_success}",
        flush=True,
    )
    return record


@dataclass
class SessionResult:
    """What one session did with the runs it was given (run ids in the given order).

    Attributes:
        banked: Runs banked in this session.
        excluded: Runs with ``MAX_ATTEMPTS`` logged failures (never attempted again).
        left: Runs neither banked nor excluded because the session stopped first; a
            later session attempts them again.
        stopped: True when the stop rule ended the session.
    """

    banked: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)
    stopped: bool = False


def run_session(
    runs: Sequence[RunSpec],
    attempt: Callable[[RunSpec], object],
    state: Path,
    *,
    parallel: int = 1,
    stop_after: int = STOP_AFTER_FAILURES,
) -> SessionResult:
    """Attempt every run, queueing each failed one again until it is banked or excluded.

    ``attempt(spec)`` makes one attempt and raises :class:`InfrastructureError` when it
    fails. Each failure is logged with its attempt number (:func:`log_failure`), and the
    run goes back in the queue with the same spec, behind the runs already queued, until
    it has ``MAX_ATTEMPTS`` logged failures, counted from the log (earlier sessions
    included). Any other exception stops the session and propagates. After
    ``stop_after`` failed attempts in a row with no run banked in between, no further
    attempt starts; attempts already running finish and are recorded.
    """
    halt = threading.Event()
    lock = threading.Lock()
    streak = 0

    def attempt_once(spec: RunSpec) -> str:
        nonlocal streak
        if halt.is_set():
            return "left"
        number = failure_counts(state).get(spec.run_id, 0) + 1
        if number > MAX_ATTEMPTS:
            return "excluded"
        started = _now()
        print(
            f"{started} start {spec.run_id} ({spec.config_id}), attempt {number} of {MAX_ATTEMPTS}",
            flush=True,
        )
        try:
            attempt(spec)
        except InfrastructureError as failure:
            logged = log_failure(state, spec.run_id, started, failure)
            print(
                f"FAILED {spec.run_id} (attempt {logged} of {MAX_ATTEMPTS}): {failure.error}",
                flush=True,
            )
            with lock:
                streak += 1
                if streak >= stop_after:
                    halt.set()
            if logged >= MAX_ATTEMPTS:
                print(f"EXCLUDED {spec.run_id}: {logged} failed attempts", flush=True)
                return "excluded"
            return "failed"
        with lock:
            streak = 0
        return "banked"

    def guarded(spec: RunSpec) -> str:
        try:
            return attempt_once(spec)
        except BaseException:
            halt.set()  # an unexpected error: start nothing more
            raise

    outcome: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        queued: dict[Future[str], RunSpec] = {pool.submit(guarded, spec): spec for spec in runs}
        try:
            while queued:
                done, _ = wait(queued, return_when=FIRST_COMPLETED)
                for future in done:
                    spec = queued.pop(future)
                    result = future.result()
                    if result == "failed" and not halt.is_set():
                        queued[pool.submit(guarded, spec)] = spec  # retried after the queue
                    else:
                        outcome[spec.run_id] = "left" if result == "failed" else result
        except BaseException:
            halt.set()  # an error or an interrupt: the queued attempts never start
            raise
    order = [spec.run_id for spec in runs]
    return SessionResult(
        banked=[r for r in order if outcome.get(r) == "banked"],
        excluded=[r for r in order if outcome.get(r) == "excluded"],
        left=[r for r in order if outcome.get(r) == "left"],
        stopped=halt.is_set(),
    )


def run_model(
    plan: Plan,
    model_name: str,
    runs: Sequence[RunSpec],
    args: argparse.Namespace,
    artifacts: Path,
    state: Path,
    sha: str,
    code: Mapping[str, Any],
) -> SessionResult:
    """Serve one model, with the window per slot that ``--n-ctx`` asks for (the pinned
    one by default, :func:`served_model`), and run its share of the plan
    (:func:`run_session`). Each run's replies are cached where :func:`response_cache`
    says: a run a plan amendment added gets a cache of its own."""
    server = LocalServer(
        served_model(LOCAL_MODELS[model_name], args.n_ctx),
        port=args.port,
        threads=args.threads,
        log_path=state / f"server-{model_name}.log",
        engine=args.engine,
        parallel=args.parallel,
    )
    backend = LocalOpenAIBackend(server.base_url, timeout_s=args.request_timeout)
    clients = {
        cache: ModelClient(ROOT, {"local": backend}, cache)
        for cache in dict.fromkeys(response_cache(plan, spec) for spec in runs)
    }

    def attempt(spec: RunSpec) -> RunRecord:
        client = clients[response_cache(plan, spec)]
        return one_run(plan, spec, client, artifacts, sha, server, code)

    with server:
        return run_session(runs, attempt, state, parallel=args.parallel)


@contextmanager
def sigterm_stops_session() -> Iterator[None]:
    """While the block runs, a SIGTERM raises ``SystemExit(143)`` in the main thread, so
    the session stops as it does on an exception: no new attempt starts, the attempts
    already running end, and every model server's context exits, which stops the
    server (review F3: a plain SIGTERM left the llama-server running). The handler that
    was there before is put back afterwards."""

    def stop(signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def main(argv: Sequence[str] | None = None) -> int:
    """Run every pending run of a plan (exit 1 when the stop rule ends the session)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None, help="stop after this many runs")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--dry-run", action="store_true", help="list pending runs and exit")
    parser.add_argument("--engine", choices=("llama.cpp", "llama-cpp-python"), default="llama.cpp")
    parser.add_argument(
        "--parallel", type=int, default=1, help="concurrent runs per model (at least 1)"
    )
    parser.add_argument(
        "--n-ctx",
        type=int,
        default=None,
        metavar="TOKENS",
        help="context window per server slot (default: the pinned model's); another window "
        "serves only runs whose plan amendment requires it (DECISIONS D71)",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=3600.0,
        help="seconds one model call may take (a cold prompt on a shared CPU can take minutes)",
    )
    args = parser.parse_args(argv)
    if args.n_ctx is not None and args.n_ctx < 1:
        parser.error(f"--n-ctx must be a positive number of tokens, not {args.n_ctx}")
    if args.parallel < 1:
        parser.error(f"--parallel must be at least 1 slot, not {args.parallel}")
    try:
        plan = load_plan(args.plan)
        check_amendments(plan, pinned_windows())
    except ValueError as exc:
        print(f"{args.plan}: {exc}", file=sys.stderr)
        return 2
    artifacts = args.plan.parent / "runs"
    state = RUNS / plan.study
    try:
        counts = failure_counts(state)
    except ValueError as exc:
        print(f"{exc}; repair the log before running study {plan.study}", file=sys.stderr)
        return 2
    todo = pending(plan, artifacts, counts)
    out = excluded(plan, artifacts, counts)
    listed = f": {', '.join(out)}" if out else ""
    print(
        f"study {plan.study}: {len(todo)} of {len(plan.runs)} runs pending; {len(out)} excluded "
        f"(after {MAX_ATTEMPTS} failed attempts, or replaced by a plan amendment){listed}",
        flush=True,
    )
    specs = {r.run_id: r for r in plan.runs}
    refused = {
        run_id: why
        for run_id in todo
        if (
            why := window_refusal(
                plan, specs[run_id], args.n_ctx, args.parallel, engine=args.engine
            )
        )
        is not None
    }
    if args.dry_run:
        for run_id in todo:
            print(run_id)
            amendment = plan.amendment(run_id)
            if amendment is not None:
                print(
                    f"  plan amendment {amendment.decision}: in place of {amendment.replaces}; "
                    f"it needs {amendment.server.describe()}"
                )
            if run_id in refused:
                print(f"  refused on this session's server: {refused[run_id]}")
        replaced_by = {amendment.replaces: amendment for amendment in plan.amendments}
        for run_id in out:
            note = f"{counts.get(run_id, 0)} failed attempts"
            if run_id in replaced_by:
                by = replaced_by[run_id]
                note += f"; replaced by {by.run_id}, {by.decision}"
            print(f"excluded: {run_id} ({note})")
        return 0
    if args.parallel > 1 and args.engine != "llama.cpp":
        parser.error("--parallel above 1 needs --engine llama.cpp (continuous batching)")
    for run_id, why in refused.items():
        print(f"REFUSED: {run_id}: {why}; it waits for a session that serves it", file=sys.stderr)
    todo = [run_id for run_id in todo if run_id not in refused]
    if refused and not todo:
        print(
            f"REFUSED: no pending run of study {plan.study} can run on this session's server "
            "(--n-ctx, --parallel); no server starts",
            file=sys.stderr,
        )
        return 2
    state.mkdir(parents=True, exist_ok=True)
    (state / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    if args.limit is not None:
        todo = todo[: args.limit]
    code = code_state()
    sha = str(code["snapshot_of"]) if code["code"] == "snapshot" else git_sha()
    if todo:
        try:
            hiding = preflight(plan.study)
        except (CheckoutExposedError, SandboxUnavailableError) as exc:
            print(f"REFUSED: {exc}; no run of study {plan.study} starts", file=sys.stderr)
            return 2
        shown = ", ".join(hiding["shown_in_checkout"]) or "nothing"
        print(f"sandbox: {hiding['backend']} hides the checkout (shown in it: {shown})", flush=True)
    by_model: dict[str, list[RunSpec]] = {}
    for run_id in todo:
        by_model.setdefault(plan.arm(specs[run_id].config_id).model, []).append(specs[run_id])
    total = SessionResult()
    try:
        with sigterm_stops_session():
            for model_name, runs in by_model.items():
                result = run_model(plan, model_name, runs, args, artifacts, state, sha, code)
                total.banked += result.banked
                total.excluded += result.excluded
                if result.stopped:
                    total.stopped = True
                    break
    except (CheckoutExposedError, ServerMismatchError, ServerStateError) as exc:
        print(f"REFUSED: {exc}; study {plan.study} stops, no attempt logged", file=sys.stderr)
        return 2
    print(f"study {plan.study}: {len(total.banked)} run(s) banked this session", flush=True)
    if total.excluded:
        print(
            f"study {plan.study}: excluded after {MAX_ATTEMPTS} failed attempts: "
            f"{', '.join(total.excluded)}",
            flush=True,
        )
    if total.stopped:
        waiting = [r for r in todo if r not in total.banked and r not in total.excluded]
        print(
            f"STOPPED: {STOP_AFTER_FAILURES} failed attempts in a row with no run banked, so "
            f"the failure looks systematic (see {state / FAILURES}). Fix the cause and "
            f"restart; {len(waiting)} run(s) wait, and their logged attempts count toward "
            f"the cap of {MAX_ATTEMPTS}.",
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
