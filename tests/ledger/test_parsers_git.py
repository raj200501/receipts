"""Tests for the git diff, manifest, and hidden-check parsers (hand-written fixtures)."""

from __future__ import annotations

import pytest

from receipts.ledger.parsers.git import (
    merge_diff_files,
    parse_git_diff,
    parse_name_status,
    parse_numstat,
    split_rename,
    unquote_path,
)
from receipts.ledger.parsers.hidden import parse_hidden_check_list, parse_hidden_checks
from receipts.ledger.parsers.manifests import (
    dependency_changes,
    is_manifest,
    manifest_kind,
    normalize_name,
    parse_dependencies,
    split_requirement,
)

from .helpers import fixture


def test_numstat() -> None:
    files = parse_numstat(fixture("git/numstat.txt"))
    assert files == [
        {"path": "src/calc.py", "status": "M", "added": 12, "removed": 3},
        {
            "path": "docs/new/guide.md",
            "status": "R",
            "added": 0,
            "removed": 0,
            "old_path": "docs/old/guide.md",
        },
        {"path": "tests/test_calc.py", "status": "M", "added": 5, "removed": 0},
        {"path": "assets/logo.png", "status": "M", "added": 0, "removed": 0},
        {"path": "src/legacy.py", "status": "M", "added": 0, "removed": 7},
        {"path": "src/café.py", "status": "M", "added": 4, "removed": 1},
        {
            "path": "README.rst",
            "status": "R",
            "added": 2,
            "removed": 2,
            "old_path": "README.md",
        },
    ]


def test_name_status_and_merge() -> None:
    files = parse_git_diff(fixture("git/numstat.txt"), fixture("git/name_status.txt"))
    assert [(f["path"], f["status"], f["added"], f["removed"]) for f in files] == [
        ("src/calc.py", "M", 12, 3),
        ("docs/new/guide.md", "R", 0, 0),
        ("tests/test_calc.py", "A", 5, 0),
        ("assets/logo.png", "M", 0, 0),
        ("src/legacy.py", "D", 0, 7),
        ("src/café.py", "M", 4, 1),
        ("README.rst", "R", 2, 2),
    ]
    assert files[1]["old_path"] == "docs/old/guide.md"
    assert "old_path" not in files[0]


def test_name_status_copies_type_changes_and_unknowns() -> None:
    text = "C75\ta.py\tb.py\nT\tlink\nU\tconflict.txt\nX\tweird\nR100\tonly-one-field\nnot a line\n"
    assert parse_name_status(text) == [
        {"path": "b.py", "status": "A", "added": 0, "removed": 0, "old_path": "a.py"},
        {"path": "link", "status": "M", "added": 0, "removed": 0},
        {"path": "conflict.txt", "status": "M", "added": 0, "removed": 0},
    ]


def test_merge_keeps_numstat_only_entries_and_handles_empty_status() -> None:
    numstat = parse_numstat("1\t0\ta.py\n2\t2\tb.py\n")
    status = parse_name_status("A\ta.py\n")
    merged = merge_diff_files(status, numstat)
    assert [(f["path"], f["status"], f["added"]) for f in merged] == [
        ("a.py", "A", 1),
        ("b.py", "M", 2),
    ]
    assert merge_diff_files([], numstat) == numstat
    assert parse_git_diff("", "") == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain.py", "plain.py"),
        ('"caf\\303\\251.py"', "caf\u00e9.py"),
        ('"tab\\there\\"q\\\\"', 'tab\there"q\\'),
        ('"bell\\a"', "bell\a"),
        ('"bad\\377"', "bad\ufffd"),
        ('"x\\"', "x\\"),
        ('"\\q"', "q"),
        ('"x\\\u00e9"', "x?"),
        ('""', ""),
        ('"', '"'),
    ],
)
def test_unquote_path(raw: str, expected: str) -> None:
    assert unquote_path(raw) == expected


def test_split_rename_forms() -> None:
    assert split_rename("a.py => b.py") == ("a.py", "b.py")
    assert split_rename("src/{ => sub}/x.py") == ("src/x.py", "src/sub/x.py")
    assert split_rename("{old => new}/x.py") == ("old/x.py", "new/x.py")
    assert split_rename('"d\\303\\251/{a => b}.txt"') == ("dé/a.txt", "dé/b.txt")
    assert split_rename('"a\\tb" => "c"') == ("a\tb", "c")
    assert split_rename("plain.py") is None


def test_manifest_kinds() -> None:
    assert manifest_kind("pyproject.toml") == "pyproject"
    assert manifest_kind("web/package.json") == "package"
    assert manifest_kind("requirements.txt") == "requirements"
    assert manifest_kind("requirements-dev.txt") == "requirements"
    assert manifest_kind("requirements/base.txt") == "requirements"
    assert manifest_kind("requirements.in") == "requirements"
    assert manifest_kind("backend\\requirements.txt") == "requirements"
    assert manifest_kind("package-lock.json") is None
    assert manifest_kind("notes.txt") is None
    assert is_manifest("pyproject.toml") and not is_manifest("setup.cfg")


def test_split_requirement() -> None:
    assert split_requirement("rich[jupyter] >= 13.7") == ("rich", "[jupyter] >= 13.7")
    assert split_requirement("requests") == ("requests", "")
    assert split_requirement("pkg @ https://example.invalid/p.whl") == (
        "pkg",
        "@ https://example.invalid/p.whl",
    )
    assert split_requirement("https://example.invalid/p.whl") is None
    assert split_requirement("git+https://example.invalid/x.git") is None
    assert split_requirement("./local/path") is None
    assert normalize_name("Py.YAML__x") == "py-yaml-x"


def test_requirements_changes() -> None:
    changes = dependency_changes(
        "requirements.txt",
        fixture("manifests/requirements_old.txt"),
        fixture("manifests/requirements_new.txt"),
    )
    assert changes == [
        {
            "manifest": "requirements.txt",
            "name": "acme-toolkit",
            "change": "added",
            "old": None,
            "new": "-e git+https://example.invalid/acme/toolkit.git@v1.2#egg=acme-toolkit",
        },
        {
            "manifest": "requirements.txt",
            "name": "click",
            "change": "removed",
            "old": ">=8,<9",
            "new": None,
        },
        {
            "manifest": "requirements.txt",
            "name": "requests",
            "change": "changed",
            "old": "==2.31.0",
            "new": "==2.32.3",
        },
        {
            "manifest": "requirements.txt",
            "name": "rich",
            "change": "added",
            "old": None,
            "new": "[jupyter]>=13.7",
        },
    ]


def test_requirements_duplicate_names_with_markers_are_merged() -> None:
    deps = parse_dependencies(
        "requirements.txt", "numpy<2; python_version<'3.9'\nnumpy>=2; python_version>='3.9'\n"
    )
    assert deps == {
        ("requirements", "numpy"): (
            "numpy",
            "<2; python_version<'3.9' | >=2; python_version>='3.9'",
        )
    }


def test_pyproject_changes() -> None:
    changes = dependency_changes(
        "pyproject.toml",
        fixture("manifests/pyproject_old.toml"),
        fixture("manifests/pyproject_new.toml"),
    )
    assert [(c["name"], c["change"], c["old"], c["new"]) for c in changes] == [
        ("httpx", "changed", ">=0.27", ">=0.28"),
        ("openpyxl", "added", None, ">=3.1"),
        ("ruff", "removed", ">=0.5", None),
        ("tenacity", "added", None, ">=8.2"),
    ]


def test_poetry_changes() -> None:
    changes = dependency_changes(
        "pyproject.toml",
        fixture("manifests/poetry_old.toml"),
        fixture("manifests/poetry_new.toml"),
    )
    assert [(c["name"], c["change"], c["old"], c["new"]) for c in changes] == [
        ("legacy-lib", "removed", "1.0.0", None),
        ("orjson", "added", None, "^3.10"),
        ("pytest-cov", "added", None, "^5.0"),
        ("requests", "changed", "^2.31", "^2.32"),
    ]


def test_poetry_specs_and_legacy_dev_dependencies() -> None:
    text = (
        "[tool.poetry.dependencies]\n"
        'a = { version = "^1" }\n'
        'b = { git = "https://example.invalid/b.git", branch = "main" }\n'
        '[tool.poetry.dev-dependencies]\nc = "*"\n'
    )
    deps = parse_dependencies("pyproject.toml", text)
    assert deps == {
        ("poetry", "a"): ("a", "^1"),
        ("poetry", "b"): ("b", '{"branch":"main","git":"https://example.invalid/b.git"}'),
        ("poetry-dev", "c"): ("c", "*"),
    }


def test_package_json_changes() -> None:
    changes = dependency_changes(
        "web/package.json",
        fixture("manifests/package_old.json"),
        fixture("manifests/package_new.json"),
    )
    assert changes == [
        {
            "manifest": "web/package.json",
            "name": "eslint",
            "change": "changed",
            "old": "^8.57.0",
            "new": "^9.9.0",
        },
        {
            "manifest": "web/package.json",
            "name": "express",
            "change": "changed",
            "old": "^4.18.2",
            "new": "^4.19.2",
        },
        {
            "manifest": "web/package.json",
            "name": "fsevents",
            "change": "added",
            "old": None,
            "new": "^2.3.3",
        },
        {
            "manifest": "web/package.json",
            "name": "lodash",
            "change": "removed",
            "old": "^4.17.21",
            "new": None,
        },
        {
            "manifest": "web/package.json",
            "name": "zod",
            "change": "added",
            "old": None,
            "new": "^3.23.8",
        },
    ]


def test_created_deleted_unknown_and_unparseable_manifests() -> None:
    created = dependency_changes("package.json", None, '{"dependencies": {"a": {"x": 1}}}')
    assert created == [
        {"manifest": "package.json", "name": "a", "change": "added", "old": None, "new": '{"x":1}'}
    ]
    deleted = dependency_changes("requirements.txt", "a==1\n", None)
    assert [(c["name"], c["change"]) for c in deleted] == [("a", "removed")]
    assert dependency_changes("setup.cfg", "x", "y") == []
    assert dependency_changes("package.json", "{broken", '{"dependencies": {"a": "1"}}') == []
    assert dependency_changes("pyproject.toml", "[project]\n", "not = [toml") == []
    assert parse_dependencies("setup.cfg", "") is None
    assert parse_dependencies("package.json", "[1, 2]") == {}


def test_moving_a_dependency_between_sections_is_remove_plus_add() -> None:
    old = '[project]\ndependencies = ["rich>=13"]\n'
    new = '[dependency-groups]\ndev = ["rich>=13"]\n'
    changes = dependency_changes("pyproject.toml", old, new)
    # sorted by name, then section: "group:dev" before "project"
    assert [(c["name"], c["change"]) for c in changes] == [("rich", "added"), ("rich", "removed")]
    assert (
        dependency_changes("pyproject.toml", '[project]\ndependencies = "x"\n', old)[0]["change"]
        == "added"
    )


def test_hidden_checks_mixed() -> None:
    data = parse_hidden_checks(fixture("hidden/mixed.txt"))
    assert data == {
        "passed": 2,
        "failed": 1,
        "total": 3,
        "checks": [
            {"name": "div_raises_on_zero", "passed": True, "requirement": "R1"},
            {"name": "neg_handles_zero", "passed": False, "requirement": "R2"},
            {"name": "docs_mention_div", "passed": True},
        ],
        "source": "snapshot",
    }


def test_hidden_checks_trailing_blank_lines_and_source() -> None:
    data = parse_hidden_checks(fixture("hidden/all_pass.txt") + "\n\n", source="harness")
    assert data is not None
    assert (data["passed"], data["failed"], data["total"], data["source"]) == (2, 0, 2, "harness")
    assert parse_hidden_checks('{"checks": []}') == {
        "passed": 0,
        "failed": 0,
        "total": 0,
        "checks": [],
        "source": "snapshot",
    }


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n\n",
        fixture("hidden/not_last_line.txt"),
        fixture("hidden/bad_types.txt"),
        "[1, 2]",
        '{"checks": {}}',
        '{"checks": [1]}',
        '{"checks": [{"name": "", "passed": true}]}',
        '{"checks": [{"name": "a", "passed": 1}]}',
        '{"checks": [{"name": "a", "passed": true, "requirement": 2}]}',
        "{not json",
    ],
)
def test_hidden_checks_fail_closed(text: str) -> None:
    assert parse_hidden_check_list(text) is None
    assert parse_hidden_checks(text) is None
