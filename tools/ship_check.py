#!/usr/bin/env python3
"""``make ship-check``: the 14 Definition-of-Done gates (docs/BUILD_BRIEF.md section 6).

Order of work:

1. In the original checkout, check the parts of G14 that concern it: the working
   tree is clean, nothing under ``private/`` is tracked, ``private/`` is ignored,
   and any private hash manifest matches.
2. Clone HEAD into a temporary directory and run every other check there, so
   only committed state counts.

It verifies banked artifacts (presence, provenance, hashes, preregistration
links, thresholds) and recomputes statistics from them. It never runs an
experiment and never calls a model. It writes nothing inside the working tree;
sub-command logs go to the temporary directory, named on stderr.

stdout is exactly ``HEAD <sha> fresh-clone``, one ``G<n> <PASS|FAIL> <evidence>``
line per gate, and then ``SHIP-CHECK: PASS 14/14`` or ``SHIP-CHECK: FAIL <n>/14``.
With ``--fast`` slow steps are skipped (``make ci`` is not re-run and tests marked
``slow`` are deselected) and the last line is
``SHIP-CHECK-FAST (does not count): <n>/14``. Only a full run counts.

The artifact layout each gate reads is documented in docs/PLAN.md under
"Artifact contract". This file is stdlib-only so it runs before ``make setup``.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import tokenize  # noqa: E402
import tomllib  # noqa: E402
from collections import Counter  # noqa: E402
from collections.abc import Callable, Iterable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

CORE_MODULES: tuple[str, ...] = ("ledger", "claims", "verify", "analysis", "hook")
COVERAGE_MIN = 85.0
DEMO_LIMIT_S = 180.0
G5_PRECISION_MIN = 0.95
G5_RECALL_MIN = 0.90
G6_MIN_TASKS = 30
G7_MIN_CONFIGS = 3
G7_MIN_FAMILIES = 2
G7_MIN_RUNS = 60
HOOK_MEDIAN_MAX_S = 5.0
REPORT_WORDS = (4000, 8000)
REQUIRED_FILES = ("LICENSE", "CITATION.cff", "SECURITY.md", "CONTRIBUTING.md")
HYPE = re.compile(r"(?i)\b(revolutionary|groundbreaking|state[- ]of[- ]the[- ]art)\b")
EM_DASH = "\N{EM DASH}"
MECHANISM_CLASSES = frozenset({"saw_and_reported_otherwise", "truncated_before_agent", "never_saw"})
VERDICTS = frozenset({"supported", "contradicted", "unverifiable"})
NON_AGENTS = frozenset({"", "mock", "fixture", "synthetic", "reference"})
README_SECTIONS = (
    "what it is",
    "result",
    "how it works",
    "your own",
    "reproduc",
    "limitation",
    "disclosure",
    "related work",
    "citation",
    "license",
)
REPORT_SECTIONS = (
    "abstract",
    "introduction",
    "related work",
    "method",
    "experiment",
    "result",
    "limitation",
    "ethic",
    "reproducib",
)


class GateError(Exception):
    """Raised inside a gate check with the short evidence for its FAIL line."""


@dataclass
class CmdResult:
    """Outcome of one sub-command."""

    name: str
    returncode: int
    stdout: str
    stderr: str
    seconds: float

    @property
    def ok(self) -> bool:
        """True when the command exited 0."""
        return self.returncode == 0

    @property
    def output(self) -> str:
        """stdout followed by stderr, for logs."""
        return self.stdout + self.stderr

    def last_line(self) -> str:
        """Return the last non-empty stdout line (stderr carries tool warnings)."""
        lines = [line for line in self.stdout.splitlines() if line.strip()]
        return lines[-1].strip() if lines else ""


@dataclass
class Context:
    """Shared state for one ship-check run."""

    orig: Path
    clone: Path
    logs: Path
    fast: bool
    sha: str
    pre: dict[str, str] = field(default_factory=dict)
    results: dict[str, CmdResult] = field(default_factory=dict)

    def env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Environment for sub-commands: the caller's, minus any active virtualenv."""
        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "CONDA_PREFIX")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.update(extra or {})
        return env

    def run(
        self,
        name: str,
        argv: Sequence[str],
        timeout: float,
        extra_env: Mapping[str, str] | None = None,
    ) -> CmdResult:
        """Run ``argv`` in the clone, log it, and cache the result by ``name``."""
        if name in self.results:
            return self.results[name]
        start = time.monotonic()
        try:
            proc = subprocess.run(
                list(argv),
                cwd=self.clone,
                env=self.env(extra_env),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or ""
            text = out.decode(errors="replace") if isinstance(out, bytes) else out
            code, stdout, stderr = 124, text, f"[timeout after {timeout:.0f}s]"
        except FileNotFoundError as exc:
            code, stdout, stderr = 127, "", str(exc)
        result = CmdResult(name, code, stdout, stderr, time.monotonic() - start)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        (self.logs / f"{safe}.log").write_text(
            f"$ {' '.join(argv)}\n[exit {code} in {result.seconds:.1f}s]\n"
            f"--- stdout\n{stdout}--- stderr\n{stderr}",
            encoding="utf-8",
        )
        self.results[name] = result
        return result

    def make(self, target: str, timeout: float, *args: str) -> CmdResult:
        """Run ``make <target>`` in the clone."""
        return self.run(f"make-{target}", ["make", "--no-print-directory", target, *args], timeout)

    def python(self, name: str, script_args: Sequence[str], timeout: float) -> CmdResult:
        """Run a repository script with the clone's environment."""
        return self.run(name, ["uv", "run", "--no-sync", "python", *script_args], timeout)


# ---------------------------------------------------------------- small helpers


def git(root: Path, *args: str) -> str:
    """Run git in ``root`` and return stdout (raises CalledProcessError on failure)."""
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(directory: Path) -> str:
    """Hash a directory: sorted relative paths with each file's SHA-256."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(directory).as_posix()
        digest.update(f"{rel}\0{sha256_file(path)}\n".encode())
    return digest.hexdigest()


def load_json(root: Path, rel: str) -> Any:
    """Load a JSON artifact or fail the gate naming it."""
    path = root / rel
    if not path.is_file():
        raise GateError(f"{rel} missing")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateError(f"{rel} is not valid JSON ({exc.msg})") from exc


def load_jsonl(root: Path, rel: str) -> list[Any]:
    """Load a JSONL artifact or fail the gate naming it."""
    path = root / rel
    if not path.is_file():
        raise GateError(f"{rel} missing")
    rows: list[Any] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise GateError(f"{rel}:{number} is not valid JSON") from exc
    return rows


def require(condition: bool, evidence: str) -> None:
    """Fail the gate with ``evidence`` unless ``condition`` holds."""
    if not condition:
        raise GateError(evidence)


def require_provenance(rel: str, data: Mapping[str, Any]) -> None:
    """Every banked artifact carries provenance with at least a git SHA and a command."""
    prov = data.get("provenance")
    require(isinstance(prov, dict), f"{rel} has no provenance")
    assert isinstance(prov, dict)
    for key in ("git_sha", "command", "created"):
        require(bool(prov.get(key)), f"{rel} provenance lacks {key}")


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (95% by default)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def fmt_ci(successes: int, n: int) -> str:
    """Format ``successes/n`` as an estimate with its Wilson interval."""
    lo, hi = wilson(successes, n)
    est = successes / n if n else float("nan")
    return f"{est:.3f}[{lo:.3f},{hi:.3f}]"


def headings(text: str) -> list[str]:
    """Return the lowercased Markdown headings in ``text``."""
    return [m.group(1).strip().lower() for m in re.finditer(r"^#{1,6}\s+(.+)$", text, re.M)]


def strip_code(text: str) -> str:
    """Remove fenced code blocks."""
    return re.sub(r"^(```|~~~).*?^\1[^\n]*$", "", text, flags=re.S | re.M)


def first_commit(root: Path, rel: str) -> str | None:
    """Return the commit that first added ``rel`` in ``root``."""
    shas = git(root, "log", "--format=%H", "--diff-filter=A", "--follow", "--", rel).split()
    return shas[-1] if shas else None


def strictly_before(root: Path, older: str, newer: str) -> bool:
    """True if commit ``older`` is a strict ancestor of commit ``newer``."""
    if older == newer:
        return False
    proc = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def network_isolation() -> list[str]:
    """Return a command prefix that removes network access, or [] when unavailable."""
    unshare = shutil.which("unshare")
    if unshare is None:
        return []
    probe = subprocess.run([unshare, "-rn", "true"], capture_output=True, check=False)
    return [unshare, "-rn"] if probe.returncode == 0 else []


# ---------------------------------------------------------------- pre-phase (G14)


def pre_phase(orig: Path) -> dict[str, str]:
    """Check the original checkout; returns problems keyed by check name."""
    problems: dict[str, str] = {}
    status = git(orig, "status", "--porcelain", "--untracked-files=all")
    if status.strip():
        problems["clean"] = f"working tree not clean ({len(status.splitlines())} entries)"
    tracked_private = git(orig, "ls-files", "--", "private").split()
    if tracked_private:
        problems["private"] = f"{len(tracked_private)} file(s) under private/ are tracked"
    ignored = subprocess.run(
        ["git", "-C", str(orig), "check-ignore", "-q", "private/probe"], check=False
    )
    if ignored.returncode != 0:
        problems["private-ignore"] = "private/ is not git-ignored"
    manifest = orig / "artifacts" / "private_manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for rel, digest in dict(data.get("files", {})).items():
            path = orig / str(rel)
            if not str(rel).startswith("private/"):
                problems["manifest"] = f"private manifest lists {rel} outside private/"
            elif not path.is_file() or sha256_file(path) != digest:
                problems["manifest"] = f"private manifest mismatch for {rel}"
    return problems


# ---------------------------------------------------------------- gates


def g1(ctx: Context) -> str:
    """Build and tests: setup, tests pass, coverage >= 85% on core modules."""
    setup = ctx.make("setup", 900)
    require(setup.ok, f"make setup failed (exit {setup.returncode})")
    cov = ctx.logs / "coverage.json"
    args = [f"COV_JSON={cov}"]
    if ctx.fast:
        args.append("PYTEST_ARGS=-m 'not slow'")
    test = ctx.make("test", 1800, *args)
    require(test.ok, f"make test failed (exit {test.returncode})")
    require(cov.is_file(), "make test wrote no coverage report")
    data = json.loads(cov.read_text(encoding="utf-8"))
    pyproject = tomllib.loads((ctx.clone / "pyproject.toml").read_text(encoding="utf-8"))
    omit = pyproject.get("tool", {}).get("coverage", {}).get("run", {}).get("omit", [])
    for pattern in omit:
        stem = Path(str(pattern)).stem
        contract = ctx.clone / "tests" / "contract" / f"test_{stem}.py"
        require(
            contract.is_file() and "fixtures/recorded" in contract.read_text(encoding="utf-8"),
            f"coverage omits {pattern} without a recorded-fixture contract test",
        )
    per_module: dict[str, list[int]] = {}
    total = [0, 0]
    for name, info in data.get("files", {}).items():
        parts = Path(name).as_posix().split("/")
        if "receipts" not in parts:
            continue
        rel = parts[parts.index("receipts") + 1 :]
        summary = info["summary"]
        covered, statements = int(summary["covered_lines"]), int(summary["num_statements"])
        total[0] += covered
        total[1] += statements
        module = rel[0].removesuffix(".py")
        bucket = per_module.setdefault(module, [0, 0])
        bucket[0] += covered
        bucket[1] += statements
    missing = [
        m
        for m in CORE_MODULES
        if not (ctx.clone / "src" / "receipts" / m).is_dir()
        and not (ctx.clone / "src" / "receipts" / f"{m}.py").is_file()
    ]
    require(not missing, "core modules missing: " + ", ".join(missing))
    overall = 100.0 * total[0] / total[1] if total[1] else 0.0
    require(overall >= COVERAGE_MIN, f"package coverage {overall:.1f}% < {COVERAGE_MIN:.0f}%")
    low = []
    for module in CORE_MODULES:
        covered, statements = per_module.get(module, [0, 0])
        pct = 100.0 * covered / statements if statements else 0.0
        if pct < COVERAGE_MIN:
            low.append(f"{module} {pct:.1f}%")
    require(not low, "core coverage below 85%: " + ", ".join(low))
    return f"setup ok; tests pass; coverage {overall:.1f}%, every core module >= 85%"


TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore(?P<rest>.*)$")
TYPE_IGNORE_OK = re.compile(r"^\[[\w,\- ]+\]\s+#\s*\S.{2,}")


def unexplained_type_ignores(source: str) -> list[int]:
    """Line numbers of ``type: ignore`` comments that lack an error code and a reason.

    Only real comments count (found with ``tokenize``), so text inside string
    literals, such as test data, is ignored. Untokenizable source reports line 0.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return [0]
    bad: list[int] = []
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        m = TYPE_IGNORE.search(token.string)
        if m and not TYPE_IGNORE_OK.match(m.group("rest").strip()):
            bad.append(token.start[0])
    return bad


def g2(ctx: Context) -> str:
    """Static quality: ruff check, ruff format --check, mypy --strict, reasons on ignores."""
    ctx.make("setup", 900)
    lint = ctx.make("lint", 600)
    require(lint.ok, "ruff check or ruff format --check failed")
    types = ctx.make("typecheck", 900)
    require(types.ok, "mypy --strict failed")
    bad: list[str] = []
    for rel in git(ctx.clone, "ls-files", "*.py").split():
        source = (ctx.clone / rel).read_text(encoding="utf-8")
        bad.extend(f"{rel}:{line}" for line in unexplained_type_ignores(source))
    require(not bad, "type: ignore without code and reason at " + ", ".join(bad[:3]))
    return "ruff check, ruff format --check, mypy --strict clean; every type: ignore has a reason"


def g3(ctx: Context, gate_ok: Mapping[int, bool]) -> str:
    """CI parity: ci.yml runs make ci on 3.11 and 3.12, and make ci passes locally."""
    workflow = ctx.clone / ".github" / "workflows" / "ci.yml"
    require(workflow.is_file(), ".github/workflows/ci.yml missing")
    text = workflow.read_text(encoding="utf-8")
    require(
        re.search(r"^\s*(?:-\s*)?run:\s*make ci\s*$", text, re.M) is not None,
        "ci.yml has no 'run: make ci' step",
    )
    versions = re.search(r"python-version:\s*\[([^\]]*)\]", text)
    found = set(re.findall(r"\d+\.\d+", versions.group(1))) if versions else set()
    require({"3.11", "3.12"} <= found, "ci.yml matrix lacks Python 3.11 and 3.12")
    require("matrix.python-version" in text, "ci.yml does not use the matrix Python")
    if ctx.fast:
        require(
            gate_ok.get(1, False) and gate_ok.get(2, False) and gate_ok.get(4, False),
            "fast: make ci parts (lint, typecheck, test, demo) do not all pass",
        )
        return "workflow ok; fast: make ci not re-run, its parts pass in G1, G2, G4"
    ci = ctx.make("ci", 3600)
    require(ci.ok, f"make ci failed (exit {ci.returncode})")
    return f"workflow runs make ci on 3.11 and 3.12; make ci passed in {ci.seconds:.0f}s"


def g4(ctx: Context) -> str:
    """Offline demo: under 3 minutes, no network, no model calls, matches golden output."""
    ctx.make("setup", 900)
    golden = ctx.clone / "tests" / "golden" / "demo_output.txt"
    usage = ctx.clone / "artifacts" / "usage" / "ledger.jsonl"
    usage_before = sha256_file(usage) if usage.is_file() else ""
    prefix = network_isolation()
    offline = {"RECEIPTS_OFFLINE": "1"}
    if not prefix:
        dead = "http://127.0.0.1:9"
        offline.update(
            {
                "HTTPS_PROXY": dead,
                "HTTP_PROXY": dead,
                "https_proxy": dead,
                "http_proxy": dead,
                "NO_PROXY": "",
                "no_proxy": "",
            }
        )
    method = "unshare -rn" if prefix else "dead proxy"
    demo = ctx.run(
        "demo-check", [*prefix, "make", "--no-print-directory", "demo"], DEMO_LIMIT_S + 30, offline
    )
    require(demo.ok, f"make demo failed offline (exit {demo.returncode}, {method})")
    require(demo.seconds < DEMO_LIMIT_S, f"make demo took {demo.seconds:.0f}s >= 180s")
    require(golden.is_file(), "tests/golden/demo_output.txt missing")
    raw = ctx.run(
        "demo-raw",
        [*prefix, "uv", "run", "--no-sync", "python", "tools/demo.py"],
        DEMO_LIMIT_S + 30,
        offline,
    )
    require(raw.ok, "tools/demo.py failed when run without --check")
    require(
        raw.stdout == golden.read_text(encoding="utf-8"),
        "demo output differs from tests/golden/demo_output.txt",
    )
    after = sha256_file(usage) if usage.is_file() else ""
    require(after == usage_before, "demo logged a model call in the usage ledger")
    return f"make demo {demo.seconds:.0f}s offline ({method}); matches golden; no model calls"


def g5(ctx: Context) -> str:
    """Instrument validity on the held-out seeded set, plus ledger completeness."""
    root = ctx.clone
    counts_rel, eval_rel = "artifacts/e0/claim_type_counts.json", "artifacts/e0/seeded_eval.json"
    counts = load_json(root, counts_rel)
    require_provenance(counts_rel, counts)
    smoke = load_json(root, "artifacts/bench/smoke_runs.json")
    smoke_ids = {str(r.get("run_id")) for r in smoke.get("runs", []) if not r.get("synthetic")}
    sources = [str(r) for r in counts.get("source_runs", [])]
    require(
        bool(sources) and set(sources) <= smoke_ids,
        "claim type counts do not come from real G6 smoke runs",
    )
    ranked = sorted(dict(counts.get("counts", {})).items(), key=lambda kv: (-int(kv[1]), kv[0]))
    require(len(ranked) >= 5, "fewer than five claim types counted")
    top5 = [name for name, _ in ranked[:5]]
    seeded = load_json(root, eval_rel)
    require_provenance(eval_rel, seeded)
    require(seeded.get("split") == "heldout", "seeded_eval.json is not the held-out split")
    manifest_rel = str(seeded.get("heldout_manifest", ""))
    manifest = load_json(root, manifest_rel)
    m_first, e_first = first_commit(root, manifest_rel), first_commit(root, eval_rel)
    require(
        m_first is not None and e_first is not None and strictly_before(root, m_first, e_first),
        "held-out manifest was not committed before the G5 evaluation",
    )
    reports = dict(manifest.get("reports", {}))
    for report_id, digest in reports.items():
        path = root / "artifacts" / "e0" / "seeded" / "heldout" / f"{report_id}.json"
        require(
            path.is_file() and sha256_file(path) == digest,
            f"held-out report {report_id} missing or changed",
        )
    items = list(seeded.get("items", []))
    require(
        all(str(i.get("report_id")) in reports for i in items),
        "seeded_eval items include reports outside the held-out manifest",
    )
    parts: list[str] = []
    failing: list[str] = []
    for ctype in top5:
        mine = [i for i in items if i.get("claim_type") == ctype]
        gold = [i for i in mine if i.get("gold_verdict") in VERDICTS]
        pred = [i for i in mine if i.get("pred_verdict") in VERDICTS]
        correct = sum(1 for i in gold if i.get("pred_verdict") == i.get("gold_verdict"))
        if not gold or not pred:
            failing.append(f"{ctype}: no seeded claims")
            continue
        p, r = correct / len(pred), correct / len(gold)
        parts.append(f"{ctype} P={fmt_ci(correct, len(pred))} R={fmt_ci(correct, len(gold))}")
        if p < G5_PRECISION_MIN or r < G5_RECALL_MIN:
            failing.append(ctype)
    completeness_rel = "artifacts/e0/ledger_completeness.json"
    completeness = load_json(root, completeness_rel)
    require_provenance(completeness_rel, completeness)
    runs = list(completeness.get("runs", []))
    require(bool(runs), "no ledger completeness validation runs")
    gaps = 0
    for run in runs:
        missing = Counter(map(str, run.get("transcript_commands", []))) - Counter(
            map(str, run.get("ledger_commands", []))
        )
        gaps += sum(missing.values())
    require(not failing, "below P>=0.95/R>=0.90: " + "; ".join(failing) + " | " + "; ".join(parts))
    require(gaps == 0, f"ledger completeness gap: {gaps} command(s) missing from ledgers")
    return "; ".join(parts) + f"; ledger completeness 100% on {len(runs)} runs"


def g6(ctx: Context) -> str:
    """Benchmark complete: >= 30 tasks, each with hidden checks, reference, manifest, smoke run."""
    root = ctx.clone
    tasks_dir = root / "bench" / "tasks"
    tasks = sorted(p for p in tasks_dir.glob("*") if (p / "task.toml").is_file())
    require(len(tasks) >= G6_MIN_TASKS, f"{len(tasks)} tasks < {G6_MIN_TASKS}")
    validation = load_json(root, "artifacts/bench/reference_validation.json")
    require_provenance("artifacts/bench/reference_validation.json", validation)
    smoke = load_json(root, "artifacts/bench/smoke_runs.json")
    require_provenance("artifacts/bench/smoke_runs.json", smoke)
    smoked = {
        str(r.get("task_id"))
        for r in smoke.get("runs", [])
        if r.get("synthetic") is False and str(r.get("agent", "")).lower() not in NON_AGENTS
    }
    checked = dict(validation.get("tasks", {}))
    problems: list[str] = []
    for task in tasks:
        tid = task.name
        hidden, reference = task / "hidden", task / "reference"
        if not hidden.is_dir() or not any(p.is_file() for p in hidden.rglob("*")):
            problems.append(f"{tid}: no hidden checks")
        if not reference.is_dir() or not any(p.is_file() for p in reference.rglob("*")):
            problems.append(f"{tid}: no reference solution")
        manifest = task / "manifest.json"
        if not manifest.is_file() or not json.loads(manifest.read_text()).get("manipulations"):
            problems.append(f"{tid}: no manipulation manifest")
        entry = checked.get(tid, {})
        if entry.get("hidden_passed") is not True or entry.get("tree_sha256") != tree_sha256(task):
            problems.append(f"{tid}: reference not validated against current task files")
        if tid not in smoked:
            problems.append(f"{tid}: no real agent smoke run")
    require(not problems, f"{len(problems)} problem(s): " + "; ".join(problems[:3]))
    return f"{len(tasks)} tasks; references pass hidden checks; manifests; smoke runs for all"


def _e1_runs(root: Path) -> list[dict[str, Any]]:
    rows = load_jsonl(root, "artifacts/e1/runs.jsonl")
    return [r for r in rows if isinstance(r, dict)]


def g7(ctx: Context) -> str:
    """Main study: as preregistered, >= 3 configs, >= 2 families, >= 60 runs each, intervals."""
    root = ctx.clone
    results_rel = "artifacts/e1/results.json"
    results = load_json(root, results_rel)
    require_provenance(results_rel, results)
    require(
        results.get("confirmatory") is True and bool(results.get("prereg")),
        "E1 results are not marked confirmatory with a preregistration",
    )
    runs = _e1_runs(root)
    require(all(r.get("synthetic") is False for r in runs), "E1 contains synthetic runs")
    included = [r for r in runs if r.get("included") is True]
    by_config: dict[str, list[dict[str, Any]]] = {}
    for run in included:
        by_config.setdefault(str(run.get("config_id")), []).append(run)
    families = {str(r.get("model_family")) for r in included}
    prereg_text = (root / str(results["prereg"])).read_text(encoding="utf-8")
    planned = re.search(r"planned_runs_per_config:\s*(\d+)", prereg_text)
    floor = max(G7_MIN_RUNS, int(planned.group(1)) if planned else 0)
    require(len(by_config) >= G7_MIN_CONFIGS, f"{len(by_config)} agent configurations < 3")
    require(len(families) >= G7_MIN_FAMILIES, f"{len(families)} model families < 2")
    short = [f"{c}={len(v)}" for c, v in by_config.items() if len(v) < floor]
    require(not short, f"configs below {floor} runs: " + ", ".join(short))
    reported = dict(results.get("configs", {}))
    require(set(reported) == set(by_config), "results.json configs differ from runs.jsonl")
    for config, rows in by_config.items():
        entry = reported[config]
        require(int(entry.get("n_runs", -1)) == len(rows), f"{config}: n_runs mismatch")
        fs = sum(1 for r in rows if r.get("false_success") is True) / len(rows)
        claims = [c for r in rows for c in r.get("claims", [])]
        cc = sum(1 for c in claims if c.get("verdict") == "contradicted") / max(1, len(claims))
        for metric, value in (("false_success_rate", fs), ("contradicted_claim_rate", cc)):
            stat = entry.get(metric, {})
            est, lo, hi = stat.get("estimate"), stat.get("ci_low"), stat.get("ci_high")
            require(
                isinstance(est, int | float) and abs(float(est) - value) < 1e-9,
                f"{config}.{metric} does not recompute from runs.jsonl",
            )
            require(
                isinstance(lo, int | float)
                and isinstance(hi, int | float)
                and float(lo) <= value <= float(hi),
                f"{config}.{metric} lacks a valid interval",
            )
    sizes = ", ".join(f"{c}={len(v)}" for c, v in sorted(by_config.items()))
    return f"{len(by_config)} configs, {len(families)} families, runs {sizes}; rates recompute"


def g8(ctx: Context) -> str:
    """Mechanisms (E2) and judges (E3) ran and are reported, including null results."""
    root = ctx.clone
    contradicted = {
        (str(r.get("run_id")), str(c.get("claim_id")))
        for r in _e1_runs(root)
        if r.get("included") is True
        for c in r.get("claims", [])
        if c.get("verdict") == "contradicted"
    }
    mech_rel = "artifacts/e2/mechanism.json"
    mech = load_json(root, mech_rel)
    require_provenance(mech_rel, mech)
    rows = list(mech.get("claims", []))
    classified = {(str(m.get("run_id")), str(m.get("claim_id"))) for m in rows}
    require(classified == contradicted, "E2 does not classify exactly the E1 contradicted claims")
    require(all(m.get("class") in MECHANISM_CLASSES for m in rows), "E2 has unknown classes")
    judges_rel = "artifacts/e3/judges.json"
    judges = load_json(root, judges_rel)
    require_provenance(judges_rel, judges)
    configs = list(judges.get("judges", []))
    require(len(configs) >= 2, f"E3 has {len(configs)} judge configuration(s) < 2")
    for judge in configs:
        per_type = dict(judge.get("per_type", {}))
        require(bool(per_type), f"judge {judge.get('judge_id')} has no per-type results")
        for counts in per_type.values():
            require(
                all(isinstance(counts.get(k), int) for k in ("tp", "fp", "fn")),
                f"judge {judge.get('judge_id')} lacks tp/fp/fn counts",
            )
    report = root / "docs" / "REPORT.md"
    require(report.is_file(), "docs/REPORT.md missing")
    heads = headings(report.read_text(encoding="utf-8"))
    require(any("e2" in h or "mechanism" in h for h in heads), "REPORT.md has no E2 section")
    require(any("e3" in h or "judge" in h for h in heads), "REPORT.md has no E3 section")
    mix = Counter(str(m.get("class")) for m in rows)
    return f"E2 classified {len(rows)} claims {dict(mix)}; E3 {len(configs)} judges; reported"


def g9(ctx: Context) -> str:
    """Mitigation: E4 ran on held-out tasks; receipts-hook packaged, latency, demo transcript."""
    root = ctx.clone
    e4_rel = "artifacts/e4/results.json"
    e4 = load_json(root, e4_rel)
    require_provenance(e4_rel, e4)
    e1_tasks = {str(r.get("task_id")) for r in _e1_runs(root)}
    e4_tasks = {str(t) for t in e4.get("tasks", [])}
    require(bool(e4_tasks), "E4 lists no tasks")
    require(not (e4_tasks & e1_tasks), "E4 tasks overlap E1 tasks (not held out)")
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject.get("project", {}).get("scripts", {})
    require("receipts-hook" in scripts, "pyproject has no receipts-hook entry point")
    hook_doc = root / "docs" / "HOOK.md"
    require(
        hook_doc.is_file() and any("install" in h for h in headings(hook_doc.read_text())),
        "docs/HOOK.md with install instructions missing",
    )
    latency = load_json(root, "artifacts/hook/latency.json")
    require_provenance("artifacts/hook/latency.json", latency)
    samples = [float(s) for s in latency.get("samples_s", [])]
    require(len(samples) >= 20, f"{len(samples)} latency samples < 20")
    median = statistics.median(samples)
    require(median < HOOK_MEDIAN_MAX_S, f"median hook latency {median:.2f}s >= 5s")
    transcript = root / "artifacts" / "hook" / "demo_transcript.txt"
    require(transcript.is_file(), "artifacts/hook/demo_transcript.txt missing")
    header = transcript.read_text(encoding="utf-8").splitlines()[:1]
    script = re.search(r"generated by (\S+)", header[0]) if header else None
    require(
        script is not None and (root / script.group(1)).is_file(),
        "demo transcript does not name an existing generating script",
    )
    return f"E4 on {len(e4_tasks)} held-out tasks; hook packaged; median latency {median:.2f}s"


def g10(ctx: Context) -> str:
    """Claim integrity: make claimcheck and make freshness pass on README.md and REPORT.md."""
    ctx.make("setup", 900)
    claim = ctx.make("claimcheck", 600)
    fresh = ctx.make("freshness", 1200)
    for result, label in ((claim, "claimcheck"), (fresh, "freshness")):
        covered = all(f"{doc}:" in result.stdout for doc in ("README.md", "docs/REPORT.md"))
        require(result.ok, f"make {label} failed: {result.last_line()[:80]}")
        require(covered, f"make {label} did not check both README.md and docs/REPORT.md")
    return "make claimcheck and make freshness pass on README.md and docs/REPORT.md"


def g11(ctx: Context) -> str:
    """Preregistration integrity, refusing a vacuous pass with no confirmatory artifacts."""
    ctx.make("setup", 900)
    verify = ctx.make("prereg-verify", 600)
    require(verify.ok, f"make prereg-verify failed: {verify.last_line()[:80]}")
    detail = ctx.python("prereg-json", ["tools/prereg.py", "verify", "--json"], 600)
    try:
        data = json.loads(detail.stdout)
    except json.JSONDecodeError:
        data = {}
    n = len(data.get("confirmatory_artifacts", []))
    require(data.get("ok") is True and n >= 1, "no confirmatory artifacts cite a preregistration")
    return (
        f"chain intact; {data.get('frozen')} frozen; {n} confirmatory artifact(s) postdate prereg"
    )


def g12(ctx: Context) -> str:
    """Independent review: latest review is SHIP for the current code, zero blocking."""
    ctx.make("setup", 900)
    review = ctx.python("review", ["tools/review.py", "--validate-only"], 600)
    require(
        review.ok and review.last_line() == "REVIEW: SHIP",
        "latest review is not a valid SHIP for HEAD: " + review.last_line()[:60],
    )
    return "artifacts/review/latest.json: REVIEW: SHIP for HEAD, 0 blocking"


def _first_screen(text: str) -> str:
    return "\n".join(text.splitlines()[:60])


def g13(ctx: Context) -> str:
    """Documentation: README follows section 11, REPORT.md complete, citecheck passes."""
    root = ctx.clone
    readme = (root / "README.md").read_text(encoding="utf-8")
    brief = (root / "docs" / "BUILD_BRIEF.md").read_text(encoding="utf-8")
    require(readme != brief, "README.md is still the build brief")
    screen = _first_screen(readme)
    require(re.search(r"^#\s+receipts\b", screen, re.M | re.I) is not None, "no title")
    require(
        "<!--n:" in screen and re.search(r"(?i)\b(CI|interval)\b", screen) is not None,
        "first screen lacks a bound finding with its interval",
    )
    figure = re.search(r"!\[[^\]]*\]\(([^)]+\.svg)\)", screen)
    manifest = root / "artifacts" / "report" / "manifest.json"
    figures = json.loads(manifest.read_text()).get("figures", []) if manifest.is_file() else []
    require(
        figure is not None and (root / figure.group(1)).is_file() and figure.group(1) in figures,
        "headline SVG missing or not generated by make report",
    )
    require(re.search(r"^\|.*\|\s*\n\|\s*:?-{3,}", screen, re.M) is not None, "no headline table")
    require(
        re.search(r"(?i)^#+\s+.*quickstart", screen, re.M) is not None
        and "```" in screen.split("uickstart", 1)[-1],
        "no quickstart on the first screen",
    )
    heads = headings(readme)
    missing = [s for s in README_SECTIONS if not any(s in h for h in heads)]
    require(not missing, "README lacks sections: " + ", ".join(missing))
    report_path = root / "docs" / "REPORT.md"
    require(report_path.is_file(), "docs/REPORT.md missing")
    report = report_path.read_text(encoding="utf-8")
    missing = [s for s in REPORT_SECTIONS if not any(s in h for h in headings(report))]
    require(not missing, "REPORT.md lacks sections: " + ", ".join(missing))
    words = len(re.findall(r"\b\w+\b", strip_code(report)))
    require(REPORT_WORDS[0] <= words <= REPORT_WORDS[1], f"REPORT.md has {words} words")
    for name, text in (("README.md", readme), ("docs/REPORT.md", report)):
        require(EM_DASH not in text, f"{name} contains an em dash")
        require(HYPE.search(text) is None, f"{name} uses a hype word")
    ctx.make("setup", 900)
    cite = ctx.make("citecheck", 600)
    require(cite.ok, f"make citecheck failed: {cite.last_line()[:80]}")
    return f"README follows section 11; REPORT.md {words} words; every reference verified"


def g14(ctx: Context) -> str:
    """Hygiene: secrets scan, budget, private/ untracked, required files, clean tree."""
    require(not ctx.pre, "original checkout: " + "; ".join(ctx.pre.values()))
    ctx.make("setup", 900)
    scan = ctx.make("secrets-scan", 600)
    require(scan.ok, f"make secrets-scan: {scan.last_line()[:80]}")
    spend = ctx.make("budget", 600)
    require(
        spend.ok and re.search(r"^cash_usd = 0$", spend.output, re.M) is not None,
        f"make budget: {spend.last_line()[:80]}",
    )
    absent = [f for f in REQUIRED_FILES if not (ctx.clone / f).is_file()]
    require(not absent, "missing " + ", ".join(absent))
    return "secrets clean; cash_usd = 0, caps respected; private/ untracked; files present; clean"


# ---------------------------------------------------------------- driver


def run_gates(ctx: Context) -> list[tuple[int, bool, str]]:
    """Run G1 to G14 in order and return ``(n, ok, evidence)`` for each."""
    simple: dict[int, Callable[[Context], str]] = {
        1: g1,
        2: g2,
        4: g4,
        5: g5,
        6: g6,
        7: g7,
        8: g8,
        9: g9,
        10: g10,
        11: g11,
        12: g12,
        13: g13,
        14: g14,
    }
    outcome: dict[int, tuple[bool, str]] = {}
    for n in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 3):
        try:
            gate_ok = {k: v[0] for k, v in outcome.items()}
            evidence = g3(ctx, gate_ok) if n == 3 else simple[n](ctx)
            outcome[n] = (True, evidence)
        except GateError as exc:
            outcome[n] = (False, str(exc))
        except Exception as exc:  # a crashing check is a FAIL, never a skip
            outcome[n] = (False, f"check error: {type(exc).__name__}: {exc}"[:160])
    return [(n, *outcome[n]) for n in range(1, 15)]


def one_line(text: str) -> str:
    """Collapse evidence to a single line."""
    return " ".join(text.split())


def main(argv: Iterable[str] | None = None) -> int:
    """Run ship-check and print the exact report format."""
    parser = argparse.ArgumentParser(description="Run the 14 ship gates on a fresh clone.")
    parser.add_argument("--fast", action="store_true", help="skip slow steps; does not count")
    parser.add_argument("--keep", action="store_true", help="keep the temporary clone")
    args = parser.parse_args(list(argv) if argv is not None else None)
    orig = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    sha = git(orig, "rev-parse", "HEAD").strip()
    pre = pre_phase(orig)
    tmp = Path(tempfile.mkdtemp(prefix="receipts-ship-check-"))
    logs = tmp / "logs"
    logs.mkdir()
    clone = tmp / "clone"
    subprocess.run(["git", "clone", "--quiet", str(orig), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "checkout", "--quiet", "--detach", sha], check=True)
    ctx = Context(orig=orig, clone=clone, logs=logs, fast=args.fast, sha=sha, pre=pre)
    results = run_gates(ctx)
    print(f"HEAD {sha} fresh-clone")
    for n, ok, evidence in results:
        print(f"G{n} {'PASS' if ok else 'FAIL'} {one_line(evidence)}")
    passed = sum(1 for _, ok, _ in results if ok)
    if args.fast:
        print(f"SHIP-CHECK-FAST (does not count): {passed}/14")
    elif passed == 14:
        print("SHIP-CHECK: PASS 14/14")
    else:
        print(f"SHIP-CHECK: FAIL {passed}/14")
    if not args.keep:
        shutil.rmtree(clone, ignore_errors=True)
    print(f"ship-check logs: {logs}", file=sys.stderr)
    return 0 if passed == 14 and not args.fast else 1


if __name__ == "__main__":
    sys.exit(main())
