#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
PYTEST_BIN="${COOKIMPORT_PYTEST_BIN:-.venv/bin/pytest}"
PYTEST_PATH="$repo_root/$PYTEST_BIN"
MAXFAIL="${COOKIMPORT_TEST_MAXFAIL:-1}"
export COOKIMPORT_TEST_SUITE=1

test_temp_root="${COOKIMPORT_TEST_TEMP_ROOT:-/tmp}"
keep_host_temp="${COOKIMPORT_TEST_KEEP_HOST_TEMP:-0}"
if [[ "$keep_host_temp" != "1" && -d "$test_temp_root" ]]; then
  override_temp_root=0
  for candidate in "${TMPDIR:-}" "${TEMP:-}" "${TMP:-}"; do
    if [[ -n "$candidate" && "$candidate" == /mnt/* ]]; then
      override_temp_root=1
      break
    fi
  done
  if [[ $override_temp_root -eq 0 && -z "${TMPDIR:-}" && -z "${TEMP:-}" && -z "${TMP:-}" ]]; then
    override_temp_root=1
  fi
  if [[ $override_temp_root -eq 1 ]]; then
    export TMPDIR="$test_temp_root"
    export TEMP="$test_temp_root"
    export TMP="$test_temp_root"
  fi
fi

domains=(analytics bench cli core ingestion labelstudio llm parsing staging)

usage() {
  cat <<'USAGE'
Usage:
  scripts/test-suite.sh smoke
    Run the smoke slice.
  scripts/test-suite.sh fast
    Run all non-slow tests.
  scripts/test-suite.sh domain <name>
    Run a specific domain folder (non-slow).
  scripts/test-suite.sh all-fast
    Run non-slow tests in each domain separately.
  scripts/test-suite.sh full
    Run the full suite (no filters).

Environment:
  COOKIMPORT_PYTEST_BIN: pytest path (default .venv/bin/pytest)
  COOKIMPORT_TEST_MAXFAIL: max failures before stop (default 1)
  COOKIMPORT_TEST_TEMP_ROOT: temp root for wrapper-driven runs when host temp points at /mnt/* (default /tmp)
  COOKIMPORT_TEST_KEEP_HOST_TEMP: set to 1 to disable the wrapper temp-root override
USAGE
}

run_pytest() {
  "$PYTEST_PATH" --maxfail="$MAXFAIL" "$@"
}

run_pytest_full() {
  "$PYTEST_PATH" "$@"
}

is_known_domain() {
  local candidate="$1"
  local d
  for d in "${domains[@]}"; do
    if [[ "$d" == "$candidate" ]]; then
      return 0
    fi
  done
  return 1
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

mode="${1}"
shift

case "$mode" in
  smoke)
    run_pytest -m smoke "$@"
    ;;
  fast)
    run_pytest -m "not slow" "$@"
    ;;
  domain)
    if [[ $# -lt 1 ]]; then
      echo "Missing domain name. Use one of: ${domains[*]}" >&2
      exit 1
    fi
    domain="$1"
    shift
    if ! is_known_domain "$domain"; then
      echo "Unknown domain '$domain'. Use one of: ${domains[*]}" >&2
      exit 1
    fi
    run_pytest "tests/$domain" -m "not slow" "$@"
    ;;
  all-fast)
    for domain in "${domains[@]}"; do
      echo "===> tests/$domain (non-slow)"
      run_pytest "tests/$domain" -m "not slow" "$@"
    done
    # Root-level cross-domain test that is intentionally outside domain folders.
    run_pytest tests/test_eval_freeform_practical_metrics.py "$@"
    ;;
  full)
    run_pytest_full "$@"
    ;;
  *)
    usage
    exit 1
    ;;
esac
