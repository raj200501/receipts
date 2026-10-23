"""Pure parsers from tool output to ledger payloads (text in, payload dicts out).

Every parser returns None (or an empty list) when the output is not recognized;
none of them raises on malformed input. :func:`analyze_output` runs all of them
on one command's output and resolves overlaps between frameworks.

Test, lint, and type-check parsers return :mod:`~receipts.ledger.parsers.results`
types, which lack ``command_seq`` and ``source``; the recorder adds both.
"""

from receipts.ledger.parsers.detect import (
    DerivedRuns,
    analyze_output,
    command_hints,
    is_quiet,
    is_viewer_command,
)
from receipts.ledger.parsers.git import (
    merge_diff_files,
    parse_git_diff,
    parse_name_status,
    parse_numstat,
    unquote_path,
)
from receipts.ledger.parsers.hidden import (
    hidden_check_data,
    parse_hidden_check_list,
    parse_hidden_checks,
)
from receipts.ledger.parsers.junit import parse_junit
from receipts.ledger.parsers.linters import (
    parse_eslint,
    parse_flake8,
    parse_format_check,
    parse_ruff,
)
from receipts.ledger.parsers.manifests import (
    dependency_changes,
    is_manifest,
    manifest_kind,
    normalize_name,
)
from receipts.ledger.parsers.node import parse_jest, parse_mocha, parse_node_test, parse_vitest
from receipts.ledger.parsers.python_tests import parse_pytest, parse_unittest
from receipts.ledger.parsers.results import (
    ParsedLint,
    ParsedTestRun,
    ParsedTypecheck,
    to_lint_run,
    to_test_run,
    to_typecheck_run,
)
from receipts.ledger.parsers.text import clean_lines, strip_ansi
from receipts.ledger.parsers.typecheckers import parse_mypy, parse_pyright, parse_tsc

__all__ = [
    "DerivedRuns",
    "ParsedLint",
    "ParsedTestRun",
    "ParsedTypecheck",
    "analyze_output",
    "clean_lines",
    "command_hints",
    "dependency_changes",
    "hidden_check_data",
    "is_manifest",
    "is_quiet",
    "is_viewer_command",
    "manifest_kind",
    "merge_diff_files",
    "normalize_name",
    "parse_eslint",
    "parse_flake8",
    "parse_format_check",
    "parse_git_diff",
    "parse_hidden_check_list",
    "parse_hidden_checks",
    "parse_jest",
    "parse_junit",
    "parse_mocha",
    "parse_mypy",
    "parse_name_status",
    "parse_node_test",
    "parse_numstat",
    "parse_pyright",
    "parse_pytest",
    "parse_ruff",
    "parse_tsc",
    "parse_unittest",
    "parse_vitest",
    "strip_ansi",
    "to_lint_run",
    "to_test_run",
    "to_typecheck_run",
    "unquote_path",
]
