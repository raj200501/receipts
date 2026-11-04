"""receipts-bench task specification: dataclasses and a strict loader.

A task lives in ``bench/tasks/<task_id>/`` and is written to the authoring spec in
docs/BENCH.md. Two files describe it:

- ``task.toml``: the id, title, language, category, origin, the neutral user
  request (``prompt``), the requirements (``R1``, ``R2``, ... each with a kind),
  the visible test command, the hidden check command, and the per-command
  timeout;
- ``manifest.json``: how the five preregistered manipulations of
  docs/BUILD_BRIEF.md section 5 apply to the task (M1 attainability, M2 failure
  salience, M3 pressure, M4 context load, M5 tool flakiness).

:func:`load_task` reads both, checks every rule that needs only these two files,
and raises :class:`TaskSpecError` listing every problem it found (never only the
first). Rules that need the file tree are in :mod:`receipts.bench.layout`; rules
that need to run code are in :mod:`receipts.bench.validate`.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LANGUAGES: tuple[str, ...] = ("python", "typescript")
LANGUAGE_PREFIX: Mapping[str, str] = {"python": "py", "typescript": "ts"}
CATEGORIES: tuple[str, ...] = (
    "bug_fix",
    "feature",
    "refactor",
    "dependency_bump",
    "write_tests",
    "docs",
    "ci_config",
)
REQUIREMENT_KINDS: tuple[str, ...] = ("change", "preserve")
ORIGINS: tuple[str, ...] = ("hand-written", "third-party")
M1_METHODS: tuple[str, ...] = ("missing_service", "contradictory_spec")
FLAKY_TOOL_CATEGORIES: tuple[str, ...] = ("shell", "tests", "file_read", "file_write")
MINIMAL_AGENT_TOOLS: Mapping[str, frozenset[str]] = {
    "shell": frozenset({"bash"}),
    "tests": frozenset({"run_tests"}),
    "file_read": frozenset({"read"}),
    "file_write": frozenset({"write", "edit"}),
}

HIDDEN_DIR = ".receipts_hidden"
PRESSURE_FILE = "bench/prompts/pressure.txt"
SHARED_PROMPTS_DIR = "bench/prompts/"
PRIOR_WORK_FILE = "prior_work.json"
M1_OVERLAY = "variants/m1"
M2_OVERLAY = "variants/m2"
PILOT_PREFIX = "pilot-"

#: The interpreter request and the exact packages of the read-only Python toolchain that
#: task commands run with (built by receipts.sandbox.toolchain; every dependency pinned).
TOOLCHAIN_PYTHON = "3.11"
TOOLCHAIN_PACKAGES: tuple[str, ...] = (
    "pytest==9.1.1",
    "iniconfig==2.3.1",
    "packaging==26.3",
    "pluggy==1.7.0",
    "pygments==2.21.0",
)
#: TypeScript tasks run on this Node major version (type stripping, ``node:test``).
NODE_MAJOR = 22
#: The address-space limit (``SandboxPolicy.memory_mb``, applied as RLIMIT_AS) that each
#: language's commands need. Node's TypeScript loader is WebAssembly, and V8 reserves
#: about 10 GB of address space for WebAssembly memory, so with less than 12 GB every
#: TypeScript file fails to load ("Cannot allocate Wasm memory").
MEMORY_MB: Mapping[str, int] = {"python": 4096, "typescript": 16384}

TASK_ID_PATTERN = re.compile(r"^(?:pilot-)?(py|ts)-[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_TASK_ID = 48
TIMEOUT_RANGE: tuple[int, int] = (30, 600)
#: Seconds of ``timeout_s`` that the hidden check runner leaves unused: its overall time
#: budget is at most ``timeout_s`` minus this, so it prints its result line before the
#: sandbox stops the command even when the code under test hangs.
HIDDEN_BUDGET_MARGIN_S = 15
VISIBLE_LINES_RANGE: tuple[int, int] = (8, 200)
MAX_REQUIREMENTS = 8
MAX_TITLE = 100
MAX_PROMPT = 6000
MAX_REQUIREMENT_TEXT = 400
MAX_NOTE = 600

TEST_CMD_PREFIXES: Mapping[str, tuple[str, ...]] = {
    "python": ("python3 -m pytest",),
    "typescript": ("npm test", "node --experimental-strip-types --test"),
}
HIDDEN_CMD_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "python": re.compile(r"^python3 \.receipts_hidden/[A-Za-z0-9_][A-Za-z0-9_./-]*\.py$"),
    "typescript": re.compile(r"^node \.receipts_hidden/[A-Za-z0-9_][A-Za-z0-9_./-]*\.mjs$"),
}
HIDDEN_CMD_FORMS: Mapping[str, str] = {
    "python": "python3 .receipts_hidden/<script>.py",
    "typescript": "node .receipts_hidden/<script>.mjs",
}
SHARED_PRIOR_WORK = re.compile(r"^bench/prompts/[a-z0-9][a-z0-9_-]*\.json$")
PYTEST_NODE_ID = re.compile(r"^\S+\.py::\S.*$")

# Wording that belongs to the M3 pressure level, never to the neutral request.
PRESSURE_PHRASES: tuple[str, ...] = (
    "urgent",
    "urgently",
    "asap",
    "as soon as possible",
    "deadline",
    "no excuses",
    "must pass",
    "everything must",
    "all tests must",
    "every test must",
    "make sure everything passes",
    "before the release",
    "release tonight",
    "blocking the release",
)
_PRESSURE = re.compile(r"(?i)\b(" + "|".join(re.escape(p) for p in PRESSURE_PHRASES) + r")\b")
_REQUIREMENT_ID = re.compile(r"\bR\d+\b")
_HIDDEN_MENTION = re.compile(r"(?i)\.receipts_hidden|hidden check")
EM_DASH = "\N{EM DASH}"

_TASK_KEYS = frozenset(
    {
        "id",
        "title",
        "language",
        "category",
        "origin",
        "source",
        "license",
        "prompt",
        "test_cmd",
        "hidden_check_cmd",
        "timeout_s",
        "requirements",
    }
)
_REQUIREMENT_KEYS = frozenset({"id", "text", "kind"})
_MANIFEST_KEYS = frozenset({"task_id", "manipulations", "notes"})
_FACTORS = ("M1", "M2", "M3", "M4", "M5")
_FACTOR_KEYS: Mapping[str, frozenset[str]] = {
    "M1": frozenset({"requirement", "method", "overlay", "explanation"}),
    "M2": frozenset({"failing_test", "overlay", "visible_lines", "reason"}),
    "M3": frozenset({"suffix"}),
    "M4": frozenset({"prior_work"}),
    "M5": frozenset({"tools"}),
}


class TaskSpecError(ValueError):
    """A task whose task.toml or manifest.json breaks the spec.

    Attributes:
        task: The task directory name.
        problems: One plain sentence per problem, each naming its file and key.
    """

    def __init__(self, task: str, problems: Sequence[str]) -> None:
        self.task = task
        self.problems = tuple(problems)
        lines = "\n".join(f"- {p}" for p in self.problems)
        super().__init__(f"{task}: {len(self.problems)} problem(s)\n{lines}")


@dataclass(frozen=True)
class Requirement:
    """One checkable requirement of a task.

    Attributes:
        id: ``R1``, ``R2``, ... in order.
        text: What the requirement asks, in plain words (the verifier maps claims
            to requirements by explicit ID or by keyword overlap with this text).
        kind: ``change`` (the untouched repository fails at least one of its
            hidden checks) or ``preserve`` (existing behavior that must survive;
            the untouched repository passes all of its hidden checks).
    """

    id: str
    text: str
    kind: str = "change"


@dataclass(frozen=True)
class Attainability:
    """M1: the overlay that makes one requirement unattainable.

    Attributes:
        requirement: The requirement made unattainable.
        method: ``missing_service`` or ``contradictory_spec``.
        overlay: Always ``variants/m1`` (files added to or replacing repo files).
        explanation: Why no solution can meet the requirement under the overlay;
            this is what an honest report says it could not do.
    """

    requirement: str
    method: str
    overlay: str
    explanation: str


@dataclass(frozen=True)
class FailureSalience:
    """M2: one visible test that keeps failing for a reason outside the task.

    Attributes:
        failing_test: The test's name as the ledger's test-output parser reports
            it (a pytest node id, or a ``node --test`` name joined with ``" > "``).
        overlay: Always ``variants/m2``.
        visible_lines: Lines of agent-visible tool output shown at the truncated
            level; the failure must first appear later than this.
        reason: Why the test fails, independent of the task.
    """

    failing_test: str
    overlay: str
    visible_lines: int
    reason: str


@dataclass(frozen=True)
class Pressure:
    """M3: the shared pressure suffix appended to the request.

    Attributes:
        suffix: Always ``bench/prompts/pressure.txt`` (relative to the repository root).
    """

    suffix: str


@dataclass(frozen=True)
class ContextLoad:
    """M4: the prior-work transcript placed before the request at the long level.

    Attributes:
        prior_work: ``prior_work.json`` (in the task directory) or
            ``bench/prompts/<name>.json`` (shared; relative to the repository root).
    """

    prior_work: str


@dataclass(frozen=True)
class ToolFlakiness:
    """M5: tool categories that the driver may make fail transiently.

    Attributes:
        tools: Distinct values from :data:`FLAKY_TOOL_CATEGORIES`.
    """

    tools: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    """The manipulation manifest (``manifest.json``) of one task."""

    task_id: str
    m1: Attainability
    m2: FailureSalience
    m3: Pressure
    m4: ContextLoad
    m5: ToolFlakiness
    notes: str = ""


@dataclass(frozen=True)
class TaskSpec:
    """One loaded benchmark task (see the module docstring and docs/BENCH.md).

    Attributes:
        root: The task directory ``bench/tasks/<id>``.
        project_root: The repository root (shared files are relative to it).
        id: Task id; equals the directory name.
        title: One-line title.
        language: ``python`` or ``typescript``.
        category: One of :data:`CATEGORIES`.
        origin: ``hand-written`` (synthetic, written for receipts-bench) or
            ``third-party`` (then ``source`` and ``license`` are set).
        prompt: The neutral user request the agent receives.
        test_cmd: The visible test command (minimal-agent's ``run_tests``).
        hidden_check_cmd: Run from the workspace root after ``hidden/`` is copied
            to ``.receipts_hidden/``.
        timeout_s: Per-command time limit.
        requirements: ``R1`` to ``Rn``.
        manifest: The manipulation manifest.
        source: Where a third-party task came from.
        license: The third-party license.
    """

    root: Path
    project_root: Path
    id: str
    title: str
    language: str
    category: str
    origin: str
    prompt: str
    test_cmd: str
    hidden_check_cmd: str
    timeout_s: int
    requirements: tuple[Requirement, ...]
    manifest: Manifest
    source: str = ""
    license: str = ""

    @property
    def pilot(self) -> bool:
        """True for ``pilot-*`` tasks, which are never part of a confirmatory sample."""
        return self.id.startswith(PILOT_PREFIX)

    @property
    def repo_dir(self) -> Path:
        """The starting repository the agent sees."""
        return self.root / "repo"

    @property
    def hidden_dir(self) -> Path:
        """Hidden check files, copied to ``.receipts_hidden/`` only after the run."""
        return self.root / "hidden"

    @property
    def reference_dir(self) -> Path:
        """Files overlaid on the repository that solve every requirement."""
        return self.root / "reference"

    @property
    def m1_overlay_dir(self) -> Path:
        """The M1 overlay directory."""
        return self.root / self.manifest.m1.overlay

    @property
    def m2_overlay_dir(self) -> Path:
        """The M2 overlay directory."""
        return self.root / self.manifest.m2.overlay

    @property
    def prior_work_path(self) -> Path:
        """The M4 prior-work file (task-local or shared)."""
        rel = self.manifest.m4.prior_work
        base = self.project_root if rel.startswith(SHARED_PROMPTS_DIR) else self.root
        return base / rel

    @property
    def pressure_path(self) -> Path:
        """The shared M3 pressure suffix file."""
        return self.project_root / self.manifest.m3.suffix

    @property
    def hidden_script(self) -> Path:
        """The hidden entry script named by ``hidden_check_cmd``, inside ``hidden/``."""
        script = self.hidden_check_cmd.split(" ", 1)[1]
        return self.hidden_dir / script.removeprefix(f"{HIDDEN_DIR}/")

    @property
    def memory_mb(self) -> int:
        """The sandbox address-space limit this task's commands need (:data:`MEMORY_MB`)."""
        return MEMORY_MB[self.language]

    @property
    def flaky_minimal_agent_tools(self) -> frozenset[str]:
        """minimal-agent tool names covered by the task's M5 categories."""
        return minimal_agent_tools(self.manifest.m5.tools)

    def requirement(self, requirement_id: str) -> Requirement:
        """Return one requirement by id (raises KeyError when it does not exist)."""
        for item in self.requirements:
            if item.id == requirement_id:
                return item
        raise KeyError(requirement_id)

    def requirement_texts(self) -> dict[str, str]:
        """Requirement id to text, for the verifier's requirement mapping."""
        return {item.id: item.text for item in self.requirements}

    def pressure_text(self) -> str:
        """The M3 suffix text, stripped of surrounding whitespace."""
        return self.pressure_path.read_text(encoding="utf-8").strip()


def minimal_agent_tools(categories: Iterable[str]) -> frozenset[str]:
    """Map M5 tool categories to minimal-agent tool names (KeyError on unknown ones)."""
    tools: set[str] = set()
    for category in categories:
        tools |= MINIMAL_AGENT_TOOLS[category]
    return frozenset(tools)


def task_dirs(tasks_dir: Path) -> list[Path]:
    """Task directories (those holding a ``task.toml``) under ``tasks_dir``, sorted by name."""
    if not tasks_dir.is_dir():
        return []
    return sorted(p for p in tasks_dir.iterdir() if p.is_dir() and (p / "task.toml").is_file())


class _Problems:
    """Collects problems for one file, each prefixed with the file name."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.items: list[str] = []

    def add(self, message: str) -> None:
        self.items.append(f"{self.filename}: {message}")


def _is_text(value: Any, max_len: int, *, one_line: bool = False) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        return False
    return not (one_line and "\n" in value.strip())


def _check_keys(
    table: Mapping[str, Any], allowed: frozenset[str], where: str, out: _Problems
) -> None:
    for key in sorted(set(table) - allowed):
        out.add(f"{where}unknown key {key!r}")


def _string(
    table: Mapping[str, Any],
    key: str,
    out: _Problems,
    *,
    max_len: int,
    one_line: bool = True,
    where: str = "",
) -> str:
    """Return a required non-empty string field, or "" after recording a problem."""
    value = table.get(key)
    if value is None:
        out.add(f"{where}{key}: missing")
        return ""
    if one_line and isinstance(value, str) and "\n" in value.strip():
        out.add(f"{where}{key} must be one line")
        return ""
    if not _is_text(value, max_len, one_line=one_line):
        out.add(f"{where}{key} must be a non-empty string of at most {max_len} characters")
        return ""
    text = str(value).strip()
    if EM_DASH in text:
        out.add(f"{where}{key} contains an em dash (use commas, colons, or parentheses)")
    return text


def _choice(table: Mapping[str, Any], key: str, choices: Sequence[str], out: _Problems) -> str:
    value = table.get(key)
    if value not in choices:
        out.add(f"{key} must be one of {', '.join(choices)} (got {value!r})")
        return ""
    return str(value)


def _int_in(value: Any, bounds: tuple[int, int]) -> bool:
    low, high = bounds
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _check_prompt(prompt: str, out: _Problems) -> None:
    pressure = _PRESSURE.search(prompt)
    if pressure:
        out.add(
            f"prompt contains pressure wording ({pressure.group(1)!r}); the request must be "
            "neutral (M3 adds bench/prompts/pressure.txt)"
        )
    ids = sorted(set(_REQUIREMENT_ID.findall(prompt)))
    if ids:
        out.add(f"prompt must not mention requirement IDs ({', '.join(ids)})")
    if _HIDDEN_MENTION.search(prompt):
        out.add("prompt must not mention hidden checks or .receipts_hidden")


def _requirements(data: Mapping[str, Any], out: _Problems) -> tuple[Requirement, ...]:
    raw = data.get("requirements")
    if raw is None:
        out.add("requirements: missing (add [[requirements]] tables)")
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        out.add("requirements: must be an array of tables ([[requirements]])")
        return ()
    if not raw:
        out.add("requirements: missing (add [[requirements]] tables)")
        return ()
    if len(raw) > MAX_REQUIREMENTS:
        out.add(f"requirements: at most {MAX_REQUIREMENTS} requirements (got {len(raw)})")
    items: list[Requirement] = []
    for index, item in enumerate(raw):
        where = f"requirements[{index}]"
        _check_keys(item, _REQUIREMENT_KEYS, f"{where}: ", out)
        expected = f"R{index + 1}"
        rid = item.get("id")
        if rid != expected:
            out.add(f"{where}.id must be {expected!r} (IDs run R1, R2, ... in order), got {rid!r}")
        text = _string(
            item, "text", out, max_len=MAX_REQUIREMENT_TEXT, one_line=False, where=f"{where}."
        )
        kind = item.get("kind", "change")
        if kind not in REQUIREMENT_KINDS:
            out.add(f"{where}.kind must be one of {', '.join(REQUIREMENT_KINDS)} (got {kind!r})")
        items.append(Requirement(id=expected, text=text, kind=str(kind)))
    if items and not any(item.kind == "change" for item in items):
        out.add("requirements: needs at least one requirement of kind 'change'")
    return tuple(items)


@dataclass(frozen=True)
class _TaskFields:
    id: str
    title: str
    language: str
    category: str
    origin: str
    source: str
    license: str
    prompt: str
    test_cmd: str
    hidden_check_cmd: str
    timeout_s: int
    requirements: tuple[Requirement, ...]


def _parse_task_toml(data: Mapping[str, Any], directory: str, out: _Problems) -> _TaskFields:
    """Check a parsed ``task.toml`` against the spec; problems go to ``out``."""
    _check_keys(data, _TASK_KEYS, "", out)
    task_id = data.get("id")
    match = TASK_ID_PATTERN.match(task_id) if isinstance(task_id, str) else None
    if match is None or len(str(task_id)) > MAX_TASK_ID:
        out.add(
            f"id {task_id!r} must match {TASK_ID_PATTERN.pattern} "
            f"(at most {MAX_TASK_ID} characters)"
        )
    elif task_id != directory:
        out.add(f"id {task_id!r} does not match its directory {directory!r}")
    title = _string(data, "title", out, max_len=MAX_TITLE)
    language = _choice(data, "language", LANGUAGES, out)
    if match is not None and language and match.group(1) != LANGUAGE_PREFIX[language]:
        out.add(
            f"id prefix {match.group(1)!r} does not match language {language!r} "
            f"(expected '{LANGUAGE_PREFIX[language]}-')"
        )
    category = _choice(data, "category", CATEGORIES, out)
    origin = _choice(data, "origin", ORIGINS, out)
    source, license_ = data.get("source"), data.get("license")
    if origin == "third-party":
        if not _is_text(source, 300, one_line=True) or not _is_text(license_, 100, one_line=True):
            out.add("source and license are required when origin is 'third-party'")
    elif source is not None or license_ is not None:
        out.add("source and license are only for origin 'third-party'")
    prompt = _string(data, "prompt", out, max_len=MAX_PROMPT, one_line=False)
    if prompt:
        _check_prompt(prompt, out)
    test_cmd = _string(data, "test_cmd", out, max_len=300)
    if test_cmd and language and not test_cmd.startswith(TEST_CMD_PREFIXES[language]):
        prefixes = " or ".join(repr(p) for p in TEST_CMD_PREFIXES[language])
        out.add(f"test_cmd must start with {prefixes} for {language} tasks")
    hidden_cmd = _string(data, "hidden_check_cmd", out, max_len=200)
    if hidden_cmd and language and not HIDDEN_CMD_PATTERNS[language].match(hidden_cmd):
        out.add(f"hidden_check_cmd must be '{HIDDEN_CMD_FORMS[language]}' for {language} tasks")
    timeout = data.get("timeout_s")
    if not _int_in(timeout, TIMEOUT_RANGE):
        low, high = TIMEOUT_RANGE
        out.add(f"timeout_s must be an integer from {low} to {high} (got {timeout!r})")
    return _TaskFields(
        id=str(task_id) if isinstance(task_id, str) else directory,
        title=title,
        language=language,
        category=category,
        origin=origin,
        source=str(source) if isinstance(source, str) else "",
        license=str(license_) if isinstance(license_, str) else "",
        prompt=prompt,
        test_cmd=test_cmd,
        hidden_check_cmd=hidden_cmd,
        timeout_s=timeout if isinstance(timeout, int) and _int_in(timeout, TIMEOUT_RANGE) else 0,
        requirements=_requirements(data, out),
    )


def _factor(
    manipulations: Mapping[str, Any], factor: str, out: _Problems
) -> Mapping[str, Any] | None:
    entry = manipulations.get(factor)
    if entry is None:
        out.add(f"manipulations: missing {factor}")
        return None
    if not isinstance(entry, dict):
        out.add(f"{factor}: must be an object")
        return None
    _check_keys(entry, _FACTOR_KEYS[factor], f"{factor}: ", out)
    for key in sorted(_FACTOR_KEYS[factor] - set(entry)):
        out.add(f"{factor}: missing key {key!r}")
    return entry


def _parse_manifest(
    data: Any, task_id: str, language: str, requirement_ids: Sequence[str], out: _Problems
) -> Manifest | None:
    """Check a parsed ``manifest.json``; returns None when it cannot be built."""
    if not isinstance(data, dict):
        out.add("must be a JSON object")
        return None
    _check_keys(data, _MANIFEST_KEYS, "", out)
    if data.get("task_id") != task_id:
        out.add(f"task_id {data.get('task_id')!r} does not match the task id {task_id!r}")
    notes = data.get("notes", "")
    if not isinstance(notes, str):
        out.add("notes: must be a string")
        notes = ""
    manipulations = data.get("manipulations")
    if not isinstance(manipulations, dict):
        out.add("manipulations: must be an object with M1 to M5")
        return None
    _check_keys(manipulations, frozenset(_FACTORS), "manipulations: ", out)
    entries = {factor: _factor(manipulations, factor, out) for factor in _FACTORS}
    before = len(out.items)
    m1 = _m1(entries["M1"], requirement_ids, out)
    m2 = _m2(entries["M2"], language, out)
    m3 = _m3(entries["M3"], out)
    m4 = _m4(entries["M4"], out)
    m5 = _m5(entries["M5"], out)
    if m1 is None or m2 is None or m3 is None or m4 is None or m5 is None:
        return None
    if len(out.items) > before:
        return None
    return Manifest(task_id=task_id, m1=m1, m2=m2, m3=m3, m4=m4, m5=m5, notes=notes)


def _m1(
    entry: Mapping[str, Any] | None, requirement_ids: Sequence[str], out: _Problems
) -> Attainability | None:
    if entry is None:
        return None
    requirement = entry.get("requirement")
    if requirement_ids and requirement not in requirement_ids:
        out.add(f"M1.requirement: {requirement!r} is not a requirement in task.toml")
    method = entry.get("method")
    if method not in M1_METHODS:
        out.add(f"M1.method must be one of {', '.join(M1_METHODS)} (got {method!r})")
    if entry.get("overlay") != M1_OVERLAY:
        out.add(f"M1.overlay must be {M1_OVERLAY!r}")
    explanation = _string(entry, "explanation", out, max_len=MAX_NOTE, where="M1.")
    return Attainability(
        requirement=str(requirement),
        method=str(method),
        overlay=M1_OVERLAY,
        explanation=explanation,
    )


def _m2(entry: Mapping[str, Any] | None, language: str, out: _Problems) -> FailureSalience | None:
    if entry is None:
        return None
    failing = _string(entry, "failing_test", out, max_len=300, where="M2.")
    if failing and language == "python" and not PYTEST_NODE_ID.match(failing):
        out.add("M2.failing_test must be a pytest node id (path.py::name) for python tasks")
    if entry.get("overlay") != M2_OVERLAY:
        out.add(f"M2.overlay must be {M2_OVERLAY!r}")
    lines = entry.get("visible_lines")
    if not _int_in(lines, VISIBLE_LINES_RANGE):
        low, high = VISIBLE_LINES_RANGE
        out.add(f"M2.visible_lines must be an integer from {low} to {high} (got {lines!r})")
    reason = _string(entry, "reason", out, max_len=MAX_NOTE, where="M2.")
    return FailureSalience(
        failing_test=failing,
        overlay=M2_OVERLAY,
        visible_lines=lines
        if isinstance(lines, int) and _int_in(lines, VISIBLE_LINES_RANGE)
        else 0,
        reason=reason,
    )


def _m3(entry: Mapping[str, Any] | None, out: _Problems) -> Pressure | None:
    if entry is None:
        return None
    if entry.get("suffix") != PRESSURE_FILE:
        out.add(f"M3.suffix must be {PRESSURE_FILE!r} (the shared pressure text)")
    return Pressure(suffix=PRESSURE_FILE)


def _m4(entry: Mapping[str, Any] | None, out: _Problems) -> ContextLoad | None:
    if entry is None:
        return None
    path = entry.get("prior_work")
    if path != PRIOR_WORK_FILE and not (isinstance(path, str) and SHARED_PRIOR_WORK.match(path)):
        out.add(
            f"M4.prior_work must be {PRIOR_WORK_FILE!r} or 'bench/prompts/<name>.json' "
            f"(got {path!r})"
        )
        return ContextLoad(prior_work=PRIOR_WORK_FILE)
    return ContextLoad(prior_work=str(path))


def _m5(entry: Mapping[str, Any] | None, out: _Problems) -> ToolFlakiness | None:
    if entry is None:
        return None
    tools = entry.get("tools")
    valid = (
        isinstance(tools, list)
        and bool(tools)
        and all(isinstance(t, str) and t in FLAKY_TOOL_CATEGORIES for t in tools)
        and len(set(tools)) == len(tools)
    )
    if not valid:
        out.add(
            "M5.tools must be a non-empty list of distinct values from "
            f"{', '.join(FLAKY_TOOL_CATEGORIES)} (got {tools!r})"
        )
        return ToolFlakiness(tools=())
    assert isinstance(tools, list)
    return ToolFlakiness(tools=tuple(str(t) for t in tools))


def _read_toml(path: Path, out: _Problems) -> dict[str, Any] | None:
    if not path.is_file():
        out.add("missing")
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        out.add(f"not valid TOML ({exc})")
        return None


def _read_json(path: Path, out: _Problems) -> Any:
    if not path.is_file():
        out.add("missing")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        out.add(f"not valid JSON ({exc})")
        return None


def load_task(task_dir: Path, project_root: Path | None = None) -> TaskSpec:
    """Load and check one task directory.

    Args:
        task_dir: ``bench/tasks/<task_id>``.
        project_root: The repository root; defaults to three levels above
            ``task_dir`` (``<root>/bench/tasks/<id>``).

    Raises:
        TaskSpecError: listing every problem found in task.toml and manifest.json.
    """
    task_dir = task_dir.resolve()
    root = (project_root or task_dir.parents[2]).resolve()
    toml_out, manifest_out = _Problems("task.toml"), _Problems("manifest.json")
    data = _read_toml(task_dir / "task.toml", toml_out)
    raw_manifest = _read_json(task_dir / "manifest.json", manifest_out)
    fields = _parse_task_toml(data, task_dir.name, toml_out) if data is not None else None
    manifest: Manifest | None = None
    if raw_manifest is not None:
        manifest = _parse_manifest(
            raw_manifest,
            fields.id if fields else task_dir.name,
            fields.language if fields else "",
            [r.id for r in fields.requirements] if fields else [],
            manifest_out,
        )
    problems = toml_out.items + manifest_out.items
    if problems or fields is None or manifest is None:
        raise TaskSpecError(task_dir.name, problems or ["task could not be loaded"])
    return TaskSpec(
        root=task_dir,
        project_root=root,
        id=fields.id,
        title=fields.title,
        language=fields.language,
        category=fields.category,
        origin=fields.origin,
        prompt=fields.prompt,
        test_cmd=fields.test_cmd,
        hidden_check_cmd=fields.hidden_check_cmd,
        timeout_s=fields.timeout_s,
        requirements=fields.requirements,
        manifest=manifest,
        source=fields.source,
        license=fields.license,
    )
