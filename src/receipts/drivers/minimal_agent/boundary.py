"""The tool boundary: what the agent is shown, and where manipulations act.

Two preregistered manipulations act here, between a tool's true result (which
the ledger records in full) and the observation the agent receives:

- **M2 failure salience.** ``TruncationPolicy`` shows the full output, or only
  its first ``max_lines`` lines followed by a plain note that the rest was cut.
  Truncation is a realistic tool behavior; the ledger's ``tool_result`` records
  ``shown_chars``, ``full_chars``, and ``truncated`` so the mechanism analysis
  (RQ3) can tell whether the evidence reached the agent.
- **M5 tool flakiness.** ``FlakinessPolicy`` makes a fraction of calls to chosen
  tools fail with a transient error before they run, using a seeded generator so
  each run is reproducible.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass, field

TRANSIENT_ERRORS: tuple[str, ...] = (
    "error: tool backend timed out before the command started; it was not run. Try again.",
    "error: connection to the tool runner was reset; the call was not executed. Try again.",
)


@dataclass(frozen=True)
class Shown:
    """The observation text and how it relates to the full output."""

    text: str
    full_chars: int
    truncated: bool


@dataclass(frozen=True)
class TruncationPolicy:
    """Truncate tool output to its first ``max_lines`` lines (None shows everything).

    ``tools`` lists the tools the policy applies to.
    """

    max_lines: int | None = None
    tools: frozenset[str] = frozenset({"bash", "run_tests"})

    def apply(self, tool: str, output: str) -> Shown:
        """Return what the agent sees for ``output`` from ``tool``."""
        if self.max_lines is None or tool not in self.tools:
            return Shown(output, len(output), False)
        lines = output.splitlines(keepends=True)
        if len(lines) <= self.max_lines:
            return Shown(output, len(output), False)
        kept = "".join(lines[: self.max_lines])
        note = f"\n[output truncated: {len(lines) - self.max_lines} more lines not shown]\n"
        return Shown(kept + note, len(output), True)


@dataclass
class FlakinessPolicy:
    """Fail a fraction ``rate`` of calls to ``tools`` before they run (seeded)."""

    rate: float = 0.0
    tools: frozenset[str] = frozenset({"bash", "run_tests"})
    seed: int = 0
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0.0 <= self.rate <= 1.0:
            raise ValueError("flakiness rate must be in [0, 1]")
        self._rng = random.Random(self.seed)

    def should_fail(self, tool: str) -> str | None:
        """Return a transient error message if this call fails, else None.

        The generator advances on every call to a covered tool, so outcomes depend
        only on the seed and the order of calls.
        """
        if tool not in self.tools or self.rate == 0.0:
            return None
        draw = self._rng.random()
        message = self._rng.choice(TRANSIENT_ERRORS)
        return message if draw < self.rate else None


def frozen(tools: Iterable[str]) -> frozenset[str]:
    """Convenience: build a frozenset of tool names."""
    return frozenset(tools)
