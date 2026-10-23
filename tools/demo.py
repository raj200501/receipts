"""``make demo``: offline demo from recorded fixtures (gate G4). Not built yet.

When built, it runs receipts over recorded agent runs with no network and no
model calls, prints the claim-by-claim verdicts, and with ``--check`` compares
stdout with the committed golden output. Until then it exits 1 so that no gate
can pass on it.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Report that the demo is not built yet."""
    print("demo: not built yet (docs/PLAN.md milestone M1); failing on purpose")
    return 1


if __name__ == "__main__":
    sys.exit(main())
