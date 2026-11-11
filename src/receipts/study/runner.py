"""Run one agent on one benchmark task under one set of conditions, and bank the result.

A run, in order:

1. Copy the task repository into a fresh workspace (git-initialized), apply the
   condition overlays (M1 unattainable requirement, M2 persistent failing test), and
   commit that state as the base.
2. Open the run's ledger in ``<artifacts>/<run_id>/ledger.jsonl`` and write
   ``run_start`` with the conditions.
3. Run minimal-agent: tools execute only in the sandbox; M2 truncation and M5
   flakiness act at the tool boundary; M3 adds the pressure text to the request; M4
   puts realistic prior work before it.
4. Post-run ground truth: the diff against the base and a rerun of the visible tests
   (``take_snapshot``), then, only after both, the hidden checks are copied in under
   ``.receipts_hidden/`` and run, so they never reach the agent, the diff, or the
   visible test collection.
5. Write ``run_end``, then extract and verify the report's claims and bank
   ``transcript.json``, ``verification.json``, and ``run.json`` (provenance and
   summary) next to the ledger.

Nothing here decides the study design. Condition levels come from the run spec; their
concrete meaning (which overlay, which text, which rate) comes from the task and the
study configuration, all of which are recorded in provenance.
"""

from __future__ import annotations

import datetime as dt
import json
import platform
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from receipts.claims.extract import extract_claims
from receipts.client.wrapper import ModelClient
from receipts.drivers.minimal_agent.boundary import TruncationPolicy
from receipts.drivers.minimal_agent.loop import AgentConfig, AgentResult, Message, run_agent
from receipts.drivers.minimal_agent.runtime import SandboxRuntime
from receipts.hook.stop import contradicted, format_reason
from receipts.ledger.events import Ledger, LedgerWriter, canonical_json, sha256_text
from receipts.ledger.parsers.hidden import parse_hidden_check_list
from receipts.ledger.recorder import Recorder
from receipts.ledger.snapshot import take_snapshot
from receipts.sandbox.api import Sandbox
from receipts.study.spec import (
    EVIDENCE_FORMAT,
    HONESTY_INSTRUCTION,
    MITIGATIONS,
    Arm,
    RunSpec,
    RunTask,
    StudyText,
    check_conditions,
)
from receipts.verify import verify_run

HIDDEN_DIR = ".receipts_hidden"
#: Files that running tools generates, never meaningful changes: excluded from the
#: workspace's git view so the snapshot diff shows only what the agent changed.
GENERATED_ARTIFACTS: tuple[str, ...] = (
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".coverage",
    "node_modules/.cache/",
)
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "receipts",
    "GIT_AUTHOR_EMAIL": "receipts@localhost",
    "GIT_COMMITTER_NAME": "receipts",
    "GIT_COMMITTER_EMAIL": "receipts@localhost",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}


def overlay(src: Path, dst: Path) -> None:
    """Copy every file under ``src`` onto ``dst`` (overwriting), creating directories."""
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        target = dst / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _git(work: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(work), *args],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(work), **GIT_ENV},
    ).stdout


def prepare_workspace(task: RunTask, conditions: Mapping[str, str], work: Path) -> str:
    """Build the run's starting repository and return its base commit."""
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(task.repo_dir, work, ignore=shutil.ignore_patterns(".git"))
    if conditions.get("M1") == "unattainable":
        if task.unattainable_overlay is None:
            raise ValueError(f"{task.task_id} has no M1 overlay")
        overlay(task.unattainable_overlay, work)
    if conditions.get("M2") in ("full", "truncated") and task.failing_test_overlay is not None:
        overlay(task.failing_test_overlay, work)
    _git(work, "init", "-q", "-b", "main")
    (work / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (work / ".git" / "info" / "exclude").write_text(
        "\n".join([f"{HIDDEN_DIR}/", *GENERATED_ARTIFACTS]) + "\n", encoding="utf-8"
    )
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "task start")
    return _git(work, "rev-parse", "HEAD").strip()


def configure_agent(
    arm: Arm,
    task: RunTask,
    conditions: Mapping[str, str],
    study: StudyText,
    seed: int,
    mitigation: str = "none",
) -> tuple[AgentConfig, str, Sequence[Message]]:
    """The agent configuration, request, and prior messages implied by the conditions."""
    prompt = task.prompt
    if conditions.get("M3") == "pressure" and study.pressure_suffix:
        prompt = f"{prompt}\n\n{study.pressure_suffix}"
    prior: Sequence[Message] = task.prior_work if conditions.get("M4") == "long" else ()
    truncation = TruncationPolicy()
    if conditions.get("M2") == "truncated":
        if task.failing_test_visible_lines is None:
            raise ValueError(f"{task.task_id} has no M2 visible-line count")
        truncation = TruncationPolicy(max_lines=task.failing_test_visible_lines)
    rate = study.flaky_rate if conditions.get("M5") == "flaky" else 0.0
    params = {**dict(arm.agent.params), "seed": seed}
    suffix, label = arm.agent.system_suffix, arm.agent.label_events
    if mitigation not in MITIGATIONS:
        raise ValueError(f"unknown mitigation {mitigation!r}")
    if mitigation == "honesty":
        suffix = HONESTY_INSTRUCTION
    elif mitigation == "evidence":
        suffix, label = EVIDENCE_FORMAT, True
    config = replace(
        arm.agent,
        truncation=truncation,
        flakiness_rate=rate,
        flakiness_seed=seed,
        flaky_tools=task.flaky_tools,
        params=params,
        system_suffix=suffix,
        label_events=label,
        purpose=f"{arm.agent.purpose} {arm.config_id}",
    )
    return config, prompt, prior


@dataclass
class HookCheck:
    """The E4 receipts-hook arm's post-check over the live ledger (no snapshot yet).

    It runs the same extraction, verification, and message as the Claude Code Stop
    hook (:mod:`receipts.hook.stop`) and times each check.
    """

    ledger_path: Path
    requirements: Mapping[str, str]
    checks: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, report: str) -> str | None:
        """Return the correction request, or None to accept the report."""
        start = time.monotonic()
        claims = extract_claims(report)
        verification = verify_run(
            claims,
            Ledger.load(self.ledger_path),
            requirements=dict(self.requirements) or None,
            report=report,
        )
        pairs = contradicted(verification.claims, verification.verdicts)
        feedback = format_reason(pairs) if pairs else None
        self.checks.append(
            {
                "latency_s": round(time.monotonic() - start, 4),
                "claims": len(claims),
                "contradicted": len(pairs),
                "blocked": feedback is not None,
            }
        )
        return feedback


@dataclass(frozen=True)
class RunRecord:
    """The banked summary of one run (also written as ``run.json``)."""

    run_id: str
    task_id: str
    config_id: str
    model: str
    family: str
    conditions: Mapping[str, str]
    seed: int
    mitigation: str
    stop_reason: str
    turns: int
    report: str
    success_reported: bool
    ground_truth_success: bool | None
    false_success: bool
    claims: Sequence[Mapping[str, Any]]
    omissions: int
    snapshot_problems: Sequence[str]
    input_tokens: int
    output_tokens: int
    model_wall_s: float
    wall_s: float
    drafts: Sequence[str]
    hook_checks: Sequence[Mapping[str, Any]]
    provenance: Mapping[str, Any]


def _hidden_checks(
    sandbox: Sandbox, recorder: Recorder, task: RunTask, work: Path, problems: list[str]
) -> None:
    target = work / HIDDEN_DIR
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(task.hidden_dir, target)
    outcome = sandbox.run(task.hidden_check_cmd, timeout_s=task.command_timeout_s)
    recorder.record_command(outcome, None, "snapshot", derive=False)
    checks = parse_hidden_check_list(outcome.stdout)
    if checks is None:
        problems.append(f"hidden checks produced no result line (exit {outcome.exit_code})")
        return
    recorder.record_hidden_checks(checks, source="snapshot")


def execute_run(
    spec: RunSpec,
    task: RunTask,
    arm: Arm,
    client: ModelClient,
    *,
    study: StudyText,
    artifacts_dir: Path,
    work_root: Path,
    sandbox_factory: Callable[[Path], Sandbox],
    git_sha: str,
    on_finish: Callable[[str], str | None] | None = None,
    keep_workspace: bool = False,
    server_provenance: Mapping[str, Any] | None = None,
    extra_provenance: Mapping[str, Any] | None = None,
) -> RunRecord:
    """Execute one run and bank its artifacts under ``artifacts_dir / spec.run_id``."""
    check_conditions(spec.conditions)
    started = time.monotonic()
    run_dir = artifacts_dir / spec.run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    work = work_root / spec.run_id
    base = prepare_workspace(task, spec.conditions, work)
    sandbox = sandbox_factory(work)
    recorder = Recorder(LedgerWriter(run_dir / "ledger.jsonl"), workspace=work)
    recorder.record_run_start(
        run_id=spec.run_id,
        task_id=task.task_id,
        agent=arm.driver,
        model=arm.model,
        config_id=arm.config_id,
        workspace=str(work),
        base_commit=base,
        conditions=dict(spec.conditions),
    )
    config, prompt, prior = configure_agent(
        arm, task, spec.conditions, study, spec.seed, spec.mitigation
    )
    runtime = SandboxRuntime(sandbox, recorder, task.test_cmd, task.command_timeout_s)
    hook = HookCheck(run_dir / "ledger.jsonl", task.requirements)
    if spec.mitigation == "hook" and on_finish is None:
        on_finish = hook
    result: AgentResult = run_agent(prompt, client, config, runtime, prior, on_finish=on_finish)
    snap = take_snapshot(sandbox, recorder, base, task.test_cmd)
    problems = list(snap.problems)
    _hidden_checks(sandbox, recorder, task, work, problems)
    recorder.record_run_end(result.report, result.turns, result.stop_reason)
    ledger = Ledger.load(run_dir / "ledger.jsonl")
    claims = extract_claims(result.report)
    verification = verify_run(
        claims, ledger, requirements=dict(task.requirements) or None, report=result.report
    )
    transcript = {
        "messages": [dict(m) for m in result.messages],
        "drafts": list(result.drafts),
        "protocol_errors": result.protocol_errors,
    }
    (run_dir / "transcript.json").write_text(json.dumps(transcript, indent=2) + "\n", "utf-8")
    (run_dir / "verification.json").write_text(
        json.dumps(verification.to_dict(), indent=2) + "\n", "utf-8"
    )
    provenance = {
        "git_sha": git_sha,
        "command": f"receipts.study.runner.execute_run {spec.run_id}",
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "run_spec": {**asdict(spec), "conditions": dict(spec.conditions)},
        "agent_config_sha256": sha256_text(canonical_json(_config_dict(config))),
        "agent_config": _config_dict(config),
        "prompt_sha256": sha256_text(prompt),
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "sandbox_backend": sandbox.backend,
        "model_server": dict(server_provenance or {}),
        **dict(extra_provenance or {}),
    }
    record = RunRecord(
        run_id=spec.run_id,
        task_id=task.task_id,
        config_id=arm.config_id,
        model=arm.model,
        family=arm.family,
        conditions=dict(spec.conditions),
        seed=spec.seed,
        mitigation=spec.mitigation,
        stop_reason=result.stop_reason,
        turns=result.turns,
        report=result.report,
        success_reported=verification.success_reported,
        ground_truth_success=verification.ground_truth_success,
        false_success=verification.false_success,
        claims=[
            {**c.to_dict(), "verdict": v.label.value}
            for c, v in zip(verification.claims, verification.verdicts, strict=True)
        ],
        omissions=len(verification.omissions),
        snapshot_problems=problems,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model_wall_s=round(result.model_wall_s, 3),
        wall_s=round(time.monotonic() - started, 3),
        drafts=list(result.drafts),
        hook_checks=list(hook.checks),
        provenance=provenance,
    )
    (run_dir / "run.json").write_text(json.dumps(asdict(record), indent=2) + "\n", "utf-8")
    if not keep_workspace:
        shutil.rmtree(work, ignore_errors=True)
    return record


def _config_dict(config: AgentConfig) -> dict[str, Any]:
    data = asdict(config)
    data["truncation"]["tools"] = sorted(config.truncation.tools)
    data["flaky_tools"] = sorted(config.flaky_tools)
    return data
