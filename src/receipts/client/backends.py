"""Model backends behind :class:`receipts.client.wrapper.ModelClient`.

- :class:`LocalOpenAIBackend`: an OpenAI-compatible chat endpoint on localhost
  (the llama-cpp-python server, llama.cpp ``llama-server``, or Ollama). $0.
- :class:`ClaudeCLIBackend`: one short headless ``claude -p`` call through the
  Max plan. Only reachable through the wrapper, which applies the billing guard
  and the caps first. Never uses ``--bare`` (it authenticates only with an API
  key), always ``--restricted --strict-mcp-config`` with no tools.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from receipts.client.wrapper import ModelRequest, ModelResponse

#: Parent-session markers removed from a Claude child's environment (section 8, "Nesting").
PARENT_SESSION_VARS: tuple[str, ...] = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


class BackendError(RuntimeError):
    """Raised when a backend call fails."""


@dataclass
class LocalOpenAIBackend:
    """Chat completions against a local OpenAI-compatible server.

    Args:
        base_url: For example ``http://127.0.0.1:8081/v1``. Must be a loopback address.
        timeout_s: Per-request timeout.
    """

    base_url: str
    timeout_s: float = 900.0
    name: str = "local"
    is_claude: bool = False

    def __post_init__(self) -> None:
        host = self.base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("the local backend only talks to a loopback server")

    def complete(self, request: ModelRequest) -> ModelResponse:
        """POST one chat completion and parse text, token counts, and finish reason."""
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [dict(m) for m in request.messages],
            **dict(request.params),
        }
        data = json.dumps(body).encode("utf-8")
        http = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        start = time.monotonic()
        try:
            with opener.open(http, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BackendError(f"local backend call failed: {exc}") from exc
        wall = time.monotonic() - start
        try:
            choice = payload["choices"][0]
            text = str(choice["message"].get("content") or "")
            usage = payload.get("usage", {})
            return ModelResponse(
                text=text,
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                wall_s=wall,
                finish_reason=str(choice.get("finish_reason") or ""),
                raw={"model": payload.get("model"), "usage": usage},
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise BackendError(f"unexpected local backend response: {exc}") from exc


Runner = Callable[[Sequence[str], Mapping[str, str], str, float], tuple[int, str, str]]


def run_process(
    argv: Sequence[str], env: Mapping[str, str], stdin: str, timeout: float
) -> tuple[int, str, str]:
    """Run ``argv`` with ``stdin`` and return ``(returncode, stdout, stderr)``."""
    proc = subprocess.run(
        list(argv),
        input=stdin,
        capture_output=True,
        text=True,
        env=dict(env),
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def child_env(env: Mapping[str, str]) -> dict[str, str]:
    """The environment for a Claude child: the parent's, minus parent-session markers."""
    return {k: v for k, v in env.items() if k not in PARENT_SESSION_VARS}


@dataclass
class ClaudeCLIBackend:
    """One single-turn ``claude -p`` call with no tools (labeling, judging, extraction).

    The system prompt is the request's first message when its role is ``system``;
    the remaining messages are joined as the user prompt on stdin.
    """

    executable: str = "claude"
    timeout_s: float = 600.0
    runner: Runner = run_process
    name: str = "claude"
    is_claude: bool = True

    def command(self, request: ModelRequest) -> list[str]:
        """Return the exact command line recorded in provenance."""
        system = next((m["content"] for m in request.messages if m["role"] == "system"), "")
        argv = [
            self.executable,
            "-p",
            "--model",
            request.model,
            "--output-format",
            "json",
            "--restricted",
            "--strict-mcp-config",
            "--tools",
            "",
        ]
        if system:
            argv += ["--system-prompt", system]
        return argv

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Run the call and parse the JSON result (``total_cost_usd`` is a plan estimate)."""
        prompt = "\n\n".join(m["content"] for m in request.messages if m["role"] != "system")
        start = time.monotonic()
        code, out, err = self.runner(
            self.command(request), child_env(os.environ), prompt, self.timeout_s
        )
        wall = time.monotonic() - start
        if code != 0:
            raise BackendError(f"claude -p exited {code}: {err.strip()[:200]}")
        try:
            result = json.loads(out)
            usage = result.get("usage", {})
            return ModelResponse(
                text=str(result.get("result", "")),
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                wall_s=wall,
                finish_reason=str(result.get("subtype", "")),
                plan_equivalent_usd=float(result.get("total_cost_usd", 0.0)),
                raw={"session_id": result.get("session_id"), "is_error": result.get("is_error")},
            )
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            raise BackendError(f"unexpected claude -p output: {exc}") from exc
