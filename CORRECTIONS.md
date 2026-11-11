# Corrections

Every changed or withdrawn claim gets a dated entry here (rule 3 of
docs/BUILD_BRIEF.md section 9), newest first.

## 2026-11-11

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
