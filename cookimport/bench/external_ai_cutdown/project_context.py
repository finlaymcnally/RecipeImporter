from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_PROJECT_CONTEXT_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_PROJECT_CONTEXT_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_PROJECT_CONTEXT_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def _extract_project_context_front_matter(text: str) -> dict[str, str]:
    match = _PROJECT_CONTEXT_FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    payload: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key_text = key.strip()
        value_text = value.strip().strip("'\"")
        if key_text and value_text:
            payload[key_text] = value_text
    return payload


def _extract_project_context_title(text: str, context_path: Path) -> str:
    heading_match = _PROJECT_CONTEXT_HEADING_RE.search(text)
    if heading_match:
        heading = heading_match.group(1).strip()
        heading = re.sub(r"`[^`]+`", "", heading)
        heading = re.sub(r"\s*\(code-verified on [^)]+\)\s*$", "", heading, flags=re.IGNORECASE)
        if ":" in heading:
            heading = heading.split(":", 1)[0].strip()
        heading = " ".join(heading.split())
        if heading:
            return heading

    front_matter = _extract_project_context_front_matter(text)
    summary = front_matter.get("summary")
    if summary:
        return summary
    return context_path.stem


def _extract_project_context_version_or_date(text: str, context_path: Path) -> str:
    heading_match = _PROJECT_CONTEXT_HEADING_RE.search(text)
    if heading_match:
        heading = heading_match.group(1)
        date_match = _PROJECT_CONTEXT_DATE_RE.search(heading)
        if date_match:
            return date_match.group(1)

    front_matter = _extract_project_context_front_matter(text)
    for key in ("version", "date", "updated", "last_updated"):
        value = front_matter.get(key)
        if value:
            date_match = _PROJECT_CONTEXT_DATE_RE.search(value)
            if date_match:
                return date_match.group(1)
            return value

    timestamp = datetime.fromtimestamp(context_path.stat().st_mtime, tz=timezone.utc)
    return timestamp.strftime("%Y-%m-%d")


def _project_context_metadata(
    *,
    repo_root: Path,
    project_context_rel_path: Path,
) -> dict[str, Any]:
    context_path = repo_root / project_context_rel_path
    metadata = {
        "project_context_path": str(project_context_rel_path).replace("\\", "/"),
        "project_context_title": "missing",
        "project_context_version_or_date": "missing",
        "project_context_hash": "missing",
    }
    if not context_path.is_file():
        return metadata

    raw_bytes = context_path.read_bytes()
    text = raw_bytes.decode("utf-8", errors="replace")
    metadata["project_context_title"] = _extract_project_context_title(text, context_path)
    metadata["project_context_version_or_date"] = _extract_project_context_version_or_date(
        text,
        context_path,
    )
    metadata["project_context_hash"] = hashlib.sha256(raw_bytes).hexdigest()
    return metadata


def _build_project_context_digest(
    *,
    records: list[Any],
    comparison_summary: dict[str, Any],
    project_context_metadata: dict[str, Any],
    prompt_pairs_per_category: int,
    alignment_healthy_coverage_min: float,
    alignment_healthy_match_ratio_min: float,
    coerce_int: Callable[[Any], int | None],
    normalized_setting_value: Callable[[Any], str],
    record_setting_values: Callable[[list[Any], str], set[str]],
    format_setting_values: Callable[[set[str]], str],
) -> list[str]:
    codex_runs = [record for record in records if bool(getattr(record, "codex_enabled", False))]
    baseline_runs = [record for record in records if not bool(getattr(record, "codex_enabled", False))]
    pairs_raw = comparison_summary.get("pairs")
    pair_count = len(pairs_raw) if isinstance(pairs_raw, list) else 0
    changed_lines_total = coerce_int(comparison_summary.get("changed_lines_total")) or 0

    llm_pipelines = {
        normalized_setting_value(getattr(record, "llm_recipe_pipeline", None)) for record in records
    }
    line_role_values = {
        normalized_setting_value(getattr(record, "line_role_pipeline", None)) for record in records
    }
    atomic_splitter_values = {
        normalized_setting_value(getattr(record, "atomic_block_splitter", None))
        for record in records
    }
    section_backends = record_setting_values(records, "section_detector_backend")
    ingredient_parsers = record_setting_values(records, "ingredient_parser_backend")
    ingredient_fix_backends = record_setting_values(records, "ingredient_text_fix_backend")
    epub_preprocess_modes = record_setting_values(records, "epub_unstructured_preprocess_mode")

    prompt_sampling_caveat = (
        "convenience prompt log keeps all calls when `--prompt-pairs-per-category 0`; "
        "`full_prompt_log.jsonl` remains the source of truth."
        if prompt_pairs_per_category <= 0
        else (
            "convenience prompt log samples at most "
            f"{prompt_pairs_per_category} calls per stage; `full_prompt_log.jsonl` remains complete."
        )
    )

    return [
        (
            "- context_pointer: "
            f"`{project_context_metadata['project_context_path']}` | "
            f"title=`{project_context_metadata['project_context_title']}` | "
            f"version_or_date=`{project_context_metadata['project_context_version_or_date']}` | "
            f"sha256=`{project_context_metadata['project_context_hash']}`"
        ),
        (
            "- system_summary: "
            f"runs={len(records)} (codex={len(codex_runs)}, baseline={len(baseline_runs)}), "
            f"paired_comparisons={pair_count}, changed_lines={changed_lines_total}."
        ),
        (
            "- benchmark_contract: source-rows scoring compares predicted labels against "
            "row-gold labels (including structural labels such as "
            "`INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`)."
        ),
        (
            "- label_ontology_cheat_sheet: common row-gold labels in this benchmark include "
            "`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, "
            "`RECIPE_NOTES`, and `OTHER`."
        ),
        (
            "- projection_bridge: build-intermediate prompt spans (`start_block_index`/`end_block_index`) "
            "are projected into row-level diagnostics so changed-line rows can be split into "
            "`inside_active_recipe_span` vs `outside_active_recipe_span`."
        ),
        (
            "- active_pipeline_map: llm_recipe_pipeline="
            f"{format_setting_values(llm_pipelines)}, "
            f"line_role_pipeline={format_setting_values(line_role_values)}, "
            f"atomic_block_splitter={format_setting_values(atomic_splitter_values)}; "
            "codex-vs-baseline pairing is by source_key with nearest timestamp baseline "
            "(baseline values: `off`/`none`/empty)."
        ),
        (
            "- backend_caveat: section_detector_backend="
            f"{format_setting_values(section_backends)}, "
            f"ingredient_parser_backend={format_setting_values(ingredient_parsers)}, "
            f"ingredient_text_fix_backend={format_setting_values(ingredient_fix_backends)}, "
            f"epub_unstructured_preprocess_mode={format_setting_values(epub_preprocess_modes)}."
        ),
        (
            "- artifact_legend: root diagnosis artifacts are `changed_lines.codex_vs_vanilla.jsonl`, "
            "`per_recipe_or_per_span_breakdown.json`, `targeted_prompt_cases.md`, and "
            "`label_policy_adjudication_notes.md`; blended starter-pack artifacts live under "
            "`starter_pack_v1/`; run folders retain `need_to_know_summary.json` plus codex trace "
            "artifacts when available."
        ),
        (
            "- sampling_caveat: sampled line-level JSONL artifacts are bounded by `--sample-limit`; "
            "`unmatched_pred_blocks.jsonl` is counts-only unless alignment quality is weak "
            f"(coverage<{alignment_healthy_coverage_min} or "
            f"match_ratio<{alignment_healthy_match_ratio_min}); {prompt_sampling_caveat}"
        ),
    ]
