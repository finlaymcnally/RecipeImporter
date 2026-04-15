from __future__ import annotations

from pathlib import Path

import pytest

from cookimport.bench.prediction_records import (
    PredictionRecord,
    make_prediction_record,
    read_prediction_records,
    read_single_prediction_record,
    write_prediction_records,
)


def test_prediction_record_roundtrip_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "prediction_records.jsonl"
    records = [
        make_prediction_record(
            example_id="example-0",
            example_index=0,
            prediction={"semantic_row_predictions_path": "/tmp/a.json"},
            predict_meta={"source_file": "book.epub"},
        ),
        make_prediction_record(
            example_id="example-1",
            example_index=1,
            prediction={"semantic_row_predictions_path": "/tmp/b.json"},
            predict_meta={"source_file": "book-two.epub"},
        ),
    ]

    write_prediction_records(path, records)
    loaded = list(read_prediction_records(path))

    assert loaded == records


def test_prediction_record_missing_required_key_raises_clear_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prediction_records.jsonl"
    path.write_text(
        '{"schema_version":1,"example_id":"example-0","example_index":0,"prediction":{}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required key: predict_meta"):
        list(read_prediction_records(path))


def test_read_single_prediction_record_requires_exactly_one(tmp_path: Path) -> None:
    path = tmp_path / "prediction_records.jsonl"
    records = [
        PredictionRecord(
            schema_version=1,
            example_id="example-0",
            example_index=0,
            prediction={"semantic_row_predictions_path": "/tmp/a.json"},
            predict_meta={"source_file": "book.epub"},
        ),
        PredictionRecord(
            schema_version=1,
            example_id="example-1",
            example_index=1,
            prediction={"semantic_row_predictions_path": "/tmp/b.json"},
            predict_meta={"source_file": "book-two.epub"},
        ),
    ]
    write_prediction_records(path, records)

    with pytest.raises(ValueError, match="contains multiple records"):
        read_single_prediction_record(path)
