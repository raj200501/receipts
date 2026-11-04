"""Tests for receipts.bench.validate: reference validation through a Sandbox.

The tasks validated here are the synthetic toy task from tests/bench/factory.py (broken
one way at a time, which is synthetic test data) and the repository's own pilot tasks.
Every command runs in the subprocess-backed fake sandbox from tests/bench/fakes.py, in
workspaces under pytest's ``tmp_path``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Collection, Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from receipts.bench import validate
from receipts.bench.hashing import tree_sha256
from receipts.bench.priorwork import PriorWorkError
from receipts.bench.spec import load_task
from receipts.bench.validate import (
    PHASES,
    HiddenSummary,
    PhaseError,
    SuiteSummary,
    TaskValidation,
    first_failure_line,
    overlay,
    validate_path,
    validate_task,
)
from receipts.sandbox.api import CommandOutcome, Sandbox

from .factory import (
    GREET_SOLVED,
    HIDDEN_CASES,
    M2_TEST,
    MANIFEST,
    TASK_TOML,
    build_task,
    manifest_with,
    prior_work,
)
from .fakes import SubprocessSandbox, factory

ROOT = Path(__file__).resolve().parents[2]
PILOTS = ("pilot-py-bizdays", "pilot-py-timesheet", "pilot-ts-feedsync", "pilot-ts-gradebook")


def _validate(
    tmp_path: Path,
    overrides: Mapping[str, str | None] | None = None,
    *,
    phases: Collection[str] | None = None,
    tests: int = 16,
) -> TaskValidation:
    task = load_task(build_task(tmp_path / "project", overrides=overrides, tests=tests))
    return validate_task(task, factory(), phases=phases, work_root=tmp_path / "work")


def _step(result: TaskValidation, name: str) -> validate.Step:
    matches = [step for step in result.steps if step.name == name]
    assert len(matches) == 1, [step.name for step in result.steps]
    return matches[0]


def _failed(result: TaskValidation) -> list[str]:
    return [step.name for step in result.steps if not step.ok]


def _hidden_script(checks: list[dict[str, object]], status: int) -> str:
    """A hidden check entry script that prints a fixed result (synthetic test data)."""
    return (
        "import json\nimport sys\n\n"
        f"print('log line')\nprint(json.dumps({{'checks': {checks!r}}}))\nsys.exit({status})\n"
    )


# The synthetic task, end to end -------------------------------------------------------


def test_synthetic_task_is_valid(tmp_path: Path) -> None:
    task_dir = build_task(tmp_path / "project")
    result = validate_task(load_task(task_dir), factory(), work_root=tmp_path / "work")
    assert result.valid, result.problems
    assert result.complete
    assert result.phases_run == PHASES
    assert result.repeats == 2
    assert result.tree_sha256 == tree_sha256(task_dir)
    assert (result.task_id, result.language, result.category) == (
        "py-toy-greet",
        "python",
        "feature",
    )
    assert not result.pilot
    assert result.problems == []
    assert result.phases["reference"]["replaces"] == ["src/toy/greet.py"]
    assert result.phases["reference"]["adds"] == []
    assert result.phases["m2_start"]["truncation"]["visible_lines"] == 12
    assert len(result.phases["reference"]["tests"]) == 2
    assert len(result.phases["reference"]["hidden"]) == 2
    data = result.to_dict()
    assert data["hidden_passed"] is True
    assert data["valid"] is True
    assert data["tree_sha256"] == result.tree_sha256
    assert data["phases_run"] == list(PHASES)
    assert {step["name"] for step in data["steps"]} >= {"layout", "reference.hidden_pass"}
    json.dumps(data)
    assert not (tmp_path / "work" / "py-toy-greet-baseline").exists()


def test_workspaces_can_be_kept_for_inspection(tmp_path: Path) -> None:
    task = load_task(build_task(tmp_path / "project"))
    validate_task(
        task, factory(), phases={"baseline"}, work_root=tmp_path / "work", keep_workspaces=True
    )
    kept = tmp_path / "work" / "py-toy-greet-baseline"
    assert (kept / ".git").is_dir()
    assert (kept / ".receipts_hidden" / "check.py").is_file()


def test_default_work_root_is_a_removed_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[Path] = []
    real = tempfile.mkdtemp

    def mkdtemp(prefix: str = "") -> str:
        path = real(prefix=prefix, dir=tmp_path)
        made.append(Path(path))
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    task = load_task(build_task(tmp_path / "project"))
    result = validate_task(task, factory(), phases={"m1"})
    assert _failed(result) == []
    assert len(made) == 1
    assert not made[0].exists()


def test_partial_validation_is_never_valid(tmp_path: Path) -> None:
    result = _validate(tmp_path, phases={"baseline"})
    assert _failed(result) == []
    assert not result.complete
    assert not result.valid
    assert result.to_dict()["hidden_passed"] is False


def test_single_repeat_is_not_complete(tmp_path: Path) -> None:
    task = load_task(build_task(tmp_path / "project"))
    result = validate_task(task, factory(), phases={"reference"}, repeats=1, work_root=tmp_path)
    assert result.repeats == 1
    assert not result.complete


def test_bad_arguments_are_rejected(tmp_path: Path) -> None:
    task = load_task(build_task(tmp_path / "project"))
    with pytest.raises(ValueError, match="unknown phases: smoke"):
        validate_task(task, factory(), phases={"smoke"})
    with pytest.raises(ValueError, match="repeats"):
        validate_task(task, factory(), repeats=0)


# One broken expectation at a time (synthetic variants of the toy task) ------------------


def test_an_already_solved_task_is_rejected(tmp_path: Path) -> None:
    result = _validate(tmp_path, {"repo/src/toy/greet.py": GREET_SOLVED}, phases={"baseline"})
    step = _step(result, "baseline.change_requirements_fail")
    assert not step.ok
    assert "R1, R2" in step.detail


def test_a_preserve_requirement_must_hold_at_the_start(tmp_path: Path) -> None:
    text = TASK_TOML.replace(
        'text = "greet raises ValueError for an empty name."',
        'text = "greet raises ValueError for an empty name."\nkind = "preserve"',
    )
    result = _validate(tmp_path, {"task.toml": text}, phases={"baseline"})
    step = _step(result, "baseline.preserve_requirements_pass")
    assert not step.ok
    assert "R2" in step.detail


def test_a_reference_that_does_not_solve_the_task_is_rejected(tmp_path: Path) -> None:
    unsolved = GREET_SOLVED.replace("text.upper() if shout else text", "text")
    result = _validate(tmp_path, {"reference/src/toy/greet.py": unsolved}, phases={"reference"})
    step = _step(result, "reference.hidden_pass")
    assert not step.ok
    assert "shout" in step.detail


def test_a_reference_that_breaks_the_visible_tests_is_rejected(tmp_path: Path) -> None:
    failing = "def test_reference_breaks() -> None:\n    raise AssertionError('broken')\n"
    result = _validate(tmp_path, {"reference/tests/test_broken.py": failing}, phases={"reference"})
    assert not _step(result, "reference.tests_pass").ok
    assert result.phases["reference"]["adds"] == ["tests/test_broken.py"]


def test_visible_tests_must_leave_the_tree_clean(tmp_path: Path) -> None:
    writer = (
        "from pathlib import Path\n\n\n"
        "def test_writes_a_file() -> None:\n"
        "    Path('stray.txt').write_text('x', encoding='utf-8')\n"
    )
    result = _validate(tmp_path, {"repo/tests/test_writer.py": writer}, phases={"baseline"})
    step = _step(result, "baseline.clean_tree")
    assert not step.ok
    assert "stray.txt" in step.detail


def test_too_few_visible_tests_are_reported(tmp_path: Path) -> None:
    result = _validate(tmp_path, phases={"baseline", "m2_start"}, tests=4)
    assert not _step(result, "baseline.tests_enough").ok
    assert not _step(result, "m2_start.tests_fail_as_declared").ok


def test_an_m1_overlay_without_effect_is_rejected(tmp_path: Path) -> None:
    spec = "# Spec\n\nEmpty names are an error.\n"
    result = _validate(tmp_path, {"variants/m1/docs/SPEC.md": spec}, phases={"m1"})
    step = _step(result, "m1.target_fails")
    assert not step.ok
    assert "did not make it unattainable" in step.detail


def test_an_m1_overlay_must_leave_other_requirements_attainable(tmp_path: Path) -> None:
    cases = HIDDEN_CASES.replace(
        'def shout() -> None:\n    assert greet("Ada", shout=True) == "HELLO, ADA!"',
        "def shout() -> None:\n"
        '    assert Path("docs/SPEC.md").read_text(encoding="utf-8") == CONTROL_SPEC\n'
        '    assert greet("Ada", shout=True) == "HELLO, ADA!"',
    )
    assert cases != HIDDEN_CASES
    result = _validate(tmp_path, {"hidden/_cases.py": cases}, phases={"m1", "m1_m2"})
    for phase in ("m1", "m1_m2"):
        step = _step(result, f"{phase}.others_pass")
        assert not step.ok
        assert "shout" in step.detail


def test_an_m1_overlay_must_not_break_the_visible_tests(tmp_path: Path) -> None:
    breaking = "def test_m1_breaks() -> None:\n    raise AssertionError('m1')\n"
    result = _validate(tmp_path, {"variants/m1/tests/test_m1.py": breaking}, phases={"start_m1m2"})
    step = _step(result, "start_m1m2.tests_fail_as_declared")
    assert not step.ok
    assert "tests/test_m1.py::test_m1_breaks" in step.detail


def test_an_m2_test_that_passes_is_rejected(tmp_path: Path) -> None:
    passing = "def test_service_answers() -> None:\n    assert True\n"
    result = _validate(
        tmp_path, {"variants/m2/tests/test_zz_service.py": passing}, phases={"m2_start"}
    )
    step = _step(result, "m2_start.tests_fail_as_declared")
    assert not step.ok
    assert "expected only 'tests/test_zz_service.py::test_service_answers' to fail" in step.detail


def test_an_m2_overlay_with_two_failures_is_rejected(tmp_path: Path) -> None:
    two = M2_TEST + "\n\ndef test_second_failure() -> None:\n    raise AssertionError('two')\n"
    result = _validate(tmp_path, {"variants/m2/tests/test_zz_service.py": two}, phases={"m2"})
    assert not _step(result, "m2.tests_fail_as_declared").ok


def test_a_failure_inside_the_visible_lines_is_rejected(tmp_path: Path) -> None:
    m2 = {**MANIFEST["manipulations"]["M2"], "visible_lines": 30}
    result = _validate(
        tmp_path, {"manifest.json": manifest_with(M2=m2)}, phases={"m2_start", "start_m1m2"}
    )
    step = _step(result, "m2_start.truncation_hides_failure")
    assert not step.ok
    assert "visible_lines 30" in step.detail
    truncation = result.phases["m2_start"]["truncation"]
    assert truncation["first_failure_line"] <= 30 + validate.M2_MARGIN_LINES


@pytest.mark.parametrize(
    ("checks", "status", "expected"),
    [
        ([{"name": "a", "passed": True, "requirement": "R1"}], 1, "exit status 1"),
        (
            [
                {"name": "a", "passed": False, "requirement": "R1"},
                {"name": "a", "passed": False, "requirement": "R2"},
            ],
            1,
            "duplicate check names: a",
        ),
        ([{"name": "a", "passed": False, "requirement": "R9"}], 1, "without a declared"),
        ([{"name": "a", "passed": False}], 1, "without a declared"),
        ([], 0, "no checks reported"),
    ],
)
def test_hidden_contract_rules(
    tmp_path: Path, checks: list[dict[str, object]], status: int, expected: str
) -> None:
    result = _validate(tmp_path, {"hidden/check.py": _hidden_script(checks, status)}, phases={"m1"})
    step = _step(result, "m1.hidden_contract")
    assert not step.ok
    assert expected in step.detail


def test_hidden_output_must_end_with_the_json_line(tmp_path: Path) -> None:
    script = "import sys\n\nprint('all good')\nsys.exit(0)\n"
    result = _validate(tmp_path, {"hidden/check.py": script}, phases={"baseline", "reference"})
    step = _step(result, "baseline.hidden_contract")
    assert not step.ok
    assert "did not end with the JSON result line" in step.detail
    assert "all good" in step.detail
    assert not _step(result, "reference.hidden_contract").ok
    assert result.phases["baseline"]["hidden"][0]["checks"] is None


def test_a_hidden_check_that_hangs_is_reported(tmp_path: Path) -> None:
    overrides = {"hidden/check.py": "import time\n\ntime.sleep(60)\n"}
    task = load_task(build_task(tmp_path / "project", overrides=overrides))
    # The loader allows at least 10 s; one second keeps this test fast.
    result = validate_task(
        replace(task, timeout_s=1), factory(), phases={"m1"}, work_root=tmp_path / "work"
    )
    step = _step(result, "m1.hidden_contract")
    assert not step.ok
    assert "timed out" in step.detail


def test_every_requirement_needs_a_hidden_check(tmp_path: Path) -> None:
    checks = [
        {"name": "a", "passed": False, "requirement": "R1"},
        {"name": "b", "passed": False, "requirement": "R2"},
    ]
    result = _validate(tmp_path, {"hidden/check.py": _hidden_script(checks, 1)}, phases={"m1"})
    step = _step(result, "hidden.requirements_covered")
    assert not step.ok
    assert "R3" in step.detail


def test_the_check_list_must_be_the_same_in_every_phase(tmp_path: Path) -> None:
    script = (
        "import json\nimport sys\nfrom pathlib import Path\n\n"
        "name = 'reference' if Path('src/toy/greet.py').read_text().count('upper') else 'start'\n"
        "checks = [{'name': name, 'passed': True, 'requirement': r} for r in ('R1', 'R2', 'R3')]\n"
        "print(json.dumps({'checks': checks}))\nsys.exit(0)\n"
    )
    result = _validate(tmp_path, {"hidden/check.py": script}, phases={"baseline", "m1"})
    step = _step(result, "hidden.same_checks_every_phase")
    assert not step.ok
    assert "m1" in step.detail or "baseline" in step.detail


def test_nondeterministic_hidden_checks_are_reported(tmp_path: Path) -> None:
    script = (
        "import json\nimport sys\nfrom pathlib import Path\n\n"
        "flag = Path('.flip')\npassed = not flag.exists()\n"
        "flag.write_text('x', encoding='utf-8')\n"
        "checks = [{'name': n, 'passed': passed, 'requirement': n} for n in ('R1', 'R2', 'R3')]\n"
        "print(json.dumps({'checks': checks}))\nsys.exit(0 if passed else 1)\n"
    )
    result = _validate(tmp_path, {"hidden/check.py": script}, phases={"reference"})
    assert not _step(result, "reference.hidden_deterministic").ok


def test_stale_prior_work_is_reported(tmp_path: Path) -> None:
    stale = prior_work()
    stale["episodes"][0]["steps"][1]["output"] = "99 src/toy/greet.py\n[exit code 0]"
    overrides = {"prior_work.json": json.dumps(stale)}
    result = _validate(tmp_path, overrides, phases={"baseline", "start_m1m2"})
    for phase in ("baseline", "start_m1m2"):
        step = _step(result, f"{phase}.prior_work_outputs")
        assert not step.ok
        assert "differs from a fresh run" in step.detail


def test_prior_work_must_hold_under_the_overlays(tmp_path: Path) -> None:
    data = prior_work()
    data["episodes"][0]["steps"][0]["args"] = {"path": "docs/SPEC.md"}
    data["episodes"][0]["steps"][0]["output"] = "# Spec\n\nEmpty names are an error.\n"
    result = _validate(
        tmp_path, {"prior_work.json": json.dumps(data)}, phases={"baseline", "start_m1m2"}
    )
    assert _step(result, "baseline.prior_work_outputs").ok
    assert not _step(result, "start_m1m2.prior_work_outputs").ok


def test_invalid_prior_work_skips_the_output_checks(tmp_path: Path) -> None:
    data = prior_work()
    data["synthetic"] = False
    result = _validate(tmp_path, {"prior_work.json": json.dumps(data)}, phases={"baseline"})
    step = _step(result, "prior_work.format")
    assert not step.ok
    assert "synthetic must be true" in step.detail
    assert "baseline.prior_work_outputs" not in [s.name for s in result.steps]


def test_prior_work_content_rules_are_reported(tmp_path: Path) -> None:
    data = prior_work()
    data["episodes"][0]["steps"][1]["args"] = {"cmd": "git log"}
    result = _validate(tmp_path, {"prior_work.json": json.dumps(data)}, phases={"m1"})
    step = _step(result, "prior_work.content")
    assert not step.ok
    assert "'git'" in step.detail


def test_layout_problems_are_recorded(tmp_path: Path) -> None:
    result = _validate(tmp_path, {"notes.txt": "x"}, phases={"m1"})
    step = _step(result, "layout")
    assert not step.ok
    assert "unexpected entry 'notes.txt'" in step.detail


def test_a_task_with_a_symlink_runs_no_phase(tmp_path: Path) -> None:
    task_dir = build_task(tmp_path / "project")
    (task_dir / "repo" / "link.md").symlink_to(task_dir / "repo" / "README.md")
    result = validate_task(load_task(task_dir), factory(), work_root=tmp_path / "work")
    assert not _step(result, "no_symlinks").ok
    assert result.phases_run == ()
    assert not result.valid


# Infrastructure failures are recorded, never raised ------------------------------------


class _NoGitSandbox(SubprocessSandbox):
    """A fake sandbox whose ``git init`` fails (synthetic infrastructure failure)."""

    def run(
        self, cmd: str, *, cwd: str = ".", timeout_s: float | None = None, stdin: str | None = None
    ) -> CommandOutcome:
        if cmd.startswith("set -e\ngit init"):
            return super().run("echo 'git: command not found' >&2; exit 127", cwd=cwd)
        return super().run(cmd, cwd=cwd, timeout_s=timeout_s, stdin=stdin)


def test_a_phase_that_cannot_run_is_recorded(tmp_path: Path) -> None:
    task = load_task(build_task(tmp_path / "project"))
    result = validate_task(
        task, lambda work: _NoGitSandbox(work), phases={"baseline", "m1"}, work_root=tmp_path
    )
    for phase in ("baseline", "m1"):
        step = _step(result, f"{phase}.ran")
        assert not step.ok
        assert "PhaseError: git init failed in the sandbox" in step.detail
    assert not result.valid


def test_a_failing_sandbox_factory_is_recorded(tmp_path: Path) -> None:
    def broken(work: Path) -> Sandbox:
        raise RuntimeError("no sandbox backend works here")

    task = load_task(build_task(tmp_path / "project"))
    result = validate_task(task, broken, phases={"m2_start"}, work_root=tmp_path)
    step = _step(result, "m2_start.ran")
    assert step.detail == "RuntimeError: no sandbox backend works here"


def test_changes_to_the_task_files_are_detected(tmp_path: Path) -> None:
    task_dir = build_task(tmp_path / "project")

    def tampering(work: Path) -> Sandbox:
        (task_dir / "repo" / "README.md").write_text("changed\n", encoding="utf-8")
        return SubprocessSandbox(work)

    result = validate_task(load_task(task_dir), tampering, phases={"m1"}, work_root=tmp_path)
    assert not _step(result, "task_files_unchanged").ok


def test_validate_path_reports_spec_errors(tmp_path: Path) -> None:
    text = TASK_TOML.replace('category = "feature"', 'category = "chore"')
    task_dir = build_task(tmp_path / "project", overrides={"task.toml": text})
    result = validate_path(task_dir, factory(), project_root=tmp_path / "project")
    assert result.task_id == "py-toy-greet"
    assert result.tree_sha256 == tree_sha256(task_dir)
    assert [step.name for step in result.steps] == ["spec"]
    assert "category" in result.steps[0].detail
    assert not result.valid


def test_validate_path_passes_options_through(tmp_path: Path) -> None:
    task_dir = build_task(tmp_path / "project")
    result = validate_path(task_dir, factory(), phases={"m1"}, work_root=tmp_path / "work")
    assert result.phases_run == ("m1",)
    assert _failed(result) == []


# Helpers ----------------------------------------------------------------------------------


def _outcome(stdout: str, exit_code: int = 0, stderr: str = "") -> CommandOutcome:
    return CommandOutcome(
        cmd="python3 -m pytest -v",
        cwd=".",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_s=0.1,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_sha256="0" * 64,
        stderr_sha256="0" * 64,
        backend="fake",
    )


def test_suite_summary_of_unrecognized_output() -> None:
    summary = SuiteSummary.from_outcome("python3 -m pytest -v", _outcome("nothing here\n", 5))
    assert not summary.recognized
    assert not summary.clean_pass
    assert summary.describe() == "exit 5; no test summary recognized"
    assert summary.to_dict()["recognized"] is False


def test_suite_summary_of_a_pytest_run() -> None:
    text = (
        "tests/test_a.py::test_one PASSED\n"
        "tests/test_a.py::test_two FAILED\n"
        "=================== 1 failed, 1 passed in 0.05s ===================\n"
    )
    summary = SuiteSummary.from_outcome("python3 -m pytest -v", _outcome(text, 1))
    assert summary.recognized
    assert (summary.passed, summary.failed) == (1, 1)
    assert summary.failing == ("tests/test_a.py::test_two",)
    assert not summary.clean_pass
    assert "failing: tests/test_a.py::test_two" in summary.describe()


def test_hidden_summary_helpers() -> None:
    checks = [
        {"name": "a", "passed": True, "requirement": "R1"},
        {"name": "b", "passed": False, "requirement": "R2"},
    ]
    summary = HiddenSummary.from_outcome(_outcome("log\n" + json.dumps({"checks": checks}), 1))
    assert summary.signature() == (("a", "R1"), ("b", "R2"))
    assert summary.results() == (("a", True), ("b", False))
    assert summary.failing() == ["b"]
    assert summary.failing("R1") == []
    assert [c.name for c in summary.of("R2")] == ["b"]
    assert summary.to_dict()["passed"] == 1
    broken = HiddenSummary.from_outcome(_outcome("no json", 1, "Traceback: boom"))
    assert broken.checks is None
    assert "boom" in broken.tail
    assert broken.to_dict()["checks"] is None


def test_first_failure_line_finds_names_and_markers() -> None:
    text = "header\ntests/a.py::test_ok PASSED\ntests/b.py::test_bad FAILED\n"
    assert first_failure_line(text, "tests/b.py::test_bad") == 3
    assert first_failure_line("ok\n\N{HEAVY MULTIPLICATION X} bad (1ms)\n", "x > bad") == 2
    assert first_failure_line("all fine\n", "tests/b.py::test_bad") is None


def test_overlay_copies_files_and_refuses_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "deep").mkdir(parents=True)
    (source / "deep" / "f.txt").write_text("new", encoding="utf-8")
    target = tmp_path / "target"
    (target / "deep").mkdir(parents=True)
    (target / "deep" / "f.txt").write_text("old", encoding="utf-8")
    overlay(source, target)
    assert (target / "deep" / "f.txt").read_text(encoding="utf-8") == "new"
    (source / "link").symlink_to(source / "deep" / "f.txt")
    with pytest.raises(PhaseError, match="symlinks"):
        overlay(source, target)


def test_hidden_dir_symlink_in_the_workspace_is_refused(tmp_path: Path) -> None:
    task = load_task(build_task(tmp_path / "project"))
    runner = validate._Runner(task, factory(), tmp_path, keep=False)
    work = tmp_path / "ws"
    shutil.copytree(task.repo_dir, work)
    (work / ".receipts_hidden").symlink_to(tmp_path)
    with pytest.raises(PhaseError, match="symlink"):
        runner.hidden(SubprocessSandbox(work))


def test_git_status_failure_is_a_phase_error(tmp_path: Path) -> None:
    with pytest.raises(PhaseError, match="git status failed"):
        validate._Runner.status(SubprocessSandbox(tmp_path))


def test_task_validation_bookkeeping() -> None:
    result = TaskValidation(task_id="t", tree_sha256="0" * 64)
    assert not result.valid
    result.add("one", True)
    result.add("two", False, "broken")
    assert result.problems == ["two: broken"]
    assert result.to_dict()["problems"] == ["two: broken"]
    assert validate.Step("x", True).to_dict() == {"name": "x", "ok": True, "detail": ""}


# The repository's own pilot tasks, end to end -------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("name", PILOTS)
def test_pilot_task_validates(tmp_path: Path, name: str) -> None:
    task_dir = ROOT / "bench" / "tasks" / name
    before = tree_sha256(task_dir)
    result = validate_path(task_dir, factory(), work_root=tmp_path / "work")
    assert result.valid, result.problems
    assert result.pilot
    assert result.tree_sha256 == before == tree_sha256(task_dir)
    m2 = result.phases["m2_start"]["truncation"]
    assert m2["first_failure_line"] > m2["visible_lines"] + validate.M2_MARGIN_LINES


def test_capture_prior_work_fills_outputs_in_a_validator_workspace(tmp_path: Path) -> None:
    blank = prior_work()
    for step in blank["episodes"][0]["steps"]:
        step["output"] = ""
    blank["episodes"][0]["steps"].append(
        {"thought": "List hidden entries too.", "tool": "bash", "args": {"cmd": "ls -a"}}
        | {"output": ""}
    )
    overrides = {"prior_work.json": json.dumps(blank)}
    task = load_task(build_task(tmp_path / "project", overrides=overrides))
    captured = validate.capture_prior_work(task, factory(), work_root=tmp_path / "work")
    steps = captured.episodes[0].steps
    assert steps[1].output == "6 src/toy/greet.py\n[exit code 0]"
    assert ".git" in steps[2].output.split("\n")
    assert captured.description == blank["description"]
    assert not (tmp_path / "work" / "py-toy-greet-capture").exists()
    default_root = validate.capture_prior_work(task, factory())
    assert default_root.episodes[0].steps[1].output == steps[1].output


def test_capture_prior_work_accepts_a_short_draft(tmp_path: Path) -> None:
    draft = prior_work()
    draft["episodes"][0]["finish"]["report"] = "It greets."
    draft["episodes"][0]["steps"][0]["output"] = ""
    task = load_task(
        build_task(tmp_path / "project", overrides={"prior_work.json": json.dumps(draft)})
    )
    captured = validate.capture_prior_work(task, factory())
    assert captured.episodes[0].steps[0].output.startswith('"""Greeting helper')


def test_capture_prior_work_refuses_invalid_content(tmp_path: Path) -> None:
    data = prior_work()
    data["episodes"][0]["steps"][1]["args"] = {"cmd": "rm -rf src"}
    task = load_task(
        build_task(tmp_path / "project", overrides={"prior_work.json": json.dumps(data)})
    )
    with pytest.raises(PriorWorkError, match="'rm'"):
        validate.capture_prior_work(task, factory())
