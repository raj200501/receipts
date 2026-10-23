"""The Stop hook: check the final report against the session ledger before the user reads it.

When any claim is contradicted by the ledger, the hook returns
``{"decision": "block", "reason": ...}``. Claude Code then keeps the session going
and shows the reason to Claude, which can correct its report. The reason lists each
contradicted claim with the evidence, in plain words, and asks only for an accurate
report (it never asks the agent to hide or change anything else).

Loops are prevented twice over: when ``stop_hook_active`` is true (Claude is already
continuing because of a stop hook) the hook never blocks again, and Claude Code itself
caps consecutive stop-hook continuations.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from receipts.claims.extract import extract_claims
from receipts.claims.types import Claim
from receipts.hook.inputs import HookInput
from receipts.ledger.events import Ledger
from receipts.verify import Label, Verdict, verify_run

MAX_LISTED = 5


def contradicted(claims: Sequence[Claim], verdicts: Sequence[Verdict]) -> list[tuple[Claim, Verdict]]:
    """Pairs of (claim, verdict) whose verdict is contradicted, in report order."""
    by_id = {v.claim_id: v for v in verdicts}
    return [
        (c, by_id[c.claim_id])
        for c in claims
        if c.claim_id in by_id and by_id[c.claim_id].label == Label.CONTRADICTED
    ]


def format_reason(pairs: Sequence[tuple[Claim, Verdict]]) -> str:
    """The message Claude sees when the hook blocks."""
    lines = [
        "receipts checked your final report against this session's record of commands, "
        "test runs, and file changes. These statements are contradicted by that record:"
    ]
    for claim, verdict in pairs[:MAX_LISTED]:
        lines.append(f'- "{claim.text.strip()}": {verdict.reason}')
    if len(pairs) > MAX_LISTED:
        lines.append(f"- and {len(pairs) - MAX_LISTED} more")
    lines.append(
        "Please write a corrected final report that states accurately what was done and "
        "what still fails or was not done."
    )
    return "\n".join(lines)


def stop_decision(hook: HookInput, ledger_path: Path) -> dict[str, Any] | None:
    """Return the Stop hook's JSON output, or None to let the session end."""
    if hook.stop_hook_active or not hook.last_assistant_message.strip():
        return None
    if not ledger_path.is_file():
        return None
    ledger = Ledger.load(ledger_path)
    report = hook.last_assistant_message
    claims = extract_claims(report)
    if not claims:
        return None
    verification = verify_run(claims, ledger, report=report)
    pairs = contradicted(verification.claims, verification.verdicts)
    if not pairs:
        return None
    return {"decision": "block", "reason": format_reason(pairs)}
