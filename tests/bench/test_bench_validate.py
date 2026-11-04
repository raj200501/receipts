"""Tests for tools/bench_validate.py.

The tasks are the synthetic toy task from tests/bench/factory.py (test data). The tool
never builds a real toolchain or picks a real sandbox here: tests pass a factory builder
that returns the subprocess-backed fake sandbox, or patch the sandbox package.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import bench_validate
import ship_check
from receipts.bench.hashing import tree_sha256
from receipts.bench.spec import TOOLCHAIN_PACKAGES
from receipts.bench.validate import SandboxFactory
from receipts.sandbox import select, toolchain
from receipts.sandbox.toolchain import Toolchain, ToolchainError

from .factory import TASK_TOML, build_task
from .fakes import SubprocessSandbox, factory

Builder = Callable[[argparse.Namespace], tuple[Callable[[int], SandboxFactory], dict[str, Any]]]
LIMITS: list[int] = []


def _fake_builder(
    args: argparse.Namespace,
) -> tuple[Callable[[int], SandboxFactory], dict[str, Any]]:
    def maker(memory_mb: int) -> SandboxFactory:
        LIMITS.append(memory_mb)
        return factory()

    return maker, {"backends": ["fake"]}


def _project(tmp_path: Path, *, broken: bool = False) -> Path:
    """A project with the valid toy task and, optionally, one with a spec error."""
    project = tmp_path / "project"
    build_task(project)
    if broken:
        text = TASK_TOML.replace('id = "py-toy-greet"', 'id = "py-toy-broken"').replace(
            'category = "feature"', 'category = "chore"'
        )
        build_task(project, task_id="py-toy-broken", overrides={"task.toml": text})
    return project


def _run(project: Path, out: Path, *extra: str, builder: Builder = _fake_builder) -> int:
    argv = [
        "--tasks-dir",
        str(project / "bench" / "tasks"),
        "--project-root",
        str(project),
        "--out",
        str(out),
        *extra,
    ]
    return bench_validate.main(argv, build_factory=builder)


def test_a_full_run_writes_the_g6_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    out = tmp_path / "artifacts" / "reference_validation.json"
    LIMITS.clear()
    assert _run(project, out, "--jobs", "2") == 0
    assert LIMITS == [16384, 4096]
    printed = capsys.readouterr().out
    assert "PASS py-toy-greet" in printed
    assert "1 of 1 tasks valid" in printed
    data = json.loads(out.read_text(encoding="utf-8"))
    ship_check.require_provenance("reference_validation.json", data)
    entry = data["tasks"]["py-toy-greet"]
    task = project / "bench" / "tasks" / "py-toy-greet"
    assert entry["hidden_passed"] is True
    assert entry["tree_sha256"] == ship_check.tree_sha256(task) == tree_sha256(task)
    provenance = data["provenance"]
    assert provenance["command"].startswith("python tools/bench_validate.py --tasks-dir ")
    assert provenance["environment"]["backends"] == ["fake"]
    assert provenance["environment"]["sandbox"]["backend"] == "fake"
    assert any(line.startswith("v22") for line in provenance["environment"]["sandbox"]["versions"])
    assert (
        bench_validate.main(["--verify", "--out", str(out), "--tasks-dir", str(task.parent)]) == 0
    )
    (task / "repo" / "README.md").write_text("changed\n", encoding="utf-8")
    assert (
        bench_validate.main(["--verify", "--out", str(out), "--tasks-dir", str(task.parent)]) == 1
    )
    assert "OUT OF DATE py-toy-greet" in capsys.readouterr().out


def test_an_invalid_task_fails_the_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path, broken=True)
    out = tmp_path / "out.json"
    assert _run(project, out) == 1
    assert "FAIL py-toy-broken: spec: task.toml: category" in capsys.readouterr().out
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["tasks"]["py-toy-broken"]["hidden_passed"] is False
    assert data["summary"]["invalid"] == ["py-toy-broken"]


def test_a_limited_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _project(tmp_path, broken=True)
    out = tmp_path / "out.json"
    assert _run(project, out, "--task", "py-toy-broken") == 1
    assert not out.exists()
    assert "artifact not written" in capsys.readouterr().out
    assert _run(project, out, "--no-write", "--task", "py-toy-broken") == 1
    assert not out.exists()


def test_setup_problems_exit_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    out = tmp_path / "out.json"
    assert _run(project, out, "--task", "py-nope") == 2
    assert "unknown task ids: py-nope" in capsys.readouterr().err
    assert _run(tmp_path / "empty", out) == 2
    assert "no tasks under" in capsys.readouterr().err

    def broken_factory(
        args: argparse.Namespace,
    ) -> tuple[Callable[[int], SandboxFactory], dict[str, Any]]:
        def make(work: Path) -> SubprocessSandbox:
            raise RuntimeError("no backend works here")

        return lambda memory_mb: make, {}

    assert _run(project, out, builder=broken_factory) == 2
    assert "no sandbox: RuntimeError: no backend works here" in capsys.readouterr().err
    assert not out.exists()


def test_verify_without_an_artifact(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert bench_validate.main(["--verify", "--out", str(tmp_path / "missing.json")]) == 1
    assert "cannot read" in capsys.readouterr().err


def test_jobs_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        bench_validate.parse_args(["--jobs", "0"])


def _fake_toolchain(path: Path) -> Toolchain:
    """A Toolchain record for an interpreter that already has pytest (test data)."""
    bin_dir = Path(sys.executable).parent
    return Toolchain(
        path=path,
        python=Path(sys.executable),
        bin_dir=bin_dir,
        packages=TOOLCHAIN_PACKAGES,
        installed=("pytest==9.1.1",),
        base_prefix=Path(sys.base_prefix),
        readonly_paths=(path,),
        built=False,
        commands=(),
    )


def test_default_factory_builds_the_toolchain_and_uses_make_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, Any] = {}

    def fake_toolchain(path: Path, packages: tuple[str, ...], **options: Any) -> Toolchain:
        calls["toolchain"] = (path, packages, options)
        return _fake_toolchain(tmp_path / "toolchain")

    def fake_make_sandbox(workspace: Path, policy: Any, prefer: tuple[str, ...]) -> Any:
        calls["sandbox"] = (policy, prefer)
        return SubprocessSandbox(workspace)

    monkeypatch.setattr(toolchain, "python_toolchain", fake_toolchain)
    monkeypatch.setattr(select, "make_sandbox", fake_make_sandbox)
    args = bench_validate.parse_args(["--backend", "unshare", "--offline"])
    maker, setup = bench_validate.default_factory(args)
    sandbox = maker(16384)(tmp_path)
    assert sandbox.workspace == tmp_path
    path, packages, options = calls["toolchain"]
    assert path == bench_validate.ROOT / bench_validate.DEFAULT_TOOLCHAIN
    assert packages == TOOLCHAIN_PACKAGES
    assert options == {"python": "3.11", "offline": True}
    policy, prefer = calls["sandbox"]
    assert prefer == ("unshare",)
    assert policy.memory_mb == 16384
    assert policy.env["PATH"].startswith(str(Path(sys.executable).parent) + ":")
    assert tmp_path / "toolchain" in policy.readonly_paths
    assert setup["backends"] == ["unshare"]
    assert setup["memory_mb"] == {"python": 4096, "typescript": 16384}
    assert setup["toolchain"]["installed"] == ["pytest==9.1.1"]


def test_default_factory_without_a_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(select, "make_sandbox", lambda ws, policy, prefer: SubprocessSandbox(ws))
    maker, setup = bench_validate.default_factory(bench_validate.parse_args(["--no-toolchain"]))
    assert setup["backends"] == ["bwrap", "unshare"]
    assert "toolchain" not in setup
    assert maker(4096)(tmp_path).workspace == tmp_path


def test_default_factory_reports_a_toolchain_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(path: Path, packages: tuple[str, ...], **options: Any) -> Toolchain:
        raise ToolchainError("uv venv failed: no network")

    monkeypatch.setattr(toolchain, "python_toolchain", failing)
    with pytest.raises(bench_validate.SetupError, match="no network"):
        bench_validate.default_factory(bench_validate.parse_args([]))


def test_default_factory_without_the_sandbox_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "receipts.sandbox.select", None)
    with pytest.raises(bench_validate.SetupError, match=r"receipts\.sandbox is not available"):
        bench_validate.default_factory(bench_validate.parse_args([]))


def test_probe_environment_runs_in_the_sandbox() -> None:
    probe = bench_validate.probe_environment(factory())
    assert probe["backend"] == "fake"
    assert probe["probe_exit_code"] == 0
    assert any(line.startswith("Python 3.") for line in probe["versions"])
    assert any(line.startswith("git version") for line in probe["versions"])


def test_git_state(tmp_path: Path, git_repo: Path, commit: Callable[[Path, str], str]) -> None:
    assert bench_validate.git_state(tmp_path) == {"git_sha": "unknown", "bench_dirty": None}
    (git_repo / "bench").mkdir()
    (git_repo / "bench" / "a.txt").write_text("a", encoding="utf-8")
    sha = commit(git_repo, "start")
    assert bench_validate.git_state(git_repo) == {"git_sha": sha, "bench_dirty": False}
    (git_repo / "bench" / "a.txt").write_text("b", encoding="utf-8")
    assert bench_validate.git_state(git_repo)["bench_dirty"] is True


def test_the_script_runs_as_a_program(tmp_path: Path) -> None:
    script = Path(bench_validate.__file__)
    proc = subprocess.run(
        [sys.executable, str(script), "--verify", "--out", str(tmp_path / "none.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "cannot read" in proc.stderr


def test_capture_prior_work_rewrites_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    path = project / "bench" / "tasks" / "py-toy-greet" / "prior_work.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["episodes"][0]["steps"][1]["output"] = "stale"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert _run(project, tmp_path / "out.json", "--capture-prior-work", "py-toy-greet") == 0
    assert "rendered characters" in capsys.readouterr().out
    fresh = json.loads(path.read_text(encoding="utf-8"))
    assert fresh["episodes"][0]["steps"][1]["output"] == "6 src/toy/greet.py\n[exit code 0]"
    assert not (tmp_path / "out.json").exists()


def test_capture_prior_work_reports_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    path = project / "bench" / "tasks" / "py-toy-greet" / "prior_work.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["synthetic"] = False
    path.write_text(json.dumps(data), encoding="utf-8")
    assert _run(project, tmp_path / "out.json", "--capture-prior-work", "py-toy-greet") == 1
    assert "cannot capture prior work" in capsys.readouterr().err
    assert _run(project, tmp_path / "out.json", "--capture-prior-work", "py-nope") == 2
    data["synthetic"] = True
    data["episodes"][0]["finish"]["report"] = "Short."
    path.write_text(json.dumps(data), encoding="utf-8")
    assert _run(project, tmp_path / "out.json", "--capture-prior-work", "py-toy-greet") == 1
    assert "M4 needs" in capsys.readouterr().err


def test_a_phase_limited_run_reports_the_selected_phases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    out = tmp_path / "out.json"
    assert _run(project, out, "--phase", "baseline", "--phase", "m1") == 0
    printed = capsys.readouterr().out
    assert "0 of 1 tasks valid" in printed
    assert "1 of 1 tasks hold in the selected phases" in printed
    assert not out.exists()
    cases = (project / "bench" / "tasks" / "py-toy-greet" / "hidden" / "_cases.py").read_text()
    broken = cases.replace('assert greet("Ada") == "Hello, Ada!"', 'assert greet("Ada") == "Hi"')
    (project / "bench" / "tasks" / "py-toy-greet" / "hidden" / "_cases.py").write_text(broken)
    assert _run(project, out, "--phase", "baseline") == 1
