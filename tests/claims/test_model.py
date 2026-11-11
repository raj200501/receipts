"""Tests for receipts.claims.model. Reports and model replies here are hand-written fakes."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import pytest

from receipts.claims.model import (
    CLAIM_JSON_SCHEMA,
    PARAM_SPECS,
    REQUIRED_PARAMS,
    ModelExtractor,
    build_prompt,
    grounded_params,
    normalize_command,
    normalize_params,
    parse_response,
    schema_errors,
)
from receipts.claims.segment import Unit, segment
from receipts.claims.types import Claim, ClaimType

# Hand-written test input (synthetic), not model output.
REPORT = (
    "I wired the retry logic into the HTTP client.\n\n"
    "The old shim is gone from `src/compat.py`.\n\n"
    "Unit tests pass (`pytest tests/unit`).\n"
)


def reply(*claims: dict[str, object]) -> str:
    """A fake model reply holding ``claims``."""
    return json.dumps({"claims": list(claims)})


def item(
    claim_type: str,
    text: str,
    params: dict[str, object] | None = None,
    negated: bool = False,
    passage: int = 1,
) -> dict[str, object]:
    return {
        "passage": passage,
        "type": claim_type,
        "text": text,
        "params": params or {},
        "negated": negated,
    }


def passage_of(prompt: str, text: str) -> int:
    """The number of the prompt passage ("P2: ...") that contains ``text`` (0 for none)."""
    for line in prompt.splitlines():
        head, _, body = line.partition(": ")
        if head.startswith("P") and head[1:].isdigit() and text in body:
            return int(head[1:])
    return 0


class FakeModel:
    """A fake ``complete`` callable that records prompts and answers from a function."""

    def __init__(self, answer: Callable[[str], str]) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer(prompt)


# --- schema ----------------------------------------------------------------------------


def test_schema_lists_every_claim_type_and_known_param() -> None:
    claims = CLAIM_JSON_SCHEMA["properties"]["claims"]
    entry = claims["items"]
    assert CLAIM_JSON_SCHEMA["required"] == ["claims"] and claims["type"] == "array"
    assert entry["properties"]["type"]["enum"] == [t.value for t in ClaimType]
    assert entry["required"] == ["passage", "type", "text", "params", "negated"]
    assert entry["properties"]["passage"] == {"type": "integer", "minimum": 1}
    assert entry["additionalProperties"] is False
    params = entry["properties"]["params"]
    assert params["additionalProperties"] is False
    known = {key for specs in PARAM_SPECS.values() for key in specs}
    assert set(params["properties"]) == known
    assert params["properties"]["passed"] == {"type": ["integer", "null"], "minimum": 0}
    assert params["properties"]["path"] == {"type": ["string", "null"]}
    json.dumps(CLAIM_JSON_SCHEMA)  # serializable as is


def test_param_specs_cover_every_type_and_required_params_are_known() -> None:
    assert set(PARAM_SPECS) == set(ClaimType)
    for claim_type, required in REQUIRED_PARAMS.items():
        assert required <= set(PARAM_SPECS[claim_type])
    assert REQUIRED_PARAMS[ClaimType.RAN_COMMAND] == {"command"}
    assert PARAM_SPECS[ClaimType.TASK_COMPLETE] == {}


def test_schema_errors_accepts_a_valid_reply() -> None:
    data = json.loads(reply(item("tests_pass", "Unit tests pass", {"scope": "unit"})))
    assert schema_errors(data, CLAIM_JSON_SCHEMA) == []
    assert schema_errors({"claims": []}, CLAIM_JSON_SCHEMA) == []


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ([], "$: expected object"),
        ({}, "missing 'claims'"),
        ({"claims": [], "extra": 1}, "unexpected key 'extra'"),
        ({"claims": {}}, "$.claims: expected array"),
        ({"claims": [item("nope", "x")]}, "is not one of the allowed values"),
        ({"claims": [item("other", "")]}, "shorter than 1 characters"),
        ({"claims": [item("test_count", "x", {"passed": -1})]}, "-1 is below 0"),
        ({"claims": [item("test_count", "x", {"passed": True})]}, "expected integer or null"),
        ({"claims": [item("test_count", "x", {"passed": "3"})]}, "expected integer or null"),
        ({"claims": [item("other", "x", {"colour": "red"})]}, "unexpected key 'colour'"),
        (
            {"claims": [{"passage": 1, "type": "other", "text": "x", "params": {}}]},
            "missing 'negated'",
        ),
        ({"claims": [item("other", "x", passage=0)]}, "0 is below 1"),
        (
            {"claims": [{"type": "other", "text": "x", "params": {}, "negated": False}]},
            "missing 'passage'",
        ),
        (
            {"claims": [item("other", "x", negated="no")]},  # type: ignore[arg-type]  # not a bool
            "negated: expected boolean",
        ),
    ],
)
def test_schema_errors_reports_each_problem(data: object, fragment: str) -> None:
    errors = schema_errors(data, CLAIM_JSON_SCHEMA)
    assert any(fragment in error for error in errors), errors


def test_schema_errors_paths_name_the_offending_item() -> None:
    data = {"claims": [item("other", "ok"), item("other", "x", {"tool": 3})]}
    assert schema_errors(data, CLAIM_JSON_SCHEMA) == [
        "$.claims[1].params.tool: expected string or null"
    ]


# --- normalization -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("`pytest -q`", ("pytest -q", False)),
        ("$ npm test", ("npm test", False)),
        ("the full test suite", ("the full test suite", True)),
        ("the tests", ("the tests", False)),
        ("the slow tests", ("the tests", True)),
        ("bundle exec rspec", ("bundle exec rspec", False)),
        ("./gradlew test", ("./gradlew test", False)),
        ("ran the linter", None),
        ("the", None),
        ("", None),
        ("123 456", None),
        ("(cd app)", None),
    ],
)
def test_normalize_command(raw: str, expected: tuple[str, bool] | None) -> None:
    assert normalize_command(raw) == expected


@pytest.mark.parametrize(
    ("claim_type", "params", "negated", "expected"),
    [
        # keys and value types
        (ClaimType.TESTS_PASS, {"path": "a.py"}, False, None),
        (ClaimType.TEST_COUNT, {"passed": "12"}, False, None),
        (ClaimType.TEST_COUNT, {"passed": True}, False, None),
        (ClaimType.TEST_COUNT, {"passed": -2}, False, None),
        (ClaimType.LINT_CLEAN, {"tool": 3}, False, None),
        (ClaimType.LINT_CLEAN, {"tool": None}, False, (ClaimType.LINT_CLEAN, {}, False)),
        (
            ClaimType.LINT_CLEAN,
            {"tool": " `ruff` "},
            False,
            (ClaimType.LINT_CLEAN, {"tool": "ruff"}, False),
        ),
        (ClaimType.TASK_COMPLETE, {}, False, (ClaimType.TASK_COMPLETE, {}, False)),
        # required params
        (ClaimType.FILE_MODIFIED, {}, False, None),
        (ClaimType.FILE_MODIFIED, {"path": "  "}, False, None),
        (ClaimType.BUG_FIXED, {"description": None}, False, None),
        # paths
        (
            ClaimType.FILE_MODIFIED,
            {"path": "`src/app.py:12`"},
            False,
            (ClaimType.FILE_MODIFIED, {"path": "src/app.py"}, False),
        ),
        (ClaimType.FILE_UNCHANGED, {"path": "the CLI"}, False, None),
        (
            ClaimType.TESTS_ADDED,
            {"path": "the parser", "target": "empty input"},
            False,
            (ClaimType.TESTS_ADDED, {"target": "empty input"}, False),
        ),
        (
            ClaimType.TESTS_ADDED,
            {"path": "tests/test_io.py::test_roundtrip"},
            False,
            (ClaimType.TESTS_ADDED, {"path": "tests/test_io.py"}, False),
        ),
        # commands
        (
            ClaimType.RAN_COMMAND,
            {"command": "`pytest -q`"},
            False,
            (ClaimType.RAN_COMMAND, {"command": "pytest -q"}, False),
        ),
        (ClaimType.RAN_COMMAND, {"command": "ran the linter"}, False, None),
        (ClaimType.RAN_COMMAND, {"command": "the integration tests"}, True, None),
        (
            ClaimType.RAN_COMMAND,
            {"command": "the integration tests"},
            False,
            (ClaimType.RAN_COMMAND, {"command": "the integration tests"}, False),
        ),
        (
            ClaimType.RAN_COMMAND,
            {"command": "the linter"},
            True,
            (ClaimType.RAN_COMMAND, {"command": "the linter"}, True),
        ),
        # dependencies
        (
            ClaimType.DEPENDENCY_ADDED,
            {"name": "requests>=2.32"},
            False,
            (ClaimType.DEPENDENCY_ADDED, {"name": "requests", "version": "2.32"}, False),
        ),
        (
            ClaimType.DEPENDENCY_UPDATED,
            {"name": "lodash", "version": "v4.17.21"},
            False,
            (ClaimType.DEPENDENCY_UPDATED, {"name": "lodash", "version": "4.17.21"}, False),
        ),
        (
            ClaimType.DEPENDENCY_UPDATED,
            {"name": "lodash@4.17.20", "version": "4.17.21"},
            False,
            (ClaimType.DEPENDENCY_UPDATED, {"name": "lodash", "version": "4.17.21"}, False),
        ),
        (
            ClaimType.DEPENDENCY_UPDATED,
            {"name": "django", "version": "latest"},
            False,
            (ClaimType.DEPENDENCY_UPDATED, {"name": "django"}, False),
        ),
        (
            ClaimType.DEPENDENCY_REMOVED,
            {"name": "six==1.16"},
            False,
            (ClaimType.DEPENDENCY_REMOVED, {"name": "six"}, False),
        ),
        (ClaimType.DEPENDENCY_ADDED, {"name": "the parser"}, False, None),
        # test counts
        (ClaimType.TEST_COUNT, {}, False, None),
        (ClaimType.TEST_COUNT, {"passed": None, "total": None}, False, None),
        (ClaimType.TEST_COUNT, {"failed": 2}, False, (ClaimType.TESTS_PASS, {}, True)),
        (ClaimType.TEST_COUNT, {"failed": 0}, False, (ClaimType.TEST_COUNT, {"failed": 0}, False)),
        (
            ClaimType.TEST_COUNT,
            {"passed": 12, "total": 13, "failed": 1},
            False,
            (ClaimType.TEST_COUNT, {"passed": 12, "total": 13, "failed": 1}, False),
        ),
        # descriptions keep inline code
        (
            ClaimType.BUG_FIXED,
            {"description": " the off-by-one in `parse_range` "},
            False,
            (ClaimType.BUG_FIXED, {"description": "the off-by-one in `parse_range`"}, False),
        ),
    ],
)
def test_normalize_params(
    claim_type: ClaimType,
    params: dict[str, object],
    negated: bool,
    expected: tuple[ClaimType, dict[str, object], bool] | None,
) -> None:
    assert normalize_params(claim_type, params, negated) == expected


def test_grounded_params_passes_malformed_values_on_and_rejects_empty_commands() -> None:
    # Values of the wrong JSON type are left for normalize_params to reject.
    assert grounded_params({"path": ["a.py"], "passed": True}, "Updated a.py") == {
        "path": ["a.py"],
        "passed": True,
    }
    assert grounded_params({"command": "``"}, "Ran it") is None
    assert grounded_params({"version": "latest", "name": "django"}, "Upgraded django") == {
        "version": "latest",
        "name": "django",
    }


# --- prompt --------------------------------------------------------------------------------


def test_build_prompt_holds_report_passages_and_every_type() -> None:
    units = list(segment(REPORT).units)
    prompt = build_prompt(REPORT, units[:2])
    assert "<report>\n" + REPORT + "\n</report>" in prompt
    assert "P1: I wired the retry logic into the HTTP client." in prompt
    assert "P2: The old shim is gone from `src/compat.py`." in prompt
    assert "P3:" not in prompt
    for claim_type in ClaimType:
        assert f"\n{claim_type.value} " in prompt
    assert '{"claims": [' in prompt and "{{" not in prompt
    assert chr(0x2014) not in prompt  # no em dash in the prompt


# --- responses -------------------------------------------------------------------------------


def test_parse_response_keeps_verbatim_claims_in_report_order() -> None:
    text = reply(
        item("tests_pass", "Unit tests pass", {"scope": "unit"}),
        item(
            "feature_implemented",
            " I wired the retry logic into the HTTP client. ",
            {"description": "the retry logic"},
        ),
    )
    claims = parse_response(text, REPORT)
    assert [c.claim_id for c in claims] == ["c0", "c1"]
    first, second = claims
    assert first.type is ClaimType.FEATURE_IMPLEMENTED and first.extractor == "model"
    assert first.text == "I wired the retry logic into the HTTP client."
    assert REPORT[first.span[0] : first.span[1]] == first.text
    assert second == Claim(
        "c1",
        ClaimType.TESTS_PASS,
        "Unit tests pass",
        (REPORT.index("Unit tests pass"), REPORT.index("Unit tests pass") + 15),
        {"scope": "unit"},
        False,
        "model",
    )


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"claims": {}}',
        '{"items": []}',
        '{"claims": [], "note": "extra"}',
        "{broken",
        "",
    ],
)
def test_parse_response_rejects_malformed_replies(text: str) -> None:
    assert parse_response(text, REPORT) == []


def test_parse_response_finds_json_in_fences_or_prose() -> None:
    body = reply(item("tests_pass", "Unit tests pass"))
    assert len(parse_response(f"```json\n{body}\n```", REPORT)) == 1
    assert len(parse_response(f"Here you go:\n{body}\nThanks.", REPORT)) == 1
    assert parse_response("Here: {not json}", REPORT) == []


def test_parse_response_drops_claims_that_fail_a_check() -> None:
    text = reply(
        item("tests_pass", "All 40 tests pass"),  # not in the report: invented
        item("tests_pass", "unit tests pass"),  # case differs: not verbatim
        item("other", "..."),  # no letter or digit
        item("file_modified", "The old shim is gone", {"path": "the shim"}),  # bad path
        {
            "passage": 1,
            "type": "tests_pass",
            "text": "Unit tests pass",
            "params": {},
            "negated": False,
            "x": 1,
        },
        item("lint_clean", "Unit tests pass", {"scope": "unit"}),  # wrong param for type
        item(
            "file_deleted",
            "The old shim is gone from `src/compat.py`.",
            {"path": "`src/compat.py`"},
        ),
    )
    claims = parse_response(text, REPORT)
    assert [(c.type, dict(c.params)) for c in claims] == [
        (ClaimType.FILE_DELETED, {"path": "src/compat.py"})
    ]


def test_parse_response_within_picks_an_occurrence_inside_the_spans() -> None:
    report = "Done.\n\nThen more work.\n\nDone."
    later = (report.rindex("Done."), len(report))
    text = reply(item("task_complete", "Done."))
    assert [c.span for c in parse_response(text, report)] == [(0, 5)]
    assert [c.span for c in parse_response(text, report, within=[later])] == [later]
    assert parse_response(text, report, within=[(6, 20)]) == []
    assert (
        parse_response(reply(item("task_complete", "Done.", passage=2)), report, within=[later])
        == []
    )


def test_parse_response_places_identical_texts_in_the_passage_they_name() -> None:
    report = "The cache is warm.\n\nSome notes here.\n\nThe cache is warm."
    spans = [u.span for u in segment(report).units]
    text = reply(
        item("other", "The cache is warm.", {"description": "cache warm"}, passage=1),
        item("other", "The cache is warm.", {"description": "cache still warm"}, passage=3),
    )
    claims = parse_response(text, report, within=spans)
    assert [c.span for c in claims] == [spans[0], spans[2]]


#: (claim text, type, params the model gave, params kept or None when the claim is
#: rejected). Identifying params the text never states are invented, so the claim goes;
#: a tool or scope the text does not name is dropped and the claim kept; descriptions may
#: paraphrase. Hand-written test input.
GROUNDING_CASES: list[tuple[str, str, dict[str, object], dict[str, object] | None]] = [
    ("I updated the config", "file_modified", {"path": "src/settings/prod.py"}, None),
    (
        "I updated `src/settings/prod.py:12`",
        "file_modified",
        {"path": "src/settings/prod.py"},
        {"path": "src/settings/prod.py"},
    ),
    ("Updated src/app.py", "file_modified", {"path": "app.py"}, {"path": "app.py"}),
    ("Updated data.py", "file_modified", {"path": "a.py"}, None),
    ("Added a test", "tests_added", {"path": "tests/test_x.py"}, None),
    ("the service", "dependency_added", {"name": "requests", "version": "2.32"}, None),
    ("Added Requests", "dependency_added", {"name": "requests"}, {"name": "requests"}),
    (
        "Added `typing-extensions`",
        "dependency_added",
        {"name": "typing_extensions"},
        {"name": "typing_extensions"},
    ),
    ("Bumped lodash", "dependency_updated", {"name": "lodash", "version": "4.17.21"}, None),
    (
        "Bumped lodash to v4.17.21",
        "dependency_updated",
        {"name": "lodash", "version": "4.17.21"},
        {"name": "lodash", "version": "4.17.21"},
    ),
    ("The cache is warm.", "ran_command", {"command": "pytest -q"}, None),
    ("Ran `$ pytest -q`", "ran_command", {"command": "$ pytest -q"}, {"command": "pytest -q"}),
    (
        "I ran the slow tests",
        "ran_command",
        {"command": "the slow tests"},
        {"command": "the tests"},
    ),
    ("More notes.", "test_count", {"passed": 99, "total": 99}, None),
    ("All 42 tests pass", "test_count", {"passed": 42, "total": 42}, {"passed": 42, "total": 42}),
    ("All 42 tests pass", "test_count", {"passed": 42, "total": 42, "failed": 0}, None),
    (
        "twelve passed, none failed",
        "test_count",
        {"passed": 12, "failed": 0},
        {"passed": 12, "failed": 0},
    ),
    ("Lint is clean", "lint_clean", {"tool": "ruff"}, {}),
    ("ruff is clean", "lint_clean", {"tool": "ruff"}, {"tool": "ruff"}),
    ("The suite is green", "tests_pass", {"scope": "all"}, {}),
    (
        "Fixed the date bug",
        "bug_fixed",
        {"description": "dates before 1970"},
        {"description": "dates before 1970"},
    ),
]


@pytest.mark.parametrize(
    ("text", "claim_type", "params", "kept"), GROUNDING_CASES, ids=[c[0] for c in GROUNDING_CASES]
)
def test_parse_response_requires_params_stated_in_the_text(
    text: str, claim_type: str, params: dict[str, object], kept: dict[str, object] | None
) -> None:
    report = f"Notes. {text} More notes."
    claims = parse_response(reply(item(claim_type, text, params)), report)
    if kept is None:
        assert claims == []
    else:
        assert [dict(c.params) for c in claims] == [kept]


def test_parse_response_applies_normalization() -> None:
    report = "Ran into 1 failing test. Tests: 1 failed."
    text = reply(item("test_count", "Tests: 1 failed.", {"failed": 1}))
    (claim,) = parse_response(text, report)
    assert (claim.type, dict(claim.params), claim.negated) == (ClaimType.TESTS_PASS, {}, True)


# --- extractor ---------------------------------------------------------------------------------


def units_of(report: str) -> Sequence[Unit]:
    return segment(report).units


def test_model_extractor_rejects_a_bad_batch_size() -> None:
    with pytest.raises(ValueError, match="max_units"):
        ModelExtractor(lambda prompt: "", max_units=0)


def test_model_extractor_sends_nothing_without_units() -> None:
    fake = FakeModel(lambda prompt: reply())
    assert ModelExtractor(fake).extract(REPORT, []) == []
    assert fake.prompts == []


def test_model_extractor_batches_units_and_keeps_claims_inside_them() -> None:
    units = units_of(REPORT)
    assert len(units) == 3

    def answer(prompt: str) -> str:
        claims = [
            item(
                "feature_implemented",
                "I wired the retry logic into the HTTP client.",
                {"description": "the retry logic"},
            ),
            item("tests_pass", "Unit tests pass", {"scope": "unit"}),
            item(
                "file_deleted",
                "The old shim is gone from `src/compat.py`.",
                {"path": "src/compat.py"},
            ),
        ]
        for claim in claims:  # each claim names the passage its text is in (0: not sent)
            claim["passage"] = passage_of(prompt, str(claim["text"])) or 99
        return reply(*claims)

    fake = FakeModel(answer)
    claims = ModelExtractor(fake, max_units=2).extract(REPORT, [units[0], units[2]])
    assert len(fake.prompts) == 1
    assert [c.type for c in claims] == [ClaimType.FEATURE_IMPLEMENTED, ClaimType.TESTS_PASS]
    assert [c.claim_id for c in claims] == ["c0", "c1"]
    fake = FakeModel(answer)
    claims = ModelExtractor(fake, max_units=2).extract(REPORT, units)
    assert len(fake.prompts) == 2
    assert "P1: Unit tests pass" in fake.prompts[1]
    assert [c.type for c in claims] == [
        ClaimType.FEATURE_IMPLEMENTED,
        ClaimType.FILE_DELETED,
        ClaimType.TESTS_PASS,
    ]


def test_model_extractor_dedupes_identical_claims_of_one_unit() -> None:
    report = "Unit tests pass (yes, unit tests pass)."
    assert len(units_of(report)) == 1
    text = reply(
        item("tests_pass", "Unit tests pass", {"scope": "unit"}),
        item("tests_pass", "unit tests pass", {"scope": "unit"}),
        item("tests_pass", "Unit tests pass", {"scope": "all"}),
    )
    claims = ModelExtractor(lambda prompt: text).extract(report, units_of(report))
    # the text never says "all", so that scope is dropped, which leaves a different claim
    assert [dict(c.params) for c in claims] == [{"scope": "unit"}, {}]


def test_model_extractor_lets_model_errors_propagate() -> None:
    def broken(prompt: str) -> str:
        raise TimeoutError("model did not answer")

    with pytest.raises(TimeoutError):
        ModelExtractor(broken).extract(REPORT, units_of(REPORT))
