from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from cookimport import __version__
from cookimport.core.models import (
    ChunkHighlight,
    ChunkLane,
    ConversionReport,
    ConversionResult,
    KnowledgeChunk,
    RawArtifact,
    RecipeCandidate,
    TipCandidate,
    TipTags,
    TopicCandidate,
)
from cookimport.parsing.label_source_of_truth import (
    LabelFirstCompatibilityResult,
    build_authoritative_stage_block_predictions,
)
from cookimport.parsing.tables import ExtractedTable
from cookimport.parsing.sections import extract_ingredient_sections, extract_instruction_sections
from cookimport.parsing.step_segmentation import (
    DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY,
    DEFAULT_INSTRUCTION_STEP_SEGMENTER,
    segment_instruction_steps,
)
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1
from cookimport.staging.jsonld import recipe_candidate_to_jsonld
from cookimport.staging.stage_block_predictions import build_stage_block_predictions

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_OUTPUT_CATEGORY_INTERMEDIATE = "intermediateDrafts"
_OUTPUT_CATEGORY_FINAL = "finalDrafts"
_OUTPUT_CATEGORY_TIPS = "tips"
_OUTPUT_CATEGORY_TOPIC_CANDIDATES = "topicCandidates"
_OUTPUT_CATEGORY_CHUNKS = "chunks"
_OUTPUT_CATEGORY_TABLES = "tables"
_OUTPUT_CATEGORY_RAW = "rawArtifacts"
_OUTPUT_CATEGORY_SECTIONS = "sections"
_OUTPUT_CATEGORY_BENCH = "benchArtifacts"

_IO_PACE_EVERY_WRITES_ENV = "COOKIMPORT_IO_PACE_EVERY_WRITES"
_IO_PACE_SLEEP_MS_ENV = "COOKIMPORT_IO_PACE_SLEEP_MS"

_io_pace_lock = threading.Lock()
_io_pace_counter = 0
_io_pace_every_writes = 0
_io_pace_sleep_seconds = 0.0
_io_pace_last_env: tuple[str | None, str | None] = (None, None)


def _refresh_io_pace_from_env() -> None:
    global _io_pace_every_writes
    global _io_pace_sleep_seconds
    global _io_pace_last_env

    every_raw = os.getenv(_IO_PACE_EVERY_WRITES_ENV)
    sleep_raw = os.getenv(_IO_PACE_SLEEP_MS_ENV)
    if (every_raw, sleep_raw) == _io_pace_last_env:
        return
    _io_pace_last_env = (every_raw, sleep_raw)

    try:
        parsed_every = int(str(every_raw or "0").strip() or "0")
    except (TypeError, ValueError):
        parsed_every = 0

    try:
        parsed_sleep_ms = float(str(sleep_raw or "0").strip() or "0")
    except (TypeError, ValueError):
        parsed_sleep_ms = 0.0

    _io_pace_every_writes = max(0, parsed_every)
    _io_pace_sleep_seconds = max(0.0, parsed_sleep_ms / 1000.0)


def _io_pace_tick() -> None:
    """Optional I/O pacing to reduce disk-thrash on write-heavy runs (WSL/QualitySuite).

    Defaults to disabled and only activates when both env vars are set:
    - COOKIMPORT_IO_PACE_EVERY_WRITES (int)
    - COOKIMPORT_IO_PACE_SLEEP_MS (float)
    """

    _refresh_io_pace_from_env()
    if _io_pace_every_writes <= 0 or _io_pace_sleep_seconds <= 0:
        return

    should_sleep = False
    with _io_pace_lock:
        global _io_pace_counter
        _io_pace_counter += 1
        should_sleep = (_io_pace_counter % _io_pace_every_writes) == 0

    if should_sleep:
        time.sleep(_io_pace_sleep_seconds)


@dataclass
class OutputStats:
    base_dir: Path
    max_largest_files: int = 5
    file_counts: dict[str, int] = field(default_factory=dict)
    byte_counts: dict[str, int] = field(default_factory=dict)
    largest_files: list[dict[str, Any]] = field(default_factory=list)

    def record_path(self, category: str, path: Path) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        self._record(category, path, size)

    def _record(self, category: str, path: Path, size: int) -> None:
        self.file_counts[category] = self.file_counts.get(category, 0) + 1
        self.byte_counts[category] = self.byte_counts.get(category, 0) + size
        rel_path = self._rel_path(path)
        self._track_largest(rel_path, size, category)

    def _rel_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.base_dir))
        except ValueError:
            return str(path)

    def _track_largest(self, rel_path: str, size: int, category: str) -> None:
        entry = {"path": rel_path, "bytes": size, "category": category}
        if len(self.largest_files) < self.max_largest_files:
            self.largest_files.append(entry)
            self.largest_files.sort(key=lambda item: item["bytes"], reverse=True)
            return
        if size <= self.largest_files[-1]["bytes"]:
            return
        self.largest_files.append(entry)
        self.largest_files.sort(key=lambda item: item["bytes"], reverse=True)
        if len(self.largest_files) > self.max_largest_files:
            self.largest_files.pop()

    def to_report(self) -> dict[str, Any]:
        files: dict[str, dict[str, int]] = {}
        total_count = 0
        total_bytes = 0
        for category in sorted(self.file_counts):
            count = self.file_counts[category]
            bytes_written = self.byte_counts.get(category, 0)
            files[category] = {"count": count, "bytes": bytes_written}
            total_count += count
            total_bytes += bytes_written
        files["total"] = {"count": total_count, "bytes": total_bytes}
        report: dict[str, Any] = {"files": files}
        if self.largest_files:
            report["largestFiles"] = self.largest_files
        return report


def _write_json_payload(
    payload: Any,
    out_path: Path,
    *,
    output_stats: OutputStats | None,
    category: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _io_pace_tick()
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if output_stats:
        output_stats.record_path(category, out_path)


def _write_text_payload(
    text: str,
    out_path: Path,
    *,
    output_stats: OutputStats | None,
    category: str,
    encoding: str = "utf-8",
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _io_pace_tick()
    out_path.write_text(text, encoding=encoding)
    if output_stats:
        output_stats.record_path(category, out_path)


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = _SLUG_RE.sub("_", lowered).strip("_")
    return slug or "unknown"


def _slugify_location(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "location"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", cleaned).strip("_")
    return slug or "location"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


@lru_cache(maxsize=256)
def _hash_file_cached(path_str: str, mtime_ns: int, size_bytes: int) -> str:
    # Keep metadata in cache keys so edits invalidate cached hashes.
    _ = (mtime_ns, size_bytes)
    return _hash_file(Path(path_str))


def _hash_path_with_cache(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return _hash_file(path)
    try:
        canonical_path = str(path.resolve())
    except OSError:
        canonical_path = str(path)
    return _hash_file_cached(canonical_path, int(stat.st_mtime_ns), int(stat.st_size))


def _resolve_file_hash(results: ConversionResult, provenance: dict[str, Any]) -> str:
    file_hash = provenance.get("file_hash") or provenance.get("fileHash")
    if file_hash:
        return str(file_hash)
    workbook_path = provenance.get("file_path") or provenance.get("filePath")
    if workbook_path:
        path = Path(str(workbook_path))
        if path.exists():
            return _hash_path_with_cache(path)
    if results.workbook_path:
        path = Path(results.workbook_path)
        if path.exists():
            return _hash_path_with_cache(path)
    return "unknown"


def _resolve_workbook_name(results: ConversionResult, provenance: dict[str, Any]) -> str:
    if results.workbook:
        return results.workbook
    if provenance.get("workbook"):
        return str(provenance["workbook"])
    workbook_path = provenance.get("file_path") or provenance.get("filePath")
    if workbook_path:
        return Path(str(workbook_path)).name
    return "workbook"


def _resolve_sheet_name(provenance: dict[str, Any]) -> str:
    return str(provenance.get("sheet") or "sheet")


def _resolve_row_index(provenance: dict[str, Any]) -> int:
    for key in ("row_index", "rowIndex", "row"):
        if key in provenance:
            try:
                return int(provenance[key])
            except (TypeError, ValueError):
                return 0
    location = provenance.get("location")
    if isinstance(location, dict):
        for key in ("row_index", "rowIndex", "row", "chunk_index", "chunkIndex", "chunk"):
            if key in location:
                try:
                    return int(location[key])
                except (TypeError, ValueError):
                    return 0
    return 0


def _ensure_provenance(candidate: RecipeCandidate) -> dict[str, Any]:
    if candidate.provenance is None:
        candidate.provenance = {}
    return candidate.provenance


def _ensure_candidate_id(
    candidate: RecipeCandidate,
    file_hash: str,
    sheet_slug: str,
    row_index: int,
) -> str:
    provenance = _ensure_provenance(candidate)
    existing = provenance.get("@id") or provenance.get("id")
    if existing:
        return str(existing)
    if candidate.identifier:
        provenance["@id"] = candidate.identifier
        provenance.setdefault("converter_version", __version__)
        return candidate.identifier
    stable_id = f"urn:recipeimport:excel:{file_hash}:{sheet_slug}:r{row_index}"
    provenance["@id"] = stable_id
    provenance.setdefault("converter_version", __version__)
    return stable_id


def _resolve_tip_index(provenance: dict[str, Any]) -> int | None:
    for key in ("tip_index", "tipIndex", "tip"):
        if key in provenance:
            try:
                return int(provenance[key])
            except (TypeError, ValueError):
                return None
    return None


def _ensure_tip_id(
    tip: TipCandidate,
    file_hash: str,
    sheet_slug: str,
    row_index: int,
    tip_index: int,
) -> str:
    provenance = tip.provenance or {}
    existing = provenance.get("@id") or provenance.get("id") or tip.identifier
    if existing:
        tip.identifier = str(existing)
        return tip.identifier
    stable_id = f"urn:recipeimport:tip:{file_hash}:{sheet_slug}:t{row_index}:{tip_index}"
    tip.identifier = stable_id
    provenance["@id"] = stable_id
    provenance.setdefault("converter_version", __version__)
    tip.provenance = provenance
    return stable_id


def _ensure_topic_id(
    topic: TopicCandidate,
    file_hash: str,
    sheet_slug: str,
    row_index: int,
    topic_index: int,
) -> str:
    provenance = topic.provenance or {}
    existing = provenance.get("@id") or provenance.get("id") or topic.identifier
    if existing:
        topic.identifier = str(existing)
        return topic.identifier
    stable_id = f"urn:recipeimport:topic:{file_hash}:{sheet_slug}:tc{row_index}:{topic_index}"
    topic.identifier = stable_id
    provenance["@id"] = stable_id
    provenance.setdefault("converter_version", __version__)
    topic.provenance = provenance
    return stable_id


def _ensure_source(results: ConversionResult, candidate: RecipeCandidate) -> None:
    if not candidate.source:
        if results.workbook_path:
            candidate.source = Path(results.workbook_path).name
        elif results.workbook:
            candidate.source = results.workbook


def write_intermediate_outputs(
    results: ConversionResult,
    out_dir: Path,
    *,
    output_stats: OutputStats | None = None,
    schemaorg_overrides_by_recipe_id: dict[str, dict[str, Any]] | None = None,
    instruction_step_options: Mapping[str, Any] | None = None,
) -> None:
    """Write intermediate schema.org Recipe JSON outputs.

    These are the raw extracted recipes before transformation to final format.
    Output path: {out_dir}/r{index}.jsonld
    """
    for index, candidate in enumerate(results.recipes):
        _ensure_source(results, candidate)
        provenance = _ensure_provenance(candidate)
        sheet_name = _resolve_sheet_name(provenance)
        row_index = _resolve_row_index(provenance)
        sheet_slug = _slugify(sheet_name)
        file_hash = _resolve_file_hash(results, provenance)

        # Ensure stable ID for the candidate
        _ensure_candidate_id(candidate, file_hash, sheet_slug, row_index)

        override_payload = None
        if schemaorg_overrides_by_recipe_id is not None:
            override_payload = schemaorg_overrides_by_recipe_id.get(candidate.identifier)
        if isinstance(override_payload, dict):
            jsonld = dict(override_payload)
        elif hasattr(override_payload, "model_dump"):
            jsonld = override_payload.model_dump(mode="json", by_alias=True, exclude_none=True)
        else:
            jsonld = recipe_candidate_to_jsonld(
                candidate,
                instruction_step_options=instruction_step_options,
            )

        out_path = out_dir / f"r{index}.jsonld"
        _write_json_payload(
            jsonld,
            out_path,
            output_stats=output_stats,
            category=_OUTPUT_CATEGORY_INTERMEDIATE,
        )


def write_draft_outputs(
    results: ConversionResult,
    out_dir: Path,
    *,
    output_stats: OutputStats | None = None,
    draft_overrides_by_recipe_id: dict[str, dict[str, Any]] | None = None,
    ingredient_parser_options: Mapping[str, Any] | None = None,
    instruction_step_options: Mapping[str, Any] | None = None,
) -> None:
    """Write cookbook3 outputs (internal model name: RecipeDraftV1).

    Output path: {out_dir}/r{index}.json
    """
    emit_p6_metadata_debug = False
    if isinstance(instruction_step_options, Mapping):
        value = instruction_step_options.get("p6_emit_metadata_debug", False)
        if isinstance(value, bool):
            emit_p6_metadata_debug = value
        else:
            emit_p6_metadata_debug = str(value).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }

    p6_debug_rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(results.recipes):
        _ensure_source(results, candidate)
        provenance = _ensure_provenance(candidate)
        sheet_name = _resolve_sheet_name(provenance)
        row_index = _resolve_row_index(provenance)
        sheet_slug = _slugify(sheet_name)
        file_hash = _resolve_file_hash(results, provenance)
        recipe_id = _ensure_candidate_id(candidate, file_hash, sheet_slug, row_index)

        override_payload = None
        if draft_overrides_by_recipe_id is not None:
            override_payload = draft_overrides_by_recipe_id.get(recipe_id)
        if isinstance(override_payload, dict):
            draft = dict(override_payload)
        elif hasattr(override_payload, "model_dump"):
            draft = override_payload.model_dump(mode="json", by_alias=True, exclude_none=True)
        else:
            draft = recipe_candidate_to_draft_v1(
                candidate,
                ingredient_parser_options=ingredient_parser_options,
                instruction_step_options=instruction_step_options,
            )

        _normalize_draft_compatibility_aliases(draft)

        p6_debug_payload = None
        if isinstance(draft, dict):
            p6_debug_payload = draft.pop("_p6_debug", None)
        if emit_p6_metadata_debug and isinstance(p6_debug_payload, dict):
            p6_debug_rows.append(
                {
                    "recipe_id": recipe_id,
                    "file_index": index,
                    "p6": p6_debug_payload,
                }
            )

        out_path = out_dir / f"r{index}.json"
        _write_json_payload(
            draft,
            out_path,
            output_stats=output_stats,
            category=_OUTPUT_CATEGORY_FINAL,
        )

    if emit_p6_metadata_debug and p6_debug_rows:
        run_root = out_dir.parent.parent
        workbook_slug = out_dir.name
        debug_path = run_root / ".bench" / workbook_slug / "p6_metadata_debug.jsonl"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(
            "\n".join(
                json.dumps(row, sort_keys=True, ensure_ascii=True)
                for row in p6_debug_rows
            )
            + "\n",
            encoding="utf-8",
        )
        if output_stats:
            output_stats.record_path(_OUTPUT_CATEGORY_BENCH, debug_path)


def _normalize_draft_compatibility_aliases(payload: Any) -> None:
    if not isinstance(payload, dict):
        return

    recipe_payload = payload.get("recipe")
    if not isinstance(recipe_payload, dict):
        recipe_payload = {}

    steps_payload = payload.get("steps")
    if not isinstance(steps_payload, list):
        steps_payload = []

    title = str(recipe_payload.get("title") or "").strip()
    if not title:
        title = "Untitled Recipe"

    derived_ingredients: list[str] = []
    seen_ingredients: set[str] = set()
    derived_instructions: list[str] = []
    for step in steps_payload:
        if not isinstance(step, dict):
            continue
        instruction_text = str(step.get("instruction") or "").strip()
        if instruction_text:
            derived_instructions.append(instruction_text)
        ingredient_lines = step.get("ingredient_lines")
        if not isinstance(ingredient_lines, list):
            continue
        for line in ingredient_lines:
            if not isinstance(line, dict):
                continue
            ingredient_text = str(
                line.get("raw_text")
                or line.get("raw_ingredient_text")
                or ""
            ).strip()
            if not ingredient_text or ingredient_text in seen_ingredients:
                continue
            seen_ingredients.add(ingredient_text)
            derived_ingredients.append(ingredient_text)

    existing_name = payload.get("name")
    if not str(existing_name or "").strip():
        payload["name"] = title

    if "ingredients" not in payload or payload.get("ingredients") is None:
        payload["ingredients"] = derived_ingredients

    if "instructions" not in payload or payload.get("instructions") is None:
        payload["instructions"] = derived_instructions


def _coerce_instruction_text(value: Any) -> str:
    text = getattr(value, "text", value)
    return str(text).strip()


def _resolve_instruction_step_segmentation_options(
    options: Mapping[str, Any] | None,
) -> tuple[str, str]:
    from cookimport.config.codex_decision import bucket1_fixed_behavior

    fixed_behavior = bucket1_fixed_behavior()
    if not isinstance(options, Mapping):
        return (
            fixed_behavior.instruction_step_segmentation_policy,
            fixed_behavior.instruction_step_segmenter,
        )
    policy = str(
        options.get(
            "instruction_step_segmentation_policy",
            fixed_behavior.instruction_step_segmentation_policy,
        )
    ).strip().lower().replace("-", "_")
    segmenter = str(
        options.get(
            "instruction_step_segmenter",
            fixed_behavior.instruction_step_segmenter,
        )
    ).strip().lower().replace("-", "_")
    return (policy, segmenter)


def _effective_instruction_texts(
    candidate: RecipeCandidate,
    *,
    instruction_step_options: Mapping[str, Any] | None,
) -> list[str]:
    instruction_texts = [_coerce_instruction_text(item) for item in candidate.instructions]
    policy, segmenter = _resolve_instruction_step_segmentation_options(
        instruction_step_options
    )
    return segment_instruction_steps(
        instruction_texts,
        policy=policy,
        backend=segmenter,
    )


def _section_display_name(key: str, *display_maps: dict[str, str]) -> str:
    for mapping in display_maps:
        display_name = mapping.get(key)
        if display_name:
            return display_name
    return key.replace("_", " ").strip().title() or "Main"


def write_section_outputs(
    out_dir: Path,
    workbook_slug: str,
    candidates: list[RecipeCandidate],
    *,
    output_stats: OutputStats | None = None,
    write_markdown: bool = True,
    instruction_step_options: Mapping[str, Any] | None = None,
) -> None:
    """Write grouped ingredient/step section artifacts per recipe."""
    sections_dir = out_dir / "sections" / workbook_slug
    sections_dir.mkdir(parents=True, exist_ok=True)

    markdown_lines: list[str] | None = None
    if write_markdown:
        markdown_lines = [
            "# Recipe Sections",
            "",
        ]

    for index, candidate in enumerate(candidates):
        ingredient_sections = extract_ingredient_sections(candidate.ingredients)
        instruction_texts = _effective_instruction_texts(
            candidate,
            instruction_step_options=instruction_step_options,
        )
        instruction_sections = extract_instruction_sections(instruction_texts)

        ingredient_by_key: dict[str, list[str]] = {}
        for line, key in zip(
            ingredient_sections.lines_no_headers,
            ingredient_sections.section_key_by_line,
        ):
            ingredient_by_key.setdefault(key, []).append(line)

        steps_by_key: dict[str, list[str]] = {}
        for line, key in zip(
            instruction_sections.lines_no_headers,
            instruction_sections.section_key_by_line,
        ):
            steps_by_key.setdefault(key, []).append(line)

        ordered_keys: list[str] = []
        for key in ingredient_sections.section_key_by_line + instruction_sections.section_key_by_line:
            if key not in ordered_keys:
                ordered_keys.append(key)

        section_entries: list[dict[str, Any]] = []
        for key in ordered_keys:
            ingredients = ingredient_by_key.get(key, [])
            steps = steps_by_key.get(key, [])
            if not ingredients and not steps:
                continue
            section_entries.append(
                {
                    "name": _section_display_name(
                        key,
                        instruction_sections.section_display_by_key,
                        ingredient_sections.section_display_by_key,
                    ),
                    "key": key,
                    "ingredients": ingredients,
                    "steps": steps,
                }
            )

        recipe_id = (
            candidate.provenance.get("@id")
            or candidate.provenance.get("id")
            or candidate.identifier
            or f"r{index}"
        )
        payload = {
            "recipe_id": recipe_id,
            "title": candidate.name,
            "sections": section_entries,
        }
        section_json_path = sections_dir / f"r{index}.sections.json"
        _write_json_payload(
            payload,
            section_json_path,
            output_stats=output_stats,
            category=_OUTPUT_CATEGORY_SECTIONS,
        )

        if markdown_lines is not None:
            markdown_lines.append(f"## r{index}: {candidate.name}")
            if not section_entries:
                markdown_lines.append("")
                markdown_lines.append("(No section groups detected.)")
                markdown_lines.append("")
                continue
            markdown_lines.append("")
            for section in section_entries:
                markdown_lines.append(f"### {section['name']} ({section['key']})")
                ingredients = section.get("ingredients", [])
                steps = section.get("steps", [])
                if ingredients:
                    markdown_lines.append("Ingredients:")
                    for ingredient in ingredients:
                        markdown_lines.append(f"- {ingredient}")
                else:
                    markdown_lines.append("Ingredients: (none)")
                if steps:
                    markdown_lines.append("Steps:")
                    for step in steps:
                        markdown_lines.append(f"- {step}")
                else:
                    markdown_lines.append("Steps: (none)")
                markdown_lines.append("")

    if markdown_lines is not None:
        _write_text_payload(
            "\n".join(markdown_lines).rstrip() + "\n",
            sections_dir / "sections.md",
            output_stats=output_stats,
            category=_OUTPUT_CATEGORY_SECTIONS,
        )


def write_tip_outputs(
    results: ConversionResult,
    out_dir: Path,
    *,
    output_stats: OutputStats | None = None,
    write_markdown: bool = True,
) -> None:
    """Write tip/knowledge outputs.

    Output path: {out_dir}/t{index}.json
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    general_tips = [
        tip for tip in results.tips if tip.scope == "general" and tip.standalone
    ]
    for index, tip in enumerate(general_tips):
        provenance = tip.provenance or {}
        sheet_name = _resolve_sheet_name(provenance)
        row_index = _resolve_row_index(provenance)
        tip_index = _resolve_tip_index(provenance)
        if tip_index is None:
            tip_index = index
        sheet_slug = _slugify(sheet_name)
        file_hash = _resolve_file_hash(results, provenance)

        _ensure_tip_id(tip, file_hash, sheet_slug, row_index, tip_index)

        payload = tip.model_dump(by_alias=True, exclude_none=True)
        out_path = out_dir / f"t{index}.json"
        _write_json_payload(
            payload,
            out_path,
            output_stats=output_stats,
            category=_OUTPUT_CATEGORY_TIPS,
        )

    if not write_markdown:
        return

    summary_path = out_dir / "tips.md"
    if general_tips:
        lines = ["# Tip Summary", ""]
        for group in _group_tip_summaries(general_tips):
            indices = ", ".join(group["indices"])
            anchor_text = _format_tip_anchors(
                _collect_tip_anchors(group["tips"])  # type: ignore[arg-type]
            )
            header = f"- {indices}{anchor_text}"
            lines.append(header)
            group_header = group.get("header")
            if group_header:
                lines.append(f"  {group_header}")
            for tip_text in group["texts"]:
                lines.append(f"  {tip_text}")
        _write_text_payload(
            "\n".join(lines).strip() + "\n",
            summary_path,
            output_stats=output_stats,
            category=_OUTPUT_CATEGORY_TIPS,
        )
    else:
        _write_text_payload(
            "# Tip Summary\n\n(No tips generated.)\n",
            summary_path,
            output_stats=output_stats,
            category=_OUTPUT_CATEGORY_TIPS,
        )


def write_topic_candidate_outputs(
    results: ConversionResult,
    out_dir: Path,
    *,
    output_stats: OutputStats | None = None,
    write_markdown: bool = True,
) -> None:
    """Write topic-candidate outputs for evaluation and LLM prefiltering.

    Output path: {out_dir}/topic_candidates.json, {out_dir}/topic_candidates.md
    """
    if not results.topic_candidates:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads: list[dict[str, Any]] = []
    for index, topic in enumerate(results.topic_candidates):
        provenance = topic.provenance or {}
        sheet_name = _resolve_sheet_name(provenance)
        row_index = _resolve_row_index(provenance)
        topic_index = _resolve_tip_index(provenance)
        if topic_index is None:
            topic_index = index
        sheet_slug = _slugify(sheet_name)
        file_hash = _resolve_file_hash(results, provenance)
        _ensure_topic_id(topic, file_hash, sheet_slug, row_index, topic_index)
        payloads.append(topic.model_dump(by_alias=True, exclude_none=True))

    json_path = out_dir / "topic_candidates.json"
    _write_json_payload(
        payloads,
        json_path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_TOPIC_CANDIDATES,
    )

    if not write_markdown:
        return

    lines = [
        "# Topic Candidates",
        "",
        "_These are standalone atom-level snippets captured before tip classification. Use for evaluation/LLM prefiltering._",
        "",
    ]
    for index, topic in enumerate(results.topic_candidates):
        anchors = _format_tip_anchors(_collect_tip_anchors([topic]))
        provenance = topic.provenance or {}
        atom_meta = provenance.get("atom") if isinstance(provenance, dict) else None
        atom_kind = None
        if isinstance(atom_meta, dict):
            atom_kind = atom_meta.get("kind")
        kind_suffix = f" ({atom_kind})" if atom_kind else ""
        lines.append(f"- tc{index}{anchors}{kind_suffix}")
        header = _normalize_topic_header(topic.header or provenance.get("topic_header"))
        if header and header != topic.text:
            lines.append(f"  {header}")
        lines.append(f"  {topic.text}")
        if isinstance(atom_meta, dict):
            context_prev = _truncate_context(atom_meta.get("context_prev"))
            context_next = _truncate_context(atom_meta.get("context_next"))
            if context_prev:
                lines.append(f"  prev: {context_prev}")
            if context_next:
                lines.append(f"  next: {context_next}")
    md_path = out_dir / "topic_candidates.md"
    _write_text_payload(
        "\n".join(lines).strip() + "\n",
        md_path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_TOPIC_CANDIDATES,
    )


_GENERIC_TIP_HEADERS = {
    "tip",
    "tips",
    "note",
    "notes",
    "hint",
    "hints",
    "pro tip",
    "pro tips",
}


def _normalize_topic_header(header: Any) -> str | None:
    if not header:
        return None
    cleaned = str(header).strip()
    if not cleaned:
        return None
    if cleaned.lower() in _GENERIC_TIP_HEADERS:
        return None
    return cleaned


def _truncate_context(value: Any, limit: int = 140) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 3, 0)] + "..."


def _group_tip_summaries(tips: list[TipCandidate]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for index, tip in enumerate(tips):
        key = _tip_summary_key(tip)
        if current is None or current["key"] != key:
            header = _tip_summary_header(tip)
            current = {
                "key": key,
                "indices": [f"t{index}"],
                "texts": [tip.text],
                "tips": [tip],
                "header": header,
            }
            groups.append(current)
        else:
            current["indices"].append(f"t{index}")
            current["texts"].append(tip.text)
            current["tips"].append(tip)
    return groups


def _tip_summary_key(tip: TipCandidate) -> tuple:
    provenance = tip.provenance or {}
    location = provenance.get("location", {}) if isinstance(provenance, dict) else {}
    header = _tip_summary_header(tip)
    block_index = location.get("block_index")
    start_block = location.get("start_block")
    end_block = location.get("end_block")
    chunk_index = location.get("chunk_index")
    return (
        tip.source_recipe_id,
        block_index,
        start_block,
        end_block,
        chunk_index,
        header,
    )


def _tip_summary_header(tip: TipCandidate) -> str | None:
    provenance = tip.provenance or {}
    header = (
        provenance.get("topic_header")
        or provenance.get("topicHeader")
        or provenance.get("tip_header")
        or provenance.get("tipHeader")
    )
    if not header:
        return None
    cleaned = str(header).strip()
    if not cleaned:
        return None
    if cleaned.lower() in _GENERIC_TIP_HEADERS:
        return None
    return cleaned


def _collect_tip_anchors(tips: list[TipCandidate | TopicCandidate]) -> dict[str, list[str]]:
    anchors = {
        "dishes": [],
        "ingredients": [],
        "techniques": [],
        "cooking_methods": [],
        "tools": [],
    }

    def add_unique(target: list[str], values: list[str]) -> None:
        for value in values:
            if value not in target:
                target.append(value)

    for tip in tips:
        tags = tip.tags
        add_unique(anchors["dishes"], list(tags.dishes))
        ingredient_values = (
            list(tags.meats)
            + list(tags.vegetables)
            + list(tags.herbs)
            + list(tags.spices)
            + list(tags.dairy)
            + list(tags.grains)
            + list(tags.legumes)
            + list(tags.fruits)
            + list(tags.sweeteners)
            + list(tags.oils_fats)
        )
        add_unique(anchors["ingredients"], ingredient_values)
        add_unique(anchors["techniques"], list(tags.techniques))
        add_unique(anchors["cooking_methods"], list(tags.cooking_methods))
        add_unique(anchors["tools"], list(tags.tools))

    return anchors


def _format_tip_anchors(anchors: dict[str, list[str]]) -> str:
    parts: list[str] = []
    if anchors.get("dishes"):
        parts.append(f"dish: {', '.join(anchors['dishes'])}")
    if anchors.get("ingredients"):
        parts.append(f"ingredients: {', '.join(anchors['ingredients'])}")
    if anchors.get("techniques"):
        parts.append(f"techniques: {', '.join(anchors['techniques'])}")
    if anchors.get("cooking_methods"):
        parts.append(f"methods: {', '.join(anchors['cooking_methods'])}")
    if anchors.get("tools"):
        parts.append(f"tools: {', '.join(anchors['tools'])}")
    if not parts:
        return ""
    return " [" + "; ".join(parts) + "]"


def write_raw_artifacts(
    results: ConversionResult,
    out_dir: Path,
    *,
    output_stats: OutputStats | None = None,
) -> None:
    """Write raw artifacts captured during conversion.

    Output path: {out_dir}/raw/{importer}/{source_hash}/{location_id}.{ext}
    """
    if not results.raw_artifacts:
        return

    for artifact in results.raw_artifacts:
        _write_raw_artifact(artifact, out_dir, output_stats=output_stats)


def _write_raw_artifact(
    artifact: RawArtifact,
    out_dir: Path,
    *,
    output_stats: OutputStats | None = None,
) -> None:
    importer_slug = _slugify(artifact.importer)
    source_hash = artifact.source_hash or "unknown"
    location = _slugify_location(artifact.location_id)
    ext = (artifact.extension or "txt").lstrip(".")

    target_dir = out_dir / "raw" / importer_slug / source_hash
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{location}.{ext}"

    payload = artifact.content
    if isinstance(payload, (dict, list)):
        _write_text_payload(
            json.dumps(payload, indent=2, sort_keys=True),
            target_path,
            output_stats=output_stats,
            category=_OUTPUT_CATEGORY_RAW,
            encoding=artifact.encoding or "utf-8",
        )
        return
    if isinstance(payload, bytes):
        _io_pace_tick()
        target_path.write_bytes(payload)
        if output_stats:
            output_stats.record_path(_OUTPUT_CATEGORY_RAW, target_path)
        return
    text_payload = "" if payload is None else str(payload)
    _write_text_payload(
        text_payload,
        target_path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_RAW,
        encoding=artifact.encoding or "utf-8",
    )


def write_report(report: ConversionReport, out_dir: Path, workbook_name: str) -> Path:
    """Write a conversion report JSON file for a workbook.

    Output path: {out_dir}/{workbook_slug}.excel_import_report.json
    """
    slug = _slugify(workbook_name)
    out_path = out_dir / f"{slug}.excel_import_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(by_alias=True, exclude_none=True)
    _io_pace_tick()
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------
# Knowledge Chunk Outputs
# --------------------------------------------------------------------------


def write_chunk_outputs(
    chunks: list[KnowledgeChunk],
    out_dir: Path,
    *,
    output_stats: OutputStats | None = None,
    write_markdown: bool = True,
) -> None:
    """Write knowledge chunk outputs.

    Output path: {out_dir}/c{index}.json and {out_dir}/chunks.md
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write individual chunk JSON files
    for index, chunk in enumerate(chunks):
        payload = chunk.model_dump(by_alias=True, exclude_none=True)
        out_path = out_dir / f"c{index}.json"
        _write_json_payload(
            payload,
            out_path,
            output_stats=output_stats,
            category=_OUTPUT_CATEGORY_CHUNKS,
        )

    if not write_markdown:
        return

    # Write chunks.md summary
    summary_path = out_dir / "chunks.md"
    lines = _format_chunks_md(chunks)
    _write_text_payload(
        "\n".join(lines).strip() + "\n",
        summary_path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_CHUNKS,
    )


def write_table_outputs(
    run_out_dir: Path,
    workbook_slug: str,
    tables: list[ExtractedTable],
    *,
    source_file: str | None = None,
    output_stats: OutputStats | None = None,
    write_markdown: bool = True,
) -> None:
    tables_dir = run_out_dir / "tables" / workbook_slug
    tables_dir.mkdir(parents=True, exist_ok=True)

    jsonl_lines = [
        json.dumps(table.model_dump(mode="json", exclude_none=True), sort_keys=True)
        for table in tables
    ]
    jsonl_payload = "\n".join(jsonl_lines)
    if jsonl_payload:
        jsonl_payload += "\n"
    _write_text_payload(
        jsonl_payload,
        tables_dir / "tables.jsonl",
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_TABLES,
    )

    if not write_markdown:
        return

    lines = ["# Extracted Tables", ""]
    if not tables:
        lines.append("(No tables detected.)")
    else:
        for table_index, table in enumerate(tables, start=1):
            title = table.caption or f"Table {table_index}"
            lines.append(f"## {title}")
            lines.append("")
            source_value = source_file or "unknown"
            lines.append(
                "Source: "
                f"{source_value} | Blocks: {table.start_block_index}-{table.end_block_index} "
                f"| Confidence: {table.confidence:.2f}"
            )
            lines.append("")
            if table.markdown:
                lines.append(table.markdown)
            else:
                lines.append("(No renderable rows)")
            lines.append("")
    _write_text_payload(
        "\n".join(lines).rstrip() + "\n",
        tables_dir / "tables.md",
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_TABLES,
    )


def write_stage_block_predictions(
    *,
    results: ConversionResult,
    run_root: Path,
    workbook_slug: str,
    source_file: str | None = None,
    source_hash: str | None = None,
    archive_blocks: list[dict[str, Any]] | None = None,
    knowledge_block_classifications_path: Path | None = None,
    knowledge_snippets_path: Path | None = None,
    output_stats: OutputStats | None = None,
    label_first_result: LabelFirstCompatibilityResult | None = None,
) -> Path:
    """Write deterministic block-level stage predictions for benchmark scoring."""
    if label_first_result is not None:
        payload = build_authoritative_stage_block_predictions(
            block_labels=label_first_result.block_labels,
            archive_blocks=label_first_result.archive_blocks,
            source_file=source_file or "",
            source_hash=source_hash or label_first_result.source_hash or "unknown",
            workbook_slug=workbook_slug,
        )
    else:
        payload = build_stage_block_predictions(
            results,
            workbook_slug,
            source_file=source_file,
            source_hash=source_hash,
            archive_blocks=archive_blocks,
            knowledge_block_classifications_path=knowledge_block_classifications_path,
            knowledge_snippets_path=knowledge_snippets_path,
        )
    out_path = run_root / ".bench" / workbook_slug / "stage_block_predictions.json"
    _write_json_payload(
        payload,
        out_path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_BENCH,
    )
    return out_path


def _format_chunks_md(chunks: list[KnowledgeChunk]) -> list[str]:
    """Format chunks into markdown summary optimized for debugging."""
    lines = [
        "# Knowledge Chunks Summary",
        "",
        "_Structure-first chunking with lane classification and tip highlights._",
        "",
    ]

    # Summary statistics
    knowledge_count = sum(1 for c in chunks if c.lane == ChunkLane.KNOWLEDGE)
    # Treat legacy narrative lane as noise for reporting.
    noise_count = sum(
        1 for c in chunks if c.lane in (ChunkLane.NOISE, ChunkLane.NARRATIVE)
    )
    total_highlights = sum(c.highlight_count for c in chunks)

    lines.append("## Statistics")
    lines.append("")
    lines.append(f"- Total chunks: {len(chunks)}")
    lines.append(f"- Knowledge: {knowledge_count}")
    lines.append(f"- Noise: {noise_count}")
    lines.append(f"- Total highlights: {total_highlights}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Individual chunks
    for chunk in chunks:
        lines.extend(_format_chunk_entry(chunk))
        lines.append("")

    return lines


def _format_chunk_entry(chunk: KnowledgeChunk) -> list[str]:
    """Format a single chunk entry for chunks.md."""
    lines = []

    # Header with ID, lane, and title
    lane_emoji = {
        ChunkLane.KNOWLEDGE: "📚",
        ChunkLane.NARRATIVE: "🔇",
        ChunkLane.NOISE: "🔇",
    }.get(chunk.lane, "❓")

    title_display = chunk.title or "(untitled)"
    if len(title_display) > 60:
        title_display = title_display[:57] + "..."

    lines.append(f"### {chunk.identifier} {lane_emoji} {chunk.lane.value.upper()}")
    lines.append(f"**{title_display}**")
    lines.append("")

    # Section path
    if chunk.section_path:
        path_str = " > ".join(chunk.section_path)
        lines.append(f"Section: {path_str}")
        lines.append("")

    # Boundary reasons
    lines.append(
        f"Boundaries: {chunk.boundary_start_reason.value} → {chunk.boundary_end_reason.value}"
    )

    # Block IDs
    if chunk.block_ids:
        block_range = f"[{min(chunk.block_ids)}..{max(chunk.block_ids)}]"
        lines.append(f"Blocks: {block_range} ({len(chunk.block_ids)} blocks)")

    # Tip density and highlights
    if chunk.lane == ChunkLane.KNOWLEDGE:
        lines.append(f"Tip density: {chunk.tip_density:.2f} | Highlights: {chunk.highlight_count}")

    lines.append("")

    # Tags summary
    tags = _format_chunk_tags(chunk.tags)
    if tags:
        lines.append(f"Tags: {tags}")
        lines.append("")

    # Text preview (first ~500 chars)
    text_preview = chunk.text[:500]
    if len(chunk.text) > 500:
        text_preview += "..."
    # Indent the preview
    preview_lines = text_preview.split("\n")
    lines.append("```")
    for pl in preview_lines[:10]:  # Limit to 10 lines
        lines.append(pl)
    if len(preview_lines) > 10:
        lines.append("...")
    lines.append("```")

    # Highlights summary (if any)
    if chunk.highlights:
        lines.append("")
        lines.append(f"**Highlights ({len(chunk.highlights)}):**")
        for i, hl in enumerate(chunk.highlights[:5]):  # Show first 5
            self_mark = "✓" if hl.self_contained else "○"
            hl_preview = hl.text[:100]
            if len(hl.text) > 100:
                hl_preview += "..."
            lines.append(f"  {i+1}. {self_mark} {hl_preview}")
        if len(chunk.highlights) > 5:
            lines.append(f"  ... and {len(chunk.highlights) - 5} more")

    return lines


def _format_chunk_tags(tags: TipTags) -> str:
    """Format chunk tags as a compact string."""
    parts: list[str] = []

    def add_if_present(name: str, values: list[str]) -> None:
        if values:
            parts.append(f"{name}: {', '.join(values[:3])}")
            if len(values) > 3:
                parts[-1] += f" (+{len(values) - 3})"

    add_if_present("dishes", list(tags.dishes))
    add_if_present("techniques", list(tags.techniques))
    add_if_present("methods", list(tags.cooking_methods))
    add_if_present("tools", list(tags.tools))

    # Combine all ingredient categories
    ingredients = (
        list(tags.meats) + list(tags.vegetables) + list(tags.herbs) +
        list(tags.spices) + list(tags.dairy) + list(tags.grains)
    )
    add_if_present("ingredients", ingredients)

    return " | ".join(parts) if parts else ""
