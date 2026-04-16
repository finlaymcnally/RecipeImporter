from __future__ import annotations

import json
from pathlib import Path

from cookimport.core.models import (
    ChunkLane,
    ConversionReport,
    ConversionResult,
    KnowledgeChunk,
    RawArtifact,
    RecipeCandidate,
    SourceBlock,
)
from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    LabelFirstStageResult,
)
from cookimport.staging.semantic_row_predictions import (
    UNRESOLVED_CANDIDATE_ROW_CATEGORY_KEY,
    UNRESOLVED_CANDIDATE_ROW_INDICES_KEY,
    UNRESOLVED_RECIPE_OWNED_RECIPE_ID_BY_ROW_INDEX_KEY,
    UNRESOLVED_RECIPE_OWNED_ROW_INDICES_KEY,
    _is_howto_section_text,
    build_semantic_row_predictions,
)
from cookimport.staging.writer import write_semantic_row_predictions
from tests.nonrecipe_stage_helpers import (
    make_authority_result,
    make_candidate_status_result,
    make_recipe_ownership_result,
    make_routing_result,
    make_seed_result,
    make_stage_result,
)


def _build_result(
    *,
    comment_text: str | None = "Chef's note: taste first.",
    description: str | None = None,
    note_block_text: str = "Chef's note: taste first.",
) -> ConversionResult:
    recipe_payload: dict[str, object] = {
        "identifier": "urn:recipe:test:simple",
        "name": "Simple Soup",
        "recipeIngredient": ["1 cup stock", "Salt"],
        "recipeInstructions": ["Heat stock.", "Variations: add herbs.", "Serve."],
        "recipeYield": "Serves 2",
        "prepTime": "PT10M",
        "provenance": {"location": {"start_block": 0, "end_block": 7}},
    }
    if comment_text is not None:
        recipe_payload["comment"] = [{"text": comment_text}]
    if description is not None:
        recipe_payload["description"] = description

    recipe = RecipeCandidate(**recipe_payload)

    raw = RawArtifact(
        importer="text",
        sourceHash="abc123",
        locationId="full_text",
        extension="json",
        content={
            "blocks": [
                {"index": 0, "text": "Simple Soup", "features": {"is_heading": True}},
                {"index": 1, "text": "Serves 2"},
                {"index": 2, "text": "Prep time: 10 minutes"},
                {"index": 3, "text": "1 cup stock", "features": {"block_role": "ingredient_line"}},
                {"index": 4, "text": "Salt", "features": {"block_role": "ingredient_line"}},
                {"index": 5, "text": "Heat stock.", "features": {"block_role": "instruction_line"}},
                {"index": 6, "text": "Variations: add herbs.", "features": {"block_role": "instruction_line"}},
                {"index": 7, "text": note_block_text},
                {"index": 8, "text": "Use clean tools for food safety."},
            ],
            "block_count": 9,
        },
        metadata={"artifact_type": "extracted_blocks"},
    )

    return ConversionResult(
        recipes=[recipe],
        sourceBlocks=[
            SourceBlock(blockId="b0", orderIndex=0, text="Simple Soup"),
            SourceBlock(blockId="b1", orderIndex=1, text="Serves 2"),
            SourceBlock(blockId="b2", orderIndex=2, text="Prep time: 10 minutes"),
            SourceBlock(blockId="b3", orderIndex=3, text="1 cup stock"),
            SourceBlock(blockId="b4", orderIndex=4, text="Salt"),
            SourceBlock(blockId="b5", orderIndex=5, text="Heat stock."),
            SourceBlock(blockId="b6", orderIndex=6, text="Variations: add herbs."),
            SourceBlock(blockId="b7", orderIndex=7, text=note_block_text),
            SourceBlock(blockId="b8", orderIndex=8, text="Use clean tools for food safety."),
        ],
        report=ConversionReport(),
        rawArtifacts=[raw],
        workbook="simple",
        workbookPath="/tmp/simple.txt",
    )


def _single_recipe_ownership(
    result: ConversionResult,
    owned_row_indices: range | list[int],
) -> object:
    recipe_id = str(result.recipes[0].identifier)
    return make_recipe_ownership_result(
        owned_by_recipe_id={recipe_id: list(owned_row_indices)},
        all_block_indices=list(range(len(result.source_blocks))),
    )


def test_build_semantic_row_predictions_assigns_one_label_per_row(tmp_path: Path) -> None:
    result = _build_result()

    payload = build_semantic_row_predictions(
        result,
        "simple",
        recipe_ownership_result=_single_recipe_ownership(result, range(8)),
        nonrecipe_stage_result=make_stage_result(
            seed=make_seed_result({8: "candidate"}),
            routing=make_routing_result(candidate_row_indices=[8]),
            authority=make_authority_result({8: "knowledge"}),
            candidate_status=make_candidate_status_result(
                finalized_candidate_row_indices=[8],
                unresolved_candidate_route_by_index={},
            ),
        ),
    )

    assert payload["schema_version"] == "semantic_row_predictions.v1"
    assert payload["row_count"] == 9

    row_labels = payload["row_labels"]
    assert set(row_labels.keys()) == {str(index) for index in range(9)}

    assert row_labels["0"] == "RECIPE_TITLE"
    assert row_labels["1"] == "YIELD_LINE"
    assert row_labels["2"] == "TIME_LINE"
    assert row_labels["3"] == "INGREDIENT_LINE"
    assert row_labels["4"] == "INGREDIENT_LINE"
    assert row_labels["5"] == "INSTRUCTION_LINE"
    assert row_labels["6"] == "INSTRUCTION_LINE"
    assert row_labels["7"] == "RECIPE_NOTES"
    assert row_labels["8"] == "KNOWLEDGE"

    label_rows = payload["label_rows"]
    for index in range(9):
        label = row_labels[str(index)]
        assert index in label_rows[label]

    conflicts = payload["conflicts"]
    assert conflicts == []
    assert "KNOWLEDGE labels were derived from final non-recipe authority." in payload["notes"]
    assert "All candidate non-recipe rows had final authority before scoring." in payload["notes"]


def test_build_semantic_row_predictions_without_nonrecipe_authority_do_not_project_chunk_lanes() -> None:
    result = _build_result()
    result.chunks = [
        KnowledgeChunk(
            id="c0",
            lane=ChunkLane.KNOWLEDGE,
            text="Use clean tools for food safety.",
            blockIds=[0],
        )
    ]

    payload = build_semantic_row_predictions(
        result,
        "simple",
        recipe_ownership_result=_single_recipe_ownership(result, range(8)),
    )

    assert payload["row_labels"]["8"] == "OTHER"
    assert 8 not in payload["label_rows"]["KNOWLEDGE"]
    assert (
        "KNOWLEDGE labels require final non-recipe authority; no fallback chunk-lane projection ran."
        in payload["notes"]
    )


def test_build_semantic_row_predictions_ignores_nonrecipe_finalize_other_rows() -> None:
    result = _build_result()

    payload = build_semantic_row_predictions(
        result,
        "simple",
        recipe_ownership_result=_single_recipe_ownership(result, range(8)),
        nonrecipe_stage_result=make_stage_result(
            seed=make_seed_result({8: "candidate"}),
            routing=make_routing_result(candidate_row_indices=[8]),
            authority=make_authority_result({8: "other"}),
            candidate_status=make_candidate_status_result(
                finalized_candidate_row_indices=[8],
                unresolved_candidate_route_by_index={},
            ),
        ),
    )

    assert payload["row_labels"]["8"] == "OTHER"


def test_build_semantic_row_predictions_ignores_divested_non_promoted_recipe_entries() -> None:
    result = _build_result()
    recipe_id = str(result.recipes[0].identifier)

    payload = build_semantic_row_predictions(
        result,
        "simple",
        recipe_ownership_result=make_recipe_ownership_result(
            owned_by_recipe_id={
                recipe_id: list(range(8)),
                "urn:recipe:test:divested": [],
            },
            divested_by_recipe_id={"urn:recipe:test:divested": [8]},
            all_block_indices=list(range(9)),
        ),
        nonrecipe_stage_result=make_stage_result(
            seed=make_seed_result({8: "candidate"}),
            routing=make_routing_result(candidate_row_indices=[8]),
            authority=make_authority_result({8: "knowledge"}),
            candidate_status=make_candidate_status_result(
                finalized_candidate_row_indices=[8],
                unresolved_candidate_route_by_index={},
            ),
        ),
    )

    assert payload["row_labels"]["8"] == "KNOWLEDGE"


def test_build_semantic_row_predictions_ignores_unresolved_candidate_knowledge() -> None:
    result = _build_result()

    payload = build_semantic_row_predictions(
        result,
        "simple",
        recipe_ownership_result=_single_recipe_ownership(result, range(8)),
        nonrecipe_stage_result=make_stage_result(
            seed=make_seed_result({8: "candidate"}),
            routing=make_routing_result(candidate_row_indices=[8]),
            authority=make_authority_result({}),
            candidate_status=make_candidate_status_result(
                finalized_candidate_row_indices=[],
                unresolved_candidate_route_by_index={8: "candidate"},
            ),
        ),
    )

    assert payload["row_labels"]["8"] == "OTHER"
    assert payload[UNRESOLVED_CANDIDATE_ROW_INDICES_KEY] == [8]
    assert payload[UNRESOLVED_CANDIDATE_ROW_CATEGORY_KEY] == {"8": "candidate"}
    assert payload["counts"]["unresolved_candidate_rows"] == 1
    assert (
        "Candidate non-recipe rows without final authority were marked unresolved and excluded from semantic scoring."
        in payload["notes"]
    )


def test_build_semantic_row_predictions_uses_boundary_labels_for_withheld_fragmentary_recipe() -> None:
    result = _build_result()
    recipe_id = str(result.recipes[0].identifier)
    result.recipes = []

    payload = build_semantic_row_predictions(
        result,
        "simple",
        recipe_ownership_result=make_recipe_ownership_result(
            owned_by_recipe_id={recipe_id: list(range(8))},
            all_block_indices=list(range(9)),
        ),
        recipe_authority_decisions_by_recipe_id={
            recipe_id: {
                "recipe_id": recipe_id,
                "semantic_outcome": "partial_recipe",
                "publish_status": "withheld_partial",
                "ownership_action": "retain",
                "owned_row_indices": list(range(8)),
                "divested_row_indices": [],
                "retained_row_indices": list(range(8)),
                "worker_repair_status": "fragmentary",
            }
        },
        boundary_labels=[
            AuthoritativeBlockLabel(
                source_block_id=f"b{index}",
                source_block_index=index,
                supporting_atomic_indices=[],
                deterministic_label=label,
                final_label=label,
                decided_by="rule",
                reason_tags=[],
                escalation_reasons=[],
            )
            for index, label in [
                (0, "RECIPE_TITLE"),
                (1, "YIELD_LINE"),
                (2, "TIME_LINE"),
                (3, "INGREDIENT_LINE"),
                (4, "INGREDIENT_LINE"),
                (5, "INSTRUCTION_LINE"),
                (6, "INSTRUCTION_LINE"),
                (7, "RECIPE_NOTES"),
                (8, "NONRECIPE_CANDIDATE"),
            ]
        ],
    )

    assert payload["row_labels"]["0"] == "RECIPE_TITLE"
    assert payload["row_labels"]["7"] == "RECIPE_NOTES"
    assert payload[UNRESOLVED_RECIPE_OWNED_ROW_INDICES_KEY] == []
    assert payload[UNRESOLVED_RECIPE_OWNED_RECIPE_ID_BY_ROW_INDEX_KEY] == {}
    assert payload["unresolved_recipe_exact_evidence"] == []


def test_build_semantic_row_predictions_marks_recipe_owned_rows_unresolved_when_withheld_recipe_has_no_evidence() -> None:
    result = _build_result()
    recipe_id = str(result.recipes[0].identifier)
    result.recipes = []

    payload = build_semantic_row_predictions(
        result,
        "simple",
        recipe_ownership_result=make_recipe_ownership_result(
            owned_by_recipe_id={recipe_id: [0, 1, 2]},
            all_block_indices=list(range(9)),
        ),
        recipe_authority_decisions_by_recipe_id={
            recipe_id: {
                "recipe_id": recipe_id,
                "semantic_outcome": "partial_recipe",
                "publish_status": "withheld_partial",
                "ownership_action": "retain",
                "owned_row_indices": [0, 1, 2],
                "divested_row_indices": [],
                "retained_row_indices": [0, 1, 2],
                "worker_repair_status": "fragmentary",
            }
        },
        boundary_labels=[
            AuthoritativeBlockLabel(
                source_block_id=f"b{index}",
                source_block_index=index,
                supporting_atomic_indices=[],
                deterministic_label="OTHER",
                final_label="OTHER",
                decided_by="rule",
                reason_tags=[],
                escalation_reasons=[],
            )
            for index in range(9)
        ],
    )

    assert payload[UNRESOLVED_RECIPE_OWNED_ROW_INDICES_KEY] == [0, 1, 2]
    assert payload[UNRESOLVED_RECIPE_OWNED_RECIPE_ID_BY_ROW_INDEX_KEY] == {
        "0": recipe_id,
        "1": recipe_id,
        "2": recipe_id,
    }
    assert payload["counts"]["unresolved_recipe_owned_rows"] == 3


def test_build_semantic_row_predictions_records_unresolved_exact_title_evidence_instead_of_guessing() -> None:
    recipe = RecipeCandidate(
        identifier="urn:recipe:test:narrative-title",
        name="PAN-SEARED SALMON",
        recipeIngredient=["2 salmon fillets"],
        recipeInstructions=["Sear the salmon."],
        provenance={"location": {"start_block": 0, "end_block": 1}},
    )
    raw = RawArtifact(
        importer="text",
        sourceHash="abc123",
        locationId="full_text",
        extension="json",
        content={
            "blocks": [
                {"index": 0, "text": "PAN-SEARED SALMON", "features": {"is_heading": True}},
                {
                    "index": 1,
                    "text": (
                        "I first cooked this on a rainy night, and this paragraph is memoir-like "
                        "scene-setting prose instead of recipe structure."
                    ),
                },
            ],
            "block_count": 2,
        },
        metadata={"artifact_type": "extracted_blocks"},
    )
    result = ConversionResult(
        recipes=[recipe],
        sourceBlocks=[
            SourceBlock(blockId="b0", orderIndex=0, text="PAN-SEARED SALMON"),
            SourceBlock(
                blockId="b1",
                orderIndex=1,
                text=(
                    "I first cooked this on a rainy night, and this paragraph is memoir-like "
                    "scene-setting prose instead of recipe structure."
                ),
            ),
        ],
        report=ConversionReport(),
        rawArtifacts=[raw],
        workbook="narrative-title",
        workbookPath="/tmp/narrative-title.txt",
    )

    payload = build_semantic_row_predictions(
        result,
        "narrative-title",
        recipe_ownership_result=_single_recipe_ownership(result, range(2)),
    )

    assert payload["row_labels"]["0"] == "OTHER"
    assert payload["unresolved_recipe_exact_evidence"] == [
        {
            "recipe_id": "urn:recipe:test:narrative-title",
            "label": "RECIPE_TITLE",
            "value": "PAN-SEARED SALMON",
        }
    ]


def test_build_semantic_row_predictions_marks_notes_from_description_only() -> None:
    result = _build_result(
        comment_text=None,
        description="Why this recipe works\nKeep the heat low to avoid curdling.",
        note_block_text="Keep the heat low to avoid curdling.",
    )

    payload = build_semantic_row_predictions(
        result,
        "simple",
        recipe_ownership_result=_single_recipe_ownership(result, range(8)),
    )

    assert payload["row_labels"]["7"] == "RECIPE_NOTES"
    assert 7 in payload["label_rows"]["RECIPE_NOTES"]


def test_write_semantic_row_predictions_prefers_final_nonrecipe_authority(
    tmp_path: Path,
) -> None:
    result = _build_result()
    archive_blocks = list(result.raw_artifacts[0].content["blocks"])
    label_first_result = LabelFirstStageResult(
        updated_conversion_result=result,
        archive_blocks=archive_blocks,
        source_hash="abc123",
        block_labels=[
            AuthoritativeBlockLabel(
                source_block_id=f"b{index}",
                source_block_index=index,
                supporting_atomic_indices=[],
                deterministic_label="OTHER",
                final_label="OTHER",
                decided_by="rule",
                reason_tags=[],
                escalation_reasons=[],
            )
            for index in range(9)
        ],
    )

    output_path = write_semantic_row_predictions(
        results=result,
        run_root=tmp_path,
        workbook_slug="simple",
        recipe_ownership_result=_single_recipe_ownership(result, range(8)),
        source_file="/tmp/simple.txt",
        nonrecipe_stage_result=make_stage_result(
            seed=make_seed_result({8: "candidate"}),
            routing=make_routing_result(candidate_row_indices=[8]),
            authority=make_authority_result({8: "knowledge"}),
            candidate_status=make_candidate_status_result(
                finalized_candidate_row_indices=[8],
                unresolved_candidate_route_by_index={},
            ),
        ),
        label_first_result=label_first_result,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["row_labels"]["8"] == "KNOWLEDGE"


def _build_sectioned_result() -> ConversionResult:
    recipe = RecipeCandidate(
        identifier="urn:recipe:test:sectioned",
        name="Meat and Gravy",
        recipeIngredient=[
            "For the meat:",
            "1 lb beef",
            "For the gravy:",
            "2 tbsp flour",
        ],
        recipeInstructions=[
            "For the meat:",
            "Brown the beef.",
            "For the gravy:",
            "Whisk flour into drippings.",
        ],
        provenance={"location": {"start_block": 0, "end_block": 8}},
    )

    raw = RawArtifact(
        importer="text",
        sourceHash="abc123",
        locationId="full_text",
        extension="json",
        content={
            "blocks": [
                {"index": 0, "text": "Meat and Gravy", "features": {"is_heading": True}},
                {"index": 1, "text": "For the meat:", "features": {"block_role": "ingredient_line"}},
                {"index": 2, "text": "1 lb beef", "features": {"block_role": "ingredient_line"}},
                {"index": 3, "text": "For the gravy:", "features": {"block_role": "ingredient_line"}},
                {"index": 4, "text": "2 tbsp flour", "features": {"block_role": "ingredient_line"}},
                {"index": 5, "text": "For the meat:", "features": {"block_role": "instruction_line"}},
                {"index": 6, "text": "Brown the beef.", "features": {"block_role": "instruction_line"}},
                {"index": 7, "text": "For the gravy:", "features": {"block_role": "instruction_line"}},
                {
                    "index": 8,
                    "text": "Whisk flour into drippings.",
                    "features": {"block_role": "instruction_line"},
                },
            ],
            "block_count": 9,
        },
        metadata={"artifact_type": "extracted_blocks"},
    )

    return ConversionResult(
        recipes=[recipe],
        sourceBlocks=[
            SourceBlock(blockId="b0", orderIndex=0, text="Stew with Gravy"),
            SourceBlock(blockId="b1", orderIndex=1, text="For the stew:"),
            SourceBlock(blockId="b2", orderIndex=2, text="1 lb beef"),
            SourceBlock(blockId="b3", orderIndex=3, text="For the gravy:"),
            SourceBlock(blockId="b4", orderIndex=4, text="2 tbsp flour"),
            SourceBlock(blockId="b5", orderIndex=5, text="For the meat:"),
            SourceBlock(blockId="b6", orderIndex=6, text="Brown the beef."),
            SourceBlock(blockId="b7", orderIndex=7, text="For the gravy:"),
            SourceBlock(blockId="b8", orderIndex=8, text="Whisk flour into drippings."),
        ],
        report=ConversionReport(),
        rawArtifacts=[raw],
        workbook="sectioned",
        workbookPath="/tmp/sectioned.txt",
    )


def test_build_semantic_row_predictions_emits_howto_sections_from_headers() -> None:
    result = _build_sectioned_result()
    payload = build_semantic_row_predictions(
        result,
        "sectioned",
        recipe_ownership_result=_single_recipe_ownership(result, range(9)),
    )

    row_labels = payload["row_labels"]
    assert row_labels["0"] == "OTHER"
    assert row_labels["1"] == "OTHER"
    assert row_labels["3"] == "HOWTO_SECTION"
    assert row_labels["5"] == "HOWTO_SECTION"
    assert row_labels["7"] == "HOWTO_SECTION"
    assert row_labels["2"] == "INGREDIENT_LINE"
    assert row_labels["6"] == "INSTRUCTION_LINE"

    conflicts = payload["conflicts"]
    assert any(
        row.get("row_index") == 3
        and set(row.get("labels", []))
        == {"HOWTO_SECTION", "INGREDIENT_LINE", "INSTRUCTION_LINE"}
        for row in conflicts
    )
    assert any(
        row.get("row_index") == 5
        and set(row.get("labels", []))
        == {"HOWTO_SECTION", "INGREDIENT_LINE", "INSTRUCTION_LINE"}
        for row in conflicts
    )


def test_is_howto_section_text_rejects_generic_all_caps_single_word_headers() -> None:
    assert _is_howto_section_text("FOR THE SAUCE")
    assert _is_howto_section_text("To Serve")
    assert not _is_howto_section_text("CHAPTER")


def test_build_semantic_row_predictions_supports_line_range_provenance() -> None:
    recipe = RecipeCandidate(
        identifier="urn:recipe:test:line-range",
        name="Meat and Gravy",
        recipeIngredient=["For the meat:", "1 lb beef"],
        recipeInstructions=["For the meat:", "Brown the beef."],
        provenance={"location": {"start_line": 1, "end_line": 7}},
    )
    raw = RawArtifact(
        importer="text",
        sourceHash="abc123",
        locationId="full_text",
        extension="json",
        content={
            "lines": [
                {"index": 0, "text": "Title: Meat and Gravy"},
                {"index": 1, "text": "Ingredients:"},
                {"index": 2, "text": "For the meat:"},
                {"index": 3, "text": "1 lb beef"},
                {"index": 4, "text": "Instructions:"},
                {"index": 5, "text": "For the meat:"},
                {"index": 6, "text": "Brown the beef."},
            ],
            "text": "Title: Meat and Gravy\nIngredients:\nFor the meat:\n1 lb beef\nInstructions:\nFor the meat:\nBrown the beef.\n",
        },
        metadata={"artifact_type": "extracted_text"},
    )
    result = ConversionResult(
        recipes=[recipe],
        sourceBlocks=[
            SourceBlock(blockId="b0", orderIndex=0, text="Title: Meat and Gravy"),
            SourceBlock(blockId="b1", orderIndex=1, text="Ingredients:"),
            SourceBlock(blockId="b2", orderIndex=2, text="For the meat:"),
            SourceBlock(blockId="b3", orderIndex=3, text="1 lb beef"),
            SourceBlock(blockId="b4", orderIndex=4, text="Instructions:"),
            SourceBlock(blockId="b5", orderIndex=5, text="For the meat:"),
            SourceBlock(blockId="b6", orderIndex=6, text="Brown the beef."),
        ],
        report=ConversionReport(),
        rawArtifacts=[raw],
        workbook="line-range",
        workbookPath="/tmp/line-range.txt",
    )

    payload = build_semantic_row_predictions(
        result,
        "line-range",
        recipe_ownership_result=_single_recipe_ownership(result, range(7)),
    )

    assert payload["row_labels"]["2"] == "HOWTO_SECTION"
    assert payload["row_labels"]["5"] == "HOWTO_SECTION"
    assert all(
        "lacked block-range provenance" not in note
        for note in payload["notes"]
    )


def test_build_semantic_row_predictions_rejects_title_without_boundary_evidence() -> None:
    recipe = RecipeCandidate(
        identifier="urn:recipe:test:narrative-title",
        name="PAN-SEARED SALMON",
        recipeIngredient=["2 salmon fillets"],
        recipeInstructions=["Sear the salmon."],
        provenance={"location": {"start_block": 0, "end_block": 1}},
    )
    raw = RawArtifact(
        importer="text",
        sourceHash="abc123",
        locationId="full_text",
        extension="json",
        content={
            "blocks": [
                {"index": 0, "text": "PAN-SEARED SALMON", "features": {"is_heading": True}},
                {
                    "index": 1,
                    "text": (
                        "I first cooked this on a rainy night, and this paragraph is memoir-like "
                        "scene-setting prose instead of recipe structure."
                    ),
                },
            ],
            "block_count": 2,
        },
        metadata={"artifact_type": "extracted_blocks"},
    )
    result = ConversionResult(
        recipes=[recipe],
        sourceBlocks=[
            SourceBlock(blockId="b0", orderIndex=0, text="PAN-SEARED SALMON"),
            SourceBlock(
                blockId="b1",
                orderIndex=1,
                text=(
                    "I first cooked this on a rainy night, and this paragraph is memoir-like "
                    "scene-setting prose instead of recipe structure."
                ),
            ),
        ],
        report=ConversionReport(),
        rawArtifacts=[raw],
        workbook="narrative-title",
        workbookPath="/tmp/narrative-title.txt",
    )

    payload = build_semantic_row_predictions(
        result,
        "narrative-title",
        recipe_ownership_result=_single_recipe_ownership(result, range(2)),
    )

    assert payload["row_labels"]["0"] == "OTHER"
    assert not payload["label_rows"]["RECIPE_TITLE"]
