"""Run the E3 judges (RQ4) as prereg/0003-e3-judges.md says, and write ``artifacts/e3/``.

    python tools/run_judges.py --dry-run [--limit N]  # the sample, calls, tokens; no model
    python tools/run_judges.py                        # both judges over the preregistered sample
    python tools/run_judges.py --confirmatory         # refused unless section 8 holds
    python tools/run_judges.py --limit 5 --judges qwen7b-transcript --out runs/e3/part.json

The sample (section 3): K and the seed come from the preregistration's machine-readable
lines (``--prereg``, default ``prereg/0003-e3-judges.md``: ``sample_runs:`` and
``sample_seed:``); ``--sample-runs`` and ``--sample-seed`` replace them for an
exploratory run. The sample is drawn from ``artifacts/e1/runs.jsonl`` with
:func:`receipts.evaluation.e3.draw_sample`, in ``--dry-run`` too. Without a K, a dry run
counts every run of the sampling frame (so its per-call estimate can size K) and any
other run is refused. ``--limit N`` judges the first N sampled runs by run id.

Each judge (:data:`receipts.evaluation.e3.JUDGES`) reads a sampled run's native
transcript (``artifacts/studies/e1/runs/<run_id>/transcript.json``) and the claims of its
row, never the ledger; its labels are scored against the rows' re-verified verdicts
(:mod:`receipts.evaluation.e3`). The valid types come from the held-out evaluation
``artifacts/e0/seeded_eval.json`` through :func:`receipts.study.rescore.load_valid_types`.

Calls go through :class:`receipts.client.wrapper.ModelClient` to a local model server
started with :class:`receipts.client.server.LocalServer`, one judge model at a time, as
``tools/run_study.py`` does (llama.cpp's ``llama-server`` by default, DECISIONS D30).
Responses are cached by content hash under ``runs/cache``, so a banked call is never
re-run, and a judge whose every call is cached starts no server. The PID goes to
``runs/e3/pid`` and server logs to ``runs/e3/``.

Failures (section 7): a failed call (a backend error) is appended to
``runs/e3/failures.jsonl`` with its attempt number, and the run stops without an
artifact; cached responses are kept, so a rerun resumes and tries the call again. A call
with three logged failures is never made again: its run is excluded for both judges and
reported as a deviation. A client refusal (offline, billing guard) or a server that
cannot start stops the run without counting an attempt.

Outputs: ``artifacts/e3/judges.json`` and the raw replies ``artifacts/e3/replies.jsonl``
(for ``--out X.json``, the replies go to ``X.replies.jsonl``). A partial run
(``--limit``, ``--judges`` naming fewer than both judges, or a sample other than the
preregistered one) never writes the default path and needs ``--out`` with another path;
an exploratory run never replaces a confirmatory artifact; a judge named twice is
refused; all of this before any model call (:func:`output_problem`). Exit status: 0 done;
1 invalid input, a refused confirmatory artifact, or a failed call; 2 a usage problem
(unknown or repeated judges, an output this run may not write, no sample size, a bad K).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import receipts
import receipts.analysis
from receipts.client import models
from receipts.client.backends import LocalOpenAIBackend
from receipts.client.models import LOCAL_MODELS
from receipts.client.server import LocalServer
from receipts.client.wrapper import ModelClient, ModelRequest
from receipts.evaluation import e3, judges, mechanism
from receipts.evaluation.judges import JudgeConfig
from receipts.ledger import events
from receipts.study import rescore, results_e4

ROOT = Path(__file__).resolve().parents[1]
E1_ROWS = e3.ROWS
E1_RUNS = "artifacts/studies/e1/runs"
E1_RESULTS = e3.E1_RESULTS
E2_MECHANISM = "artifacts/e2/mechanism.json"
SEEDED_EVAL = e3.SEEDED_EVAL
LOCK = "prereg/LOCK.json"
OUT = "artifacts/e3/judges.json"
REPLIES = "artifacts/e3/replies.jsonl"
STATE = "runs/e3"
FAILURES = "failures.jsonl"
#: The analysis code (prereg 0003 section 8): this tool, ``receipts.evaluation.e3`` and
#: ``receipts.evaluation.judges``, the helpers they import from
#: ``receipts.study.results_e4`` and ``receipts.analysis`` (the Wilson and bootstrap
#: intervals), the valid types of ``receipts.study.rescore``, and the modules they read
#: the E2 classes, the pinned models, and the hashes from. Its uncommitted changes block
#: a confirmatory artifact, and its changes after the freeze commit are the deviation
#: ``analysis_code_changed``.
ANALYSIS_CODE: tuple[str, ...] = (
    "tools/run_judges.py",
    "src/receipts/evaluation/e3.py",
    "src/receipts/evaluation/judges.py",
    "src/receipts/evaluation/mechanism.py",
    "src/receipts/study/results_e4.py",
    "src/receipts/study/rescore.py",
    "src/receipts/analysis",
    "src/receipts/client/models.py",
    "src/receipts/ledger/events.py",
)


# Git ----------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str | None:
    """``git -C root <args>`` stdout, or None when git fails."""
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    except OSError:
        return None
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None


def is_checkout(root: Path) -> bool:
    """Whether ``root`` is the top-level directory of a git checkout."""
    top = _git(root, "rev-parse", "--show-toplevel")
    return top is not None and Path(top.strip()).resolve() == root.resolve()


def git_sha(root: Path = ROOT) -> str:
    """HEAD of the checkout at ``root`` ("unknown" outside a git checkout)."""
    out = _git(root, "rev-parse", "HEAD")
    return out.strip() if out else "unknown"


def uncommitted(root: Path, paths: Sequence[str]) -> list[str] | None:
    """Files under ``paths`` with uncommitted changes, untracked ones included.

    None when ``root`` is not the top of a git checkout.
    """
    if not is_checkout(root):
        return None
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    if out is None:
        return None
    tokens, found, index = out.split("\0"), set(), 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        found.add(token[3:])
        if token[0] in "RC" and index < len(tokens):
            found.add(tokens[index])
            index += 1
    return sorted(found)


def changed_since(root: Path, commit: str, paths: Sequence[str]) -> list[str] | None:
    """Files under ``paths`` that differ between ``commit`` and HEAD (None: git failed)."""
    out = _git(root, "diff", "--name-only", "-z", commit, "HEAD", "--", *paths)
    return None if out is None else sorted(p for p in out.split("\0") if p)


def lock_commit(root: Path, rel: str) -> results_e4.LockCommit | None:
    """The first commit whose ``prereg/LOCK.json`` lists ``rel``, with the SHA-256 it records.

    None when no commit does, or ``root`` is not a git checkout.
    """
    if not is_checkout(root):
        return None
    out = _git(root, "log", "--format=%H", "--reverse", "--topo-order", "--", LOCK)
    for sha in (out or "").split():
        text = _git(root, "show", f"{sha}:{LOCK}")
        try:
            data = json.loads(text) if text is not None else None
        except json.JSONDecodeError:
            continue
        entries = data.get("entries") if isinstance(data, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("file") == rel:
                return results_e4.LockCommit(sha, str(entry.get("sha256")))
    return None


# The analysis code --------------------------------------------------------------------------


def code_files() -> dict[str, Path]:
    """Every analysis code file this process runs, by its path in the repository."""
    src = Path(receipts.__file__).resolve().parents[1]
    files: dict[str, Path] = {"tools/run_judges.py": Path(__file__).resolve()}
    modules = (e3, judges, mechanism, results_e4, rescore, models, events)
    paths = [Path(str(m.__file__)).resolve() for m in modules]
    paths += sorted(Path(str(receipts.analysis.__file__)).resolve().parent.glob("*.py"))
    for path in paths:
        try:
            files["src/" + path.relative_to(src).as_posix()] = path
        except ValueError:
            files[path.as_posix()] = path
    return files


def analysis_code_state(
    root: Path, freeze: str | None
) -> tuple[list[str], list[dict[str, Any]], dict[str, str], list[str]]:
    """Problems and deviations of the analysis code, its file hashes, and its dirty files.

    Problems (they block a confirmatory artifact, section 8 condition 7): ``root`` is not
    a git checkout; the code that runs differs from the files under ``root`` (so the
    checks below would not describe it); or :data:`ANALYSIS_CODE` has uncommitted
    changes. A change after the freeze commit is the deviation ``analysis_code_changed``,
    reported with the result of the freeze-commit code on the same inputs (section 8).

    Returns:
        ``(problems, deviations, hashes, dirty)``.
    """
    files = code_files()
    hashes = {rel: results_e4.sha256_file(path) for rel, path in files.items()}
    problems: list[str] = []
    differ = sorted(
        rel
        for rel, digest in hashes.items()
        if not (root / rel).is_file() or results_e4.sha256_file(root / rel) != digest
    )
    if differ:
        problems.append(
            "the analysis code that runs differs from the files under --root: "
            + ", ".join(differ[:5])
        )
    dirty = uncommitted(root, ANALYSIS_CODE)
    if dirty is None:
        problems.append(f"{root} is not a git checkout, so the analysis code has no commit")
    elif dirty:
        problems.append(
            "the analysis code has uncommitted changes, so the artifact could not be "
            "reproduced from its git SHA: " + ", ".join(dirty[:5])
        )
    deviations: list[dict[str, Any]] = []
    if freeze is not None and dirty is not None:
        changed = changed_since(root, freeze, ANALYSIS_CODE)
        if changed is None:
            problems.append(f"the analysis code cannot be compared with the freeze commit {freeze}")
        elif changed:
            deviations.append(
                {
                    "kind": "analysis_code_changed",
                    "prereg_section": "8",
                    "detail": f"analysis code changed after the freeze commit {freeze[:12]}: "
                    + ", ".join(changed)
                    + "; the result of the freeze-commit code on the same inputs is the "
                    "preregistered one and is reported beside this one",
                    "files": changed,
                }
            )
    return problems, deviations, hashes, dirty or []


def input_problems(root: Path) -> list[str]:
    """Confirmatory blockers from where the held-out evaluation came (section 8 item 6).

    The valid types must come from the held-out G5 evaluation that gate G5 checks: the
    committed ``artifacts/e0/seeded_eval.json``. Uncommitted changes to it block a
    confirmatory artifact. (Outside a checkout :func:`analysis_code_state` already blocks.)
    """
    dirty = uncommitted(root, [SEEDED_EVAL])
    if dirty:
        return [
            f"the held-out evaluation {SEEDED_EVAL} has uncommitted changes, so it is not the "
            "committed evaluation gate G5 checks"
        ]
    return []


# Inputs and outputs -------------------------------------------------------------------------


def cache_path(cache_dir: Path, request: ModelRequest) -> Path:
    """Where :class:`ModelClient` caches the response to ``request`` (its cache layout)."""
    key = request.cache_key()
    return cache_dir / key[:2] / f"{key}.json"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def replies_path(root: Path, out: Path) -> Path:
    """Where the raw replies of a run writing ``out`` go.

    ``artifacts/e3/replies.jsonl`` next to the default ``artifacts/e3/judges.json``;
    ``X.replies.jsonl`` next to any other ``--out X.json``.
    """
    if out.resolve() == (root / OUT).resolve():
        return root / REPLIES
    return out.with_name(f"{out.stem}.replies.jsonl")


def output_problem(
    root: Path,
    out: Path,
    *,
    judges: Sequence[str],
    limit: int | None,
    preregistered_sample: bool = True,
    confirmatory: bool = False,
) -> str | None:
    """Why this run may not write ``out`` (None when it may); checked before any call.

    ``<root>/artifacts/e3/judges.json`` holds the full E3 run, so a partial run
    (``--limit``, not every judge of :data:`receipts.evaluation.e3.JUDGES`, or a sample
    other than the preregistered one) never writes it and cannot replace a complete
    artifact there. ``--out`` may not be the default replies file. No run replaces a
    confirmatory artifact with an exploratory one, at that path or any other
    (:func:`receipts.study.results_e4.holds_confirmatory_artifact`). Either run can write
    to ``--out`` with another path.
    """
    every = [j.judge_id for j in e3.JUDGES]
    reasons = [f"--limit {limit}"] if limit is not None else []
    if set(judges) != set(every):
        reasons.append(f"judges {', '.join(judges)} of {', '.join(every)}")
    if not preregistered_sample:
        reasons.append("a sample other than the preregistered one")
    if out.resolve() == (root / REPLIES).resolve():
        return f"--out {REPLIES} is the replies file of {OUT}; pass another path"
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
    """The rows of ``artifacts/e1/runs.jsonl`` (strict JSON lines); ValueError when missing."""
    if not path.is_file():
        raise ValueError(f"{E1_ROWS} is missing: E3 samples the included E1 runs")
    return results_e4.load_jsonl_objects(path)


def read_failures(path: Path) -> list[dict[str, Any]]:
    """The entries of the failure log ``runs/e3/failures.jsonl`` (empty when absent)."""
    return results_e4.load_jsonl_objects(path) if path.is_file() else []


def append_failure(path: Path, error: e3.JudgeCallError) -> int:
    """Log one failed call and return its attempt number (one more than those logged)."""
    attempt = e3.failure_counts(read_failures(path)).get(error.cache_key, 0) + 1
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(e3.failure_entry(error, attempt, now), sort_keys=True) + "\n")
    return attempt


def read_json_object(path: Path) -> dict[str, Any]:
    """A JSON object from ``path``; ValueError when it is not one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} is not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def analyzed_digest(root: Path) -> str | None:
    """The ``artifacts/e1/runs.jsonl`` SHA-256 that ``artifacts/e1/results.json`` records.

    None when the results are missing, unreadable, or record none; the confirmatory rules
    then refuse (:func:`receipts.evaluation.e3.confirmatory_problems`).
    """
    path = root / E1_RESULTS
    try:
        return e3.analyzed_rows_sha256(read_json_object(path)) if path.is_file() else None
    except (OSError, ValueError):
        return None


def replies_text(records: Sequence[Mapping[str, Any]]) -> str:
    """The replies file: one strict JSON object per line, keys sorted."""
    return "".join(
        json.dumps(results_e4.strict_json(r), sort_keys=True, allow_nan=False) + "\n"
        for r in records
    )


@contextlib.contextmanager
def serve(
    config: JudgeConfig, args: argparse.Namespace, pending: int
) -> Iterator[tuple[e3.Completion, dict[str, Any]]]:
    """A completion function for one judge, and its server's provenance.

    The judge model's server is started only when ``pending`` calls are not cached;
    otherwise every call is served from the cache by the client. The server verifies the
    model file's pinned SHA-256 before it starts (:meth:`LocalServer.start`).
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


def _print_sample(
    sample: e3.Sample | None, frame: int, lines: tuple[int | None, int | None], prereg: bool
) -> None:
    if sample is None:
        print(
            "E3 dry run: K is not fixed (the preregistration's sample_runs or sample_seed line "
            f"is missing, and none was given), so every one of the {frame} runs of the "
            "sampling frame is counted; no model is called"
        )
        return
    origin = "the preregistered sample" if prereg else "not the preregistered sample"
    print(
        f"E3 dry run: K = {sample.sample_runs} with seed {sample.seed} ({origin}; the "
        f"preregistration says sample_runs {lines[0]}, sample_seed {lines[1]}): "
        f"{len(sample.run_ids)} run(s) sampled from the {frame} of the sampling frame; "
        "no model is called"
    )
    for arm in sample.arms:
        short = f", shortfall {arm.shortfall}" if arm.shortfall else ""
        print(f"  {arm.config_id}: {len(arm.eligible)} eligible, {len(arm.sampled)} sampled{short}")


def _print_plan(plan: dict[str, Any]) -> None:
    if plan["runs_excluded"]:
        print(f"  {plan['runs_excluded']} run(s) excluded under section 7 make no call")
    for judge in plan["judges"]:
        mean = judge["mean_input_tokens"]
        per_call = f", about {mean:.0f} per call" if mean is not None else ""
        print(
            f"  {judge['judge_id']} ({judge['model']}): {judge['calls']} calls, "
            f"{judge['cached']} cached, {judge['new']} new; about "
            f"{judge['estimated_input_tokens']} input tokens{per_call} ({plan['estimate']}), "
            f"at most {judge['max_output_tokens']} output tokens; "
            f"{judge['over_context_estimate']} call(s) may exceed the "
            f"{plan['context_tokens']}-token context"
        )
    print(f"  total: {plan['total_calls']} calls, {plan['total_new']} new")


def main(argv: Sequence[str] | None = None) -> int:
    """Judge the sampled E1 runs (or count the calls with ``--dry-run``)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root to read")
    parser.add_argument("--judges", default=",".join(j.judge_id for j in e3.JUDGES))
    parser.add_argument("--limit", type=int, default=None, help="judge the first N sampled runs")
    parser.add_argument("--dry-run", action="store_true", help="draw the sample; call no model")
    parser.add_argument("--out", type=Path, default=None, help=f"default: <root>/{OUT}")
    parser.add_argument("--cache", type=Path, default=None, help="default: <root>/runs/cache")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--engine", choices=("llama.cpp", "llama-cpp-python"), default="llama.cpp")
    parser.add_argument("--request-timeout", type=float, default=3600.0)
    parser.add_argument(
        "--prereg", default=e3.PREREG_PATH, help="the preregistration to read and cite"
    )
    parser.add_argument("--sample-runs", type=int, default=None, help="K for an exploratory run")
    parser.add_argument("--sample-seed", type=int, default=None, help="seed for an exploratory run")
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
    configs = tuple(j for j in e3.JUDGES if j.judge_id in wanted)  # preregistered order
    prereg_file = root / args.prereg
    text = prereg_file.read_text(encoding="utf-8") if prereg_file.is_file() else ""
    lines = e3.parse_sample_lines(text)
    k = args.sample_runs if args.sample_runs is not None else lines[0]
    seed = args.sample_seed if args.sample_seed is not None else lines[1]
    preregistered = None not in lines and (k, seed) == lines
    out: Path = args.out if args.out is not None else root / OUT
    if not args.dry_run:  # a dry run writes nothing
        if k is None or seed is None:
            print(
                f"E3: no sample size: {args.prereg} has no machine-readable sample_runs or "
                "sample_seed line; pass --sample-runs and --sample-seed (with --out) for an "
                "exploratory run",
                file=sys.stderr,
            )
            return 2
        problem = output_problem(
            root,
            out,
            judges=wanted,
            limit=args.limit,
            preregistered_sample=preregistered,
            confirmatory=args.confirmatory,
        )
        if problem is not None:
            print(f"E3: {problem}", file=sys.stderr)
            return 2
    try:
        rows = load_rows(root / E1_ROWS)
        e3.check_rows(rows)
    except (OSError, ValueError) as exc:
        print(f"E3: {exc}", file=sys.stderr)
        return 1
    sample: e3.Sample | None = None
    if k is not None and seed is not None:
        try:
            sample = e3.draw_sample(rows, k, seed)
        except ValueError as exc:
            print(f"E3: {exc}", file=sys.stderr)
            return 2
        run_ids = list(sample.run_ids)
    else:  # a dry run without K: the whole frame
        run_ids = sorted(str(row["run_id"]) for row in rows if e3.in_frame(row))
    if args.limit is not None:
        run_ids = run_ids[: max(0, args.limit)]
    failure_log = root / STATE / FAILURES
    try:
        items = e3.load_items(rows, root / E1_RUNS, root, run_ids)
        exclusions = e3.unservable_calls(e3.JUDGES, items, read_failures(failure_log))
    except (OSError, ValueError) as exc:
        print(f"E3: {exc}", file=sys.stderr)
        return 1
    skip = set(exclusions)
    frame = sum(1 for row in rows if e3.in_frame(row))
    if args.dry_run:
        _print_sample(sample, frame, lines, preregistered)
        _print_plan(
            e3.plan_calls(
                configs, items, is_cached=lambda r: cache_path(args.cache, r).is_file(), skip=skip
            )
        )
        return 0
    seeded = root / SEEDED_EVAL
    mechanism_file = root / E2_MECHANISM
    try:
        valid = rescore.load_valid_types(seeded) if seeded.is_file() else None
        classes = (
            e3.mechanism_classes(read_json_object(mechanism_file))
            if mechanism_file.is_file()
            else None
        )
    except (OSError, ValueError) as exc:
        print(f"E3: {exc}", file=sys.stderr)
        return 1
    status = results_e4.committed_status(
        results_e4.prereg_status(root, args.prereg), lock_commit(root, args.prereg)
    )
    problems, deviations, hashes, dirty = analysis_code_state(root, status.freeze_commit)
    context = e3.Context(
        rows=tuple(rows),
        sample=sample,
        prereg=status,
        prereg_lines=lines,
        configs=configs,
        limit=args.limit,
        valid_types=valid,
        rows_sha256=results_e4.sha256_file(root / E1_ROWS),
        analyzed_rows_sha256=analyzed_digest(root),
        code_problems=tuple([*problems, *input_problems(root)]),
        deviations=tuple(deviations),
        exclusions=exclusions,
        classes=classes,
    )
    if args.confirmatory:
        refused = e3.confirmatory_problems(context, items)
        if refused:
            print("E3: refusing a confirmatory E3 artifact: " + "; ".join(refused), file=sys.stderr)
            return 1
    state = root / STATE
    state.mkdir(parents=True, exist_ok=True)
    (state / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    runs: list[e3.JudgeRun] = []
    servers: dict[str, dict[str, Any]] = {}
    try:
        for config in configs:
            requests = [
                e3.judge_request(config, item)
                for item in items
                if item.claims and item.run_id not in skip
            ]
            pending = sum(1 for r in requests if not cache_path(args.cache, r).is_file())
            with serve(config, args, pending) as (complete, provenance):
                synthetic = provenance.get("synthetic_judge") is True
                runs.append(e3.run_judge(config, items, complete, synthetic=synthetic, skip=skip))
            servers[config.judge_id] = dict(provenance)
    except e3.JudgeCallError as exc:
        attempt = append_failure(failure_log, exc)
        after = (
            f"; the call has failed {attempt} times, so the next run excludes run {exc.run_id} "
            "for both judges"
            if attempt >= e3.MAX_ATTEMPTS
            else "; a rerun tries it again"
        )
        print(
            f"E3: {exc} (attempt {attempt} of {e3.MAX_ATTEMPTS}, logged in "
            f"{STATE}/{FAILURES}); cached calls are kept{after}",
            file=sys.stderr,
        )
        return 1
    except (RuntimeError, OSError) as exc:  # server start, model file, or a client refusal
        print(
            f"E3: a judge call failed ({exc}); no attempt is counted, and cached calls are kept "
            "for a rerun",
            file=sys.stderr,
        )
        return 1
    inputs = {E1_ROWS: context.rows_sha256 or ""}
    for item in items:
        inputs.update(item.sources)
    for rel in (SEEDED_EVAL, E1_RESULTS, E2_MECHANISM, args.prereg, LOCK, f"{STATE}/{FAILURES}"):
        if (root / rel).is_file():
            inputs[rel] = results_e4.sha256_file(root / rel)
    records = e3.reply_records(runs, excluded=skip)
    text_out = replies_text(records)
    replies_file = replies_path(root, out)
    replies = {
        "path": _rel(replies_file, root),
        "sha256": hashlib.sha256(text_out.encode("utf-8")).hexdigest(),
        "records": len(records),
    }
    provenance = {
        "git_sha": git_sha(root),
        "command": " ".join(["python", "tools/run_judges.py", *arguments]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "inputs": dict(sorted(inputs.items())),
        "cache_dir": _rel(args.cache, root),
        "failure_log": f"{STATE}/{FAILURES}",
        "analysis_code": hashes,
        "uncommitted_analysis_code": dirty,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": version("numpy"),
            "scipy": version("scipy"),
        },
    }
    try:
        artifact = e3.judges_artifact(
            context,
            items,
            runs,
            provenance=provenance,
            servers=servers,
            replies=replies,
            confirmatory=args.confirmatory,
        )
    except ValueError as exc:
        print(f"E3: {exc}", file=sys.stderr)
        return 1
    replies_file.parent.mkdir(parents=True, exist_ok=True)
    replies_file.write_text(text_out, encoding="utf-8")
    results_e4.write_strict_json(out, artifact)
    label = " SYNTHETIC" if artifact["synthetic"] else ""
    counts = artifact["runs"]
    print(
        f"E3: wrote {out} and {replies_file} ({artifact['analysis']}{label}): {len(runs)} "
        f"judge(s) over {counts['judged']} of {counts['sampled']} sampled E1 runs "
        f"({len(counts['excluded'])} excluded)"
    )
    for reason in artifact["confirmatory_problems"]:
        print(f"  not confirmatory: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
