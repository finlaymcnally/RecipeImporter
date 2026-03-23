from __future__ import annotations

import datetime as dt
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    RecipeCandidate,
    SourceBlock,
    SourceSupport,
)
from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    LabelFirstStageResult,
    RecipeSpan,
    RecipeSpanDecision,
)
from cookimport.staging import import_session


def _recipe(name: str, start_block: int, end_block: int) -> RecipeCandidate:
    return RecipeCandidate(
        name=name,
        identifier=f"urn:test:{name.lower()}",
        recipeIngredient=["1 item"],
        recipeInstructions=["Do the thing."],
        provenance={"location": {"start_block": start_block, "end_block": end_block}},
    )


def _label_block(index: int, label: str) -> AuthoritativeBlockLabel:
    return AuthoritativeBlockLabel(
        source_block_id=f"b{index}",
        source_block_index=index,
        supporting_atomic_indices=[index],
        deterministic_label=label,
        final_label=label,
        decided_by="rule",
        reason_tags=[],
    )


def _no_op_writers(monkeypatch) -> None:
    monkeypatch.setattr(import_session, "write_nonrecipe_stage_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_knowledge_outputs_artifact", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_authoritative_recipe_semantics", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_intermediate_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_draft_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_section_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_chunk_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_table_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_raw_artifacts", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_stage_block_predictions", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "enrich_report_with_stats", lambda *args, **kwargs: None)

    def _write_report(report, run_root, _stem):
        path = Path(run_root) / "report.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(import_session, "write_report", _write_report)


def _boundary_result(
    extracted_bundle,
    label_result: LabelFirstStageResult,
    conversion_result: ConversionResult,
) -> import_session.RecipeBoundaryResult:
    recipe_block_indices = {
        int(block_index)
        for span in label_result.recipe_spans
        for block_index in span.block_indices
    }
    recipe_owned_blocks = [
        dict(block)
        for block in label_result.archive_blocks
        if int(block.get("index", -1)) in recipe_block_indices
    ]
    outside_recipe_blocks = [
        dict(block)
        for block in label_result.archive_blocks
        if int(block.get("index", -1)) not in recipe_block_indices
    ]
    return import_session.RecipeBoundaryResult(
        extracted_bundle=extracted_bundle,
        label_first_result=label_result,
        conversion_result=conversion_result,
        recipe_owned_blocks=recipe_owned_blocks,
        outside_recipe_blocks=outside_recipe_blocks,
    )


def test_execute_stage_import_session_keeps_label_first_zero_recipe_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _no_op_writers(monkeypatch)
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")

    original_result = ConversionResult(
        recipes=[_recipe("Importer Recipe", 0, 0)],
        sourceBlocks=[
            SourceBlock(
                blockId="b0",
                orderIndex=0,
                text="Technique note",
                sourceText="Technique note",
                location={"line_index": 0},
            )
        ],
        nonRecipeBlocks=[],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    authoritative_result = ConversionResult(
        recipes=[],
        sourceBlocks=[
            SourceBlock(
                blockId="b0",
                orderIndex=0,
                text="Technique note",
                sourceText="Technique note",
                location={"line_index": 0},
            )
        ],
        nonRecipeBlocks=[{"index": 99, "text": "stale non-recipe cache"}],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    label_result = LabelFirstStageResult(
        labeled_lines=[],
        block_labels=[_label_block(0, "KNOWLEDGE")],
        recipe_spans=[],
        span_decisions=[
            RecipeSpanDecision(
                span_id="pseudo_recipe_span_0",
                decision="rejected_pseudo_recipe_span",
                rejection_reason="rejected_missing_title_anchor",
                start_block_index=0,
                end_block_index=1,
                block_indices=[0, 1],
                source_block_ids=["b0", "b1"],
                warnings=[
                    "recipe_span_started_without_title",
                    "recipe_span_missing_title_label",
                ],
                escalation_reasons=["missing_required_recipe_fields"],
                decision_notes=[
                    "recipe_span_started_without_title",
                    "span_missing_title_block",
                ],
            )
        ],
        non_recipe_lines=[],
        updated_conversion_result=authoritative_result,
        archive_blocks=[{"index": 0, "block_id": "b0", "text": "Technique note"}],
        source_hash="hash-123",
    )
    monkeypatch.setattr(
        import_session,
        "run_recipe_boundary_stage",
        lambda **_kwargs: _boundary_result(
            _kwargs["extracted_bundle"],
            label_result,
            authoritative_result,
        ),
    )
    monkeypatch.setattr(import_session, "extract_and_annotate_tables", lambda *args, **kwargs: [])
    monkeypatch.setattr(import_session, "chunks_from_non_recipe_blocks", lambda *args, **kwargs: [])

    session = import_session.execute_stage_import_session_from_result(
        result=original_result,
        source_file=source,
        run_root=tmp_path / "out",
        run_dt=dt.datetime(2026, 3, 16, 10, 0, 0),
        importer_name="text",
        run_settings=RunSettings.from_dict({}, warn_context="test"),
        run_config={},
        run_config_hash=None,
        run_config_summary=None,
        write_raw_artifacts_enabled=False,
    )

    assert session.conversion_result.recipes == []
    assert any(
        "Authoritative Stage 2 regrouping found zero recipes" in warning
        for warning in session.conversion_result.report.warnings
    )
    mismatch_path = (
        tmp_path
        / "out"
        / "group_recipe_spans"
        / "book"
        / "authority_mismatch.json"
    )
    assert mismatch_path.is_file()
    assert session.label_artifact_paths["authority_mismatch_path"] == mismatch_path
    assert session.recipe_boundary_result is not None
    assert session.recipe_refine_result is not None
    assert session.nonrecipe_route_result is not None
    assert session.knowledge_final_result is not None
    assert session.label_artifact_paths["span_decisions_path"].is_file()
    span_path = session.label_artifact_paths["recipe_spans_path"]
    span_payload = span_path.read_text(encoding="utf-8")
    assert '"recipe_spans": []' in span_payload
    decision_payload = session.label_artifact_paths["span_decisions_path"].read_text(
        encoding="utf-8"
    )
    assert '"decision": "rejected_pseudo_recipe_span"' in decision_payload
    assert '"rejection_reason": "rejected_missing_title_anchor"' in decision_payload


def test_execute_stage_import_session_uses_stage7_rows_for_tables_and_chunks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _no_op_writers(monkeypatch)
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")

    original_result = ConversionResult(
        recipes=[_recipe("Recipe", 0, 0)],
        sourceBlocks=[
            SourceBlock(
                blockId="b0",
                orderIndex=0,
                text="Recipe",
                sourceText="Recipe",
                location={"line_index": 0},
            ),
            SourceBlock(
                blockId="b1",
                orderIndex=1,
                text="Technique note",
                sourceText="Technique note",
                location={"line_index": 1},
            ),
        ],
        nonRecipeBlocks=[{"index": 77, "text": "stale block"}],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    authoritative_result = ConversionResult(
        recipes=[_recipe("Recipe", 0, 0)],
        sourceBlocks=[
            SourceBlock(
                blockId="b0",
                orderIndex=0,
                text="Recipe",
                sourceText="Recipe",
                location={"line_index": 0},
            ),
            SourceBlock(
                blockId="b1",
                orderIndex=1,
                text="Technique note",
                sourceText="Technique note",
                location={"line_index": 1},
            ),
        ],
        nonRecipeBlocks=[{"index": 88, "text": "old cache"}],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    label_result = LabelFirstStageResult(
        labeled_lines=[],
        block_labels=[_label_block(0, "RECIPE_TITLE"), _label_block(1, "KNOWLEDGE")],
        recipe_spans=[
            RecipeSpan(
                span_id="recipe.0",
                start_block_index=0,
                end_block_index=1,
                block_indices=[0],
                source_block_ids=["b0"],
            )
        ],
        non_recipe_lines=[],
        updated_conversion_result=authoritative_result,
        archive_blocks=[
            {"index": 0, "block_id": "b0", "text": "Recipe"},
            {"index": 1, "block_id": "b1", "text": "Technique note"},
        ],
        source_hash="hash-123",
    )
    monkeypatch.setattr(
        import_session,
        "run_recipe_boundary_stage",
        lambda **_kwargs: _boundary_result(
            _kwargs["extracted_bundle"],
            label_result,
            authoritative_result,
        ),
    )
    seen_table_rows: list[list[dict[str, object]]] = []
    seen_chunk_rows: list[list[dict[str, object]]] = []

    def _capture_tables(rows, **_kwargs):
        seen_table_rows.append(list(rows))
        return []

    def _capture_chunks(rows, **_kwargs):
        seen_chunk_rows.append(list(rows))
        return []

    monkeypatch.setattr(import_session, "extract_and_annotate_tables", _capture_tables)
    monkeypatch.setattr(import_session, "chunks_from_non_recipe_blocks", _capture_chunks)

    session = import_session.execute_stage_import_session_from_result(
        result=original_result,
        source_file=source,
        run_root=tmp_path / "out",
        run_dt=dt.datetime(2026, 3, 16, 10, 0, 0),
        importer_name="text",
        run_settings=RunSettings.from_dict({}, warn_context="test"),
        run_config={},
        run_config_hash=None,
        run_config_summary=None,
        write_raw_artifacts_enabled=False,
    )

    assert [row["index"] for row in seen_table_rows[0]] == [1]
    assert [row["index"] for row in seen_chunk_rows[0]] == [1]
    assert [row["index"] for row in session.conversion_result.non_recipe_blocks] == [1]


def test_execute_stage_import_session_writes_source_model_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _no_op_writers(monkeypatch)
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")

    original_result = ConversionResult(
        sourceBlocks=[
            SourceBlock(
                blockId="b0",
                orderIndex=0,
                text="Technique note",
                sourceText="Technique note",
                location={"line_index": 0},
            )
        ],
        sourceSupport=[
            SourceSupport(
                hintClass="proposal",
                kind="candidate_recipe_region",
                referencedBlockIds=["b0"],
                payload={"reason": "heading"},
            )
        ],
        nonRecipeBlocks=[],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    authoritative_result = ConversionResult(
        sourceBlocks=list(original_result.source_blocks),
        sourceSupport=list(original_result.source_support),
        nonRecipeBlocks=[{"index": 0, "text": "Technique note"}],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    label_result = LabelFirstStageResult(
        labeled_lines=[],
        block_labels=[_label_block(0, "KNOWLEDGE")],
        recipe_spans=[],
        span_decisions=[],
        non_recipe_lines=[],
        updated_conversion_result=authoritative_result,
        archive_blocks=[{"index": 0, "block_id": "b0", "text": "Technique note"}],
        source_hash="hash-123",
    )
    monkeypatch.setattr(
        import_session,
        "run_recipe_boundary_stage",
        lambda **_kwargs: _boundary_result(
            _kwargs["extracted_bundle"],
            label_result,
            authoritative_result,
        ),
    )
    monkeypatch.setattr(import_session, "extract_and_annotate_tables", lambda *args, **kwargs: [])
    monkeypatch.setattr(import_session, "chunks_from_non_recipe_blocks", lambda *args, **kwargs: [])

    session = import_session.execute_stage_import_session_from_result(
        result=original_result,
        source_file=source,
        run_root=tmp_path / "out",
        run_dt=dt.datetime(2026, 3, 23, 12, 0, 0),
        importer_name="text",
        run_settings=RunSettings.from_dict({}, warn_context="test"),
        run_config={},
        run_config_hash=None,
        run_config_summary=None,
        write_raw_artifacts_enabled=False,
    )

    source_blocks_path = session.source_artifact_paths["source_blocks_path"]
    source_support_path = session.source_artifact_paths["source_support_path"]
    assert source_blocks_path.is_file()
    assert source_support_path.is_file()
    assert '"blockId": "b0"' in source_blocks_path.read_text(encoding="utf-8")
    assert '"authoritative": false' in source_support_path.read_text(encoding="utf-8")
