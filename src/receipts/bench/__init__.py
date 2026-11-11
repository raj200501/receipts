"""receipts-bench: benchmark task specification, static rules, and reference validation.

docs/BENCH.md is the authoring spec. Modules:

- :mod:`receipts.bench.spec`: dataclasses and the strict loader for ``task.toml``
  and ``manifest.json``;
- :mod:`receipts.bench.layout`: static rules on a task's file tree;
- :mod:`receipts.bench.priorwork`: the M4 prior-work transcript format;
- :mod:`receipts.bench.hashing`: the task tree hash shared with ``tools/ship_check.py``;
- :mod:`receipts.bench.validate`: :func:`validate_task`, which runs everything
  through a :class:`receipts.sandbox.api.Sandbox`;
- :mod:`receipts.bench.artifact`: validating many tasks and the G6 artifact
  (``artifacts/bench/reference_validation.json``), written by ``tools/bench_validate.py``.
"""
