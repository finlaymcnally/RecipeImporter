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
    stage_artifact_stem,
)

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
        "stage_key": "recipe_llm_correct_and_link",
        "stage_order": 1,
        "stage_label": "Recipe Correction",
        "stage_artifact_stem": "recipe_correction",
        "default_pipeline_id": "recipe.correction.compact.v1",
        "manifest_name": RECIPE_MANIFEST_FILE_NAME,
    },
    {
        "stage_key": "nonrecipe_knowledge_review",
        "stage_order": 4,
        "stage_label": "Non-Recipe Knowledge Review",
        "stage_artifact_stem": "knowledge",
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
    "knowledge": "Non-Recipe Knowledge Review",
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


def summarize_prompt_log(*, full_prompt_log_path: Path) -> dict[str, Any] | None:
    if not full_prompt_log_path.exists() or not full_prompt_log_path.is_file():
        return None

    by_stage: dict[str, dict[str, Any]] = {}
    unique_runtime_shard_keys: set[tuple[str, str]] = set()
    total_rows = 0
    rows_without_runtime_shard_id = 0
    try:
        lines = full_prompt_log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(row, Mapping):
            continue
        total_rows += 1
        stage_key = str(row.get("stage_key") or "").strip() or "unknown"
        stage_payload = by_stage.setdefault(
            stage_key,
            {
                "stage_key": stage_key,
                "stage_label": _PROMPT_STAGE_LABELS_BY_KEY.get(
                    stage_key,
                    stage_key.replace("_", " ").title(),
                ),
                "stage_artifact_stem": str(row.get("stage_artifact_stem") or "").strip() or None,
                "row_count": 0,
                "runtime_shard_count": 0,
                "runtime_worker_count": 0,
                "runtime_owned_id_count": 0,
                "rows_without_runtime_shard_id": 0,
                "_runtime_shard_ids": set(),
                "_runtime_worker_ids": set(),
                "_runtime_owned_ids": set(),
            },
        )
        stage_payload["row_count"] += 1

        runtime_shard_id = str(row.get("runtime_shard_id") or "").strip()
        if runtime_shard_id:
            cast(set[str], stage_payload["_runtime_shard_ids"]).add(runtime_shard_id)
            unique_runtime_shard_keys.add((stage_key, runtime_shard_id))
        else:
            rows_without_runtime_shard_id += 1
            stage_payload["rows_without_runtime_shard_id"] += 1

        runtime_worker_id = str(row.get("runtime_worker_id") or "").strip()
        if runtime_worker_id:
            cast(set[str], stage_payload["_runtime_worker_ids"]).add(runtime_worker_id)

        runtime_owned_ids = row.get("runtime_owned_ids")
        if isinstance(runtime_owned_ids, list):
            for owned_id in runtime_owned_ids:
                owned_id_text = str(owned_id or "").strip()
                if owned_id_text:
                    cast(set[str], stage_payload["_runtime_owned_ids"]).add(owned_id_text)

    if total_rows <= 0:
        return None

    for stage_payload in by_stage.values():
        stage_payload["runtime_shard_count"] = len(stage_payload.pop("_runtime_shard_ids"))
        stage_payload["runtime_worker_count"] = len(stage_payload.pop("_runtime_worker_ids"))
        stage_payload["runtime_owned_id_count"] = len(stage_payload.pop("_runtime_owned_ids"))

    runtime_shard_count = len(unique_runtime_shard_keys)
    runtime_shard_count_status = "missing"
    if runtime_shard_count > 0:
        runtime_shard_count_status = (
            "complete" if rows_without_runtime_shard_id == 0 else "partial"
        )
    return {
        "schema_version": PROMPT_LOG_SUMMARY_SCHEMA_VERSION,
        "full_prompt_log_rows": total_rows,
        "runtime_shard_count": runtime_shard_count,
        "runtime_shard_count_status": runtime_shard_count_status,
        "rows_without_runtime_shard_id": rows_without_runtime_shard_id,
        "by_stage": by_stage,
    }


def write_prompt_log_summary(
    *,
    full_prompt_log_path: Path,
    output_path: Path | None = None,
) -> Path | None:
    summary = summarize_prompt_log(full_prompt_log_path=full_prompt_log_path)
    if summary is None:
        return None
    target_path = (
        output_path
        if output_path is not None
        else full_prompt_log_path.with_name(PROMPT_LOG_SUMMARY_JSON_NAME)
    )
    target_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target_path


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
    if stage_key == "recipe_llm_correct_and_link":
        process_runs = manifest_payload.get("process_runs")
        if not isinstance(process_runs, dict):
            return None
        pass_payload = process_runs.get("recipe_correction")
        return pass_payload if isinstance(pass_payload, dict) else None
    if stage_key == "nonrecipe_knowledge_review":
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
    if stage_key == "recipe_llm_correct_and_link":
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
    if stage_key == "nonrecipe_knowledge_review":
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
        "recipe_llm_correct_and_link": "recipe_phase_input_dir",
        "nonrecipe_knowledge_review": "knowledge_in_dir",
    }
    output_key_map = {
        "recipe_llm_correct_and_link": "recipe_phase_proposals_dir",
        "nonrecipe_knowledge_review": "proposals_dir",
    }

    input_key = input_key_map.get(stage_key)
    output_key = output_key_map.get(stage_key)
    pass_in = paths_payload.get(input_key) if input_key is not None else None
    pass_out = paths_payload.get(output_key) if output_key is not None else None

    in_dir = Path(str(pass_in)) if isinstance(pass_in, str) else None
    out_dir = Path(str(pass_out)) if isinstance(pass_out, str) else None
    if in_dir is None or not in_dir.exists():
        if stage_key == "recipe_llm_correct_and_link":
            in_dir = run_dir / "recipe_phase_runtime" / "inputs"
        else:
            in_dir = run_dir / stage_dir_name / "in"
    if out_dir is None or not out_dir.exists():
        if stage_key == "recipe_llm_correct_and_link":
            out_dir = run_dir / "recipe_phase_runtime" / "proposals"
        elif stage_key == "nonrecipe_knowledge_review":
            out_dir = run_dir / stage_dir_name / "proposals"
        else:
            out_dir = run_dir / stage_dir_name / "out"
    return in_dir, out_dir


def _runtime_stage_dir_name(stage_key: str) -> str:
    if stage_key == "recipe_llm_correct_and_link":
        return "recipe_phase_runtime"
    return stage_artifact_stem(stage_key)


def discover_codexfarm_prompt_run_descriptors(
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
        active_discoverers = (discover_codexfarm_prompt_run_descriptors,)
    else:
        active_discoverers = discoverers
    descriptors: list[PromptRunDescriptor] = []
    for discoverer in active_discoverers:
        discovered = list(discoverer(pred_run=pred_run))
        if discovered:
            descriptors.extend(discovered)
            break
    return descriptors


def _resolve_recipe_id(*, parsed_input: Any, parsed_output: Any, fallback_name: str) -> str | None:
    for payload in (parsed_input, parsed_output):
        if isinstance(payload, dict):
            candidate = str(payload.get("recipe_id") or "").strip()
            if candidate:
                return candidate
    stem = Path(fallback_name).stem
    candidate_from_name = re.sub(r"^r\d+_", "", stem).strip()
    return candidate_from_name or None


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


def _resolve_codex_exec_csv_paths(
    manifest_payload: dict[str, Any],
    *,
    repo_root: Path,
) -> list[Path]:
    candidates: list[Path] = []
    for process_run_payload in _iter_process_run_payloads(manifest_payload):
        telemetry_payload = process_run_payload.get("telemetry")
        if not isinstance(telemetry_payload, dict):
            continue
        csv_path_raw = telemetry_payload.get("csv_path")
        if isinstance(csv_path_raw, str) and csv_path_raw.strip():
            candidates.append(Path(csv_path_raw.strip()))
    candidates.append((repo_root / "var" / "codex_exec_activity.csv").resolve())

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
    *,
    repo_root: Path,
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
    for csv_path in _resolve_codex_exec_csv_paths(manifest_payload, repo_root=repo_root):
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
                    if existing is None or _telemetry_row_sort_key(row) >= _telemetry_row_sort_key(existing):
                        rows_by_run_and_input[run_id][input_name] = row
                        csv_source_by_run_id[run_id] = str(csv_path)
        except OSError:
            continue
    return rows_by_run_and_input, csv_source_by_run_id


def _load_run_assets_for_process_run(
    *,
    process_run_payload: dict[str, Any] | None,
    repo_root: Path,
) -> dict[str, Any]:
    if not isinstance(process_run_payload, dict):
        return {}
    run_id = str(process_run_payload.get("run_id") or "").strip()
    if not run_id:
        return {}
    run_assets_dir = (repo_root / "var" / "run_assets" / run_id).resolve()
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


def _collect_prompt_attachments(
    payload: Any,
    *,
    prompt_file: Path,
    pred_run: Path,
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
                and resolved.suffix.lower() in _TEXT_ATTACHMENT_SUFFIXES
            ):
                if resolved not in seen:
                    seen.add(resolved)
                    found.append(resolved)
                break

    _walk(payload)
    return found


def _resolve_saved_artifact_path(*, raw_path: str | None, repo_root: Path) -> Path | None:
    cleaned = _clean_text(raw_path)
    if cleaned is None:
        return None
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = (repo_root / candidate).resolve()
    resolved = candidate.resolve(strict=False)
    if resolved.exists() and resolved.is_file():
        return resolved
    return None


def _load_jsonl_events(*, events_path: Path | None) -> list[dict[str, Any]]:
    if events_path is None or not events_path.exists() or not events_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for raw_line in events_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parsed = _parse_json_text(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
    except OSError:
        return []
    return rows


def _load_message_text(*, message_path: Path | None) -> str | None:
    if message_path is None or not message_path.exists() or not message_path.is_file():
        return None
    parsed = _parse_json_text(_safe_read_text(message_path))
    if isinstance(parsed, dict):
        text = _clean_text(parsed.get("text"))
        if text is not None:
            return text
    raw_text = _safe_read_text(message_path).strip()
    return raw_text or None


def _activity_excerpt(value: Any, *, max_chars: int = 220) -> str | None:
    if isinstance(value, str):
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            return None
        if len(cleaned) > max_chars:
            return cleaned[: max_chars - 3].rstrip() + "..."
        return cleaned
    return None


def _activity_path_excerpt(value: Any, *, max_parts: int = 4, max_chars: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    path_parts = [part for part in Path(cleaned).parts if part not in {"/", "\\"}]
    if path_parts and len(path_parts) > max_parts:
        cleaned = ".../" + "/".join(path_parts[-max_parts:])
    return _activity_excerpt(cleaned, max_chars=max_chars)


def _extract_visible_reasoning_text(payload: Mapping[str, Any]) -> str | None:
    for key in ("summary_text", "summary", "text", "delta", "content"):
        excerpt = _activity_excerpt(payload.get(key))
        if excerpt is not None:
            return excerpt
    return None


def _summarize_activity_entry_lines(
    entries: Sequence[Mapping[str, Any]],
    *,
    max_entries: int = _ACTIVITY_TRACE_SUMMARY_ENTRY_LIMIT,
) -> list[str]:
    lines: list[str] = []
    for entry in entries[:max_entries]:
        summary = _clean_text(entry.get("summary")) if isinstance(entry, Mapping) else None
        if summary is not None:
            lines.append(summary)
    return lines


def _build_activity_trace_from_events(
    *,
    events: Sequence[Mapping[str, Any]],
    last_message_text: str | None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    reasoning_events: list[dict[str, Any]] = []
    action_event_types: list[str] = []
    reasoning_event_types: list[str] = []
    seen_action_event_types: set[str] = set()
    seen_reasoning_event_types: set[str] = set()
    command_count = 0
    agent_message_count = 0
    reasoning_event_count = 0
    lifecycle_event_count = 0

    def _append_entry(entry: dict[str, Any]) -> None:
        if len(entries) < _ACTIVITY_TRACE_MAX_ENTRIES:
            entries.append(entry)

    def _append_visible_item_entry(item: Mapping[str, Any], *, payload_type: str) -> None:
        item_type = str(item.get("type") or "").strip()
        if not item_type:
            return
        if item_type not in seen_action_event_types:
            seen_action_event_types.add(item_type)
            action_event_types.append(item_type)
        if item_type == "file_change":
            changes = item.get("changes")
            normalized_changes = (
                [change for change in changes if isinstance(change, Mapping)]
                if isinstance(changes, list)
                else []
            )
            if not normalized_changes:
                _append_entry(
                    {
                        "kind": "file_change",
                        "event_type": payload_type,
                        "summary": "Updated files",
                    }
                )
                return
            verb_map = {
                "add": "Created",
                "create": "Created",
                "delete": "Deleted",
                "remove": "Deleted",
                "rename": "Renamed",
                "update": "Updated",
            }
            if len(normalized_changes) == 1:
                change = normalized_changes[0]
                raw_kind = _clean_text(change.get("kind")) or "update"
                summary_verb = verb_map.get(raw_kind, raw_kind.capitalize())
                path_excerpt = _activity_path_excerpt(change.get("path"))
                summary = (
                    f"{summary_verb} `{path_excerpt}`"
                    if path_excerpt is not None
                    else f"{summary_verb} file"
                )
                _append_entry(
                    {
                        "kind": "file_change",
                        "event_type": payload_type,
                        "summary": summary,
                        "changes": [dict(change)],
                    }
                )
                return
            rendered_changes: list[str] = []
            for change in normalized_changes[:3]:
                raw_kind = _clean_text(change.get("kind")) or "update"
                summary_verb = verb_map.get(raw_kind, raw_kind.capitalize())
                path_excerpt = _activity_path_excerpt(change.get("path"))
                if path_excerpt is not None:
                    rendered_changes.append(f"{summary_verb.lower()} `{path_excerpt}`")
                else:
                    rendered_changes.append(summary_verb.lower())
            if len(normalized_changes) > 3:
                rendered_changes.append(f"... ({len(normalized_changes) - 3} more)")
            _append_entry(
                {
                    "kind": "file_change",
                    "event_type": payload_type,
                    "summary": "File changes: " + ", ".join(rendered_changes),
                    "changes": [dict(change) for change in normalized_changes],
                }
            )
            return

        descriptor = (
            _activity_excerpt(item.get("text"))
            or _activity_excerpt(item.get("summary"))
            or _activity_excerpt(item.get("delta"))
            or _activity_excerpt(item.get("content"))
            or _activity_excerpt(item.get("query"))
            or _activity_path_excerpt(item.get("path"))
            or _activity_excerpt(item.get("url"))
            or _activity_excerpt(item.get("title"))
        )
        summary = (
            f"Completed `{item_type}`: {descriptor}"
            if descriptor is not None
            else f"Completed `{item_type}`"
        )
        entry: dict[str, Any] = {
            "kind": "visible_item",
            "event_type": payload_type,
            "item_type": item_type,
            "summary": summary,
        }
        path_excerpt = _activity_path_excerpt(item.get("path"))
        if path_excerpt is not None:
            entry["path"] = path_excerpt
        query_excerpt = _activity_excerpt(item.get("query"))
        if query_excerpt is not None:
            entry["query"] = query_excerpt
        _append_entry(entry)

    for event in events:
        payload_type = str(event.get("type") or "").strip()
        if not payload_type:
            continue
        if payload_type in {"thread.started", "thread.completed", "turn.completed", "turn.failed"}:
            lifecycle_event_count += 1
            if payload_type not in seen_action_event_types:
                seen_action_event_types.add(payload_type)
                action_event_types.append(payload_type)
            if payload_type == "thread.started":
                _append_entry(
                    {
                        "kind": "lifecycle",
                        "event_type": payload_type,
                        "summary": "Session started",
                    }
                )
            elif payload_type == "turn.completed":
                _append_entry(
                    {
                        "kind": "lifecycle",
                        "event_type": payload_type,
                        "summary": "Turn completed",
                    }
                )
            elif payload_type == "turn.failed":
                error_payload = event.get("error")
                error_excerpt = None
                if isinstance(error_payload, Mapping):
                    error_excerpt = _activity_excerpt(
                        error_payload.get("message") or error_payload.get("detail")
                    )
                elif isinstance(error_payload, str):
                    error_excerpt = _activity_excerpt(error_payload)
                summary = (
                    f"Turn failed: {error_excerpt}"
                    if error_excerpt is not None
                    else "Turn failed"
                )
                _append_entry(
                    {
                        "kind": "lifecycle",
                        "event_type": payload_type,
                        "summary": summary,
                    }
                )
            continue
        if "reasoning_summary" in payload_type or payload_type.startswith("response.reasoning"):
            reasoning_event_count += 1
            if payload_type not in seen_reasoning_event_types:
                seen_reasoning_event_types.add(payload_type)
                reasoning_event_types.append(payload_type)
            reasoning_payload = dict(event)
            reasoning_events.append(reasoning_payload)
            excerpt = _extract_visible_reasoning_text(reasoning_payload)
            if excerpt is not None:
                _append_entry(
                    {
                        "kind": "reasoning_summary",
                        "event_type": payload_type,
                        "summary": f"Reasoning summary: {excerpt}",
                    }
                )
            continue
        if payload_type not in {"item.started", "item.completed"}:
            continue
        item = event.get("item")
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "").strip()
        if not item_type:
            continue
        if payload_type == "item.completed" and item_type == "command_execution":
            command_count += 1
            if item_type not in seen_action_event_types:
                seen_action_event_types.add(item_type)
                action_event_types.append(item_type)
            command_text = _activity_excerpt(item.get("command"), max_chars=260)
            exit_code = _coerce_int(item.get("exit_code"))
            if command_text is None:
                summary = "Ran command"
            elif exit_code is not None and exit_code != 0:
                summary = f"Ran `{command_text}` (exit {exit_code})"
            else:
                summary = f"Ran `{command_text}`"
            _append_entry(
                {
                    "kind": "command",
                    "event_type": payload_type,
                    "summary": summary,
                    "command": _clean_text(item.get("command")),
                    "exit_code": exit_code,
                }
            )
            continue
        if payload_type == "item.completed" and item_type == "agent_message":
            agent_message_count += 1
            if item_type not in seen_action_event_types:
                seen_action_event_types.add(item_type)
                action_event_types.append(item_type)
            excerpt = _activity_excerpt(item.get("text"))
            summary = (
                f"Agent message: {excerpt}"
                if excerpt is not None
                else "Agent message emitted"
            )
            _append_entry(
                {
                    "kind": "agent_message",
                    "event_type": payload_type,
                    "summary": summary,
                    "excerpt": excerpt,
                }
            )
            continue
        if payload_type == "item.completed" and item_type == "reasoning":
            reasoning_event_count += 1
            if item_type not in seen_reasoning_event_types:
                seen_reasoning_event_types.add(item_type)
                reasoning_event_types.append(item_type)
            reasoning_payload = dict(item)
            reasoning_payload.setdefault("type", item_type)
            reasoning_events.append(reasoning_payload)
            excerpt = _extract_visible_reasoning_text(reasoning_payload)
            if excerpt is not None:
                _append_entry(
                    {
                        "kind": "reasoning_summary",
                        "event_type": payload_type,
                        "summary": f"Reasoning summary: {excerpt}",
                    }
                )
            continue
        if payload_type == "item.completed":
            _append_visible_item_entry(item, payload_type=payload_type)

    if agent_message_count <= 0 and last_message_text is not None:
        agent_message_count = 1
        excerpt = _activity_excerpt(last_message_text)
        _append_entry(
            {
                "kind": "agent_message",
                "event_type": "last_message.json",
                "summary": (
                    f"Final agent message: {excerpt}"
                    if excerpt is not None
                    else "Final agent message captured"
                ),
                "excerpt": excerpt,
            }
        )

    return {
        "event_count": len(events),
        "command_count": command_count,
        "agent_message_count": agent_message_count,
        "reasoning_event_count": reasoning_event_count,
        "lifecycle_event_count": lifecycle_event_count,
        "action_event_count": command_count + agent_message_count + lifecycle_event_count,
        "action_event_types": action_event_types,
        "reasoning_event_types": reasoning_event_types,
        "reasoning_events": reasoning_events,
        "entries": entries,
        "entries_truncated": len(entries) >= _ACTIVITY_TRACE_MAX_ENTRIES,
    }


def _export_prompt_activity_trace(
    *,
    row_payload: dict[str, Any],
    prompts_dir: Path,
    repo_root: Path,
) -> dict[str, Any] | None:
    request_telemetry = (
        row_payload.get("request_telemetry")
        if isinstance(row_payload.get("request_telemetry"), dict)
        else {}
    )
    call_id = _clean_text(row_payload.get("call_id")) or "call"
    stage_key = _clean_text(row_payload.get("stage_key"))
    events_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("events_path")),
        repo_root=repo_root,
    )
    last_message_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("last_message_path")),
        repo_root=repo_root,
    )
    usage_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("usage_path")),
        repo_root=repo_root,
    )
    live_status_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("live_status_path")),
        repo_root=repo_root,
    )
    workspace_manifest_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("workspace_manifest_path")),
        repo_root=repo_root,
    )
    stdout_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("stdout_path")),
        repo_root=repo_root,
    )
    stderr_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("stderr_path")),
        repo_root=repo_root,
    )
    events = _load_jsonl_events(events_path=events_path)
    last_message_text = _load_message_text(message_path=last_message_path)
    if events:
        computed = _build_activity_trace_from_events(
            events=events,
            last_message_text=last_message_text,
        )
    elif last_message_text is not None:
        computed = _build_activity_trace_from_events(events=(), last_message_text=last_message_text)
    else:
        return None

    activity_traces_dir = prompts_dir / ACTIVITY_TRACES_DIR_NAME
    activity_traces_dir.mkdir(parents=True, exist_ok=True)
    exported_path = activity_traces_dir / f"{slugify_name(call_id)}.json"
    payload = {
        "schema_version": PROMPT_ACTIVITY_TRACE_SCHEMA_VERSION,
        "path": str(exported_path),
        "available": True,
        "call_id": call_id,
        "run_id": _clean_text(row_payload.get("run_id")),
        "recipe_id": _clean_text(row_payload.get("recipe_id")),
        "stage_key": stage_key,
        "stage_label": _clean_text(row_payload.get("stage_label")),
        "model": _clean_text(row_payload.get("model"))
        or _clean_text(request_telemetry.get("model")),
        "reasoning_effort": _clean_text(request_telemetry.get("reasoning_effort"))
        or _clean_text((row_payload.get("decoding_params") or {}).get("reasoning_effort"))
        if isinstance(row_payload.get("decoding_params"), dict)
        else _clean_text(request_telemetry.get("reasoning_effort")),
        "task_id": _clean_text(request_telemetry.get("task_id")),
        "worker_id": _clean_text(row_payload.get("runtime_worker_id"))
        or _clean_text(request_telemetry.get("worker_id")),
        "runtime_shard_id": _clean_text(row_payload.get("runtime_shard_id"))
        or _clean_text(request_telemetry.get("shard_id")),
        "source_events_path": str(events_path) if events_path is not None else None,
        "source_last_message_path": (
            str(last_message_path) if last_message_path is not None else None
        ),
        "source_usage_path": str(usage_path) if usage_path is not None else None,
        "source_live_status_path": (
            str(live_status_path) if live_status_path is not None else None
        ),
        "source_workspace_manifest_path": (
            str(workspace_manifest_path) if workspace_manifest_path is not None else None
        ),
        "source_stdout_path": str(stdout_path) if stdout_path is not None else None,
        "source_stderr_path": str(stderr_path) if stderr_path is not None else None,
        **computed,
    }
    exported_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _resolve_prompt_local_activity_trace_path(*, raw_path: str | None, prompts_dir: Path) -> Path | None:
    cleaned = _clean_text(raw_path)
    if cleaned is None:
        return None
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = (prompts_dir / candidate).resolve(strict=False)
    return candidate.resolve(strict=False)


def _load_exported_activity_trace_payload(
    *,
    trace_path: Path | None,
) -> dict[str, Any] | None:
    if trace_path is None or not trace_path.exists() or not trace_path.is_file():
        return None
    parsed = _parse_json_text(_safe_read_text(trace_path))
    if not isinstance(parsed, dict):
        return None
    return dict(parsed)


def _effective_activity_trace_payload(
    *,
    row: Mapping[str, Any],
    prompts_dir: Path,
) -> dict[str, Any]:
    row_payload = row.get("activity_trace") if isinstance(row.get("activity_trace"), dict) else {}
    request_telemetry = (
        row.get("request_telemetry") if isinstance(row.get("request_telemetry"), dict) else {}
    )
    raw_path = _clean_text(row_payload.get("path")) or _clean_text(
        request_telemetry.get("activity_trace_path")
    )
    exported_path = _resolve_prompt_local_activity_trace_path(raw_path=raw_path, prompts_dir=prompts_dir)
    exported_payload = _load_exported_activity_trace_payload(trace_path=exported_path)
    if isinstance(exported_payload, dict):
        return exported_payload
    return dict(row_payload) if isinstance(row_payload, Mapping) else {}


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

                activity_trace_payload = _effective_activity_trace_payload(
                    row=row,
                    prompts_dir=full_prompt_log_path.parent,
                )
                activity_trace_path: str | None = None
                activity_trace_available = False
                activity_trace_command_count: int | None = None
                activity_trace_agent_message_count: int | None = None
                activity_trace_reasoning_count: int | None = None
                activity_trace_excerpt_lines: list[str] = []
                if isinstance(activity_trace_payload, dict):
                    trace_path = activity_trace_payload.get("path")
                    if isinstance(trace_path, str) and trace_path.strip():
                        activity_trace_path = trace_path.strip()
                    activity_trace_available = bool(activity_trace_payload.get("available"))
                    command_count = activity_trace_payload.get("command_count")
                    if isinstance(command_count, int):
                        activity_trace_command_count = command_count
                    agent_message_count = activity_trace_payload.get("agent_message_count")
                    if isinstance(agent_message_count, int):
                        activity_trace_agent_message_count = agent_message_count
                    reasoning_count = activity_trace_payload.get("reasoning_event_count")
                    if isinstance(reasoning_count, int):
                        activity_trace_reasoning_count = reasoning_count
                    raw_entries = activity_trace_payload.get("entries")
                    if isinstance(raw_entries, list):
                        activity_trace_excerpt_lines = _summarize_activity_entry_lines(
                            [entry for entry in raw_entries if isinstance(entry, Mapping)]
                        )

                call_id = str(row.get("call_id") or "").strip() or "<unknown>"
                recipe_id = str(row.get("recipe_id") or "").strip() or "<unknown>"
                samples_by_stage[stage_group_key].append(
                    {
                        "call_id": call_id,
                        "recipe_id": recipe_id,
                        "prompt": prompt_text.rstrip("\n"),
                        "activity_trace_available": activity_trace_available,
                        "activity_trace_path": activity_trace_path,
                        "activity_trace_command_count": activity_trace_command_count,
                        "activity_trace_agent_message_count": activity_trace_agent_message_count,
                        "activity_trace_reasoning_count": activity_trace_reasoning_count,
                        "activity_trace_excerpt_lines": activity_trace_excerpt_lines,
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
        "",
    ]

    occupied_stage_orders = {
        int(metadata.get("stage_order") or 999)
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
    for stage_spec in _CODEXFARM_STAGE_SPECS:
        stage_key = str(stage_spec["stage_key"])
        stage_order = int(stage_spec.get("stage_order") or 999)
        if stage_order in occupied_stage_orders:
            continue
        placeholder_metadata = _build_prompt_stage_metadata(
            stage_key=stage_key,
            pipeline_id=_clean_prompt_stage_text(stage_spec.get("default_pipeline_id")),
        )
        render_entries.append(
            (
                str(placeholder_metadata.get("heading_key") or stage_key),
                placeholder_metadata,
                [],
                999 + stage_order,
            )
        )
    render_entries.sort(
        key=lambda entry: (
            int(entry[1].get("stage_order") or 999),
            entry[3],
            entry[0],
        )
    )

    for stage_group_key, metadata, stage_samples, _ in render_entries:
        stage_label = str(metadata.get("label") or "Prompt Stage")
        lines.append(f"## {stage_group_key} ({stage_label})")
        lines.append("")
        pipeline_id = _clean_prompt_stage_text(metadata.get("pipeline_id"))
        if pipeline_id is not None:
            lines.append(f"- pipeline_id: `{pipeline_id}`")
            lines.append("")
        if not stage_samples:
            lines.append("_No rows captured for this stage._")
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
            lines.append("Activity Trace:")
            activity_trace_available = bool(sample.get("activity_trace_available"))
            activity_trace_path = sample.get("activity_trace_path")
            activity_trace_command_count = sample.get("activity_trace_command_count")
            activity_trace_agent_message_count = sample.get("activity_trace_agent_message_count")
            activity_trace_reasoning_count = sample.get("activity_trace_reasoning_count")
            activity_trace_excerpt_lines = list(sample.get("activity_trace_excerpt_lines") or [])
            if activity_trace_path:
                lines.append(f"- path: `{activity_trace_path}`")
            if isinstance(activity_trace_command_count, int):
                lines.append(f"- command_count: `{activity_trace_command_count}`")
            if isinstance(activity_trace_agent_message_count, int):
                lines.append(
                    f"- agent_message_count: `{activity_trace_agent_message_count}`"
                )
            if isinstance(activity_trace_reasoning_count, int):
                lines.append(
                    f"- reasoning_event_count: `{activity_trace_reasoning_count}`"
                )
            if activity_trace_excerpt_lines:
                lines.append("- sample entries:")
                for excerpt_line in activity_trace_excerpt_lines:
                    lines.append(f"  - {excerpt_line}")
            elif not activity_trace_available:
                lines.append("- _No exported activity trace available for this sample._")
            lines.append("")

    try:
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return None
    return output_path


def build_codex_farm_activity_trace_summaries(
    *,
    full_prompt_log_path: Path,
    output_jsonl_path: Path,
    output_md_path: Path,
    examples_per_stage: int = 3,
) -> tuple[Path | None, Path | None]:
    rows = _load_prompt_rows(full_prompt_log_path)
    if not rows:
        output_jsonl_path.unlink(missing_ok=True)
        output_md_path.unlink(missing_ok=True)
        return None, None

    summary_rows: list[dict[str, Any]] = []
    stage_summary: dict[str, dict[str, Any]] = {}
    stage_examples: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        stage_metadata = _prompt_stage_metadata_from_row(row)
        stage_key = str(stage_metadata.get("heading_key") or stage_metadata.get("stage_key") or "stage")
        stage_label = str(stage_metadata.get("label") or "Prompt Stage")
        activity_trace_payload = _effective_activity_trace_payload(
            row=row,
            prompts_dir=full_prompt_log_path.parent,
        )
        activity_trace_path = _clean_text(activity_trace_payload.get("path"))
        activity_trace_exists = bool(
            activity_trace_path and Path(activity_trace_path).exists()
        )
        trace_available = bool(activity_trace_payload.get("available"))
        command_count = _coerce_int(activity_trace_payload.get("command_count")) or 0
        agent_message_count = (
            _coerce_int(activity_trace_payload.get("agent_message_count")) or 0
        )
        reasoning_event_count = (
            _coerce_int(activity_trace_payload.get("reasoning_event_count")) or 0
        )
        event_count = _coerce_int(activity_trace_payload.get("event_count")) or 0
        entries = activity_trace_payload.get("entries")
        normalized_entries = (
            [dict(entry) for entry in entries if isinstance(entry, Mapping)]
            if isinstance(entries, list)
            else []
        )
        entry_excerpt_lines = _summarize_activity_entry_lines(
            normalized_entries,
            max_entries=_ACTIVITY_TRACE_SUMMARY_ENTRY_LIMIT,
        )
        summary_row = {
            "schema_version": PROMPT_ACTIVITY_TRACE_SUMMARY_SCHEMA_VERSION,
            "run_id": row.get("run_id"),
            "call_id": row.get("call_id"),
            "recipe_id": row.get("recipe_id"),
            "stage_key": stage_key,
            "stage_label": stage_label,
            "stage_order": stage_metadata.get("stage_order"),
            "activity_trace_path": activity_trace_path,
            "activity_trace_exists": activity_trace_exists,
            "activity_trace_available": trace_available,
            "process_run_id": row.get("process_run_id"),
            "event_count": event_count,
            "command_count": command_count,
            "agent_message_count": agent_message_count,
            "reasoning_event_count": reasoning_event_count,
            "reasoning_event_types": list(
                activity_trace_payload.get("reasoning_event_types") or []
            )
            if isinstance(activity_trace_payload.get("reasoning_event_types"), list)
            else [],
            "action_event_count": _coerce_int(activity_trace_payload.get("action_event_count")),
            "action_event_types": list(
                activity_trace_payload.get("action_event_types") or []
            )
            if isinstance(activity_trace_payload.get("action_event_types"), list)
            else [],
            "source_events_path": _clean_text(activity_trace_payload.get("source_events_path")),
            "entry_excerpt_lines": entry_excerpt_lines,
        }
        summary_rows.append(summary_row)

        stage_state = stage_summary.setdefault(
            stage_key,
            {
                "stage_label": stage_label,
                "stage_order": int(stage_metadata.get("stage_order") or 999),
                "rows": 0,
                "activity_trace_present": 0,
                "activity_trace_exists": 0,
                "activity_trace_available": 0,
                "command_rows": 0,
                "agent_message_rows": 0,
                "reasoning_event_rows": 0,
            },
        )
        stage_state["rows"] += 1
        if activity_trace_path is not None:
            stage_state["activity_trace_present"] += 1
        if activity_trace_exists:
            stage_state["activity_trace_exists"] += 1
        if trace_available:
            stage_state["activity_trace_available"] += 1
        if command_count > 0:
            stage_state["command_rows"] += 1
        if agent_message_count > 0:
            stage_state["agent_message_rows"] += 1
        if reasoning_event_count and reasoning_event_count > 0:
            stage_state["reasoning_event_rows"] += 1

        stage_examples.setdefault(stage_key, [])
        if len(stage_examples[stage_key]) < examples_per_stage:
            stage_examples[stage_key].append(summary_row)

    output_jsonl_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in summary_rows),
        encoding="utf-8",
    )

    total_rows = len(summary_rows)
    total_activity_trace_present = sum(
        int(stage["activity_trace_present"]) for stage in stage_summary.values()
    )
    total_activity_trace_exists = sum(
        int(stage["activity_trace_exists"]) for stage in stage_summary.values()
    )
    total_activity_trace_available = sum(
        int(stage["activity_trace_available"]) for stage in stage_summary.values()
    )
    total_command_rows = sum(int(stage["command_rows"]) for stage in stage_summary.values())
    total_agent_message_rows = sum(
        int(stage["agent_message_rows"]) for stage in stage_summary.values()
    )
    total_reasoning_event_rows = sum(
        int(stage["reasoning_event_rows"]) for stage in stage_summary.values()
    )
    generated_timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    lines: list[str] = [
        "# CodexFarm Activity Trace Summary",
        "",
        f"Generated: {generated_timestamp}",
        "Source:",
        f"- {full_prompt_log_path}",
        "",
        "Overall:",
        f"- total_rows: `{total_rows}`",
        f"- rows_with_activity_trace: `{total_activity_trace_present}`",
        f"- rows_with_existing_activity_trace_file: `{total_activity_trace_exists}`",
        f"- rows_with_available_activity_trace_payload: `{total_activity_trace_available}`",
        f"- rows_with_commands: `{total_command_rows}`",
        f"- rows_with_agent_messages: `{total_agent_message_rows}`",
        f"- rows_with_reasoning_events: `{total_reasoning_event_rows}`",
        "",
    ]
    for stage_key, stage_state in sorted(
        stage_summary.items(),
        key=lambda item: (
            int(item[1].get("stage_order") or 999),
            item[0],
        ),
    ):
        lines.extend(
            [
                f"## {stage_key} ({stage_state['stage_label']})",
                "",
                f"- rows: `{stage_state['rows']}`",
                f"- rows_with_activity_trace: `{stage_state['activity_trace_present']}`",
                f"- rows_with_existing_activity_trace_file: `{stage_state['activity_trace_exists']}`",
                f"- rows_with_available_activity_trace_payload: `{stage_state['activity_trace_available']}`",
                f"- rows_with_commands: `{stage_state['command_rows']}`",
                f"- rows_with_agent_messages: `{stage_state['agent_message_rows']}`",
                f"- rows_with_reasoning_events: `{stage_state['reasoning_event_rows']}`",
                "",
                "### Sample Rows",
                "",
            ]
        )
        examples = stage_examples.get(stage_key, [])
        if not examples:
            lines.append("_No rows captured for this stage._")
            lines.append("")
            continue
        for example in examples:
            lines.append(f"- call_id: `{example.get('call_id') or '<unknown>'}`")
            lines.append(f"  recipe_id: `{example.get('recipe_id') or '<unknown>'}`")
            lines.append(
                f"  activity_trace_exists: `{example.get('activity_trace_exists')}`"
            )
            lines.append(f"  command_count: `{example.get('command_count')}`")
            lines.append(
                f"  agent_message_count: `{example.get('agent_message_count')}`"
            )
            lines.append(
                f"  reasoning_event_count: `{example.get('reasoning_event_count')}`"
            )
            activity_trace_path = _clean_text(example.get("activity_trace_path"))
            if activity_trace_path is not None:
                lines.append(f"  activity_trace_path: `{activity_trace_path}`")
            excerpt_lines = example.get("entry_excerpt_lines")
            if isinstance(excerpt_lines, list) and excerpt_lines:
                lines.append("  sample_entries:")
                for excerpt_line in excerpt_lines:
                    lines.append(f"  - {excerpt_line}")
            lines.append("")

    output_md_path.write_text("\n".join(lines), encoding="utf-8")
    return output_jsonl_path, output_md_path
def _parse_prompt_index_from_name(name: str) -> int | None:
    match = re.search(r"(\d+)", str(name or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _load_prompt_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_json_sequence(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _load_phase_runtime_index(stage_root: Path) -> dict[str, Any]:
    phase_manifest = _load_json_dict(stage_root / "phase_manifest.json") or {}
    if not phase_manifest:
        return {}
    worker_assignments = _load_json_sequence(stage_root / "worker_assignments.json")
    shard_rows = _load_prompt_rows(stage_root / "shard_manifest.jsonl")
    worker_by_shard_id: dict[str, str] = {}
    for assignment in worker_assignments:
        worker_id = _clean_text(assignment.get("worker_id"))
        if worker_id is None:
            continue
        for shard_id in assignment.get("shard_ids") or []:
            rendered_shard_id = _clean_text(shard_id)
            if rendered_shard_id is not None:
                worker_by_shard_id[rendered_shard_id] = worker_id
    shard_by_id: dict[str, dict[str, Any]] = {}
    shard_by_owned_id: dict[str, dict[str, Any]] = {}
    shard_by_prompt_index: dict[int, dict[str, Any]] = {}
    telemetry_by_shard_id: dict[str, dict[str, Any]] = {}
    telemetry_payload = _load_json_dict(stage_root / "telemetry.json") or {}
    telemetry_rows = (
        telemetry_payload.get("rows") if isinstance(telemetry_payload.get("rows"), list) else []
    )
    for row in telemetry_rows:
        if not isinstance(row, dict):
            continue
        shard_id = _clean_text(row.get("task_id"))
        if shard_id is not None:
            telemetry_by_shard_id[shard_id] = dict(row)
    for row in shard_rows:
        shard_id = _clean_text(row.get("shard_id"))
        if shard_id is None:
            continue
        normalized = {
            "shard_id": shard_id,
            "owned_ids": [
                str(item).strip()
                for item in row.get("owned_ids") or []
                if str(item).strip()
            ],
            "worker_id": worker_by_shard_id.get(shard_id),
            "input_file": None,
            "debug_input_file": None,
            "telemetry_row": telemetry_by_shard_id.get(shard_id),
            "metadata": dict(row.get("metadata") or {})
            if isinstance(row.get("metadata"), dict)
            else {},
        }
        worker_id = normalized.get("worker_id")
        if worker_id:
            input_file = stage_root / "workers" / str(worker_id) / "in" / f"{shard_id}.json"
            if input_file.exists() and input_file.is_file():
                normalized["input_file"] = str(input_file)
            debug_input_file = stage_root / "workers" / str(worker_id) / "debug" / f"{shard_id}.json"
            if debug_input_file.exists() and debug_input_file.is_file():
                normalized["debug_input_file"] = str(debug_input_file)
        shard_by_id[shard_id] = normalized
        for owned_id in normalized["owned_ids"]:
            shard_by_owned_id[owned_id] = normalized
        prompt_index = _coerce_int(normalized["metadata"].get("prompt_index"))
        if prompt_index is not None:
            shard_by_prompt_index[prompt_index] = normalized
    return {
        "pipeline_id": _clean_text(phase_manifest.get("pipeline_id")),
        "shard_by_id": shard_by_id,
        "shard_by_owned_id": shard_by_owned_id,
        "shard_by_prompt_index": shard_by_prompt_index,
        "telemetry_by_shard_id": telemetry_by_shard_id,
    }


def _resolve_runtime_context(
    *,
    runtime_index: Mapping[str, Any] | None,
    shard_id: str | None = None,
    owned_id: str | None = None,
    prompt_index: int | None = None,
) -> dict[str, Any]:
    if not isinstance(runtime_index, Mapping):
        return {}
    shard_row = None
    if shard_id:
        shard_row = (runtime_index.get("shard_by_id") or {}).get(shard_id)
    if shard_row is None and owned_id:
        shard_row = (runtime_index.get("shard_by_owned_id") or {}).get(owned_id)
    if shard_row is None and prompt_index is not None:
        shard_row = (runtime_index.get("shard_by_prompt_index") or {}).get(prompt_index)
    if not isinstance(shard_row, Mapping):
        return {}
    return {
        "runtime_pipeline_id": runtime_index.get("pipeline_id"),
        "runtime_shard_id": shard_row.get("shard_id"),
        "runtime_worker_id": shard_row.get("worker_id"),
        "runtime_owned_ids": list(shard_row.get("owned_ids") or []),
        "request_input_file": shard_row.get("input_file"),
        "debug_input_file": shard_row.get("debug_input_file"),
        "runtime_telemetry_row": (
            dict(shard_row.get("telemetry_row"))
            if isinstance(shard_row.get("telemetry_row"), Mapping)
            else None
        ),
    }


def _prompt_row_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    return (
        _coerce_int(row.get("stage_order")) or 999,
        str(row.get("stage_key") or ""),
        str(row.get("call_id") or ""),
    )


def _upsert_text_section(
    *,
    path: Path,
    start_marker: str,
    end_marker: str,
    body: str,
) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() and path.is_file() else ""
    start_index = text.find(start_marker)
    end_index = text.find(end_marker)
    section_text = (
        f"{start_marker}\n"
        f"{body.rstrip()}\n"
        f"{end_marker}\n"
    )
    if start_index >= 0 and end_index >= 0 and end_index >= start_index:
        end_index += len(end_marker)
        if end_index < len(text) and text[end_index : end_index + 1] == "\n":
            end_index += 1
        updated = text[:start_index].rstrip()
        if updated:
            updated += "\n\n"
        updated += section_text
        suffix = text[end_index:].lstrip("\n")
        if suffix:
            updated += "\n" + suffix
        path.write_text(updated.rstrip() + "\n", encoding="utf-8")
        return

    updated = text.rstrip()
    if updated:
        updated += "\n\n"
    updated += section_text
    path.write_text(updated.rstrip() + "\n", encoding="utf-8")


def _resolve_stage_run_root_for_prompt_exports(*, pred_run: Path) -> Path | None:
    candidate = pred_run.resolve(strict=False)
    if candidate.is_dir() and (
        (candidate / "raw" / "llm").is_dir()
        or (candidate / "line-role-pipeline" / "prompts").is_dir()
    ):
        return candidate

    prediction_run_manifest = _load_json_dict(pred_run / "run_manifest.json")
    prediction_artifacts = (
        prediction_run_manifest.get("artifacts")
        if isinstance(prediction_run_manifest, dict)
        else None
    )
    if not isinstance(prediction_artifacts, dict):
        return None

    for artifact_key in ("stage_run_dir", "processed_output_run_dir"):
        resolved = _resolve_artifact_path(pred_run, prediction_artifacts.get(artifact_key))
        if resolved is None or not resolved.exists() or not resolved.is_dir():
            continue
        if (resolved / "raw" / "llm").is_dir() or (
            resolved / "line-role-pipeline" / "prompts"
        ).is_dir():
            return resolved

    return None


def _copy_prompt_artifact_file(*, source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
    except Exception:  # noqa: BLE001
        target.write_text(_safe_read_text(source), encoding="utf-8")


def _build_line_role_prompt_rows(
    *,
    pred_run: Path,
    eval_output_dir: Path,
    repo_root: Path,
) -> tuple[list[dict[str, Any]], str] | tuple[list[dict[str, Any]], None]:
    stage_run_root = _resolve_stage_run_root_for_prompt_exports(pred_run=pred_run)
    if stage_run_root is None:
        return [], None

    stage_prompt_dir = stage_run_root / "line-role-pipeline" / "prompts"
    if not stage_prompt_dir.exists() or not stage_prompt_dir.is_dir():
        return [], None

    prompts_dir = eval_output_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    export_dir = prompts_dir / "line-role-pipeline"
    export_dir.mkdir(parents=True, exist_ok=True)
    telemetry_summary_path = stage_run_root / "line-role-pipeline" / "telemetry_summary.json"
    telemetry_summary = _load_json_dict(telemetry_summary_path) or {}
    phases = telemetry_summary.get("phases")
    phases_by_key: dict[str, dict[str, Any]] = {}
    if isinstance(phases, list):
        for phase_payload in phases:
            if not isinstance(phase_payload, dict):
                continue
            phase_key = _clean_text(phase_payload.get("phase_key"))
            if phase_key is not None:
                phases_by_key[phase_key] = phase_payload
    if telemetry_summary_path.exists() and telemetry_summary_path.is_file():
        _copy_prompt_artifact_file(
            source=telemetry_summary_path,
            target=export_dir / "telemetry_summary.json",
        )

    pred_run_manifest = _load_json_dict(pred_run / "run_manifest.json") or {}
    pred_run_source = (
        pred_run_manifest.get("source")
        if isinstance(pred_run_manifest.get("source"), dict)
        else {}
    )
    source_file = None
    if isinstance(pred_run_source, dict):
        source_file = _clean_text(pred_run_source.get("path"))

    rows: list[dict[str, Any]] = []
    detail_lines: list[str] = []
    phase_specs = [
        {
            "phase_key": "line_role",
            "prompt_stem": "line_role_prompt",
            "stage_key": "line_role",
            "stage_label": "Line Role",
            "stage_artifact_stem": "line_role",
            "stage_order": 2,
        }
    ]

    for spec in phase_specs:
        phase_key = spec["phase_key"]
        phase_prompt_dir = stage_prompt_dir / phase_key
        if not phase_prompt_dir.exists() or not phase_prompt_dir.is_dir():
            continue
        phase_export_dir = export_dir / phase_key
        phase_export_dir.mkdir(parents=True, exist_ok=True)
        for source_path in sorted(phase_prompt_dir.iterdir(), key=lambda path: path.name):
            if source_path.is_file():
                _copy_prompt_artifact_file(
                    source=source_path,
                    target=phase_export_dir / source_path.name,
                )

        runtime_index = _load_phase_runtime_index(
            stage_run_root / "line-role-pipeline" / "runtime" / phase_key
        )
        phase_payload = phases_by_key.get(phase_key) or {}
        phase_batches = phase_payload.get("batches")
        batches_by_prompt_index: dict[int, dict[str, Any]] = {}
        if isinstance(phase_batches, list):
            for batch in phase_batches:
                if not isinstance(batch, dict):
                    continue
                prompt_index = _coerce_int(batch.get("prompt_index"))
                if prompt_index is not None:
                    batches_by_prompt_index[prompt_index] = batch

        detail_lines.extend(
            [
                f"=== CATEGORY {spec['stage_key']} ({spec['stage_label']}) | stage_dir: line-role-pipeline/{phase_key} ===",
                f"source_dir: {phase_prompt_dir}",
                "",
            ]
        )

        prompt_glob = f"{spec['prompt_stem']}_*.txt"
        for prompt_file in sorted(phase_prompt_dir.glob(prompt_glob), key=lambda path: path.name):
            if (
                f"{spec['prompt_stem']}_response_" in prompt_file.name
                or f"{spec['prompt_stem']}_parsed_" in prompt_file.name
            ):
                continue
            prompt_index = _parse_prompt_index_from_name(prompt_file.name)
            if prompt_index is None:
                continue
            response_file = phase_prompt_dir / f"{spec['prompt_stem']}_response_{prompt_index:04d}.txt"
            parsed_file = phase_prompt_dir / f"{spec['prompt_stem']}_parsed_{prompt_index:04d}.json"
            exported_prompt_file = phase_export_dir / prompt_file.name
            exported_response_file = phase_export_dir / response_file.name
            exported_parsed_file = phase_export_dir / parsed_file.name

            prompt_text = _safe_read_text(prompt_file)
            response_text = _safe_read_text(response_file) if response_file.exists() else ""
            parsed_response = _load_json_value(parsed_file)
            if parsed_response is None:
                parsed_response = _parse_json_text(response_text)

            runtime_context = _resolve_runtime_context(
                runtime_index=runtime_index,
                prompt_index=prompt_index,
            )
            runtime_telemetry_row = (
                dict(runtime_context.get("runtime_telemetry_row"))
                if isinstance(runtime_context.get("runtime_telemetry_row"), dict)
                else {}
            )
            input_file = (
                Path(str(runtime_context.get("request_input_file")))
                if _clean_text(runtime_context.get("request_input_file")) is not None
                else None
            )
            debug_input_file = (
                Path(str(runtime_context.get("debug_input_file")))
                if _clean_text(runtime_context.get("debug_input_file")) is not None
                else None
            )
            input_payload = _load_json_value(input_file) if input_file is not None else None
            input_text = _safe_read_text(input_file) if input_file is not None else ""
            debug_input_payload = (
                _load_json_value(debug_input_file) if debug_input_file is not None else None
            )
            debug_input_text = (
                _safe_read_text(debug_input_file) if debug_input_file is not None else ""
            )
            exported_input_file = None
            exported_debug_input_file = None
            if input_file is not None and input_file.exists():
                exported_input_file = phase_export_dir / "in" / input_file.name
                _copy_prompt_artifact_file(source=input_file, target=exported_input_file)
            if debug_input_file is not None and debug_input_file.exists():
                exported_debug_input_file = phase_export_dir / "debug" / debug_input_file.name
                _copy_prompt_artifact_file(
                    source=debug_input_file,
                    target=exported_debug_input_file,
                )

            detail_lines.append(f"INPUT {spec['stage_key']} => {prompt_file.name}")
            if exported_input_file is not None:
                detail_lines.append(f"task_file: {exported_input_file}")
            if exported_debug_input_file is not None:
                detail_lines.append(f"debug_task_file: {exported_debug_input_file}")
            detail_lines.append("-" * 80)
            detail_lines.append(prompt_text)
            detail_lines.append("-" * 80)
            detail_lines.append("")
            if response_file.exists():
                detail_lines.append(f"OUTPUT {spec['stage_key']} => {response_file.name}")
                detail_lines.append("-" * 80)
                detail_lines.append(response_text)
                detail_lines.append("-" * 80)
                detail_lines.append("")
            if parsed_file.exists():
                detail_lines.append(f"PARSED {spec['stage_key']} => {parsed_file.name}")
                detail_lines.append("-" * 80)
                detail_lines.append(_safe_read_text(parsed_file))
                detail_lines.append("-" * 80)
                detail_lines.append("")

            batch_payload = batches_by_prompt_index.get(prompt_index, {})
            attempts = batch_payload.get("attempts")
            attempt_payload = attempts[0] if isinstance(attempts, list) and attempts else {}
            process_run_payload = (
                attempt_payload.get("process_run")
                if isinstance(attempt_payload, dict)
                else {}
            )
            if not isinstance(process_run_payload, dict):
                process_run_payload = {}
            process_payload = process_run_payload.get("process_payload")
            if not isinstance(process_payload, dict):
                process_payload = {}
            pipeline_id = (
                _clean_text(process_run_payload.get("pipeline_id"))
                or _clean_text(process_payload.get("pipeline_id"))
                or _clean_text((runtime_index or {}).get("pipeline_id"))
                or _clean_text(telemetry_summary.get("codex_farm_pipeline_id"))
                or "line-role.canonical.v1"
            )
            model_value = _clean_text(process_payload.get("codex_model"))
            reasoning_effort_value = _clean_text(process_payload.get("codex_reasoning_effort"))
            output_schema_path = (
                _clean_text(process_run_payload.get("output_schema_path"))
                or _clean_text(process_payload.get("output_schema_path"))
            )
            response_format_payload: dict[str, Any] | None = None
            if output_schema_path is not None:
                output_schema_payload = _load_json_dict(Path(output_schema_path))
                if isinstance(output_schema_payload, dict):
                    response_format_payload = {
                        "type": "json_schema",
                        "json_schema": output_schema_payload,
                    }

            usage_payload = (
                attempt_payload.get("usage")
                if isinstance(attempt_payload, dict)
                and isinstance(attempt_payload.get("usage"), dict)
                else {}
            )
            if not isinstance(usage_payload, dict):
                usage_payload = {}
            timestamp_utc = _timestamp_utc_for_path(prompt_file)
            call_id = f"{spec['prompt_stem']}_{prompt_index:04d}"
            request_messages = [{"role": "user", "content": prompt_text}]
            row_payload = {
                "run_id": eval_output_dir.name,
                "schema_version": PROMPT_CALL_RECORD_SCHEMA_VERSION,
                "call_id": call_id,
                "timestamp_utc": timestamp_utc,
                "recipe_id": f"{phase_key}_{prompt_index:04d}",
                "source_file": source_file,
                "pipeline_id": pipeline_id,
                "stage_key": spec["stage_key"],
                "stage_heading_key": spec["stage_key"],
                "stage_label": spec["stage_label"],
                "stage_artifact_stem": spec["stage_artifact_stem"],
                "stage_dir_name": "line-role-pipeline",
                "stage_order": spec["stage_order"],
                "process_run_id": _clean_text(process_payload.get("run_id")),
                "model": model_value,
                "prompt_input_mode": (
                    _clean_text(runtime_telemetry_row.get("prompt_input_mode")) or "path"
                ),
                "request_payload_source": "line_role_saved_prompt_text",
                "request_messages": request_messages,
                "system_prompt": None,
                "developer_prompt": None,
                "user_prompt": prompt_text,
                "rendered_prompt_text": prompt_text,
                "rendered_messages": request_messages,
                "prompt_templates": {
                    "prompt_template_text": None,
                    "prompt_template_path": None,
                },
                "template_vars": {
                    "INPUT_PATH": str(exported_input_file) if exported_input_file is not None else None,
                    "INPUT_TEXT": input_text or None,
                },
                "inserted_context_blocks": [],
                "request": {
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
                    "sandbox": None,
                    "ask_for_approval": None,
                    "web_search": None,
                    "output_schema_path": output_schema_path,
                },
                "request_input_payload": input_payload,
                "request_input_text": input_text or None,
                "debug_input_payload": debug_input_payload,
                "debug_input_text": debug_input_text or None,
                "task_prompt_text": input_text or None,
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
                    "output_text": response_text or None,
                    "output_file": str(exported_response_file) if response_file.exists() else None,
                },
                "parsed_response": parsed_response,
                "request_input_file": (
                    str(exported_input_file)
                    if exported_input_file is not None
                    else None
                ),
                "debug_input_file": (
                    str(exported_debug_input_file)
                    if exported_debug_input_file is not None
                    else None
                ),
                "request_telemetry": {
                    "status": (
                        _clean_text(process_payload.get("status"))
                        or _clean_text(runtime_telemetry_row.get("status"))
                    ),
                    "duration_ms": _coerce_int(runtime_telemetry_row.get("duration_ms")),
                    "attempt_index": _coerce_int(attempt_payload.get("attempt_index")),
                    "prompt_index": prompt_index,
                    "candidate_count": _coerce_int(batch_payload.get("candidate_count")),
                    "requested_atomic_indices": list(batch_payload.get("requested_atomic_indices") or []),
                    "returncode": _coerce_int(attempt_payload.get("returncode")),
                    "response_present": _coerce_bool(attempt_payload.get("response_present")),
                    "turn_failed_message": (
                        _clean_text(attempt_payload.get("turn_failed_message"))
                        or _clean_text(runtime_telemetry_row.get("turn_failed_message"))
                    ),
                    "tokens_input": (
                        _coerce_int(usage_payload.get("tokens_input"))
                        or _coerce_int(runtime_telemetry_row.get("tokens_input"))
                    ),
                    "tokens_cached_input": (
                        _coerce_int(usage_payload.get("tokens_cached_input"))
                        or _coerce_int(runtime_telemetry_row.get("tokens_cached_input"))
                    ),
                    "tokens_output": (
                        _coerce_int(usage_payload.get("tokens_output"))
                        or _coerce_int(runtime_telemetry_row.get("tokens_output"))
                    ),
                    "tokens_reasoning": (
                        _coerce_int(usage_payload.get("tokens_reasoning"))
                        or _coerce_int(runtime_telemetry_row.get("tokens_reasoning"))
                    ),
                    "tokens_total": (
                        _coerce_int(usage_payload.get("tokens_total"))
                        or _coerce_int(runtime_telemetry_row.get("tokens_total"))
                    ),
                    "worker_id": runtime_context.get("runtime_worker_id"),
                    "shard_id": runtime_context.get("runtime_shard_id"),
                    "owned_ids": list(runtime_context.get("runtime_owned_ids") or []),
                    "events_path": _clean_text(runtime_telemetry_row.get("events_path"))
                    or _clean_text(process_payload.get("events_path")),
                    "last_message_path": _clean_text(
                        runtime_telemetry_row.get("last_message_path")
                    )
                    or _clean_text(process_payload.get("last_message_path")),
                    "usage_path": _clean_text(runtime_telemetry_row.get("usage_path"))
                    or _clean_text(process_payload.get("usage_path")),
                    "live_status_path": _clean_text(
                        runtime_telemetry_row.get("live_status_path")
                    )
                    or _clean_text(process_payload.get("live_status_path")),
                    "workspace_manifest_path": _clean_text(
                        runtime_telemetry_row.get("workspace_manifest_path")
                    )
                    or _clean_text(process_payload.get("workspace_manifest_path")),
                    "stdout_path": _clean_text(runtime_telemetry_row.get("stdout_path"))
                    or _clean_text(process_payload.get("stdout_path")),
                    "stderr_path": _clean_text(runtime_telemetry_row.get("stderr_path"))
                    or _clean_text(process_payload.get("stderr_path")),
                },
                "runtime_shard_id": runtime_context.get("runtime_shard_id"),
                "runtime_worker_id": runtime_context.get("runtime_worker_id"),
                "runtime_owned_ids": list(runtime_context.get("runtime_owned_ids") or []),
                "activity_trace": None,
            }
            activity_trace_payload = _export_prompt_activity_trace(
                row_payload=row_payload,
                prompts_dir=prompts_dir,
                repo_root=repo_root,
            )
            row_payload["activity_trace"] = activity_trace_payload
            if (
                isinstance(activity_trace_payload, dict)
                and isinstance(row_payload.get("request_telemetry"), dict)
            ):
                row_payload["request_telemetry"]["activity_trace_path"] = (
                    activity_trace_payload.get("path")
                )
            if parsed_file.exists():
                row_payload["parsed_response_file"] = str(exported_parsed_file)
            rows.append(row_payload)

    if not rows:
        return [], None

    category_path = prompts_dir / "prompt_line_role.txt"
    category_path.write_text("\n".join(detail_lines).rstrip() + "\n", encoding="utf-8")
    return rows, str(category_path)


def _append_line_role_prompt_artifacts(
    *,
    pred_run: Path,
    eval_output_dir: Path,
    repo_root: Path,
) -> Path | None:
    prompts_dir = eval_output_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_response_log_path = prompts_dir / "prompt_request_response_log.txt"
    full_prompt_log_path = prompts_dir / "full_prompt_log.jsonl"
    prompt_type_samples_path = prompts_dir / PROMPT_TYPE_SAMPLES_MD_NAME
    category_manifest_path = prompts_dir / "prompt_category_logs_manifest.txt"

    line_role_rows, category_path = _build_line_role_prompt_rows(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
        repo_root=repo_root,
    )
    if not line_role_rows:
        return None

    existing_rows = [
        row
        for row in _load_prompt_rows(full_prompt_log_path)
        if str(row.get("stage_key") or "")
        != "line_role"
    ]
    merged_rows = sorted(existing_rows + line_role_rows, key=_prompt_row_sort_key)
    full_prompt_log_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in merged_rows
        ),
        encoding="utf-8",
    )

    section_lines: list[str] = []
    for row in line_role_rows:
        call_id = str(row.get("call_id") or "")
        stage_key = str(row.get("stage_key") or "line_role")
        request_input_file = _clean_text(row.get("request_input_file"))
        debug_input_file = _clean_text(row.get("debug_input_file"))
        raw_response = row.get("raw_response")
        response_file = (
            _clean_text(raw_response.get("output_file"))
            if isinstance(raw_response, dict)
            else None
        )
        rendered_prompt_text = str(row.get("rendered_prompt_text") or "")
        response_text = (
            str(raw_response.get("output_text") or "")
            if isinstance(raw_response, dict)
            else ""
        )
        section_lines.append(f"INPUT {stage_key} => {call_id}")
        if request_input_file is not None:
            section_lines.append(f"path: {request_input_file}")
        if debug_input_file is not None:
            section_lines.append(f"debug_path: {debug_input_file}")
        section_lines.append("-" * 80)
        section_lines.append(rendered_prompt_text)
        section_lines.append("-" * 80)
        section_lines.append("")
        if response_text:
            section_lines.append(f"OUTPUT {stage_key} => {call_id}")
            if response_file is not None:
                section_lines.append(f"path: {response_file}")
            section_lines.append("-" * 80)
            section_lines.append(response_text)
            section_lines.append("-" * 80)
            section_lines.append("")
    _upsert_text_section(
        path=prompt_response_log_path,
        start_marker="=== LINE_ROLE INTERACTIONS :: BEGIN ===",
        end_marker="=== LINE_ROLE INTERACTIONS :: END ===",
        body="\n".join(section_lines).rstrip(),
    )

    manifest_lines: list[str] = []
    if category_manifest_path.exists() and category_manifest_path.is_file():
        manifest_lines = [
            line.strip()
            for line in category_manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if category_path is not None and category_path not in manifest_lines:
        manifest_lines.append(category_path)
        stage_order_by_manifest_path = {
            str(prompts_dir / "prompt_recipe_llm_correct_and_link.txt"): 1,
            str(prompts_dir / "prompt_line_role.txt"): 2,
            str(prompts_dir / "prompt_nonrecipe_knowledge_review.txt"): 4,
        }
        manifest_lines.sort(
            key=lambda path: (
                stage_order_by_manifest_path.get(path, 999),
                path,
            )
        )
        category_manifest_path.write_text(
            "\n".join(manifest_lines).rstrip() + "\n",
            encoding="utf-8",
        )

    build_codex_farm_prompt_type_samples_markdown(
        full_prompt_log_path=full_prompt_log_path,
        output_path=prompt_type_samples_path,
        examples_per_pass=3,
    )
    return prompt_response_log_path


def render_prompt_artifacts_from_descriptors(
    *,
    pred_run: Path,
    eval_output_dir: Path,
    repo_root: Path,
    run_descriptors: Sequence[PromptRunDescriptor],
) -> Path | None:
    if not run_descriptors:
        return None

    prompts_dir = eval_output_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_response_log_path = prompts_dir / "prompt_request_response_log.txt"
    full_prompt_log_path = prompts_dir / "full_prompt_log.jsonl"
    prompt_type_samples_path = prompts_dir / PROMPT_TYPE_SAMPLES_MD_NAME

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
    lines: list[str] = []
    category_lines: dict[str, list[str]] = {}
    category_has_payload: dict[str, bool] = {}
    category_stage_metadata: dict[str, dict[str, Any]] = {}

    with full_prompt_log_path.open("w", encoding="utf-8") as full_prompt_log_handle:
        for run_descriptor in sorted(run_descriptors, key=lambda row: row.run_dir.name):
            run_dir = run_descriptor.run_dir
            manifest_payload_by_name = run_descriptor.manifest_payload_by_name
            manifest_path_by_name = run_descriptor.manifest_path_by_name
            if not manifest_payload_by_name:
                lines.append(f"=== SKIP: missing pass manifests in {run_dir} ===")
                continue

            lines.append(f"=== CODexFarm run: {run_dir.name} ===")
            if manifest_path_by_name:
                lines.append("manifests:")
                for manifest_name in sorted(manifest_path_by_name):
                    lines.append(f"- {manifest_path_by_name[manifest_name]}")
            primary_manifest = manifest_payload_by_name.get(RECIPE_MANIFEST_FILE_NAME, {})
            llm_enabled = primary_manifest.get("enabled")
            if llm_enabled is not None:
                lines.append(f"enabled: {llm_enabled}")
            if run_descriptor.codex_farm_pipeline:
                lines.append(f"pipeline: {run_descriptor.codex_farm_pipeline}")
            if run_descriptor.codex_farm_model:
                lines.append(f"codex_farm_model: {run_descriptor.codex_farm_model}")
            codex_reasoning_effort = run_descriptor.codex_farm_reasoning_effort
            lines.append("")

            telemetry_rows_by_manifest_name: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
            telemetry_csv_by_manifest_name: dict[str, dict[str, str]] = {}
            for manifest_name, manifest_payload in manifest_payload_by_name.items():
                rows_by_run_id, csv_by_run_id = _load_codex_exec_rows_for_manifest(
                    manifest_payload,
                    repo_root=repo_root,
                )
                telemetry_rows_by_manifest_name[manifest_name] = rows_by_run_id
                telemetry_csv_by_manifest_name[manifest_name] = csv_by_run_id

            process_run_stages = [
                stage
                for stage in run_descriptor.stages
                if isinstance(stage.process_run_payload, dict)
            ]
            if process_run_stages:
                lines.append("--- PROCESS RUN PAYLOAD SNIPPETS ---")
                for stage in process_run_stages:
                    lines.append(f"--- process_run[{stage.stage_key}] ({stage.manifest_name}) ---")
                    try:
                        lines.append(json.dumps(stage.process_run_payload, indent=2, sort_keys=True))
                    except Exception:
                        lines.append(str(stage.process_run_payload))
                lines.append("")

            for stage in run_descriptor.stages:
                category_key = stage.stage_key
                category_lines.setdefault(category_key, [])
                category_has_payload.setdefault(category_key, False)
                runtime_stage_root = None
                if stage.stage_key == "recipe_llm_correct_and_link":
                    runtime_stage_root = run_dir / "recipe_phase_runtime"
                elif stage.stage_key == "nonrecipe_knowledge_review":
                    runtime_stage_root = run_dir / "knowledge"
                runtime_index = (
                    _load_phase_runtime_index(runtime_stage_root)
                    if isinstance(runtime_stage_root, Path)
                    else {}
                )

                pass_assets = _load_run_assets_for_process_run(
                    process_run_payload=stage.process_run_payload,
                    repo_root=repo_root,
                )
                process_run_id = _clean_text(pass_assets.get("run_id"))
                telemetry_rows_by_run_id = telemetry_rows_by_manifest_name.get(stage.manifest_name, {})
                telemetry_csv_by_run_id = telemetry_csv_by_manifest_name.get(stage.manifest_name, {})
                pass_telemetry_rows = (
                    telemetry_rows_by_run_id.get(process_run_id, {})
                    if process_run_id is not None
                    else {}
                )

                stage_metadata = {
                    "stage_order": stage.stage_order,
                    "pipeline_id": stage.pipeline_id,
                    "stage_key": stage.stage_key,
                    "heading_key": stage.stage_heading_key,
                    "label": stage.stage_label,
                    "artifact_stem": stage.stage_artifact_stem,
                    "path_root": stage.stage_dir_name,
                }
                category_stage_metadata[category_key] = dict(stage_metadata)

                category = category_lines[category_key]
                category.append(
                    "=== CATEGORY "
                    f"{stage.stage_key} ({stage.stage_heading_key} / {stage.stage_label}) "
                    f"| stage_dir: {stage.stage_dir_name} | run: {run_dir.name} ==="
                )
                if stage.manifest_path is not None:
                    category.append(f"manifest: {stage.manifest_path}")
                if stage.pipeline_id is not None:
                    category.append(f"pipeline_id: {stage.pipeline_id}")
                category.append("")

                input_files = _files_in_dir(stage.input_dir)
                lines.append(f"--- {stage.stage_key.upper()} INPUT FILES ---")
                lines.append(f"source_dir: {stage.input_dir}")
                category.append(f"--- {stage.stage_key.upper()} PROMPT INPUT FILES ---")
                category.append(f"source_dir: {stage.input_dir}")
                for prompt_file in input_files:
                    category_has_payload[category_key] = True
                    lines.append(f"INPUT {stage.stage_key} => {prompt_file.name}")
                    lines.append("-" * 80)
                    prompt_text = _safe_read_text(prompt_file)
                    lines.append(prompt_text)
                    lines.append("-" * 80)
                    lines.append("")

                    category.append(f"INPUT {stage.stage_key} => {prompt_file.name}")
                    category.append("-" * 80)
                    category.append(prompt_text)
                    category.append("-" * 80)
                    category.append("")

                    payload = _parse_json_text(prompt_text)
                    attachment_paths = _collect_prompt_attachments(
                        payload,
                        prompt_file=prompt_file,
                        pred_run=pred_run,
                    )
                    if attachment_paths:
                        category.append(
                            f"--- ATTACHMENT FILES REFERENCED BY {prompt_file.name} ---"
                        )
                        for attachment_path in attachment_paths:
                            category.append(f"ATTACHMENT {stage.stage_key} => {attachment_path}")
                            category.append("-" * 80)
                            category.append(_safe_read_text(attachment_path))
                            category.append("-" * 80)
                            category.append("")

                output_files = _files_in_dir(stage.output_dir)
                lines.append(f"--- {stage.stage_key.upper()} RESPONSE FILES ---")
                lines.append(f"source_dir: {stage.output_dir}")
                category.append(f"--- {stage.stage_key.upper()} PROMPT RESPONSE FILES ---")
                category.append(f"source_dir: {stage.output_dir}")
                for response_file in output_files:
                    category_has_payload[category_key] = True
                    lines.append(f"OUTPUT {stage.stage_key} => {response_file.name}")
                    lines.append("-" * 80)
                    response_text = _safe_read_text(response_file)
                    lines.append(response_text)
                    lines.append("-" * 80)
                    lines.append("")
                    category.append(f"OUTPUT {stage.stage_key} => {response_file.name}")
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
                    runtime_context = _resolve_runtime_context(
                        runtime_index=runtime_index,
                        shard_id=(
                            _clean_text(_coerce_dict(parsed_input).get("bid"))
                            or _clean_text(_coerce_dict(parsed_input).get("bundle_id"))
                            or _clean_text(_coerce_dict(parsed_input).get("shard_id"))
                            or _clean_text(_coerce_dict(parsed_output).get("bid"))
                            or _clean_text(_coerce_dict(parsed_output).get("bundle_id"))
                            or _clean_text(_coerce_dict(parsed_output).get("shard_id"))
                            or (
                                call_stem
                                if stage.stage_key == "nonrecipe_knowledge_review"
                                else None
                            )
                        ),
                        owned_id=recipe_id,
                    )
                    runtime_telemetry_row = (
                        dict(runtime_context.get("runtime_telemetry_row"))
                        if isinstance(runtime_context.get("runtime_telemetry_row"), dict)
                        else {}
                    )
                    if telemetry_row is None and runtime_telemetry_row:
                        telemetry_row = runtime_telemetry_row
                    if telemetry_timestamp_utc is None and runtime_telemetry_row:
                        telemetry_timestamp_utc = (
                            _clean_text(runtime_telemetry_row.get("finished_at_utc"))
                            or _clean_text(runtime_telemetry_row.get("logged_at_utc"))
                        )
                    if telemetry_output_path is None and runtime_telemetry_row:
                        output_path_text = _clean_text(runtime_telemetry_row.get("output_path"))
                        if output_path_text is not None:
                            telemetry_output_path = Path(output_path_text)
                    timestamp_utc = (
                        telemetry_timestamp_utc
                        or _timestamp_utc_for_path(output_file)
                        or _timestamp_utc_for_path(input_file)
                    )

                    rendered_prompt_text = _render_prompt_text(
                        template_text=pass_assets.get("prompt_template_text")
                        if isinstance(pass_assets, dict)
                        else None,
                        input_text=input_text,
                        input_file=(input_file or (stage.input_dir / file_name)),
                    )
                    request_payload_source = "reconstructed_from_prompt_template"
                    if telemetry_prompt_text:
                        rendered_prompt_text = telemetry_prompt_text
                        request_payload_source = "telemetry_csv"
                    elif runtime_telemetry_row.get("prompt_text"):
                        rendered_prompt_text = str(runtime_telemetry_row.get("prompt_text"))
                        request_payload_source = "runtime_telemetry"
                    request_messages = [{"role": "user", "content": rendered_prompt_text}]

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
                        model_candidate = str(effective_pipeline_payload.get("codex_model") or "").strip()
                        if model_candidate:
                            model_value = model_candidate
                    if model_value is None and run_descriptor.codex_farm_model:
                        model_value = run_descriptor.codex_farm_model
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
                        "pipeline_id": stage.pipeline_id,
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
                        usage_payload = _parse_json_text(str(telemetry_row.get("usage_json") or ""))
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
                            "execution_attempt_index": _coerce_int(telemetry_row.get("execution_attempt_index")),
                            "lease_claim_index": _coerce_int(telemetry_row.get("lease_claim_index")),
                            "input_path": _clean_text(telemetry_row.get("input_path")),
                            "output_path": _clean_text(telemetry_row.get("output_path")),
                            "prompt_chars": _coerce_int(telemetry_row.get("prompt_chars")),
                            "prompt_sha256": _clean_text(telemetry_row.get("prompt_sha256")),
                            "output_bytes": _coerce_int(telemetry_row.get("output_bytes")),
                            "output_sha256": _clean_text(telemetry_row.get("output_sha256")),
                            "output_payload_present": _coerce_bool(telemetry_row.get("output_payload_present")),
                            "output_preview_chars": _coerce_int(telemetry_row.get("output_preview_chars")),
                            "output_preview_truncated": _coerce_bool(telemetry_row.get("output_preview_truncated")),
                            "output_preview": telemetry_row.get("output_preview"),
                            "tokens_input": _coerce_int(telemetry_row.get("tokens_input")),
                            "tokens_cached_input": _coerce_int(telemetry_row.get("tokens_cached_input")),
                            "tokens_output": _coerce_int(telemetry_row.get("tokens_output")),
                            "tokens_reasoning": _coerce_int(telemetry_row.get("tokens_reasoning")),
                            "tokens_total": _coerce_int(telemetry_row.get("tokens_total")),
                            "usage_json": usage_payload,
                            "model": telemetry_model,
                            "reasoning_effort": telemetry_reasoning_effort,
                            "sandbox": telemetry_sandbox,
                            "ask_for_approval": telemetry_ask_for_approval,
                            "web_search": telemetry_web_search,
                            "output_schema_path": telemetry_output_schema_path,
                            "worker_id": runtime_context.get("runtime_worker_id"),
                            "shard_id": runtime_context.get("runtime_shard_id"),
                            "owned_ids": list(runtime_context.get("runtime_owned_ids") or []),
                            "events_path": _clean_text(telemetry_row.get("events_path")),
                            "last_message_path": _clean_text(telemetry_row.get("last_message_path")),
                            "usage_path": _clean_text(telemetry_row.get("usage_path")),
                            "live_status_path": _clean_text(telemetry_row.get("live_status_path")),
                            "workspace_manifest_path": _clean_text(
                                telemetry_row.get("workspace_manifest_path")
                            ),
                            "stdout_path": _clean_text(telemetry_row.get("stdout_path")),
                            "stderr_path": _clean_text(telemetry_row.get("stderr_path")),
                        }

                    row_payload = {
                        "run_id": benchmark_run_id,
                        "schema_version": PROMPT_CALL_RECORD_SCHEMA_VERSION,
                        "call_id": call_stem,
                        "timestamp_utc": timestamp_utc,
                        "recipe_id": recipe_id,
                        "source_file": source_file,
                        "pipeline_id": stage.pipeline_id,
                        "stage_key": stage.stage_key,
                        "stage_heading_key": stage.stage_heading_key,
                        "stage_label": stage.stage_label,
                        "stage_artifact_stem": stage.stage_artifact_stem,
                        "stage_dir_name": stage.stage_dir_name,
                        "stage_order": stage.stage_order,
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
                        "runtime_shard_id": runtime_context.get("runtime_shard_id"),
                        "runtime_worker_id": runtime_context.get("runtime_worker_id"),
                        "runtime_owned_ids": list(runtime_context.get("runtime_owned_ids") or []),
                        "activity_trace": None,
                    }
                    activity_trace_payload = _export_prompt_activity_trace(
                        row_payload=row_payload,
                        prompts_dir=prompts_dir,
                        repo_root=repo_root,
                    )
                    row_payload["activity_trace"] = activity_trace_payload
                    if (
                        isinstance(activity_trace_payload, dict)
                        and isinstance(request_telemetry, dict)
                    ):
                        request_telemetry["activity_trace_path"] = activity_trace_payload.get(
                            "path"
                        )
                    full_prompt_log_handle.write(
                        json.dumps(
                            PromptCallRecord(
                                schema_version=PROMPT_CALL_RECORD_SCHEMA_VERSION,
                                row=row_payload,
                            ).to_row(),
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    full_prompt_log_rows += 1

    if not lines:
        full_prompt_log_path.unlink(missing_ok=True)
        prompt_type_samples_path.unlink(missing_ok=True)
        return None

    prompt_response_log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    category_manifest_lines: list[str] = []
    category_sort_keys = sorted(
        category_stage_metadata.keys(),
        key=lambda key: (
            int(category_stage_metadata.get(key, {}).get("stage_order") or 999),
            key,
        ),
    )
    for category_key in category_sort_keys:
        if not category_has_payload.get(category_key):
            continue
        metadata = category_stage_metadata.get(category_key) or {}
        category_path = prompts_dir / f"prompt_{slugify_name(category_key)}.txt"
        category_path.write_text(
            "\n".join(category_lines.get(category_key, [])) + "\n",
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
        build_codex_farm_prompt_type_samples_markdown(
            full_prompt_log_path=full_prompt_log_path,
            output_path=prompt_type_samples_path,
            examples_per_pass=3,
        )

    return prompt_response_log_path


def build_codex_farm_prompt_response_log(
    *,
    pred_run: Path,
    eval_output_dir: Path,
    repo_root: Path | None = None,
    run_descriptors: Sequence[PromptRunDescriptor] | None = None,
) -> Path | None:
    return build_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
        repo_root=repo_root,
        run_descriptors=run_descriptors,
        discoverers=(discover_codexfarm_prompt_run_descriptors,),
    )


def build_prompt_response_log(
    *,
    pred_run: Path,
    eval_output_dir: Path,
    repo_root: Path | None = None,
    run_descriptors: Sequence[PromptRunDescriptor] | None = None,
    discoverers: Sequence[PromptRunDescriptorDiscoverer] | None = None,
) -> Path | None:
    resolved_repo_root = (
        repo_root.resolve(strict=False)
        if isinstance(repo_root, Path)
        else Path.cwd().resolve()
    )
    prompts_dir = eval_output_dir / "prompts"
    activity_traces_dir = prompts_dir / ACTIVITY_TRACES_DIR_NAME
    if activity_traces_dir.exists() and activity_traces_dir.is_dir():
        shutil.rmtree(activity_traces_dir)
    discovered = (
        list(run_descriptors)
        if run_descriptors is not None
        else discover_prompt_run_descriptors(pred_run=pred_run, discoverers=discoverers)
    )
    prompt_log_path = render_prompt_artifacts_from_descriptors(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
        repo_root=resolved_repo_root,
        run_descriptors=discovered,
    )
    line_role_prompt_log_path = _append_line_role_prompt_artifacts(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
        repo_root=resolved_repo_root,
    )
    full_prompt_log_path = prompts_dir / "full_prompt_log.jsonl"
    prompt_log_summary_path = prompts_dir / PROMPT_LOG_SUMMARY_JSON_NAME
    activity_trace_summary_jsonl_path = prompts_dir / ACTIVITY_TRACE_SUMMARY_JSONL_NAME
    activity_trace_summary_md_path = prompts_dir / ACTIVITY_TRACE_SUMMARY_MD_NAME
    if full_prompt_log_path.exists() and full_prompt_log_path.is_file():
        write_prompt_log_summary(
            full_prompt_log_path=full_prompt_log_path,
            output_path=prompt_log_summary_path,
        )
        build_codex_farm_activity_trace_summaries(
            full_prompt_log_path=full_prompt_log_path,
            output_jsonl_path=activity_trace_summary_jsonl_path,
            output_md_path=activity_trace_summary_md_path,
        )
    else:
        prompt_log_summary_path.unlink(missing_ok=True)
        activity_trace_summary_jsonl_path.unlink(missing_ok=True)
        activity_trace_summary_md_path.unlink(missing_ok=True)
    return prompt_log_path or line_role_prompt_log_path


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
    "discover_codexfarm_prompt_run_descriptors",
    "render_prompt_artifacts_from_descriptors",
    "summarize_prompt_log",
    "write_prompt_log_summary",
]
