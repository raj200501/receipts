"""BwrapSandbox: bubblewrap with the host root read-only and the workspace writable.

Layout of every sandbox (later mounts cover earlier ones; the variable part is sorted
by path depth so a nested mount always wins over its parent):

- the host root bind-mounted read-only, with a private ``/dev`` and a new ``/proc``;
- private, empty, writable ``/tmp`` and ``/run`` (so host sockets under ``/run``, such
  as the Docker daemon's, are out of reach: a read-only mount does not stop
  ``connect()`` on a Unix socket);
- hidden paths: known credential locations under every home directory (each entry of
  ``/home``, every home in the password database, ``/root``, and the current user's),
  system credential files, and this project's own checkout (benchmark hidden checks,
  private data) are covered by an empty tmpfs (directories) or ``/dev/null`` (files);
- ``policy.readonly_paths`` bind-mounted read-only at the same path (a tool under a
  hidden or private path, such as this checkout's ``.venv`` or a toolchain under
  ``/tmp``, is visible only when listed there);
- the workspace bind-mounted read-write at the same path, the only writable host path.

All namespaces are unshared (``--unshare-all``: no network unless ``policy.network``),
all capabilities are dropped (``--cap-drop ALL``; without it a sandbox started by root
could remount the root read-write), and the sandbox dies with its parent and runs in
a new session. The environment is cleared and rebuilt from the allowlist
(:func:`receipts.sandbox.env.clean_env`); the launcher applies the address-space,
CPU-time, and process rlimits inside the namespaces. ``max_procs`` is also enforced
with a per-command pids cgroup when one is available (:mod:`receipts.sandbox.cgroup`),
because the kernel does not apply ``ulimit -u`` to the host's root user; ``/sys`` is
read-only inside, so a command cannot leave that cgroup.

The mounts are computed again before every command: a hidden path that has vanished
is skipped, and a read-only path that has vanished raises
:class:`~receipts.sandbox.api.SandboxUnavailableError`. The launcher reports through a
status pipe that it started the command, so when bubblewrap itself fails (a mount it
cannot make, for example), :meth:`~receipts.sandbox.base.ProcessSandbox.run` raises
instead of reporting bubblewrap's exit status as the command's.

Known limits:

- Without a usable pids cgroup (cgroup v2 without delegation, or a read-only
  cgroup filesystem), ``max_procs`` rests on ``ulimit -u`` alone, which does not bind
  the host's root user; :attr:`~receipts.sandbox.base.ProcessSandbox.process_limit`
  then reports ``"none"`` under root.
- Hiding covers the listed credential locations, not every secret on the host: a
  sandbox started by root can read any other file root can read.
"""

from __future__ import annotations

import contextlib
import pwd
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import ClassVar

from receipts.sandbox.api import SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import (
    LAUNCHER_ARG0,
    BackendProbe,
    ProcessSandbox,
    StartReport,
    check_readonly_paths,
    find_executable,
    launcher_script,
    require_paths,
    rlimit_values,
)
from receipts.sandbox.process import DEFAULT_MAX_CAPTURE_BYTES, Launch

#: Credential locations hidden under each home directory (best effort, not exhaustive).
CREDENTIAL_PATHS: tuple[str, ...] = (
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".boto",
    ".config/gcloud",
    ".config/gh",
    ".config/hub",
    ".config/rclone",
    ".docker",
    ".kube",
    ".netrc",
    ".git-credentials",
    ".gitconfig",
    ".npmrc",
    ".pypirc",
    ".yarnrc",
    ".yarnrc.yml",
    ".gradle",
    ".m2",
    ".cargo/credentials",
    ".cargo/credentials.toml",
    ".claude",
    ".claude.json",
    ".config/claude",
    ".codex",
    ".gemini",
    ".ccr",
    ".pki",
    ".local/share/keyrings",
    ".password-store",
    ".vault-token",
    ".s3cfg",
    ".mozilla",
    ".config/google-chrome",
    ".config/chromium",
)

#: System files and directories with password hashes, private keys (SSH host keys, TLS
#: keys), or mounted secrets, hidden when present. A sandbox started by root runs as
#: a user that owns root's files, so file permissions alone do not protect these.
SYSTEM_CREDENTIAL_PATHS: tuple[str, ...] = (
    "/etc/shadow",
    "/etc/gshadow",
    "/etc/ssh",
    "/etc/ssl/private",
    "/var/run/secrets",
)

#: Directories replaced by a private, empty tmpfs in every sandbox.
PRIVATE_DIRS: tuple[str, ...] = ("/tmp", "/run")


def project_root() -> Path | None:
    """The receipts checkout this package runs from, or None when installed elsewhere."""
    root = Path(__file__).resolve().parents[3]
    if (root / "pyproject.toml").is_file() and (root / "src" / "receipts").is_dir():
        return root
    return None


def home_directories(
    home_root: Path = Path("/home"), passwd_homes: Iterable[str] | None = None
) -> tuple[Path, ...]:
    """Every home directory on this host that exists, without duplicates.

    Args:
        home_root: The directory whose entries are home directories (``/home``).
        passwd_homes: Home directories from the password database; read with
            :func:`pwd.getpwall` if None.

    Returns:
        The current user's home, ``/root``, each directory directly under
        ``home_root``, and each password-database home, in that order, resolved.
    """
    if passwd_homes is None:
        passwd_homes = [entry.pw_dir for entry in pwd.getpwall()]
    candidates = [Path.home(), Path("/root")]
    with contextlib.suppress(OSError):
        candidates += sorted(child for child in home_root.iterdir() if child.is_dir())
    candidates += [Path(home) for home in passwd_homes if home and Path(home).is_absolute()]
    found: dict[Path, None] = {}
    for home in candidates:
        if home.is_dir():
            found[home.resolve()] = None
    return tuple(found)


def default_hidden_paths(
    homes: Iterable[Path] | None = None, project: Path | None = None
) -> tuple[Path, ...]:
    """Host paths a :class:`BwrapSandbox` hides unless told otherwise.

    Args:
        homes: Home directories to scan for :data:`CREDENTIAL_PATHS`; every home
            directory on the host (:func:`home_directories`) if None.
        project: A checkout to hide; :func:`project_root` if None.

    Returns:
        Existing paths, resolved, without duplicates: credential locations under each
        home, :data:`SYSTEM_CREDENTIAL_PATHS`, and the project checkout.
    """
    if homes is None:
        homes = home_directories()
    candidates = [Path(home) / rel for home in homes for rel in CREDENTIAL_PATHS]
    candidates += [Path(p) for p in SYSTEM_CREDENTIAL_PATHS]
    checkout = project_root() if project is None else project
    if checkout is not None:
        candidates.append(checkout)
    found: dict[Path, None] = {}
    for path in candidates:
        if path.exists():
            found[path.resolve()] = None
    return tuple(found)


def _depth(path: Path) -> int:
    return len(path.parts)


def mount_args(
    workspace: Path, readonly: Sequence[Path] = (), hidden: Sequence[Path] = ()
) -> list[str]:
    """The bubblewrap mount options for one sandbox (see the module docstring)."""
    ops: list[tuple[int, int, str, list[str]]] = []
    for private in PRIVATE_DIRS:
        if Path(private).is_dir():
            ops.append((_depth(Path(private)), 0, private, ["--tmpfs", private]))
    for path in hidden:
        if path.is_dir():
            ops.append((_depth(path), 0, str(path), ["--tmpfs", str(path)]))
        elif path.exists():
            ops.append((_depth(path), 0, str(path), ["--ro-bind", "/dev/null", str(path)]))
    for path in readonly:
        ops.append((_depth(path), 1, str(path), ["--ro-bind", str(path), str(path)]))
    ops.append((_depth(workspace), 2, str(workspace), ["--bind", str(workspace), str(workspace)]))
    ops.sort(key=lambda op: (op[0], op[1], op[2]))
    args = ["--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
    for op in ops:
        args.extend(op[3])
    return args


class BwrapSandbox(ProcessSandbox):
    """Run each command in a fresh bubblewrap sandbox (see the module docstring).

    Writes are confined to the workspace and there is no network unless
    ``policy.network``. ``max_procs`` is enforced with a pids cgroup when one is
    available (see :attr:`process_limit` and the module's known limits).

    Args:
        workspace: The workspace directory, the only writable host path.
        policy: Limits and allowances; :class:`SandboxPolicy` defaults if None.
        bwrap: The bubblewrap executable.
        hide_paths: Host paths to hide; :func:`default_hidden_paths` if None. Paths
            that do not exist are skipped. ``/tmp`` and ``/run`` are always private.
        max_capture_bytes: Stream ceiling before the command is stopped.

    Raises:
        SandboxUnavailableError: bubblewrap or bash is not installed.
        ValueError: The workspace, the policy, or a read-only path is invalid.
    """

    backend_name: ClassVar[str] = "bwrap"
    confines_writes: ClassVar[bool] = True
    start_report: ClassVar[StartReport] = "fd"
    uses_pids_cgroup: ClassVar[bool] = True

    def __init__(
        self,
        workspace: str | Path,
        policy: SandboxPolicy | None = None,
        *,
        bwrap: str = "bwrap",
        hide_paths: Iterable[str | Path] | None = None,
        max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
    ) -> None:
        super().__init__(workspace, policy, max_capture_bytes=max_capture_bytes)
        self._bwrap = find_executable(bwrap, "bubblewrap")
        self._bash = find_executable("bash", "bash")
        self._readonly = check_readonly_paths(self._policy.readonly_paths)
        if hide_paths is None:
            hidden = default_hidden_paths()
        else:
            hidden = tuple(Path(p).resolve() for p in hide_paths if Path(p).exists())
        self._hidden = hidden

    @property
    def executable(self) -> str:
        """The bubblewrap executable in use."""
        return self._bwrap

    @property
    def hidden_paths(self) -> tuple[Path, ...]:
        """The host paths this sandbox hides (besides the private ``/tmp`` and ``/run``)."""
        return self._hidden

    def launch(
        self, cmd: str, cwd: Path, *, interactive: bool = False, status_fd: int | None = None
    ) -> Launch:
        """The bubblewrap command line for ``cmd`` (``cwd`` is the same path inside).

        The mounts are computed now: hidden paths that no longer exist are skipped.
        With ``status_fd``, the launcher reports on it that the command started.

        Raises:
            SandboxUnavailableError: A read-only path no longer exists.
        """
        require_paths(self._readonly, "read-only paths")
        hidden = [path for path in self._hidden if path.exists()]
        argv = [self._bwrap, *mount_args(self._workspace, self._readonly, hidden)]
        argv.append("--unshare-all")
        if self._policy.network:
            argv.append("--share-net")
        argv += ["--cap-drop", "ALL", "--die-with-parent", "--new-session", "--clearenv"]
        for name, value in sorted(self._env.items()):
            argv += ["--setenv", name, value]
        script = launcher_script(self._bash, rlimit_values(self._policy), status_fd=status_fd)
        argv += ["--chdir", str(cwd), "--", self._bash, "-c", script, LAUNCHER_ARG0, cmd]
        fds = () if status_fd is None else (status_fd,)
        return Launch(argv=tuple(argv), env=self._env, cwd=cwd, pass_fds=fds)


def probe_bwrap(bwrap: str = "bwrap") -> BackendProbe:
    """Check that bubblewrap can run a trivial command with this module's full layout.

    The detail of a working backend names the executable and how ``max_procs`` is
    enforced (:attr:`~receipts.sandbox.base.ProcessSandbox.process_limit`).
    """
    try:
        with tempfile.TemporaryDirectory(prefix="receipts-probe-") as tmp:
            box = BwrapSandbox(tmp, SandboxPolicy(timeout_s=30.0), bwrap=bwrap)
            outcome = box.run("true")
    except SandboxUnavailableError as exc:
        return BackendProbe("bwrap", False, f"bubblewrap fails here: {exc}")
    if outcome.exit_code != 0:
        lines = outcome.stderr.strip().splitlines()
        reason = lines[-1] if lines else f"exit code {outcome.exit_code}"
        return BackendProbe("bwrap", False, f"bubblewrap fails here: {reason}")
    return BackendProbe("bwrap", True, f"{box.executable} (process limit: {box.process_limit})")
