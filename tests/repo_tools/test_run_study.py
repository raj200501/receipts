"""tools/run_study.py: the three-attempt retry rule for infrastructure failures, the
sandbox that hides the checkout, and the code-snapshot check.

prereg/0001-e1-main-study.md section 10: a failed attempt is logged with its attempt
number, the run is retried with the same seed up to two times, the attempts are counted
from ``runs/<study>/failures.jsonl`` so the cap holds across restarts, and a run with
three logged failures is excluded. DECISIONS D67 (review N18): every run's sandbox hides
the checkout and a sandbox that shows it is refused; a code snapshot must be the src/
tree of its commit. Every plan, run, failure, checkout, commit, and server here is a
SYNTHETIC test fixture and no model is called. One test starts a real bubblewrap
sandbox on a synthetic checkout under /var/tmp (removed afterwards); nothing else is
written outside tmp_path.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import signal
import subprocess
import tarfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

import receipts
import run_study
from receipts.client.server import LocalModel, LocalServer, ServerStateError
from receipts.sandbox.bwrap import probe_bwrap
from receipts.study.plan import (
    Plan,
    ServerRequirement,
    amend_plan,
    amendment_cache,
    local_arm,
    smoke_plan,
    write_plan,
)
from receipts.study.spec import RunSpec

needs_bwrap = pytest.mark.skipif(not probe_bwrap().ok, reason="bubblewrap does not work here")

SYNTHETIC_MODELS = ("synthetic-model-a", "synthetic-model-b")
PINNED_N_CTX = 16384


def synthetic_model(name: str = SYNTHETIC_MODELS[0], n_ctx: int = PINNED_N_CTX) -> LocalModel:
    """A SYNTHETIC pinned model (no file behind it; nothing here serves it)."""
    path = Path("/nonexistent/synthetic.gguf")
    return LocalModel(name, "fam", path, "0" * 64, "SYNTHETIC", n_ctx)


def synthetic_plan(n_runs: int = 4, study: str = "synthetic-study") -> Plan:
    """A SYNTHETIC plan: two arms on two model names, ``n_runs`` runs each."""
    arms = [
        local_arm("arm-a", SYNTHETIC_MODELS[0], "fam-a"),
        local_arm("arm-b", SYNTHETIC_MODELS[1], "fam-b"),
    ]
    runs = [
        RunSpec(f"{study}-{i:03d}-{arm.config_id}", study, "py-synthetic", arm.config_id, {}, i)
        for arm in arms
        for i in range(n_runs)
    ]
    return Plan(study, arms, runs, notes="SYNTHETIC plan for a test")


def specs(n: int, study: str = "synthetic-study") -> list[RunSpec]:
    """``n`` SYNTHETIC run specs of one arm."""
    return [
        RunSpec(f"{study}-{i:03d}", study, "py-synthetic", "arm-a", {}, 100 + i) for i in range(n)
    ]


def failure(message: str = "synthetic server error") -> run_study.InfrastructureError:
    """A SYNTHETIC infrastructure failure."""
    return run_study.InfrastructureError(f"RuntimeError: {message}", "Traceback: synthetic")


def logged(state: Path) -> list[dict[str, Any]]:
    """Every entry of the failure log under ``state``."""
    path = state / "failures.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_log(state: Path, entries: list[dict[str, Any]]) -> None:
    """A SYNTHETIC failure log from earlier sessions."""
    state.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(entry) + "\n" for entry in entries)
    (state / "failures.jsonl").write_text(text, encoding="utf-8")


class Script:
    """A SYNTHETIC attempt function: each run fails a set number of times, then banks."""

    def __init__(self, fail_first: dict[str, int] | None = None, *, always: bool = False):
        self.fail_first = dict(fail_first or {})
        self.always = always
        self.calls: list[RunSpec] = []
        self._lock = threading.Lock()

    def __call__(self, spec: RunSpec) -> None:
        with self._lock:
            self.calls.append(spec)
            previous = sum(1 for s in self.calls[:-1] if s.run_id == spec.run_id)
        if self.always or previous < self.fail_first.get(spec.run_id, 0):
            raise failure(f"attempt {previous + 1} of {spec.run_id}")

    def order(self) -> list[str]:
        """Run ids in the order they were attempted."""
        return [spec.run_id for spec in self.calls]


# The failure log ---------------------------------------------------------------------


def test_failure_counts_count_every_logged_line_per_run(tmp_path: Path) -> None:
    assert run_study.failure_counts(tmp_path) == {}
    write_log(
        tmp_path,
        [
            # A line in the old format (no attempt number) still counts as a failure.
            {"run_id": "r1", "at": "2026-11-04T07:20:04+00:00", "error": "E", "trace": ""},
            {"run_id": "r1", "attempt": 2, "time": "t", "error": "E"},
            {"run_id": "r2", "attempt": 1, "time": "t", "error": "E"},
        ],
    )
    with (tmp_path / "failures.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    assert run_study.failure_counts(tmp_path) == {"r1": 2, "r2": 1}


@pytest.mark.parametrize(
    ("line", "message"),
    [('{"run_id": "r1", "error": ', "not JSON"), ('{"error": "E"}', "run_id"), ("[1]", "run_id")],
)
def test_failure_counts_refuse_a_log_they_cannot_count(
    tmp_path: Path, line: str, message: str
) -> None:
    (tmp_path / "failures.jsonl").write_text(f'{{"run_id": "r1"}}\n{line}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        run_study.failure_counts(tmp_path)


def test_log_failure_records_the_attempt_number(tmp_path: Path) -> None:
    write_log(tmp_path, [{"run_id": "r1", "at": "earlier", "error": "E", "trace": ""}])
    assert run_study.log_failure(tmp_path, "r1", "2026-11-04T10:00:00+00:00", failure()) == 2
    assert run_study.log_failure(tmp_path, "r2", "2026-11-04T10:00:00+00:00", failure()) == 1
    assert run_study.log_failure(tmp_path, "r1", "2026-11-04T11:00:00+00:00", failure()) == 3
    entries = logged(tmp_path)
    assert [(e["run_id"], e.get("attempt")) for e in entries] == [
        ("r1", None),
        ("r1", 2),
        ("r2", 1),
        ("r1", 3),
    ]
    last = entries[-1]
    assert set(last) == {"run_id", "attempt", "started", "time", "error", "trace"}
    assert last["started"] == "2026-11-04T11:00:00+00:00"
    assert last["error"] == "RuntimeError: synthetic server error"
    assert last["trace"] == "Traceback: synthetic"


def test_pending_and_excluded_runs(tmp_path: Path) -> None:
    plan = synthetic_plan(n_runs=2)
    ids = [run.run_id for run in plan.ordered()]
    artifacts = tmp_path / "runs"
    for banked in (ids[0], ids[3]):
        (artifacts / banked).mkdir(parents=True)
        (artifacts / banked / "run.json").write_text("{}", encoding="utf-8")
    counts = {ids[1]: 3, ids[2]: 2, ids[3]: 3, "not-in-plan": 5}
    assert run_study.excluded(plan, artifacts, counts) == [ids[1]]
    assert run_study.pending(plan, artifacts, counts) == [ids[2]]
    assert run_study.pending(plan, artifacts, {}) == [ids[1], ids[2]]


# The session: retries, the cap, and the stop rule -------------------------------------------


def test_a_failed_run_is_retried_with_the_same_spec_after_the_queued_runs(tmp_path: Path) -> None:
    runs = specs(3)
    script = Script({runs[0].run_id: 2})
    result = run_study.run_session(runs, script, tmp_path)
    a, b, c = (run.run_id for run in runs)
    assert script.order() == [a, b, c, a, a]
    # Every attempt gets the planned spec itself: the same seed each time.
    assert all(spec is runs[0] for spec in script.calls if spec.run_id == a)
    assert sorted(result.banked) == sorted([a, b, c])
    assert (result.excluded, result.left, result.stopped) == ([], [], False)
    assert [(e["run_id"], e["attempt"]) for e in logged(tmp_path)] == [(a, 1), (a, 2)]


def test_a_run_is_excluded_after_three_failed_attempts(tmp_path: Path) -> None:
    runs = specs(2)
    bad, good = runs[0].run_id, runs[1].run_id
    script = Script({bad: 99})
    result = run_study.run_session(runs, script, tmp_path)
    assert script.order() == [bad, good, bad, bad]
    assert (result.banked, result.excluded, result.stopped) == ([good], [bad], False)
    assert [(e["run_id"], e["attempt"]) for e in logged(tmp_path)] == [
        (bad, 1),
        (bad, 2),
        (bad, 3),
    ]


def test_the_cap_holds_across_restarts(tmp_path: Path) -> None:
    runs = specs(2)
    first, second = runs[0].run_id, runs[1].run_id
    # Earlier sessions logged two failures of the first run and three of the second.
    write_log(
        tmp_path,
        [{"run_id": first, "attempt": n, "time": "t", "error": "E"} for n in (1, 2)]
        + [{"run_id": second, "attempt": n, "time": "t", "error": "E"} for n in (1, 2, 3)],
    )
    script = Script(always=True)
    result = run_study.run_session(runs, script, tmp_path)
    # One attempt is left for the first run; the second is never attempted again.
    assert script.order() == [first]
    assert sorted(result.excluded) == sorted([first, second]) and not result.banked
    assert [e["attempt"] for e in logged(tmp_path)] == [1, 2, 1, 2, 3, 3]


def test_the_session_stops_when_failures_repeat_across_runs(tmp_path: Path) -> None:
    # A SYNTHETIC dead model server: every attempt of every run fails.
    runs = specs(6)
    script = Script(always=True)
    result = run_study.run_session(runs, script, tmp_path)
    tried = [run.run_id for run in runs[: run_study.STOP_AFTER_FAILURES]]
    assert script.order() == tried
    assert result.stopped is True
    assert sorted(result.left) == sorted(run.run_id for run in runs) and not result.excluded
    # Each tried run used one attempt; the others keep all three for a later session.
    assert run_study.failure_counts(tmp_path) == dict.fromkeys(tried, 1)


def test_one_run_failing_its_attempts_in_a_row_does_not_stop_the_session(tmp_path: Path) -> None:
    runs = specs(1)
    result = run_study.run_session(runs, Script(always=True), tmp_path)
    assert result.stopped is False and result.excluded == [runs[0].run_id]
    assert run_study.STOP_AFTER_FAILURES > run_study.MAX_ATTEMPTS


def test_a_banked_run_resets_the_stop_rule(tmp_path: Path) -> None:
    runs = specs(7)
    # Three runs fail, one banks, three more fail: never four failures in a row before
    # the retries; the retries then fail in a row and stop the session.
    script = Script({run.run_id: 99 for i, run in enumerate(runs) if i != 3})
    result = run_study.run_session(runs, script, tmp_path)
    assert script.order()[:7] == [run.run_id for run in runs]
    assert result.banked == [runs[3].run_id]
    assert result.stopped is True


def test_an_unexpected_error_stops_the_session_and_is_not_logged(tmp_path: Path) -> None:
    runs = specs(3)
    calls: list[str] = []

    def broken(spec: RunSpec) -> None:
        calls.append(spec.run_id)
        raise KeyError("synthetic setup error")

    with pytest.raises(KeyError):
        run_study.run_session(runs, broken, tmp_path)
    assert calls == [runs[0].run_id]
    assert logged(tmp_path) == []


def test_an_interrupt_starts_no_queued_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = specs(4)
    script = Script()
    running, release = threading.Event(), threading.Event()

    def slow(spec: RunSpec) -> None:
        script(spec)
        running.set()
        release.wait(timeout=10)

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        assert running.wait(timeout=10)  # the first attempt has started
        release.set()
        raise KeyboardInterrupt

    monkeypatch.setattr(run_study, "wait", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_study.run_session(runs, slow, tmp_path)
    # The attempt already running finished; none of the queued ones started.
    assert script.order() == [runs[0].run_id]


def test_parallel_sessions_count_each_run_separately(tmp_path: Path) -> None:
    runs = specs(8)
    script = Script({run.run_id: 1 for run in runs[::2]})
    # The stop rule is set out of reach: completion order depends on thread scheduling.
    result = run_study.run_session(runs, script, tmp_path, parallel=3, stop_after=100)
    assert sorted(result.banked) == sorted(run.run_id for run in runs)
    assert run_study.failure_counts(tmp_path) == {run.run_id: 1 for run in runs[::2]}
    assert all(e["attempt"] == 1 for e in logged(tmp_path))


# one_run: which errors are infrastructure failures ---------------------------------------


@pytest.fixture
def no_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace task loading, the toolchain, the tree hash, and the pinned models with
    SYNTHETIC stand-ins."""
    task = SimpleNamespace(command_timeout_s=60.0, memory_mb=512)
    monkeypatch.setattr(run_study, "load_run_task", lambda path: task)
    monkeypatch.setattr(run_study, "toolchain", lambda: SimpleNamespace(installed=("pkg==1",)))
    monkeypatch.setattr(run_study, "with_toolchain", lambda policy, chain: policy)
    monkeypatch.setattr(run_study, "tree_sha256", lambda path: "f" * 64)
    models = {name: synthetic_model(name) for name in SYNTHETIC_MODELS}
    monkeypatch.setattr(run_study, "LOCAL_MODELS", models)


def call_one_run(
    spec: RunSpec,
    plan: Plan | None = None,
    n_ctx: int | None = None,
    *,
    cache: Path | None = None,
    engine: str = "llama.cpp",
) -> Any:
    """one_run with stand-in client and server (serving the model of the run's arm with
    window ``n_ctx``, the pinned one by default, on one slot); the client caches in
    ``cache``, by default the run's own response cache (:func:`run_study.response_cache`).
    Each test patches execute_run."""
    plan = plan or synthetic_plan()
    pinned = run_study.LOCAL_MODELS[plan.arm(spec.config_id).model]
    server = FakeServer(run_study.served_model(pinned, n_ctx), parallel=1, engine=engine)
    client = SimpleNamespace(cache_dir=cache or run_study.response_cache(plan, spec))
    code = {"code": "working tree"}
    return run_study.one_run(plan, spec, client, Path("/nonexistent"), "a" * 40, server, code)


def raise_in_execute_run(*args: Any, **kwargs: Any) -> Any:
    """A SYNTHETIC execute_run that fails like a full disk."""
    raise OSError("synthetic: no space left on device")


def test_one_run_turns_an_error_in_execute_run_into_an_infrastructure_failure(
    no_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_study, "execute_run", raise_in_execute_run)
    with pytest.raises(run_study.InfrastructureError) as caught:
        call_one_run(synthetic_plan().runs[0])
    assert caught.value.error == "OSError: synthetic: no space left on device"
    assert "OSError" in caught.value.trace


def test_one_run_lets_setup_errors_stop_the_session(
    no_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(path: Path) -> Any:
        raise FileNotFoundError(path)

    monkeypatch.setattr(run_study, "load_run_task", missing)
    monkeypatch.setattr(run_study, "execute_run", raise_in_execute_run)
    with pytest.raises(FileNotFoundError):
        call_one_run(synthetic_plan().runs[0])


def test_one_run_passes_the_planned_spec_and_provenance(
    no_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def execute(spec: RunSpec, task: Any, arm: Any, client: Any, **kwargs: Any) -> Any:
        seen.update(kwargs, spec=spec, arm=arm)
        return SimpleNamespace(stop_reason="finished", turns=3, false_success=False)

    monkeypatch.setattr(run_study, "execute_run", execute)
    spec = synthetic_plan().runs[1]
    call_one_run(spec)
    assert seen["spec"] is spec and seen["arm"].config_id == spec.config_id
    assert seen["git_sha"] == "a" * 40
    assert seen["extra_provenance"]["task_tree_sha256"] == "f" * 64
    assert seen["extra_provenance"]["code"] == "working tree"
    # The run record's model server says which window per slot it served, and that it
    # is the pinned one, and what the live server reported serving (DECISIONS D71).
    server = seen["server_provenance"]
    assert server["n_ctx_per_slot"] == server["n_ctx_per_slot_default"] == PINNED_N_CTX
    assert server["n_ctx_per_slot_is_default"] is True
    assert server["reported"] == {
        "source": "GET /props",
        "n_ctx_per_slot": PINNED_N_CTX,
        "total_slots": 1,
        "model_path": str(synthetic_model().path),
    }
    assert "response_cache" not in seen["extra_provenance"]


def test_one_run_confirms_the_live_server_before_the_run(
    no_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review F3: a server that is not this session's own (another one on the port, a
    # dead process, another window reported) refuses the run before it starts.
    monkeypatch.setattr(run_study, "execute_run", raise_in_execute_run)
    monkeypatch.setattr(FakeServer, "confirm_error", "SYNTHETIC: the server process exited")
    with pytest.raises(run_study.ServerMismatchError, match="process exited"):
        call_one_run(synthetic_plan().runs[0])


# The server's context window per slot (DECISIONS D71) -------------------------------------


def test_served_model_is_the_pinned_one_unless_another_window_is_asked() -> None:
    pinned = synthetic_model()
    assert run_study.served_model(pinned, None) is pinned
    assert run_study.served_model(pinned, PINNED_N_CTX) is pinned
    raised = run_study.served_model(pinned, 32768)
    assert raised == dataclasses.replace(pinned, n_ctx=32768) and raised.n_ctx == 32768
    assert pinned.n_ctx == PINNED_N_CTX  # the pinned model itself is unchanged
    with pytest.raises(ValueError, match="positive"):
        run_study.served_model(pinned, 0)


@pytest.mark.parametrize(("n_ctx", "pinned"), [(None, True), (32768, False), (8192, False)])
def test_the_server_record_says_whether_the_window_is_the_pinned_one(
    monkeypatch: pytest.MonkeyPatch, n_ctx: int | None, pinned: bool
) -> None:
    model = synthetic_model()
    monkeypatch.setattr(run_study, "LOCAL_MODELS", {model.name: model})
    server = LocalServer(run_study.served_model(model, n_ctx), engine="llama.cpp", parallel=1)
    record = run_study.server_record(server)
    served = n_ctx or PINNED_N_CTX
    assert record["n_ctx_per_slot"] == served and record["ctx_size"] == served
    assert record["n_ctx_per_slot_default"] == PINNED_N_CTX
    assert record["n_ctx_per_slot_is_default"] is pinned
    assert record["server_command"] == list(server.command())
    command = record["server_command"]
    assert command[command.index("--ctx-size") + 1] == str(served)


def test_run_model_serves_the_window_the_session_asks_for(
    tmp_path: Path, no_models: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = synthetic_plan(n_runs=1)
    monkeypatch.setattr(run_study, "run_session", lambda runs, attempt, state, **kw: None)
    for n_ctx in (None, 32768):
        args = SimpleNamespace(
            port=1, threads=1, engine="llama.cpp", parallel=1, request_timeout=1.0, n_ctx=n_ctx
        )
        run_study.run_model(plan, SYNTHETIC_MODELS[0], [], args, tmp_path, tmp_path, "a" * 40, {})
    assert FakeServer.served == [
        (SYNTHETIC_MODELS[0], PINNED_N_CTX, 1),
        (SYNTHETIC_MODELS[0], 32768, 1),
    ]
    assert run_study.LOCAL_MODELS[SYNTHETIC_MODELS[0]].n_ctx == PINNED_N_CTX


def test_main_refuses_a_window_that_is_not_a_positive_number(
    tmp_path: Path, no_models: None, capsys: pytest.CaptureFixture[str]
) -> None:
    path = plan_file(tmp_path, synthetic_plan(n_runs=1))
    with pytest.raises(SystemExit):
        run_study.main(["--plan", str(path), "--n-ctx", "0"])
    assert "--n-ctx must be a positive number of tokens" in capsys.readouterr().err
    assert FakeServer.started == []


@pytest.mark.parametrize("slots", ["0", "-1"])
@pytest.mark.parametrize("dry_run", [[], ["--dry-run"]])
def test_main_refuses_fewer_than_one_slot(
    tmp_path: Path,
    no_models: None,
    capsys: pytest.CaptureFixture[str],
    slots: str,
    dry_run: list[str],
) -> None:
    # Review F7: --parallel 0 would start "--ctx-size 0 --parallel 0" and bank a run
    # whose record banking and G6 refuse, with no way to redo it.
    path = plan_file(tmp_path, synthetic_plan(n_runs=1))
    with pytest.raises(SystemExit):
        run_study.main(["--plan", str(path), "--parallel", slots, *dry_run])
    assert "--parallel must be at least 1" in capsys.readouterr().err
    assert FakeServer.started == []


def test_sigterm_stops_the_session_and_its_server(
    tmp_path: Path, no_models: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review F3: a plain SIGTERM to the runner left its llama-server running. Now the
    # session stops and the server's context exits, so the server is stopped.
    path = plan_file(tmp_path, synthetic_plan(n_runs=1))

    def terminated(runs: Any, attempt: Any, state: Path, **kwargs: Any) -> Any:
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(30)  # the handler raises SystemExit before this ends
        raise AssertionError("SIGTERM did not stop the session")

    def unhandled(signum: int, frame: object) -> None:
        raise AssertionError("the session left SIGTERM to the handler it found")

    monkeypatch.setattr(run_study, "run_session", terminated)
    previous = signal.signal(signal.SIGTERM, unhandled)  # so pytest itself is not killed
    try:
        with pytest.raises(SystemExit) as stopped:
            run_study.main(["--plan", str(path)])
        assert stopped.value.code == 128 + signal.SIGTERM
        assert FakeServer.started == FakeServer.stopped == [SYNTHETIC_MODELS[0]]
        assert signal.getsignal(signal.SIGTERM) is unhandled  # the handler it found is back
    finally:
        signal.signal(signal.SIGTERM, previous)


# main: what it reports, and what it never re-runs ----------------------------------------


def plan_file(tmp_path: Path, plan: Plan) -> Path:
    """Write a SYNTHETIC plan.json under tmp_path."""
    path = tmp_path / "artifacts" / "studies" / plan.study / "plan.json"
    write_plan(path, plan)
    return path


def test_dry_run_lists_pending_and_excluded_runs_and_leaves_the_pid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run_study, "RUNS", tmp_path / "state")
    plan = synthetic_plan(n_runs=2)
    path = plan_file(tmp_path, plan)
    ids = [run.run_id for run in plan.ordered()]
    state = tmp_path / "state" / plan.study
    write_log(
        state, [{"run_id": ids[0], "attempt": n, "time": "t", "error": "E"} for n in (1, 2, 3)]
    )
    (state / "pid").write_text("12345\n", encoding="utf-8")
    assert run_study.main(["--plan", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "3 of 4 runs pending" in out and "1 excluded" in out
    assert [line for line in out.splitlines() if line in ids] == ids[1:]
    assert f"excluded: {ids[0]} (3 failed attempts)" in out.splitlines()
    assert (state / "pid").read_text(encoding="utf-8") == "12345\n"


def test_main_refuses_a_failure_log_it_cannot_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run_study, "RUNS", tmp_path / "state")
    plan = synthetic_plan()
    path = plan_file(tmp_path, plan)
    state = tmp_path / "state" / plan.study
    state.mkdir(parents=True)
    (state / "failures.jsonl").write_text('{"run_id": \n', encoding="utf-8")
    assert run_study.main(["--plan", str(path), "--dry-run"]) == 2
    assert run_study.main(["--plan", str(path)]) == 2
    assert "not JSON" in capsys.readouterr().err
    assert not (state / "pid").exists()


class FakeServer:
    """A SYNTHETIC model server: records which model it serves, with which window per
    slot and how many slots, and when it runs and stops. It reports serving what it was
    given, as llama-server's GET /props does, unless ``confirm_error`` is set."""

    started: ClassVar[list[str]] = []
    stopped: ClassVar[list[str]] = []
    served: ClassVar[list[tuple[str, int, int]]] = []
    confirm_error: ClassVar[str | None] = None

    def __init__(self, model: LocalModel, **kwargs: Any) -> None:
        self.model = model
        self.parallel = int(kwargs.get("parallel", 1))
        self.engine = str(kwargs.get("engine", "llama.cpp"))
        self.base_url = "http://127.0.0.1:1/v1"

    def __enter__(self) -> FakeServer:
        FakeServer.started.append(self.model.name)
        FakeServer.served.append((self.model.name, self.model.n_ctx, self.parallel))
        return self

    def __exit__(self, *exc: object) -> None:
        FakeServer.stopped.append(self.model.name)

    def confirm_serving(self) -> dict[str, Any] | None:
        if self.confirm_error is not None:
            raise ServerStateError(self.confirm_error)
        if self.engine != "llama.cpp":
            return None
        return {
            "source": "GET /props",
            "n_ctx_per_slot": self.model.n_ctx,
            "total_slots": self.parallel,
            "model_path": str(self.model.path),
        }

    def provenance(self) -> dict[str, Any]:
        return {
            "model": self.model.name,
            "parallel_slots": self.parallel,
            "n_ctx_per_slot": self.model.n_ctx,
        }


@pytest.fixture
def no_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Stand-ins for the pinned models, the model server, backend, client, code state,
    and the sandbox preflight (all SYNTHETIC)."""
    FakeServer.started = []
    FakeServer.stopped = []
    FakeServer.served = []
    models = {name: synthetic_model(name) for name in SYNTHETIC_MODELS}
    monkeypatch.setattr(run_study, "RUNS", tmp_path / "state")
    monkeypatch.setattr(run_study, "LOCAL_MODELS", models)
    monkeypatch.setattr(run_study, "LocalServer", FakeServer)
    monkeypatch.setattr(run_study, "LocalOpenAIBackend", lambda *a, **k: object())
    monkeypatch.setattr(run_study, "ModelClient", lambda *a, **k: object())
    monkeypatch.setattr(run_study, "code_state", lambda: {"code": "working tree"})
    monkeypatch.setattr(run_study, "git_sha", lambda: "b" * 40)
    hidden = {"backend": "synthetic", "checkout_hidden": True, "shown_in_checkout": []}
    monkeypatch.setattr(run_study, "preflight", lambda study: hidden)


def test_main_retries_excludes_and_reports_per_model_group(
    tmp_path: Path,
    no_models: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = synthetic_plan(n_runs=3)
    path = plan_file(tmp_path, plan)
    ids = [run.run_id for run in plan.ordered()]
    attempts: list[tuple[str, str, int]] = []

    def one_run(plan: Plan, spec: RunSpec, client: Any, artifacts: Path, *rest: Any) -> None:
        server = rest[1]
        attempts.append((spec.run_id, server.model.name, spec.seed))
        assert server.model.name == plan.arm(spec.config_id).model
        if spec.run_id == ids[1]:
            raise failure("synthetic sandbox error")
        (artifacts / spec.run_id).mkdir(parents=True)
        (artifacts / spec.run_id / "run.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(run_study, "one_run", one_run)
    assert run_study.main(["--plan", str(path)]) == 0
    assert FakeServer.started == list(SYNTHETIC_MODELS)
    assert [a[0] for a in attempts].count(ids[1]) == 3
    assert {seed for run_id, _, seed in attempts if run_id == ids[1]} == {plan.ordered()[1].seed}
    state = tmp_path / "state" / plan.study
    assert run_study.failure_counts(state) == {ids[1]: 3}
    assert (state / "pid").is_file()
    out = capsys.readouterr().out
    assert "5 run(s) banked this session" in out
    assert f"excluded after 3 failed attempts: {ids[1]}" in out
    # A restart attempts nothing and reports the run as excluded.
    attempts.clear()
    assert run_study.main(["--plan", str(path)]) == 0
    assert attempts == []
    assert "0 of 6 runs pending; 1 excluded" in capsys.readouterr().out


def test_main_exits_1_when_the_session_stops(
    tmp_path: Path,
    no_models: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = synthetic_plan(n_runs=6)
    path = plan_file(tmp_path, plan)

    def dead_server(plan: Plan, spec: RunSpec, *rest: Any) -> None:
        raise failure("synthetic: connection refused")

    monkeypatch.setattr(run_study, "one_run", dead_server)
    assert run_study.main(["--plan", str(path)]) == 1
    # The first model group stopped the session; the second model never started.
    assert FakeServer.started == [SYNTHETIC_MODELS[0]]
    assert "STOPPED" in capsys.readouterr().out
    state = tmp_path / "state" / plan.study
    assert sum(run_study.failure_counts(state).values()) == run_study.STOP_AFTER_FAILURES


def test_an_untracked_source_file_counts_as_uncommitted_code(
    git_repo: Path, commit: Callable[[Path, str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # An untracked module under src/ can change what a working-tree run executes, so the
    # run record lists it (G9 reads uncommitted_at_start; review finding real-path-5).
    (git_repo / "src").mkdir()
    (git_repo / "src" / "kept.py").write_text("x = 1\n", encoding="utf-8")
    commit(git_repo, "SYNTHETIC tracked source")
    (git_repo / "src" / "planted.py").write_text("x = 2\n", encoding="utf-8")
    monkeypatch.setattr(run_study, "ROOT", git_repo)
    assert run_study.dirty_files() == ["src/planted.py"]


# The sandbox hides the checkout (review N18, DECISIONS D67) ---------------------------


class SyntheticBox:
    """A SYNTHETIC sandbox that hides the given paths; its one command is the probe."""

    def __init__(
        self, workspace: Path, hidden: list[Path], *, backend: str = "bwrap", seen: bool = False
    ) -> None:
        self.workspace = workspace
        self.backend = backend
        self.hidden = [p.resolve() for p in hidden]
        self.shown = [workspace.resolve()]
        self.seen = seen
        self.commands: list[str] = []

    def hides(self, path: str | Path) -> bool:
        target = Path(path).resolve()
        if any(s == target or s in target.parents for s in self.shown):
            return False
        return any(h == target or h in target.parents for h in self.hidden)

    def shown_within(self, path: str | Path) -> tuple[Path, ...]:
        target = Path(path).resolve()
        return tuple(sorted(s for s in self.shown if target in s.parents))

    def run(self, cmd: str, **kwargs: Any) -> Any:
        self.commands.append(cmd)
        return SimpleNamespace(exit_code=1 if self.seen else 0, stdout="", stderr="")


@pytest.fixture
def checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_checkout: Callable[[Path], Path]
) -> Path:
    """A SYNTHETIC checkout as ROOT, the only checkout the study sandbox must hide."""
    root = make_checkout(tmp_path / "checkout").resolve()
    monkeypatch.setattr(run_study, "ROOT", root)
    monkeypatch.setattr(run_study, "RUNS", root / "runs")
    monkeypatch.setattr(run_study, "project_root", lambda: root)
    return root


def test_the_study_sandbox_hides_the_checkout_and_the_default_paths(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_make_sandbox(workspace: Path, policy: Any, **kwargs: Any) -> Any:
        calls.append({"workspace": workspace, "policy": policy, **kwargs})
        return SyntheticBox(workspace, list(kwargs["hide_paths"]))

    monkeypatch.setattr(run_study, "make_sandbox", fake_make_sandbox)
    work = checkout / "runs" / "work" / "smoke" / "run-1"
    work.mkdir(parents=True)
    policy = run_study.SandboxPolicy()
    box = run_study.study_sandbox(work, policy)
    (call,) = calls
    assert call["workspace"] == work and call["policy"] is policy
    assert call["prefer"] == run_study.BACKENDS == ("bwrap",)
    hidden = set(call["hide_paths"])
    assert checkout in hidden
    assert set(run_study.default_hidden_paths(project=checkout)) <= hidden
    # The workspace under the checkout stays the sandbox's own.
    assert box.hides(checkout) and not box.hides(work)


def test_the_checkout_of_the_imported_package_is_hidden_too(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # For example the main checkout around a worktree that runs the study.
    outer = (tmp_path / "outer").resolve()
    outer.mkdir()
    monkeypatch.setattr(run_study, "project_root", lambda: outer)
    assert run_study.checkouts() == (checkout, outer)
    assert {checkout, outer} <= set(run_study.hidden_paths())


def test_checkout_hiding_records_the_backend_and_what_stays_visible(checkout: Path) -> None:
    toolchain = checkout / "runs" / "toolchains" / "bench-py311"
    work = checkout / "runs" / "work" / "smoke" / "run-1"
    for directory in (toolchain, work):
        directory.mkdir(parents=True)
    box = SyntheticBox(work, [checkout])
    box.shown.append(toolchain)
    record = run_study.checkout_hiding(box)
    assert record == {
        "backend": "bwrap",
        "checkout_hidden": True,
        "shown_in_checkout": ["runs/toolchains/bench-py311", "runs/work/smoke/run-1"],
    }
    # A command inside looked for the checkout's pyproject.toml and did not find it.
    assert box.commands == [f"test ! -e {checkout / 'pyproject.toml'}"]


def test_checkout_hiding_refuses_a_sandbox_that_shows_the_checkout(
    checkout: Path, tmp_path: Path
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(run_study.CheckoutExposedError, match="lets commands reach"):
        run_study.checkout_hiding(SyntheticBox(work, []))
    # A backend that cannot say what it hides (unshare sees the whole host).
    blind = SimpleNamespace(backend="unshare", workspace=work)
    with pytest.raises(run_study.CheckoutExposedError, match="cannot say"):
        run_study.checkout_hiding(blind)
    # The layout says hidden, but a command inside still finds the checkout.
    with pytest.raises(run_study.CheckoutExposedError, match="finds"):
        run_study.checkout_hiding(SyntheticBox(work, [checkout], seen=True))
    # A workspace that is the checkout itself shows all of it.
    with pytest.raises(run_study.CheckoutExposedError, match="lets commands reach"):
        run_study.checkout_hiding(SyntheticBox(checkout, [checkout]))


def test_one_run_builds_hidden_sandboxes_and_checks_them_before_the_run(
    no_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def execute(spec: RunSpec, task: Any, arm: Any, client: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(stop_reason="finished", turns=1, false_success=False)

    monkeypatch.setattr(run_study, "execute_run", execute)
    built: list[tuple[Path, Any]] = []

    def record(work: Path, policy: Any) -> None:
        built.append((work, policy))

    monkeypatch.setattr(run_study, "study_sandbox", record)
    call_one_run(synthetic_plan().runs[0])
    assert seen["sandbox_check"] is run_study.checkout_hiding
    seen["sandbox_factory"](Path("/nonexistent/work"))
    assert built and built[0][0] == Path("/nonexistent/work")


def test_a_refusal_in_a_run_stops_the_session_and_logs_no_attempt(
    no_setup: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def refused(*args: Any, **kwargs: Any) -> Any:
        raise run_study.CheckoutExposedError("SYNTHETIC: the sandbox shows the checkout")

    monkeypatch.setattr(run_study, "execute_run", refused)
    spec = synthetic_plan().runs[0]
    with pytest.raises(run_study.CheckoutExposedError):
        call_one_run(spec)
    with pytest.raises(run_study.CheckoutExposedError):
        run_study.run_session([spec], lambda s: call_one_run(s), tmp_path)
    assert logged(tmp_path) == []


def test_main_refuses_to_start_when_the_sandbox_shows_the_checkout(
    tmp_path: Path,
    no_models: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def exposed(study: str) -> dict[str, Any]:
        raise run_study.CheckoutExposedError("SYNTHETIC: bwrap lets commands reach /x")

    monkeypatch.setattr(run_study, "preflight", exposed)
    attempts: list[str] = []
    monkeypatch.setattr(run_study, "one_run", lambda plan, spec, *rest: attempts.append(spec))
    plan = synthetic_plan(n_runs=1)
    assert run_study.main(["--plan", str(plan_file(tmp_path, plan))]) == 2
    assert FakeServer.started == [] and attempts == []
    assert "REFUSED" in capsys.readouterr().err


def test_main_stops_with_status_2_when_a_run_refuses_its_sandbox(
    tmp_path: Path,
    no_models: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refusing(plan: Plan, spec: RunSpec, *rest: Any) -> None:
        raise run_study.CheckoutExposedError("SYNTHETIC: the sandbox shows the checkout")

    monkeypatch.setattr(run_study, "one_run", refusing)
    plan = synthetic_plan(n_runs=2)
    assert run_study.main(["--plan", str(plan_file(tmp_path, plan))]) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert run_study.failure_counts(tmp_path / "state" / plan.study) == {}


def test_preflight_checks_a_sandbox_beside_the_run_workspaces(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_study, "toolchain", lambda: SimpleNamespace(installed=()))
    monkeypatch.setattr(run_study, "with_toolchain", lambda policy, chain: policy)
    workspaces: list[Path] = []

    def sandbox(work: Path, policy: Any) -> SyntheticBox:
        workspaces.append(work)
        assert work.is_dir()
        return SyntheticBox(work, [checkout])

    monkeypatch.setattr(run_study, "study_sandbox", sandbox)
    record = run_study.preflight("synthetic-study")
    assert record["checkout_hidden"] is True and record["backend"] == "bwrap"
    (work,) = workspaces
    assert work.parent == checkout / "runs" / "work" / "synthetic-study"
    assert not work.exists()
    monkeypatch.setattr(run_study, "study_sandbox", lambda work, policy: SyntheticBox(work, []))
    with pytest.raises(run_study.CheckoutExposedError):
        run_study.preflight("synthetic-study")
    assert list((checkout / "runs" / "work" / "synthetic-study").iterdir()) == []


@needs_bwrap
def test_a_real_study_sandbox_cannot_list_the_checkouts_bench(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch, make_checkout: Callable[[Path], Path]
) -> None:
    # The checkout lies outside /tmp, and this test process imports receipts from
    # another checkout, so only the explicit hide in run_study can keep it out.
    root = make_checkout(outside_tmp / "checkout")
    monkeypatch.setattr(run_study, "ROOT", root)
    toolchain = root / "runs" / "toolchains" / "synthetic"
    (toolchain / "bin").mkdir(parents=True)
    (toolchain / "bin" / "tool").write_text("SYNTHETIC tool\n", encoding="utf-8")
    work = root / "runs" / "work" / "smoke" / "run-1"
    work.mkdir(parents=True)
    policy = run_study.SandboxPolicy(readonly_paths=(toolchain,))
    box = run_study.study_sandbox(work, policy)
    listing = box.run(f"ls -A {root}/bench")
    assert listing.exit_code != 0 and listing.stdout == ""
    assert box.run(f"cat {root}/private/notes.txt").stdout == ""
    assert box.run(f"cat {toolchain}/bin/tool").stdout == "SYNTHETIC tool\n"
    assert box.run("echo made > made.txt && cat made.txt").stdout == "made\n"
    assert (work / "made.txt").read_text(encoding="utf-8") == "made\n"
    record = run_study.checkout_hiding(box)
    assert record["backend"] == "bwrap" and record["checkout_hidden"] is True
    assert record["shown_in_checkout"] == ["runs/toolchains/synthetic", "runs/work/smoke/run-1"]


# The code snapshot is the src/ tree of the commit it names --------------------------------


def snapshot_of(repo: Path, sha: str, dest: Path) -> Path:
    """Extract ``git archive <sha> src`` under ``dest/<sha>`` as tools/snapshot_code.sh does."""
    snapshot = dest / sha
    snapshot.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", sha, "src"], capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(snapshot, filter="tar")
    (snapshot / "SNAPSHOT_OF").write_text(sha + "\n", encoding="utf-8")
    return snapshot


@pytest.fixture
def committed(
    git_repo: Path, commit: Callable[[Path, str], str], monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, str]:
    """A SYNTHETIC repository as ROOT with a committed src/ tree, and its commit."""
    package = git_repo / "src" / "receipts"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""SYNTHETIC package."""\n', encoding="utf-8")
    (package / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    script = package / "run.sh"
    script.write_text("#!/bin/sh\necho synthetic\n", encoding="utf-8")
    script.chmod(0o755)
    (git_repo / "README.md").write_text("SYNTHETIC\n", encoding="utf-8")
    monkeypatch.setattr(run_study, "ROOT", git_repo)
    return git_repo, commit(git_repo, "SYNTHETIC source")


def test_a_snapshot_of_its_commit_has_no_differences(
    committed: tuple[Path, str], tmp_path: Path
) -> None:
    repo, sha = committed
    snapshot = snapshot_of(repo, sha, tmp_path / "code")
    # Importing the snapshot writes bytecode caches; they are not part of the tree.
    cache = snapshot / "src" / "receipts" / "__pycache__"
    cache.mkdir()
    (cache / "mod.cpython-311.pyc").write_bytes(b"SYNTHETIC bytecode")
    assert run_study.snapshot_differences(snapshot, sha) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("edit", "src/receipts/mod.py differs from the commit"),
        ("extra", "src/receipts/planted.py is not in commit"),
        ("missing", "src/receipts/mod.py is missing"),
        ("mode", "src/receipts/run.sh has a different executable bit"),
        ("not-pyc", "src/receipts/__pycache__/note.txt is not in commit"),
    ],
)
def test_a_snapshot_that_differs_from_its_commit_is_listed(
    committed: tuple[Path, str], tmp_path: Path, change: str, expected: str
) -> None:
    repo, sha = committed
    snapshot = snapshot_of(repo, sha, tmp_path / "code")
    package = snapshot / "src" / "receipts"
    if change == "edit":
        (package / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    elif change == "extra":
        (package / "planted.py").write_text("x = 1\n", encoding="utf-8")
    elif change == "missing":
        (package / "mod.py").unlink()
    elif change == "mode":
        (package / "run.sh").chmod(0o644)
    else:
        (package / "__pycache__").mkdir()
        (package / "__pycache__" / "note.txt").write_text("SYNTHETIC\n", encoding="utf-8")
    differences = run_study.snapshot_differences(snapshot, sha)
    assert any(expected in line for line in differences), differences


def test_a_snapshot_naming_no_commit_of_this_repository_is_refused(
    committed: tuple[Path, str], tmp_path: Path
) -> None:
    repo, sha = committed
    snapshot = snapshot_of(repo, sha, tmp_path / "code")
    assert "not a full commit id" in run_study.snapshot_differences(snapshot, sha[:12])[0]
    unknown = "f" * 40
    assert f"commit {unknown} is not in" in run_study.snapshot_differences(snapshot, unknown)[0]


def test_code_state_verifies_the_snapshot_it_imports(
    committed: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, sha = committed
    snapshot = snapshot_of(repo, sha, tmp_path / "code")
    monkeypatch.setattr(receipts, "__file__", str(snapshot / "src" / "receipts" / "__init__.py"))
    assert run_study.code_state() == {
        "code": "snapshot",
        "snapshot_of": sha,
        "snapshot_verified": True,
    }
    (snapshot / "src" / "receipts" / "mod.py").write_text("VALUE = 3\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=f"not src/ of commit {sha}"):
        run_study.code_state()
    # A self-declared marker naming another commit is refused the same way.
    (snapshot / "src" / "receipts" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (snapshot / "SNAPSHOT_OF").write_text("f" * 40 + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not in"):
        run_study.code_state()


# A run a plan amendment added, and the server it needs (DECISIONS D71) -------------------

SMOKE_TASKS = ("py-one", "py-two", "py-three")
REPLACED = "smoke-py-two-arm-a"
ADDED = "smoke-py-two-arm-a-ctx32k"


def amended_plan(pinned: int = PINNED_N_CTX) -> Plan:
    """A SYNTHETIC smoke plan of one arm whose second run an amendment replaced with a run
    that needs at least 32768 tokens per slot on one slot (raising the pinned window
    ``pinned``)."""
    arm = local_arm("arm-a", SYNTHETIC_MODELS[0], "fam-a")
    base = smoke_plan("smoke", SMOKE_TASKS, arm)
    return amend_plan(
        base,
        REPLACED,
        ServerRequirement(
            min_n_ctx_per_slot=32768, max_parallel_slots=1, pinned_n_ctx_per_slot=pinned
        ),
        decision="D71",
        reason="SYNTHETIC: the request outgrew the window",
        date="2026-11-12",
    )


def bank(artifacts: Path, *run_ids: str) -> None:
    """Mark SYNTHETIC runs as banked (a run.json in their directory)."""
    for run_id in run_ids:
        (artifacts / run_id).mkdir(parents=True)
        (artifacts / run_id / "run.json").write_text("{}", encoding="utf-8")


def test_a_replaced_run_is_excluded_whatever_the_failure_log_holds(tmp_path: Path) -> None:
    plan = amended_plan()
    artifacts = tmp_path / "runs"
    bank(artifacts, "smoke-py-one-arm-a", "smoke-py-three-arm-a")
    # An empty or reset failure log does not bring the excluded run back.
    for counts in ({}, {REPLACED: 3}, {REPLACED: 1}):
        assert run_study.pending(plan, artifacts, counts) == [ADDED]
        assert run_study.excluded(plan, artifacts, counts) == [REPLACED]


def test_the_runs_a_server_may_serve(no_setup: None) -> None:
    plan = amended_plan()
    specs = {run.run_id: run for run in plan.runs}
    refusal = run_study.window_refusal
    # The added run needs at least 32768 tokens per slot on one slot, from llama.cpp.
    for n_ctx, slots in ((None, 1), (PINNED_N_CTX, 1), (32767, 1), (32768, 2), (32768, 0)):
        why = refusal(plan, specs[ADDED], n_ctx, slots)
        assert why is not None and "D71" in why, (n_ctx, slots)
    assert refusal(plan, specs[ADDED], 32768, 1) is None
    assert refusal(plan, specs[ADDED], 65536, 1) is None
    why = refusal(plan, specs[ADDED], 32768, 1, engine="llama-cpp-python")
    assert why is not None and "llama.cpp" in why
    # A plan amendment made for another pinned window than the model's is refused too.
    other = amended_plan(pinned=8192)
    why = refusal(other, {r.run_id: r for r in other.runs}[ADDED], 32768, 1)
    assert why is not None and "pinned window" in why
    # Every other run is served only with the pinned window, so a raised window serves
    # the run that needs it and no other.
    other = specs["smoke-py-one-arm-a"]
    assert refusal(plan, other, None, 4) is None
    assert refusal(plan, other, PINNED_N_CTX, 4) is None
    why = refusal(plan, other, 32768, 1)
    assert why is not None and "no server requirement" in why


def test_dry_run_shows_the_amendment_and_the_server_it_needs(
    tmp_path: Path, no_models: None, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = amended_plan()
    path = plan_file(tmp_path, plan)
    bank(path.parent / "runs", "smoke-py-one-arm-a", "smoke-py-three-arm-a")
    write_log(
        tmp_path / "state" / "smoke",
        [{"run_id": REPLACED, "attempt": n, "time": "t", "error": "E"} for n in (1, 2, 3)],
    )
    assert run_study.main(["--plan", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "1 of 4 runs pending; 1 excluded" in out
    assert ADDED in out.splitlines()
    assert f"in place of {REPLACED}" in out and "at least 32768 tokens per slot" in out
    assert "refused on this session's server" in out
    assert f"excluded: {REPLACED} (3 failed attempts; replaced by {ADDED}, D71)" in out
    assert run_study.main(["--plan", str(path), "--dry-run", "--n-ctx", "32768"]) == 0
    assert "refused on this session's server" not in capsys.readouterr().out


def added_only(tmp_path: Path) -> Path:
    """The SYNTHETIC amended plan with every run banked or excluded but the added one."""
    path = plan_file(tmp_path, amended_plan())
    bank(path.parent / "runs", "smoke-py-one-arm-a", "smoke-py-three-arm-a")
    return path


def record_attempts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch one_run to bank each SYNTHETIC run it is given and return their ids."""
    attempts: list[str] = []

    def one_run(plan: Plan, spec: RunSpec, client: Any, artifacts: Path, *rest: Any) -> None:
        attempts.append(spec.run_id)
        bank(artifacts, spec.run_id)

    monkeypatch.setattr(run_study, "one_run", one_run)
    return attempts


@pytest.mark.parametrize(
    "options",
    [
        pytest.param([], id="pinned-window"),
        pytest.param(["--n-ctx", "16384"], id="pinned-window-named"),
        pytest.param(["--n-ctx", "24576"], id="smaller-window"),
        pytest.param(["--n-ctx", "32768", "--parallel", "2"], id="two-slots"),
    ],
)
def test_main_refuses_the_added_run_on_a_server_it_does_not_fit(
    tmp_path: Path,
    no_models: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    options: list[str],
) -> None:
    path = added_only(tmp_path)
    attempts = record_attempts(monkeypatch)
    assert run_study.main(["--plan", str(path), *options]) == 2
    err = capsys.readouterr().err
    assert f"REFUSED: {ADDED}:" in err and "D71" in err
    # No server started, nothing was attempted or logged, and no session began.
    assert FakeServer.started == [] and attempts == []
    state = tmp_path / "state" / "smoke"
    assert run_study.failure_counts(state) == {} and not (state / "pid").exists()


def test_main_runs_the_added_run_on_the_server_it_needs(
    tmp_path: Path,
    no_models: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = added_only(tmp_path)
    attempts = record_attempts(monkeypatch)
    argv = ["--plan", str(path), "--n-ctx", "32768", "--parallel", "1"]
    assert run_study.main(argv) == 0
    assert attempts == [ADDED]
    assert FakeServer.served == [(SYNTHETIC_MODELS[0], 32768, 1)]
    assert "1 run(s) banked this session" in capsys.readouterr().out


def test_a_raised_window_serves_only_the_runs_that_need_it(
    tmp_path: Path,
    no_models: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = plan_file(tmp_path, amended_plan())  # two plain runs pending beside the added one
    attempts = record_attempts(monkeypatch)
    assert run_study.main(["--plan", str(path), "--n-ctx", "32768"]) == 0
    assert attempts == [ADDED]
    err = capsys.readouterr().err
    assert "REFUSED: smoke-py-one-arm-a:" in err and "no server requirement" in err
    # A session with the pinned window then makes the plain runs, never the added one again.
    attempts.clear()
    assert run_study.main(["--plan", str(path)]) == 0
    assert attempts == ["smoke-py-one-arm-a", "smoke-py-three-arm-a"]
    assert FakeServer.served[-1] == (SYNTHETIC_MODELS[0], PINNED_N_CTX, 1)
    # With nothing it may serve, a session with a raised window refuses to start.
    plain = plan_file(tmp_path / "plain", synthetic_plan(n_runs=1, study="smoke"))
    assert run_study.main(["--plan", str(plain), "--n-ctx", "32768"]) == 2


def test_one_run_refuses_a_server_that_does_not_serve_the_run(
    no_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    def execute(spec: RunSpec, task: Any, arm: Any, client: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return SimpleNamespace(stop_reason="finished", turns=1, false_success=False)

    monkeypatch.setattr(run_study, "execute_run", execute)
    plan = amended_plan()
    specs = {run.run_id: run for run in plan.runs}
    with pytest.raises(run_study.ServerMismatchError, match="at least 32768"):
        call_one_run(specs[ADDED], plan)
    with pytest.raises(run_study.ServerMismatchError, match="no server requirement"):
        call_one_run(specs["smoke-py-one-arm-a"], plan, n_ctx=32768)
    with pytest.raises(run_study.ServerMismatchError, match=r"llama\.cpp"):
        call_one_run(specs[ADDED], plan, n_ctx=32768, engine="llama-cpp-python")
    # Review F3 (false rejection): the added run's replies never come from the shared
    # cache, which holds the replies the excluded run got on the server with the pinned
    # window.
    shared = run_study.RUNS / "cache"
    with pytest.raises(run_study.ServerMismatchError, match="response cache"):
        call_one_run(specs[ADDED], plan, n_ctx=32768, cache=shared)
    assert seen == []
    # On the server it needs, the run records its amendment, the raised window, what the
    # live server reported, and its own response cache.
    call_one_run(specs[ADDED], plan, n_ctx=32768)
    (kwargs,) = seen
    extra = kwargs["extra_provenance"]
    assert extra["plan_amendment"] == plan.amendments[0].to_json()
    assert extra["response_cache"] == amendment_cache("smoke", ADDED)
    server = kwargs["server_provenance"]
    assert server["n_ctx_per_slot"] == 32768 and server["n_ctx_per_slot_is_default"] is False
    assert server["reported"]["n_ctx_per_slot"] == 32768
    assert server["reported"]["total_slots"] == 1
    call_one_run(specs["smoke-py-one-arm-a"], plan)
    assert "plan_amendment" not in seen[-1]["extra_provenance"]
    assert "response_cache" not in seen[-1]["extra_provenance"]


def test_an_added_run_has_its_own_response_cache_and_other_runs_share_one() -> None:
    plan = amended_plan()
    specs = {run.run_id: run for run in plan.runs}
    assert (
        run_study.response_cache(plan, specs[ADDED]) == run_study.RUNS / "smoke" / "cache" / ADDED
    )
    assert run_study.ROOT / amendment_cache("smoke", ADDED) == run_study.response_cache(
        plan, specs[ADDED]
    )
    assert run_study.response_cache(plan, specs["smoke-py-one-arm-a"]) == run_study.RUNS / "cache"


def test_run_model_serves_an_added_run_from_its_own_cache(
    tmp_path: Path, no_models: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    caches: list[tuple[str, Path]] = []

    class RecordingClient:
        def __init__(self, root: Path, backends: Any, cache_dir: Path) -> None:
            self.cache_dir = cache_dir

    def one_run(plan: Plan, spec: RunSpec, client: Any, *rest: Any) -> None:
        caches.append((spec.run_id, client.cache_dir))

    def each(runs: Any, attempt: Any, state: Path, **kwargs: Any) -> Any:
        for spec in runs:
            attempt(spec)
        return run_study.SessionResult()

    monkeypatch.setattr(run_study, "ModelClient", RecordingClient)
    monkeypatch.setattr(run_study, "one_run", one_run)
    monkeypatch.setattr(run_study, "run_session", each)
    plan = amended_plan()
    specs = {run.run_id: run for run in plan.runs}
    args = SimpleNamespace(
        port=1, threads=1, engine="llama.cpp", parallel=1, request_timeout=1.0, n_ctx=32768
    )
    runs = [specs[ADDED], specs["smoke-py-one-arm-a"]]
    run_study.run_model(plan, SYNTHETIC_MODELS[0], runs, args, tmp_path, tmp_path, "a" * 40, {})
    state = tmp_path / "state"
    assert caches == [
        (ADDED, state / "smoke" / "cache" / ADDED),
        ("smoke-py-one-arm-a", state / "cache"),
    ]


def test_main_refuses_a_plan_whose_amendment_raises_another_pinned_window(
    tmp_path: Path, no_models: None, capsys: pytest.CaptureFixture[str]
) -> None:
    path = plan_file(tmp_path, amended_plan(pinned=8192))
    assert run_study.main(["--plan", str(path), "--dry-run"]) == 2
    assert "pinned window of 8192" in capsys.readouterr().err


def test_a_server_mismatch_stops_the_session_and_logs_no_attempt(
    tmp_path: Path,
    no_models: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def mismatch(plan: Plan, spec: RunSpec, *rest: Any) -> None:
        raise run_study.ServerMismatchError(f"SYNTHETIC: {spec.run_id} needs another server")

    monkeypatch.setattr(run_study, "one_run", mismatch)
    path = added_only(tmp_path)
    assert run_study.main(["--plan", str(path), "--n-ctx", "32768"]) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert run_study.failure_counts(tmp_path / "state" / "smoke") == {}


def test_main_refuses_a_plan_whose_amendment_does_not_hold(
    tmp_path: Path, no_models: None, capsys: pytest.CaptureFixture[str]
) -> None:
    path = plan_file(tmp_path, amended_plan())
    data = json.loads(path.read_text(encoding="utf-8"))
    data["runs"][-1]["seed"] = 7  # the added run is no longer the replaced run's spec
    path.write_text(json.dumps(data), encoding="utf-8")
    assert run_study.main(["--plan", str(path), "--dry-run"]) == 2
    assert "not the planned run" in capsys.readouterr().err


def test_a_server_that_cannot_start_as_its_own_is_a_refusal(
    tmp_path: Path,
    no_models: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Review F3: when another server already answers on the port, LocalServer.start
    # refuses, and the session stops with no attempt logged.
    def occupied(self: FakeServer) -> FakeServer:
        raise ServerStateError("SYNTHETIC: something already answers on port 1")

    monkeypatch.setattr(FakeServer, "__enter__", occupied)
    attempts = record_attempts(monkeypatch)
    path = plan_file(tmp_path, synthetic_plan(n_runs=1))
    assert run_study.main(["--plan", str(path)]) == 2
    assert "REFUSED: SYNTHETIC: something already answers on port 1" in capsys.readouterr().err
    assert attempts == []
    assert run_study.failure_counts(tmp_path / "state" / "synthetic-study") == {}


def test_an_added_run_needs_a_server_that_reports_what_it_serves(
    no_setup: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_study, "execute_run", raise_in_execute_run)
    monkeypatch.setattr(FakeServer, "confirm_serving", lambda self: None)
    plan = amended_plan()
    specs = {run.run_id: run for run in plan.runs}
    with pytest.raises(run_study.ServerMismatchError, match="does not report"):
        call_one_run(specs[ADDED], plan, n_ctx=32768)
