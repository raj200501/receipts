"""``make freshness``: re-derive every live number from banked artifacts (rule 1, gate G10).

Runs ``tools/report.py --numbers-only --out <tmp>`` to rebuild the numbers
registry from ``artifacts/`` into a temporary file, then requires that:

1. the rebuilt registry equals the committed ``artifacts/report/numbers.json``
   (same keys, values, sources, and source hashes), so no committed number is
   stale; and
2. every marker in each document has a key in the rebuilt registry and shows
   exactly the rebuilt value; and
3. every derived artifact (``receipts.report.derived``: the smoke summary built from
   the banked run records, and the E1, E2, E3, and E4 study artifacts) equals a fresh
   derivation by its committed script, run again with the arguments its provenance
   records (E3 re-scored from the banked judge replies, with no model call), in
   everything but when, where, and how it was made; the smoke summary also records
   exactly the run records that exist now. So a banked run that the summary leaves
   out, or a value typed by hand into any of them (an E2 class, an E3 count, an E1 or
   E4 test statistic or decision), fails here (DECISIONS D56, D65).

A document byte-identical to docs/BUILD_BRIEF.md is exempt, as in claimcheck.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from claimcheck import BRIEF, REGISTRY, load_registry, markers
from gitutil import repo_root
from receipts.report.derived import check as check_derived


def rebuild_registry(root: Path, out: Path) -> tuple[bool, str]:
    """Run the report generator in numbers-only mode; returns (ok, message)."""
    script = root / "tools" / "report.py"
    if not script.is_file():
        return False, "tools/report.py is missing"
    proc = subprocess.run(
        [sys.executable, str(script), "--numbers-only", "--out", str(out)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or ["no output"]
        return False, f"tools/report.py --numbers-only failed: {tail[0]}"
    return True, "rebuilt"


def compare_registries(
    committed: Mapping[str, Mapping[str, str]], fresh: Mapping[str, Mapping[str, str]]
) -> list[str]:
    """Return a problem for every key whose committed entry differs from the rebuilt one."""
    problems = [
        f"{k}: in committed registry but no longer derived" for k in committed.keys() - fresh.keys()
    ]
    problems += [
        f"{k}: derived but missing from committed registry" for k in fresh.keys() - committed.keys()
    ]
    for key in sorted(committed.keys() & fresh.keys()):
        if dict(committed[key]) != dict(fresh[key]):
            problems.append(
                f"{key}: committed {dict(committed[key])} != rebuilt {dict(fresh[key])}"
            )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Rebuild the registry and compare it with the committed one and the documents."""
    parser = argparse.ArgumentParser(description="Re-derive every live number.")
    parser.add_argument("docs", nargs="+")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    brief = (root / BRIEF).read_text(encoding="utf-8") if (root / BRIEF).is_file() else None
    problems: list[str] = []
    live_docs: list[tuple[str, str]] = []
    for doc in args.docs:
        path = root / doc
        if not path.is_file():
            problems.append(f"{doc}: document is missing")
            continue
        text = path.read_text(encoding="utf-8")
        if text == brief:
            print(f"{doc}: identical to the build brief (exempt)")
            continue
        live_docs.append((doc, text))
    if live_docs:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "numbers.json"
            ok, message = rebuild_registry(root, out)
            if not ok:
                problems.append(message)
            else:
                fresh_raw = json.loads(out.read_text(encoding="utf-8")).get("numbers", {})
                fresh = {
                    str(k): {str(a): str(b) for a, b in v.items()} for k, v in fresh_raw.items()
                }
                problems += [
                    f"{REGISTRY}: {p}" for p in compare_registries(load_registry(root), fresh)
                ]
                for doc, text in live_docs:
                    for key, shown, line in markers(text):
                        value = fresh.get(key, {}).get("value")
                        if value != shown:
                            problems.append(
                                f"{doc}:{line}: {key} shows {shown!r}, rebuilt {value!r}"
                            )
                    print(f"{doc}: {len(markers(text))} live number(s) re-derived")
        derived = check_derived(root)
        problems += derived
        if not derived:
            print("derived artifacts: each equals a fresh derivation from its inputs")
    for problem in problems:
        print(f"problem: {problem}")
    print("FRESHNESS: " + ("PASS" if not problems else f"FAIL {len(problems)}"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
