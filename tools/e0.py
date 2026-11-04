"""E0 tooling for gate G5: material for blind writers and adjudicators, and scoring.

    python tools/e0.py counts [--runs DIR] [--allow-dirty] [--out FILE]
    python tools/e0.py packets [--runs DIR] --out OUTDIR
    python tools/e0.py check-raw --packets DIR FILE...
    python tools/e0.py adjudication-packets [--runs DIR] --raw DIR --packets DIR --out OUTDIR
    python tools/e0.py check-adjudication --packets DIR FILE...
    python tools/e0.py blindness --agents PATH... [--clear FILE] [--out FILE]
    python tools/e0.py merge --raw DIR --adjudication DIR [--blindness FILE] [--out FILE]
    python tools/e0.py split --packets DIR [--merged FILE]
    python tools/e0.py evaluate [--split heldout|dev] [--allow-dirty] [--out FILE]
    python tools/e0.py completeness [--runs DIR...] [--bench DIR] [--out FILE]

The logic lives in ``receipts.evaluation.e0``; docs/E0_PROTOCOL.md ("Files and
commands") describes each step. Nothing here runs a writer, calls a model, or needs the
network. Blind writers and adjudicators run ``check-raw`` and ``check-adjudication``:
those commands never import ``receipts.claims`` or ``receipts.verify``.

Exit status: 0 on success, 1 when a check finds problems (``check-raw`` and
``check-adjudication``; ``blindness`` when merge would refuse its result), 2 when a step
refuses.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from receipts.evaluation import e0

ROOT = Path(__file__).resolve().parents[1]

Handler = Callable[[argparse.Namespace, Path, str], int]


def _out(args: argparse.Namespace, root: Path, default: str) -> Path:
    return Path(args.out) if args.out else root / default


def _written(path: Path, root: Path, summary: str) -> int:
    print(f"wrote {e0.display_path(root, path)}: {summary}")
    return 0


def cmd_counts(args: argparse.Namespace, root: Path, command: str) -> int:
    """Claim-type counts on the real smoke-run reports."""
    runs = Path(args.runs) if args.runs else root / e0.SMOKE_RUNS
    data = e0.counts_artifact(root, runs, command=command, allow_dirty=args.allow_dirty)
    path = _out(args, root, e0.COUNTS)
    e0.write_json(path, data)
    top = ", ".join(data["top5"])
    return _written(path, root, f"{len(data['source_runs'])} reports; top five: {top}")


def cmd_packets(args: argparse.Namespace, root: Path, command: str) -> int:
    """One writer packet per real run."""
    runs = Path(args.runs) if args.runs else root / e0.SMOKE_RUNS
    index = e0.write_writer_packets(root, runs, Path(args.out), command=command)
    return _written(Path(args.out) / "index.json", root, f"{len(index['packets'])} packets")


def _report(problems: Sequence[str], files: int, what: str) -> int:
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"{what}: {files} file(s), no problems")
    return 0


def cmd_check_raw(args: argparse.Namespace, root: Path, command: str) -> int:
    """Validate writer outputs (run by blind writers)."""
    del root, command
    paths = [Path(p) for p in args.files]
    return _report(e0.check_raw_files(paths, Path(args.packets)), len(paths), "check-raw")


def cmd_adjudication_packets(args: argparse.Namespace, root: Path, command: str) -> int:
    """One adjudication packet per writer output."""
    runs = Path(args.runs) if args.runs else root / e0.SMOKE_RUNS
    index = e0.write_adjudication_packets(
        root, runs, Path(args.raw), Path(args.packets), Path(args.out), command=command
    )
    return _written(Path(args.out) / "index.json", root, f"{len(index['reports'])} packets")


def cmd_check_adjudication(args: argparse.Namespace, root: Path, command: str) -> int:
    """Validate adjudicator outputs (run by blind adjudicators)."""
    del root, command
    paths = [Path(p) for p in args.files]
    problems = e0.check_adjudication_files(paths, Path(args.packets))
    return _report(problems, len(paths), "check-adjudication")


def cmd_blindness(args: argparse.Namespace, root: Path, command: str) -> int:
    """Scan writer and adjudicator transcripts for access to the instrument.

    Exits 1 (after writing the artifact) when merge would refuse it: a transcript that
    could not be read in full, or one that voids but declares no id.
    """
    clearances = Path(args.clear) if args.clear else None
    agents = [Path(p) for p in args.agents]
    data = e0.blindness_artifact(root, agents, command=command, clearances=clearances)
    path = _out(args, root, e0.BLINDNESS)
    e0.write_json(path, data)
    scans = data["transcripts"]
    for scan in scans:
        if scan["unparsed_lines"]:
            print(
                f"{scan['file']}: {scan['unparsed_lines']} line(s) that are not JSON objects; "
                "merge refuses until it is scanned in full"
            )
    for name in data["unattributed"]:
        print(f"{name}: voids but declares no writer or adjudicator id; merge refuses")
    violating = sum(1 for scan in scans if scan["violations"])
    reviewing = sum(1 for scan in scans if any(r["cleared"] is None for r in scan["reviews"]))
    summary = (
        f"{len(scans)} transcripts, {violating} with violations, {reviewing} with uncleared "
        f"reviews, {len(data['unscannable'])} unscannable; "
        f"voided: {', '.join(data['voided']) or 'none'}"
    )
    _written(path, root, summary)
    return 1 if data["unscannable"] or data["unattributed"] else 0


def cmd_merge(args: argparse.Namespace, root: Path, command: str) -> int:
    """Keep the claims writer and adjudicator agree on."""
    blindness = Path(args.blindness) if args.blindness else None
    data = e0.merge_artifact(
        root, Path(args.raw), Path(args.adjudication), blindness, command=command
    )
    path = _out(args, root, e0.MERGED)
    e0.write_json(path, data)
    kept = sum(data["kept_by_type"].values())
    summary = (
        f"{len(data['reports'])} reports, {kept} gold claims, {data['drops']['total']} dropped"
    )
    return _written(path, root, summary + f", {len(data['excluded_reports'])} reports excluded")


def cmd_split(args: argparse.Namespace, root: Path, command: str) -> int:
    """Write the dev and held-out halves and the held-out manifest."""
    merged = Path(args.merged) if args.merged else root / e0.MERGED
    manifest = e0.write_split(root, merged, Path(args.packets), command=command)
    summary = f"{len(manifest['reports'])} held out, {manifest['dev_reports']} dev"
    return _written(root / e0.MANIFEST, root, summary)


def cmd_evaluate(args: argparse.Namespace, root: Path, command: str) -> int:
    """Score the instrument on a seeded split."""
    data = e0.evaluate(root, args.split, command=command, allow_dirty=args.allow_dirty)
    default = e0.EVAL if args.split == "heldout" else e0.EVAL_DEV
    path = _out(args, root, default)
    e0.write_json(path, data)
    for name in data["top5"]:
        entry = data["per_type"][name]
        print(f"{name}: {_rate(entry, 'precision')} {_rate(entry, 'recall')}")
    verdict = (
        "all top-five types pass" if data["all_top5_pass"] else "not every top-five type passes"
    )
    return _written(path, root, f"{data['split']}, {data['reports']} reports; {verdict}")


def _rate(entry: dict[str, object], name: str) -> str:
    value, interval = entry[name], entry[f"{name}_ci"]
    if not isinstance(value, float) or not isinstance(interval, list):
        return f"{name[0].upper()}=n/a"
    return f"{name[0].upper()}={value:.3f} [{interval[0]:.3f}, {interval[1]:.3f}]"


def cmd_completeness(args: argparse.Namespace, root: Path, command: str) -> int:
    """E0b: transcript commands versus ledger commands."""
    runs = [Path(p) for p in args.runs] if args.runs else [root / e0.SMOKE_RUNS]
    bench = Path(args.bench) if args.bench else root / "bench" / "tasks"
    data = e0.completeness_artifact(root, runs, bench, command=command)
    path = _out(args, root, e0.COMPLETENESS)
    e0.write_json(path, data)
    return _written(path, root, f"{len(data['runs'])} runs, {data['total_missing']} missing")


def build_parser() -> argparse.ArgumentParser:
    """The command-line interface (one subcommand per E0 step)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: Handler, help_text: str) -> argparse.ArgumentParser:
        command = sub.add_parser(name, help=help_text)
        command.set_defaults(handler=handler)
        return command

    p = add("counts", cmd_counts, "claim-type counts on real smoke-run reports")
    p.add_argument("--runs", help=f"banked runs directory (default {e0.SMOKE_RUNS})")
    p.add_argument("--allow-dirty", action="store_true", help="tests only; recorded")
    p.add_argument("--out", help=f"output file (default {e0.COUNTS})")
    p = add("packets", cmd_packets, "one writer packet per real run")
    p.add_argument("--runs", help=f"banked runs directory (default {e0.SMOKE_RUNS})")
    p.add_argument("--out", required=True, help="output directory")
    p = add("check-raw", cmd_check_raw, "validate writer outputs")
    p.add_argument("--packets", required=True, help="the writer packets directory")
    p.add_argument("files", nargs="+")
    p = add("adjudication-packets", cmd_adjudication_packets, "one packet per writer output")
    p.add_argument("--runs", help=f"banked runs directory (default {e0.SMOKE_RUNS})")
    p.add_argument("--raw", required=True, help="directory of writer outputs")
    p.add_argument("--packets", required=True, help="the writer packets directory")
    p.add_argument("--out", required=True, help="output directory")
    p = add("check-adjudication", cmd_check_adjudication, "validate adjudicator outputs")
    p.add_argument("--packets", required=True, help="the adjudication packets directory")
    p.add_argument("files", nargs="+")
    p = add("blindness", cmd_blindness, "scan writer and adjudicator transcripts")
    p.add_argument("--agents", nargs="+", required=True, help="transcript files or directories")
    p.add_argument("--clear", help="review entries a person cleared (JSON, see the protocol)")
    p.add_argument("--out", help=f"output file (default {e0.BLINDNESS})")
    p = add("merge", cmd_merge, "keep the claims writer and adjudicator agree on")
    p.add_argument("--raw", required=True, help="directory of writer outputs")
    p.add_argument("--adjudication", required=True, help="directory of adjudicator outputs")
    p.add_argument("--blindness", help="blindness artifact whose voided ids are excluded")
    p.add_argument("--out", help=f"output file (default {e0.MERGED})")
    p = add("split", cmd_split, "dev and held-out halves and the held-out manifest")
    p.add_argument("--packets", required=True, help="the writer packets directory")
    p.add_argument("--merged", help=f"merged file (default {e0.MERGED})")
    p = add("evaluate", cmd_evaluate, "precision and recall per claim type")
    p.add_argument("--split", choices=("heldout", "dev"), default="heldout")
    p.add_argument(
        "--allow-dirty", action="store_true", help="dev split only (refused for heldout)"
    )
    p.add_argument("--out", help=f"output file (default {e0.EVAL} or {e0.EVAL_DEV})")
    p = add("completeness", cmd_completeness, "E0b ledger completeness")
    p.add_argument("--runs", nargs="+", help=f"banked runs directories (default {e0.SMOKE_RUNS})")
    p.add_argument("--bench", help="benchmark tasks directory (default bench/tasks)")
    p.add_argument("--out", help=f"output file (default {e0.COMPLETENESS})")
    return parser


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    """Run one E0 step; ``root`` is the repository the artifacts belong to."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(args_list)
    command = shlex.join(["python", "tools/e0.py", *args_list])
    handler: Handler = args.handler
    try:
        return handler(args, root, command)
    except e0.E0Error as exc:
        print(f"e0 {args.command}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
