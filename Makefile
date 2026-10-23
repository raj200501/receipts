# receipts: every target from docs/BUILD_BRIEF.md section 10.1 step 7.
# Targets that are not built yet exit non-zero with a message saying so.

SHELL := /bin/bash
PY ?= 3.11
RUN := uv run --no-sync
COV_JSON ?= runs/coverage.json
PYTEST_ARGS ?=

.PHONY: setup doctor test lint typecheck ci demo prereg-verify claimcheck freshness \
	citecheck secrets-scan budget review report reproduce ship-check

setup:
	uv sync --locked --python $(PY)

doctor:
	PYTHONPATH=src python3 -m receipts.doctor --apply

test:
	@mkdir -p "$(dir $(COV_JSON))"
	$(RUN) pytest --cov=receipts --cov-report=term-missing \
		--cov-report=json:$(COV_JSON) $(PYTEST_ARGS)

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

typecheck:
	$(RUN) mypy --strict

ci: lint typecheck test demo

demo:
	$(RUN) python tools/demo.py --check

prereg-verify:
	$(RUN) python tools/prereg.py verify

claimcheck:
	$(RUN) python tools/claimcheck.py README.md docs/REPORT.md

freshness:
	$(RUN) python tools/freshness.py README.md docs/REPORT.md

citecheck:
	$(RUN) python tools/citecheck.py README.md docs/REPORT.md

secrets-scan:
	$(RUN) python tools/secrets_scan.py

budget:
	$(RUN) python tools/budget_report.py

review:
	$(RUN) python tools/review.py

report:
	$(RUN) python tools/report.py

reproduce:
	$(RUN) python tools/report.py --reproduce

ship-check:
	python3 tools/ship_check.py
