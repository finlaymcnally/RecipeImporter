from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cookimport.labelstudio.freeform_tasks import build_freeform_span_tasks
from cookimport.labelstudio.label_config_freeform import FREEFORM_LABEL_CONTROL_NAME
from cookimport.labelstudio.result_ids import make_safe_label_studio_result_id
from cookimport.labelstudio.row_gold import write_row_gold_rows
from cookimport.parsing.source_rows import SourceRow, load_source_rows


@dataclass(frozen=True)
class MigrationResult:
    migrated_labeled_row_count: int
    ambiguous_row_count: int
    unlabeled_row_count: int
    conflicting_row_count: int
    row_gold_rows: list[dict[str, Any]]
    ambiguous_rows: list[dict[str, Any]]
    conflicting_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class RowProjectSeed:
    tasks: list[dict[str, Any]]
    seeded_annotation_count: int
    task_count: int


def migrate_freeform_export_to_row_gold(
    *,
    freeform_span_labels_jsonl_path: Path,
    source_rows_jsonl_path: Path,
) -> MigrationResult:
    span_rows = _read_jsonl(freeform_span_labels_jsonl_path)
    source_rows = load_source_rows(source_rows_jsonl_path)
    rows_by_block: dict[int, list[SourceRow]] = {}
    for row in source_rows:
        rows_by_block.setdefault(int(row.block_index), []).append(row)
    for rows in rows_by_block.values():
        rows.sort(key=lambda row: (int(row.start_char_in_block), int(row.row_index)))

    row_labels: dict[str, set[str]] = {}
    row_payload: dict[str, dict[str, Any]] = {}
    ambiguous_rows: list[dict[str, Any]] = []

    for span_row in span_rows:
        touched_blocks = span_row.get("touched_blocks")
        if not isinstance(touched_blocks, list):
            touched_blocks = []
        start_offset = _coerce_int(span_row.get("start_offset"))
        end_offset = _coerce_int(span_row.get("end_offset"))
        if start_offset is None or end_offset is None or end_offset <= start_offset:
            continue
        label = str(span_row.get("label") or "").strip()
        if not label:
            continue

        for touched in touched_blocks:
            if not isinstance(touched, dict):
                continue
            block_index = _coerce_int(touched.get("block_index"))
            segment_start = _coerce_int(touched.get("segment_start"))
            segment_end = _coerce_int(touched.get("segment_end"))
            if (
                block_index is None
                or segment_start is None
                or segment_end is None
                or segment_end <= segment_start
            ):
                continue
            local_start = max(0, start_offset - segment_start)
            local_end = min(segment_end - segment_start, end_offset - segment_start)
            if local_end <= local_start:
                continue
            for row in rows_by_block.get(block_index, []):
                overlap = min(local_end, int(row.end_char_in_block)) - max(
                    local_start, int(row.start_char_in_block)
                )
                if overlap <= 0:
                    continue
                row_id = str(row.row_id)
                row_labels.setdefault(row_id, set()).add(label)
                row_payload.setdefault(
                    row_id,
                    {
                        "row_id": row_id,
                        "row_index": int(row.row_index),
                        "block_index": int(row.block_index),
                        "row_ordinal": int(row.row_ordinal),
                        "text": str(row.text),
                        "source_hash": str(row.source_hash),
                        "source_file": str(span_row.get("source_file") or "unknown"),
                    },
                )
                row_length = max(1, int(row.end_char_in_block) - int(row.start_char_in_block))
                if overlap < row_length:
                    ambiguous_rows.append(
                        {
                            "row_id": row_id,
                            "label": label,
                            "row_index": int(row.row_index),
                            "block_index": int(row.block_index),
                            "row_text": str(row.text),
                            "overlap_chars": overlap,
                            "row_length": row_length,
                            "span_id": span_row.get("span_id"),
                        }
                    )

    row_gold_rows: list[dict[str, Any]] = []
    conflicting_rows: list[dict[str, Any]] = []
    for row in sorted(source_rows, key=lambda value: int(value.row_index)):
        payload = row_payload.get(str(row.row_id))
        if payload is None:
            payload = {
                "row_id": str(row.row_id),
                "row_index": int(row.row_index),
                "block_index": int(row.block_index),
                "row_ordinal": int(row.row_ordinal),
                "text": str(row.text),
                "source_hash": str(row.source_hash),
                "source_file": "unknown",
            }
        labels = sorted(row_labels.get(str(row.row_id), set()))
        if not labels:
            labels = ["OTHER"]
        gold_row = {
            **payload,
            "labels": labels,
        }
        row_gold_rows.append(gold_row)
        if len(labels) > 1:
            conflicting_rows.append(gold_row)

    labeled_row_ids = {str(row.get("row_id")) for row in row_gold_rows}
    unlabeled_row_count = sum(
        1 for row in source_rows if str(row.row_id) not in labeled_row_ids
    )
    return MigrationResult(
        migrated_labeled_row_count=len(row_gold_rows),
        ambiguous_row_count=len(ambiguous_rows),
        unlabeled_row_count=unlabeled_row_count,
        conflicting_row_count=len(conflicting_rows),
        row_gold_rows=row_gold_rows,
        ambiguous_rows=ambiguous_rows,
        conflicting_rows=conflicting_rows,
    )


def build_row_labelstudio_seed_package(
    *,
    migration_result: MigrationResult,
    source_rows_jsonl_path: Path,
) -> RowProjectSeed:
    source_rows = load_source_rows(source_rows_jsonl_path)
    tasks = build_freeform_span_tasks(
        archive=[row.model_dump(mode="json") for row in source_rows],
        source_hash=source_rows[0].source_hash if source_rows else "unknown",
        source_file=Path(source_rows_jsonl_path).name,
        book_id=Path(source_rows_jsonl_path).stem,
        segment_blocks=40,
        segment_overlap=5,
        segment_focus_blocks=40,
    )
    labels_by_row_id = {
        str(row.get("row_id")): list(row.get("labels") or [])
        for row in migration_result.row_gold_rows
    }
    seeded_annotation_count = 0
    for task in tasks:
        data = task.get("data")
        if not isinstance(data, dict):
            continue
        source_map = data.get("source_map")
        if not isinstance(source_map, dict):
            continue
        rows = source_map.get("rows")
        if not isinstance(rows, list):
            continue
        result_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("row_id") or "")
            labels = labels_by_row_id.get(row_id)
            if not labels:
                continue
            start = _coerce_int(row.get("segment_start"))
            end = _coerce_int(row.get("segment_end"))
            if start is None or end is None or end <= start:
                continue
            for label in labels:
                result_rows.append(
                    {
                        "id": make_safe_label_studio_result_id(
                            f"seed-{row_id}-{label}"
                        ),
                        "type": "labels",
                        "from_name": FREEFORM_LABEL_CONTROL_NAME,
                        "to_name": "segment_text",
                        "value": {
                            "start": start,
                            "end": end,
                            "text": str(data.get("segment_text") or "")[start:end],
                            "labels": [label],
                        },
                    }
                )
        if result_rows:
            task["predictions"] = [
                {
                    "model_version": "row-migration-seed-v1",
                    "score": 1.0,
                    "result": result_rows,
                }
            ]
            seeded_annotation_count += len(result_rows)
    return RowProjectSeed(
        tasks=tasks,
        seeded_annotation_count=seeded_annotation_count,
        task_count=len(tasks),
    )


def write_migration_result(
    *,
    output_dir: Path,
    migration_result: MigrationResult,
    seed_package: RowProjectSeed | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    row_gold_path = output_dir / "row_gold_labels.jsonl"
    ambiguous_path = output_dir / "row_gold_ambiguous.jsonl"
    conflicts_path = output_dir / "row_gold_conflicts.jsonl"
    summary_path = output_dir / "migration_summary.json"
    write_row_gold_rows(row_gold_path, migration_result.row_gold_rows)
    write_row_gold_rows(ambiguous_path, migration_result.ambiguous_rows)
    write_row_gold_rows(conflicts_path, migration_result.conflicting_rows)
    if seed_package is not None:
        tasks_path = output_dir / "row_seed_tasks.jsonl"
        tasks_path.write_text(
            "\n".join(json.dumps(task) for task in seed_package.tasks) + "\n",
            encoding="utf-8",
        )
    else:
        tasks_path = output_dir / "row_seed_tasks.jsonl"
        tasks_path.write_text("", encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "migrated_labeled_row_count": migration_result.migrated_labeled_row_count,
                "ambiguous_row_count": migration_result.ambiguous_row_count,
                "unlabeled_row_count": migration_result.unlabeled_row_count,
                "conflicting_row_count": migration_result.conflicting_row_count,
                "seed_task_count": seed_package.task_count if seed_package else 0,
                "seeded_annotation_count": (
                    seed_package.seeded_annotation_count if seed_package else 0
                ),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "row_gold_path": row_gold_path,
        "ambiguous_path": ambiguous_path,
        "conflicts_path": conflicts_path,
        "summary_path": summary_path,
        "seed_tasks_path": tasks_path,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
