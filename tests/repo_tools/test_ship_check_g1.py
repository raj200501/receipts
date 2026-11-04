"""Gate G1 of tools/ship_check.py on synthetic projects (findings H00 to H03).

Every project built here is SYNTHETIC: a tiny ``receipts`` package with the five core
modules, made only to exercise ``ship_check.g1``. Nothing in it is a model result or a
real-world result. The projects run the real ``make``, ``uv run --no-sync``, pytest, and
coverage.py; their ``.venv`` is a symlink to the venv running these tests, and their
``setup`` target is a no-op so nothing is ever synced into that venv.

Each case runs pytest and coverage in subprocesses, so the module is marked ``slow``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import ship_check

Commit = Callable[[Path, str], str]

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        sys.prefix == sys.base_prefix or not (shutil.which("uv") and shutil.which("make")),
        reason="needs make, uv, and a virtualenv to link synthetic projects to",
    ),
]

MAKEFILE = """\
# SYNTHETIC test project for tools/ship_check.py gate G1 (not a real project).
SHELL := /bin/bash
PY ?= 3.11
RUN := uv run --no-sync
COV_JSON ?= runs/coverage.json
PYTEST_ARGS ?=

setup:
\t@true

test:
\t@mkdir -p "$(dir $(COV_JSON))"
\t$(RUN) pytest --cov=receipts --cov-report=json:$(COV_JSON) $(PYTEST_ARGS)
"""

PYPROJECT = """\
# SYNTHETIC test project for tools/ship_check.py gate G1.
[project]
name = "synthetic-receipts"
version = "0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-p no:cacheprovider"

[tool.coverage.run]
source = ["receipts"]
branch = false
omit = {omit}
{extra}"""

CORE = '''"""Synthetic core module {name}."""


def bump(x: int) -> int:
    """Return x plus one."""
    return x + 1
'''

CORE_TEST = '''"""Synthetic tests for the core modules."""

from receipts import analysis, claims, hook, ledger, verify


def test_core() -> None:
    for module in (ledger, claims, verify, analysis, hook):
        assert module.bump(1) == 2
'''

FILLER = "".join(
    f"\n\ndef filler_{i}(x: int) -> int:\n    y = x + {i}\n    return y * 2\n" for i in range(20)
)

ADAPTER = (
    '''"""Synthetic adapter that would call an external service (never contacted)."""

import json


class Backend:
    """Synthetic backend."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def parse(self, payload: str) -> str:
        """Return the reply text of a recorded payload."""
        data = json.loads(payload)
        return str(data["reply"])
'''
    + FILLER
)

ADAPTER_IN_CLASS = '''"""Synthetic adapter with all of its code inside one class."""


class Backend:
    """Synthetic backend."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
''' + "".join(
    f"\n    def filler_{i}(self, x: int) -> int:\n        y = x + {i}\n        return y * 2\n"
    for i in range(20)
)

FIXTURE = '{"reply": "hello"}\n'

CONTRACT_PATHLIB = '''"""Synthetic recorded-fixture contract test for receipts.client.backends."""

from pathlib import Path

from receipts.client.backends import Backend

REPLY = Path(__file__).resolve().parents[1] / "fixtures" / "recorded" / "backends" / "reply.json"


def test_backend_parses_recorded_reply() -> None:
    assert Backend("http://unused.invalid").parse(REPLY.read_text()) == "hello"
'''

CONTRACT_CONSTANT = '''"""Synthetic contract test; its fixture path is split across constants."""

from pathlib import Path

from receipts.client.backends import Backend

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RECORDED = FIXTURES / "recorded"


def test_backend_parses_recorded_reply() -> None:
    reply = (RECORDED / "backends" / "reply.json").read_text()
    assert Backend("http://unused.invalid").parse(reply) == "hello"
'''

CONTRACT_SPELLED = '''"""Synthetic contract test naming tests/fixtures/recorded/ in one string."""

from receipts.client.backends import Backend


def test_backend_parses_recorded_reply() -> None:
    with open("tests/fixtures/recorded/backends/reply.json") as handle:
        assert Backend("http://unused.invalid").parse(handle.read()) == "hello"
'''

CONTRACT_SKIPPED = '''"""Synthetic contract test that skips because its fixture is not committed."""

from pathlib import Path

import pytest

from receipts.client.backends import Backend

CHAT = Path("tests/fixtures/recorded/backends/chat.json")


@pytest.mark.skipif(not CHAT.exists(), reason="fixture missing")
def test_backend_parses_chat() -> None:
    assert Backend("http://unused.invalid").parse(CHAT.read_text())


def test_fixture_dir_named() -> None:
    assert "fixtures/recorded" in str(CHAT)
'''

CONTRACT_IMPORT_ONLY = '''"""Synthetic contract test: imports the adapter, reads a fixture."""

from pathlib import Path

import receipts.client.backends  # noqa: F401

REPLY = Path("tests/fixtures/recorded/backends/reply.json")


def test_fixture_present() -> None:
    assert REPLY.read_text()
'''

CONTRACT_NO_FIXTURE = '''"""Synthetic contract test: calls the adapter, opens no fixture."""

from receipts.client.backends import Backend

# Mentions fixtures/recorded but never opens a file there.


def test_backend_parses_inline_reply() -> None:
    assert Backend("http://unused.invalid").parse('{"reply": "hi"}') == "hi"
'''


def build(
    root: Path,
    commit: Commit,
    *,
    omit: str = "[]",
    extra_config: str = "",
    files: dict[str, str] | None = None,
    drop: tuple[str, ...] = (),
    fast: bool = False,
) -> ship_check.Context:
    """Write a SYNTHETIC G1 project into ``root``, commit it, and return its Context."""
    layout: dict[str, str] = {
        "Makefile": MAKEFILE,
        "pyproject.toml": PYPROJECT.format(omit=omit, extra=extra_config),
        ".gitignore": ".venv\nruns/\n",
        "src/receipts/__init__.py": '"""Synthetic package."""\n',
        "tests/test_core.py": CORE_TEST,
    }
    for name in ship_check.CORE_MODULES:
        layout[f"src/receipts/{name}/__init__.py"] = CORE.format(name=name)
    layout.update(files or {})
    for rel in drop:
        layout.pop(rel)
    for rel, text in layout.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    sha = commit(root, "synthetic G1 project")
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=fast, sha=sha)


ADAPTER_FILES = {
    "src/receipts/client/__init__.py": '"""Synthetic client package."""\n',
    "src/receipts/client/backends.py": ADAPTER,
}


def needs_isolation() -> None:
    if ship_check.network_isolation() is None:
        pytest.skip("no working network isolation (unshare -rn, bwrap, sandbox-exec)")


# ---------------------------------------------------------------- controls


def test_clean_synthetic_project_passes(git_repo: Path, commit: Commit) -> None:
    ctx = build(git_repo, commit)
    assert "every core module >= 85%" in ship_check.g1(ctx)


def test_untested_adapter_fails(git_repo: Path, commit: Commit) -> None:
    ctx = build(git_repo, commit, files=ADAPTER_FILES)
    with pytest.raises(ship_check.GateError, match="package coverage"):
        ship_check.g1(ctx)


def test_failing_test_fails(git_repo: Path, commit: Commit) -> None:
    broken = {"tests/test_broken.py": "def test_broken() -> None:\n    assert False\n"}
    ctx = build(git_repo, commit, files=broken)
    with pytest.raises(ship_check.GateError, match="make test failed"):
        ship_check.g1(ctx)


def test_pragma_on_a_small_stub_outside_core_still_passes(git_repo: Path, commit: Commit) -> None:
    stub = {
        "src/receipts/client/__init__.py": (
            '"""Synthetic client."""\n\n\ndef stub() -> int:  # pragma: no cover\n    return 1\n'
        ),
        "tests/test_client.py": "import receipts.client\n\n\ndef test_import() -> None:\n"
        "    assert receipts.client.stub\n",
    }
    ctx = build(git_repo, commit, files=stub)
    assert "every core module >= 85%" in ship_check.g1(ctx)


# ---------------------------------------------------------------- H00 (old code: PASS)


@pytest.mark.parametrize(
    ("variant", "extra_config", "files"),
    [
        (
            "report-omit",
            '\n[tool.coverage.report]\nomit = ["*/client/backends.py"]\n',
            {},
        ),
        (
            "coveragerc",
            "",
            {".coveragerc": "[run]\nsource = receipts\nomit = */client/backends.py\n"},
        ),
        (
            "setup-cfg",
            "",
            {"setup.cfg": "[coverage:run]\nomit = */client/backends.py\n"},
        ),
        (
            "tox-ini",
            "",
            {"tox.ini": "[coverage:report]\nomit = */client/backends.py\n"},
        ),
        (
            "coveragerc-toml",
            "",
            {".coveragerc.toml": '[run]\nomit = ["*/client/backends.py"]\n'},
        ),
        (
            "report-include",
            '\n[tool.coverage.report]\ninclude = ["*/ledger/*", "*/claims/*", "*/verify/*",'
            ' "*/analysis/*", "*/hook/*"]\n',
            {},
        ),
        (
            "exclude-also",
            '\n[tool.coverage.report]\nexclude_also = ["class Backend"]\n',
            {"src/receipts/client/backends.py": ADAPTER_IN_CLASS},
        ),
        (
            "pragma",
            "",
            {
                "src/receipts/client/backends.py": ADAPTER_IN_CLASS.replace(
                    "class Backend:", "class Backend:  # pragma: no cover"
                )
            },
        ),
    ],
)
def test_coverage_config_cannot_drop_code(
    git_repo: Path, commit: Commit, variant: str, extra_config: str, files: dict[str, str]
) -> None:
    ctx = build(git_repo, commit, extra_config=extra_config, files={**ADAPTER_FILES, **files})
    with pytest.raises(ship_check.GateError, match="package coverage"):
        ship_check.g1(ctx)


def test_core_subpackage_without_init_is_measured(git_repo: Path, commit: Commit) -> None:
    namespace = {
        "src/receipts/analysis/rates.py": CORE.format(name="analysis.rates"),
        "src/receipts/analysis/glmm.py": '"""Synthetic untested analysis code."""\n' + FILLER,
        "tests/test_core.py": CORE_TEST.replace(
            "from receipts import analysis, claims, hook, ledger, verify",
            "from receipts import claims, hook, ledger, verify\n"
            "from receipts.analysis import rates",
        ).replace(
            "(ledger, claims, verify, analysis, hook)", "(ledger, claims, verify, rates, hook)"
        ),
    }
    ctx = build(git_repo, commit, files=namespace, drop=("src/receipts/analysis/__init__.py",))
    with pytest.raises(ship_check.GateError, match="coverage"):
        ship_check.g1(ctx)


def test_target_that_drops_pytest_args_still_uses_harness_settings(
    git_repo: Path, commit: Commit
) -> None:
    # COVERAGE_RCFILE carries the harness settings even without $(PYTEST_ARGS).
    ctx = build(
        git_repo,
        commit,
        extra_config='\n[tool.coverage.report]\nomit = ["*/client/backends.py"]\n',
        files={**ADAPTER_FILES, "Makefile": MAKEFILE.replace(" $(PYTEST_ARGS)\n", "\n")},
    )
    with pytest.raises(ship_check.GateError, match="package coverage"):
        ship_check.g1(ctx)


def test_target_overriding_the_coverage_config_fails(git_repo: Path, commit: Commit) -> None:
    # The project's own --cov-config after $(PYTEST_ARGS) wins over the harness file.
    ctx = build(
        git_repo,
        commit,
        files={
            **ADAPTER_FILES,
            "project.coveragerc": "[run]\nsource = receipts\nomit = */client/backends.py\n",
            "Makefile": MAKEFILE.replace(
                " $(PYTEST_ARGS)\n", " $(PYTEST_ARGS) --cov-config=project.coveragerc\n"
            ),
        },
    )
    with pytest.raises(ship_check.GateError, match="harness coverage settings"):
        ship_check.g1(ctx)


def test_fast_mode_keeps_the_harness_coverage_settings(git_repo: Path, commit: Commit) -> None:
    files = {
        **ADAPTER_FILES,
        ".coveragerc": "[run]\nsource = receipts\nomit = */client/backends.py\n",
        "tests/test_slow.py": "import pytest\n\n\n@pytest.mark.slow\n"
        "def test_slow_and_broken() -> None:\n    assert False\n",
    }
    ctx = build(git_repo, commit, files=files, fast=True)
    with pytest.raises(ship_check.GateError, match="package coverage"):
        ship_check.g1(ctx)


def test_fast_mode_deselects_slow_tests(git_repo: Path, commit: Commit) -> None:
    files = {
        "tests/test_slow.py": "import pytest\n\n\n@pytest.mark.slow\n"
        "def test_slow_and_broken() -> None:\n    assert False\n",
    }
    ctx = build(git_repo, commit, files=files, fast=True)
    assert "every core module >= 85%" in ship_check.g1(ctx)


# ---------------------------------------------------------------- H01 (old code: PASS)


def test_comment_only_contract_file_is_rejected(git_repo: Path, commit: Commit) -> None:
    files = {
        **ADAPTER_FILES,
        "src/receipts/sandbox/__init__.py": '"""Synthetic sandbox package."""\n',
        "src/receipts/sandbox/backends.py": ADAPTER,
        "tests/contract/test_backends.py": "# fixtures/recorded\n",
    }
    ctx = build(
        git_repo, commit, omit='["*/client/backends.py", "*/sandbox/backends.py"]', files=files
    )
    with pytest.raises(ship_check.GateError, match="contract test"):
        ship_check.g1(ctx)


def test_docstring_only_contract_for_core_file_is_rejected(git_repo: Path, commit: Commit) -> None:
    files = {
        "src/receipts/verify/checkers.py": '"""Synthetic untested core code."""\n' + FILLER,
        "tests/contract/test_checkers.py": '"""See tests/fixtures/recorded/."""\n',
    }
    ctx = build(git_repo, commit, omit='["*/verify/checkers.py"]', files=files)
    with pytest.raises(ship_check.GateError, match="contract test"):
        ship_check.g1(ctx)


def test_glob_named_contract_file_is_rejected(git_repo: Path, commit: Commit) -> None:
    files = {
        "src/receipts/ledger/remote.py": '"""Synthetic untested core code."""\n' + FILLER,
        "tests/contract/test_rem*.py": "# fixtures/recorded\n",
    }
    ctx = build(git_repo, commit, omit='["*/ledger/rem*"]', files=files)
    with pytest.raises(ship_check.GateError, match="contract test"):
        ship_check.g1(ctx)


def test_skipped_contract_test_is_rejected(git_repo: Path, commit: Commit) -> None:
    needs_isolation()
    files = {**ADAPTER_FILES, "tests/contract/test_backends.py": CONTRACT_SKIPPED}
    ctx = build(git_repo, commit, omit='["*/client/backends.py"]', files=files)
    with pytest.raises(ship_check.GateError, match="skip"):
        ship_check.g1(ctx)


def test_import_only_contract_test_is_rejected(git_repo: Path, commit: Commit) -> None:
    needs_isolation()
    files = {
        **ADAPTER_FILES,
        "tests/fixtures/recorded/backends/reply.json": FIXTURE,
        "tests/contract/test_backends.py": CONTRACT_IMPORT_ONLY,
    }
    ctx = build(git_repo, commit, omit='["*/client/backends.py"]', files=files)
    with pytest.raises(ship_check.GateError, match="calls no code"):
        ship_check.g1(ctx)


def test_contract_test_must_read_a_committed_recorded_fixture(
    git_repo: Path, commit: Commit
) -> None:
    needs_isolation()
    files = {**ADAPTER_FILES, "tests/contract/test_backends.py": CONTRACT_NO_FIXTURE}
    ctx = build(git_repo, commit, omit='["*/client/backends.py"]', files=files)
    with pytest.raises(ship_check.GateError, match="recorded"):
        ship_check.g1(ctx)


def test_omit_pattern_matching_no_package_file_drops_nothing(
    git_repo: Path, commit: Commit
) -> None:
    # A stale or test-only pattern removes no package code, so it needs no contract test.
    ctx = build(git_repo, commit, omit='["*/client/gone.py", "*/tests/*"]')
    assert "every core module >= 85%" in ship_check.g1(ctx)


# ---------------------------------------------------------------- H02 (old code: FAIL)


@pytest.mark.parametrize("contract", [CONTRACT_PATHLIB, CONTRACT_CONSTANT, CONTRACT_SPELLED])
def test_real_contract_test_allows_the_omission(
    git_repo: Path, commit: Commit, contract: str
) -> None:
    needs_isolation()
    files = {
        **ADAPTER_FILES,
        "tests/fixtures/recorded/backends/reply.json": FIXTURE,
        "tests/contract/test_backends.py": contract,
    }
    ctx = build(git_repo, commit, omit='["*/client/backends.py"]', files=files)
    evidence = ship_check.g1(ctx)
    assert "every core module >= 85%" in evidence and "contract" in evidence


# ---------------------------------------------------------------- H03, G1 part (old code: PASS)


BROKEN = {"tests/test_broken.py": "def test_broken() -> None:\n    assert False\n"}


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PYTEST_ADDOPTS", "--deselect tests/test_broken.py::test_broken"),
        ("PYTEST_ARGS", "-k 'not broken'"),
        ("MAKEFLAGS", " -- PYTEST_ARGS=--deselect=tests/test_broken.py::test_broken"),
    ],
)
def test_caller_environment_cannot_deselect_failing_tests(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    ctx = build(git_repo, commit, files=BROKEN)
    monkeypatch.setenv(name, value)
    with pytest.raises(ship_check.GateError, match="make test failed"):
        ship_check.g1(ctx)


def test_caller_coverage_rcfile_is_ignored(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = build(git_repo, commit, files=ADAPTER_FILES)
    rcfile = tmp_path / "outside.coveragerc"
    rcfile.write_text("[run]\nsource = receipts\nomit = */client/backends.py\n")
    monkeypatch.setenv("COVERAGE_RCFILE", str(rcfile))
    with pytest.raises(ship_check.GateError, match="package coverage"):
        ship_check.g1(ctx)


def test_synthetic_projects_never_sync_the_shared_venv(git_repo: Path, commit: Commit) -> None:
    ctx = build(git_repo, commit)
    dry = subprocess.run(
        ["make", "-n", "setup"], cwd=ctx.clone, capture_output=True, text=True, check=True
    )
    assert "uv sync" not in dry.stdout
