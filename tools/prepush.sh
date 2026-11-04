#!/bin/bash
# Pre-push check (DECISIONS D27, D28): `make ci` must pass on a fresh clone of HEAD
# before anything is pushed. Writes nothing inside the working tree.
set -euo pipefail
ROOT=$(git rev-parse --show-toplevel)
SHA=$(git -C "$ROOT" rev-parse HEAD)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/receipts-prepush-XXXXXX")
trap 'rm -rf "$TMP"' EXIT
git clone --quiet "$ROOT" "$TMP/clone"
git -C "$TMP/clone" checkout --quiet --detach "$SHA"
cd "$TMP/clone"
export PYTHONDONTWRITEBYTECODE=1
unset VIRTUAL_ENV
if make --no-print-directory setup >"$TMP/setup.log" 2>&1 && make --no-print-directory ci >"$TMP/ci.log" 2>&1; then
  echo "PREPUSH: PASS make ci on fresh clone of $SHA"
else
  tail -n 40 "$TMP/setup.log" "$TMP/ci.log" 2>/dev/null || true
  echo "PREPUSH: FAIL make ci on fresh clone of $SHA (do not push)"
  exit 1
fi
