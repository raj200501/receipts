"""``make budget``: show that cash spend is 0 and every cap is respected (gate G14).

Checks, in order: ``budget.toml`` parses; no cap is looser than the brief's
defaults (docs/BUILD_BRIEF.md section 8); ``cash_usd`` is 0 in the config and in
the usage ledger; and no day in ``artifacts/usage/ledger.jsonl`` exceeded a
Claude cap after CAP_SHARE scaling.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from gitutil import repo_root
from receipts import budget


def main(argv: Sequence[str] | None = None) -> int:
    """Print the budget report; exit 1 on any violation."""
    parser = argparse.ArgumentParser(description="Check caps and usage against the brief.")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    problems: list[str] = []
    try:
        caps = budget.load_caps(root / "budget.toml")
        defaults = budget.parse_brief_defaults(
            (root / "docs" / "BUILD_BRIEF.md").read_text(encoding="utf-8")
        )
        records = budget.read_usage(root / "artifacts" / "usage" / "ledger.jsonl")
    except (OSError, budget.BudgetError) as exc:
        print(f"BUDGET: FAIL {exc}")
        return 1
    problems.extend(budget.check_against_defaults(caps, defaults))
    problems.extend(budget.check_usage(records, caps))
    cash = caps.cash_usd + budget.total_cash(records)
    print(f"cash_usd = {cash:g}")
    for key, value in caps.as_dict().items():
        if key != "cash_usd":
            print(f"cap {key} = {value:g} (brief default {defaults.as_dict()[key]:g})")
    kinds = Counter(r.kind for r in records if r.backend == "claude" and not r.cache_hit)
    days = sorted({r.day for r in records})
    print(
        f"usage: {len(records)} logged calls over {len(days)} day(s); Claude calls by kind: "
        + (", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) or "none")
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
