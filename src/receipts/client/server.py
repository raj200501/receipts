"""Start and stop the local llama-cpp-python server for one pinned GGUF model."""

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
from typing import Literal

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
        n_ctx: Context window to serve with.
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


def server_ready(base_url: str, timeout_s: float = 2.0) -> bool:
    """True when ``GET {base_url}/models`` answers with JSON."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(base_url.rstrip("/") + "/models", timeout=timeout_s) as resp:
            json.loads(resp.read().decode("utf-8"))
            return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError):
        return False


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

    def command(self) -> Sequence[str]:
        """The server command line."""
        if self.engine == "llama.cpp":
            return llama_server_command(
                self.model, self.port, self.threads, self.parallel, self.llama_server
            )
        return server_command(self.model, self.port, self.threads, self.python)

    def start(self) -> None:
        """Verify the model hash, start the server, and wait until it answers."""
        if self.verify_hash and file_sha256(self.model.path) != self.model.sha256:
            raise RuntimeError(f"{self.model.path} does not match its pinned sha256")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("ab")
        self._proc = subprocess.Popen(list(self.command()), stdout=log, stderr=log)
        deadline = time.monotonic() + self.startup_timeout_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"model server exited early; see {self.log_path}")
            if server_ready(self.base_url):
                return
            self._sleep(1.0)
        self.stop()
        raise RuntimeError("model server did not become ready in time")

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
        """Provenance fields for artifacts produced with this server."""
        return {
            "model": self.model.name,
            "family": self.model.family,
            "model_file": self.model.path.name,
            "model_sha256": self.model.sha256,
            "model_source": self.model.source,
            "engine": self.engine,
            "parallel_slots": self.parallel,
            "server_command": list(self.command()),
            "server_command_sha256": sha256_text(" ".join(self.command())),
        }
