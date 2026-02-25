from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from cookimport.config.run_settings import RunSettings
from cookimport.llm.codex_farm_runner import CodexFarmRunner
from cookimport.tagging.catalog import (
    TagCatalog,
    get_catalog_fingerprint_from_json,
    load_catalog_from_json,
)
from cookimport.tagging.engine import TagSuggestion, _apply_policies, suggest_tags_deterministic
from cookimport.tagging.llm_second_pass import (
    LlmSecondPassBatchResult,
    LlmSecondPassConfig,
    LlmSecondPassRequest,
    suggest_tags_with_llm_batch,
)
from cookimport.tagging.policies import CATEGORY_POLICIES
from cookimport.tagging.render import (
    render_suggestions_text,
    serialize_suggestions_json,
    write_run_report,
    write_tags_json,
)
from cookimport.tagging.signals import RecipeSignalPack, signals_from_draft_json

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DraftTaggingRecord:
    recipe_key: str
    draft_path: Path
    signals: RecipeSignalPack
    suggestions: list[TagSuggestion]
    new_tag_proposals: list[dict[str, str]]
    rendered_text: str
    serialized: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DraftTaggingRunResult:
    records: list[DraftTaggingRecord]
    skipped_files: list[str]
    llm_report: dict[str, Any]
    llm_validation: dict[str, Any]
    report_path: Path | None = None


@dataclass(frozen=True, slots=True)
class StageTaggingPassResult:
    enabled: bool
    pipeline: str
    catalog_json: str | None
    tags_index_path: Path | None
    workbook_reports: dict[str, str]
    totals: dict[str, int]
    llm: dict[str, Any]


def suggest_tags_for_draft_files(
    *,
    draft_files: Sequence[Path],
    catalog: TagCatalog,
    catalog_fingerprint: str,
    explain: bool = False,
    per_recipe_out_dir: Path | None = None,
    report_path: Path | None = None,
    llm_config: LlmSecondPassConfig | None = None,
    llm_raw_pass_dir: Path | None = None,
) -> DraftTaggingRunResult:
    parsed: list[tuple[str, Path, RecipeSignalPack, list[Any]]] = []
    skipped_files: list[str] = []

    for index, draft_path in enumerate(draft_files):
        try:
            signals = signals_from_draft_json(draft_path)
        except Exception as exc:  # noqa: BLE001
            skipped_files.append(f"{draft_path.name}: {exc}")
            logger.warning("Skipping draft for tagging %s: %s", draft_path, exc)
            continue
        recipe_key = f"recipe_{index:05d}_{draft_path.stem}"
        deterministic = suggest_tags_deterministic(catalog, signals)
        parsed.append((recipe_key, draft_path, signals, deterministic))

    batch_result = LlmSecondPassBatchResult.empty()
    if llm_config is not None and llm_config.enabled and parsed:
        requests: list[LlmSecondPassRequest] = []
        for recipe_key, _draft_path, _signals, deterministic in parsed:
            filled_categories = {suggestion.category_key for suggestion in deterministic}
            missing_categories = tuple(
                category_key
                for category_key in CATEGORY_POLICIES
                if category_key in catalog.categories_by_key and category_key not in filled_categories
            )
            if not missing_categories:
                continue
            requests.append(
                LlmSecondPassRequest(
                    recipe_key=recipe_key,
                    signals=_signals,
                    missing_categories=missing_categories,
                )
            )
        if requests:
            batch_result = suggest_tags_with_llm_batch(
                requests,
                catalog,
                config=llm_config,
                raw_pass_dir=llm_raw_pass_dir,
            )

    pipeline_id = str(batch_result.llm_report.get("pipeline_id") or "").strip() or None
    records: list[DraftTaggingRecord] = []
    per_recipe_serialized: list[dict[str, Any]] = []

    for recipe_key, draft_path, signals, deterministic in parsed:
        llm_suggestions = list(batch_result.suggestions_by_recipe.get(recipe_key, []))
        merged = list(deterministic)
        if llm_suggestions:
            merged.extend(llm_suggestions)
            merged = _apply_policies(catalog, merged)
        new_tag_proposals = list(batch_result.new_tag_proposals_by_recipe.get(recipe_key, []))
        recipe_id = str(signals.recipe_id or draft_path.stem)
        title = signals.title or draft_path.stem
        rendered = render_suggestions_text(title, merged, explain=explain)
        serialized = serialize_suggestions_json(
            merged,
            recipe_id=recipe_id,
            title=title,
            catalog_fingerprint=catalog_fingerprint,
            new_tag_proposals=new_tag_proposals,
            llm_pipeline_id=pipeline_id,
        )
        records.append(
            DraftTaggingRecord(
                recipe_key=recipe_key,
                draft_path=draft_path,
                signals=signals,
                suggestions=merged,
                new_tag_proposals=new_tag_proposals,
                rendered_text=rendered,
                serialized=serialized,
            )
        )
        per_recipe_serialized.append(serialized)
        if per_recipe_out_dir is not None:
            per_recipe_path = per_recipe_out_dir / draft_path.with_suffix(".tags.json").name
            write_tags_json(
                per_recipe_path,
                merged,
                recipe_id=recipe_id,
                title=title,
                catalog_fingerprint=catalog_fingerprint,
                new_tag_proposals=new_tag_proposals,
                llm_pipeline_id=pipeline_id,
            )

    if report_path is not None:
        llm_report = _with_validation(batch_result.llm_report, batch_result.llm_validation)
        write_run_report(
            report_path,
            len(per_recipe_serialized),
            per_recipe_serialized,
            catalog_fingerprint=catalog_fingerprint,
            llm_report=llm_report,
        )

    return DraftTaggingRunResult(
        records=records,
        skipped_files=skipped_files,
        llm_report=dict(batch_result.llm_report),
        llm_validation=dict(batch_result.llm_validation),
        report_path=report_path,
    )


def run_stage_tagging_pass(
    *,
    run_root: Path,
    run_settings: RunSettings,
    status_callback: Callable[[str], None] | None = None,
    llm_runner: CodexFarmRunner | None = None,
) -> StageTaggingPassResult:
    if run_settings.llm_tags_pipeline.value == "off":
        return StageTaggingPassResult(
            enabled=False,
            pipeline="off",
            catalog_json=None,
            tags_index_path=None,
            workbook_reports={},
            totals={"workbooks": 0, "recipes": 0, "tags": 0, "llm_tags": 0, "new_tag_proposals": 0},
            llm={"enabled": False, "pipeline": "off"},
        )

    catalog_json = Path(run_settings.tag_catalog_json).expanduser()
    if not catalog_json.exists():
        raise FileNotFoundError(
            f"Tag catalog JSON not found: {catalog_json}. "
            "Provide --tag-catalog-json when --llm-tags-pipeline is enabled."
        )

    final_drafts_root = run_root / "final drafts"
    if not final_drafts_root.exists():
        return StageTaggingPassResult(
            enabled=True,
            pipeline=run_settings.llm_tags_pipeline.value,
            catalog_json=str(catalog_json),
            tags_index_path=None,
            workbook_reports={},
            totals={"workbooks": 0, "recipes": 0, "tags": 0, "llm_tags": 0, "new_tag_proposals": 0},
            llm={"enabled": True, "pipeline_id": run_settings.codex_farm_pipeline_pass5_tags},
        )
    workbook_dirs = sorted(path for path in final_drafts_root.iterdir() if path.is_dir())
    tags_root = run_root / "tags"
    tags_root.mkdir(parents=True, exist_ok=True)

    catalog = load_catalog_from_json(catalog_json)
    catalog_fingerprint = get_catalog_fingerprint_from_json(catalog_json)
    llm_config = LlmSecondPassConfig(
        enabled=True,
        pipeline_id=run_settings.codex_farm_pipeline_pass5_tags,
        codex_farm_cmd=run_settings.codex_farm_cmd,
        codex_farm_root=run_settings.codex_farm_root,
        codex_farm_workspace_root=run_settings.codex_farm_workspace_root,
        failure_mode=run_settings.codex_farm_failure_mode.value,
        runner=llm_runner,
    )

    workbook_reports: dict[str, str] = {}
    total_recipes = 0
    total_tags = 0
    total_llm_tags = 0
    total_new_tag_proposals = 0
    llm_reports: list[dict[str, Any]] = []
    llm_validations: list[dict[str, Any]] = []

    total_workbooks = len(workbook_dirs)
    for index, workbook_dir in enumerate(workbook_dirs, start=1):
        workbook_slug = workbook_dir.name
        draft_files = sorted(workbook_dir.glob("*.json"))
        if not draft_files:
            continue
        if status_callback is not None:
            status_callback(f"Tagging pass task {index}/{total_workbooks}: {workbook_slug}")
        workbook_tags_dir = tags_root / workbook_slug
        report_path = workbook_tags_dir / "tagging_report.json"
        result = suggest_tags_for_draft_files(
            draft_files=draft_files,
            catalog=catalog,
            catalog_fingerprint=catalog_fingerprint,
            per_recipe_out_dir=workbook_tags_dir,
            report_path=report_path,
            llm_config=llm_config,
            llm_raw_pass_dir=run_root / "raw" / "llm" / workbook_slug / "pass5_tags",
        )
        workbook_reports[workbook_slug] = str(report_path.relative_to(run_root))
        llm_reports.append(result.llm_report)
        llm_validations.append(result.llm_validation)
        total_recipes += len(result.records)
        for record in result.records:
            total_tags += len(record.suggestions)
            total_llm_tags += sum(1 for suggestion in record.suggestions if suggestion.source == "llm")
            total_new_tag_proposals += len(record.new_tag_proposals)

    tags_index_path = tags_root / "tags_index.json"
    tags_index_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog_fingerprint": catalog_fingerprint,
        "tag_catalog_json": str(catalog_json),
        "pipeline": run_settings.llm_tags_pipeline.value,
        "pipeline_id": run_settings.codex_farm_pipeline_pass5_tags,
        "workbooks": workbook_reports,
        "totals": {
            "workbooks": len(workbook_reports),
            "recipes": total_recipes,
            "tags": total_tags,
            "llm_tags": total_llm_tags,
            "new_tag_proposals": total_new_tag_proposals,
        },
        "llm": {
            "reports": llm_reports,
            "validations": llm_validations,
        },
    }
    tags_index_path.write_text(
        json.dumps(tags_index_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return StageTaggingPassResult(
        enabled=True,
        pipeline=run_settings.llm_tags_pipeline.value,
        catalog_json=str(catalog_json),
        tags_index_path=tags_index_path,
        workbook_reports=workbook_reports,
        totals={
            "workbooks": len(workbook_reports),
            "recipes": total_recipes,
            "tags": total_tags,
            "llm_tags": total_llm_tags,
            "new_tag_proposals": total_new_tag_proposals,
        },
        llm={
            "reports": llm_reports,
            "validations": llm_validations,
            "pipeline_id": run_settings.codex_farm_pipeline_pass5_tags,
        },
    )


def _with_validation(llm_report: dict[str, Any], llm_validation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(llm_report)
    if llm_validation:
        payload["validation"] = dict(llm_validation)
    return payload
