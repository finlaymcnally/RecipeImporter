from __future__ import annotations

# Shared imports and helper writers for the split benchmark-helper test modules.

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


def _benchmark_test_run_settings(
    payload: dict[str, object] | None = None,
    *,
    warn_context: str = "test",
) -> cli.RunSettings:
    config: dict[str, object] = {}
    if payload:
        config.update(payload)
    run_settings_payload = {
        key: value for key, value in config.items() if key in cli.RunSettings.model_fields
    }
    return cli.RunSettings.from_dict(run_settings_payload, warn_context=warn_context)


def _patch_benchmark_call_kwargs_codex_policy(
    monkeypatch: pytest.MonkeyPatch,
    *,
    default_policy: str = "auto",
) -> None:
    real = cli.build_benchmark_call_kwargs_from_run_settings

    def _wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
        payload = real(*args, **kwargs)
        payload.setdefault("codex_execution_policy", default_policy)
        return payload

    monkeypatch.setattr(cli, "build_benchmark_call_kwargs_from_run_settings", _wrapped)


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
                "run_kind": "labelstudio_benchmark_prediction_stage",
                "run_config": {},
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


def _fake_offline_prediction_stage(
    *,
    prediction_generation_kwargs: dict[str, object],
    eval_output_dir: Path,
    predictions_out_path: Path | None,
    source_file: Path,
    extractor: str,
    signature_seed: str | None = None,
    prediction_seconds: float = 0.0,
) -> cli.BenchmarkPredictionStageResult:
    fake_kwargs = dict(prediction_generation_kwargs)
    fake_kwargs["eval_output_dir"] = eval_output_dir
    fake_kwargs["predictions_out"] = predictions_out_path
    _write_fake_all_method_prediction_phase_artifacts(
        kwargs=fake_kwargs,
        source_file=source_file,
        extractor=extractor,
        signature_seed=signature_seed,
        prediction_seconds=prediction_seconds,
    )
    prediction_bundle = cli.BenchmarkPredictionBundle(
        import_result={
            "run_root": str(eval_output_dir / "prediction-run"),
            "timing": {"prediction_seconds": prediction_seconds},
        },
        pred_run=eval_output_dir / "prediction-run",
        pred_context=cli.PredRunContext(
            recipes=1,
            processed_report_path="",
            stage_block_predictions_path="",
            extracted_archive_path="",
            source_file=str(source_file),
            source_hash=f"source-{source_file.stem}",
            run_config=None,
            run_config_hash=f"hash-{extractor}",
            run_config_summary=f"epub_extractor={extractor}",
            tokens_input=None,
            tokens_cached_input=None,
            tokens_output=None,
            tokens_reasoning=None,
            tokens_total=None,
        ),
        stage_predictions_path=eval_output_dir / "prediction-run" / "stage_block_predictions.json",
        extracted_archive_path=eval_output_dir / "prediction-run" / "extracted_archive.json",
        prediction_phase_seconds=prediction_seconds,
    )
    return cli.BenchmarkPredictionStageResult(
        prediction_bundle=prediction_bundle,
        prediction_records=list(read_prediction_records(predictions_out_path))
        if predictions_out_path is not None
        else [],
        codexfarm_prompt_response_log_path=None,
        single_offline_split_cache_metadata=None,
    )


def _write_labelstudio_compare_source_row(
    *,
    run_root: Path,
    source_key: str,
    practical_f1: float,
    line_accuracy: float,
    ingredient_recall: float,
    variant_recall: float,
    llm_recipe_pipeline: str,
    codex_farm_recipe_mode: str,
    write_required_llm_debug: bool,
    write_prompt_manifests: bool | None = None,
    include_prediction_run_config: bool = True,
) -> dict[str, object]:
    source_root = run_root / "sources" / source_key
    eval_root = source_root / "winner_eval"
    prediction_run_root = eval_root / "prediction-run"
    prediction_run_root.mkdir(parents=True, exist_ok=True)

    (eval_root / "aligned_prediction_blocks.jsonl").write_text(
        "{}\n",
        encoding="utf-8",
    )

    eval_report = {
        "practical_f1": practical_f1,
        "overall_line_accuracy": line_accuracy,
        "per_label": {
            "INGREDIENT_LINE": {"recall": ingredient_recall},
            "RECIPE_VARIANT": {"recall": variant_recall},
        },
        "artifacts": {
            "aligned_prediction_blocks_jsonl": "aligned_prediction_blocks.jsonl",
        },
    }
    (eval_root / "eval_report.json").write_text(
        json.dumps(eval_report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if write_prompt_manifests is None:
        write_prompt_manifests = bool(write_required_llm_debug)
    if include_prediction_run_config:
        prediction_run_config = {
            "llm_recipe_pipeline": llm_recipe_pipeline,
            "codex_farm_recipe_mode": codex_farm_recipe_mode,
        }
    else:
        prediction_run_config = {}
    prediction_run_manifest = {
        "run_config": (
            {"prediction_run_config": prediction_run_config}
            if prediction_run_config
            else {}
        ),
        "artifacts": {"artifact_root_dir": "prediction-run"},
    }
    (eval_root / "run_manifest.json").write_text(
        json.dumps(prediction_run_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if (
        llm_recipe_pipeline == "codex-recipe-shard-v1"
        and codex_farm_recipe_mode == "benchmark"
        and write_required_llm_debug
    ):
        llm_root = prediction_run_root / "llm"
        correction_in = llm_root / "recipe_correction" / "in"
        correction_out = llm_root / "recipe_correction" / "out"
        for folder in (correction_in, correction_out):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "r0000.json").write_text("{}", encoding="utf-8")
        llm_manifest = {
            "pipeline": "codex-recipe-shard-v1",
            "pipelines": {
                "recipe_correction": "recipe.correction.compact.v1",
            },
            "paths": {
                "recipe_correction_in": str(correction_in),
                "recipe_correction_out": str(correction_out),
            },
            "process_runs": {
                "recipe_correction": {
                    "run_id": "run-recipe-correction",
                    "pipeline_id": "recipe.correction.compact.v1",
                },
            },
        }
        llm_manifest_path = prediction_run_root / "recipe_manifest.json"
        llm_manifest_path.write_text(
            json.dumps(llm_manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        prediction_run_manifest["artifacts"]["recipe_manifest_json"] = str(llm_manifest_path)
        if write_prompt_manifests:
            prompt_input_payloads = [
                correction_in / "prompt_request_0.json",
            ]
            prompt_output_payloads = [
                correction_out / "prompt_response_0.json",
            ]
            for payload_path in prompt_input_payloads:
                payload_path.write_text("{}", encoding="utf-8")
            for payload_path in prompt_output_payloads:
                payload_path.write_text("{}", encoding="utf-8")
            prompt_inputs_manifest_path = prediction_run_root / "prompt_inputs_manifest.txt"
            prompt_outputs_manifest_path = prediction_run_root / "prompt_outputs_manifest.txt"
            prompt_inputs_manifest_path.write_text(
                "\n".join(str(path) for path in prompt_input_payloads) + "\n",
                encoding="utf-8",
            )
            prompt_outputs_manifest_path.write_text(
                "\n".join(str(path) for path in prompt_output_payloads) + "\n",
                encoding="utf-8",
            )
            prediction_run_manifest["artifacts"]["prompt_inputs_manifest_txt"] = str(
                prompt_inputs_manifest_path
            )
            prediction_run_manifest["artifacts"]["prompt_outputs_manifest_txt"] = str(
                prompt_outputs_manifest_path
            )

    (prediction_run_root / "run_manifest.json").write_text(
        json.dumps(prediction_run_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    source_report_path = source_root / "all_method_benchmark_report.json"
    source_report = {
        "winner_by_f1": {
            "eval_report_json": str(eval_root / "eval_report.json"),
        }
    }
    source_report_path.write_text(
        json.dumps(source_report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return {
        "source_group_key": source_key,
        "report_json_path": str(source_report_path),
        "winner_metrics": {
            "precision": practical_f1,
            "recall": practical_f1,
            "f1": practical_f1,
            "practical_f1": practical_f1,
        },
    }


def _write_labelstudio_compare_multi_source_report(
    run_root: Path,
    rows: list[dict[str, object]],
) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    payload = {"sources": rows}
    (run_root / "all_method_benchmark_multi_source_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _dispatch_fake_prediction_stage_via_legacy_benchmark_double(
    *,
    fake_labelstudio_benchmark: callable,
    prediction_generation_kwargs: dict[str, object],
    eval_output_dir: Path,
    predictions_out_path: Path | None,
    source_file: Path,
    extractor: str,
    signature_seed: str | None = None,
    prediction_seconds: float = 0.0,
    extra_kwargs: dict[str, object] | None = None,
) -> cli.BenchmarkPredictionStageResult:
    alignment_cache_dir = prediction_generation_kwargs.get("alignment_cache_dir")
    if alignment_cache_dir is None:
        alignment_cache_dir = eval_output_dir.parent / ".cache" / "canonical_alignment"
    translated_kwargs: dict[str, object] = {
        "eval_output_dir": eval_output_dir,
        "processed_output_dir": prediction_generation_kwargs.get("processed_output_root"),
        "predictions_out": predictions_out_path,
        "source_file": prediction_generation_kwargs.get("path"),
        "epub_extractor": prediction_generation_kwargs.get("epub_extractor"),
        "alignment_cache_dir": alignment_cache_dir,
        "prediction_stage_only": True,
    }
    if extra_kwargs:
        translated_kwargs.update(extra_kwargs)
    fake_labelstudio_benchmark(**translated_kwargs)
    return _fake_offline_prediction_stage(
        prediction_generation_kwargs=prediction_generation_kwargs,
        eval_output_dir=eval_output_dir,
        predictions_out_path=predictions_out_path,
        source_file=source_file,
        extractor=extractor,
        signature_seed=signature_seed,
        prediction_seconds=prediction_seconds,
    )
