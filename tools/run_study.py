"""Execute a study plan with local models: smoke runs, pilots, and preregistered studies.

    python tools/run_study.py --plan artifacts/studies/<study>/plan.json [--limit N]

Runs are grouped by model; for each model one pinned, hash-verified llama-cpp-python
server is started, and every run goes through :mod:`receipts.study.runner` with the
sandbox chosen by :func:`receipts.sandbox.select.make_sandbox`. Each run's artifacts land
in ``artifacts/studies/<study>/runs/<run_id>/``; a run that already has ``run.json`` is
never re-run, so the command is safe to restart. Infrastructure failures (sandbox or
server errors, not agent behavior) are appended to ``runs/<study>/failures.jsonl`` and
the run is left unbanked for a later attempt. Start long plans in the background with
``nohup``; the PID is written to ``runs/<study>/pid`` (section 8, usage hygiene).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import traceback
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from receipts.sandbox.select import make_sandbox
from receipts.study.tasks import load_run_task

from receipts.client.backends import LocalOpenAIBackend
from receipts.client.models import LOCAL_MODELS
from receipts.client.server import LocalServer
from receipts.client.wrapper import ModelClient
from receipts.sandbox.api import SandboxPolicy
from receipts.study.plan import Plan, load_plan
from receipts.study.runner import execute_run
from receipts.study.spec import RunSpec

ROOT = Path(__file__).resolve().parents[1]
_FAILURES_LOCK = threading.Lock()


def git_sha() -> str:
    """HEAD of this repository (recorded in every run's provenance)."""
    return subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def pending(plan: Plan, artifacts: Path) -> list[str]:
    """Run ids of the plan that are not banked yet, in execution order."""
    return [r.run_id for r in plan.ordered() if not (artifacts / r.run_id / "run.json").is_file()]


def one_run(
    plan: Plan,
    spec: RunSpec,
    client: ModelClient,
    artifacts: Path,
    state: Path,
    sha: str,
    server: LocalServer,
) -> bool:
    """Execute one run; on an infrastructure failure, log it and return False."""
    task = load_run_task(ROOT / "bench" / "tasks" / spec.task_id)
    policy = SandboxPolicy(timeout_s=task.command_timeout_s)
    started = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    print(f"{started} start {spec.run_id} ({spec.config_id})", flush=True)
    try:
        record = execute_run(
            spec,
            task,
            plan.arm(spec.config_id),
            client,
            study=plan.text,
            artifacts_dir=artifacts,
            work_root=ROOT / "runs" / "work" / plan.study,
            sandbox_factory=lambda work: make_sandbox(work, policy),
            git_sha=sha,
            server_provenance=server.provenance(),
        )
    except Exception as exc:  # infrastructure failure: log it, leave the run unbanked
        with _FAILURES_LOCK, (state / "failures.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "run_id": spec.run_id,
                        "at": started,
                        "error": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc()[-4000:],
                    }
                )
                + "\n"
            )
        print(f"FAILED {spec.run_id}: {type(exc).__name__}: {exc}", flush=True)
        return False
    print(
        f"done {spec.run_id}: {record.stop_reason} after {record.turns} turns; "
        f"false_success={record.false_success}",
        flush=True,
    )
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Run every unbanked run of a plan."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None, help="stop after this many runs")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--dry-run", action="store_true", help="list pending runs and exit")
    parser.add_argument("--engine", choices=("llama.cpp", "llama-cpp-python"), default="llama.cpp")
    parser.add_argument("--parallel", type=int, default=1, help="concurrent runs per model")
    args = parser.parse_args(argv)
    plan = load_plan(args.plan)
    study_dir = args.plan.parent
    artifacts = study_dir / "runs"
    state = ROOT / "runs" / plan.study
    state.mkdir(parents=True, exist_ok=True)
    (state / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    todo = pending(plan, artifacts)
    print(f"study {plan.study}: {len(todo)} of {len(plan.runs)} runs pending", flush=True)
    if args.dry_run:
        for run_id in todo:
            print(run_id)
        return 0
    if args.parallel > 1 and args.engine != "llama.cpp":
        parser.error("--parallel above 1 needs --engine llama.cpp (continuous batching)")
    if args.limit is not None:
        todo = todo[: args.limit]
    sha = git_sha()
    specs = {r.run_id: r for r in plan.runs}
    done = 0
    by_model: dict[str, list[str]] = {}
    for run_id in todo:
        by_model.setdefault(plan.arm(specs[run_id].config_id).model, []).append(run_id)
    for model_name, run_ids in by_model.items():
        model = LOCAL_MODELS[model_name]
        server = LocalServer(
            model,
            port=args.port,
            threads=args.threads,
            log_path=state / f"server-{model_name}.log",
            engine=args.engine,
            parallel=args.parallel,
        )
        client = ModelClient(
            ROOT, {"local": LocalOpenAIBackend(server.base_url)}, ROOT / "runs" / "cache"
        )
        with server, ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = [
                pool.submit(one_run, plan, specs[r], client, artifacts, state, sha, server)
                for r in run_ids
            ]
            done += sum(1 for f in futures if f.result())
    print(f"study {plan.study}: {done} run(s) banked this session", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
