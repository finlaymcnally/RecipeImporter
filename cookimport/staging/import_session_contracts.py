from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cookimport.core.models import ConversionResult
from cookimport.parsing.label_source_of_truth import LabelFirstStageResult
from cookimport.staging.nonrecipe_stage import NonRecipeStageResult
from cookimport.staging.pipeline_runtime import (
    ExtractedBookBundle,
    KnowledgeFinalResult,
    NonrecipeRouteResult,
    RecipeBoundaryResult,
    RecipeRefineResult,
)


@dataclass(frozen=True)
class StageImportSessionResult:
    run_root: Path
    workbook_slug: str
    source_file: Path
    source_hash: str
    importer_name: str
    conversion_result: ConversionResult
    report_path: Path
    stage_block_predictions_path: Path
    run_config: dict[str, Any] | None
    run_config_hash: str | None
    run_config_summary: str | None
    llm_report: dict[str, Any]
    timing: dict[str, Any]
    label_first_result: LabelFirstStageResult | None = None
    label_artifact_paths: dict[str, Path] | None = None
    source_artifact_paths: dict[str, Path] | None = None
    authoritative_recipe_payloads_path: Path | None = None
    nonrecipe_stage_result: NonRecipeStageResult | None = None
    extracted_book_bundle: ExtractedBookBundle | None = None
    recipe_boundary_result: RecipeBoundaryResult | None = None
    recipe_refine_result: RecipeRefineResult | None = None
    nonrecipe_route_result: NonrecipeRouteResult | None = None
    knowledge_final_result: KnowledgeFinalResult | None = None
