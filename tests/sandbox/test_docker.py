"""Tests for DockerSandbox.

Most tests use a fake ``docker`` client (a shell script written by the test, synthetic
behaviour) so they need no daemon. Tests marked slow run real containers and are
skipped unless the daemon answers and the default image is cached.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from receipts.sandbox.api import CommandOutcome, Sandbox, SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import LAUNCHER_ARG0, MAX_COMMAND_BYTES, STARTED
from receipts.sandbox.docker import (
    CLIENT_ENV_NAMES,
    DEFAULT_IMAGE,
    DockerSandbox,
    check_image,
    check_mount_path,
    docker_client_env,
    probe_docker,
)
from receipts.sandbox.env import DEFAULT_PATH
from receipts.sandbox.process import TIMEOUT_EXIT_CODE

from .helpers import CONNECT_CMD, docker_probe, requires

FAKE_DOCKER = """#!/bin/bash
# Synthetic stand-in for the docker client, written by tests/sandbox/test_docker.py.
# "run" emulates a container by running the launcher locally (no isolation; the
# commands are this test file's own fixtures), unless a failure mode is enabled.
{{ printf '%s ' "$@" | tr '\\n' ' '; echo; }} >> {log}
case "$1" in
  info) if [ -f {root}/info_ok ]; then echo 99.0.0-synthetic; exit 0; fi
        echo "Cannot connect to the Docker daemon" >&2; exit 1 ;;
  image) [ -f {root}/image_ok ] && exit 0; exit 1 ;;
  rm) exit 0 ;;
  run) if [ -f {root}/run_sleeps ]; then exec sleep 30; fi
       if [ -f {root}/run_silent ]; then exit 3; fi
       if [ -f {root}/daemon_error ]; then
         echo "docker: Error response from daemon: synthetic" >&2; exit 125
       fi
       args=("$@")
       for ((i = 0; i + 4 < ${{#args[@]}}; i++)); do
         if [ "${{args[i]}}" = bash ] && [ "${{args[i+1]}}" = -c ] \\
            && [ "${{args[i+3]}}" = receipts-sandbox ]; then
           exec bash -c "${{args[i+2]}}" receipts-sandbox "${{args[i+4]}}"
         fi
       done
       exit 2 ;;
esac
exit 2
"""


@dataclass
class FakeDocker:
    """A fake docker client and its call log."""

    root: Path

    @property
    def path(self) -> str:
        """The fake client's executable."""
        return str(self.root / "docker")

    def enable(self, name: str) -> None:
        """Turn on the synthetic behaviour ``name`` (for example ``"info_ok"``)."""
        (self.root / name).touch()

    def disable(self, name: str) -> None:
        """Turn off the synthetic behaviour ``name``."""
        (self.root / name).unlink(missing_ok=True)

    def calls(self) -> list[str]:
        """Each call's arguments, joined by spaces, in order."""
        log = self.root / "calls.log"
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return [line.strip() for line in lines]


@pytest.fixture
def fake_docker(tmp_path: Path) -> FakeDocker:
    """A fake docker client under this test's temporary directory."""
    root = tmp_path / "fake-docker"
    root.mkdir()
    script = root / "docker"
    script.write_text(FAKE_DOCKER.format(log=root / "calls.log", root=root), encoding="utf-8")
    script.chmod(0o755)
    return FakeDocker(root)


def value_after(argv: list[str], flag: str) -> str:
    """The argument right after the first ``flag`` in ``argv``."""
    return argv[argv.index(flag) + 1]


def values_after(argv: list[str], flag: str) -> list[str]:
    """The argument after each ``flag`` in ``argv``, in order."""
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == flag]


def test_command_line_has_every_isolation_flag(
    workspace: Path, tmp_path: Path, fake_docker: FakeDocker
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    policy = SandboxPolicy(
        memory_mb=1024, cpu_s=90, max_procs=64, readonly_paths=(tools,), env={"X": "1"}
    )
    box = DockerSandbox(workspace, policy, docker=fake_docker.path, cpus=1.5, tmp_size_mb=128)
    ws = workspace.resolve()
    argv = box.command("echo hi", ws / "sub", "receipts-test")
    assert argv[:3] == [fake_docker.path, "run", "--rm"]
    assert value_after(argv, "--name") == "receipts-test"
    assert value_after(argv, "--pull") == "never"
    assert value_after(argv, "--network") == "none"
    assert "--read-only" in argv
    assert value_after(argv, "--tmpfs") == "/tmp:rw,exec,nosuid,nodev,size=128m"
    assert value_after(argv, "--pids-limit") == "64"
    assert value_after(argv, "--memory") == "1024m"
    assert value_after(argv, "--memory-swap") == "1024m"
    assert value_after(argv, "--cpus") == "1.5"
    assert value_after(argv, "--ulimit") == "cpu=90:90"
    assert value_after(argv, "--cap-drop") == "ALL"
    assert value_after(argv, "--security-opt") == "no-new-privileges"
    owner = ws.stat()
    assert value_after(argv, "--user") == f"{owner.st_uid}:{owner.st_gid}"
    assert value_after(argv, "--workdir") == str(ws / "sub")
    assert values_after(argv, "--mount") == [
        f"type=bind,source={ws},target={ws}",
        f"type=bind,source={tools.resolve()},target={tools.resolve()},readonly",
    ]
    env = dict(item.split("=", 1) for item in values_after(argv, "--env"))
    assert env == box.env and env["PATH"] == DEFAULT_PATH and env["X"] == "1"
    assert "--interactive" not in argv
    image_at = argv.index(DEFAULT_IMAGE)
    assert argv[image_at + 1 : image_at + 3] == ["bash", "-c"]
    assert argv[-2:] == [LAUNCHER_ARG0, "echo hi"]
    assert "compgen -e" in argv[-3]
    assert f"printf '%s\\n' {STARTED} >&1" in argv[-3]


def test_interactive_and_network_options(workspace: Path, fake_docker: FakeDocker) -> None:
    ws = workspace.resolve()
    box = DockerSandbox(workspace, docker=fake_docker.path, image="local/img:1")
    assert "--interactive" in box.command("cat", ws, "n", interactive=True)
    assert "local/img:1" in box.command("true", ws, "n")
    networked = DockerSandbox(workspace, SandboxPolicy(network=True), docker=fake_docker.path)
    assert "--network" not in networked.command("true", ws, "n")


def test_constructor_checks(workspace: Path, tmp_path: Path, fake_docker: FakeDocker) -> None:
    box = DockerSandbox(workspace, docker=fake_docker.path)
    assert isinstance(box, Sandbox)
    assert (box.backend, box.confines_writes, box.image) == ("docker", True, DEFAULT_IMAGE)
    assert box.process_limit == "docker"
    assert box.executable == fake_docker.path
    with pytest.raises(ValueError, match="cpus"):
        DockerSandbox(workspace, docker=fake_docker.path, cpus=0)
    with pytest.raises(ValueError, match="tmp_size_mb"):
        DockerSandbox(workspace, docker=fake_docker.path, tmp_size_mb=0)
    with pytest.raises(ValueError, match="image"):
        DockerSandbox(workspace, docker=fake_docker.path, image="--privileged")
    odd = tmp_path / "a,b"
    odd.mkdir()
    with pytest.raises(ValueError, match="--mount"):
        DockerSandbox(odd, docker=fake_docker.path)
    with pytest.raises(SandboxUnavailableError, match="docker"):
        DockerSandbox(workspace, docker="receipts-no-such-docker")


@pytest.mark.parametrize("image", ["", "-x", "a b", "img\n"])
def test_check_image_refuses_bad_references(image: str) -> None:
    with pytest.raises(ValueError):
        check_image(image)


def test_check_mount_path() -> None:
    assert check_mount_path(Path("/a/b")) == Path("/a/b")
    for bad in ("/a,b", '/a"b', "/a\nb"):
        with pytest.raises(ValueError):
            check_mount_path(Path(bad))


def test_client_env_drops_credentials(planted_secrets: dict[str, str]) -> None:
    env = docker_client_env({**os.environ, "DOCKER_HOST": "unix:///synthetic.sock"})
    assert set(env) <= set(CLIENT_ENV_NAMES)
    assert env["DOCKER_HOST"] == "unix:///synthetic.sock"
    for name in planted_secrets:
        assert name not in env


def test_run_through_the_client(workspace: Path, fake_docker: FakeDocker) -> None:
    box = DockerSandbox(workspace, docker=fake_docker.path)
    outcome = box.run("echo out; echo err >&2; exit 7", cwd="sub")
    assert (outcome.exit_code, outcome.stdout, outcome.stderr) == (7, "out\n", "err\n")
    assert (outcome.backend, outcome.cwd) == ("docker", "sub")
    assert fake_docker.calls()[0].startswith("run --rm --name receipts-")


def test_a_command_exiting_125_is_its_own_outcome(workspace: Path, fake_docker: FakeDocker) -> None:
    outcome = DockerSandbox(workspace, docker=fake_docker.path).run("echo hi; exit 125")
    assert (outcome.exit_code, outcome.stdout) == (125, "hi\n")


def test_a_daemon_error_is_a_sandbox_failure(workspace: Path, fake_docker: FakeDocker) -> None:
    fake_docker.enable("daemon_error")
    box = DockerSandbox(workspace, docker=fake_docker.path)
    with pytest.raises(SandboxUnavailableError) as caught:
        box.run("true")
    message = str(caught.value)
    assert "docker: the sandbox did not start the command" in message
    assert "exit code 125: docker: Error response from daemon: synthetic" in message


def test_a_vanished_readonly_path_is_a_sandbox_failure(
    workspace: Path, tmp_path: Path, fake_docker: FakeDocker
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    box = DockerSandbox(workspace, SandboxPolicy(readonly_paths=(tools,)), docker=fake_docker.path)
    assert box.run("true").exit_code == 0
    tools.rmdir()
    with pytest.raises(SandboxUnavailableError, match="read-only paths no longer exist"):
        box.run("true")


def test_timeout_kills_the_container(workspace: Path, fake_docker: FakeDocker) -> None:
    fake_docker.enable("run_sleeps")
    outcome = DockerSandbox(workspace, docker=fake_docker.path).run("sleep 60", timeout_s=0.5)
    assert outcome.timed_out and outcome.exit_code == TIMEOUT_EXIT_CODE
    run_call, *stops = fake_docker.calls()
    name = run_call.split()[run_call.split().index("--name") + 1]
    assert stops == [f"rm --force {name}", f"rm --force {name}"]


def test_stop_container_ignores_client_errors(
    workspace: Path, fake_docker: FakeDocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = DockerSandbox(workspace, docker=fake_docker.path)

    def broken(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("synthetic failure")

    monkeypatch.setattr("receipts.sandbox.docker.subprocess.run", broken)
    box.stop_container("receipts-gone")


def test_probe_docker_reports_each_failure(fake_docker: FakeDocker) -> None:
    missing = probe_docker("receipts-no-such-docker")
    assert not missing.ok and "docker" in missing.detail
    down = probe_docker(fake_docker.path)
    assert not down.ok and "not reachable" in down.detail
    fake_docker.enable("info_ok")
    uncached = probe_docker(fake_docker.path, image="local/img:1")
    assert not uncached.ok and "local/img:1" in uncached.detail
    fake_docker.enable("image_ok")
    fake_docker.enable("daemon_error")
    broken = probe_docker(fake_docker.path)
    assert not broken.ok and "containers do not run here" in broken.detail
    assert "Error response from daemon: synthetic" in broken.detail
    fake_docker.disable("daemon_error")
    fake_docker.enable("run_silent")
    assert "exit code 3" in probe_docker(fake_docker.path).detail
    fake_docker.disable("run_silent")
    ready = probe_docker(fake_docker.path)
    assert ready.ok and "99.0.0-synthetic" in ready.detail
    runs = [call for call in fake_docker.calls() if call.startswith("run ")]
    assert runs and all("--network none" in call for call in runs)


def test_probe_docker_survives_an_unmountable_temporary_directory(
    fake_docker: FakeDocker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker.enable("info_ok")
    fake_docker.enable("image_ok")
    odd = tmp_path / "tmp,dir"
    odd.mkdir()
    monkeypatch.setattr("receipts.sandbox.docker.tempfile.tempdir", str(odd))
    probe = probe_docker(fake_docker.path)
    assert not probe.ok and "--mount" in probe.detail


def test_probe_docker_survives_a_hung_client(
    fake_docker: FakeDocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    def hung(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("docker", 1)

    monkeypatch.setattr("receipts.sandbox.docker.subprocess.run", hung)
    assert not probe_docker(fake_docker.path).ok


def failing_true(self: object, cmd: str, **kwargs: object) -> CommandOutcome:
    """A synthetic outcome for a sandbox that started ``true`` and saw it fail."""
    return CommandOutcome(
        cmd=cmd,
        cwd=".",
        exit_code=3,
        stdout="",
        stderr="synthetic: true failed\n",
        duration_s=0.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_sha256="",
        stderr_sha256="",
        backend="synthetic",
    )


def test_probe_docker_reports_a_trivial_command_that_fails(
    fake_docker: FakeDocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker.enable("info_ok")
    fake_docker.enable("image_ok")
    monkeypatch.setattr(DockerSandbox, "run", failing_true)
    probe = probe_docker(fake_docker.path)
    assert not probe.ok and probe.detail == "containers do not run here: synthetic: true failed"


# Real containers --------------------------------------------------------------------

needs_docker = requires(docker_probe())


@pytest.mark.slow
@needs_docker
def test_real_container_isolation(
    workspace: Path, tmp_path: Path, planted_secrets: dict[str, str]
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "note.txt").write_text("tool data\n", encoding="utf-8")
    box = DockerSandbox(workspace, SandboxPolicy(readonly_paths=(tools,)))
    net = box.run(CONNECT_CMD)
    assert net.exit_code != 0
    assert box.run("echo x > /etc/receipts-probe").exit_code != 0
    assert box.run("echo x > /tmp/scratch && cat /tmp/scratch").stdout == "x\n"
    assert box.run("echo x > made.txt").exit_code == 0
    assert (workspace / "made.txt").read_text(encoding="utf-8") == "x\n"
    assert box.run(f"cat {tools}/note.txt").stdout == "tool data\n"
    assert box.run(f"touch {tools}/new").exit_code != 0
    env = box.run("env").stdout
    for name, value in planted_secrets.items():
        assert f"{name}=" not in env and value not in env
    assert "PYTHON_VERSION=" not in env
    owner = workspace.resolve().stat().st_uid
    assert box.run("id -u").stdout.strip() == str(owner)
    killed = box.run("kill -9 $$")
    assert (killed.exit_code, killed.stderr) == (137, "")
    assert box.run("cat", stdin="piped").stdout == "piped"
    assert box.run("#" + "x" * (MAX_COMMAND_BYTES - 1)).exit_code == 0


@pytest.mark.slow
@needs_docker
def test_an_early_timeout_leaves_no_container_behind(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = DockerSandbox(workspace)
    names: list[str] = []
    real_stop = box.stop_container

    def recording(name: str) -> None:
        names.append(name)
        real_stop(name)

    monkeypatch.setattr(box, "stop_container", recording)
    # Timeouts shorter than container start-up. A single "docker kill" before the client
    # was killed left a container in the Created state for one of these eight timeouts.
    timeouts = [0.05 * step for step in range(1, 9)]
    for timeout_s in timeouts:
        assert box.run("sleep 30", timeout_s=timeout_s).timed_out
    assert len(set(names)) == len(timeouts)
    for name in sorted(set(names)):
        listed = subprocess.run(
            [box.executable, "ps", "--all", "--quiet", "--filter", f"name={name}"],
            capture_output=True,
            text=True,
            check=True,
            env=docker_client_env(os.environ),
            timeout=60,
        )
        assert listed.stdout.strip() == "", name


@pytest.mark.slow
@needs_docker
def test_real_container_is_killed_on_timeout(workspace: Path) -> None:
    box = DockerSandbox(workspace)
    outcome = box.run("(sleep 2; touch late) & sleep 60", timeout_s=1.0)
    assert outcome.timed_out and outcome.exit_code == TIMEOUT_EXIT_CODE
    time.sleep(2.5)
    assert not (workspace / "late").exists()
