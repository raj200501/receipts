"""Run the E3 judges (RQ4) over every included E1 run and write ``artifacts/e3/judges.json``.

    python tools/run_judges.py --dry-run [--limit N]  # count calls and tokens; no model
    python tools/run_judges.py                        # every judge over every included run
    python tools/run_judges.py --limit 5 --judges qwen7b-transcript --out runs/e3/part.json

Each judge (:data:`receipts.evaluation.e3.JUDGES`) reads a run's native transcript
(``artifacts/studies/e1/runs/<run_id>/transcript.json``) and the claims extracted from its
final report (``run.json``), never the ledger; its labels are scored against the ledger
verdicts in ``artifacts/e1/runs.jsonl`` per claim type (:mod:`receipts.evaluation.e3`).

Calls go through :class:`receipts.client.wrapper.ModelClient` to a local model server
started with :class:`receipts.client.server.LocalServer`, one judge model at a time, as
``tools/run_study.py`` does (llama.cpp's ``llama-server`` by default, DECISIONS D30).
Responses are cached by content hash under ``runs/cache``, so a banked call is never
re-run, and a judge whose every call is cached starts no server. ``--limit N`` judges
the first N included runs by run id and marks the artifact incomplete. A partial run
(``--limit``, or ``--judges`` naming fewer than every judge) never writes the default
``artifacts/e3/judges.json``, which holds the full run, so it needs ``--out`` with another
path, and no exploratory run replaces a confirmatory artifact; both are refused before
any model call (:func:`output_problem`). The PID goes to ``runs/e3/pid`` and server logs
to ``runs/e3/``. Exit status: 0 done, 1 invalid input, a refused artifact, or a failed
model call (cached responses are kept, so a rerun resumes), 2 unknown or repeated judge
names, or an output this run may not write.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from receipts.client.backends import LocalOpenAIBackend
from receipts.client.models import LOCAL_MODELS
from receipts.client.server import LocalServer
from receipts.client.wrapper import ModelClient, ModelRequest
from receipts.evaluation import e3
from receipts.evaluation.judges import JudgeConfig
from receipts.study import results_e4

ROOT = Path(__file__).resolve().parents[1]
E1_ROWS = "artifacts/e1/runs.jsonl"
E1_RUNS = "artifacts/studies/e1/runs"
SEEDED_EVAL = "artifacts/e0/seeded_eval.json"
OUT = "artifacts/e3/judges.json"
STATE = "runs/e3"


def git_sha() -> str:
    """HEAD of this repository ("unknown" outside a git checkout)."""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def cache_path(cache_dir: Path, request: ModelRequest) -> Path:
    """Where :class:`ModelClient` caches the response to ``request`` (its cache layout)."""
    key = request.cache_key()
    return cache_dir / key[:2] / f"{key}.json"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def output_problem(
    root: Path,
    out: Path,
    *,
    judges: Sequence[str],
    limit: int | None,
    confirmatory: bool = False,
) -> str | None:
    """Why this run may not write ``out`` (None when it may); checked before any call.

    ``<root>/artifacts/e3/judges.json`` holds the full E3 run, so a partial run
    (``--limit``, or not every judge of :data:`receipts.evaluation.e3.JUDGES`) never
    writes it and cannot replace a complete artifact there. No run replaces a
    confirmatory artifact with an exploratory one, at that path or any other
    (:func:`receipts.study.results_e4.holds_confirmatory_artifact`). Either run can
    write to ``--out`` with another path.
    """
    every = [j.judge_id for j in e3.JUDGES]
    reasons = [f"--limit {limit}"] if limit is not None else []
    if set(judges) != set(every):
        reasons.append(f"judges {', '.join(judges)} of {', '.join(every)}")
    if reasons and out.resolve() == (root / OUT).resolve():
        return (
            f"a partial run ({'; '.join(reasons)}) never writes {OUT}, which holds the full "
            "E3 run; pass --out with another path"
        )
    if not confirmatory and results_e4.holds_confirmatory_artifact(out):
        return (
            f"{_rel(out, root)} holds a confirmatory artifact and an exploratory run never "
            "replaces it; rerun with --confirmatory, or pass --out with another path"
        )
    return None


def load_rows(path: Path) -> list[dict[str, Any]]:
    """The rows of ``artifacts/e1/runs.jsonl``; ValueError when the file is missing."""
    if not path.is_file():
        raise ValueError(f"{E1_ROWS} is missing: E3 judges the included E1 runs")
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@contextlib.contextmanager
def serve(
    config: JudgeConfig, args: argparse.Namespace, pending: int
) -> Iterator[tuple[e3.Completion, dict[str, Any]]]:
    """A completion function for one judge, and its server's provenance.

    The judge model's server is started only when ``pending`` calls are not cached;
    otherwise every call is served from the cache by the client.
    """
    model = LOCAL_MODELS[config.model]
    server = LocalServer(
        model,
        port=args.port,
        threads=args.threads,
        log_path=args.root / STATE / f"server-{model.name}.log",
        engine=args.engine,
    )
    backend = LocalOpenAIBackend(server.base_url, timeout_s=args.request_timeout)
    client = ModelClient(args.root, {"local": backend}, args.cache)
    provenance: dict[str, Any] = {
        **server.provenance(),
        "started": pending > 0,
        "pending_calls": pending,
    }
    if pending:
        with server:
            yield client.complete, provenance
    else:
        yield client.complete, provenance


def _print_plan(plan: dict[str, Any], included: int) -> None:
    print(
        f"E3 dry run: {plan['runs']} of {included} included E1 runs "
        f"({plan['runs_without_claims']} without claims make no call); no model is called"
    )
    for judge in plan["judges"]:
        print(
            f"  {judge['judge_id']} ({judge['model']}): {judge['calls']} calls, "
            f"{judge['cached']} cached, {judge['new']} new; about "
            f"{judge['estimated_input_tokens']} input tokens ({plan['estimate']}), at most "
            f"{judge['max_output_tokens']} output tokens; {judge['over_context_estimate']} "
            f"call(s) may exceed the {plan['context_tokens']}-token context"
        )
    print(f"  total: {plan['total_calls']} calls, {plan['total_new']} new")


def main(argv: Sequence[str] | None = None) -> int:
    """Judge the included E1 runs (or count the calls with ``--dry-run``)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root to read")
    parser.add_argument("--judges", default=",".join(j.judge_id for j in e3.JUDGES))
    parser.add_argument("--limit", type=int, default=None, help="judge the first N runs only")
    parser.add_argument("--dry-run", action="store_true", help="count calls; call no model")
    parser.add_argument("--out", type=Path, default=None, help=f"default: <root>/{OUT}")
    parser.add_argument("--cache", type=Path, default=None, help="default: <root>/runs/cache")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--engine", choices=("llama.cpp", "llama-cpp-python"), default="llama.cpp")
    parser.add_argument("--request-timeout", type=float, default=3600.0)
    parser.add_argument("--prereg", default=None, help="a preregistration to cite, if any")
    parser.add_argument("--confirmatory", action="store_true")
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    root: Path = args.root
    args.cache = args.cache if args.cache is not None else root / "runs" / "cache"
    known = {j.judge_id: j for j in e3.JUDGES}
    wanted = [name.strip() for name in str(args.judges).split(",") if name.strip()]
    unknown = [name for name in wanted if name not in known]
    if unknown or not wanted:
        print(
            f"E3: unknown judge(s) {', '.join(unknown) or '(none given)'}; "
            f"known: {', '.join(known)}",
            file=sys.stderr,
        )
        return 2
    repeated = sorted({name for name in wanted if wanted.count(name) > 1})
    if repeated:
        print(f"E3: judge(s) named more than once: {', '.join(repeated)}", file=sys.stderr)
        return 2
    configs = [known[name] for name in wanted]
    out: Path = args.out if args.out is not None else root / OUT
    if not args.dry_run:  # a dry run writes nothing
        problem = output_problem(
            root, out, judges=wanted, limit=args.limit, confirmatory=args.confirmatory
        )
        if problem is not None:
            print(f"E3: {problem}", file=sys.stderr)
            return 2
    try:
        rows = load_rows(root / E1_ROWS)
        items = e3.load_items(rows, root / E1_RUNS, root)
    except ValueError as exc:
        print(f"E3: {exc}", file=sys.stderr)
        return 1
    included = len(items)
    if args.limit is not None:
        items = items[: max(0, args.limit)]
    if args.dry_run:
        _print_plan(
            e3.plan_calls(configs, items, is_cached=lambda r: cache_path(args.cache, r).is_file()),
            included,
        )
        return 0
    inputs = {E1_ROWS: results_e4.sha256_file(root / E1_ROWS)}
    for item in items:
        inputs.update(item.sources)
    valid = None
    if (root / SEEDED_EVAL).is_file():
        try:
            valid = results_e4.g5_valid_types(
                json.loads((root / SEEDED_EVAL).read_text(encoding="utf-8"))
            )
        except ValueError as exc:
            print(f"E3: {SEEDED_EVAL}: {exc}", file=sys.stderr)
            return 1
        inputs[SEEDED_EVAL] = results_e4.sha256_file(root / SEEDED_EVAL)
    prereg = results_e4.prereg_status(root, args.prereg) if args.prereg else None
    if args.confirmatory:
        problems = e3.confirmatory_problems(prereg, items, limit=args.limit)
        if problems:
            print(
                "E3: refusing a confirmatory E3 artifact: " + "; ".join(problems), file=sys.stderr
            )
            return 1
    state = root / STATE
    state.mkdir(parents=True, exist_ok=True)
    (state / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    runs: list[e3.JudgeRun] = []
    servers: dict[str, dict[str, Any]] = {}
    try:
        for config in configs:
            requests = [e3.judge_request(config, item) for item in items if item.claims]
            pending = sum(1 for r in requests if not cache_path(args.cache, r).is_file())
            with serve(config, args, pending) as (complete, provenance):
                runs.append(e3.run_judge(config, items, complete))
            servers[config.judge_id] = provenance
    except (RuntimeError, OSError) as exc:  # server start, model file, backend, or refusal
        print(
            f"E3: a judge call failed ({exc}); cached calls are kept for a rerun", file=sys.stderr
        )
        return 1
    if prereg is not None and prereg.sha256:
        inputs[prereg.path] = prereg.sha256
    provenance = {
        "git_sha": git_sha(),
        "command": " ".join(["python", "tools/run_judges.py", *arguments]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "inputs": dict(sorted(inputs.items())),
        "model_servers": servers,
        "cache_dir": _rel(args.cache, root),
    }
    try:
        artifact = e3.judges_artifact(
            runs,
            items,
            included_runs=included,
            limit=args.limit,
            valid_types=valid,
            provenance=provenance,
            prereg=prereg,
            confirmatory=args.confirmatory,
        )
    except ValueError as exc:
        print(f"E3: {exc}", file=sys.stderr)
        return 1
    results_e4.write_strict_json(out, artifact)
    label = " SYNTHETIC" if artifact["synthetic"] else ""
    print(
        f"E3: wrote {out} ({artifact['analysis']}{label}): {len(runs)} judge(s) over "
        f"{artifact['runs']['judged']} of {included} included E1 runs"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
