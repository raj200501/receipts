"""DockerSandbox: one ``docker run --rm --network none`` container per command.

Each container:

- runs a locally cached image (``--pull never``; Docker Hub rate-limits pulls, D22),
  by default ``python:3.11-slim``;
- has a read-only root filesystem with a private tmpfs ``/tmp``;
- sees the workspace bind-mounted read-write at the same path, each
  ``policy.readonly_paths`` entry read-only at the same path, and nothing else of
  the host;
- runs as the workspace owner's user and group, with every capability dropped and
  ``no-new-privileges``;
- is limited by ``--pids-limit`` (``max_procs``), ``--memory`` without swap
  (``memory_mb``), ``--cpus``, and a CPU-time ulimit (``cpu_s``);
- gets the clean environment (:func:`receipts.sandbox.env.clean_env`) through
  ``--env``, and nothing from the host environment; the launcher unsets any other
  variable the image defines (such as ``PYTHON_VERSION``), so the command sees the
  same environment as under the other backends.

On timeout the container is removed with ``docker rm --force``, once before the
client is killed and once after it is gone: a timeout shorter than container start-up
can otherwise leave a container the daemon created after the first removal (seen
here with a 0.2 second timeout). The ``docker`` client itself runs with only the
variables it needs to find the daemon.

The launcher writes :data:`~receipts.sandbox.base.STARTED` as the first line of the
container's stdout before it runs the command, and that line is removed from the
captured stream. Output a command writes inside the container can only follow it, so
when the client's stdout does not begin with it, the container never ran the command
(the daemon refused it, or a mount source is gone):
:meth:`~receipts.sandbox.base.ProcessSandbox.run` then raises
:class:`~receipts.sandbox.api.SandboxUnavailableError` instead of reporting the
client's exit status (125 for daemon errors) as the command's. Read-only paths are
checked again before each command for the same reason.

The default image has bash and Python but neither git nor pytest; commands that need
them want another locally cached image. :func:`receipts.sandbox.select.make_sandbox`
runs a check command (by default ``command -v git``) so that a backend without the
tools is skipped.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from receipts.sandbox.api import SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import (
    LAUNCHER_ARG0,
    STARTED,
    BackendProbe,
    ProcessSandbox,
    StartReport,
    check_readonly_paths,
    find_executable,
    launcher_script,
    require_paths,
)
from receipts.sandbox.process import DEFAULT_MAX_CAPTURE_BYTES, Launch

DEFAULT_IMAGE = "python:3.11-slim"

#: The first bytes of the client's stdout once the container's launcher has started.
STARTED_MARKER = f"{STARTED}\n".encode()

#: Host variables the ``docker`` client may see (to find and talk to the daemon).
CLIENT_ENV_NAMES: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
    "DOCKER_HOST",
    "DOCKER_CONFIG",
    "DOCKER_CONTEXT",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
    "DOCKER_API_VERSION",
)

_STOP_TIMEOUT_S = 30.0


def docker_client_env(host_env: Mapping[str, str]) -> dict[str, str]:
    """The environment of the ``docker`` client process: :data:`CLIENT_ENV_NAMES` only."""
    return {name: host_env[name] for name in CLIENT_ENV_NAMES if name in host_env}


def check_image(image: str) -> str:
    """Return ``image``, or raise ValueError if it is empty, has whitespace, or starts with -."""
    if not image or image.startswith("-") or any(ch.isspace() for ch in image):
        raise ValueError(f"invalid Docker image reference: {image!r}")
    return image


def check_mount_path(path: Path) -> Path:
    """Return ``path``, or raise ValueError if ``--mount`` cannot express it."""
    text = str(path)
    if any(ch in text for ch in ',"\n\r'):
        raise ValueError(f"path cannot be bind-mounted by docker --mount: {text!r}")
    return path


class DockerSandbox(ProcessSandbox):
    """Run each command in a fresh, network-less container (see the module docstring).

    Args:
        workspace: The workspace directory, mounted read-write at the same path.
        policy: Limits and allowances; :class:`SandboxPolicy` defaults if None.
        image: A locally cached image that has bash.
        docker: The ``docker`` client executable.
        cpus: The ``--cpus`` quota; the smaller of 2 and the host CPU count if None.
        tmp_size_mb: Size of the container's tmpfs ``/tmp``.
        max_capture_bytes: Stream ceiling before the command is stopped.

    Raises:
        SandboxUnavailableError: The ``docker`` client is not installed.
        ValueError: The workspace, the policy, a path, the image, ``cpus``, or
            ``tmp_size_mb`` is invalid.
    """

    backend_name: ClassVar[str] = "docker"
    confines_writes: ClassVar[bool] = True
    start_report: ClassVar[StartReport] = "stdout"

    def __init__(
        self,
        workspace: str | Path,
        policy: SandboxPolicy | None = None,
        *,
        image: str = DEFAULT_IMAGE,
        docker: str = "docker",
        cpus: float | None = None,
        tmp_size_mb: int = 512,
        max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
    ) -> None:
        super().__init__(workspace, policy, max_capture_bytes=max_capture_bytes)
        self._docker = find_executable(docker, "the docker CLI")
        self._image = check_image(image)
        self._cpus = float(min(2, os.cpu_count() or 1)) if cpus is None else float(cpus)
        if not self._cpus > 0:
            raise ValueError(f"cpus must be positive, got {cpus!r}")
        if tmp_size_mb <= 0:
            raise ValueError(f"tmp_size_mb must be positive, got {tmp_size_mb!r}")
        self._tmp_size_mb = tmp_size_mb
        self._readonly = tuple(
            check_mount_path(p) for p in check_readonly_paths(self._policy.readonly_paths)
        )
        check_mount_path(self._workspace)
        owner = self._workspace.stat()
        self._user = f"{owner.st_uid}:{owner.st_gid}"
        self._client_env = docker_client_env(os.environ)

    @property
    def executable(self) -> str:
        """The ``docker`` client in use."""
        return self._docker

    @property
    def image(self) -> str:
        """The image every container runs."""
        return self._image

    @property
    def process_limit(self) -> str:
        """``"docker"``: ``max_procs`` is the container's ``--pids-limit``."""
        return "docker"

    def command(self, cmd: str, cwd: Path, name: str, *, interactive: bool = False) -> list[str]:
        """The ``docker run`` command line for ``cmd`` in container ``name``."""
        policy = self._policy
        ws = str(self._workspace)
        argv = [
            self._docker,
            "run",
            "--rm",
            "--name",
            name,
            "--pull",
            "never",
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,exec,nosuid,nodev,size={self._tmp_size_mb}m",
            "--pids-limit",
            str(policy.max_procs),
            "--memory",
            f"{policy.memory_mb}m",
            "--memory-swap",
            f"{policy.memory_mb}m",
            "--cpus",
            f"{self._cpus:g}",
            "--ulimit",
            f"cpu={policy.cpu_s}:{policy.cpu_s}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            self._user,
            "--workdir",
            str(cwd),
            "--mount",
            f"type=bind,source={ws},target={ws}",
        ]
        if not policy.network:
            argv += ["--network", "none"]
        for path in self._readonly:
            argv += ["--mount", f"type=bind,source={path},target={path},readonly"]
        for key, value in sorted(self._env.items()):
            argv += ["--env", f"{key}={value}"]
        if interactive:
            argv.append("--interactive")
        script = launcher_script("bash", keep=self._env, status_fd=1)
        argv += [self._image, "bash", "-c", script, LAUNCHER_ARG0, cmd]
        return argv

    def stop_container(self, name: str) -> None:
        """``docker rm --force`` container ``name``, running or only created.

        Errors are ignored: the container may be gone already, or not created yet.
        """
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                [self._docker, "rm", "--force", name],
                capture_output=True,
                timeout=_STOP_TIMEOUT_S,
                check=False,
                env=self._client_env,
            )

    def launch(
        self, cmd: str, cwd: Path, *, interactive: bool = False, status_fd: int | None = None
    ) -> Launch:
        """A ``docker run`` launch whose stop step removes the container.

        ``status_fd`` is not used: descriptors do not reach a container, so the
        launcher reports on stdout (:data:`STARTED_MARKER`).

        Raises:
            SandboxUnavailableError: A read-only path no longer exists.
        """
        require_paths(self._readonly, "read-only paths")
        name = f"receipts-{uuid.uuid4().hex[:16]}"
        return Launch(
            argv=tuple(self.command(cmd, cwd, name, interactive=interactive)),
            env=self._client_env,
            cwd=self._workspace,
            stop=lambda: self.stop_container(name),
            stdout_marker=STARTED_MARKER,
        )


def _client(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=docker_client_env(os.environ),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def probe_docker(
    docker: str = "docker", image: str = DEFAULT_IMAGE, *, timeout_s: float = 30.0
) -> BackendProbe:
    """Check that Docker can run this module's containers here, without pulling.

    Three steps, each limited to ``timeout_s``: the daemon answers ``docker info``,
    ``image`` is cached locally, and one ``true`` command runs in a container with
    every option :class:`DockerSandbox` uses (a daemon can answer and still be unable
    to start such a container, or to mount a host directory).
    """
    try:
        exe = find_executable(docker, "the docker CLI")
    except SandboxUnavailableError as exc:
        return BackendProbe("docker", False, str(exc))
    info = _client([exe, "info", "--format", "{{.ServerVersion}}"], timeout_s)
    if info is None or info.returncode != 0:
        return BackendProbe("docker", False, "the Docker daemon is not reachable")
    found = _client([exe, "image", "inspect", "--format", "{{.Id}}", image], timeout_s)
    if found is None or found.returncode != 0:
        return BackendProbe("docker", False, f"image {image} is not cached locally")
    try:
        with tempfile.TemporaryDirectory(prefix="receipts-probe-") as tmp:
            box = DockerSandbox(tmp, SandboxPolicy(timeout_s=timeout_s), image=image, docker=exe)
            outcome = box.run("true")
    except (SandboxUnavailableError, ValueError, OSError) as exc:
        return BackendProbe("docker", False, f"containers do not run here: {exc}")
    if outcome.exit_code != 0:
        lines = outcome.stderr.strip().splitlines()
        reason = lines[-1] if lines else f"exit code {outcome.exit_code}"
        return BackendProbe("docker", False, f"containers do not run here: {reason}")
    version = info.stdout.strip() or "unknown"
    return BackendProbe("docker", True, f"{exe} (server {version}, image {image})")
