from __future__ import annotations

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

    assert artifacts["do_no_harm_diagnostics_path"].name == "do_no_harm_diagnostics.json"
    assert artifacts["do_no_harm_changed_rows_path"].name == "do_no_harm_changed_rows.jsonl"
