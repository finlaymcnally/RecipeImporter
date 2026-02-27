from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
from pathlib import Path
from typing import Any

import pytest

from cookimport.bench.canonical_alignment_cache import (
    CANONICAL_ALIGNMENT_ALGO_VERSION,
    CANONICAL_ALIGNMENT_NORMALIZATION_VERSION,
    CanonicalAlignmentDiskCache,
    build_cache_file_key,
    hash_block_boundaries,
    make_cache_entry,
    sha256_text,
)
from cookimport.bench.eval_canonical_text import evaluate_canonical_text


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def _write_minimal_canonical_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    gold_export_root = tmp_path / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    canonical_text = "Title\nSubtitle\n1 cup stock"
    (gold_export_root / "canonical_text.txt").write_text(canonical_text, encoding="utf-8")
    _write_jsonl(
        gold_export_root / "canonical_block_map.jsonl",
        [
            {"block_index": 0, "start_char": 0, "end_char": 5},
            {"block_index": 1, "start_char": 6, "end_char": 14},
            {"block_index": 2, "start_char": 15, "end_char": 26},
        ],
    )
    _write_jsonl(
        gold_export_root / "canonical_span_labels.jsonl",
        [
            {"span_id": "s0", "label": "RECIPE_TITLE", "start_char": 0, "end_char": 5},
            {"span_id": "s1", "label": "RECIPE_TITLE", "start_char": 6, "end_char": 14},
            {
                "span_id": "s2",
                "label": "INGREDIENT_LINE",
                "start_char": 15,
                "end_char": 26,
            },
        ],
    )
    (gold_export_root / "canonical_manifest.json").write_text(
        json.dumps({"schema_version": "canonical_gold.v1"}, sort_keys=True),
        encoding="utf-8",
    )

    stage_predictions_path = tmp_path / "stage_block_predictions.json"
    stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": "demo",
                "source_file": "demo.epub",
                "source_hash": "abc123",
                "block_count": 2,
                "block_labels": {"0": "RECIPE_TITLE", "1": "INGREDIENT_LINE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {"index": 0, "text": "Title\nSubtitle"},
                {"index": 1, "text": "1 cup stock"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return gold_export_root, stage_predictions_path, extracted_archive_path


def _write_boundary_cache_fixture(
    tmp_path: Path,
    *,
    fixture_name: str,
    block_texts: list[str],
) -> tuple[Path, Path, Path]:
    fixture_root = tmp_path / fixture_name
    gold_export_root = fixture_root / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    canonical_text = "Title\n\nSubtitle\n\n1 cup stock"
    (gold_export_root / "canonical_text.txt").write_text(canonical_text, encoding="utf-8")
    _write_jsonl(
        gold_export_root / "canonical_block_map.jsonl",
        [
            {"block_index": 0, "start_char": 0, "end_char": 5},
            {"block_index": 1, "start_char": 7, "end_char": 15},
            {"block_index": 2, "start_char": 17, "end_char": 28},
        ],
    )
    _write_jsonl(
        gold_export_root / "canonical_span_labels.jsonl",
        [
            {"span_id": "t", "label": "OTHER", "start_char": 0, "end_char": 5},
            {"span_id": "s", "label": "OTHER", "start_char": 7, "end_char": 15},
            {"span_id": "i", "label": "OTHER", "start_char": 17, "end_char": 28},
        ],
    )
    (gold_export_root / "canonical_manifest.json").write_text(
        json.dumps({"schema_version": "canonical_gold.v1"}, sort_keys=True),
        encoding="utf-8",
    )

    block_labels = {str(index): "OTHER" for index, _text in enumerate(block_texts)}
    stage_predictions_path = fixture_root / "stage_block_predictions.json"
    stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": fixture_name,
                "source_file": f"{fixture_name}.epub",
                "source_hash": fixture_name,
                "block_count": len(block_texts),
                "block_labels": block_labels,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_archive_path = fixture_root / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [{"index": index, "text": text} for index, text in enumerate(block_texts)],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return gold_export_root, stage_predictions_path, extracted_archive_path


def _cache_test_key_and_signatures() -> tuple[str, dict[str, Any]]:
    canonical_text = "title\nsubtitle\n1 cup stock"
    prediction_text = "title\nsubtitle\n1 cup stock"
    boundaries = [(0, 14), (15, 26)]
    canonical_hash = sha256_text(canonical_text)
    prediction_hash = sha256_text(prediction_text)
    boundaries_hash = hash_block_boundaries(boundaries)
    signatures = {
        "alignment_strategy": "legacy",
        "normalization_version": CANONICAL_ALIGNMENT_NORMALIZATION_VERSION,
        "repo_alignment_algo_version": CANONICAL_ALIGNMENT_ALGO_VERSION,
        "canonical_normalized_sha256": canonical_hash,
        "prediction_normalized_sha256": prediction_hash,
        "prediction_block_boundaries_sha256": boundaries_hash,
        "canonical_normalized_char_count": len(canonical_text),
        "prediction_normalized_char_count": len(prediction_text),
    }
    key = build_cache_file_key(
        alignment_strategy="legacy",
        canonical_normalized_sha256=canonical_hash,
        prediction_normalized_sha256=prediction_hash,
        prediction_block_boundaries_sha256=boundaries_hash,
        normalization_version=CANONICAL_ALIGNMENT_NORMALIZATION_VERSION,
        algo_version=CANONICAL_ALIGNMENT_ALGO_VERSION,
    )
    return key, signatures


def _cache_worker(
    *,
    cache_dir: str,
    cache_key: str,
    signatures: dict[str, Any],
    result_path: str,
    hold_seconds: float,
    ready_path: str | None = None,
    wait_for_ready_path: str | None = None,
) -> None:
    if wait_for_ready_path:
        wait_path = Path(wait_for_ready_path)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if wait_path.exists():
                break
            time.sleep(0.01)
        else:
            raise RuntimeError("timed out waiting for primary worker lock signal")

    cache = CanonicalAlignmentDiskCache(Path(cache_dir), wait_seconds=120, poll_seconds=0.01)
    computed = False
    lock_acquired = False
    cache_hit_before = False
    cache_hit_after = False

    entry, _error = cache.try_load(cache_key, expected_signatures=signatures)
    cache_hit_before = entry is not None
    if entry is None:
        with cache.lock_for_key(cache_key) as acquired:
            lock_acquired = bool(acquired)
            if ready_path:
                Path(ready_path).write_text("ready\n", encoding="utf-8")
            entry, _error = cache.try_load(cache_key, expected_signatures=signatures)
            if entry is not None:
                cache_hit_after = True
            elif acquired:
                if hold_seconds > 0:
                    time.sleep(hold_seconds)
                cache.write_atomic(
                    cache_key,
                    make_cache_entry(
                        alignment_strategy="legacy",
                        canonical_normalized_sha256=signatures["canonical_normalized_sha256"],
                        prediction_normalized_sha256=signatures["prediction_normalized_sha256"],
                        prediction_block_boundaries_sha256=signatures[
                            "prediction_block_boundaries_sha256"
                        ],
                        canonical_normalized_char_count=int(
                            signatures["canonical_normalized_char_count"]
                        ),
                        prediction_normalized_char_count=int(
                            signatures["prediction_normalized_char_count"]
                        ),
                        payload={"aligned_rows": [], "alignment": {"cached": True}},
                    ),
                )
                computed = True

    result = {
        "computed": computed,
        "lock_acquired": lock_acquired,
        "cache_hit_before": cache_hit_before,
        "cache_hit_after": cache_hit_after,
    }
    Path(result_path).write_text(json.dumps(result, sort_keys=True), encoding="utf-8")


def test_canonical_alignment_cache_hit_and_boundary_invalidation(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "alignment-cache"
    first_fixture = _write_minimal_canonical_fixture(tmp_path / "first-input")
    second_fixture = _write_boundary_cache_fixture(
        tmp_path,
        fixture_name="boundary-shifted",
        block_texts=["Title", "Subtitle", "1 cup stock"],
    )

    first_eval_dir = tmp_path / "first-eval"
    second_eval_dir = tmp_path / "second-eval"
    boundary_eval_dir = tmp_path / "boundary-eval"

    first_result = evaluate_canonical_text(
        gold_export_root=first_fixture[0],
        stage_predictions_json=first_fixture[1],
        extracted_blocks_json=first_fixture[2],
        out_dir=first_eval_dir,
        alignment_cache_dir=cache_dir,
    )
    second_result = evaluate_canonical_text(
        gold_export_root=first_fixture[0],
        stage_predictions_json=first_fixture[1],
        extracted_blocks_json=first_fixture[2],
        out_dir=second_eval_dir,
        alignment_cache_dir=cache_dir,
    )
    boundary_result = evaluate_canonical_text(
        gold_export_root=second_fixture[0],
        stage_predictions_json=second_fixture[1],
        extracted_blocks_json=second_fixture[2],
        out_dir=boundary_eval_dir,
        alignment_cache_dir=cache_dir,
    )

    first_report = first_result["report"]
    second_report = second_result["report"]
    boundary_report = boundary_result["report"]

    first_telemetry = first_report["evaluation_telemetry"]
    second_telemetry = second_report["evaluation_telemetry"]
    boundary_telemetry = boundary_report["evaluation_telemetry"]

    assert first_telemetry["alignment_cache_enabled"] is True
    assert first_telemetry["alignment_cache_hit"] is False
    assert second_telemetry["alignment_cache_enabled"] is True
    assert second_telemetry["alignment_cache_hit"] is True
    assert second_telemetry["subphases"]["alignment_sequence_matcher_seconds"] == pytest.approx(0.0)
    assert boundary_telemetry["alignment_cache_hit"] is False
    assert boundary_telemetry["alignment_cache_key"] != second_telemetry["alignment_cache_key"]

    assert first_report["overall_line_accuracy"] == pytest.approx(second_report["overall_line_accuracy"])
    assert first_report["macro_f1_excluding_other"] == pytest.approx(
        second_report["macro_f1_excluding_other"]
    )
    assert first_report["wrong_label_blocks"] == second_report["wrong_label_blocks"]
    assert first_report["missed_gold_blocks"] == second_report["missed_gold_blocks"]

    for artifact_name in (
        "missed_gold_lines.jsonl",
        "wrong_label_lines.jsonl",
        "aligned_prediction_blocks.jsonl",
        "unmatched_pred_blocks.jsonl",
        "alignment_gaps.jsonl",
    ):
        assert (first_eval_dir / artifact_name).read_text(encoding="utf-8") == (
            second_eval_dir / artifact_name
        ).read_text(encoding="utf-8")


def test_canonical_alignment_disk_cache_single_compute_under_concurrency(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key, signatures = _cache_test_key_and_signatures()
    ready_path = tmp_path / "primary-ready.signal"
    first_result_path = tmp_path / "worker1.json"
    second_result_path = tmp_path / "worker2.json"

    context = mp.get_context("spawn")
    worker1 = context.Process(
        target=_cache_worker,
        kwargs={
            "cache_dir": str(cache_dir),
            "cache_key": cache_key,
            "signatures": signatures,
            "result_path": str(first_result_path),
            "hold_seconds": 0.3,
            "ready_path": str(ready_path),
        },
    )
    worker2 = context.Process(
        target=_cache_worker,
        kwargs={
            "cache_dir": str(cache_dir),
            "cache_key": cache_key,
            "signatures": signatures,
            "result_path": str(second_result_path),
            "hold_seconds": 0.0,
            "wait_for_ready_path": str(ready_path),
        },
    )

    worker1.start()
    worker2.start()
    worker1.join(timeout=20)
    worker2.join(timeout=20)

    assert worker1.exitcode == 0
    assert worker2.exitcode == 0

    first_result = json.loads(first_result_path.read_text(encoding="utf-8"))
    second_result = json.loads(second_result_path.read_text(encoding="utf-8"))
    computed_count = int(bool(first_result["computed"])) + int(bool(second_result["computed"]))
    assert computed_count == 1
    assert any(
        (not bool(result["computed"]))
        and (bool(result["cache_hit_before"]) or bool(result["cache_hit_after"]))
        for result in (first_result, second_result)
    )

    cache = CanonicalAlignmentDiskCache(cache_dir)
    cached_entry, cache_error = cache.try_load(cache_key, expected_signatures=signatures)
    assert cache_error is None
    assert cached_entry is not None


def _pick_dead_pid() -> int:
    for candidate in (999_999, 888_888, 777_777):
        try:
            os.kill(candidate, 0)
        except ProcessLookupError:
            return candidate
        except PermissionError:
            continue
    return os.getpid() + 1_000_000


def test_canonical_alignment_disk_cache_lock_recovers_dead_owner_without_age_wait(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key, _signatures = _cache_test_key_and_signatures()
    cache = CanonicalAlignmentDiskCache(cache_dir, wait_seconds=5, poll_seconds=0.01)

    lock_path = cache.lock_path_for_key(cache_key)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    dead_pid = _pick_dead_pid()
    lock_path.write_text(f"pid={dead_pid} started_at={time.time():.6f}\n", encoding="utf-8")

    started = time.monotonic()
    with cache.lock_for_key(cache_key) as acquired:
        assert acquired is True
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert not lock_path.exists()
