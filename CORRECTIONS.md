# Corrections

Every changed or withdrawn claim gets a dated entry here (rule 3 of
docs/BUILD_BRIEF.md section 9), newest first.

## 2026-11-25

- **docs/REPORT.md, section 7.1** (fixed in 6d4a697): it called the smoke study "partway"
  and said the banked runs were not a random sample of the benchmark. The study is
  complete, with one run of every task; one task was run again under a plan amendment
  (D71, D72).
- **docs/REPORT.md, section 8** (fixed in 6d4a697): it listed G6 among the gates that
  cannot pass. G6 passes.
- **README.md, Limitations, and docs/REPORT.md, section 7.4** (fixed in 6d4a697): they
  said the banked runs were the tasks that happened to run first. They are one unreplicated
  run of each task.
- **README.md, Dual use, and docs/DATA.md** (fixed in 6d4a697): they said no smoke run
  carries the canary. The larger-window py-units-refactor run (D71) carries it in
  `run.json`, `verification.json`, and its ledger.
- **README.md, Limitations, and docs/REPORT.md, section 3** (fixed in 6d4a697): they said
  every banked smoke run left this repository's checkout readable to the agent. The
  larger-window py-units-refactor run hid it (its `run.json` records `checkout_hidden`).
- **README.md, Quickstart** (fixed in 6d4a697): its heading promised the demo "under a
  minute", a timing claim with no banked measurement. It is gone.
- **README.md, "One false report caught, one missed", and the launch draft in outbound/**:
  they said that for the larger-window py-units-refactor report "nothing was flagged".
  receipts did flag the run: it listed the failed hidden checks the report does not admit.
  What it missed is narrower: the extractor found no claim, so no claim was contradicted.
- **README.md, Quickstart**: it said `make demo` prints each recorded run's report card.
  `make demo` prints only whether the output matches the golden file; `tools/demo.py`
  prints the cards, and the Quickstart now runs it.
- **README.md, Use it on your own agent** (from 6d4a697): the one-session trial changed
  into the receipts checkout and then started Claude Code there, so the trial session
  would have run on this repository instead of the user's project. It now starts Claude
  Code from the user's project.
- **README.md, Integrity by construction** (from 6d4a697): it said an unbound number
  "fails the build"; CI runs `make ci`, which does not run claimcheck, so the number fails
  `make claimcheck` and gate G10. It also said gates G7 to G9 run the same derivation as
  freshness; they re-derive only the study artifacts they read.
- **README.md, Status** (from 6d4a697): the G2 row no longer said that G2 passes because
  D51 narrowed its type-ignore scan, which D55 requires the README to say. The Status
  section says it again.
- **docs/REPORT.md, section 12** (from 6bcce25): its next steps said to "keep G12 current"
  and that G12 "holds" while its review matches the commit, which reads as if G12 passed.
  It fails at any commit without a SHIP review of its own; the text now says so.
- **docs/BENCH_CATALOG.md, docs/BENCH.md, bench/README.md** (from 6d4a697): they called the
  catalog the full task set. It lists every task except the pilot exemplars, which
  docs/BENCH.md and bench/README.md list.
- **README.md, Dual use, and docs/DATA.md** (from 6d4a697): their account of which banked
  runs lack the canary left out the early pipeline-check run, which also predates D59.
- **README.md, Limitations, and docs/REPORT.md, section 3** (from 6d4a697): "made from a
  code snapshot before D67" read as a time, but several smoke runs started after D67 was
  recorded, from older code. Every smoke run except the D71 run ran from code older than
  D67.
- **README.md, Responsible disclosure, Dual use** (from 6bcce25; review B7): the shortened
  bullet said "Hidden checks decide false success" and dropped the caveat that false success
  counts only reports in which the extractor finds a success claim, so a report that avoids
  extractable claims also avoids it. The caveat is back, with the py-ci-workflow and
  ts-ci-workflow runs that show it.
- **README.md, Why it matters** (from fc89cc9, inexact since 6bcce25 bound the hook latency;
  review N24): it said every number on the page is re-derived "from the raw run records", which does not fit the hook latency numbers,
  wall-time samples re-derived only into their median and maximum. It also headed the study
  design "A measurement, not an anecdote" although no study has run; it now says "Designed
  as a measurement".
- **docs/HOOK.md, Measured cost and effect** (from 6bcce25; review N24): it said the latency
  tool replays the Stop hook "exactly as Claude Code calls it". It runs
  `python -m receipts.hook stop` on minimal-agent study ledgers, while an installed hook runs
  the `receipts-hook` entry point on recorder ledgers; the text now says so. DECISIONS.md D73
  said the latency is bound in docs/HOOK.md; it is bound in README.md and docs/REPORT.md.
- **docs/REPORT.md, section 8** (review N24): it said gates G7 to G9 run the same
  re-derivation as `make freshness`. Each re-derives only the study artifacts it reads.
- **outbound/launch-post-draft.md** (review N24): it called E4 "a test of the Claude Code
  hook". E4 tests the hook's check inside minimal-agent and does not measure the Claude Code
  hook.
- **SECURITY.md, Scope and design** (since bootstrap; review B8): it said `make secrets-scan`
  runs in CI. CI runs only `make ci`, which did not include the scan until D74; it does now,
  so CI and `tools/prepush.sh` run it as rule 6 requires.
- **docs/REPORT.md, sections 1 and 8, pyproject.toml, tools/hook_latency.py** (review N24):
  REPORT said E4 "includes receipts-hook" (E4 tests the check behind it inside minimal-agent)
  and that a local hook "now refuses" commits under a wrong identity (that hook lived in one
  checkout, outside the repository); the package description said "Check every claim" (receipts
  checks the claims its extractor finds); the latency tool's docstring said it replays the hook
  "exactly as Claude Code would call it".
- **docs/BENCH.md, docs/REPORT.md section 8, tests/bench/test_validate.py** (review N24):
  BENCH.md said the pipeline "checks every claim in the report" (it checks the claims it
  extracts); REPORT listed the files CORRECTIONS.md corrects, and the list had fallen behind
  (each entry names its file instead); a skip message said "CI installs 22", but the workflow
  installs no Node.

## 2026-11-12

- **README.md (opening and status), STATUS.md, and DECISIONS D71: why py-units-refactor was
  excluded.** They said that after its first turn the request no longer fit the model
  server's context window, and that the first attempt timed out on the same request. The
  banked usage ledger and the server log show that in its second and third attempts the run
  reached its turn cap, and its final-report request then exceeded the window; the first
  attempt timed out on an earlier request that fit. The documents now say so (D72).

- **docs/REPORT.md section 7.2, the contradicted claims** (changed because new runs were
  banked): it said the contradicted claims "were all feature claims refuted by hidden
  checks". In the newly banked ts-parser-tests run, a claim that tests were added and a
  file claim are contradicted by the empty post-run diff. The section now says most were
  feature claims and describes that run.

- **docs/REPORT.md section 3.1 and docs/BENCH.md section 6, "the agent never sees" the hidden
  checks** (review N18): true of the agent's workspace, which receives them only after the
  agent stops, but the sandbox did not hide the checkout that stores them for runs made from
  a code snapshot, so every banked smoke run could have read them under the read-only host
  root. A path audit of the smoke ledgers finds no command or file-tool call that reached
  outside its workspace. Study runs now hide the checkout and refuse to start otherwise
  (D67); both documents and the README's Limitations say so. docs/BENCH.md also named
  `unshare -rn` as a sandbox for task commands and for task validation; neither uses it.

- **README.md and docs/REPORT.md, the runs with only file claims** (review N17): they said
  the ts-ci-workflow, ts-cli-docs, py-lru-ttl, and ts-matrix-refactor reports yield only
  file claims. The py-lru-ttl report also yields a supported claim that tests were added.
  The conclusion holds (none of these reports yields a success claim). Both documents now
  name that claim, and they add a known instrument error the independent review found
  (N19): in slugify-tests and email-tests, a claim that tests were added was supported
  although the added file was never collected and the test count did not rise, which the
  claim taxonomy requires.

- **README.md and docs/REPORT.md, the ts-cli-docs file claim**: they said the run "created no
  script". It did: the ledger records `scripts/check-docs.ts` created and package.json
  changed. The error is narrower: the claim was read as one about README.md, the file in
  its purpose clause, which had changed, so its verdict was right for the wrong reason and
  the script was never checked. Found by an adversarial check of the documents.
- **README.md, the task-success result**: it named "E1, task success" as its confirmatory
  test. Prereg 0001 has no task-success outcome; task success is E4's secondary outcome Z3
  (prereg 0002 section 4), and E1 uses each run's hidden-check result to decide false
  success (Y1). The line now says so.
- **README.md, the canary**: "the smoke runs banked so far do not" implied that later smoke
  runs would carry the canary; none will, since all smoke runs use an earlier snapshot.
- **The headline figure**: it called every bar a "share of runs" over all banked runs, but
  the report-based bars are over the runs with a final report. Each bar now gives its own
  count.
- **artifacts/README.md, docs/HOOK.md, docs/DATA.md, docs/REPORT.md, STATUS.md**: the
  manifest lists generated files with their own hashes, not source artifacts, and only
  `make reproduce` checks it; the hook removes its before-copy only after a successful edit;
  `run.json` holds no verdict evidence; the pipeline-check run record has no task hash; and
  the smoke summary records the environment that derived it, not that of its runs (as the
  2026-11-11 provenance entry below also said).
- **README.md, the benchmark description** (changed in e8ee5de, review N9): "small,
  realistic Python and TypeScript repositories" became "synthetic and written for the
  benchmark to look like real projects", without an entry here until now.
- **README.md and docs/REPORT.md, the report card and the revised extractor** (changed
  because the code changed back): the entry below describes a report card showing the
  bizdays completion sentence contradicted, and both documents said that a revised
  extractor (D60) reads most of the listed completion statements. D60 is reverted (D61), so
  the demo again shows only the supported "all existing tests passed", and those sentences
  are removed.
- **README.md "What a report card looks like" and docs/REPORT.md Figure 1** (changed because
  the code changed): the offline demo replays a banked run with the current extractor, and
  the revised extractor (D60) now reads the bizdays report's completion sentence, so the
  regenerated report card shows it contradicted by the hidden checks. The text that said the
  card shows only a supported "all existing tests passed" now describes both claims, and the
  passages about the smoke runs say that the run-time extractor, not the current one, missed
  that sentence.

## 2026-11-11

- **docs/REPORT.md section 7.2 and README.md, the turn cap**: "Every run ended with a final
  report" held for the first banked runs, but ts-csv-parse, banked later, reached the turn
  cap and never answered the final-report request, so its report is empty. Both documents
  now count the runs that reached the cap with and without a report
  (`turn_cap_without_report` in the smoke summary). The interim counts in both documents
  now cover the runs banked up to this commit.
- **README.md, Responsible disclosure, the canary string**: it described the canary as
  covering the benchmark's answer keys without saying that the banked runs quote those
  answer keys (hidden-check names and output) and carry no canary (review N8). New study
  runs now carry it in those files (D59); the README and docs/DATA.md state that the smoke
  runs banked so far do not.
- **README.md and docs/REPORT.md, what freshness re-derives** (until the commit after
  8692254): they said `make freshness` re-derives every live number from the banked
  artifacts, but it rebuilt only the registry, so the smoke summary it reads was never
  checked against the run records it summarizes (review B1). Freshness now re-derives it
  (D56), which makes the statement true; the documents say so.
- **artifacts/README.md and docs/REPORT.md, provenance**: they said every artifact carries
  provenance with the config hash, models, seeds, environment, and usage. Only the run
  records did; the smoke summary had its commit, command, time, and input hashes, and the
  registry, manifest, citation record, review record, and plans have none of those fields
  (review N4). The summary now carries the models, config hashes, seeds, environment, and
  usage of its runs, and artifacts/README.md states what each kind of artifact records.
- **README.md, docs/REPORT.md, and STATUS.md, the canary string** (changed in 85f9b92):
  until then the README said receipts-bench had no canary string yet and that one would go
  into every task file before the benchmark was released as a dataset. D52 put the canary
  into every task definition and every answer-key file with a comment syntax, and on
  purpose into none of the files an agent sees, so that commitment was narrowed without an
  entry here. The new wording ("every task definition and answer-key file carries a canary
  string") was also not exact: JSON answer-key files have no comment syntax and carry none.
  The documents now state the scope exactly. Found by the independent review of e4230cc
  (B4).
- **README.md and docs/REPORT.md, the py-cli-json error, corrected again**: the entry on
  the first signal below says a feature claim mapped to a preserve requirement makes the
  py-cli-json run count as claiming success. That is wrong. Any non-negated success-type
  claim marks a report as claiming success, whatever its verdict or mapping, so the run
  counts as claiming success because of its first sentence. The wrong mapping only made
  that claim supported where, mapped to the requirement it describes, it would likely be
  contradicted, which keeps the run among the false successes without a contradicted
  claim. Both documents now say so (review N1).
- **README.md, Status, gate G2**: it called the benchmark task repositories third-party
  code to the project. They are synthetic, written for the benchmark (docs/REPORT.md
  section 4); D51 rests on the brief treating task repositories like the code receipts
  never runs on the host, not on outside authorship (D55). The README now says so and
  states that G2 went from failing to passing because its scan was narrowed (rule 13;
  review N7).
- **README.md, the pre-push check**: it said `tools/prepush.sh` runs `make ci` for each of
  Python 3.11 and 3.12. The script runs `make setup` and `make ci` once, with one Python
  version; it is run once per version (review N3).
- **docs/REPORT.md, the review record**: it said `artifacts/review/latest.json` does not
  exist; the reviewer's record of e4230cc is banked there (2cf2cef) (review N13).
- **docs/HOOK.md, what the recorder keeps** (and the earlier entry below that called file
  edits "recorded as hashes, not content"): for an edit, the ledger holds the tool's input,
  which for a Write is the new content, beside hashes of the file before and after, and the
  recorder keeps a copy of the file as it was before the edit in its state directory until
  the edit's result arrives (review N15).
- **README.md, quickstart and a citation**: the quickstart listed `make ci`, the full suite,
  beside the offline demo, and did not say that `make setup` needs the network; it now
  shows setup and the demo only. Chen and Liu were cited as a NeurIPS poster; the banked
  check shows a NeurIPS workshop poster (review N12, N14).
- **docs/E0_PROTOCOL.md, Scoring and Evaluate** (changed because the code changed, before
  any held-out scoring): it said each seeded report is scored with
  `verify_run(claims, ledger, report=report)`, that is without requirements, and that the
  held-out evaluation checks four paths for uncommitted changes. The preregistration
  drafts require the verifier mode that gives each report its task's requirement texts
  (D54), so the evaluation now runs and records that mode and also checks
  `src/receipts/bench`; the document describes this.
- **README.md, the first screen and Status; docs/REPORT.md, next steps** (pushed from
  229a14f to 906140c): they said the TypeScript catalog tasks were the smoke runs still to
  run. The plan's own dry run lists the pending runs: three Python tasks and every
  TypeScript catalog task except ts-ci-workflow, which has run. Both documents now say "the
  remaining tasks, most of them TypeScript".
- **README.md and docs/REPORT.md, the wrapper** (changed because the code changed): they
  said that `receipts wrap` labels claims about the agent's commands contradicted, that
  files untracked before the run show up as added, and that neither the wrapper nor the
  `receipts` command line has tests. All three are fixed (D50), with tests, so the docs
  now describe the new behavior, and the README's Status lists G1 as passing.
- **README.md and docs/REPORT.md, status and scope wording** (pushed up to d2aa9ea): they
  called the study and its analysis scripts "preregistered" (the preregistrations are
  unfrozen drafts and `prereg/LOCK.json` does not exist yet), said receipts "checks every
  claim" (only the claims its extractor finds) and "adds" a cross-agent measurement and a
  mitigation (designed, not yet run), described E4 as a test of receipts-hook (it tests
  the hook's check code inside minimal-agent, not the Claude Code hook), presented false
  success as safe from claim avoidance (it still depends on extraction), stated a
  universal before-acting rule for DECISIONS.md (one entry was recorded late), and
  summarized two related-work sources more strongly than their banked checks support
  (overselling "common"; MASK "for chat models"). docs/REPORT.md also said CORRECTIONS.md
  had no entries and that no draft covered E3. All corrected.
- **README.md and docs/REPORT.md, the first signal** (pushed from a7067e9 to 035bf29): they
  presented "no extracted claim was contradicted" in most false successes as evidence that
  reports check out claim by claim while being wrong about the outcome, and README.md
  first said "receipts found no false sentence at all". An adversarial review of the docs,
  checked against the banked runs, found that most of those reports state the requested
  change in a sentence the extractor missed (md-toc, bizdays, atomic-store, money-round)
  or checked wrongly (slugify-tests), so the count mostly reflects the unvalidated
  extractor and is likely too high. Both documents now say so and list the errors. The
  README also described the py-cli-json error wrongly (the failure admission is correctly
  an admission; a feature claim mapped to a preserve requirement makes the run count as
  claiming success) and said "the hidden checks failed in every run" where it meant that
  no run passed all of them.
- **README.md, Use it on your own agent and module list**: it said every final report is
  checked by the Stop hook (the check is skipped after a stop-hook block and for a session
  with no tool call), that `receipts wrap` leaves claims about commands unverifiable (the
  verifier labels them contradicted, a known bug), and that every banked run is
  re-verified (only E1 and E4 banking re-verifies; the smoke numbers use run-time
  verdicts). It also said E0 agents never see the instrument code (blindness is audited
  from transcripts, not enforced) and called the whole quickstart offline (only the demo
  is). All are corrected; docs/REPORT.md and docs/HOOK.md had matching statements (file
  edits are recorded as hashes, not content; the wrapper and CLI have no tests).
- **README.md, Status section** (from commit 1352467 on the session branch): it said
  that `make ci` passes on a fresh clone before every push and that the CI workflow runs
  it on Python 3.11 and 3.12. Pushes had been checked on Python 3.11 only, and at those
  commits `make ci` failed on Python 3.12: `mypy --strict` reported errors under the
  NumPy 2.5 type stubs that the lock resolves for 3.12. Fixed in 7ac1494. The Status
  section now says that both versions are checked on a fresh clone before a push.
- **docs/HOOK.md, Measured cost and effect**: it said that the hook's added latency and
  its effect on reports (E4) "are reported" in docs/REPORT.md. Neither has been measured.
  The section now says so.
