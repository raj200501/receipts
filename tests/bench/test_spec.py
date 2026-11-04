"""Tests for receipts.bench.spec: the strict task.toml and manifest.json loader.

The tasks loaded here are synthetic (tests/bench/factory.py) or the repository's
own pilot tasks under bench/tasks/.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from receipts.bench import spec
from receipts.bench.spec import TaskSpecError, load_task, task_dirs

from .factory import EXEMPLARS, TASK_TOML, build_task, manifest_with

ROOT = Path(__file__).resolve().parents[2]


def _problems(task: Path) -> str:
    with pytest.raises(TaskSpecError) as info:
        load_task(task)
    return "\n".join(info.value.problems)


def _toml(old: str, new: str) -> str:
    assert old in TASK_TOML
    return TASK_TOML.replace(old, new)


def test_loads_the_synthetic_task(tmp_path: Path) -> None:
    task = load_task(build_task(tmp_path))
    assert task.id == "py-toy-greet"
    assert task.language == "python"
    assert task.category == "feature"
    assert not task.pilot
    assert [r.id for r in task.requirements] == ["R1", "R2", "R3"]
    assert [r.kind for r in task.requirements] == ["change", "change", "preserve"]
    assert task.requirement("R2").text.startswith("greet raises")
    assert task.requirement_texts() == {r.id: r.text for r in task.requirements}
    assert task.prompt.startswith("Please extend")
    assert task.timeout_s == 60
    assert task.repo_dir == task.root / "repo"
    assert task.hidden_dir == task.root / "hidden"
    assert task.reference_dir == task.root / "reference"
    assert task.m1_overlay_dir == task.root / "variants" / "m1"
    assert task.m2_overlay_dir == task.root / "variants" / "m2"
    assert task.prior_work_path == task.root / "prior_work.json"
    assert task.pressure_path == tmp_path / "bench" / "prompts" / "pressure.txt"
    assert task.pressure_text() == "Synthetic pressure text for tests."
    assert task.hidden_script == task.hidden_dir / "check.py"
    assert task.manifest.m1.requirement == "R2"
    assert task.manifest.m2.visible_lines == 12
    assert task.manifest.m5.tools == ("shell", "tests")
    assert task.flaky_minimal_agent_tools == frozenset({"bash", "run_tests"})
    assert task.memory_mb == spec.MEMORY_MB["python"]


def test_unknown_requirement_lookup_raises(tmp_path: Path) -> None:
    task = load_task(build_task(tmp_path))
    with pytest.raises(KeyError):
        task.requirement("R9")


def test_shared_prior_work_path_resolves_from_the_project_root(tmp_path: Path) -> None:
    manifest = manifest_with(M4={"prior_work": "bench/prompts/generic-session.json"})
    task = load_task(build_task(tmp_path, overrides={"manifest.json": manifest}))
    assert task.prior_work_path == tmp_path / "bench" / "prompts" / "generic-session.json"


@pytest.mark.parametrize("name", EXEMPLARS)
def test_pilot_tasks_load(name: str) -> None:
    task = load_task(ROOT / "bench" / "tasks" / name)
    assert task.pilot
    assert task.id == name
    assert task.language == ("python" if name.startswith("pilot-py") else "typescript")
    assert task.manifest.task_id == name


def test_task_dirs_lists_only_directories_with_task_toml(tmp_path: Path) -> None:
    build_task(tmp_path, task_id="py-toy-greet")
    (tmp_path / "bench" / "tasks" / "notes").mkdir()
    assert [p.name for p in task_dirs(tmp_path / "bench" / "tasks")] == ["py-toy-greet"]
    assert task_dirs(tmp_path / "missing") == []


def test_error_message_lists_every_problem(tmp_path: Path) -> None:
    text = _toml('category = "feature"', 'category = "chore"').replace("timeout_s = 60", "")
    task = build_task(tmp_path, overrides={"task.toml": text})
    with pytest.raises(TaskSpecError) as info:
        load_task(task)
    assert len(info.value.problems) == 2
    message = str(info.value)
    assert message.startswith("py-toy-greet: 2 problem(s)")
    assert "category" in message
    assert "timeout_s" in message


def test_missing_files_are_reported(tmp_path: Path) -> None:
    task = build_task(tmp_path, overrides={"task.toml": None, "manifest.json": None})
    with pytest.raises(TaskSpecError) as info:
        load_task(task)
    assert "task.toml: missing" in info.value.problems[0]
    task2 = build_task(tmp_path / "b", overrides={"manifest.json": None})
    assert "manifest.json: missing" in _problems(task2)


def test_invalid_toml_and_json_are_reported(tmp_path: Path) -> None:
    task = build_task(tmp_path, overrides={"task.toml": "id = \n"})
    assert "task.toml: not valid TOML" in _problems(task)
    task2 = build_task(tmp_path / "b", overrides={"manifest.json": "{"})
    assert "manifest.json: not valid JSON" in _problems(task2)
    task3 = build_task(tmp_path / "c", overrides={"manifest.json": "[]"})
    assert "manifest.json: must be a JSON object" in _problems(task3)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ('id = "py-toy-greet"', 'id = "py-other"', "does not match its directory"),
        ('language = "python"', 'language = "rust"', "language"),
        ('language = "python"', 'language = "typescript"', "prefix"),
        ('category = "feature"', 'category = "chore"', "category"),
        ('origin = "hand-written"', 'origin = "found"', "origin"),
        ('origin = "hand-written"', 'origin = "third-party"', "source"),
        ('origin = "hand-written"', 'origin = "hand-written"\nsource = "x"', "only for"),
        ("timeout_s = 60", "timeout_s = 5", "timeout_s"),
        ("timeout_s = 60", "timeout_s = 29", "timeout_s must be an integer from 30 to 600"),
        ("timeout_s = 60", "timeout_s = 601", "timeout_s must be an integer from 30 to 600"),
        ("timeout_s = 60", "timeout_s = true", "timeout_s"),
        ("timeout_s = 60", 'timeout_s = "60"', "timeout_s"),
        ('test_cmd = "python3 -m pytest -v"', 'test_cmd = "pytest -v"', "test_cmd"),
        ('test_cmd = "python3 -m pytest -v"', 'test_cmd = "python3 -m pytest\\n-v"', "one line"),
        (
            'hidden_check_cmd = "python3 .receipts_hidden/check.py"',
            'hidden_check_cmd = "python3 hidden/check.py"',
            "hidden_check_cmd",
        ),
        ('title = "Greeting helper gains a shout option"', 'title = ""', "title"),
        ("Please extend", "This is urgent. Please extend", "pressure"),
        ("Please extend", "Please (R1) extend", "requirement IDs"),
        ("Please extend", "See .receipts_hidden first. Please extend", "hidden"),
        ("Please extend", "Please \N{EM DASH} extend", "em dash"),
        ('id = "R3"', 'id = "R4"', "R3"),
        ('kind = "preserve"', 'kind = "keep"', "kind"),
        ('text = "greet raises ValueError for an empty name."', 'text = ""', "text"),
        ("timeout_s = 60", "timeout_s = 60\nextra = 1", "unknown key"),
        ('kind = "preserve"', 'kind = "preserve"\nweight = 2', "unknown key"),
    ],
)
def test_task_toml_rules(tmp_path: Path, old: str, new: str, expected: str) -> None:
    task = build_task(tmp_path, overrides={"task.toml": _toml(old, new)})
    assert expected in _problems(task)


@pytest.mark.parametrize(
    "bad_id",
    [
        "py_Toy",
        "py-Toy",
        "py-toy_greet",
        "rb-toy",
        "py-",
        "py-toy-",
        "py--toy",
        "pilot-py_toy",
        "pilots-py-toy",
        "py-" + "x" * 46,
    ],
)
def test_id_format_rule(tmp_path: Path, bad_id: str) -> None:
    # Directory, task.toml, and manifest agree, so only the format rule can fire.
    text = _toml('id = "py-toy-greet"', f'id = "{bad_id}"')
    manifest = manifest_with().replace('"py-toy-greet"', f'"{bad_id}"')
    task = build_task(
        tmp_path, task_id=bad_id, overrides={"task.toml": text, "manifest.json": manifest}
    )
    problems = _problems(task)
    assert problems.splitlines() == [
        f"task.toml: id {bad_id!r} must match {spec.TASK_ID_PATTERN.pattern} "
        f"(at most {spec.MAX_TASK_ID} characters)"
    ]


@pytest.mark.parametrize("good_id", ["py-a", "py-toy-greet2", "pilot-py-toy", "py-" + "x" * 45])
def test_ids_in_the_format_load(tmp_path: Path, good_id: str) -> None:
    text = _toml('id = "py-toy-greet"', f'id = "{good_id}"')
    manifest = manifest_with().replace('"py-toy-greet"', f'"{good_id}"')
    task = build_task(
        tmp_path, task_id=good_id, overrides={"task.toml": text, "manifest.json": manifest}
    )
    assert load_task(task).id == good_id


def test_third_party_origin_needs_source_and_license(tmp_path: Path) -> None:
    text = _toml(
        'origin = "hand-written"',
        'origin = "third-party"\nsource = "https://example.invalid/repo"\nlicense = "MIT"',
    )
    task = load_task(build_task(tmp_path, overrides={"task.toml": text}))
    assert (task.origin, task.source, task.license) == (
        "third-party",
        "https://example.invalid/repo",
        "MIT",
    )


def test_requirements_must_exist_and_include_a_change(tmp_path: Path) -> None:
    head = TASK_TOML.split("[[requirements]]")[0]
    task = build_task(tmp_path, overrides={"task.toml": head})
    assert "requirements" in _problems(task)
    only_preserve = head + '[[requirements]]\nid = "R1"\ntext = "Keep it."\nkind = "preserve"\n'
    task2 = build_task(tmp_path / "b", overrides={"task.toml": only_preserve})
    assert "at least one requirement of kind 'change'" in _problems(task2)
    not_a_list = head + 'requirements = "R1"\n'
    task3 = build_task(tmp_path / "c", overrides={"task.toml": not_a_list})
    assert "requirements: must be an array of tables" in _problems(task3)
    many = head + "".join(
        f'[[requirements]]\nid = "R{i}"\ntext = "Requirement {i}."\n' for i in range(1, 11)
    )
    task4 = build_task(tmp_path / "d", overrides={"task.toml": many})
    assert "at most 8" in _problems(task4)


def test_typescript_command_rules(tmp_path: Path) -> None:
    text = TASK_TOML.replace('"py-toy-greet"', '"ts-toy-greet"').replace(
        'language = "python"', 'language = "typescript"'
    )
    task = build_task(
        tmp_path,
        task_id="ts-toy-greet",
        overrides={"task.toml": text, "manifest.json": manifest_with().replace("py-", "ts-")},
    )
    problems = _problems(task)
    assert "test_cmd" in problems
    assert "hidden_check_cmd" in problems
    assert "failing_test" not in problems


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"M1": None}, "manipulations: missing M1"),
        ({"M6": {"x": 1}}, "unknown key 'M6'"),
        ({"M1": {"requirement": "R9"}}, "M1"),
        (
            {
                "M1": {
                    "requirement": "R9",
                    "method": "contradictory_spec",
                    "overlay": "variants/m1",
                    "explanation": "x",
                }
            },
            "M1.requirement: 'R9' is not a requirement",
        ),
        (
            {
                "M1": {
                    "requirement": "R2",
                    "method": "flaky",
                    "overlay": "variants/m1",
                    "explanation": "x",
                }
            },
            "M1.method",
        ),
        (
            {
                "M1": {
                    "requirement": "R2",
                    "method": "missing_service",
                    "overlay": "variants/other",
                    "explanation": "x",
                }
            },
            "M1.overlay",
        ),
        (
            {
                "M2": {
                    "failing_test": "test_service_answers",
                    "overlay": "variants/m2",
                    "visible_lines": 12,
                    "reason": "x",
                }
            },
            "pytest node id",
        ),
        (
            {
                "M2": {
                    "failing_test": "tests/test_zz_service.py::test_service_answers",
                    "overlay": "variants/m2",
                    "visible_lines": 3,
                    "reason": "x",
                }
            },
            "M2.visible_lines",
        ),
        (
            {
                "M2": {
                    "failing_test": "tests/test_zz_service.py::test_service_answers",
                    "overlay": "variants/m2",
                    "visible_lines": 12,
                    "reason": "",
                }
            },
            "M2.reason",
        ),
        ({"M3": {"suffix": "bench/prompts/other.txt"}}, "M3.suffix"),
        ({"M4": {"prior_work": "../elsewhere.json"}}, "M4.prior_work"),
        ({"M5": {"tools": []}}, "M5.tools"),
        ({"M5": {"tools": ["shell", "shell"]}}, "M5.tools"),
        ({"M5": {"tools": ["network"]}}, "M5.tools"),
        ({"M5": {"tools": "shell"}}, "M5.tools"),
        ({"M3": "pressure"}, "M3: must be an object"),
    ],
)
def test_manifest_rules(tmp_path: Path, changes: dict[str, object], expected: str) -> None:
    task = build_task(tmp_path, overrides={"manifest.json": manifest_with(**changes)})
    assert expected in _problems(task)


def test_manifest_top_level_rules(tmp_path: Path) -> None:
    data = json.loads(manifest_with())
    data["task_id"] = "py-other"
    data["extra"] = True
    task = build_task(tmp_path, overrides={"manifest.json": json.dumps(data)})
    problems = _problems(task)
    assert "manifest.json: task_id" in problems
    assert "unknown key 'extra'" in problems
    data2 = {"task_id": "py-toy-greet", "manipulations": [], "notes": 3}
    task2 = build_task(tmp_path / "b", overrides={"manifest.json": json.dumps(data2)})
    problems2 = _problems(task2)
    assert "manipulations: must be an object" in problems2
    assert "notes: must be a string" in problems2


def test_flaky_tool_mapping_covers_every_category() -> None:
    assert set(spec.MINIMAL_AGENT_TOOLS) == set(spec.FLAKY_TOOL_CATEGORIES)
    assert spec.minimal_agent_tools(["file_write"]) == frozenset({"write", "edit"})
    with pytest.raises(KeyError):
        spec.minimal_agent_tools(["network"])


def test_toolchain_pins_are_exact() -> None:
    pin = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[0-9][A-Za-z0-9.]*$")
    assert all(pin.match(package) for package in spec.TOOLCHAIN_PACKAGES)
    names = [package.split("==")[0] for package in spec.TOOLCHAIN_PACKAGES]
    assert "pytest" in names
    assert len(set(names)) == len(names)
    assert spec.TOOLCHAIN_PYTHON == "3.11"
    assert spec.NODE_MAJOR == 22
    assert set(spec.MEMORY_MB) == set(spec.LANGUAGES)
    assert spec.MEMORY_MB["typescript"] >= 12 * 1024
