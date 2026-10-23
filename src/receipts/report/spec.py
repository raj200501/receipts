"""The project's report: which numbers and figures ``make report`` derives.

Derivations are added here as their artifacts are banked. Each one reads exactly one
artifact; a number that is not derived here cannot appear in README.md or
docs/REPORT.md (``make claimcheck``).
"""

from __future__ import annotations

from receipts.report.build import ReportSpec

SPEC = ReportSpec()
