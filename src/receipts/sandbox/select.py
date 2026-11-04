"""Pick the best sandbox backend that works on this machine.

The order of preference follows docs/BUILD_BRIEF.md section 8 and DECISIONS D22:
Docker (``--network none``), then bubblewrap, then ``unshare -rn``. Only the first two
confine writes; ``unshare`` may run only this project's own generated tasks (D5), so
callers that run third-party code should pass ``prefer=("docker", "bwrap")``.

A backend can work and still lack what the commands need: the default Docker image
has no git and no pytest, while bubblewrap sees the host's tools. Callers that depend
on a tool pass ``check_cmd`` (for example ``"command -v git"``) to
:func:`make_sandbox`, which then skips every backend where it fails.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from receipts.sandbox.api import CommandOutcome, SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import BackendProbe, ProcessSandbox
from receipts.sandbox.bwrap import BwrapSandbox, probe_bwrap
from receipts.sandbox.docker import DEFAULT_IMAGE, DockerSandbox, probe_docker
from receipts.sandbox.unshare import UnshareSandbox, probe_unshare

DEFAULT_PREFERENCE: tuple[str, ...] = ("docker", "bwrap", "unshare")

#: Probe for each backend name, given the Docker image to look for.
PROBES: dict[str, Callable[[str], BackendProbe]] = {
    "docker": lambda image: probe_docker(image=image),
    "bwrap": lambda image: probe_bwrap(),
    "unshare": lambda image: probe_unshare(),
}

#: Builds a sandbox: (workspace, policy, Docker image, bubblewrap hide_paths).
Factory = Callable[
    [str | Path, SandboxPolicy | None, str, Iterable[str | Path] | None], ProcessSandbox
]

#: Constructor for each backend name.
FACTORIES: dict[str, Factory] = {
    "docker": lambda ws, policy, image, hide: DockerSandbox(ws, policy, image=image),
    "bwrap": lambda ws, policy, image, hide: BwrapSandbox(ws, policy, hide_paths=hide),
    "unshare": lambda ws, policy, image, hide: UnshareSandbox(ws, policy),
}


def _check_names(prefer: Sequence[str]) -> tuple[str, ...]:
    names = tuple(prefer)
    unknown = sorted(set(names) - set(PROBES))
    if unknown:
        raise ValueError(f"unknown sandbox backends: {', '.join(unknown)}")
    if not names:
        raise ValueError("prefer names no backend")
    return names


def probe_backends(
    prefer: Sequence[str] = DEFAULT_PREFERENCE, *, image: str = DEFAULT_IMAGE
) -> tuple[BackendProbe, ...]:
    """Probe each named backend, in order, and return every result."""
    return tuple(PROBES[name](image) for name in _check_names(prefer))


def available_backends(
    prefer: Sequence[str] = DEFAULT_PREFERENCE, *, image: str = DEFAULT_IMAGE
) -> tuple[str, ...]:
    """Names of the backends that work on this machine, in the order of ``prefer``.

    Each probe is cheap: ``docker info`` and ``docker image inspect`` for Docker, and
    one ``true`` command for bubblewrap and unshare.

    Raises:
        ValueError: ``prefer`` is empty or names an unknown backend.
    """
    return tuple(p.name for p in probe_backends(prefer, image=image) if p.ok)


def _describe(outcome: CommandOutcome) -> str:
    """``exit N``, a timeout note, and the last stderr line of ``outcome``."""
    lines = outcome.stderr.strip().splitlines()
    tail = f": {lines[-1]}" if lines else ""
    timed_out = " (timed out)" if outcome.timed_out else ""
    return f"exit {outcome.exit_code}{timed_out}{tail}"


def make_sandbox(
    workspace: str | Path,
    policy: SandboxPolicy | None = None,
    prefer: Sequence[str] = DEFAULT_PREFERENCE,
    *,
    image: str = DEFAULT_IMAGE,
    hide_paths: Iterable[str | Path] | None = None,
    check_cmd: str | None = None,
) -> ProcessSandbox:
    """Return a sandbox on ``workspace`` from the first backend in ``prefer`` that works.

    A backend works when its probe succeeds, its sandbox can be built, and, if
    ``check_cmd`` is given, that command exits 0 inside the sandbox (run in the
    workspace root under ``policy``; it should only inspect, never write).

    Args:
        workspace: The workspace directory.
        policy: Limits and allowances; :class:`SandboxPolicy` defaults if None.
        prefer: Backend names in order of preference.
        image: The image for the Docker backend.
        hide_paths: Host paths the bubblewrap backend hides (its defaults if None).
        check_cmd: Optional shell command that must succeed in the chosen sandbox,
            for example ``"command -v git && python3 -m pytest --version"``.

    Raises:
        SandboxUnavailableError: No backend in ``prefer`` works; the message gives
            each backend's reason.
        ValueError: ``prefer`` is empty or names an unknown backend, or the
            workspace or policy is invalid.
    """
    reasons = []
    for name in _check_names(prefer):
        probe = PROBES[name](image)
        if not probe.ok:
            reasons.append(f"{name}: {probe.detail}")
            continue
        try:
            box = FACTORIES[name](workspace, policy, image, hide_paths)
        except SandboxUnavailableError as exc:
            reasons.append(f"{name}: {exc}")
            continue
        if check_cmd is not None:
            outcome = box.run(check_cmd)
            if outcome.exit_code != 0:
                reasons.append(f"{name}: check command failed ({_describe(outcome)})")
                continue
        return box
    raise SandboxUnavailableError("no sandbox backend works here: " + "; ".join(reasons))
