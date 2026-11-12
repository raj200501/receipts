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

import freshness
import report
from receipts.report import derived
from receipts.report.derived import (
    DERIVED,
    Derived,
    DerivedError,
    arguments,
    check,
    comparable,
    differences,
    recorded_arguments,
    refresh,
    same,
)
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
        id="e2",
    ),
    pytest.param(
        E3,
        "python tools/run_judges.py --prereg prereg/0003-e3-judges.md --confirmatory",
        ["--prereg", "prereg/0003-e3-judges.md", "--confirmatory", "--rescore"],
        id="e3-rescore-added",
    ),
    pytest.param(
        E3,
        "python tools/run_judges.py --limit 3 --judges=qwen7b-transcript --out runs/e3/p.json",
        ["--limit", "3", "--judges=qwen7b-transcript", "--rescore"],
        id="e3-partial",
    ),
    pytest.param(E4, "python tools/analyze_e4.py", [], id="e4-defaults"),
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
    command = "python tools/analyze.py e1 --runs artifacts/link/runs.jsonl"
    with pytest.raises(DerivedError, match="through a symbolic link"):
        recorded_arguments(root, E1, command)
    inside = root / "artifacts" / "inner"
    inside.mkdir()
    (root / "artifacts" / "near").symlink_to(inside, target_is_directory=True)
    near = "python tools/analyze.py e1 --runs artifacts/near/runs.jsonl"
    assert recorded_arguments(root, E1, near) == ["--runs", "artifacts/near/runs.jsonl"]


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
