from __future__ import annotations

from cookimport.core.reporting import enrich_report_with_stats
from cookimport.parsing.label_source_of_truth import build_label_first_stage_result
from cookimport.parsing.tables import extract_and_annotate_tables
from cookimport.staging.import_session_contracts import StageImportSessionResult
from cookimport.staging.deterministic_prep import (
    DeterministicPrepBundleResult,
    build_deterministic_prep_key,
    build_shard_recommendations_from_prep_bundle,
    load_existing_deterministic_prep_bundle,
    load_deterministic_prep_bundle,
    load_recipe_boundary_result_from_deterministic_prep_bundle,
    persist_deterministic_prep_bundle_from_stage_run,
    resolve_or_build_deterministic_prep_bundle,
)
from cookimport.staging.import_session_flows.authority import _write_label_first_artifacts
from cookimport.staging.import_session_flows.output_stage import (
    execute_stage_import_session_from_recipe_boundary_result,
    execute_stage_import_session_from_result,
)
from cookimport.staging.import_session_flows.reporting import _notify_stage_progress
from cookimport.staging.pipeline_runtime import (
    ExtractedBookBundle,
    NonrecipeFinalizeResult,
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
    write_recipe_authority_decisions,
    write_recipe_block_ownership,
    write_report,
    write_section_outputs,
    write_stage_block_predictions,
    write_table_outputs,
)

__all__ = [
    "DeterministicPrepBundleResult",
    "ExtractedBookBundle",
    "NonrecipeFinalizeResult",
    "NonrecipeRouteResult",
    "RecipeBoundaryResult",
    "RecipeRefineResult",
    "StageImportSessionResult",
    "_notify_stage_progress",
    "_write_label_first_artifacts",
    "build_label_first_stage_result",
    "build_deterministic_prep_key",
    "build_shard_recommendations_from_prep_bundle",
    "enrich_report_with_stats",
    "execute_stage_import_session_from_recipe_boundary_result",
    "execute_stage_import_session_from_result",
    "extract_and_annotate_tables",
    "load_existing_deterministic_prep_bundle",
    "load_deterministic_prep_bundle",
    "load_recipe_boundary_result_from_deterministic_prep_bundle",
    "persist_deterministic_prep_bundle_from_stage_run",
    "resolve_or_build_deterministic_prep_bundle",
    "run_recipe_boundary_stage",
    "write_authoritative_recipe_semantics",
    "write_chunk_outputs",
    "write_draft_outputs",
    "write_knowledge_outputs_artifact",
    "write_intermediate_outputs",
    "write_nonrecipe_stage_outputs",
    "write_raw_artifacts",
    "write_recipe_authority_decisions",
    "write_recipe_block_ownership",
    "write_report",
    "write_section_outputs",
    "write_stage_block_predictions",
    "write_table_outputs",
]
