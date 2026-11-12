"""Artifacts derived from other banked artifacts, and their re-derivation (DECISIONS D56, D65).

A derived artifact is written by a committed script from other banked artifacts, its
inputs. :data:`DERIVED` lists every one a gate or a bound number reads:

- ``artifacts/exploratory/smoke_outcomes.json``: ``tools/smoke_outcomes.py``'s summary
  of the banked smoke run records;
- ``artifacts/e1/results.json`` and ``artifacts/e2/mechanism.json``: ``tools/analyze.py
  e1`` and ``tools/analyze.py e2``, the E1 and E2 analyses of the banked E1 rows and runs
  (gates G7 and G8);
- ``artifacts/e3/judges.json``: ``tools/run_judges.py``, the E3 judges (gate G8),
  re-derived with ``--rescore``, which serves every judge call from the banked replies
  (``artifacts/e3/replies.jsonl``), so no model is called and a reply the file lacks
  fails the re-derivation;
- ``artifacts/e4/results.json``: ``tools/analyze_e4.py``, the E4 analysis (gate G9).

:func:`check` runs each script again into a temporary file and requires the fresh
artifact to equal the committed one in everything except when, where, and how it was
made (``provenance`` keys :data:`VOLATILE`), compared as JSON values (``1`` is not
``true`` and not ``1.0``), so no value can be typed in. The smoke summary has an input
pattern: the inputs its provenance records (path to SHA-256) must also be exactly the
files the pattern matches now, so a run banked, removed, or changed after it was written
makes it stale. A study artifact records the inputs it read itself (``provenance.inputs``),
which are part of the compared content, and is derived again with the arguments its
``provenance.command`` records (:func:`recorded_arguments`), so an exploratory artifact
made with, say, ``--n-boot 10`` is derived again the same way; a recorded command that
names another script, passes ``--root``, or passes a path that leads out of this
repository is refused, so a derivation reads only the repository. Every derivation runs with
``RECEIPTS_OFFLINE=1``, so the model client refuses any call. An item whose artifact is
absent is skipped, except the smoke summary when its pattern matches a file.

``make freshness`` and ``make reproduce`` report what :func:`check` finds for every item,
and gates G7, G8, and G9 run ``python -m receipts.report.derived <path>`` (:func:`main`)
in their fresh clone for the artifacts they read. ``make report`` calls :func:`refresh`
first, which rewrites only the smoke summary, and only when its content would change, so
rebuilding does not churn its timestamp; the study artifacts are written by their own
commands, never by ``make report``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class Derived:
    """A derived artifact and how to derive it again.

    All paths are relative to the repository root. The script must accept ``--out PATH``
    and read its inputs from the repository it sits in.

    Attributes:
        path: The artifact.
        script: The committed script that writes it.
        inputs: The pattern its inputs match, which its recorded ``provenance.inputs``
            must equal exactly; None for an artifact that records the inputs it read
            itself, as part of its compared content.
        args: Fixed leading arguments (the subcommand): passed first, and a recorded
            command must begin with them.
        recorded: Re-use the arguments recorded in the committed artifact's
            ``provenance.command`` (:func:`recorded_arguments`).
        extra: Arguments passed after the recorded ones (E3's ``--rescore``).
        rewritable: ``make report`` may rewrite it (:func:`refresh`).
    """

    path: str
    script: str
    inputs: str | None = None
    args: tuple[str, ...] = ()
    recorded: bool = False
    extra: tuple[str, ...] = ()
    rewritable: bool = False

    @property
    def command(self) -> str:
        """The command that derives the artifact again, as a reader would type it."""
        return " ".join(["python", self.script, *self.args, *self.extra])

    @property
    def remedy(self) -> str:
        """What to do when the committed artifact is not a fresh derivation."""
        if self.rewritable:
            return "run make report"
        recorded = " with the arguments its provenance records" if self.recorded else ""
        return f"derive it again with {self.command}{recorded} and commit it"


#: Every derived artifact that a gate or a number in README.md or docs/REPORT.md reads.
DERIVED: tuple[Derived, ...] = (
    Derived(
        "artifacts/exploratory/smoke_outcomes.json",
        "tools/smoke_outcomes.py",
        "artifacts/studies/smoke/runs/*/run.json",
        rewritable=True,
    ),
    Derived("artifacts/e1/results.json", "tools/analyze.py", args=("e1",), recorded=True),
    Derived("artifacts/e2/mechanism.json", "tools/analyze.py", args=("e2",), recorded=True),
    Derived("artifacts/e3/judges.json", "tools/run_judges.py", recorded=True, extra=("--rescore",)),
    Derived("artifacts/e4/results.json", "tools/analyze_e4.py", recorded=True),
)
#: Provenance keys that record when, where, and how an artifact was made, not what it
#: holds: a derivation on another commit, Python, or machine gives the same content.
VOLATILE: frozenset[str] = frozenset({"git_sha", "command", "created", "environment"})
#: The interpreter word a recorded command may begin with.
_PYTHON = re.compile(r"python(?:3(?:\.\d+)?)?")
#: The environment a derivation adds: the model client refuses every call.
OFFLINE = {"RECEIPTS_OFFLINE": "1"}


class DerivedError(RuntimeError):
    """A derived artifact cannot be derived again: its script is missing or fails, or
    its recorded command is not one a re-derivation runs."""


def comparable(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """``artifact`` without the provenance keys in :data:`VOLATILE`."""
    out = dict(artifact)
    prov = out.get("provenance")
    if isinstance(prov, Mapping):
        out["provenance"] = {k: v for k, v in prov.items() if k not in VOLATILE}
    return out


def same(a: object, b: object) -> bool:
    """Whether ``a`` and ``b`` are the same JSON value: unlike ``==``, ``1``, ``1.0``, and
    ``true`` differ, and a NaN equals itself."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _differing(a: object, b: object, at: str) -> Iterator[str]:
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        for key in sorted(set(a) | set(b), key=str):
            sub = f"{at}.{key}" if at else str(key)
            if key in a and key in b:
                yield from _differing(a[key], b[key], sub)
            else:
                yield sub
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            yield from _differing(x, y, f"{at}.{index}" if at else str(index))
    elif not same(a, b):
        yield at or "the whole artifact"


def differences(a: Mapping[str, Any], b: Mapping[str, Any], limit: int = 5) -> str:
    """The dotted paths (list items by index) at which ``a`` and ``b`` differ as JSON
    values, the first ``limit`` of them, comma-separated."""
    paths = list(_differing(a, b, ""))
    shown = ", ".join(paths[:limit])
    return shown + (f", and {len(paths) - limit} more" if len(paths) > limit else "")


def current_inputs(root: Path, item: Derived) -> dict[str, str]:
    """The files ``item``'s input pattern matches under ``root``, path to SHA-256 (empty
    when it has no pattern)."""
    if item.inputs is None:
        return {}
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.glob(item.inputs))
        if p.is_file()
    }


def _option(token: str, name: str) -> bool:
    """Whether ``token`` names the long option ``name`` as argparse reads it: in full or
    abbreviated to three or more characters, alone or with ``=VALUE``."""
    head = token.split("=", 1)[0]
    return len(head) >= 3 and head.startswith("--") and name.startswith(head)


def recorded_arguments(root: Path, item: Derived, command: object) -> list[str]:
    """The arguments a re-derivation of ``item`` takes from the committed artifact's
    ``provenance.command``: those after the script and ``item.args``, without ``--out``
    and its value.

    The command is read as the tools record it (``"python <script> <arguments>"``, joined
    by single spaces). A re-derivation reads only the repository at ``root``: so the
    command must name ``item.script`` with ``item.args``, and no argument may be
    ``--root``, an absolute path, a path with a ``..`` part, or a path that leads out of
    ``root`` through a symbolic link.

    Raises:
        DerivedError: The command is missing or is not one a re-derivation runs.
    """
    if not isinstance(command, str) or not command.strip():
        raise DerivedError("its provenance records no command to derive it again with")
    if "\x00" in command:
        raise DerivedError("its provenance.command holds a NUL character")
    tokens = command.split(" ")
    fixed = list(item.args)
    if len(tokens) < 2 or not _PYTHON.fullmatch(tokens[0]) or tokens[1] != item.script:
        raise DerivedError(
            f"its provenance.command ({command[:80]!r}) does not run {item.script}, the "
            "script that derives it"
        )
    if tokens[2 : 2 + len(fixed)] != fixed:
        said = " ".join(tokens[1 : 2 + len(fixed)])
        raise DerivedError(
            f"its provenance.command runs {said}, not {' '.join([item.script, *fixed])}"
        )
    rest = tokens[2 + len(fixed) :]
    kept: list[str] = []
    index = 0
    inside = root.resolve()
    while index < len(rest):
        token = rest[index]
        index += 1
        if _option(token, "--out"):
            index += 0 if "=" in token else 1  # the value goes with it
            continue
        if _option(token, "--root"):
            raise DerivedError(
                f"its provenance.command passes {token.split('=', 1)[0]}, and a re-derivation "
                "reads this repository, not another root"
            )
        value = token.split("=", 1)[1] if token.startswith("--") and "=" in token else token
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts:
            raise DerivedError(
                f"its provenance.command passes {value!r}, an absolute path or one with a .. "
                "part, and a re-derivation reads only this repository"
            )
        if not (root / value).resolve().is_relative_to(inside):
            raise DerivedError(
                f"its provenance.command passes {value!r}, which leads out of this repository "
                "through a symbolic link"
            )
        kept.append(token)
    return kept


def arguments(root: Path, item: Derived, committed: Mapping[str, Any] | None) -> list[str]:
    """The arguments a fresh derivation of ``item`` passes its script before ``--out``:
    ``item.args``, then the recorded ones of ``committed`` (when ``item.recorded``), then
    ``item.extra``.

    Raises:
        DerivedError: :func:`recorded_arguments` refuses the recorded command.
    """
    recorded: list[str] = []
    if item.recorded:
        prov = committed.get("provenance") if committed is not None else None
        command = prov.get("command") if isinstance(prov, Mapping) else None
        recorded = recorded_arguments(root, item, command)
    return [*item.args, *recorded, *item.extra]


def derive(root: Path, item: Derived, args: Sequence[str] = ()) -> dict[str, Any]:
    """Run ``item``'s script with ``args`` into a temporary file and return what it wrote.

    The script runs in ``root`` with the caller's environment and ``RECEIPTS_OFFLINE=1``.

    Raises:
        DerivedError: The script is missing, fails, writes invalid JSON, or writes no
            JSON object.
    """
    script = root / item.script
    if not script.is_file():
        raise DerivedError(f"{item.script} is missing")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / Path(item.path).name
        proc = subprocess.run(
            [sys.executable, item.script, *args, "--out", str(out)],
            cwd=root,
            env={**os.environ, **OFFLINE},
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 or not out.is_file():
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or ["no output"]
            raise DerivedError(f"{item.script} failed: {tail[0]}")
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except ValueError as exc:  # also a file that is not UTF-8
            raise DerivedError(f"{item.script} wrote invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise DerivedError(f"{item.script} wrote no JSON object")
    return data


def _read(target: Path) -> dict[str, Any]:
    """The committed artifact at ``target``; ValueError naming what is wrong with it."""
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:  # also a file that is not UTF-8
        raise ValueError(f"not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def _input_problem(item: Derived, recorded: object, inputs: Mapping[str, str]) -> str | None:
    """Why the inputs the smoke summary records are not the files its pattern matches."""
    if recorded == inputs:
        return None
    recorded = recorded if isinstance(recorded, dict) else {}
    added = sorted(inputs.keys() - recorded.keys())
    gone = sorted(recorded.keys() - inputs.keys())
    changed = sorted(k for k in inputs.keys() & recorded.keys() if inputs[k] != recorded[k])
    detail = "; ".join(
        f"{label}: {', '.join(paths)}"
        for label, paths in (("new", added), ("removed", gone), ("changed", changed))
        if paths
    )
    return (
        f"{item.path}: its recorded inputs are not the current {item.inputs} files "
        f"({detail or 'malformed'}); {item.remedy}"
    )


def check(root: Path, items: Sequence[Derived] = DERIVED, *, present: bool = False) -> list[str]:
    """Every way a committed derived artifact differs from a fresh derivation.

    An artifact that is absent is skipped, unless its input pattern matches a file, or
    ``present`` asks for every item to exist (:func:`main` with named paths).
    """
    problems: list[str] = []
    for item in items:
        target = root / item.path
        inputs = current_inputs(root, item)
        if not target.is_file():
            if inputs:
                problems.append(
                    f"{item.path}: missing, though {item.inputs} matches {len(inputs)} "
                    f"file(s); {item.remedy}"
                )
            elif present:
                problems.append(f"{item.path}: missing, so there is nothing to derive again")
            continue
        try:
            committed = _read(target)
        except ValueError as exc:
            problems.append(f"{item.path}: {exc}")
            continue
        prov = committed.get("provenance")
        if not isinstance(prov, dict):
            problems.append(f"{item.path}: its provenance is not a JSON object; {item.remedy}")
            continue
        if item.inputs is not None:
            problem = _input_problem(item, prov.get("inputs"), inputs)
            if problem is not None:
                problems.append(problem)
        try:
            fresh = derive(root, item, arguments(root, item, committed))
        except DerivedError as exc:
            problems.append(f"{item.path}: {exc}")
            continue
        if not same(comparable(fresh), comparable(committed)):
            problems.append(
                f"{item.path}: differs from a fresh derivation by {item.script} "
                f"({differences(comparable(fresh), comparable(committed))}); {item.remedy}"
            )
    return problems


def refresh(root: Path, items: Sequence[Derived] = DERIVED) -> list[str]:
    """Rewrite each rewritable derived artifact whose content a fresh derivation changes.

    Only items marked ``rewritable`` (the smoke summary) are derived; a study artifact is
    written by its own command, never here. A rewritable artifact with no inputs and no
    committed file is skipped. Returns the paths written.

    Raises:
        DerivedError: A script failed while its inputs exist.
    """
    written: list[str] = []
    for item in items:
        if not item.rewritable:
            continue
        target = root / item.path
        if not target.is_file() and not current_inputs(root, item):
            continue
        fresh = derive(root, item)
        if target.is_file():
            try:
                committed: dict[str, Any] | None = _read(target)
            except ValueError:  # also a file that is not UTF-8; written again below
                committed = None
            if committed is not None and same(comparable(committed), comparable(fresh)):
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(item.path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m receipts.report.derived [--root DIR] [PATH ...]``: check the named
    derived artifacts (every one of :data:`DERIVED` when none is named) against fresh
    derivations; a named artifact must exist. Prints each problem, then
    ``DERIVED: PASS`` or ``DERIVED: FAIL <n>``; exit status 0, 1 on a problem, 2 for a
    path that :data:`DERIVED` does not list."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="derived artifacts (default: every one)")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)
    known = {item.path: item for item in DERIVED}
    unknown = [path for path in args.paths if path not in known]
    if unknown:
        print(
            f"derived: {', '.join(unknown)} is not a derived artifact; known: " + ", ".join(known),
            file=sys.stderr,
        )
        return 2
    items = [known[path] for path in args.paths] or list(DERIVED)
    problems = check(args.root, items, present=bool(args.paths))
    for problem in problems:
        print(f"problem: {problem}")
    failed = {problem.split(": ", 1)[0] for problem in problems}
    for item in items:
        if item.path not in failed and (args.root / item.path).is_file():
            print(f"{item.path}: re-derived by {item.command}; equals the committed artifact")
    print("DERIVED: " + ("PASS" if not problems else f"FAIL {len(problems)}"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
