#!/usr/bin/env bash
# Extract one commit's src/ under runs/code/<sha>/ so a long study session imports that
# exact code while other work edits the working tree (see tools/run_study.py code_state).
#   tools/snapshot_code.sh [<commit>]    # default HEAD; prints the PYTHONPATH to use
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
sha="$(git -C "$root" rev-parse "${1:-HEAD}")"
dest="$root/runs/code/$sha"
if [ ! -f "$dest/SNAPSHOT_OF" ]; then
  rm -rf "$dest"
  mkdir -p "$dest"
  git -C "$root" archive "$sha" src | tar -x -C "$dest"
  printf '%s\n' "$sha" > "$dest/SNAPSHOT_OF"
fi
printf '%s\n' "$dest/src"
