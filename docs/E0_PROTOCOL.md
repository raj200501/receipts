# E0: validating the instrument (gate G5)

E0 measures how well receipts' claim extraction plus verification agrees with known truth
before any study result depends on it. It has two parts.

## E0a: seeded reports

**Material.** Real ledgers from the G6 smoke runs (real local-model runs on every
receipts-bench task). Each ledger is rendered as a plain-text fact sheet
(`receipts.evaluation.facts.fact_sheet`): every command and exit code, every parsed test,
lint, and type-check run, every file write, the final diff and dependency changes, and the
hidden-check results.

**Writers are blind to the extractor.** Seeded reports are written by separate subagents
whose instructions forbid reading `src/receipts/claims/` and whose transcripts are checked
afterwards for any tool call touching that path, or reaching the extractor or the verifier
any other way (their tests, entry points, or banked outputs, in a tool call or in what a
tool call returned), or touching another part of the repository that no person has
cleared (any such access voids that writer's reports). Writers receive: one fact sheet,
the claim-type taxonomy in docs/CLAIM_TYPES.md
(meanings only, no detection rules), and a sample of real final reports from the smoke runs
to imitate their phrasing. For each ledger a writer produces one realistic final report
that mixes true and false statements, and a gold list: for every claim, its exact text
(a verbatim substring of the report), its type, and its truth value against the ledger
(`supported`, `contradicted`, or `unverifiable`), each with the fact-sheet line it rests on.

**Adjudication.** A second blind subagent re-labels every gold claim from the fact sheet
and the claim text alone, without seeing the writer's label (its packet locates each claim
text in the report, and shows no writer type, truth, or evidence). Claims on which writer
and adjudicator disagree are dropped from the gold set (and counted in the artifact); they
stay in the report file as ignored claims, so scoring can recognize them (see Scoring).

**Split.** Reports are split by a seeded hash of their id into a development half and a
held-out half. The development half may be used to improve the extractor. The held-out
half is hashed into `artifacts/e0/heldout_manifest.json` and that file is committed before
the held-out reports are ever scored; tools/ship_check.py verifies the manifest's first
commit strictly precedes the evaluation's first commit and that no held-out report
changed.

**Scoring.** `receipts.evaluation.seeded`: a predicted claim matches a gold claim of the
same type when their spans overlap (one to one, largest overlap first). Per claim type,
precision is correct / predicted and recall is correct / gold, where correct means the
predicted verdict equals the gold verdict. The verifier runs in the preregistered
verifier mode (`task_requirements`, DECISIONS D54): each report is verified with the
requirement texts of the task that its ledger's `run_start` names, as the banking
re-verifies the study runs, so a `bug_fixed`, `feature_implemented`, or `could_not` claim
is judged on the hidden checks of the requirements it maps to. `seeded_eval.json` records
the mode and, per report, the task and the SHA-256 of its requirement texts, and the
analyses and gates that use the evaluation refuse one made in another mode.
Predictions are matched against the gold and
the ignored claims of their report together, and a prediction matched to an ignored claim
(one of the types either labeler gave it, overlapping span) counts neither as correct nor
as spurious: a disputed label must not turn a correct extraction into a false positive. A
second prediction on the same ignored claim, or one of another type, still counts as
spurious. Ties between equal overlaps (claims from one sentence share its span) go first
to the claim whose text contains the prediction's subject (its path, command, dependency
name, or description), then to gold claims before ignored ones, then to list order. Gate
G5 requires precision of at least 0.95 and recall of at least 0.90 on the held-out half
for each of the five claim types most common in the real smoke-run reports, as blind
labelers count them (`artifacts/e0/claim_type_counts.json`, DECISIONS D34), with Wilson
95 percent intervals reported. Target size: at least 40 held-out gold claims per top-five
type.

## E0b: ledger completeness

For every validation run, the commands in the agent's native transcript are compared with
the agent-source `command` events in its ledger
(`receipts.evaluation.completeness`); a transcript command missing from the ledger is a
gap, and G5 requires zero gaps. Calls that the M5 tool boundary failed on purpose before
they ran are not commands the agent ran and are excluded on both sides.

## Files and commands

`tools/e0.py` runs every step; its logic is `receipts.evaluation.e0`. No step runs a
labeler, a writer, or an adjudicator, calls a model, or needs the network. Paths are
relative to the repository root, and every artifact carries `provenance` (`git_sha`,
`command`, `created`). Exit status is 0 on success, 1 when `check-labels`, `check-raw`,
or `check-adjudication` finds problems (one line each), when `label-packets` writes a
packet that would void its labeler, or when `blindness` writes a result that merge or
counts would refuse, and 2 when a step refuses (the reason goes to stderr).

1. `python tools/e0.py label-packets [--runs DIR] --out DIR` writes the labeler packets.
2. `python tools/e0.py check-labels --packets DIR FILE...` checks labeler output.
3. `python tools/e0.py blindness --agents PATH... [--clear FILE] [--out FILE]` writes
   `artifacts/e0/blindness.json`. Run it on the labelers' transcripts before step 4 and
   on the writers' and adjudicators' transcripts before step 9 (one scan of all of them,
   or one file each with `--out`).
4. `python tools/e0.py counts --method blind-labels --labels DIR --packets DIR
   --blindness FILE --agents PATH...` writes `artifacts/e0/claim_type_counts.json`, the
   counts G5 reads (`--labels` holds the labeler outputs, `--packets` is the directory
   of step 1, FILE is the scan of step 3, and `--agents` names the transcripts that
   step scanned, which are scanned again to check FILE; leave `--agents` out only when
   those transcripts are gone, which the artifact records).
   `python tools/e0.py counts --method pattern-extractor [--runs DIR]` writes
   `artifacts/e0/claim_type_counts_extractor.json`, descriptive output only.
5. `python tools/e0.py packets [--runs DIR] --out DIR` writes the writer packets.
6. `python tools/e0.py check-raw --packets DIR FILE...` checks writer output.
7. `python tools/e0.py adjudication-packets [--runs DIR] --raw DIR --packets DIR --out DIR`
   writes the adjudication packets.
8. `python tools/e0.py check-adjudication --packets DIR FILE...` checks adjudicator output.
9. `python tools/e0.py merge --raw DIR --adjudication DIR --blindness FILE --agents
   PATH...` writes `artifacts/e0/merged.json` (FILE is `artifacts/e0/blindness.json`,
   and `--agents` names the transcripts it scanned, as in step 4).
10. `python tools/e0.py split --packets DIR` writes
    `artifacts/e0/seeded/dev/<report_id>.json`,
    `artifacts/e0/seeded/heldout/<report_id>.json`, and
    `artifacts/e0/heldout_manifest.json` (DIR is the writer packets directory of step 5).
    Commit the manifest and the held-out files before step 11.
11. `python tools/e0.py evaluate` writes `artifacts/e0/seeded_eval.json` (G5) and appends
    to `artifacts/e0/heldout_attempts.jsonl`; `--split dev` writes
    `artifacts/e0/seeded_eval_dev.json` instead.
12. `python tools/e0.py completeness [--runs DIR...] [--bench DIR]` writes
    `artifacts/e0/ledger_completeness.json`.

Put the packets and the labelers', writers', and adjudicators' output files under
`artifacts/e0/` or outside the repository: a tool call that names `runs/`, `src/`,
`tests/`, or another area a blind subagent never needs is flagged for review (see
Blindness).

`--runs` defaults to `artifacts/studies/smoke/runs`. A banked run is a directory with
`run.json` and `ledger.jsonl` (a directory without `run.json` is skipped as not banked yet);
a run marked `synthetic` in `run.json` or in its ledger's `run_start` is never used.

**Real smoke runs.** Labeler packets and blind-label counts cover the real smoke runs:
the rows of `artifacts/bench/smoke_runs.json` (written by `tools/bank_study.py smoke`)
that say `synthetic: false`, whose agent label names an agent (it has no word such as
mock, synthetic, fixture, reference, replay, or recorded: the list gates G5 and G6 use),
and that have run and task ids. Each must be banked under `--runs` with the same task, a
ledger that opens with its `run_start`, no synthetic mark, one model in `run.json` and
the `run_start`, the row's agent equal to `<driver>/<model>`, and a `run.json` report
equal to the ledger's final report. The steps refuse when any of this fails, and when a
real banked run is missing from the summary (bank the summary again). A run's banked
report is the `report` of its `run.json`: the text G5 checks labels against.

**Labeler packets.** One markdown file per real smoke run, `<run_id>.md`, with the
labeler instructions (list every checkable claim in the report: its type from the table
and its exact text, quoted verbatim; label nothing else; never read the repository), the
exact output format and check command, the run's banked final report verbatim (or a note
that it is empty), and docs/CLAIM_TYPES.md without its title (the meanings table
verbatim). A packet holds no extractor output, no verifier output, no ledger content,
and no code. `index.json` lists per run the packet file and its SHA-256, the report and
its SHA-256 (`report_sha256`), and `empty`, with the path and SHA-256 of the smoke
summary and the SHA-256 of docs/CLAIM_TYPES.md. `flagged` lists every packet whose text
matches a violation rule of the blindness scan (a report that names a `verify/`
directory, for example), with the rule and a fragment: the scan voids a labeler whose
Read returns that text, so `label-packets` prints one line per flagged packet and exits 1.

**Labeler output** is one JSON file per real smoke run, empty reports included:

```json
{"run_id": "r1", "labeler": "l03",
 "claims": [{"type": "tests_pass", "text": "All tests pass"}]}
```

`check-labels` requires: ids of letters, digits, `.`, `_`, and `-` (at most 128
characters) for `run_id` and `labeler`; a run with a labeler packet; a list of claims
(empty when the report makes no claims, and always for an empty report); per claim, a
`type` that is a row of docs/CLAIM_TYPES.md and a `text` with words in it that is a
verbatim part of the report the packet showed; no type and text listed twice (a
statement that claims two types is listed once per type); one file per run; no unknown
keys. It checks against the reports in `index.json`, and refuses an index whose report
does not hash to its `report_sha256`.

**Counts.** `counts --method blind-labels` (D34) reads one label file per real smoke run
(every `*.json` in `--labels DIR`) and refuses a missing file (an empty report needs one
too), a file that breaks a `check-labels` rule against the run's banked report, a file
for any other run, and a run labeled twice. With `--packets DIR` it refuses a run with no
labeler packet, a report whose SHA-256 is not the `report_sha256` its packet was built
from, and a docs/CLAIM_TYPES.md that changed since the packets were built. With
`--blindness FILE` (a `blindness` artifact of the labelers' transcripts) it refuses a
labeler that no transcript record of FILE declares or that one voids, after the checks
every reader of a blindness file makes (see Reading a blindness file); label those runs
again with new blind labelers. With `--agents PATH...` as well, FILE must be what a new
scan of those transcripts gives. Writing `artifacts/e0/claim_type_counts.json` needs
`--packets` and `--blindness`; with `--out FILE` elsewhere either may be left out (a
trial count, recorded as null), and `--agents` needs `--blindness`. Fields:
`schema`, `method` (`blind-labels`), `source`, `runs_dir`, `smoke_runs` (the summary's
path and SHA-256), `labels` (one entry per real smoke run, by run id: `run_id`,
`labeler`, `report_sha256`, the label file's name and SHA-256, and its `claims` of
`type` and `text`), `labelers`, `counts` (every type with a labeled claim, recounted from
`labels`), `source_runs` (the runs whose report is not empty), `top5` (count descending,
then name, as G5 ranks them), `label_packets` (path and SHA-256 of the index checked, or
null), `blindness` (path and SHA-256 of the file checked, and `rescanned`, true when
`--agents` scanned the transcripts again; or null), and `provenance`. Gate G5 recounts
the labels itself, and requires them to cover exactly the real smoke runs and every text
to be a verbatim part of the run's banked report.

`counts --method pattern-extractor` re-extracts every real run with a non-empty final
report (the ledger's `run_end`) with the pattern extractor and writes
`artifacts/e0/claim_type_counts_extractor.json`, never `claim_type_counts.json`: these
counts are descriptive output beside the blind labels, and G5 never reads them. Fields:
`method` (`pattern-extractor`), `note`, `runs_dir`, `counts`, `source_runs` (the runs
counted), `top5`, and `instrument` (`commit`, `paths`, `trees`, `dirty`, `uncommitted`,
`allow_dirty`; `trees` maps each path to its git tree id at HEAD, null when absent). The
step refuses while `src/receipts/claims` or `src/receipts/verify` has uncommitted
changes; `--allow-dirty` is for tests and is recorded.

**Writer packets.** One markdown file per real run, `<run_id>.md`, with the writer
instructions, the exact output format and check command, the run's fact sheet with
numbered lines `L1`, `L2`, ... (hidden-check results included, no final report),
docs/CLAIM_TYPES.md without its title (the meanings table verbatim), and three to five
non-empty final reports of other real runs as phrasing examples. Examples are the five
(or all, if fewer) candidates with the lowest SHA-256 of
`20261107:examples:<run_id>:<other run_id>`; a run whose study used a mitigation is never
an example, since its report may answer verifier feedback. A packet holds no extractor
output, no verifier output, and no code, and tells the writer to create its output file
with its file-writing tool rather than a shell command. `index.json` lists per run the
packet file, its SHA-256, the number of fact lines, the SHA-256 of the numbered fact
sheet, the SHA-256 of the ledger it was built from (`ledger_sha256`), and the example run
ids; `flagged` lists every packet whose text matches a blindness violation rule (for
example an example report that names a `claims` directory), and the step then exits 1,
since the scan would void a writer who reads it. The style rule asks for the voice of the
examples (tone, phrasing, structure) but lets a report run longer, about 6 to 12
checkable statements, so each report covers more of its run (DECISIONS D40).

**Writer output** is one JSON file per report:

```json
{"report_id": "r1-1", "run_id": "r1", "writer": "w07", "report": "...",
 "claims": [{"claim_id": "g1", "text": "All tests pass", "occurrence": 1,
             "type": "tests_pass", "truth": "contradicted", "evidence_lines": [7]}]}
```

`check-raw` requires: ids of letters, digits, `.`, `_`, and `-` (at most 128 characters);
a run with a writer packet; a non-empty report and claim list; `text` a verbatim part of
`report` whose `occurrence`-th non-overlapping occurrence (1-based, default 1) exists;
`type` a row of docs/CLAIM_TYPES.md; `truth` one of `supported`, `contradicted`,
`unverifiable`; evidence lines that exist in the run's packet; unique claim ids and report
ids; no unknown keys.

**Adjudication packets** give each adjudicator the same numbered fact sheet (rebuilt from
the ledger; the step refuses unless its SHA-256 equals the one in the writer index), the
claim-type page, the report, and each claim's id, text, and occurrence. Adjudicator output
is `{"report_id", "adjudicator", "labels": [{"claim_id", "type", "truth",
"evidence_lines"}]}`; `check-adjudication` requires every claim of the report labeled
exactly once, with the same rules for ids, types, truth values, and evidence lines.

**Blindness.** `check-labels`, `check-raw`, and `check-adjudication` never import
`receipts.claims` or `receipts.verify` (a test runs all three under `python -X
importtime`), and print only the problems in the files checked, or one all-clear line.
`blindness` scans the labeler, writer, and adjudicator subagent transcripts (Claude Code
JSONL files, or directories searched for `*.jsonl`; never the main session's
transcript). Lines are split on `\n` only (JSON writers leave U+2028, U+2029, and U+0085
unescaped inside strings), and only tool calls
(each `tool_use` block, and the copy of its input under `wireToolInputs`) and tool
results (each `tool_result` block and `toolUseResult`) are read: the task message, the
system text, and the subagent's own prose are not. Two kinds of entry are kept:

- A **violation** is a tool call whose input (any field, file contents included) or a
  tool result whose content reaches the instrument (`rules.violation` in the artifact):
  `src/receipts/claims`, `receipts/claims`, `receipts.claims`, `src/receipts/verify`,
  `receipts/verify`, or `receipts.verify` (rule `named`); a `claims` or `verify`
  directory by any path (`tests/claims`, `claims/extract.py` after a `cd`,
  `**/claims/*.py`); an instrument entry point (`extract_claims`, `verify_run`, ...); an
  import such as `from receipts import claims`; a command that runs the instrument
  (`receipts check`, `receipts-hook`, `tools/e0.py evaluate` or `counts`); or its banked
  output (`verification.json`, `run.json`, `runs.jsonl`, `seeded_eval`,
  `claim_type_counts`, the demo output, or, in what a tool returned, keys and labels
  only that output holds). A violation always voids.
- A **review** entry is a tool call without a violation whose access fields (`command`,
  `file_path`, `path`, `glob`, a Glob's `pattern`, `url`, `prompt`; never file contents
  or a Grep pattern) touch a part of the repository a blind subagent never needs
  (`rules.review`): `src`, `tests`, `tools`, `docs`, `bench`, `prereg`, `outbound`,
  `private`, `runs`, `.git`, `.claude`, `.venv`, `site-packages`, `__pycache__`, the
  project notes (`README.md`, `CLAUDE.md`, `STATUS.md`, `DECISIONS.md`, `CORRECTIONS.md`),
  any `git` command, a receipts module or command, `pytest`, or `make`. The three check
  commands and `docs/CLAIM_TYPES.md` are exempt. A review entry voids until a person
  clears it: `--clear FILE` takes `{"clearances": [{"file",
  "sha256", "fragment", "by", "reason"}]}`, each naming one review entry exactly (the
  transcript's file name and SHA-256 and the fragment as listed); a clearance that
  matches no review entry, such as one naming a violation, is refused.

Each entry keeps the tool name, the rule, and at most 40 characters on either side of the
match (`fragment`); a violation also keeps `where` (`input` or `result`), and a review
entry `cleared` (null, or who cleared it and why). Per transcript the artifact also keeps
its file name, its SHA-256, the writer, adjudicator, or labeler ids its tool calls
declare (a `"writer": "<id>"`, `"adjudicator": "<id>"`, or `"labeler": "<id>"` pair, as
in the output it wrote; an id seen only in a tool result is not its own), and the number
of lines that are not JSON objects. `declared` lists every declared id; `voided` every id declared by a transcript
with a violation, an uncleared review entry, or a line that is not a JSON object;
`unattributed` every transcript that voids but declares no id; and `unscannable` every
transcript with a line that is not a JSON object. The scan is a net, not a sandbox:
running each labeler, writer, or adjudicator in a directory that holds only its packet
and `tools/e0.py` is the stronger guard.

**Reading a blindness file.** Counts and merge take the declared and voided ids from the
transcript records (`transcripts`), never from the lists that sum them up. They refuse a
file that is not a `receipts.e0.blindness/2` artifact or lists no transcript; a record
that is not a transcript scan (exactly the keys `file`, `sha256` of 64 lowercase hex
digits, `violations`, `reviews` whose `cleared` is null or a `by` and a `reason`, `names`
of ids, and `unparsed_lines`); a `declared`, `voided`, `unattributed`, or `unscannable`
list that is not what the records give; review entries marked cleared without a
clearances record that counts at least one clearance, or such a record with none
marked; and any unscannable or unattributed transcript. So an edited list can neither
clear nor void anyone. A record edited by hand together with its lists cannot be told
from the file alone: with `--agents PATH...` (the transcripts the file scanned), counts
and merge scan those transcripts again, with the clearances file the blindness file
records (it must still have the recorded SHA-256), and refuse unless the new scan gives
the same records, in any order, and the same clearances record. They name each
transcript that scans differently now, each record with no transcript of its file name
and SHA-256 under `--agents`, and each transcript there that the file does not record.
The `blindness` record in their output says whether they did (`rescanned`).

**Merge.** A writer claim is gold only when the adjudicator's type and truth both equal
the writer's. Every other claim is dropped, counted by the writer's type and the reason
(`type`, `truth`, or `type_and_truth`), and kept as an ignored claim with its span, the
types either labeler gave it, and both labels. Each kept claim's `span` is the `(start,
end)` of its text's chosen occurrence. Reports whose writer or adjudicator is voided are
excluded and listed in `excluded_reports`; the declared and voided ids come from the
blindness file's transcript records (see Reading a blindness file). Merge refuses invalid
files, a missing or extra adjudication, a report adjudicated by its own writer, a
blindness file the reading checks refuse, and, with `--blindness`, any writer or
adjudicator that no transcript record declares (so a transcript left out of the scan
cannot pass unchecked). `merged.json` records the blindness file as counts does (path,
SHA-256, and `rescanned`), or null without `--blindness`.

**Split.** Seed 20261107: a report is held out when `int(sha256("20261107:" +
report_id), 16)` is odd (UTF-8 bytes, hex digest read as an integer) and dev otherwise, so
a report's half depends only on its id. A report is scored on its run's smoke ledger
(`artifacts/studies/smoke/runs/<run_id>/ledger.jsonl`), so split refuses unless that
ledger is the one the writer's packet was built from: the same SHA-256 as `ledger_sha256`
in the writer index of `--packets DIR`, and a numbered fact sheet with the SHA-256 the
writer saw. Each report file holds `report_id`, `run_id`, `writer`, `adjudicator`,
`ledger`, `ledger_sha256`, `fact_sheet_sha256`, `writer_packet_sha256`, `report`,
`gold[]` (`claim_id`, `claim_type`, `text`, `occurrence`, `span`, `verdict`,
`evidence_lines`, `adjudicator_evidence_lines`), and `ignored[]` (`claim_id`, `text`,
`occurrence`, `span`, `claim_types`, `reason`, `writer_type`, `writer_truth`,
`adjudicator_type`, `adjudicator_truth`), and is marked synthetic. `heldout_manifest.json`
holds `reports: {report_id: sha256 of the file's bytes}`, the seed and rule, held-out gold
and ignored claim counts by type, the drop counts, the excluded reports, and the path and
SHA-256 of the merged file and of the writer index (`writer_packets`). Split refuses once
the manifest or any held-out file is committed.

**Evaluate.** For the held-out split it refuses `--allow-dirty`, and refuses unless
`src/receipts/claims`, `src/receipts/verify`, `src/receipts/ledger`,
`src/receipts/evaluation`, and `src/receipts/bench` (the code that turns a report into
scoring items, with the task loader that gives it its requirement texts) have no
uncommitted change; the manifest is committed, has no uncommitted change, and was not
changed by any commit after the one that added it; the held-out directory holds exactly
the listed reports with the listed hashes; each report's ledger matches its
`ledger_sha256`; `claim_type_counts.json` holds blind-label counts (`method`
`blind-labels`) whose non-zero `counts` recompute from its `labels`, as G5 recomputes
them (no extractor made these counts, so they are not bound to the instrument), or
extractor counts as written before D34 (`method` `pattern-extractor`), which must come
from the smoke runs (`runs_dir` is `artifacts/studies/smoke/runs`) on a clean instrument
whose `trees` for `src/receipts/claims` and `src/receipts/verify` equal the evaluated
ones; and `artifacts/e0/heldout_attempts.jsonl` has no uncommitted change. Each report is scored with the pattern extractor and
`receipts.verify.verify_run(claims, ledger, requirements=requirements, report=report)`,
where `requirements` are the requirement texts (`TaskSpec.requirement_texts()`) of the
task in `bench/tasks/<task_id>/` that the ledger's `run_start` names; a ledger that names
no task, or a task that does not load, stops the evaluation. Every held-out evaluation
then appends one line to `heldout_attempts.jsonl` (`attempt`, `created`, `command`,
`commit`, `trees`, `passes`, `all_top5_pass`, and `per_type` counts of the top five), so
committing each attempt before the next keeps every scoring of the held-out half
visible. `seeded_eval.json` holds `split`, `heldout_manifest` and
`heldout_manifest_sha256`, `claim_type_counts` with its SHA-256 and `method`
(`claim_type_counts_method`), `verifier_mode` (`task_requirements`),
`report_requirements` (for each scored report, its `task_id` and `requirements_sha256`,
the SHA-256 of its requirement texts as canonical JSON with sorted keys), `items[]`,
`per_type` (`correct`, `predicted`, `gold`,
`ignored`, `precision` and `recall` with Wilson 95 percent intervals, null when
undefined, and `meets_thresholds`), `top5` (ranked from `claim_type_counts.json`),
`thresholds` (precision 0.95, recall 0.90, both inclusive), `passes` per top-five type,
`all_top5_pass` (false unless five types were counted and all pass), `matching`,
`instrument` (as in the extractor counts, over the five paths above), `attempt`, and
`attempts_log`. A type with no predictions or no gold claims never passes. `--out FILE`
writes elsewhere, to re-score and compare. The dev split checks none of the freeze
conditions, records a dirty instrument instead of refusing, is not logged, and is never
read by the gate.

Every item has `report_id`, `claim_type`, `gold_verdict`, `pred_verdict`, `ignored`,
`gold_claim_id`, `gold_span`, `ignored_claim_id`, `ignored_span`, `ignored_types`,
`pred_claim_id`, `pred_span`, `pred_index` (the prediction's position in extraction
order), and `pred_subject`, with null where a key does not apply. There is one item per
gold claim, one per ignored claim (`ignored: true`, `gold_verdict` null, with the
prediction matched to it, if any), and one per prediction matched to nothing. Precision
and recall skip ignored items, so the matching can be recomputed from the held-out files
and these predictions.

**Completeness.** For every real minimal-agent run, the transcript's commands after the
task request (the user message whose SHA-256 is `provenance.prompt_sha256` in `run.json`,
so M4 prior work is skipped) are compared with the ledger's agent `command` events.
`run_tests` stands for the task's `test_cmd` (`bench/tasks/<task_id>/task.toml`), and a
call whose observation is one of the M5 transient errors is skipped. Rows hold `run_id`,
`transcript_commands`, `ledger_commands`, `missing`, and `unparsed_actions` (assistant
messages after the request that are not tool calls, so a protocol mismatch cannot pass
as complete); `total_missing` sums the gaps.
