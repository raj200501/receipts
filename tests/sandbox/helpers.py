"""Shared helpers for the sandbox tests: backend availability and process checks."""

from __future__ import annotations

import functools
import time
import uuid
from pathlib import Path

import pytest

from receipts.sandbox.base import BackendProbe
from receipts.sandbox.bwrap import probe_bwrap
from receipts.sandbox.docker import DEFAULT_IMAGE, probe_docker
from receipts.sandbox.unshare import probe_unshare

#: Synthetic credential-like values planted in the host environment (test data only).
PLANTED_SECRETS: dict[str, str] = {
    "GH_TOKEN": "synthetic-gh-token-value",
    "GITHUB_TOKEN": "synthetic-github-token-value",
    "SSH_AUTH_SOCK": "/tmp/synthetic-agent.sock",
    "AWS_ACCESS_KEY_ID": "SYNTHETICAWSKEYID",
    "AWS_SECRET_ACCESS_KEY": "synthetic-aws-secret-value",
    "ANTHROPIC_API_KEY": "synthetic-anthropic-key-value",
    "ANTHROPIC_BASE_URL": "http://synthetic.invalid",
    "HTTPS_PROXY": "http://synthetic-user:synthetic-pass@proxy.invalid:3128",
}

#: Python one-liner that tries to open a TCP connection to a public resolver.
CONNECT_CMD = "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)\""

#: Command that tries to fork 60 children and prints how many forks succeeded and
#: failed (``"<started> <failed>"``); the children exit once the parent is done.
FORK_CMD = (
    "python3 -c 'import os\n"
    "r, w = os.pipe()\n"
    "started = failed = 0\n"
    "for _ in range(60):\n"
    "    try:\n"
    "        pid = os.fork()\n"
    "    except OSError:\n"
    "        failed += 1\n"
    "        continue\n"
    "    if pid == 0:\n"
    "        os.close(w)\n"
    "        os.read(r, 1)\n"
    "        os._exit(0)\n"
    "    started += 1\n"
    "os.close(w)\n"
    "print(started, failed)'"
)


@functools.cache
def bwrap_probe() -> BackendProbe:
    """Whether bubblewrap works here (probed once per test session)."""
    return probe_bwrap()


@functools.cache
def unshare_probe() -> BackendProbe:
    """Whether unshare works here (probed once per test session)."""
    return probe_unshare()


@functools.cache
def docker_probe() -> BackendProbe:
    """Whether Docker works here with the default image cached (probed once)."""
    return probe_docker(image=DEFAULT_IMAGE)


def requires(probe: BackendProbe) -> pytest.MarkDecorator:
    """Skip the test with a clear reason unless ``probe`` succeeded."""
    return pytest.mark.skipif(
        not probe.ok, reason=f"{probe.name} does not work on this machine: {probe.detail}"
    )


def unique_marker() -> str:
    """A process-name marker no other test (or agent) uses."""
    return f"receipts-test-marker-{uuid.uuid4().hex}"


def processes_with(marker: str) -> list[int]:
    """PIDs of live processes whose command line contains ``marker``."""
    needle = marker.encode()
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if needle in cmdline:
            found.append(int(entry.name))
    return found


def wait_until_gone(marker: str, timeout_s: float = 5.0) -> bool:
    """True once no process carries ``marker``; False if some still do after the wait."""
    deadline = time.monotonic() + timeout_s
    while processes_with(marker):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def background_sleeper(marker: str, *, own_session: bool = False) -> str:
    """Shell text that starts a long sleep named ``marker`` in the background."""
    start = "setsid " if own_session else ""
    return f"{start}bash -c 'exec -a {marker} sleep 60' &"
