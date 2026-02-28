#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

exec "${SCRIPT_DIR}/with-codex-farm.sh" "${REPO_ROOT}/.venv/bin/cookimport" "$@"
