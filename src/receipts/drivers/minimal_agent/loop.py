"""minimal-agent's loop: ask the model for one action, run it, show the result, repeat.

The loop is independent of where tools run: a :class:`ToolRuntime` executes
actions (inside the sandbox) and records ledger events, so the loop never touches
the host. Every model call goes through :class:`receipts.client.ModelClient`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from receipts.client.wrapper import CallKind, ModelClient, ModelRequest
from receipts.drivers.minimal_agent.boundary import FlakinessPolicy, Shown, TruncationPolicy
from receipts.drivers.minimal_agent.protocol import (
    SYSTEM_PROMPT,
    Action,
    ProtocolError,
    format_protocol_error,
    parse_action,
)

Message = Mapping[str, str]


class ToolRuntime(Protocol):
    """Executes actions in the sandbox and records them in the ledger."""

    def record_call(self, action: Action) -> int:
        """Record a ``tool_call`` event and return its sequence number."""
        ...

    def execute(self, action: Action, call_seq: int) -> tuple[str, bool]:
        """Run a non-finish action; return its true output and whether it failed."""
        ...

    def record_result(self, action: Action, call_seq: int, shown: Shown, is_error: bool) -> None:
        """Record the ``tool_result`` event: exactly what the agent was shown."""
        ...


@dataclass(frozen=True)
class AgentConfig:
    """One minimal-agent configuration.

    Attributes:
        backend: Client backend name (``"local"`` or ``"claude"``).
        model: Model identifier passed to the backend.
        max_turns: Model calls allowed before the run stops with ``max_turns``.
        params: Sampling parameters (temperature, max_tokens, seed).
        truncation: M2 tool-boundary policy.
        flakiness_rate: M5 failure rate for covered tools (0 disables).
        flakiness_seed: Seed for M5 draws.
        context_chars: Soft budget for the conversation sent to the model; older
            tool results are elided first when it is exceeded.
        kind: Usage kind for each call (``local_call`` for local models).
        purpose: Usage-ledger label prefix.
    """

    backend: str
    model: str
    max_turns: int = 30
    params: Mapping[str, Any] = field(
        default_factory=lambda: {"temperature": 0.2, "max_tokens": 1024, "seed": 0}
    )
    truncation: TruncationPolicy = field(default_factory=TruncationPolicy)
    flakiness_rate: float = 0.0
    flakiness_seed: int = 0
    context_chars: int = 40_000
    kind: CallKind = "local_call"
    purpose: str = "minimal-agent"


@dataclass(frozen=True)
class AgentResult:
    """How a run ended, and its native transcript."""

    report: str
    turns: int
    stop_reason: str
    messages: Sequence[Message]
    protocol_errors: int


ELIDED = "[earlier tool output omitted to fit the context window]"


def compact(messages: Sequence[Message], budget_chars: int, keep_recent: int = 6) -> list[Message]:
    """Elide old tool results, oldest first, until the conversation fits the budget.

    The system prompt, the task message (index 1 and any prior-work messages before
    the first assistant turn), every assistant message, and the last
    ``keep_recent`` messages are never elided.
    """
    out: list[Message] = [dict(m) for m in messages]
    first_assistant = next((i for i, m in enumerate(out) if m["role"] == "assistant"), len(out))
    protected = set(range(first_assistant)) | set(range(max(0, len(out) - keep_recent), len(out)))
    total = sum(len(m["content"]) for m in out)
    for index, message in enumerate(out):
        if total <= budget_chars:
            break
        if index in protected or message["role"] != "user" or message["content"] == ELIDED:
            continue
        total -= len(message["content"]) - len(ELIDED)
        out[index] = {"role": "user", "content": ELIDED}
    return out


def observation(action: Action, text: str) -> str:
    """Format a tool result as the next user message."""
    return f"Result of {action.tool}:\n{text}"


def run_agent(
    task_prompt: str,
    client: ModelClient,
    config: AgentConfig,
    runtime: ToolRuntime,
    prior_messages: Sequence[Message] = (),
) -> AgentResult:
    """Run minimal-agent until ``finish`` or ``max_turns``.

    Args:
        task_prompt: The user request (with any M3 pressure text already applied).
        client: The model client wrapper.
        config: The agent configuration.
        runtime: Executes and records actions.
        prior_messages: M4 context load: realistic earlier work placed before the task.
    """
    flaky = FlakinessPolicy(config.flakiness_rate, seed=config.flakiness_seed)
    messages: list[Message] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *prior_messages,
        {"role": "user", "content": task_prompt},
    ]
    errors = 0
    for turn in range(1, config.max_turns + 1):
        response = client.complete(
            ModelRequest(
                backend=config.backend,
                model=config.model,
                messages=compact(messages, config.context_chars),
                params=dict(config.params),
                kind=config.kind,
                purpose=f"{config.purpose} turn {turn}",
            )
        )
        messages.append({"role": "assistant", "content": response.text})
        try:
            action = parse_action(response.text)
        except ProtocolError as exc:
            errors += 1
            messages.append({"role": "user", "content": format_protocol_error(exc)})
            continue
        call_seq = runtime.record_call(action)
        if action.tool == "finish":
            return AgentResult(str(action.args["report"]), turn, "finished", messages, errors)
        failure = flaky.should_fail(action.tool)
        if failure is not None:
            shown = Shown(failure, len(failure), False)
            runtime.record_result(action, call_seq, shown, True)
        else:
            output, is_error = runtime.execute(action, call_seq)
            shown = config.truncation.apply(action.tool, output)
            runtime.record_result(action, call_seq, shown, is_error)
        messages.append({"role": "user", "content": observation(action, shown.text)})
    return AgentResult("", config.max_turns, "max_turns", messages, errors)
