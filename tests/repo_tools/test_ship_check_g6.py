"""Gate G6 of tools/ship_check.py on a synthetic benchmark (H17, with the G5 part in H20).

Every task, reference validation, banked smoke run, and smoke-run row here is SYNTHETIC,
made up only to exercise ``ship_check.g6``. Smoke rows are marked ``synthetic: false``
only so the gate treats them as real runs; nothing here is a model result or a
real-world result.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import ship_check
from receipts.bench.hashing import tree_sha256
from receipts.ledger.events import GENESIS, Event

GateError = ship_check.GateError
MODEL = "qwen2.5-coder-7b-instruct-q4km"
AGENT = f"minimal-agent/{MODEL}"
PROV = {
    "git_sha": "0" * 40,
    "command": "SYNTHETIC test fixture",
    "created": "2026-11-04T00:00:00+00:00",
}
N_TASKS = 30
RUNS = "artifacts/studies/smoke/runs"
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


def bank(root: Path, run_id: str, task_id: str) -> None:
    """Bank one SYNTHETIC smoke run: run.json, its ledger, and its transcript."""
    put(root, f"{RUNS}/{run_id}/run.json", {"run_id": run_id, "task_id": task_id, "model": MODEL})
    start = {"run_id": run_id, "task_id": task_id, "agent": "minimal-agent", "model": MODEL}
    write_ledger(root / RUNS / run_id / "ledger.jsonl", [("run_start", start)])
    messages = [
        {"role": "user", "content": "SYNTHETIC task"},
        {"role": "assistant", "content": "{}"},
    ]
    put(root, f"{RUNS}/{run_id}/transcript.json", {"messages": messages})


def benchmark(
    root: Path, agent: object = AGENT, tamper: Tamper | None = None
) -> ship_check.Context:
    """Thirty SYNTHETIC tasks with validated references and one banked smoke run each."""
    validated = {}
    rows = []
    for i in range(N_TASKS):
        tid = f"py-synthetic-{i:02d}"
        task = f"bench/tasks/{tid}"
        put(root, f"{task}/task.toml", f'id = "{tid}"\nlanguage = "python"\n')
        put(root, f"{task}/hidden/test_hidden.py", "def test_ok():\n    assert True\n")
        put(root, f"{task}/reference/fix.py", "VALUE = 1\n")
        put(root, f"{task}/manifest.json", {"manipulations": {"M1": "synthetic overlay"}})
        validated[tid] = {"tree_sha256": tree_sha256(root / task), "hidden_passed": True}
        rows.append({"run_id": f"smoke-{tid}", "task_id": tid, "agent": agent, "synthetic": False})
        bank(root, f"smoke-{tid}", tid)
    put(root, "artifacts/bench/reference_validation.json", {"tasks": validated, "provenance": PROV})
    put(root, "artifacts/bench/smoke_runs.json", {"runs": rows, "provenance": PROV})
    if tamper is not None:
        tamper(root / RUNS / "smoke-py-synthetic-07")
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha="0" * 40)


def test_real_smoke_runs_pass(tmp_path: Path) -> None:
    assert "smoke runs for all" in ship_check.g6(benchmark(tmp_path / "repo"))


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


def retask(run: Path) -> None:
    """Make run.json record another task."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    put(run, "run.json", {**data, "task_id": "py-synthetic-08"})


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
    put(run, "run.json", {**data, "model": OTHER_MODEL})
    start = {"run_id": run.name, "task_id": data["task_id"], "agent": "minimal-agent"}
    write_ledger(run / "ledger.jsonl", [("run_start", {**start, "model": OTHER_MODEL})])


def models_disagree(run: Path) -> None:
    """run.json names another model than its ledger's run_start (review-1)."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    put(run, "run.json", {**data, "model": OTHER_MODEL})


def mock_model(run: Path) -> None:
    """A banked run whose ledger and run.json both name a mock model (review-1)."""
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    put(run, "run.json", {**data, "model": "mock"})
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


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        pytest.param(unlink_all, r"run\.json missing", id="not-banked"),
        pytest.param(retask, "does not record run", id="other-task"),
        pytest.param(edit_ledger, "hash chain broken", id="edited-ledger"),
        pytest.param(no_run_start, "does not open with the run_start", id="no-run-start"),
        pytest.param(other_model, "is not the banked", id="other-model"),
        pytest.param(models_disagree, "does not record the driver and model", id="models-disagree"),
        pytest.param(mock_model, "which is not an agent", id="mock-model"),
        pytest.param(silent_transcript, "no agent turn", id="no-agent-turn"),
        pytest.param(synthetic_start, "marked synthetic", id="synthetic-run"),
    ],
)
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
