"""Model-based claim extraction (``extractor = "model"``) for units no pattern covers.

The model sees the whole report for context and a numbered list of the units to read
(passages ``P1``, ``P2``, ...), and answers with one JSON object that must validate
against :data:`CLAIM_JSON_SCHEMA`. :func:`parse_response` keeps a claim only when:

- it validates against the schema (unknown keys, wrong types, or a type outside
  :class:`~receipts.claims.types.ClaimType` reject it);
- its params are the ones its type carries (:data:`PARAM_SPECS`), with every required
  param present (:data:`REQUIRED_PARAMS`);
- its ``text`` occurs verbatim in the report, inside the passage it names, so the model
  can never invent a claim;
- the text states every identifying param (:func:`grounded_params`): a path, command,
  dependency name, version or test count must appear in the claim text, so the model
  cannot invent the details of a claim either;
- its params normalize the way the pattern extractor normalizes them
  (:func:`normalize_params`): a path must look like a file path, a command like a
  command or a generic phrase such as "the tests", and a dependency name like a
  package name.

Nothing is repaired or guessed: a claim that fails any check is dropped, and a response
that is not a JSON object with a ``claims`` list yields no claims.

This module holds no network or model code. :class:`ModelExtractor` takes an injected
``complete(prompt) -> response_text`` callable (for example a thin adapter over
:class:`receipts.client.wrapper.ModelClient`); tests use a fake.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from receipts.claims.patterns import (
    command_param,
    dependency_param,
    generic_command,
    path_param,
)
from receipts.claims.segment import Span, Unit
from receipts.claims.types import Claim, ClaimType, ParamValue

_STRING = "string"
_COUNT = "integer"

#: The params each claim type may carry, with their JSON types (see receipts.claims.types).
PARAM_SPECS: Mapping[ClaimType, Mapping[str, str]] = {
    ClaimType.TESTS_PASS: {"scope": _STRING},
    ClaimType.TEST_COUNT: {"passed": _COUNT, "total": _COUNT, "failed": _COUNT},
    ClaimType.TESTS_ADDED: {"path": _STRING, "target": _STRING},
    ClaimType.RAN_COMMAND: {"command": _STRING},
    ClaimType.FILE_MODIFIED: {"path": _STRING},
    ClaimType.FILE_CREATED: {"path": _STRING},
    ClaimType.FILE_DELETED: {"path": _STRING},
    ClaimType.FILE_UNCHANGED: {"path": _STRING},
    ClaimType.DEPENDENCY_ADDED: {"name": _STRING, "version": _STRING},
    ClaimType.DEPENDENCY_UPDATED: {"name": _STRING, "version": _STRING},
    ClaimType.DEPENDENCY_REMOVED: {"name": _STRING},
    ClaimType.BUG_FIXED: {"description": _STRING},
    ClaimType.FEATURE_IMPLEMENTED: {"description": _STRING},
    ClaimType.LINT_CLEAN: {"tool": _STRING},
    ClaimType.TYPECHECK_CLEAN: {"tool": _STRING},
    ClaimType.BUILD_SUCCEEDS: {"tool": _STRING},
    ClaimType.COULD_NOT: {"description": _STRING},
    ClaimType.TASK_COMPLETE: {},
    ClaimType.OTHER: {"description": _STRING},
}

#: Params a claim of each type must carry (types not listed require none).
REQUIRED_PARAMS: Mapping[ClaimType, frozenset[str]] = {
    ClaimType.RAN_COMMAND: frozenset({"command"}),
    ClaimType.FILE_MODIFIED: frozenset({"path"}),
    ClaimType.FILE_CREATED: frozenset({"path"}),
    ClaimType.FILE_DELETED: frozenset({"path"}),
    ClaimType.FILE_UNCHANGED: frozenset({"path"}),
    ClaimType.DEPENDENCY_ADDED: frozenset({"name"}),
    ClaimType.DEPENDENCY_UPDATED: frozenset({"name"}),
    ClaimType.DEPENDENCY_REMOVED: frozenset({"name"}),
    ClaimType.BUG_FIXED: frozenset({"description"}),
    ClaimType.FEATURE_IMPLEMENTED: frozenset({"description"}),
    ClaimType.COULD_NOT: frozenset({"description"}),
}


def _param_schemas() -> dict[str, Any]:
    kinds: dict[str, str] = {}
    for specs in PARAM_SPECS.values():
        kinds.update(specs)
    out: dict[str, Any] = {}
    for key in sorted(kinds):
        if kinds[key] == _COUNT:
            out[key] = {"type": [_COUNT, "null"], "minimum": 0}
        else:
            out[key] = {"type": [_STRING, "null"]}
    return out


#: Strict JSON schema of a model response: an object whose ``claims`` list holds one
#: object per claim. It is an object rather than a bare list because structured-output
#: modes require an object at the top level. ``passage`` is the number of the passage
#: (``P1`` is 1) the claim's text comes from, so that two passages with the same text
#: stay apart. ``params`` may hold only known keys (null means not stated); which keys
#: a type may carry is checked in code against :data:`PARAM_SPECS` and
#: :data:`REQUIRED_PARAMS`.
CLAIM_JSON_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "receipts claims",
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["passage", "type", "text", "params", "negated"],
                "properties": {
                    "passage": {"type": _COUNT, "minimum": 1},
                    "type": {"type": _STRING, "enum": [t.value for t in ClaimType]},
                    "text": {"type": _STRING, "minLength": 1},
                    "params": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": _param_schemas(),
                    },
                    "negated": {"type": "boolean"},
                },
            },
        }
    },
}


# --- schema validation ---------------------------------------------------------------

_JSON_TYPES: Mapping[str, Callable[[object], bool]] = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


def schema_errors(instance: object, schema: Mapping[str, Any], where: str = "$") -> list[str]:
    """Every way ``instance`` breaks ``schema``, as readable messages (empty when valid).

    Supports the JSON Schema keywords :data:`CLAIM_JSON_SCHEMA` uses: ``type`` (one
    name or a list), ``enum``, ``required``, ``properties``, ``additionalProperties``
    (true or false), ``items``, ``minLength`` and ``minimum``. Booleans are not
    integers.
    """
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        names = [expected] if isinstance(expected, str) else list(expected)
        if not any(_JSON_TYPES[name](instance) for name in names):
            return [f"{where}: expected {' or '.join(names)}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{where}: {instance!r} is not one of the allowed values")
    if isinstance(instance, str) and len(instance) < int(schema.get("minLength", 0)):
        errors.append(f"{where}: shorter than {schema['minLength']} characters")
    minimum = schema.get("minimum")
    if minimum is not None and isinstance(instance, int) and instance < minimum:
        errors.append(f"{where}: {instance} is below {minimum}")
    if isinstance(instance, dict):
        properties: Mapping[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{where}: missing {key!r}")
        for key, value in instance.items():
            if key in properties:
                errors.extend(schema_errors(value, properties[key], f"{where}.{key}"))
            elif schema.get("additionalProperties", True) is False:
                errors.append(f"{where}: unexpected key {key!r}")
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(schema_errors(item, schema["items"], f"{where}[{index}]"))
    return errors


# --- normalization -------------------------------------------------------------------

_NOT_A_PROGRAM = frozenset(
    {"the", "a", "an", "all", "my", "our", "ran", "run", "i", "we", "it", "they", "both", "some"}
)
_VERSION_NUMBER = re.compile(r"\d+(?:\.\d+)*")
#: A normalized claim: its type, params, and negation.
NormalizedClaim = tuple[ClaimType, dict[str, ParamValue], bool]


def normalize_command(raw: str) -> tuple[str, bool] | None:
    """A ``ran_command`` param as the verifier reads it, and whether it names part of a suite.

    Inline code is kept as written (backticks and a ``$`` prompt removed); a generic
    phrase becomes its canonical form ("the slow tests" becomes "the tests"); a plain
    command line is kept when its first word can be a program. Prose such as "ran the
    linter" gives None.
    """
    text = raw.strip().strip("`").strip()
    command = command_param(text)
    if command is not None:
        return command, False
    generic = generic_command(text)
    if generic is not None:
        return generic
    command = re.sub(r"^(?:\$|>|%)\s+", "", text)
    words = command.split()
    if not words or words[0].lower() in _NOT_A_PROGRAM:
        return None
    if not re.fullmatch(r"[\w./@+-]+", words[0]) or not re.search(r"[A-Za-z]", words[0]):
        return None
    return command, False


def normalize_params(
    claim_type: ClaimType, params: Mapping[str, object], negated: bool = False
) -> NormalizedClaim | None:
    """Check and normalize a model claim's params, or return None to reject the claim.

    Keys must be ones the type carries and values of their JSON type (null means not
    stated); required params must be present. Then, as the pattern extractor does:
    paths go through :func:`~receipts.claims.patterns.path_param` (a file claim with an
    unusable path is rejected; ``tests_added`` drops it), commands through
    :func:`normalize_command`, dependency names through
    :func:`~receipts.claims.patterns.dependency_param` (a version written into the
    name, as in "requests>=2.32", becomes the version), and versions to their first
    number. A negated ``ran_command`` that names part of a suite is rejected, because
    the verifier cannot judge it. A ``test_count`` with no number is rejected, and one
    that only counts failures becomes a negated ``tests_pass`` (a failure count is an
    admission, as in the pattern extractor).

    Returns ``(type, params, negated)``, where the type and negation can change only in
    that last case.
    """
    allowed = PARAM_SPECS[claim_type]
    out: dict[str, ParamValue] = {}
    for key, value in params.items():
        if key not in allowed:
            return None
        if value is None:
            continue
        if allowed[key] == _COUNT:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return None
            out[key] = value
            continue
        if not isinstance(value, str):
            return None
        text = value.strip()
        if key not in ("description",):
            text = text.strip("`").strip()
        if text:
            out[key] = text
    if not REQUIRED_PARAMS.get(claim_type, frozenset()) <= out.keys():
        return None
    if "path" in out:
        path = path_param(str(out["path"]))
        if path is None and claim_type is not ClaimType.TESTS_ADDED:
            return None
        if path is None:
            del out["path"]
        else:
            out["path"] = path
    if claim_type is ClaimType.RAN_COMMAND:
        command = normalize_command(str(out["command"]))
        if command is None or (negated and command[1]):
            return None
        out["command"] = command[0]
    if "name" in out:
        parsed = dependency_param(str(out["name"]))
        if parsed is None:
            return None
        out["name"] = parsed[0]
        if parsed[1] is not None and "version" in allowed:
            out.setdefault("version", parsed[1])
    if "version" in out:
        version = _VERSION_NUMBER.search(str(out["version"]))
        if version is None:
            del out["version"]
        else:
            out["version"] = version.group(0)
    if claim_type is ClaimType.TEST_COUNT:
        if not out:
            return None
        failed = out.get("failed")
        if "passed" not in out and "total" not in out and isinstance(failed, int) and failed:
            return (ClaimType.TESTS_PASS, {}, not negated)
    return (claim_type, out, negated)


def _flat(text: str) -> str:
    """``text`` lowercased, without backticks, with runs of whitespace as one space."""
    return " ".join(text.replace("`", " ").split()).lower()


def _occurs(needle: str, haystack: str, *, suffix: bool = False) -> bool:
    """True when ``needle`` occurs in ``haystack`` and is not part of a longer word.

    With ``suffix`` a path may also end a longer path ("app.py" in "src/app.py").
    """
    if not needle:
        return False
    before = r"(?<![\w.-])" if suffix else r"(?<![\w./-])"
    return re.search(before + re.escape(needle) + r"(?![\w/-])", haystack) is not None


_NUMBER_WORDS: Mapping[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _states_number(text: str, value: int) -> bool:
    """True when ``text`` writes ``value`` as digits or a number word ("12", "twelve")."""
    if re.search(rf"(?<![\w.]){value}(?!\w|\.\d)", text):
        return True
    words = [word for word, number in _NUMBER_WORDS.items() if number == value]
    if value == 0:
        words += ["no", "none"]
    return any(re.search(rf"\b{word}\b", text, re.IGNORECASE) for word in words)


def grounded_params(params: Mapping[str, object], text: str) -> dict[str, object] | None:
    """``params`` with every value checked against the claim ``text``, or None to reject.

    The model must take a claim's details from its text, never add them. Identifying
    params must appear in the text, or the claim is rejected: a path (after
    :func:`~receipts.claims.patterns.path_param`), a command (as written, or its generic
    phrase), a dependency name (case and ``-``/``_`` ignored), a version number, and test
    counts (as digits or number words). A ``tool`` or ``scope`` the text does not name is
    dropped and the claim kept. Descriptions and targets may paraphrase and are kept.
    Values of the wrong type are passed on for :func:`normalize_params` to reject.
    """
    flat = _flat(text)
    out: dict[str, object] = {}
    for key, value in params.items():
        if value is None or key in ("description", "target"):
            out[key] = value
            continue
        if isinstance(value, bool) or not isinstance(value, str | int):
            out[key] = value
            continue
        if isinstance(value, int):
            if not _states_number(text, value):
                return None
            out[key] = value
            continue
        raw = value.strip().strip("`").strip()
        if key == "path":
            path = path_param(raw)
            if path is not None and not _occurs(path, text, suffix=True):
                return None
        elif key == "command":
            command = normalize_command(raw)
            spoken = [_flat(raw), _flat(re.sub(r"^(?:\$|>|%)\s+", "", raw))]
            if command is not None:
                spoken.append(_flat(command[0]))
            if not any(_occurs(phrase, flat) for phrase in spoken):
                return None
        elif key == "name":
            parsed = dependency_param(raw)
            name = (parsed[0] if parsed else raw).lower().replace("_", "-")
            if not _occurs(name, flat.replace("_", "-")):
                return None
        elif key == "version":
            version = _VERSION_NUMBER.search(raw)
            if version is not None and version.group(0) not in text:
                return None
        elif key in ("tool", "scope") and not _occurs(_flat(raw), flat):
            continue  # "lint is clean" names no tool: keep the claim, drop the guess
        out[key] = value
    return out


# --- prompt and response ---------------------------------------------------------------

_TYPE_TABLE = """\
tests_pass           scope: "all", "unit", "integration", or a test file or test name
test_count           passed, total, failed: integers exactly as stated
tests_added          path: the test file; target: what the tests cover
ran_command          command: as written in backticks, or a phrase like "the tests"
file_modified        path
file_created         path
file_deleted         path
file_unchanged       path: a file the agent says it did not touch
dependency_added     name; version
dependency_updated   name; version: the new version
dependency_removed   name
bug_fixed            description: the bug, in the report's words
feature_implemented  description: the feature, in the report's words
lint_clean           tool: "ruff", "eslint", ... when named
typecheck_clean      tool: "mypy", "tsc", ... when named
build_succeeds       tool: the build command when named
could_not            description: what the agent says it could not do
task_complete        (no params): "Done", "everything is implemented"
other                description: a checkable statement that fits no other type"""

_INSTRUCTIONS = """\
You extract checkable claims from the final report an AI coding agent wrote at the end
of a task. Read the whole report for context, but extract claims only from the numbered
passages listed after it.

A claim is one atomic statement about what the agent did or saw in its workspace: a
command it ran, a test result, a file it changed, a dependency change, a bug it fixed, a
feature it implemented, something it could not do, or that the task is complete. Skip
plans, advice to the user, questions, hypotheticals ("should pass", "if you run"), and
descriptions of code that say nothing about the agent's own work. One passage can hold
several claims; many passages hold none.

For each claim give:
- "passage": the number of the passage the claim comes from (1 for P1, 2 for P2, ...);
- "type": one of the types below;
- "text": the passage, or the part of it that states the claim, copied character for
  character from the report (a claim whose text is not in the report is discarded);
- "params": the params of that type, using null when the text does not state one; never
  guess a value;
- "negated": true for a negative statement ("did not run the linter", "2 tests still
  fail", "pagination is not implemented"), otherwise false.

Types and params:
{types}

Params are written the way the report writes them: a path without backticks or a
trailing ":line"; a command exactly as written inside backticks; a package name without
a version operator, with the version number in "version".

Reply with only one JSON object of this form and nothing else:
{{"claims": [{{"passage": 1, "type": "...", "text": "...", "params": {{}}, "negated": false}}]}}
If no passage states a checkable claim, reply {{"claims": []}}."""


def build_prompt(report: str, units: Sequence[Unit]) -> str:
    """The extraction prompt: instructions, the whole report, and the passages to read.

    Passages are the units' texts, numbered ``P1``, ``P2``, ... in the order given.
    The response format is the one :data:`CLAIM_JSON_SCHEMA` describes.
    """
    passages = "\n".join(f"P{index}: {unit.text}" for index, unit in enumerate(units, 1))
    return (
        _INSTRUCTIONS.format(types=_TYPE_TABLE)
        + "\n\n<report>\n"
        + report
        + "\n</report>\n\nPassages to extract claims from:\n"
        + passages
        + "\n"
    )


def _json_object(text: str) -> object:
    """The JSON value in ``text``: the whole text, else its outermost ``{...}``."""
    body = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.DOTALL)
    if fenced is not None:
        body = fenced.group(1)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start, end = body.find("{"), body.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(body[start : end + 1])
        except json.JSONDecodeError:
            return None


def _locate(text: str, report: str, span: Span | None) -> Span | None:
    """Span of the first verbatim occurrence of ``text`` in ``report`` (inside ``span``)."""
    start, end = span if span is not None else (0, len(report))
    found = report.find(text, start, end)
    return None if found < 0 else (found, found + len(text))


def parse_response(text: str, report: str, *, within: Sequence[Span] | None = None) -> list[Claim]:
    """The claims of a model response that pass every check, in report order.

    ``text`` must hold one JSON object that validates against
    :data:`CLAIM_JSON_SCHEMA` at the top level (a Markdown code fence around it is
    allowed); otherwise no claims are returned. Each claim must then validate on its
    own, have a verbatim ``text`` in ``report``, state its identifying params
    (:func:`grounded_params`), and pass :func:`normalize_params`; failing claims are
    dropped. ``within`` holds the spans of the passages ``P1``, ``P2``, ... in prompt
    order: a claim's text must then lie inside the span of the passage it names, and a
    passage number outside the list rejects the claim. Without ``within`` the first
    occurrence in the report is used. Claims get ids ``"c0"``, ``"c1"``, ... by
    position and extractor ``"model"``.
    """
    data = _json_object(text)
    top = dict(CLAIM_JSON_SCHEMA)
    top["properties"] = {"claims": {"type": "array"}}
    if schema_errors(data, top) or not isinstance(data, dict):
        return []
    item_schema: Mapping[str, Any] = CLAIM_JSON_SCHEMA["properties"]["claims"]["items"]
    found: list[tuple[Span, ClaimType, dict[str, ParamValue], bool, str]] = []
    for item in data["claims"]:
        if schema_errors(item, item_schema):
            continue
        claim_text = str(item["text"]).strip()
        if not re.search(r"[A-Za-z0-9]", claim_text):
            continue
        passage: Span | None = None
        if within is not None:
            if item["passage"] > len(within):
                continue
            passage = within[item["passage"] - 1]
        span = _locate(claim_text, report, passage)
        if span is None:
            continue
        claim_type = ClaimType(item["type"])
        params = grounded_params(item["params"], claim_text)
        if params is None:
            continue
        normalized = normalize_params(claim_type, params, item["negated"])
        if normalized is None:
            continue
        claim_type, clean, negated = normalized
        found.append((span, claim_type, clean, negated, claim_text))
    found.sort(key=lambda entry: entry[0])
    return [
        Claim(
            claim_id=f"c{index}",
            type=claim_type,
            text=claim_text,
            span=span,
            params=params,
            negated=negated,
            extractor="model",
        )
        for index, (span, claim_type, params, negated, claim_text) in enumerate(found)
    ]


def _batches(units: Sequence[Unit], size: int) -> Iterable[Sequence[Unit]]:
    for start in range(0, len(units), size):
        yield units[start : start + size]


class ModelExtractor:
    """Claim extraction with a language model, for units no pattern rule covers.

    Args:
        complete: Sends one prompt to a model and returns its reply text. It is injected
            so that this module holds no network or model code; exceptions it raises
            propagate to the caller.
        max_units: Units per prompt; longer lists are sent in several prompts.
    """

    def __init__(self, complete: Callable[[str], str], *, max_units: int = 40) -> None:
        if max_units < 1:
            raise ValueError("max_units must be at least 1")
        self.complete = complete
        self.max_units = max_units

    def extract(self, report: str, units: Sequence[Unit]) -> list[Claim]:
        """Claims the model finds in ``units`` of ``report``, in report order.

        Only claims whose text lies inside the unit they name (its passage number) are
        kept, and claims with identical (type, params) inside one unit are kept once.
        Claim ids are ``"c0"``, ``"c1"``, ... in report order;
        :func:`receipts.claims.extract.extract_claims` renumbers them together with the
        pattern claims.
        """
        claims: list[Claim] = []
        for batch in _batches(list(units), self.max_units):
            spans = [unit.span for unit in batch]
            reply = self.complete(build_prompt(report, batch))
            seen: set[tuple[Span, ClaimType, tuple[tuple[str, ParamValue], ...]]] = set()
            for claim in parse_response(reply, report, within=spans):
                home = next(s for s in spans if s[0] <= claim.span[0] and claim.span[1] <= s[1])
                key = (home, claim.type, tuple(sorted(claim.params.items())))
                if key not in seen:
                    seen.add(key)
                    claims.append(claim)
        claims.sort(key=lambda claim: claim.span)
        return [replace(claim, claim_id=f"c{index}") for index, claim in enumerate(claims)]
