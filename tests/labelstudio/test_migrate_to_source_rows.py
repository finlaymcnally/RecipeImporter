import json

from cookimport.labelstudio.migrate_to_source_rows import (
    MigrationResult,
    build_row_labelstudio_seed_package,
    migrate_freeform_export_to_row_gold,
)
from cookimport.parsing.source_rows import SourceRow, write_source_rows


def test_row_seed_package_uses_non_overlapping_focus_rows(tmp_path) -> None:
    rows = [
        SourceRow(
            row_id=f"row-{index}",
            source_hash="hash-1",
            row_index=index,
            row_ordinal=index,
            block_id=f"block-{index}",
            block_index=index,
            start_char_in_block=0,
            end_char_in_block=len(f"row {index}"),
            text=f"row {index}",
            rule_tags=[],
        )
        for index in range(245)
    ]
    source_rows_path = tmp_path / "source_rows.jsonl"
    write_source_rows(source_rows_path, rows)

    migration_result = MigrationResult(
        migrated_labeled_row_count=len(rows),
        ambiguous_row_count=0,
        unlabeled_row_count=0,
        conflicting_row_count=0,
        row_gold_rows=[
            {
                "row_id": row.row_id,
                "row_index": row.row_index,
                "block_index": row.block_index,
                "row_ordinal": row.row_ordinal,
                "text": row.text,
                "source_hash": row.source_hash,
                "source_file": "test-source",
                "labels": ["OTHER"],
            }
            for row in rows
        ],
        ambiguous_rows=[],
        conflicting_rows=[],
    )

    seed_package = build_row_labelstudio_seed_package(
        migration_result=migration_result,
        source_rows_jsonl_path=source_rows_path,
    )

    assert seed_package.task_count == 3

    focus_row_groups: list[list[str]] = []
    for task in seed_package.tasks:
        data = task.get("data")
        assert isinstance(data, dict)
        source_map = data.get("source_map")
        assert isinstance(source_map, dict)
        rows_payload = source_map.get("rows")
        assert isinstance(rows_payload, list)
        focus_row_groups.append([str(row.get("row_id")) for row in rows_payload if isinstance(row, dict)])

    assert focus_row_groups[0] == [f"row-{index}" for index in range(120)]
    assert focus_row_groups[1] == [f"row-{index}" for index in range(120, 240)]
    assert focus_row_groups[2] == [f"row-{index}" for index in range(240, 245)]
    assert set(focus_row_groups[0]).isdisjoint(focus_row_groups[1])
    assert set(focus_row_groups[1]).isdisjoint(focus_row_groups[2])


def test_migrate_freeform_export_to_row_gold_prefers_source_block_index(tmp_path) -> None:
    source_rows = [
        SourceRow(
            row_id="row-a",
            source_hash="hash-1",
            row_index=0,
            row_ordinal=0,
            block_id="block-10",
            block_index=10,
            start_char_in_block=0,
            end_char_in_block=len("Bright Cabbage Slaw"),
            text="Bright Cabbage Slaw",
            rule_tags=["title_like"],
        ),
        SourceRow(
            row_id="row-b",
            source_hash="hash-1",
            row_index=1,
            row_ordinal=0,
            block_id="block-20",
            block_index=20,
            start_char_in_block=0,
            end_char_in_block=len("Salt is essential."),
            text="Salt is essential.",
            rule_tags=["explicit_prose"],
        ),
    ]
    source_rows_path = tmp_path / "source_rows.jsonl"
    write_source_rows(source_rows_path, source_rows)

    freeform_path = tmp_path / "freeform_span_labels.jsonl"
    freeform_path.write_text(
        json.dumps(
            {
                "label": "RECIPE_TITLE",
                "span_id": "span-1",
                "start_offset": 0,
                "end_offset": len("Bright Cabbage Slaw"),
                "touched_blocks": [
                    {
                        "block_index": 1,
                        "source_block_index": 10,
                        "segment_start": 0,
                        "segment_end": len("Bright Cabbage Slaw"),
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = migrate_freeform_export_to_row_gold(
        freeform_span_labels_jsonl_path=freeform_path,
        source_rows_jsonl_path=source_rows_path,
    )

    labels_by_row_id = {
        row["row_id"]: row["labels"]
        for row in result.row_gold_rows
    }
    assert labels_by_row_id == {
        "row-a": ["RECIPE_TITLE"],
        "row-b": ["OTHER"],
    }


def test_migrate_freeform_export_to_row_gold_prefers_exact_row_id_for_row_native_spans(
    tmp_path,
) -> None:
    texts = [
        "Add the remaining croutons, asparagus, and macerated onions (but not their vinegar, yet). Tear in the mint leaves in small pieces.",
        "Crumble in the feta in large pieces. Dress with another 1/3 cup vinaigrette and season with salt, then taste.",
        "Adjust seasoning with salt, vinaigrette, and the macerating vinegar as needed. Toss, taste again, and serve at room temperature.",
    ]
    source_rows = []
    start = 0
    for row_index, text in enumerate(texts):
        end = start + len(text)
        source_rows.append(
            SourceRow(
                row_id=f"row-{row_index}",
                source_hash="hash-1",
                row_index=row_index,
                row_ordinal=row_index,
                block_id="block-1274",
                block_index=1274,
                start_char_in_block=start,
                end_char_in_block=end,
                text=text,
                rule_tags=["instruction_like"],
            )
        )
        start = end + 1

    source_rows_path = tmp_path / "source_rows.jsonl"
    write_source_rows(source_rows_path, source_rows)

    freeform_rows = [
        {
            "label": "INSTRUCTION_LINE",
            "span_id": "span-1",
            "start_offset": 3687,
            "end_offset": 3817,
            "source_file": "source_rows.jsonl",
            "touched_blocks": [
                {
                    "row_id": "row-0",
                    "row_index": 0,
                    "block_index": 0,
                    "source_block_index": 1274,
                    "segment_start": 3687,
                    "segment_end": 3817,
                }
            ],
        },
        {
            "label": "OTHER",
            "span_id": "span-2",
            "start_offset": 3819,
            "end_offset": 3928,
            "source_file": "source_rows.jsonl",
            "touched_blocks": [
                {
                    "row_id": "row-1",
                    "row_index": 1,
                    "block_index": 1,
                    "source_block_index": 1274,
                    "segment_start": 3819,
                    "segment_end": 3928,
                }
            ],
        },
        {
            "label": "OTHER",
            "span_id": "span-3",
            "start_offset": 3930,
            "end_offset": 4058,
            "source_file": "source_rows.jsonl",
            "touched_blocks": [
                {
                    "row_id": "row-2",
                    "row_index": 2,
                    "block_index": 2,
                    "source_block_index": 1274,
                    "segment_start": 3930,
                    "segment_end": 4058,
                }
            ],
        },
    ]
    freeform_path = tmp_path / "freeform_span_labels.jsonl"
    freeform_path.write_text(
        "\n".join(json.dumps(row) for row in freeform_rows) + "\n",
        encoding="utf-8",
    )

    result = migrate_freeform_export_to_row_gold(
        freeform_span_labels_jsonl_path=freeform_path,
        source_rows_jsonl_path=source_rows_path,
    )

    labels_by_row_id = {
        row["row_id"]: row["labels"]
        for row in result.row_gold_rows
    }
    assert labels_by_row_id == {
        "row-0": ["INSTRUCTION_LINE"],
        "row-1": ["OTHER"],
        "row-2": ["OTHER"],
    }
    assert result.conflicting_rows == []
    assert result.ambiguous_rows == []
