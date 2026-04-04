from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from cookimport.bench.prediction_records import read_prediction_records
from cookimport.cli_support import (
    ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION,
    ALL_METHOD_EVAL_SIGNATURE_SCHEMA_VERSION,
    ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV,
    ALL_METHOD_PREDICTION_REUSE_CACHE_SCHEMA_VERSION,
    ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION,
    ALL_METHOD_PREDICTION_REUSE_LOCK_SUFFIX,
    ALL_METHOD_PREDICTION_REUSE_POLL_SECONDS,
    ALL_METHOD_PREDICTION_REUSE_WAIT_SECONDS,
    ALL_METHOD_SPLIT_CONVERT_INPUT_FIELDS,
    ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION,
    BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
    SINGLE_BOOK_SPLIT_CACHE_KEY_SCHEMA_VERSION,
    SINGLE_BOOK_SPLIT_CACHE_LOCK_SUFFIX,
    SINGLE_BOOK_SPLIT_CACHE_POLL_SECONDS,
    SINGLE_BOOK_SPLIT_CACHE_ROOT_ENV,
    SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION,
    SINGLE_BOOK_SPLIT_CACHE_WAIT_SECONDS,
    SINGLE_BOOK_SPLIT_CONVERT_INPUT_FIELDS,
    _fail,
)
from cookimport.config.prediction_identity import (
    build_all_method_prediction_identity_payload,
)
from cookimport.config.run_settings import RunSettings
from cookimport.core.reporting import compute_file_hash

from .bench_all_method_reporting import _report_count


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _normalize_single_book_split_cache_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "off", "none", "disabled", "false", "0"}:
        return "off"
    if normalized in {"auto", "on", "enabled", "true", "1"}:
        return "auto"
    _fail(
        f"Invalid single-book split-cache mode: {value!r}. "
        "Expected one of: off, auto."
    )
    return "off"


def _stable_json_sha256(payload: Any) -> str:
    canonical = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _all_method_prediction_reuse_key_payload(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> dict[str, Any]:
    return {
        "schema_version": ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION,
        "source_file": str(source_file),
        "prediction_identity": build_all_method_prediction_identity_payload(
            run_settings
        ),
    }


def _all_method_split_convert_input_key_payload(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> dict[str, Any]:
    run_config = run_settings.to_run_config_dict()
    selected_inputs = {
        key: run_config.get(key)
        for key in ALL_METHOD_SPLIT_CONVERT_INPUT_FIELDS
        if key in run_config
    }
    return {
        "schema_version": ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION,
        "source_file": str(source_file),
        "inputs": selected_inputs,
    }


def _build_all_method_prediction_reuse_key(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> str:
    return _stable_json_sha256(
        _all_method_prediction_reuse_key_payload(
            source_file=source_file,
            run_settings=run_settings,
        )
    )


def _build_all_method_split_convert_input_key(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> str:
    return _stable_json_sha256(
        _all_method_split_convert_input_key_payload(
            source_file=source_file,
            run_settings=run_settings,
        )
    )


def _single_book_split_cache_key_payload(
    *,
    source_file: Path,
    source_hash: str | None,
    pipeline: str | None,
    run_settings: RunSettings,
) -> dict[str, Any]:
    run_config = run_settings.to_run_config_dict()
    selected_inputs = {
        key: run_config.get(key)
        for key in SINGLE_BOOK_SPLIT_CONVERT_INPUT_FIELDS
        if key in run_config
    }
    normalized_pipeline = str(pipeline or "auto").strip().lower()
    return {
        "schema_version": SINGLE_BOOK_SPLIT_CACHE_KEY_SCHEMA_VERSION,
        "source_file": str(source_file),
        "source_hash": str(source_hash or "").strip() or None,
        "pipeline": normalized_pipeline or "auto",
        "inputs": selected_inputs,
    }


def _build_single_book_split_cache_key(
    *,
    source_file: Path,
    source_hash: str | None,
    pipeline: str | None,
    run_settings: RunSettings,
) -> str:
    return _stable_json_sha256(
        _single_book_split_cache_key_payload(
            source_file=source_file,
            source_hash=source_hash,
            pipeline=pipeline,
            run_settings=run_settings,
        )
    )


def _single_book_split_cache_entry_path(
    *,
    cache_root: Path,
    split_cache_key: str,
) -> Path:
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(split_cache_key or "").strip())
    if not safe_key:
        safe_key = "unknown"
    return cache_root / f"{safe_key}.json"


def _single_book_split_cache_lock_path(
    cache_path: Path,
) -> Path:
    return cache_path.with_suffix(
        f"{cache_path.suffix}{SINGLE_BOOK_SPLIT_CACHE_LOCK_SUFFIX}"
    )


def _load_single_book_split_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if (
        str(payload.get("schema_version") or "").strip()
        != SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION
    ):
        return None
    cached_key = str(payload.get("single_book_split_cache_key") or "").strip()
    if cached_key != str(expected_key or "").strip():
        return None
    conversion_payload = payload.get("conversion_result")
    if not isinstance(conversion_payload, dict):
        return None
    return payload


def _write_single_book_split_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _acquire_single_book_split_cache_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                    sort_keys=True,
                )
            )
    except Exception:  # noqa: BLE001
        try:
            lock_path.unlink()
        except OSError:
            pass
        return False
    return True


def _release_single_book_split_cache_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        return


def _wait_for_single_book_split_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
    lock_path: Path,
    wait_seconds: float = SINGLE_BOOK_SPLIT_CACHE_WAIT_SECONDS,
    poll_seconds: float = SINGLE_BOOK_SPLIT_CACHE_POLL_SECONDS,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    sleep_seconds = max(0.05, float(poll_seconds))
    while time.monotonic() < deadline:
        cached = _load_single_book_split_cache_entry(
            cache_path=cache_path,
            expected_key=expected_key,
        )
        if cached is not None:
            return cached
        if not lock_path.exists():
            break
        time.sleep(sleep_seconds)
    return _load_single_book_split_cache_entry(
        cache_path=cache_path,
        expected_key=expected_key,
    )


def _all_method_prediction_reuse_cache_entry_path(
    *,
    cache_dir: Path,
    prediction_reuse_key: str,
) -> Path:
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(prediction_reuse_key or "").strip())
    if not safe_key:
        safe_key = "unknown"
    return cache_dir / f"{safe_key}.json"


def _load_all_method_prediction_reuse_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if (
        str(payload.get("schema_version") or "").strip()
        != ALL_METHOD_PREDICTION_REUSE_CACHE_SCHEMA_VERSION
    ):
        return None
    cached_key = str(payload.get("prediction_reuse_key") or "").strip()
    if cached_key != str(expected_key):
        return None
    config_dir = str(payload.get("config_dir") or "").strip()
    source_eval_output_dir = str(payload.get("source_eval_output_dir") or "").strip()
    if not config_dir and not source_eval_output_dir:
        return None
    return payload


def _write_all_method_prediction_reuse_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _acquire_all_method_prediction_reuse_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                    sort_keys=True,
                )
            )
    except Exception:  # noqa: BLE001
        try:
            lock_path.unlink()
        except OSError:
            pass
        return False
    return True


def _release_all_method_prediction_reuse_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        return


def _wait_for_all_method_prediction_reuse_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
    lock_path: Path,
    wait_seconds: float = ALL_METHOD_PREDICTION_REUSE_WAIT_SECONDS,
    poll_seconds: float = ALL_METHOD_PREDICTION_REUSE_POLL_SECONDS,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    sleep_seconds = max(0.05, float(poll_seconds))
    while time.monotonic() < deadline:
        cached = _load_all_method_prediction_reuse_cache_entry(
            cache_path=cache_path,
            expected_key=expected_key,
        )
        if cached is not None:
            return cached
        if not lock_path.exists():
            break
        time.sleep(sleep_seconds)
    return _load_all_method_prediction_reuse_cache_entry(
        cache_path=cache_path,
        expected_key=expected_key,
    )


def _path_is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:  # noqa: BLE001
        return False


def _copytree_with_hardlink_fallback(
    *,
    source_dir: Path,
    target_dir: Path,
) -> None:
    try:
        shutil.copytree(source_dir, target_dir, copy_function=os.link)
    except Exception:  # noqa: BLE001
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)


def _copy_all_method_prediction_artifacts_for_reuse(
    *,
    source_config_dir: str,
    target_config_dir: str,
    root_output_dir: Path,
    scratch_root: Path,
    processed_output_root: Path,
    source_eval_output_dir: Path | None = None,
    source_scratch_output_dir: Path | None = None,
    source_processed_output_dir: Path | None = None,
) -> float | None:
    source_dir = str(source_config_dir or "").strip()
    target_dir = str(target_config_dir or "").strip()
    if not target_dir:
        return None
    if source_dir and source_dir == target_dir and source_eval_output_dir is None:
        return None

    if source_eval_output_dir is not None:
        resolved_source_eval_output_dir = Path(source_eval_output_dir).expanduser()
    else:
        if not source_dir:
            return None
        resolved_source_eval_output_dir = root_output_dir / source_dir
    target_eval_output_dir = root_output_dir / target_dir
    if resolved_source_eval_output_dir.resolve(
        strict=False
    ) == target_eval_output_dir.resolve(strict=False):
        return None
    source_prediction_records = resolved_source_eval_output_dir / "prediction-records.jsonl"
    if (
        not resolved_source_eval_output_dir.exists()
        or not resolved_source_eval_output_dir.is_dir()
        or not source_prediction_records.exists()
        or not source_prediction_records.is_file()
    ):
        return None

    if source_scratch_output_dir is not None:
        source_scratch_dir = Path(source_scratch_output_dir).expanduser()
    elif source_dir:
        source_scratch_dir = scratch_root / source_dir
    else:
        source_scratch_dir = Path("__missing_prediction_reuse_scratch__")
    target_scratch_dir = scratch_root / target_dir
    if source_processed_output_dir is not None:
        source_processed_dir = Path(source_processed_output_dir).expanduser()
    elif source_dir:
        source_processed_dir = processed_output_root / source_dir
    else:
        source_processed_dir = Path("__missing_prediction_reuse_processed__")
    target_processed_dir = processed_output_root / target_dir

    def _reset_tree(target_dir_path: Path) -> None:
        if target_dir_path.exists():
            shutil.rmtree(target_dir_path)

    copy_started = time.monotonic()
    _reset_tree(target_eval_output_dir)
    _reset_tree(target_scratch_dir)
    _reset_tree(target_processed_dir)
    _copytree_with_hardlink_fallback(
        source_dir=resolved_source_eval_output_dir,
        target_dir=target_eval_output_dir,
    )
    if source_scratch_dir.exists() and source_scratch_dir.is_dir():
        _copytree_with_hardlink_fallback(
            source_dir=source_scratch_dir,
            target_dir=target_scratch_dir,
        )
    if source_processed_dir.exists() and source_processed_dir.is_dir():
        _copytree_with_hardlink_fallback(
            source_dir=source_processed_dir,
            target_dir=target_processed_dir,
        )
    return max(0.0, time.monotonic() - copy_started)


def _all_method_eval_signature_prediction_rows(
    *,
    prediction_record_path: Path,
) -> list[dict[str, Any]]:
    prediction_records = list(read_prediction_records(prediction_record_path))
    if not prediction_records:
        raise ValueError(f"Prediction record file is empty: {prediction_record_path}")
    signature_rows: list[dict[str, Any]] = []
    for record in prediction_records:
        signature_rows.append(
            {
                "example_index": int(record.example_index),
                "prediction": _json_safe(record.prediction),
            }
        )
    signature_rows.sort(
        key=lambda row: (
            int(row.get("example_index", 0)),
            _stable_json_sha256(row.get("prediction", {})),
        )
    )
    return signature_rows


def _all_method_gold_fingerprint(gold_spans_path: Path) -> dict[str, Any]:
    fingerprint: dict[str, Any] = {"gold_spans_path": str(gold_spans_path)}
    if gold_spans_path.exists() and gold_spans_path.is_file():
        try:
            fingerprint["gold_spans_sha256"] = compute_file_hash(gold_spans_path)
        except Exception:  # noqa: BLE001
            fingerprint["gold_spans_sha256"] = None

    gold_export_root = gold_spans_path.parent
    for artifact_name in (
        "canonical_text.txt",
        "canonical_span_labels.jsonl",
        "canonical_manifest.json",
    ):
        artifact_path = gold_export_root / artifact_name
        if not artifact_path.exists() or not artifact_path.is_file():
            continue
        key = f"{artifact_name.replace('.', '_')}_sha256"
        try:
            fingerprint[key] = compute_file_hash(artifact_path)
        except Exception:  # noqa: BLE001
            fingerprint[key] = None
    return fingerprint


def _build_all_method_eval_signature(
    *,
    gold_spans_path: Path,
    prediction_record_path: Path,
    eval_mode: str,
    sequence_matcher: str,
    schema_version: str = ALL_METHOD_EVAL_SIGNATURE_SCHEMA_VERSION,
) -> str:
    signature_payload = {
        "schema_version": str(schema_version or ALL_METHOD_EVAL_SIGNATURE_SCHEMA_VERSION),
        "eval_mode": str(eval_mode or BENCHMARK_EVAL_MODE_CANONICAL_TEXT),
        "sequence_matcher": str(sequence_matcher or "dmp"),
        "gold_fingerprint": _all_method_gold_fingerprint(gold_spans_path),
        "prediction_rows": _all_method_eval_signature_prediction_rows(
            prediction_record_path=prediction_record_path
        ),
    }
    return _stable_json_sha256(signature_payload)


def _group_all_method_rows_by_eval_signature(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        eval_signature = str(row.get("eval_signature") or "").strip()
        if not eval_signature:
            continue
        grouped_rows[eval_signature].append(row)
    for eval_signature in list(grouped_rows):
        grouped_rows[eval_signature].sort(
            key=lambda row: _report_count(row.get("config_index"))
        )
    return dict(grouped_rows)


def _all_method_prediction_reuse_summary(
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    successful_rows = [
        row
        for row in rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    prediction_signatures_unique = len(
        {
            str(row.get("prediction_reuse_key") or "").strip()
            for row in successful_rows
            if str(row.get("prediction_reuse_key") or "").strip()
        }
    )
    prediction_runs_executed = sum(
        1
        for row in successful_rows
        if str(row.get("prediction_result_source") or "").strip().lower() == "executed"
    )
    prediction_results_reused_in_run = sum(
        1
        for row in successful_rows
        if str(row.get("prediction_result_source") or "").strip().lower()
        == "reused_in_run"
    )
    prediction_results_reused_cross_run = sum(
        1
        for row in successful_rows
        if str(row.get("prediction_result_source") or "").strip().lower()
        == "reused_cross_run"
    )

    split_convert_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in successful_rows:
        split_key = str(row.get("prediction_split_convert_input_key") or "").strip()
        if not split_key:
            continue
        split_convert_groups[split_key].append(row)
    split_convert_input_groups = len(split_convert_groups)
    split_convert_reuse_candidates = sum(
        max(0, len(group_rows) - 1) for group_rows in split_convert_groups.values()
    )
    split_convert_reuse_safe_candidates = 0
    split_convert_reuse_blocked_by_prediction_variance = 0
    for group_rows in split_convert_groups.values():
        if len(group_rows) <= 1:
            continue
        candidate_count = len(group_rows) - 1
        prediction_keys = {
            str(row.get("prediction_reuse_key") or "").strip()
            for row in group_rows
            if str(row.get("prediction_reuse_key") or "").strip()
        }
        if len(prediction_keys) <= 1:
            split_convert_reuse_safe_candidates += candidate_count
        else:
            split_convert_reuse_blocked_by_prediction_variance += candidate_count

    return {
        "prediction_signatures_unique": prediction_signatures_unique,
        "prediction_runs_executed": prediction_runs_executed,
        "prediction_results_reused_in_run": prediction_results_reused_in_run,
        "prediction_results_reused_cross_run": prediction_results_reused_cross_run,
        "split_convert_input_groups": split_convert_input_groups,
        "split_convert_reuse_candidates": split_convert_reuse_candidates,
        "split_convert_reuse_safe_candidates": split_convert_reuse_safe_candidates,
        "split_convert_reuse_blocked_by_prediction_variance": (
            split_convert_reuse_blocked_by_prediction_variance
        ),
    }


def _resolve_all_method_eval_signature_cache_dir(
    *,
    root_output_dir: Path,
    alignment_cache_dir: Path | None,
) -> Path:
    if alignment_cache_dir is None:
        return root_output_dir / ".cache" / "eval_signature_results"

    resolved_alignment_dir = alignment_cache_dir.expanduser()
    if resolved_alignment_dir.name == "canonical_alignment":
        return resolved_alignment_dir.parent / "eval_signature_results"
    if resolved_alignment_dir.parent.name == "canonical_alignment":
        return (
            resolved_alignment_dir.parent.parent
            / "eval_signature_results"
            / resolved_alignment_dir.name
        )
    return resolved_alignment_dir.parent / "eval_signature_results"


def _resolve_all_method_prediction_reuse_cache_dir(*, root_output_dir: Path) -> Path:
    env_override = str(
        os.getenv(ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV, "") or ""
    ).strip()
    if env_override:
        return Path(env_override).expanduser()
    return root_output_dir / ".prediction_reuse_cache"


def _load_all_method_eval_signature_cache_entry(
    *,
    cache_path: Path,
    expected_signature: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    schema_version = str(payload.get("schema_version") or "").strip()
    if schema_version != ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION:
        return None
    cached_signature = str(payload.get("eval_signature") or "").strip()
    if cached_signature != str(expected_signature):
        return None
    report_payload = payload.get("report")
    if not isinstance(report_payload, dict):
        return None
    return payload


def _write_all_method_eval_signature_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _materialize_all_method_cached_eval_outputs(
    *,
    eval_output_dir: Path,
    report_payload: dict[str, Any],
    report_md_text: str | None,
) -> tuple[Path, Path]:
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = eval_output_dir / "eval_report.json"
    report_md_path = eval_output_dir / "eval_report.md"
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    rendered_md = str(report_md_text or "").strip()
    if not rendered_md:
        rendered_md = (
            "# Benchmark Eval Report (Cached)\n\n"
            "Evaluation report reused from all-method signature cache."
    )
    report_md_path.write_text(rendered_md, encoding="utf-8")
    return report_json_path, report_md_path


def _resolve_all_method_prediction_record_path(
    *,
    root_output_dir: Path,
    row: dict[str, Any],
) -> Path | None:
    raw_value = str(row.get("prediction_record_jsonl") or "").strip()
    if not raw_value:
        return None
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = root_output_dir / candidate
    return candidate


def _resolve_single_book_split_cache_root(
    *,
    session_root: Path,
    split_cache_dir: Path | None,
) -> Path:
    if split_cache_dir is not None:
        return split_cache_dir.expanduser()
    env_override = str(os.getenv(SINGLE_BOOK_SPLIT_CACHE_ROOT_ENV, "") or "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return session_root / ".split-cache"
