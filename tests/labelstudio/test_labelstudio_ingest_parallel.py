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
from cookimport.labelstudio.ingest import (
    _acquire_split_phase_slot,
    _apply_nonrecipe_authority_to_predictions,
    _normalize_llm_recipe_pipeline,
    _write_authoritative_line_role_artifacts,
    generate_pred_run_artifacts,
    _merge_parallel_results,
    _plan_parallel_convert_jobs,
    _write_processed_outputs,
    run_labelstudio_import,
)
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
from cookimport.staging.import_session import StageImportSessionResult


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
            tips=[],
            tip_candidates=[],
            topic_candidates=[],
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


def test_llm_recipe_pipeline_normalizer_rejects_legacy_codex_farm_ids() -> None:
    with pytest.raises(ValueError, match="Invalid llm_recipe_pipeline"):
        _normalize_llm_recipe_pipeline("codex-farm-3pass-v1")
    with pytest.raises(ValueError, match="Invalid llm_recipe_pipeline"):
        _normalize_llm_recipe_pipeline("codex-farm-2stage-repair-v1")


def test_generate_pred_run_artifacts_rejects_legacy_prelabel_provider_alias(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")

    with pytest.raises(ValueError, match="prelabel_provider must be 'codex-farm'"):
        generate_pred_run_artifacts(
            path=source,
            output_dir=tmp_path / "golden",
            prelabel_provider="codex-cli",
        )


def test_generate_pred_run_artifacts_plan_mode_writes_codex_plan_without_conversion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    class FakeImporter:
        name = "fake"

        def convert(self, *_args, **_kwargs):
            return ConversionResult(
                recipes=[
                    RecipeCandidate(
                        name="Toast",
                        identifier="urn:test:toast",
                        recipeIngredient=["1 slice bread"],
                        recipeInstructions=["Toast the bread."],
                        provenance={"location": {"start_block": 0, "end_block": 1}},
                    )
                ],
                tips=[],
                tipCandidates=[],
                topicCandidates=[],
                nonRecipeBlocks=[],
                rawArtifacts=[
                    RawArtifact(
                        importer="fake",
                        sourceHash="hash",
                        locationId="full_text",
                        extension="json",
                        content={
                            "blocks": [
                                {"index": 0, "text": "Toast"},
                                {"index": 1, "text": "1 slice bread"},
                                {"index": 2, "text": "Toast the bread."},
                            ]
                        },
                        metadata={"artifact_type": "extracted_blocks"},
                    )
                ],
                report=ConversionReport(),
                workbook="book",
                workbookPath=str(source),
            )

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        codex_execution_policy="plan",
    )

    run_root = Path(result["run_root"])
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    run_manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    plan_payload = json.loads(
        (run_root / "codex_execution_plan.json").read_text(encoding="utf-8")
    )

    assert result["codex_execution_plan_only"] is True
    assert manifest["codex_execution_plan_only"] is True
    assert manifest["tasks_jsonl_status"] == "skipped_plan_only"
    assert run_manifest["artifacts"]["codex_execution_plan_json"] == "codex_execution_plan.json"
    assert run_manifest["run_config"]["codex_execution_policy_requested_mode"] == "plan"
    assert run_manifest["run_config"]["codex_execution_policy_resolved_mode"] == "plan"
    assert plan_payload["plan_only"] is True
    assert plan_payload["codex_surfaces"] == ["recipe"]
    assert plan_payload["planned_work"]["recipe_codex_farm"]["recipe_count"] == 1


def test_generate_pred_run_artifacts_plan_mode_tracks_prelabel_codex_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    class FakeImporter:
        name = "fake"

        def convert(self, *_args, **_kwargs):
            return ConversionResult(
                recipes=[],
                tips=[],
                tipCandidates=[],
                topicCandidates=[],
                nonRecipeBlocks=[],
                rawArtifacts=[
                    RawArtifact(
                        importer="fake",
                        sourceHash="hash",
                        locationId="full_text",
                        extension="json",
                        content={
                            "blocks": [
                                {"index": 0, "text": "Toast"},
                                {"index": 1, "text": "1 slice bread"},
                            ]
                        },
                        metadata={"artifact_type": "extracted_blocks"},
                    )
                ],
                report=ConversionReport(),
                workbook="book",
                workbookPath=str(source),
            )

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        prelabel=True,
        codex_execution_policy="plan",
    )

    run_root = Path(result["run_root"])
    run_manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    plan_payload = json.loads(
        (run_root / "codex_execution_plan.json").read_text(encoding="utf-8")
    )

    assert result["codex_execution_plan_only"] is True
    assert run_manifest["run_config"]["prelabel_enabled"] is True
    assert run_manifest["run_config"]["codex_decision_codex_surfaces"] == ["prelabel"]
    assert plan_payload["codex_surfaces"] == ["prelabel"]
    assert plan_payload["planned_work"]["prelabel"]["enabled"] is True


def test_generate_pred_run_artifacts_plan_mode_uses_stage7_rows_for_knowledge_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    class FakeImporter:
        name = "fake"

        def convert(self, *_args, **_kwargs):
            return ConversionResult(
                recipes=[
                    RecipeCandidate(
                        name="Toast",
                        identifier="urn:test:toast",
                        recipeIngredient=["1 slice bread"],
                        recipeInstructions=["Toast the bread."],
                        provenance={"location": {"start_block": 0, "end_block": 1}},
                    )
                ],
                tips=[],
                tipCandidates=[],
                topicCandidates=[],
                nonRecipeBlocks=[
                    {"index": 90, "text": "stale block 1"},
                    {"index": 91, "text": "stale block 2"},
                ],
                rawArtifacts=[],
                report=ConversionReport(),
                workbook="book",
                workbookPath=str(source),
            )

    authoritative_result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 0, "end_block": 1}},
            )
        ],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[
            {"index": 90, "text": "old cache 1"},
            {"index": 91, "text": "old cache 2"},
        ],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    label_result = LabelFirstStageResult(
        labeled_lines=[],
        block_labels=[
            AuthoritativeBlockLabel(
                source_block_id="b0",
                source_block_index=0,
                supporting_atomic_indices=[0],
                deterministic_label="RECIPE_TITLE",
                final_label="RECIPE_TITLE",
                decided_by="rule",
            ),
            AuthoritativeBlockLabel(
                source_block_id="b1",
                source_block_index=1,
                supporting_atomic_indices=[1],
                deterministic_label="INSTRUCTION_LINE",
                final_label="INSTRUCTION_LINE",
                decided_by="rule",
            ),
            AuthoritativeBlockLabel(
                source_block_id="b2",
                source_block_index=2,
                supporting_atomic_indices=[2],
                deterministic_label="KNOWLEDGE",
                final_label="KNOWLEDGE",
                decided_by="rule",
            ),
        ],
        recipe_spans=[
            RecipeSpan(
                span_id="recipe.0",
                start_block_index=0,
                end_block_index=2,
                block_indices=[0, 1],
                source_block_ids=["b0", "b1"],
            )
        ],
        non_recipe_lines=[],
        updated_conversion_result=authoritative_result,
        archive_blocks=[
            {"index": 0, "block_id": "b0", "text": "Toast"},
            {"index": 1, "block_id": "b1", "text": "Toast the bread."},
            {"index": 2, "block_id": "b2", "text": "Use day-old bread."},
        ],
        source_hash="hash",
    )

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_label_first_stage_result",
        lambda **_kwargs: label_result,
    )
    seen_rows: list[list[dict[str, object]]] = []

    def _capture_chunks(rows, **_kwargs):
        seen_rows.append(list(rows))
        return []

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.chunks_from_non_recipe_blocks",
        _capture_chunks,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        llm_recipe_pipeline="off",
        llm_knowledge_pipeline="codex-knowledge-shard-v1",
        codex_execution_policy="plan",
    )

    run_root = Path(result["run_root"])
    plan_payload = json.loads(
        (run_root / "codex_execution_plan.json").read_text(encoding="utf-8")
    )

    assert [row["index"] for row in seen_rows[0]] == [2]
    assert (
        plan_payload["planned_work"]["nonrecipe_knowledge_review"]["non_recipe_block_count"]
        == 1
    )


def test_plan_parallel_convert_jobs_pdf_splits(monkeypatch) -> None:
    path = Path("sample.pdf")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._resolve_pdf_page_count",
        lambda _path: 120,
    )

    jobs = _plan_parallel_convert_jobs(
        path,
        workers=2,
        pdf_split_workers=4,
        epub_split_workers=1,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
    )

    assert len(jobs) == 3
    assert jobs[0]["start_page"] == 0
    assert jobs[1]["start_page"] == 40
    assert jobs[2]["start_page"] == 80
    assert jobs[0]["start_spine"] is None


def test_plan_parallel_convert_jobs_epub_markitdown_disables_split(monkeypatch) -> None:
    path = Path("sample.epub")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._resolve_epub_spine_count",
        lambda _path: 120,
    )

    jobs = _plan_parallel_convert_jobs(
        path,
        workers=2,
        pdf_split_workers=1,
        epub_split_workers=4,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        epub_extractor="markitdown",
    )

    assert len(jobs) == 1
    assert jobs[0]["start_spine"] is None
    assert jobs[0]["end_spine"] is None


def test_plan_parallel_convert_jobs_epub_unstructured_uses_split(monkeypatch) -> None:
    path = Path("sample.epub")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._resolve_epub_spine_count",
        lambda _path: 120,
    )

    jobs = _plan_parallel_convert_jobs(
        path,
        workers=2,
        pdf_split_workers=1,
        epub_split_workers=4,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        epub_extractor="unstructured",
    )

    assert len(jobs) > 1
    assert jobs[0]["start_spine"] == 0
    assert jobs[-1]["end_spine"] == 120


def test_split_phase_slot_gate_emits_wait_acquire_release(
    monkeypatch, tmp_path: Path
) -> None:
    gate_dir = tmp_path / "split-slot-gate"
    messages: list[str] = []
    attempts = {"count": 0}

    def fake_try_lock(_handle) -> bool:
        attempts["count"] += 1
        return attempts["count"] >= 3

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._try_acquire_file_lock_nonblocking",
        fake_try_lock,
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.time.sleep", lambda *_: None)

    with _acquire_split_phase_slot(
        slots=2,
        gate_dir=gate_dir,
        notify=messages.append,
        status_label="Config 1/4",
    ):
        pass

    assert any("waiting for split slot" in message for message in messages)
    assert any("acquired split slot" in message for message in messages)
    assert any("released split slot" in message for message in messages)


def test_merge_parallel_results_combines_and_reorders(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_text("source", encoding="utf-8")

    job_a = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Later",
                identifier="old-later",
                provenance={"location": {"start_page": 9, "start_block": 20}},
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="pdf",
                source_hash="hash-a",
                location_id="loc-a",
                extension="json",
                content={
                    "block_count": 3,
                    "blocks": [
                        {"index": 0, "text": "a"},
                        {"index": 1, "text": "b"},
                        {"index": 2, "text": "c"},
                    ],
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )
    job_b = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Earlier",
                identifier="old-earlier",
                provenance={"location": {"start_page": 1, "start_block": 1}},
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="pdf",
                source_hash="hash-b",
                location_id="loc-b",
                extension="json",
                content={
                    "block_count": 2,
                    "blocks": [
                        {"index": 0, "text": "x"},
                        {"index": 1, "text": "y"},
                    ],
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    merged = _merge_parallel_results(
        source,
        "pdf",
        [
            {"job_index": 1, "start_page": 8, "result": job_a},
            {"job_index": 0, "start_page": 0, "result": job_b},
        ],
    )

    assert len(merged.recipes) == 2
    assert merged.recipes[0].name == "Earlier"
    assert merged.recipes[1].name == "Later"
    assert merged.recipes[0].identifier != "old-earlier"
    assert merged.recipes[1].identifier != "old-later"
    assert merged.recipes[1].provenance["location"]["start_block"] == 22
    assert len(merged.raw_artifacts) == 2
    shifted = next(artifact for artifact in merged.raw_artifacts if artifact.source_hash == "hash-a")
    shifted_indices = [block["index"] for block in shifted.content["blocks"]]
    assert shifted_indices == [2, 3, 4]
    assert merged.report.total_recipes == 2
    assert merged.report.total_tip_candidates == 0
    assert merged.report.total_topic_candidates == 0
    assert merged.report.total_standalone_blocks == 0


def test_write_processed_outputs_writes_report_total_mismatch_diagnostics(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_root = tmp_path / "processed"

    result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Simple Soup",
                ingredients=["1 cup stock"],
                instructions=["Heat stock."],
                identifier="urn:recipeimport:test:soup",
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(
            total_recipes=9,
            total_tips=8,
            total_tip_candidates=7,
            total_topic_candidates=6,
            total_standalone_blocks=5,
            total_standalone_topic_blocks=4,
        ),
        workbook="book",
        workbook_path=str(source),
    )

    run_dt = dt.datetime(2026, 3, 4, 12, 34, 56)
    run_root = _write_processed_outputs(
        result=result,
        path=source,
        run_dt=run_dt,
        output_root=output_root,
        importer_name="epub",
        run_config={"table_extraction": "off"},
    )

    mismatch_path = run_root / "book.report_totals_mismatch_diagnostics.json"
    assert not mismatch_path.exists()
    authority_mismatch_path = (
        run_root / "group_recipe_spans" / "book" / "authority_mismatch.json"
    )
    assert authority_mismatch_path.exists()

    report_path = run_root / "book.excel_import_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["totalRecipes"] == 0
    assert payload["totalTips"] == 0
    assert not any(
        "report_total_mismatch_detected" in warning
        for warning in payload.get("warnings", [])
    )


def test_write_processed_outputs_writes_report_total_mismatch_diagnostics_for_explicit_zero_totals(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_root = tmp_path / "processed"

    result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Simple Soup",
                ingredients=["1 cup stock"],
                instructions=["Heat stock."],
                identifier="urn:recipeimport:test:soup",
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(
            total_recipes=0,
            total_tips=0,
            total_tip_candidates=0,
            total_topic_candidates=0,
            total_standalone_blocks=0,
            total_standalone_topic_blocks=0,
        ),
        workbook="book",
        workbook_path=str(source),
    )

    run_dt = dt.datetime(2026, 3, 4, 12, 34, 56)
    run_root = _write_processed_outputs(
        result=result,
        path=source,
        run_dt=run_dt,
        output_root=output_root,
        importer_name="epub",
        run_config={"table_extraction": "off"},
    )

    mismatch_path = run_root / "book.report_totals_mismatch_diagnostics.json"
    assert not mismatch_path.exists()


def test_write_processed_outputs_writes_report_total_mismatch_diagnostics_for_implicit_defaults(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_root = tmp_path / "processed"

    result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Simple Soup",
                ingredients=["1 cup stock"],
                instructions=["Heat stock."],
                identifier="urn:recipeimport:test:soup",
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    run_dt = dt.datetime(2026, 3, 4, 12, 34, 56)
    run_root = _write_processed_outputs(
        result=result,
        path=source,
        run_dt=run_dt,
        output_root=output_root,
        importer_name="epub",
        run_config={"table_extraction": "off"},
    )

    mismatch_path = run_root / "book.report_totals_mismatch_diagnostics.json"
    assert not mismatch_path.exists()

    report_path = run_root / "book.excel_import_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert not any(
        "report_total_mismatch_detected" in warning
        for warning in payload.get("warnings", [])
    )


def test_run_labelstudio_import_emits_post_merge_progress(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

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

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks):
            self.uploaded_batches.append(len(tasks))

    monkeypatch.setattr("cookimport.labelstudio.ingest.registry.get_importer", lambda _name: FakeImporter())
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._plan_parallel_convert_jobs",
        lambda *_args, **_kwargs: [{"job_index": 0, "start_page": None, "end_page": None, "start_spine": None, "end_spine": None}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(index=0, text="hello", location={"block_index": 0}, source_kind="raw")
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._write_processed_outputs",
        lambda **_kwargs: processed_root / "2026-02-11_00:00:00",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [
            {"data": {"segment_id": f"seg-{i}"}} for i in range(401)
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 1000,
            "segment_chars": 950,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.LabelStudioClient", FakeLabelStudioClient)

    progress_messages: list[str] = []
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
        epub_split_workers=1,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        processed_output_root=processed_root,
        allow_labelstudio_write=True,
    )

    assert "Building extracted archive..." in progress_messages
    assert "Writing processed cookbook outputs..." in progress_messages
    assert "Building freeform span tasks..." in progress_messages
    assert "Uploading 401 task(s) in 3 batch(es)..." in progress_messages
    assert "Uploaded 401/401 task(s)." in progress_messages
    assert progress_messages[-1] == "Label Studio import artifacts complete."


def test_run_labelstudio_import_split_workers_emit_worker_activity(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="cookimport.config.run_settings")
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

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

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._plan_parallel_convert_jobs",
        lambda *_args, **_kwargs: [
            {
                "job_index": 0,
                "start_page": None,
                "end_page": None,
                "start_spine": 0,
                "end_spine": 10,
            },
            {
                "job_index": 1,
                "start_page": None,
                "end_page": None,
                "start_spine": 10,
                "end_spine": 20,
            },
            {
                "job_index": 2,
                "start_page": None,
                "end_page": None,
                "start_spine": 20,
                "end_spine": 30,
            },
        ],
    )
    monkeypatch.setattr(
        "cookimport.core.executor_fallback.ProcessPoolExecutor",
        ThreadPoolExecutor,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._parallel_convert_worker",
        lambda *_args, **_kwargs: ("fake", fake_result),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._merge_parallel_results",
        lambda *_args, **_kwargs: fake_result,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(index=0, text="hello", location={"block_index": 0}, source_kind="raw")
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._write_processed_outputs",
        lambda **_kwargs: processed_root / "2026-02-11_00:00:00",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [
            {"data": {"segment_id": f"seg-{i}"}} for i in range(5)
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 1000,
            "segment_chars": 950,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    progress_messages: list[str] = []
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

    assert any(
        "Running split conversion... task 0/3 (workers=2)" in message
        for message in progress_messages
    )
    assert any(
        "Running split conversion... task 3/3 (workers=2)" in message
        for message in progress_messages
    )
    worker_events = [
        parse_worker_activity(message) for message in progress_messages
    ]
    assert any(
        isinstance(event, dict)
        and event.get("type") == "activity"
        and event.get("worker_total") == 2
        and str(event.get("status") or "").startswith("job ")
        for event in worker_events
    )
    assert any(
        isinstance(event, dict) and event.get("type") == "reset"
        for event in worker_events
    )
    assert not any(
        "Ignoring unknown labelstudio split run config keys" in record.getMessage()
        for record in caplog.records
    )


def test_run_labelstudio_import_split_workers_fallback_to_thread_on_process_denied(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    class FakeLabelStudioClient:
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

        def import_tasks(self, _project_id: int, _tasks):
            return None

    class BrokenProcessPoolExecutor:
        def __init__(self, *_args, **_kwargs) -> None:
            raise PermissionError("sandbox denied")

    thread_pool_started = {"count": 0}

    class TrackingThreadPoolExecutor(ThreadPoolExecutor):
        def __init__(self, *args, **kwargs):
            thread_pool_started["count"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._plan_parallel_convert_jobs",
        lambda *_args, **_kwargs: [
            {
                "job_index": 0,
                "start_page": None,
                "end_page": None,
                "start_spine": 0,
                "end_spine": 10,
            },
            {
                "job_index": 1,
                "start_page": None,
                "end_page": None,
                "start_spine": 10,
                "end_spine": 20,
            },
            {
                "job_index": 2,
                "start_page": None,
                "end_page": None,
                "start_spine": 20,
                "end_spine": 30,
            },
        ],
    )
    monkeypatch.setattr(
        "cookimport.core.executor_fallback.ProcessPoolExecutor",
        BrokenProcessPoolExecutor,
    )
    monkeypatch.setattr(
        "cookimport.core.executor_fallback.ThreadPoolExecutor",
        TrackingThreadPoolExecutor,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._parallel_convert_worker",
        lambda *_args, **_kwargs: ("fake", fake_result),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._merge_parallel_results",
        lambda *_args, **_kwargs: fake_result,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(index=0, text="hello", location={"block_index": 0}, source_kind="raw")
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._write_processed_outputs",
        lambda **_kwargs: processed_root / "2026-02-11_00:00:00",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [
            {"data": {"segment_id": f"seg-{i}"}} for i in range(5)
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 1000,
            "segment_chars": 950,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    progress_messages: list[str] = []
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

    assert thread_pool_started["count"] >= 1
    assert any(
        "using thread-based worker concurrency" in message.lower()
        for message in progress_messages
    )
    assert not any(
        "running split jobs serially" in message.lower()
        for message in progress_messages
    )
    worker_events = [parse_worker_activity(message) for message in progress_messages]
    assert any(
        isinstance(event, dict)
        and event.get("type") == "activity"
        and event.get("worker_total") == 2
        for event in worker_events
    )


def test_generate_pred_run_artifacts_reports_prelabel_task_progress(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    tasks = [
        {"data": {"segment_id": "seg-1"}},
        {"data": {"segment_id": "seg-2"}},
    ]

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks_in, **_kwargs: tasks_in,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._build_prelabel_provider",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.preflight_codex_model_access",
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
        "cookimport.labelstudio.ingest.prelabel_freeform_task",
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

    assert any(
        "Running freeform prelabeling... task 0/2" in msg
        for msg in progress_messages
    )
    assert any("workers=2" in msg and "task 0/2" in msg for msg in progress_messages)
    assert any(
        "Running freeform prelabeling... task 1/2" in msg
        for msg in progress_messages
    )
    assert any("workers=2" in msg and "task 1/2" in msg for msg in progress_messages)
    assert any(
        "Running freeform prelabeling... task 2/2" in msg
        for msg in progress_messages
    )
    assert any("workers=2" in msg and "task 2/2" in msg for msg in progress_messages)
    worker_events = [
        parse_worker_activity(message)
        for message in progress_messages
    ]
    assert any(
        isinstance(event, dict)
        and event.get("type") == "activity"
        and event.get("worker_total") == 2
        and str(event.get("status") or "").startswith("task ")
        for event in worker_events
    )
    assert seen_granularity == ["span", "span"]
    assert result["prelabel"]["granularity"] == "span"
    assert result["prelabel"]["workers"] == 2
    assert result["prelabel"]["prompt_log_count"] == 2
    prompt_log_path = result["prelabel_prompt_log_path"]
    assert prompt_log_path is not None
    assert prompt_log_path.name == "prelabel_prompt_log.md"
    content = prompt_log_path.read_text(encoding="utf-8")
    assert "# Prelabel Prompt Log" in content
    assert "## Task 1/2 - `seg-1`" in content
    assert "## Task 2/2 - `seg-2`" in content
    assert "test metadata" in content
    assert "test prompt" in content


def test_generate_pred_run_artifacts_stops_prelabel_after_rate_limit_429(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    tasks = [
        {"data": {"segment_id": "seg-1"}},
        {"data": {"segment_id": "seg-2"}},
        {"data": {"segment_id": "seg-3"}},
    ]

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks_in, **_kwargs: tasks_in,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._build_prelabel_provider",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.preflight_codex_model_access",
        lambda **_kwargs: None,
    )

    prelabel_calls: list[str] = []

    def _fake_prelabel(task_payload, **_kwargs):
        segment_id = str(task_payload.get("data", {}).get("segment_id") or "")
        prelabel_calls.append(segment_id)
        raise RuntimeError("HTTP 429 Too Many Requests: rate limit exceeded")

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.prelabel_freeform_task",
        _fake_prelabel,
    )

    progress_messages: list[str] = []
    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        prelabel=True,
        allow_codex=True,
        prelabel_workers=1,
        prelabel_allow_partial=True,
        progress_callback=progress_messages.append,
    )

    assert prelabel_calls == ["seg-1"]
    assert any("HTTP 429" in message for message in progress_messages)
    prelabel_summary = result["prelabel"]
    assert prelabel_summary["rate_limit_stop_triggered"] is True
    assert prelabel_summary["rate_limit_failure_count"] == 1
    assert prelabel_summary["rate_limit_skipped_count"] == 2
    assert prelabel_summary["failure_count"] == 3
    assert prelabel_summary["success_count"] == 0

    errors_path = result["prelabel_errors_path"]
    assert errors_path is not None
    rows = [
        json.loads(line)
        for line in errors_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 3
    assert rows[0]["segment_id"] == "seg-1"
    assert rows[0]["rate_limit"] is True


def test_generate_pred_run_artifacts_ignores_progress_callback_errors(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._plan_parallel_convert_jobs",
        lambda *_args, **_kwargs: [
            {
                "job_index": 0,
                "start_page": None,
                "end_page": None,
                "start_spine": None,
                "end_spine": None,
            }
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._write_processed_outputs",
        lambda **_kwargs: output_dir / "processed",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "segment_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )

    progress_messages: list[str] = []

    def _broken_callback(message: str) -> None:
        progress_messages.append(message)
        raise RuntimeError("ui callback failed")

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        progress_callback=_broken_callback,
    )

    assert result["tasks_total"] == 1
    assert "fake convert complete" in progress_messages


def test_generate_pred_run_artifacts_can_skip_tasks_jsonl(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "segment_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        write_label_studio_tasks=False,
    )

    run_root = Path(result["run_root"])
    assert not (run_root / "label_studio_tasks.jsonl").exists()
    assert result["tasks_jsonl_status"] == "skipped_by_config"

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tasks_jsonl_status"] == "skipped_by_config"
    assert manifest["write_label_studio_tasks"] is False

    run_manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["artifacts"]["tasks_jsonl_status"] == "skipped_by_config"
    assert "tasks_jsonl" not in run_manifest["artifacts"]


def test_generate_pred_run_artifacts_line_role_projection_prefers_projection_for_scoring(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="fake",
                sourceHash="hash-123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Pancakes"},
                        {"index": 1, "text": "SERVES 2"},
                        {"index": 2, "text": "1 cup flour"},
                        {"index": 3, "text": "Whisk batter"},
                        {"index": 4, "text": "NOTE: Keep warm"},
                    ]
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )
    label_first_result = _make_label_first_result(
        source=source,
        raw_artifacts=fake_result.raw_artifacts,
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Pancakes SERVES 2 1 cup flour; Whisk batter NOTE: Keep warm",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Toast the bread.",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash-123",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_label_first_stage_result",
        lambda **_kwargs: label_first_result,
    )
    monkeypatch.setattr(
        "cookimport.staging.import_session.build_label_first_stage_result",
        lambda **_kwargs: label_first_result,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        processed_output_root=processed_root,
        line_role_pipeline="codex-line-role-shard-v1",
        allow_codex=True,
        write_label_studio_tasks=False,
        write_markdown=False,
    )

    projected_spans_path = result["line_role_pipeline_projected_spans_path"]
    assert projected_spans_path is not None and projected_spans_path.exists()
    projected_stage_path = projected_spans_path.parent / "stage_block_predictions.json"
    projected_archive_path = projected_spans_path.parent / "extracted_archive.json"
    assert projected_stage_path.exists()
    assert projected_archive_path.exists()
    processed_run_root = Path(result["processed_run_root"])
    processed_stage_path = (
        processed_run_root / ".bench" / "book" / "stage_block_predictions.json"
    )
    mirrored_stage_path = Path(result["stage_block_predictions_path"])
    assert mirrored_stage_path == projected_stage_path
    assert result["extracted_archive_path"] == projected_archive_path
    assert processed_stage_path.exists()
    assert processed_stage_path != projected_stage_path

    stage_payload = json.loads(mirrored_stage_path.read_text(encoding="utf-8"))
    assert stage_payload["block_labels"]["0"] == "RECIPE_TITLE"
    assert stage_payload["block_labels"]["1"] == "YIELD_LINE"
    assert stage_payload["block_labels"]["2"] == "INGREDIENT_LINE"
    assert stage_payload["block_labels"]["3"] == "INSTRUCTION_LINE"
    assert stage_payload["block_labels"]["4"] == "RECIPE_NOTES"

    projected_rows = [
        json.loads(line)
        for line in projected_spans_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    predicted_ingredients = [
        row["text"] for row in projected_rows if row.get("label") == "INGREDIENT_LINE"
    ]
    predicted_instructions = [
        row["text"] for row in projected_rows if row.get("label") == "INSTRUCTION_LINE"
    ]
    predicted_notes = [
        row["text"] for row in projected_rows if row.get("label") == "RECIPE_NOTES"
    ]

    processed_draft = json.loads(
        (
            processed_run_root
            / "final drafts"
            / "book"
            / "r0.json"
        ).read_text(encoding="utf-8")
    )
    assert processed_draft["recipe"]["title"] == "Pancakes"
    assert [
        line["raw_text"]
        for step in processed_draft["steps"]
        for line in step.get("ingredient_lines", [])
    ] == predicted_ingredients
    assert processed_draft["steps"][0]["instruction"] == "Gather and prepare ingredients."
    assert [step["instruction"] for step in processed_draft["steps"][1:]] == predicted_instructions
    assert predicted_notes == ["NOTE: Keep warm"]
    assert result["line_role_pipeline_recipe_projection"]["recipes_applied"] == 1
    assert (
        result["line_role_pipeline_recipe_projection"][
            "authoritative_stage_outputs_mutated"
        ]
        is False
    )


def test_authoritative_line_role_artifacts_preserve_atomic_projection_semantics(
    tmp_path: Path,
) -> None:
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

    stage_payload = json.loads(
        artifacts["stage_block_predictions_path"].read_text(encoding="utf-8")
    )
    archive_payload = json.loads(
        artifacts["extracted_archive_path"].read_text(encoding="utf-8")
    )

    assert stage_payload["block_count"] == 3
    assert stage_payload["block_labels"] == {
        "0": "RECIPE_TITLE",
        "1": "YIELD_LINE",
        "2": "INGREDIENT_LINE",
    }
    assert len(archive_payload) == 3
    assert archive_payload[1]["location"]["features"]["line_role_projection"] is True
    assert archive_payload[1]["location"]["block_index"] == 0
    assert summary["span_count"] == 3


def test_generate_pred_run_artifacts_processed_output_reuses_final_nonrecipe_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="fake",
                sourceHash="hash-123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Pancakes"},
                        {"index": 1, "text": "1 cup flour"},
                        {"index": 2, "text": "Salt strengthens flavor."},
                    ]
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
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
            final_label="OTHER",
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
            final_label="OTHER",
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

    final_nonrecipe_stage_result = NonRecipeStageResult(
        nonrecipe_spans=[],
        knowledge_spans=[],
        other_spans=[],
        block_category_by_index={2: "knowledge"},
        seed_block_category_by_index={2: "other"},
        refinement_report={
            "enabled": True,
            "authority_mode": "knowledge_refined_final_authority",
            "input_mode": "stage7_seed_nonrecipe_spans",
            "seed_nonrecipe_span_count": 1,
            "final_nonrecipe_span_count": 1,
            "changed_block_count": 1,
            "changed_blocks": [
                {
                    "block_index": 2,
                    "seed_category": "other",
                    "final_category": "knowledge",
                }
            ],
            "conflicts": [],
            "ignored_block_indices": [],
            "scored_effect": "mutated",
        },
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

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

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash-123",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
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
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.execute_stage_import_session_from_result",
        _fake_execute_stage_import_session_from_result,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        processed_output_root=processed_root,
        line_role_pipeline="codex-line-role-shard-v1",
        allow_codex=True,
        write_label_studio_tasks=False,
        write_markdown=False,
    )

    stage_payload = json.loads(
        Path(result["stage_block_predictions_path"]).read_text(encoding="utf-8")
    )
    telemetry_payload = json.loads(
        (
            Path(result["line_role_pipeline_projected_spans_path"]).parent
            / "telemetry_summary.json"
        ).read_text(encoding="utf-8")
    )

    assert stage_payload["block_labels"]["2"] == "KNOWLEDGE"
    assert result["line_role_pipeline_recipe_projection"][
        "authoritative_stage_outputs_mutated"
    ] is True
    assert result["line_role_pipeline_recipe_projection"]["mode"] == (
        "final_authority_projection"
    )
    assert telemetry_payload["mode"] == "final_authority_projection"
    assert telemetry_payload["changed_block_indices"] == [2]


def test_nonrecipe_authority_projection_preserves_recipe_notes_outside_recipe() -> None:
    predictions = [
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:10",
            block_index=10,
            atomic_index=10,
            text="Refrigerate leftovers, covered, for up to 3 days.",
            within_recipe_span=False,
            label="RECIPE_NOTES",
            decided_by="rule",
            reason_tags=["storage_or_serving_note"],
        )
    ]
    nonrecipe_stage_result = NonRecipeStageResult(
        nonrecipe_spans=[],
        knowledge_spans=[],
        other_spans=[],
        block_category_by_index={10: "other"},
        refinement_report={
            "authority_mode": "deterministic_seed_only",
            "scored_effect": "seed_only",
            "changed_blocks": [{"block_index": 10}],
        },
    )

    adjusted, summary = _apply_nonrecipe_authority_to_predictions(
        predictions=predictions,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    assert summary["changed_block_count"] == 1
    assert len(adjusted) == 1
    assert adjusted[0].label == "RECIPE_NOTES"
    assert "nonrecipe_authority:other" not in adjusted[0].reason_tags


def test_generate_pred_run_artifacts_line_role_lets_labeler_resolve_inflight_default(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    observed_codex_max_inflight: list[int | None] = []

    def _fake_label_atomic_lines_with_baseline(candidates, _settings, **kwargs):
        observed_codex_max_inflight.append(kwargs.get("codex_max_inflight"))
        predictions = [
            CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                block_id=candidate.block_id,
                block_index=candidate.block_index,
                atomic_index=candidate.atomic_index,
                text=str(candidate.text),
                label="OTHER",
                decided_by="rule",
                reason_tags=["test_label"],
            )
            for candidate in candidates
        ]
        return predictions, predictions

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash-123",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._build_line_role_candidates_from_archive",
        lambda **_kwargs: [
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id="block:0",
                block_index=0,
                atomic_index=0,
                text="Example line",
                within_recipe_span=True,
            ),
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.label_atomic_lines_with_baseline",
        _fake_label_atomic_lines_with_baseline,
    )

    generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        line_role_pipeline="codex-line-role-shard-v1",
        allow_codex=True,
        split_phase_slots=1,
        write_label_studio_tasks=False,
        write_markdown=False,
    )

    assert observed_codex_max_inflight == [None]


def test_generate_pred_run_artifacts_writes_authoritative_line_role_artifacts_after_llm_recipe_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    initial_result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 99, "end_block": 99}},
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )
    updated_result = initial_result.model_copy(deep=True)
    updated_result.recipes[0].provenance = {
        "location": {"start_block": 0, "end_block": 0}
    }

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return initial_result.model_copy(deep=True)

    def _fake_run_codex_farm_recipe_pipeline(**_kwargs):
        return SimpleNamespace(
            updated_conversion_result=updated_result.model_copy(deep=True),
            intermediate_overrides_by_recipe_id={},
            final_overrides_by_recipe_id={},
            llm_report={"enabled": True, "pipeline": "codex-recipe-shard-v1"},
        )

    authoritative_calls: list[int] = []

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Toast the bread.",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash-123",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.run_codex_farm_recipe_pipeline",
        _fake_run_codex_farm_recipe_pipeline,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._write_authoritative_line_role_artifacts",
        lambda **_kwargs: (
            authoritative_calls.append(1) or {
                "line_role_predictions_path": tmp_path / "line_role_predictions.jsonl",
                "projected_spans_path": tmp_path / "projected_spans.jsonl",
                "stage_block_predictions_path": tmp_path / "stage_block_predictions.json",
                "extracted_archive_path": tmp_path / "extracted_archive.json",
            },
            {
                "recipes_applied": 0,
                "span_count": 0,
                "authoritative_stage_outputs_mutated": False,
                "mode": "authoritative_reuse",
            },
        ),
    )

    generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-shard-v1",
        allow_codex=True,
        write_label_studio_tasks=False,
        write_markdown=False,
    )

    assert authoritative_calls == [1]


def test_generate_pred_run_artifacts_passes_allow_codex_to_line_role_live_llm(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    observed_live_llm_allowed: list[bool | None] = []

    def _fake_label_atomic_lines_with_baseline(candidates, _settings, **kwargs):
        observed_live_llm_allowed.append(kwargs.get("live_llm_allowed"))
        predictions = [
            CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                block_id=candidate.block_id,
                block_index=candidate.block_index,
                atomic_index=candidate.atomic_index,
                text=str(candidate.text),
                label="OTHER",
                decided_by="rule",
                reason_tags=["test_label"],
            )
            for candidate in candidates
        ]
        return predictions, predictions

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash-123",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._build_line_role_candidates_from_archive",
        lambda **_kwargs: [
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id="block:0",
                block_index=0,
                atomic_index=0,
                text="Example line",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            ),
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.label_atomic_lines_with_baseline",
        _fake_label_atomic_lines_with_baseline,
    )

    generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        line_role_pipeline="codex-line-role-shard-v1",
        allow_codex=True,
        split_phase_slots=1,
        write_label_studio_tasks=False,
        write_markdown=False,
    )

    assert observed_live_llm_allowed == [True]


def test_generate_pred_run_artifacts_passes_write_markdown_to_processed_outputs(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "segment_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )

    captured: dict[str, object] = {}

    def _fake_execute_stage_import_session_from_result(**kwargs):
        captured["write_markdown"] = kwargs.get("write_markdown")
        run_root = tmp_path / "processed-output" / "2026-03-03_02.00.00"
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
        )

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.execute_stage_import_session_from_result",
        _fake_execute_stage_import_session_from_result,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        processed_output_root=tmp_path / "processed-output",
        write_markdown=False,
    )

    assert captured["write_markdown"] is False
    assert result["run_config"]["write_markdown"] is False


def test_prepare_extracted_archive_matches_legacy_payload(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_text("source", encoding="utf-8")
    raw_artifacts = [
        RawArtifact(
            importer="pdf",
            source_hash="hash-123",
            location_id="full_text",
            extension="json",
            content={
                "blocks": [
                    {"index": 0, "text": "First block", "page": 1},
                    {"index": 1, "text": "Second block", "page": 1},
                ]
            },
            metadata={"artifact_type": "extracted_blocks"},
        )
    ]
    result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=raw_artifacts,
        report=ConversionReport(),
        workbook=source.stem,
        workbook_path=str(source),
    )

    legacy_archive = build_extracted_archive(result, raw_artifacts)
    prepared_archive = prepare_extracted_archive(
        result=result,
        raw_artifacts=raw_artifacts,
        source_file=source.name,
        source_hash="hash-123",
        archive_builder=build_extracted_archive,
    )
    legacy_payload = [
        {
            "index": block.index,
            "text": block.text,
            "location": block.location,
            "source_kind": block.source_kind,
        }
        for block in legacy_archive
    ]

    assert prepared_archive_payload(prepared_archive) == legacy_payload
    assert list(prepared_archive.blocks) == legacy_archive
    assert prepared_archive.block_count == len(legacy_archive)


def test_generate_pred_run_artifacts_markdown_toggle_keeps_stage_predictions_identical(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")

    fake_result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Recipe",
                provenance={"location": {"start_block": 0}},
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="epub",
                source_hash="hash",
                location_id="full_text",
                extension="json",
                content={"blocks": [{"index": 0, "text": "Recipe"}]},
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "segment_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )

    with_markdown = generate_pred_run_artifacts(
        path=source,
        output_dir=tmp_path / "golden-a",
        pipeline="fake",
        processed_output_root=tmp_path / "processed-a",
        write_markdown=True,
        write_label_studio_tasks=False,
    )
    without_markdown = generate_pred_run_artifacts(
        path=source,
        output_dir=tmp_path / "golden-b",
        pipeline="fake",
        processed_output_root=tmp_path / "processed-b",
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert with_markdown["stage_block_predictions_path"] is not None
    assert without_markdown["stage_block_predictions_path"] is not None
    with_stage_path = Path(with_markdown["stage_block_predictions_path"])
    without_stage_path = Path(without_markdown["stage_block_predictions_path"])
    with_stage_payload = json.loads(with_stage_path.read_text(encoding="utf-8"))
    without_stage_payload = json.loads(without_stage_path.read_text(encoding="utf-8"))
    assert with_stage_payload == without_stage_payload

    with_archive_payload = json.loads(
        (Path(with_markdown["run_root"]) / "extracted_archive.json").read_text(
            encoding="utf-8"
        )
    )
    without_archive_payload = json.loads(
        (Path(without_markdown["run_root"]) / "extracted_archive.json").read_text(
            encoding="utf-8"
        )
    )
    assert with_archive_payload == without_archive_payload


def test_generate_pred_run_artifacts_freeform_focus_and_target_manifest_fields(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=i,
                text=f"block {i}",
                location={"block_index": i},
                source_kind="raw",
            )
            for i in range(9)
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks_in, **_kwargs: tasks_in,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        segment_blocks=4,
        segment_overlap=1,
        segment_focus_blocks=2,
        target_task_count=4,
        prelabel=False,
    )

    manifest = json.loads(result["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["segment_blocks"] == 4
    assert manifest["segment_focus_blocks"] == 2
    assert manifest["segment_overlap_requested"] == 1
    assert manifest["segment_overlap_effective"] == 2
    assert manifest["segment_overlap"] == 2
    assert manifest["target_task_count"] == 4
    assert manifest["task_count"] == 4
    assert isinstance(manifest.get("timing"), dict)
    assert manifest["timing"]["total_seconds"] >= 0.0
    assert manifest["timing"]["prediction_seconds"] >= 0.0
    assert manifest["timing"]["checkpoints"]["conversion_seconds"] >= 0.0

    assert result["tasks"][0]["data"]["segment_text"] == "block 1\n\nblock 2"
    assert isinstance(result.get("timing"), dict)
    assert result["timing"]["total_seconds"] >= 0.0
    first_source_map = result["tasks"][0]["data"]["source_map"]
    assert first_source_map["focus_start_block_index"] == 1
    assert first_source_map["focus_end_block_index"] == 2
    assert first_source_map["focus_block_indices"] == [1, 2]
    assert first_source_map["context_before_block_range"] == "0"
    assert first_source_map["context_after_block_range"] == "3"


def test_generate_pred_run_artifacts_freeform_focus_floor_adjusts_overlap_without_target(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=i,
                text=f"block {i}",
                location={"block_index": i},
                source_kind="raw",
            )
            for i in range(9)
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks_in, **_kwargs: tasks_in,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        segment_blocks=4,
        segment_overlap=1,
        segment_focus_blocks=2,
        target_task_count=None,
        prelabel=False,
    )

    manifest = json.loads(result["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["segment_blocks"] == 4
    assert manifest["segment_focus_blocks"] == 2
    assert manifest["segment_overlap_requested"] == 1
    assert manifest["segment_overlap_effective"] == 2
    assert manifest["segment_overlap"] == 2
    assert manifest["target_task_count"] is None
    assert manifest["task_count"] == 4


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


def test_run_labelstudio_import_falls_back_to_post_import_annotations(
    monkeypatch, tmp_path: Path
) -> None:
    tasks = [
        {
            "data": {"segment_id": "seg-1"},
            "annotations": [{"result": [{"value": {"start": 0, "end": 5, "labels": ["TIP"]}}]}],
        },
        {
            "data": {"segment_id": "seg-2"},
            "annotations": [{"result": [{"value": {"start": 6, "end": 11, "labels": ["NOTES"]}}]}],
        },
    ]

    class FakeLabelStudioClient:
        inline_rejections = 0
        created_annotations: list[tuple[int, dict[str, object]]] = []
        imported_batches: list[list[dict[str, object]]] = []

        def __init__(self, _url: str, _key: str) -> None:
            return None

        def list_projects(self):
            return []

        def find_project_by_title(self, _title: str):
            return None

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks_payload):
            payload = [dict(item) for item in tasks_payload]
            self.imported_batches.append(payload)
            if any("annotations" in item for item in payload):
                FakeLabelStudioClient.inline_rejections += 1
                raise RuntimeError("inline annotation import rejected")
            return {"task_count": len(payload)}

        def list_project_tasks(self, _project_id: int):
            return [
                {"id": 501, "data": {"segment_id": "seg-1"}},
                {"id": 502, "data": {"segment_id": "seg-2"}},
            ]

        def create_annotation(self, task_id: int, annotation: dict[str, object]):
            self.created_annotations.append((task_id, annotation))
            return {"id": len(self.created_annotations)}

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    result = run_labelstudio_import(
        path=tmp_path / "book.epub",
        output_dir=tmp_path / "golden",
        pipeline="auto",
        project_name="prelabel test",
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=False,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        limit=None,
        sample=None,
        prelabel=True,
        prelabel_upload_as="annotations",
        allow_codex=True,
        allow_labelstudio_write=True,
    )

    assert result["tasks_uploaded"] == 2
    assert result["prelabel_inline_annotations_fallback"] is True
    assert result["prelabel_post_import_annotations_created"] == 2
    assert FakeLabelStudioClient.inline_rejections == 1
    assert len(FakeLabelStudioClient.created_annotations) == 2


def test_run_labelstudio_import_can_upload_prelabels_as_predictions(
    monkeypatch, tmp_path: Path
) -> None:
    tasks = [
        {
            "data": {"segment_id": "seg-1"},
            "annotations": [{"result": [{"value": {"start": 0, "end": 5, "labels": ["TIP"]}}]}],
        }
    ]

    class FakeLabelStudioClient:
        imported_batches: list[list[dict[str, object]]] = []

        def __init__(self, _url: str, _key: str) -> None:
            return None

        def list_projects(self):
            return []

        def find_project_by_title(self, _title: str):
            return None

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks_payload):
            payload = [dict(item) for item in tasks_payload]
            self.imported_batches.append(payload)
            return {"task_count": len(payload)}

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    run_labelstudio_import(
        path=tmp_path / "book.epub",
        output_dir=tmp_path / "golden",
        pipeline="auto",
        project_name="prelabel prediction test",
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=False,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        limit=None,
        sample=None,
        prelabel=True,
        prelabel_upload_as="predictions",
        allow_codex=True,
        allow_labelstudio_write=True,
    )

    assert len(FakeLabelStudioClient.imported_batches) == 1
    uploaded = FakeLabelStudioClient.imported_batches[0][0]
    assert "predictions" in uploaded
    assert "annotations" not in uploaded


def test_run_labelstudio_import_skips_resume_manifest_when_project_is_new(
    monkeypatch, tmp_path: Path
) -> None:
    output_dir = tmp_path / "golden"
    stale_manifest = output_dir / "2026-02-10_00.00.00" / "labelstudio" / "book" / "manifest.json"
    stale_manifest.parent.mkdir(parents=True, exist_ok=True)
    stale_manifest.write_text(
        '{"project_name":"benchmark-project","task_scope":"freeform-spans"}',
        encoding="utf-8",
    )

    tasks = [{"data": {"chunk_id": "chunk-1"}}]

    class FakeLabelStudioClient:
        imported_batches: list[list[dict[str, object]]] = []

        def __init__(self, _url: str, _key: str) -> None:
            return None

        def list_projects(self):
            return []

        def find_project_by_title(self, _title: str):
            return None

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks_payload):
            payload = [dict(item) for item in tasks_payload]
            self.imported_batches.append(payload)
            return {"task_count": len(payload)}

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    result = run_labelstudio_import(
        path=tmp_path / "book.epub",
        output_dir=output_dir,
        pipeline="auto",
        project_name="benchmark-project",
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=True,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        limit=None,
        sample=None,
        allow_labelstudio_write=True,
    )

    assert result["tasks_uploaded"] == 1
    assert len(FakeLabelStudioClient.imported_batches) == 1


def test_run_labelstudio_import_scope_mismatch_auto_dedupes_project_for_benchmark(
    monkeypatch, tmp_path: Path
) -> None:
    output_dir = tmp_path / "golden"
    stale_manifest = (
        output_dir / "2026-02-10_00.00.00" / "labelstudio" / "benchmark_project" / "manifest.json"
    )
    stale_manifest.parent.mkdir(parents=True, exist_ok=True)
    stale_manifest.write_text(
        '{"project_name":"benchmark_project","task_scope":"freeform-spans"}',
        encoding="utf-8",
    )

    tasks = [{"data": {"chunk_id": "chunk-1"}}]

    class FakeLabelStudioClient:
        imported_batches: list[list[dict[str, object]]] = []
        created_titles: list[str] = []

        def __init__(self, _url: str, _key: str) -> None:
            return None

        def list_projects(self):
            return [{"id": 42, "title": "benchmark_project"}]

        def find_project_by_title(self, title: str):
            if title == "benchmark_project":
                return {"id": 42, "title": title}
            return None

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            self.created_titles.append(title)
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks_payload):
            payload = [dict(item) for item in tasks_payload]
            self.imported_batches.append(payload)
            return {"task_count": len(payload)}

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    result = run_labelstudio_import(
        path=tmp_path / "benchmark_project.epub",
        output_dir=output_dir,
        pipeline="auto",
        project_name=None,
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=True,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        limit=None,
        sample=None,
        auto_project_name_on_scope_mismatch=True,
        allow_labelstudio_write=True,
    )

    assert result["project_name"] == "benchmark_project-1"
    assert FakeLabelStudioClient.created_titles == ["benchmark_project-1"]
    assert result["tasks_uploaded"] == 1
    assert len(FakeLabelStudioClient.imported_batches) == 1
