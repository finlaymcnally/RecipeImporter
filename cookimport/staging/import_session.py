from __future__ import annotations

from typing import Any

from cookimport.core.reporting import enrich_report_with_stats
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks
from cookimport.parsing.label_source_of_truth import build_label_first_stage_result
from cookimport.parsing.tables import extract_and_annotate_tables
from cookimport.staging.import_session_contracts import StageImportSessionResult
from cookimport.staging.import_session_flows.authority import _write_label_first_artifacts
from cookimport.staging.import_session_flows.output_stage import (
    execute_stage_import_session_from_result as _execute_stage_import_session_from_result,
)
from cookimport.staging.import_session_flows.reporting import _notify_stage_progress
from cookimport.staging.pipeline_runtime import (
    ExtractedBookBundle,
    KnowledgeFinalResult,
    NonrecipeRouteResult,
    RecipeBoundaryResult,
    RecipeRefineResult,
    run_recipe_boundary_stage,
)
from cookimport.staging.writer import (
    write_authoritative_recipe_semantics,
    write_chunk_outputs,
    write_draft_outputs,
    write_knowledge_outputs_artifact,
    write_intermediate_outputs,
    write_nonrecipe_stage_outputs,
    write_raw_artifacts,
    write_report,
    write_section_outputs,
    write_stage_block_predictions,
    write_table_outputs,
)


def _sync_import_session_compat() -> None:
    from cookimport.staging import pipeline_runtime as _pipeline_runtime
    from cookimport.staging.import_session_flows import output_stage as _output_stage

    synced_names = (
        "_notify_stage_progress",
        "_write_label_first_artifacts",
        "build_label_first_stage_result",
        "chunks_from_non_recipe_blocks",
        "enrich_report_with_stats",
        "extract_and_annotate_tables",
        "run_recipe_boundary_stage",
        "write_authoritative_recipe_semantics",
        "write_chunk_outputs",
        "write_draft_outputs",
        "write_knowledge_outputs_artifact",
        "write_intermediate_outputs",
        "write_nonrecipe_stage_outputs",
        "write_raw_artifacts",
        "write_report",
        "write_section_outputs",
        "write_stage_block_predictions",
        "write_table_outputs",
    )
    for name in synced_names:
        setattr(_output_stage, name, globals()[name])
    _pipeline_runtime.build_label_first_stage_result = build_label_first_stage_result


def execute_stage_import_session_from_result(*args: Any, **kwargs: Any) -> StageImportSessionResult:
    _sync_import_session_compat()
    return _execute_stage_import_session_from_result(*args, **kwargs)


__all__ = [
    "ExtractedBookBundle",
    "KnowledgeFinalResult",
    "NonrecipeRouteResult",
    "RecipeBoundaryResult",
    "RecipeRefineResult",
    "StageImportSessionResult",
    "_notify_stage_progress",
    "_write_label_first_artifacts",
    "build_label_first_stage_result",
    "chunks_from_non_recipe_blocks",
    "enrich_report_with_stats",
    "execute_stage_import_session_from_result",
    "extract_and_annotate_tables",
    "run_recipe_boundary_stage",
    "write_authoritative_recipe_semantics",
    "write_chunk_outputs",
    "write_draft_outputs",
    "write_knowledge_outputs_artifact",
    "write_intermediate_outputs",
    "write_nonrecipe_stage_outputs",
    "write_raw_artifacts",
    "write_report",
    "write_section_outputs",
    "write_stage_block_predictions",
    "write_table_outputs",
]
