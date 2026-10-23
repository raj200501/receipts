"""``make citecheck``: offline validation of banked citation checks (rule 11, gate G13).

``artifacts/citecheck.json`` is written by the ``citation-checker`` subagent after
it opened each reference. This tool never touches the network. It requires:

1. every entry has a key, title, authors, year, url, final_url, page_title,
   retrieval date, a 64-hex content hash, and status ``verified`` or ``dropped``;
2. every external URL in each document matches the ``url`` or ``final_url`` of a
   ``verified`` entry (links to this repository are not references); and
3. no document cites a ``dropped`` reference.

A document byte-identical to docs/BUILD_BRIEF.md is exempt; its reading list
is verified before it is cited anywhere else.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from gitutil import repo_root

CITECHECK = "artifacts/citecheck.json"
BRIEF = "docs/BUILD_BRIEF.md"
SELF_URL = re.compile(r"^https?://(?:www\.)?github\.com/raj200501/receipts(?:[/#?].*)?$")
URL = re.compile(r"https?://[^\s)>\]\"'`]+")
REQUIRED = ("key", "title", "authors", "year", "url", "final_url", "page_title", "retrieved")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize(url: str) -> str:
    """Normalize a URL for matching: drop trailing punctuation, slash, and fragment."""
    url = url.rstrip(".,;:")
    url = url.split("#", 1)[0]
    return url.rstrip("/")


def validate_entry(entry: Mapping[str, Any]) -> list[str]:
    """Return problems with one citecheck entry."""
    key = str(entry.get("key", "?"))
    problems = [f"{key}: missing {field}" for field in REQUIRED if not entry.get(field)]
    if entry.get("status") not in ("verified", "dropped"):
        problems.append(f"{key}: status must be verified or dropped")
    if entry.get("status") == "verified" and not HEX64.match(str(entry.get("content_sha256", ""))):
        problems.append(f"{key}: content_sha256 must be 64 lowercase hex characters")
    if entry.get("retrieved") and not DATE.match(str(entry["retrieved"])):
        problems.append(f"{key}: retrieved must be YYYY-MM-DD")
    if not isinstance(entry.get("authors", []), list):
        problems.append(f"{key}: authors must be a list")
    return problems


def cited_urls(text: str) -> list[str]:
    """Return external URLs cited in ``text`` (excluding this repository)."""
    return [normalize(u) for u in URL.findall(text) if not SELF_URL.match(normalize(u))]


def check(root: Path, docs: Sequence[str]) -> tuple[list[str], int]:
    """Run every check; returns problems and the number of verified references."""
    problems: list[str] = []
    path = root / CITECHECK
    if not path.is_file():
        return [f"{CITECHECK} is missing (run the citation-checker subagent)"], 0
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("references", []) if isinstance(data, dict) else []
    verified: set[str] = set()
    dropped: set[str] = set()
    for entry in entries:
        problems.extend(validate_entry(entry))
        urls = {normalize(str(entry.get("url", ""))), normalize(str(entry.get("final_url", "")))}
        (verified if entry.get("status") == "verified" else dropped).update(urls)
    brief = (root / BRIEF).read_text(encoding="utf-8") if (root / BRIEF).is_file() else None
    for doc in docs:
        doc_path = root / doc
        if not doc_path.is_file():
            problems.append(f"{doc}: document is missing")
            continue
        text = doc_path.read_text(encoding="utf-8")
        if text == brief:
            continue
        for url in cited_urls(text):
            if url in dropped:
                problems.append(f"{doc}: cites dropped reference {url}")
            elif url not in verified:
                problems.append(f"{doc}: {url} has no verified citecheck entry")
    n_verified = sum(1 for e in entries if e.get("status") == "verified")
    return problems, n_verified


def main(argv: Sequence[str] | None = None) -> int:
    """Validate citecheck.json and the documents' references."""
    parser = argparse.ArgumentParser(description="Validate banked citation checks offline.")
    parser.add_argument("docs", nargs="*", default=["README.md", "docs/REPORT.md"])
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    try:
        problems, n_verified = check(root, args.docs)
    except (OSError, json.JSONDecodeError) as exc:
        problems, n_verified = [f"{CITECHECK}: {exc}"], 0
    for problem in problems:
        print(f"problem: {problem}")
    print(f"verified references: {n_verified}")
    print("CITECHECK: " + ("PASS" if not problems else f"FAIL {len(problems)}"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
