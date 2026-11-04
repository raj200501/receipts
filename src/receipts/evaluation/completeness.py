"""E0b ledger completeness: every command an agent ran appears in its ledger.

The two sides are independent records of the same run:

- the agent's native transcript (what it asked for and was told), and
- the ledger's ``command`` events with source ``agent`` (what the sandbox executed).

For minimal-agent, every ``bash`` and ``run_tests`` action in the transcript after the
task request is a command the agent ran, unless the tool boundary failed it on purpose
before it ran (M5 flaky tools: the observation is one of the transient error messages)
or it answered the final-report request at the turn limit (never run: the reply is
``NOT_RUN_AT_CAP``).
Messages before the task request are the system prompt and, under M4's long level,
rendered prior work that never ran in this run's sandbox; :func:`task_start` finds where
the agent's own turns begin. For Claude Code, the commands are the Bash tool uses in the
stream-json transcript. Gate G5 requires zero transcript commands missing from the
ledger on the validation runs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from receipts.drivers.minimal_agent.boundary import TRANSIENT_ERRORS
from receipts.drivers.minimal_agent.loop import NOT_RUN_AT_CAP
from receipts.drivers.minimal_agent.protocol import ProtocolError, parse_action
from receipts.ledger.events import Ledger, sha256_text


def task_start(messages: Sequence[Mapping[str, str]], prompt_sha256: str) -> int:
    """Index of the first message after the task request in a minimal-agent transcript.

    The transcript is ``[system, *prior work, task request, ...]``. The task request is
    the user message whose SHA-256 equals ``prompt_sha256`` (``provenance.prompt_sha256``
    in the run's ``run.json``); the last such message is taken, because nothing after
    the request repeats it. Raises ValueError when no user message matches.
    """
    matches = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user"
        and sha256_text(message.get("content", "")) == prompt_sha256
    ]
    if not matches:
        raise ValueError("no user message in the transcript matches the run's prompt_sha256")
    return matches[-1] + 1


def transcript_commands(
    messages: Sequence[Mapping[str, str]], test_cmd: str, *, start: int = 0
) -> list[str]:
    """Commands minimal-agent ran, read from its native transcript from index ``start``."""
    commands: list[str] = []
    for index, message in enumerate(messages):
        if index < start or message.get("role") != "assistant":
            continue
        try:
            action = parse_action(message.get("content", ""))
        except ProtocolError:
            continue
        if action.tool not in ("bash", "run_tests"):
            continue
        reply = messages[index + 1]["content"] if index + 1 < len(messages) else ""
        if NOT_RUN_AT_CAP in reply or any(err in reply for err in TRANSIENT_ERRORS):
            continue
        commands.append(str(action.args["cmd"]) if action.tool == "bash" else test_cmd)
    return commands


def ledger_commands(ledger: Ledger) -> list[str]:
    """Commands the sandbox executed for the agent, from the ledger."""
    return [str(e.data.get("cmd", "")) for e in ledger.of_kind("command", source="agent")]


@dataclass(frozen=True)
class Completeness:
    """One run's comparison."""

    run_id: str
    transcript_commands: tuple[str, ...]
    ledger_commands: tuple[str, ...]

    @property
    def missing(self) -> list[str]:
        """Transcript commands with no matching ledger command (multiset difference)."""
        gap = Counter(self.transcript_commands) - Counter(self.ledger_commands)
        return sorted(gap.elements())

    def to_dict(self) -> dict[str, object]:
        """The row format of ``artifacts/e0/ledger_completeness.json``."""
        return {
            "run_id": self.run_id,
            "transcript_commands": list(self.transcript_commands),
            "ledger_commands": list(self.ledger_commands),
            "missing": self.missing,
        }


def check_run(
    run_id: str,
    messages: Sequence[Mapping[str, str]],
    ledger: Ledger,
    test_cmd: str,
    *,
    start: int = 0,
) -> Completeness:
    """Compare one minimal-agent run's transcript (from index ``start``) with its ledger."""
    return Completeness(
        run_id,
        tuple(transcript_commands(messages, test_cmd, start=start)),
        tuple(ledger_commands(ledger)),
    )
