"""Adapt receipts-bench tasks (``receipts.bench.spec``) to what the study runner needs."""

from __future__ import annotations

from pathlib import Path

from receipts.bench.priorwork import load_prior_work, render_messages
from receipts.bench.spec import TaskSpec, load_task
from receipts.study.spec import RunTask


def run_task_from_spec(spec: TaskSpec) -> RunTask:
    """The runner's view of a loaded benchmark task, with every manipulation resolved."""
    return RunTask(
        task_id=spec.id,
        prompt=spec.prompt,
        test_cmd=spec.test_cmd,
        hidden_check_cmd=spec.hidden_check_cmd,
        repo_dir=spec.repo_dir,
        hidden_dir=spec.hidden_dir,
        unattainable_overlay=spec.m1_overlay_dir,
        failing_test_overlay=spec.m2_overlay_dir,
        failing_test_visible_lines=spec.manifest.m2.visible_lines,
        prior_work=render_messages(load_prior_work(spec.prior_work_path)),
        requirements=spec.requirement_texts(),
        command_timeout_s=float(spec.timeout_s),
        flaky_tools=spec.flaky_minimal_agent_tools,
    )


def load_run_task(task_dir: Path) -> RunTask:
    """Load and validate a benchmark task directory for the runner."""
    return run_task_from_spec(load_task(task_dir))
