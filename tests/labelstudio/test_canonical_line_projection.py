from __future__ import annotations

import json

from cookimport.labelstudio.canonical_line_projection import (
    project_line_roles_to_freeform_spans,
    write_line_role_projection_artifacts,
)
from cookimport.parsing.canonical_line_roles import CanonicalLineRolePrediction


def test_projection_preserves_within_recipe_span_for_urn_ids() -> None:
    spans = project_line_roles_to_freeform_spans(
        [
            CanonicalLineRolePrediction(
                recipe_id="urn:recipe:seaandsmoke:c0",
                block_id="b10",
                block_index=10,
                atomic_index=0,
                text="1 cup sugar",
                within_recipe_span=True,
                label="INGREDIENT_LINE",
                confidence=0.99,
                decided_by="rule",
                reason_tags=["test"],
            )
        ]
    )

    assert spans[0].recipe_index is None
    assert spans[0].within_recipe_span is True


def test_projection_keeps_explicit_span_flag_even_for_recipe_index_ids() -> None:
    spans = project_line_roles_to_freeform_spans(
        [
            CanonicalLineRolePrediction(
                recipe_id="recipe:2",
                block_id="b11",
                block_index=11,
                atomic_index=1,
                text="Preface",
                within_recipe_span=False,
                label="OTHER",
                confidence=0.99,
                decided_by="rule",
                reason_tags=["test"],
            )
        ]
    )

    assert spans[0].recipe_index == 2
    assert spans[0].within_recipe_span is False


def test_projection_artifacts_include_do_no_harm_paths_when_present(tmp_path) -> None:
    pipeline_dir = tmp_path / "line-role-pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "guardrail_report.json").write_text("{}", encoding="utf-8")
    (pipeline_dir / "guardrail_changed_rows.jsonl").write_text("", encoding="utf-8")
    (pipeline_dir / "do_no_harm_diagnostics.json").write_text("{}", encoding="utf-8")
    (pipeline_dir / "do_no_harm_changed_rows.jsonl").write_text("", encoding="utf-8")

    artifacts = write_line_role_projection_artifacts(
        run_root=tmp_path,
        source_file="book.epub",
        source_hash="hash",
        workbook_slug="book",
        predictions=[
            CanonicalLineRolePrediction(
                recipe_id="recipe:0",
                block_id="b0",
                block_index=0,
                atomic_index=0,
                text="1 cup sugar",
                within_recipe_span=True,
                label="INGREDIENT_LINE",
                confidence=0.99,
                decided_by="rule",
                reason_tags=["test"],
            )
        ],
    )

    assert artifacts["guardrail_report_path"].name == "guardrail_report.json"
    assert artifacts["guardrail_changed_rows_path"].name == "guardrail_changed_rows.jsonl"
    assert artifacts["do_no_harm_diagnostics_path"].name == "do_no_harm_diagnostics.json"
    assert artifacts["do_no_harm_changed_rows_path"].name == "do_no_harm_changed_rows.jsonl"


def test_projection_artifacts_merge_pass4_knowledge_into_other_spans(tmp_path) -> None:
    block_classifications_path = tmp_path / "block_classifications.jsonl"
    block_classifications_path.write_text(
        json.dumps(
            {
                "block_index": 1,
                "category": "knowledge",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = write_line_role_projection_artifacts(
        run_root=tmp_path,
        source_file="book.epub",
        source_hash="hash",
        workbook_slug="book",
        predictions=[
            CanonicalLineRolePrediction(
                recipe_id=None,
                block_id="b0",
                block_index=0,
                atomic_index=0,
                text="Recipe title",
                within_recipe_span=False,
                label="RECIPE_TITLE",
                confidence=0.99,
                decided_by="rule",
                reason_tags=["test"],
            ),
            CanonicalLineRolePrediction(
                recipe_id=None,
                block_id="b1",
                block_index=1,
                atomic_index=1,
                text="Useful kitchen note",
                within_recipe_span=False,
                label="OTHER",
                confidence=0.99,
                decided_by="rule",
                reason_tags=["test"],
            ),
        ],
        knowledge_block_classifications_path=block_classifications_path,
    )

    stage_payload = json.loads(
        artifacts["stage_block_predictions_path"].read_text(encoding="utf-8")
    )
    assert stage_payload["block_labels"]["1"] == "KNOWLEDGE"
    assert any("Pass4 block classifications merged" in note for note in stage_payload["notes"])

    merge_report = json.loads(
        artifacts["pass4_merge_report_path"].read_text(encoding="utf-8")
    )
    assert merge_report["merge_mode"] == "block_classifications"
    assert merge_report["selected_line_count"] == 1
    assert merge_report["upgraded_other_to_knowledge_count"] == 1

    changed_rows = [
        json.loads(line)
        for line in artifacts["pass4_merge_changed_rows_path"].read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert len(changed_rows) == 1
    assert changed_rows[0]["line_index"] == 1
    assert changed_rows[0]["old_label"] == "OTHER"
    assert changed_rows[0]["new_label"] == "KNOWLEDGE"
    assert changed_rows[0]["selection_reason"] == "block_classification_knowledge"

    projected_rows = [
        json.loads(line)
        for line in artifacts["projected_spans_path"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert projected_rows[1]["label"] == "KNOWLEDGE"


def test_projection_artifacts_downgrade_pass4_other_classifications(tmp_path) -> None:
    block_classifications_path = tmp_path / "block_classifications.jsonl"
    block_classifications_path.write_text(
        json.dumps(
            {
                "block_index": 1,
                "category": "other",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = write_line_role_projection_artifacts(
        run_root=tmp_path,
        source_file="book.epub",
        source_hash="hash",
        workbook_slug="book",
        predictions=[
            CanonicalLineRolePrediction(
                recipe_id=None,
                block_id="b1",
                block_index=1,
                atomic_index=1,
                text="Kitchen memoir prose",
                within_recipe_span=False,
                label="KNOWLEDGE",
                confidence=0.99,
                decided_by="rule",
                reason_tags=["test"],
            ),
            CanonicalLineRolePrediction(
                recipe_id="recipe:0",
                block_id="b2",
                block_index=2,
                atomic_index=2,
                text="1 cup stock",
                within_recipe_span=True,
                label="INGREDIENT_LINE",
                confidence=0.99,
                decided_by="rule",
                reason_tags=["test"],
            ),
        ],
        knowledge_block_classifications_path=block_classifications_path,
    )

    projected_rows = [
        json.loads(line)
        for line in artifacts["projected_spans_path"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert projected_rows[0]["label"] == "OTHER"
    assert projected_rows[1]["label"] == "INGREDIENT_LINE"
