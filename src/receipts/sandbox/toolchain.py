"""A read-only Python toolchain for sandboxed commands, built once outside any sandbox.

Sandboxed commands have no network, so test tools such as pytest must already exist.
:func:`python_toolchain` builds a uv virtualenv with pinned packages on the host (this
is the project's own setup, not third-party code, so it runs outside the sandbox and
may use the network), records what it built in a marker file, and reuses it on later
calls with the same specification. :func:`with_toolchain` then puts its ``bin``
directory first on the sandbox ``PATH`` and makes its directories read-only mounts.

uv is always run with ``--no-config`` (no ``uv.toml`` or ``pyproject.toml`` from the
current directory) and installs with ``--link-mode copy``, so the virtualenv does not
depend on uv's cache. The interpreter's own prefix is added to the read-only paths
unless it is a system prefix (``/usr``, ``/usr/local``); a virtualenv built on a system
interpreter therefore works under bubblewrap and unshare, which see the host's
``/usr``, but not inside a Docker image, which has its own.
"""

from __future__ import annotations

import fcntl
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from receipts.sandbox.api import SandboxPolicy
from receipts.sandbox.env import DEFAULT_PATH

MARKER_NAME = "receipts-toolchain.json"
BUILDING_NAME = ".receipts-toolchain-building"

#: Interpreter prefixes that every host has; they are never mounted explicitly.
SYSTEM_PREFIXES: frozenset[Path] = frozenset({Path("/"), Path("/usr"), Path("/usr/local")})

_PIN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?(?:\[[A-Za-z0-9._,-]+\])?"
    r"==[A-Za-z0-9][A-Za-z0-9.+!_-]*"
)

#: Runs one command (argv, working directory) and returns its result.
Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


class ToolchainError(RuntimeError):
    """Raised when a toolchain cannot be built or an existing path is not a toolchain."""


@dataclass(frozen=True)
class Toolchain:
    """A built virtualenv that sandboxed commands may use read-only.

    Attributes:
        path: The virtualenv directory.
        python: Its interpreter.
        bin_dir: Its ``bin`` directory (put first on the sandbox ``PATH``).
        packages: The pinned packages it was built from.
        installed: ``uv pip freeze`` output: every installed distribution and version.
        base_prefix: The base interpreter's prefix (``sys.base_prefix``).
        readonly_paths: Host paths a sandbox must mount read-only to use it.
        built: True if this call built it, False if an existing build was reused.
        commands: The build commands run by this call (empty when reused).
    """

    path: Path
    python: Path
    bin_dir: Path
    packages: tuple[str, ...]
    installed: tuple[str, ...]
    base_prefix: Path
    readonly_paths: tuple[Path, ...]
    built: bool
    commands: tuple[tuple[str, ...], ...]


def check_pins(packages: Iterable[str]) -> tuple[str, ...]:
    """Return ``packages`` if every one is pinned exactly (``name==version``).

    Raises:
        ValueError: A package is not of the form ``name==version`` (extras allowed).
    """
    pins = tuple(packages)
    loose = [p for p in pins if not _PIN.fullmatch(p)]
    if loose:
        raise ValueError(f"packages must be pinned as name==version: {', '.join(loose)}")
    return pins


def venv_python(path: Path) -> Path:
    """The interpreter of the virtualenv at ``path``."""
    return path / "bin" / "python"


def toolchain_commands(
    path: str | Path,
    packages: Iterable[str],
    *,
    python: str = "3.11",
    uv: str = "uv",
    exclude_newer: str | None = None,
    offline: bool = False,
) -> list[list[str]]:
    """The uv commands that build the toolchain at ``path``, in order.

    Args:
        path: The virtualenv directory.
        packages: Pinned packages (see :func:`check_pins`); none means no install step.
        python: The interpreter request passed to ``uv venv --python``.
        uv: The uv executable.
        exclude_newer: Optional date: dependencies are resolved as of this date.
        offline: Pass ``--offline`` to every uv command.
    """
    pins = check_pins(packages)
    target = Path(path)
    extra = ["--offline"] if offline else []
    commands = [
        [
            uv,
            "venv",
            "--no-config",
            "--no-project",
            "--allow-existing",
            "--quiet",
            "--python",
            python,
            *extra,
            str(target),
        ]
    ]
    if pins:
        newer = ["--exclude-newer", exclude_newer] if exclude_newer else []
        commands.append(
            [
                uv,
                "pip",
                "install",
                "--no-config",
                "--quiet",
                "--link-mode",
                "copy",
                "--python",
                str(venv_python(target)),
                *newer,
                *extra,
                *pins,
            ]
        )
    return commands


def inspect_commands(path: str | Path, *, uv: str = "uv") -> list[list[str]]:
    """The commands that report what a built toolchain holds: freeze, then base prefix."""
    python = str(venv_python(Path(path)))
    return [
        [uv, "pip", "freeze", "--no-config", "--python", python],
        [python, "-c", "import sys; print(sys.base_prefix)"],
    ]


def _default_runner(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), cwd=cwd, capture_output=True, text=True, check=False, timeout=1800
    )


def _checked(run: Runner, argv: Sequence[str], cwd: Path) -> str:
    result = run(argv, cwd)
    if result.returncode != 0:
        lines = (result.stderr or "").strip().splitlines()
        reason = lines[-1] if lines else f"exit code {result.returncode}"
        raise ToolchainError(f"{' '.join(argv[:3])} failed: {reason}")
    return result.stdout or ""


@contextmanager
def _locked(lock_path: Path) -> Iterator[None]:
    with lock_path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_marker(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((path / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _readonly_paths(path: Path, base_prefix: Path) -> tuple[Path, ...]:
    if base_prefix in SYSTEM_PREFIXES:
        return (path,)
    return (path, base_prefix)


def _from_marker(path: Path, marker: dict[str, Any]) -> Toolchain:
    base_prefix = Path(marker["base_prefix"])
    return Toolchain(
        path=path,
        python=venv_python(path),
        bin_dir=path / "bin",
        packages=tuple(marker["spec"]["packages"]),
        installed=tuple(marker["installed"]),
        base_prefix=base_prefix,
        readonly_paths=_readonly_paths(path, base_prefix),
        built=False,
        commands=(),
    )


def _clear_previous(path: Path) -> None:
    """Remove an outdated or half-built toolchain; refuse anything else."""
    if (path / MARKER_NAME).is_file() or (path / BUILDING_NAME).is_file():
        shutil.rmtree(path)
    elif path.is_dir() and not any(path.iterdir()):
        path.rmdir()
    else:
        raise ToolchainError(f"refusing to replace {path}: it is not a receipts toolchain")


def python_toolchain(
    path: str | Path,
    packages: Iterable[str],
    *,
    python: str = "3.11",
    uv: str = "uv",
    exclude_newer: str | None = None,
    offline: bool = False,
    run: Runner | None = None,
) -> Toolchain:
    """Build (once) a uv virtualenv at ``path`` with pinned ``packages``.

    A later call with the same specification (interpreter request, packages,
    ``exclude_newer``) reuses the build without running anything. A different
    specification rebuilds it. Concurrent calls for the same path are serialized
    with a lock file next to it.

    Args:
        path: The virtualenv directory (created; its parent is created if missing).
        packages: Pinned packages, for example ``("pytest==8.3.3",)``.
        python: The interpreter request for ``uv venv --python``.
        uv: The uv executable.
        exclude_newer: Optional date limiting dependency versions.
        offline: Forbid uv from using the network.
        run: Command runner (tests pass a fake); ``subprocess.run`` if None.

    Raises:
        ValueError: A package is not pinned.
        ToolchainError: A build command failed, or ``path`` exists and is not a
            receipts toolchain.
    """
    pins = check_pins(packages)
    target = Path(path).absolute()
    runner: Runner = run if run is not None else _default_runner
    spec = {"python": python, "packages": sorted(pins), "exclude_newer": exclude_newer}
    target.parent.mkdir(parents=True, exist_ok=True)
    with _locked(target.parent / f".{target.name}.lock"):
        marker = _read_marker(target)
        if (
            marker is not None
            and marker.get("spec") == spec
            and venv_python(target).exists()
            and not (target / BUILDING_NAME).exists()
        ):
            return _from_marker(target, marker)
        if target.exists() or target.is_symlink():
            _clear_previous(target)
        target.mkdir()
        (target / BUILDING_NAME).write_text("receipts toolchain build in progress\n", "utf-8")
        commands = toolchain_commands(
            target, pins, python=python, uv=uv, exclude_newer=exclude_newer, offline=offline
        )
        for argv in commands:
            _checked(runner, argv, target.parent)
        freeze, prefix = inspect_commands(target, uv=uv)
        installed = tuple(
            line.strip() for line in _checked(runner, freeze, target.parent).splitlines()
        )
        installed = tuple(line for line in installed if line)
        base_prefix = Path(_checked(runner, prefix, target.parent).strip())
        record = {
            "spec": spec,
            "installed": list(installed),
            "base_prefix": str(base_prefix),
            "commands": commands,
        }
        (target / MARKER_NAME).write_text(json.dumps(record, indent=2) + "\n", "utf-8")
        (target / BUILDING_NAME).unlink()
    return Toolchain(
        path=target,
        python=venv_python(target),
        bin_dir=target / "bin",
        packages=pins,
        installed=installed,
        base_prefix=base_prefix,
        readonly_paths=_readonly_paths(target, base_prefix),
        built=True,
        commands=tuple(tuple(argv) for argv in commands),
    )


def with_toolchain(
    policy: SandboxPolicy, toolchain: Toolchain, base_path: str = DEFAULT_PATH
) -> SandboxPolicy:
    """Return ``policy`` with the toolchain first on ``PATH`` and its paths read-only.

    The previous ``PATH`` (``policy.env["PATH"]`` or ``base_path``) follows the
    toolchain's ``bin`` directory; read-only paths are merged without duplicates.
    """
    current = policy.env.get("PATH", base_path)
    env = {**policy.env, "PATH": f"{toolchain.bin_dir}:{current}"}
    readonly = tuple(dict.fromkeys([*policy.readonly_paths, *toolchain.readonly_paths]))
    return replace(policy, env=env, readonly_paths=readonly)
