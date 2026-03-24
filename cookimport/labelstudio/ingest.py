from __future__ import annotations

from cookimport.core.reporting import compute_file_hash
from cookimport.labelstudio.archive import build_extracted_archive
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.freeform_tasks import (
    build_freeform_span_tasks,
    compute_freeform_task_coverage,
    sample_freeform_tasks,
)
from cookimport.labelstudio.ingest_flows.artifacts import (
    _apply_nonrecipe_authority_to_predictions,
    _write_authoritative_line_role_artifacts,
    _write_processed_outputs,
)
from cookimport.labelstudio.ingest_flows.normalize import _normalize_llm_recipe_pipeline
from cookimport.labelstudio.ingest_flows.prediction_run import generate_pred_run_artifacts
from cookimport.labelstudio.ingest_flows.split_cache import (
    _acquire_split_phase_slot,
    _try_acquire_file_lock_nonblocking,
)
from cookimport.labelstudio.ingest_flows.split_merge import (
    _merge_parallel_results,
    _parallel_convert_worker,
)
from cookimport.labelstudio.ingest_flows.upload import run_labelstudio_import
from cookimport.labelstudio.ingest_support import (
    _build_line_role_candidates_from_archive,
    _build_prelabel_provider,
    _dedupe_project_name,
    _resolve_project_name,
)
from cookimport.labelstudio.prelabel import (
    preflight_codex_model_access,
    prelabel_freeform_task,
)
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.parsing.label_source_of_truth import build_label_first_stage_result
from cookimport.plugins import registry
from cookimport.staging.import_session import execute_stage_import_session_from_result
from cookimport.staging.job_planning import plan_source_job

__all__ = [
    "LabelStudioClient",
    "_acquire_split_phase_slot",
    "_apply_nonrecipe_authority_to_predictions",
    "_build_line_role_candidates_from_archive",
    "_build_prelabel_provider",
    "_dedupe_project_name",
    "_merge_parallel_results",
    "_normalize_llm_recipe_pipeline",
    "_parallel_convert_worker",
    "_resolve_project_name",
    "_try_acquire_file_lock_nonblocking",
    "_write_authoritative_line_role_artifacts",
    "_write_processed_outputs",
    "build_extracted_archive",
    "build_freeform_span_tasks",
    "build_label_first_stage_result",
    "compute_file_hash",
    "compute_freeform_task_coverage",
    "execute_stage_import_session_from_result",
    "generate_pred_run_artifacts",
    "plan_source_job",
    "preflight_codex_model_access",
    "prelabel_freeform_task",
    "registry",
    "run_codex_farm_recipe_pipeline",
    "run_labelstudio_import",
    "sample_freeform_tasks",
]
