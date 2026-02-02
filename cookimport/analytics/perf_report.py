from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_RUN_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")
_HISTORY_FILENAME = "performance_history.csv"
_HISTORY_DIRNAME = ".history"


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
    output_files: int | None
    output_bytes: int | None
    checkpoints: dict[str, float]

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


def history_path(out_dir: Path) -> Path:
    return out_dir / _HISTORY_DIRNAME / _HISTORY_FILENAME


def resolve_run_dir(run_dir: Path | None, out_dir: Path) -> Path | None:
    if run_dir is not None:
        return run_dir
    candidates = [
        path
        for path in out_dir.iterdir()
        if path.is_dir() and _RUN_DIR_PATTERN.match(path.name)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.name)


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

    recipes = _safe_int(data.get("totalRecipes"))
    tips = _safe_int(data.get("totalTips"))
    tip_candidates = _safe_int(data.get("totalTipCandidates"))
    topic_candidates = _safe_int(data.get("totalTopicCandidates"))

    output_files, output_bytes = _extract_output_totals(data.get("outputStats"))

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
        importer_name=data.get("importerName"),
        total_seconds=total_seconds,
        parsing_seconds=parsing_seconds,
        writing_seconds=writing_seconds,
        ocr_seconds=ocr_seconds,
        recipes=recipes,
        tips=tips,
        tip_candidates=tip_candidates,
        topic_candidates=topic_candidates,
        output_files=output_files,
        output_bytes=output_bytes,
        checkpoints=checkpoints,
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


def _safe_int(value: Any, *, allow_none: bool = False) -> int | None:
    if value is None:
        return None if allow_none else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return None if allow_none else 0


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
    }


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
