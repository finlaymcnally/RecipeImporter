from __future__ import annotations

# Shared benchmark-helper case bodies live here so focused `test_*.py` entrypoints
# can re-export them without keeping one huge pytest target.

import builtins
import csv
import datetime as dt
import inspect
import json
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import cookimport.cli as cli
from cookimport.bench.prediction_records import (
    make_prediction_record,
    read_prediction_records,
    write_prediction_records,
)
from cookimport.core.progress_messages import (
    format_worker_activity,
    format_worker_activity_reset,
)
from cookimport.llm.prompt_budget import (
    build_prediction_run_prompt_budget_summary,
    write_prediction_run_prompt_budget_summary,
)
from cookimport.labelstudio.ingest import (
    generate_pred_run_artifacts,
    run_labelstudio_import,
)


def _write_fake_all_method_prediction_phase_artifacts(
    *,
    kwargs: dict[str, object],
    source_file: Path,
    extractor: str,
    signature_seed: str | None = None,
    prediction_seconds: float = 0.0,
) -> None:
    eval_output_dir = kwargs["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)
    eval_output_dir.mkdir(parents=True, exist_ok=True)

    run_config_hash = f"hash-{extractor}"
    run_config_summary = f"epub_extractor={extractor}"
    record_text = signature_seed or extractor
    predictions_out = kwargs.get("predictions_out")
    if isinstance(predictions_out, Path):
        write_prediction_records(
            predictions_out,
            [
                make_prediction_record(
                    example_id=f"all-method:{source_file.name}:{record_text}:0",
                    example_index=0,
                    prediction={
                        "schema_kind": "stage-block.v1",
                        "block_index": 0,
                        "pred_label": "RECIPE_TITLE",
                        "block_text": f"pred::{record_text}",
                        "block_features": {"signature_seed": record_text},
                    },
                    predict_meta={
                        "source_file": str(source_file),
                        "source_hash": f"source-{source_file.stem}",
                        "workbook_slug": source_file.stem,
                        "run_config_hash": run_config_hash,
                        "run_config_summary": run_config_summary,
                        "timing": {"prediction_seconds": prediction_seconds},
                    },
                )
            ],
        )

    pred_run = eval_output_dir / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": f"source-{source_file.stem}",
                "run_config_hash": run_config_hash,
                "run_config_summary": run_config_summary,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (eval_output_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_config": {
                    "execution_mode": str(kwargs.get("execution_mode") or "pipelined"),
                    "predict_only": True,
                },
                "artifacts": {
                    "timing": {
                        "total_seconds": prediction_seconds,
                        "prediction_seconds": prediction_seconds,
                        "evaluation_seconds": 0.0,
                    }
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_fake_all_method_eval_artifacts(
    *,
    eval_output_dir: Path,
    score: float,
    total_seconds: float | None = None,
) -> None:
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "precision": score,
        "recall": score,
        "f1": score,
        "practical_precision": score,
        "practical_recall": score,
        "practical_f1": score,
    }
    if total_seconds is not None:
        report["timing"] = {
            "total_seconds": float(total_seconds),
            "prediction_seconds": 0.0,
            "evaluation_seconds": float(total_seconds),
        }
    (eval_output_dir / "eval_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (eval_output_dir / "eval_report.md").write_text("report", encoding="utf-8")
