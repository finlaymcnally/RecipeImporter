from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from cookimport.parsing.epub_auto_select import selected_auto_score

_RUN_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}\.\d{2}\.\d{2}$")
_LEGACY_RUN_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")
_HISTORY_FILENAME = "performance_history.csv"
_HISTORY_DIRNAME = ".history"
_BENCHMARK_CATEGORIES = {"benchmark_eval", "benchmark_prediction"}


@dataclass(frozen=True)
class PerfRow:
    file_name: str
    report_path: Path
    run_dir: Path
    run_timestamp: str | None
    importer_name: str | None
    total_seconds: float
    parsing_seconds: float
    writing_seconds: float
    ocr_seconds: float
    recipes: int
    tips: int
    tip_candidates: int
    topic_candidates: int
    standalone_blocks: int | None
    standalone_topic_blocks: int | None
    standalone_topic_coverage: float | None
    output_files: int | None
    output_bytes: int | None
    checkpoints: dict[str, float]
    run_config: dict[str, Any] | None = None
    run_config_hash: str | None = None
    run_config_summary: str | None = None
    epub_extractor_requested: str | None = None
    epub_extractor_effective: str | None = None
    epub_auto_selected_score: float | None = None

    @property
    def total_units(self) -> int:
        return self.recipes + self.tips + self.tip_candidates + self.topic_candidates

    @property
    def per_unit_seconds(self) -> float | None:
        if self.total_units <= 0:
            return None
        return self.total_seconds / self.total_units

    @property
    def knowledge_share(self) -> float:
        total_units = self.total_units
        if total_units <= 0:
            return 0.0
        return self.topic_candidates / total_units

    @property
    def is_knowledge_heavy(self) -> bool:
        return self.total_units > 0 and self.knowledge_share >= 0.6

    @property
    def per_recipe_seconds(self) -> float | None:
        if self.recipes <= 0:
            return None
        return self.total_seconds / self.recipes

    @property
    def per_tip_seconds(self) -> float | None:
        if self.tips <= 0:
            return None
        return self.total_seconds / self.tips

    @property
    def per_tip_candidate_seconds(self) -> float | None:
        if self.tip_candidates <= 0:
            return None
        return self.total_seconds / self.tip_candidates

    @property
    def per_topic_candidate_seconds(self) -> float | None:
        if self.topic_candidates <= 0:
            return None
        return self.total_seconds / self.topic_candidates

    def dominant_stage(self) -> tuple[str, float] | None:
        total = self.total_seconds
        if total <= 0:
            return None
        parsing = self.parsing_seconds
        writing = self.writing_seconds
        other = max(0.0, total - parsing - writing)
        stage_seconds, stage_name = max(
            (parsing, "parsing"),
            (writing, "writing"),
            (other, "other"),
            key=lambda item: item[0],
        )
        if stage_seconds / total < 0.5:
            return None
        return stage_name, stage_seconds

    def dominant_checkpoint(self) -> tuple[str, float] | None:
        if not self.checkpoints:
            return None
        name, seconds = max(self.checkpoints.items(), key=lambda item: item[1])
        return name, seconds


@dataclass(frozen=True)
class PerfSummary:
    run_dir: Path
    rows: list[PerfRow]
    total_outliers: list[PerfRow]
    parsing_outliers: list[PerfRow]
    writing_outliers: list[PerfRow]
    per_recipe_outliers: list[PerfRow]
    per_unit_outliers: list[PerfRow]
    knowledge_heavy: list[PerfRow]


@dataclass(frozen=True)
class BenchmarkCsvBackfillSummary:
    benchmark_rows: int
    rows_updated: int
    recipes_filled: int
    report_paths_filled: int
    source_files_filled: int
    rows_still_missing_recipes: int


@dataclass(frozen=True)
class _BenchmarkBackfillContext:
    recipes: int | None = None
    report_path: str = ""
    source_file: str = ""


def history_path(out_dir: Path) -> Path:
    return out_dir / _HISTORY_DIRNAME / _HISTORY_FILENAME


def resolve_run_dir(run_dir: Path | None, out_dir: Path) -> Path | None:
    if run_dir is not None:
        return run_dir
    candidates: list[tuple[dt.datetime, Path]] = []
    for path in out_dir.iterdir():
        if not path.is_dir():
            continue
        parsed = _parse_run_dir_timestamp(path.name)
        if parsed is None:
            continue
        candidates.append((parsed, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1].name))[1]


def _parse_run_dir_timestamp(folder_name: str) -> dt.datetime | None:
    if _RUN_DIR_PATTERN.match(folder_name):
        try:
            return dt.datetime.strptime(folder_name, "%Y-%m-%d_%H.%M.%S")
        except ValueError:
            return None
    if _LEGACY_RUN_DIR_PATTERN.match(folder_name):
        try:
            return dt.datetime.strptime(folder_name, "%Y-%m-%d-%H-%M-%S")
        except ValueError:
            return None
    return None


def load_perf_rows(run_dir: Path) -> list[PerfRow]:
    rows: list[PerfRow] = []
    for report_path in sorted(run_dir.glob("*.excel_import_report.json")):
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        row = _row_from_report(run_dir, report_path, data)
        if row is not None:
            rows.append(row)
    return rows


def build_perf_summary(run_dir: Path) -> PerfSummary:
    rows = load_perf_rows(run_dir)
    total_outliers = _find_outliers(rows, lambda row: row.total_seconds)
    parsing_outliers = _find_outliers(rows, lambda row: row.parsing_seconds)
    writing_outliers = _find_outliers(rows, lambda row: row.writing_seconds)
    per_unit_outliers = _find_outliers(
        rows,
        lambda row: row.per_unit_seconds,
        predicate=_has_enough_units,
    )
    per_recipe_outliers = _find_outliers(
        rows,
        lambda row: row.per_recipe_seconds,
        predicate=_is_recipe_heavy,
    )
    knowledge_heavy = [row for row in rows if row.is_knowledge_heavy]
    return PerfSummary(
        run_dir=run_dir,
        rows=rows,
        total_outliers=total_outliers,
        parsing_outliers=parsing_outliers,
        writing_outliers=writing_outliers,
        per_recipe_outliers=per_recipe_outliers,
        per_unit_outliers=per_unit_outliers,
        knowledge_heavy=knowledge_heavy,
    )


def format_summary_line(row: PerfRow) -> str:
    parts = [
        f"{row.file_name}: total {_fmt_seconds(row.total_seconds)}"
        f" (parse {_fmt_seconds(row.parsing_seconds)}, write {_fmt_seconds(row.writing_seconds)})",
        f"r {row.recipes} t {row.tips} tc {row.tip_candidates} top {row.topic_candidates}",
        "per r {per_r} per t {per_t} per tc {per_tc} per top {per_top}".format(
            per_r=_fmt_optional(row.per_recipe_seconds),
            per_t=_fmt_optional(row.per_tip_seconds),
            per_tc=_fmt_optional(row.per_tip_candidate_seconds),
            per_top=_fmt_optional(row.per_topic_candidate_seconds),
        ),
    ]
    dominant = _format_dominant(row)
    if dominant:
        parts.append(f"dominant {dominant}")
    if row.is_knowledge_heavy:
        parts.append(f"knowledge-heavy {row.knowledge_share:.0%} topics")
    if (
        row.standalone_blocks is not None
        and row.standalone_topic_blocks is not None
        and (row.standalone_blocks > 0 or row.standalone_topic_blocks > 0)
    ):
        coverage = row.standalone_topic_coverage
        if coverage is None and row.standalone_blocks:
            coverage = row.standalone_topic_blocks / row.standalone_blocks
        if coverage is not None:
            parts.append(
                "standalone {topic}/{total} ({coverage:.0%})".format(
                    topic=row.standalone_topic_blocks,
                    total=row.standalone_blocks,
                    coverage=coverage,
                )
            )
        else:
            parts.append(
                f"standalone {row.standalone_topic_blocks}/{row.standalone_blocks}"
            )
    return " | ".join(parts)


def append_history_csv(rows: Iterable[PerfRow], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        _ensure_csv_schema(csv_path)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_csv(row))


def append_benchmark_csv(
    report: dict[str, Any],
    csv_path: Path,
    *,
    run_timestamp: str,
    run_dir: str,
    eval_scope: str = "",
    source_file: str = "",
    recipes: int | None = None,
    processed_report_path: str = "",
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    epub_extractor_requested: str | None = None,
    epub_extractor_effective: str | None = None,
    epub_auto_selected_score: float | None = None,
    run_category: str = "benchmark_eval",
) -> None:
    """Append one benchmark eval row to the performance history CSV.

    Stage-only columns are left empty; benchmark-only columns are populated
    from *report* (an eval_report.json-shaped dict).
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        _ensure_csv_schema(csv_path)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0

    counts = report.get("counts") or {}
    precision = _safe_float_or_none(report.get("precision"))
    recall = _safe_float_or_none(report.get("recall"))
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)

    app_aligned = report.get("app_aligned") or {}
    supported_relaxed = app_aligned.get("supported_labels_relaxed") or {}

    boundary = report.get("boundary") or {}
    resolved_run_config_hash = run_config_hash
    resolved_run_config_summary = run_config_summary
    if run_config is not None:
        if resolved_run_config_hash is None:
            resolved_run_config_hash = _stable_hash_for_run_config(run_config)
        if resolved_run_config_summary is None:
            resolved_run_config_summary = _summary_for_run_config(run_config)
    resolved_requested = _normalize_optional_text(epub_extractor_requested)
    if resolved_requested is None and run_config is not None:
        resolved_requested = _normalize_optional_text(
            run_config.get("epub_extractor_requested")
        )
    if resolved_requested is None and run_config is not None:
        resolved_requested = _normalize_optional_text(run_config.get("epub_extractor"))

    resolved_effective = _normalize_optional_text(epub_extractor_effective)
    if resolved_effective is None and run_config is not None:
        resolved_effective = _normalize_optional_text(
            run_config.get("epub_extractor_effective")
        )
    if resolved_effective is None and run_config is not None:
        resolved_effective = _normalize_optional_text(run_config.get("epub_extractor"))

    resolved_auto_score = epub_auto_selected_score
    if resolved_auto_score is None and run_config is not None:
        resolved_auto_score = _safe_float_or_none(run_config.get("epub_auto_selected_score"))

    row: dict[str, Any] = {field: "" for field in _CSV_FIELDS}
    row.update({
        "run_timestamp": run_timestamp,
        "run_dir": run_dir,
        "file_name": source_file,
        "report_path": processed_report_path,
        "recipes": recipes if recipes is not None else "",
        "run_category": run_category,
        "eval_scope": eval_scope,
        "precision": precision if precision is not None else "",
        "recall": recall if recall is not None else "",
        "f1": f1 if f1 is not None else "",
        "gold_total": counts.get("gold_total", ""),
        "gold_matched": counts.get("gold_matched", ""),
        "pred_total": counts.get("pred_total", ""),
        "supported_precision": supported_relaxed.get("precision", ""),
        "supported_recall": supported_relaxed.get("recall", ""),
        "boundary_correct": boundary.get("correct", ""),
        "boundary_over": boundary.get("over", ""),
        "boundary_under": boundary.get("under", ""),
        "boundary_partial": boundary.get("partial", ""),
        "run_config_hash": resolved_run_config_hash or "",
        "run_config_summary": resolved_run_config_summary or "",
        "run_config_json": (
            json.dumps(run_config, sort_keys=True)
            if run_config is not None
            else ""
        ),
        "epub_extractor_requested": resolved_requested or "",
        "epub_extractor_effective": resolved_effective or "",
        "epub_auto_selected_score": (
            resolved_auto_score if resolved_auto_score is not None else ""
        ),
    })

    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def backfill_benchmark_history_csv(
    csv_path: Path,
    *,
    write: bool = True,
) -> BenchmarkCsvBackfillSummary:
    """Patch benchmark rows with missing recipe/report/source fields from manifests."""
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    _ensure_csv_schema(csv_path)
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    benchmark_rows = 0
    rows_updated = 0
    recipes_filled = 0
    report_paths_filled = 0
    source_files_filled = 0
    rows_still_missing_recipes = 0

    for row in rows:
        if row.get("run_category", "") not in _BENCHMARK_CATEGORIES:
            continue
        benchmark_rows += 1

        row_updated = False
        run_dir_value = str(row.get("run_dir") or "").strip()
        run_dir = Path(run_dir_value) if run_dir_value else None

        recipes_before = _parse_int_or_none(row.get("recipes"))
        recipes_value = recipes_before
        report_path_value = str(row.get("report_path") or "").strip()
        source_file_value = str(row.get("file_name") or "").strip()

        if recipes_value is None and report_path_value:
            recipes_value = _load_total_recipes_from_report(report_path_value)

        context = _collect_benchmark_backfill_context(run_dir)

        if recipes_value is None and context.recipes is not None:
            row["recipes"] = str(context.recipes)
            recipes_value = context.recipes
            row_updated = True
            recipes_filled += 1

        if not report_path_value and context.report_path:
            row["report_path"] = context.report_path
            report_path_value = context.report_path
            row_updated = True
            report_paths_filled += 1

        if not source_file_value and context.source_file:
            row["file_name"] = context.source_file
            source_file_value = context.source_file
            row_updated = True
            source_files_filled += 1

        if recipes_before is None and recipes_value is None:
            rows_still_missing_recipes += 1

        if row_updated:
            rows_updated += 1

    if write and rows_updated > 0:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in _CSV_FIELDS})

    return BenchmarkCsvBackfillSummary(
        benchmark_rows=benchmark_rows,
        rows_updated=rows_updated,
        recipes_filled=recipes_filled,
        report_paths_filled=report_paths_filled,
        source_files_filled=source_files_filled,
        rows_still_missing_recipes=rows_still_missing_recipes,
    )


def _row_from_report(run_dir: Path, report_path: Path, data: dict[str, Any]) -> PerfRow | None:
    timing = data.get("timing") or {}
    checkpoints_raw = timing.get("checkpoints") or {}
    checkpoints = {
        str(key): _safe_float(value)
        for key, value in checkpoints_raw.items()
        if _safe_float(value) > 0
    }
    total_seconds = _safe_float(timing.get("total_seconds") or timing.get("totalSeconds"))
    parsing_seconds = _safe_float(timing.get("parsing_seconds") or timing.get("parsingSeconds"))
    writing_seconds = _safe_float(timing.get("writing_seconds") or timing.get("writingSeconds"))
    ocr_seconds = _safe_float(timing.get("ocr_seconds") or timing.get("ocrSeconds"))

    importer_name = _normalize_optional_text(data.get("importerName"))
    recipes = _safe_int(data.get("totalRecipes"))
    tips = _safe_int(data.get("totalTips"))
    tip_candidates = _safe_int(data.get("totalTipCandidates"))
    topic_candidates = _safe_int(data.get("totalTopicCandidates"))
    standalone_blocks = _safe_int(data.get("totalStandaloneBlocks"), allow_none=True)
    standalone_topic_blocks = _safe_int(
        data.get("totalStandaloneTopicBlocks"), allow_none=True
    )
    standalone_topic_coverage = _safe_float_or_none(data.get("standaloneTopicCoverage"))
    if (
        standalone_topic_coverage is None
        and standalone_blocks
        and standalone_topic_blocks is not None
    ):
        standalone_topic_coverage = standalone_topic_blocks / standalone_blocks

    output_files, output_bytes = _extract_output_totals(data.get("outputStats"))
    run_config = data.get("runConfig")
    if not isinstance(run_config, dict):
        run_config = None
    run_config_hash = str(data.get("runConfigHash") or "").strip() or None
    run_config_summary = str(data.get("runConfigSummary") or "").strip() or None
    if run_config_hash is None and run_config is not None:
        run_config_hash = _stable_hash_for_run_config(run_config)
    if run_config_summary is None and run_config is not None:
        run_config_summary = _summary_for_run_config(run_config)
    requested_extractor = _normalize_optional_text(data.get("epubExtractorRequested"))
    effective_extractor = _normalize_optional_text(data.get("epubExtractorEffective"))
    if requested_extractor is None and run_config is not None:
        requested_extractor = _normalize_optional_text(run_config.get("epub_extractor_requested"))
    if requested_extractor is None and run_config is not None:
        requested_extractor = _normalize_optional_text(run_config.get("epub_extractor"))
    if effective_extractor is None and run_config is not None:
        effective_extractor = _normalize_optional_text(run_config.get("epub_extractor_effective"))
    if effective_extractor is None:
        effective_extractor = _normalize_optional_text(data.get("epubBackend"))
    if effective_extractor is None and run_config is not None:
        effective_extractor = _normalize_optional_text(run_config.get("epub_extractor"))
    auto_selected_score = _safe_float_or_none(data.get("epubAutoSelectedScore"))
    if auto_selected_score is None:
        artifact = data.get("epubAutoSelection")
        auto_selected_score = selected_auto_score(artifact if isinstance(artifact, dict) else None)
    if auto_selected_score is None and run_config is not None:
        auto_selected_score = _safe_float_or_none(run_config.get("epub_auto_selected_score"))
    if (importer_name or "").lower() != "epub":
        requested_extractor = None
        effective_extractor = None
        auto_selected_score = None

    source_file = data.get("sourceFile")
    if source_file:
        file_name = Path(str(source_file)).name
    else:
        file_name = report_path.stem.replace(".excel_import_report", "")

    return PerfRow(
        file_name=file_name,
        report_path=report_path,
        run_dir=run_dir,
        run_timestamp=data.get("runTimestamp"),
        importer_name=importer_name,
        total_seconds=total_seconds,
        parsing_seconds=parsing_seconds,
        writing_seconds=writing_seconds,
        ocr_seconds=ocr_seconds,
        recipes=recipes,
        tips=tips,
        tip_candidates=tip_candidates,
        topic_candidates=topic_candidates,
        standalone_blocks=standalone_blocks,
        standalone_topic_blocks=standalone_topic_blocks,
        standalone_topic_coverage=standalone_topic_coverage,
        output_files=output_files,
        output_bytes=output_bytes,
        checkpoints=checkpoints,
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        epub_extractor_requested=requested_extractor,
        epub_extractor_effective=effective_extractor,
        epub_auto_selected_score=auto_selected_score,
    )


def _extract_output_totals(output_stats: Any) -> tuple[int | None, int | None]:
    if not isinstance(output_stats, dict):
        return None, None
    files = output_stats.get("files")
    if not isinstance(files, dict):
        return None, None
    total = files.get("total")
    if not isinstance(total, dict):
        return None, None
    count = total.get("count")
    bytes_written = total.get("bytes")
    return _safe_int(count, allow_none=True), _safe_int(bytes_written, allow_none=True)


def _find_outliers(rows: list[PerfRow], metric, *, predicate=None) -> list[PerfRow]:
    values = [
        metric(row)
        for row in rows
        if metric(row) is not None and (predicate is None or predicate(row))
    ]
    if not values:
        return []
    median = _median(values)
    if median is None or median <= 0:
        return []
    threshold = median * 3.0
    return [
        row
        for row in rows
        if metric(row) is not None
        and metric(row) > threshold
        and (predicate is None or predicate(row))
    ]


def _is_recipe_heavy(row: PerfRow) -> bool:
    return row.recipes >= 10 and not row.is_knowledge_heavy


def _has_enough_units(row: PerfRow) -> bool:
    return row.total_units >= 50


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def _format_dominant(row: PerfRow) -> str | None:
    stage = row.dominant_stage()
    if stage is None:
        return None
    stage_name, stage_seconds = stage
    if stage_name == "writing":
        checkpoint = row.dominant_checkpoint()
        if checkpoint:
            name, seconds = checkpoint
            return f"{stage_name}:{name} {_fmt_seconds(seconds)}"
    return f"{stage_name} {_fmt_seconds(stage_seconds)}"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _safe_int(value: Any, *, allow_none: bool = False) -> int | None:
    if value is None:
        return None if allow_none else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return None if allow_none else 0


def _parse_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None


def _load_total_recipes_from_report(report_path_value: Path | str | None) -> int | None:
    if report_path_value is None:
        return None
    report_path = Path(report_path_value)
    if not report_path.exists() or not report_path.is_file():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return _parse_int_or_none(payload.get("totalRecipes"))


def _load_manifest_backfill_context(
    manifest_path: Path,
) -> _BenchmarkBackfillContext | None:
    if not manifest_path.exists() or not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None

    report_path = str(payload.get("processed_report_path") or "")
    recipes = _parse_int_or_none(payload.get("recipe_count"))
    if recipes is None and report_path:
        recipes = _load_total_recipes_from_report(report_path)

    return _BenchmarkBackfillContext(
        recipes=recipes,
        report_path=report_path,
        source_file=str(payload.get("source_file") or ""),
    )


def _collect_benchmark_backfill_context(run_dir: Path | None) -> _BenchmarkBackfillContext:
    if run_dir is None:
        return _BenchmarkBackfillContext()

    contexts: list[_BenchmarkBackfillContext] = []
    for manifest_path in (
        run_dir / "prediction-run" / "manifest.json",
        run_dir / "manifest.json",
    ):
        context = _load_manifest_backfill_context(manifest_path)
        if context is not None:
            contexts.append(context)

    per_item_contexts: list[_BenchmarkBackfillContext] = []
    for manifest_path in sorted(run_dir.glob("per_item/*/pred_run/manifest.json")):
        context = _load_manifest_backfill_context(manifest_path)
        if context is not None:
            per_item_contexts.append(context)

    recipes: int | None = None
    report_path = ""
    source_file = ""

    for context in contexts:
        if recipes is None and context.recipes is not None:
            recipes = context.recipes
        if not report_path and context.report_path:
            report_path = context.report_path
        if not source_file and context.source_file:
            source_file = context.source_file

    if recipes is None and per_item_contexts:
        summed = sum(
            context.recipes for context in per_item_contexts if context.recipes is not None
        )
        if summed > 0 or any(context.recipes == 0 for context in per_item_contexts):
            recipes = summed

    return _BenchmarkBackfillContext(
        recipes=recipes,
        report_path=report_path,
        source_file=source_file,
    )


def _fmt_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}s"


def _fmt_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}s"


_CSV_FIELDS = [
    "run_timestamp",
    "run_dir",
    "file_name",
    "report_path",
    "importer_name",
    "total_seconds",
    "parsing_seconds",
    "writing_seconds",
    "ocr_seconds",
    "recipes",
    "tips",
    "tip_candidates",
    "topic_candidates",
    "standalone_blocks",
    "standalone_topic_blocks",
    "standalone_topic_coverage",
    "total_units",
    "per_recipe_seconds",
    "per_tip_seconds",
    "per_tip_candidate_seconds",
    "per_topic_candidate_seconds",
    "per_unit_seconds",
    "output_files",
    "output_bytes",
    "knowledge_share",
    "knowledge_heavy",
    "dominant_stage",
    "dominant_stage_seconds",
    "dominant_checkpoint",
    "dominant_checkpoint_seconds",
    # Benchmark eval columns (empty for stage_import rows)
    "run_category",
    "eval_scope",
    "precision",
    "recall",
    "f1",
    "gold_total",
    "gold_matched",
    "pred_total",
    "supported_precision",
    "supported_recall",
    "boundary_correct",
    "boundary_over",
    "boundary_under",
    "boundary_partial",
    "epub_extractor_requested",
    "epub_extractor_effective",
    "epub_auto_selected_score",
    "run_config_hash",
    "run_config_summary",
    "run_config_json",
]


def _row_to_csv(row: PerfRow) -> dict[str, Any]:
    stage = row.dominant_stage()
    checkpoint = row.dominant_checkpoint()
    dominant_stage = stage[0] if stage else ""
    dominant_stage_seconds = stage[1] if stage else ""
    dominant_checkpoint = checkpoint[0] if checkpoint else ""
    dominant_checkpoint_seconds = checkpoint[1] if checkpoint else ""

    return {
        "run_timestamp": row.run_timestamp or "",
        "run_dir": str(row.run_dir),
        "file_name": row.file_name,
        "report_path": str(row.report_path),
        "importer_name": row.importer_name or "",
        "total_seconds": row.total_seconds,
        "parsing_seconds": row.parsing_seconds,
        "writing_seconds": row.writing_seconds,
        "ocr_seconds": row.ocr_seconds,
        "recipes": row.recipes,
        "tips": row.tips,
        "tip_candidates": row.tip_candidates,
        "topic_candidates": row.topic_candidates,
        "standalone_blocks": (
            row.standalone_blocks if row.standalone_blocks is not None else ""
        ),
        "standalone_topic_blocks": (
            row.standalone_topic_blocks if row.standalone_topic_blocks is not None else ""
        ),
        "standalone_topic_coverage": (
            row.standalone_topic_coverage if row.standalone_topic_coverage is not None else ""
        ),
        "total_units": row.total_units,
        "per_recipe_seconds": row.per_recipe_seconds if row.per_recipe_seconds is not None else "",
        "per_tip_seconds": row.per_tip_seconds if row.per_tip_seconds is not None else "",
        "per_tip_candidate_seconds": row.per_tip_candidate_seconds if row.per_tip_candidate_seconds is not None else "",
        "per_topic_candidate_seconds": row.per_topic_candidate_seconds if row.per_topic_candidate_seconds is not None else "",
        "per_unit_seconds": row.per_unit_seconds if row.per_unit_seconds is not None else "",
        "output_files": row.output_files if row.output_files is not None else "",
        "output_bytes": row.output_bytes if row.output_bytes is not None else "",
        "knowledge_share": row.knowledge_share if row.total_units > 0 else "",
        "knowledge_heavy": "yes" if row.is_knowledge_heavy else "",
        "dominant_stage": dominant_stage,
        "dominant_stage_seconds": dominant_stage_seconds,
        "dominant_checkpoint": dominant_checkpoint,
        "dominant_checkpoint_seconds": dominant_checkpoint_seconds,
        "run_category": "stage_import",
        "eval_scope": "",
        "precision": "",
        "recall": "",
        "f1": "",
        "gold_total": "",
        "gold_matched": "",
        "pred_total": "",
        "supported_precision": "",
        "supported_recall": "",
        "boundary_correct": "",
        "boundary_over": "",
        "boundary_under": "",
        "boundary_partial": "",
        "epub_extractor_requested": row.epub_extractor_requested or "",
        "epub_extractor_effective": row.epub_extractor_effective or "",
        "epub_auto_selected_score": (
            row.epub_auto_selected_score if row.epub_auto_selected_score is not None else ""
        ),
        "run_config_hash": row.run_config_hash or "",
        "run_config_summary": row.run_config_summary or "",
        "run_config_json": (
            json.dumps(row.run_config, sort_keys=True)
            if row.run_config is not None
            else ""
        ),
    }


def _stable_hash_for_run_config(run_config: dict[str, Any]) -> str:
    canonical_json = json.dumps(
        run_config,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _summary_for_run_config(run_config: dict[str, Any]) -> str:
    ordered_keys = (
        "epub_extractor",
        "epub_extractor_requested",
        "epub_extractor_effective",
        "ocr_device",
        "ocr_batch_size",
        "workers",
        "effective_workers",
        "pdf_split_workers",
        "epub_split_workers",
        "pdf_pages_per_job",
        "epub_spine_items_per_job",
        "warm_models",
    )
    parts: list[str] = []
    for key in ordered_keys:
        if key not in run_config:
            continue
        value = run_config.get(key)
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " | ".join(parts)


def _ensure_csv_schema(csv_path: Path) -> None:
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            existing_fields = reader.fieldnames or []
            if existing_fields == _CSV_FIELDS:
                return
            existing_rows = list(reader)
    except OSError:
        return

    try:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for row in existing_rows:
                normalized = {field: row.get(field, "") for field in _CSV_FIELDS}
                writer.writerow(normalized)
    except OSError:
        return
