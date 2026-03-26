from __future__ import annotations

from pathlib import Path

import pytest

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    RawArtifact,
    SourceBlock,
    SourceSupport,
)
from cookimport.core.source_model import (
    normalize_source_support,
    offset_source_support,
    resolve_conversion_source_model,
    write_source_model_artifacts,
)
from cookimport.parsing.label_source_of_truth import build_label_first_stage_result
from cookimport.config.run_settings import RunSettings


def test_resolve_conversion_source_model_rejects_legacy_extracted_rows_only() -> None:
    result = ConversionResult(
        rawArtifacts=[
            RawArtifact(
                importer="excel",
                sourceHash="hash-123",
                locationId="full_rows",
                extension="json",
                content={
                    "rows": [
                        {
                            "sheet": "Sheet1",
                            "row_index": 3,
                            "headers": ["Name", "Ingredients"],
                            "row": ["Cake", "Flour"],
                        }
                    ]
                },
                metadata={"artifact_type": "extracted_rows"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="/tmp/book.xlsx",
    )

    with pytest.raises(ValueError, match="Stage input is missing canonical source blocks"):
        resolve_conversion_source_model(result)


def test_normalize_source_support_forces_non_authoritative_metadata() -> None:
    [support] = normalize_source_support(
        [
            {
                "hintClass": "proposal",
                "kind": "candidate_recipe_region",
                "referencedBlockIds": ["b0"],
                "payload": {"reason": "heading"},
                "metadata": {"authoritative": True, "source": "test"},
            }
        ]
    )

    assert support.metadata == {"authoritative": False, "source": "test"}


def test_offset_source_support_rebases_known_block_id_formats() -> None:
    [support] = offset_source_support(
        [
            SourceSupport(
                hintClass="evidence",
                kind="structured_recipe_object",
                referencedBlockIds=["b0", "block:2", "custom-id"],
                payload={"name": "Title"},
            )
        ],
        3,
    )

    assert support.referenced_block_ids == ["b3", "b5", "custom-id"]
    assert support.metadata == {"authoritative": False}


def test_source_support_does_not_create_recipe_authority(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("Technique note", encoding="utf-8")
    result = ConversionResult(
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
                payload={"reason": "structured export says recipe"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath=str(source),
    )

    stage_result = build_label_first_stage_result(
        conversion_result=result,
        source_file=source,
        importer_name="text",
        run_settings=RunSettings.from_dict({}, warn_context="test"),
        live_llm_allowed=False,
    )

    assert stage_result.updated_conversion_result.recipes == []
    assert [row["index"] for row in stage_result.updated_conversion_result.non_recipe_blocks] == [0]
    assert stage_result.updated_conversion_result.non_recipe_blocks[0]["text"] == "Technique note"


def test_write_source_model_artifacts_writes_expected_files(tmp_path: Path) -> None:
    paths = write_source_model_artifacts(
        tmp_path,
        "book",
        [
            SourceBlock(
                blockId="b0",
                orderIndex=0,
                text="Title",
                sourceText="Title",
                location={"line_index": 0},
            )
        ],
        [
            SourceSupport(
                hintClass="evidence",
                kind="structured_recipe_object",
                referencedBlockIds=["b0"],
                payload={"name": "Title"},
            )
        ],
    )

    assert paths["source_blocks_path"] == tmp_path / "raw" / "source" / "book" / "source_blocks.jsonl"
    assert paths["source_support_path"] == tmp_path / "raw" / "source" / "book" / "source_support.json"
    assert paths["source_blocks_path"].is_file()
    assert paths["source_support_path"].is_file()
    assert '"blockId": "b0"' in paths["source_blocks_path"].read_text(encoding="utf-8")
    assert '"authoritative": false' in paths["source_support_path"].read_text(encoding="utf-8")
