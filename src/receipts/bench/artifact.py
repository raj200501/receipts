"""The reference-validation artifact that gate G6 reads.

``artifacts/bench/reference_validation.json`` holds one entry per task, keyed by task
id, with the task tree hash and ``hidden_passed`` (true only for a complete validation
in which every expectation held), plus the whole validation record as evidence::

    {
      "schema": "receipts.bench.reference_validation/1",
      "tasks": {"<id>": {"tree_sha256": "...", "hidden_passed": true, ...}},
      "summary": {"tasks": 4, "valid": 4, "invalid": []},
      "provenance": {"git_sha": "...", "command": "...", "created": "...", ...}
    }

``tools/ship_check.py`` recomputes every task's tree hash from a fresh clone, so an
entry is only good for the exact task files it was made from. :func:`check_artifact`
applies the same rules offline, so an author can see whether the banked artifact is
still current without running anything.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from receipts.bench.hashing import tree_sha256
from receipts.bench.spec import TaskSpec, TaskSpecError, load_task, task_dirs
from receipts.bench.validate import SandboxFactory, TaskValidation, spec_failure, validate_task

SCHEMA = "receipts.bench.reference_validation/1"
ARTIFACT_PATH = "artifacts/bench/reference_validation.json"
REQUIRED_PROVENANCE: tuple[str, ...] = ("git_sha", "command", "created")


def validate_all(
    tasks: Sequence[Path],
    factory_for: Callable[[TaskSpec], SandboxFactory],
    *,
    project_root: Path | None = None,
    jobs: int = 1,
    progress: Callable[[TaskValidation], None] | None = None,
    **options: Any,
) -> list[TaskValidation]:
    """Validate every task directory, ``jobs`` tasks at a time.

    Args:
        tasks: Task directories (``bench/tasks/<id>``).
        factory_for: Returns the sandbox factory for one loaded task (so each task can
            get the sandbox policy it needs, such as :attr:`TaskSpec.memory_mb`).
        project_root: The repository root (shared prompt files are relative to it).
        jobs: How many tasks run at once (each in its own workspaces).
        progress: Called with each result as soon as it is ready.
        **options: Passed to :func:`receipts.bench.validate.validate_task`.

    Returns:
        The results in the order of ``tasks``; a task that does not load is a result
        with failed ``spec`` steps.

    Raises:
        ValueError: ``jobs`` is less than 1.
    """
    if jobs < 1:
        raise ValueError("jobs must be at least 1")

    def one(task_dir: Path) -> TaskValidation:
        try:
            task = load_task(task_dir, project_root)
        except TaskSpecError as exc:
            result = spec_failure(task_dir, exc)
        else:
            result = validate_task(task, factory_for(task), **options)
        if progress is not None:
            progress(result)
        return result

    if jobs == 1:
        return [one(task) for task in tasks]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, tasks))


def build_artifact(
    results: Sequence[TaskValidation], provenance: Mapping[str, Any]
) -> dict[str, Any]:
    """The artifact for ``results`` (see the module docstring).

    Raises:
        ValueError: Two results share a task id, or ``provenance`` lacks one of
            :data:`REQUIRED_PROVENANCE`.
    """
    missing = [key for key in REQUIRED_PROVENANCE if not provenance.get(key)]
    if missing:
        raise ValueError(f"provenance lacks {', '.join(missing)}")
    ids = [result.task_id for result in results]
    duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate task ids: {', '.join(duplicates)}")
    ordered = sorted(results, key=lambda result: result.task_id)
    invalid = [result.task_id for result in ordered if not result.valid]
    return {
        "schema": SCHEMA,
        "tasks": {result.task_id: result.to_dict() for result in ordered},
        "summary": {
            "tasks": len(ordered),
            "valid": len(ordered) - len(invalid),
            "invalid": invalid,
        },
        "provenance": dict(provenance),
    }


def write_artifact(data: Mapping[str, Any], path: Path) -> None:
    """Write the artifact as indented JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_artifact(data: Any, tasks_dir: Path) -> list[str]:
    """Problems that gate G6 would find with this artifact for the tasks under ``tasks_dir``.

    Every task directory needs an entry whose ``hidden_passed`` is true and whose
    ``tree_sha256`` matches the current files; the artifact needs the provenance keys.
    Returns an empty list when the artifact is current.
    """
    if not isinstance(data, dict):
        return ["the artifact is not a JSON object"]
    problems: list[str] = []
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        problems.append("no provenance")
    else:
        problems.extend(
            f"provenance lacks {key}" for key in REQUIRED_PROVENANCE if not provenance.get(key)
        )
    entries = data.get("tasks")
    if not isinstance(entries, dict):
        return [*problems, "no tasks mapping"]
    for task in task_dirs(tasks_dir):
        entry = entries.get(task.name)
        if not isinstance(entry, dict):
            problems.append(f"{task.name}: not validated")
        elif entry.get("hidden_passed") is not True:
            problems.append(f"{task.name}: validation did not pass")
        elif entry.get("tree_sha256") != tree_sha256(task):
            problems.append(f"{task.name}: task files changed since the validation")
    return problems


def load_artifact(path: Path) -> Any:
    """Read an artifact file (raises OSError or json.JSONDecodeError)."""
    return json.loads(path.read_text(encoding="utf-8"))
