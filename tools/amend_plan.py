"""Add one run to the smoke plan in place of a run the runner excluded (DECISIONS D71).

    python tools/amend_plan.py --plan artifacts/studies/smoke/plan.json \\
        --replace RUN_ID --n-ctx TOKENS --decision D71 --reason TEXT [--date YYYY-MM-DD]

The new run (:func:`receipts.study.plan.amend_plan`) is the excluded run's planned spec,
with the same study, task, arm, conditions, seed, and mitigation, under the id
``<excluded id>-ctx<window>`` (``-ctx32k`` for 32768 tokens). It needs a model server
with at least ``--n-ctx`` tokens of context per slot on one slot: ``tools/run_study.py``
refuses to run it on any other server, and never attempts the excluded run again. The
plan file gains that run and the amendment record (requirement, decision, reason, date,
and the SHA-256 of the plan file before) and nothing else. The tool prints the SHA-256
of the plan file's bytes before and after. It only reads the runner's failure log, and
it changes no banked run.

It refuses (exit 2, nothing written) when:

- the plan file is not exactly the text ``write_plan`` writes for it, since rewriting
  it would then change other bytes too;
- the plan is not of an amendable study (the smoke study only), ``--replace`` is not one
  of its planned runs, or the run's task already has an amendment (one new run per task);
- the run to replace has a directory under ``runs/`` beside the plan: it is banked, or
  a run of it is in progress;
- the runner has not excluded it: ``runs/<study>/failures.jsonl`` logs fewer than
  ``MAX_ATTEMPTS`` failed attempts of it (``tools/run_study.py`` counts them the same
  way), or the log cannot be counted;
- the run's model is not a pinned local model, or ``--n-ctx`` does not raise its pinned
  window per slot;
- the amendment is malformed (an empty decision or reason, a date that is not ISO 8601).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

import run_study
from receipts.client.models import LOCAL_MODELS
from receipts.study.plan import (
    AMENDABLE_STUDIES,
    ServerRequirement,
    amend_plan,
    load_plan,
    plan_text,
    write_plan,
)

#: The slots the new run's server may have: one (DECISIONS D71).
SLOTS = 1


class RefusalError(Exception):
    """The amendment cannot be made; nothing has been written."""


def sha256(data: bytes) -> str:
    """Hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def amend(
    path: Path, replaces: str, n_ctx: int, *, decision: str, reason: str, date: str
) -> list[str]:
    """Amend the plan at ``path`` in place of the excluded run ``replaces``; return what
    to print (the plan's SHA-256 before and after, and the run added).

    Raises:
        RefusalError: One of the refusals in the module docstring; nothing is written.
    """
    raw = path.read_bytes()
    try:
        plan = load_plan(path)
    except (ValueError, KeyError, TypeError) as exc:
        raise RefusalError(f"{path} is not a readable plan ({exc})") from exc
    if plan_text(plan).encode("utf-8") != raw:
        raise RefusalError(
            f"{path} is not the text write_plan writes for it, so rewriting it would change "
            "more than the amendment"
        )
    if plan.study not in AMENDABLE_STUDIES:
        raise RefusalError(
            f"the {plan.study} plan is not amended after its runs began: only "
            f"{', '.join(AMENDABLE_STUDIES)} (DECISIONS D71)"
        )
    spec = next((run for run in plan.runs if run.run_id == replaces), None)
    if spec is None:
        raise RefusalError(f"{replaces} is not a planned run of the {plan.study} plan")
    if (path.parent / "runs" / replaces).exists():
        raise RefusalError(
            f"{replaces} is banked or in progress ({path.parent / 'runs' / replaces} exists); "
            "only a run the runner excluded is replaced"
        )
    state = run_study.RUNS / plan.study
    try:
        logged = run_study.failure_counts(state).get(replaces, 0)
    except ValueError as exc:
        raise RefusalError(str(exc)) from exc
    if logged < run_study.MAX_ATTEMPTS:
        raise RefusalError(
            f"{state / run_study.FAILURES} logs {logged} failed attempt(s) of {replaces}, "
            f"fewer than the {run_study.MAX_ATTEMPTS} that exclude a run"
        )
    model = plan.arm(spec.config_id).model
    pinned = LOCAL_MODELS.get(model)
    if pinned is None:
        raise RefusalError(f"{model} is not a pinned local model")
    if n_ctx <= pinned.n_ctx:
        raise RefusalError(
            f"--n-ctx {n_ctx} does not raise the pinned window of {pinned.n_ctx} tokens per "
            f"slot of {model}"
        )
    server = ServerRequirement(min_n_ctx_per_slot=n_ctx, max_parallel_slots=SLOTS)
    try:
        amended = amend_plan(
            plan,
            replaces,
            server,
            decision=decision,
            reason=reason,
            date=date,
            plan_sha256_before=sha256(raw),
        )
    except ValueError as exc:
        raise RefusalError(str(exc)) from exc
    write_plan(path, amended)
    added = amended.amendments[-1]
    return [
        f"plan_sha256 before: {sha256(raw)}",
        f"added {added.run_id} in place of {replaces} (excluded after {logged} failed "
        f"attempts); it needs {server.describe()} ({decision})",
        f"plan_sha256 after: {sha256(path.read_bytes())}",
        "  (SHA-256 of the plan.json bytes; the amendment record keeps the one before)",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Amend one plan (exit 2 on a refusal, with nothing written)."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--replace", required=True, metavar="RUN_ID", help="the excluded run")
    parser.add_argument(
        "--n-ctx",
        type=int,
        required=True,
        metavar="TOKENS",
        help="the least context window per server slot the new run needs",
    )
    parser.add_argument("--decision", required=True, help="the DECISIONS.md entry, e.g. D71")
    parser.add_argument("--reason", required=True, help="why the run was excluded, and the fix")
    parser.add_argument(
        "--date",
        default=dt.datetime.now(dt.UTC).date().isoformat(),
        help="the day of the amendment, YYYY-MM-DD (default: today, UTC)",
    )
    args = parser.parse_args(argv)
    if args.n_ctx < 1:
        parser.error(f"--n-ctx must be a positive number of tokens, not {args.n_ctx}")
    try:
        lines = amend(
            args.plan,
            args.replace,
            args.n_ctx,
            decision=args.decision,
            reason=args.reason,
            date=args.date,
        )
    except RefusalError as exc:
        print(f"amend_plan: refused: {exc}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
