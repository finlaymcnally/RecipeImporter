from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _normalize_timing(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key in (
        "total_seconds",
        "prediction_seconds",
        "evaluation_seconds",
        "artifact_write_seconds",
        "history_append_seconds",
        "parsing_seconds",
        "writing_seconds",
        "ocr_seconds",
    ):
        value = _safe_float(payload.get(key))
        if value is None:
            continue
        normalized[key] = max(0.0, value)
    checkpoints: dict[str, float] = {}
    raw_checkpoints = payload.get("checkpoints")
    if isinstance(raw_checkpoints, dict):
        for raw_key, raw_value in raw_checkpoints.items():
            value = _safe_float(raw_value)
            if value is None:
                continue
            checkpoints[str(raw_key)] = max(0.0, value)
    normalized["checkpoints"] = checkpoints
    return normalized


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_all_method_root(path: Path) -> Path:
    if (path / "all_method_benchmark_multi_source_report.json").exists():
        return path
    candidate = path / "all-method-benchmark"
    if candidate.exists():
        return candidate
    return path


def collect_all_method_timing_summary(path: Path | str) -> dict[str, Any]:
    """Normalize all-method benchmark timing into one analyzer-ready payload."""
    root = _resolve_all_method_root(Path(path))
    source_rows: list[dict[str, Any]] = []
    variant_rows: list[dict[str, Any]] = []

    if not root.exists() or not root.is_dir():
        return {
            "root": str(root),
            "sources": [],
            "variants": [],
            "timing_summary": {
                "source_count": 0,
                "variant_count": 0,
                "source_total_seconds": 0.0,
                "source_average_seconds": None,
                "source_median_seconds": None,
                "slowest_source": None,
                "slowest_source_seconds": None,
                "slowest_config": None,
                "slowest_config_seconds": None,
            },
        }

    for source_dir in sorted(candidate for candidate in root.iterdir() if candidate.is_dir()):
        if source_dir.name.startswith("."):
            continue
        report_payload = _load_json(source_dir / "all_method_benchmark_report.json")
        report_variants = report_payload.get("variants")
        if not isinstance(report_variants, list):
            report_variants = []

        successful_rows: list[tuple[dict[str, Any], float]] = []
        for row in report_variants:
            if not isinstance(row, dict):
                continue
            if str(row.get("status") or "").strip().lower() != "ok":
                continue
            config_dir = str(row.get("config_dir") or "").strip()
            if not config_dir:
                continue
            timing = _normalize_timing(row.get("timing"))
            total_seconds = _safe_float(timing.get("total_seconds"))
            if total_seconds is None:
                eval_report = _load_json(source_dir / config_dir / "eval_report.json")
                timing = _normalize_timing(eval_report.get("timing"))
                total_seconds = _safe_float(timing.get("total_seconds"))
            if total_seconds is None:
                continue
            successful_rows.append((row, total_seconds))
            variant_rows.append(
                {
                    "source_slug": source_dir.name,
                    "config_dir": config_dir,
                    "run_config_hash": row.get("run_config_hash"),
                    "run_config_summary": row.get("run_config_summary"),
                    "timing": timing,
                }
            )

        seconds = [value for _row, value in successful_rows]
        slowest_row = max(successful_rows, key=lambda item: item[1])[0] if successful_rows else {}
        source_rows.append(
            {
                "source_slug": source_dir.name,
                "source_dir": str(source_dir),
                "variant_count": len(successful_rows),
                "total_seconds": sum(seconds),
                "average_seconds": (sum(seconds) / len(seconds)) if seconds else None,
                "median_seconds": _median(seconds),
                "slowest_config_dir": slowest_row.get("config_dir"),
                "slowest_config_seconds": max(seconds) if seconds else None,
            }
        )

    source_seconds = [row["total_seconds"] for row in source_rows if row["variant_count"] > 0]
    slowest_source = max(source_rows, key=lambda row: row["total_seconds"]) if source_rows else {}
    slowest_variant = {}
    if variant_rows:
        slowest_variant = max(
            variant_rows,
            key=lambda row: _safe_float(row.get("timing", {}).get("total_seconds")) or 0.0,
        )

    return {
        "root": str(root),
        "sources": source_rows,
        "variants": variant_rows,
        "timing_summary": {
            "source_count": len(source_rows),
            "variant_count": len(variant_rows),
            "source_total_seconds": sum(source_seconds),
            "source_average_seconds": (
                sum(source_seconds) / len(source_seconds) if source_seconds else None
            ),
            "source_median_seconds": _median(source_seconds),
            "slowest_source": slowest_source.get("source_slug"),
            "slowest_source_seconds": slowest_source.get("total_seconds"),
            "slowest_config": (
                f"{slowest_variant.get('source_slug', '')}/{slowest_variant.get('config_dir', '')}".strip(
                    "/"
                )
                if slowest_variant
                else None
            ),
            "slowest_config_seconds": _safe_float(
                slowest_variant.get("timing", {}).get("total_seconds")
            )
            if slowest_variant
            else None,
        },
    }
