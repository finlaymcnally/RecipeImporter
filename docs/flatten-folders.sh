#!/usr/bin/env bash
# Simple command:
#   bash docs/flatten-folders.sh <folder>
#
# If <folder> contains immediate subfolders, this script creates one output
# .md file per subfolder under <folder>_md (one level deep only).
# If no immediate subfolders exist, all files in that folder are flattened into
# a single .md file.
#
# By default, this script avoids exploding output size by:
# - truncating large files to a preview (see FLATTEN_MAX_BYTES)
# - not inlining raw binary blobs (e.g. .png, .zip)
# - previewing .gz files by showing a decompressed excerpt (not raw gzip bytes)
#
# Environment variables:
#   FLATTEN_MAX_BYTES   Max bytes to inline per file (default: 120000).
#
# Output examples:
#   docs/codex_exec_bench_cutdown -> docs/codex_exec_bench_cutdown_md

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

max_bytes="${FLATTEN_MAX_BYTES:-120000}"
if [[ ! "$max_bytes" =~ ^[0-9]+$ ]] || [[ "$max_bytes" -le 0 ]]; then
  echo "Error: FLATTEN_MAX_BYTES must be a positive integer (got: '$max_bytes')." >&2
  exit 1
fi

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

is_binary_extension() {
  local file_name="$1"
  if [[ "$file_name" != *.* ]]; then
    return 1
  fi
  case "${file_name##*.}" in
    # Treat gzip separately (we preview decompressed content).
    gz|GZ) return 1 ;;
    # Common binary / archive formats: do not inline raw bytes.
    zip|ZIP|tar|TAR|tgz|TGZ|bz2|BZ2|xz|XZ|7z|7Z|rar|RAR) return 0 ;;
    png|PNG|jpg|JPG|jpeg|JPEG|gif|GIF|webp|WEBP|bmp|BMP|ico|ICO|icns|ICNS) return 0 ;;
    pdf|PDF) return 0 ;;
    mp3|MP3|mp4|MP4|m4a|M4A|mov|MOV|avi|AVI|wav|WAV|flac|FLAC|ogg|OGG) return 0 ;;
    parquet|PARQUET|arrow|ARROW|feather|FEATHER|avro|AVRO) return 0 ;;
    sqlite|SQLITE|db|DB) return 0 ;;
    *) return 1 ;;
  esac
}

write_file_preview() {
  local file_path="$1"
  local file_name
  file_name="$(basename "$file_path")"

  if is_binary_extension "$file_name"; then
    local size_bytes
    size_bytes="$(wc -c <"$file_path" | tr -d ' ')"
    echo "_Omitted: binary file (${size_bytes} bytes)._"
    return 0
  fi

  if [[ "$file_name" == *.gz || "$file_name" == *.GZ ]]; then
    local size_bytes
    size_bytes="$(wc -c <"$file_path" | tr -d ' ')"
    echo "_gzip file (${size_bytes} bytes). Showing up to ${max_bytes} bytes of decompressed preview._"
    echo
    # Do not inline raw gzip bytes; preview the decompressed content.
    gzip -dc "$file_path" 2>/dev/null | head -c "$max_bytes" || true
    echo
    echo
    echo "_(End of decompressed preview.)_"
    return 0
  fi

  local size_bytes
  size_bytes="$(wc -c <"$file_path" | tr -d ' ')"
  if [[ "$size_bytes" -le "$max_bytes" ]]; then
    cat "$file_path"
    return 0
  fi

  echo "_Truncated: ${size_bytes} bytes total. Showing first ${max_bytes} bytes._"
  echo
  head -c "$max_bytes" "$file_path"
  echo
  echo
  echo "_(End of preview.)_"
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
        write_file_preview "$file"
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
