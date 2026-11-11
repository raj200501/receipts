# Corrections

Every changed or withdrawn claim gets a dated entry here (rule 3 of
docs/BUILD_BRIEF.md section 9), newest first.

## 2026-11-11

- **README.md, Status section** (from commit 1352467 on the session branch): it said
  that `make ci` passes on a fresh clone before every push and that the CI workflow runs
  it on Python 3.11 and 3.12. Pushes had been checked on Python 3.11 only, and at those
  commits `make ci` failed on Python 3.12: `mypy --strict` reported errors under the
  NumPy 2.5 type stubs that the lock resolves for 3.12. Fixed in 7ac1494. The Status
  section now says that both versions are checked on a fresh clone before a push.
- **docs/HOOK.md, Measured cost and effect**: it said that the hook's added latency and
  its effect on reports (E4) "are reported" in docs/REPORT.md. Neither has been measured.
  The section now says so.
