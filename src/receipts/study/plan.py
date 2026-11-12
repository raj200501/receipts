"""Study plans: the arms, the study-level manipulation text, and every planned run.

A plan is written to ``artifacts/studies/<study>/plan.json`` and committed before any
of its runs (for confirmatory studies, with the preregistration that cites it). Runs
are executed in plan order, grouped by model so the local server restarts as rarely
as possible, and a run whose ``run.json`` already exists is never re-run.

An exploratory plan may later gain one run per task in place of a run the runner
excluded (DECISIONS D71): :func:`amend_plan` appends the excluded run's planned spec
under a new id and records a :class:`PlanAmendment` (what the new run needs from the
model server, why, and the SHA-256 of the plan file before), and leaves every other
byte of the plan as it was. The excluded run stays planned under its own id and is
never attempted again. :func:`check_amendments` holds every amendment to D71's terms:
the added run is the excluded run's spec, on one slot with a window per slot above the
pinned one, and the plan without the amendment is, byte for byte, the plan the
amendment records the SHA-256 of, so nothing else in the plan changed with it.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, TypeGuard

from receipts.drivers.minimal_agent.loop import AgentConfig
from receipts.drivers.minimal_agent.protocol import ACTION_SCHEMA
from receipts.ledger.events import canonical_json, sha256_text
from receipts.study.spec import CONDITION_LEVELS, Arm, RunSpec, StudyText, check_conditions

#: Studies whose plan may gain a run after its runs began: the exploratory smoke study
#: (DECISIONS D71). A preregistered plan changes only through a dated preregistration
#: amendment, so the E1 and E4 plans are never amended here.
AMENDABLE_STUDIES: tuple[str, ...] = ("smoke",)

#: The decision that allows a plan amendment (DECISIONS D71), and the slots the model
#: server of a run an amendment added has: one.
AMENDMENT_DECISION = "D71"
AMENDMENT_SLOTS = 1

#: The planned-run fields an added run shares with the run it replaces (all but its id).
SAME_AS_REPLACED: tuple[str, ...] = (
    "study",
    "task_id",
    "config_id",
    "conditions",
    "seed",
    "mitigation",
)

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ServerRequirement:
    """What a run a plan amendment added needs from the model server (DECISIONS D71).

    Attributes:
        min_n_ctx_per_slot: The least context window per slot, in tokens: what one
            request's prompt and reply may take together. It is above
            ``pinned_n_ctx_per_slot``.
        max_parallel_slots: The most slots the server may run at once
            (:data:`AMENDMENT_SLOTS`, one).
        pinned_n_ctx_per_slot: The pinned window per slot of the run's model, which the
            amendment raises; every other run of the study is served with it.
    """

    min_n_ctx_per_slot: int
    max_parallel_slots: int
    pinned_n_ctx_per_slot: int

    def problems(self, n_ctx_per_slot: int, parallel_slots: int) -> list[str]:
        """How a server with ``n_ctx_per_slot`` tokens per slot on ``parallel_slots``
        slots falls short of this requirement (an empty list: it meets it). A window or
        slot count that is not a positive integer serves nothing."""
        if not (_positive_int(n_ctx_per_slot) and _positive_int(parallel_slots)):
            return [
                "a server needs a positive window per slot and at least one slot, not "
                f"{n_ctx_per_slot!r} tokens on {parallel_slots!r} slot(s)"
            ]
        found = []
        if n_ctx_per_slot < self.min_n_ctx_per_slot:
            found.append(
                f"it needs at least {self.min_n_ctx_per_slot} tokens per slot, not {n_ctx_per_slot}"
            )
        if parallel_slots > self.max_parallel_slots:
            found.append(
                f"it needs at most {self.max_parallel_slots} slot(s), not {parallel_slots}"
            )
        return found

    def describe(self) -> str:
        """The requirement in words."""
        return (
            f"at least {self.min_n_ctx_per_slot} tokens per slot (the pinned window is "
            f"{self.pinned_n_ctx_per_slot}) on at most {self.max_parallel_slots} slot(s)"
        )


@dataclass(frozen=True)
class PlanAmendment:
    """One run added to a plan after its runs began, in place of an excluded run.

    Attributes:
        run_id: The added run: the replaced run's planned spec under this id.
        replaces: The run the runner excluded; it stays planned and is never attempted
            again.
        server: What the added run needs from the model server.
        decision: The DECISIONS.md entry that allows the amendment
            (:data:`AMENDMENT_DECISION`).
        reason: Why the replaced run was excluded and what the added run changes.
        date: The day of the amendment (ISO 8601, ``YYYY-MM-DD``).
        plan_sha256_before: SHA-256 of the plan file's bytes before the amendment (the
            text :func:`plan_text` writes for :func:`plan_before` the amendment).
    """

    run_id: str
    replaces: str
    server: ServerRequirement
    decision: str
    reason: str
    date: str
    plan_sha256_before: str

    def to_json(self) -> dict[str, Any]:
        """The amendment as stored in ``plan.json`` (``amendments``)."""
        return asdict(self)


#: minimal-agent sampling defaults for local arms (seed is set per run).
LOCAL_PARAMS: Mapping[str, Any] = {
    "temperature": 0.3,
    "max_tokens": 1024,
    "response_format": {"type": "json_object", "schema": dict(ACTION_SCHEMA)},
}
"""Request parameters of every local arm (DECISIONS D39, D46): the action grammar keeps
each reply a syntactically valid action, and 1024 tokens fits a typical file write."""


def local_arm(config_id: str, model: str, family: str, max_turns: int = 16) -> Arm:
    """A minimal-agent arm served by the local backend."""
    agent = AgentConfig(
        backend="local",
        model=model,
        max_turns=max_turns,
        params=dict(LOCAL_PARAMS),
        purpose=f"minimal-agent {model}",
    )
    return Arm(config_id=config_id, driver="minimal-agent", model=model, family=family, agent=agent)


@dataclass(frozen=True)
class Plan:
    """A study plan.

    ``amendments`` lists the runs added after the plan's runs began, each in place of
    an excluded run (:func:`amend_plan`); a plan without any stores none.
    """

    study: str
    arms: Sequence[Arm]
    runs: Sequence[RunSpec]
    text: StudyText = field(default_factory=StudyText)
    notes: str = ""
    amendments: Sequence[PlanAmendment] = ()

    def arm(self, config_id: str) -> Arm:
        """The arm with ``config_id``."""
        for arm in self.arms:
            if arm.config_id == config_id:
                return arm
        raise KeyError(config_id)

    def amendment(self, run_id: str) -> PlanAmendment | None:
        """The amendment that added run ``run_id``; None for a run planned from the start."""
        for amendment in self.amendments:
            if amendment.run_id == run_id:
                return amendment
        return None

    def replaced(self) -> frozenset[str]:
        """The runs an amendment replaced: excluded runs, never attempted again."""
        return frozenset(amendment.replaces for amendment in self.amendments)

    def to_json(self) -> dict[str, Any]:
        """The plan as stored in ``plan.json``; ``amendments`` only when there are any,
        so a plan without them is stored exactly as before amendments existed."""
        data: dict[str, Any] = {
            "schema": "receipts.study-plan/1",
            "study": self.study,
            "notes": self.notes,
            "text": asdict(self.text),
            "arms": [_arm_json(a) for a in self.arms],
            "runs": [{**asdict(r), "conditions": dict(r.conditions)} for r in self.runs],
        }
        if self.amendments:
            data["amendments"] = [amendment.to_json() for amendment in self.amendments]
        return data

    def sha256(self) -> str:
        """Content hash of the plan (cited by preregistrations and run provenance)."""
        return sha256_text(canonical_json(self.to_json()))

    def ordered(self) -> list[RunSpec]:
        """Runs grouped by model (in first-appearance order), plan order within a model."""
        order: dict[str, int] = {}
        for run in self.runs:
            order.setdefault(self.arm(run.config_id).model, len(order))
        return sorted(
            self.runs,
            key=lambda r: (order[self.arm(r.config_id).model], self.runs.index(r)),
        )


def _arm_json(arm: Arm) -> dict[str, Any]:
    agent = asdict(arm.agent)
    agent["truncation"]["tools"] = sorted(arm.agent.truncation.tools)
    agent["flaky_tools"] = sorted(arm.agent.flaky_tools)
    return {
        "config_id": arm.config_id,
        "driver": arm.driver,
        "model": arm.model,
        "family": arm.family,
        "agent": agent,
    }


def _arm_from_json(data: Mapping[str, Any]) -> Arm:
    agent = dict(data["agent"])
    trunc = agent.pop("truncation")
    from receipts.drivers.minimal_agent.boundary import TruncationPolicy

    agent["truncation"] = TruncationPolicy(
        max_lines=trunc.get("max_lines"), tools=frozenset(trunc.get("tools", ()))
    )
    if "flaky_tools" in agent:
        agent["flaky_tools"] = frozenset(agent["flaky_tools"])
    return Arm(
        config_id=str(data["config_id"]),
        driver=str(data["driver"]),
        model=str(data["model"]),
        family=str(data["family"]),
        agent=AgentConfig(**agent),
    )


def _positive_int(value: object) -> TypeGuard[int]:
    """True for an int (not a bool) of at least 1."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


#: The fields of a stored server requirement (``amendments[].server``).
SERVER_FIELDS: tuple[str, ...] = (
    "min_n_ctx_per_slot",
    "max_parallel_slots",
    "pinned_n_ctx_per_slot",
)


def _amendment_from_json(data: object) -> PlanAmendment:
    """One record of ``plan.json``'s ``amendments``.

    Raises:
        ValueError: The record is not an object with every :class:`PlanAmendment`
            field, or its server requirement is not three positive integers.
    """
    names = ("run_id", "replaces", "server", "decision", "reason", "date", "plan_sha256_before")
    if not isinstance(data, dict) or any(name not in data for name in names):
        raise ValueError(f"a plan amendment must be an object with {', '.join(names)}")
    server = data["server"]
    limits = SERVER_FIELDS
    if not isinstance(server, dict) or not all(_positive_int(server.get(k)) for k in limits):
        raise ValueError(
            f"plan amendment {data['run_id']!r}: its server requirement must give "
            f"{' and '.join(limits)} as positive integers"
        )
    text = {name: data[name] for name in names if name != "server"}
    if not all(isinstance(value, str) for value in text.values()):
        raise ValueError(f"plan amendment {data['run_id']!r}: its fields must be text")
    return PlanAmendment(
        server=ServerRequirement(
            min_n_ctx_per_slot=server["min_n_ctx_per_slot"],
            max_parallel_slots=server["max_parallel_slots"],
            pinned_n_ctx_per_slot=server["pinned_n_ctx_per_slot"],
        ),
        **text,
    )


def load_plan(path: Path) -> Plan:
    """Read ``plan.json``.

    Raises:
        ValueError: Its ``amendments`` are not a list of well-formed records.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    runs = [
        RunSpec(
            run_id=str(r["run_id"]),
            study=str(r["study"]),
            task_id=str(r["task_id"]),
            config_id=str(r["config_id"]),
            conditions={str(k): str(v) for k, v in r["conditions"].items()},
            seed=int(r["seed"]),
            mitigation=str(r.get("mitigation", "none")),
        )
        for r in data["runs"]
    ]
    records = data.get("amendments", [])
    if not isinstance(records, list):
        raise ValueError(f"{path}: amendments must be a list of plan amendment records")
    return Plan(
        study=str(data["study"]),
        arms=[_arm_from_json(a) for a in data["arms"]],
        runs=runs,
        text=StudyText(**data.get("text", {})),
        notes=str(data.get("notes", "")),
        amendments=tuple(_amendment_from_json(record) for record in records),
    )


def plan_text(plan: Plan) -> str:
    """The exact text :func:`write_plan` writes for ``plan`` (no checks)."""
    return json.dumps(plan.to_json(), indent=2, sort_keys=True) + "\n"


def plan_before(plan: Plan, count: int = 0) -> Plan:
    """``plan`` as it was before its amendments from number ``count`` on (all of them by
    default): without those amendment records and the runs they added."""
    later = {amendment.run_id for amendment in plan.amendments[count:]}
    return replace(
        plan,
        runs=[run for run in plan.runs if run.run_id not in later],
        amendments=tuple(plan.amendments[:count]),
    )


def check_amendments(plan: Plan, pinned_windows: Mapping[str, int] | None = None) -> None:
    """Raise ValueError unless every amendment of ``plan`` holds (DECISIONS D71).

    The plan's study is one of :data:`AMENDABLE_STUDIES`. Each amendment adds a planned
    run in place of another planned run, and the two share every planned field but the
    run id (:data:`SAME_AS_REPLACED`): the same task, arm, conditions, seed, and
    mitigation. It is allowed by :data:`AMENDMENT_DECISION`, and its server requirement
    keeps that decision's terms: positive integers, a window per slot above the pinned
    one it records, on :data:`AMENDMENT_SLOTS` slot. With ``pinned_windows`` (each
    pinned model's window per slot), the recorded pinned window must be that of the
    added run's model. Its reason and date are given (the date in ISO 8601). No task is
    amended more than once: since an added run and the run it replaces share their
    task, no run is then added or replaced twice, and an added run is never replaced in
    turn.

    The runs the amendments added are the plan's last runs, in the order of the
    amendments, and each amendment records the SHA-256 of the plan before it: the text
    :func:`plan_text` writes for :func:`plan_before` it. So a planned run, an arm, or any
    other part of the plan that changed after an amendment, or a run added outside one,
    is found.
    """
    if not plan.amendments:
        return
    if plan.study not in AMENDABLE_STUDIES:
        raise ValueError(
            f"the {plan.study} plan is not amended after its runs began: only "
            f"{', '.join(AMENDABLE_STUDIES)} (DECISIONS D71); a preregistered plan changes "
            "only through a preregistration amendment"
        )
    planned = {run.run_id: run for run in plan.runs}
    tasks: set[str] = set()
    for amendment in plan.amendments:
        name = f"plan amendment {amendment.run_id}"
        added, replaced = planned.get(amendment.run_id), planned.get(amendment.replaces)
        if added is None or replaced is None:
            missing = amendment.run_id if added is None else amendment.replaces
            raise ValueError(f"{name}: {missing} is not a planned run")
        if amendment.run_id == amendment.replaces:
            raise ValueError(f"{name}: a run cannot be added in place of itself")
        if any(getattr(added, f) != getattr(replaced, f) for f in SAME_AS_REPLACED):
            raise ValueError(
                f"{name}: {amendment.run_id} is not the planned run {amendment.replaces} "
                f"under a new id (they must share {', '.join(SAME_AS_REPLACED)})"
            )
        if amendment.decision != AMENDMENT_DECISION:
            raise ValueError(
                f"{name}: a plan amendment is allowed by {AMENDMENT_DECISION} only, not "
                f"{amendment.decision!r}"
            )
        server = amendment.server
        if not all(_positive_int(getattr(server, limit)) for limit in SERVER_FIELDS):
            raise ValueError(
                f"{name}: the server requirement needs a positive window per slot, a "
                "positive number of slots, and the positive pinned window it raises"
            )
        if server.min_n_ctx_per_slot <= server.pinned_n_ctx_per_slot:
            raise ValueError(
                f"{name}: {server.min_n_ctx_per_slot} tokens per slot does not raise the "
                f"pinned window of {server.pinned_n_ctx_per_slot} ({AMENDMENT_DECISION})"
            )
        if server.max_parallel_slots != AMENDMENT_SLOTS:
            raise ValueError(
                f"{name}: the added run's server has one slot ({AMENDMENT_DECISION}), not "
                f"at most {server.max_parallel_slots}"
            )
        if pinned_windows is not None:
            try:
                model = plan.arm(added.config_id).model
            except KeyError as exc:
                raise ValueError(f"{name}: {added.config_id} is not an arm of the plan") from exc
            pinned = pinned_windows.get(model)
            if pinned is None:
                raise ValueError(f"{name}: {model} is not a pinned local model")
            if pinned != server.pinned_n_ctx_per_slot:
                raise ValueError(
                    f"{name}: it records a pinned window of {server.pinned_n_ctx_per_slot} "
                    f"tokens per slot, and {model} has a pinned window of {pinned}"
                )
        if not amendment.reason.strip():
            raise ValueError(f"{name}: the amendment needs a reason")
        try:
            dt.date.fromisoformat(amendment.date)
        except ValueError as exc:
            raise ValueError(f"{name}: {amendment.date!r} is not an ISO 8601 date") from exc
        if not _SHA256_HEX.fullmatch(amendment.plan_sha256_before):
            raise ValueError(
                f"{name}: plan_sha256_before must be the plan file's SHA-256 before the "
                "amendment (64 lowercase hex digits)"
            )
        if added.task_id in tasks:
            raise ValueError(
                f"{name}: task {added.task_id} is amended more than once (one new run per "
                "task, DECISIONS D71)"
            )
        tasks.add(added.task_id)
    tail = [run.run_id for run in plan.runs[len(plan.runs) - len(plan.amendments) :]]
    if tail != [amendment.run_id for amendment in plan.amendments]:
        raise ValueError(
            "the runs that plan amendments added must be the plan's last runs, in the "
            "order of the amendments, so a run was added outside an amendment"
        )
    for index, amendment in enumerate(plan.amendments):
        if sha256_text(plan_text(plan_before(plan, index))) != amendment.plan_sha256_before:
            raise ValueError(
                f"plan amendment {amendment.run_id}: its plan_sha256_before is not the "
                "SHA-256 of the plan as it was before the amendment (the plan without it "
                "and any later amendment, as write_plan writes it), so the plan changed "
                "outside its amendments"
            )


def write_plan(path: Path, plan: Plan) -> None:
    """Write ``plan.json`` after validating every run's arm and conditions and every
    amendment (:func:`check_amendments`)."""
    ids = {a.config_id for a in plan.arms}
    seen: set[str] = set()
    for run in plan.runs:
        if run.config_id not in ids:
            raise ValueError(f"run {run.run_id} names unknown arm {run.config_id}")
        if run.run_id in seen:
            raise ValueError(f"duplicate run id {run.run_id}")
        seen.add(run.run_id)
        check_conditions(run.conditions)
    check_amendments(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan_text(plan), encoding="utf-8")


def amendment_cache(study: str, run_id: str) -> str:
    """Where the model responses of the run ``run_id`` that an amendment added are
    cached, relative to the checkout: a directory of its own (``runs/<study>/cache/<run
    id>``), so no reply comes from the shared cache of runs made on another server."""
    return f"runs/{study}/cache/{run_id}"


def amendment_run_id(replaces: str, server: ServerRequirement) -> str:
    """The id of the run added in place of ``replaces``: ``<replaces>-ctx<window>``, the
    window in units of 1024 tokens when it is a multiple of 1024 (``-ctx32k``)."""
    window = server.min_n_ctx_per_slot
    return f"{replaces}-ctx{window // 1024}k" if window % 1024 == 0 else f"{replaces}-ctx{window}"


def amend_plan(
    plan: Plan,
    replaces: str,
    server: ServerRequirement,
    *,
    decision: str,
    reason: str,
    date: str,
) -> Plan:
    """``plan`` with one run added in place of the excluded run ``replaces`` (DECISIONS D71).

    The added run is ``replaces``'s planned spec (study, task, arm, conditions, seed,
    and mitigation) under the id :func:`amendment_run_id` gives, after every planned run;
    it needs ``server`` from the model server. The amendment record keeps the decision,
    the reason, the date, and ``plan_sha256_before``, the SHA-256 of the text
    :func:`write_plan` writes for ``plan`` (the plan file's bytes before the
    amendment). Every other part of the plan stays as it was, and ``replaces`` stays
    planned under its own id. Whether ``replaces`` was excluded is the caller's to check
    (``tools/amend_plan.py`` reads the runner's failure log).

    Raises:
        ValueError: The study is not amendable, ``replaces`` is not a planned run, its
            task already has an amendment (one new run per task), the new id is already
            planned, or the amendment does not hold (:func:`check_amendments`).
    """
    planned = {run.run_id: run for run in plan.runs}
    old = planned.get(replaces)
    if old is None:
        raise ValueError(f"{replaces} is not a planned run of the {plan.study} plan")
    for earlier in plan.amendments:
        if planned[earlier.run_id].task_id == old.task_id:
            raise ValueError(
                f"task {old.task_id} already has an amendment ({earlier.run_id} in place of "
                f"{earlier.replaces}); a task gets one new run only (DECISIONS D71)"
            )
    run_id = amendment_run_id(replaces, server)
    if run_id in planned:
        raise ValueError(f"{run_id} is already planned")
    record = PlanAmendment(
        run_id=run_id,
        replaces=replaces,
        server=server,
        decision=decision,
        reason=reason,
        date=date,
        plan_sha256_before=sha256_text(plan_text(plan)),
    )
    amended = replace(
        plan,
        runs=[*plan.runs, replace(old, run_id=run_id)],
        amendments=(*plan.amendments, record),
    )
    check_amendments(amended)
    return amended


def _flag(command: Sequence[str], name: str) -> str | None:
    """The value after ``name`` in a command line, or None when it is not there."""
    for index, word in enumerate(command[:-1]):
        if word == name:
            return command[index + 1]
    return None


#: What the live model server reported serving, as ``tools/run_study.py`` records it
#: (``provenance.model_server.reported``, from :meth:`LocalServer.confirm_serving`): the
#: window per slot, the slots, and the model file of llama.cpp's ``GET /props``.
REPORTED_FIELDS: tuple[str, ...] = ("n_ctx_per_slot", "total_slots", "model_path")


def server_record_problems(server: ServerRequirement, record: object) -> list[str]:
    """How a run record's model server (``provenance.model_server``, as
    ``tools/run_study.py`` records it) fails ``server`` or disagrees with itself; an empty
    list when it meets the requirement and every field agrees (DECISIONS D71).

    The server must be llama.cpp's and record its window per slot (``n_ctx_per_slot``)
    and its slots (``parallel_slots``) as positive integers that meet ``server``; its
    command line must be the one its SHA-256 names and give the same window and slots
    (``--ctx-size`` is the window times the slots, with ``--parallel`` slots), as must
    ``ctx_size``; it must record the pinned window ``server`` raises
    (``n_ctx_per_slot_default``) and say that it did not serve it
    (``n_ctx_per_slot_is_default``); and what the live server reported serving
    (``reported``: :data:`REPORTED_FIELDS`) must be that window, those slots, and the
    model file of its command line. So a run made on a smaller window, a record edited in
    one field only, or a run served by another server than the one it started, is found.
    """
    if not isinstance(record, Mapping):
        return ["the run records no model server (provenance.model_server)"]
    window, slots = record.get("n_ctx_per_slot"), record.get("parallel_slots")
    if not (_positive_int(window) and _positive_int(slots)):
        return [
            "the model server does not record its window per slot and its slots as positive "
            "integers (n_ctx_per_slot, parallel_slots)"
        ]
    found = server.problems(window, slots)
    engine = record.get("engine")
    if engine != "llama.cpp":
        return [
            *found,
            f"the model server's engine is {engine!r}, and a run an amendment added is served "
            "by llama.cpp, whose server reports the window per slot and the slots it serves",
        ]
    command = record.get("server_command")
    if not (isinstance(command, list) and all(isinstance(word, str) for word in command)):
        return [*found, "the model server records no command line (server_command)"]
    if sha256_text(" ".join(command)) != record.get("server_command_sha256"):
        found.append("the server command is not the one its SHA-256 (server_command_sha256) names")
    for name, value in {"--ctx-size": str(window * slots), "--parallel": str(slots)}.items():
        if _flag(command, name) != value:
            found.append(
                f"the server command gives {name} {_flag(command, name)}, not the {value} that "
                f"{window} tokens per slot on {slots} slot(s) take"
            )
    if record.get("ctx_size") != window * slots:
        found.append(
            f"ctx_size {record.get('ctx_size')!r} is not the {window * slots} tokens it serves"
        )
    default = record.get("n_ctx_per_slot_default")
    if default != server.pinned_n_ctx_per_slot:
        found.append(
            f"the run records the pinned window {default!r}, and its amendment raises the "
            f"pinned window of {server.pinned_n_ctx_per_slot} tokens per slot "
            "(n_ctx_per_slot_default)"
        )
    elif record.get("n_ctx_per_slot_is_default") is not (window == default):
        found.append(
            f"n_ctx_per_slot_is_default does not say whether {window} tokens per slot is the "
            f"pinned window of {default}"
        )
    reported = record.get("reported")
    if not isinstance(reported, Mapping):
        found.append(
            "the run records nothing the live server reported serving (reported), so the "
            "server that answered is not known to be the one it started"
        )
        return found
    expected = {
        "n_ctx_per_slot": window,
        "total_slots": slots,
        "model_path": _flag(command, "--model"),
    }
    differing = [
        f"{name} {reported.get(name)!r}, not {value!r}"
        for name, value in expected.items()
        if reported.get(name) != value or isinstance(reported.get(name), bool)
    ]
    if differing:
        found.append(f"the live server reports {'; '.join(differing)} (reported)")
    return found


def run_record_problems(plan: Plan, record: Mapping[str, Any]) -> list[str]:
    """How a banked run record (``run.json``) was not made as ``plan`` plans it; an empty
    list when it was (DECISIONS D71).

    The run is a planned run that no amendment replaced (an excluded run stays excluded
    and is never banked); ``run.json`` records the planned task and arm, the planned
    arm's model, and, in its provenance, the planned run spec. A run an amendment added
    also records that amendment (``provenance.plan_amendment``), a model server that
    meets its requirement (:func:`server_record_problems`), its own response cache
    (``provenance.response_cache``, :func:`amendment_cache`), that the code that ran is
    its commit (a verified snapshot of ``git_sha``, or a working tree with no
    uncommitted change), and a sandbox that hid the checkout (``provenance.sandbox``,
    DECISIONS D67).
    """
    run_id = record.get("run_id")
    spec = next((run for run in plan.runs if run.run_id == run_id), None)
    if spec is None:
        return [f"{run_id!r} is not a planned run of the {plan.study} plan"]
    if spec.run_id in plan.replaced():
        return [f"{spec.run_id} was replaced by a plan amendment, so it stays excluded"]
    found = []
    if record.get("task_id") != spec.task_id:
        found.append(f"run.json records task {record.get('task_id')!r}, not {spec.task_id}")
    if record.get("config_id") != spec.config_id:
        found.append(f"run.json records arm {record.get('config_id')!r}, not {spec.config_id}")
    arm = next((arm for arm in plan.arms if arm.config_id == spec.config_id), None)
    if arm is None:
        found.append(f"the plan has no arm {spec.config_id} for its run {spec.run_id}")
    elif record.get("model") != arm.model:
        found.append(
            f"run.json records model {record.get('model')!r}, not {arm.model}, the model of "
            f"its planned arm {spec.config_id}"
        )
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        return [*found, "run.json has no provenance"]
    if provenance.get("run_spec") != {**asdict(spec), "conditions": dict(spec.conditions)}:
        found.append("run.json does not record the planned run spec (provenance.run_spec)")
    amendment = plan.amendment(spec.run_id)
    if amendment is not None:
        if provenance.get("plan_amendment") != amendment.to_json():
            found.append(
                f"run.json does not record the plan amendment that added it "
                f"({amendment.decision}, provenance.plan_amendment)"
            )
        found += server_record_problems(amendment.server, provenance.get("model_server"))
        cache = amendment_cache(plan.study, spec.run_id)
        if provenance.get("response_cache") != cache:
            found.append(
                f"run.json records the response cache {provenance.get('response_cache')!r}, "
                f"not its own {cache}, so its replies may come from runs made on another "
                "server (provenance.response_cache)"
            )
        code = provenance.get("code")
        snapshot = (
            code == "snapshot"
            and provenance.get("snapshot_verified") is True
            and provenance.get("snapshot_of") == provenance.get("git_sha")
        )
        clean = code == "working tree" and provenance.get("uncommitted_at_start") == []
        if not (snapshot or clean):
            found.append(
                "run.json does not record that the code that ran is its commit (a verified "
                "snapshot of git_sha, or a working tree with no uncommitted change)"
            )
        sandbox = provenance.get("sandbox")
        if not (isinstance(sandbox, Mapping) and sandbox.get("checkout_hidden") is True):
            found.append(
                "run.json does not record a sandbox that hid the checkout (provenance.sandbox, "
                "DECISIONS D67)"
            )
    return found


def smoke_plan(study: str, task_ids: Iterable[str], arm: Arm, seed: int = 0) -> Plan:
    """One run per task for one arm, with no manipulation (G6 smoke runs)."""
    runs = [
        RunSpec(f"{study}-{task_id}-{arm.config_id}", study, task_id, arm.config_id, {}, seed)
        for task_id in task_ids
    ]
    return Plan(study=study, arms=[arm], runs=runs, notes="smoke runs: no manipulation")


def half_fraction_cells() -> list[dict[str, str]]:
    """The 16 cells of the 2^(5-1) design with defining relation I = M1 M2 M3 M4 M5.

    Resolution V: every main effect and two-way interaction is estimable, aliased only
    with three-way or higher interactions.
    """
    factors = list(CONDITION_LEVELS)
    cells = []
    for code in range(16):
        bits = [(code >> i) & 1 for i in range(4)]
        bits.append((sum(bits) + 1) % 2)  # makes the product of the +/-1 codes equal +1
        cells.append({f: CONDITION_LEVELS[f][b] for f, b in zip(factors, bits, strict=True)})
    return cells


def factorial_plan(
    study: str,
    task_ids: Sequence[str],
    arms: Sequence[Arm],
    replicates: int,
    seed: int,
    text: StudyText,
) -> Plan:
    """Every arm gets the same ``replicates`` x 16 runs: identical tasks, cells, seeds.

    Tasks are assigned to cells by a seeded shuffle that balances tasks across cells as
    evenly as possible; the resulting (task, cell, seed) list is shared by every arm, so
    agents are compared on identical work.
    """
    rng = random.Random(seed)
    cells = half_fraction_cells() * replicates
    tasks = [task_ids[i % len(task_ids)] for i in range(len(cells))]
    rng.shuffle(tasks)
    seeds = [rng.randrange(1, 2**31) for _ in cells]
    runs = []
    for arm in arms:
        for i, (task, cell, run_seed) in enumerate(zip(tasks, cells, seeds, strict=True)):
            run_id = f"{study}-{i:03d}-{arm.config_id}"
            runs.append(RunSpec(run_id, study, task, arm.config_id, dict(cell), run_seed))
    return Plan(study=study, arms=list(arms), runs=runs, text=text)
