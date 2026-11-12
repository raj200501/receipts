"""Gate G6 of tools/ship_check.py on a synthetic benchmark (H17, with the G5 part in H20).

Every task, plan, plan amendment, reference validation, banked smoke run, ledger,
transcript, server record, failure log, and smoke-run row here is SYNTHETIC, made up
only to exercise ``ship_check.g6`` in a scratch git repository under tmp_path. Smoke rows
are marked ``synthetic: false`` only so the gate treats them as real runs; nothing here
is a model result or a real-world result, and no model is called.

The benchmark is committed as the real one is: the plan and the runs first, then (with
an amendment) the amended plan on its own, then the run it added (DECISIONS D71).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import ship_check
from receipts.bench.hashing import tree_sha256
from receipts.client.server import LocalModel, LocalServer
from receipts.ledger.events import GENESIS, Event, canonical_json, sha256_text
from receipts.study import aggregate
from receipts.study.plan import (
    Plan,
    ServerRequirement,
    amend_plan,
    amendment_cache,
    load_plan,
    local_arm,
    smoke_plan,
    write_plan,
)

GateError = ship_check.GateError
MODEL = "qwen2.5-coder-7b-instruct-q4km"
OTHER_MODEL = "granite-3.3-8b-instruct-q4km"
AGENT = f"minimal-agent/{MODEL}"
CONFIG = "ma-qwen7b"
PROV = {
    "git_sha": "0" * 40,
    "command": "SYNTHETIC test fixture",
    "created": "2026-11-04T00:00:00+00:00",
}
N_TASKS = 30
RUNS = "artifacts/studies/smoke/runs"
PLAN = "artifacts/studies/smoke/plan.json"
SMOKE = "artifacts/bench/smoke_runs.json"
FAILURES = "artifacts/studies/smoke/failures.jsonl"
PINNED = 16384
MODEL_PATH = Path("/nonexistent/SYNTHETIC.gguf")
EXCLUDED = f"smoke-py-synthetic-07-{CONFIG}"
ADDED = f"{EXCLUDED}-ctx32k"
#: The SYNTHETIC agent configuration every run of the arm records (as the runner does).
AGENT_CONFIG = {"backend": "local", "model": MODEL, "max_turns": 16, "purpose": "SYNTHETIC"}
Tamper = Callable[[Path], None]
Edit = Callable[[dict[str, Any]], None]


def put(root: Path, rel: str, data: Any) -> None:
    """Write text, or JSON, creating parent directories."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2) + "\n", "utf-8")


def write_ledger(path: Path, events: Sequence[tuple[str, Mapping[str, Any]]]) -> None:
    """A hash-chained ledger written with receipts.ledger's own event hashing."""
    prev, lines = GENESIS, []
    for seq, (kind, data) in enumerate(events):
        ts = 1_700_000_000.0 + seq
        event = Event(
            seq, ts, kind, dict(data), prev, Event.compute_hash(seq, ts, kind, data, prev)
        )
        lines.append(event.to_json())
        prev = event.hash
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def model_server(n_ctx: int = PINNED, slots: int = 4) -> dict[str, Any]:
    """The SYNTHETIC model server record tools/run_study.py writes for a llama.cpp server
    with ``n_ctx`` tokens per slot on ``slots`` slots, with what the live server reported
    serving (nothing is served here)."""
    model = LocalModel(MODEL, "qwen", MODEL_PATH, "0" * 64, "SYNTHETIC", n_ctx)
    record = dict(LocalServer(model, engine="llama.cpp", parallel=slots).provenance())
    record["n_ctx_per_slot_default"] = PINNED
    record["n_ctx_per_slot_is_default"] = n_ctx == PINNED
    record["reported"] = {
        "source": "GET /props",
        "n_ctx_per_slot": n_ctx,
        "total_slots": slots,
        "model_path": str(MODEL_PATH),
    }
    return record


def base_plan() -> Plan:
    """The SYNTHETIC smoke plan: one run per task."""
    tasks = [f"py-synthetic-{i:02d}" for i in range(N_TASKS)]
    return smoke_plan("smoke", tasks, local_arm(CONFIG, MODEL, "qwen"))


def amended(plan: Plan) -> Plan:
    """``plan`` with task 07's run replaced by one that needs 32768 tokens per slot on one
    slot (DECISIONS D71)."""
    server = ServerRequirement(
        min_n_ctx_per_slot=32768, max_parallel_slots=1, pinned_n_ctx_per_slot=PINNED
    )
    reason = "SYNTHETIC: the final-report request outgrew the window"
    return amend_plan(plan, EXCLUDED, server, decision="D71", reason=reason, date="2026-11-12")


def bank(
    root: Path, plan: Plan, run_id: str, git_sha: str = "a" * 40, window: int = PINNED
) -> None:
    """Bank one SYNTHETIC smoke run as the runner banks a planned run: run.json, a ledger
    from run_start to run_end with a failed hidden check, and a transcript. A planned
    run is served ``window`` tokens per slot on four slots."""
    spec = next(run for run in plan.runs if run.run_id == run_id)
    prov: dict[str, Any] = {
        "git_sha": git_sha,
        "run_spec": {**dataclasses.asdict(spec), "conditions": dict(spec.conditions)},
        "agent_config": dict(AGENT_CONFIG),
        "agent_config_sha256": sha256_text(canonical_json(AGENT_CONFIG)),
        "model_server": model_server(window, 4),
    }
    amendment = plan.amendment(run_id)
    if amendment is not None:
        # As tools/run_study.py records a run made from a verified snapshot of its commit
        # in a sandbox that hid the checkout (DECISIONS D67).
        prov.update(
            plan_amendment=amendment.to_json(),
            model_server=model_server(32768, 1),
            response_cache=amendment_cache("smoke", run_id),
            code="snapshot",
            snapshot_of=git_sha,
            snapshot_verified=True,
            sandbox={"backend": "bwrap", "checkout_hidden": True, "shown_in_checkout": []},
        )
    report = "SYNTHETIC report"
    record = {
        "run_id": run_id,
        "task_id": spec.task_id,
        "config_id": spec.config_id,
        "model": MODEL,
        "stop_reason": "finished",
        "turns": 1,
        "report": report,
        "ground_truth_success": False,
        "provenance": prov,
    }
    put(root, f"{RUNS}/{run_id}/run.json", record)
    start = {"run_id": run_id, "task_id": spec.task_id, "agent": "minimal-agent", "model": MODEL}
    check = {"checks": [{"name": "test_hidden", "passed": False}], "total": 1, "failed": 1}
    end = {"final_report": report, "turns": 1, "stop_reason": "finished", "source": "harness"}
    events = [("run_start", start), ("hidden_check", check), ("run_end", end)]
    write_ledger(root / RUNS / run_id / "ledger.jsonl", events)
    messages = [
        {"role": "user", "content": "SYNTHETIC task"},
        {"role": "assistant", "content": "{}"},
    ]
    put(root, f"{RUNS}/{run_id}/transcript.json", {"messages": messages})


def git(root: Path, *args: str) -> str:
    """Run git in the SYNTHETIC repository."""
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def commit_all(root: Path, message: str) -> str:
    """Commit everything in the SYNTHETIC repository; return the commit."""
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


def log_failures(root: Path, run_id: str = EXCLUDED, attempts: int = 3) -> None:
    """The SYNTHETIC banked failure log: ``attempts`` failed attempts of ``run_id``."""
    entries = [
        {"run_id": run_id, "attempt": n, "started": "s", "time": "t", "error": "SYNTHETIC"}
        for n in range(1, attempts + 1)
    ]
    put(root, FAILURES, "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries))


def bank_rows(root: Path, edit: Edit | None = None) -> None:
    """Write smoke_runs.json as tools/bank_study.py does, from the run directories (with
    the banked failure log's summary), then let ``edit`` change it."""
    records = aggregate.load_records(root / RUNS)
    plan = root / PLAN
    plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest() if plan.is_file() else ""
    smoke = aggregate.smoke_runs_artifact(records, {**PROV, "plan_sha256": plan_sha})
    log = root / FAILURES
    smoke["failures"] = (
        {
            "source": "runs/smoke/failures.jsonl",
            "banked": FAILURES,
            "sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            "entries": len(log.read_text(encoding="utf-8").splitlines()),
            "added": 0,
        }
        if log.is_file()
        else None
    )
    if edit is not None:
        edit(smoke)
    put(root, SMOKE, smoke)


def benchmark(
    root: Path,
    tamper: Tamper | None = None,
    *,
    amend: bool = False,
    target: str | None = None,
    edit_rows: Edit | None = None,
    attempts: int = 3,
    window: int = PINNED,
) -> ship_check.Context:
    """Thirty SYNTHETIC tasks with validated references, their smoke plan, and one banked
    smoke run each (served ``window`` tokens per slot), committed in a git repository.
    With ``amend``, task 07's run was excluded after ``attempts`` logged failures (no
    failure log for 0), the plan amendment is committed on its own, and then the run it
    added is banked, made from the amendment commit. ``tamper`` changes the run
    ``target`` (task 07's banked run by default) before the last commit, and
    smoke_runs.json is then banked from the run directories as they are, so every check
    behind the rows is exercised; ``edit_rows`` changes the rows after that."""
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    plan = base_plan()
    write_plan(root / PLAN, plan)
    validated = {}
    for spec in plan.runs:
        tid = spec.task_id
        task = f"bench/tasks/{tid}"
        put(root, f"{task}/task.toml", f'id = "{tid}"\nlanguage = "python"\n')
        put(root, f"{task}/hidden/test_hidden.py", "def test_ok():\n    assert True\n")
        put(root, f"{task}/reference/fix.py", "VALUE = 1\n")
        put(root, f"{task}/manifest.json", {"manipulations": {"M1": "synthetic overlay"}})
        validated[tid] = {"tree_sha256": tree_sha256(root / task), "hidden_passed": True}
        if not (amend and spec.run_id == EXCLUDED):
            bank(root, plan, spec.run_id, window=window)
    put(root, "artifacts/bench/reference_validation.json", {"tasks": validated, "provenance": PROV})
    if amend:
        if attempts:  # the runner excluded task 07's run after three failed attempts
            log_failures(root, attempts=attempts)
        bank_rows(root)
        commit_all(root, "SYNTHETIC benchmark and smoke runs")
        plan = amended(plan)
        write_plan(root / PLAN, plan)
        amendment_commit = commit_all(root, "SYNTHETIC plan amendment (D71)")
        bank(root, plan, ADDED, git_sha=amendment_commit)
    if tamper is not None:
        tamper(root / RUNS / (target or (ADDED if amend else EXCLUDED)))
    bank_rows(root, edit_rows)
    commit_all(root, "SYNTHETIC smoke runs banked")
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha="0" * 40)


def repo_of(run: Path) -> Path:
    """The SYNTHETIC repository a banked run directory lies in."""
    return run.parents[4]


def test_real_smoke_runs_pass(tmp_path: Path) -> None:
    evidence = ship_check.g6(benchmark(tmp_path / "repo"))
    assert "smoke runs for all" in evidence and "plan amendment" not in evidence


def test_a_genuine_run_of_a_plan_amendment_passes(tmp_path: Path) -> None:
    evidence = ship_check.g6(benchmark(tmp_path / "repo", amend=True))
    assert "smoke runs for all" in evidence
    assert "1 from a plan amendment, on the server it needs" in evidence


# The rows of smoke_runs.json and the runs behind them -------------------------------------


@pytest.mark.parametrize(
    "agent",
    [
        pytest.param("minimal-agent/mock", id="mock-model"),
        pytest.param(None, id="null"),
        pytest.param(" mock ", id="padded"),
        pytest.param("Mock-Agent", id="mixed-case"),
        pytest.param("scripted", id="scripted"),
        pytest.param("minimal-agent/replay-fixture", id="replay"),
        pytest.param(42, id="not-a-string"),
    ],
)
def test_rows_that_do_not_name_the_agent_of_their_run_fail(tmp_path: Path, agent: object) -> None:
    # Old code: only five exact lowercase words were refused, and null became "none".
    # Now a row's agent must be the one banking derives from its run.json.
    def relabel(smoke: dict[str, Any]) -> None:
        for row in smoke["runs"]:
            row["agent"] = agent

    with pytest.raises(GateError, match="one row per banked smoke run"):
        ship_check.g6(benchmark(tmp_path / "repo", edit_rows=relabel))


def drop_row(smoke: dict[str, Any]) -> None:
    """A banked run without a row."""
    smoke["runs"] = [row for row in smoke["runs"] if row["run_id"] != EXCLUDED]


def duplicate_row(smoke: dict[str, Any]) -> None:
    """A row counted twice (review F5)."""
    smoke["runs"].append(dict(smoke["runs"][0]))


def unbanked_row(smoke: dict[str, Any]) -> None:
    """A row marked synthetic for a run that is not banked (review F5)."""
    smoke["runs"].append({**smoke["runs"][0], "run_id": "smoke-unbanked", "synthetic": True})


def edited_row(smoke: dict[str, Any]) -> None:
    """A row whose turns, stop reason, and arm differ from its run.json (review F5)."""
    smoke["runs"][3].update(turns=99, stop_reason="finished_at_cap", config_id="ma-other")


def other_plan_hash(smoke: dict[str, Any]) -> None:
    """Rows banked from another plan than the committed one."""
    smoke["provenance"]["plan_sha256"] = "0" * 64


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(drop_row, "one row per banked smoke run", id="missing-row"),
        pytest.param(duplicate_row, "one row per banked smoke run", id="duplicate-row"),
        pytest.param(unbanked_row, "one row per banked smoke run", id="unbanked-row"),
        pytest.param(edited_row, "one row per banked smoke run", id="edited-row"),
        pytest.param(other_plan_hash, "plan_sha256", id="other-plan"),
    ],
)
def test_rows_that_are_not_the_banked_runs_fail(tmp_path: Path, edit: Edit, message: str) -> None:
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", edit_rows=edit))


def unlink_all(run: Path) -> None:
    """Remove a banked run."""
    for path in run.iterdir():
        path.unlink()


def edit_record(run: Path, **changes: Any) -> None:
    """Change top-level fields of run.json."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    put(run, "run.json", {**data, **changes})


def edit_provenance(run: Path, **changes: Any) -> None:
    """Change fields of run.json's provenance."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    put(run, "run.json", {**data, "provenance": {**data["provenance"], **changes}})


def retask(run: Path) -> None:
    """Make run.json record another task."""
    edit_record(run, task_id="py-synthetic-08")


def edit_ledger(run: Path) -> None:
    """Change an event's payload without updating its hash."""
    text = (run / "ledger.jsonl").read_text(encoding="utf-8")
    put(run, "ledger.jsonl", text.replace('"model":', '"modelx":', 1))


def no_run_start(run: Path) -> None:
    """A ledger whose first event is not the run_start."""
    write_ledger(run / "ledger.jsonl", [("tool_call", {"tool": "bash", "source": "agent"})])


def start_only(run: Path) -> None:
    """A ledger that holds only the run_start (review F6's stand-in)."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    start = {"run_id": run.name, "task_id": data["task_id"], "agent": "minimal-agent"}
    write_ledger(run / "ledger.jsonl", [("run_start", {**start, "model": MODEL})])


def other_model(run: Path) -> None:
    """A run made by another model than its planned arm's, recorded consistently."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    edit_record(run, model=OTHER_MODEL)
    start = {"run_id": run.name, "task_id": data["task_id"], "agent": "minimal-agent"}
    end = {"final_report": data["report"], "turns": 1, "stop_reason": "finished"}
    events = [("run_start", {**start, "model": OTHER_MODEL}), ("run_end", end)]
    write_ledger(run / "ledger.jsonl", events)


def models_disagree(run: Path) -> None:
    """run.json names another model than its ledger's run_start (review-1)."""
    edit_record(run, model=OTHER_MODEL)


def mock_model(run: Path) -> None:
    """A banked run whose ledger and run.json both name a mock model (review-1)."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    edit_record(run, model="mock")
    start = {"run_id": run.name, "task_id": data["task_id"], "agent": "minimal-agent"}
    write_ledger(run / "ledger.jsonl", [("run_start", {**start, "model": "mock"})])


def silent_transcript(run: Path) -> None:
    """A transcript without one agent turn."""
    put(run, "transcript.json", {"messages": [{"role": "user", "content": "SYNTHETIC task"}]})


def synthetic_start(run: Path) -> None:
    """A run whose ledger marks it synthetic."""
    start = {
        "run_id": run.name,
        "task_id": "py-synthetic-07",
        "agent": "minimal-agent",
        "model": MODEL,
        "synthetic": True,
    }
    write_ledger(run / "ledger.jsonl", [("run_start", start)])


def other_arm(run: Path) -> None:
    """run.json records another arm than the planned one."""
    edit_record(run, config_id="ma-granite8b")


def other_seed(run: Path) -> None:
    """The run's provenance records a run spec with another seed than the planned one."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    spec = {**data["provenance"]["run_spec"], "seed": 5}
    edit_provenance(run, run_spec=spec)


def other_turns(run: Path) -> None:
    """run.json's turns are not its ledger's (review F6)."""
    edit_record(run, turns=7)


def other_report(run: Path) -> None:
    """run.json's report is not the one its ledger closed with (review F6)."""
    edit_record(run, report="SYNTHETIC edited report")


def other_truth(run: Path) -> None:
    """run.json says the hidden checks passed; its ledger says they failed (review F6)."""
    edit_record(run, ground_truth_success=True)


TAMPERS = [
    pytest.param(unlink_all, "no real agent smoke run", id="not-banked"),
    pytest.param(retask, "does not open with the run_start", id="other-task"),
    pytest.param(edit_ledger, "hash chain broken", id="edited-ledger"),
    pytest.param(no_run_start, "does not open with the run_start", id="no-run-start"),
    pytest.param(start_only, "does not end with the run_end", id="start-only-ledger"),
    pytest.param(other_model, "planned arm", id="other-model"),
    pytest.param(models_disagree, "does not record the driver and model", id="models-disagree"),
    pytest.param(mock_model, "not real agent runs", id="mock-model"),
    pytest.param(silent_transcript, "no agent turn", id="no-agent-turn"),
    pytest.param(synthetic_start, "marked synthetic", id="synthetic-run"),
    pytest.param(other_arm, "planned task and arm", id="other-arm"),
    pytest.param(other_seed, "planned run spec", id="other-seed"),
    pytest.param(other_turns, "does not end with the run_end", id="other-turns"),
    pytest.param(other_report, "does not end with the run_end", id="other-report"),
    pytest.param(other_truth, "ground_truth_success", id="other-ground-truth"),
]


@pytest.mark.parametrize(("tamper", "message"), TAMPERS)
def test_smoke_rows_must_be_banked_runs(tmp_path: Path, tamper: Tamper, message: str) -> None:
    # Old code: the summary row alone counted, with no run behind it.
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=tamper))


@pytest.mark.parametrize(("tamper", "message"), TAMPERS)
def test_the_amended_run_is_checked_as_every_run_is(
    tmp_path: Path, tamper: Tamper, message: str
) -> None:
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=tamper, amend=True))


def test_the_real_agent_predicate() -> None:
    assert ship_check.is_real_agent("claude-code/sonnet")
    assert ship_check.is_real_agent(AGENT)
    for label in ("", "   ", "minimal-agent/MOCK", "Reference", "stub-agent", None, 3):
        assert not ship_check.is_real_agent(label)
    rows = [
        {"run_id": "a", "task_id": "t", "agent": AGENT, "synthetic": False},
        {"run_id": "b", "task_id": "t", "agent": AGENT},
        {"run_id": "c", "task_id": "t", "agent": AGENT, "synthetic": 0},
        {"run_id": "", "task_id": "t", "agent": AGENT, "synthetic": False},
        {"run_id": "e", "agent": AGENT, "synthetic": False},
    ]
    assert [r["run_id"] for r in ship_check.real_smoke_runs({"runs": rows})] == ["a"]
    with pytest.raises(GateError, match="malformed"):
        ship_check.real_smoke_runs({"runs": [1]})


# A run that a plan amendment added (DECISIONS D71) ----------------------------------------


def pinned_window(run: Path) -> None:
    """The run was made on the pinned window on four slots (a consistent record)."""
    edit_provenance(run, model_server=model_server(PINNED, 4))


def four_slots(run: Path) -> None:
    """The run was made with the raised window but on four slots (a consistent record)."""
    edit_provenance(run, model_server=model_server(32768, 4))


def edited_size(run: Path) -> None:
    """Only ctx_size is edited."""
    edit_provenance(run, model_server={**model_server(32768, 1), "ctx_size": 65536})


def claims_the_window(run: Path) -> None:
    """Only the window field says 32768; the command still serves 16384 per slot."""
    edit_provenance(run, model_server={**model_server(PINNED, 1), "n_ctx_per_slot": 32768})


def edited_command(run: Path) -> None:
    """The command line is edited and its SHA-256 left as it was."""
    server = model_server(32768, 1)
    command = list(server["server_command"])
    command[command.index("--port") + 1] = "9999"
    edit_provenance(run, model_server={**server, "server_command": command})


def rehashed_slots(run: Path) -> None:
    """The command runs two slots, consistently hashed, while the record says one."""
    server = model_server(32768, 1)
    command = list(server["server_command"])
    command[command.index("--parallel") + 1] = "2"
    server.update(server_command=command, server_command_sha256=sha256_text(" ".join(command)))
    edit_provenance(run, model_server=server)


def says_pinned(run: Path) -> None:
    """The record says the raised window is the pinned one."""
    edit_provenance(run, model_server={**model_server(32768, 1), "n_ctx_per_slot_is_default": True})


def other_default(run: Path) -> None:
    """The record names another pinned window than the amendment raised."""
    edit_provenance(run, model_server={**model_server(32768, 1), "n_ctx_per_slot_default": 8192})


def unreported(run: Path) -> None:
    """The record holds nothing the live server reported (review F3)."""
    edit_provenance(run, model_server={**model_server(32768, 1), "reported": None})


def reported_other_window(run: Path) -> None:
    """The live server reported the excluded run's window (a server left by an earlier
    session answered, review F3)."""
    server = model_server(32768, 1)
    server["reported"] = {**server["reported"], "n_ctx_per_slot": PINNED, "total_slots": 4}
    edit_provenance(run, model_server=server)


def python_engine(run: Path) -> None:
    """The run was served by llama-cpp-python, which reports nothing it serves."""
    model = LocalModel(MODEL, "qwen", MODEL_PATH, "0" * 64, "SYNTHETIC", 32768)
    server = dict(LocalServer(model, engine="llama-cpp-python").provenance())
    server.update(n_ctx_per_slot_default=PINNED, n_ctx_per_slot_is_default=False)
    edit_provenance(run, model_server=server)


def no_server(run: Path) -> None:
    """The record holds no model server."""
    edit_provenance(run, model_server=None)


def no_amendment(run: Path) -> None:
    """The run does not record the amendment that added it."""
    edit_provenance(run, plan_amendment=None)


def other_amendment(run: Path) -> None:
    """The run records another reason than the plan's amendment gives."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    amendment = {**data["provenance"]["plan_amendment"], "reason": "SYNTHETIC: another reason"}
    edit_provenance(run, plan_amendment=amendment)


def shared_cache(run: Path) -> None:
    """The run's replies came from the shared response cache (review F3, false rejection)."""
    edit_provenance(run, response_cache="runs/cache")


def other_agent(run: Path) -> None:
    """The run was made with an agent configuration no banked run of its arm used."""
    agent = {**AGENT_CONFIG, "max_turns": 40}
    edit_provenance(run, agent_config=agent, agent_config_sha256=sha256_text(canonical_json(agent)))


def agent_hash_only(run: Path) -> None:
    """The agent configuration is edited and its SHA-256 left as it was."""
    edit_provenance(run, agent_config={**AGENT_CONFIG, "max_turns": 40})


def made_before_the_amendment(run: Path) -> None:
    """The run records a commit whose plan does not hold the amendment (review F6)."""
    root = repo_of(run)
    first = git(root, "rev-list", "--max-parents=0", "HEAD").strip()
    edit_provenance(run, git_sha=first)


def unknown_commit(run: Path) -> None:
    """The run records a commit that is not in the repository."""
    edit_provenance(run, git_sha="f" * 40)


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        pytest.param(pinned_window, "at least 32768 tokens per slot", id="pinned-window"),
        pytest.param(four_slots, r"at most 1 slot\(s\)", id="four-slots"),
        pytest.param(edited_size, "ctx_size 65536", id="edited-size"),
        pytest.param(claims_the_window, "--ctx-size", id="claimed-window"),
        pytest.param(edited_command, "SHA-256", id="edited-command"),
        pytest.param(rehashed_slots, "--parallel", id="two-slots-in-the-command"),
        pytest.param(says_pinned, "n_ctx_per_slot_is_default", id="says-pinned"),
        pytest.param(other_default, "pinned window", id="other-pinned-window"),
        pytest.param(unreported, "reported", id="not-reported"),
        pytest.param(reported_other_window, "live server reports", id="reported-16k-on-4"),
        pytest.param(python_engine, r"llama\.cpp", id="llama-cpp-python"),
        pytest.param(no_server, "no model server", id="no-server"),
        pytest.param(no_amendment, "plan amendment that added it", id="no-amendment"),
        pytest.param(other_amendment, "plan amendment that added it", id="other-amendment"),
        pytest.param(shared_cache, "response cache", id="shared-cache"),
        pytest.param(other_agent, "agent configuration", id="other-agent"),
        pytest.param(agent_hash_only, "agent configuration", id="agent-edited"),
        pytest.param(made_before_the_amendment, "holds the amendment", id="made-before"),
        pytest.param(unknown_commit, "holds the amendment", id="unknown-commit"),
    ],
)
def test_an_amended_run_not_made_on_the_server_it_needs_fails(
    tmp_path: Path, tamper: Tamper, message: str
) -> None:
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=tamper, amend=True))


def test_the_excluded_run_stays_excluded(tmp_path: Path) -> None:
    def also_excluded(run: Path) -> None:
        bank(repo_of(run), base_plan(), EXCLUDED)

    with pytest.raises(GateError, match="replaced by a plan amendment"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=also_excluded, amend=True))


def test_a_smoke_run_the_plan_does_not_hold_fails(tmp_path: Path) -> None:
    # Review F5 (V4): an unplanned run directory, with or without a row, fails.
    def unplanned(run: Path) -> None:
        bank(repo_of(run), amended(base_plan()), ADDED)

    with pytest.raises(GateError, match="not a planned run"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=unplanned))

    def without_row(smoke: dict[str, Any]) -> None:
        smoke["runs"] = [row for row in smoke["runs"] if row["run_id"] != ADDED]

    with pytest.raises(GateError, match="one row per banked smoke run"):
        ship_check.g6(benchmark(tmp_path / "repo2", tamper=unplanned, edit_rows=without_row))


# The plan, its amendment, and its committed history (review F1, F2) ------------------------


def rewrite_plan(root: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    """Edit the SYNTHETIC repository's plan.json in place, as write_plan writes it."""
    data = json.loads((root / PLAN).read_text(encoding="utf-8"))
    edit(data)
    put(root, PLAN, json.dumps(data, indent=2, sort_keys=True) + "\n")


def run_of(data: dict[str, Any], run_id: str) -> dict[str, Any]:
    """The planned run ``run_id`` in plan.json data."""
    return next(run for run in data["runs"] if run["run_id"] == run_id)


def both_seeds(data: dict[str, Any]) -> None:
    """V2: the replaced and the added run both get seed 7 and another mitigation."""
    for rid in (EXCLUDED, ADDED):
        run_of(data, rid).update(seed=7, mitigation="honesty")


def two_runs_appended(data: dict[str, Any]) -> None:
    """V3: two runs added to runs[] with no amendment."""
    for rid in ("smoke-py-synthetic-03-r2", f"{EXCLUDED}-r2"):
        data["runs"].append({**run_of(data, EXCLUDED), "run_id": rid})


def arm_model(data: dict[str, Any]) -> None:
    """V8: the arm's model becomes another model."""
    data["arms"][0]["model"] = data["arms"][0]["agent"]["model"] = OTHER_MODEL


def requirement(**server: int) -> Callable[[dict[str, Any]], None]:
    """V1: the amendment's server requirement edited by hand."""

    def edit(data: dict[str, Any]) -> None:
        data["amendments"][0]["server"].update(server)

    return edit


def decision(data: dict[str, Any]) -> None:
    """The amendment names another decision."""
    data["amendments"][0]["decision"] = "D70"


def before_hash(data: dict[str, Any]) -> None:
    """The amendment records another plan's SHA-256."""
    data["amendments"][0]["plan_sha256_before"] = "0" * 64


def amendment_removed(data: dict[str, Any]) -> None:
    """The amendment is removed and its run kept as a plain planned run."""
    data.pop("amendments")


def amended_twice(data: dict[str, Any]) -> None:
    """The amendment appears twice."""
    data["amendments"].append(dict(data["amendments"][0]))


def notes_edited(data: dict[str, Any]) -> None:
    """The plan's notes change after the amendment."""
    data["notes"] = "SYNTHETIC: edited notes"


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(both_seeds, "plan_sha256_before", id="v2-both-seeds"),
        pytest.param(two_runs_appended, "last runs", id="v3-runs-appended"),
        pytest.param(arm_model, "plan_sha256_before", id="v8-arm-model"),
        pytest.param(
            requirement(min_n_ctx_per_slot=PINNED, max_parallel_slots=4),
            "does not raise",
            id="v1-excluded-runs-server",
        ),
        pytest.param(requirement(max_parallel_slots=4), "one slot", id="v1-four-slots"),
        pytest.param(requirement(pinned_n_ctx_per_slot=32768), "does not raise", id="pinned"),
        pytest.param(decision, "D71", id="other-decision"),
        pytest.param(before_hash, "plan_sha256_before", id="before-hash"),
        pytest.param(amended_twice, "more than once", id="twice"),
        pytest.param(notes_edited, "plan_sha256_before", id="notes"),
        pytest.param(lambda d: d.update(amendments={}), "amendments", id="not-a-list"),
        pytest.param(lambda d: d["runs"].append(d["runs"][0]), "repeats", id="repeated-run"),
    ],
)
def test_a_plan_edited_after_its_amendment_fails(
    tmp_path: Path, edit: Callable[[dict[str, Any]], None], message: str
) -> None:
    def broken_plan(run: Path) -> None:
        rewrite_plan(repo_of(run), edit)

    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=broken_plan, amend=True))


def test_a_consistent_forgery_of_the_plan_history_fails(tmp_path: Path) -> None:
    # Review F2: the seed of the excluded run is changed in its own commit before the
    # amendment, so the amendment records the SHA-256 of the plan before it. No
    # committed version may change a planned run outside an amendment.
    root = tmp_path / "repo"
    ctx = benchmark(root, amend=True)
    git(root, "reset", "-q", "--hard", "HEAD~2")  # back to the banked runs
    rewrite_plan(root, lambda d: run_of(d, EXCLUDED).update(seed=7))
    commit_all(root, "SYNTHETIC: change the excluded run's seed")
    plan = amended(load_plan(root / PLAN))
    write_plan(root / PLAN, plan)
    sha = commit_all(root, "SYNTHETIC plan amendment of the edited plan")
    bank(root, plan, ADDED, git_sha=sha)
    bank_rows(root)
    commit_all(root, "SYNTHETIC smoke runs banked")
    with pytest.raises(GateError, match="plans other runs than"):
        ship_check.g6(ctx)


def test_an_amendment_made_to_another_plan_than_its_parents_fails(tmp_path: Path) -> None:
    # Review F2: the amendment commit also edits the replaced run, and the amendment
    # records the SHA-256 of that edited plan; its parent's plan file has another one.
    root = tmp_path / "repo"
    ctx = benchmark(root, amend=True)
    git(root, "reset", "-q", "--hard", "HEAD~2")
    edited = load_plan(root / PLAN)
    runs = [dataclasses.replace(r, seed=7) if r.run_id == EXCLUDED else r for r in edited.runs]
    plan = amended(dataclasses.replace(edited, runs=runs))
    write_plan(root / PLAN, plan)
    sha = commit_all(root, "SYNTHETIC plan amendment and seed edit in one commit")
    bank(root, plan, ADDED, git_sha=sha)
    bank_rows(root)
    commit_all(root, "SYNTHETIC smoke runs banked")
    with pytest.raises(GateError, match=r"plans other runs than|the plan file before it"):
        ship_check.g6(ctx)


def test_the_plan_is_never_removed_once_committed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    ctx = benchmark(root)
    text = (root / PLAN).read_text(encoding="utf-8")
    (root / PLAN).unlink()
    commit_all(root, "SYNTHETIC: remove the plan")
    put(root, PLAN, text)
    commit_all(root, "SYNTHETIC: put it back")
    with pytest.raises(GateError, match="removed"):
        ship_check.g6(ctx)


def test_a_missing_smoke_plan_fails(tmp_path: Path) -> None:
    def no_plan(run: Path) -> None:
        (repo_of(run) / PLAN).unlink()

    with pytest.raises(GateError, match=r"plan\.json missing"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=no_plan))


def test_the_pinned_window_is_the_one_the_other_runs_were_served(tmp_path: Path) -> None:
    # Review F1: the amendment's pinned window must be the window per slot every other
    # banked run of the model was served with.
    with pytest.raises(GateError, match="pinned window"):
        ship_check.g6(benchmark(tmp_path / "repo", amend=True, window=8192))


# The banked failure log (review F2, F5) -----------------------------------------------------


@pytest.mark.parametrize("attempts", [2, 0])
def test_the_failure_log_must_show_the_replaced_run_excluded(tmp_path: Path, attempts: int) -> None:
    # D71: only a run the runner excluded (three logged failures) is replaced.
    with pytest.raises(GateError, match="fewer than"):
        ship_check.g6(benchmark(tmp_path / "repo", amend=True, attempts=attempts))


def test_a_run_the_failure_log_excludes_is_never_banked(tmp_path: Path) -> None:
    def three_more(run: Path) -> None:
        root = repo_of(run)
        entries = [
            {"run_id": "smoke-py-synthetic-03-ma-qwen7b", "attempt": n, "error": "SYNTHETIC"}
            for n in (1, 2, 3)
        ]
        more = "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries)
        put(root, FAILURES, (root / FAILURES).read_text(encoding="utf-8") + more)

    with pytest.raises(GateError, match="never banked"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=three_more, amend=True))


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(
            lambda smoke: smoke["failures"].update(sha256="0" * 64), "failure log", id="sha"
        ),
        pytest.param(
            lambda smoke: smoke["failures"].update(entries=2), "failure log", id="entries"
        ),
        pytest.param(lambda smoke: smoke.update(failures=None), "failure log", id="no-summary"),
    ],
)
def test_the_failure_summary_must_be_the_banked_log(
    tmp_path: Path, edit: Edit, message: str
) -> None:
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", amend=True, edit_rows=edit))


def test_a_logged_failure_stays_logged(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    ctx = benchmark(root, amend=True)
    log_failures(root, attempts=3)
    lines = (root / FAILURES).read_text(encoding="utf-8").splitlines()
    put(root, FAILURES, "\n".join([*lines[1:], lines[0]]) + "\n")  # same entries, reordered
    bank_rows(root)
    commit_all(root, "SYNTHETIC: rewrite the failure log")
    with pytest.raises(GateError, match="start of the one at HEAD"):
        ship_check.g6(ctx)


# Banked runs are immutable (DECISIONS D62; review F4) ----------------------------------------


def symlinked(root: Path) -> None:
    """V6: run.json becomes a symlink to an edited copy (a type change)."""
    run = root / RUNS / "smoke-py-synthetic-03-ma-qwen7b"
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    put(run, "run.v2.json", {**data, "report": "SYNTHETIC edited report"})
    (run / "run.json").unlink()
    (run / "run.json").symlink_to("run.v2.json")
    commit_all(root, "SYNTHETIC: a symlink in place of run.json")


def merge_edit(root: Path) -> None:
    """V7: run.json edited inside a merge commit."""
    git(root, "checkout", "-q", "-b", "side")
    put(root, "SIDE.txt", "SYNTHETIC side branch\n")
    commit_all(root, "SYNTHETIC side commit")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "--no-ff", "--no-commit", "side")
    edit_record(root / RUNS / "smoke-py-synthetic-03-ma-qwen7b", turns=99)
    commit_all(root, "SYNTHETIC merge with an edit")


def discarded_side_edit(root: Path) -> None:
    """A side branch edits a banked run.json; an "ours" merge keeps the original."""
    git(root, "checkout", "-q", "-b", "side")
    edit_record(root / RUNS / "smoke-py-synthetic-03-ma-qwen7b", turns=99)
    commit_all(root, "SYNTHETIC side edit")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "-s", "ours", "--no-edit", "side")


def later_edit(root: Path) -> None:
    """A later commit rewrites a banked run.json."""
    edit_record(root / RUNS / ADDED, turns=99)
    commit_all(root, "SYNTHETIC later change")


def later_delete(root: Path) -> None:
    """A later commit deletes a banked file."""
    (root / RUNS / ADDED / "transcript.json").unlink()
    commit_all(root, "SYNTHETIC later delete")


def executable(root: Path) -> None:
    """A banked file becomes executable (a mode change git logs as a modification)."""
    git(root, "update-index", "--chmod=+x", f"{RUNS}/{ADDED}/run.json")
    git(root, "commit", "-q", "-m", "SYNTHETIC chmod")


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(later_edit, id="edit"),
        pytest.param(later_delete, id="delete"),
        pytest.param(symlinked, id="v6-symlink"),
        pytest.param(merge_edit, id="v7-merge-edit"),
        pytest.param(discarded_side_edit, id="discarded-side-edit"),
        pytest.param(executable, id="mode-change"),
    ],
)
def test_a_banked_smoke_run_changed_after_it_was_committed_fails(
    tmp_path: Path, change: Callable[[Path], None]
) -> None:
    # DECISIONS D62: a banked run is never changed or removed. Each later change here
    # fails G6, whatever it is: an edit, a deletion, a type change, an edit inside a
    # merge commit, or an edit on a side branch that a merge discarded.
    ctx = benchmark(tmp_path / "repo", amend=True)
    change(ctx.clone)
    with pytest.raises(GateError, match=r"later changed or deleted|not a regular file"):
        ship_check.g6(ctx)


def test_a_run_banked_as_a_symlink_fails(tmp_path: Path) -> None:
    # Review F4: a banked file must be a regular file from the start.
    def link(run: Path) -> None:
        data = json.loads((run / "run.json").read_text(encoding="utf-8"))
        put(run, "record.json", data)
        (run / "run.json").unlink()
        (run / "run.json").symlink_to("record.json")

    with pytest.raises(GateError, match="not a regular file"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=link))


@pytest.mark.parametrize("study", ["e1", "e4"])
def test_the_immutability_rule_is_the_same_for_every_study(tmp_path: Path, study: str) -> None:
    # G7 and G9 share require_unchanged_runs with G6 (review F4).
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    run = f"artifacts/studies/{study}/runs/{study}-000-arm"
    put(root, f"{run}/run.json", {"SYNTHETIC": "banked run"})
    commit_all(root, "SYNTHETIC banked run")
    ship_check.require_unchanged_runs(root, study)
    git(root, "checkout", "-q", "-b", "side")
    put(root, "SIDE.txt", "SYNTHETIC side branch\n")
    commit_all(root, "SYNTHETIC side commit")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "--no-ff", "--no-commit", "side")
    put(root, f"{run}/run.json", {"SYNTHETIC": "edited in the merge"})
    commit_all(root, "SYNTHETIC merge with an edit")
    with pytest.raises(GateError, match="later changed or deleted"):
        ship_check.require_unchanged_runs(root, study)


def type_change_and_back(root: Path) -> None:
    """run.json becomes a symlink, and then a regular file again with a field no other
    check reads edited: two type changes, no plain modification, and no deletion
    (review F4)."""
    run = root / RUNS / "smoke-py-synthetic-03-ma-qwen7b"
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    put(run, "other.json", data)
    (run / "run.json").unlink()
    (run / "run.json").symlink_to("other.json")
    commit_all(root, "SYNTHETIC: a symlink in place of run.json")
    (run / "run.json").unlink()
    put(run, "run.json", {**data, "SYNTHETIC_note": "edited after banking"})
    commit_all(root, "SYNTHETIC: a regular file again, edited")


def edited_and_reverted_on_a_side_branch(root: Path) -> None:
    """A side branch edits a banked run.json and reverts the edit before it is merged, so
    the merge differs from neither parent: only a walk of every commit finds the edit."""
    git(root, "checkout", "-q", "-b", "side")
    run = root / RUNS / "smoke-py-synthetic-03-ma-qwen7b"
    original = (run / "run.json").read_text(encoding="utf-8")
    edit_record(run, SYNTHETIC_note="edited on a side branch")
    commit_all(root, "SYNTHETIC side edit")
    put(run, "run.json", original)
    commit_all(root, "SYNTHETIC side revert")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "--no-edit", "side")


def test_an_edit_reverted_on_a_merged_side_branch_fails(tmp_path: Path) -> None:
    # DECISIONS D62 holds for every commit of HEAD's history (git log --full-history).
    ctx = benchmark(tmp_path / "repo", amend=True)
    edited_and_reverted_on_a_side_branch(ctx.clone)
    with pytest.raises(GateError, match="later changed or deleted"):
        ship_check.g6(ctx)


def test_a_type_change_and_back_fails(tmp_path: Path) -> None:
    ctx = benchmark(tmp_path / "repo", amend=True)
    type_change_and_back(ctx.clone)
    with pytest.raises(GateError, match="later changed or deleted"):
        ship_check.g6(ctx)


def reported_other_file(run: Path) -> None:
    """The live server reported serving another model file than its command names."""
    server = model_server(32768, 1)
    server["reported"] = {**server["reported"], "model_path": "/other/SYNTHETIC.gguf"}
    edit_provenance(run, model_server=server)


def end_of_another_kind(run: Path) -> None:
    """The ledger's last event carries the run_end fields but is not a run_end."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    start = {"run_id": run.name, "task_id": data["task_id"], "agent": "minimal-agent"}
    check = {"checks": [{"name": "test_hidden", "passed": False}], "total": 1, "failed": 1}
    end = {"final_report": data["report"], "turns": 1, "stop_reason": "finished"}
    events = [("run_start", {**start, "model": MODEL}), ("hidden_check", check), ("note", end)]
    write_ledger(run / "ledger.jsonl", events)


def reported_bool_slots(run: Path) -> None:
    """The live server's slot count is reported as true, not 1."""
    server = model_server(32768, 1)
    server["reported"] = {**server["reported"], "total_slots": True}
    edit_provenance(run, model_server=server)


def other_snapshot(run: Path) -> None:
    """The run says it ran from a code snapshot of another commit than its git_sha."""
    edit_provenance(run, code="snapshot", snapshot_of="e" * 40)


def unverified_snapshot(run: Path) -> None:
    """The run's code snapshot was not checked against its commit."""
    edit_provenance(run, snapshot_verified=False)


def dirty_tree(run: Path) -> None:
    """The run ran from a working tree with an uncommitted change under src/."""
    edit_provenance(run, code="working tree", uncommitted_at_start=["src/receipts/SYNTHETIC.py"])


def exposed_sandbox(run: Path) -> None:
    """The run's sandbox did not hide the checkout (DECISIONS D67)."""
    edit_provenance(run, sandbox={"backend": "bwrap", "checkout_hidden": False})


def no_sandbox(run: Path) -> None:
    """The run records no sandbox."""
    edit_provenance(run, sandbox=None)


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        pytest.param(unverified_snapshot, "code that ran", id="unverified-snapshot"),
        pytest.param(dirty_tree, "code that ran", id="dirty-working-tree"),
        pytest.param(exposed_sandbox, "hid the checkout", id="exposed-sandbox"),
        pytest.param(no_sandbox, "hid the checkout", id="no-sandbox"),
        pytest.param(reported_bool_slots, "live server reports", id="reported-bool"),
        pytest.param(reported_other_file, "live server reports", id="reported-other-file"),
        pytest.param(end_of_another_kind, "does not end with the run_end", id="end-not-run-end"),
        pytest.param(other_snapshot, "code that ran", id="other-snapshot"),
    ],
)
def test_more_amended_run_records_that_fail(tmp_path: Path, tamper: Tamper, message: str) -> None:
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=tamper, amend=True))


def test_a_genuine_run_from_a_clean_working_tree_passes(tmp_path: Path) -> None:
    def working_tree(run: Path) -> None:
        data = json.loads((run / "run.json").read_text(encoding="utf-8"))
        prov = {k: v for k, v in data["provenance"].items() if not k.startswith("snapshot")}
        put(run, "run.json", {**data, "provenance": {**prov, "code": "working tree"}})
        edit_provenance(run, uncommitted_at_start=[])

    evidence = ship_check.g6(benchmark(tmp_path / "repo", tamper=working_tree, amend=True))
    assert "1 from a plan amendment" in evidence


def test_the_smoke_files_are_regular_files(tmp_path: Path) -> None:
    # smoke_runs.json as a symlink to a copy of itself: same content, not a regular file.
    def link_rows(smoke: dict[str, Any]) -> None:
        return None

    root = tmp_path / "repo"
    ctx = benchmark(root, edit_rows=link_rows)
    text = (root / SMOKE).read_text(encoding="utf-8")
    put(root, "artifacts/bench/smoke_runs.copy.json", text)
    (root / SMOKE).unlink()
    (root / SMOKE).symlink_to("smoke_runs.copy.json")
    commit_all(root, "SYNTHETIC: smoke_runs.json as a symlink")
    with pytest.raises(GateError, match="not a regular file"):
        ship_check.g6(ctx)


def history(root: Path, *edits: Callable[[dict[str, Any]], None]) -> None:
    """Commit each edit of the SYNTHETIC repository's plan in turn."""
    for number, edit in enumerate(edits):
        rewrite_plan(root, edit)
        commit_all(root, f"SYNTHETIC plan edit {number}")


def test_fixed_plan_fields_never_change_in_any_commit(tmp_path: Path) -> None:
    # The notes change and change back: HEAD's plan is as before, a commit's was not.
    root = tmp_path / "repo"
    ctx = benchmark(root)
    notes = json.loads((root / PLAN).read_text(encoding="utf-8"))["notes"]
    history(
        root, lambda d: d.update(notes="SYNTHETIC: other notes"), lambda d: d.update(notes=notes)
    )
    with pytest.raises(GateError, match="has another schema, study, notes, text"):
        ship_check.g6(ctx)


def test_arms_never_change_once_the_plan_holds_an_amendment(tmp_path: Path) -> None:
    # The arm changes after the amendment and changes back before HEAD.
    root = tmp_path / "repo"
    ctx = benchmark(root, amend=True)
    turns = json.loads((root / PLAN).read_text(encoding="utf-8"))["arms"][0]["agent"]["max_turns"]

    def arm(value: int) -> Callable[[dict[str, Any]], None]:
        return lambda d: d["arms"][0]["agent"].update(max_turns=value)

    history(root, arm(40), arm(turns))
    with pytest.raises(GateError, match="other arms than"):
        ship_check.g6(ctx)


def test_an_amendment_committed_with_an_arm_edit_fails(tmp_path: Path) -> None:
    # The amendment commit also edits the arm, and the amendment records the SHA-256 of
    # the edited plan: HEAD's plan is consistent, its parent's plan file is another one.
    root = tmp_path / "repo"
    ctx = benchmark(root, amend=True)
    git(root, "reset", "-q", "--hard", "HEAD~2")
    edited = load_plan(root / PLAN)
    arms = [local_arm(CONFIG, MODEL, "qwen", max_turns=40)]
    plan = amended(dataclasses.replace(edited, arms=arms))
    write_plan(root / PLAN, plan)
    sha = commit_all(root, "SYNTHETIC plan amendment and arm edit in one commit")
    bank(root, plan, ADDED, git_sha=sha)
    bank_rows(root)
    commit_all(root, "SYNTHETIC smoke runs banked")
    with pytest.raises(GateError, match="the plan file before it"):
        ship_check.g6(ctx)


def test_two_amendments_in_one_commit_fail(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    benchmark(root, amend=True)
    git(root, "reset", "-q", "--hard", "HEAD~2")
    once = amended(load_plan(root / PLAN))
    server = ServerRequirement(
        min_n_ctx_per_slot=32768, max_parallel_slots=1, pinned_n_ctx_per_slot=PINNED
    )
    replaced = f"smoke-py-synthetic-08-{CONFIG}"
    twice = amend_plan(
        once, replaced, server, decision="D71", reason="SYNTHETIC", date="2026-11-12"
    )
    write_plan(root / PLAN, twice)
    commit_all(root, "SYNTHETIC two plan amendments in one commit")
    with pytest.raises(GateError, match="more than one plan amendment"):
        ship_check.check_plan_history(root, json.loads((root / PLAN).read_text(encoding="utf-8")))


def test_a_plan_first_committed_with_an_amendment_fails(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    write_plan(root / PLAN, amended(base_plan()))
    commit_all(root, "SYNTHETIC plan committed already amended")
    with pytest.raises(GateError, match="committed without any first"):
        ship_check.check_plan_history(root, json.loads((root / PLAN).read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(
            lambda smoke: smoke.update(failures={"banked": FAILURES, "sha256": "0" * 64}),
            "summarizes a banked failure log",
            id="summary-without-log",
        ),
    ],
)
def test_a_failure_summary_without_a_banked_log_fails(
    tmp_path: Path, edit: Edit, message: str
) -> None:
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", edit_rows=edit))


def test_a_failure_log_line_that_is_not_an_entry_fails(tmp_path: Path) -> None:
    def broken_line(run: Path) -> None:
        root = repo_of(run)
        put(root, FAILURES, (root / FAILURES).read_text(encoding="utf-8") + "[]\n")

    with pytest.raises(GateError, match="names no run id"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=broken_line, amend=True))


def test_an_amendment_record_is_never_rewritten(tmp_path: Path) -> None:
    # Review F2: the amendment's reason is rewritten after the amendment was committed,
    # and the added run records the new one: HEAD is consistent, the committed history
    # is not.
    def rewritten(run: Path) -> None:
        root = repo_of(run)
        rewrite_plan(root, lambda d: d["amendments"][0].update(reason="SYNTHETIC: rewritten"))
        data = json.loads((run / "run.json").read_text(encoding="utf-8"))
        amendment = {**data["provenance"]["plan_amendment"], "reason": "SYNTHETIC: rewritten"}
        edit_provenance(run, plan_amendment=amendment)

    with pytest.raises(GateError, match="never changed or removed"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=rewritten, amend=True))


def test_the_gate_reads_amendments_as_the_plan_library_writes_them() -> None:
    # ship_check is stdlib-only and keeps its own copies of these terms; they must be
    # the plan library's and the runner's.
    import run_study
    from receipts.study import plan as library

    assert ship_check.SAME_AS_REPLACED == library.SAME_AS_REPLACED
    assert ship_check.AMENDMENT_DECISION == library.AMENDMENT_DECISION
    assert ship_check.AMENDMENT_SLOTS == library.AMENDMENT_SLOTS
    assert ship_check.AMENDMENT_SERVER_FIELDS == library.SERVER_FIELDS
    assert ship_check.MAX_ATTEMPTS == run_study.MAX_ATTEMPTS
    assert library.amendment_cache("smoke", ADDED) == f"runs/smoke/cache/{ADDED}"
    once = amended(base_plan())
    twice = amend_plan(
        once,
        f"smoke-py-synthetic-08-{CONFIG}",
        once.amendments[0].server,
        decision="D71",
        reason="SYNTHETIC",
        date="2026-11-12",
    )
    data = json.loads(library.plan_text(twice))
    assert ship_check.plan_file_text(data) == library.plan_text(twice)
    for count in (0, 1, 2):
        assert ship_check.plan_before(data, count) == library.plan_before(twice, count).to_json()
