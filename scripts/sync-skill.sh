#!/usr/bin/env bash
# Copy the canonical skill (skill/) into every package that ships it.
#   scripts/sync-skill.sh          write the copies
#   scripts/sync-skill.sh --check  fail if any copy is out of date (CI)
set -euo pipefail
cd "$(dirname "$0")/.."
targets=(plugins/claude-code/skills/macos-computer-use packages/pi/skills/macos-computer-use)
status=0
for t in "${targets[@]}"; do
  if [ "${1:-}" = "--check" ]; then
    if ! diff -r skill "$t" >/dev/null 2>&1; then
      echo "out of date: $t (run scripts/sync-skill.sh)" >&2
      status=1
    fi
  else
    rm -rf "$t" && mkdir -p "$(dirname "$t")" && cp -R skill "$t"
    echo "synced $t"
  fi
done
exit $status
