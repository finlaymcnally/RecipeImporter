#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  cat >&2 <<'USAGE'
Usage: scripts/with-codex-farm.sh <command> [args...]

Runs one command with COOKIMPORT_ALLOW_CODEX_FARM=1 for this process only.
Example:
  scripts/with-codex-farm.sh cookimport stage ./book.epub --llm-recipe-pipeline codex-farm-3pass-v1
USAGE
  exit 2
fi

export COOKIMPORT_ALLOW_CODEX_FARM=1
exec "$@"
