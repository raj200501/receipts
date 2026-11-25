# Draft: announcement post for receipts (for Raj to review and send; not sent)

Every number below is bound to `artifacts/exploratory/smoke_outcomes.json`. Check it with
`uv run --no-sync python tools/claimcheck.py outbound/launch-post-draft.md`, and run the check
again after any edit that touches a number. Copy the text from the rendered page so the
binding comments stay out of the post.

## Short version

Every AI coding agent ends its work with a report, and people act on it: they merge, close
the ticket, move on. I built receipts, an open-source tool that splits that report into
atomic claims and checks each one against a hash-chained ledger of what actually happened in
the agent's sandbox: commands, exit codes, test runs, diffs, and hidden checks the agent
never had. Each claim comes back supported, contradicted, or unverifiable, with the evidence
attached. It runs offline, around any agent CLI, or live in Claude Code as a Stop hook.

First signal, exploratory and not yet a preregistered study: in
<!--n:smoke.runs-->40<!--/n--> unmanipulated runs of a local Qwen2.5-Coder-7B-Instruct
agent, no run completed its task, yet <!--n:smoke.success_claimed.pct-->38%<!--/n--> of the
final reports claimed success. In one run the agent wrote no file and reported adding tests;
receipts contradicted the claim and pointed at the empty diff. In another, the agent's only
edit failed and its report still described a finished, tested refactor, and the extractor
found no claim to check, so no claim was contradicted; receipts listed only the failed hidden
checks the report does not admit. Measuring that gap is the next step: a
blind validation of the extractor and verifiers, before any of this counts as a finding.

After that: a randomized study across agents and realistic situations (an unattainable
requirement, truncated output, time pressure, flaky tools), written as draft
preregistrations, and a test of the Claude Code hook that asks the agent to correct a report
its own record contradicts.

https://github.com/raj200501/receipts

## Notes for Raj

- The small-model result says more about the instrument and the benchmark than about
  capable agents; the README's Limitations section says so, and a reader will ask.
- The instrument is not validated yet. Reading the reports by hand shows extraction
  errors, most of which make the count of false successes without a contradicted claim too
  high (README, Limitations). Say so if you quote the numbers.
- The missed report is worth naming, not hiding: it shows why the blind validation (E0)
  comes first.
- Check that the link opens on the latest RELEASE-READY commit of `main`.
