from __future__ import annotations

from cookimport.labelstudio.canonical_line_projection import (
    build_line_role_stage_prediction_payload,
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
                decided_by="rule",
                reason_tags=["test"],
            )
        ]
    )

    assert spans[0].recipe_index == 2
    assert spans[0].within_recipe_span is False


def test_projection_artifacts_ignore_removed_guardrail_sidecars(tmp_path) -> None:
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
                decided_by="rule",
                reason_tags=["test"],
            )
        ],
    )

    assert "guardrail_report_path" not in artifacts
    assert "guardrail_changed_rows_path" not in artifacts
    assert "do_no_harm_diagnostics_path" not in artifacts
    assert "do_no_harm_changed_rows_path" not in artifacts


def test_projection_artifacts_preserve_projected_labels(tmp_path) -> None:
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
                decided_by="rule",
                reason_tags=["test"],
            ),
        ],
    )

    projected_rows = artifacts["projected_spans_path"].read_text(encoding="utf-8").splitlines()
    assert '"label": "OTHER"' in projected_rows[1]


def test_stage_projection_payload_aggregates_atomic_rows_by_source_block() -> None:
    projected_spans = project_line_roles_to_freeform_spans(
        [
            CanonicalLineRolePrediction(
                recipe_id="recipe:0",
                block_id="b7",
                block_index=7,
                atomic_index=0,
                text="Pancakes",
                within_recipe_span=True,
                label="RECIPE_TITLE",
                decided_by="rule",
                reason_tags=["test"],
            ),
            CanonicalLineRolePrediction(
                recipe_id="recipe:0",
                block_id="b7",
                block_index=7,
                atomic_index=1,
                text="SERVES 2",
                within_recipe_span=True,
                label="YIELD_LINE",
                decided_by="rule",
                reason_tags=["test"],
            ),
        ]
    )
    stage_payload = build_line_role_stage_prediction_payload(
        projected_spans,
        source_file="book.epub",
        source_hash="hash",
        workbook_slug="book",
    )

    assert stage_payload["block_count"] == 8
    assert stage_payload["block_labels"]["7"] == "RECIPE_TITLE"
    assert stage_payload["label_blocks"]["RECIPE_TITLE"] == [7]
    assert stage_payload["conflicts"] == [
        {"block_index": 7, "labels": ["RECIPE_TITLE", "YIELD_LINE"]}
    ]
