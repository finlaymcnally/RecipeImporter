from __future__ import annotations

from typing import Any, Mapping

from cookimport.llm.codex_farm_knowledge_jobs import KnowledgeJobBuildReport
from cookimport.llm.knowledge_prompt_builder import build_knowledge_direct_prompt
from cookimport.llm.phase_plan import (
    attach_survivability_to_phase_plan,
    build_phase_plan,
)
from cookimport.runs.stage_names import stage_label


def _knowledge_phase_plan_shard_specs(
    *,
    build_report: KnowledgeJobBuildReport,
    worker_id_by_shard_id: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    worker_lookup = dict(worker_id_by_shard_id or {})
    shard_specs: list[dict[str, Any]] = []
    for shard in build_report.shard_entries:
        input_payload = (
            dict(shard.input_payload) if isinstance(shard.input_payload, Mapping) else {}
        )
        prompt_text = build_knowledge_direct_prompt(input_payload)
        metadata = dict(shard.metadata) if isinstance(shard.metadata, Mapping) else {}
        shard_specs.append(
            {
                "shard_id": shard.shard_id,
                "worker_id": worker_lookup.get(shard.shard_id),
                "owned_ids": list(shard.owned_ids),
                "call_ids": [shard.shard_id],
                "prompt_chars": len(prompt_text),
                "task_prompt_chars": len(prompt_text),
                "work_unit_count": int(metadata.get("char_count") or 0),
                "work_unit_label": "chars",
            }
        )
    return shard_specs


def build_knowledge_stage_phase_plan(
    *,
    build_report: KnowledgeJobBuildReport,
    pipeline_id: str,
    surface_pipeline: str,
    worker_count: int | None,
    requested_shard_count: int | None = None,
    worker_id_by_shard_id: Mapping[str, str] | None = None,
    survivability_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    shard_count = len(build_report.shard_entries)
    phase_plan = build_phase_plan(
        stage_key="nonrecipe_finalize",
        stage_label=stage_label("nonrecipe_finalize"),
        stage_order=4,
        surface_pipeline=surface_pipeline,
        runtime_pipeline_id=pipeline_id,
        worker_count=worker_count,
        requested_shard_count=(
            int(requested_shard_count)
            if requested_shard_count is not None
            else (int(build_report.requested_shard_count) if shard_count > 0 else 1)
        ),
        budget_native_shard_count=(
            int(build_report.packet_count_before_partition) if shard_count > 0 else 1
        ),
        launch_shard_count=shard_count,
        planning_warnings=list(build_report.planning_warnings),
        shard_specs=_knowledge_phase_plan_shard_specs(
            build_report=build_report,
            worker_id_by_shard_id=worker_id_by_shard_id,
        ),
    )
    return attach_survivability_to_phase_plan(
        phase_plan=phase_plan,
        survivability_report=survivability_report,
    )
