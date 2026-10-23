"""Parser for hidden-check output (the contract between receipts-bench and the recorder).

A hidden check command prints, as the last line of stdout, one JSON object::

    {"checks": [{"name": "<str>", "passed": <bool>, "requirement": "R1"}]}

``requirement`` is optional. Everything before that line is free-form log text.
Trailing blank lines are ignored. The parser fails closed: any deviation from
the contract (a non-object, a missing or mistyped field) means "not recognized",
never a guess.
"""

from __future__ import annotations

import json
from typing import Any

from receipts.ledger.events import HiddenCheck, HiddenCheckData, Source


def _check(item: Any) -> HiddenCheck | None:
    if not isinstance(item, dict):
        return None
    name, passed = item.get("name"), item.get("passed")
    if not isinstance(name, str) or not name or not isinstance(passed, bool):
        return None
    check = HiddenCheck(name=name, passed=passed)
    if "requirement" in item:
        requirement = item["requirement"]
        if not isinstance(requirement, str):
            return None
        check["requirement"] = requirement
    return check


def parse_hidden_check_list(stdout: str) -> list[HiddenCheck] | None:
    """The checks from the last non-blank stdout line, or None if it breaks the contract."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("checks"), list):
        return None
    checks: list[HiddenCheck] = []
    for item in payload["checks"]:
        check = _check(item)
        if check is None:
            return None
        checks.append(check)
    return checks


def hidden_check_data(checks: list[HiddenCheck], source: Source = "snapshot") -> HiddenCheckData:
    """The ``hidden_check`` payload for ``checks``, with pass, fail and total counts."""
    passed = sum(1 for check in checks if check["passed"])
    return HiddenCheckData(
        passed=passed,
        failed=len(checks) - passed,
        total=len(checks),
        checks=checks,
        source=source,
    )


def parse_hidden_checks(stdout: str, source: Source = "snapshot") -> HiddenCheckData | None:
    """Parse a hidden check command's stdout into a ``hidden_check`` payload.

    Returns None when the last non-blank line is not a JSON object with a
    ``checks`` list whose items all have a non-empty string ``name``, a boolean
    ``passed``, and, if present, a string ``requirement``.
    """
    checks = parse_hidden_check_list(stdout)
    return None if checks is None else hidden_check_data(checks, source)
