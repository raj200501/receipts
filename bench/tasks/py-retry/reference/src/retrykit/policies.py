"""Named retry policies from ``data/policies.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retrykit.errors import PolicyError

POLICIES_PATH = Path(__file__).resolve().parents[2] / "data" / "policies.json"
KNOWN_KEYS = ("max_attempts", "delay", "backoff", "max_delay")


def load_policy(name: str, path: Path = POLICIES_PATH) -> dict[str, Any]:
    """The settings of policy ``name`` (any of :data:`KNOWN_KEYS`).

    Raises :class:`PolicyError` when the file cannot be read or has no such policy.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        policies = data["policies"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PolicyError(f"cannot read retry policies from {path}: {exc}") from None
    if name not in policies:
        known = ", ".join(sorted(policies)) or "none"
        raise PolicyError(f"unknown retry policy {name!r}; known policies: {known}")
    policy = policies[name]
    return {key: policy[key] for key in KNOWN_KEYS if key in policy}
