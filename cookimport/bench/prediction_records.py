from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

PREDICTION_RECORD_SCHEMA_VERSION = 1

_REQUIRED_FIELDS = (
    "schema_version",
    "example_id",
    "example_index",
    "prediction",
    "predict_meta",
)


@dataclass(frozen=True)
class PredictionRecord:
    schema_version: int
    example_id: str
    example_index: int
    prediction: dict[str, Any]
    predict_meta: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "example_id": str(self.example_id),
            "example_index": int(self.example_index),
            "prediction": dict(self.prediction),
            "predict_meta": dict(self.predict_meta),
        }


def make_prediction_record(
    *,
    example_id: str,
    example_index: int,
    prediction: dict[str, Any],
    predict_meta: dict[str, Any],
) -> PredictionRecord:
    return _validate_prediction_record_payload(
        {
            "schema_version": PREDICTION_RECORD_SCHEMA_VERSION,
            "example_id": example_id,
            "example_index": example_index,
            "prediction": prediction,
            "predict_meta": predict_meta,
        }
    )


def _validation_context(*, line_number: int | None = None) -> str:
    if line_number is None:
        return "prediction record"
    return f"prediction record line {line_number}"


def _validate_prediction_record_payload(
    payload: Any,
    *,
    line_number: int | None = None,
) -> PredictionRecord:
    context = _validation_context(line_number=line_number)
    if not isinstance(payload, dict):
        raise ValueError(f"{context} must be a JSON object.")

    for field_name in _REQUIRED_FIELDS:
        if field_name not in payload:
            raise ValueError(f"{context} missing required key: {field_name}")

    try:
        schema_version = int(payload.get("schema_version"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} has invalid schema_version.") from exc
    if schema_version != PREDICTION_RECORD_SCHEMA_VERSION:
        raise ValueError(
            f"{context} schema_version {schema_version} is not supported."
        )

    example_id = str(payload.get("example_id") or "").strip()
    if not example_id:
        raise ValueError(f"{context} example_id must be a non-empty string.")

    try:
        example_index = int(payload.get("example_index"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} has invalid example_index.") from exc
    if example_index < 0:
        raise ValueError(f"{context} example_index must be >= 0.")

    prediction = payload.get("prediction")
    if not isinstance(prediction, dict):
        raise ValueError(f"{context} prediction must be a JSON object.")

    predict_meta = payload.get("predict_meta")
    if not isinstance(predict_meta, dict):
        raise ValueError(f"{context} predict_meta must be a JSON object.")

    return PredictionRecord(
        schema_version=schema_version,
        example_id=example_id,
        example_index=example_index,
        prediction=dict(prediction),
        predict_meta=dict(predict_meta),
    )


def write_prediction_records(path: Path, records: Iterable[PredictionRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    )
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(
                    json.dumps(
                        record.to_payload(),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    )
                )
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def read_prediction_records(path: Path) -> Iterator[PredictionRecord]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Prediction record file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"prediction record line {line_number} is not valid JSON."
                ) from exc
            yield _validate_prediction_record_payload(
                payload,
                line_number=line_number,
            )


def read_single_prediction_record(path: Path) -> PredictionRecord:
    records = list(read_prediction_records(path))
    if not records:
        raise ValueError(f"Prediction record file is empty: {path}")
    if len(records) > 1:
        raise ValueError(
            "Prediction record file contains multiple records; expected exactly one."
        )
    return records[0]
