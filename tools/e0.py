"""E0 tooling for gate G5: material for blind subagents, checks of their work, and scoring.

    python tools/e0.py label-packets [--runs DIR] --out OUTDIR
    python tools/e0.py check-labels --packets DIR FILE...
    python tools/e0.py counts --method blind-labels --labels DIR [--packets DIR]
                              [--blindness FILE [--agents PATH...]] [--runs DIR]
                              [--out FILE]
    python tools/e0.py counts --method pattern-extractor [--runs DIR] [--allow-dirty]
                              [--out FILE]
    python tools/e0.py packets [--runs DIR] --out OUTDIR
    python tools/e0.py check-raw --packets DIR FILE...
    python tools/e0.py adjudication-packets [--runs DIR] --raw DIR --packets DIR --out OUTDIR
    python tools/e0.py check-adjudication --packets DIR FILE...
    python tools/e0.py blindness --agents PATH... [--clear FILE] [--out FILE]
    python tools/e0.py merge --raw DIR --adjudication DIR [--blindness FILE [--agents PATH...]]
                             [--out FILE]
    python tools/e0.py split --packets DIR [--merged FILE]
    python tools/e0.py evaluate [--split heldout|dev] [--allow-dirty] [--out FILE]
    python tools/e0.py recheck
    python tools/e0.py completeness [--runs DIR...] [--bench DIR] [--out FILE]

The logic lives in ``receipts.evaluation.e0``; docs/E0_PROTOCOL.md ("Files and
commands") describes each step. Nothing here runs a subagent, calls a model, or needs the
network. Blind labelers, writers, and adjudicators run ``check-labels``, ``check-raw``,
and ``check-adjudication``: those commands never import ``receipts.claims`` or
``receipts.verify``. The claim-type counts gate G5 reads come from blind labels
(``counts --method blind-labels``, DECISIONS D34); extractor counts are descriptive output
in a file of their own. ``recheck`` scores the held-out half again, writes nothing, and
logs no attempt; gate G5 runs it in its clone (DECISIONS D66).

Exit status: 0 on success, 1 when a check finds problems (``check-labels``, ``check-raw``,
and ``check-adjudication``; ``label-packets`` when a packet would void its labeler;
``blindness`` when merge or counts would refuse its result; ``recheck`` when the
held-out evaluation is not what its reports score now), 2 when a step refuses. A
refusal or a ``recheck`` difference is one ``e0 <step>: <reason>`` line on stderr.
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


def _agents(args: argparse.Namespace) -> list[Path] | None:
    """The ``--agents`` transcripts that ``counts`` and ``merge`` scan again, if any."""
    return [Path(p) for p in args.agents] if args.agents else None


def cmd_label_packets(args: argparse.Namespace, root: Path, command: str) -> int:
    """One labeler packet per real smoke run.

    Exits 1 (after writing the packets) when a packet's text matches a blindness rule,
    since the scan would void the labeler who reads it.
    """
    runs = Path(args.runs) if args.runs else root / e0.SMOKE_RUNS
    index = e0.write_label_packets(root, runs, Path(args.out), command=command)
    for flag in index["flagged"]:
        print(
            f"{flag['run_id']}: its packet matches the blindness rule {flag['rule']!r} "
            f"({flag['fragment']!r}); the scan voids a labeler who reads it"
        )
    empty = sum(1 for entry in index["packets"] if entry["empty"])
    summary = f"{len(index['packets'])} packets ({empty} with an empty report)"
    _written(Path(args.out) / "index.json", root, summary)
    return 1 if index["flagged"] else 0


def cmd_check_labels(args: argparse.Namespace, root: Path, command: str) -> int:
    """Validate labeler outputs (run by blind labelers)."""
    del root, command
    paths = [Path(p) for p in args.files]
    return _report(e0.check_label_files(paths, Path(args.packets)), len(paths), "check-labels")


def cmd_counts(args: argparse.Namespace, root: Path, command: str) -> int:
    """Claim-type counts of the real smoke-run reports.

    ``blind-labels`` writes the counts gate G5 recomputes (default
    ``artifacts/e0/claim_type_counts.json``, which needs ``--packets`` and
    ``--blindness``; ``--agents`` scans the labelers' transcripts again to check the
    blindness file); ``pattern-extractor`` writes descriptive extractor counts, never to
    that file.
    """
    runs = Path(args.runs) if args.runs else root / e0.SMOKE_RUNS
    gate_file = (root / e0.COUNTS).resolve()
    if args.method == e0.EXTRACTOR_METHOD:
        if args.labels or args.packets or args.blindness or args.agents:
            raise e0.E0Error(
                "--labels, --packets, --blindness, and --agents apply only to --method blind-labels"
            )
        path = _out(args, root, e0.EXTRACTOR_COUNTS)
        if path.resolve() == gate_file:
            raise e0.E0Error(
                f"extractor counts never go to {e0.COUNTS}: it holds the blind-label counts "
                "gate G5 reads (D34)"
            )
        data = e0.extractor_counts_artifact(
            root, runs, command=command, allow_dirty=args.allow_dirty
        )
        e0.write_json(path, data)
        top = ", ".join(data["top5"])
        summary = f"{len(data['source_runs'])} reports; top five: {top}"
        return _written(path, root, summary + "; descriptive only, not the G5 counts")
    if args.allow_dirty:
        raise e0.E0Error("--allow-dirty applies only to --method pattern-extractor")
    if not args.labels:
        raise e0.E0Error("--method blind-labels needs --labels DIR")
    path = _out(args, root, e0.COUNTS)
    if path.resolve() == gate_file and not (args.packets and args.blindness):
        raise e0.E0Error(
            f"{e0.COUNTS} needs --packets and --blindness (D34: labels of the reports the "
            "packets showed, by labelers the blindness scan cleared); use --out FILE for a "
            "trial count"
        )
    data = e0.blind_counts_artifact(
        root,
        runs,
        Path(args.labels),
        packets_dir=Path(args.packets) if args.packets else None,
        blindness_path=Path(args.blindness) if args.blindness else None,
        agents=_agents(args),
        command=command,
    )
    e0.write_json(path, data)
    claims = sum(data["counts"].values())
    summary = (
        f"{len(data['labels'])} runs labeled, {len(data['source_runs'])} with a report, "
        f"{claims} claims; top five: {', '.join(data['top5'])}"
    )
    return _written(path, root, summary)


def cmd_packets(args: argparse.Namespace, root: Path, command: str) -> int:
    """One writer packet per real run.

    Exits 1 (after writing the packets) when a packet's text matches a blindness rule,
    since the scan would void the writer who reads it.
    """
    runs = Path(args.runs) if args.runs else root / e0.SMOKE_RUNS
    index = e0.write_writer_packets(root, runs, Path(args.out), command=command)
    for flag in index["flagged"]:
        print(
            f"{flag['run_id']}: its packet matches the blindness rule {flag['rule']!r} "
            f"({flag['fragment']!r}); the scan voids a writer who reads it"
        )
    _written(Path(args.out) / "index.json", root, f"{len(index['packets'])} packets")
    return 1 if index["flagged"] else 0


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
    """Scan labeler, writer, and adjudicator transcripts for access to the instrument.

    Exits 1 (after writing the artifact) when merge or counts would refuse it: a
    transcript that could not be read in full, or one that voids but declares no id.
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
                "merge and counts refuse until it is scanned in full"
            )
    for name in data["unattributed"]:
        print(
            f"{name}: voids but declares no writer, adjudicator, or labeler id; merge and "
            "counts refuse"
        )
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
    """Keep the claims writer and adjudicator agree on (``--agents``: scan again)."""
    blindness = Path(args.blindness) if args.blindness else None
    data = e0.merge_artifact(
        root,
        Path(args.raw),
        Path(args.adjudication),
        blindness,
        command=command,
        agents=_agents(args),
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


def cmd_recheck(args: argparse.Namespace, root: Path, command: str) -> int:
    """Score the held-out half again and compare it with the committed evaluation.

    The check gate G5 runs in its clone (DECISIONS D66): it calls no model, writes no
    file, and logs no attempt. Exits 1, with the differing fields and the first
    differing item on one stderr line, when ``artifacts/e0/seeded_eval.json`` is not what
    the held-out reports score now, and 2 (through :func:`main`) when it refuses: it
    cannot score them again, or could only with code other than the evaluated commit's.
    """
    del args, command
    try:
        data = e0.recheck(root)
    except e0.RecheckMismatchError as exc:
        print(f"e0 recheck: {exc}", file=sys.stderr)
        return 1
    print(
        f"recheck: {e0.EVAL} (attempt {data.get('attempt')}) is what its {data.get('reports')} "
        "held-out reports score now; nothing written, no attempt logged"
    )
    return 0


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

    p = add("label-packets", cmd_label_packets, "one labeler packet per real smoke run")
    p.add_argument("--runs", help=f"banked runs directory (default {e0.SMOKE_RUNS})")
    p.add_argument("--out", required=True, help="output directory")
    p = add("check-labels", cmd_check_labels, "validate labeler outputs")
    p.add_argument("--packets", required=True, help="the labeler packets directory")
    p.add_argument("files", nargs="+")
    p = add("counts", cmd_counts, "claim-type counts of the real smoke-run reports")
    p.add_argument(
        "--method",
        required=True,
        choices=(e0.COUNTS_METHOD, e0.EXTRACTOR_METHOD),
        help="blind-labels (the counts G5 reads) or pattern-extractor (descriptive only)",
    )
    p.add_argument("--labels", help="directory of labeler outputs (blind-labels)")
    p.add_argument("--packets", help="the labeler packets directory (blind-labels)")
    p.add_argument("--blindness", help="blindness artifact of the labelers (blind-labels)")
    p.add_argument(
        "--agents",
        nargs="+",
        help="the transcripts --blindness scanned, scanned again to check it (blind-labels)",
    )
    p.add_argument("--runs", help=f"banked runs directory (default {e0.SMOKE_RUNS})")
    p.add_argument(
        "--allow-dirty", action="store_true", help="pattern-extractor, tests only; recorded"
    )
    p.add_argument("--out", help=f"output file (default {e0.COUNTS}, or {e0.EXTRACTOR_COUNTS})")
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
    p = add("blindness", cmd_blindness, "scan labeler, writer, and adjudicator transcripts")
    p.add_argument("--agents", nargs="+", required=True, help="transcript files or directories")
    p.add_argument("--clear", help="review entries a person cleared (JSON, see the protocol)")
    p.add_argument("--out", help=f"output file (default {e0.BLINDNESS})")
    p = add("merge", cmd_merge, "keep the claims writer and adjudicator agree on")
    p.add_argument("--raw", required=True, help="directory of writer outputs")
    p.add_argument("--adjudication", required=True, help="directory of adjudicator outputs")
    p.add_argument("--blindness", help="blindness artifact whose voided ids are excluded")
    p.add_argument(
        "--agents", nargs="+", help="the transcripts --blindness scanned, scanned again to check it"
    )
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
    add(
        "recheck",
        cmd_recheck,
        f"score the held-out half again and compare it with {e0.EVAL} (writes nothing)",
    )
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
