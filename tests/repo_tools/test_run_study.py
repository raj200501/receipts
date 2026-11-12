"""tools/run_study.py: the three-attempt retry rule for infrastructure failures.

prereg/0001-e1-main-study.md section 10: a failed attempt is logged with its attempt
number, the run is retried with the same seed up to two times, the attempts are counted
from ``runs/<study>/failures.jsonl`` so the cap holds across restarts, and a run with
three logged failures is excluded. Every plan, run, failure, and server here is a
SYNTHETIC test fixture: no model is called, no sandbox starts, and nothing is written
outside tmp_path.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

import run_study
from receipts.study.plan import Plan, local_arm, write_plan
from receipts.study.spec import RunSpec

SYNTHETIC_MODELS = ("synthetic-model-a", "synthetic-model-b")


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
    """Replace task loading, the toolchain, and the tree hash with SYNTHETIC stand-ins."""
    task = SimpleNamespace(command_timeout_s=60.0, memory_mb=512)
    monkeypatch.setattr(run_study, "load_run_task", lambda path: task)
    monkeypatch.setattr(run_study, "toolchain", lambda: SimpleNamespace(installed=("pkg==1",)))
    monkeypatch.setattr(run_study, "with_toolchain", lambda policy, chain: policy)
    monkeypatch.setattr(run_study, "tree_sha256", lambda path: "f" * 64)


def call_one_run(spec: RunSpec) -> Any:
    """one_run with stand-in client and server; each test patches execute_run."""
    server = SimpleNamespace(provenance=lambda: {"model": "synthetic"})
    code = {"code": "working tree"}
    return run_study.one_run(
        synthetic_plan(), spec, object(), Path("/nonexistent"), "a" * 40, server, code
    )


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
    """A SYNTHETIC model server: records which model it serves and when it runs."""

    started: ClassVar[list[str]] = []

    def __init__(self, model: Any, **kwargs: Any) -> None:
        self.model = model
        self.base_url = "http://127.0.0.1:1/v1"

    def __enter__(self) -> FakeServer:
        FakeServer.started.append(self.model.name)
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def provenance(self) -> dict[str, Any]:
        return {"model": self.model.name}


@pytest.fixture
def no_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Stand-ins for the model server, backend, client, and code state (all SYNTHETIC)."""
    FakeServer.started = []
    models = {name: SimpleNamespace(name=name) for name in SYNTHETIC_MODELS}
    monkeypatch.setattr(run_study, "RUNS", tmp_path / "state")
    monkeypatch.setattr(run_study, "LOCAL_MODELS", models)
    monkeypatch.setattr(run_study, "LocalServer", FakeServer)
    monkeypatch.setattr(run_study, "LocalOpenAIBackend", lambda *a, **k: object())
    monkeypatch.setattr(run_study, "ModelClient", lambda *a, **k: object())
    monkeypatch.setattr(run_study, "code_state", lambda: {"code": "working tree"})
    monkeypatch.setattr(run_study, "git_sha", lambda: "b" * 40)


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
