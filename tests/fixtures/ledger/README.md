# Ledger parser fixtures (hand-written)

Every file under this directory is a **hand-written example**, modeled on the
output format of the named tool and version. None of them was captured from a
real run, and none of the numbers in them is a measured result. They exist only
to test the parsers in `src/receipts/ledger/parsers/`.

One file is copied from real tool output instead: `node/spec_nested_suites.txt` is
Node v22's spec reporter run on a toy test file written for the fixture (stack frames
removed). It is not a model run and holds no measured result.

Where the file format allows it, the first line or a comment says so again
(`[hand-written fixture ...]`). Parsers must ignore that line, the same way they
ignore any other log text around a recognized summary. The one exception is
`lint/eslint_clean_npm.txt`, whose point is that it holds no tool output at all
(ESLint prints nothing on success); this README is its label.

| Directory | Modeled on |
| --- | --- |
| `pytest/` | pytest 8.3 terminal output: normal, `-q`, `-v`, `-rA`, collection errors, ANSI color, truncated |
| `unittest/` | `python -m unittest` (Python 3.11) |
| `junit/` | JUnit XML from pytest `--junitxml`, jest-junit, mocha-junit-reporter |
| `node/` | `node --test` (Node 20 and 22): TAP and spec reporters, inside `npm test` |
| `jest/` | Jest 29 default and `--verbose` reporters, inside `npm test` |
| `vitest/` | Vitest 1.6 and 2.1 default reporter |
| `mocha/` | Mocha 10 spec reporter |
| `lint/` | ruff 0.12, flake8 7, ESLint 9 stylish, `ruff format --check` |
| `typecheck/` | mypy 1.11, pyright 1.1, tsc 5.5 (plain and pretty) |
| `git/` | `git diff --numstat -M` and `git diff --name-status -M` |
| `manifests/` | requirements.txt, pyproject.toml (PEP 621, PEP 735, Poetry), package.json |
| `hidden/` | the hidden-check output contract (last stdout line is a JSON object) |
| `mixed/` | wrappers that run several tools in one command (`make ci`) |
