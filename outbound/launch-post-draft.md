# Draft: announcement post for receipts (for Raj to review and send; not sent)

Every number below is bound to `artifacts/exploratory/smoke_outcomes.json`. Check it with
`uv run --no-sync python tools/claimcheck.py outbound/launch-post-draft.md`, and run the check
again after any edit that touches a number. Copy the text from the rendered page so the
binding comments stay out of the post.

## Short version

I built receipts, an open-source tool that extracts the claims in an AI coding agent's final
report and checks each one against a ledger of what actually happened in its sandbox:
commands, exit codes, test runs, diffs, and hidden checks. Each claim comes back supported,
contradicted, or unverifiable, with the evidence attached.

First signal, exploratory and not yet a preregistered study: in
<!--n:smoke.runs-->20<!--/n--> smoke runs of a local Qwen2.5-Coder-7B-Instruct agent, no
run passed all of its hidden checks, yet <!--n:smoke.success_claimed.pct-->50%<!--/n--> of
the final reports claimed success. The runs also tested receipts itself. In
<!--n:smoke.false_success_without_contradicted_claim.k-->7<!--/n--> of those
<!--n:smoke.false_success_without_contradicted_claim.n-->10<!--/n--> false successes, no
extracted claim was contradicted, and reading the reports by hand shows why: most say the
requested change was made, in a sentence the extractor missed or checked wrongly. So the
next step is a blind validation of the extractor and verifiers, before any of this counts
as a finding.

Next: that validation, then a randomized study across agents and realistic situations (an
unattainable requirement, truncated output, time pressure, flaky tools), written as draft
preregistrations, and a test of a Claude Code Stop hook that asks the agent to correct a
report its own record contradicts.

https://github.com/raj200501/receipts

## Notes for Raj

- The small-model result says more about the instrument and the benchmark than about
  capable agents; the README's Limitations section says so, and a reader will ask.
- The instrument is not validated yet. Reading the reports by hand shows extraction
  errors, most of which make the count of false successes without a
  contradicted claim too high (README, Limitations). Say so if
  you quote the numbers.
- Before posting, fast-forward `main` to the session branch (STATUS.md, Needs Raj), so the
  link opens on the real README rather than the brief.
