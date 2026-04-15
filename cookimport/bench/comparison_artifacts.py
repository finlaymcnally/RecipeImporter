from __future__ import annotations

from pathlib import Path

PRIMARY_BENCHMARK_COMPARISON_JSON_FILE_NAME = "benchmark_comparison.json"
LEGACY_BENCHMARK_COMPARISON_JSON_FILE_NAME = "codex_vs_vanilla_comparison.json"
PRIMARY_BENCHMARK_COMPARISON_MD_FILE_NAME = "benchmark_comparison.md"
LEGACY_BENCHMARK_COMPARISON_MD_FILE_NAME = "codex_vs_vanilla_comparison.md"
PRIMARY_BENCHMARK_CHANGED_LINES_FILE_NAME = "changed_lines.benchmark_comparison.jsonl"
LEGACY_BENCHMARK_CHANGED_LINES_FILE_NAME = "changed_lines.codex_vs_vanilla.jsonl"

BENCHMARK_COMPARISON_JSON_FILE_NAMES: tuple[str, ...] = (
    PRIMARY_BENCHMARK_COMPARISON_JSON_FILE_NAME,
    LEGACY_BENCHMARK_COMPARISON_JSON_FILE_NAME,
)
BENCHMARK_COMPARISON_MD_FILE_NAMES: tuple[str, ...] = (
    PRIMARY_BENCHMARK_COMPARISON_MD_FILE_NAME,
    LEGACY_BENCHMARK_COMPARISON_MD_FILE_NAME,
)
BENCHMARK_CHANGED_LINES_FILE_NAMES: tuple[str, ...] = (
    PRIMARY_BENCHMARK_CHANGED_LINES_FILE_NAME,
    LEGACY_BENCHMARK_CHANGED_LINES_FILE_NAME,
)


def resolve_existing_artifact_path(
    root: Path,
    candidate_file_names: tuple[str, ...],
) -> Path | None:
    for file_name in candidate_file_names:
        candidate = root / file_name
        if candidate.is_file():
            return candidate
    return None


def resolve_existing_benchmark_comparison_json_path(root: Path) -> Path | None:
    return resolve_existing_artifact_path(root, BENCHMARK_COMPARISON_JSON_FILE_NAMES)


def resolve_existing_benchmark_comparison_markdown_path(root: Path) -> Path | None:
    return resolve_existing_artifact_path(root, BENCHMARK_COMPARISON_MD_FILE_NAMES)


def resolve_existing_benchmark_changed_lines_path(root: Path) -> Path | None:
    return resolve_existing_artifact_path(root, BENCHMARK_CHANGED_LINES_FILE_NAMES)
