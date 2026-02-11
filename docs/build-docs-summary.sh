#!/usr/bin/env bash
# How to run:
#   bash docs/build-docs-summary.sh
# Output:
#   docs/<timestamp>_importer-docs-summary.md
# Note:
#   Image files are skipped from the generated summary.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docs_dir="${repo_root}/docs"
timestamp="$(date +"%Y-%m-%d_%H%M%S")"
output="${docs_dir}/${timestamp}_importer-docs-summary.md"

if [[ ! -d "$docs_dir" ]]; then
  echo "Docs directory not found: $docs_dir" >&2
  exit 1
fi

mapfile -d '' files < <(find "$docs_dir" -type f -print0 | sort -z)

{
  cat <<EOF
---
summary: "Combined snapshot of docs/ as of ${timestamp}."
read_when:
  - When you need a single-file snapshot of the docs tree.
---
# Importer Docs Summary
Generated: ${timestamp}
Source root: docs/

EOF

  for file in "${files[@]}"; do
    if [[ "$file" == "$output" ]]; then
      continue
    fi

    ext="${file##*.}"
    ext_lower="$(printf "%s" "$ext" | tr '[:upper:]' '[:lower:]')"
    case "$ext_lower" in
      png|jpg|jpeg|gif|bmp|webp|tiff|tif|svg|ico|avif|heic|heif)
        continue
        ;;
    esac

    mime_info="$(file --mime "$file" 2>/dev/null || true)"
    if [[ "$mime_info" == *"image/"* ]]; then
      continue
    fi

    rel="${file#$repo_root/}"
    echo "## ${rel}"
    echo ""

    if [[ "$mime_info" == *"charset=binary"* ]]; then
      echo "_Binary file; base64-encoded below._"
      echo ""
      printf '```base64\n'
      base64 "$file"
      printf '```\n'
      echo ""
      continue
    fi

    case "$ext_lower" in
      md) lang="markdown" ;;
      json) lang="json" ;;
      ts) lang="ts" ;;
      html|htm) lang="html" ;;
      txt) lang="text" ;;
      yml|yaml) lang="yaml" ;;
      *) lang="" ;;
    esac

    if [[ -n "$lang" ]]; then
      printf '```%s\n' "$lang"
    else
      printf '```\n'
    fi
    cat "$file"
    printf '```\n'
    echo ""
  done
} > "$output"

echo "Wrote $output"
