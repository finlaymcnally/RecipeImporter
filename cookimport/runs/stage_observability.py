from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1


STAGE_OBSERVABILITY_SCHEMA_VERSION = "stage_observability.v1"
RECIPE_MANIFEST_FILE_NAME = "recipe_manifest.json"
KNOWLEDGE_MANIFEST_FILE_NAME = "knowledge_manifest.json"


class StageWorkbookObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workbook_slug: str
    pipeline_id: str | None = None
    manifest_path: str | None = None
    stage_dir: str | None = None
    input_dir: str | None = None
    output_dir: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class ObservedStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_key: str
    stage_label: str
    stage_artifact_stem: str
    stage_family: str
    stage_order: int
    workbooks: list[StageWorkbookObservation] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class StageObservabilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = STAGE_OBSERVABILITY_SCHEMA_VERSION
    run_kind: str
    run_id: str
    created_at: str
    stages: list[ObservedStage] = Field(default_factory=list)


_STAGE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "label_det": {
        "label": "Deterministic Labels",
        "artifact_stem": "label_det",
        "family": "label_stage",
        "order": 5,
    },
    "label_llm_correct": {
        "label": "Label LLM Correction",
        "artifact_stem": "label_llm_correct",
        "family": "label_stage",
        "order": 6,
    },
    "group_recipe_spans": {
        "label": "Group Recipe Spans",
        "artifact_stem": "group_recipe_spans",
        "family": "label_stage",
        "order": 7,
    },
    "classify_nonrecipe": {
        "label": "Classify Non-Recipe",
        "artifact_stem": "classify_nonrecipe",
        "family": "deterministic",
        "order": 8,
    },
    "build_intermediate_det": {
        "label": "Build Intermediate Recipe",
        "artifact_stem": "build_intermediate_det",
        "family": "recipe_deterministic",
        "order": 10,
    },
    "recipe_llm_correct_and_link": {
        "label": "Recipe LLM Correction",
        "artifact_stem": "recipe_correction",
        "family": "recipe_llm",
        "order": 20,
    },
    "build_final_recipe": {
        "label": "Build Final Recipe",
        "artifact_stem": "build_final_recipe",
        "family": "recipe_deterministic",
        "order": 30,
    },
    "extract_knowledge_optional": {
        "label": "Non-Recipe Knowledge Review",
        "artifact_stem": "knowledge",
        "family": "knowledge_llm",
        "order": 40,
    },
    "write_outputs": {
        "label": "Write Outputs",
        "artifact_stem": "write_outputs",
        "family": "deterministic",
        "order": 90,
    },
}


def stage_label(stage_key: str) -> str:
    definition = _STAGE_DEFINITIONS.get(stage_key, {})
    return str(definition.get("label") or stage_key.replace("_", " ").title())


def stage_artifact_stem(stage_key: str) -> str:
    definition = _STAGE_DEFINITIONS.get(stage_key, {})
    return str(definition.get("artifact_stem") or stage_key)


def stage_order(stage_key: str) -> int:
    definition = _STAGE_DEFINITIONS.get(stage_key, {})
    try:
        return int(definition.get("order") or 999)
    except (TypeError, ValueError):
        return 999


def stage_family(stage_key: str) -> str:
    definition = _STAGE_DEFINITIONS.get(stage_key, {})
    return str(definition.get("family") or "stage")


def recipe_stage_keys_for_pipeline(pipeline_id: str | None) -> tuple[str, ...]:
    normalized = str(pipeline_id or "").strip()
    if normalized == RECIPE_CODEX_FARM_PIPELINE_SHARD_V1:
        return (
            "build_intermediate_det",
            "recipe_llm_correct_and_link",
            "build_final_recipe",
        )
    return ()


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _relative_to(run_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(run_root))
    except ValueError:
        return str(path)


def _path_from_manifest(value: Any) -> Path | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return Path(cleaned)


def _has_json_payloads(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return any(child.is_file() for child in path.iterdir())


def _recipe_stage_key_map(
    *,
    recipe_manifest_payload: Mapping[str, Any],
    workbook_dir: Path,
) -> tuple[str, ...]:
    pipeline_id = str(recipe_manifest_payload.get("pipeline") or "").strip() or None
    candidate_keys = list(recipe_stage_keys_for_pipeline(pipeline_id))
    if pipeline_id == RECIPE_CODEX_FARM_PIPELINE_SHARD_V1:
        return tuple(candidate_keys)
    if "final" in candidate_keys and not (workbook_dir / "final").exists():
        candidate_keys = [key for key in candidate_keys if key != "final"]
    return tuple(candidate_keys)


def build_stage_observability_report(
    *,
    run_root: Path,
    run_kind: str,
    created_at: str,
    run_config: Mapping[str, Any] | None = None,
) -> StageObservabilityReport:
    stage_rows: dict[str, ObservedStage] = {}

    raw_llm_root = run_root / "raw" / "llm"
    if raw_llm_root.exists() and raw_llm_root.is_dir():
        for workbook_dir in sorted(path for path in raw_llm_root.iterdir() if path.is_dir()):
            workbook_slug = workbook_dir.name
            recipe_manifest_path = workbook_dir / RECIPE_MANIFEST_FILE_NAME
            recipe_manifest_payload = _load_json_dict(recipe_manifest_path) or {}
            recipe_pipeline_id = str(recipe_manifest_payload.get("pipeline") or "").strip() or None
            recipe_paths = recipe_manifest_payload.get("paths")
            if not isinstance(recipe_paths, Mapping):
                recipe_paths = {}
            for key in _recipe_stage_key_map(
                recipe_manifest_payload=recipe_manifest_payload,
                workbook_dir=workbook_dir,
            ):
                if key == "recipe_llm_correct_and_link":
                    stage_dir = _path_from_manifest(
                        recipe_paths.get("recipe_phase_runtime_dir")
                    ) or (workbook_dir / "recipe_phase_runtime")
                    input_dir = _path_from_manifest(
                        recipe_paths.get("recipe_phase_input_dir")
                    ) or (stage_dir / "inputs")
                    output_dir = _path_from_manifest(
                        recipe_paths.get("recipe_phase_proposals_dir")
                    ) or (stage_dir / "proposals")
                else:
                    stage_dir = workbook_dir / stage_artifact_stem(key)
                    input_dir = stage_dir / "in"
                    output_dir = stage_dir / "out"
                if (
                    key == "recipe_llm_correct_and_link"
                    and not stage_dir.exists()
                    and not input_dir.exists()
                    and not output_dir.exists()
                ):
                    continue
                if key not in {
                    "build_intermediate_det",
                    "build_final_recipe",
                } and not stage_dir.exists() and not input_dir.exists() and not output_dir.exists():
                    continue
                stage_rows.setdefault(
                    key,
                    ObservedStage(
                        stage_key=key,
                        stage_label=stage_label(key),
                        stage_artifact_stem=stage_artifact_stem(key),
                        stage_family=stage_family(key),
                        stage_order=stage_order(key),
                    ),
                )
                workbook_observation = StageWorkbookObservation(
                    workbook_slug=workbook_slug,
                    pipeline_id=recipe_pipeline_id,
                    manifest_path=_relative_to(run_root, recipe_manifest_path)
                    if recipe_manifest_path.exists()
                    else None,
                    stage_dir=_relative_to(run_root, stage_dir) if stage_dir.exists() else None,
                    input_dir=_relative_to(run_root, input_dir) if input_dir.exists() else None,
                    output_dir=_relative_to(run_root, output_dir) if output_dir.exists() else None,
                )
                stage_rows[key].workbooks.append(workbook_observation)

            knowledge_manifest_path = workbook_dir / KNOWLEDGE_MANIFEST_FILE_NAME
            knowledge_manifest_payload = _load_json_dict(knowledge_manifest_path) or {}
            knowledge_paths = knowledge_manifest_payload.get("paths")
            if not isinstance(knowledge_paths, Mapping):
                knowledge_paths = {}
            knowledge_dir = workbook_dir / stage_artifact_stem("extract_knowledge_optional")
            knowledge_input_dir = _path_from_manifest(
                knowledge_paths.get("knowledge_in_dir")
            ) or (knowledge_dir / "in")
            knowledge_output_dir = _path_from_manifest(
                knowledge_paths.get("proposals_dir")
            ) or (knowledge_dir / "proposals")
            if knowledge_manifest_path.exists() or knowledge_dir.exists():
                key = "extract_knowledge_optional"
                stage_rows.setdefault(
                    key,
                    ObservedStage(
                        stage_key=key,
                        stage_label=stage_label(key),
                        stage_artifact_stem=stage_artifact_stem(key),
                        stage_family=stage_family(key),
                        stage_order=stage_order(key),
                    ),
                )
                stage_rows[key].workbooks.append(
                    StageWorkbookObservation(
                        workbook_slug=workbook_slug,
                        pipeline_id=str(knowledge_manifest_payload.get("pipeline_id") or "").strip()
                        or None,
                        manifest_path=_relative_to(run_root, knowledge_manifest_path)
                        if knowledge_manifest_path.exists()
                        else None,
                        stage_dir=_relative_to(run_root, knowledge_dir) if knowledge_dir.exists() else None,
                        input_dir=_relative_to(run_root, knowledge_input_dir)
                        if knowledge_input_dir.exists()
                        else None,
                        output_dir=_relative_to(run_root, knowledge_output_dir)
                        if knowledge_output_dir.exists()
                        else None,
                    )
                )


    write_outputs_paths: dict[str, str] = {}
    for stage_key in ("label_det", "label_llm_correct", "group_recipe_spans"):
        stage_dir = run_root / stage_artifact_stem(stage_key)
        if not stage_dir.exists() or not stage_dir.is_dir():
            continue
        stage_rows.setdefault(
            stage_key,
            ObservedStage(
                stage_key=stage_key,
                stage_label=stage_label(stage_key),
                stage_artifact_stem=stage_artifact_stem(stage_key),
                stage_family=stage_family(stage_key),
                stage_order=stage_order(stage_key),
            ),
        )
        for workbook_dir in sorted(path for path in stage_dir.iterdir() if path.is_dir()):
            artifact_paths = {
                path.name: _relative_to(run_root, path)
                for path in sorted(workbook_dir.iterdir())
                if path.is_file()
            }
            stage_rows[stage_key].workbooks.append(
                StageWorkbookObservation(
                    workbook_slug=workbook_dir.name,
                    stage_dir=_relative_to(run_root, workbook_dir),
                    artifact_paths={
                        key: value
                        for key, value in artifact_paths.items()
                        if value is not None
                    },
                )
            )
    nonrecipe_spans_path = run_root / "08_nonrecipe_spans.json"
    if nonrecipe_spans_path.exists():
        stage_key = "classify_nonrecipe"
        stage_rows.setdefault(
            stage_key,
            ObservedStage(
                stage_key=stage_key,
                stage_label=stage_label(stage_key),
                stage_artifact_stem=stage_artifact_stem(stage_key),
                stage_family=stage_family(stage_key),
                stage_order=stage_order(stage_key),
                artifact_paths={
                    "nonrecipe_spans_json": _relative_to(run_root, nonrecipe_spans_path) or ""
                },
            ),
        )
    knowledge_outputs_path = run_root / "09_knowledge_outputs.json"
    if knowledge_outputs_path.exists():
        stage_key = "extract_knowledge_optional"
        stage_rows.setdefault(
            stage_key,
            ObservedStage(
                stage_key=stage_key,
                stage_label=stage_label(stage_key),
                stage_artifact_stem=stage_artifact_stem(stage_key),
                stage_family=stage_family(stage_key),
                stage_order=stage_order(stage_key),
                artifact_paths={
                    "knowledge_outputs_json": _relative_to(run_root, knowledge_outputs_path) or ""
                },
            ),
        )
    for artifact_key, path_name in (
        ("intermediate_drafts_dir", "intermediate drafts"),
        ("final_drafts_dir", "final drafts"),
        ("tips_dir", "tips"),
        ("chunks_dir", "chunks"),
        ("knowledge_dir", "knowledge"),
        ("bench_dir", ".bench"),
        ("reports_glob", "*.excel_import_report.json"),
    ):
        if "*" in path_name:
            matches = sorted(run_root.glob(path_name))
            if matches:
                write_outputs_paths[artifact_key] = str(path_name)
            continue
        target = run_root / path_name
        if target.exists():
            write_outputs_paths[artifact_key] = path_name
    if write_outputs_paths or (run_config is not None and run_kind == "stage"):
        stage_rows.setdefault(
            "write_outputs",
            ObservedStage(
                stage_key="write_outputs",
                stage_label=stage_label("write_outputs"),
                stage_artifact_stem=stage_artifact_stem("write_outputs"),
                stage_family=stage_family("write_outputs"),
                stage_order=stage_order("write_outputs"),
                artifact_paths=write_outputs_paths,
            ),
        )

    report = StageObservabilityReport(
        run_kind=run_kind,
        run_id=run_root.name,
        created_at=created_at,
        stages=sorted(
            stage_rows.values(),
            key=lambda row: (row.stage_order, row.stage_key),
        ),
    )
    return report


def write_stage_observability_report(
    *,
    run_root: Path,
    report: StageObservabilityReport,
) -> Path:
    run_root.mkdir(parents=True, exist_ok=True)
    report_path = run_root / "stage_observability.json"
    tmp_path = run_root / "stage_observability.json.tmp"
    tmp_path.write_text(
        json.dumps(report.model_dump(exclude_none=True), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(report_path)
    return report_path


def load_stage_observability_report(path: Path) -> StageObservabilityReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Stage observability payload must be an object: {path}")
    return StageObservabilityReport.model_validate(payload)
