"""Tests for the client wrapper, backends, and local server manager (all offline)."""

from __future__ import annotations

import json
import shutil
import stat
import threading
from collections.abc import Iterator, Mapping, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from receipts import guard
from receipts.client import backends, server, wrapper
from receipts.client.models import LOCAL_MODELS
from receipts.client.wrapper import ClientRefusedError, ModelClient, ModelRequest, ModelResponse

ROOT = Path(__file__).resolve().parents[2]


class FakeBackend:
    """Counts calls; returns a fixed response (synthetic)."""

    def __init__(self, name: str = "local", is_claude: bool = False) -> None:
        self.name = name
        self.is_claude = is_claude
        self.calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return ModelResponse("ok", 10, 2, 0.5, "stop", plan_equivalent_usd=0.01)


def make_root(tmp_path: Path, launch: str = "cap_share = 0.2\n") -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    shutil.copy(ROOT / "budget.toml", root / "budget.toml")
    (root / "launch.toml").write_text(launch)
    return root


def client(
    root: Path,
    backend: FakeBackend,
    env: Mapping[str, str] | None = None,
    problems: Sequence[guard.GuardProblem] = (),
) -> ModelClient:
    return ModelClient(
        root,
        {backend.name: backend},
        root / "cache",
        env=env or {},
        clock=lambda: 1_761_184_800.0,
        guard_check=lambda: list(problems),
    )


def request(**over: Any) -> ModelRequest:
    base: dict[str, Any] = {
        "backend": "local",
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "params": {"temperature": 0},
    }
    return ModelRequest(**{**base, **over})


def usage(root: Path) -> list[dict[str, Any]]:
    path = root / "artifacts" / "usage" / "ledger.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_cache_hit_never_recalls(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    fake = FakeBackend()
    c = client(root, fake)
    first = c.complete(request())
    second = c.complete(request())
    assert fake.calls == 1 and not first.cache_hit and second.cache_hit
    rows = usage(root)
    assert [r["cache_hit"] for r in rows] == [False, True]
    assert all(r["cash_usd"] == 0 and r["plan_equivalent_usd"] == 0.0 for r in rows)
    assert rows[0]["day"] == "2025-10-23" and rows[0]["cap_share"] == 0.2
    assert request().cache_key() != request(params={"temperature": 1}).cache_key()


def test_offline_and_unknown_backend(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    with pytest.raises(ClientRefusedError, match="RECEIPTS_OFFLINE"):
        client(root, FakeBackend(), env={"RECEIPTS_OFFLINE": "1"}).complete(request())
    with pytest.raises(ClientRefusedError, match="unknown backend"):
        client(root, FakeBackend()).complete(request(backend="nope"))


def test_claude_refused_by_guard(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    fake = FakeBackend("claude", is_claude=True)
    c = client(root, fake, problems=[guard.GuardProblem("env", "ANTHROPIC_BASE_URL")])
    with pytest.raises(ClientRefusedError, match="billing guard"):
        c.complete(request(backend="claude", kind="single_call"))
    assert fake.calls == 0


def test_claude_caps_scaled_by_cap_share(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    fake = FakeBackend("claude", is_claude=True)
    c = client(root, fake)
    assert c.caps().claude_review_runs_per_day == 1
    c.complete(request(backend="claude", kind="review_run"))
    with pytest.raises(ClientRefusedError, match="claude_review_runs_per_day reached"):
        c.complete(
            request(
                backend="claude", kind="review_run", messages=[{"role": "user", "content": "2"}]
            )
        )
    assert c.complete(request(backend="claude", kind="review_run")).cache_hit
    with pytest.raises(ClientRefusedError, match="capped kind"):
        c.complete(request(backend="claude", kind="local_call", model="other"))
    rows = usage(root)
    assert rows[0]["backend"] == "claude" and rows[0]["plan_equivalent_usd"] == 0.01
    assert c.used_today("review_run") == 1


def test_env_cap_share_is_stricter(tmp_path: Path) -> None:
    root = make_root(tmp_path, launch="")
    assert client(root, FakeBackend(), env={"CAP_SHARE": "0.5"}).cap_share() == 0.5


def test_response_roundtrip() -> None:
    resp = ModelResponse("t", 1, 2, 0.1, "stop", raw={"a": 1})
    back = ModelResponse.from_dict(resp.to_dict(), cache_hit=True)
    assert back.text == "t" and back.cache_hit and back.raw == {"a": 1}


class _Handler(BaseHTTPRequestHandler):
    reply: ClassVar[dict[str, Any]] = {}
    received: ClassVar[dict[str, Any]] = {}

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        type(self).received = json.loads(self.rfile.read(length))
        body = json.dumps(self.reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        body = b'{"data": []}'
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        del args


@pytest.fixture
def http_server() -> Iterator[HTTPServer]:
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()


def test_local_backend_roundtrip(http_server: HTTPServer) -> None:
    _Handler.reply = {
        "model": "m",
        "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    port = http_server.server_address[1]
    backend = backends.LocalOpenAIBackend(f"http://127.0.0.1:{port}/v1")
    resp = backend.complete(request(params={"temperature": 0, "max_tokens": 5}))
    assert (resp.text, resp.input_tokens, resp.output_tokens) == ("hello", 7, 3)
    assert _Handler.received["max_tokens"] == 5
    _Handler.reply = {"choices": []}
    with pytest.raises(backends.BackendError, match="unexpected"):
        backend.complete(request())
    assert server.server_ready(f"http://127.0.0.1:{port}/v1")


def test_local_backend_pins_each_thread_to_its_own_slot(http_server: HTTPServer) -> None:
    _Handler.reply = {
        "model": "m",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    port = http_server.server_address[1]
    backend = backends.LocalOpenAIBackend(f"http://127.0.0.1:{port}/v1")
    seen: dict[str, list[int]] = {}
    lock = threading.Lock()

    def worker(name: str) -> None:
        for _ in range(2):
            slot = backend.slot()
            with lock:
                backend.complete(request())
                seen.setdefault(name, []).append(int(_Handler.received["id_slot"]))
            assert slot == backend.slot()

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # One stable slot per thread, a different one for every thread: 0, 1, 2 in some order.
    assert all(len(set(slots)) == 1 for slots in seen.values())
    assert sorted(slots[0] for slots in seen.values()) == [0, 1, 2]
    unpinned = backends.LocalOpenAIBackend(f"http://127.0.0.1:{port}/v1", pin_slots=False)
    unpinned.complete(request())
    assert "id_slot" not in _Handler.received


def test_local_backend_rejects_remote_and_dead_server() -> None:
    with pytest.raises(ValueError, match="loopback"):
        backends.LocalOpenAIBackend("https://api.example.com/v1")
    dead = backends.LocalOpenAIBackend("http://127.0.0.1:9/v1", timeout_s=2)
    with pytest.raises(backends.BackendError, match="failed"):
        dead.complete(request())
    assert not server.server_ready("http://127.0.0.1:9/v1", timeout_s=1)


def test_claude_cli_backend_command_and_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def runner(
        argv: Sequence[str], env: Mapping[str, str], stdin: str, timeout: float
    ) -> tuple[int, str, str]:
        seen.update(argv=list(argv), env=dict(env), stdin=stdin)
        out = {
            "result": "yes",
            "usage": {"input_tokens": 4, "output_tokens": 1},
            "total_cost_usd": 0.002,
            "subtype": "success",
        }
        return 0, json.dumps(out), ""

    monkeypatch.setenv("CLAUDECODE", "1")
    backend = backends.ClaudeCLIBackend(runner=runner)
    req = request(
        backend="claude",
        model="haiku",
        messages=[{"role": "system", "content": "Label."}, {"role": "user", "content": "x"}],
    )
    resp = backend.complete(req)
    assert resp.text == "yes" and resp.plan_equivalent_usd == 0.002
    assert "--bare" not in seen["argv"] and "--restricted" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--system-prompt") + 1] == "Label."
    assert "CLAUDECODE" not in seen["env"] and seen["stdin"] == "x"
    assert "--system-prompt" not in backend.command(request(model="haiku"))
    fail = backends.ClaudeCLIBackend(runner=lambda a, e, s, t: (1, "", "boom"))
    with pytest.raises(backends.BackendError, match="exited 1"):
        fail.complete(req)
    junk = backends.ClaudeCLIBackend(runner=lambda a, e, s, t: (0, "not json", ""))
    with pytest.raises(backends.BackendError, match="unexpected"):
        junk.complete(req)


def test_run_process() -> None:
    assert backends.run_process(["cat"], {}, "abc", 5) == (0, "abc", "")


FAKE_SERVER = """#!/usr/bin/env python3
import sys, json
from http.server import BaseHTTPRequestHandler, HTTPServer
port = int(sys.argv[sys.argv.index("--port") + 1])
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"data": []}')
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def free_port() -> int:
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    srv.server_close()
    return port


def test_local_server_lifecycle(tmp_path: Path) -> None:
    """A fake 'python' stands in for llama-cpp-python (synthetic, offline)."""
    fake_python = tmp_path / "python"
    fake_python.write_text(FAKE_SERVER)
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IEXEC)
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"weights")
    model = server.LocalModel("m", "fam", gguf, server.file_sha256(gguf), "test")
    srv = server.LocalServer(
        model, port=free_port(), python=fake_python, log_path=tmp_path / "log.txt"
    )
    with srv:
        assert server.server_ready(srv.base_url)
    assert srv.provenance()["model_sha256"] == model.sha256
    assert "--n_ctx" in server.server_command(model, 1, 2)
    bad = server.LocalServer(
        server.LocalModel("m", "fam", gguf, "0" * 64, "test"), python=fake_python
    )
    with pytest.raises(RuntimeError, match="pinned sha256"):
        bad.start()
    dead_python = tmp_path / "dead"
    dead_python.write_text("#!/bin/sh\nexit 3\n")
    dead_python.chmod(0o755)
    dead = server.LocalServer(
        model, port=free_port(), python=dead_python, log_path=tmp_path / "log2.txt"
    )
    with pytest.raises(RuntimeError, match="exited early"):
        dead.start()
    srv.stop()


def test_local_server_startup_timeout(tmp_path: Path) -> None:
    sleeper = tmp_path / "python"
    sleeper.write_text("#!/bin/sh\nsleep 30\n")
    sleeper.chmod(0o755)
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"w")
    model = server.LocalModel("m", "fam", gguf, server.file_sha256(gguf), "test")
    srv = server.LocalServer(
        model,
        port=free_port(),
        python=sleeper,
        log_path=tmp_path / "log.txt",
        startup_timeout_s=0.5,
    )
    srv._sleep = lambda s: None
    with pytest.raises(RuntimeError, match="did not become ready"):
        srv.start()


def test_pinned_models_registry() -> None:
    assert {m.family for m in LOCAL_MODELS.values()} == {"qwen", "granite"}
    assert all(len(m.sha256) == 64 for m in LOCAL_MODELS.values())


def test_wrapper_module_exports() -> None:
    assert wrapper.ClientRefusedError is ClientRefusedError


def test_llama_cpp_engine_command_and_lifecycle(tmp_path: Path) -> None:
    fake = tmp_path / "llama-server"
    fake.write_text(FAKE_SERVER)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"weights")
    model = server.LocalModel("m", "fam", gguf, server.file_sha256(gguf), "test", n_ctx=4096)
    cmd = server.llama_server_command(model, 1234, 4, 3, fake)
    assert cmd[cmd.index("--ctx-size") + 1] == "12288" and cmd[cmd.index("--parallel") + 1] == "3"
    srv = server.LocalServer(
        model,
        port=free_port(),
        engine="llama.cpp",
        parallel=2,
        llama_server=fake,
        log_path=tmp_path / "log.txt",
    )
    with srv:
        assert server.server_ready(srv.base_url)
    prov = srv.provenance()
    assert prov["engine"] == "llama.cpp" and prov["parallel_slots"] == 2


def test_completion_function_routes_through_client(tmp_path: Path) -> None:
    from receipts.client.adapters import completion_function

    root = make_root(tmp_path)
    fake = FakeBackend()
    c = client(root, fake)
    complete = completion_function(c, backend="local", model="m", purpose="claims:model")
    assert complete("extract") == "ok" and complete("extract") == "ok"
    assert fake.calls == 1 and usage(root)[0]["purpose"] == "claims:model"
