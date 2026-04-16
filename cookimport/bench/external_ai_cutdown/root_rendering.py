from __future__ import annotations

import gzip
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from cookimport.bench.comparison_artifacts import (
    PRIMARY_BENCHMARK_COMPARISON_JSON_FILE_NAME,
    resolve_existing_benchmark_comparison_json_path,
)

_FLATTEN_MAX_BYTES = 120000
_BINARY_EXTENSIONS = {
    ".zip",
    ".tar",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".icns",
    ".pdf",
    ".mp3",
    ".mp4",
    ".m4a",
    ".mov",
    ".avi",
    ".wav",
    ".flac",
    ".ogg",
    ".parquet",
    ".arrow",
    ".feather",
    ".avro",
    ".sqlite",
    ".db",
}
_CODE_FENCE_BY_EXTENSION = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".text": "text",
    ".json": "json",
    ".jsonl": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".sh": "bash",
    ".bash": "bash",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".sql": "sql",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".csv": "csv",
}


def _code_fence_for_file(path: Path) -> str:
    return _CODE_FENCE_BY_EXTENSION.get(path.suffix.lower(), "text")


def _is_binary_extension(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix == ".gz":
        return False
    return suffix in _BINARY_EXTENSIONS


def _render_file_preview(path: Path, *, max_bytes: int) -> str:
    size_bytes = int(path.stat().st_size)
    if _is_binary_extension(path):
        return f"_Omitted: binary file ({size_bytes} bytes)._"

    if path.suffix.lower() == ".gz":
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
                preview = handle.read(max_bytes)
        except OSError:
            return "_Omitted: unreadable gzip file._"
        return (
            f"_gzip file ({size_bytes} bytes). Showing up to {max_bytes} bytes of decompressed preview._\n\n"
            f"{preview}\n\n_(End of decompressed preview.)_"
        )

    raw_bytes = path.read_bytes()
    if size_bytes <= max_bytes:
        return raw_bytes.decode("utf-8", errors="replace")
    preview = raw_bytes[:max_bytes].decode("utf-8", errors="replace")
    return (
        f"_Truncated: {size_bytes} bytes total. Showing first {max_bytes} bytes._\n\n"
        f"{preview}\n\n_(End of preview.)_"
    )


def _write_flattened_markdown(
    *,
    source_dir: Path,
    output_file: Path,
    source_name: str,
    recursive: bool = False,
    max_bytes: int = _FLATTEN_MAX_BYTES,
) -> None:
    if recursive:
        files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    else:
        files = sorted(path for path in source_dir.iterdir() if path.is_file())

    lines: list[str] = [
        "---",
        f'summary: "Flattened contents of {source_name}."',
        "read_when:",
        '  - "When you need all files from this folder in one Markdown file."',
        "---",
        "",
        f"# Flattened folder: {source_name}",
        "",
        f"Source: `{source_dir}`",
        "",
    ]
    if not files:
        lines.append("_No files found._")
    else:
        for path in files:
            section_name = (
                str(path.relative_to(source_dir)) if recursive else path.name
            )
            lines.append(f"## {section_name}")
            lines.append("")
            lines.append(f"```{_code_fence_for_file(path)}")
            lines.append(_render_file_preview(path, max_bytes=max_bytes))
            lines.append("```")
            lines.append("")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _flatten_output_without_script(
    *,
    output_dir: Path,
    md_output_dir: Path,
    max_bytes: int = _FLATTEN_MAX_BYTES,
) -> None:
    subdirs = sorted(path for path in output_dir.iterdir() if path.is_dir())
    if subdirs:
        for subdir in subdirs:
            _write_flattened_markdown(
                source_dir=subdir,
                output_file=md_output_dir / f"{subdir.name}.md",
                source_name=subdir.name,
                recursive=False,
                max_bytes=max_bytes,
            )
        return

    _write_flattened_markdown(
        source_dir=output_dir,
        output_file=md_output_dir / f"{output_dir.name}.md",
        source_name=output_dir.name,
        recursive=True,
        max_bytes=max_bytes,
    )


def _append_json_section(
    sections: list[str],
    *,
    title: str,
    path: Path,
    load_json: Callable[[Path], dict[str, Any]],
) -> None:
    if not path.is_file():
        return
    sections.append(f"## {title}")
    sections.append("```json")
    sections.append(json.dumps(load_json(path), indent=2, sort_keys=True))
    sections.append("```")
    sections.append("")


def _write_readme(
    *,
    output_dir: Path,
    input_dir: Path,
    records: list[Any],
    sample_limit: int,
    excerpt_limit: int,
    prompt_pairs_per_category: int,
    project_context_digest_lines: list[str],
    flattened: bool,
    timestamp_now: Callable[[], str],
    full_prompt_log_file_name: str,
    line_level_sampled_jsonl_inputs: tuple[tuple[str, str], ...],
    wrong_label_full_context_file_name: str,
    preprocess_trace_failures_file_name: str,
    prompt_log_file_name: str,
    prompt_warning_aggregate_file_name: str,
    projection_trace_file_name: str,
    changed_lines_file_name: str,
    per_recipe_breakdown_file_name: str,
    targeted_prompt_cases_file_name: str,
    label_policy_notes_file_name: str,
    starter_pack_dir_name: str,
) -> None:
    lines: list[str] = []
    lines.append("# Benchmark Need-To-Know Package")
    lines.append("")
    lines.append(f"Generated: {timestamp_now()}")
    lines.append(f"Source folder: `{input_dir}`")
    lines.append(f"Run count: {len(records)}")
    lines.append(f"Sample limit per JSONL artifact: {sample_limit}")
    lines.append(f"Excerpt char limit for sampled text fields: {excerpt_limit}")
    if prompt_pairs_per_category <= 0:
        lines.append(
            "Codex Exec sampled prompt log: convenience file keeps all calls from "
            "`full_prompt_log.jsonl` when available."
        )
    else:
        lines.append(
            "Codex Exec sampled prompt log: convenience-only sampled calls per stage "
            f"(max {prompt_pairs_per_category}, sampled from full_prompt_log.jsonl when available)"
        )
    lines.append(
        "Codex Exec full prompt log: `full_prompt_log.jsonl` copied as complete machine-readable call rows (no sampling/truncation)."
    )
    lines.append("")
    lines.append("Each run folder includes:")
    lines.append("- `need_to_know_summary.json`")
    lines.append("- `eval_report.md` (if present in source run)")
    lines.append(f"- `{full_prompt_log_file_name}` (required for codex-enabled runs)")
    for _, output_name in line_level_sampled_jsonl_inputs:
        lines.append(f"- `{output_name}`")
    lines.append(f"- `{wrong_label_full_context_file_name}` (when wrong-label rows exist)")
    lines.append(
        f"- `{preprocess_trace_failures_file_name}` "
        "(codex runs with failures and available prediction/context artifacts)"
    )
    lines.append(f"- `{prompt_log_file_name}` (optional convenience-only)")
    lines.append(
        f"- `{prompt_warning_aggregate_file_name}` (codex runs when full log is available)"
    )
    lines.append(f"- `{projection_trace_file_name}` (codex runs when full log is available)")
    lines.append(
        "- `unmatched_pred_blocks.jsonl` is reported as counts-only by default; "
        "alignment debug samples are emitted only when alignment quality is weak."
    )
    lines.append("")
    lines.append("Root files:")
    lines.append("- `run_index.json`")
    lines.append("- `comparison_summary.json`")
    lines.append(f"- `{changed_lines_file_name}`")
    lines.append(f"- `{per_recipe_breakdown_file_name}`")
    lines.append(f"- `{targeted_prompt_cases_file_name}`")
    lines.append(f"- `{label_policy_notes_file_name}`")
    lines.append("- `process_manifest.json`")
    lines.append(f"- `{starter_pack_dir_name}/` (deterministic blended first-look starter pack)")
    if flattened:
        lines.append("")
        lines.append(
            "Flattened markdown output is written to sibling folder "
            f"`{output_dir.name}_md`."
        )
    lines.append("")
    lines.append("## Project Context Digest")
    lines.append("")
    lines.extend(project_context_digest_lines)
    lines.append("")
    lines.append("Run index:")
    for record in sorted(records, key=lambda row: str(getattr(row, "run_id", ""))):
        lines.append(
            "- "
            f"`{getattr(record, 'output_subdir', '')}` | "
            f"source={getattr(record, 'source_file', None) or 'unknown'} "
            f"| llm_recipe_pipeline={getattr(record, 'llm_recipe_pipeline', '')} "
            f"| atomic_block_splitter={getattr(record, 'atomic_block_splitter', '')} "
            f"| line_role_pipeline={getattr(record, 'line_role_pipeline', '')} "
            f"| overall_line_accuracy={getattr(record, 'metric_overall_line_accuracy', None)}"
        )
    lines.append("")

    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_root_summary_markdown(
    output_dir: Path,
    *,
    aggregated_root_summary_md: str,
    changed_lines_file_name: str,
    per_recipe_breakdown_file_name: str,
    targeted_prompt_cases_file_name: str,
    label_policy_notes_file_name: str,
    load_json: Callable[[Path], dict[str, Any]],
    jsonl_row_count: Callable[[Path], int],
) -> Path:
    readme_path = output_dir / "README.md"
    run_index_path = output_dir / "run_index.json"
    comparison_summary_path = output_dir / "comparison_summary.json"
    changed_lines_path = output_dir / changed_lines_file_name
    per_recipe_breakdown_path = output_dir / per_recipe_breakdown_file_name
    targeted_prompt_cases_path = output_dir / targeted_prompt_cases_file_name
    label_policy_notes_path = output_dir / label_policy_notes_file_name
    process_manifest_path = output_dir / "process_manifest.json"

    sections: list[str] = ["# Benchmark Need-To-Know Package (Flattened)", ""]

    if readme_path.is_file():
        sections.append("## README")
        sections.append(readme_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    _append_json_section(
        sections,
        title="run_index.json",
        path=run_index_path,
        load_json=load_json,
    )
    _append_json_section(
        sections,
        title="comparison_summary.json",
        path=comparison_summary_path,
        load_json=load_json,
    )

    if changed_lines_path.is_file():
        sections.append(f"## {changed_lines_file_name}")
        sections.append(f"Rows: {jsonl_row_count(changed_lines_path)} (see file for full details).")
        sections.append("")

    _append_json_section(
        sections,
        title=per_recipe_breakdown_file_name,
        path=per_recipe_breakdown_path,
        load_json=load_json,
    )

    if targeted_prompt_cases_path.is_file():
        sections.append(f"## {targeted_prompt_cases_file_name}")
        sections.append(targeted_prompt_cases_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    if label_policy_notes_path.is_file():
        sections.append(f"## {label_policy_notes_file_name}")
        sections.append(label_policy_notes_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    _append_json_section(
        sections,
        title="process_manifest.json",
        path=process_manifest_path,
        load_json=load_json,
    )

    output_path = output_dir / aggregated_root_summary_md
    output_path.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")

    for source_path in (
        readme_path,
        run_index_path,
        comparison_summary_path,
        process_manifest_path,
    ):
        if source_path.is_file():
            source_path.unlink()

    return output_path


def _flatten_output(
    *,
    repo_root: Path,
    output_dir: Path,
    flatten_script: Path,
    root_metadata_files: tuple[str, ...],
    starter_pack_dir_name: str,
    aggregated_root_summary_md: str,
    changed_lines_file_name: str,
    per_recipe_breakdown_file_name: str,
    targeted_prompt_cases_file_name: str,
    label_policy_notes_file_name: str,
    load_json: Callable[[Path], dict[str, Any]],
    jsonl_row_count: Callable[[Path], int],
) -> Path:
    script_path = (
        (repo_root / flatten_script).resolve()
        if not flatten_script.is_absolute()
        else flatten_script
    )
    md_output_dir = output_dir.parent / f"{output_dir.name}_md"
    md_output_dir.mkdir(parents=True, exist_ok=True)
    if script_path.is_file():
        subprocess.run(
            ["bash", str(script_path), str(output_dir)],
            cwd=repo_root,
            check=True,
        )
    else:
        _flatten_output_without_script(output_dir=output_dir, md_output_dir=md_output_dir)

    for file_name in root_metadata_files:
        source = output_dir / file_name
        if source.is_file():
            shutil.copy2(source, md_output_dir / file_name)
    starter_pack_source = output_dir / starter_pack_dir_name
    if starter_pack_source.is_dir():
        shutil.copytree(
            starter_pack_source,
            md_output_dir / starter_pack_dir_name,
            dirs_exist_ok=True,
        )

    _write_root_summary_markdown(
        md_output_dir,
        aggregated_root_summary_md=aggregated_root_summary_md,
        changed_lines_file_name=changed_lines_file_name,
        per_recipe_breakdown_file_name=per_recipe_breakdown_file_name,
        targeted_prompt_cases_file_name=targeted_prompt_cases_file_name,
        label_policy_notes_file_name=label_policy_notes_file_name,
        load_json=load_json,
        jsonl_row_count=jsonl_row_count,
    )
    return md_output_dir


def write_flattened_summary_for_existing_runs(
    *,
    output_dir: Path,
    timestamp_now: Callable[[], str],
    aggregated_root_summary_md: str,
    starter_pack_dir_name: str,
    starter_pack_readme_file_name: str,
    starter_pack_manifest_file_name: str,
    starter_pack_comparison_mirror_file_name: str,
    starter_pack_breakdown_mirror_file_name: str,
    load_json: Callable[[Path], dict[str, Any]],
) -> Path:
    output_root = output_dir.resolve()
    comparison_json_path = resolve_existing_benchmark_comparison_json_path(output_root)
    if comparison_json_path is None:
        comparison_json_path = output_root / PRIMARY_BENCHMARK_COMPARISON_JSON_FILE_NAME
    starter_pack_dir = output_root / starter_pack_dir_name
    starter_readme_path = starter_pack_dir / starter_pack_readme_file_name
    starter_manifest_path = starter_pack_dir / starter_pack_manifest_file_name
    starter_comparison_path = starter_pack_dir / starter_pack_comparison_mirror_file_name
    starter_breakdown_path = starter_pack_dir / starter_pack_breakdown_mirror_file_name
    single_book_summary_path = output_root / "single_book_summary.md"

    sections: list[str] = [
        "# Benchmark Need-To-Know Package (Flattened)",
        "",
        f"- Generated at: `{timestamp_now()}`",
        f"- Session root: `{output_root}`",
        "",
    ]

    if single_book_summary_path.is_file():
        sections.append("## single_book_summary.md")
        sections.append(single_book_summary_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    _append_json_section(
        sections,
        title=comparison_json_path.name,
        path=comparison_json_path,
        load_json=load_json,
    )

    if starter_readme_path.is_file():
        sections.append(f"## {starter_pack_dir_name}/{starter_pack_readme_file_name}")
        sections.append(starter_readme_path.read_text(encoding="utf-8").rstrip())
        sections.append("")

    _append_json_section(
        sections,
        title=f"{starter_pack_dir_name}/{starter_pack_manifest_file_name}",
        path=starter_manifest_path,
        load_json=load_json,
    )
    _append_json_section(
        sections,
        title=f"{starter_pack_dir_name}/{starter_pack_comparison_mirror_file_name}",
        path=starter_comparison_path,
        load_json=load_json,
    )
    _append_json_section(
        sections,
        title=f"{starter_pack_dir_name}/{starter_pack_breakdown_mirror_file_name}",
        path=starter_breakdown_path,
        load_json=load_json,
    )

    output_path = output_root / aggregated_root_summary_md
    output_path.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    return output_path
