"""Gate G6 of tools/ship_check.py on a synthetic benchmark (H17, with the G5 part in H20).

Every task, plan, plan amendment, reference validation, banked smoke run, server record,
and smoke-run row here is SYNTHETIC, made up only to exercise ``ship_check.g6``. Smoke
rows are marked ``synthetic: false`` only so the gate treats them as real runs; nothing
here is a model result or a real-world result, and no model is called.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import ship_check
from receipts.bench.hashing import tree_sha256
from receipts.client.server import LocalModel, LocalServer
from receipts.ledger.events import GENESIS, Event, sha256_text
from receipts.study.plan import (
    Plan,
    ServerRequirement,
    amend_plan,
    local_arm,
    smoke_plan,
    write_plan,
)

GateError = ship_check.GateError
MODEL = "qwen2.5-coder-7b-instruct-q4km"
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
PINNED = 16384
EXCLUDED = f"smoke-py-synthetic-07-{CONFIG}"
ADDED = f"{EXCLUDED}-ctx32k"
Tamper = Callable[[Path], None]


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
    with ``n_ctx`` tokens per slot on ``slots`` slots (nothing is served here)."""
    model = LocalModel(MODEL, "qwen", Path("/nonexistent.gguf"), "0" * 64, "SYNTHETIC", n_ctx)
    record = dict(LocalServer(model, engine="llama.cpp", parallel=slots).provenance())
    record["n_ctx_per_slot_default"] = PINNED
    record["n_ctx_per_slot_is_default"] = n_ctx == PINNED
    return record


def the_plan(amend: bool) -> Plan:
    """The SYNTHETIC smoke plan: one run per task; with ``amend``, task 07's run is
    replaced by one that needs 32768 tokens per slot on one slot (DECISIONS D71)."""
    tasks = [f"py-synthetic-{i:02d}" for i in range(N_TASKS)]
    plan = smoke_plan("smoke", tasks, local_arm(CONFIG, MODEL, "qwen"))
    if not amend:
        return plan
    return amend_plan(
        plan,
        EXCLUDED,
        ServerRequirement(
            min_n_ctx_per_slot=32768, max_parallel_slots=1, pinned_n_ctx_per_slot=PINNED
        ),
        decision="D71",
        reason="SYNTHETIC: the request outgrew the window",
        date="2026-11-12",
    )


def bank(root: Path, plan: Plan, run_id: str) -> None:
    """Bank one SYNTHETIC smoke run as planned: run.json, its ledger, and its transcript."""
    spec = next(run for run in plan.runs if run.run_id == run_id)
    prov: dict[str, Any] = {
        "run_spec": {**dataclasses.asdict(spec), "conditions": dict(spec.conditions)},
        "model_server": model_server(),
    }
    amendment = plan.amendment(run_id)
    if amendment is not None:
        prov.update(plan_amendment=amendment.to_json(), model_server=model_server(32768, 1))
    record = {
        "run_id": run_id,
        "task_id": spec.task_id,
        "config_id": spec.config_id,
        "model": MODEL,
        "provenance": prov,
    }
    put(root, f"{RUNS}/{run_id}/run.json", record)
    start = {"run_id": run_id, "task_id": spec.task_id, "agent": "minimal-agent", "model": MODEL}
    write_ledger(root / RUNS / run_id / "ledger.jsonl", [("run_start", start)])
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


def commit_all(root: Path, message: str) -> None:
    """Commit everything in the SYNTHETIC repository."""
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)


def benchmark(
    root: Path,
    agent: object = AGENT,
    tamper: Tamper | None = None,
    *,
    amend: bool = False,
    target: str | None = None,
) -> ship_check.Context:
    """Thirty SYNTHETIC tasks with validated references, their smoke plan, and one banked
    smoke run each, committed in a git repository. With ``amend``, task 07's run is the
    one a plan amendment added. ``tamper`` changes the run ``target`` (task 07's banked
    run by default) before the commit."""
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    plan = the_plan(amend)
    write_plan(root / PLAN, plan)
    validated = {}
    rows = []
    replaced = plan.replaced()
    for spec in plan.runs:
        if spec.run_id in replaced:
            continue  # the excluded run stays excluded: never banked
        tid = spec.task_id
        task = f"bench/tasks/{tid}"
        put(root, f"{task}/task.toml", f'id = "{tid}"\nlanguage = "python"\n')
        put(root, f"{task}/hidden/test_hidden.py", "def test_ok():\n    assert True\n")
        put(root, f"{task}/reference/fix.py", "VALUE = 1\n")
        put(root, f"{task}/manifest.json", {"manipulations": {"M1": "synthetic overlay"}})
        validated[tid] = {"tree_sha256": tree_sha256(root / task), "hidden_passed": True}
        rows.append({"run_id": spec.run_id, "task_id": tid, "agent": agent, "synthetic": False})
        bank(root, plan, spec.run_id)
    put(root, "artifacts/bench/reference_validation.json", {"tasks": validated, "provenance": PROV})
    put(root, "artifacts/bench/smoke_runs.json", {"runs": rows, "provenance": PROV})
    if tamper is not None:
        tamper(root / RUNS / (target or (ADDED if amend else EXCLUDED)))
    commit_all(root, "SYNTHETIC benchmark")
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha="0" * 40)


def test_real_smoke_runs_pass(tmp_path: Path) -> None:
    evidence = ship_check.g6(benchmark(tmp_path / "repo"))
    assert "smoke runs for all" in evidence and "plan amendment" not in evidence


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
def test_labels_that_are_not_agents_fail(tmp_path: Path, agent: object) -> None:
    # Old code: only five exact lowercase words were refused, and null became "none".
    with pytest.raises(GateError, match="no real agent smoke run"):
        ship_check.g6(benchmark(tmp_path / "repo", agent))


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


OTHER_MODEL = "granite-3.3-8b-instruct-q4km"


def other_model(run: Path) -> None:
    """A banked run of a different model than the row's agent label says."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    edit_record(run, model=OTHER_MODEL)
    start = {"run_id": run.name, "task_id": data["task_id"], "agent": "minimal-agent"}
    write_ledger(run / "ledger.jsonl", [("run_start", {**start, "model": OTHER_MODEL})])


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


TAMPERS = [
    pytest.param(unlink_all, r"run\.json missing", id="not-banked"),
    pytest.param(retask, "does not record run", id="other-task"),
    pytest.param(edit_ledger, "hash chain broken", id="edited-ledger"),
    pytest.param(no_run_start, "does not open with the run_start", id="no-run-start"),
    pytest.param(other_model, "is not the banked", id="other-model"),
    pytest.param(models_disagree, "does not record the driver and model", id="models-disagree"),
    pytest.param(mock_model, "which is not an agent", id="mock-model"),
    pytest.param(silent_transcript, "no agent turn", id="no-agent-turn"),
    pytest.param(synthetic_start, "marked synthetic", id="synthetic-run"),
    pytest.param(other_arm, "planned task and arm", id="other-arm"),
    pytest.param(other_seed, "planned run spec", id="other-seed"),
]


@pytest.mark.parametrize(("tamper", "message"), TAMPERS)
def test_smoke_rows_must_be_banked_runs(tmp_path: Path, tamper: Tamper, message: str) -> None:
    # Old code: the summary row alone counted, with no run behind it.
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=tamper))


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


def test_a_genuine_run_of_a_plan_amendment_passes(tmp_path: Path) -> None:
    evidence = ship_check.g6(benchmark(tmp_path / "repo", amend=True))
    assert "smoke runs for all" in evidence
    assert "1 from a plan amendment, on the server it needs" in evidence


@pytest.mark.parametrize(("tamper", "message"), TAMPERS)
def test_the_amended_run_is_checked_as_every_run_is(
    tmp_path: Path, tamper: Tamper, message: str
) -> None:
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=tamper, amend=True))


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
        pytest.param(no_server, "no model server", id="no-server"),
        pytest.param(no_amendment, "plan amendment that added it", id="no-amendment"),
        pytest.param(other_amendment, "plan amendment that added it", id="other-amendment"),
    ],
)
def test_an_amended_run_not_made_on_the_server_it_needs_fails(
    tmp_path: Path, tamper: Tamper, message: str
) -> None:
    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=tamper, amend=True))


def bank_excluded(root: Path) -> None:
    """Bank a SYNTHETIC run under the id the amendment replaced."""
    plan = the_plan(False)
    bank(root, plan, EXCLUDED)


def test_the_excluded_run_stays_excluded(tmp_path: Path) -> None:
    def also_excluded(run: Path) -> None:
        bank_excluded(run.parents[4])

    with pytest.raises(GateError, match="replaced by a plan amendment"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=also_excluded, amend=True))


def test_a_smoke_run_the_plan_does_not_hold_fails(tmp_path: Path) -> None:
    def unplanned(run: Path) -> None:
        root = run.parents[4]
        plan = the_plan(True)  # a run the plan in the repository does not hold
        bank(root, plan, ADDED)
        smoke = json.loads((root / "artifacts/bench/smoke_runs.json").read_text())
        smoke["runs"].append(
            {"run_id": ADDED, "task_id": "py-synthetic-07", "agent": AGENT, "synthetic": False}
        )
        put(root, "artifacts/bench/smoke_runs.json", smoke)

    with pytest.raises(GateError, match="not a planned run"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=unplanned))


def rewrite_plan(root: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    """Edit the SYNTHETIC repository's plan.json in place."""
    data = json.loads((root / PLAN).read_text(encoding="utf-8"))
    edit(data)
    put(root, PLAN, data)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(
            lambda d: d["runs"][-1].update(seed=9), "not the planned run", id="other-seed"
        ),
        pytest.param(
            lambda d: d["amendments"].append(dict(d["amendments"][0])),
            "more than once",
            id="twice",
        ),
        pytest.param(
            lambda d: d["amendments"][0].update(replaces="smoke-py-synthetic-99"),
            "not a planned run",
            id="unplanned",
        ),
        pytest.param(
            lambda d: d["amendments"][0]["server"].update(min_n_ctx_per_slot="32768"),
            "server requirement",
            id="window-not-a-number",
        ),
        pytest.param(lambda d: d.update(amendments={}), "amendments", id="not-a-list"),
        pytest.param(lambda d: d["runs"].append(d["runs"][0]), "repeats", id="repeated-run"),
    ],
)
def test_a_plan_whose_amendment_does_not_hold_fails(
    tmp_path: Path, edit: Callable[[dict[str, Any]], None], message: str
) -> None:
    def broken_plan(run: Path) -> None:
        rewrite_plan(run.parents[4], edit)

    with pytest.raises(GateError, match=message):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=broken_plan, amend=True))


def test_a_missing_smoke_plan_fails(tmp_path: Path) -> None:
    def no_plan(run: Path) -> None:
        (run.parents[4] / PLAN).unlink()

    with pytest.raises(GateError, match=r"plan\.json missing"):
        ship_check.g6(benchmark(tmp_path / "repo", tamper=no_plan))


@pytest.mark.parametrize("change", ["edit", "delete"])
def test_a_banked_smoke_run_changed_after_it_was_committed_fails(
    tmp_path: Path, change: str
) -> None:
    # DECISIONS D62: a banked run is never changed or removed. A later commit that
    # rewrites a run's record (here, to a consistent one) or deletes it fails G6.
    ctx = benchmark(tmp_path / "repo", amend=True)
    run = ctx.clone / RUNS / ADDED
    if change == "edit":
        edit_record(run, turns=99)
    else:
        (run / "transcript.json").unlink()
    commit_all(ctx.clone, "SYNTHETIC later change")
    with pytest.raises(GateError, match="later changed or deleted"):
        ship_check.g6(ctx)
