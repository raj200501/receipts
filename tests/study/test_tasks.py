"""The runner's view of benchmark tasks (receipts.study.tasks)."""

from __future__ import annotations

from pathlib import Path

import pytest

from receipts.bench.spec import MEMORY_MB, load_task
from receipts.study.tasks import load_run_task, run_task_from_spec

TASKS = Path(__file__).resolve().parents[2] / "bench" / "tasks"


@pytest.mark.parametrize(
    ("task_id", "language"),
    [("pilot-py-timesheet", "python"), ("pilot-ts-feedsync", "typescript")],
)
def test_run_task_carries_every_manipulation_and_limit(task_id: str, language: str) -> None:
    spec = load_task(TASKS / task_id)
    task = run_task_from_spec(spec)
    assert task.task_id == task_id
    assert task.prompt == spec.prompt
    assert task.test_cmd == spec.test_cmd
    assert task.hidden_check_cmd == spec.hidden_check_cmd
    assert task.unattainable_overlay == spec.m1_overlay_dir
    assert task.failing_test_overlay == spec.m2_overlay_dir
    assert task.failing_test_visible_lines == spec.manifest.m2.visible_lines
    assert task.prior_work, "M4 long level needs prior work"
    assert task.requirements == spec.requirement_texts()
    assert task.command_timeout_s == float(spec.timeout_s)
    assert task.flaky_tools == spec.flaky_minimal_agent_tools
    assert task.memory_mb == MEMORY_MB[language]


def test_typescript_tasks_get_the_larger_address_space() -> None:
    py = load_run_task(TASKS / "pilot-py-timesheet")
    ts = load_run_task(TASKS / "pilot-ts-feedsync")
    assert ts.memory_mb > py.memory_mb
