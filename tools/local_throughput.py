"""Measure local model throughput on this machine (planning input for docs/PLAN.md).

Starts the llama-cpp-python server for one pinned model, sends prompts of a few
sizes through the client wrapper (so usage is logged), and records wall time and
token counts. Writes ``artifacts/env/local_throughput_<model>.json`` with
provenance. Prompts carry a nonce so the response cache never serves them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from receipts.client.backends import LocalOpenAIBackend
from receipts.client.models import LOCAL_MODELS
from receipts.client.server import LocalServer
from receipts.client.wrapper import ModelClient, ModelRequest

FILLER = "def add(a, b):\n    return a + b\n\ndef test_add():\n    assert add(1, 2) == 3\n\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the measurement and write the artifact."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("model", choices=sorted(LOCAL_MODELS))
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--nonce", required=True, help="unique string, e.g. a timestamp")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    model = LOCAL_MODELS[args.model]
    server = LocalServer(
        model,
        port=args.port,
        threads=args.threads,
        log_path=root / "runs" / "throughput" / f"{model.name}.log",
    )
    client = ModelClient(
        root, {"local": LocalOpenAIBackend(server.base_url)}, root / "runs" / "cache"
    )
    samples = []
    with server:
        for repeats, max_tokens in ((4, 64), (40, 64), (40, 256)):
            content = f"[{args.nonce} {repeats} {max_tokens}]\n" + FILLER * repeats
            content += "\nExplain in a few sentences what this code does."
            resp = client.complete(
                ModelRequest(
                    backend="local",
                    model=model.name,
                    messages=[{"role": "user", "content": content}],
                    params={"temperature": 0, "max_tokens": max_tokens, "seed": 0},
                    purpose="env:local_throughput",
                )
            )
            samples.append(
                {
                    "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens,
                    "wall_s": round(resp.wall_s, 3),
                    "max_tokens": max_tokens,
                }
            )
    sha = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    out = {
        "schema": "receipts.env.local_throughput/1",
        "note": "Machine measurement for planning; concurrent CPU load may lower it.",
        "samples": samples,
        "provenance": {
            "git_sha": sha,
            "command": " ".join([sys.executable, *sys.argv]),
            "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "environment": {
                "platform": platform.platform(),
                "cpus": os.cpu_count(),
                "threads": args.threads,
            },
            **server.provenance(),
        },
    }
    path = root / "artifacts" / "env" / f"local_throughput_{model.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(samples))
    return 0


if __name__ == "__main__":
    sys.exit(main())
