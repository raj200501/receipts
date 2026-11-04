"""Tests for the read-only Python toolchain.

Most tests use a fake command runner (synthetic results, no network, no uv). One test
builds a real, empty virtualenv with ``uv --offline`` and uses it inside bubblewrap.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from receipts.sandbox.api import SandboxPolicy
from receipts.sandbox.env import DEFAULT_PATH
from receipts.sandbox.toolchain import (
    BUILDING_NAME,
    MARKER_NAME,
    Toolchain,
    ToolchainError,
    check_pins,
    inspect_commands,
    python_toolchain,
    toolchain_commands,
    venv_python,
    with_toolchain,
)

from .helpers import bwrap_probe


class FakeRunner:
    """Records commands; simulates uv by creating the venv interpreter (synthetic)."""

    def __init__(self, base_prefix: str = "/usr", fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.base_prefix = base_prefix
        self.fail_on = fail_on

    def __call__(self, argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        args = tuple(argv)
        self.calls.append(args)
        if self.fail_on is not None and self.fail_on in args:
            return subprocess.CompletedProcess(args, 2, "", "error: synthetic failure\n")
        if args[1] == "venv":
            python = venv_python(Path(args[-1]))
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("synthetic interpreter", encoding="utf-8")
        stdout = ""
        if args[1:3] == ("pip", "freeze"):
            stdout = "iniconfig==2.0.0\npytest==8.3.3\n\n"
        elif args[1] == "-c":
            stdout = self.base_prefix + "\n"
        return subprocess.CompletedProcess(args, 0, stdout, "")


@pytest.mark.parametrize(
    "spec", ["pytest==8.3.3", "Foo_Bar[extra,more]==1.0rc1", "a==1", "x.y-z==2024.1.post2+local"]
)
def test_pins_are_accepted(spec: str) -> None:
    assert check_pins([spec]) == (spec,)


@pytest.mark.parametrize(
    "spec", ["pytest", "pytest>=8", "pytest==", "-e .", "git+https://example.invalid/x", "a==1 ;b"]
)
def test_unpinned_packages_are_refused(spec: str) -> None:
    with pytest.raises(ValueError, match="pinned"):
        check_pins(["pytest==8.3.3", spec])


def test_toolchain_commands_are_exact(tmp_path: Path) -> None:
    target = tmp_path / "tc"
    commands = toolchain_commands(
        target, ["pytest==8.3.3"], python="3.12", uv="/opt/uv", exclude_newer="2026-10-01"
    )
    assert commands == [
        [
            "/opt/uv",
            "venv",
            "--no-config",
            "--no-project",
            "--allow-existing",
            "--quiet",
            "--python",
            "3.12",
            str(target),
        ],
        [
            "/opt/uv",
            "pip",
            "install",
            "--no-config",
            "--quiet",
            "--link-mode",
            "copy",
            "--python",
            str(target / "bin" / "python"),
            "--exclude-newer",
            "2026-10-01",
            "pytest==8.3.3",
        ],
    ]


def test_no_packages_means_no_install_and_offline_is_passed(tmp_path: Path) -> None:
    commands = toolchain_commands(tmp_path / "tc", [], offline=True)
    assert len(commands) == 1 and "--offline" in commands[0]
    assert "--offline" in toolchain_commands(tmp_path / "tc", ["a==1"], offline=True)[1]


def test_inspect_commands(tmp_path: Path) -> None:
    freeze, prefix = inspect_commands(tmp_path / "tc", uv="uv")
    assert freeze[:3] == ["uv", "pip", "freeze"] and "--no-config" in freeze
    assert prefix[0] == str(tmp_path / "tc" / "bin" / "python")


def test_build_runs_the_commands_and_records_a_marker(tmp_path: Path) -> None:
    runner = FakeRunner()
    tc = python_toolchain(tmp_path / "tc", ["pytest==8.3.3"], run=runner)
    target = (tmp_path / "tc").absolute()
    assert [call[1] for call in runner.calls] == ["venv", "pip", "pip", "-c"]
    assert tc.built and tc.commands == tuple(
        tuple(c) for c in toolchain_commands(target, ["pytest==8.3.3"])
    )
    assert (tc.path, tc.python, tc.bin_dir) == (target, target / "bin" / "python", target / "bin")
    assert tc.installed == ("iniconfig==2.0.0", "pytest==8.3.3")
    assert tc.base_prefix == Path("/usr") and tc.readonly_paths == (target,)
    marker = json.loads((target / MARKER_NAME).read_text(encoding="utf-8"))
    assert marker["spec"] == {
        "python": "3.11",
        "packages": ["pytest==8.3.3"],
        "exclude_newer": None,
    }
    assert not (target / BUILDING_NAME).exists()


def test_a_second_call_reuses_the_build(tmp_path: Path) -> None:
    first = python_toolchain(tmp_path / "tc", ["pytest==8.3.3"], run=FakeRunner())
    runner = FakeRunner()
    again = python_toolchain(tmp_path / "tc", ["pytest==8.3.3"], run=runner)
    assert runner.calls == []
    assert not again.built and again.commands == ()
    assert (again.installed, again.readonly_paths) == (first.installed, first.readonly_paths)


def test_a_changed_specification_rebuilds(tmp_path: Path) -> None:
    python_toolchain(tmp_path / "tc", ["pytest==8.3.3"], run=FakeRunner())
    (tmp_path / "tc" / "leftover").write_text("old build", encoding="utf-8")
    runner = FakeRunner()
    tc = python_toolchain(tmp_path / "tc", ["pytest==8.3.4"], run=runner)
    assert tc.built and runner.calls
    assert not (tmp_path / "tc" / "leftover").exists()


def test_a_non_system_interpreter_prefix_is_mounted_too(tmp_path: Path) -> None:
    prefix = "/opt/python/cpython-3.11-synthetic"
    tc = python_toolchain(tmp_path / "tc", [], run=FakeRunner(base_prefix=prefix))
    assert tc.readonly_paths == ((tmp_path / "tc").absolute(), Path(prefix))
    reused = python_toolchain(tmp_path / "tc", [], run=FakeRunner())
    assert reused.readonly_paths == tc.readonly_paths


def test_an_unrelated_existing_directory_is_never_replaced(tmp_path: Path) -> None:
    target = tmp_path / "important"
    target.mkdir()
    (target / "data.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ToolchainError, match="not a receipts toolchain"):
        python_toolchain(target, [], run=FakeRunner())
    assert (target / "data.txt").read_text(encoding="utf-8") == "keep me"


def test_an_empty_existing_directory_is_used(tmp_path: Path) -> None:
    (tmp_path / "tc").mkdir()
    assert python_toolchain(tmp_path / "tc", [], run=FakeRunner()).built


def test_a_failed_build_is_reported_and_retried(tmp_path: Path) -> None:
    with pytest.raises(ToolchainError, match="synthetic failure"):
        python_toolchain(tmp_path / "tc", ["pytest==8.3.3"], run=FakeRunner(fail_on="install"))
    assert (tmp_path / "tc" / BUILDING_NAME).exists()
    tc = python_toolchain(tmp_path / "tc", ["pytest==8.3.3"], run=FakeRunner())
    assert tc.built and not (tmp_path / "tc" / BUILDING_NAME).exists()


def test_a_failure_without_stderr_names_the_exit_code(tmp_path: Path) -> None:
    def silent(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(tuple(argv), 3, "", "")

    with pytest.raises(ToolchainError, match="exit code 3"):
        python_toolchain(tmp_path / "tc", [], run=silent)


@pytest.mark.parametrize("marker", ["[1, 2", "[1, 2]", '{"spec": "other"}'])
def test_an_unreadable_marker_means_rebuild(tmp_path: Path, marker: str) -> None:
    python_toolchain(tmp_path / "tc", [], run=FakeRunner())
    (tmp_path / "tc" / MARKER_NAME).write_text(marker, encoding="utf-8")
    runner = FakeRunner()
    assert python_toolchain(tmp_path / "tc", [], run=runner).built
    assert runner.calls


def make_toolchain(path: Path) -> Toolchain:
    return Toolchain(
        path=path,
        python=path / "bin" / "python",
        bin_dir=path / "bin",
        packages=(),
        installed=(),
        base_prefix=Path("/usr"),
        readonly_paths=(path,),
        built=True,
        commands=(),
    )


def test_with_toolchain_prepends_path_and_merges_readonly_paths() -> None:
    tc = make_toolchain(Path("/opt/tc"))
    policy = with_toolchain(SandboxPolicy(timeout_s=9.0, readonly_paths=(Path("/opt/tc"),)), tc)
    assert policy.env["PATH"] == f"/opt/tc/bin:{DEFAULT_PATH}"
    assert policy.readonly_paths == (Path("/opt/tc"),)
    assert policy.timeout_s == 9.0
    layered = with_toolchain(SandboxPolicy(env={"PATH": "/x/bin", "A": "1"}), tc)
    assert layered.env == {"PATH": "/opt/tc/bin:/x/bin", "A": "1"}


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_real_offline_build_works_inside_bubblewrap(tmp_path: Path) -> None:
    from receipts.sandbox.bwrap import BwrapSandbox

    tc = python_toolchain(tmp_path / "tc", [], python=sys.executable, offline=True)
    assert tc.built and tc.python.exists()
    assert not python_toolchain(tmp_path / "tc", [], python=sys.executable, offline=True).built
    if not bwrap_probe().ok:
        pytest.skip(f"bubblewrap does not work here: {bwrap_probe().detail}")
    ws = tmp_path / "ws"
    ws.mkdir()
    box = BwrapSandbox(ws, with_toolchain(SandboxPolicy(), tc))
    outcome = box.run('python -c "import sys; print(sys.prefix)"')
    assert (outcome.exit_code, outcome.stdout.strip()) == (0, str(tc.path))
    assert box.run(f"touch {tc.path}/new").exit_code != 0
