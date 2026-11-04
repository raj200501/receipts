"""Gate G3 of tools/ship_check.py on synthetic projects (findings H07 to H09).

Every workflow and Makefile here is SYNTHETIC, shaped like the committed ones and made
only to exercise ``ship_check.g3``. The Makefile recipes only ``echo``, so ``make ci``
and its dry runs finish in milliseconds; nothing here is a model or real-world result.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import ship_check

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="needs make")

CI_YML = """\
name: ci

# SYNTHETIC copy of the committed workflow shape (tests for tools/ship_check.py G3).
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  ci:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - name: Install Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}
      - name: Setup
        run: make setup PY=${{ matrix.python-version }}
      - name: Lint, typecheck, test, offline demo
        run: make ci
"""
SETUP_STEP = "      - name: Setup\n        run: make setup PY=${{ matrix.python-version }}\n"
SETUP = "        run: make setup PY=${{ matrix.python-version }}\n"
CI_STEP = "      - name: Lint, typecheck, test, offline demo\n        run: make ci\n"
CI = "        run: make ci\n"
MATRIX = '        python-version: ["3.11", "3.12"]\n'
INSTALL = (
    "      - name: Install Python ${{ matrix.python-version }}\n"
    "        run: uv python install ${{ matrix.python-version }}\n"
)
RUNS_ON = "    runs-on: ubuntu-latest\n"

MAKEFILE = """\
# SYNTHETIC test project for tools/ship_check.py gate G3 (recipes only echo).
PY ?= 3.11
PYTEST_ARGS ?=
COV_JSON ?= runs/coverage.json
RUN := echo

setup:
\t@true

lint:
\t$(RUN) ruff check .
\t$(RUN) ruff format --check .

typecheck:
\t$(RUN) mypy --strict

test:
\t@mkdir -p "$(dir $(COV_JSON))"
\t$(RUN) pytest --cov=receipts --cov-report=term-missing \\
\t\t--cov-report=json:$(COV_JSON) $(PYTEST_ARGS)

demo:
\t$(RUN) python tools/demo.py --check

ci: lint typecheck test demo
"""
ALL_PARTS_PASS = {1: True, 2: True, 4: True}


def variant(*pairs: tuple[str, str]) -> str:
    """The synthetic workflow with each ``(old, new)`` replacement applied once."""
    text = CI_YML
    for old, new in pairs:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


def project(
    root: Path, workflow: str = CI_YML, makefile: str = MAKEFILE, fast: bool = True
) -> ship_check.Context:
    """Write a SYNTHETIC G3 project into ``root`` and return its Context."""
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(workflow, encoding="utf-8")
    (root / "Makefile").write_text(makefile, encoding="utf-8")
    logs = root / "logs"
    logs.mkdir()
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=fast, sha="0" * 40)


ACCEPTED = {
    # H09: equivalent workflows the old regexes rejected.
    "trailing-comment": variant((CI, "        run: make ci  # lint, typecheck, test, demo\n")),
    "quoted": variant((CI, '        run: "make ci"\n')),
    "literal-block": variant(
        (
            SETUP_STEP + CI_STEP,
            "      - name: Setup and check\n        run: |\n"
            "          make setup PY=${{ matrix.python-version }}\n          make ci\n",
        )
    ),
    "block-list-matrix": variant(
        (MATRIX, '        python-version:\n          - "3.11"\n          - "3.12"\n')
    ),
    "include-rows": variant(
        (
            MATRIX,
            '        include:\n          - python-version: "3.11"\n'
            '          - python-version: "3.12"\n',
        )
    ),
    "literal-strip": variant(
        (CI, "        run: |-\n          set -x\n          make ci  # all checks\n")
    ),
    # Equivalent forms the old checks happened to accept too.
    "plain-continued": variant((CI, "        run:\n          make ci\n")),
    "py-from-job-env": variant(
        (SETUP, "        run: make setup\n"),
        (RUNS_ON, RUNS_ON + "    env:\n      PY: ${{ matrix.python-version }}\n"),
    ),
    "py-from-step-env": variant(
        (
            SETUP,
            "        run: make setup\n        env:\n          PY: ${{ matrix.python-version }}\n",
        )
    ),
}

REJECTED = {
    # H08: workflows the old text search passed although CI never tests 3.12 or make ci.
    "setup-without-py": (variant((SETUP, "        run: make setup\n")), "matrix Python"),
    "job-if-false": (variant((RUNS_ON, "    if: false\n" + RUNS_ON)), "runs only if"),
    "matrix-only-in-comments": (
        variant((SETUP, "        run: make setup\n"), (INSTALL, "      # matrix.python-version\n")),
        "matrix Python",
    ),
    "matrix-commented-out": (
        variant((MATRIX, '        # python-version: ["3.11", "3.12"]\n')),
        "matrix lacks",
    ),
    "continue-on-error": (
        variant((CI, CI + "        continue-on-error: true\n")),
        "failure ignored",
    ),
    "exclude-drops-3.12": (
        variant((MATRIX, MATRIX + '        exclude:\n          - python-version: "3.12"\n')),
        "matrix lacks",
    ),
    "ci-in-second-job": (
        variant(
            (
                CI_STEP,
                "      - run: make test\n  lint:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n      - run: make setup\n"
                "      - run: make ci\n",
            )
        ),
        "matrix lacks",
    ),
    # Broken workflows the old regexes already rejected; the new reader must too.
    "folded": (
        variant((CI, "        run: >\n          echo start\n          make ci\n")),
        "no step",
    ),
    "cross-step-env": (
        variant(
            (
                SETUP_STEP + CI_STEP,
                "      - name: Setup\n        run: |\n"
                "          make setup PY=${{ matrix.python-version }}\n"
                "      - name: Lint and typecheck only\n        run: make lint typecheck\n"
                "        env:\n          SKIPPED: |\n            make ci\n",
            )
        ),
        "no step",
    ),
    "commented-out": (variant((CI, "        run: make lint\n        # run: make ci\n")), "no step"),
    "or-true": (variant((CI, "        run: make ci || true\n")), "no step"),
    "continuation": (
        variant((CI, "        run: |\n          echo \\\n          make ci\n")),
        "no step",
    ),
    "custom-shell-not-last": (
        variant(
            (
                CI,
                "        shell: bash {0}\n        run: |\n          make ci\n          echo done\n",
            )
        ),
        "failure ignored",
    ),
}


def test_committed_workflow_shape_passes(tmp_path: Path) -> None:
    assert "workflow ok" in ship_check.g3(project(tmp_path), ALL_PARTS_PASS)


@pytest.mark.parametrize("name", sorted(ACCEPTED))
def test_equivalent_workflows_pass(tmp_path: Path, name: str) -> None:
    assert "workflow ok" in ship_check.g3(project(tmp_path, ACCEPTED[name]), ALL_PARTS_PASS)


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_broken_workflows_fail(tmp_path: Path, name: str) -> None:
    workflow, match = REJECTED[name]
    with pytest.raises(ship_check.GateError, match=match):
        ship_check.g3(project(tmp_path, workflow), ALL_PARTS_PASS)


def test_unreadable_yaml_is_a_fail_not_a_crash(tmp_path: Path) -> None:
    broken = variant((MATRIX, '        python-version: ["3.11", "3.12"\n'))
    with pytest.raises(ship_check.GateError, match="cannot read"):
        ship_check.g3(project(tmp_path, broken), ALL_PARTS_PASS)


# ---------------------------------------------------------------- H07 (old code: PASS)

RESTRUCTURED = MAKEFILE.replace(
    "ci: lint typecheck test demo\n",
    "ci:\n\t$(MAKE) lint\n\t$(MAKE) typecheck\n\t$(MAKE) test\n\t$(MAKE) demo\n",
)


BROKEN_MAKEFILES = {
    "lint-only": (MAKEFILE.replace("ci: lint typecheck test demo", "ci: lint"), "does not run"),
    "no-demo": (
        MAKEFILE.replace("ci: lint typecheck test demo", "ci: lint typecheck test"),
        "demo",
    ),
    "empty": (MAKEFILE.replace("ci: lint typecheck test demo", "ci:"), "does not run"),
    "decoy-line": (
        MAKEFILE.replace(
            "ci: lint typecheck test demo",
            "ci: lint\n\t@: ruff format --check mypy --strict pytest tools/demo.py --check",
        ),
        "does not run",
    ),
    "ignored-demo-errors": (
        MAKEFILE.replace("\t$(RUN) python tools/demo.py", "\t-$(RUN) python tools/demo.py"),
        "ignores errors in: demo",
    ),
    "dot-ignore": (MAKEFILE + "\n.IGNORE:\n", "ignores errors"),
}


@pytest.mark.parametrize("name", sorted(BROKEN_MAKEFILES))
@pytest.mark.parametrize("fast", [True, False])
def test_make_ci_must_run_every_part(tmp_path: Path, name: str, fast: bool) -> None:
    makefile, match = BROKEN_MAKEFILES[name]
    ctx = project(tmp_path, makefile=makefile, fast=fast)
    with pytest.raises(ship_check.GateError, match=match):
        ship_check.g3(ctx, ALL_PARTS_PASS)


@pytest.mark.parametrize("makefile", [MAKEFILE, RESTRUCTURED], ids=["prerequisites", "recursive"])
def test_full_mode_runs_make_ci(tmp_path: Path, makefile: str) -> None:
    evidence = ship_check.g3(project(tmp_path, makefile=makefile, fast=False), {})
    assert "make ci passed" in evidence


def test_make_ci_failure_fails(tmp_path: Path) -> None:
    makefile = MAKEFILE.replace("\t$(RUN) mypy --strict", "\tfalse")
    with pytest.raises(ship_check.GateError, match="make ci failed"):
        ship_check.g3(project(tmp_path, makefile=makefile, fast=False), {})


def test_fast_mode_needs_the_parts_to_pass(tmp_path: Path) -> None:
    with pytest.raises(ship_check.GateError, match="do not all pass"):
        ship_check.g3(project(tmp_path), {1: True, 2: False, 4: True})
