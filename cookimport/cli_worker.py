from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import multiprocessing
import os
import pickle
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cookimport.config.run_settings import (
    RUN_SETTING_CONTRACT_FULL,
    RunSettings,
    project_run_config_payload,
)
from cookimport.core.models import ConversionReport, MappingConfig
from cookimport.core.slug import slugify_name
from cookimport.core.reporting import compute_file_hash
from cookimport.core.timing import TimingStats, measure
from cookimport.plugins import registry
# Ensure plugins are registered in workers
from cookimport.plugins import excel, text, epub, pdf, recipesage, paprika, webschema  # noqa: F401
from cookimport.staging.job_planning import JobSpec
from cookimport.staging.writer import write_raw_artifacts

logger = logging.getLogger(__name__)

_STAGE_WORKER_REQUEST_ARG = "--stage-worker-request"
_STAGE_WORKER_SELF_TEST_ARG = "--stage-worker-self-test"


@contextmanager
def _temporary_epub_extractor(value: str | None):
    if not value:
        yield
        return
    previous = os.environ.get("C3IMP_EPUB_EXTRACTOR")
    os.environ["C3IMP_EPUB_EXTRACTOR"] = str(value)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("C3IMP_EPUB_EXTRACTOR", None)
        else:
            os.environ["C3IMP_EPUB_EXTRACTOR"] = previous

def _worker_label() -> str:
    process_label = f"{multiprocessing.current_process().name} ({os.getpid()})"
    thread_name = str(threading.current_thread().name or "").strip()
    if thread_name and thread_name != "MainThread":
        return f"{process_label} / {thread_name}"
    return process_label

def _safe_progress_put(progress_queue: Any | None, payload: tuple[Any, ...]) -> None:
    if not progress_queue:
        return
    try:
        put_nowait = getattr(progress_queue, "put_nowait", None)
        if callable(put_nowait):
            put_nowait(payload)
            return
        progress_queue.put(payload, block=False)
    except Exception:
        # Best-effort progress only; never block worker execution.
        pass

def _build_progress_reporter(
    progress_queue: Any | None,
    display_label: str,
    *,
    heartbeat_seconds: float = 5.0,
) -> tuple[str, Any, threading.Event, threading.Thread]:
    worker_label = _worker_label()
    last_message = {"text": "Starting job..."}
    stop_event = threading.Event()

    def _emit(msg: str) -> None:
        _safe_progress_put(
            progress_queue,
            (worker_label, display_label, msg, dt.datetime.now().timestamp()),
        )

    def report(msg: str) -> None:
        last_message["text"] = msg
        _emit(msg)

    def heartbeat() -> None:
        while not stop_event.wait(heartbeat_seconds):
            _emit(last_message["text"])

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    return worker_label, report, stop_event, thread

def apply_result_limits(
    result: Any,
    recipe_limit: int | None,
    *,
    limit_label: int | None = None,
) -> tuple[int, bool]:
    original_recipes = len(result.recipes)

    if recipe_limit is not None:
        result.recipes = result.recipes[: max(recipe_limit, 0)]

    result.report.total_recipes = len(result.recipes)

    truncated = len(result.recipes) < original_recipes
    if truncated:
        parts = []
        if len(result.recipes) < original_recipes:
            parts.append(f"{len(result.recipes)} of {original_recipes} recipes")
        limit_prefix = f"Limit {limit_label} applied. " if limit_label is not None else "Limit applied. "
        result.report.warnings.append(f"{limit_prefix}Output truncated to {', '.join(parts)}.")

    return len(result.recipes), truncated


def _run_import(
    file_path: Path,
    mapping_config: MappingConfig | None,
    progress_callback: Any | None = None,
    *,
    run_settings: RunSettings | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
    start_spine: int | None = None,
    end_spine: int | None = None,
) -> tuple[Any, TimingStats, MappingConfig | None]:
    file_stats = TimingStats()

    importer, score = registry.best_importer_for_path(file_path)
    if importer is None or score <= 0:
        raise ValueError("No importer")

    resolved_mapping = mapping_config
    if resolved_mapping is None:
        if progress_callback:
            progress_callback("Inspecting file structure...")
        inspection = importer.inspect(file_path)
        resolved_mapping = inspection.mapping_stub

    with measure(file_stats, "parsing"):
        if start_page is not None or end_page is not None:
            if importer.name != "pdf":
                raise ValueError("Page range provided for non-PDF importer")
            result = importer.convert(
                file_path,
                resolved_mapping,
                progress_callback=progress_callback,
                run_settings=run_settings,
                start_page=start_page,
                end_page=end_page,
            )
        elif start_spine is not None or end_spine is not None:
            if importer.name != "epub":
                raise ValueError("Spine range provided for non-EPUB importer")
            result = importer.convert(
                file_path,
                resolved_mapping,
                progress_callback=progress_callback,
                run_settings=run_settings,
                start_spine=start_spine,
                end_spine=end_spine,
            )
        else:
            result = importer.convert(
                file_path,
                resolved_mapping,
                progress_callback=progress_callback,
                run_settings=run_settings,
            )

    return result, file_stats, resolved_mapping

def execute_source_job(
    job: JobSpec,
    out: Path,
    mapping_config: MappingConfig | None,
    run_dt: dt.datetime,
    progress_queue: Any | None = None,
    display_name: str | None = None,
    epub_extractor: str | None = None,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
) -> dict[str, Any]:
    """Process one planned source job and return a mergeable payload."""

    file_path = job.file_path
    display_label = display_name or job.display_name
    worker_label, _report_progress, stop_event, heartbeat_thread = _build_progress_reporter(
        progress_queue,
        display_label,
    )

    importer, score = registry.best_importer_for_path(file_path)
    if importer is None or score <= 0:
        return {
            "file": file_path.name,
            "status": "skipped",
            "reason": "No importer",
            "importer_name": None,
            "job_index": job.job_index,
            "job_count": job.job_count,
            "start_page": job.start_page,
            "end_page": job.end_page,
            "start_spine": job.start_spine,
            "end_spine": job.end_spine,
            "worker_label": worker_label,
        }

    try:
        start_total = dt.datetime.now()
        run_settings = RunSettings.from_dict(
            project_run_config_payload(run_config, contract=RUN_SETTING_CONTRACT_FULL),
            warn_context="stage run config",
        )

        # Note: mapping_config is already passed in and overridden by CLI if needed
        _report_progress("Starting file...")
        _report_progress("Parsing recipes...")
        with _temporary_epub_extractor(epub_extractor):
            result, file_stats, resolved_mapping = _run_import(
                file_path,
                mapping_config,
                _report_progress,
                run_settings=run_settings,
                start_page=job.start_page,
                end_page=job.end_page,
                start_spine=job.start_spine,
                end_spine=job.end_spine,
            )

        workbook_slug = slugify_name(file_path.stem)
        job_root = out / ".job_parts" / workbook_slug / f"job_{job.job_index}"

        with measure(file_stats, "writing"):
            _report_progress("Writing raw artifacts...")
            write_raw_artifacts(result, job_root)

        _ = resolved_mapping
        result.report.importer_name = importer.name
        if run_config is not None:
            result.report.run_config = dict(run_config)
        result.report.run_config_hash = run_config_hash
        result.report.run_config_summary = run_config_summary
        result.raw_artifacts = []
        file_stats.total_seconds = (dt.datetime.now() - start_total).total_seconds()

        _report_progress("Done")

        return {
            "file": file_path.name,
            "status": "success",
            "recipes": len(result.recipes),
            "duration": file_stats.total_seconds,
            "timing": file_stats.to_dict(),
            "importer_name": importer.name,
            "job_index": job.job_index,
            "job_count": job.job_count,
            "start_page": job.start_page,
            "end_page": job.end_page,
            "start_spine": job.start_spine,
            "end_spine": job.end_spine,
            "result": result,
            "worker_label": worker_label,
        }
    except Exception as exc:
        _report_progress(f"Error: {exc}")
        return {
            "file": file_path.name,
            "status": "error",
            "reason": str(exc),
            "importer_name": importer.name,
            "job_index": job.job_index,
            "job_count": job.job_count,
            "start_page": job.start_page,
            "end_page": job.end_page,
            "start_spine": job.start_spine,
            "end_spine": job.end_spine,
            "worker_label": worker_label,
        }
    finally:
        stop_event.set()
        if heartbeat_thread.is_alive():
            heartbeat_thread.join(timeout=0.5)


def _run_stage_worker_request(request_path: Path) -> int:
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid stage worker request payload.")

    result_path_raw = str(payload.get("result_path") or "").strip()
    if not result_path_raw:
        raise ValueError("Stage worker request is missing result_path.")
    result_path = Path(result_path_raw).expanduser()
    result_path.parent.mkdir(parents=True, exist_ok=True)

    job_payload_raw = payload.get("job")
    job_payload = dict(job_payload_raw) if isinstance(job_payload_raw, dict) else {}
    job_kind = str(job_payload.get("job_kind") or "").strip()

    file_path = Path(str(job_payload.get("file_path") or "")).expanduser()
    out_path = Path(str(job_payload.get("out_path") or "")).expanduser()
    job = JobSpec.from_payload(job_payload)
    display_name = str(job_payload.get("display_name") or "").strip() or job.display_name

    mapping_payload_raw = job_payload.get("mapping_config")
    mapping_payload = (
        dict(mapping_payload_raw) if isinstance(mapping_payload_raw, dict) else None
    )
    mapping_config = (
        MappingConfig.model_validate(mapping_payload)
        if isinstance(mapping_payload, dict)
        else None
    )

    run_dt_raw = str(job_payload.get("run_dt") or "").strip()
    if not run_dt_raw:
        raise ValueError("Stage worker request is missing run_dt.")
    run_dt = dt.datetime.fromisoformat(run_dt_raw)

    run_config_raw = job_payload.get("run_config")
    run_config = dict(run_config_raw) if isinstance(run_config_raw, dict) else None
    run_config_hash = str(job_payload.get("run_config_hash") or "").strip() or None
    run_config_summary = (
        str(job_payload.get("run_config_summary") or "").strip() or None
    )

    if job_kind == "source_job":
        epub_extractor = str(job_payload.get("epub_extractor") or "").strip() or None
        result = execute_source_job(
            job=job,
            out=out_path,
            mapping_config=mapping_config,
            run_dt=run_dt,
            progress_queue=None,
            display_name=display_name,
            epub_extractor=epub_extractor,
            run_config=run_config,
            run_config_hash=run_config_hash,
            run_config_summary=run_config_summary,
        )
    else:
        raise ValueError(f"Unsupported stage worker job kind: {job_kind or '<empty>'}")

    with result_path.open("wb") as handle:
        pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return 0


def _build_worker_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cookimport.cli_worker",
        add_help=True,
    )
    parser.add_argument(
        _STAGE_WORKER_REQUEST_ARG,
        dest="stage_worker_request",
        type=str,
        default="",
        help="Internal worker mode: run one stage job from a request JSON file.",
    )
    parser.add_argument(
        _STAGE_WORKER_SELF_TEST_ARG,
        dest="stage_worker_self_test",
        action="store_true",
        help="Internal probe mode for stage subprocess worker availability.",
    )
    return parser


def _main(argv: list[str] | None = None) -> int:
    parser = _build_worker_cli_parser()
    args = parser.parse_args(argv)
    if bool(getattr(args, "stage_worker_self_test", False)):
        return 0
    request_path_raw = str(getattr(args, "stage_worker_request", "") or "").strip()
    if not request_path_raw:
        parser.error(
            f"{_STAGE_WORKER_REQUEST_ARG} is required when invoking this module directly."
        )
    return _run_stage_worker_request(Path(request_path_raw).expanduser())


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
