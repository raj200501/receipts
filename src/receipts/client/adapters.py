"""Adapters between the client wrapper and components that take a plain callable."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from receipts.client.wrapper import CallKind, ModelClient, ModelRequest


def completion_function(
    client: ModelClient,
    *,
    backend: str,
    model: str,
    purpose: str,
    params: Mapping[str, Any] | None = None,
    kind: CallKind = "local_call",
) -> Callable[[str], str]:
    """A ``complete(prompt) -> text`` function that sends every prompt through ``client``.

    Used by :class:`receipts.claims.model.ModelExtractor`, so model extraction is cached,
    capped, and logged like every other model call.
    """
    fixed = dict(params or {"temperature": 0, "max_tokens": 2048, "seed": 0})

    def complete(prompt: str) -> str:
        request = ModelRequest(
            backend=backend,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            params=fixed,
            kind=kind,
            purpose=purpose,
        )
        return client.complete(request).text

    return complete
