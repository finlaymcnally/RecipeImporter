from __future__ import annotations
import csv
import datetime as dt
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, cast
from cookimport.core.slug import slugify_name
from cookimport.runs import (
    KNOWLEDGE_MANIFEST_FILE_NAME,
    RECIPE_MANIFEST_FILE_NAME,
    stage_label,
    stage_artifact_stem,
)
from cookimport.runs.stage_names import canonical_stage_key
PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION = "prompt_run_descriptor.v1"
PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION = "prompt_stage_descriptor.v1"
PROMPT_CALL_RECORD_SCHEMA_VERSION = "prompt_call_record.v1"
PROMPT_LOG_SUMMARY_SCHEMA_VERSION = "prompt_log_summary.v1"
PROMPT_ACTIVITY_TRACE_SCHEMA_VERSION = "prompt_activity_trace.v1"
PROMPT_ACTIVITY_TRACE_SUMMARY_SCHEMA_VERSION = "prompt_activity_trace_summary.v1"
PROMPT_LOG_SUMMARY_JSON_NAME = "prompt_log_summary.json"
PROMPT_TYPE_SAMPLES_MD_NAME = "prompt_type_samples_from_full_prompt_log.md"
ACTIVITY_TRACES_DIR_NAME = "activity_traces"
ACTIVITY_TRACE_SUMMARY_JSONL_NAME = "activity_trace_summary.jsonl"
ACTIVITY_TRACE_SUMMARY_MD_NAME = "activity_trace_summary.md"
_CODEXFARM_STAGE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "stage_key": "recipe_refine",
        "stage_order": 1,
        "stage_label": stage_label("recipe_refine"),
        "stage_artifact_stem": stage_artifact_stem("recipe_refine"),
        "default_pipeline_id": "recipe.correction.compact.v1",
        "manifest_name": RECIPE_MANIFEST_FILE_NAME,
    },
    {
        "stage_key": "nonrecipe_finalize",
        "stage_order": 4,
        "stage_label": stage_label("nonrecipe_finalize"),
        "stage_artifact_stem": stage_artifact_stem("nonrecipe_finalize"),
        "default_pipeline_id": "recipe.knowledge.packet.v1",
        "manifest_name": KNOWLEDGE_MANIFEST_FILE_NAME,
    },
)
_CODEXFARM_STAGE_SPEC_BY_KEY: dict[str, dict[str, Any]] = {
    str(spec["stage_key"]): spec for spec in _CODEXFARM_STAGE_SPECS
}
_PROMPT_STAGE_LABELS_BY_KEY = {
    **{
        str(spec["stage_key"]): str(spec["stage_label"])
        for spec in _CODEXFARM_STAGE_SPECS
    },
    "recipe_correction": stage_label("recipe_refine"),
    "knowledge": stage_label("nonrecipe_finalize"),
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
_ACTIVITY_TRACE_MAX_ENTRIES = 25
_ACTIVITY_TRACE_SUMMARY_ENTRY_LIMIT = 3
__all__ = [
    "ACTIVITY_TRACES_DIR_NAME",
    "ACTIVITY_TRACE_SUMMARY_JSONL_NAME",
    "ACTIVITY_TRACE_SUMMARY_MD_NAME",
    "PROMPT_CALL_RECORD_SCHEMA_VERSION",
    "PROMPT_ACTIVITY_TRACE_SCHEMA_VERSION",
    "PROMPT_ACTIVITY_TRACE_SUMMARY_SCHEMA_VERSION",
    "PROMPT_LOG_SUMMARY_JSON_NAME",
    "PROMPT_LOG_SUMMARY_SCHEMA_VERSION",
    "PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION",
    "PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION",
    "PROMPT_TYPE_SAMPLES_MD_NAME",
    "build_codex_farm_activity_trace_summaries",
    "PromptCallRecord",
    "PromptRunDescriptorDiscoverer",
    "PromptRunDescriptor",
    "PromptStageDescriptor",
    "build_codex_farm_prompt_response_log",
    "build_prompt_response_log",
    "build_codex_farm_prompt_type_samples_markdown",
    "discover_prompt_run_descriptors",
    "discover_codex_exec_prompt_run_descriptors",
    "render_prompt_artifacts_from_descriptors",
    "summarize_prompt_log",
    "write_prompt_log_summary",
]

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
    stage_order: int
    stage_dir_name: str
    stage_key: str
    stage_heading_key: str
    stage_label: str
    stage_artifact_stem: str
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
class PromptRunDescriptorDiscoverer(Protocol):
    def __call__(self, *, pred_run: Path) -> Sequence[PromptRunDescriptor]:
        ...
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
def _load_json_value(path: Path) -> Any | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"<<unreadable file: {exc}>>"
def _resolve_artifact_path(base_dir: Path, value: Any) -> Path | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    path = Path(cleaned).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve(strict=False)
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
def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
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
def _fallback_prompt_stage_key(*, stage_key: str, path_root: str | None) -> str:
    root_slug = slugify_name(str(path_root or "").strip()) if path_root else ""
    if root_slug.startswith(f"{stage_key}_"):
        trimmed = root_slug[len(stage_key) + 1 :].strip("_")
        if trimmed:
            return trimmed
    return root_slug or stage_key or "stage"
def _prompt_stage_label_from_key(stage_key: str) -> str:
    normalized = slugify_name(stage_key)
    mapped = _PROMPT_STAGE_LABELS_BY_KEY.get(normalized)
    if mapped is not None:
        return mapped
    return normalized.replace("_", " ").strip().title() or "Prompt Stage"
def _build_prompt_stage_metadata(
    *,
    stage_key: str,
    pipeline_id: str | None,
) -> dict[str, Any]:
    normalized_stage_key = slugify_name(stage_key)
    stage_spec = _CODEXFARM_STAGE_SPEC_BY_KEY.get(normalized_stage_key, {})
    stage_order = int(stage_spec.get("stage_order") or 999)
    canonical_stage_key = (
        _clean_prompt_stage_text(stage_spec.get("stage_key"))
        or normalized_stage_key
        or _derive_prompt_stage_key_from_pipeline_id(pipeline_id)
        or _fallback_prompt_stage_key(stage_key=normalized_stage_key, path_root=None)
    )
    default_label = _clean_prompt_stage_text(stage_spec.get("stage_label"))
    default_artifact_stem = _clean_prompt_stage_text(stage_spec.get("stage_artifact_stem"))
    return {
        "stage_order": stage_order,
        "pipeline_id": _clean_prompt_stage_text(pipeline_id)
        or _clean_prompt_stage_text(stage_spec.get("default_pipeline_id")),
        "stage_key": canonical_stage_key,
        "heading_key": canonical_stage_key,
        "label": (
            default_label
            if default_label is not None
            else _prompt_stage_label_from_key(canonical_stage_key)
        ),
        "artifact_stem": slugify_name(
            default_artifact_stem or canonical_stage_key or f"stage_{stage_order}"
        ),
    }
def _prompt_stage_metadata_from_row(row: dict[str, Any]) -> dict[str, Any]:
    stage_key = (
        _clean_prompt_stage_text(row.get("stage_key"))
        or _clean_prompt_stage_text(row.get("stage_heading_key"))
        or _clean_prompt_stage_text(row.get("stage_artifact_stem"))
        or "stage"
    )
    metadata = _build_prompt_stage_metadata(
        stage_key=stage_key,
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
    try:
        stage_order = int(row.get("stage_order"))
    except (TypeError, ValueError):
        stage_order = None
    if stage_order is not None:
        metadata["stage_order"] = stage_order
    return metadata
def _resolve_process_run_payload_for_stage(
    *,
    stage_key: str,
    manifest_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if stage_key == "recipe_refine":
        process_runs = manifest_payload.get("process_runs")
        if not isinstance(process_runs, dict):
            return None
        pass_payload = process_runs.get("recipe_correction")
        return pass_payload if isinstance(pass_payload, dict) else None
    if stage_key == "nonrecipe_finalize":
        process_run = manifest_payload.get("process_run")
        if isinstance(process_run, dict):
            return process_run
        llm_report = manifest_payload.get("llm_report")
        if isinstance(llm_report, dict):
            report_process_run = llm_report.get("process_run")
            if isinstance(report_process_run, dict):
                return report_process_run
        return None
    return None
def _resolve_manifest_pipeline_id_for_stage(
    *,
    stage_key: str,
    manifest_payload: dict[str, Any],
) -> str | None:
    stage_spec = _CODEXFARM_STAGE_SPEC_BY_KEY.get(stage_key, {})
    default_pipeline_id = _clean_prompt_stage_text(stage_spec.get("default_pipeline_id"))
    if stage_key == "recipe_refine":
        process_run = _resolve_process_run_payload_for_stage(
            stage_key=stage_key,
            manifest_payload=manifest_payload,
        )
        if isinstance(process_run, dict):
            candidate = _clean_text(process_run.get("pipeline_id"))
            if candidate is not None:
                return candidate
        pipelines = manifest_payload.get("pipelines")
        if isinstance(pipelines, dict):
            candidate = _clean_text(pipelines.get("recipe_correction"))
            if candidate is not None:
                return candidate
        return default_pipeline_id
    if stage_key == "nonrecipe_finalize":
        candidate = _clean_text(manifest_payload.get("pipeline_id"))
        if candidate is not None:
            return candidate
        llm_report = manifest_payload.get("llm_report")
        if isinstance(llm_report, dict):
            report_candidate = _clean_text(llm_report.get("pipeline_id"))
            if report_candidate is not None:
                return report_candidate
        return default_pipeline_id
    return default_pipeline_id
def _resolve_stage_in_out_dirs(
    *,
    stage_key: str,
    manifest_payload: dict[str, Any],
    run_dir: Path,
    stage_dir_name: str,
) -> tuple[Path, Path]:
    paths_payload: dict[str, Any] = {}
    if not paths_payload:
        raw_paths = manifest_payload.get("paths")
        if isinstance(raw_paths, dict):
            paths_payload = raw_paths

    input_key_map = {
        "recipe_refine": "recipe_phase_input_dir",
        "nonrecipe_finalize": "knowledge_in_dir",
    }
    output_key_map = {
        "recipe_refine": "recipe_phase_proposals_dir",
        "nonrecipe_finalize": "proposals_dir",
    }

    input_key = input_key_map.get(stage_key)
    output_key = output_key_map.get(stage_key)
    pass_in = paths_payload.get(input_key) if input_key is not None else None
    pass_out = paths_payload.get(output_key) if output_key is not None else None

    in_dir = Path(str(pass_in)) if isinstance(pass_in, str) else None
    out_dir = Path(str(pass_out)) if isinstance(pass_out, str) else None
    if in_dir is None or not in_dir.exists():
        if stage_key == "recipe_refine":
            in_dir = run_dir / "recipe_phase_runtime" / "inputs"
        else:
            in_dir = run_dir / stage_dir_name / "in"
    if out_dir is None or not out_dir.exists():
        if stage_key == "recipe_refine":
            out_dir = run_dir / "recipe_phase_runtime" / "proposals"
        elif stage_key == "nonrecipe_finalize":
            out_dir = run_dir / stage_dir_name / "proposals"
        else:
            out_dir = run_dir / stage_dir_name / "out"
    return in_dir, out_dir
def _runtime_stage_dir_name(stage_key: str) -> str:
    if stage_key == "recipe_refine":
        return "recipe_phase_runtime"
    return stage_artifact_stem(stage_key)
def discover_codex_exec_prompt_run_descriptors(
    *,
    pred_run: Path,
) -> list[PromptRunDescriptor]:
    discovery_root = pred_run
    raw_llm_dir = discovery_root / "raw" / "llm"
    if not raw_llm_dir.exists() or not raw_llm_dir.is_dir():
        prediction_run_manifest = _load_json_dict(pred_run / "run_manifest.json")
        prediction_artifacts = (
            prediction_run_manifest.get("artifacts")
            if isinstance(prediction_run_manifest, dict)
            else None
        )
        if isinstance(prediction_artifacts, dict):
            for artifact_key in ("stage_run_dir", "processed_output_run_dir"):
                candidate_root = _resolve_artifact_path(
                    pred_run,
                    prediction_artifacts.get(artifact_key),
                )
                if candidate_root is None:
                    continue
                candidate_raw_llm_dir = candidate_root / "raw" / "llm"
                if candidate_raw_llm_dir.exists() and candidate_raw_llm_dir.is_dir():
                    discovery_root = candidate_root
                    raw_llm_dir = candidate_raw_llm_dir
                    break
            else:
                recipe_manifest_path = _resolve_artifact_path(
                    pred_run,
                    prediction_artifacts.get(RECIPE_MANIFEST_FILE_NAME)
                    or prediction_artifacts.get("recipe_manifest_json"),
                )
                if recipe_manifest_path is not None:
                    for ancestor in recipe_manifest_path.parents:
                        candidate_raw_llm_dir = ancestor / "raw" / "llm"
                        if (
                            candidate_raw_llm_dir.exists()
                            and candidate_raw_llm_dir.is_dir()
                        ):
                            discovery_root = ancestor
                            raw_llm_dir = candidate_raw_llm_dir
                            break
    if not raw_llm_dir.exists() or not raw_llm_dir.is_dir():
        return []

    run_dirs: list[Path] = [path for path in raw_llm_dir.iterdir() if path.is_dir()]
    if not run_dirs:
        return []

    descriptors: list[PromptRunDescriptor] = []
    manifest_names = sorted(
        {
            str(spec["manifest_name"])
            for spec in _CODEXFARM_STAGE_SPECS
        }
    )
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
            notes.append("missing prompt manifests")
        else:
            for stage_spec in _CODEXFARM_STAGE_SPECS:
                stage_key = str(stage_spec["stage_key"])
                manifest_name = str(stage_spec["manifest_name"])
                manifest_payload = manifest_payload_by_name.get(manifest_name)
                if not isinstance(manifest_payload, dict):
                    continue
                pipeline_id = _resolve_manifest_pipeline_id_for_stage(
                    stage_key=stage_key,
                    manifest_payload=manifest_payload,
                )
                stage_metadata = _build_prompt_stage_metadata(
                    stage_key=stage_key,
                    pipeline_id=pipeline_id,
                )
                resolved_stage_dir_name = _runtime_stage_dir_name(
                    str(stage_metadata.get("stage_key") or stage_key)
                )
                input_dir, output_dir = _resolve_stage_in_out_dirs(
                    stage_key=stage_key,
                    manifest_payload=manifest_payload,
                    run_dir=run_dir,
                    stage_dir_name=resolved_stage_dir_name,
                )
                process_run_payload = _resolve_process_run_payload_for_stage(
                    stage_key=stage_key,
                    manifest_payload=manifest_payload,
                )
                stages.append(
                    PromptStageDescriptor(
                        schema_version=PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION,
                        stage_order=int(stage_metadata.get("stage_order") or 999),
                        stage_dir_name=resolved_stage_dir_name,
                        stage_key=str(stage_metadata.get("stage_key") or stage_key),
                        stage_heading_key=str(
                            stage_metadata.get("heading_key")
                            or stage_metadata.get("stage_key")
                            or stage_key
                        ),
                        stage_label=str(stage_metadata.get("label") or "Prompt Stage"),
                        stage_artifact_stem=str(
                            stage_metadata.get("artifact_stem") or stage_key
                        ),
                        pipeline_id=pipeline_id,
                        manifest_name=manifest_name,
                        manifest_path=manifest_path_by_name.get(manifest_name),
                        manifest_payload=manifest_payload,
                        process_run_payload=(
                            process_run_payload if isinstance(process_run_payload, dict) else None
                        ),
                        input_dir=input_dir,
                        output_dir=output_dir,
                    )
                )

        primary_manifest = manifest_payload_by_name.get(RECIPE_MANIFEST_FILE_NAME, {})
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
                            stage.stage_order,
                            stage.stage_key,
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
def discover_prompt_run_descriptors(
    *,
    pred_run: Path,
    discoverers: Sequence[PromptRunDescriptorDiscoverer] | None = None,
) -> list[PromptRunDescriptor]:
    active_discoverers: Sequence[PromptRunDescriptorDiscoverer]
    if discoverers is None:
        active_discoverers = (discover_codex_exec_prompt_run_descriptors,)
    else:
        active_discoverers = discoverers
    descriptors: list[PromptRunDescriptor] = []
    for discoverer in active_discoverers:
        discovered = list(discoverer(pred_run=pred_run))
        if discovered:
            descriptors.extend(discovered)
            break
    return descriptors
