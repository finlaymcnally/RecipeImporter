from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from cookimport.core.progress_messages import parse_worker_activity
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    RawArtifact,
    RecipeCandidate,
)
from cookimport.labelstudio.archive import (
    build_extracted_archive,
    prepare_extracted_archive,
    prepared_archive_payload,
)
from cookimport.labelstudio.ingest_flows.artifacts import (
    _apply_nonrecipe_authority_to_predictions,
    _write_authoritative_line_role_artifacts,
    _write_processed_outputs,
)
from cookimport.labelstudio.ingest_flows.normalize import _normalize_llm_recipe_pipeline
from cookimport.labelstudio.ingest_flows.prediction_run import (
    generate_pred_run_artifacts,
)
from cookimport.labelstudio.ingest_flows.split_cache import _acquire_split_phase_slot
from cookimport.labelstudio.ingest_flows.split_merge import _merge_parallel_results
from cookimport.labelstudio.ingest_flows.upload import run_labelstudio_import
from cookimport.labelstudio.models import ArchiveBlock
from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    AuthoritativeLabeledLine,
    LabelFirstStageResult,
    RecipeSpan,
)
from cookimport.parsing.canonical_line_roles import CanonicalLineRolePrediction
from cookimport.staging.nonrecipe_stage import NonRecipeStageResult
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate
from cookimport.staging.job_planning import JobSpec, plan_source_job
from cookimport.staging.import_session import StageImportSessionResult
from tests.nonrecipe_stage_helpers import (
    make_authority_result,
    make_finalize_status_result,
    make_routing_result,
    make_seed_result,
    make_stage_result,
)


def _make_label_first_result(
    *,
    source: Path,
    raw_artifacts: list[RawArtifact],
) -> LabelFirstStageResult:
    return LabelFirstStageResult(
        labeled_lines=[
            AuthoritativeLabeledLine(
                source_block_id="block:0",
                source_block_index=0,
                atomic_index=0,
                text="Pancakes",
                deterministic_label="RECIPE_TITLE",
                final_label="RECIPE_TITLE",
                decided_by="rule",
            ),
            AuthoritativeLabeledLine(
                source_block_id="block:1",
                source_block_index=1,
                atomic_index=1,
                text="SERVES 2",
                deterministic_label="YIELD_LINE",
                final_label="YIELD_LINE",
                decided_by="rule",
            ),
            AuthoritativeLabeledLine(
                source_block_id="block:2",
                source_block_index=2,
                atomic_index=2,
                text="1 cup flour",
                deterministic_label="INGREDIENT_LINE",
                final_label="INGREDIENT_LINE",
                decided_by="rule",
            ),
            AuthoritativeLabeledLine(
                source_block_id="block:3",
                source_block_index=3,
                atomic_index=3,
                text="Whisk batter",
                deterministic_label="INSTRUCTION_LINE",
                final_label="INSTRUCTION_LINE",
                decided_by="rule",
            ),
            AuthoritativeLabeledLine(
                source_block_id="block:4",
                source_block_index=4,
                atomic_index=4,
                text="NOTE: Keep warm",
                deterministic_label="RECIPE_NOTES",
                final_label="RECIPE_NOTES",
                decided_by="rule",
            ),
        ],
        block_labels=[
            AuthoritativeBlockLabel(
                source_block_id="block:0",
                source_block_index=0,
                supporting_atomic_indices=[0],
                deterministic_label="RECIPE_TITLE",
                final_label="RECIPE_TITLE",
                decided_by="rule",
            ),
            AuthoritativeBlockLabel(
                source_block_id="block:1",
                source_block_index=1,
                supporting_atomic_indices=[1],
                deterministic_label="YIELD_LINE",
                final_label="YIELD_LINE",
                decided_by="rule",
            ),
            AuthoritativeBlockLabel(
                source_block_id="block:2",
                source_block_index=2,
                supporting_atomic_indices=[2],
                deterministic_label="INGREDIENT_LINE",
                final_label="INGREDIENT_LINE",
                decided_by="rule",
            ),
            AuthoritativeBlockLabel(
                source_block_id="block:3",
                source_block_index=3,
                supporting_atomic_indices=[3],
                deterministic_label="INSTRUCTION_LINE",
                final_label="INSTRUCTION_LINE",
                decided_by="rule",
            ),
            AuthoritativeBlockLabel(
                source_block_id="block:4",
                source_block_index=4,
                supporting_atomic_indices=[4],
                deterministic_label="RECIPE_NOTES",
                final_label="RECIPE_NOTES",
                decided_by="rule",
            ),
        ],
        recipe_spans=[
            RecipeSpan(
                span_id="recipe_span_0",
                start_block_index=0,
                end_block_index=4,
                block_indices=[0, 1, 2, 3, 4],
                source_block_ids=[
                    "block:0",
                    "block:1",
                    "block:2",
                    "block:3",
                    "block:4",
                ],
                start_atomic_index=0,
                end_atomic_index=4,
                atomic_indices=[0, 1, 2, 3, 4],
                title_block_index=0,
                title_atomic_index=0,
            )
        ],
        non_recipe_lines=[],
        updated_conversion_result=ConversionResult(
            recipes=[
                RecipeCandidate(
                    name="Pancakes",
                    identifier="recipe-1",
                    recipeIngredient=["1 cup flour"],
                    recipeInstructions=["Whisk batter"],
                    comment=[{"text": "NOTE: Keep warm"}],
                    recipeYield="SERVES 2",
                    provenance={"location": {"start_block": 0, "end_block": 4}},
                )
            ],
            sourceBlocks=[
                {"blockId": "b0", "orderIndex": 0, "text": "Pancakes"},
                {"blockId": "b1", "orderIndex": 1, "text": "SERVES 2"},
                {"blockId": "b2", "orderIndex": 2, "text": "1 cup flour"},
                {"blockId": "b3", "orderIndex": 3, "text": "Whisk batter"},
                {"blockId": "b4", "orderIndex": 4, "text": "NOTE: Keep warm"},
            ],
            non_recipe_blocks=[],
            raw_artifacts=raw_artifacts,
            report=ConversionReport(),
            workbook="book",
            workbook_path=str(source),
        ),
        archive_blocks=[
            {
                "index": 0,
                "block_id": "block:0",
                "text": "Pancakes",
                "location": {"block_index": 0},
            },
            {
                "index": 1,
                "block_id": "block:1",
                "text": "SERVES 2",
                "location": {"block_index": 1},
            },
            {
                "index": 2,
                "block_id": "block:2",
                "text": "1 cup flour",
                "location": {"block_index": 2},
            },
            {
                "index": 3,
                "block_id": "block:3",
                "text": "Whisk batter",
                "location": {"block_index": 3},
            },
            {
                "index": 4,
                "block_id": "block:4",
                "text": "NOTE: Keep warm",
                "location": {"block_index": 4},
            },
        ],
        source_hash="hash-123",
    )


def _make_empty_conversion_result(source: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "Pancakes"},
            {"blockId": "b1", "orderIndex": 1, "text": "SERVES 2"},
            {"blockId": "b2", "orderIndex": 2, "text": "1 cup flour"},
            {"blockId": "b3", "orderIndex": 3, "text": "Mix ingredients."},
            {"blockId": "b4", "orderIndex": 4, "text": "Salt strengthens flavor."},
        ],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )


def _install_basic_generate_pred_run_artifacts_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_result: ConversionResult,
    archive_blocks: list[ArchiveBlock],
    source_hash: str = "hash-123",
    coverage_payload: dict[str, object] | None = None,
    patch_parsing_archive: bool = False,
) -> None:
    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_extracted_archive",
        lambda *_args, **_kwargs: archive_blocks,
    )
    if patch_parsing_archive:
        monkeypatch.setattr(
            "cookimport.parsing.label_source_of_truth.build_extracted_archive",
            lambda *_args, **_kwargs: archive_blocks,
        )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash",
        lambda _path: source_hash,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: coverage_payload
        or {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )


def _make_projection_conversion_result(
    *,
    source: Path,
    block_texts: list[str],
) -> ConversionResult:
    return ConversionResult(
        recipes=[],
        sourceBlocks=[
            {"blockId": f"b{index}", "orderIndex": index, "text": text}
            for index, text in enumerate(block_texts)
        ],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="fake",
                sourceHash="hash-123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": index, "text": text}
                        for index, text in enumerate(block_texts)
                    ]
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )


def _install_projection_generate_pred_run_artifacts_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source: Path,
    fake_result: ConversionResult,
    label_first_result: LabelFirstStageResult,
    archive_blocks: list[ArchiveBlock],
    execute_stage_import_session_from_result: callable | None = None,
    patch_parsing_archive: bool = False,
) -> None:
    _install_basic_generate_pred_run_artifacts_mocks(
        monkeypatch,
        fake_result=fake_result,
        archive_blocks=archive_blocks,
        patch_parsing_archive=patch_parsing_archive,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_label_first_stage_result",
        lambda **_kwargs: label_first_result,
    )
    monkeypatch.setattr(
        "cookimport.staging.pipeline_runtime.build_label_first_stage_result",
        lambda **_kwargs: label_first_result,
        raising=False,
    )
    if execute_stage_import_session_from_result is not None:
        monkeypatch.setattr(
            "cookimport.labelstudio.ingest_flows.prediction_run.execute_stage_import_session_from_result",
            execute_stage_import_session_from_result,
        )


def _install_split_import_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_result: ConversionResult,
    processed_root: Path,
    task_count: int,
    planned_jobs: list[JobSpec],
    process_pool_executor: object | None = None,
    thread_pool_executor: object | None = None,
) -> None:
    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    class FakeLabelStudioClient:
        uploaded_batches: list[int] = []

        def __init__(self, _url: str, _key: str) -> None:
            pass

        def list_projects(self):
            return []

        def find_project_by_title(self, _title: str):
            return None

        def create_project(
            self, title: str, _label_config: str, description: str | None = None
        ):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks):
            self.uploaded_batches.append(len(tasks))

    def _fake_execute_stage_import_session_from_result(**kwargs):
        run_root = processed_root / "2026-02-11_00:00:00"
        run_root.mkdir(parents=True, exist_ok=True)
        stage_predictions_path = run_root / ".bench" / "book" / "stage_block_predictions.json"
        stage_predictions_path.parent.mkdir(parents=True, exist_ok=True)
        stage_predictions_path.write_text(
            json.dumps(
                {
                    "schema_version": "stage_block_predictions.v1",
                    "block_labels": {},
                    "label_blocks": {},
                    "workbook_slug": "book",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_path = run_root / "book.excel_import_report.json"
        report_path.write_text("{}", encoding="utf-8")
        return StageImportSessionResult(
            run_root=run_root,
            workbook_slug="book",
            source_file=planned_jobs[0].file_path if planned_jobs else Path("unknown"),
            source_hash="hash",
            importer_name="fake",
            conversion_result=kwargs["result"],
            report_path=report_path,
            stage_block_predictions_path=stage_predictions_path,
            run_config={},
            run_config_hash=None,
            run_config_summary=None,
            llm_report={"enabled": False, "pipeline": "off"},
            timing={},
        )

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.plan_source_job",
        lambda *_args, **_kwargs: planned_jobs,
    )
    if process_pool_executor is not None:
        monkeypatch.setattr(
            "cookimport.core.executor_fallback.ProcessPoolExecutor",
            process_pool_executor,
        )
    if thread_pool_executor is not None:
        monkeypatch.setattr(
            "cookimport.core.executor_fallback.ThreadPoolExecutor",
            thread_pool_executor,
        )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._parallel_convert_worker",
        lambda *_args, **_kwargs: ("fake", fake_result),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._merge_parallel_results",
        lambda *_args, **_kwargs: fake_result,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.execute_stage_import_session_from_result",
        _fake_execute_stage_import_session_from_result,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(index=0, text="hello", location={"block_index": 0}, source_kind="raw")
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._write_processed_outputs",
        lambda **_kwargs: processed_root / "2026-02-11_00:00:00",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: [
            {"data": {"segment_id": f"seg-{i}"}} for i in range(task_count)
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 1000,
            "segment_chars": 950,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.upload.LabelStudioClient",
        FakeLabelStudioClient,
    )


def _run_split_labelstudio_import_case(
    *,
    source: Path,
    output_dir: Path,
    processed_root: Path,
    progress_messages: list[str],
) -> None:
    run_labelstudio_import(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        project_name="benchmark project",
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=False,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="test",
        limit=None,
        sample=None,
        progress_callback=progress_messages.append,
        workers=2,
        pdf_split_workers=1,
        epub_split_workers=2,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        processed_output_root=processed_root,
        allow_labelstudio_write=True,
    )


def _run_prelabel_task_progress_fixture(
    *,
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    output_dir: Path,
) -> dict[str, object]:
    fake_result = _make_empty_conversion_result(source)
    _install_basic_generate_pred_run_artifacts_mocks(
        monkeypatch,
        fake_result=fake_result,
        archive_blocks=[
            SimpleNamespace(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
        source_hash="hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: [
            {"data": {"segment_id": "seg-1"}},
            {"data": {"segment_id": "seg-2"}},
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._build_prelabel_provider",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.preflight_codex_model_access",
        lambda **_kwargs: None,
    )
    seen_granularity: list[str] = []

    def _fake_prelabel(_task, **kwargs):
        seen_granularity.append(str(kwargs.get("prelabel_granularity")))
        prompt_log_callback = kwargs.get("prompt_log_callback")
        if callable(prompt_log_callback):
            prompt_log_callback(
                {
                    "prompt": "test prompt",
                    "prompt_hash": "abc123",
                    "included_with_prompt_description": "test metadata",
                    "included_with_prompt": {"segment_block_count": 1},
                }
            )
        return {
            "result": [
                {
                    "value": {
                        "start": 0,
                        "end": 5,
                        "labels": ["TIP"],
                    }
                }
            ]
        }

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.prelabel_freeform_task",
        _fake_prelabel,
    )

    progress_messages: list[str] = []
    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        prelabel=True,
        allow_codex=True,
        prelabel_granularity="span",
        prelabel_workers=2,
        progress_callback=progress_messages.append,
    )
    prompt_log_path = result["prelabel_prompt_log_path"]
    assert prompt_log_path is not None
    return {
        "progress_messages": progress_messages,
        "seen_granularity": seen_granularity,
        "result": result,
        "prompt_log_path": prompt_log_path,
        "prompt_log_content": prompt_log_path.read_text(encoding="utf-8"),
    }


def _build_authoritative_atomic_projection_fixture(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    label_first_result = _make_label_first_result(source=source, raw_artifacts=[])
    label_first_result = label_first_result.model_copy(deep=True)
    label_first_result.labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Tahini Dressing",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=1,
            text="Makes 1 cup",
            deterministic_label="YIELD_LINE",
            final_label="YIELD_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=2,
            text="1/2 cup tahini",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
    ]
    label_first_result.block_labels = [
        AuthoritativeBlockLabel(
            source_block_id="block:0",
            source_block_index=0,
            supporting_atomic_indices=[0, 1],
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[2],
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
    ]
    label_first_result.archive_blocks = [
        {
            "index": 0,
            "block_id": "block:0",
            "text": "Tahini Dressing Makes 1 cup",
            "location": {"block_index": 0},
        },
        {
            "index": 1,
            "block_id": "block:1",
            "text": "1/2 cup tahini",
            "location": {"block_index": 1},
        },
    ]
    label_first_result.recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=1,
            block_indices=[0, 1],
            source_block_ids=["block:0", "block:1"],
            start_atomic_index=0,
            end_atomic_index=2,
            atomic_indices=[0, 1, 2],
            title_block_index=0,
            title_atomic_index=0,
        )
    ]

    artifacts, summary = _write_authoritative_line_role_artifacts(
        run_root=tmp_path,
        source_file=str(source),
        source_hash="hash-123",
        workbook_slug="book",
        label_first_result=label_first_result,
    )

    return {
        "archive_payload": json.loads(
            artifacts["extracted_archive_path"].read_text(encoding="utf-8")
        ),
        "stage_payload": json.loads(
            artifacts["stage_block_predictions_path"].read_text(encoding="utf-8")
        ),
        "summary": summary,
    }


def _build_final_nonrecipe_authority_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
) -> dict[str, object]:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = _make_projection_conversion_result(
        source=source,
        block_texts=[
            "Pancakes",
            "1 cup flour",
            "Salt strengthens flavor.",
        ],
    )

    label_first_result = _make_label_first_result(
        source=source,
        raw_artifacts=fake_result.raw_artifacts,
    ).model_copy(deep=True)
    label_first_result.labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Pancakes",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="1 cup flour",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:2",
            source_block_index=2,
            atomic_index=2,
            text="Salt strengthens flavor.",
            deterministic_label="OTHER",
            final_label="NONRECIPE_CANDIDATE",
            decided_by="rule",
        ),
    ]
    label_first_result.block_labels = [
        AuthoritativeBlockLabel(
            source_block_id="block:0",
            source_block_index=0,
            supporting_atomic_indices=[0],
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[1],
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:2",
            source_block_index=2,
            supporting_atomic_indices=[2],
            deterministic_label="OTHER",
            final_label="NONRECIPE_CANDIDATE",
            decided_by="rule",
        ),
    ]
    label_first_result.archive_blocks = [
        {
            "index": 0,
            "block_id": "block:0",
            "text": "Pancakes",
            "location": {"block_index": 0},
        },
        {
            "index": 1,
            "block_id": "block:1",
            "text": "1 cup flour",
            "location": {"block_index": 1},
        },
        {
            "index": 2,
            "block_id": "block:2",
            "text": "Salt strengthens flavor.",
            "location": {"block_index": 2},
        },
    ]
    label_first_result.recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=1,
            block_indices=[0, 1],
            source_block_ids=["block:0", "block:1"],
            start_atomic_index=0,
            end_atomic_index=1,
            atomic_indices=[0, 1],
            title_block_index=0,
            title_atomic_index=0,
        )
    ]

    final_nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({2: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[2]),
        authority=make_authority_result({2: "knowledge"}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[2],
            unreviewed_block_category_by_index={},
        ),
        refinement_report={
            "enabled": True,
            "authority_mode": "knowledge_refined_final",
            "input_mode": "nonrecipe_candidate_spans",
            "seed_nonrecipe_span_count": 1,
            "final_nonrecipe_span_count": 1,
            "changed_block_count": 1,
            "changed_blocks": [
                {
                    "block_index": 2,
                    "previous_final_category": None,
                    "final_category": "knowledge",
                    "applied_packet_ids": [],
                }
            ],
            "conflicts": [],
            "ignored_block_indices": [],
            "scored_effect": "final_authority",
        },
    )

    def _fake_execute_stage_import_session_from_result(**kwargs):
        run_root = kwargs["run_root"]
        run_root.mkdir(parents=True, exist_ok=True)
        stage_predictions_path = run_root / ".bench" / "book" / "stage_block_predictions.json"
        stage_predictions_path.parent.mkdir(parents=True, exist_ok=True)
        stage_predictions_path.write_text(
            json.dumps(
                {
                    "schema_version": "stage_block_predictions.v1",
                    "block_labels": {"0": "RECIPE_TITLE", "1": "INGREDIENT_LINE", "2": "KNOWLEDGE"},
                    "label_blocks": {
                        "RECIPE_TITLE": [0],
                        "INGREDIENT_LINE": [1],
                        "KNOWLEDGE": [2],
                    },
                    "workbook_slug": "book",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        full_text_path = run_root / "raw" / "fake" / "hash-123" / "full_text.json"
        full_text_path.parent.mkdir(parents=True, exist_ok=True)
        full_text_path.write_text("[]", encoding="utf-8")
        report_path = run_root / "book.excel_import_report.json"
        report_path.write_text("{}", encoding="utf-8")
        result = kwargs["result"]
        return StageImportSessionResult(
            run_root=run_root,
            workbook_slug="book",
            source_file=source,
            source_hash="hash-123",
            importer_name="fake",
            conversion_result=result,
            report_path=report_path,
            stage_block_predictions_path=stage_predictions_path,
            run_config={"write_markdown": kwargs.get("write_markdown")},
            run_config_hash=None,
            run_config_summary=None,
            llm_report={"enabled": False, "pipeline": "off"},
            timing={},
            label_first_result=label_first_result,
            nonrecipe_stage_result=final_nonrecipe_stage_result,
        )

    _install_projection_generate_pred_run_artifacts_mocks(
        monkeypatch,
        source=source,
        fake_result=fake_result,
        label_first_result=label_first_result,
        archive_blocks=[
            ArchiveBlock(
                index=0,
                text="Pancakes",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            ),
            ArchiveBlock(
                index=1,
                text="1 cup flour",
                location={"block_index": 1, "line_index": 0},
                source_kind="raw",
            ),
            ArchiveBlock(
                index=2,
                text="Salt strengthens flavor.",
                location={"block_index": 2, "line_index": 0},
                source_kind="raw",
            ),
        ],
        execute_stage_import_session_from_result=_fake_execute_stage_import_session_from_result,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        processed_output_root=processed_root,
        line_role_pipeline="codex-line-role-route-v2",
        allow_codex=True,
        write_label_studio_tasks=False,
        write_markdown=False,
    )
    return {
        "result": result,
    }


def _fake_pred_result(tmp_path: Path, tasks: list[dict[str, object]]) -> dict[str, object]:
    run_root = tmp_path / "2026-02-20_12.00.00" / "labelstudio" / "book"
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(
        "{}",
        encoding="utf-8",
    )
    return {
        "run_root": run_root,
        "processed_run_root": None,
        "processed_report_path": None,
        "tasks_total": len(tasks),
        "tasks": tasks,
        "manifest_path": manifest_path,
        "label_config": "<View/>",
        "run_config": {},
        "run_config_hash": None,
        "run_config_summary": None,
        "file_hash": "hash",
        "importer_name": "fake",
        "prelabel": {"enabled": True},
        "prelabel_report_path": run_root / "prelabel_report.json",
        "prelabel_errors_path": run_root / "prelabel_errors.jsonl",
    }
