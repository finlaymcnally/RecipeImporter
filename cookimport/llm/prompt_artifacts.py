from __future__ import annotations

import csv
import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from cookimport.core.slug import slugify_name

PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION = "prompt_run_descriptor.v1"
PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION = "prompt_stage_descriptor.v1"
PROMPT_CALL_RECORD_SCHEMA_VERSION = "prompt_call_record.v1"
PROMPT_TYPE_SAMPLES_MD_NAME = "prompt_type_samples_from_full_prompt_log.md"

_CODEXFARM_PASS_DIR_MAP: dict[str, str] = {
    "pass1": "pass1_chunking",
    "pass2": "pass2_schemaorg",
    "pass3": "pass3_final",
    "pass4": "pass4_knowledge",
    "pass5": "pass5_tags",
}

_CODEXFARM_PASS_TASK_MAP: dict[str, str] = {
    "pass1": "task1",
    "pass2": "task2",
    "pass3": "task3",
    "pass4": "task4",
    "pass5": "task5",
}

_CODEXFARM_PASS_PIPELINE_MAP: dict[str, str] = {
    "pass1": "recipe.chunking.v1",
    "pass2": "recipe.schemaorg.compact.v1",
    "pass3": "recipe.final.compact.v1",
    "pass4": "recipe.knowledge.compact.v1",
    "pass5": "recipe.tags.v1",
}

_CODEXFARM_PASS_SORT_ORDER: dict[str, int] = {
    "pass1": 1,
    "pass2": 2,
    "pass3": 3,
    "pass4": 4,
    "pass5": 5,
}

_CODEXFARM_PASS_MANIFEST_NAME_MAP: dict[str, str] = {
    "pass1": "llm_manifest.json",
    "pass2": "llm_manifest.json",
    "pass3": "llm_manifest.json",
    "pass4": "pass4_knowledge_manifest.json",
    "pass5": "pass5_tags_manifest.json",
}


@dataclass(frozen=True)
class PromptCallRecord:
    schema_version: str
    row: dict[str, Any]

    def to_row(self) -> dict[str, Any]:
        payload = dict(self.row)
        payload.setdefault("schema_version", self.schema_version)
        return payload


@dataclass(frozen=True)
class PromptStageDescriptor:
    schema_version: str
    legacy_pass: str
    task_name: str
    slot_index: int
    stage_dir_name: str
    stage_key: str
    stage_heading_key: str
    stage_label: str
    stage_artifact_stem: str
    stage_matches_legacy: bool
    pipeline_id: str | None
    manifest_name: str
    manifest_path: Path | None
    manifest_payload: dict[str, Any]
    process_run_payload: dict[str, Any] | None
    input_dir: Path
    output_dir: Path


@dataclass(frozen=True)
class PromptRunDescriptor:
    schema_version: str
    run_dir: Path
    manifest_payload_by_name: dict[str, dict[str, Any]]
    manifest_path_by_name: dict[str, Path]
    stages: tuple[PromptStageDescriptor, ...]
    codex_farm_pipeline: str | None
    codex_farm_model: str | None
    codex_farm_reasoning_effort: str | None
    notes: tuple[str, ...] = field(default_factory=tuple)

_PROMPT_STAGE_SLOT_METADATA: dict[str, dict[str, Any]] = {
    "pass1": {
        "slot_index": 1,
        "default_label": "Chunking",
        "default_artifact_stem": "pass1_chunking",
        "expected_stage_key": "chunking",
    },
    "pass2": {
        "slot_index": 2,
        "default_label": "Schema.org Extraction",
        "default_artifact_stem": "pass2_schemaorg",
        "expected_stage_key": "schemaorg",
    },
    "pass3": {
        "slot_index": 3,
        "default_label": "Final Draft",
        "default_artifact_stem": "pass3_final",
        "expected_stage_key": "final",
    },
    "pass4": {
        "slot_index": 4,
        "default_label": "Knowledge Harvest",
        "default_artifact_stem": "pass4_knowledge",
        "expected_stage_key": "knowledge",
    },
    "pass5": {
        "slot_index": 5,
        "default_label": "Tag Suggestions",
        "default_artifact_stem": "pass5_tags",
        "expected_stage_key": "tags",
    },
}

_PROMPT_STAGE_LABELS_BY_KEY = {
    "chunking": "Chunking",
    "schemaorg": "Schema.org Extraction",
    "final": "Final Draft",
    "knowledge": "Knowledge Harvest",
    "tags": "Tag Suggestions",
    "merged_repair": "Merged Repair",
}

_TEXT_ATTACHMENT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".csv",
}


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"<<unreadable file: {exc}>>"


def _parse_json_text(raw_text: str) -> Any | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _files_in_dir(path: Path | None) -> list[Path]:
    if path is None or not path.exists() or not path.is_dir():
        return []
    return sorted((child for child in path.iterdir() if child.is_file()), key=lambda p: p.name)


def _clean_text(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return None
    if cleaned in {"1", "true", "yes", "y", "on"}:
        return True
    if cleaned in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _parse_json_string_list(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parsed = _parse_json_text(text)
    if not isinstance(parsed, list):
        return []
    rows: list[str] = []
    for item in parsed:
        cleaned = _clean_text(item)
        if cleaned is not None:
            rows.append(cleaned)
    return rows


def _timestamp_utc_for_path(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        timestamp = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    except OSError:
        return None
    return timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_prompt_stage_text(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _derive_prompt_stage_key_from_pipeline_id(pipeline_id: str | None) -> str | None:
    normalized = _clean_prompt_stage_text(pipeline_id)
    if normalized is None:
        return None
    filtered_tokens: list[str] = []
    for token in re.split(r"[^a-z0-9]+", normalized.lower()):
        if not token:
            continue
        if token in {"recipe", "compact", "pipeline", "codex", "farm"}:
            continue
        if re.fullmatch(r"v\d+", token):
            continue
        filtered_tokens.append(token)
    if not filtered_tokens:
        return None
    return slugify_name("_".join(filtered_tokens))


def _fallback_prompt_stage_key(*, pass_name: str, path_root: str | None) -> str:
    root_slug = slugify_name(str(path_root or "").strip()) if path_root else ""
    if root_slug.startswith(f"{pass_name}_"):
        trimmed = root_slug[len(pass_name) + 1 :].strip("_")
        if trimmed:
            return trimmed
    return root_slug or pass_name or "stage"


def _prompt_stage_label_from_key(stage_key: str) -> str:
    normalized = slugify_name(stage_key)
    mapped = _PROMPT_STAGE_LABELS_BY_KEY.get(normalized)
    if mapped is not None:
        return mapped
    return normalized.replace("_", " ").strip().title() or "Prompt Stage"


def _build_prompt_stage_metadata(
    *,
    pass_name: str,
    path_root: str | None,
    pipeline_id: str | None,
) -> dict[str, Any]:
    slot_metadata = _PROMPT_STAGE_SLOT_METADATA.get(pass_name, {})
    slot_index = int(slot_metadata.get("slot_index") or 999)
    expected_stage_key = _clean_prompt_stage_text(
        slot_metadata.get("expected_stage_key")
    )
    default_label = _clean_prompt_stage_text(slot_metadata.get("default_label"))
    default_artifact_stem = _clean_prompt_stage_text(
        slot_metadata.get("default_artifact_stem")
    )
    path_slug = slugify_name(str(path_root or "").strip()) if path_root else ""
    stage_key = _derive_prompt_stage_key_from_pipeline_id(pipeline_id) or _fallback_prompt_stage_key(
        pass_name=pass_name,
        path_root=path_root,
    )
    matches_legacy = bool(
        expected_stage_key
        and stage_key == expected_stage_key
        and path_slug
        and expected_stage_key in path_slug
    )
    heading_key = pass_name if matches_legacy else stage_key
    artifact_stem = (
        path_slug
        if matches_legacy and path_slug
        else slugify_name(stage_key or default_artifact_stem or pass_name)
    )
    label = (
        default_label
        if matches_legacy and default_label is not None
        else _prompt_stage_label_from_key(stage_key)
    )
    return {
        "pass_name": pass_name,
        "slot_index": slot_index,
        "pipeline_id": _clean_prompt_stage_text(pipeline_id),
        "path_root": _clean_prompt_stage_text(path_root),
        "stage_key": stage_key,
        "heading_key": heading_key,
        "label": label,
        "artifact_stem": artifact_stem or f"stage_{slot_index}",
        "matches_legacy": matches_legacy,
    }


def _prompt_stage_metadata_from_row(row: dict[str, Any]) -> dict[str, Any]:
    pass_name = (
        _clean_prompt_stage_text(row.get("legacy_pass"))
        or _clean_prompt_stage_text(row.get("pass"))
        or "stage"
    )
    metadata = _build_prompt_stage_metadata(
        pass_name=pass_name,
        path_root=(
            _clean_prompt_stage_text(row.get("stage_dir_name"))
            or _clean_prompt_stage_text(row.get("stage_dir"))
            or _clean_prompt_stage_text(row.get("path_root"))
        ),
        pipeline_id=_clean_prompt_stage_text(row.get("pipeline_id")),
    )
    stage_key = _clean_prompt_stage_text(row.get("stage_key"))
    if stage_key is not None:
        metadata["stage_key"] = slugify_name(stage_key)
    heading_key = _clean_prompt_stage_text(row.get("stage_heading_key"))
    if heading_key is not None:
        metadata["heading_key"] = slugify_name(heading_key)
    label = _clean_prompt_stage_text(row.get("stage_label"))
    if label is not None:
        metadata["label"] = label
    artifact_stem = _clean_prompt_stage_text(row.get("stage_artifact_stem"))
    if artifact_stem is not None:
        metadata["artifact_stem"] = slugify_name(artifact_stem)
    if "stage_matches_legacy" in row:
        metadata["matches_legacy"] = bool(row.get("stage_matches_legacy"))
    try:
        stage_slot_index = int(row.get("stage_slot_index"))
    except (TypeError, ValueError):
        stage_slot_index = None
    if stage_slot_index is not None:
        metadata["slot_index"] = stage_slot_index
    return metadata


def _resolve_process_run_payload_for_legacy_pass(
    *,
    legacy_pass: str,
    manifest_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if legacy_pass in {"pass1", "pass2", "pass3"}:
        process_runs = manifest_payload.get("process_runs")
        if not isinstance(process_runs, dict):
            return None
        pass_payload = process_runs.get(legacy_pass)
        return pass_payload if isinstance(pass_payload, dict) else None
    if legacy_pass == "pass4":
        process_run = manifest_payload.get("process_run")
        if isinstance(process_run, dict):
            return process_run
        llm_report = manifest_payload.get("llm_report")
        if isinstance(llm_report, dict):
            report_process_run = llm_report.get("process_run")
            if isinstance(report_process_run, dict):
                return report_process_run
        return None
    if legacy_pass == "pass5":
        llm_report = manifest_payload.get("llm_report")
        if isinstance(llm_report, dict):
            report_process_run = llm_report.get("process_run")
            if isinstance(report_process_run, dict):
                return report_process_run
        process_run = manifest_payload.get("process_run")
        if isinstance(process_run, dict):
            return process_run
    return None


def _resolve_manifest_pipeline_id_for_legacy_pass(
    *,
    legacy_pass: str,
    manifest_payload: dict[str, Any],
) -> str | None:
    if legacy_pass in {"pass1", "pass2", "pass3"}:
        process_run = _resolve_process_run_payload_for_legacy_pass(
            legacy_pass=legacy_pass,
            manifest_payload=manifest_payload,
        )
        if isinstance(process_run, dict):
            candidate = _clean_text(process_run.get("pipeline_id"))
            if candidate is not None:
                return candidate
        return _CODEXFARM_PASS_PIPELINE_MAP.get(legacy_pass)
    if legacy_pass == "pass4":
        candidate = _clean_text(manifest_payload.get("pipeline_id"))
        if candidate is not None:
            return candidate
        llm_report = manifest_payload.get("llm_report")
        if isinstance(llm_report, dict):
            report_candidate = _clean_text(llm_report.get("pipeline_id"))
            if report_candidate is not None:
                return report_candidate
        return _CODEXFARM_PASS_PIPELINE_MAP.get(legacy_pass)
    if legacy_pass == "pass5":
        llm_report = manifest_payload.get("llm_report")
        if isinstance(llm_report, dict):
            report_candidate = _clean_text(llm_report.get("pipeline_id"))
            if report_candidate is not None:
                return report_candidate
        candidate = _clean_text(manifest_payload.get("pipeline_id"))
        if candidate is not None:
            return candidate
    return _CODEXFARM_PASS_PIPELINE_MAP.get(legacy_pass)


def _resolve_stage_in_out_dirs_for_legacy_pass(
    *,
    legacy_pass: str,
    manifest_payload: dict[str, Any],
    run_dir: Path,
    stage_dir_name: str,
) -> tuple[Path, Path]:
    paths_payload: dict[str, Any] = {}
    if legacy_pass == "pass5":
        llm_report = manifest_payload.get("llm_report")
        if isinstance(llm_report, dict):
            llm_paths = llm_report.get("paths")
            if isinstance(llm_paths, dict):
                paths_payload = llm_paths
    if not paths_payload:
        raw_paths = manifest_payload.get("paths")
        if isinstance(raw_paths, dict):
            paths_payload = raw_paths

    pass_input_key_map = {
        "pass1": "pass1_in",
        "pass2": "pass2_in",
        "pass3": "pass3_in",
        "pass4": "pass4_in_dir",
        "pass5": "in_dir",
    }
    pass_output_key_map = {
        "pass1": "pass1_out",
        "pass2": "pass2_out",
        "pass3": "pass3_out",
        "pass4": "pass4_out_dir",
        "pass5": "out_dir",
    }

    input_key = pass_input_key_map.get(legacy_pass)
    output_key = pass_output_key_map.get(legacy_pass)
    pass_in = paths_payload.get(input_key) if input_key is not None else None
    pass_out = paths_payload.get(output_key) if output_key is not None else None

    in_dir = Path(str(pass_in)) if isinstance(pass_in, str) else None
    out_dir = Path(str(pass_out)) if isinstance(pass_out, str) else None
    if in_dir is None or not in_dir.exists():
        in_dir = run_dir / stage_dir_name / "in"
    if out_dir is None or not out_dir.exists():
        out_dir = run_dir / stage_dir_name / "out"
    return in_dir, out_dir


def discover_codexfarm_prompt_run_descriptors(
    *,
    pred_run: Path,
) -> list[PromptRunDescriptor]:
    raw_llm_dir = pred_run / "raw" / "llm"
    if not raw_llm_dir.exists() or not raw_llm_dir.is_dir():
        return []

    run_dirs: list[Path] = [path for path in raw_llm_dir.iterdir() if path.is_dir()]
    if not run_dirs:
        return []

    descriptors: list[PromptRunDescriptor] = []
    manifest_names = sorted(set(_CODEXFARM_PASS_MANIFEST_NAME_MAP.values()))
    for run_dir in sorted(run_dirs, key=lambda value: value.name):
        manifest_payload_by_name: dict[str, dict[str, Any]] = {}
        manifest_path_by_name: dict[str, Path] = {}
        for manifest_name in manifest_names:
            manifest_path = run_dir / manifest_name
            payload = _load_json_dict(manifest_path) or {}
            if not payload:
                continue
            manifest_payload_by_name[manifest_name] = payload
            manifest_path_by_name[manifest_name] = manifest_path

        notes: list[str] = []
        stages: list[PromptStageDescriptor] = []
        if not manifest_payload_by_name:
            notes.append("missing pass manifests")
        else:
            for legacy_pass, stage_dir_name in _CODEXFARM_PASS_DIR_MAP.items():
                manifest_name = _CODEXFARM_PASS_MANIFEST_NAME_MAP.get(legacy_pass)
                if manifest_name is None:
                    continue
                manifest_payload = manifest_payload_by_name.get(manifest_name)
                if not isinstance(manifest_payload, dict):
                    continue
                pipeline_id = _resolve_manifest_pipeline_id_for_legacy_pass(
                    legacy_pass=legacy_pass,
                    manifest_payload=manifest_payload,
                )
                stage_metadata = _build_prompt_stage_metadata(
                    pass_name=legacy_pass,
                    path_root=stage_dir_name,
                    pipeline_id=pipeline_id,
                )
                input_dir, output_dir = _resolve_stage_in_out_dirs_for_legacy_pass(
                    legacy_pass=legacy_pass,
                    manifest_payload=manifest_payload,
                    run_dir=run_dir,
                    stage_dir_name=stage_dir_name,
                )
                process_run_payload = _resolve_process_run_payload_for_legacy_pass(
                    legacy_pass=legacy_pass,
                    manifest_payload=manifest_payload,
                )
                stages.append(
                    PromptStageDescriptor(
                        schema_version=PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION,
                        legacy_pass=legacy_pass,
                        task_name=_CODEXFARM_PASS_TASK_MAP.get(legacy_pass, legacy_pass),
                        slot_index=int(stage_metadata.get("slot_index") or 999),
                        stage_dir_name=stage_dir_name,
                        stage_key=str(stage_metadata.get("stage_key") or legacy_pass),
                        stage_heading_key=str(
                            stage_metadata.get("heading_key")
                            or stage_metadata.get("stage_key")
                            or legacy_pass
                        ),
                        stage_label=str(stage_metadata.get("label") or "Prompt Stage"),
                        stage_artifact_stem=str(
                            stage_metadata.get("artifact_stem") or legacy_pass
                        ),
                        stage_matches_legacy=bool(stage_metadata.get("matches_legacy")),
                        pipeline_id=pipeline_id,
                        manifest_name=manifest_name,
                        manifest_path=manifest_path_by_name.get(manifest_name),
                        manifest_payload=manifest_payload,
                        process_run_payload=(
                            process_run_payload
                            if isinstance(process_run_payload, dict)
                            else None
                        ),
                        input_dir=input_dir,
                        output_dir=output_dir,
                    )
                )

        primary_manifest = manifest_payload_by_name.get("llm_manifest.json", {})
        descriptors.append(
            PromptRunDescriptor(
                schema_version=PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION,
                run_dir=run_dir,
                manifest_payload_by_name=manifest_payload_by_name,
                manifest_path_by_name=manifest_path_by_name,
                stages=tuple(
                    sorted(
                        stages,
                        key=lambda stage: (
                            stage.slot_index,
                            _CODEXFARM_PASS_SORT_ORDER.get(stage.legacy_pass, 999),
                            stage.legacy_pass,
                        ),
                    )
                ),
                codex_farm_pipeline=_clean_text(primary_manifest.get("pipeline")),
                codex_farm_model=_clean_text(primary_manifest.get("codex_farm_model")),
                codex_farm_reasoning_effort=_clean_text(
                    primary_manifest.get("codex_farm_reasoning_effort")
                ),
                notes=tuple(notes),
            )
        )
    return descriptors


def build_codex_farm_prompt_type_samples_markdown(
    *,
    full_prompt_log_path: Path,
    output_path: Path,
    examples_per_pass: int = 3,
) -> Path | None:
    if examples_per_pass <= 0:
        return None
    if not full_prompt_log_path.exists() or not full_prompt_log_path.is_file():
        return None

    samples_by_stage: dict[str, list[dict[str, Any]]] = {}
    stage_metadata_by_key: dict[str, dict[str, Any]] = {}
    stage_first_seen: dict[str, int] = {}

    def _extract_reasoning_excerpt(
        reasoning_events: list[dict[str, Any]],
        *,
        max_events: int = 3,
        max_chars: int = 3000,
    ) -> str | None:
        if not reasoning_events:
            return None
        snippets: list[str] = []
        for event in reasoning_events[:max_events]:
            if not isinstance(event, dict):
                continue
            for key in ("summary_text", "summary", "text", "delta", "content"):
                value = event.get(key)
                if isinstance(value, str):
                    cleaned = value.strip()
                    if cleaned:
                        snippets.append(cleaned)
                        break
        if snippets:
            joined = "\n\n".join(snippets)
            if len(joined) > max_chars:
                return joined[: max_chars - 3].rstrip() + "..."
            return joined
        try:
            serialized = json.dumps(
                reasoning_events[:max_events],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        except TypeError:
            return None
        if len(serialized) > max_chars:
            return serialized[: max_chars - 3].rstrip() + "..."
        return serialized

    try:
        with full_prompt_log_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                stage_metadata = _prompt_stage_metadata_from_row(row)
                stage_group_key = str(stage_metadata.get("heading_key") or "").strip()
                if not stage_group_key:
                    continue
                if stage_group_key not in samples_by_stage:
                    samples_by_stage[stage_group_key] = []
                    stage_metadata_by_key[stage_group_key] = dict(stage_metadata)
                    stage_first_seen[stage_group_key] = len(stage_first_seen)
                if len(samples_by_stage[stage_group_key]) >= examples_per_pass:
                    continue

                prompt_text: str | None = None
                request_messages = row.get("request_messages")
                if isinstance(request_messages, list) and request_messages:
                    first_message = request_messages[0]
                    if isinstance(first_message, dict):
                        content = first_message.get("content")
                        if isinstance(content, str):
                            prompt_text = content
                if prompt_text is None:
                    rendered_prompt_text = row.get("rendered_prompt_text")
                    if isinstance(rendered_prompt_text, str):
                        prompt_text = rendered_prompt_text
                if prompt_text is None:
                    user_prompt = row.get("user_prompt")
                    if isinstance(user_prompt, str):
                        prompt_text = user_prompt
                prompt_text = str(prompt_text or "")

                thinking_trace_payload = row.get("thinking_trace")
                reasoning_events: list[dict[str, Any]] = []
                thinking_trace_path: str | None = None
                thinking_trace_available = False
                thinking_trace_reasoning_count: int | None = None
                if isinstance(thinking_trace_payload, dict):
                    raw_reasoning_events = thinking_trace_payload.get("reasoning_events")
                    if isinstance(raw_reasoning_events, list):
                        reasoning_events = [
                            event
                            for event in raw_reasoning_events
                            if isinstance(event, dict)
                        ]
                    trace_path = thinking_trace_payload.get("path")
                    if isinstance(trace_path, str) and trace_path.strip():
                        thinking_trace_path = trace_path.strip()
                    thinking_trace_available = bool(thinking_trace_payload.get("available"))
                    reasoning_count = thinking_trace_payload.get("reasoning_event_count")
                    if isinstance(reasoning_count, int):
                        thinking_trace_reasoning_count = reasoning_count
                thinking_trace_excerpt = _extract_reasoning_excerpt(reasoning_events)

                call_id = str(row.get("call_id") or "").strip() or "<unknown>"
                recipe_id = str(row.get("recipe_id") or "").strip() or "<unknown>"
                samples_by_stage[stage_group_key].append(
                    {
                        "call_id": call_id,
                        "recipe_id": recipe_id,
                        "prompt": prompt_text.rstrip("\n"),
                        "thinking_trace_available": thinking_trace_available,
                        "thinking_trace_path": thinking_trace_path,
                        "thinking_trace_reasoning_count": thinking_trace_reasoning_count,
                        "thinking_trace_excerpt": thinking_trace_excerpt,
                    }
                )
    except OSError:
        return None

    if not any(samples_by_stage.values()):
        return None

    generated_timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    lines: list[str] = [
        "# CodexFarm Prompt Samples (Literal)",
        "",
        f"Generated: {generated_timestamp}",
        "Source:",
        f"- {full_prompt_log_path}",
        "",
        "Notes:",
        "- Samples are verbatim from `request_messages[0].content` when available.",
        "- Includes full inline JSON payloads exactly as emitted.",
        f"- Up to {examples_per_pass} examples per discovered prompt stage.",
        "- When a prompt stage diverges from a legacy pass slot, the observed stage label is shown instead of the compatibility pass name.",
        "",
    ]

    occupied_slot_indices = {
        int(metadata.get("slot_index") or 999)
        for metadata in stage_metadata_by_key.values()
    }
    render_entries: list[tuple[str, dict[str, Any], list[dict[str, Any]], int]] = []
    for stage_group_key, metadata in stage_metadata_by_key.items():
        render_entries.append(
            (
                stage_group_key,
                metadata,
                samples_by_stage.get(stage_group_key, []),
                stage_first_seen.get(stage_group_key, 0),
            )
        )
    for pass_name, slot_metadata in _PROMPT_STAGE_SLOT_METADATA.items():
        slot_index = int(slot_metadata.get("slot_index") or 999)
        if slot_index in occupied_slot_indices:
            continue
        placeholder_metadata = _build_prompt_stage_metadata(
            pass_name=pass_name,
            path_root=_clean_prompt_stage_text(slot_metadata.get("default_artifact_stem")),
            pipeline_id=None,
        )
        render_entries.append(
            (
                str(placeholder_metadata.get("heading_key") or pass_name),
                placeholder_metadata,
                [],
                999 + slot_index,
            )
        )
    render_entries.sort(
        key=lambda entry: (
            int(entry[1].get("slot_index") or 999),
            entry[3],
            entry[0],
        )
    )

    for stage_group_key, metadata, stage_samples, _ in render_entries:
        stage_label = str(metadata.get("label") or "Prompt Stage")
        lines.append(f"## {stage_group_key} ({stage_label})")
        lines.append("")
        legacy_pass = _clean_prompt_stage_text(metadata.get("pass_name"))
        pipeline_id = _clean_prompt_stage_text(metadata.get("pipeline_id"))
        if not bool(metadata.get("matches_legacy")):
            if legacy_pass is not None:
                lines.append(f"- legacy_slot: `{legacy_pass}`")
            if pipeline_id is not None:
                lines.append(f"- pipeline_id: `{pipeline_id}`")
            if legacy_pass is not None or pipeline_id is not None:
                lines.append("")
        if not stage_samples:
            lines.append("_No rows captured for this pass._")
            lines.append("")
            continue
        for index, sample in enumerate(stage_samples, start=1):
            lines.append(f"### Example {index}")
            lines.append(f"call_id: `{sample['call_id']}`")
            lines.append(f"recipe_id: `{sample['recipe_id']}`")
            lines.append("")
            lines.append("```text")
            lines.append(sample["prompt"])
            lines.append("```")
            lines.append("")
            lines.append("Thinking Trace:")
            thinking_trace_available = bool(sample.get("thinking_trace_available"))
            thinking_trace_reasoning_count = sample.get("thinking_trace_reasoning_count")
            thinking_trace_path = sample.get("thinking_trace_path")
            thinking_trace_excerpt = sample.get("thinking_trace_excerpt")
            if thinking_trace_path:
                lines.append(f"- trace_path: `{thinking_trace_path}`")
            if isinstance(thinking_trace_reasoning_count, int):
                lines.append(
                    f"- reasoning_event_count: `{thinking_trace_reasoning_count}`"
                )
            if thinking_trace_excerpt:
                lines.append("")
                lines.append("```text")
                lines.append(str(thinking_trace_excerpt))
                lines.append("```")
            elif not thinking_trace_available:
                lines.append("- _No thinking trace captured for this sample._")
            lines.append("")

    try:
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return None
    return output_path


def build_codex_farm_prompt_response_log(
    *,
    pred_run: Path,
    eval_output_dir: Path,
) -> Path | None:
    raw_llm_dir = pred_run / "raw" / "llm"
    if not raw_llm_dir.exists() or not raw_llm_dir.is_dir():
        return None

    run_dirs: list[Path] = [
        path for path in raw_llm_dir.iterdir() if path.is_dir()
    ]
    if not run_dirs:
        return None

    prompts_dir = eval_output_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_response_log_path = prompts_dir / "prompt_request_response_log.txt"
    full_prompt_log_path = prompts_dir / "full_prompt_log.jsonl"
    prompt_type_samples_path = prompts_dir / _PROMPT_TYPE_SAMPLES_MD_NAME

    pass_dir_map: dict[str, str] = {
        "pass1": "pass1_chunking",
        "pass2": "pass2_schemaorg",
        "pass3": "pass3_final",
        "pass4": "pass4_knowledge",
        "pass5": "pass5_tags",
    }
    pass_task_map: dict[str, str] = {
        "pass1": "task1",
        "pass2": "task2",
        "pass3": "task3",
        "pass4": "task4",
        "pass5": "task5",
    }
    pass_pipeline_map: dict[str, str] = {
        "pass1": "recipe.chunking.v1",
        "pass2": "recipe.schemaorg.compact.v1",
        "pass3": "recipe.final.compact.v1",
        "pass4": "recipe.knowledge.compact.v1",
        "pass5": "recipe.tags.v1",
    }
    pass_sort_order: dict[str, int] = {
        "pass1": 1,
        "pass2": 2,
        "pass3": 3,
        "pass4": 4,
        "pass5": 5,
    }
    pass_manifest_name_map: dict[str, str] = {
        "pass1": "llm_manifest.json",
        "pass2": "llm_manifest.json",
        "pass3": "llm_manifest.json",
        "pass4": "pass4_knowledge_manifest.json",
        "pass5": "pass5_tags_manifest.json",
    }

    def _safe_read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return f"<<unreadable file: {exc}>>"

    def _files_in_dir(path: Path | None) -> list[Path]:
        if path is None or not path.exists() or not path.is_dir():
            return []
        return sorted((child for child in path.iterdir() if child.is_file()), key=lambda p: p.name)

    text_attachment_suffixes = {
        ".json",
        ".jsonl",
        ".md",
        ".txt",
        ".yaml",
        ".yml",
        ".csv",
    }

    def _parse_json_text(raw_text: str) -> Any | None:
        text = str(raw_text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _timestamp_utc_for_path(path: Path | None) -> str | None:
        if path is None or not path.exists() or not path.is_file():
            return None
        try:
            timestamp = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
        except OSError:
            return None
        return timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")

    def _resolve_recipe_id(*, parsed_input: Any, parsed_output: Any, fallback_name: str) -> str | None:
        for payload in (parsed_input, parsed_output):
            if isinstance(payload, dict):
                candidate = str(payload.get("recipe_id") or "").strip()
                if candidate:
                    return candidate
        stem = Path(fallback_name).stem
        candidate_from_name = re.sub(r"^r\d+_", "", stem).strip()
        return candidate_from_name or None

    def _load_run_assets_for_process_run(
        *,
        process_run_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(process_run_payload, dict):
            return {}
        run_id = str(process_run_payload.get("run_id") or "").strip()
        if not run_id:
            return {}
        run_assets_dir = (REPO_ROOT / "var" / "run_assets" / run_id).resolve()
        if not run_assets_dir.exists() or not run_assets_dir.is_dir():
            return {"run_id": run_id}

        assets_manifest = _load_json_dict(run_assets_dir / "manifest.json") or {}
        prompt_template_text = _safe_read_text(run_assets_dir / "prompt.template.txt")
        output_schema_payload = _load_json_dict(run_assets_dir / "output.schema.json")
        effective_pipeline_payload = _load_json_dict(run_assets_dir / "effective_pipeline.json")
        pipeline_source_payload = _load_json_dict(run_assets_dir / "pipeline.source.json")
        source_metadata = assets_manifest.get("source_metadata")
        prompt_source_path = None
        output_schema_source_path = None
        if isinstance(source_metadata, dict):
            prompt_source_path = str(source_metadata.get("prompt_source_path") or "").strip() or None
            output_schema_source_path = (
                str(source_metadata.get("output_schema_source_path") or "").strip() or None
            )
        return {
            "run_id": run_id,
            "run_assets_dir": str(run_assets_dir),
            "prompt_template_text": prompt_template_text,
            "prompt_source_path": prompt_source_path,
            "output_schema_source_path": output_schema_source_path,
            "output_schema_payload": output_schema_payload,
            "effective_pipeline_payload": effective_pipeline_payload,
            "pipeline_source_payload": pipeline_source_payload,
        }

    def _resolve_process_run_payload(
        *,
        pass_name: str,
        manifest_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if pass_name in {"pass1", "pass2", "pass3"}:
            process_runs = manifest_payload.get("process_runs")
            if not isinstance(process_runs, dict):
                return None
            pass_payload = process_runs.get(pass_name)
            return pass_payload if isinstance(pass_payload, dict) else None

        if pass_name == "pass4":
            process_run = manifest_payload.get("process_run")
            if isinstance(process_run, dict):
                return process_run
            llm_report = manifest_payload.get("llm_report")
            if isinstance(llm_report, dict):
                report_process_run = llm_report.get("process_run")
                if isinstance(report_process_run, dict):
                    return report_process_run
            return None

        if pass_name == "pass5":
            llm_report = manifest_payload.get("llm_report")
            if isinstance(llm_report, dict):
                report_process_run = llm_report.get("process_run")
                if isinstance(report_process_run, dict):
                    return report_process_run
            process_run = manifest_payload.get("process_run")
            if isinstance(process_run, dict):
                return process_run
            return None

        return None

    def _resolve_manifest_pipeline_id(
        *,
        pass_name: str,
        manifest_payload: dict[str, Any],
    ) -> str | None:
        if pass_name in {"pass1", "pass2", "pass3"}:
            process_run = _resolve_process_run_payload(
                pass_name=pass_name,
                manifest_payload=manifest_payload,
            )
            if isinstance(process_run, dict):
                candidate = _clean_text(process_run.get("pipeline_id"))
                if candidate is not None:
                    return candidate
            return pass_pipeline_map.get(pass_name)
        if pass_name == "pass4":
            candidate = _clean_text(manifest_payload.get("pipeline_id"))
            if candidate is not None:
                return candidate
            llm_report = manifest_payload.get("llm_report")
            if isinstance(llm_report, dict):
                report_candidate = _clean_text(llm_report.get("pipeline_id"))
                if report_candidate is not None:
                    return report_candidate
            return pass_pipeline_map.get(pass_name)
        if pass_name == "pass5":
            llm_report = manifest_payload.get("llm_report")
            if isinstance(llm_report, dict):
                report_candidate = _clean_text(llm_report.get("pipeline_id"))
                if report_candidate is not None:
                    return report_candidate
            candidate = _clean_text(manifest_payload.get("pipeline_id"))
            if candidate is not None:
                return candidate
            return pass_pipeline_map.get(pass_name)
        return pass_pipeline_map.get(pass_name)

    def _resolve_pass_in_out_dirs(
        *,
        pass_name: str,
        manifest_payload: dict[str, Any],
        run_dir: Path,
        path_root: str,
    ) -> tuple[Path, Path]:
        paths_payload: dict[str, Any] = {}
        if pass_name == "pass5":
            llm_report = manifest_payload.get("llm_report")
            if isinstance(llm_report, dict):
                llm_paths = llm_report.get("paths")
                if isinstance(llm_paths, dict):
                    paths_payload = llm_paths
        if not paths_payload:
            raw_paths = manifest_payload.get("paths")
            if isinstance(raw_paths, dict):
                paths_payload = raw_paths

        pass_input_key_map = {
            "pass1": "pass1_in",
            "pass2": "pass2_in",
            "pass3": "pass3_in",
            "pass4": "pass4_in_dir",
            "pass5": "in_dir",
        }
        pass_output_key_map = {
            "pass1": "pass1_out",
            "pass2": "pass2_out",
            "pass3": "pass3_out",
            "pass4": "pass4_out_dir",
            "pass5": "out_dir",
        }

        input_key = pass_input_key_map.get(pass_name)
        output_key = pass_output_key_map.get(pass_name)
        pass_in = paths_payload.get(input_key) if input_key is not None else None
        pass_out = paths_payload.get(output_key) if output_key is not None else None

        in_dir = Path(str(pass_in)) if isinstance(pass_in, str) else None
        out_dir = Path(str(pass_out)) if isinstance(pass_out, str) else None
        if in_dir is None or not in_dir.exists():
            in_dir = run_dir / path_root / "in"
        if out_dir is None or not out_dir.exists():
            out_dir = run_dir / path_root / "out"
        return in_dir, out_dir

    def _render_prompt_text(
        *,
        template_text: str | None,
        input_text: str,
        input_file: Path,
    ) -> str:
        template = str(template_text or "")
        if not template.strip():
            return input_text
        rendered = template.replace("{{INPUT_TEXT}}", input_text)
        rendered = rendered.replace("{{ INPUT_TEXT }}", input_text)
        rendered = rendered.replace("{{INPUT_PATH}}", str(input_file))
        rendered = rendered.replace("{{ INPUT_PATH }}", str(input_file))
        return rendered

    def _collect_inserted_context_blocks(parsed_input: Any) -> list[dict[str, Any]]:
        if not isinstance(parsed_input, dict):
            return []
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, int | None]] = set()
        for key in ("blocks_before", "blocks_candidate", "blocks_after", "blocks"):
            blocks = parsed_input.get(key)
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                block_id = str(block.get("block_id") or "").strip() or None
                index_value = block.get("index")
                try:
                    index = int(index_value) if index_value is not None else None
                except (TypeError, ValueError):
                    index = None
                dedupe_key = (str(block_id or ""), index)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                rows.append(
                    {
                        "source_key": key,
                        "block_id": block_id,
                        "index": index,
                        "text": block.get("text"),
                    }
                )
        return rows

    def _clean_text(value: Any) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None

    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _coerce_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        cleaned = str(value or "").strip().lower()
        if not cleaned:
            return None
        if cleaned in {"1", "true", "yes", "y", "on"}:
            return True
        if cleaned in {"0", "false", "no", "n", "off"}:
            return False
        return None

    def _parse_json_string_list(value: Any) -> list[str]:
        text = str(value or "").strip()
        if not text:
            return []
        parsed = _parse_json_text(text)
        if not isinstance(parsed, list):
            return []
        rows: list[str] = []
        for item in parsed:
            cleaned = _clean_text(item)
            if cleaned is not None:
                rows.append(cleaned)
        return rows

    def _telemetry_row_sort_key(row: dict[str, Any]) -> tuple[int, int, str, str]:
        execution_attempt = _coerce_int(row.get("execution_attempt_index"))
        if execution_attempt is None:
            execution_attempt = _coerce_int(row.get("attempt_index")) or 0
        lease_claim_index = _coerce_int(row.get("lease_claim_index")) or 0
        finished_at = str(row.get("finished_at_utc") or row.get("logged_at_utc") or "")
        task_id = str(row.get("task_id") or "")
        return (execution_attempt, lease_claim_index, finished_at, task_id)

    def _iter_process_run_payloads(
        manifest_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        process_runs = manifest_payload.get("process_runs")
        if isinstance(process_runs, dict):
            for pass_payload in process_runs.values():
                if isinstance(pass_payload, dict):
                    rows.append(pass_payload)
        process_run = manifest_payload.get("process_run")
        if isinstance(process_run, dict):
            rows.append(process_run)
        llm_report = manifest_payload.get("llm_report")
        if isinstance(llm_report, dict):
            report_process_run = llm_report.get("process_run")
            if isinstance(report_process_run, dict):
                rows.append(report_process_run)
        return rows

    def _resolve_codex_exec_csv_paths(manifest_payload: dict[str, Any]) -> list[Path]:
        candidates: list[Path] = []
        for process_run_payload in _iter_process_run_payloads(manifest_payload):
            telemetry_payload = process_run_payload.get("telemetry")
            if not isinstance(telemetry_payload, dict):
                continue
            csv_path_raw = telemetry_payload.get("csv_path")
            if isinstance(csv_path_raw, str) and csv_path_raw.strip():
                candidates.append(Path(csv_path_raw.strip()))
        candidates.append((REPO_ROOT / "var" / "codex_exec_activity.csv").resolve())

        rows: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            if candidate.exists() and candidate.is_file():
                rows.append(candidate)
        return rows

    def _load_codex_exec_rows_for_manifest(
        manifest_payload: dict[str, Any],
    ) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, str]]:
        run_ids: set[str] = set()
        for process_run_payload in _iter_process_run_payloads(manifest_payload):
            run_id = _clean_text(process_run_payload.get("run_id"))
            if run_id:
                run_ids.add(run_id)
        if not run_ids:
            return {}, {}

        rows_by_run_and_input: dict[str, dict[str, dict[str, Any]]] = {
            run_id: {} for run_id in run_ids
        }
        csv_source_by_run_id: dict[str, str] = {}
        for csv_path in _resolve_codex_exec_csv_paths(manifest_payload):
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    for raw_row in reader:
                        run_id = _clean_text(raw_row.get("run_id"))
                        if run_id is None or run_id not in run_ids:
                            continue
                        input_path = _clean_text(raw_row.get("input_path"))
                        if input_path is None:
                            continue
                        input_name = Path(input_path).name
                        if not input_name:
                            continue
                        row = {str(key): value for key, value in raw_row.items()}
                        existing = rows_by_run_and_input[run_id].get(input_name)
                        if (
                            existing is None
                            or _telemetry_row_sort_key(row)
                            >= _telemetry_row_sort_key(existing)
                        ):
                            rows_by_run_and_input[run_id][input_name] = row
                            csv_source_by_run_id[run_id] = str(csv_path)
            except OSError:
                continue
        return rows_by_run_and_input, csv_source_by_run_id

    pred_run_manifest = _load_json_dict(pred_run / "run_manifest.json") or {}
    pred_run_source = (
        pred_run_manifest.get("source")
        if isinstance(pred_run_manifest.get("source"), dict)
        else {}
    )
    source_file = None
    if isinstance(pred_run_source, dict):
        source_file_raw = pred_run_source.get("path")
        if isinstance(source_file_raw, str) and source_file_raw.strip():
            source_file = source_file_raw.strip()

    benchmark_run_id = eval_output_dir.name
    full_prompt_log_rows = 0
    full_prompt_log_handle = full_prompt_log_path.open("w", encoding="utf-8")

    def _collect_prompt_attachments(
        payload: Any,
        *,
        prompt_file: Path,
    ) -> list[Path]:
        found: list[Path] = []
        seen: set[Path] = set()

        def _walk(node: Any, current_key: str | None = None) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    _walk(value, str(key))
                return
            if isinstance(node, list):
                for value in node:
                    _walk(value, current_key)
                return
            if not isinstance(node, str):
                return
            key = (current_key or "").strip().lower()
            if "path" not in key and "file" not in key:
                return
            raw_value = node.strip()
            if not raw_value or "\n" in raw_value or re.match(r"^[a-z]+://", raw_value):
                return
            candidate = Path(raw_value)
            candidates: list[Path] = []
            if candidate.is_absolute():
                candidates.append(candidate)
            else:
                candidates.append((prompt_file.parent / candidate).resolve())
                candidates.append((pred_run / candidate).resolve())
            for resolved in candidates:
                if (
                    resolved.exists()
                    and resolved.is_file()
                    and resolved.suffix.lower() in text_attachment_suffixes
                ):
                    if resolved not in seen:
                        seen.add(resolved)
                        found.append(resolved)
                    break

        _walk(payload)
        return found

    def _resolve_telemetry_trace_path(
        *,
        telemetry_trace_path: str | None,
        output_file: Path | None,
        out_dir: Path,
        task_id: str | None,
    ) -> Path | None:
        candidates: list[Path] = []
        trace_name: str | None = None
        if telemetry_trace_path is not None:
            telemetry_candidate = Path(telemetry_trace_path).expanduser()
            if not telemetry_candidate.is_absolute():
                telemetry_candidate = (REPO_ROOT / telemetry_candidate).resolve()
            trace_name = telemetry_candidate.name
            candidates.append(telemetry_candidate)

        search_roots: list[Path] = [out_dir]
        if output_file is not None:
            search_roots.insert(0, output_file.parent)

        for root in search_roots:
            if task_id is not None:
                task_dir = root / ".codex-farm-traces" / task_id
                if trace_name:
                    candidates.append(task_dir / trace_name)
                if task_dir.exists() and task_dir.is_dir():
                    candidates.extend(sorted(task_dir.glob("*.trace.json")))
            if trace_name:
                candidates.append(root / ".codex-farm-traces" / trace_name)

        for candidate in candidates:
            resolved = candidate.resolve(strict=False)
            if resolved.exists() and resolved.is_file():
                return resolved
        return None

    def _load_thinking_trace_payload(*, trace_path: Path | None) -> dict[str, Any] | None:
        if trace_path is None or not trace_path.exists() or not trace_path.is_file():
            return None
        parsed = _parse_json_text(_safe_read_text(trace_path))
        if not isinstance(parsed, dict):
            return None
        reasoning_events = parsed.get("reasoning_events")
        normalized_reasoning_events = reasoning_events if isinstance(reasoning_events, list) else []
        action_types = parsed.get("action_event_types")
        reasoning_types = parsed.get("reasoning_event_types")
        return {
            "path": str(trace_path),
            "captured_at_utc": _clean_text(parsed.get("captured_at_utc")),
            "run_id": _clean_text(parsed.get("run_id")),
            "pipeline_id": _clean_text(parsed.get("pipeline_id")),
            "task_id": _clean_text(parsed.get("task_id")),
            "model": _clean_text(parsed.get("model")),
            "reasoning_effort": _clean_text(parsed.get("reasoning_effort")),
            "event_count": _coerce_int(parsed.get("event_count")),
            "action_event_count": _coerce_int(parsed.get("action_event_count")),
            "action_event_types": (
                [str(item) for item in action_types if isinstance(item, str)]
                if isinstance(action_types, list)
                else []
            ),
            "reasoning_event_count": _coerce_int(parsed.get("reasoning_event_count")),
            "reasoning_event_types": (
                [str(item) for item in reasoning_types if isinstance(item, str)]
                if isinstance(reasoning_types, list)
                else []
            ),
            "reasoning_events": normalized_reasoning_events,
            "available": bool(
                _coerce_int(parsed.get("reasoning_event_count")) or normalized_reasoning_events
            ),
        }

    lines: list[str] = []
    category_lines: dict[str, list[str]] = {pass_name: [] for pass_name in pass_dir_map}
    category_has_payload: dict[str, bool] = {pass_name: False for pass_name in pass_dir_map}
    category_stage_metadata: dict[str, dict[str, Any]] = {}
    try:
        for run_dir in sorted(run_dirs, key=lambda value: value.name):
            manifest_payload_by_name: dict[str, dict[str, Any]] = {}
            manifest_path_by_name: dict[str, Path] = {}
            for manifest_name in sorted(set(pass_manifest_name_map.values())):
                manifest_path = run_dir / manifest_name
                payload = _load_json_dict(manifest_path) or {}
                if not payload:
                    continue
                manifest_payload_by_name[manifest_name] = payload
                manifest_path_by_name[manifest_name] = manifest_path
            if not manifest_payload_by_name:
                lines.append(f"=== SKIP: missing pass manifests in {run_dir} ===")
                continue

            primary_manifest = manifest_payload_by_name.get("llm_manifest.json", {})
            lines.append(f"=== CODexFarm run: {run_dir.name} ===")
            if manifest_path_by_name:
                lines.append("manifests:")
                for manifest_name in sorted(manifest_path_by_name):
                    lines.append(f"- {manifest_path_by_name[manifest_name]}")
            llm_enabled = primary_manifest.get("enabled")
            if llm_enabled is not None:
                lines.append(f"enabled: {llm_enabled}")
            codex_pipeline = primary_manifest.get("pipeline")
            if isinstance(codex_pipeline, str):
                lines.append(f"pipeline: {codex_pipeline}")
            codex_model = primary_manifest.get("codex_farm_model")
            if isinstance(codex_model, str):
                lines.append(f"codex_farm_model: {codex_model}")
            codex_reasoning_effort = str(
                primary_manifest.get("codex_farm_reasoning_effort") or ""
            ).strip() or None
            lines.append("")

            telemetry_rows_by_manifest_name: dict[
                str, dict[str, dict[str, dict[str, Any]]]
            ] = {}
            telemetry_csv_by_manifest_name: dict[str, dict[str, str]] = {}
            for manifest_name, manifest_payload in manifest_payload_by_name.items():
                rows_by_run_id, csv_by_run_id = _load_codex_exec_rows_for_manifest(
                    manifest_payload
                )
                telemetry_rows_by_manifest_name[manifest_name] = rows_by_run_id
                telemetry_csv_by_manifest_name[manifest_name] = csv_by_run_id

            if any(
                isinstance(
                    _resolve_process_run_payload(
                        pass_name=pass_name,
                        manifest_payload=manifest_payload_by_name[
                            pass_manifest_name_map[pass_name]
                        ],
                    ),
                    dict,
                )
                for pass_name in pass_dir_map
                if pass_manifest_name_map[pass_name] in manifest_payload_by_name
            ):
                lines.append("--- PROCESS RUN PAYLOAD SNIPPETS ---")
                for pass_name in sorted(
                    pass_dir_map,
                    key=lambda value: pass_sort_order.get(value, 999),
                ):
                    manifest_name = pass_manifest_name_map.get(pass_name)
                    if manifest_name is None:
                        continue
                    manifest_payload = manifest_payload_by_name.get(manifest_name)
                    if not isinstance(manifest_payload, dict):
                        continue
                    run_payload = _resolve_process_run_payload(
                        pass_name=pass_name,
                        manifest_payload=manifest_payload,
                    )
                    if not isinstance(run_payload, dict):
                        continue
                    lines.append(
                        f"--- process_run[{pass_name}] ({manifest_name}) ---"
                    )
                    try:
                        lines.append(json.dumps(run_payload, indent=2, sort_keys=True))
                    except Exception:
                        lines.append(str(run_payload))
                lines.append("")

            for pass_name, path_root in pass_dir_map.items():
                manifest_name = pass_manifest_name_map.get(pass_name)
                if manifest_name is None:
                    continue
                manifest_payload = manifest_payload_by_name.get(manifest_name)
                if not isinstance(manifest_payload, dict):
                    continue
                manifest_path = manifest_path_by_name.get(manifest_name)
                task_name = pass_task_map.get(pass_name, pass_name)
                process_run_payload = _resolve_process_run_payload(
                    pass_name=pass_name,
                    manifest_payload=manifest_payload,
                )
                pass_assets = _load_run_assets_for_process_run(
                    process_run_payload=process_run_payload,
                )
                process_run_id = _clean_text(pass_assets.get("run_id"))
                telemetry_rows_by_run_id = telemetry_rows_by_manifest_name.get(
                    manifest_name, {}
                )
                telemetry_csv_by_run_id = telemetry_csv_by_manifest_name.get(
                    manifest_name, {}
                )
                pass_telemetry_rows = (
                    telemetry_rows_by_run_id.get(process_run_id, {})
                    if process_run_id is not None
                    else {}
                )
                in_dir, out_dir = _resolve_pass_in_out_dirs(
                    pass_name=pass_name,
                    manifest_payload=manifest_payload,
                    run_dir=run_dir,
                    path_root=path_root,
                )
                pipeline_id = _resolve_manifest_pipeline_id(
                    pass_name=pass_name,
                    manifest_payload=manifest_payload,
                )
                stage_metadata = _build_prompt_stage_metadata(
                    pass_name=pass_name,
                    path_root=path_root,
                    pipeline_id=pipeline_id,
                )
                category_stage_metadata[pass_name] = dict(stage_metadata)

                category = category_lines[pass_name]
                category.append(
                    "=== CATEGORY "
                    f"{task_name} ({stage_metadata['heading_key']} / {stage_metadata['label']}) "
                    f"| legacy_slot: {pass_name} | raw_dir: {path_root} | run: {run_dir.name} ==="
                )
                if manifest_path is not None:
                    category.append(f"manifest: {manifest_path}")
                if pipeline_id is not None:
                    category.append(f"pipeline_id: {pipeline_id}")
                category.append("")

                input_files = _files_in_dir(in_dir)
                lines.append(f"--- {pass_name.upper()} INPUT FILES ---")
                lines.append(f"source_dir: {in_dir}")
                category.append(f"--- {task_name.upper()} PROMPT INPUT FILES ---")
                category.append(f"source_dir: {in_dir}")
                for prompt_file in input_files:
                    category_has_payload[pass_name] = True
                    lines.append(f"INPUT {pass_name} => {prompt_file.name}")
                    lines.append("-" * 80)
                    prompt_text = _safe_read_text(prompt_file)
                    lines.append(prompt_text)
                    lines.append("-" * 80)
                    lines.append("")

                    category.append(f"INPUT {task_name} => {prompt_file.name}")
                    category.append("-" * 80)
                    category.append(prompt_text)
                    category.append("-" * 80)
                    category.append("")

                    payload: Any = _parse_json_text(prompt_text)
                    attachment_paths = _collect_prompt_attachments(
                        payload,
                        prompt_file=prompt_file,
                    )
                    if attachment_paths:
                        category.append(
                            f"--- ATTACHMENT FILES REFERENCED BY {prompt_file.name} ---"
                        )
                        for attachment_path in attachment_paths:
                            category.append(f"ATTACHMENT {task_name} => {attachment_path}")
                            category.append("-" * 80)
                            category.append(_safe_read_text(attachment_path))
                            category.append("-" * 80)
                            category.append("")

                output_files = _files_in_dir(out_dir)
                lines.append(f"--- {pass_name.upper()} RESPONSE FILES ---")
                lines.append(f"source_dir: {out_dir}")
                category.append(f"--- {task_name.upper()} PROMPT RESPONSE FILES ---")
                category.append(f"source_dir: {out_dir}")
                for response_file in output_files:
                    category_has_payload[pass_name] = True
                    lines.append(f"OUTPUT {pass_name} => {response_file.name}")
                    lines.append("-" * 80)
                    response_text = _safe_read_text(response_file)
                    lines.append(response_text)
                    lines.append("-" * 80)
                    lines.append("")
                    category.append(f"OUTPUT {task_name} => {response_file.name}")
                    category.append("-" * 80)
                    category.append(response_text)
                    category.append("-" * 80)
                    category.append("")
                lines.append("")
                category.append("")

                file_names = sorted({file.name for file in input_files} | {file.name for file in output_files})
                output_by_name = {file.name: file for file in output_files}
                input_by_name = {file.name: file for file in input_files}
                for file_name in file_names:
                    input_file = input_by_name.get(file_name)
                    output_file = output_by_name.get(file_name)
                    input_text = _safe_read_text(input_file) if input_file is not None else ""
                    output_text = _safe_read_text(output_file) if output_file is not None else ""
                    telemetry_row = pass_telemetry_rows.get(file_name)
                    if telemetry_row is None and input_file is not None:
                        telemetry_row = pass_telemetry_rows.get(input_file.name)
                    if telemetry_row is None and output_file is not None:
                        telemetry_row = pass_telemetry_rows.get(output_file.name)

                    telemetry_prompt_text = (
                        str(telemetry_row.get("prompt_text"))
                        if isinstance(telemetry_row, dict)
                        and telemetry_row.get("prompt_text") is not None
                        else ""
                    )
                    telemetry_timestamp_utc = None
                    telemetry_output_path = None
                    if isinstance(telemetry_row, dict):
                        telemetry_timestamp_utc = (
                            _clean_text(telemetry_row.get("finished_at_utc"))
                            or _clean_text(telemetry_row.get("logged_at_utc"))
                        )
                        output_path_text = _clean_text(telemetry_row.get("output_path"))
                        if output_path_text is not None:
                            telemetry_output_path = Path(output_path_text)
                    if not output_text and telemetry_output_path is not None:
                        output_text = _safe_read_text(telemetry_output_path)

                    parsed_input = _parse_json_text(input_text)
                    parsed_output = _parse_json_text(output_text)

                    timestamp_utc = (
                        telemetry_timestamp_utc
                        or _timestamp_utc_for_path(output_file)
                        or _timestamp_utc_for_path(input_file)
                    )
                    call_stem = (
                        input_file.stem
                        if input_file is not None
                        else (output_file.stem if output_file is not None else Path(file_name).stem)
                    )
                    recipe_id = _resolve_recipe_id(
                        parsed_input=parsed_input,
                        parsed_output=parsed_output,
                        fallback_name=file_name,
                    )

                    rendered_prompt_text = _render_prompt_text(
                        template_text=pass_assets.get("prompt_template_text")
                        if isinstance(pass_assets, dict)
                        else None,
                        input_text=input_text,
                        input_file=(input_file or (in_dir / file_name)),
                    )
                    request_payload_source = "reconstructed_from_prompt_template"
                    if telemetry_prompt_text:
                        rendered_prompt_text = telemetry_prompt_text
                        request_payload_source = "telemetry_csv"
                    request_messages = [
                        {
                            "role": "user",
                            "content": rendered_prompt_text,
                        }
                    ]
                    response_format_payload: dict[str, Any] | None = None
                    output_schema_payload = pass_assets.get("output_schema_payload")
                    if isinstance(output_schema_payload, dict):
                        response_format_payload = {
                            "type": "json_schema",
                            "json_schema": output_schema_payload,
                        }

                    effective_pipeline_payload = pass_assets.get("effective_pipeline_payload")
                    model_value = None
                    if isinstance(effective_pipeline_payload, dict):
                        model_candidate = str(
                            effective_pipeline_payload.get("codex_model") or ""
                        ).strip()
                        if model_candidate:
                            model_value = model_candidate
                    if model_value is None and isinstance(codex_model, str):
                        model_value = codex_model
                    telemetry_model = (
                        _clean_text(telemetry_row.get("model"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    if telemetry_model is not None:
                        model_value = telemetry_model

                    effective_reasoning_effort = (
                        _clean_text(effective_pipeline_payload.get("codex_reasoning_effort"))
                        if isinstance(effective_pipeline_payload, dict)
                        else None
                    )
                    telemetry_reasoning_effort = (
                        _clean_text(telemetry_row.get("reasoning_effort"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    reasoning_effort_value = (
                        telemetry_reasoning_effort
                        or codex_reasoning_effort
                        or effective_reasoning_effort
                    )

                    telemetry_sandbox = (
                        _clean_text(telemetry_row.get("sandbox"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    fallback_sandbox = (
                        _clean_text(effective_pipeline_payload.get("codex_sandbox"))
                        if isinstance(effective_pipeline_payload, dict)
                        else None
                    )
                    sandbox_value = telemetry_sandbox or fallback_sandbox

                    telemetry_ask_for_approval = (
                        _coerce_bool(telemetry_row.get("ask_for_approval"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    fallback_ask_for_approval = (
                        _coerce_bool(effective_pipeline_payload.get("codex_ask_for_approval"))
                        if isinstance(effective_pipeline_payload, dict)
                        else None
                    )
                    ask_for_approval_value = (
                        telemetry_ask_for_approval
                        if telemetry_ask_for_approval is not None
                        else fallback_ask_for_approval
                    )

                    telemetry_web_search = (
                        _coerce_bool(telemetry_row.get("web_search"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    fallback_web_search = (
                        _coerce_bool(effective_pipeline_payload.get("codex_web_search"))
                        if isinstance(effective_pipeline_payload, dict)
                        else None
                    )
                    web_search_value = (
                        telemetry_web_search
                        if telemetry_web_search is not None
                        else fallback_web_search
                    )

                    telemetry_output_schema_path = (
                        _clean_text(telemetry_row.get("output_schema_path"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    telemetry_task_id = (
                        _clean_text(telemetry_row.get("task_id"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    telemetry_trace_path = (
                        _clean_text(telemetry_row.get("trace_path"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    telemetry_trace_action_count = (
                        _coerce_int(telemetry_row.get("trace_action_count"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    telemetry_trace_action_types = (
                        _parse_json_string_list(telemetry_row.get("trace_action_types_json"))
                        if isinstance(telemetry_row, dict)
                        else []
                    )
                    telemetry_trace_reasoning_count = (
                        _coerce_int(telemetry_row.get("trace_reasoning_count"))
                        if isinstance(telemetry_row, dict)
                        else None
                    )
                    telemetry_trace_reasoning_types = (
                        _parse_json_string_list(telemetry_row.get("trace_reasoning_types_json"))
                        if isinstance(telemetry_row, dict)
                        else []
                    )
                    resolved_trace_path = _resolve_telemetry_trace_path(
                        telemetry_trace_path=telemetry_trace_path,
                        output_file=output_file,
                        out_dir=out_dir,
                        task_id=telemetry_task_id,
                    )
                    thinking_trace_payload = _load_thinking_trace_payload(
                        trace_path=resolved_trace_path
                    )
                    if isinstance(thinking_trace_payload, dict):
                        if telemetry_trace_action_count is None:
                            telemetry_trace_action_count = thinking_trace_payload.get(
                                "action_event_count"
                            )
                        if not telemetry_trace_action_types:
                            telemetry_trace_action_types = list(
                                thinking_trace_payload.get("action_event_types") or []
                            )
                        if telemetry_trace_reasoning_count is None:
                            telemetry_trace_reasoning_count = thinking_trace_payload.get(
                                "reasoning_event_count"
                            )
                        if not telemetry_trace_reasoning_types:
                            telemetry_trace_reasoning_types = list(
                                thinking_trace_payload.get("reasoning_event_types") or []
                            )

                    request_payload: dict[str, Any] = {
                        "messages": request_messages,
                        "tools": [],
                        "response_format": response_format_payload,
                        "model": model_value,
                        "reasoning_effort": reasoning_effort_value,
                        "temperature": None,
                        "top_p": None,
                        "max_output_tokens": None,
                        "seed": None,
                        "pipeline_id": pipeline_id,
                        "sandbox": sandbox_value,
                        "ask_for_approval": ask_for_approval_value,
                        "web_search": web_search_value,
                        "output_schema_path": telemetry_output_schema_path,
                    }

                    template_vars: dict[str, Any] = {
                        "INPUT_PATH": str(input_file) if input_file is not None else None,
                        "INPUT_TEXT": input_text,
                    }
                    prompt_templates = {
                        "prompt_template_text": pass_assets.get("prompt_template_text"),
                        "prompt_template_path": pass_assets.get("prompt_source_path"),
                    }

                    request_telemetry: dict[str, Any] | None = None
                    if isinstance(telemetry_row, dict):
                        usage_payload = _parse_json_text(
                            str(telemetry_row.get("usage_json") or "")
                        )
                        request_telemetry = {
                            "csv_path": (
                                telemetry_csv_by_run_id.get(process_run_id)
                                if process_run_id is not None
                                else None
                            ),
                            "task_id": telemetry_task_id,
                            "worker_id": _clean_text(telemetry_row.get("worker_id")),
                            "thread_id": _clean_text(telemetry_row.get("thread_id")),
                            "status": _clean_text(telemetry_row.get("status")),
                            "duration_ms": _coerce_int(telemetry_row.get("duration_ms")),
                            "attempt_index": _coerce_int(telemetry_row.get("attempt_index")),
                            "execution_attempt_index": _coerce_int(
                                telemetry_row.get("execution_attempt_index")
                            ),
                            "lease_claim_index": _coerce_int(
                                telemetry_row.get("lease_claim_index")
                            ),
                            "input_path": _clean_text(telemetry_row.get("input_path")),
                            "output_path": _clean_text(telemetry_row.get("output_path")),
                            "prompt_chars": _coerce_int(telemetry_row.get("prompt_chars")),
                            "prompt_sha256": _clean_text(telemetry_row.get("prompt_sha256")),
                            "output_bytes": _coerce_int(telemetry_row.get("output_bytes")),
                            "output_sha256": _clean_text(telemetry_row.get("output_sha256")),
                            "output_payload_present": _coerce_bool(
                                telemetry_row.get("output_payload_present")
                            ),
                            "output_preview_chars": _coerce_int(
                                telemetry_row.get("output_preview_chars")
                            ),
                            "output_preview_truncated": _coerce_bool(
                                telemetry_row.get("output_preview_truncated")
                            ),
                            "output_preview": telemetry_row.get("output_preview"),
                            "tokens_input": _coerce_int(telemetry_row.get("tokens_input")),
                            "tokens_cached_input": _coerce_int(
                                telemetry_row.get("tokens_cached_input")
                            ),
                            "tokens_output": _coerce_int(telemetry_row.get("tokens_output")),
                            "tokens_reasoning": _coerce_int(
                                telemetry_row.get("tokens_reasoning")
                            ),
                            "tokens_total": _coerce_int(telemetry_row.get("tokens_total")),
                            "usage_json": usage_payload,
                            "model": telemetry_model,
                            "reasoning_effort": telemetry_reasoning_effort,
                            "sandbox": telemetry_sandbox,
                            "ask_for_approval": telemetry_ask_for_approval,
                            "web_search": telemetry_web_search,
                            "output_schema_path": telemetry_output_schema_path,
                            "trace_path": telemetry_trace_path,
                            "trace_resolved_path": (
                                str(resolved_trace_path)
                                if resolved_trace_path is not None
                                else None
                            ),
                            "trace_action_count": telemetry_trace_action_count,
                            "trace_action_types": telemetry_trace_action_types,
                            "trace_reasoning_count": telemetry_trace_reasoning_count,
                            "trace_reasoning_types": telemetry_trace_reasoning_types,
                        }

                    row_payload = {
                        "run_id": benchmark_run_id,
                        "pass": pass_name,
                        "legacy_pass": pass_name,
                        "call_id": call_stem,
                        "timestamp_utc": timestamp_utc,
                        "recipe_id": recipe_id,
                        "source_file": source_file,
                        "pipeline_id": pipeline_id,
                        "stage_key": stage_metadata["stage_key"],
                        "stage_heading_key": stage_metadata["heading_key"],
                        "stage_label": stage_metadata["label"],
                        "stage_artifact_stem": stage_metadata["artifact_stem"],
                        "stage_dir_name": path_root,
                        "stage_slot_index": stage_metadata["slot_index"],
                        "stage_matches_legacy": stage_metadata["matches_legacy"],
                        "process_run_id": process_run_id,
                        "model": model_value,
                        "request_payload_source": request_payload_source,
                        "request_messages": request_messages,
                        "system_prompt": None,
                        "developer_prompt": None,
                        "user_prompt": rendered_prompt_text,
                        "rendered_prompt_text": rendered_prompt_text,
                        "rendered_messages": request_messages,
                        "prompt_templates": prompt_templates,
                        "template_vars": template_vars,
                        "inserted_context_blocks": _collect_inserted_context_blocks(parsed_input),
                        "request": request_payload,
                        "request_input_payload": parsed_input,
                        "tools": [],
                        "response_format": response_format_payload,
                        "decoding_params": {
                            "temperature": None,
                            "top_p": None,
                            "max_output_tokens": None,
                            "seed": None,
                            "reasoning_effort": reasoning_effort_value,
                        },
                        "raw_response": {
                            "output_text": output_text,
                            "output_file": (
                                str(output_file)
                                if output_file is not None
                                else (
                                    str(telemetry_output_path)
                                    if telemetry_output_path is not None
                                    else None
                                )
                            ),
                        },
                        "parsed_response": parsed_output,
                        "request_input_file": str(input_file) if input_file is not None else None,
                        "request_telemetry": request_telemetry,
                        "thinking_trace": thinking_trace_payload,
                    }
                    full_prompt_log_handle.write(
                        json.dumps(row_payload, ensure_ascii=False) + "\n"
                    )
                    full_prompt_log_rows += 1
    finally:
        full_prompt_log_handle.close()

    if not lines:
        full_prompt_log_path.unlink(missing_ok=True)
        prompt_type_samples_path.unlink(missing_ok=True)
        return None

    prompt_response_log_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    category_manifest_lines: list[str] = []
    for pass_name, path_root in pass_dir_map.items():
        if not category_has_payload.get(pass_name):
            continue
        task_name = pass_task_map.get(pass_name, pass_name)
        stage_metadata = category_stage_metadata.get(pass_name) or _build_prompt_stage_metadata(
            pass_name=pass_name,
            path_root=path_root,
            pipeline_id=None,
        )
        category_path = prompts_dir / (
            f"prompt_{task_name}_{stage_metadata['artifact_stem']}.txt"
        )
        category_path.write_text(
            "\n".join(category_lines[pass_name]) + "\n",
            encoding="utf-8",
        )
        category_manifest_lines.append(str(category_path))
    if category_manifest_lines:
        (prompts_dir / "prompt_category_logs_manifest.txt").write_text(
            "\n".join(category_manifest_lines) + "\n",
            encoding="utf-8",
        )

    if full_prompt_log_rows <= 0:
        full_prompt_log_path.unlink(missing_ok=True)
        prompt_type_samples_path.unlink(missing_ok=True)
    else:
        _build_codex_farm_prompt_type_samples_markdown(
            full_prompt_log_path=full_prompt_log_path,
            output_path=prompt_type_samples_path,
            examples_per_pass=3,
        )

    return prompt_response_log_path
