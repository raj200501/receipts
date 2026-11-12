"""Start and stop the local model server for one pinned GGUF model.

A server is started only on a port nothing answers on, and once it answers the session
confirms that the server is its own process serving what it was started with: for
llama.cpp, the window per slot, the slots, and the model file that ``GET /props``
reports (:meth:`LocalServer.confirm_serving`, DECISIONS D71). A server left running
by an earlier session therefore never answers a later session's requests unnoticed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from receipts.ledger.events import sha256_text

DEFAULT_PYTHON = Path("/opt/receipts-llm/bin/python")
DEFAULT_LLAMA_SERVER = Path("/opt/receipts-llamacpp/build/bin/llama-server")


@dataclass(frozen=True)
class LocalModel:
    """A pinned local model.

    Attributes:
        name: Short name used in configs, e.g. ``"qwen2.5-coder-7b-q4km"``.
        family: Model family for G7, e.g. ``"qwen"`` or ``"granite"``.
        path: Path of the GGUF file.
        sha256: Expected SHA-256 of the file (checked before serving).
        source: Repository and revision it came from.
        n_ctx: Context window to serve with, per slot: the pinned window. A study
            session may serve a copy with another window (``tools/run_study.py
            --n-ctx``, DECISIONS D71), and the run record says so.
    """

    name: str
    family: str
    path: Path
    sha256: str
    source: str
    n_ctx: int = 16384


def llama_server_command(
    model: LocalModel, port: int, threads: int, parallel: int, binary: Path = DEFAULT_LLAMA_SERVER
) -> list[str]:
    """llama.cpp ``llama-server`` with ``parallel`` slots and continuous batching.

    Each slot gets the model's full context (the server divides ``--ctx-size`` among
    slots), and the KV cache is stored at 8 bits to fit several slots in RAM.
    """
    return [
        str(binary),
        "--model",
        str(model.path),
        "--alias",
        model.name,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        str(model.n_ctx * parallel),
        "--parallel",
        str(parallel),
        "--threads",
        str(threads),
        "--cache-type-k",
        "q8_0",
        "--cache-type-v",
        "q8_0",
        "--jinja",
    ]


def server_command(
    model: LocalModel, port: int, threads: int, python: Path = DEFAULT_PYTHON
) -> list[str]:
    """Return the exact server command line (recorded in run provenance)."""
    return [
        str(python),
        "-m",
        "llama_cpp.server",
        "--model",
        str(model.path),
        "--model_alias",
        model.name,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--n_ctx",
        str(model.n_ctx),
        "--n_threads",
        str(threads),
        "--cache",
        "true",
    ]


def file_sha256(path: Path, chunk: int = 1 << 22) -> str:
    """SHA-256 of a large file, streamed."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


class ServerStateError(RuntimeError):
    """The model server that answers is not this session's own server serving what it
    was started with (DECISIONS D71): something else holds the port, the server process
    is not running, or it reports another window per slot, slot count, or model file."""


def get_json(url: str, timeout_s: float = 30.0) -> object:
    """``GET url`` on the loopback without any proxy, parsed as JSON; None when nothing
    answers or the answer is not JSON."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError):
        return None


def server_ready(base_url: str, timeout_s: float = 2.0) -> bool:
    """True when ``GET {base_url}/models`` answers with JSON."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(base_url.rstrip("/") + "/models", timeout=timeout_s) as resp:
            json.loads(resp.read().decode("utf-8"))
            return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError):
        return False


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def props_report(props: object) -> dict[str, Any] | None:
    """What llama.cpp's ``GET /props`` says its server serves: the window per slot
    (``default_generation_settings.n_ctx``), the slots (``total_slots``), and the model
    file (``model_path``), as ``{"source": "GET /props", "n_ctx_per_slot": ...,
    "total_slots": ..., "model_path": ...}``; None when it does not say all three (the
    window and slots as positive integers, the file as text)."""
    if not isinstance(props, dict):
        return None
    settings = props.get("default_generation_settings")
    window = settings.get("n_ctx") if isinstance(settings, dict) else None
    slots, path = props.get("total_slots"), props.get("model_path")
    if not (_positive_int(window) and _positive_int(slots) and isinstance(path, str)):
        return None
    return {
        "source": "GET /props",
        "n_ctx_per_slot": window,
        "total_slots": slots,
        "model_path": path,
    }


@dataclass
class LocalServer:
    """A running local model server (llama-cpp-python, or llama.cpp with parallel slots).

    Use as a context manager.

    Args:
        model: The pinned model to serve; its hash is verified first unless
            ``verify_hash`` is False.
        port: Loopback port.
        threads: CPU threads for inference.
        log_path: Where server stdout and stderr go (under ``runs/``).
    """

    model: LocalModel
    port: int = 8081
    threads: int = 4
    log_path: Path = Path("runs/llm-server.log")
    python: Path = DEFAULT_PYTHON
    engine: Literal["llama-cpp-python", "llama.cpp"] = "llama-cpp-python"
    parallel: int = 1
    llama_server: Path = DEFAULT_LLAMA_SERVER
    verify_hash: bool = True
    startup_timeout_s: float = 300.0
    _proc: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    @property
    def base_url(self) -> str:
        """The OpenAI-compatible base URL."""
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def ctx_size(self) -> int:
        """The context the server holds in all, in tokens: llama.cpp gives each of its
        ``parallel`` slots the model's window (``--ctx-size`` is their sum), and
        llama-cpp-python serves one sequence with the model's window (``--n_ctx``)."""
        if self.engine == "llama.cpp":
            return self.model.n_ctx * self.parallel
        return self.model.n_ctx

    def command(self) -> Sequence[str]:
        """The server command line."""
        if self.engine == "llama.cpp":
            return llama_server_command(
                self.model, self.port, self.threads, self.parallel, self.llama_server
            )
        return server_command(self.model, self.port, self.threads, self.python)

    def start(self) -> None:
        """Verify the model hash, start the server, and wait until it answers.

        Nothing may answer on the port before the server starts: requests would reach
        that server instead. Once the port answers, the server must be this session's
        own process serving what it was started with (:meth:`confirm_serving`).

        Raises:
            RuntimeError: The model file does not match its pinned SHA-256, the server
                exited early, or it did not answer in time.
            ServerStateError: Something already answers on the port (no server is
                started), or the server that answers is not this one serving what it was
                started with (it is stopped).
        """
        if self.verify_hash and file_sha256(self.model.path) != self.model.sha256:
            raise RuntimeError(f"{self.model.path} does not match its pinned sha256")
        if server_ready(self.base_url):
            raise ServerStateError(
                f"something already answers on port {self.port} ({self.base_url}), so this "
                "session's requests would reach it and not the server it starts; stop it first"
            )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("ab")
        self._proc = subprocess.Popen(list(self.command()), stdout=log, stderr=log)
        deadline = time.monotonic() + self.startup_timeout_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"model server exited early; see {self.log_path}")
            if server_ready(self.base_url):
                try:
                    self.confirm_serving()
                except ServerStateError:
                    self.stop()
                    raise
                return
            self._sleep(1.0)
        self.stop()
        raise RuntimeError("model server did not become ready in time")

    def confirm_serving(self) -> dict[str, Any] | None:
        """Confirm that this session's server process is running and, for llama.cpp,
        that it reports serving the window per slot, the slots, and the model file it was
        started with (``GET /props``, :func:`props_report`); return that report, or None
        for llama-cpp-python, which reports neither.

        Raises:
            ServerStateError: The process is not running, so whatever answers on the
                port is another server; or the report is missing or differs.
        """
        if self._proc is None or self._proc.poll() is not None:
            raise ServerStateError(
                f"this session's model server is not running, so whatever answers on port "
                f"{self.port} is not it"
            )
        if self.engine != "llama.cpp":
            return None
        report = props_report(get_json(f"http://127.0.0.1:{self.port}/props"))
        if report is None:
            raise ServerStateError(
                f"the server on port {self.port} does not report the window per slot, the "
                "slots, and the model file it serves (GET /props)"
            )
        expected = {
            "n_ctx_per_slot": self.model.n_ctx,
            "total_slots": self.parallel,
            "model_path": str(self.model.path),
        }
        differing = [
            f"{name} {report[name]!r}, not {value!r}"
            for name, value in expected.items()
            if report[name] != value
        ]
        if differing:
            raise ServerStateError(
                f"the server on port {self.port} reports {'; '.join(differing)}, so it does not "
                "serve what this session started"
            )
        return report

    def stop(self) -> None:
        """Stop the server if it is running."""
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=30)
        self._proc = None

    def __enter__(self) -> LocalServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def provenance(self) -> dict[str, object]:
        """Provenance fields for artifacts produced with this server.

        Besides the model, the engine, and the exact command line, it records the
        context window of each slot (``n_ctx_per_slot``: the tokens that one request's
        prompt and reply may take together), the number of slots (``parallel_slots``),
        and the context the server holds in all (``ctx_size``, :attr:`ctx_size`).
        """
        return {
            "model": self.model.name,
            "family": self.model.family,
            "model_file": self.model.path.name,
            "model_sha256": self.model.sha256,
            "model_source": self.model.source,
            "engine": self.engine,
            "parallel_slots": self.parallel,
            "n_ctx_per_slot": self.model.n_ctx,
            "ctx_size": self.ctx_size,
            "server_command": list(self.command()),
            "server_command_sha256": sha256_text(" ".join(self.command())),
        }
