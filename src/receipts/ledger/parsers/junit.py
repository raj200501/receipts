"""Parser for JUnit XML reports (pytest ``--junitxml``, jest-junit, mocha and node reporters).

The report may be embedded in other output (a reporter that writes XML to stdout,
or ``cat report.xml``); the parser takes the span from the first ``<testsuites``
or ``<testsuite`` element (or the XML declaration before it) to the last matching
closing tag. Documents that declare a DOCTYPE or entities are refused, so entity
expansion never runs on untrusted input.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Literal

from receipts.ledger.events import TestCase
from receipts.ledger.parsers.results import ParsedTestRun, make_test_run
from receipts.ledger.parsers.text import strip_ansi

_ROOT_START = re.compile(r"<testsuites?\b")


def _local(tag: str) -> str:
    """Element name without an XML namespace."""
    return tag.rsplit("}", 1)[-1]


def _extract(text: str) -> str | None:
    """The XML span of a JUnit report inside ``text``, or None if there is none."""
    match = _ROOT_START.search(text)
    if match is None:
        return None
    start = match.start()
    declaration = text.rfind("<?xml", 0, start)
    if declaration != -1:
        start = declaration
    closing = "</testsuites>" if text.startswith("<testsuites", match.start()) else "</testsuite>"
    end = text.rfind(closing)
    return text[start : end + len(closing)] if end > match.start() else text[start:]


def _case_name(element: ET.Element) -> str:
    """``classname.name``, or just ``name`` when the class name is empty or repeated in it."""
    name = element.get("name", "")
    classname = element.get("classname", "")
    if not classname or name.startswith(classname):
        return name
    return f"{classname}.{name}"


def parse_junit(text: str) -> ParsedTestRun | None:
    """Parse a JUnit XML report with one or many ``testsuite`` elements.

    Counts come from the ``testcase`` elements themselves (suite attributes are
    often inconsistent): a ``failure`` child means failed, an ``error`` child
    error, a ``skipped`` child skipped, none of them passed. Returns None when
    there is no report, it is malformed or truncated, or it declares a DOCTYPE.
    """
    snippet = _extract(strip_ansi(text))
    if snippet is None or "<!DOCTYPE" in snippet or "<!ENTITY" in snippet:
        return None
    try:
        root = ET.fromstring(snippet)
    except ET.ParseError:
        return None
    if _local(root.tag) not in ("testsuites", "testsuite"):
        return None

    cases: list[TestCase] = []
    failing: list[str] = []
    collection_failures = 0
    for element in root.iter():
        if _local(element.tag) != "testcase":
            continue
        children = {_local(child.tag): child for child in element}
        name = _case_name(element)
        outcome: Literal["passed", "failed", "error", "skipped"]
        if "failure" in children:
            outcome = "failed"
        elif "error" in children:
            outcome = "error"
            if "collection failure" in children["error"].get("message", ""):
                collection_failures += 1
        elif "skipped" in children:
            outcome = "skipped"
        else:
            outcome = "passed"
        cases.append(TestCase(name=name, outcome=outcome))
        if outcome in ("failed", "error"):
            failing.append(name)

    def count(outcome: str) -> int:
        return sum(1 for case in cases if case["outcome"] == outcome)

    passed, failed, skipped = count("passed"), count("failed"), count("skipped")
    return make_test_run(
        "junit",
        passed=passed,
        failed=failed,
        errors=count("error"),
        skipped=skipped,
        failing=list(dict.fromkeys(failing)),
        collection_error=collection_failures > 0 and passed + failed + skipped == 0,
        cases=cases,
    )
