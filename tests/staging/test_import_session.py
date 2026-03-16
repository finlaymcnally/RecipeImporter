from __future__ import annotations

import datetime as dt
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate
from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    LabelFirstStageResult,
    RecipeSpan,
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
    monkeypatch.setattr(import_session, "write_intermediate_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_draft_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_section_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_tip_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_topic_candidate_outputs", lambda *args, **kwargs: None)
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


def test_execute_stage_import_session_keeps_label_first_zero_recipe_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _no_op_writers(monkeypatch)
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")

    original_result = ConversionResult(
        recipes=[_recipe("Importer Recipe", 0, 0)],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    authoritative_result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
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
        non_recipe_lines=[],
        updated_conversion_result=authoritative_result,
        archive_blocks=[{"index": 0, "block_id": "b0", "text": "Technique note"}],
        source_hash="hash-123",
    )
    monkeypatch.setattr(
        import_session,
        "build_label_first_stage_result",
        lambda **_kwargs: label_result,
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
    assert session.label_artifact_paths["span_decisions_path"].is_file()


def test_execute_stage_import_session_uses_stage7_rows_for_tables_and_chunks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _no_op_writers(monkeypatch)
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")

    original_result = ConversionResult(
        recipes=[_recipe("Recipe", 0, 0)],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[{"index": 77, "text": "stale block"}],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    authoritative_result = ConversionResult(
        recipes=[_recipe("Recipe", 0, 0)],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
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
        "build_label_first_stage_result",
        lambda **_kwargs: label_result,
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
