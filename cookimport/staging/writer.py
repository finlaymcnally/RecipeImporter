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
    AuthoritativeRecipeSemantics,
    ChunkHighlight,
    ChunkLane,
    ConversionReport,
    ConversionResult,
    KnowledgeChunk,
    RawArtifact,
    RecipeCandidate,
    TipTags,
)
from cookimport.parsing.label_source_of_truth import (
    LabelFirstStageResult,
)
from cookimport.staging.nonrecipe_stage import NonRecipeStageResult
from cookimport.parsing.tables import ExtractedTable
from cookimport.parsing.sections import extract_ingredient_sections, extract_instruction_sections
from cookimport.parsing.step_segmentation import (
    DEFAULT_INSTRUCTION_STEP_SEGMENTATION_POLICY,
    DEFAULT_INSTRUCTION_STEP_SEGMENTER,
    segment_instruction_steps,
)
from cookimport.staging.draft_v1 import (
    authoritative_recipe_semantics_to_draft_v1,
    recipe_candidate_to_draft_v1,
)
from cookimport.staging.jsonld import (
    authoritative_recipe_semantics_to_jsonld,
    recipe_candidate_to_jsonld,
)
from cookimport.staging.output_names import (
    NONRECIPE_AUTHORITY_FILE_NAME,
    NONRECIPE_AUTHORITY_SCHEMA_VERSION,
    NONRECIPE_EXCLUSIONS_FILE_NAME,
    NONRECIPE_FINALIZE_STATUS_FILE_NAME,
    NONRECIPE_FINALIZE_STATUS_SCHEMA_VERSION,
    NONRECIPE_FINAL_CATEGORY_FIELD,
    NONRECIPE_KNOWLEDGE_GROUPS_FILE_NAME,
    NONRECIPE_KNOWLEDGE_GROUPS_SCHEMA_VERSION,
    NONRECIPE_ROUTE_FIELD,
    NONRECIPE_ROUTE_FILE_NAME,
    NONRECIPE_ROUTE_SCHEMA_VERSION,
    NONRECIPE_CANDIDATE_INPUT_MODE,
)
from cookimport.staging.stage_block_predictions import build_stage_block_predictions

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_OUTPUT_CATEGORY_INTERMEDIATE = "intermediateDrafts"
_OUTPUT_CATEGORY_FINAL = "finalDrafts"
_OUTPUT_CATEGORY_CHUNKS = "chunks"
_OUTPUT_CATEGORY_TABLES = "tables"
_OUTPUT_CATEGORY_RAW = "rawArtifacts"
_OUTPUT_CATEGORY_SECTIONS = "sections"
_OUTPUT_CATEGORY_BENCH = "benchArtifacts"
_OUTPUT_CATEGORY_NONRECIPE = "nonRecipe"
_OUTPUT_CATEGORY_KNOWLEDGE = "knowledge"
_OUTPUT_CATEGORY_RECIPE_AUTHORITY = "recipeAuthority"

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
    authoritative_payloads_by_recipe_id: Mapping[str, AuthoritativeRecipeSemantics | dict[str, Any]]
    | None = None,
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
        elif authoritative_payloads_by_recipe_id is not None:
            authoritative_payload = authoritative_payloads_by_recipe_id.get(candidate.identifier)
            if authoritative_payload is not None:
                semantics = (
                    authoritative_payload
                    if isinstance(authoritative_payload, AuthoritativeRecipeSemantics)
                    else AuthoritativeRecipeSemantics.model_validate(authoritative_payload)
                )
                jsonld = authoritative_recipe_semantics_to_jsonld(
                    semantics,
                    template_candidate=candidate,
                )
            else:
                jsonld = recipe_candidate_to_jsonld(
                    candidate,
                    instruction_step_options=instruction_step_options,
                )
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
    authoritative_payloads_by_recipe_id: Mapping[str, AuthoritativeRecipeSemantics | dict[str, Any]]
    | None = None,
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
            for legacy_alias_key in ("name", "ingredients", "instructions"):
                draft.pop(legacy_alias_key, None)
        elif hasattr(override_payload, "model_dump"):
            draft = override_payload.model_dump(mode="json", by_alias=True, exclude_none=True)
        elif authoritative_payloads_by_recipe_id is not None:
            authoritative_payload = authoritative_payloads_by_recipe_id.get(recipe_id)
            if authoritative_payload is not None:
                semantics = (
                    authoritative_payload
                    if isinstance(authoritative_payload, AuthoritativeRecipeSemantics)
                    else AuthoritativeRecipeSemantics.model_validate(authoritative_payload)
                )
                draft = authoritative_recipe_semantics_to_draft_v1(
                    semantics,
                    ingredient_parser_options=ingredient_parser_options,
                    instruction_step_options=instruction_step_options,
                )
            else:
                draft = recipe_candidate_to_draft_v1(
                    candidate,
                    ingredient_parser_options=ingredient_parser_options,
                    instruction_step_options=instruction_step_options,
                )
        else:
            draft = recipe_candidate_to_draft_v1(
                candidate,
                ingredient_parser_options=ingredient_parser_options,
                instruction_step_options=instruction_step_options,
            )

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
    authoritative_payloads_by_recipe_id: Mapping[str, AuthoritativeRecipeSemantics | dict[str, Any]]
    | None = None,
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
        recipe_id = (
            candidate.provenance.get("@id")
            or candidate.provenance.get("id")
            or candidate.identifier
            or f"r{index}"
        )
        authoritative_payload = None
        if authoritative_payloads_by_recipe_id is not None:
            authoritative_payload = authoritative_payloads_by_recipe_id.get(str(recipe_id))
        if authoritative_payload is not None:
            semantics = (
                authoritative_payload
                if isinstance(authoritative_payload, AuthoritativeRecipeSemantics)
                else AuthoritativeRecipeSemantics.model_validate(authoritative_payload)
            )
            ingredient_sections = extract_ingredient_sections(list(semantics.ingredients))
            instruction_sections = extract_instruction_sections(list(semantics.instructions))
            recipe_title = semantics.title
            recipe_id = semantics.recipe_id
        else:
            ingredient_sections = extract_ingredient_sections(candidate.ingredients)
            instruction_texts = _effective_instruction_texts(
                candidate,
                instruction_step_options=instruction_step_options,
            )
            instruction_sections = extract_instruction_sections(instruction_texts)
            recipe_title = candidate.name

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

        payload = {
            "recipe_id": recipe_id,
            "title": recipe_title,
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
            markdown_lines.append(f"## r{index}: {recipe_title}")
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


def write_authoritative_recipe_semantics(
    *,
    payloads_by_recipe_id: Mapping[str, AuthoritativeRecipeSemantics | dict[str, Any]],
    out_path: Path,
    workbook_slug: str,
    refinement_mode: str,
    output_stats: OutputStats | None = None,
) -> Path:
    rows: list[dict[str, Any]] = []
    for recipe_id in sorted(payloads_by_recipe_id):
        payload = payloads_by_recipe_id[recipe_id]
        semantics = (
            payload
            if isinstance(payload, AuthoritativeRecipeSemantics)
            else AuthoritativeRecipeSemantics.model_validate(payload)
        )
        rows.append(semantics.model_dump(mode="json", by_alias=True, exclude_none=True))
    _write_json_payload(
        {
            "schema_version": "authoritative_recipe_payloads.v1",
            "workbook_slug": workbook_slug,
            "refinement_mode": refinement_mode,
            "recipe_count": len(rows),
            "recipes": rows,
        },
        out_path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_RECIPE_AUTHORITY,
    )
    return out_path


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
    nonrecipe_stage_result: NonRecipeStageResult | None = None,
    output_stats: OutputStats | None = None,
    label_first_result: LabelFirstStageResult | None = None,
) -> Path:
    """Write deterministic block-level stage predictions for benchmark scoring."""
    payload = build_stage_block_predictions(
        results,
        workbook_slug,
        source_file=source_file,
        source_hash=source_hash or (label_first_result.source_hash if label_first_result is not None else None),
        archive_blocks=archive_blocks or (
            list(label_first_result.archive_blocks)
            if label_first_result is not None
            else None
        ),
        nonrecipe_stage_result=nonrecipe_stage_result,
    )
    out_path = run_root / ".bench" / workbook_slug / "stage_block_predictions.json"
    _write_json_payload(
        payload,
        out_path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_BENCH,
    )
    return out_path


def write_nonrecipe_stage_outputs(
    stage_result: NonRecipeStageResult,
    output_dir: Path,
    *,
    output_stats: OutputStats | None = None,
) -> Path:
    path = write_nonrecipe_route_artifact(
        stage_result,
        output_dir,
        output_stats=output_stats,
    )
    write_nonrecipe_exclusions_ledger(
        stage_result,
        output_dir,
        output_stats=output_stats,
    )
    return path


def _block_id_for_stage_result(
    stage_result: NonRecipeStageResult,
    block_index: int,
) -> str:
    for span in (
        list(stage_result.seed.seed_nonrecipe_spans)
        + list(stage_result.routing.candidate_nonrecipe_spans)
        + list(stage_result.routing.excluded_nonrecipe_spans)
    ):
        for candidate_index, block_id in zip(span.block_indices, span.block_ids, strict=False):
            if int(candidate_index) == int(block_index):
                return str(block_id)
    return f"b{int(block_index)}"


def _serialize_nonrecipe_span(span: Any) -> dict[str, Any]:
    return {
        "span_id": span.span_id,
        "category": span.category,
        "block_start_index": span.block_start_index,
        "block_end_index": span.block_end_index,
        "block_indices": list(span.block_indices),
        "block_ids": list(span.block_ids),
    }


def _knowledge_counts_for_block_map(block_category_by_index: Mapping[int, str]) -> dict[str, int]:
    return {
        "knowledge_blocks": sum(
            1 for category in block_category_by_index.values() if category == "knowledge"
        ),
        "other_blocks": sum(
            1 for category in block_category_by_index.values() if category == "other"
        ),
    }


def write_nonrecipe_route_artifact(
    stage_result: NonRecipeStageResult,
    output_dir: Path,
    *,
    output_stats: OutputStats | None = None,
) -> Path:
    path = output_dir / NONRECIPE_ROUTE_FILE_NAME
    routing = stage_result.routing
    candidate_block_ids = [
        _block_id_for_stage_result(stage_result, int(block_index))
        for block_index in routing.candidate_block_indices
    ]
    excluded_block_ids = [
        _block_id_for_stage_result(stage_result, int(block_index))
        for block_index in routing.excluded_block_indices
    ]
    payload = {
        "schema_version": NONRECIPE_ROUTE_SCHEMA_VERSION,
        "counts": {
            "seed_nonrecipe_spans": len(stage_result.seed.seed_nonrecipe_spans),
            "seed_candidate_spans": len(stage_result.seed.seed_candidate_spans),
            "seed_excluded_spans": len(stage_result.seed.seed_excluded_spans),
            "candidate_nonrecipe_spans": len(routing.candidate_nonrecipe_spans),
            "excluded_nonrecipe_spans": len(routing.excluded_nonrecipe_spans),
            "candidate_blocks": len(routing.candidate_block_indices),
            "excluded_blocks": len(routing.excluded_block_indices),
            "warnings": len(routing.warnings),
        },
        "warnings": list(routing.warnings),
        "seed_route_by_index": {
            str(index): route
            for index, route in sorted(stage_result.seed.seed_route_by_index.items())
        },
        "route_by_block": {
            str(index): route
            for index, route in sorted(routing.route_by_block.items())
        },
        "candidate_block_indices": list(routing.candidate_block_indices),
        "candidate_block_ids": candidate_block_ids,
        "excluded_block_indices": list(routing.excluded_block_indices),
        "excluded_block_ids": excluded_block_ids,
        "exclusion_reason_by_block": {
            str(index): reason
            for index, reason in sorted(routing.exclusion_reason_by_block.items())
        },
        "seed_nonrecipe_spans": [
            _serialize_nonrecipe_span(span)
            for span in stage_result.seed.seed_nonrecipe_spans
        ],
        "candidate_spans": [
            _serialize_nonrecipe_span(span)
            for span in routing.candidate_nonrecipe_spans
        ],
        "excluded_spans": [
            _serialize_nonrecipe_span(span)
            for span in routing.excluded_nonrecipe_spans
        ],
        "block_preview_by_index": {
            str(index): preview
            for index, preview in sorted(routing.block_preview_by_index.items())
        },
    }
    _write_json_payload(
        payload,
        path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_NONRECIPE,
    )
    return path


def write_nonrecipe_exclusions_ledger(
    stage_result: NonRecipeStageResult,
    output_dir: Path,
    *,
    output_stats: OutputStats | None = None,
) -> Path:
    exclusion_ledger_path = output_dir / NONRECIPE_EXCLUSIONS_FILE_NAME
    routing = stage_result.routing
    exclusion_rows = [
        {
            "block_index": int(block_index),
            "block_id": _block_id_for_stage_result(stage_result, int(block_index)),
            "final_category": "other",
            "exclusion_reason": reason,
            "preview": str(routing.block_preview_by_index.get(int(block_index)) or ""),
            "exclusion_source": "line_role",
        }
        for block_index, reason in sorted(routing.exclusion_reason_by_block.items())
    ]
    exclusion_payload = "\n".join(
        json.dumps(row, sort_keys=True) for row in exclusion_rows
    )
    if exclusion_payload:
        exclusion_payload += "\n"
    _write_text_payload(
        exclusion_payload,
        exclusion_ledger_path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_NONRECIPE,
    )
    return exclusion_ledger_path


def write_knowledge_outputs_artifact(
    *,
    run_root: Path,
    stage_result: NonRecipeStageResult,
    llm_report: Mapping[str, Any] | None,
    knowledge_group_records: list[dict[str, Any]] | None,
    snippet_records: list[dict[str, Any]] | None,
    output_stats: OutputStats | None = None,
) -> Path:
    write_nonrecipe_authority_artifact(
        run_root=run_root,
        stage_result=stage_result,
        output_stats=output_stats,
    )
    write_nonrecipe_knowledge_groups_artifact(
        run_root=run_root,
        knowledge_group_records=knowledge_group_records,
        output_stats=output_stats,
    )
    return write_nonrecipe_finalize_status_artifact(
        run_root=run_root,
        stage_result=stage_result,
        llm_report=llm_report,
        snippet_records=snippet_records,
        output_stats=output_stats,
    )


def write_nonrecipe_authority_artifact(
    *,
    run_root: Path,
    stage_result: NonRecipeStageResult,
    output_stats: OutputStats | None = None,
) -> Path:
    path = run_root / NONRECIPE_AUTHORITY_FILE_NAME
    authority = stage_result.authority
    payload = {
        "schema_version": NONRECIPE_AUTHORITY_SCHEMA_VERSION,
        "authority_mode": str(
            stage_result.refinement_report.get("authority_mode")
            or "deterministic_route_only"
        ),
        "scored_effect": str(
            stage_result.refinement_report.get("scored_effect")
            or "route_only"
        ),
        "counts": {
            "authoritative_nonrecipe_spans": len(authority.authoritative_nonrecipe_spans),
            "authoritative_knowledge_spans": len(authority.authoritative_knowledge_spans),
            "authoritative_other_spans": len(authority.authoritative_other_spans),
            "final_authority_blocks": len(authority.authoritative_block_indices),
            **_knowledge_counts_for_block_map(authority.authoritative_block_category_by_index),
            "warnings": len(stage_result.routing.warnings),
        },
        "final_authority_block_indices": list(authority.authoritative_block_indices),
        "authoritative_block_category_by_index": {
            str(index): category
            for index, category in sorted(authority.authoritative_block_category_by_index.items())
        },
        "authoritative_spans": [
            _serialize_nonrecipe_span(span)
            for span in authority.authoritative_nonrecipe_spans
        ],
        "authoritative_knowledge_spans": [
            _serialize_nonrecipe_span(span)
            for span in authority.authoritative_knowledge_spans
        ],
        "authoritative_other_spans": [
            _serialize_nonrecipe_span(span)
            for span in authority.authoritative_other_spans
        ],
        "warnings": list(stage_result.routing.warnings),
    }
    _write_json_payload(
        payload,
        path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_NONRECIPE,
    )
    return path


def write_nonrecipe_knowledge_groups_artifact(
    *,
    run_root: Path,
    knowledge_group_records: list[dict[str, Any]] | None,
    output_stats: OutputStats | None = None,
) -> Path:
    path = run_root / NONRECIPE_KNOWLEDGE_GROUPS_FILE_NAME
    payload = {
        "schema_version": NONRECIPE_KNOWLEDGE_GROUPS_SCHEMA_VERSION,
        "count": len(knowledge_group_records or []),
        "knowledge_groups": list(knowledge_group_records or []),
    }
    _write_json_payload(
        payload,
        path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_KNOWLEDGE,
    )
    return path


def write_nonrecipe_finalize_status_artifact(
    *,
    run_root: Path,
    stage_result: NonRecipeStageResult,
    llm_report: Mapping[str, Any] | None,
    snippet_records: list[dict[str, Any]] | None,
    output_stats: OutputStats | None = None,
) -> Path:
    counts = {}
    if isinstance(llm_report, Mapping):
        raw_counts = llm_report.get("counts")
        if isinstance(raw_counts, Mapping):
            counts = {
                str(key): raw_counts.get(key)
                for key in raw_counts
            }
    path = run_root / NONRECIPE_FINALIZE_STATUS_FILE_NAME
    routing = stage_result.routing
    authority = stage_result.authority
    candidate_status_result = stage_result.candidate_status
    finalized_candidate_block_indices = list(
        candidate_status_result.finalized_candidate_block_indices
    )
    changed_block_indices = [
        int(row.get("block_index"))
        for row in (stage_result.refinement_report.get("changed_blocks") or [])
        if isinstance(row, dict) and row.get("block_index") is not None
    ]
    candidate_status = str(
        (llm_report or {}).get("candidate_status")
        or ""
    ).strip()
    if not candidate_status:
        candidate_status = "not_run" if not bool((llm_report or {}).get("enabled")) else "unknown"
    payload = {
        "schema_version": NONRECIPE_FINALIZE_STATUS_SCHEMA_VERSION,
        "input_mode": str(
            (llm_report or {}).get("input_mode")
            or NONRECIPE_CANDIDATE_INPUT_MODE
        ),
        "candidate_status": candidate_status,
        "stage_status": str((llm_report or {}).get("stage_status") or ""),
        "counts": {
            "candidate_blocks": len(routing.candidate_block_indices),
            "excluded_blocks": len(routing.excluded_block_indices),
            "finalized_candidate_blocks": len(finalized_candidate_block_indices),
            "final_authority_blocks": len(authority.authoritative_block_indices),
            "unresolved_candidate_blocks": len(
                candidate_status_result.unresolved_candidate_block_indices
            ),
            "shards_written": int(counts.get("shards_written") or 0),
            "outputs_parsed": int(counts.get("outputs_parsed") or 0),
            "packets_missing": int(counts.get("packets_missing") or 0),
            "skipped_packet_count": int(counts.get("skipped_packet_count") or 0),
            "snippets_written": int(counts.get("snippets_written") or 0),
            "decisions_applied": int(counts.get("decisions_applied") or 0),
            "changed_blocks": int(counts.get("changed_blocks") or 0),
        },
        "pipeline": str((llm_report or {}).get("pipeline") or "off"),
        "enabled": bool((llm_report or {}).get("enabled")),
        "authority_mode": str(
            (llm_report or {}).get("authority_mode")
            or stage_result.refinement_report.get("authority_mode")
            or "deterministic_route_only"
        ),
        "scored_effect": str(
            (llm_report or {}).get("scored_effect")
            or stage_result.refinement_report.get("scored_effect")
            or "route_only"
        ),
        "artifact_paths": dict((llm_report or {}).get("paths") or {}),
        "missing_packet_ids": list((llm_report or {}).get("missing_packet_ids") or []),
        "candidate_summary": dict(
            (llm_report or {}).get("candidate_summary")
            or (llm_report or {}).get("review_summary")
            or {}
        ),
        "route_by_block": {
            str(index): route
            for index, route in sorted(routing.route_by_block.items())
        },
        "candidate_block_indices": list(routing.candidate_block_indices),
        "excluded_block_indices": list(routing.excluded_block_indices),
        "finalized_candidate_block_indices": finalized_candidate_block_indices,
        "unresolved_candidate_block_indices": list(
            candidate_status_result.unresolved_candidate_block_indices
        ),
        "unresolved_candidate_route_by_index": {
            str(index): route
            for index, route in sorted(
                candidate_status_result.unresolved_candidate_route_by_index.items()
            )
        },
        "unresolved_candidate_spans": [
            _serialize_nonrecipe_span(span)
            for span in candidate_status_result.unresolved_candidate_spans
        ],
        "changed_block_indices": changed_block_indices,
        "warnings": list(routing.warnings),
        "refinement_report": dict(stage_result.refinement_report),
        "snippets_written": len(snippet_records or []),
    }
    _write_json_payload(
        payload,
        path,
        output_stats=output_stats,
        category=_OUTPUT_CATEGORY_KNOWLEDGE,
    )
    return path


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
    # Treat the narrative lane as noise for reporting.
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
