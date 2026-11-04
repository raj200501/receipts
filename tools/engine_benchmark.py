"""Compare local serving engines on this machine (planning input; DECISIONS D30).

Sends the same batch of agent-sized requests (about 1200 prompt tokens, up to 160
generated tokens) to (a) the llama-cpp-python server one at a time and (b) llama.cpp's
``llama-server`` with ``--slots`` parallel slots, all at once. Every request goes through
the client wrapper, so usage is logged. Writes
``artifacts/env/engine_benchmark_<model>.json`` with each request's tokens and wall time
and each batch's total wall time, plus provenance.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from receipts.client.backends import LocalOpenAIBackend
from receipts.client.models import LOCAL_MODELS
from receipts.client.server import LocalServer
from receipts.client.wrapper import ModelClient, ModelRequest

ROOT = Path(__file__).resolve().parents[1]
Engine = Literal["llama-cpp-python", "llama.cpp"]
FILLER = "def add(a, b):\n    return a + b\n\ndef test_add():\n    assert add(1, 2) == 3\n\n"


def batch(client: ModelClient, model: str, tag: str, n: int, concurrent: bool) -> dict[str, Any]:
    """Send ``n`` distinct requests; return per-request rows and the batch wall time."""

    def one(i: int) -> dict[str, Any]:
        content = f"[{tag} {i}]\n" + FILLER * 40 + "\nExplain in a few sentences what this does."
        resp = client.complete(
            ModelRequest(
                backend="local",
                model=model,
                messages=[{"role": "user", "content": content}],
                params={"temperature": 0, "max_tokens": 160, "seed": i},
                purpose=f"env:engine_benchmark {tag}",
            )
        )
        return {
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "wall_s": round(resp.wall_s, 3),
        }

    start = time.monotonic()
    if concurrent:
        with ThreadPoolExecutor(max_workers=n) as pool:
            rows = list(pool.map(one, range(n)))
    else:
        rows = [one(i) for i in range(n)]
    return {
        "concurrent": concurrent,
        "requests": rows,
        "batch_wall_s": round(time.monotonic() - start, 3),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run both engines and write the artifact."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("model", choices=sorted(LOCAL_MODELS))
    parser.add_argument("--slots", type=int, default=3)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--include-llama-cpp-python", action="store_true")
    args = parser.parse_args(argv)
    model = LOCAL_MODELS[args.model]
    threads = os.cpu_count() or 4
    results = []
    engines: tuple[tuple[Engine, int, bool], ...] = (
        ("llama.cpp", args.slots, False),
        ("llama.cpp", args.slots, True),
    )
    if args.include_llama_cpp_python:
        engines = (("llama-cpp-python", 1, False), *engines)
    for engine, parallel, concurrent in engines:
        server = LocalServer(
            model,
            port=8095,
            threads=threads,
            engine=engine,
            parallel=parallel,
            log_path=ROOT / "runs" / "engine-bench" / f"{engine}.log",
        )
        client = ModelClient(
            ROOT, {"local": LocalOpenAIBackend(server.base_url)}, ROOT / "runs" / "cache"
        )
        tag = f"{args.nonce} {engine} {'concurrent' if concurrent else 'sequential'}"
        try:
            with server:
                results.append(
                    {
                        "engine": engine,
                        "parallel_slots": parallel,
                        **batch(client, model.name, tag, args.slots, concurrent),
                        "server": server.provenance(),
                    }
                )
        except Exception as exc:  # a crashing engine is a result, recorded as such
            results.append(
                {
                    "engine": engine,
                    "parallel_slots": parallel,
                    "concurrent": concurrent,
                    "failed": f"{type(exc).__name__}: {exc}",
                }
            )
    sha = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    out = {
        "schema": "receipts.env.engine_benchmark/1",
        "note": "Planning measurement; other processes may share the CPU.",
        "results": results,
        "provenance": {
            "git_sha": sha,
            "command": " ".join([sys.executable, *sys.argv]),
            "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "environment": {"platform": platform.platform(), "cpus": threads},
        },
    }
    path = ROOT / "artifacts" / "env" / f"engine_benchmark_{model.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            [
                {k: r.get(k) for k in ("engine", "concurrent", "batch_wall_s", "failed")}
                for r in results
            ]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
