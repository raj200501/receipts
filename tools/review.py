"""``make review``: validate and print the latest independent review (gate G12).

The review is written by the reviewer, never by the main session: either a
headless ``claude -p --model opus`` run (when the billing guard is clear and the
daily ``claude_review_runs_per_day`` cap allows), or the ``reviewer`` subagent
in ``.claude/agents/reviewer.md``, which writes ``artifacts/review/latest.json``
itself. This tool then validates the file and prints it, ending with the
verdict line ``REVIEW: SHIP`` or ``REVIEW: BLOCK``.

A review counts for the current code only if the reviewed commit differs from
HEAD in nothing but ``artifacts/review/``, ``STATUS.md``, and ``docs/LOG.md``.
A SHIP verdict also needs zero blocking issues, and every non-blocking issue
must be listed in docs/REVIEW_LOG.md. Anything else prints ``REVIEW: BLOCK``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from gitutil import GitError, git, repo_root
from receipts import guard

LATEST = "artifacts/review/latest.json"
REVIEW_LOG = "docs/REVIEW_LOG.md"
ALLOWED_DRIFT = ("artifacts/review/", "STATUS.md", "docs/LOG.md")
SHA = re.compile(r"^[0-9a-f]{40}$")


def drift_allowed(path: str) -> bool:
    """True if ``path`` may differ between the reviewed commit and HEAD."""
    return any(path == a or (a.endswith("/") and path.startswith(a)) for a in ALLOWED_DRIFT)


def validate(root: Path, review: Mapping[str, Any]) -> list[str]:
    """Return every reason ``review`` does not count as a SHIP review of HEAD."""
    problems: list[str] = []
    if review.get("schema") != "receipts.review/1":
        problems.append("schema must be receipts.review/1")
    commit = str(review.get("reviewed_commit", ""))
    if not SHA.match(commit):
        problems.append("reviewed_commit must be a full 40-character SHA")
    else:
        try:
            changed = git(root, "diff", "--name-only", commit, "HEAD").split()
        except GitError:
            changed = None
            problems.append(f"reviewed_commit {commit[:12]} is not in this repository")
        if changed is not None:
            drift = [p for p in changed if not drift_allowed(p)]
            if drift:
                problems.append(
                    f"code changed since the reviewed commit {commit[:12]}: "
                    + ", ".join(drift[:5])
                    + (" ..." if len(drift) > 5 else "")
                )
    verdict = review.get("verdict")
    blocking = review.get("blocking", [])
    nonblocking = review.get("nonblocking", [])
    if verdict not in ("SHIP", "BLOCK"):
        problems.append("verdict must be SHIP or BLOCK")
    if not isinstance(blocking, list) or not isinstance(nonblocking, list):
        problems.append("blocking and nonblocking must be lists")
        return problems
    if verdict == "SHIP" and blocking:
        problems.append("verdict is SHIP but blocking issues are open")
    text = str(review.get("text", "")).rstrip()
    last = text.splitlines()[-1].strip() if text else ""
    if last != f"REVIEW: {verdict}":
        problems.append("the review text must end with its verdict line")
    log_path = root / REVIEW_LOG
    log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    for issue in nonblocking:
        issue_id = str(issue.get("id", "")) if isinstance(issue, dict) else ""
        if not issue_id or not re.search(rf"\b{re.escape(issue_id)}\b", log):
            problems.append(f"non-blocking issue {issue_id or '?'} is not listed in {REVIEW_LOG}")
    return problems


def headless_available(root: Path) -> tuple[bool, str]:
    """Return whether a headless opus review may run now, and why not if it may not."""
    problems = guard.billing_guard_problems(repo=root)
    if problems:
        return False, "billing guard tripped (" + ", ".join(p.name for p in problems) + ")"
    return False, "headless review runner not built yet; use the reviewer subagent"


def main(argv: Sequence[str] | None = None) -> int:
    """Validate and print the latest review. Exit 0 only for a valid SHIP review of HEAD."""
    parser = argparse.ArgumentParser(description="Validate and print the latest review.")
    parser.add_argument("--validate-only", action="store_true", help="never start a model run")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    if not args.validate_only and os.environ.get("RECEIPTS_OFFLINE") != "1":
        ok, why = headless_available(root)
        if not ok:
            print(f"headless review unavailable: {why}")
    path = root / LATEST
    if not path.is_file():
        print(f"no review yet: {LATEST} is missing (run the reviewer subagent)")
        print("REVIEW: BLOCK")
        return 1
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{LATEST} is not valid JSON: {exc}")
        print("REVIEW: BLOCK")
        return 1
    problems = validate(root, review)
    body = str(review.get("text", "")).rstrip().splitlines()
    for line in body[:-1]:
        print(line)
    print(f"reviewed_commit: {review.get('reviewed_commit')}")
    print(f"blocking: {len(review.get('blocking', []))}")
    print(f"nonblocking: {len(review.get('nonblocking', []))}")
    for problem in problems:
        print(f"invalid: {problem}")
    if problems or review.get("verdict") != "SHIP":
        print("REVIEW: BLOCK")
        return 1
    print("REVIEW: SHIP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
