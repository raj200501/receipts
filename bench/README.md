# receipts-bench

Small, realistic Python and TypeScript repositories with tasks for coding agents. Each
task ships hidden ground-truth checks, a reference solution that passes them, and a
manifest of the manipulations used in the receipts study (M1 to M5).

- `tasks/<task_id>/`: one task per directory, written to the spec in
  [docs/BENCH.md](../docs/BENCH.md); the planned set is in
  [docs/BENCH_CATALOG.md](../docs/BENCH_CATALOG.md).
- `prompts/pressure.txt`: the shared M3 pressure text appended to the request.

Every repository here is hand-written synthetic code made for this benchmark, not a
real project. Tasks named `pilot-*` are reserved for pilots and dry runs and are never
part of a confirmatory sample. The four exemplar tasks show the patterns the spec
describes:

| Task | Language | Category | What the agent is asked to do |
| --- | --- | --- | --- |
| `pilot-py-timesheet` | python | bug_fix | count overnight shifts correctly and reject empty entries |
| `pilot-py-bizdays` | python | feature | read several closure calendars and add a `between` command |
| `pilot-ts-gradebook` | typescript | bug_fix | leave excused work out and assign letters from unrounded percentages |
| `pilot-ts-feedsync` | typescript | feature | read Atom feeds, add the status feed, and add `--since` |

Validate tasks with `tools/bench_validate.py`. It runs every command in a sandbox:

    python tools/bench_validate.py --task pilot-py-bizdays    # one task, writes nothing
    python tools/bench_validate.py                            # all tasks, writes the artifact
    python tools/bench_validate.py --verify                   # is the artifact current?

A full run writes `artifacts/bench/reference_validation.json`, which gate G6 checks
against the current task files.
