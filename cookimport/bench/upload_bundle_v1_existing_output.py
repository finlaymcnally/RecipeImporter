from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable

from cookimport.bench.upload_bundle_v1_model import UploadBundleSourceModel
from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
from cookimport.runs.stage_observability import (
    recipe_stage_keys_for_pipeline,
    stage_label,
)

CANONICAL_SINGLE_CORRECTION_RECIPE_PIPELINE_ID = RECIPE_CODEX_FARM_PIPELINE_SHARD_V1


@dataclass(frozen=True)
class ExistingOutputAdapterHelpers:
    load_json_object: Callable[[Path], dict[str, Any]]
    iter_jsonl: Callable[[Path], list[dict[str, Any]]]
    load_recipe_triage_rows: Callable[[Path], list[dict[str, Any]]]
    discover_run_dirs: Callable[[Path], list[Path]]
    build_run_record_from_existing_run: Callable[[Path], Any]
    build_comparison_summary: Callable[..., tuple[Any, ...]]
    coerce_int: Callable[[Any], int | None]
    source_file_name: Callable[[str | None], str]
    source_key: Callable[[str | None, str | None], str]
    select_starter_pack_recipe_cases: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    build_selected_recipe_packets: Callable[..., list[dict[str, Any]]]


def _record_attr(record: Any, field: str, default: Any = None) -> Any:
    return getattr(record, field, default)


def _is_codex_pipeline_enabled(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized not in {"", "off", "none", "false", "0"}


def _pipeline_id_text(value: Any) -> str:
    return str(value or "").strip()


def _semantic_recipe_stages() -> list[dict[str, str]]:
    return [
        {
            "stage_key": stage_key,
            "stage_label": stage_label(stage_key),
        }
        for stage_key in recipe_stage_keys_for_pipeline(
            CANONICAL_SINGLE_CORRECTION_RECIPE_PIPELINE_ID
        )
    ]


def _semantic_recipe_stage_call_counts(
    *,
    observed_correction_call_count: int,
    observed_final_recipe_build_count: int,
) -> dict[str, int]:
    correction_count = int(observed_correction_call_count)
    final_build_count = int(observed_final_recipe_build_count)
    return {
        "build_intermediate_det": max(correction_count, final_build_count),
        "recipe_llm_correct_and_link": correction_count,
        "build_final_recipe": final_build_count,
    }


def _load_json_object(path: Path) -> dict[str, Any] | None:
    payload = _load_json_value(path)
    return payload if isinstance(payload, dict) else None


def _load_json_value(path: Path) -> Any | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return payload


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
    except Exception:  # noqa: BLE001
        return []
    return rows


def _resolve_stage_run_dir(run_dir: Path) -> Path:
    candidate = run_dir.resolve(strict=False)
    if (candidate / "raw" / "llm").is_dir() or (candidate / "line-role-pipeline").is_dir():
        return candidate
    manifest_payload = _load_json_object(candidate / "run_manifest.json") or {}
    artifacts = manifest_payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return candidate
    for key in ("stage_run_dir", "processed_output_run_dir"):
        raw = str(artifacts.get(key) or "").strip()
        if not raw:
            continue
        resolved = Path(raw).expanduser().resolve(strict=False)
        if (resolved / "raw" / "llm").is_dir() or (resolved / "line-role-pipeline").is_dir():
            return resolved
    return candidate


def _distribution(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"count": 0, "min": 0, "max": 0, "avg": 0.0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": round(sum(values) / len(values), 3),
    }


def _load_runtime_stage_summary(stage_root: Path, *, stage_key: str) -> dict[str, Any] | None:
    phase_manifest = _load_json_object(stage_root / "phase_manifest.json") or {}
    if not phase_manifest:
        return None
    telemetry = _load_json_object(stage_root / "telemetry.json") or {}
    assignments_payload = _load_json_value(stage_root / "worker_assignments.json")
    assignments = assignments_payload if isinstance(assignments_payload, list) else []
    shard_rows = _load_jsonl_rows(stage_root / "shard_manifest.jsonl")
    return {
        "stage_key": stage_key,
        "pipeline_id": str(
            phase_manifest.get("pipeline_id") or telemetry.get("pipeline_id") or ""
        ),
        "worker_count": int(
            phase_manifest.get("worker_count") or telemetry.get("worker_count") or 0
        ),
        "fresh_agent_count": int(telemetry.get("fresh_agent_count") or 0),
        "shard_count": int(
            phase_manifest.get("shard_count") or telemetry.get("shard_count") or len(shard_rows)
        ),
        "owned_id_count": sum(len(row.get("owned_ids") or []) for row in shard_rows),
        "shards_per_worker": _distribution(
            [len(assignment.get("shard_ids") or []) for assignment in assignments if isinstance(assignment, dict)]
        ),
        "owned_ids_per_shard": _distribution(
            [len(row.get("owned_ids") or []) for row in shard_rows]
        ),
    }


def _summarize_runtime_stages_for_run(run_dir: Path) -> dict[str, Any]:
    stage_run_dir = _resolve_stage_run_dir(run_dir)
    runtime_rows: dict[str, Any] = {}
    for recipe_root in sorted((stage_run_dir / "raw" / "llm").glob("*/recipe_phase_runtime")):
        summary = _load_runtime_stage_summary(
            recipe_root,
            stage_key="recipe_llm_correct_and_link",
        )
        if summary is not None:
            runtime_rows["recipe_llm_correct_and_link"] = summary
            break
    for knowledge_root in sorted((stage_run_dir / "raw" / "llm").glob("*/knowledge")):
        summary = _load_runtime_stage_summary(
            knowledge_root,
            stage_key="nonrecipe_knowledge_review",
        )
        if summary is not None:
            runtime_rows["nonrecipe_knowledge_review"] = summary
            break
    line_role_summary = _load_runtime_stage_summary(
        stage_run_dir / "line-role-pipeline" / "runtime",
        stage_key="line_role",
    )
    if line_role_summary is not None:
        runtime_rows["line_role"] = line_role_summary
    return runtime_rows


def build_recipe_pipeline_topology_context(
    *,
    codex_recipe_pipelines: list[str] | set[str],
    observed_execution_modes: list[str] | set[str],
    observed_routing_reasons: list[str] | set[str],
    observed_correction_call_count: int,
    observed_final_recipe_build_count: int,
) -> dict[str, Any]:
    raw_pipelines = sorted(
        {
            str(pipeline or "").strip()
            for pipeline in codex_recipe_pipelines
            if str(pipeline or "").strip()
        }
    )
    normalized_pipelines = sorted(
        {
            _pipeline_id_text(pipeline)
            for pipeline in raw_pipelines
            if _pipeline_id_text(pipeline)
        }
    )
    normalized_execution_modes = sorted(
        {
            str(mode or "").strip()
            for mode in observed_execution_modes
            if str(mode or "").strip()
        }
    )
    normalized_routing_reasons = sorted(
        {
            str(reason or "").strip()
            for reason in observed_routing_reasons
            if str(reason or "").strip()
        }
    )
    recipe_stages = _semantic_recipe_stages() if normalized_pipelines else []
    observed_recipe_stage_call_counts = (
        _semantic_recipe_stage_call_counts(
            observed_correction_call_count=observed_correction_call_count,
            observed_final_recipe_build_count=observed_final_recipe_build_count,
        )
        if recipe_stages
        else {}
    )
    return {
        "schema_version": "upload_bundle_recipe_pipeline_context.v4",
        "codex_recipe_pipelines": normalized_pipelines,
        "recipe_topology_key": (
            "single_correction" if recipe_stages else ""
        ),
        "recipe_stages": recipe_stages,
        "observed_recipe_stage_call_counts": observed_recipe_stage_call_counts,
        "observed_recipe_execution_modes": normalized_execution_modes,
        "observed_recipe_routing_reasons": normalized_routing_reasons,
        "observed_recipe_pipelines": normalized_pipelines,
    }


def build_recipe_pipeline_topology(
    *,
    run_rows: list[dict[str, Any]],
    comparison_pairs: list[dict[str, Any]],
    recipe_triage_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    codex_recipe_pipelines: set[str] = set()
    observed_execution_modes: set[str] = set()
    observed_routing_reasons: set[str] = set()
    observed_correction_call_count = 0
    observed_final_recipe_build_count = 0

    for row in run_rows:
        if not isinstance(row, dict):
            continue
        pipeline = str(row.get("llm_recipe_pipeline") or "").strip()
        if pipeline and _is_codex_pipeline_enabled(pipeline):
            codex_recipe_pipelines.add(pipeline)

    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_run = pair.get("codex_run")
        if not isinstance(codex_run, dict):
            continue
        pipeline = str(codex_run.get("llm_recipe_pipeline") or "").strip()
        if pipeline and _is_codex_pipeline_enabled(pipeline):
            codex_recipe_pipelines.add(pipeline)

    for row in recipe_triage_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("correction_call_id") or "").strip():
            observed_correction_call_count += 1
        if str(row.get("build_final_call_id") or "").strip():
            observed_final_recipe_build_count += 1
        execution_mode = str(row.get("build_final_status") or "").strip()
        routing_reason = str(row.get("final_mapping_reason") or "").strip()
        if execution_mode:
            observed_execution_modes.add(execution_mode)
        if routing_reason:
            observed_routing_reasons.add(routing_reason)

    return build_recipe_pipeline_topology_context(
        codex_recipe_pipelines=sorted(codex_recipe_pipelines),
        observed_execution_modes=sorted(observed_execution_modes),
        observed_routing_reasons=sorted(observed_routing_reasons),
        observed_correction_call_count=observed_correction_call_count,
        observed_final_recipe_build_count=observed_final_recipe_build_count,
    )


def build_upload_bundle_source_model_from_existing_root(
    *,
    source_root: Path,
    helpers: ExistingOutputAdapterHelpers,
    default_excerpt_limit: int = 440,
    default_targeted_prompt_cases: int = 10,
    run_index_file_name: str = "run_index.json",
    comparison_summary_file_name: str = "comparison_summary.json",
    process_manifest_file_name: str = "process_manifest.json",
    per_recipe_breakdown_file_name: str = "per_recipe_or_per_span_breakdown.json",
    changed_lines_file_name: str = "changed_lines.codex_vs_vanilla.jsonl",
    starter_pack_dir_name: str = "starter_pack_v1",
    starter_call_inventory_file_name: str = "02_call_inventory.jsonl",
    starter_selected_packets_file_name: str = "06_selected_recipe_packets.jsonl",
    starter_manifest_file_name: str = "10_process_manifest.json",
) -> UploadBundleSourceModel:
    run_index_payload = helpers.load_json_object(source_root / run_index_file_name)
    comparison_summary_payload = helpers.load_json_object(source_root / comparison_summary_file_name)
    process_manifest_payload = helpers.load_json_object(source_root / process_manifest_file_name)
    per_recipe_payload = helpers.load_json_object(source_root / per_recipe_breakdown_file_name)

    run_rows_from_root_raw = run_index_payload.get("runs")
    has_run_rows_from_root = isinstance(run_rows_from_root_raw, list)
    run_rows_from_root = run_rows_from_root_raw if has_run_rows_from_root else []
    comparison_pairs_from_root_raw = comparison_summary_payload.get("pairs")
    has_pairs_from_root = isinstance(comparison_pairs_from_root_raw, list)
    comparison_pairs_from_root = comparison_pairs_from_root_raw if has_pairs_from_root else []
    pair_breakdown_from_root = per_recipe_payload.get("pairs")
    pair_breakdown_from_root = pair_breakdown_from_root if isinstance(pair_breakdown_from_root, list) else []
    changed_lines_from_root = helpers.iter_jsonl(source_root / changed_lines_file_name)

    starter_pack_dir = source_root / starter_pack_dir_name
    starter_pack_present = starter_pack_dir.is_dir()
    starter_recipe_triage_rows = helpers.load_recipe_triage_rows(starter_pack_dir)
    starter_call_inventory_rows = helpers.iter_jsonl(
        starter_pack_dir / starter_call_inventory_file_name
    )
    starter_selected_packets = helpers.iter_jsonl(
        starter_pack_dir / starter_selected_packets_file_name
    )
    starter_manifest_payload = helpers.load_json_object(starter_pack_dir / starter_manifest_file_name)

    discovered_run_dirs = helpers.discover_run_dirs(source_root)
    derived_run_records: list[Any] = []
    for run_dir in discovered_run_dirs:
        try:
            derived_run_records.append(
                helpers.build_run_record_from_existing_run(run_dir)
            )
        except Exception:  # noqa: BLE001
            continue

    run_dir_by_id: dict[str, Path] = {}
    run_dirs_by_id: dict[str, list[Path]] = defaultdict(list)
    run_dir_by_output_subdir: dict[str, Path] = {}
    derived_run_rows: list[dict[str, Any]] = []
    for record in sorted(
        derived_run_records,
        key=lambda row: (
            _record_attr(row, "run_timestamp")
            if isinstance(_record_attr(row, "run_timestamp"), datetime)
            else datetime.min,
            str(_record_attr(row, "run_id") or ""),
            str(_record_attr(row, "run_dir") or ""),
        ),
    ):
        run_dir_path = Path(_record_attr(record, "run_dir"))
        run_id = str(_record_attr(record, "run_id") or "").strip()
        if run_id:
            run_dir_by_id.setdefault(run_id, run_dir_path)
            run_dirs_by_id[run_id].append(run_dir_path)

        output_subdir = str(_record_attr(record, "output_subdir") or "").strip()
        try:
            relative_subdir = str(run_dir_path.resolve().relative_to(source_root).as_posix())
        except Exception:  # noqa: BLE001
            relative_subdir = output_subdir
        effective_output_subdir = relative_subdir or output_subdir
        if effective_output_subdir:
            run_dir_by_output_subdir.setdefault(effective_output_subdir, run_dir_path)

        derived_run_rows.append(
            {
                "run_id": _record_attr(record, "run_id"),
                "output_subdir": effective_output_subdir,
                "source_key": _record_attr(record, "source_key"),
                "source_file": _record_attr(record, "source_file"),
                "source_hash": _record_attr(record, "source_hash"),
                "overall_line_accuracy": _record_attr(record, "metric_overall_line_accuracy"),
                "macro_f1_excluding_other": _record_attr(
                    record, "metric_macro_f1_excluding_other"
                ),
                "practical_f1": _record_attr(record, "metric_practical_f1"),
                "full_prompt_log_status": _record_attr(record, "full_prompt_log_status"),
                "full_prompt_log_rows": _record_attr(record, "full_prompt_log_rows"),
                "full_prompt_log_runtime_shard_count": _record_attr(
                    record, "full_prompt_log_runtime_shard_count"
                ),
                "full_prompt_log_runtime_shard_count_by_stage": _record_attr(
                    record, "full_prompt_log_runtime_shard_count_by_stage"
                ),
                "line_role_pipeline": _record_attr(record, "line_role_pipeline"),
                "llm_recipe_pipeline": _record_attr(record, "llm_recipe_pipeline"),
            }
        )

    derived_pairs: list[dict[str, Any]] = []
    derived_changed_lines: list[dict[str, Any]] = []
    derived_pair_breakdown: list[dict[str, Any]] = []
    derived_recipe_triage: list[dict[str, Any]] = []
    derived_call_inventory: list[dict[str, Any]] = []
    if derived_run_records:
        try:
            (
                derived_comparison_summary,
                derived_changed_lines,
                derived_pair_breakdown,
                _derived_targeted_prompt_rows,
                derived_recipe_triage,
                derived_call_inventory,
                _derived_outside_span_rows,
            ) = helpers.build_comparison_summary(
                records=derived_run_records,
                excerpt_limit=default_excerpt_limit,
                targeted_prompt_case_limit=default_targeted_prompt_cases,
            )
            derived_pairs = (
                derived_comparison_summary.get("pairs")
                if isinstance(derived_comparison_summary.get("pairs"), list)
                else []
            )
        except Exception:  # noqa: BLE001
            derived_pairs = []
            derived_changed_lines = []
            derived_pair_breakdown = []
            derived_recipe_triage = []
            derived_call_inventory = []

    effective_run_rows_raw = run_rows_from_root if run_rows_from_root else derived_run_rows
    effective_run_rows: list[dict[str, Any]] = []
    for row in effective_run_rows_raw:
        if not isinstance(row, dict):
            continue
        run_row = dict(row)
        run_id = str(run_row.get("run_id") or "").strip()
        output_subdir = str(run_row.get("output_subdir") or "").strip()
        if not output_subdir:
            run_dir = run_dir_by_id.get(run_id)
            if isinstance(run_dir, Path):
                try:
                    output_subdir = str(run_dir.resolve().relative_to(source_root).as_posix())
                except Exception:  # noqa: BLE001
                    output_subdir = str(run_dir.name)
        source_file = helpers.source_file_name(str(run_row.get("source_file") or "").strip() or None)
        source_hash = str(run_row.get("source_hash") or "").strip()
        source_key = str(run_row.get("source_key") or "").strip() or helpers.source_key(
            source_hash or None,
            source_file,
        )
        run_row["run_id"] = run_id
        run_row["output_subdir"] = output_subdir
        run_row["source_file"] = source_file
        run_row["source_hash"] = source_hash or None
        run_row["source_key"] = source_key
        run_row["llm_recipe_pipeline"] = _pipeline_id_text(run_row.get("llm_recipe_pipeline"))
        run_row["line_role_pipeline"] = _pipeline_id_text(run_row.get("line_role_pipeline"))
        if "llm_knowledge_pipeline" in run_row:
            run_row["llm_knowledge_pipeline"] = _pipeline_id_text(
                run_row.get("llm_knowledge_pipeline")
            )
        effective_run_rows.append(run_row)

    effective_pairs = comparison_pairs_from_root if comparison_pairs_from_root else derived_pairs
    effective_changed_lines = changed_lines_from_root if changed_lines_from_root else derived_changed_lines
    effective_pair_breakdown = pair_breakdown_from_root if pair_breakdown_from_root else derived_pair_breakdown
    effective_recipe_triage = (
        derived_recipe_triage if derived_recipe_triage else starter_recipe_triage_rows
    )
    effective_call_inventory = (
        derived_call_inventory if derived_call_inventory else starter_call_inventory_rows
    )

    effective_selected_packets = list(starter_selected_packets)
    if (
        not effective_selected_packets
        and effective_recipe_triage
        and effective_changed_lines
    ):
        try:
            selected_rows = helpers.select_starter_pack_recipe_cases(
                effective_recipe_triage
            )
            effective_selected_packets = helpers.build_selected_recipe_packets(
                selected_recipe_rows=selected_rows,
                changed_line_rows=effective_changed_lines,
            )
        except Exception:  # noqa: BLE001
            effective_selected_packets = []

    advertised_changed_lines = helpers.coerce_int(
        comparison_summary_payload.get("changed_lines_total")
    )
    topology = build_recipe_pipeline_topology(
        run_rows=effective_run_rows,
        comparison_pairs=effective_pairs,
        recipe_triage_rows=effective_recipe_triage,
    )
    topology["runtime_runs"] = [
        {
            "run_id": str(row.get("run_id") or ""),
            "output_subdir": str(row.get("output_subdir") or ""),
            "source_key": str(row.get("source_key") or ""),
            "runtime_stages": _summarize_runtime_stages_for_run(run_dir),
        }
        for row in effective_run_rows
        for run_dir in [run_dir_by_id.get(str(row.get("run_id") or "").strip())]
        if isinstance(run_dir, Path)
    ]
    diagnostic_families = {
        "line_role": "line_role",
        "recipe_correction": "correction_*",
        "final_recipe": "build_final_*",
        "routing_or_fallback": "routing_or_fallback",
    }

    return UploadBundleSourceModel(
        source_root=source_root,
        run_index_payload=run_index_payload,
        comparison_summary_payload=comparison_summary_payload,
        process_manifest_payload=process_manifest_payload,
        per_recipe_payload=per_recipe_payload,
        starter_manifest_payload=starter_manifest_payload,
        starter_pack_present=starter_pack_present,
        run_rows=effective_run_rows,
        comparison_pairs=effective_pairs,
        changed_line_rows=effective_changed_lines,
        pair_breakdown_rows=effective_pair_breakdown,
        recipe_triage_rows=effective_recipe_triage,
        call_inventory_rows=effective_call_inventory,
        selected_packets=effective_selected_packets,
        run_dir_by_id=run_dir_by_id,
        run_dirs_by_id={key: list(value) for key, value in run_dirs_by_id.items()},
        run_dir_by_output_subdir=run_dir_by_output_subdir,
        discovered_run_dirs=list(discovered_run_dirs),
        advertised_counts={
            "run_count": len(run_rows_from_root) if has_run_rows_from_root else None,
            "pair_count": len(comparison_pairs_from_root) if has_pairs_from_root else None,
            "changed_lines_total": advertised_changed_lines,
        },
        topology=topology,
        diagnostic_families=diagnostic_families,
        adapter_metadata={
            "uses_root_run_rows": bool(run_rows_from_root),
            "uses_root_pairs": bool(comparison_pairs_from_root),
            "uses_root_changed_lines": bool(changed_lines_from_root),
            "derived_run_count": len(derived_run_rows),
            "discovered_run_count": len(discovered_run_dirs),
        },
    )
