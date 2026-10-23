"""``make report``: figures, tables, and the numbers registry from artifacts. Not built yet.

When built, it reads only banked artifacts under ``artifacts/``, writes figures
(SVG) and tables, and writes ``artifacts/report/numbers.json`` (or ``--out``
with ``--numbers-only``), the registry that claimcheck and freshness use. With
``--reproduce`` it rebuilds everything and checks it matches what is committed.
Until then it exits 1 so that no gate can pass on it.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Report that the report generator is not built yet."""
    print("report: not built yet (docs/PLAN.md milestone M6); failing on purpose")
    return 1


if __name__ == "__main__":
    sys.exit(main())
