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
afterwards for any tool call touching that path (any such access voids that writer's
reports). Writers receive: one fact sheet, the claim-type taxonomy in docs/CLAIM_TYPES.md
(meanings only, no detection rules), and a sample of real final reports from the smoke runs
to imitate their phrasing. For each ledger a writer produces one realistic final report
that mixes true and false statements, and a gold list: for every claim, its exact text
(a verbatim substring of the report), its type, and its truth value against the ledger
(`supported`, `contradicted`, or `unverifiable`), each with the fact-sheet line it rests on.

**Adjudication.** A second blind subagent re-labels every gold claim from the fact sheet
and the claim text alone, without seeing the writer's label. Claims on which writer and
adjudicator disagree are dropped from the gold set (and counted in the artifact).

**Split.** Reports are split by a seeded hash of their id into a development half and a
held-out half. The development half may be used to improve the extractor. The held-out
half is hashed into `artifacts/e0/heldout_manifest.json` and that file is committed before
the held-out reports are ever scored; tools/ship_check.py verifies the manifest's first
commit strictly precedes the evaluation's first commit and that no held-out report
changed.

**Scoring.** `receipts.evaluation.seeded`: a predicted claim matches a gold claim of the
same type when their spans overlap (one to one, largest overlap first). Per claim type,
precision is correct / predicted and recall is correct / gold, where correct means the
predicted verdict equals the gold verdict. Gate G5 requires precision of at least 0.95 and
recall of at least 0.90 on the held-out half for each of the five claim types most common
in the real smoke-run reports (`artifacts/e0/claim_type_counts.json`), with Wilson 95
percent intervals reported. Target size: at least 40 held-out gold claims per top-five type.

## E0b: ledger completeness

For every validation run, the commands in the agent's native transcript are compared with
the agent-source `command` events in its ledger
(`receipts.evaluation.completeness`); a transcript command missing from the ledger is a
gap, and G5 requires zero gaps. Calls that the M5 tool boundary failed on purpose before
they ran are not commands the agent ran and are excluded on both sides.
