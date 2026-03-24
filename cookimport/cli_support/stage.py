from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import typer

from cookimport import cli_support as runtime
from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings_contracts import (
    RUN_SETTING_CONTRACT_FULL,
    project_run_config_payload,
)
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.progress_messages import format_phase_counter
from cookimport.core.reporting import compute_file_hash
from cookimport.core.slug import slugify_name
from cookimport.core.source_model import (
    normalize_source_blocks,
    offset_source_blocks,
    offset_source_support,
)
from cookimport.core.timing import TimingStats
from cookimport.llm import prompt_artifacts as llm_prompt_artifacts
from cookimport.paths import history_csv_for_output
from cookimport.plugins import registry
from cookimport.runs import (
    RunManifest,
    RunSource,
    build_stage_observability_report,
    load_stage_observability_report,
    write_eval_run_manifest as _write_eval_manifest_file,
    write_run_manifest,
    write_stage_observability_report,
)
from cookimport.staging.import_session import execute_stage_import_session_from_result
from cookimport.staging.writer import (
    NONRECIPE_AUTHORITY_FILE_NAME,
    NONRECIPE_REVIEW_EXCLUSIONS_FILE_NAME,
    NONRECIPE_REVIEW_STATUS_FILE_NAME,
    NONRECIPE_SEED_ROUTING_FILE_NAME,
    OutputStats,
    write_report,
)

logger = logging.getLogger(__name__)
PROCESSING_TIMESERIES_FILENAME = "processing_timeseries.jsonl"
OUTPUT_STATS_CATEGORY_RAW = "rawArtifacts"


def _path_for_manifest(run_root: Path, path_like: Path | str | None) -> str | None:
    if path_like is None:
        return None
    candidate = Path(path_like)
    try:
        return str(candidate.relative_to(run_root))
    except ValueError:
        return str(candidate)


def _write_stage_observability_best_effort(
    *,
    run_root: Path,
    run_kind: str,
    run_dt: dt.datetime,
    run_config: dict[str, Any] | None,
) -> Path | None:
    try:
        report = build_stage_observability_report(
            run_root=run_root,
            run_kind=run_kind,
            created_at=run_dt.isoformat(timespec="seconds"),
            run_config=run_config,
        )
        return write_stage_observability_report(run_root=run_root, report=report)
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Warning: failed to write stage_observability.json in {run_root}: {exc}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        logger.warning("Failed to write stage_observability.json in %s: %s", run_root, exc)
        return None


def _load_stage_observability_payload(run_root: Path) -> dict[str, Any]:
    path = run_root / "stage_observability.json"
    if not path.exists():
        return {}
    try:
        report = load_stage_observability_report(path)
    except Exception:  # noqa: BLE001
        return {}
    return report.model_dump(exclude_none=True)


def _write_run_manifest_best_effort(run_root: Path, manifest: RunManifest) -> None:
    try:
        write_run_manifest(run_root, manifest)
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Warning: failed to write run_manifest.json in {run_root}: {exc}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        logger.warning("Failed to write run_manifest.json in %s: %s", run_root, exc)


def _write_stage_run_manifest(
    *,
    run_root: Path,
    output_root: Path,
    requested_path: Path,
    run_dt: dt.datetime,
    run_config: dict[str, Any],
) -> None:
    report_paths = sorted(run_root.glob("*.excel_import_report.json"))
    importer_name: str | None = None
    if report_paths:
        try:
            report_payload = json.loads(report_paths[0].read_text(encoding="utf-8"))
            if isinstance(report_payload, dict):
                importer_name = str(report_payload.get("importerName") or "").strip() or None
        except (OSError, json.JSONDecodeError):
            importer_name = None

    source_hash: str | None = None
    if requested_path.is_file():
        try:
            source_hash = compute_file_hash(requested_path)
        except Exception as exc:  # noqa: BLE001
            typer.secho(
                f"Warning: failed to compute source hash for run manifest: {exc}",
                fg=typer.colors.YELLOW,
                err=True,
            )

    artifacts: dict[str, Any] = {}
    if report_paths:
        artifacts["reports"] = [path.name for path in report_paths]
    for path_name, artifact_key in (
        (NONRECIPE_SEED_ROUTING_FILE_NAME, "nonrecipe_seed_routing_json"),
        (NONRECIPE_REVIEW_EXCLUSIONS_FILE_NAME, "nonrecipe_review_exclusions_jsonl"),
        (NONRECIPE_AUTHORITY_FILE_NAME, "nonrecipe_authority_json"),
        (NONRECIPE_REVIEW_STATUS_FILE_NAME, "nonrecipe_review_status_json"),
    ):
        target = run_root / path_name
        if target.exists():
            artifacts[artifact_key] = path_name
    for path_key, artifact_key in (
        ("label_det", "label_det_dir"),
        ("label_llm_correct", "label_llm_correct_dir"),
        ("group_recipe_spans", "group_recipe_spans_dir"),
        ("intermediate drafts", "intermediate_drafts_dir"),
        ("final drafts", "final_drafts_dir"),
        ("chunks", "chunks_dir"),
        ("knowledge", "knowledge_dir"),
        (".bench", "bench_dir"),
        ("raw", "raw_dir"),
    ):
        target = run_root / path_key
        if target.exists():
            artifacts[artifact_key] = path_key
    bench_prediction_paths = sorted(run_root.glob(".bench/**/stage_block_predictions.json"))
    if bench_prediction_paths:
        artifacts["stage_block_predictions"] = [
            str(path.relative_to(run_root))
            for path in bench_prediction_paths
        ]
    knowledge_index = run_root / "knowledge" / "knowledge_index.json"
    if knowledge_index.exists():
        artifacts["knowledge_index"] = str(knowledge_index.relative_to(run_root))
    processing_timeseries = run_root / PROCESSING_TIMESERIES_FILENAME
    if processing_timeseries.exists():
        artifacts["processing_timeseries_jsonl"] = str(processing_timeseries.relative_to(run_root))
    stage_observability_json = run_root / "stage_observability.json"
    if stage_observability_json.exists():
        artifacts["stage_observability_json"] = str(stage_observability_json.relative_to(run_root))
    run_summary_json = run_root / "run_summary.json"
    if run_summary_json.exists():
        artifacts["run_summary_json"] = str(run_summary_json.relative_to(run_root))
    run_summary_md = run_root / "run_summary.md"
    if run_summary_md.exists():
        artifacts["run_summary_md"] = str(run_summary_md.relative_to(run_root))
    stage_worker_resolution = run_root / "stage_worker_resolution.json"
    if stage_worker_resolution.exists():
        artifacts["stage_worker_resolution_json"] = str(stage_worker_resolution.relative_to(run_root))
    prompt_artifacts_dir = run_root / "prompts"
    if prompt_artifacts_dir.exists() and prompt_artifacts_dir.is_dir():
        artifacts["prompts_dir"] = str(prompt_artifacts_dir.relative_to(run_root))
        prompt_request_response_path = prompt_artifacts_dir / "prompt_request_response_log.txt"
        if prompt_request_response_path.exists() and prompt_request_response_path.is_file():
            artifacts["prompt_request_response_txt"] = str(
                prompt_request_response_path.relative_to(run_root)
            )
        category_manifest_path = prompt_artifacts_dir / "prompt_category_logs_manifest.txt"
        if category_manifest_path.exists() and category_manifest_path.is_file():
            artifacts["prompt_category_logs_manifest_txt"] = str(
                category_manifest_path.relative_to(run_root)
            )
        full_prompt_log_path = prompt_artifacts_dir / "full_prompt_log.jsonl"
        if full_prompt_log_path.exists() and full_prompt_log_path.is_file():
            artifacts["full_prompt_log_jsonl"] = str(full_prompt_log_path.relative_to(run_root))
        prompt_log_summary_path = (
            prompt_artifacts_dir / llm_prompt_artifacts.PROMPT_LOG_SUMMARY_JSON_NAME
        )
        if prompt_log_summary_path.exists() and prompt_log_summary_path.is_file():
            artifacts["prompt_log_summary_json"] = str(prompt_log_summary_path.relative_to(run_root))
        prompt_type_samples_path = (
            prompt_artifacts_dir / llm_prompt_artifacts.PROMPT_TYPE_SAMPLES_MD_NAME
        )
        if prompt_type_samples_path.exists() and prompt_type_samples_path.is_file():
            artifacts["prompt_type_samples_from_full_prompt_log_md"] = str(
                prompt_type_samples_path.relative_to(run_root)
            )
        thinking_trace_summary_jsonl_path = (
            prompt_artifacts_dir / llm_prompt_artifacts.THINKING_TRACE_SUMMARY_JSONL_NAME
        )
        if thinking_trace_summary_jsonl_path.exists() and thinking_trace_summary_jsonl_path.is_file():
            artifacts["thinking_trace_summary_jsonl"] = str(
                thinking_trace_summary_jsonl_path.relative_to(run_root)
            )
        thinking_trace_summary_md_path = (
            prompt_artifacts_dir / llm_prompt_artifacts.THINKING_TRACE_SUMMARY_MD_NAME
        )
        if thinking_trace_summary_md_path.exists() and thinking_trace_summary_md_path.is_file():
            artifacts["thinking_trace_summary_md"] = str(
                thinking_trace_summary_md_path.relative_to(run_root)
            )
    history_csv = history_csv_for_output(output_root)
    if history_csv.exists():
        artifacts["history_csv"] = str(history_csv)

    manifest = RunManifest(
        run_kind="stage",
        run_id=run_root.name,
        created_at=run_dt.isoformat(timespec="seconds"),
        source=RunSource(
            path=str(requested_path),
            source_hash=source_hash,
            importer_name=importer_name,
        ),
        run_config=run_config,
        artifacts=artifacts,
        notes="Stage run outputs for cookbook import.",
    )
    _write_run_manifest_best_effort(run_root, manifest)


def _write_knowledge_index_best_effort(run_root: Path) -> None:
    knowledge_root = run_root / "knowledge"
    if not knowledge_root.exists():
        return
    workbooks: dict[str, dict[str, Any]] = {}
    total_snippets = 0
    for workbook_dir in sorted(path for path in knowledge_root.iterdir() if path.is_dir()):
        snippets_path = workbook_dir / "snippets.jsonl"
        preview_path = workbook_dir / "knowledge.md"
        if not snippets_path.exists() and not preview_path.exists():
            continue
        snippets_count = 0
        if snippets_path.exists():
            snippets_count = sum(
                1 for line in snippets_path.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        total_snippets += snippets_count
        workbooks[workbook_dir.name] = {
            "snippets": snippets_count,
            "snippets_path": str(snippets_path.relative_to(run_root)) if snippets_path.exists() else None,
            "preview_path": str(preview_path.relative_to(run_root)) if preview_path.exists() else None,
        }
    if not workbooks:
        return
    index_path = knowledge_root / "knowledge_index.json"
    index_payload = {
        "version": 1,
        "total_snippets": total_snippets,
        "workbooks": workbooks,
    }
    try:
        index_path.write_text(
            json.dumps(index_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write knowledge_index.json in %s: %s", knowledge_root, exc)


def _write_eval_run_manifest(
    *,
    run_root: Path,
    run_kind: str,
    source_path: str | None,
    source_hash: str | None,
    importer_name: str | None,
    run_config: dict[str, Any],
    artifacts: dict[str, Any],
    notes: str | None = None,
) -> None:
    try:
        _write_eval_manifest_file(
            run_root=run_root,
            run_kind=run_kind,
            source_path=source_path,
            source_hash=source_hash,
            importer_name=importer_name,
            run_config=run_config,
            artifacts=artifacts,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Warning: failed to write run_manifest.json in {run_root}: {exc}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        logger.warning("Failed to write run_manifest.json in %s: %s", run_root, exc)


def _require_importer(path: Path):
    importer, score = registry.best_importer_for_path(path)
    if importer is None or score <= 0:
        runtime._fail("No importer available for this path.")
    return importer


def _infer_importer_name_from_source_path(source: str | Path | None) -> str | None:
    if source is None:
        return None
    try:
        suffix = Path(str(source)).suffix.lower()
    except Exception:
        return None
    if suffix == ".epub":
        return "epub"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".doc", ".docx", ".txt", ".md", ".rtf"}:
        return "text"
    if suffix in {".html", ".htm"}:
        return "web"
    return None


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if path.is_file() and not path.name.startswith("."):
            yield path


def _resolve_mapping_path(workbook: Path, out: Path, override: Path | None) -> Path | None:
    if override is not None:
        return override
    sidecar_yaml = workbook.with_suffix(".mapping.yaml")
    sidecar_json = workbook.with_suffix(".mapping.json")
    if sidecar_yaml.exists():
        return sidecar_yaml
    if sidecar_json.exists():
        return sidecar_json
    staged = out / "mappings" / f"{workbook.stem}.mapping.yaml"
    if staged.exists():
        return staged
    return None


def _resolve_overrides_path(workbook: Path, out: Path, override: Path | None) -> Path | None:
    if override is not None:
        return override
    sidecar_yaml = workbook.with_suffix(".overrides.yaml")
    sidecar_json = workbook.with_suffix(".overrides.json")
    if sidecar_yaml.exists():
        return sidecar_yaml
    if sidecar_json.exists():
        return sidecar_json
    staged = out / "overrides" / f"{workbook.stem}.overrides.yaml"
    if staged.exists():
        return staged
    return None


def _merge_raw_artifacts(
    out: Path,
    workbook_slug: str,
    job_results: list[dict[str, Any]],
    *,
    output_stats: OutputStats | None = None,
) -> None:
    job_parts_root = out / ".job_parts" / workbook_slug
    if not job_parts_root.exists():
        return

    for job in job_results:
        job_index = int(job.get("job_index", 0))
        job_raw_root = job_parts_root / f"job_{job_index}" / "raw"
        if not job_raw_root.exists():
            continue
        for raw_path in job_raw_root.rglob("*"):
            if raw_path.is_dir():
                continue
            relative = raw_path.relative_to(job_raw_root)
            target = out / "raw" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target = _prefix_collision(target, job_index)
            shutil.move(str(raw_path), str(target))
            if output_stats is not None:
                output_stats.record_path(OUTPUT_STATS_CATEGORY_RAW, target)

    shutil.rmtree(job_parts_root, ignore_errors=True)
    job_parts_parent = out / ".job_parts"
    try:
        if job_parts_parent.exists() and not any(job_parts_parent.iterdir()):
            job_parts_parent.rmdir()
    except OSError:
        pass


def _prefix_collision(path: Path, job_index: int) -> Path:
    prefix = f"job_{job_index}_"
    candidate = path.with_name(f"{prefix}{path.name}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{prefix}{counter}_{path.name}")
        counter += 1
    return candidate


def _write_error_report(
    out: Path,
    file_path: Path,
    run_dt: dt.datetime,
    errors: list[str],
    *,
    importer_name: str | None = None,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
) -> None:
    report = ConversionReport(
        errors=errors,
        sourceFile=str(file_path),
        importerName=importer_name,
        runTimestamp=run_dt.isoformat(timespec="seconds"),
        runConfig=dict(run_config) if run_config is not None else None,
        runConfigHash=run_config_hash,
        runConfigSummary=run_config_summary,
    )
    write_report(report, out, file_path.stem)


def _job_range_start(job: dict[str, Any]) -> int:
    start_page = job.get("start_page")
    if start_page is not None:
        return int(start_page)
    start_spine = job.get("start_spine")
    if start_spine is not None:
        return int(start_spine)
    return 0


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_non_negative_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _collect_stage_run_report_payloads(run_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for report_path in sorted(run_root.glob("*.excel_import_report.json")):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        payloads.append((report_path, payload))
    return payloads


def _build_stage_run_summary_payload(
    *,
    run_root: Path,
    requested_path: Path,
    run_config: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    reports = _collect_stage_run_report_payloads(run_root)
    stage_observability_payload = _load_stage_observability_payload(run_root)
    observed_stages_raw = stage_observability_payload.get("stages")
    observed_stages = observed_stages_raw if isinstance(observed_stages_raw, list) else []

    totals: dict[str, int] = {
        "recipes": 0,
        "standalone_blocks": 0,
    }
    durations: dict[str, float] = {
        "total_seconds": 0.0,
        "parsing_seconds": 0.0,
        "writing_seconds": 0.0,
        "ocr_seconds": 0.0,
    }

    books: list[dict[str, Any]] = []
    for report_path, payload in reports:
        source_file = str(payload.get("sourceFile") or "").strip()
        book_slug = report_path.name.removesuffix(".excel_import_report.json")
        source_name = Path(source_file).name if source_file else f"{book_slug}"
        timing = payload.get("timing") if isinstance(payload.get("timing"), dict) else {}
        row = {
            "book_slug": book_slug,
            "source_file": source_file or None,
            "book_name": source_name,
            "importer": payload.get("importerName"),
            "recipes": _coerce_int(payload.get("totalRecipes")) or 0,
            "standalone_blocks": _coerce_int(payload.get("totalStandaloneBlocks")) or 0,
            "total_seconds": _coerce_non_negative_float(timing.get("total_seconds")) or 0.0,
            "parsing_seconds": _coerce_non_negative_float(timing.get("parsing_seconds")) or 0.0,
            "writing_seconds": _coerce_non_negative_float(timing.get("writing_seconds")) or 0.0,
            "ocr_seconds": _coerce_non_negative_float(timing.get("ocr_seconds")) or 0.0,
            "report_file": report_path.name,
        }
        books.append(row)
        totals["recipes"] += row["recipes"]
        totals["standalone_blocks"] += row["standalone_blocks"]
        durations["total_seconds"] += row["total_seconds"]
        durations["parsing_seconds"] += row["parsing_seconds"]
        durations["writing_seconds"] += row["writing_seconds"]
        durations["ocr_seconds"] += row["ocr_seconds"]

    codex_recipe = str(run_config.get("llm_recipe_pipeline", "off")).strip().lower()
    codex_knowledge = str(run_config.get("llm_knowledge_pipeline", "off")).strip().lower()
    codex_decision = {
        "context": run_config.get("codex_decision_context"),
        "mode": run_config.get("codex_decision_mode"),
        "allowed": run_config.get("codex_decision_allowed"),
        "explicit_activation_required": run_config.get("codex_decision_explicit_activation_required"),
        "explicit_activation_granted": run_config.get("codex_decision_explicit_activation_granted"),
        "codex_enabled": run_config.get("codex_decision_codex_enabled"),
        "codex_surfaces": run_config.get("codex_decision_codex_surfaces"),
        "deterministic_surfaces": run_config.get("codex_decision_deterministic_surfaces"),
        "summary": run_config.get("codex_decision_summary"),
        "ai_assistance_profile": run_config.get("ai_assistance_profile"),
    }

    return {
        "run_dir": run_root.name,
        "run_root": str(run_root),
        "requested_path": str(requested_path),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "book_count": len(books),
        "error_count": len(errors),
        "observed_stages": observed_stages,
        "books": books,
        "totals": {
            **totals,
            "files_with_reports": len(books),
            "errors": len(errors),
            **durations,
        },
        "major_settings": {
            **project_run_config_payload(run_config, include_internal=False),
            "effective_workers": run_config.get("effective_workers"),
        },
        "codex_farm": {
            "recipe_pipeline": codex_recipe,
            "knowledge_pipeline": codex_knowledge,
            "recipe_enabled": codex_recipe != "off",
            "knowledge_enabled": codex_knowledge != "off",
            "model": run_config.get("codex_farm_model"),
            "reasoning_effort": run_config.get("codex_farm_reasoning_effort"),
        },
        "codex_decision": codex_decision,
    }


def _write_stage_run_summary(
    *,
    run_root: Path,
    requested_path: Path,
    run_config: dict[str, Any],
    errors: list[str],
    write_markdown: bool = True,
) -> dict[str, Any] | None:
    payload = _build_stage_run_summary_payload(
        run_root=run_root,
        requested_path=requested_path,
        run_config=run_config,
        errors=errors,
    )

    run_summary_json = run_root / "run_summary.json"
    run_summary_md = run_root / "run_summary.md"

    try:
        run_summary_json.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Failed to write %s", run_summary_json)

    def _fmt_s(seconds: float | None) -> str:
        if seconds is None:
            return "n/a"
        return f"{seconds:.2f}s"

    totals = payload.get("totals", {})
    major_settings = payload.get("major_settings", {})
    codex = payload.get("codex_farm", {})
    codex_decision = payload.get("codex_decision", {})
    if write_markdown:
        md_lines = [
            "# Stage run summary",
            f"Run: {payload.get('run_dir')}",
            f"Requested: {payload.get('requested_path')}",
            "",
            "## Observed stages",
        ]
        if payload.get("observed_stages"):
            for stage in payload.get("observed_stages", []):
                md_lines.append(
                    "- {label} (`{key}`)".format(
                        label=stage.get("stage_label") or stage.get("stage_key") or "Stage",
                        key=stage.get("stage_key") or "stage",
                    )
                )
        else:
            md_lines.append("- none")

        md_lines.extend(["", "## Books"])
        if payload.get("books"):
            for book in payload.get("books", []):
                md_lines.append(
                    "- {name}: {recipes} recipes, {standalone_blocks} standalone blocks".format(
                        name=book.get("book_name") or book.get("book_slug") or "unknown",
                        recipes=book.get("recipes", 0),
                        standalone_blocks=book.get("standalone_blocks", 0),
                    )
                )
        else:
            md_lines.append("- none")

        md_lines.extend(
            [
                "",
                "## Major settings",
                f"- Codex decision: {codex_decision.get('summary') or 'n/a'}",
                f"- Codex-farm recipe pipeline: {codex.get('recipe_pipeline')}",
                f"- Codex-farm knowledge pipeline: {codex.get('knowledge_pipeline')}",
                f"- workers: {major_settings.get('workers')}",
                f"- effective_workers: {major_settings.get('effective_workers')}",
                f"- epub_extractor: {major_settings.get('epub_extractor')}",
                "",
                "## Topline metrics",
                f"- total recipes: {totals.get('recipes', 0)}",
                f"- total standalone blocks: {totals.get('standalone_blocks', 0)}",
                "- timing total/parsing/writing/ocr: {total}/{parsing}/{writing}/{ocr}".format(
                    total=_fmt_s(totals.get("total_seconds")),
                    parsing=_fmt_s(totals.get("parsing_seconds")),
                    writing=_fmt_s(totals.get("writing_seconds")),
                    ocr=_fmt_s(totals.get("ocr_seconds")),
                ),
                "",
                "## Files",
                f"- reports: {payload.get('totals', {}).get('files_with_reports', 0)}",
                f"- errors: {payload.get('error_count', 0)}",
            ]
        )

        try:
            run_summary_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        except OSError:
            logger.warning("Failed to write %s", run_summary_md)
            return payload
    else:
        run_summary_md.unlink(missing_ok=True)

    return payload


def _print_stage_summary(payload: dict[str, Any], *, write_markdown: bool = True) -> None:
    books = payload.get("books")
    if not isinstance(books, list):
        return
    book_names = [
        str(book.get("book_name") or book.get("book_slug") or "unknown")
        for book in books
    ] if books else []

    totals = payload.get("totals", {})
    codex = payload.get("codex_farm", {})
    major_settings = payload.get("major_settings", {})
    observed_stages = payload.get("observed_stages")
    observed_stage_labels = []
    if isinstance(observed_stages, list):
        observed_stage_labels = [
            str(stage.get("stage_label") or stage.get("stage_key") or "Stage")
            for stage in observed_stages
            if isinstance(stage, dict)
        ]
    run_root = str(payload.get("run_root") or "").strip()
    run_summary_name = "run_summary.md" if write_markdown else "run_summary.json"
    run_summary_path = str(Path(run_root) / run_summary_name) if run_root else f"{payload.get('run_dir')}/{run_summary_name}"

    typer.secho("\nQuick run summary:", fg=typer.colors.CYAN)
    typer.echo(f"  Books ({len(book_names)}): {', '.join(book_names) if book_names else 'none'}")
    typer.echo("  Observed stages: " + (", ".join(observed_stage_labels) if observed_stage_labels else "none"))
    typer.echo(
        "  Codex-farm (recipe/knowledge): {recipe}/{knowledge}".format(
            recipe=codex.get("recipe_pipeline", "off"),
            knowledge=codex.get("knowledge_pipeline", "off"),
        )
    )
    typer.echo(
        "  Settings: workers={workers} effective_workers={effective_workers} epub_extractor={epub_extractor}".format(
            workers=major_settings.get("workers"),
            effective_workers=major_settings.get("effective_workers"),
            epub_extractor=major_settings.get("epub_extractor"),
        )
    )
    typer.echo(
        "  Totals: recipes={recipes} standalone_blocks={standalone_blocks}".format(
            recipes=totals.get("recipes", 0),
            standalone_blocks=totals.get("standalone_blocks", 0),
        )
    )
    typer.echo(f"  Timing: total={totals.get('total_seconds', 0.0):.2f}s")
    typer.echo(f"  Run summary file: {run_summary_path}")


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


def _offset_result_block_indices(result: ConversionResult, offset: int) -> None:
    if offset <= 0:
        return
    result.source_blocks = offset_source_blocks(result.source_blocks, offset)
    result.source_support = offset_source_support(result.source_support, offset)
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        location = provenance.get("location")
        if isinstance(location, dict):
            _offset_location_fields(location, offset)

    for block in result.non_recipe_blocks:
        if not isinstance(block, dict):
            continue
        _offset_mapping_int(block, "index", offset)
        location = block.get("location")
        if isinstance(location, dict):
            _offset_location_fields(location, offset)


def _load_split_job_full_blocks(job_raw_root: Path) -> list[dict[str, Any]]:
    full_text_paths = sorted(job_raw_root.glob("**/full_text.json"))
    for full_text_path in full_text_paths:
        try:
            payload = json.loads(full_text_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        blocks = payload.get("blocks")
        if not isinstance(blocks, list):
            continue
        return [dict(block) for block in blocks if isinstance(block, dict)]
    return []


def _build_split_full_blocks(
    *,
    out: Path,
    workbook_slug: str,
    ordered_jobs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, int], dict[int, int]]:
    merged: list[dict[str, Any]] = []
    job_offsets: dict[int, int] = {}
    job_block_counts: dict[int, int] = {}
    running_offset = 0

    for job in ordered_jobs:
        job_index = int(job.get("job_index", 0))
        job_offsets[job_index] = running_offset
        job_raw_root = out / ".job_parts" / workbook_slug / f"job_{job_index}" / "raw"
        blocks = _load_split_job_full_blocks(job_raw_root)
        adjusted_count = 0
        for fallback_index, block in enumerate(blocks):
            index = _coerce_int(block.get("index"))
            if index is None:
                index = fallback_index
            adjusted_block = dict(block)
            adjusted_index = index + running_offset
            adjusted_block["index"] = adjusted_index
            adjusted_block["block_id"] = f"b{adjusted_index}"
            merged.append(adjusted_block)
            adjusted_count += 1
        job_block_counts[job_index] = adjusted_count
        running_offset += adjusted_count

    merged.sort(key=lambda block: int(_coerce_int(block.get("index")) or 0))
    return merged, job_offsets, job_block_counts


def _merge_source_jobs(
    file_path: Path,
    job_results: list[dict[str, Any]],
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
    importer_name: str | None = None,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    write_markdown: bool = True,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    workbook_slug = slugify_name(file_path.stem)
    merge_stats = TimingStats()
    merge_start = time.monotonic()
    output_stats = OutputStats(out)

    def _report_status(message: str) -> None:
        if status_callback is None:
            return
        try:
            status_callback(message)
        except Exception:
            return

    ordered_jobs = sorted(job_results, key=_job_range_start)
    run_settings = RunSettings.from_dict(
        project_run_config_payload(run_config, contract=RUN_SETTING_CONTRACT_FULL),
        warn_context="source-job merge run config",
    )
    merged_full_blocks, job_offsets, _job_block_counts = _build_split_full_blocks(
        out=out,
        workbook_slug=workbook_slug,
        ordered_jobs=ordered_jobs,
    )
    for job in ordered_jobs:
        result = job.get("result")
        if result is None:
            continue
        offset = job_offsets.get(int(job.get("job_index", 0)), 0)
        _offset_result_block_indices(result, offset)

    phase_labels = [
        "Merging source-job payloads...",
        "Building authoritative stage outputs...",
        "Merging raw artifacts...",
        "Writing report...",
        "Merge done",
    ]
    phase_total = len(phase_labels)
    phase_current = 0

    def _report_phase(label: str) -> None:
        nonlocal phase_current
        phase_current += 1
        _report_status(format_phase_counter("merge", phase_current, phase_total, label=label))

    _report_phase("Merging source-job payloads...")
    merged_source_blocks: list[Any] = []
    merged_source_support: list[Any] = []
    warnings: list[str] = []
    epub_backends: set[str] = set()

    for job in ordered_jobs:
        result = job.get("result")
        if result is None:
            continue
        merged_source_blocks.extend(result.source_blocks)
        merged_source_support.extend(result.source_support)
        if result.report and result.report.warnings:
            warnings.extend(result.report.warnings)
        if result.report and result.report.errors:
            for error in result.report.errors:
                warnings.append(f"Job {job.get('job_index')}: {error}")
        if result.report and result.report.epub_backend:
            epub_backends.add(str(result.report.epub_backend))

    resolved_importer_name = str(importer_name or ordered_jobs[0].get("importer_name") or "").strip()
    if not resolved_importer_name:
        detected_importer, detected_score = registry.best_importer_for_path(file_path)
        if detected_importer is not None and detected_score > 0:
            resolved_importer_name = str(detected_importer.name or "").strip()
    if not resolved_importer_name:
        raise ValueError(f"Could not determine importer for {file_path.name}.")
    file_hash = compute_file_hash(file_path)
    if merged_full_blocks:
        merged_full_text_path = out / "raw" / resolved_importer_name / file_hash / "full_text.json"
        merged_full_text_path.parent.mkdir(parents=True, exist_ok=True)
        merged_full_text_path.write_text(
            json.dumps(
                {
                    "blocks": merged_full_blocks,
                    "block_count": len(merged_full_blocks),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        output_stats.record_path(OUTPUT_STATS_CATEGORY_RAW, merged_full_text_path)

    report = ConversionReport(
        warnings=warnings,
        importerName=resolved_importer_name,
        runConfig=dict(run_config) if run_config is not None else None,
        runConfigHash=run_config_hash,
        runConfigSummary=run_config_summary,
    )
    if resolved_importer_name == "epub" and epub_backends:
        report.epub_backend = sorted(epub_backends)[0]
        if len(epub_backends) > 1:
            report.warnings.append(
                "epub_backend_inconsistent_across_split_jobs: " + ", ".join(sorted(epub_backends))
            )
    resolved_source_blocks = normalize_source_blocks(merged_full_blocks)
    if not resolved_source_blocks:
        resolved_source_blocks = normalize_source_blocks(merged_source_blocks)

    merged_result = ConversionResult(
        recipes=[],
        source_blocks=resolved_source_blocks,
        source_support=list(merged_source_support),
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=report,
        workbook=file_path.stem,
        workbook_path=str(file_path),
    )

    _report_phase("Building authoritative stage outputs...")
    session = execute_stage_import_session_from_result(
        result=merged_result,
        source_file=file_path,
        run_root=out,
        run_dt=run_dt,
        importer_name=resolved_importer_name,
        run_settings=run_settings,
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        mapping_config=mapping_config,
        write_markdown=write_markdown,
        progress_callback=_report_status,
        timing_stats=merge_stats,
        full_blocks=merged_full_blocks or None,
        write_raw_artifacts_enabled=False,
        output_stats=output_stats,
        recipe_limit=limit,
        recipe_limit_label=limit,
    )
    merged_result = session.conversion_result
    report = merged_result.report

    merge_stats.parsing_seconds = sum(
        float(job.get("timing", {}).get("parsing_seconds", 0.0)) for job in job_results
    )
    merge_stats.ocr_seconds = sum(
        float(job.get("timing", {}).get("ocr_seconds", 0.0)) for job in job_results
    )
    merge_overhead = max(0.0, time.monotonic() - merge_start - merge_stats.writing_seconds)
    merge_stats.checkpoints["merge_seconds"] = merge_overhead
    merge_stats.total_seconds = merge_stats.parsing_seconds + merge_stats.writing_seconds + merge_overhead

    _report_phase("Merging raw artifacts...")
    _merge_raw_artifacts(out, workbook_slug, job_results, output_stats=output_stats)
    if output_stats.file_counts:
        report.output_stats = output_stats.to_report()
    report.timing = merge_stats.to_dict()
    _report_phase("Writing report...")
    write_report(report, out, file_path.stem)
    _report_phase("Merge done")

    return {
        "file": file_path.name,
        "status": "success",
        "recipes": len(merged_result.recipes),
        "duration": merge_stats.total_seconds,
    }
