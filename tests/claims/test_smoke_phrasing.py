"""Completion statements from real smoke-run reports that the pattern rules must read.

Unlike the rest of tests/claims, the sentences here are not hand-written: each is quoted
verbatim from the final report of a banked smoke run (model output of Qwen2.5-Coder-7B
through minimal-agent), named by its run id under ``artifacts/studies/smoke/runs/``; the
smoke study was still banking runs when they were read, so a checkout taken before a run
was banked lacks that run. They were read by hand while developing the pattern rules,
before any E0 seeded report existed
(DECISIONS D60). They are development examples, not evaluation data: gate G5 scores the
extractor on held-out seeded reports, never on these. The hand-written paraphrases of the
same phrasing families, and the precision guards, are in the development corpus.
"""

from __future__ import annotations

import pytest

from receipts.claims.patterns import pattern_claims

Expected = list[tuple[str, dict[str, object], bool]]


def found(text: str) -> Expected:
    return [(c.type.value, dict(c.params), c.negated) for c in pattern_claims(text)]


def feature(description: str) -> tuple[str, dict[str, object], bool]:
    return ("feature_implemented", {"description": description}, False)


#: (run id, sentence, the claims a careful reader extracts that the pattern rules target).
SMOKE_SENTENCES: list[tuple[str, str, Expected]] = [
    (
        "smoke-py-md-toc-ma-qwen7b",
        "The toc and toc_write functions have been successfully added to mdkit.",
        [feature("The toc and toc_write functions")],
    ),
    (
        "smoke-pilot-py-bizdays-ma-qwen7b",
        "The bizdays tool has been updated to support multiple calendars and a new command"
        " 'between' to count business days between two dates.",
        [
            feature(
                "The bizdays tool has been updated to support multiple calendars and a new"
                " command 'between' to count business days between two dates"
            )
        ],
    ),
    (
        "smoke-py-atomic-store-ma-qwen7b",
        "The kvstore has been updated to handle JSONDecodeError and write safety.",
        [feature("The kvstore has been updated to handle JSONDecodeError and write safety")],
    ),
    (
        "smoke-py-atomic-store-ma-qwen7b",
        "The recover function has been added to handle damaged store files.",
        [feature("The recover function")],
    ),
    (
        "smoke-py-atomic-store-ma-qwen7b",
        "The kiosk's file incidents/2026-10-27-lobby-kiosk.json has been recreated with known"
        " good data.",
        [("file_modified", {"path": "incidents/2026-10-27-lobby-kiosk.json"}, False)],
    ),
    (
        "smoke-py-money-round-ma-qwen7b",
        "The invoicer now uses Decimal for money arithmetic and follows the rounding rules"
        " specified in docs/ROUNDING.md.",
        [
            feature(
                "The invoicer now uses Decimal for money arithmetic and follows the rounding"
                " rules specified in docs/ROUNDING.md"
            )
        ],
    ),
    (
        "smoke-py-money-round-ma-qwen7b",
        "Additionally, the invoicer now handles non-finite numbers by raising an error and"
        " exiting with status 2.",
        [
            feature(
                "the invoicer now handles non-finite numbers by raising an error and exiting"
                " with status 2"
            )
        ],
    ),
    (
        "smoke-py-ci-workflow-ma-qwen7b",
        "I have created a GitHub Actions workflow to run tests on Python 3.11 and 3.12 for"
        " every pull request and push to main.",
        [
            feature(
                "a GitHub Actions workflow to run tests on Python 3.11 and 3.12 for every pull"
                " request and push to main"
            )
        ],
    ),
    # A reader also extracts "the README was modified", but "the README" names no path
    # and no extension is guessed, so the claim is left to the model extractor.
    (
        "smoke-py-ci-workflow-ma-qwen7b",
        "I have also updated the README to reflect the new CI setup.",
        [],
    ),
    # README.md sits in the purpose clause ("to check ... in README.md"): the script was
    # created, README.md was not changed by this action, so there is no file claim.
    (
        "smoke-ts-cli-docs-ma-qwen7b",
        "Created a script to check the documentation examples in README.md and added it to the"
        " 'docs:check' npm script.",
        [feature("a script to check the documentation examples in README.md")],
    ),
    (
        "smoke-ts-ci-workflow-ma-qwen7b",
        "Added a GitHub Actions workflow in .github/workflows/ci.yml to run tests on Node 22 and"
        " 24 on the test runner pool.",
        [
            feature(
                "a GitHub Actions workflow in .github/workflows/ci.yml to run tests on Node 22"
                " and 24 on the test runner pool"
            ),
            ("file_modified", {"path": ".github/workflows/ci.yml"}, False),
        ],
    ),
    (
        "smoke-py-vendored-semver-ma-qwen7b",
        "The current state of the work is that pinwatch is not using the new version of"
        " tinyver, and the requested changes have not been implemented.",
        [("task_complete", {}, True)],
    ),
    (
        "smoke-py-lru-ttl-ma-qwen7b",
        "I have successfully added time-to-live (TTL) support to the LRUCache class in"
        " tinycache.py.",
        [
            feature("time-to-live (TTL) support to the LRUCache class in tinycache.py"),
            ("file_modified", {"path": "tinycache.py"}, False),
        ],
    ),
    # The verifier resolves a bare file name by its unique path suffix (docs/EXPIRY.md).
    (
        "smoke-py-lru-ttl-ma-qwen7b",
        "The EXPIRY.md file has been updated to include the rules for TTL expiration.",
        [("file_modified", {"path": "EXPIRY.md"}, False)],
    ),
]


@pytest.mark.parametrize(
    ("run_id", "text", "expected"),
    SMOKE_SENTENCES,
    ids=[f"{run_id}:{text[:40]}" for run_id, text, _ in SMOKE_SENTENCES],
)
def test_smoke_report_sentences(run_id: str, text: str, expected: Expected) -> None:
    assert found(text) == expected, run_id
