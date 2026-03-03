from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable

from cookimport.epub_extractor_names import (
    EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV,
    EPUB_EXTRACTOR_CANONICAL_SET,
    epub_extractor_choices_for_help,
    is_policy_locked_epub_extractor_name,
    normalize_epub_extractor_name,
)
from cookimport.config.run_settings import (
    RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR,
    RunSettings,
    build_run_settings,
    compute_effective_workers,
)
from cookimport.core.progress_messages import (
    format_task_counter,
    format_worker_activity,
    format_worker_activity_reset,
)
from cookimport.core.executor_fallback import (
    resolve_process_thread_executor,
    shutdown_executor,
)
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.reporting import compute_file_hash, enrich_report_with_stats
from cookimport.core.scoring import summarize_recipe_likeness
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.parsing.tips import partition_tip_candidates
from cookimport.parsing.chunks import (
    chunks_from_non_recipe_blocks,
    chunks_from_topic_candidates,
)
from cookimport.parsing.tables import ExtractedTable, extract_and_annotate_tables
from cookimport.plugins import registry
from cookimport.labelstudio.archive import (
    build_extracted_archive,
    normalize_display_text,
    prepare_extracted_archive,
    prepared_archive_payload,
    prepared_archive_text,
)
from cookimport.labelstudio.freeform_tasks import (
    build_freeform_span_tasks,
    compute_freeform_task_coverage,
    resolve_segment_overlap_for_target,
    sample_freeform_tasks,
)
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    build_freeform_label_config,
    normalize_freeform_label,
)
from cookimport.labelstudio.prelabel import (
    CodexCliProvider,
    PRELABEL_GRANULARITY_BLOCK,
    annotation_labels,
    codex_account_summary,
    codex_cmd_with_model,
    codex_cmd_with_reasoning_effort,
    codex_model_from_cmd,
    codex_reasoning_effort_from_cmd,
    default_codex_cmd,
    default_codex_reasoning_effort,
    is_rate_limit_message,
    normalize_codex_reasoning_effort,
    normalize_prelabel_granularity,
    preflight_codex_model_access,
    prelabel_freeform_task,
    resolve_codex_model,
)
from cookimport.runs import RunManifest, RunSource, write_run_manifest
from cookimport.staging.writer import (
    OutputStats,
    write_chunk_outputs,
    write_draft_outputs,
    write_intermediate_outputs,
    write_raw_artifacts,
    write_report,
    write_section_outputs,
    write_stage_block_predictions,
    write_table_outputs,
    write_tip_outputs,
    write_topic_candidate_outputs,
)
from cookimport.staging.pdf_jobs import (
    plan_job_ranges,
    plan_pdf_page_ranges,
    reassign_recipe_ids,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - Windows fallback keeps behavior deterministic.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

SINGLE_OFFLINE_SPLIT_CACHE_SCHEMA_VERSION = "single_offline_split_cache.v1"
SINGLE_OFFLINE_SPLIT_CACHE_LOCK_SUFFIX = ".lock"
SINGLE_OFFLINE_SPLIT_CACHE_WAIT_SECONDS = 120.0
SINGLE_OFFLINE_SPLIT_CACHE_POLL_SECONDS = 0.25


def _normalize_single_offline_split_cache_mode(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "off", "none", "disabled", "false", "0"}:
        return "off"
    if normalized in {"auto", "on", "enabled", "true", "1"}:
        return "auto"
    raise ValueError(
        "Invalid single_offline_split_cache_mode. Expected one of: off, auto."
    )


def _single_offline_split_cache_entry_path(
    *,
    cache_root: Path,
    split_cache_key: str,
) -> Path:
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(split_cache_key or "").strip())
    if not safe_key:
        safe_key = "unknown"
    return cache_root / f"{safe_key}.json"


def _single_offline_split_cache_lock_path(cache_path: Path) -> Path:
    return cache_path.with_suffix(
        f"{cache_path.suffix}{SINGLE_OFFLINE_SPLIT_CACHE_LOCK_SUFFIX}"
    )


def _load_single_offline_split_cache_entry(
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
        != SINGLE_OFFLINE_SPLIT_CACHE_SCHEMA_VERSION
    ):
        return None
    cached_key = str(payload.get("single_offline_split_cache_key") or "").strip()
    if cached_key != str(expected_key or "").strip():
        return None
    conversion_payload = payload.get("conversion_result")
    if not isinstance(conversion_payload, dict):
        return None
    return payload


def _write_single_offline_split_cache_entry(
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


def _acquire_single_offline_split_cache_lock(lock_path: Path) -> bool:
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


def _release_single_offline_split_cache_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        return


def _wait_for_single_offline_split_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
    lock_path: Path,
    wait_seconds: float = SINGLE_OFFLINE_SPLIT_CACHE_WAIT_SECONDS,
    poll_seconds: float = SINGLE_OFFLINE_SPLIT_CACHE_POLL_SECONDS,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    sleep_seconds = max(0.05, float(poll_seconds))
    while time.monotonic() < deadline:
        cached = _load_single_offline_split_cache_entry(
            cache_path=cache_path,
            expected_key=expected_key,
        )
        if cached is not None:
            return cached
        if not lock_path.exists():
            break
        time.sleep(sleep_seconds)
    return _load_single_offline_split_cache_entry(
        cache_path=cache_path,
        expected_key=expected_key,
    )


def _notify_progress_callback(
    progress_callback: Callable[[str], None] | None,
    message: str,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ignoring progress callback failure: %s", exc)


def _notify_scheduler_event_callback(
    scheduler_event_callback: Callable[[dict[str, Any]], None] | None,
    *,
    event: str,
    **payload: Any,
) -> None:
    if scheduler_event_callback is None:
        return
    event_name = str(event or "").strip()
    if not event_name:
        return
    event_payload: dict[str, Any] = {
        "event": event_name,
        "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
    }
    event_payload.update(payload)
    try:
        scheduler_event_callback(event_payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ignoring scheduler event callback failure: %s", exc)


def _task_progress_message(phase: str, current: int, total: int) -> str:
    return format_task_counter(phase, current, total, noun="task")


def _format_prelabel_prompt_log_entry_markdown(payload: dict[str, Any]) -> str:
    task_index = payload.get("task_index")
    task_total = payload.get("task_total")
    try:
        task_label = f"{int(task_index)}/{int(task_total)}"
    except (TypeError, ValueError):
        task_label = "?"
    segment_id = str(payload.get("segment_id") or "<unknown>")
    included_with_prompt = payload.get("included_with_prompt")
    if not isinstance(included_with_prompt, dict):
        included_with_prompt = {}
    included_json = json.dumps(
        included_with_prompt,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    prompt_text = str(payload.get("prompt") or "")
    if not prompt_text:
        prompt_text = "(empty prompt)"
    description = str(payload.get("included_with_prompt_description") or "").strip()
    if not description:
        description = "No additional prompt context description provided."
    lines = [
        f"## Task {task_label} - `{segment_id}`",
        "",
        f"- Logged at (UTC): `{payload.get('logged_at') or ''}`",
        f"- Task scope: `{payload.get('task_scope') or ''}`",
        f"- Granularity: `{payload.get('granularity') or ''}`",
        f"- Prompt template: `{payload.get('prompt_template') or ''}`",
        f"- Prompt hash: `{payload.get('prompt_hash') or ''}`",
        f"- Codex cmd: `{payload.get('codex_cmd') or ''}`",
        f"- Codex model: `{payload.get('codex_model') or ''}`",
        f"- Codex reasoning effort: `{payload.get('codex_reasoning_effort') or ''}`",
        f"- Codex account: `{payload.get('codex_account') or ''}`",
        f"- Source file: `{payload.get('source_file') or ''}`",
        "",
        "### What Else Was Included",
        "",
        description,
        "",
        "```json",
        included_json,
        "```",
        "",
        "### Prompt",
        "",
        "````text",
        prompt_text,
        "````",
        "",
    ]
    return "\n".join(lines)


def _coerce_bool(value: bool | str | None, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_unstructured_html_parser_version(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"v1", "v2"}:
        raise ValueError(
            "Invalid epub_unstructured_html_parser_version. "
            "Expected one of: v1, v2."
        )
    return normalized


def _normalize_unstructured_preprocess_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"none", "br_split_v1", "semantic_v1"}:
        raise ValueError(
            "Invalid epub_unstructured_preprocess_mode. "
            "Expected one of: none, br_split_v1, semantic_v1."
        )
    return normalized


def _normalize_epub_extractor(value: str) -> str:
    normalized = normalize_epub_extractor_name(value)
    if normalized not in EPUB_EXTRACTOR_CANONICAL_SET:
        raise ValueError(
            "Invalid epub_extractor. "
            f"Expected one of: {epub_extractor_choices_for_help()}."
        )
    if is_policy_locked_epub_extractor_name(normalized):
        raise ValueError(
            f"epub_extractor {normalized!r} is policy-locked off for now "
            f"(set {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 to temporarily re-enable)."
        )
    return normalized


def _normalize_llm_recipe_pipeline(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "off":
        return normalized
    if normalized == "codex-farm-3pass-v1":
        return normalized
    raise ValueError(
        f"Invalid llm_recipe_pipeline. {RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR}"
    )


def _normalize_codex_farm_failure_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"fail", "fallback"}:
        raise ValueError(
            "Invalid codex_farm_failure_mode. Expected one of: fail, fallback."
        )
    return normalized


def _normalize_codex_farm_recipe_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "extract", "default"}:
        return "extract"
    if normalized in {"benchmark", "line-label", "line-labels"}:
        return "benchmark"
    raise ValueError(
        "Invalid codex_farm_recipe_mode. Expected one of: extract, benchmark."
    )


def _normalize_codex_farm_pipeline_id(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Invalid {field_name}. Expected a non-empty pipeline id.")
    return normalized


@contextmanager
def _temporary_epub_runtime_env(
    *,
    extractor: str,
    html_parser_version: str,
    skip_headers_footers: bool,
    preprocess_mode: str,
) -> Iterable[None]:
    keys = (
        "C3IMP_EPUB_EXTRACTOR",
        "C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION",
        "C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS",
        "C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE",
    )
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["C3IMP_EPUB_EXTRACTOR"] = extractor
    os.environ["C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION"] = html_parser_version
    os.environ["C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS"] = (
        "true" if skip_headers_footers else "false"
    )
    os.environ["C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE"] = preprocess_mode
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _normalize_split_phase_slots(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


def _try_acquire_file_lock_nonblocking(handle: Any) -> bool:
    if fcntl is None:
        return True
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _release_file_lock(handle: Any) -> None:
    if fcntl is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        return


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timing_payload(
    *,
    total_seconds: float,
    prediction_seconds: float,
    parsing_seconds: float | None = None,
    writing_seconds: float | None = None,
    ocr_seconds: float | None = None,
    artifact_write_seconds: float | None = None,
    checkpoints: dict[str, float] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "total_seconds": float(max(0.0, total_seconds)),
        "prediction_seconds": float(max(0.0, prediction_seconds)),
        "checkpoints": {},
    }
    if parsing_seconds is not None:
        payload["parsing_seconds"] = float(max(0.0, parsing_seconds))
    if writing_seconds is not None:
        payload["writing_seconds"] = float(max(0.0, writing_seconds))
    if ocr_seconds is not None:
        payload["ocr_seconds"] = float(max(0.0, ocr_seconds))
    if artifact_write_seconds is not None:
        payload["artifact_write_seconds"] = float(max(0.0, artifact_write_seconds))

    checkpoint_map: dict[str, float] = {}
    if checkpoints:
        for key, value in checkpoints.items():
            numeric = _safe_float(value)
            if numeric is None or numeric < 0:
                continue
            checkpoint_map[str(key)] = float(numeric)
    payload["checkpoints"] = checkpoint_map
    return payload


def _write_processed_report_timing_best_effort(
    *,
    processed_report_path: Path | None,
    timing: dict[str, Any] | None,
    notify: Callable[[str], None] | None = None,
) -> None:
    if processed_report_path is None or timing is None:
        return
    if not processed_report_path.exists() or not processed_report_path.is_file():
        return

    try:
        payload = json.loads(processed_report_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _notify_progress_callback(
            notify,
            f"Warning: failed reading processed report timing from {processed_report_path}: {exc}",
        )
        return
    if not isinstance(payload, dict):
        return

    existing_timing = payload.get("timing")
    existing_timing_dict = existing_timing if isinstance(existing_timing, dict) else {}
    existing_checkpoints = existing_timing_dict.get("checkpoints")
    checkpoint_payload = (
        dict(existing_checkpoints) if isinstance(existing_checkpoints, dict) else {}
    )
    raw_checkpoints = timing.get("checkpoints")
    if isinstance(raw_checkpoints, dict):
        for key, value in raw_checkpoints.items():
            numeric = _safe_float(value)
            if numeric is None:
                continue
            checkpoint_payload[str(key)] = float(max(0.0, numeric))

    parsing_seconds = _safe_float(timing.get("parsing_seconds"))
    if parsing_seconds is None:
        parsing_seconds = _safe_float(existing_timing_dict.get("parsing_seconds"))
    if parsing_seconds is None:
        parsing_seconds = _safe_float(checkpoint_payload.get("conversion_seconds"))

    writing_seconds = _safe_float(timing.get("writing_seconds"))
    if writing_seconds is None:
        writing_seconds = _safe_float(existing_timing_dict.get("writing_seconds"))
    if writing_seconds is None:
        writing_seconds = _safe_float(
            checkpoint_payload.get("processed_output_write_seconds")
        )

    ocr_seconds = _safe_float(timing.get("ocr_seconds"))
    if ocr_seconds is None:
        ocr_seconds = _safe_float(existing_timing_dict.get("ocr_seconds"))

    prediction_seconds = _safe_float(timing.get("prediction_seconds"))
    total_seconds = _safe_float(timing.get("total_seconds"))
    if total_seconds is None:
        total_seconds = _safe_float(existing_timing_dict.get("total_seconds"))
    if total_seconds is None and prediction_seconds is not None:
        total_seconds = prediction_seconds

    merged_timing: dict[str, Any] = {
        "total_seconds": float(max(0.0, total_seconds or 0.0)),
        "parsing_seconds": float(max(0.0, parsing_seconds or 0.0)),
        "writing_seconds": float(max(0.0, writing_seconds or 0.0)),
        "ocr_seconds": float(max(0.0, ocr_seconds or 0.0)),
        "checkpoints": checkpoint_payload,
    }
    if prediction_seconds is not None:
        merged_timing["prediction_seconds"] = float(max(0.0, prediction_seconds))
    artifact_write_seconds = _safe_float(timing.get("artifact_write_seconds"))
    if artifact_write_seconds is not None:
        merged_timing["artifact_write_seconds"] = float(
            max(0.0, artifact_write_seconds)
        )

    payload["timing"] = merged_timing
    try:
        processed_report_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        _notify_progress_callback(
            notify,
            f"Warning: failed writing processed report timing to {processed_report_path}: {exc}",
        )


def _emit_split_phase_status(
    *,
    notify: Callable[[str], None] | None,
    message: str,
) -> None:
    cleaned = str(message or "").strip()
    if not cleaned:
        return
    if notify is not None:
        _notify_progress_callback(notify, cleaned)
        return
    print(cleaned)


@contextmanager
def _acquire_split_phase_slot(
    *,
    slots: int,
    gate_dir: Path | str | None,
    notify: Callable[[str], None] | None,
    status_label: str | None,
) -> Iterable[tuple[int, int] | None]:
    normalized_slots = _normalize_split_phase_slots(slots)
    if normalized_slots is None:
        yield None
        return

    slot_total = max(1, normalized_slots)
    slot_label = str(status_label or "").strip()
    gate_root = Path(gate_dir) if gate_dir is not None else None
    if gate_root is None:
        yield (1, slot_total)
        return
    gate_root.mkdir(parents=True, exist_ok=True)

    def _status(message: str) -> str:
        if slot_label:
            return f"{slot_label} {message}"
        return message

    waited = False
    while True:
        for slot_index in range(1, slot_total + 1):
            slot_path = gate_root / f"split_slot_{slot_index:02d}.lock"
            handle = slot_path.open("a+", encoding="utf-8")
            if not _try_acquire_file_lock_nonblocking(handle):
                handle.close()
                continue

            _emit_split_phase_status(
                notify=notify,
                message=_status(f"acquired split slot {slot_index}/{slot_total}."),
            )
            try:
                yield (slot_index, slot_total)
            finally:
                _release_file_lock(handle)
                handle.close()
                _emit_split_phase_status(
                    notify=notify,
                    message=_status(f"released split slot {slot_index}/{slot_total}."),
                )
            return

        if not waited:
            _emit_split_phase_status(
                notify=notify,
                message=_status("waiting for split slot..."),
            )
            waited = True
        time.sleep(0.2)


def _slugify_name(name: str) -> str:
    import re

    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug or "unknown"


def _dedupe_project_name(base_name: str, existing_titles: set[str]) -> str:
    candidate = base_name
    suffix = 1
    while candidate in existing_titles:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    return candidate


def _resolve_project_name(path: Path, project_name: str | None, client: LabelStudioClient) -> str:
    if project_name:
        return project_name

    base_name = path.stem.strip() or _slugify_name(path.stem)
    existing_titles = {
        str(project.get("title", ""))
        for project in client.list_projects()
        if isinstance(project, dict) and project.get("title")
    }
    return _dedupe_project_name(base_name, existing_titles)


def _find_latest_manifest(output_root: Path, project_name: str) -> Path | None:
    manifests = list(output_root.glob("**/labelstudio/**/manifest.json"))
    candidates = []
    for path in manifests:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("project_name") == project_name:
            candidates.append((path.stat().st_mtime, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _task_id_key() -> str:
    return "segment_id"


def _task_id_value(task: dict[str, Any]) -> str | None:
    key = _task_id_key()
    data = task.get("data")
    if not isinstance(data, dict):
        return None
    value = data.get(key)
    if not value:
        return None
    return str(value)


def _normalize_prelabel_upload_as(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"annotations", "predictions"}:
        raise ValueError(
            "prelabel_upload_as must be one of: annotations, predictions"
        )
    return normalized


def _strip_task_annotations(task: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(task)
    cleaned.pop("annotations", None)
    cleaned.pop("predictions", None)
    return cleaned


def _task_annotation_pairs_for_upload(
    tasks: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    pairs: list[tuple[str, dict[str, Any]]] = []
    for task in tasks:
        task_id = _task_id_value(task)
        if not task_id:
            continue
        annotations = task.get("annotations")
        if not isinstance(annotations, list) or not annotations:
            continue
        annotation = annotations[0]
        if not isinstance(annotation, dict):
            continue
        pairs.append((task_id, annotation))
    return pairs


def _load_task_ids_from_jsonl(path: Path, key: str) -> set[str]:
    task_ids: set[str] = set()
    if not path.exists():
        return task_ids
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        value = data.get(key)
        if value:
            task_ids.add(str(value))
    return task_ids


def _annotations_to_predictions(task: dict[str, Any]) -> dict[str, Any]:
    converted = _strip_task_annotations(task)
    annotations = task.get("annotations")
    if not isinstance(annotations, list) or not annotations:
        return converted
    annotation = annotations[0]
    if not isinstance(annotation, dict):
        return converted
    result = annotation.get("result")
    if not isinstance(result, list) or not result:
        return converted
    prediction = {
        "model_version": "cookimport-prelabel",
        "score": 1.0,
        "result": result,
    }
    meta = annotation.get("meta")
    if isinstance(meta, dict):
        prediction["meta"] = meta
    converted["predictions"] = [prediction]
    return converted


def _build_prelabel_provider(
    *,
    prelabel_provider: str,
    codex_cmd: str | None,
    codex_model: str | None,
    codex_reasoning_effort: str | None,
    prelabel_timeout_seconds: int,
    prelabel_cache_dir: Path | None,
    prelabel_track_token_usage: bool,
) -> CodexCliProvider:
    normalized_provider = prelabel_provider.strip().lower()
    if normalized_provider != "codex-cli":
        raise ValueError("prelabel_provider must be 'codex-cli'")
    base_cmd = (codex_cmd or default_codex_cmd()).strip()
    normalized_effort = normalize_codex_reasoning_effort(codex_reasoning_effort)
    resolved_model = resolve_codex_model(codex_model, cmd=base_cmd)
    resolved_cmd = codex_cmd_with_model(base_cmd, resolved_model)
    resolved_cmd = codex_cmd_with_reasoning_effort(resolved_cmd, normalized_effort)
    effective_model = codex_model_from_cmd(resolved_cmd) or resolved_model
    return CodexCliProvider(
        cmd=resolved_cmd,
        timeout_s=prelabel_timeout_seconds,
        cache_dir=prelabel_cache_dir,
        track_usage=prelabel_track_token_usage,
        model=effective_model,
    )


def _path_for_manifest(run_root: Path, path_like: Path | str | None) -> str | None:
    if path_like is None:
        return None
    candidate = Path(path_like)
    try:
        return str(candidate.relative_to(run_root))
    except ValueError:
        return str(candidate)


def _write_manifest_best_effort(
    run_root: Path,
    manifest: RunManifest,
    *,
    notify: Callable[[str], None] | None = None,
) -> None:
    try:
        write_run_manifest(run_root, manifest)
    except Exception as exc:  # noqa: BLE001
        message = f"Warning: failed to write run_manifest.json in {run_root}: {exc}"
        if notify is not None:
            notify(message)
        logger.warning(message)


def _write_processed_outputs(
    *,
    result: ConversionResult,
    path: Path,
    run_dt: dt.datetime,
    output_root: Path,
    importer_name: str,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    schemaorg_overrides_by_recipe_id: dict[str, dict[str, Any]] | None = None,
    draft_overrides_by_recipe_id: dict[str, dict[str, Any]] | None = None,
    llm_codex_farm: dict[str, Any] | None = None,
    knowledge_snippets_path: Path | None = None,
    write_markdown: bool = True,
) -> Path:
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    run_root = output_root / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    workbook_name = path.stem
    intermediate_dir = run_root / "intermediate drafts" / workbook_name
    final_dir = run_root / "final drafts" / workbook_name
    tips_dir = run_root / "tips" / workbook_name

    extracted_tables: list[ExtractedTable] = []
    table_extraction_enabled = (
        str((run_config or {}).get("table_extraction", "off")).strip().lower() == "on"
    )
    if table_extraction_enabled and result.non_recipe_blocks:
        source_hash = "unknown"
        for artifact in result.raw_artifacts:
            if artifact.source_hash:
                source_hash = str(artifact.source_hash)
                break
        if source_hash == "unknown":
            try:
                source_hash = compute_file_hash(path)
            except Exception:
                source_hash = "unknown"
        extracted_tables = extract_and_annotate_tables(
            result.non_recipe_blocks,
            source_hash=source_hash,
        )

    if result.non_recipe_blocks:
        result.chunks = chunks_from_non_recipe_blocks(result.non_recipe_blocks)
    elif result.topic_candidates:
        result.chunks = chunks_from_topic_candidates(result.topic_candidates)

    if result.report is None:
        result.report = ConversionReport()
    result.report.importer_name = importer_name
    if run_config is not None:
        result.report.run_config = dict(run_config)
    result.report.run_config_hash = run_config_hash
    result.report.run_config_summary = run_config_summary
    result.report.llm_codex_farm = llm_codex_farm
    result.report.run_timestamp = run_dt.isoformat(timespec="seconds")
    enrich_report_with_stats(result.report, result, path)

    output_stats = OutputStats(run_root)
    write_intermediate_outputs(
        result,
        intermediate_dir,
        output_stats=output_stats,
        schemaorg_overrides_by_recipe_id=schemaorg_overrides_by_recipe_id,
        instruction_step_options=run_config,
    )
    write_draft_outputs(
        result,
        final_dir,
        output_stats=output_stats,
        draft_overrides_by_recipe_id=draft_overrides_by_recipe_id,
        ingredient_parser_options=run_config,
        instruction_step_options=run_config,
    )
    write_section_outputs(
        run_root,
        workbook_name,
        result.recipes,
        output_stats=output_stats,
        write_markdown=write_markdown,
        instruction_step_options=run_config,
    )
    write_tip_outputs(
        result,
        tips_dir,
        output_stats=output_stats,
        write_markdown=write_markdown,
    )
    write_topic_candidate_outputs(
        result,
        tips_dir,
        output_stats=output_stats,
        write_markdown=write_markdown,
    )
    if table_extraction_enabled:
        write_table_outputs(
            run_root,
            workbook_name,
            extracted_tables,
            source_file=path.name,
            output_stats=output_stats,
            write_markdown=write_markdown,
        )
    if result.chunks:
        chunks_dir = run_root / "chunks" / workbook_name
        write_chunk_outputs(
            result.chunks,
            chunks_dir,
            output_stats=output_stats,
            write_markdown=write_markdown,
        )
    write_raw_artifacts(result, run_root, output_stats=output_stats)
    write_stage_block_predictions(
        results=result,
        run_root=run_root,
        workbook_slug=workbook_name,
        source_file=str(path),
        knowledge_snippets_path=knowledge_snippets_path,
        output_stats=output_stats,
    )

    if output_stats.file_counts:
        result.report.output_stats = output_stats.to_report()
    write_report(result.report, run_root, workbook_name)
    return run_root


def _resolve_knowledge_snippets_path(llm_report: dict[str, Any] | None) -> Path | None:
    if not isinstance(llm_report, dict):
        return None
    knowledge_payload = llm_report.get("knowledge")
    if not isinstance(knowledge_payload, dict):
        return None
    paths_payload = knowledge_payload.get("paths")
    if not isinstance(paths_payload, dict):
        return None
    snippets_path = paths_payload.get("snippets_path")
    if not snippets_path:
        return None
    try:
        candidate = Path(str(snippets_path))
    except Exception:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _resolve_pdf_page_count(path: Path) -> int | None:
    importer = registry.get_importer("pdf")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    page_count = inspection.sheets[0].page_count
    if page_count is None:
        return None
    try:
        return int(page_count)
    except (TypeError, ValueError):
        return None


def _resolve_epub_spine_count(path: Path) -> int | None:
    importer = registry.get_importer("epub")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    spine_count = inspection.sheets[0].spine_count
    if spine_count is None:
        return None
    try:
        return int(spine_count)
    except (TypeError, ValueError):
        return None


def _plan_parallel_convert_jobs(
    path: Path,
    *,
    workers: int,
    pdf_split_workers: int,
    epub_split_workers: int,
    pdf_pages_per_job: int,
    epub_spine_items_per_job: int,
    epub_extractor: str = "unstructured",
) -> list[dict[str, int | None]]:
    suffix = path.suffix.lower()
    selected_epub_extractor = epub_extractor.strip().lower()
    if suffix == ".pdf" and pdf_split_workers > 1 and pdf_pages_per_job > 0:
        page_count = _resolve_pdf_page_count(path)
        if page_count:
            ranges = plan_pdf_page_ranges(
                page_count,
                pdf_split_workers,
                pdf_pages_per_job,
            )
            if len(ranges) > 1:
                return [
                    {
                        "job_index": idx,
                        "start_page": start,
                        "end_page": end,
                        "start_spine": None,
                        "end_spine": None,
                    }
                    for idx, (start, end) in enumerate(ranges)
                ]
    if (
        suffix == ".epub"
        and selected_epub_extractor != "markitdown"
        and epub_split_workers > 1
        and epub_spine_items_per_job > 0
    ):
        spine_count = _resolve_epub_spine_count(path)
        if spine_count:
            ranges = plan_job_ranges(
                spine_count,
                epub_split_workers,
                epub_spine_items_per_job,
            )
            if len(ranges) > 1:
                return [
                    {
                        "job_index": idx,
                        "start_page": None,
                        "end_page": None,
                        "start_spine": start,
                        "end_spine": end,
                    }
                    for idx, (start, end) in enumerate(ranges)
                ]
    return [
        {
            "job_index": 0,
            "start_page": None,
            "end_page": None,
            "start_spine": None,
            "end_spine": None,
        }
    ]


def _parallel_convert_worker(
    path: Path,
    pipeline: str,
    run_mapping: Any = None,
    *,
    run_config: dict[str, Any] | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
    start_spine: int | None = None,
    end_spine: int | None = None,
) -> tuple[str, ConversionResult]:
    if pipeline == "auto":
        importer, score = registry.best_importer_for_path(path)
    else:
        importer = registry.get_importer(pipeline)
        score = 1.0 if importer else 0.0
    if importer is None or score <= 0:
        raise RuntimeError("No importer available for this path.")

    kwargs: dict[str, Any] = {"progress_callback": None}
    if start_page is not None or end_page is not None:
        kwargs["start_page"] = start_page
        kwargs["end_page"] = end_page
    if start_spine is not None or end_spine is not None:
        kwargs["start_spine"] = start_spine
        kwargs["end_spine"] = end_spine

    run_settings = RunSettings.from_dict(
        run_config,
        warn_context="labelstudio split run config",
    )
    kwargs["run_settings"] = run_settings
    result = importer.convert(path, run_mapping, **kwargs)
    return importer.name, result


def _job_sort_key(job: dict[str, Any]) -> tuple[int, int]:
    if job.get("start_page") is not None:
        return (0, int(job.get("start_page") or 0))
    if job.get("start_spine") is not None:
        return (1, int(job.get("start_spine") or 0))
    return (2, int(job.get("job_index") or 0))


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _offset_mapping_int(payload: dict[str, Any], key: str, offset: int) -> None:
    value = _coerce_int(payload.get(key))
    if value is None:
        return
    payload[key] = value + offset


def _offset_location_fields(location: dict[str, Any], offset: int) -> None:
    for key in (
        "start_block",
        "end_block",
        "block_index",
        "startBlock",
        "endBlock",
        "blockIndex",
        "tip_block_index",
        "tipBlockIndex",
    ):
        _offset_mapping_int(location, key, offset)


def _offset_provenance_block_indices(provenance: dict[str, Any], offset: int) -> None:
    location = provenance.get("location")
    if isinstance(location, dict):
        _offset_location_fields(location, offset)

    atom = provenance.get("atom")
    if isinstance(atom, dict):
        _offset_mapping_int(atom, "block_index", offset)
        _offset_mapping_int(atom, "blockIndex", offset)

    _offset_mapping_int(provenance, "tip_block_index", offset)
    _offset_mapping_int(provenance, "tipBlockIndex", offset)


def _offset_result_block_indices(result: ConversionResult, offset: int) -> None:
    if offset <= 0:
        return

    for recipe in result.recipes:
        if isinstance(recipe.provenance, dict):
            _offset_provenance_block_indices(recipe.provenance, offset)

    for tip in result.tip_candidates:
        if isinstance(tip.provenance, dict):
            _offset_provenance_block_indices(tip.provenance, offset)

    for topic in result.topic_candidates:
        if isinstance(topic.provenance, dict):
            _offset_provenance_block_indices(topic.provenance, offset)

    for block in result.non_recipe_blocks:
        if isinstance(block, dict):
            _offset_mapping_int(block, "index", offset)
            location = block.get("location")
            if isinstance(location, dict):
                _offset_location_fields(location, offset)

    for artifact in result.raw_artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        _offset_location_fields(content, offset)
        blocks = content.get("blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                _offset_mapping_int(block, "index", offset)
                _offset_location_fields(block, offset)


def _extract_result_block_count(result: ConversionResult) -> int:
    for artifact in result.raw_artifacts:
        metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
        if metadata.get("artifact_type") != "extracted_blocks":
            continue
        content = artifact.content
        if not isinstance(content, dict):
            continue
        block_count = _coerce_int(content.get("block_count"))
        if block_count is not None and block_count > 0:
            return block_count
        blocks = content.get("blocks")
        if isinstance(blocks, list) and blocks:
            return len(blocks)

    max_block_index = -1

    for artifact in result.raw_artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        blocks = content.get("blocks")
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            index = _coerce_int(block.get("index"))
            if index is not None:
                max_block_index = max(max_block_index, index)

    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        location = provenance.get("location")
        if not isinstance(location, dict):
            continue
        start = _coerce_int(location.get("start_block"))
        end = _coerce_int(location.get("end_block"))
        if start is not None:
            max_block_index = max(max_block_index, start)
        if end is not None:
            max_block_index = max(max_block_index, end)

    for block in result.non_recipe_blocks:
        if not isinstance(block, dict):
            continue
        index = _coerce_int(block.get("index"))
        if index is not None:
            max_block_index = max(max_block_index, index)

    return max_block_index + 1 if max_block_index >= 0 else 0


def _merge_parallel_results(
    path: Path,
    importer_name: str,
    job_results: list[dict[str, Any]],
) -> ConversionResult:
    ordered_jobs = sorted(job_results, key=_job_sort_key)
    merged_recipes: list[Any] = []
    merged_tip_candidates: list[Any] = []
    merged_topic_candidates: list[Any] = []
    merged_non_recipe_blocks: list[Any] = []
    merged_raw_artifacts: list[Any] = []
    warnings: list[str] = []
    block_offset = 0
    rejected_candidate_count = 0

    for job in ordered_jobs:
        result = job["result"]
        _offset_result_block_indices(result, block_offset)
        merged_recipes.extend(result.recipes)
        merged_tip_candidates.extend(result.tip_candidates)
        merged_topic_candidates.extend(result.topic_candidates)
        merged_non_recipe_blocks.extend(result.non_recipe_blocks)
        merged_raw_artifacts.extend(result.raw_artifacts)
        block_offset += _extract_result_block_count(result)
        if result.report and result.report.warnings:
            warnings.extend(result.report.warnings)
        if result.report and result.report.errors:
            warnings.extend(
                f"Job {job.get('job_index')}: {error}" for error in result.report.errors
            )
        if result.report and isinstance(result.report.recipe_likeness, dict):
            rejected_value = result.report.recipe_likeness.get(
                "rejectedCandidateCount"
            )
            if rejected_value is None:
                counts_payload = result.report.recipe_likeness.get("counts")
                if isinstance(counts_payload, dict):
                    rejected_value = counts_payload.get("reject")
            try:
                rejected_candidate_count += max(0, int(rejected_value or 0))
            except (TypeError, ValueError):
                pass

    file_hash = compute_file_hash(path)
    sorted_recipes, _ = reassign_recipe_ids(
        merged_recipes,
        merged_tip_candidates,
        file_hash=file_hash,
        importer_name=importer_name,
    )
    tips, _, _ = partition_tip_candidates(merged_tip_candidates)
    report = ConversionReport(warnings=warnings)
    recipe_likeness_results = [
        candidate.recipe_likeness
        for candidate in sorted_recipes
        if candidate.recipe_likeness is not None
    ]
    recipe_likeness_summary = summarize_recipe_likeness(
        recipe_likeness_results,
        rejected_candidate_count,
    )
    counts_payload = recipe_likeness_summary.get("counts")
    if isinstance(counts_payload, dict):
        counts_payload["reject"] = rejected_candidate_count
    recipe_likeness_summary["totalCandidates"] = (
        len(recipe_likeness_results) + rejected_candidate_count
    )
    report.recipe_likeness = recipe_likeness_summary

    return ConversionResult(
        recipes=sorted_recipes,
        tips=tips,
        tip_candidates=merged_tip_candidates,
        topic_candidates=merged_topic_candidates,
        non_recipe_blocks=merged_non_recipe_blocks,
        raw_artifacts=merged_raw_artifacts,
        report=report,
        workbook=path.stem,
        workbook_path=str(path),
    )


def generate_pred_run_artifacts(
    *,
    path: Path,
    output_dir: Path,
    pipeline: str = "auto",
    segment_blocks: int = 40,
    segment_overlap: int = 5,
    segment_focus_blocks: int | None = None,
    target_task_count: int | None = None,
    limit: int | None = None,
    sample: int | None = None,
    workers: int = 1,
    pdf_split_workers: int = 1,
    epub_split_workers: int = 1,
    pdf_pages_per_job: int = 50,
    epub_spine_items_per_job: int = 10,
    epub_extractor: str | None = None,
    epub_unstructured_html_parser_version: str | None = None,
    epub_unstructured_skip_headers_footers: bool | str | None = None,
    epub_unstructured_preprocess_mode: str | None = None,
    ocr_device: str = "auto",
    pdf_ocr_policy: str = "auto",
    ocr_batch_size: int = 1,
    pdf_column_gap_ratio: float = 0.12,
    warm_models: bool = False,
    section_detector_backend: str = "legacy",
    multi_recipe_splitter: str = "legacy",
    multi_recipe_trace: bool = False,
    multi_recipe_min_ingredient_lines: int = 1,
    multi_recipe_min_instruction_lines: int = 1,
    multi_recipe_for_the_guardrail: bool = True,
    instruction_step_segmentation_policy: str = "auto",
    instruction_step_segmenter: str = "heuristic_v1",
    web_schema_extractor: str = "builtin_jsonld",
    web_schema_normalizer: str = "simple",
    web_html_text_extractor: str = "bs4",
    web_schema_policy: str = "prefer_schema",
    web_schema_min_confidence: float = 0.75,
    web_schema_min_ingredients: int = 2,
    web_schema_min_instruction_steps: int = 1,
    ingredient_text_fix_backend: str = "none",
    ingredient_pre_normalize_mode: str = "legacy",
    ingredient_packaging_mode: str = "off",
    ingredient_parser_backend: str = "ingredient_parser_nlp",
    ingredient_unit_canonicalizer: str = "legacy",
    ingredient_missing_unit_policy: str = "null",
    p6_time_backend: str = "regex_v1",
    p6_time_total_strategy: str = "sum_all_v1",
    p6_temperature_backend: str = "regex_v1",
    p6_temperature_unit_backend: str = "builtin_v1",
    p6_ovenlike_mode: str = "keywords_v1",
    p6_yield_mode: str = "legacy_v1",
    p6_emit_metadata_debug: bool = False,
    recipe_scorer_backend: str = "heuristic_v1",
    recipe_score_gold_min: float = 0.75,
    recipe_score_silver_min: float = 0.55,
    recipe_score_bronze_min: float = 0.35,
    recipe_score_min_ingredient_lines: int = 1,
    recipe_score_min_instruction_lines: int = 1,
    llm_recipe_pipeline: str = "off",
    atomic_block_splitter: str = "off",
    line_role_pipeline: str = "off",
    codex_farm_cmd: str = "codex-farm",
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    codex_farm_pipeline_pass1: str = "recipe.chunking.v1",
    codex_farm_pipeline_pass2: str = "recipe.schemaorg.v1",
    codex_farm_pipeline_pass3: str = "recipe.final.v1",
    codex_farm_context_blocks: int = 30,
    codex_farm_recipe_mode: str = "extract",
    codex_farm_failure_mode: str = "fail",
    processed_output_root: Path | None = None,
    write_markdown: bool = True,
    write_label_studio_tasks: bool = True,
    split_phase_slots: int | None = None,
    split_phase_gate_dir: Path | str | None = None,
    split_phase_status_label: str | None = None,
    single_offline_split_cache_mode: str = "off",
    single_offline_split_cache_dir: Path | str | None = None,
    single_offline_split_cache_key: str | None = None,
    single_offline_split_cache_force: bool = False,
    prelabel: bool = False,
    prelabel_provider: str = "codex-cli",
    codex_cmd: str | None = None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
    prelabel_timeout_seconds: int = 300,
    prelabel_cache_dir: Path | None = None,
    prelabel_workers: int = 15,
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
    prelabel_allow_partial: bool = False,
    prelabel_track_token_usage: bool = True,
    scheduler_event_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    run_manifest_kind: str = "bench_pred_run",
) -> dict[str, Any]:
    """Generate prediction-run artifacts offline (no Label Studio credentials needed).

    Performs extraction, conversion, task generation and writes all artifacts to disk.
    Returns metadata dict with run_root, tasks_total, manifest_path, etc.
    """
    def _notify(message: str) -> None:
        _notify_progress_callback(progress_callback, message)

    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    normalized_prelabel_granularity = normalize_prelabel_granularity(prelabel_granularity)

    run_dt = dt.datetime.now()
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    book_slug = _slugify_name(path.stem)
    run_root = output_dir / timestamp / "labelstudio" / book_slug
    run_root.mkdir(parents=True, exist_ok=True)
    run_started = time.monotonic()
    _notify_scheduler_event_callback(
        scheduler_event_callback,
        event="prep_started",
        source_file=str(path),
        run_root=str(run_root),
    )
    conversion_seconds = 0.0
    split_wait_seconds = 0.0
    split_convert_seconds = 0.0
    processed_output_write_seconds = 0.0
    task_build_seconds = 0.0
    artifact_write_seconds = 0.0

    if pipeline == "auto":
        importer, score = registry.best_importer_for_path(path)
    else:
        importer = registry.get_importer(pipeline)
        score = 1.0 if importer else 0.0
    if importer is None or score <= 0:
        raise RuntimeError("No importer available for this path.")

    selected_epub_extractor = _normalize_epub_extractor(
        str(epub_extractor or os.environ.get("C3IMP_EPUB_EXTRACTOR", "unstructured"))
    )

    selected_html_parser_version = _normalize_unstructured_html_parser_version(
        str(
            epub_unstructured_html_parser_version
            or os.environ.get("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION", "v1")
        )
    )
    selected_preprocess_mode = _normalize_unstructured_preprocess_mode(
        str(
            epub_unstructured_preprocess_mode
            or os.environ.get("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE", "br_split_v1")
        )
    )
    selected_skip_headers_footers = _coerce_bool(
        (
            epub_unstructured_skip_headers_footers
            if epub_unstructured_skip_headers_footers is not None
            else os.environ.get("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS")
        ),
        default=False,
    )
    selected_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(llm_recipe_pipeline)
    selected_codex_farm_failure_mode = _normalize_codex_farm_failure_mode(
        codex_farm_failure_mode
    )
    selected_codex_farm_recipe_mode = _normalize_codex_farm_recipe_mode(
        codex_farm_recipe_mode
    )
    selected_codex_farm_pipeline_pass1 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass1,
        field_name="codex_farm_pipeline_pass1",
    )
    selected_codex_farm_pipeline_pass2 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass2,
        field_name="codex_farm_pipeline_pass2",
    )
    selected_codex_farm_pipeline_pass3 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass3,
        field_name="codex_farm_pipeline_pass3",
    )
    run_settings = build_run_settings(
        workers=workers,
        pdf_split_workers=pdf_split_workers,
        epub_split_workers=epub_split_workers,
        pdf_pages_per_job=pdf_pages_per_job,
        epub_spine_items_per_job=epub_spine_items_per_job,
        epub_extractor=selected_epub_extractor,
        epub_unstructured_html_parser_version=selected_html_parser_version,
        epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
        epub_unstructured_preprocess_mode=selected_preprocess_mode,
        ocr_device=ocr_device,
        pdf_ocr_policy=pdf_ocr_policy,
        ocr_batch_size=ocr_batch_size,
        pdf_column_gap_ratio=pdf_column_gap_ratio,
        warm_models=warm_models,
        section_detector_backend=section_detector_backend,
        multi_recipe_splitter=multi_recipe_splitter,
        multi_recipe_trace=multi_recipe_trace,
        multi_recipe_min_ingredient_lines=multi_recipe_min_ingredient_lines,
        multi_recipe_min_instruction_lines=multi_recipe_min_instruction_lines,
        multi_recipe_for_the_guardrail=multi_recipe_for_the_guardrail,
        instruction_step_segmentation_policy=instruction_step_segmentation_policy,
        instruction_step_segmenter=instruction_step_segmenter,
        web_schema_extractor=web_schema_extractor,
        web_schema_normalizer=web_schema_normalizer,
        web_html_text_extractor=web_html_text_extractor,
        web_schema_policy=web_schema_policy,
        web_schema_min_confidence=web_schema_min_confidence,
        web_schema_min_ingredients=web_schema_min_ingredients,
        web_schema_min_instruction_steps=web_schema_min_instruction_steps,
        ingredient_text_fix_backend=ingredient_text_fix_backend,
        ingredient_pre_normalize_mode=ingredient_pre_normalize_mode,
        ingredient_packaging_mode=ingredient_packaging_mode,
        ingredient_parser_backend=ingredient_parser_backend,
        ingredient_unit_canonicalizer=ingredient_unit_canonicalizer,
        ingredient_missing_unit_policy=ingredient_missing_unit_policy,
        p6_time_backend=p6_time_backend,
        p6_time_total_strategy=p6_time_total_strategy,
        p6_temperature_backend=p6_temperature_backend,
        p6_temperature_unit_backend=p6_temperature_unit_backend,
        p6_ovenlike_mode=p6_ovenlike_mode,
        p6_yield_mode=p6_yield_mode,
        p6_emit_metadata_debug=p6_emit_metadata_debug,
        recipe_scorer_backend=recipe_scorer_backend,
        recipe_score_gold_min=recipe_score_gold_min,
        recipe_score_silver_min=recipe_score_silver_min,
        recipe_score_bronze_min=recipe_score_bronze_min,
        recipe_score_min_ingredient_lines=recipe_score_min_ingredient_lines,
        recipe_score_min_instruction_lines=recipe_score_min_instruction_lines,
        llm_recipe_pipeline=selected_llm_recipe_pipeline,
        atomic_block_splitter=atomic_block_splitter,
        line_role_pipeline=line_role_pipeline,
        codex_farm_cmd=codex_farm_cmd,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
        codex_farm_pipeline_pass1=selected_codex_farm_pipeline_pass1,
        codex_farm_pipeline_pass2=selected_codex_farm_pipeline_pass2,
        codex_farm_pipeline_pass3=selected_codex_farm_pipeline_pass3,
        codex_farm_context_blocks=codex_farm_context_blocks,
        codex_farm_recipe_mode=selected_codex_farm_recipe_mode,
        codex_farm_failure_mode=selected_codex_farm_failure_mode,
        all_epub=path.suffix.lower() == ".epub",
        effective_workers=compute_effective_workers(
            workers=workers,
            epub_split_workers=epub_split_workers,
            epub_extractor=selected_epub_extractor,
            all_epub=path.suffix.lower() == ".epub",
        ),
    )
    worker_run_config = run_settings.to_run_config_dict()
    run_config = dict(worker_run_config)
    run_config["epub_extractor_requested"] = selected_epub_extractor
    run_config["epub_extractor_effective"] = selected_epub_extractor
    run_config["write_markdown"] = bool(write_markdown)
    run_config["write_label_studio_tasks"] = bool(write_label_studio_tasks)
    run_config_hash = hashlib.sha256(
        json.dumps(
            run_config,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    run_config_summary = " | ".join(
        f"{key}={'true' if value is True else 'false' if value is False else value}"
        for key, value in sorted(run_config.items())
    )
    run_mapping: MappingConfig | None = None
    if path.suffix.lower() == ".pdf":
        run_mapping = MappingConfig(
            ocr_device=run_settings.ocr_device.value,
            ocr_batch_size=run_settings.ocr_batch_size,
        )
    selected_single_offline_split_cache_mode = _normalize_single_offline_split_cache_mode(
        single_offline_split_cache_mode
    )
    selected_single_offline_split_cache_key = (
        str(single_offline_split_cache_key or "").strip() or None
    )
    selected_single_offline_split_cache_dir = (
        Path(single_offline_split_cache_dir).expanduser()
        if single_offline_split_cache_dir is not None
        else None
    )
    single_offline_split_cache_enabled = (
        selected_single_offline_split_cache_mode != "off"
        and selected_single_offline_split_cache_dir is not None
        and selected_single_offline_split_cache_key is not None
    )
    single_offline_split_cache_hit = False
    single_offline_split_cache_entry_path: Path | None = None
    single_offline_split_cache_lock_path: Path | None = None
    single_offline_split_cache_lock_acquired = False
    single_offline_split_cache_payload: dict[str, Any] | None = None
    if single_offline_split_cache_enabled:
        single_offline_split_cache_entry_path = _single_offline_split_cache_entry_path(
            cache_root=selected_single_offline_split_cache_dir,
            split_cache_key=selected_single_offline_split_cache_key or "",
        )
        single_offline_split_cache_lock_path = _single_offline_split_cache_lock_path(
            single_offline_split_cache_entry_path
        )
        if not single_offline_split_cache_force:
            cached_payload = _load_single_offline_split_cache_entry(
                cache_path=single_offline_split_cache_entry_path,
                expected_key=selected_single_offline_split_cache_key or "",
            )
            if cached_payload is None and single_offline_split_cache_lock_path is not None:
                single_offline_split_cache_lock_acquired = (
                    _acquire_single_offline_split_cache_lock(
                        single_offline_split_cache_lock_path
                    )
                )
                if single_offline_split_cache_lock_acquired:
                    cached_payload = _load_single_offline_split_cache_entry(
                        cache_path=single_offline_split_cache_entry_path,
                        expected_key=selected_single_offline_split_cache_key or "",
                    )
                else:
                    cached_payload = _wait_for_single_offline_split_cache_entry(
                        cache_path=single_offline_split_cache_entry_path,
                        expected_key=selected_single_offline_split_cache_key or "",
                        lock_path=single_offline_split_cache_lock_path,
                    )
            if cached_payload is not None:
                try:
                    result = ConversionResult.model_validate(
                        cached_payload.get("conversion_result")
                    )
                except Exception:  # noqa: BLE001
                    cached_payload = None
                else:
                    single_offline_split_cache_hit = True
                    single_offline_split_cache_payload = cached_payload
                    conversion_seconds = max(
                        0.0,
                        _safe_float(cached_payload.get("conversion_seconds")) or 0.0,
                    )
                    split_wait_seconds = max(
                        0.0,
                        _safe_float(cached_payload.get("split_wait_seconds")) or 0.0,
                    )
                    split_convert_seconds = max(
                        0.0,
                        _safe_float(cached_payload.get("split_convert_seconds")) or 0.0,
                    )
                    _notify("Reusing single-offline split cache conversion payload.")
                    if single_offline_split_cache_lock_acquired:
                        _release_single_offline_split_cache_lock(
                            single_offline_split_cache_lock_path
                        )
                        single_offline_split_cache_lock_acquired = False

    if not single_offline_split_cache_hit:
        conversion_started = time.monotonic()
        try:
            with _temporary_epub_runtime_env(
                extractor=selected_epub_extractor,
                html_parser_version=selected_html_parser_version,
                skip_headers_footers=selected_skip_headers_footers,
                preprocess_mode=selected_preprocess_mode,
            ):
                job_specs = _plan_parallel_convert_jobs(
                    path,
                    workers=workers,
                    pdf_split_workers=pdf_split_workers,
                    epub_split_workers=epub_split_workers,
                    pdf_pages_per_job=pdf_pages_per_job,
                    epub_spine_items_per_job=epub_spine_items_per_job,
                    epub_extractor=selected_epub_extractor,
                )
                if len(job_specs) == 1:
                    result = importer.convert(
                        path,
                        run_mapping,
                        progress_callback=_notify,
                        run_settings=run_settings,
                    )
                else:
                    split_slot_context = nullcontext()
                    normalized_split_slots = _normalize_split_phase_slots(split_phase_slots)
                    if normalized_split_slots is not None:
                        split_slot_context = _acquire_split_phase_slot(
                            slots=normalized_split_slots,
                            gate_dir=split_phase_gate_dir,
                            notify=progress_callback,
                            status_label=split_phase_status_label,
                        )

                    _notify_scheduler_event_callback(
                        scheduler_event_callback,
                        event="split_wait_started",
                        split_job_count=len(job_specs),
                        split_slots=normalized_split_slots,
                    )
                    split_wait_started = time.monotonic()
                    with split_slot_context:
                        split_wait_seconds = max(0.0, time.monotonic() - split_wait_started)
                        _notify_scheduler_event_callback(
                            scheduler_event_callback,
                            event="split_wait_finished",
                            split_wait_seconds=split_wait_seconds,
                        )
                        split_convert_started = time.monotonic()
                        _notify_scheduler_event_callback(
                            scheduler_event_callback,
                            event="split_active_started",
                            split_job_count=len(job_specs),
                        )
                        effective_workers = max(1, workers)
                        if path.suffix.lower() == ".epub":
                            effective_workers = max(effective_workers, epub_split_workers)
                        if path.suffix.lower() == ".pdf":
                            effective_workers = max(effective_workers, pdf_split_workers)
                        max_workers = min(effective_workers, len(job_specs))

                        def _split_progress_status(current: int) -> str:
                            status = _task_progress_message(
                                "Running split conversion...",
                                current,
                                len(job_specs),
                            )
                            if max_workers > 1:
                                return f"{status} (workers={max_workers})"
                            return status

                        _notify(_split_progress_status(0))
                        job_results: list[dict[str, Any]] = []
                        job_errors: list[str] = []

                        def _run_job_serial(spec: dict[str, int | None]) -> None:
                            importer_name, job_result = _parallel_convert_worker(
                                path,
                                pipeline,
                                run_mapping,
                                run_config=worker_run_config,
                                start_page=spec.get("start_page"),
                                end_page=spec.get("end_page"),
                                start_spine=spec.get("start_spine"),
                                end_spine=spec.get("end_spine"),
                            )
                            job_results.append(
                                {**spec, "result": job_result, "importer_name": importer_name}
                            )

                        def _split_worker_status(spec: dict[str, int | None]) -> str:
                            job_number = int(spec.get("job_index") or 0) + 1
                            base = f"job {job_number}/{len(job_specs)}"
                            start_page = spec.get("start_page")
                            end_page = spec.get("end_page")
                            if start_page is not None and end_page is not None:
                                try:
                                    start = int(start_page) + 1
                                    end = max(start, int(end_page))
                                except (TypeError, ValueError):
                                    return base
                                return f"{base} pages {start}-{end}"
                            start_spine = spec.get("start_spine")
                            end_spine = spec.get("end_spine")
                            if start_spine is not None and end_spine is not None:
                                try:
                                    start = int(start_spine) + 1
                                    end = max(start, int(end_spine))
                                except (TypeError, ValueError):
                                    return base
                                return f"{base} spine {start}-{end}"
                            return base

                        def _run_parallel_split_jobs(executor: Any) -> None:
                            if max_workers > 1:
                                _notify(format_worker_activity_reset())
                            pending_specs = list(job_specs)
                            futures: dict[Any, tuple[int, dict[str, int | None]]] = {}

                            def _submit(spec: dict[str, int | None], worker_slot: int) -> None:
                                future = executor.submit(
                                    _parallel_convert_worker,
                                    path,
                                    pipeline,
                                    run_mapping,
                                    run_config=worker_run_config,
                                    start_page=spec.get("start_page"),
                                    end_page=spec.get("end_page"),
                                    start_spine=spec.get("start_spine"),
                                    end_spine=spec.get("end_spine"),
                                )
                                futures[future] = (worker_slot, spec)
                                if max_workers > 1:
                                    _notify(
                                        format_worker_activity(
                                            worker_slot,
                                            max_workers,
                                            _split_worker_status(spec),
                                        )
                                    )

                            for worker_slot in range(1, max_workers + 1):
                                if not pending_specs:
                                    break
                                _submit(pending_specs.pop(0), worker_slot)

                            completed = 0
                            while futures:
                                future = next(as_completed(list(futures.keys())))
                                worker_slot, spec = futures.pop(future)
                                try:
                                    importer_name, job_result = future.result()
                                except Exception as exc:
                                    job_errors.append(
                                        f"job {spec.get('job_index', '?')}: {exc}"
                                    )
                                else:
                                    job_results.append(
                                        {
                                            **spec,
                                            "result": job_result,
                                            "importer_name": importer_name,
                                        }
                                    )
                                    completed += 1
                                    _notify(_split_progress_status(completed))
                                if pending_specs:
                                    _submit(pending_specs.pop(0), worker_slot)
                                elif max_workers > 1:
                                    _notify(
                                        format_worker_activity(
                                            worker_slot,
                                            max_workers,
                                            "idle",
                                        )
                                    )

                        def _run_serial_split_jobs() -> None:
                            for spec in job_specs:
                                try:
                                    _run_job_serial(spec)
                                except Exception as exc:  # noqa: BLE001
                                    job_errors.append(
                                        f"job {spec.get('job_index', '?')}: {exc}"
                                    )
                                _notify(_split_progress_status(len(job_results)))
                        try:
                            executor_resolution = resolve_process_thread_executor(
                                max_workers=max_workers,
                                process_unavailable_message=lambda exc: (
                                    "Process-based worker concurrency unavailable "
                                    f"({exc}); using thread-based worker concurrency."
                                ),
                                thread_unavailable_message=lambda exc: (
                                    "Thread-based worker concurrency unavailable "
                                    f"({exc}); running split jobs serially."
                                ),
                            )
                            for message in executor_resolution.messages:
                                _notify(message)
                            if executor_resolution.executor is None:
                                _run_serial_split_jobs()
                            else:
                                executor = executor_resolution.executor
                                try:
                                    _run_parallel_split_jobs(executor)
                                finally:
                                    shutdown_executor(executor, wait=True, cancel_futures=False)
                        finally:
                            if max_workers > 1:
                                _notify(format_worker_activity_reset())

                        if job_errors:
                            raise RuntimeError("Split conversion failed: " + "; ".join(job_errors))
                        if not job_results:
                            raise RuntimeError("Split conversion produced no results.")

                        importer_name = str(job_results[0].get("importer_name") or importer.name)
                        result = _merge_parallel_results(path, importer_name, job_results)
                        _notify("Merged split job results.")
                        split_convert_seconds = max(0.0, time.monotonic() - split_convert_started)
                        _notify_scheduler_event_callback(
                            scheduler_event_callback,
                            event="split_active_finished",
                            split_active_seconds=split_convert_seconds,
                        )
            conversion_seconds = max(0.0, time.monotonic() - conversion_started)

            if (
                single_offline_split_cache_enabled
                and single_offline_split_cache_entry_path is not None
                and selected_single_offline_split_cache_key is not None
            ):
                if (
                    not single_offline_split_cache_lock_acquired
                    and single_offline_split_cache_lock_path is not None
                ):
                    single_offline_split_cache_lock_acquired = (
                        _acquire_single_offline_split_cache_lock(
                            single_offline_split_cache_lock_path
                        )
                    )
                if single_offline_split_cache_lock_acquired:
                    cache_write_payload = {
                        "schema_version": SINGLE_OFFLINE_SPLIT_CACHE_SCHEMA_VERSION,
                        "single_offline_split_cache_key": selected_single_offline_split_cache_key,
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                        "source_file": str(path),
                        "run_config_hash": run_config_hash,
                        "run_config_summary": run_config_summary,
                        "conversion_seconds": conversion_seconds,
                        "split_wait_seconds": split_wait_seconds,
                        "split_convert_seconds": split_convert_seconds,
                        "conversion_result": result.model_dump(
                            mode="json",
                            by_alias=True,
                        ),
                    }
                    _write_single_offline_split_cache_entry(
                        cache_path=single_offline_split_cache_entry_path,
                        payload=cache_write_payload,
                    )
                    single_offline_split_cache_payload = cache_write_payload
        finally:
            if (
                single_offline_split_cache_lock_acquired
                and single_offline_split_cache_lock_path is not None
            ):
                _release_single_offline_split_cache_lock(
                    single_offline_split_cache_lock_path
                )
                single_offline_split_cache_lock_acquired = False
    elif single_offline_split_cache_payload is not None:
        conversion_seconds = max(
            0.0,
            _safe_float(single_offline_split_cache_payload.get("conversion_seconds"))
            or conversion_seconds,
        )
    _notify_scheduler_event_callback(
        scheduler_event_callback,
        event="prep_finished",
        conversion_seconds=conversion_seconds,
        split_wait_seconds=split_wait_seconds,
    )

    llm_schema_overrides: dict[str, dict[str, Any]] | None = None
    llm_draft_overrides: dict[str, dict[str, Any]] | None = None
    llm_report: dict[str, Any] = {"enabled": False, "pipeline": "off"}
    _notify_scheduler_event_callback(
        scheduler_event_callback,
        event="post_started",
    )
    if run_settings.llm_recipe_pipeline.value != "off":
        _notify("Running codex-farm recipe pipeline...")
        try:
            llm_apply = run_codex_farm_recipe_pipeline(
                conversion_result=result,
                run_settings=run_settings,
                run_root=run_root,
                workbook_slug=book_slug,
                progress_callback=_notify,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                warning = (
                    "LLM recipe pipeline failed; falling back to deterministic outputs: "
                    f"{exc}"
                )
                if result.report is None:
                    result.report = ConversionReport()
                result.report.warnings.append(warning)
                llm_report = {
                    "enabled": True,
                    "pipeline": run_settings.llm_recipe_pipeline.value,
                    "fallbackApplied": True,
                    "fatalError": str(exc),
                }
            else:
                raise
        else:
            result = llm_apply.updated_conversion_result
            llm_schema_overrides = llm_apply.intermediate_overrides_by_recipe_id
            llm_draft_overrides = llm_apply.final_overrides_by_recipe_id
            llm_report = dict(llm_apply.llm_report)
    if result.report is None:
        result.report = ConversionReport()
    result.report.llm_codex_farm = llm_report

    _notify("Computing source file hash...")
    file_hash = compute_file_hash(path)
    _notify("Building extracted archive...")
    prepared_archive = prepare_extracted_archive(
        result=result,
        raw_artifacts=result.raw_artifacts,
        source_file=path.name,
        source_hash=file_hash,
        archive_builder=build_extracted_archive,
    )
    archive = list(prepared_archive.blocks)
    book_id = result.workbook or path.stem
    processed_run_root: Path | None = None
    processed_report_path: Path | None = None
    processed_stage_block_predictions_path: Path | None = None
    if processed_output_root is not None:
        _notify("Writing processed cookbook outputs...")
        processed_output_started = time.monotonic()
        knowledge_snippets_path = _resolve_knowledge_snippets_path(llm_report)
        processed_run_root = _write_processed_outputs(
            result=result,
            path=path,
            run_dt=run_dt,
            output_root=processed_output_root,
            importer_name=importer.name,
            run_config=run_config,
            run_config_hash=run_config_hash,
            run_config_summary=run_config_summary,
            schemaorg_overrides_by_recipe_id=llm_schema_overrides,
            draft_overrides_by_recipe_id=llm_draft_overrides,
            llm_codex_farm=llm_report,
            knowledge_snippets_path=knowledge_snippets_path,
            write_markdown=write_markdown,
        )
        processed_report_path = (
            processed_run_root / f"{path.stem}.excel_import_report.json"
        )
        candidate_stage_predictions = (
            processed_run_root
            / ".bench"
            / path.stem
            / "stage_block_predictions.json"
        )
        if candidate_stage_predictions.exists():
            processed_stage_block_predictions_path = candidate_stage_predictions
        processed_output_write_seconds = max(
            0.0, time.monotonic() - processed_output_started
        )
        _notify("Processed cookbook outputs complete.")

    task_build_started = time.monotonic()

    tasks: list[dict[str, Any]] = []
    task_ids: list[str] = []
    coverage_payload: dict[str, Any]
    segment_ids: list[str] | None = None
    prelabel_report_path: Path | None = None
    prelabel_errors_path: Path | None = None
    prelabel_prompt_log_path: Path | None = None
    prelabel_summary: dict[str, Any] | None = None
    resolved_segment_focus_blocks: int | None = None
    effective_segment_overlap: int | None = None

    if not archive:
        raise RuntimeError("No extracted blocks available for freeform labeling.")
    if segment_focus_blocks is None:
        resolved_segment_focus_blocks = segment_blocks
    else:
        resolved_segment_focus_blocks = int(segment_focus_blocks)
    if resolved_segment_focus_blocks < 1:
        raise ValueError("segment_focus_blocks must be >= 1")
    if resolved_segment_focus_blocks > segment_blocks:
        raise ValueError("segment_focus_blocks must be <= segment_blocks")
    focus_overlap_floor = max(0, segment_blocks - resolved_segment_focus_blocks)
    effective_segment_overlap = resolve_segment_overlap_for_target(
        total_blocks=len(archive),
        segment_blocks=segment_blocks,
        requested_overlap=segment_overlap,
        target_task_count=target_task_count,
        segment_focus_blocks=resolved_segment_focus_blocks,
    )
    if effective_segment_overlap != segment_overlap:
        reasons: list[str] = []
        if target_task_count is not None:
            reasons.append(f"target tasks {target_task_count}")
        if segment_overlap < focus_overlap_floor:
            reasons.append(
                "focus coverage "
                f"(segment {segment_blocks}, focus {resolved_segment_focus_blocks})"
            )
        if reasons:
            reason_suffix = f", {', '.join(reasons)}"
        else:
            reason_suffix = ""
        _notify(
            "Adjusted freeform overlap to "
            f"{effective_segment_overlap} "
            f"(requested {segment_overlap}{reason_suffix})."
        )
    _notify("Building freeform span tasks...")
    tasks_all = build_freeform_span_tasks(
        archive=archive,
        source_hash=file_hash,
        source_file=path.name,
        book_id=book_id,
        segment_blocks=segment_blocks,
        segment_overlap=effective_segment_overlap,
        segment_focus_blocks=resolved_segment_focus_blocks,
    )
    if not tasks_all:
        raise RuntimeError("No freeform span tasks generated for labeling.")
    coverage_payload = compute_freeform_task_coverage(archive, tasks_all)
    if coverage_payload["extracted_chars"] == 0:
        raise RuntimeError(
            "No text extracted; this may be a scanned document that requires OCR."
        )
    _notify("Sampling freeform span tasks...")
    tasks = sample_freeform_tasks(tasks_all, limit=limit, sample=sample)
    if not tasks:
        raise RuntimeError(
            "No freeform span tasks generated after limit/sample filters."
        )
    if prelabel:
        total_prelabel_tasks = len(tasks)
        _notify(
            _task_progress_message(
                "Running freeform prelabeling...",
                0,
                total_prelabel_tasks,
            )
        )
        provider_cache_dir = prelabel_cache_dir or (run_root / "prelabel_cache")
        provider = _build_prelabel_provider(
            prelabel_provider=prelabel_provider,
            codex_cmd=codex_cmd,
            codex_model=codex_model,
            codex_reasoning_effort=codex_reasoning_effort,
            prelabel_timeout_seconds=prelabel_timeout_seconds,
            prelabel_cache_dir=provider_cache_dir,
            prelabel_track_token_usage=prelabel_track_token_usage,
        )
        provider_cmd = str(
            getattr(provider, "cmd", (codex_cmd or default_codex_cmd()).strip())
        )
        _notify("Checking freeform prelabel model access...")
        preflight_codex_model_access(
            cmd=provider_cmd,
            timeout_s=min(30, max(1, int(prelabel_timeout_seconds))),
        )
        provider_model = getattr(
            provider,
            "model",
            resolve_codex_model(codex_model, cmd=provider_cmd),
        )
        provider_reasoning_effort = codex_reasoning_effort_from_cmd(provider_cmd)
        if provider_reasoning_effort is None:
            provider_reasoning_effort = normalize_codex_reasoning_effort(
                codex_reasoning_effort
            )
        if provider_reasoning_effort is None:
            provider_reasoning_effort = default_codex_reasoning_effort(
                cmd=provider_cmd
            )
        provider_account = codex_account_summary(provider_cmd)
        prelabel_prompt_log_path = run_root / "prelabel_prompt_log.md"
        prelabel_prompt_log_path.write_text(
            "\n".join(
                [
                    "# Prelabel Prompt Log",
                    "",
                    f"- Generated at (UTC): {dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec='seconds')}",
                    "- One section per Codex prompt call.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        prelabel_prompt_log_count = 0
        prelabel_errors: list[dict[str, Any]] = []
        prelabel_label_counts: dict[str, int] = {}
        prelabel_success = 0
        rate_limit_stop_event = threading.Event()
        rate_limit_warning_emitted = False
        rate_limit_skip_reason = (
            "Skipped after prior HTTP 429 rate-limit failure from another task."
        )
        effective_prelabel_workers = min(
            total_prelabel_tasks,
            max(1, int(prelabel_workers)),
        )

        def _prelabel_progress_status(current: int) -> str:
            status = _task_progress_message(
                "Running freeform prelabeling...",
                current,
                total_prelabel_tasks,
            )
            if effective_prelabel_workers > 1:
                return f"{status} (workers={effective_prelabel_workers})"
            return status

        def _prelabel_worker_status_label(task_index: int, segment_id: str) -> str:
            segment_summary = segment_id.strip() or "<unknown>"
            segment_parts = segment_summary.rsplit(":", 2)
            if (
                len(segment_parts) == 3
                and segment_parts[1].isdigit()
                and segment_parts[2].isdigit()
            ):
                segment_summary = f"blocks {segment_parts[1]}-{segment_parts[2]}"
            if len(segment_summary) > 72:
                segment_summary = f"{segment_summary[:69]}..."
            return f"task {task_index}/{total_prelabel_tasks} {segment_summary}"

        worker_slot_by_thread: dict[int, int] = {}
        worker_slot_lock = threading.Lock()
        next_worker_slot = 1

        def _resolve_worker_slot() -> int:
            nonlocal next_worker_slot
            thread_id = threading.get_ident()
            with worker_slot_lock:
                existing = worker_slot_by_thread.get(thread_id)
                if existing is not None:
                    return existing
                slot = min(next_worker_slot, effective_prelabel_workers)
                worker_slot_by_thread[thread_id] = slot
                next_worker_slot += 1
                return slot

        def _emit_rate_limit_warning() -> None:
            nonlocal rate_limit_warning_emitted
            if rate_limit_warning_emitted:
                return
            _notify(
                "WARNING: freeform prelabel rate limit (HTTP 429) detected; "
                "halting additional prelabel task requests."
            )
            rate_limit_warning_emitted = True

        def _rate_limit_skip_result(
            *,
            task_index: int,
            task_payload: dict[str, Any],
            segment_id: str | None = None,
        ) -> dict[str, Any]:
            resolved_segment_id = segment_id or (
                _task_id_value(task_payload) or "<unknown>"
            )
            return {
                "task_index": task_index,
                "segment_id": resolved_segment_id,
                "annotation": None,
                "error": rate_limit_skip_reason,
                "prompt_entries": [],
                "task": task_payload,
                "rate_limit": False,
                "rate_limit_skipped": True,
            }

        if effective_prelabel_workers > 1:
            _notify(format_worker_activity_reset())
        _notify(_prelabel_progress_status(0))

        def _run_prelabel_task(
            *,
            task_index: int,
            task_payload: dict[str, Any],
        ) -> dict[str, Any]:
            segment_id = _task_id_value(task_payload) or "<unknown>"
            if rate_limit_stop_event.is_set():
                return _rate_limit_skip_result(
                    task_index=task_index,
                    task_payload=task_payload,
                    segment_id=segment_id,
                )
            prompt_entries: list[dict[str, Any]] = []
            worker_slot: int | None = None
            if effective_prelabel_workers > 1:
                worker_slot = _resolve_worker_slot()
                _notify(
                    format_worker_activity(
                        worker_slot,
                        effective_prelabel_workers,
                        _prelabel_worker_status_label(task_index, segment_id),
                    )
                )

            def _collect_prompt_log(entry: dict[str, Any]) -> None:
                prompt_entries.append(dict(entry))

            try:
                try:
                    annotation = prelabel_freeform_task(
                        task_payload,
                        provider=provider,
                        allowed_labels=set(FREEFORM_ALLOWED_LABELS),
                        prelabel_granularity=normalized_prelabel_granularity,
                        prompt_log_callback=_collect_prompt_log,
                    )
                except Exception as exc:  # noqa: BLE001
                    error_message = str(exc)
                    rate_limited = is_rate_limit_message(error_message)
                    if rate_limited:
                        rate_limit_stop_event.set()
                    return {
                        "task_index": task_index,
                        "segment_id": segment_id,
                        "annotation": None,
                        "error": error_message,
                        "prompt_entries": prompt_entries,
                        "task": task_payload,
                        "rate_limit": rate_limited,
                        "rate_limit_skipped": False,
                    }
                if annotation is None:
                    return {
                        "task_index": task_index,
                        "segment_id": segment_id,
                        "annotation": None,
                        "error": "No valid labels produced by provider output.",
                        "prompt_entries": prompt_entries,
                        "task": task_payload,
                        "rate_limit": False,
                        "rate_limit_skipped": False,
                    }
                return {
                    "task_index": task_index,
                    "segment_id": segment_id,
                    "annotation": annotation,
                    "error": None,
                    "prompt_entries": prompt_entries,
                    "task": task_payload,
                    "rate_limit": False,
                    "rate_limit_skipped": False,
                }
            finally:
                if worker_slot is not None:
                    _notify(
                        format_worker_activity(
                            worker_slot,
                            effective_prelabel_workers,
                            "idle",
                        )
                    )

        task_results: list[dict[str, Any]] = []
        if effective_prelabel_workers == 1:
            for task_index, task in enumerate(tasks, start=1):
                row = _run_prelabel_task(task_index=task_index, task_payload=task)
                task_results.append(row)
                if bool(row.get("rate_limit")):
                    _emit_rate_limit_warning()
                _notify(_prelabel_progress_status(task_index))
        else:
            with ThreadPoolExecutor(max_workers=effective_prelabel_workers) as executor:
                futures = {
                    executor.submit(
                        _run_prelabel_task,
                        task_index=task_index,
                        task_payload=task,
                    ): (task_index, task)
                    for task_index, task in enumerate(tasks, start=1)
                }
                completed_tasks = 0
                for future in as_completed(futures):
                    task_index, task = futures[future]
                    try:
                        row = future.result()
                    except Exception as exc:  # noqa: BLE001
                        error_message = str(exc)
                        rate_limited = is_rate_limit_message(error_message)
                        if rate_limited:
                            rate_limit_stop_event.set()
                        row = {
                            "task_index": task_index,
                            "segment_id": _task_id_value(task)
                            or "<unknown>",
                            "annotation": None,
                            "error": error_message,
                            "prompt_entries": [],
                            "task": task,
                            "rate_limit": rate_limited,
                            "rate_limit_skipped": False,
                        }
                    task_results.append(row)
                    if bool(row.get("rate_limit")):
                        _emit_rate_limit_warning()
                    completed_tasks += 1
                    _notify(_prelabel_progress_status(completed_tasks))
        if effective_prelabel_workers > 1:
            _notify(format_worker_activity_reset())

        task_results.sort(key=lambda row: int(row.get("task_index") or 0))

        for row in task_results:
            prompt_entries = row.get("prompt_entries")
            if not isinstance(prompt_entries, list):
                continue
            for entry in prompt_entries:
                if not isinstance(entry, dict):
                    continue
                payload = dict(entry)
                payload.setdefault("segment_id", row.get("segment_id") or "<unknown>")
                payload["task_index"] = row.get("task_index")
                payload["task_total"] = total_prelabel_tasks
                payload["logged_at"] = dt.datetime.now(
                    tz=dt.timezone.utc
                ).isoformat(timespec="seconds")
                payload["codex_cmd"] = provider_cmd
                payload["codex_model"] = provider_model
                payload["codex_reasoning_effort"] = provider_reasoning_effort
                payload["codex_account"] = provider_account
                with prelabel_prompt_log_path.open("a", encoding="utf-8") as handle:
                    handle.write(_format_prelabel_prompt_log_entry_markdown(payload))
                prelabel_prompt_log_count += 1

        rate_limit_failure_count = 0
        rate_limit_skipped_count = 0
        for row in task_results:
            segment_id = str(row.get("segment_id") or "<unknown>")
            error = row.get("error")
            if error:
                error_payload: dict[str, Any] = {
                    "segment_id": segment_id,
                    "reason": str(error),
                }
                if bool(row.get("rate_limit")):
                    error_payload["rate_limit"] = True
                    rate_limit_failure_count += 1
                if bool(row.get("rate_limit_skipped")):
                    error_payload["rate_limit_skipped"] = True
                    rate_limit_skipped_count += 1
                prelabel_errors.append(error_payload)
                continue
            annotation = row.get("annotation")
            if not isinstance(annotation, dict):
                prelabel_errors.append(
                    {
                        "segment_id": segment_id,
                        "reason": "No valid labels produced by provider output.",
                    }
                )
                continue
            task_payload = row.get("task")
            prelabel_success += 1
            if isinstance(task_payload, dict):
                annotation_result = annotation.get("result")
                if isinstance(annotation_result, list) and annotation_result:
                    task_payload["annotations"] = [annotation]
            for label in sorted(annotation_labels(annotation)):
                prelabel_label_counts[label] = prelabel_label_counts.get(label, 0) + 1

        prelabel_errors_path = run_root / "prelabel_errors.jsonl"
        if prelabel_errors:
            prelabel_errors_path.write_text(
                "\n".join(
                    json.dumps(row, sort_keys=True) for row in prelabel_errors
                )
                + "\n",
                encoding="utf-8",
            )
        else:
            prelabel_errors_path.write_text("", encoding="utf-8")
        provider_usage = None
        usage_summary = getattr(provider, "usage_summary", None)
        if callable(usage_summary):
            provider_usage = usage_summary()

        prelabel_summary = {
            "enabled": True,
            "provider": prelabel_provider,
            "granularity": normalized_prelabel_granularity,
            "codex_cmd": provider_cmd,
            "codex_model": provider_model,
            "codex_reasoning_effort": provider_reasoning_effort,
            "codex_account": provider_account,
            "cache_dir": str(provider_cache_dir),
            "workers": effective_prelabel_workers,
            "task_count": len(tasks),
            "success_count": prelabel_success,
            "failure_count": len(prelabel_errors),
            "rate_limit_stop_triggered": bool(rate_limit_stop_event.is_set()),
            "rate_limit_failure_count": rate_limit_failure_count,
            "rate_limit_skipped_count": rate_limit_skipped_count,
            "allow_partial": bool(prelabel_allow_partial),
            "token_usage_enabled": bool(prelabel_track_token_usage),
            "token_usage": provider_usage if prelabel_track_token_usage else None,
            "label_counts": prelabel_label_counts,
            "errors_path": str(prelabel_errors_path),
            "prompt_log_path": str(prelabel_prompt_log_path),
            "prompt_log_count": prelabel_prompt_log_count,
        }
        prelabel_report_path = run_root / "prelabel_report.json"
        prelabel_report_path.write_text(
            json.dumps(prelabel_summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        if rate_limit_stop_event.is_set() and not prelabel_allow_partial:
            raise RuntimeError(
                "Prelabeling stopped after HTTP 429 rate-limit response. "
                "No additional prelabel task calls were sent after the first 429. "
                "Re-run later, or use --prelabel-allow-partial to continue upload "
                "with recorded prelabel failures."
            )
        if prelabel_errors and not prelabel_allow_partial:
            raise RuntimeError(
                "Prelabeling failed for one or more tasks. "
                "Re-run with prelabel_allow_partial=True "
                "(CLI: --prelabel-allow-partial) to continue "
                "while recording failures."
            )

    label_config = build_freeform_label_config()
    segment_ids = [task.get("data", {}).get("segment_id") for task in tasks if task]
    task_ids = [segment_id for segment_id in segment_ids if segment_id]
    task_build_seconds = max(0.0, time.monotonic() - task_build_started)

    _notify("Writing prediction run artifacts...")
    artifact_write_started = time.monotonic()
    archive_path = run_root / "extracted_archive.json"
    archive_payload = prepared_archive_payload(prepared_archive)
    archive_path.write_text(
        json.dumps(archive_payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    (run_root / "extracted_text.txt").write_text(
        prepared_archive_text(prepared_archive) + "\n", encoding="utf-8"
    )

    tasks_path: Path | None = None
    tasks_jsonl_status = "written" if write_label_studio_tasks else "skipped_by_config"
    if write_label_studio_tasks:
        tasks_path = run_root / "label_studio_tasks.jsonl"
        tasks_path.write_text(
            "\n".join(json.dumps(task) for task in tasks) + "\n", encoding="utf-8"
        )

    coverage_path = run_root / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            coverage_payload,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    local_stage_block_predictions_path: Path | None = None
    if (
        processed_stage_block_predictions_path is not None
        and processed_stage_block_predictions_path.exists()
    ):
        local_stage_block_predictions_path = run_root / "stage_block_predictions.json"
        shutil.copy2(
            processed_stage_block_predictions_path,
            local_stage_block_predictions_path,
        )
    artifact_write_seconds = max(0.0, time.monotonic() - artifact_write_started)

    result_timing_payload = (
        result.report.timing if result.report and isinstance(result.report.timing, dict) else {}
    )
    parsing_seconds = _safe_float(result_timing_payload.get("parsing_seconds"))
    if parsing_seconds is None:
        parsing_seconds = _safe_float(result_timing_payload.get("parsingSeconds"))
    if parsing_seconds is None:
        parsing_seconds = conversion_seconds
    writing_seconds = _safe_float(result_timing_payload.get("writing_seconds"))
    if writing_seconds is None:
        writing_seconds = _safe_float(result_timing_payload.get("writingSeconds"))
    if writing_seconds is None:
        writing_seconds = processed_output_write_seconds
    ocr_seconds = _safe_float(result_timing_payload.get("ocr_seconds"))
    if ocr_seconds is None:
        ocr_seconds = _safe_float(result_timing_payload.get("ocrSeconds"))

    checkpoints: dict[str, float] = {
        "conversion_seconds": conversion_seconds,
        "task_build_seconds": task_build_seconds,
        "artifact_write_seconds": artifact_write_seconds,
    }
    if split_wait_seconds > 0:
        checkpoints["split_wait_seconds"] = split_wait_seconds
    if split_convert_seconds > 0:
        checkpoints["split_convert_seconds"] = split_convert_seconds
    if processed_output_write_seconds > 0:
        checkpoints["processed_output_write_seconds"] = processed_output_write_seconds

    prediction_total_seconds = max(0.0, time.monotonic() - run_started)
    timing_payload = _timing_payload(
        total_seconds=prediction_total_seconds,
        prediction_seconds=prediction_total_seconds,
        parsing_seconds=parsing_seconds,
        writing_seconds=writing_seconds,
        ocr_seconds=ocr_seconds,
        artifact_write_seconds=artifact_write_seconds,
        checkpoints=checkpoints,
    )
    _write_processed_report_timing_best_effort(
        processed_report_path=processed_report_path,
        timing=timing_payload,
        notify=_notify,
    )
    single_offline_split_cache_summary: dict[str, Any] | None = None
    if single_offline_split_cache_enabled or single_offline_split_cache_payload is not None:
        single_offline_split_cache_summary = {
            "enabled": bool(single_offline_split_cache_enabled),
            "mode": selected_single_offline_split_cache_mode,
            "key": selected_single_offline_split_cache_key,
            "dir": (
                str(selected_single_offline_split_cache_dir)
                if selected_single_offline_split_cache_dir is not None
                else None
            ),
            "force": bool(single_offline_split_cache_force),
            "hit": bool(single_offline_split_cache_hit),
            "entry_path": (
                str(single_offline_split_cache_entry_path)
                if single_offline_split_cache_entry_path is not None
                else None
            ),
            "source_hash": file_hash,
            "conversion_seconds": conversion_seconds,
            "split_wait_seconds": split_wait_seconds,
            "split_convert_seconds": split_convert_seconds,
            "created_at": (
                str((single_offline_split_cache_payload or {}).get("created_at") or "").strip()
                or None
            ),
        }

    manifest = {
        "pipeline": importer.name,
        "importer_name": importer.name,
        "source_file": str(path),
        "source_hash": file_hash,
        "book_id": book_id,
        "recipe_count": len(result.recipes),
        "tip_count": len(result.tips),
        "run_timestamp": run_dt.isoformat(timespec="seconds"),
        "run_config": run_config,
        "run_config_hash": run_config_hash,
        "run_config_summary": run_config_summary,
        "llm_codex_farm": llm_report,
        "processed_run_root": (
            str(processed_run_root) if processed_run_root is not None else None
        ),
        "processed_report_path": (
            str(processed_report_path) if processed_report_path is not None else None
        ),
        "processed_stage_block_predictions_path": (
            str(processed_stage_block_predictions_path)
            if processed_stage_block_predictions_path is not None
            else None
        ),
        "stage_block_predictions_path": (
            str(local_stage_block_predictions_path)
            if local_stage_block_predictions_path is not None
            else None
        ),
        "task_scope": "freeform-spans",
        "segment_blocks": segment_blocks,
        "segment_focus_blocks": resolved_segment_focus_blocks,
        "segment_overlap": effective_segment_overlap,
        "segment_overlap_requested": segment_overlap,
        "segment_overlap_effective": effective_segment_overlap,
        "target_task_count": target_task_count,
        "write_markdown": bool(write_markdown),
        "write_label_studio_tasks": bool(write_label_studio_tasks),
        "tasks_jsonl_status": tasks_jsonl_status,
        "tasks_jsonl_path": str(tasks_path) if tasks_path is not None else None,
        "timing": timing_payload,
        "task_count": len(tasks),
        "task_ids": task_ids,
        "segment_ids": segment_ids,
        "coverage": coverage_payload,
        "prelabel": prelabel_summary,
        "prelabel_report_path": (
            str(prelabel_report_path) if prelabel_report_path is not None else None
        ),
        "prelabel_errors_path": (
            str(prelabel_errors_path) if prelabel_errors_path is not None else None
        ),
        "prelabel_prompt_log_path": (
            str(prelabel_prompt_log_path) if prelabel_prompt_log_path is not None else None
        ),
    }
    if single_offline_split_cache_summary is not None:
        manifest["single_offline_split_cache"] = single_offline_split_cache_summary

    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    run_manifest_artifacts: dict[str, Any] = {
        "tasks_jsonl_status": tasks_jsonl_status,
        "prediction_manifest_json": "manifest.json",
        "coverage_json": "coverage.json",
        "extracted_archive_json": "extracted_archive.json",
        "extracted_text": "extracted_text.txt",
    }
    tasks_manifest_path = _path_for_manifest(run_root, tasks_path)
    if tasks_manifest_path:
        run_manifest_artifacts["tasks_jsonl"] = tasks_manifest_path
    if prelabel_report_path is not None:
        run_manifest_artifacts["prelabel_report_json"] = _path_for_manifest(
            run_root, prelabel_report_path
        )
    if prelabel_errors_path is not None:
        run_manifest_artifacts["prelabel_errors_jsonl"] = _path_for_manifest(
            run_root, prelabel_errors_path
        )
    if prelabel_prompt_log_path is not None:
        run_manifest_artifacts["prelabel_prompt_log_md"] = _path_for_manifest(
            run_root, prelabel_prompt_log_path
        )
    processed_run_path = _path_for_manifest(run_root, processed_run_root)
    if processed_run_path:
        run_manifest_artifacts["processed_output_run_dir"] = processed_run_path
    processed_report_manifest_path = _path_for_manifest(run_root, processed_report_path)
    if processed_report_manifest_path:
        run_manifest_artifacts["processed_report_json"] = processed_report_manifest_path
    processed_stage_predictions_manifest_path = _path_for_manifest(
        run_root,
        processed_stage_block_predictions_path,
    )
    if processed_stage_predictions_manifest_path:
        run_manifest_artifacts[
            "processed_stage_block_predictions_json"
        ] = processed_stage_predictions_manifest_path
    local_stage_predictions_manifest_path = _path_for_manifest(
        run_root,
        local_stage_block_predictions_path,
    )
    if local_stage_predictions_manifest_path:
        run_manifest_artifacts[
            "stage_block_predictions_json"
        ] = local_stage_predictions_manifest_path
    run_manifest_artifacts["timing"] = timing_payload
    llm_manifest_path = (
        run_root
        / "raw"
        / "llm"
        / _slugify_name(path.stem)
        / "llm_manifest.json"
    )
    if llm_manifest_path.exists():
        llm_run_dir = llm_manifest_path.parent.parent
        prompt_inputs_manifest_path = run_root / "prompt_inputs_manifest.txt"
        prompt_outputs_manifest_path = run_root / "prompt_outputs_manifest.txt"
        prompt_input_dirs = (
            llm_run_dir / "pass1_chunking" / "in",
            llm_run_dir / "pass2_schemaorg" / "in",
            llm_run_dir / "pass3_final" / "in",
        )
        prompt_output_dirs = (
            llm_run_dir / "pass1_chunking" / "out",
            llm_run_dir / "pass2_schemaorg" / "out",
            llm_run_dir / "pass3_final" / "out",
        )

        def _build_prompt_manifest(
            source_dirs: tuple[Path, ...], target_path: Path
        ) -> str | None:
            prompt_paths: list[str] = []
            for source_dir in source_dirs:
                if not source_dir.exists():
                    continue
                for prompt_file in sorted(source_dir.glob("*.json"), key=lambda p: p.name):
                    rel_path = _path_for_manifest(run_root, prompt_file)
                    if rel_path is not None:
                        prompt_paths.append(rel_path)
            target_path.write_text("\n".join(prompt_paths) + ("\n" if prompt_paths else ""), encoding="utf-8")
            return _path_for_manifest(run_root, target_path)

        prompt_inputs_manifest = _build_prompt_manifest(
            source_dirs=prompt_input_dirs,
            target_path=prompt_inputs_manifest_path,
        )
        prompt_outputs_manifest = _build_prompt_manifest(
            source_dirs=prompt_output_dirs,
            target_path=prompt_outputs_manifest_path,
        )
        if prompt_inputs_manifest is not None:
            run_manifest_artifacts[
                "prompt_inputs_manifest_txt"
            ] = prompt_inputs_manifest
        if prompt_outputs_manifest is not None:
            run_manifest_artifacts[
                "prompt_outputs_manifest_txt"
            ] = prompt_outputs_manifest
        run_manifest_artifacts["llm_manifest_json"] = _path_for_manifest(
            run_root,
            llm_manifest_path,
        )

    run_manifest_run_config = dict(run_config)
    if single_offline_split_cache_summary is not None:
        run_manifest_run_config["single_offline_split_cache"] = (
            single_offline_split_cache_summary
        )

    run_manifest_payload = RunManifest(
        run_kind=run_manifest_kind,
        run_id=run_root.name,
        created_at=run_dt.isoformat(timespec="seconds"),
        source=RunSource(
            path=str(path),
            source_hash=file_hash,
            importer_name=importer.name,
        ),
        run_config=run_manifest_run_config,
        artifacts=run_manifest_artifacts,
    )
    _write_manifest_best_effort(run_root, run_manifest_payload, notify=_notify)
    _notify("Prediction run artifacts complete.")
    _notify_scheduler_event_callback(
        scheduler_event_callback,
        event="post_finished",
        prediction_total_seconds=prediction_total_seconds,
        task_count=len(tasks),
    )

    return {
        "run_root": run_root,
        "processed_run_root": processed_run_root,
        "processed_report_path": processed_report_path,
        "processed_stage_block_predictions_path": processed_stage_block_predictions_path,
        "stage_block_predictions_path": local_stage_block_predictions_path,
        "tasks_total": len(tasks),
        "tasks_jsonl_path": tasks_path,
        "tasks_jsonl_status": tasks_jsonl_status,
        "manifest_path": manifest_path,
        "tasks": tasks,
        "task_ids": task_ids,
        "segment_ids": segment_ids,
        "coverage": coverage_payload,
        "prelabel": prelabel_summary,
        "prelabel_report_path": prelabel_report_path,
        "prelabel_errors_path": prelabel_errors_path,
        "prelabel_prompt_log_path": prelabel_prompt_log_path,
        "label_config": label_config,
        "importer_name": importer.name,
        "run_config": run_config,
        "run_config_hash": run_config_hash,
        "run_config_summary": run_config_summary,
        "single_offline_split_cache": single_offline_split_cache_summary,
        "llm_codex_farm": llm_report,
        "book_id": book_id,
        "file_hash": file_hash,
        "segment_focus_blocks": resolved_segment_focus_blocks,
        "segment_overlap_requested": segment_overlap,
        "segment_overlap_effective": effective_segment_overlap,
        "target_task_count": target_task_count,
        "timing": timing_payload,
    }


def run_labelstudio_import(
    *,
    path: Path,
    output_dir: Path,
    pipeline: str,
    project_name: str | None,
    segment_blocks: int = 40,
    segment_overlap: int = 5,
    segment_focus_blocks: int | None = None,
    target_task_count: int | None = None,
    overwrite: bool,
    resume: bool,
    label_studio_url: str,
    label_studio_api_key: str,
    limit: int | None,
    sample: int | None,
    progress_callback: Callable[[str], None] | None = None,
    workers: int = 1,
    pdf_split_workers: int = 1,
    epub_split_workers: int = 1,
    pdf_pages_per_job: int = 50,
    epub_spine_items_per_job: int = 10,
    epub_extractor: str | None = None,
    epub_unstructured_html_parser_version: str | None = None,
    epub_unstructured_skip_headers_footers: bool | str | None = None,
    epub_unstructured_preprocess_mode: str | None = None,
    ocr_device: str = "auto",
    pdf_ocr_policy: str = "auto",
    ocr_batch_size: int = 1,
    pdf_column_gap_ratio: float = 0.12,
    warm_models: bool = False,
    section_detector_backend: str = "legacy",
    multi_recipe_splitter: str = "legacy",
    multi_recipe_trace: bool = False,
    multi_recipe_min_ingredient_lines: int = 1,
    multi_recipe_min_instruction_lines: int = 1,
    multi_recipe_for_the_guardrail: bool = True,
    instruction_step_segmentation_policy: str = "auto",
    instruction_step_segmenter: str = "heuristic_v1",
    web_schema_extractor: str = "builtin_jsonld",
    web_schema_normalizer: str = "simple",
    web_html_text_extractor: str = "bs4",
    web_schema_policy: str = "prefer_schema",
    web_schema_min_confidence: float = 0.75,
    web_schema_min_ingredients: int = 2,
    web_schema_min_instruction_steps: int = 1,
    ingredient_text_fix_backend: str = "none",
    ingredient_pre_normalize_mode: str = "legacy",
    ingredient_packaging_mode: str = "off",
    ingredient_parser_backend: str = "ingredient_parser_nlp",
    ingredient_unit_canonicalizer: str = "legacy",
    ingredient_missing_unit_policy: str = "null",
    p6_time_backend: str = "regex_v1",
    p6_time_total_strategy: str = "sum_all_v1",
    p6_temperature_backend: str = "regex_v1",
    p6_temperature_unit_backend: str = "builtin_v1",
    p6_ovenlike_mode: str = "keywords_v1",
    p6_yield_mode: str = "legacy_v1",
    p6_emit_metadata_debug: bool = False,
    recipe_scorer_backend: str = "heuristic_v1",
    recipe_score_gold_min: float = 0.75,
    recipe_score_silver_min: float = 0.55,
    recipe_score_bronze_min: float = 0.35,
    recipe_score_min_ingredient_lines: int = 1,
    recipe_score_min_instruction_lines: int = 1,
    llm_recipe_pipeline: str = "off",
    codex_farm_cmd: str = "codex-farm",
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    codex_farm_pipeline_pass1: str = "recipe.chunking.v1",
    codex_farm_pipeline_pass2: str = "recipe.schemaorg.v1",
    codex_farm_pipeline_pass3: str = "recipe.final.v1",
    codex_farm_context_blocks: int = 30,
    codex_farm_recipe_mode: str = "extract",
    codex_farm_failure_mode: str = "fail",
    processed_output_root: Path | None = None,
    split_phase_slots: int | None = None,
    split_phase_gate_dir: Path | str | None = None,
    split_phase_status_label: str | None = None,
    single_offline_split_cache_mode: str = "off",
    single_offline_split_cache_dir: Path | str | None = None,
    single_offline_split_cache_key: str | None = None,
    single_offline_split_cache_force: bool = False,
    prelabel: bool = False,
    prelabel_provider: str = "codex-cli",
    codex_cmd: str | None = None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
    prelabel_timeout_seconds: int = 300,
    prelabel_cache_dir: Path | None = None,
    prelabel_workers: int = 15,
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
    prelabel_upload_as: str = "annotations",
    prelabel_allow_partial: bool = False,
    prelabel_track_token_usage: bool = True,
    scheduler_event_callback: Callable[[dict[str, Any]], None] | None = None,
    auto_project_name_on_scope_mismatch: bool = False,
    allow_labelstudio_write: bool = False,
) -> dict[str, Any]:
    def _notify(message: str) -> None:
        _notify_progress_callback(progress_callback, message)

    if not allow_labelstudio_write:
        raise RuntimeError(
            "Label Studio write blocked. Re-run with explicit upload consent "
            "(allow_labelstudio_write=True)."
        )

    # Generate all artifacts offline first
    pred = generate_pred_run_artifacts(
        path=path,
        output_dir=output_dir,
        pipeline=pipeline,
        segment_blocks=segment_blocks,
        segment_overlap=segment_overlap,
        segment_focus_blocks=segment_focus_blocks,
        target_task_count=target_task_count,
        limit=limit,
        sample=sample,
        workers=workers,
        pdf_split_workers=pdf_split_workers,
        epub_split_workers=epub_split_workers,
        pdf_pages_per_job=pdf_pages_per_job,
        epub_spine_items_per_job=epub_spine_items_per_job,
        epub_extractor=epub_extractor,
        epub_unstructured_html_parser_version=epub_unstructured_html_parser_version,
        epub_unstructured_skip_headers_footers=epub_unstructured_skip_headers_footers,
        epub_unstructured_preprocess_mode=epub_unstructured_preprocess_mode,
        ocr_device=ocr_device,
        pdf_ocr_policy=pdf_ocr_policy,
        ocr_batch_size=ocr_batch_size,
        pdf_column_gap_ratio=pdf_column_gap_ratio,
        warm_models=warm_models,
        section_detector_backend=section_detector_backend,
        multi_recipe_splitter=multi_recipe_splitter,
        multi_recipe_trace=multi_recipe_trace,
        multi_recipe_min_ingredient_lines=multi_recipe_min_ingredient_lines,
        multi_recipe_min_instruction_lines=multi_recipe_min_instruction_lines,
        multi_recipe_for_the_guardrail=multi_recipe_for_the_guardrail,
        instruction_step_segmentation_policy=instruction_step_segmentation_policy,
        instruction_step_segmenter=instruction_step_segmenter,
        web_schema_extractor=web_schema_extractor,
        web_schema_normalizer=web_schema_normalizer,
        web_html_text_extractor=web_html_text_extractor,
        web_schema_policy=web_schema_policy,
        web_schema_min_confidence=web_schema_min_confidence,
        web_schema_min_ingredients=web_schema_min_ingredients,
        web_schema_min_instruction_steps=web_schema_min_instruction_steps,
        ingredient_text_fix_backend=ingredient_text_fix_backend,
        ingredient_pre_normalize_mode=ingredient_pre_normalize_mode,
        ingredient_packaging_mode=ingredient_packaging_mode,
        ingredient_parser_backend=ingredient_parser_backend,
        ingredient_unit_canonicalizer=ingredient_unit_canonicalizer,
        ingredient_missing_unit_policy=ingredient_missing_unit_policy,
        p6_time_backend=p6_time_backend,
        p6_time_total_strategy=p6_time_total_strategy,
        p6_temperature_backend=p6_temperature_backend,
        p6_temperature_unit_backend=p6_temperature_unit_backend,
        p6_ovenlike_mode=p6_ovenlike_mode,
        p6_yield_mode=p6_yield_mode,
        p6_emit_metadata_debug=p6_emit_metadata_debug,
        recipe_scorer_backend=recipe_scorer_backend,
        recipe_score_gold_min=recipe_score_gold_min,
        recipe_score_silver_min=recipe_score_silver_min,
        recipe_score_bronze_min=recipe_score_bronze_min,
        recipe_score_min_ingredient_lines=recipe_score_min_ingredient_lines,
        recipe_score_min_instruction_lines=recipe_score_min_instruction_lines,
        llm_recipe_pipeline=llm_recipe_pipeline,
        codex_farm_cmd=codex_farm_cmd,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
        codex_farm_pipeline_pass1=codex_farm_pipeline_pass1,
        codex_farm_pipeline_pass2=codex_farm_pipeline_pass2,
        codex_farm_pipeline_pass3=codex_farm_pipeline_pass3,
        codex_farm_context_blocks=codex_farm_context_blocks,
        codex_farm_recipe_mode=codex_farm_recipe_mode,
        codex_farm_failure_mode=codex_farm_failure_mode,
        processed_output_root=processed_output_root,
        split_phase_slots=split_phase_slots,
        split_phase_gate_dir=split_phase_gate_dir,
        split_phase_status_label=split_phase_status_label,
        single_offline_split_cache_mode=single_offline_split_cache_mode,
        single_offline_split_cache_dir=single_offline_split_cache_dir,
        single_offline_split_cache_key=single_offline_split_cache_key,
        single_offline_split_cache_force=single_offline_split_cache_force,
        prelabel=prelabel,
        prelabel_provider=prelabel_provider,
        codex_cmd=codex_cmd,
        codex_model=codex_model,
        codex_reasoning_effort=codex_reasoning_effort,
        prelabel_timeout_seconds=prelabel_timeout_seconds,
        prelabel_cache_dir=prelabel_cache_dir,
        prelabel_workers=prelabel_workers,
        prelabel_granularity=prelabel_granularity,
        prelabel_allow_partial=prelabel_allow_partial,
        prelabel_track_token_usage=prelabel_track_token_usage,
        scheduler_event_callback=scheduler_event_callback,
        progress_callback=_notify,
        run_manifest_kind="labelstudio_import",
    )

    run_root = pred["run_root"]
    tasks = pred["tasks"]
    label_config = pred["label_config"]
    upload_as = _normalize_prelabel_upload_as(prelabel_upload_as)

    # Label Studio upload
    client = LabelStudioClient(label_studio_url, label_studio_api_key)
    _notify("Resolving Label Studio project...")
    project_title = _resolve_project_name(path, project_name, client)

    existing_project = client.find_project_by_title(project_title)
    if overwrite and existing_project:
        client.delete_project(existing_project["id"])
        existing_project = None

    had_existing_project = existing_project is not None
    project = existing_project
    if project is None:
        project = client.create_project(
            project_title,
            label_config,
            description="Cookbook benchmarking project (auto-generated)",
        )

    project_id = project.get("id")
    if project_id is None:
        raise RuntimeError("Label Studio project creation failed (missing id).")

    supported_scope = "freeform-spans"
    existing_task_ids: set[str] = set()
    resume_source: str | None = None
    if resume and not overwrite and had_existing_project:
        _notify("Checking resume metadata for existing tasks...")
        manifest_path = _find_latest_manifest(output_dir, project_title)
        if manifest_path and manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            resume_scope = str(payload.get("task_scope") or supported_scope)
            if resume_scope != supported_scope:
                if auto_project_name_on_scope_mismatch and project_name is None:
                    _notify(
                        f"Existing project uses task_scope={resume_scope}; "
                        f"creating a new project for task_scope={supported_scope}."
                    )
                    existing_titles = {
                        str(candidate.get("title", ""))
                        for candidate in client.list_projects()
                        if isinstance(candidate, dict) and candidate.get("title")
                    }
                    project_title = _dedupe_project_name(project_title, existing_titles)
                    project = client.create_project(
                        project_title,
                        label_config,
                        description="Cookbook benchmarking project (auto-generated)",
                    )
                    project_id = project.get("id")
                    if project_id is None:
                        raise RuntimeError("Label Studio project creation failed (missing id).")
                    had_existing_project = False
                else:
                    raise RuntimeError(
                        f"Existing project uses task_scope={resume_scope}; "
                        "use a freeform-spans project or a new project name."
                    )
            else:
                resume_source = str(manifest_path)
                existing_task_ids = set(
                    payload.get("segment_ids")
                    or payload.get("task_ids")
                    or []
                )
                tasks_path = manifest_path.parent / "label_studio_tasks.jsonl"
                if not existing_task_ids and tasks_path.exists():
                    existing_task_ids = _load_task_ids_from_jsonl(tasks_path, _task_id_key())

    upload_tasks: list[dict[str, Any]] = []
    for task in tasks:
        task_id = _task_id_value(task)
        if task_id and task_id in existing_task_ids:
            continue
        if prelabel and upload_as == "predictions":
            upload_tasks.append(_annotations_to_predictions(task))
        else:
            upload_tasks.append(task)

    batch_size = 200
    uploaded_count = 0
    inline_annotation_fallback = False
    inline_annotation_fallback_error: str | None = None
    post_import_annotation_pairs: list[tuple[str, dict[str, Any]]] = []
    post_import_annotations_created = 0
    post_import_annotation_errors: list[str] = []
    if upload_tasks:
        total_batches = (len(upload_tasks) + batch_size - 1) // batch_size
        _notify(f"Uploading {len(upload_tasks)} task(s) in {total_batches} batch(es)...")
    else:
        _notify("No new tasks to upload (resume skipped existing tasks).")
    for start in range(0, len(upload_tasks), batch_size):
        batch = upload_tasks[start : start + batch_size]
        if not batch:
            continue
        use_inline_annotations = (
            prelabel
            and upload_as == "annotations"
        )
        if use_inline_annotations:
            if inline_annotation_fallback:
                client.import_tasks(
                    project_id,
                    [_strip_task_annotations(task) for task in batch],
                )
                post_import_annotation_pairs.extend(
                    _task_annotation_pairs_for_upload(batch)
                )
            else:
                try:
                    client.import_tasks(project_id, batch)
                except Exception as exc:  # noqa: BLE001
                    inline_annotation_fallback = True
                    inline_annotation_fallback_error = str(exc)
                    _notify(
                        "Inline annotation import failed; retrying with "
                        "task-only upload and post-import annotation creation."
                    )
                    client.import_tasks(
                        project_id,
                        [_strip_task_annotations(task) for task in batch],
                    )
                    post_import_annotation_pairs.extend(
                        _task_annotation_pairs_for_upload(batch)
                    )
        else:
            client.import_tasks(project_id, batch)
        uploaded_count += len(batch)
        _notify(f"Uploaded {uploaded_count}/{len(upload_tasks)} task(s).")

    if inline_annotation_fallback and post_import_annotation_pairs:
        _notify("Resolving task IDs for post-import annotation creation...")
        remote_tasks = client.list_project_tasks(project_id)
        remote_task_ids: dict[str, int] = {}
        for remote_task in remote_tasks:
            if not isinstance(remote_task, dict):
                continue
            task_id = _task_id_value(remote_task)
            if not task_id:
                continue
            remote_id = remote_task.get("id")
            try:
                remote_task_ids[task_id] = int(remote_id)
            except (TypeError, ValueError):
                continue

        _notify(
            f"Creating {len(post_import_annotation_pairs)} annotation(s) "
            "through Label Studio API..."
        )
        for task_id_value, annotation in post_import_annotation_pairs:
            labelstudio_task_id = remote_task_ids.get(task_id_value)
            if labelstudio_task_id is None:
                post_import_annotation_errors.append(
                    f"task id lookup failed for {task_id_value}"
                )
                continue
            try:
                client.create_annotation(labelstudio_task_id, annotation)
                post_import_annotations_created += 1
            except Exception as exc:  # noqa: BLE001
                post_import_annotation_errors.append(
                    f"task {task_id_value}: {exc}"
                )

        if post_import_annotation_errors:
            if prelabel_allow_partial:
                _notify(
                    "Warning: some post-import annotations failed and were skipped."
                )
            else:
                joined = "; ".join(post_import_annotation_errors[:8])
                raise RuntimeError(
                    "Post-import annotation creation failed: "
                    + joined
                )

    # Update manifest with LS-specific fields
    manifest_path = pred["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "project_name": project_title,
        "project_id": project_id,
        "uploaded_task_count": uploaded_count,
        "resume_source": resume_source,
        "label_studio_url": label_studio_url,
        "prelabel_enabled": bool(prelabel),
        "prelabel_upload_as": upload_as if prelabel else None,
        "prelabel_inline_annotations_fallback": inline_annotation_fallback,
        "prelabel_inline_annotations_fallback_error": inline_annotation_fallback_error,
        "prelabel_post_import_annotations_created": post_import_annotations_created,
        "prelabel_post_import_annotation_error_count": len(post_import_annotation_errors),
    })
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    project_path = run_root / "project.json"
    project_path.write_text(
        json.dumps(project, indent=2, sort_keys=True), encoding="utf-8"
    )
    run_config_payload = pred.get("run_config")
    if not isinstance(run_config_payload, dict):
        run_config_payload = {}
    run_manifest_artifacts: dict[str, Any] = {
        "tasks_jsonl": "label_studio_tasks.jsonl",
        "prediction_manifest_json": "manifest.json",
        "coverage_json": "coverage.json",
        "extracted_archive_json": "extracted_archive.json",
        "extracted_text": "extracted_text.txt",
        "project_json": "project.json",
        "label_studio_project_name": project_title,
        "label_studio_project_id": project_id,
        "uploaded_task_count": uploaded_count,
        "prelabel_enabled": bool(prelabel),
        "prelabel_upload_as": upload_as if prelabel else None,
        "prelabel_inline_annotations_fallback": inline_annotation_fallback,
        "prelabel_post_import_annotations_created": post_import_annotations_created,
        "prelabel_post_import_annotation_error_count": len(post_import_annotation_errors),
    }
    prelabel_report_manifest_path = _path_for_manifest(
        run_root,
        pred.get("prelabel_report_path"),
    )
    if prelabel_report_manifest_path:
        run_manifest_artifacts["prelabel_report_json"] = prelabel_report_manifest_path
    prelabel_errors_manifest_path = _path_for_manifest(
        run_root,
        pred.get("prelabel_errors_path"),
    )
    if prelabel_errors_manifest_path:
        run_manifest_artifacts["prelabel_errors_jsonl"] = prelabel_errors_manifest_path
    prelabel_prompt_log_manifest_path = _path_for_manifest(
        run_root,
        pred.get("prelabel_prompt_log_path"),
    )
    if prelabel_prompt_log_manifest_path:
        run_manifest_artifacts["prelabel_prompt_log_md"] = (
            prelabel_prompt_log_manifest_path
        )
    processed_run_manifest_path = _path_for_manifest(run_root, pred.get("processed_run_root"))
    if processed_run_manifest_path:
        run_manifest_artifacts["processed_output_run_dir"] = processed_run_manifest_path
    processed_report_manifest_path = _path_for_manifest(
        run_root,
        pred.get("processed_report_path"),
    )
    if processed_report_manifest_path:
        run_manifest_artifacts["processed_report_json"] = processed_report_manifest_path
    prediction_timing = pred.get("timing")
    if isinstance(prediction_timing, dict):
        run_manifest_artifacts["timing"] = dict(prediction_timing)

    run_manifest_payload = RunManifest(
        run_kind="labelstudio_import",
        run_id=run_root.name,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        source=RunSource(
            path=str(path),
            source_hash=str(pred.get("file_hash") or "") or None,
            importer_name=str(pred.get("importer_name") or "") or None,
        ),
        run_config=run_config_payload,
        artifacts=run_manifest_artifacts,
        notes="Label Studio import run with upload metadata.",
    )
    _write_manifest_best_effort(run_root, run_manifest_payload, notify=_notify)
    _notify("Label Studio import artifacts complete.")

    return {
        "project": project,
        "project_name": project_title,
        "project_id": project_id,
        "run_root": run_root,
        "processed_run_root": pred["processed_run_root"],
        "processed_report_path": pred["processed_report_path"],
        "run_config": pred.get("run_config"),
        "run_config_hash": pred.get("run_config_hash"),
        "run_config_summary": pred.get("run_config_summary"),
        "timing": pred.get("timing"),
        "prelabel": pred.get("prelabel"),
        "prelabel_report_path": pred.get("prelabel_report_path"),
        "prelabel_errors_path": pred.get("prelabel_errors_path"),
        "prelabel_prompt_log_path": pred.get("prelabel_prompt_log_path"),
        "prelabel_upload_as": upload_as if prelabel else None,
        "prelabel_inline_annotations_fallback": inline_annotation_fallback,
        "prelabel_post_import_annotations_created": post_import_annotations_created,
        "prelabel_post_import_annotation_errors": post_import_annotation_errors,
        "tasks_total": pred["tasks_total"],
        "tasks_uploaded": uploaded_count,
        "manifest_path": manifest_path,
    }
