# Contributing

Thanks for your interest. receipts is a measurement project, so the bar for
changes is reproducibility and honest reporting.

## Setup

```bash
make setup     # uv sync with the locked dev dependencies (Python 3.11+)
make doctor    # what this machine can run
make ci        # lint, typecheck, test, offline demo
```

## Rules for changes

- Every public function has types, a docstring, and tests. `make lint
  typecheck test` must pass, and `mypy --strict` must stay clean. Every
  `type: ignore` carries a reason after it.
- Never hand-type a result number in README.md, docs/REPORT.md, or any results
  document. Numbers come from committed scripts over banked artifacts under
  `artifacts/`; `make claimcheck` and `make freshness` enforce this.
- Confirmatory analyses need a frozen preregistration in `prereg/` committed
  before the data exists. Changes are new, dated amendment files.
- Label synthetic or mock data as such everywhere it appears.
- Record interpretations and deviations in DECISIONS.md, and every changed or
  withdrawn claim in CORRECTIONS.md.
- Plain writing: no hype words and no em dashes.
- Never commit secrets, real transcripts, or anything under `private/`.

## Gates

`make ship-check` runs the 14 Definition-of-Done gates from
docs/BUILD_BRIEF.md section 6 on a fresh clone of HEAD. A gate is never passed
by weakening its check.
