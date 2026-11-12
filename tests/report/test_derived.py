"""Derived artifacts and their re-derivation (``receipts.report.derived``; gates G7 to G10,
DECISIONS D56 and D65).

The run records, rows, ledgers, transcripts, judge replies, and results here are
SYNTHETIC test fixtures, never model output. The scripts are the real ones
(``tools/smoke_outcomes.py``, ``tools/analyze.py``, ``tools/run_judges.py``,
``tools/analyze_e4.py``) copied into throwaway repositories (``tests/report/studies.py``),
so the checks run the same derivations as ``make freshness``, ``make reproduce``, and
the gates do on the real artifacts.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import analyze
import freshness
import report
import run_judges
from receipts.evaluation import e3 as e3_judges
from receipts.report import derived
from receipts.report.derived import (
    ABS_TOL,
    DERIVED,
    DIAGNOSTIC,
    REL_TOL,
    Derived,
    DerivedError,
    agree,
    arguments,
    check,
    comparable,
    differences,
    recorded_arguments,
    refresh,
    same,
)
from receipts.study import results as e1_analysis
from receipts.study import results_e4
from tests.repo_tools.test_smoke_outcomes import record
from tests.report import studies

ROOT = Path(__file__).resolve().parents[2]
ITEMS = {item.path: item for item in DERIVED}
SMOKE = ITEMS["artifacts/exploratory/smoke_outcomes.json"]
E1, E2, E3, E4 = (ITEMS[rel] for rel in (studies.E1, studies.E2, studies.E3, studies.E4))
RUNS = "artifacts/studies/smoke/runs"
Commit = Callable[[Path, str], str]
Change = Callable[[dict[str, Any]], None]


def bank_run(root: Path, rec: dict[str, Any]) -> str:
    """Write one synthetic run record where the smoke study banks it; returns its path."""
    rel = f"{RUNS}/{rec['run_id']}/run.json"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec), encoding="utf-8")
    return rel


def repo(root: Path, commit: Commit) -> Path:
    """A repository holding the real summary script and two banked synthetic runs."""
    (root / "tools").mkdir()
    shutil.copy(ROOT / "tools" / "smoke_outcomes.py", root / "tools" / "smoke_outcomes.py")
    bank_run(root, record("smoke-py-a", success_reported=True, done=False))
    bank_run(root, record("smoke-ts-b", success_reported=False, done=False))
    commit(root, "start")
    return root


def script(root: Path, rel: str, body: str) -> None:
    """A SYNTHETIC stand-in script at ``rel`` that runs ``body`` with ``out``, the path
    after ``--out``, bound."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "import os, pathlib, sys\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n" + body,
        encoding="utf-8",
    )


# ---------------------------------------------------------------- the registry


def test_every_derived_artifact_is_registered_with_how_to_derive_it() -> None:
    assert [(i.path, i.script, i.inputs, i.args, i.recorded, i.extra) for i in DERIVED] == [
        (SMOKE.path, "tools/smoke_outcomes.py", f"{RUNS}/*/run.json", (), False, ()),
        ("artifacts/e1/results.json", "tools/analyze.py", None, ("e1",), True, ()),
        ("artifacts/e2/mechanism.json", "tools/analyze.py", None, ("e2",), True, ()),
        ("artifacts/e3/judges.json", "tools/run_judges.py", None, (), True, ("--rescore",)),
        ("artifacts/e4/results.json", "tools/analyze_e4.py", None, (), True, ()),
    ]
    # make report writes only the smoke summary; each study artifact has its own command.
    assert [i.path for i in DERIVED if i.rewritable] == [SMOKE.path]
    assert isinstance(SMOKE, Derived)
    assert E3.command == "python tools/run_judges.py --rescore"
    assert SMOKE.remedy == "run make report"
    assert E1.remedy == (
        "derive it again with python tools/analyze.py e1 with the arguments its provenance "
        "records and commit it"
    )
    volatile = {"git_sha": "a", "created": "t", "command": "c", "environment": {"python": "3"}}
    art = {"summary": 1, "provenance": {**volatile, "x": 2}}
    assert comparable(art) == {"summary": 1, "provenance": {"x": 2}}


#: The inputs tools/analyze.py reads, by option, at their default paths: the banked ones.
ANALYZE_INPUTS = {
    "--runs": analyze.RUNS,
    "--prereg": e1_analysis.PREREG_E1,
    "--plan": analyze.PLAN,
    "--seeded": analyze.SEEDED,
    "--failures": analyze.FAILURES,
    "--run-dirs": analyze.RUN_DIRS,
}


def test_a_re_derivation_re_uses_only_the_options_each_artifact_lists() -> None:
    """Review BV1 and BV2 of the B5 fix: a recorded option that names an input may only
    name its banked default, and an option that makes a partial or exploratory run of a
    study artifact's default path is not re-used at all."""
    fixed = {i.path: {o.name: o.fixed for o in i.options if o.fixed is not None} for i in DERIVED}
    assert fixed == {
        SMOKE.path: {},
        E1.path: ANALYZE_INPUTS,
        E2.path: ANALYZE_INPUTS,
        E3.path: {"--prereg": e3_judges.PREREG_PATH, "--replies": run_judges.REPLIES},
        E4.path: {"--prereg": results_e4.PREREG_PATH},
    }
    free = {i.path: sorted(o.name for o in i.options if o.fixed is None) for i in DERIVED}
    assert free == {
        SMOKE.path: [],
        E1.path: ["--n-boot"],
        E2.path: [],
        E3.path: [
            "--cache",
            "--confirmatory",
            "--engine",
            "--judges",
            "--port",
            "--request-timeout",
            "--rescore",
            "--threads",
        ],
        E4.path: ["--confirmatory"],
    }
    flags = {i.path: sorted(o.name for o in i.options if o.flag) for i in DERIVED}
    assert flags == {
        SMOKE.path: [],
        E1.path: [],
        E2.path: [],
        E3.path: ["--confirmatory", "--rescore"],
        E4.path: ["--confirmatory"],
    }
    # Each is an option its script defines, a flag as a store_true option.
    for item in DERIVED:
        source = (ROOT / item.script).read_text(encoding="utf-8")
        for option in item.options:
            defined = f'"{option.name}", action="store_true"' if option.flag else f'"{option.name}"'
            assert defined in source, (item.script, option.name)


def test_values_are_compared_as_json_values() -> None:
    assert not same(1, True) and not same(1, 1.0) and not same(0, None)
    assert same({"a": [1, {"b": 2.5}]}, {"a": [1, {"b": 2.5}]})
    assert same(float("nan"), float("nan"))  # == would call these different
    a = {"a": {"b": 1, "c": [1, 2], "e": True}, "same": [0]}
    b = {"a": {"b": 2, "c": [1, 3], "e": 1}, "d": 0, "same": [0]}
    assert differences(a, b) == "a.b, a.c.1, a.e, d"  # true is not 1; equal lists drop out
    assert differences({"a": [1, 2]}, {"a": [1]}) == "a"  # a list of another length
    many = {f"k{n}": n for n in range(7)}
    assert differences(many, {}) == "k0, k1, k2, k3, k4, and 2 more"


def test_floats_agree_within_the_tolerance_and_every_other_value_exactly() -> None:
    """Review F1 of the B5 fix: another BLAS kernel, numpy, or scipy moves the last digits
    of a mixed-model fit (the values below are such pairs, measured on the SYNTHETIC E1
    and E4 studies), so a float agrees within REL_TOL or ABS_TOL; a string, a boolean,
    null, and an integer (a count) agree only exactly, and 1 is not 1.0."""
    assert agree(0.3990620563557907, 0.3990620563557368)  # another kernel
    assert agree(-5.443148281544655e-13, 6.022759074388995e-13)  # a sign flip at 1e-12
    assert agree(-0.04747244321341861, -0.047472412012032034)  # Python 3.12, numpy 2.5
    assert agree(-0.7254312571563394, -0.7254310647669295)
    assert not agree(0.399, 0.3994)  # a value typed in at the fourth significant digit
    assert not agree({"odds_ratio": 0.4}, {"odds_ratio": 0.8})
    big = 148.0
    assert agree(big, big * (1 + REL_TOL / 2)) and not agree(big, big * (1 + 2 * REL_TOL))
    assert agree(0.0, ABS_TOL / 2) and not agree(0.0, 2 * ABS_TOL)
    assert agree(float("nan"), float("nan")) and not agree(float("nan"), 1.0)
    assert agree(float("inf"), float("inf")) and not agree(float("inf"), -float("inf"))
    assert not agree(13, 14) and not agree(1, 1.0) and not agree(True, False)
    assert not agree("a", "b") and not agree(None, 0.0) and not agree([0.1], [0.1, 0.1])
    # An optimizer's iteration count says how a fit got there, not what it found.
    assert agree({"glmm": {"iterations": 13}}, {"glmm": {"iterations": 14}})
    assert not agree({"glmm": {"iterations": 13}}, {"glmm": {}})
    assert not agree({"glmm": {"iterations": 13}}, {"glmm": {"iterations": "13"}})
    assert not agree({"glmm": {"iterations": True}}, {"glmm": {"iterations": 1}})
    assert sorted(DIAGNOSTIC) == ["iterations"]
    a = {"a": 0.4, "b": 1.0, "c": {"iterations": 3, "n": 1}}
    b = {"a": 0.8, "b": 1.0 + 1e-12, "c": {"iterations": 4, "n": 2}}
    assert differences(a, b) == "a, c.n"


# ---------------------------------------------------------------- recorded arguments

ACCEPTED = [
    pytest.param(E1, "python tools/analyze.py e1", ["e1"], id="e1-defaults"),
    pytest.param(
        E1,
        "python tools/analyze.py e1 --n-boot 10 --out artifacts/e1/results.json",
        ["e1", "--n-boot", "10"],
        id="e1-out-dropped",
    ),
    pytest.param(
        E1,
        "python3 tools/analyze.py e1 --out=/tmp/x.json --n-boot 10",
        ["e1", "--n-boot", "10"],
        id="out-with-equals-dropped-even-absolute",
    ),
    pytest.param(E1, "python tools/analyze.py e1 --ou /tmp/x.json", ["e1"], id="out-abbreviated"),
    pytest.param(
        E2,
        "python tools/analyze.py e2 --runs artifacts/e1/runs.jsonl",
        ["e2", "--runs", "artifacts/e1/runs.jsonl"],
        id="e2-banked-rows-named",
    ),
    pytest.param(
        E2,
        "python tools/analyze.py e2 " + " ".join(f"{k}={v}" for k, v in ANALYZE_INPUTS.items()),
        ["e2", *(f"{k}={v}" for k, v in ANALYZE_INPUTS.items())],
        id="e2-every-banked-input-named",
    ),
    pytest.param(
        E3,
        "python tools/run_judges.py --prereg prereg/0003-e3-judges.md --confirmatory",
        ["--prereg", "prereg/0003-e3-judges.md", "--confirmatory", "--rescore"],
        id="e3-rescore-added",
    ),
    pytest.param(
        E3,
        "python tools/run_judges.py --rescore --replies artifacts/e3/replies.jsonl",
        ["--rescore", "--replies", "artifacts/e3/replies.jsonl"],
        id="e3-a-re-score-of-the-banked-replies",
    ),
    pytest.param(
        E3,
        "python tools/run_judges.py --judges=granite8b-transcript,qwen7b-transcript "
        "--threads 4 --port 8091 --engine llama.cpp --request-timeout 600 --cache runs/c2",
        [
            "--judges=granite8b-transcript,qwen7b-transcript",
            "--threads",
            "4",
            "--port",
            "8091",
            "--engine",
            "llama.cpp",
            "--request-timeout",
            "600",
            "--cache",
            "runs/c2",
            "--rescore",
        ],
        id="e3-every-judge-and-server-settings",
    ),
    pytest.param(E4, "python tools/analyze_e4.py", [], id="e4-defaults"),
    pytest.param(
        E4,
        "python tools/analyze_e4.py --confirmatory --prereg prereg/0002-e4-mitigation.md",
        ["--confirmatory", "--prereg", "prereg/0002-e4-mitigation.md"],
        id="e4-confirmatory",
    ),
]


@pytest.mark.parametrize(("item", "command", "expected"), ACCEPTED)
def test_a_recorded_command_gives_the_arguments_of_the_re_derivation(
    tmp_path: Path, item: Derived, command: str, expected: list[str]
) -> None:
    assert arguments(tmp_path, item, {"provenance": {"command": command}}) == expected


REFUSED = [
    pytest.param(E1, None, "records no command", id="no-command"),
    pytest.param(E1, "  ", "records no command", id="blank"),
    pytest.param(E1, "python tools/analyze_e4.py e1", "does not run tools/analyze.py", id="script"),
    pytest.param(E1, "uv run python tools/analyze.py e1", "does not run", id="through-uv"),
    pytest.param(E1, f"python {ROOT}/tools/analyze.py e1", "does not run", id="absolute-script"),
    pytest.param(
        E1,
        "python tools/analyze.py e2",
        "runs tools/analyze.py e2, not tools/analyze.py e1",
        id="other-subcommand",
    ),
    pytest.param(E1, "python tools/analyze.py", "runs tools/analyze.py, not", id="no-subcommand"),
    pytest.param(E1, "python tools/analyze.py e1 --root /elsewhere", "passes --root", id="root"),
    pytest.param(E1, "python tools/analyze.py e1 --root=.", "passes --root", id="root-equals"),
    pytest.param(E4, "python tools/analyze_e4.py --ro /x", "passes --ro", id="root-abbreviated"),
    pytest.param(
        E1, "python tools/analyze.py e1 --runs /etc/runs.jsonl", "an absolute path", id="absolute"
    ),
    pytest.param(
        E1, "python tools/analyze.py e1 --runs=../other/runs.jsonl", "a .. part", id="dotdot"
    ),
    pytest.param(
        E3, "python tools/run_judges.py --cache artifacts/../../c", "a .. part", id="inner-dotdot"
    ),
    pytest.param(E3, "python tools/run_judges.py --cache /tmp/c", "an absolute path", id="cache"),
    pytest.param(E1, "python tools/analyze.py e1 --runs \x00", "NUL", id="nul"),
    # Review BV1: an E2 (or E1) input other than the banked one, inside the repository.
    pytest.param(
        E2,
        "python tools/analyze.py e2 --runs artifacts/e2/alt_runs.jsonl",
        "passes --runs artifacts/e2/alt_runs.jsonl, not the banked input artifacts/e1/runs.jsonl",
        id="e2-other-rows",
    ),
    pytest.param(
        E2,
        "python tools/analyze.py e2 --run-dirs=artifacts/hand/runs",
        "passes --run-dirs artifacts/hand/runs, not the banked input artifacts/studies/e1/runs",
        id="e2-other-runs",
    ),
    pytest.param(
        E2,
        "python tools/analyze.py e2 --seeded artifacts/e0/other.json",
        "not the banked input artifacts/e0/seeded_eval.json",
        id="e2-other-evaluation",
    ),
    pytest.param(
        E1,
        "python tools/analyze.py e1 --plan artifacts/plan.json",
        "not the banked input artifacts/studies/e1/plan.json",
        id="e1-other-plan",
    ),
    pytest.param(
        E1,
        "python tools/analyze.py e1 --failures artifacts/none.jsonl",
        "not the banked input artifacts/studies/e1/failures.jsonl",
        id="e1-other-failure-log",
    ),
    pytest.param(
        E1,
        "python tools/analyze.py e1 --prereg prereg/9999-other.md",
        "not the banked input prereg/0001-e1-main-study.md",
        id="e1-other-prereg",
    ),
    pytest.param(
        E1,
        "python tools/analyze.py e1 --runs ./artifacts/e1/runs.jsonl",
        "not the banked input",
        id="e1-the-rows-spelled-otherwise",
    ),
    # Review BV2: a re-score of replies other than the banked ones, and the options that
    # make a partial or exploratory E3 run, which never writes the default path.
    pytest.param(
        E3,
        "python tools/run_judges.py --rescore --replies artifacts/e3/replies-alt.jsonl",
        "passes --replies artifacts/e3/replies-alt.jsonl, not the banked input "
        "artifacts/e3/replies.jsonl",
        id="e3-other-replies",
    ),
    pytest.param(
        E3,
        "python tools/run_judges.py --prereg prereg/other.md",
        "not the banked input prereg/0003-e3-judges.md",
        id="e3-other-prereg",
    ),
    pytest.param(E3, "python tools/run_judges.py --limit 3", "passes --limit, which", id="limit"),
    pytest.param(
        E3, "python tools/run_judges.py --sample-runs 12", "passes --sample-runs", id="e3-k"
    ),
    pytest.param(
        E3, "python tools/run_judges.py --sample-seed=7", "passes --sample-seed", id="e3-seed"
    ),
    pytest.param(E3, "python tools/run_judges.py --dry-run", "passes --dry-run", id="dry-run"),
    pytest.param(
        E3, "python tools/run_judges.py --confirmatory=1", "takes no value", id="flag-with-value"
    ),
    pytest.param(E3, "python tools/run_judges.py --judges", "without a value", id="no-value"),
    pytest.param(
        E3,
        "python tools/run_judges.py --judges --limit 3",
        "passes --judges with the value '--limit'",
        id="an-option-as-a-value",
    ),
    # E2 has no bootstrap, and E4's quick-check settings never write its default path.
    pytest.param(E2, "python tools/analyze.py e2 --n-boot 10", "passes --n-boot", id="e2-n-boot"),
    pytest.param(E4, "python tools/analyze_e4.py --n-boot 10", "passes --n-boot", id="e4-n-boot"),
    pytest.param(E4, "python tools/analyze_e4.py --seed 5", "passes --seed", id="e4-seed"),
    pytest.param(E4, "python tools/analyze_e4.py --n-agq=3", "passes --n-agq", id="e4-n-agq"),
    # Options are re-used only as spelled in full, so argparse reads each as the one listed.
    pytest.param(
        E1, "python tools/analyze.py e1 --n-b 10", "passes --n-b, which", id="abbreviated"
    ),
    pytest.param(E1, "python tools/analyze.py e1 extra", "passes 'extra'", id="a-positional"),
    pytest.param(E1, "python tools/analyze.py e1 -h", "passes -h, which", id="short-option"),
]


@pytest.mark.parametrize(("item", "command", "said"), REFUSED)
def test_a_recorded_command_that_could_read_outside_the_repository_is_refused(
    tmp_path: Path, item: Derived, command: object, said: str
) -> None:
    with pytest.raises(DerivedError) as caught:
        recorded_arguments(tmp_path, item, command)
    assert said in str(caught.value)


def test_a_path_through_a_symbolic_link_out_of_the_repository_is_refused(tmp_path: Path) -> None:
    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "artifacts").mkdir()
    (root / "artifacts" / "link").symlink_to(outside, target_is_directory=True)
    command = "python tools/run_judges.py --cache artifacts/link/cache"
    with pytest.raises(DerivedError, match="through a symbolic link"):
        recorded_arguments(root, E3, command)
    inside = root / "artifacts" / "inner"
    inside.mkdir()
    (root / "artifacts" / "near").symlink_to(inside, target_is_directory=True)
    near = "python tools/run_judges.py --cache artifacts/near/cache"
    assert recorded_arguments(root, E3, near) == ["--cache", "artifacts/near/cache"]
    # A banked input reached through a link out of the repository is refused as well.
    (root / "artifacts" / "e1").symlink_to(outside, target_is_directory=True)
    banked = "python tools/analyze.py e1 --runs artifacts/e1/runs.jsonl"
    with pytest.raises(DerivedError, match="through a symbolic link"):
        recorded_arguments(root, E1, banked)


def test_an_item_that_reuses_no_arguments_ignores_the_recorded_command(tmp_path: Path) -> None:
    anything = {"provenance": {"command": "python3 /tmp/x.py --root /"}}
    assert arguments(tmp_path, SMOKE, anything) == []
    assert arguments(tmp_path, SMOKE, None) == []


def test_a_derivation_runs_offline_from_the_repository_root(tmp_path: Path) -> None:
    item = Derived("artifacts/env.json", "tools/env.py")
    script(
        tmp_path,
        item.script,
        "import json\nout.write_text(json.dumps({'offline': os.environ.get('RECEIPTS_OFFLINE'),"
        " 'cwd': os.getcwd(), 'argv': sys.argv[1:-2]}))\n",
    )
    got = derived.derive(tmp_path, item, ["--n-boot", "10"])
    assert got == {"offline": "1", "cwd": str(tmp_path.resolve()), "argv": ["--n-boot", "10"]}


# ---------------------------------------------------------------- the smoke summary (D56)


def test_refresh_writes_a_missing_summary_once_and_then_leaves_it(
    git_repo: Path, commit: Commit
) -> None:
    root = repo(git_repo, commit)
    (missing,) = check(root)
    assert missing.startswith(f"{SMOKE.path}: missing, though") and "make report" in missing
    assert refresh(root) == [SMOKE.path]
    assert check(root) == []
    before = (root / SMOKE.path).read_bytes()
    assert refresh(root) == []  # nothing changed, so no rewrite and no new timestamp
    assert (root / SMOKE.path).read_bytes() == before


def test_a_run_banked_after_the_summary_makes_it_stale(git_repo: Path, commit: Commit) -> None:
    root = repo(git_repo, commit)
    refresh(root)
    new = bank_run(root, record("smoke-py-c", success_reported=True, done=False))

    inputs, content = check(root)
    assert f"new: {new}" in inputs and "recorded inputs are not the current" in inputs
    assert content.startswith(f"{SMOKE.path}: differs from a fresh derivation")
    assert "runs" in content and "summary" in content and "provenance.inputs" in content
    assert refresh(root) == [SMOKE.path]
    assert check(root) == []
    summary = json.loads((root / SMOKE.path).read_text(encoding="utf-8"))["summary"]
    assert summary["runs"] == 3


def test_a_summary_value_typed_by_hand_fails_although_the_inputs_are_current(
    git_repo: Path, commit: Commit
) -> None:
    root = repo(git_repo, commit)
    refresh(root)
    studies.edit(root, SMOKE.path, lambda art: art["summary"]["false_success"].update(k=0))

    assert check(root) == [
        f"{SMOKE.path}: differs from a fresh derivation by {SMOKE.script} "
        "(summary.false_success.k); run make report"
    ]


def test_changed_and_removed_inputs_are_named(git_repo: Path, commit: Commit) -> None:
    root = repo(git_repo, commit)
    refresh(root)
    changed = root / RUNS / "smoke-py-a" / "run.json"
    rec = json.loads(changed.read_text(encoding="utf-8"))
    rec["turns"] = 9
    changed.write_text(json.dumps(rec), encoding="utf-8")
    shutil.rmtree(root / RUNS / "smoke-ts-b")

    inputs = check(root)[0]
    assert f"changed: {RUNS}/smoke-py-a/run.json" in inputs
    assert f"removed: {RUNS}/smoke-ts-b/run.json" in inputs


def test_missing_scripts_bad_artifacts_and_failing_derivations(tmp_path: Path) -> None:
    assert check(tmp_path) == [] and refresh(tmp_path) == []  # nothing banked, nothing derived
    target = tmp_path / SMOKE.path
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")
    assert check(tmp_path)[0].startswith(f"{SMOKE.path}: not JSON")
    target.write_text("[]", encoding="utf-8")
    assert check(tmp_path) == [f"{SMOKE.path}: not a JSON object"]
    target.write_text('{"provenance": {"inputs": {}}}', encoding="utf-8")
    assert check(tmp_path) == [f"{SMOKE.path}: {SMOKE.script} is missing"]
    marked = record("smoke-py-x", success_reported=True, done=False)
    marked["synthetic"] = True  # the script refuses synthetic records
    bank_run(tmp_path, marked)
    (tmp_path / "tools").mkdir()
    shutil.copy(ROOT / "tools" / "smoke_outcomes.py", tmp_path / "tools" / "smoke_outcomes.py")
    with pytest.raises(DerivedError, match="failed: a run record is marked synthetic"):
        refresh(tmp_path)


def test_invalid_json_from_a_derivation_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    item = Derived("artifacts/derived.json", "tools/derive.py", "inputs/*.txt", rewritable=True)
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "a.txt").write_text("synthetic input\n", encoding="utf-8")
    script(tmp_path, item.script, "out.write_text('{not json')\n")
    with pytest.raises(DerivedError, match=r"tools/derive\.py wrote invalid JSON"):
        refresh(tmp_path, [item])
    (tmp_path / item.path).parent.mkdir(parents=True)
    (tmp_path / item.path).write_text('{"provenance": {"inputs": {}}}', encoding="utf-8")
    (problem,) = [p for p in check(tmp_path, [item]) if "invalid JSON" in p]
    assert problem.startswith(f"{item.path}: tools/derive.py wrote invalid JSON")


@pytest.mark.parametrize("provenance", ["a string", [1], 5, None])
def test_a_committed_provenance_that_is_not_an_object_is_a_problem(
    git_repo: Path, commit: Commit, provenance: object
) -> None:
    root = repo(git_repo, commit)
    assert refresh(root) == [SMOKE.path]
    target = root / SMOKE.path
    art = json.loads(target.read_text(encoding="utf-8"))
    art["provenance"] = provenance
    target.write_text(json.dumps(art), encoding="utf-8")
    assert check(root) == [f"{SMOKE.path}: its provenance is not a JSON object; run make report"]
    assert refresh(root) == [SMOKE.path]  # make report writes it again from the runs
    assert check(root) == []


def test_make_report_freshness_and_reproduce_follow_the_banked_runs(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(git_repo, commit)
    assert report.main(["--root", str(root)]) == 0  # make report: re-derives, then builds
    assert f"re-derived {SMOKE.path}" in capsys.readouterr().out
    assert report.main(["--root", str(root), "--reproduce"]) == 0
    stub_registry(root)
    (root / "README.md").write_text("<!--n:smoke.runs-->2<!--/n-->\n", encoding="utf-8")
    assert freshness.main(["--root", str(root), "README.md"]) == 0
    capsys.readouterr()

    bank_run(root, record("smoke-py-c", success_reported=True, done=False))
    assert freshness.main(["--root", str(root), "README.md"]) == 1
    assert "differs from a fresh derivation" in capsys.readouterr().out
    assert report.main(["--root", str(root), "--reproduce"]) == 1
    assert "recorded inputs are not the current" in capsys.readouterr().out


def stub_registry(root: Path) -> None:
    """Make freshness's registry rebuild a stand-in that writes the committed registry
    (an empty one when none is committed), so only the derived artifacts decide."""
    path = root / "artifacts" / "report" / "numbers.json"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"numbers": {}}\n', encoding="utf-8")
    script(root, "tools/report.py", f"out.write_text({path.read_text(encoding='utf-8')!r})\n")


# ---------------------------------------------------------------- the study artifacts (D65)


def test_refresh_never_derives_or_writes_a_study_artifact(tmp_path: Path) -> None:
    item = Derived("artifacts/e9/results.json", "tools/e9.py", recorded=True)
    script(tmp_path, item.script, "pathlib.Path('ran').write_text('x')\nout.write_text('{}')\n")
    target = tmp_path / item.path
    target.parent.mkdir(parents=True)
    target.write_text('{"typed": 1, "provenance": {}}\n', encoding="utf-8")
    assert refresh(tmp_path, [item]) == []
    assert target.read_text(encoding="utf-8") == '{"typed": 1, "provenance": {}}\n'
    assert not (tmp_path / "ran").exists()  # the script never ran


def test_an_absent_study_artifact_is_skipped_unless_it_is_asked_for(tmp_path: Path) -> None:
    assert check(tmp_path, [E1, E2, E3, E4]) == []
    assert check(tmp_path, [E1], present=True) == [
        f"{E1.path}: missing, so there is nothing to derive again"
    ]


@pytest.fixture(scope="module")
def e1_study(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The SYNTHETIC E1 study of :func:`tests.report.studies.e1_study`, built once."""
    return studies.e1_study(tmp_path_factory.mktemp("e1") / "repo")


@pytest.fixture
def e1_repo(e1_study: Path, tmp_path: Path) -> Path:
    """A copy of the E1 study that one test may change."""
    copy = tmp_path / "e1"
    shutil.copytree(e1_study, copy, symlinks=True)
    return copy


@pytest.fixture
def e3_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The SYNTHETIC E3 study of :func:`tests.report.studies.e3_study`."""
    return studies.e3_study(tmp_path / "e3", monkeypatch)


@pytest.fixture
def e4_repo(tmp_path: Path) -> Path:
    """The SYNTHETIC E4 study of :func:`tests.report.studies.e4_study`."""
    return studies.e4_study(tmp_path / "e4")


@pytest.mark.slow  # two E1 analyses with 10 bootstrap resamples each
def test_the_e1_and_e2_artifacts_equal_a_fresh_derivation_in_a_fresh_clone(
    e1_repo: Path, tmp_path: Path
) -> None:
    there = studies.fresh_clone(e1_repo, tmp_path / "clone")
    assert check(there, [E1, E2]) == []
    # The derivation re-used the recorded arguments of an exploratory run.
    results = json.loads((there / E1.path).read_text(encoding="utf-8"))
    assert results["provenance"]["command"] == "python tools/analyze.py e1 --n-boot 10"
    assert arguments(there, E1, results) == ["e1", "--n-boot", "10"]
    assert results["settings"]["n_boot"] == 10 and results["confirmatory"] is False


def test_the_e3_artifact_is_re_scored_from_its_banked_replies_in_a_fresh_clone(
    e3_repo: Path, tmp_path: Path
) -> None:
    assert (e3_repo / "runs" / "e3" / "pid").is_file()  # the live run's state, ignored by git
    there = studies.fresh_clone(e3_repo, tmp_path / "clone")
    assert not (there / "runs").exists()
    assert check(there, [E3]) == []
    assert not (there / "runs").exists()  # the re-score writes no state


def test_the_e4_artifact_equals_a_fresh_derivation_in_a_fresh_clone(
    e4_repo: Path, tmp_path: Path
) -> None:
    there = studies.fresh_clone(e4_repo, tmp_path / "clone")
    assert check(there, [E4]) == []


def raise_statistic_and_flip_decision(data: dict[str, Any]) -> None:
    """A hand-set E1 test statistic and a hand-set E1 test decision."""
    data["tests"]["arm_tests"]["Y1"]["statistic"] += 1.0
    test = data["tests"]["manipulation_tests"][0]
    test["reject"] = not test["reject"]


def reclassify(data: dict[str, Any]) -> None:
    """A hand-set E2 class."""
    claim = data["claims"][0]
    claim["class"] = next(c for c in data["classes"] if c != claim["class"])


def add_a_true_positive(data: dict[str, Any]) -> None:
    """A hand-set E3 count."""
    per_type = data["judges"][0]["per_type"]
    per_type[sorted(per_type)[0]]["tp"] += 1


def flip_holm_and_ratio(data: dict[str, Any]) -> None:
    """A hand-set E4 test decision and a hand-set E4 odds ratio."""
    z1 = data["outcomes"]["Z1"]
    z1["holm"]["reject"][0] = not z1["holm"]["reject"][0]
    z1["contrasts"][0]["odds_ratio"] *= 2


HAND_SET = [
    pytest.param(
        "e1_repo",
        E1,
        raise_statistic_and_flip_decision,
        ("tests.arm_tests.Y1.statistic", "tests.manipulation_tests.0.reject"),
        id="e1-test-statistic-and-decision",
        marks=pytest.mark.slow,
    ),
    pytest.param(
        "e1_repo", E2, reclassify, ("claims.0.class",), id="e2-class", marks=pytest.mark.slow
    ),
    pytest.param("e3_repo", E3, add_a_true_positive, ("judges.0.per_type.",), id="e3-count"),
    pytest.param(
        "e4_repo",
        E4,
        flip_holm_and_ratio,
        ("outcomes.Z1.holm.reject.0", "outcomes.Z1.contrasts.0.odds_ratio"),
        id="e4-test-decision-and-ratio",
    ),
]


@pytest.mark.parametrize(("repo_fixture", "item", "change", "where"), HAND_SET)
def test_a_hand_set_study_value_fails_the_gate_check_and_make_freshness(
    request: pytest.FixtureRequest,
    capsys: pytest.CaptureFixture[str],
    repo_fixture: str,
    item: Derived,
    change: Change,
    where: tuple[str, ...],
) -> None:
    """The gates run ``python -m receipts.report.derived <path>`` (:func:`derived.main`) in
    their clone, and ``make freshness`` checks every derived artifact: each fails on a
    value typed into a study artifact that a fresh derivation does not give."""
    root: Path = request.getfixturevalue(repo_fixture)
    assert derived.main(["--root", str(root), item.path]) == 0
    out = capsys.readouterr().out
    assert f"{item.path}: re-derived by {item.command}; equals the committed artifact" in out
    assert out.splitlines()[-1] == "DERIVED: PASS"
    studies.edit(root, item.path, change)
    assert derived.main(["--root", str(root), item.path]) == 1
    out = capsys.readouterr().out
    lead = f"problem: {item.path}: differs from a fresh derivation by {item.script} ("
    (problem,) = [line for line in out.splitlines() if line.startswith("problem: ")]
    assert problem.startswith(lead) and all(path in problem for path in where), problem
    assert out.splitlines()[-1] == "DERIVED: FAIL 1"
    stub_registry(root)
    (root / "README.md").write_text("SYNTHETIC: no bound numbers.\n", encoding="utf-8")
    assert freshness.main(["--root", str(root), "README.md"]) == 1
    assert lead in capsys.readouterr().out


def test_make_reproduce_fails_on_a_hand_set_study_value(
    e4_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert report.main(["--root", str(e4_repo)]) == 0  # make report: never writes E4
    studies.commit_all(e4_repo, "SYNTHETIC report outputs")
    assert report.main(["--root", str(e4_repo), "--reproduce"]) == 0
    capsys.readouterr()
    studies.edit(e4_repo, E4.path, flip_holm_and_ratio)
    kept = (e4_repo / E4.path).read_bytes()
    assert report.main(["--root", str(e4_repo)]) == 0
    assert (e4_repo / E4.path).read_bytes() == kept  # make report leaves it as it is
    capsys.readouterr()
    assert report.main(["--root", str(e4_repo), "--reproduce"]) == 1
    assert f"problem: {E4.path}: differs from a fresh derivation" in capsys.readouterr().out


def runs_haswell_kernels() -> bool:
    """Whether this CPU can run OpenBLAS's Haswell kernels (x86-64 with AVX2)."""
    try:
        return " avx2 " in Path("/proc/cpuinfo").read_text(encoding="utf-8").replace("\n", " ")
    except OSError:
        return False


#: Other numerical kernels than the ones the SYNTHETIC artifacts were written with on a
#: CPU with AVX-512: OpenBLAS's Haswell kernel (the one it picks on a CPU with AVX2 and
#: no AVX-512) and numpy without its AVX-512 code paths (review F1 of the B5 fix).
OTHER_KERNELS = [
    pytest.param(
        {"OPENBLAS_CORETYPE": "Haswell"},
        id="openblas-haswell",
        marks=pytest.mark.skipif(not runs_haswell_kernels(), reason="needs AVX2"),
    ),
    # The AVX-512 targets under the names of numpy 2.4 and later (X86_V4 and up) and of
    # earlier releases; numpy passes over a name it does not dispatch.
    pytest.param(
        {
            "NPY_DISABLE_CPU_FEATURES": "AVX512F,AVX512CD,AVX512_SKX,AVX512_CLX,AVX512_CNL,"
            "AVX512_ICL,AVX512_SPR,X86_V4"
        },
        id="numpy-without-avx512",
    ),
]


@pytest.mark.parametrize("kernel", OTHER_KERNELS)
def test_the_e4_results_equal_a_derivation_with_other_numerical_kernels(
    e4_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kernel: dict[str, str]
) -> None:
    """Review F1 of the B5 fix: the mixed models and bootstraps of E4 come out with other
    last digits under another BLAS kernel or numpy's other code paths (also another
    numpy or scipy, such as the lock's Python 3.12 resolution), and an optimizer may take
    another iteration; a genuine artifact still equals its derivation, and a value typed
    in at the fourth significant digit still fails."""
    there = studies.fresh_clone(e4_repo, tmp_path / "clone")
    for name, value in kernel.items():
        monkeypatch.setenv(name, value)
    assert check(there, [E4]) == []

    def nudge(data: dict[str, Any]) -> None:
        data["outcomes"]["Z1"]["contrasts"][0]["odds_ratio"] *= 1.001

    studies.edit(there, E4.path, nudge)
    (problem,) = check(there, [E4])
    assert problem.startswith(f"{E4.path}: differs from a fresh derivation by {E4.script} (")
    assert "(outcomes.Z1.contrasts.0.odds_ratio)" in problem


@pytest.mark.slow  # the SYNTHETIC E1 analysis runs again
@pytest.mark.parametrize("kernel", OTHER_KERNELS)
def test_the_e1_results_equal_a_derivation_with_other_numerical_kernels(
    e1_repo: Path, monkeypatch: pytest.MonkeyPatch, kernel: dict[str, str]
) -> None:
    """Review F1 of the B5 fix, for the E1 mixed models and bootstraps."""
    for name, value in kernel.items():
        monkeypatch.setenv(name, value)
    assert check(e1_repo, [E1]) == []


def test_a_banked_reply_missing_from_the_replies_fails_the_e3_re_derivation(
    e3_repo: Path,
) -> None:
    replies = e3_repo / studies.E3_REPLIES
    lines = replies.read_text(encoding="utf-8").splitlines(keepends=True)
    replies.write_text("".join(lines[:1] + lines[2:]), encoding="utf-8")
    (problem,) = check(e3_repo, [E3])
    assert problem.startswith(f"{E3.path}: tools/run_judges.py failed: E3: ")
    assert "has no banked reply of judge" in problem and "never calls a model" in problem


def test_a_study_artifact_recorded_with_a_root_is_not_derived_again(e4_repo: Path) -> None:
    def elsewhere(data: dict[str, Any]) -> None:
        data["provenance"]["command"] = "python tools/analyze_e4.py --root /elsewhere"

    studies.edit(e4_repo, E4.path, elsewhere)
    assert check(e4_repo, [E4]) == [
        f"{E4.path}: its provenance.command passes --root, and a re-derivation reads this "
        "repository, not another root"
    ]


def other_input(option: str, value: str, banked: str) -> str:
    """How the check refuses a recorded input other than the banked one."""
    return (
        f"its provenance.command passes {option} {value}, not the banked input {banked}, and "
        "a re-derivation reads only the banked inputs"
    )


def freshness_fails(root: Path, said: str, capsys: pytest.CaptureFixture[str]) -> None:
    """``make freshness`` on ``root`` fails, and says ``said``."""
    stub_registry(root)
    (root / "README.md").write_text("SYNTHETIC: no bound numbers.\n", encoding="utf-8")
    capsys.readouterr()
    assert freshness.main(["--root", str(root), "README.md"]) == 1
    assert said in capsys.readouterr().out


@pytest.mark.slow  # the SYNTHETIC E1 study is analyzed first
def test_e2_written_from_a_hand_made_rows_file_fails_the_check_and_make_freshness(
    e1_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review BV1 of the B5 fix: ``tools/analyze.py e2 --runs <a rows file committed in the
    repository>`` writes classes that the same command derives again, so the check must
    refuse the recorded input, which is not the banked one."""
    alt = "artifacts/e2/alt_runs.jsonl"
    genuine = json.loads((e1_repo / E2.path).read_text(encoding="utf-8"))
    studies.rows_without_evidence(e1_repo, alt)
    studies.operator(e1_repo, "tools/analyze.py", "e2", "--runs", alt)
    studies.commit_all(e1_repo, "SYNTHETIC E2 from a hand-made rows file")
    forged = json.loads((e1_repo / E2.path).read_text(encoding="utf-8"))
    assert forged["provenance"]["command"] == f"python tools/analyze.py e2 --runs {alt}"
    assert {c["class"] for c in forged["claims"]} == {"never_saw"}
    assert {c["class"] for c in genuine["claims"]} != {"never_saw"}
    refused = other_input("--runs", alt, analyze.RUNS)
    assert check(e1_repo, [E2]) == [f"{E2.path}: {refused}"]
    assert derived.main(["--root", str(e1_repo), E2.path]) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"problem: {E2.path}: {refused}",
        "DERIVED: FAIL 1",
    ]
    freshness_fails(e1_repo, refused, capsys)


def counts(judges: dict[str, Any]) -> dict[str, Any]:
    """Each judge's per-type detection counts."""
    keys = ("tp", "fp", "fn", "tn")
    return {
        j["judge_id"]: {t: [c[k] for k in keys] for t, c in j["per_type"].items()}
        for j in judges["judges"]
    }


def test_e3_scored_from_hand_made_replies_fails_the_check_and_make_freshness(
    e3_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review BV2 of the B5 fix: a re-score of a replies file committed beside the banked
    one gives other counts, and its own command re-scores to them, so the check must
    refuse the recorded replies, which are not the banked ones."""
    alt = "artifacts/e3/replies-alt.jsonl"
    banked = (e3_repo / studies.E3_REPLIES).read_bytes()
    genuine = json.loads((e3_repo / E3.path).read_text(encoding="utf-8"))
    studies.forged_replies(e3_repo, alt, genuine["judges"][0]["judge_id"])
    rescored = "artifacts/e3/forged.json"
    rescore = ["--rescore", "--replies", alt, "--out", rescored]
    studies.operator(e3_repo, "tools/run_judges.py", *rescore)
    (e3_repo / rescored).replace(e3_repo / E3.path)  # copied to the default path by hand
    studies.commit_all(e3_repo, "SYNTHETIC E3 scored from hand-made replies")
    forged = json.loads((e3_repo / E3.path).read_text(encoding="utf-8"))
    assert forged["replies"]["path"] == alt and counts(forged) != counts(genuine)
    assert (e3_repo / studies.E3_REPLIES).read_bytes() == banked
    refused = other_input("--replies", alt, studies.E3_REPLIES)
    assert check(e3_repo, [E3]) == [f"{E3.path}: {refused}"]
    assert derived.main(["--root", str(e3_repo), E3.path]) == 1
    assert f"problem: {E3.path}: {refused}" in capsys.readouterr().out
    freshness_fails(e3_repo, refused, capsys)


# ---------------------------------------------------------------- the command line


def test_the_command_line_names_artifacts_and_reports_each(
    e4_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = ["--root", str(e4_repo)]
    assert derived.main([*root, "artifacts/e9/results.json"]) == 2
    assert "is not a derived artifact" in capsys.readouterr().err
    assert derived.main([*root, E1.path]) == 1  # named, so it must exist
    out = capsys.readouterr().out
    assert f"problem: {E1.path}: missing, so there is nothing to derive again" in out
    assert derived.main(root) == 0  # every one: the absent ones are skipped
    out = capsys.readouterr().out
    assert f"{E4.path}: re-derived by python tools/analyze_e4.py" in out
    assert E1.path not in out and out.splitlines()[-1] == "DERIVED: PASS"


def test_the_module_runs_as_a_script(e4_repo: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "receipts.report.derived", E4.path],
        cwd=e4_repo,
        env=studies.environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[-1] == "DERIVED: PASS"
