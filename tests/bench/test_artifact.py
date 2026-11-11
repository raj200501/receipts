"""Tests for receipts.bench.artifact: the G6 reference-validation artifact.

The tasks here are the synthetic toy task from tests/bench/factory.py (test data), run
in the subprocess-backed fake sandbox, and hand-made TaskValidation records.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

import ship_check
from receipts.bench import artifact
from receipts.bench.hashing import tree_sha256
from receipts.bench.validate import PHASES, TaskValidation

from .factory import TASK_TOML, build_task
from .fakes import factory

PROVENANCE = {"git_sha": "0" * 40, "command": "python tools/bench_validate.py", "created": "now"}


def _record(task_id: str, ok: bool, digest: str = "0" * 64) -> TaskValidation:
    """A hand-made validation record (synthetic test data)."""
    result = TaskValidation(task_id=task_id, tree_sha256=digest, repeats=2)
    result.phases_run = PHASES if ok else ()
    result.add("layout", ok, "" if ok else "broken")
    return result


def test_validate_all_keeps_the_task_order_and_reports_progress(tmp_path: Path) -> None:
    project = tmp_path / "project"
    good = build_task(project)
    broken_toml = TASK_TOML.replace('id = "py-toy-greet"', 'id = "py-toy-broken"').replace(
        'category = "feature"', 'category = "chore"'
    )
    broken = build_task(project, task_id="py-toy-broken", overrides={"task.toml": broken_toml})
    seen: list[str] = []
    lock = threading.Lock()

    def progress(result: TaskValidation) -> None:
        with lock:
            seen.append(result.task_id)

    results = artifact.validate_all(
        [good, broken],
        lambda task: factory(),
        project_root=project,
        jobs=2,
        progress=progress,
        phases={"m1"},
        work_root=tmp_path / "work",
    )
    assert [result.task_id for result in results] == ["py-toy-greet", "py-toy-broken"]
    assert sorted(seen) == ["py-toy-broken", "py-toy-greet"]
    assert results[0].phases_run == ("m1",)
    assert {step.name for step in results[1].steps} == {"spec"}
    sequential = artifact.validate_all([broken], lambda task: factory(), project_root=project)
    assert sequential[0].task_id == "py-toy-broken"


def test_validate_all_needs_at_least_one_job() -> None:
    with pytest.raises(ValueError, match="jobs"):
        artifact.validate_all([], lambda task: factory(), jobs=0)


def test_build_artifact_has_the_g6_fields() -> None:
    data = artifact.build_artifact([_record("b", True), _record("a", False)], PROVENANCE)
    assert data["schema"] == artifact.SCHEMA
    assert list(data["tasks"]) == ["a", "b"]
    assert data["tasks"]["b"]["hidden_passed"] is True
    assert data["tasks"]["a"]["hidden_passed"] is False
    assert data["summary"] == {"tasks": 2, "valid": 1, "invalid": ["a"]}
    assert data["provenance"] == PROVENANCE
    ship_check.require_provenance("artifact", data)


def test_build_artifact_rejects_missing_provenance_and_duplicates() -> None:
    with pytest.raises(ValueError, match="provenance lacks git_sha, created"):
        artifact.build_artifact([], {"command": "x"})
    with pytest.raises(ValueError, match="duplicate task ids: a"):
        artifact.build_artifact([_record("a", True), _record("a", False)], PROVENANCE)


def test_write_and_check_an_artifact_like_ship_check(tmp_path: Path) -> None:
    task = build_task(tmp_path / "project")
    tasks_dir = task.parent
    result = _record("py-toy-greet", True, tree_sha256(task))
    path = tmp_path / "out" / "reference_validation.json"
    artifact.write_artifact(artifact.build_artifact([result], PROVENANCE), path)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    data = artifact.load_artifact(path)
    assert artifact.check_artifact(data, tasks_dir) == []
    entry = data["tasks"]["py-toy-greet"]
    assert entry["hidden_passed"] is True
    assert entry["tree_sha256"] == ship_check.tree_sha256(task)
    (task / "repo" / "README.md").write_text("changed\n", encoding="utf-8")
    assert artifact.check_artifact(data, tasks_dir) == [
        "py-toy-greet: task files changed since the validation"
    ]


def test_check_artifact_problems(tmp_path: Path) -> None:
    tasks_dir = build_task(tmp_path / "project").parent
    assert artifact.check_artifact([], tasks_dir) == ["the artifact is not a JSON object"]
    assert artifact.check_artifact({"tasks": {}}, tasks_dir) == [
        "no provenance",
        "py-toy-greet: not validated",
    ]
    partial = {"provenance": {"git_sha": "x"}, "tasks": "nope"}
    assert artifact.check_artifact(partial, tasks_dir) == [
        "provenance lacks command",
        "provenance lacks created",
        "no tasks mapping",
    ]
    failed = {"provenance": PROVENANCE, "tasks": {"py-toy-greet": {"hidden_passed": False}}}
    assert artifact.check_artifact(failed, tasks_dir) == ["py-toy-greet: validation did not pass"]


def test_load_artifact_raises_on_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        artifact.load_artifact(path)
