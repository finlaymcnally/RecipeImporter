#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCOPE="${DEV_CLEAN_SCOPE:-all}"

echo "[dev:clean] repo: ${ROOT_DIR} (scope: ${SCOPE})"

# Stop supabase containers for this repo when scope allows it.
if [[ "${SCOPE}" != "next" ]] && [[ -f "${ROOT_DIR}/supabase/config.toml" ]]; then
  if command -v docker >/dev/null 2>&1; then
    project_id=$(awk -F '"' '/^project_id[[:space:]]*=/{print $2; exit}' "${ROOT_DIR}/supabase/config.toml" || true)
    if [[ -n "${project_id}" ]]; then
      containers=$(docker ps --format '{{.Names}}' | grep -E "supabase_.*_${project_id}$" || true)
      if [[ -n "${containers}" ]]; then
        echo "[dev:clean] stopping supabase containers: ${containers}"
        docker stop ${containers} >/dev/null
      fi
    fi
  else
    echo "[dev:clean] docker not found; skipping supabase stop"
  fi
fi

# Kill Next dev + child node processes for this repo.
pids=$(ps -eo pid=,args= | awk -v root="${ROOT_DIR}" '
  $0 ~ root && ($0 ~ /next dev/ || $0 ~ /\.next\/dev/) {print $1}
' | tr '\n' ' ')

if [[ -n "${pids}" ]]; then
  echo "[dev:clean] terminating Next dev pids: ${pids}"
  kill -TERM ${pids} 2>/dev/null || true
  sleep 1
  for pid in ${pids}; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
  done
fi

echo "[dev:clean] done"
