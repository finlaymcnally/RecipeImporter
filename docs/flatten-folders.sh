#!/usr/bin/env bash
# Simple command:
#   bash docs/flatten-folders.sh <folder>
#
# If <folder> contains immediate subfolders, this script creates one output
# .md file per subfolder under <folder>_md (one level deep only).
# If no immediate subfolders exist, all files in that folder are flattened into
# a single .md file.
#
# Output examples:
#   docs/codexfarm_bench_cutdown -> docs/codexfarm_bench_cutdown_md

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <folder_path>" >&2
  exit 1
fi

input_path="$1"

if [[ ! -d "$input_path" ]]; then
  echo "Error: '$input_path' is not a directory." >&2
  exit 1
fi

input_dir="$(cd "$input_path" && pwd -P)"
input_name="$(basename "$input_dir")"
parent_dir="$(dirname "$input_dir")"
output_dir="${parent_dir}/${input_name}_md"

mkdir -p "$output_dir"

code_fence_for_file() {
  local file_name="$1"
  local ext="text"

  if [[ "$file_name" == *.* ]]; then
    case "${file_name##*.}" in
      md|MD|markdown|MARKDOWN) ext="markdown" ;;
      txt|TXT|text|TEXT) ext="text" ;;
      json|JSON|jsonl|JSONL) ext="json" ;;
      yml|YML|yaml|YAML) ext="yaml" ;;
      sh|SH|bash|BASH) ext="bash" ;;
      py|PY) ext="python" ;;
      js|JS) ext="javascript" ;;
      ts|TS) ext="typescript" ;;
      html|HTML|htm|HTM) ext="html" ;;
      css|CSS) ext="css" ;;
      sql|SQL) ext="sql" ;;
      toml|TOML) ext="toml" ;;
      ini|INI|cfg|CFG|conf|CONF) ext="ini" ;;
      csv|CSV) ext="csv" ;;
      *) ext="text" ;;
    esac
  fi

  printf '%s' "$ext"
}

flatten_one() {
  local source_dir="$1"
  local output_file="$2"
  local source_name="$3"
  local recursive="${4:-0}"
  local -a files
  local file fence

  if [[ "$recursive" -eq 1 ]]; then
    mapfile -d '' files < <(
      find "$source_dir" -type f -print0 | sort -z
    )
  else
    mapfile -d '' files < <(
      find "$source_dir" -mindepth 1 -maxdepth 1 -type f -print0 | sort -z
    )
  fi

  {
    echo '---'
    echo "summary: \"Flattened contents of ${source_name}.\""
    echo 'read_when:'
    echo '  - "When you need all files from this folder in one Markdown file."'
    echo '---'
    echo
    echo "# Flattened folder: ${source_name}"
    echo
    echo "Source: \`${source_dir}\`"
    echo

    if (( ${#files[@]} == 0 )); then
      echo "_No files found._"
    else
      for file in "${files[@]}"; do
        file_name="$(basename "$file")"
        fence="$(code_fence_for_file "$file_name")"
        echo "## ${file_name}"
        echo
        printf '```%s\n' "$fence"
        cat "$file"
        printf '\n```\n\n'
      done
    fi
  } > "$output_file"
}

mapfile -d '' subdirs < <(
  find "$input_dir" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z
)

if (( ${#subdirs[@]} > 0 )); then
  for subdir in "${subdirs[@]}"; do
    flatten_one "$subdir" "${output_dir}/$(basename "$subdir").md" "$(basename "$subdir")"
  done
else
  flatten_one "$input_dir" "${output_dir}/${input_name}.md" "$input_name" 1
fi

if (( ${#subdirs[@]} > 0 )); then
  echo "Wrote 1 MD file per immediate subfolder under: $output_dir"
else
  echo "Wrote flattened file: ${output_dir}/${input_name}.md"
fi
