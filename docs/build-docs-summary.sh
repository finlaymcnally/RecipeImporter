#!/usr/bin/env bash
# How to run:
#   bash docs/build-docs-summary.sh
# Output:
#   docs/<timestamp>_<root_folder_name>-docs-summary.md
# Note:
#   Only .md and .txt files are included in the generated summary.
#   Sources include docs/ and llm_pipelines/prompts/ (if that folder exists).
#   Files ending with "_log.md" are skipped.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docs_dir="${repo_root}/docs"
prompts_dir="${repo_root}/llm_pipelines/prompts"
repo_name="$(basename "$repo_root")"
timestamp="$(date +"%Y-%m-%d_%H.%M.%S")"
output="${docs_dir}/${timestamp}_${repo_name}-docs-summary.md"

if [[ ! -d "$docs_dir" ]]; then
  echo "Docs directory not found: $docs_dir" >&2
  exit 1
fi

find_roots=("$docs_dir")
source_roots=("docs/")

if [[ -d "$prompts_dir" ]]; then
  find_roots+=("$prompts_dir")
  source_roots+=("llm_pipelines/prompts/")
fi

source_roots_display="$(printf '%s, ' "${source_roots[@]}")"
source_roots_display="${source_roots_display%, }"

mapfile -d '' files < <(find "${find_roots[@]}" -type f -print0 | sort -z)

{
  cat <<EOF
---
summary: "Combined snapshot of docs/ as of ${timestamp}."
read_when:
  - When you need a single-file snapshot of the docs tree.
---
# ${repo_name} Docs Summary
Generated: ${timestamp}
Source roots: ${source_roots_display}

EOF

  for file in "${files[@]}"; do
    if [[ "$file" == "$output" ]]; then
      continue
    fi

    # Skip architecture/build/fix-attempt log docs.
    if [[ "$file" == *"_log.md" ]]; then
      continue
    fi

    ext="${file##*.}"
    ext_lower="$(printf "%s" "$ext" | tr '[:upper:]' '[:lower:]')"
    
    # Only summarize .md and .txt files
    case "$ext_lower" in
      md|txt) ;;
      *) continue ;;
    esac

    # Skip previous summary files to avoid recursive inclusion.
    if [[ "$file" == *"-docs-summary.md" ]]; then
      continue
    fi

    rel="${file#$repo_root/}"
    echo "## ${rel}"
    echo ""

    case "$ext_lower" in
      md) lang="markdown" ;;
      txt) lang="text" ;;
      *) lang="" ;;
    esac

    printf '```%s\n' "$lang"
    cat "$file"
    printf '```\n'
    echo ""
  done
} > "$output"

echo "Wrote $output"
