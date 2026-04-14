import json

from cookimport.labelstudio.migrate_to_source_rows import (
    MigrationResult,
    build_row_labelstudio_seed_package,
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
