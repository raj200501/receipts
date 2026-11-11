"""``make budget``: show that cash spend is 0 and every cap is respected (gate G14).

Checks, in order: ``budget.toml`` parses; docs/BUILD_BRIEF.md matches the SHA-256
in docs/BUILD_BRIEF.sha256, and that record still holds the digest it had when it
was first committed (so the caps cannot be raised by editing the brief and its
hash together); no cap is looser than the brief's defaults (section 8);
``cash_usd`` is 0 in the config and in the usage ledger; no day in
``artifacts/usage/ledger.jsonl`` exceeded a Claude cap after CAP_SHARE scaling;
no multi-turn Claude run recorded more turns than its cap; and every local model
is within ``local_model_max_params_b``. A line before the verdict names what the
ledger cannot show: ``disk_floor_gb`` governs downloads, and a Claude run whose
record has no ``num_turns`` has unverified turns.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from gitutil import GitError, first_commit, git, repo_root
from receipts import budget

BRIEF = "docs/BUILD_BRIEF.md"
BRIEF_HASH = "docs/BUILD_BRIEF.sha256"


def brief_problems(root: Path) -> list[str]:
    """Return a violation unless the brief matches its recorded hash as first committed."""
    recorded = budget.recorded_digest((root / BRIEF_HASH).read_text(encoding="utf-8"))
    actual = hashlib.sha256((root / BRIEF).read_bytes()).hexdigest()
    problems: list[str] = []
    if actual != recorded:
        problems.append(
            f"{BRIEF} does not match {BRIEF_HASH} (sha256 {actual[:12]}, recorded {recorded[:12]})"
        )
    try:
        added = first_commit(root, BRIEF_HASH)
        original = git(root, "show", f"{added}:{BRIEF_HASH}") if added else None
    except GitError:
        added, original = None, None
    if original is None:
        problems.append(f"{BRIEF_HASH} is not committed, so the brief has no anchor")
    elif budget.recorded_digest(original) != recorded:
        problems.append(f"{BRIEF_HASH} changed after its first commit ({str(added)[:12]})")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Print the budget report; exit 1 on any violation."""
    parser = argparse.ArgumentParser(description="Check caps and usage against the brief.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    problems: list[str] = []
    try:
        caps = budget.load_caps(root / "budget.toml")
        problems.extend(brief_problems(root))
        defaults = budget.parse_brief_defaults((root / BRIEF).read_text(encoding="utf-8"))
        records = budget.read_usage(root / "artifacts" / "usage" / "ledger.jsonl")
    except (OSError, budget.BudgetError) as exc:
        print(f"BUDGET: FAIL {exc}")
        return 1
    try:
        share = budget.effective_cap_share(os.environ, root / "launch.toml")
    except (OSError, budget.BudgetError) as exc:
        print(f"BUDGET: FAIL {exc}")
        return 1
    problems.extend(budget.check_against_defaults(caps, defaults))
    problems.extend(budget.check_usage(records, caps))
    cash = caps.cash_usd + budget.total_cash(records)
    print(f"cash_usd = {cash:g}")
    print(f"cap_share = {share:g} (stricter of CAP_SHARE and launch.toml)")
    effective = caps.effective(share).as_dict()
    for key, value in caps.as_dict().items():
        if key != "cash_usd":
            print(
                f"cap {key} = {value:g} (brief default {defaults.as_dict()[key]:g}; "
                f"effective {effective[key]:g})"
            )
    kinds = Counter(r.kind for r in records if r.backend == "claude" and not r.cache_hit)
    days = sorted({r.day for r in records})
    print(
        f"usage: {len(records)} logged calls over {len(days)} day(s); Claude calls by kind: "
        + (", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) or "none")
    )
    models = Counter(r.model for r in records if r.backend == "local" and not r.cache_hit)
    sizes = {m: budget.model_params_b(m) for m in models}
    print(
        "local models: "
        + (
            ", ".join(
                f"{m} ({'?' if sizes[m] is None else f'{sizes[m]:g}'}B, {n} calls)"
                for m, n in sorted(models.items())
            )
            or "none"
        )
    )
    unverified = budget.runs_without_turns(records)
    print(
        "not shown by the ledger: disk_floor_gb (it governs downloads; make doctor checks free "
        f"disk); turns of {unverified} Claude run(s) whose record has no num_turns"
    )
    for problem in problems:
        print(f"violation: {problem}")
    if problems:
        print(f"BUDGET: FAIL {len(problems)} violation(s)")
        return 1
    print("BUDGET: OK every cap respected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
