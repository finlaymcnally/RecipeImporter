from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    RecipeCandidate,
    SourceBlock,
    SourceSupport,
)
from cookimport.parsing.canonical_line_roles import CanonicalLineRolePrediction
from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    LabelFirstStageResult,
    RecipeSpan,
    RecipeSpanDecision,
)
from cookimport.staging import import_session
from cookimport.staging.import_session_flows import (
    authority as authority_flow,
    output_stage as output_stage_flow,
)
from tests.nonrecipe_stage_helpers import make_recipe_ownership_result


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
    monkeypatch.setattr(import_session, "write_recipe_row_ownership", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_authoritative_recipe_semantics", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_recipe_authority_decisions", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_intermediate_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_draft_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_section_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_chunk_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_table_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_raw_artifacts", lambda *args, **kwargs: None)
    monkeypatch.setattr(import_session, "write_semantic_row_predictions", lambda *args, **kwargs: None)
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
    recipe_ownership_result = make_recipe_ownership_result(
        owned_by_recipe_id={
            str(recipe.identifier): list(span.block_indices)
            for recipe, span in zip(
                conversion_result.recipes,
                label_result.recipe_spans,
                strict=False,
            )
        },
        all_block_indices=[
            int(block.get("index", 0))
            for block in label_result.archive_blocks
        ],
    )
    return import_session.RecipeBoundaryResult(
        extracted_bundle=extracted_bundle,
        label_first_result=label_result,
        conversion_result=conversion_result,
        recipe_ownership_result=recipe_ownership_result,
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
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    label_result = LabelFirstStageResult(
        labeled_lines=[],
        block_labels=[_label_block(0, "NONRECIPE_CANDIDATE")],
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
        outside_recipe_blocks=[{"index": 0, "text": "Technique note"}],
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
    monkeypatch.setattr(
        output_stage_flow,
        "chunks_from_non_recipe_blocks",
        lambda *args, **kwargs: [],
    )

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
    mismatch_path = (
        tmp_path
        / "out"
        / "recipe_boundary"
        / "book"
        / "authority_mismatch.json"
    )
    assert not mismatch_path.exists()
    assert "authority_mismatch_path" not in (session.label_artifact_paths or {})
    assert not any(
        "Authoritative Stage 2 regrouping found zero recipes" in warning
        for warning in session.conversion_result.report.warnings
    )
    assert session.recipe_boundary_result is not None
    assert session.recipe_refine_result is not None
    assert session.nonrecipe_route_result is not None
    assert session.nonrecipe_finalize_result is not None
    assert session.label_artifact_paths["span_decisions_path"].is_file()
    span_path = session.label_artifact_paths["recipe_spans_path"]
    span_payload = span_path.read_text(encoding="utf-8")
    assert '"recipe_spans": []' in span_payload
    decision_payload = session.label_artifact_paths["span_decisions_path"].read_text(
        encoding="utf-8"
    )
    assert '"decision": "rejected_pseudo_recipe_span"' in decision_payload
    assert '"rejection_reason": "rejected_missing_title_anchor"' in decision_payload


def test_execute_stage_import_session_writes_line_role_authority_artifacts_for_codex_runs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _no_op_writers(monkeypatch)
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")

    authoritative_result = ConversionResult(
        recipes=[_recipe("Toast", 0, 1)],
        sourceBlocks=[
            SourceBlock(
                blockId="b0",
                orderIndex=0,
                text="Toast",
                sourceText="Toast",
                location={"line_index": 0},
            ),
            SourceBlock(
                blockId="b1",
                orderIndex=1,
                text="1 slice bread",
                sourceText="1 slice bread",
                location={"line_index": 1},
            ),
        ],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    label_result = LabelFirstStageResult(
        authoritative_label_stage_key="line_role",
        labeled_lines=[],
        block_labels=[_label_block(0, "RECIPE_TITLE"), _label_block(1, "INGREDIENT_LINE")],
        recipe_spans=[
            RecipeSpan(
                span_id="span-1",
                start_block_index=0,
                end_block_index=1,
                block_indices=[0, 1],
                source_block_ids=["b0", "b1"],
                atomic_indices=[0, 1],
                title_block_index=0,
                title_atomic_index=0,
            )
        ],
        updated_conversion_result=authoritative_result,
        archive_blocks=[
            {"index": 0, "block_id": "b0", "text": "Toast"},
            {"index": 1, "block_id": "b1", "text": "1 slice bread"},
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
    monkeypatch.setattr(import_session, "extract_and_annotate_tables", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        output_stage_flow,
        "chunks_from_non_recipe_blocks",
        lambda *args, **kwargs: [],
    )

    session = import_session.execute_stage_import_session_from_result(
        result=authoritative_result,
        source_file=source,
        run_root=tmp_path / "out",
        run_dt=dt.datetime(2026, 4, 9, 16, 0, 0),
        importer_name="text",
        run_settings=RunSettings.from_dict(
            {"line_role_pipeline": "codex-line-role-route-v2"},
            warn_context="test",
        ),
        run_config={},
        run_config_hash=None,
        run_config_summary=None,
        write_raw_artifacts_enabled=False,
    )

    assert "label_deterministic_lines_path" not in (session.label_artifact_paths or {})
    assert "label_llm_lines_path" not in (session.label_artifact_paths or {})
    assert session.label_artifact_paths["line_role_authoritative_lines_path"].is_file()
    assert session.label_artifact_paths["line_role_authoritative_blocks_path"].is_file()
    assert not (tmp_path / "out" / "label_deterministic").exists()
    assert not (tmp_path / "out" / "label_refine").exists()
    assert (tmp_path / "out" / "line-role-pipeline" / "authoritative_labeled_lines.jsonl").exists()


def test_serialize_span_decision_emits_row_native_keys_for_row_native_models() -> None:
    payload = authority_flow._serialize_span_decision(
        RecipeSpanDecision(
            span_id="span-1",
            decision="accepted_recipe_span",
            rejection_reason=None,
            start_row_index=3,
            end_row_index=5,
            row_indices=[3, 4, 5],
            source_block_ids=["b3", "b4", "b5"],
            start_atomic_index=30,
            end_atomic_index=50,
            atomic_indices=[30, 40, 50],
            title_row_index=3,
            title_atomic_index=30,
            warnings=["warn"],
            escalation_reasons=["reason"],
            decision_notes=["note"],
        )
    )

    assert payload["start_row_index"] == 3
    assert payload["end_row_index"] == 5
    assert payload["row_indices"] == [3, 4, 5]
    assert payload["title_row_index"] == 3
    assert "start_block_index" not in payload
    assert "end_block_index" not in payload
    assert "block_indices" not in payload
    assert "title_block_index" not in payload


def test_execute_stage_import_session_uses_candidate_nonrecipe_rows_for_late_outputs_when_nonrecipe_finalize_is_off(
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
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    label_result = LabelFirstStageResult(
        labeled_lines=[],
        block_labels=[_label_block(0, "RECIPE_TITLE"), _label_block(1, "NONRECIPE_CANDIDATE")],
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
        outside_recipe_blocks=[{"index": 1, "text": "Technique note"}],
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
    monkeypatch.setattr(output_stage_flow, "chunks_from_non_recipe_blocks", _capture_chunks)

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

    assert len(seen_table_rows) == 1
    assert [row["index"] for row in seen_table_rows[0]] == [1]
    assert [row["text"] for row in seen_table_rows[0]] == ["Technique note"]
    assert len(seen_chunk_rows) == 1
    assert [row["index"] for row in seen_chunk_rows[0]] == [1]
    assert [row["text"] for row in seen_chunk_rows[0]] == ["Technique note"]
    assert session.nonrecipe_finalize_result is not None
    assert session.nonrecipe_finalize_result.authoritative_nonrecipe_blocks == []
    assert [row["index"] for row in session.nonrecipe_finalize_result.late_output_nonrecipe_blocks] == [
        1
    ]


def test_execute_stage_import_session_demotes_rejected_pseudo_recipe_title_before_nonrecipe_stage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _no_op_writers(monkeypatch)
    source = tmp_path / "book.txt"
    source.write_text("book", encoding="utf-8")

    result = ConversionResult(
        sourceBlocks=[
            SourceBlock(
                blockId="b0",
                orderIndex=0,
                text="Acid and Flavor",
                sourceText="Acid and Flavor",
                location={"line_index": 0},
            ),
            SourceBlock(
                blockId="b1",
                orderIndex=1,
                text="How Acid Works",
                sourceText="How Acid Works",
                location={"line_index": 1},
            ),
            SourceBlock(
                blockId="b2",
                orderIndex=2,
                text="Using Acid",
                sourceText="Using Acid",
                location={"line_index": 2},
            ),
            SourceBlock(
                blockId="b3",
                orderIndex=3,
                text="HEAT",
                sourceText="HEAT",
                location={"line_index": 3},
            ),
            SourceBlock(
                blockId="b4",
                orderIndex=4,
                text="What is Heat?",
                sourceText="What is Heat?",
                location={"line_index": 4},
            ),
        ],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )

    predicted_labels = {
        "Acid and Flavor": "NONRECIPE_CANDIDATE",
        "How Acid Works": "NONRECIPE_CANDIDATE",
        "Using Acid": "RECIPE_TITLE",
        "HEAT": "NONRECIPE_CANDIDATE",
        "What is Heat?": "NONRECIPE_CANDIDATE",
    }

    def _fake_label_atomic_lines_with_baseline(candidates, _settings, **_kwargs):
        predictions = []
        for candidate in candidates:
            label = predicted_labels[str(candidate.text)]
            reason_tags = ["title_like"] if label == "RECIPE_TITLE" else ["outside_recipe_span"]
            predictions.append(
                CanonicalLineRolePrediction(
                    recipe_id=candidate.recipe_id,
                    block_id=candidate.block_id,
                    block_index=candidate.block_index,
                    atomic_index=candidate.atomic_index,
                    text=str(candidate.text),
                    label=label,
                    decided_by="rule",
                    reason_tags=reason_tags,
                )
            )
        return predictions, predictions

    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.label_atomic_lines_with_baseline",
        _fake_label_atomic_lines_with_baseline,
    )
    monkeypatch.setattr(import_session, "extract_and_annotate_tables", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        output_stage_flow,
        "chunks_from_non_recipe_blocks",
        lambda *args, **kwargs: [],
    )

    session = import_session.execute_stage_import_session_from_result(
        result=result,
        source_file=source,
        run_root=tmp_path / "out",
        run_dt=dt.datetime(2026, 3, 26, 8, 25, 0),
        importer_name="text",
        run_settings=RunSettings.from_dict({}, warn_context="test"),
        run_config={},
        run_config_hash=None,
        run_config_summary=None,
        write_raw_artifacts_enabled=False,
    )

    assert session.recipe_boundary_result is not None
    assert session.nonrecipe_route_result is not None
    assert session.recipe_boundary_result.label_first_result.recipe_spans == []
    block_labels_by_index = {
        row.source_block_index: row.final_label
        for row in session.recipe_boundary_result.label_first_result.block_labels
    }
    assert block_labels_by_index[2] == "NONRECIPE_CANDIDATE"
    assert session.nonrecipe_route_result.stage_result.seed.seed_route_by_index[2] == "candidate"

    payload = json.loads(
        session.label_artifact_paths["authoritative_block_labels_path"].read_text(
            encoding="utf-8"
        )
    )
    authoritative_by_index = {
        row["source_block_index"]: row["final_label"] for row in payload["block_labels"]
    }
    assert authoritative_by_index[2] == "NONRECIPE_CANDIDATE"


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
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    authoritative_result = ConversionResult(
        sourceBlocks=list(original_result.source_blocks),
        sourceSupport=list(original_result.source_support),
        rawArtifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )
    label_result = LabelFirstStageResult(
        labeled_lines=[],
        block_labels=[_label_block(0, "NONRECIPE_CANDIDATE")],
        recipe_spans=[],
        span_decisions=[],
        non_recipe_lines=[],
        outside_recipe_blocks=[{"index": 0, "text": "Technique note"}],
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
    monkeypatch.setattr(
        output_stage_flow,
        "chunks_from_non_recipe_blocks",
        lambda *args, **kwargs: [],
    )

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
