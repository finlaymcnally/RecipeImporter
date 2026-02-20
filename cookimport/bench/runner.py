"""Suite runner: orchestrates pred-run + eval for each bench item."""

from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Callable

from cookimport.bench.cost import estimate_llm_costs, write_escalation_queue
from cookimport.bench.noise import consolidate_predictions, dedupe_predictions
from cookimport.bench.pred_run import build_pred_run_for_source
from cookimport.bench.report import aggregate_metrics, format_suite_report_md
from cookimport.bench.suite import BenchSuite
from cookimport.bench.trace import TraceCollector
from cookimport.labelstudio.eval_freeform import (
    evaluate_predicted_vs_freeform,
    format_freeform_eval_report_md,
    load_gold_freeform_ranges,
    load_predicted_labeled_ranges,
)
from cookimport.runs import RunManifest, RunSource, write_run_manifest

logger = logging.getLogger(__name__)


def _load_pred_dicts(pred_run_dir: Path) -> list[dict[str, Any]]:
    """Load prediction tasks as raw dicts for noise/cost processing."""
    tasks_path = pred_run_dir / "label_studio_tasks.jsonl"
    if not tasks_path.exists():
        return []
    dicts: list[dict[str, Any]] = []
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            dicts.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return dicts


def _write_jsonl(path: Path, records: list[dict[str, Any] | Any]) -> None:
    lines = []
    for rec in records:
        if hasattr(rec, "__dict__") and not isinstance(rec, dict):
            from dataclasses import asdict
            rec = asdict(rec)
        lines.append(json.dumps(rec))
    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


def _path_for_manifest(run_root: Path, path_like: Path | str | None) -> str | None:
    if path_like is None:
        return None
    candidate = Path(path_like)
    try:
        return str(candidate.relative_to(run_root))
    except ValueError:
        return str(candidate)


def run_suite(
    suite: BenchSuite,
    out_dir: Path,
    *,
    repo_root: Path,
    config: dict | None = None,
    baseline_run_dir: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Run the full benchmark suite and write aggregate results.

    Returns ``(run_root, aggregated_metrics)`` so callers can log the
    metrics without re-reading ``metrics.json`` from disk.
    """
    def _notify(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    run_dt = dt.datetime.now()
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    run_root = out_dir / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    # Save suite used
    suite_path = run_root / "suite_used.json"
    suite_path.write_text(suite.model_dump_json(indent=2), encoding="utf-8")

    # Initialize trace collector for the run
    trace = TraceCollector()

    per_item_results: list[dict[str, Any]] = []
    all_cost_estimates: list[dict[str, Any]] = []

    for item in suite.items:
        _notify(f"Processing {item.item_id}...")
        item_dir = run_root / "per_item" / item.item_id

        # Build pred run
        source_path = repo_root / item.source_path
        pred_run_staging = item_dir / "_pred_staging"
        pred_run_staging.mkdir(parents=True, exist_ok=True)

        _notify(f"  [{item.item_id}] Generating prediction run...")
        pred_run_dir = build_pred_run_for_source(
            source_path,
            pred_run_staging,
            config=config,
            progress_callback=lambda msg, iid=item.item_id: _notify(f"  [{iid}] {msg}"),
        )

        # Move pred-run into per_item/<item_id>/pred_run/
        target_pred = item_dir / "pred_run"
        if target_pred.exists():
            shutil.rmtree(target_pred)
        shutil.move(str(pred_run_dir), str(target_pred))
        # Clean staging
        shutil.rmtree(pred_run_staging, ignore_errors=True)

        # Load gold + predicted
        gold_dir = repo_root / item.gold_dir
        gold_spans_path = gold_dir / "exports" / "freeform_span_labels.jsonl"
        _notify(f"  [{item.item_id}] Loading gold spans...")
        gold = load_gold_freeform_ranges(gold_spans_path)

        _notify(f"  [{item.item_id}] Loading predicted ranges...")
        predicted = load_predicted_labeled_ranges(target_pred)

        # Noise reduction: load raw prediction dicts, dedupe + consolidate
        raw_preds = _load_pred_dicts(target_pred)
        raw_count = len(raw_preds)
        deduped = dedupe_predictions(raw_preds)
        consolidated = consolidate_predictions(deduped)
        noise_stats = {
            "raw_predictions": raw_count,
            "after_dedupe": len(deduped),
            "after_consolidation": len(consolidated),
            "duplicates_removed": raw_count - len(deduped),
            "overlaps_resolved": len(deduped) - len(consolidated),
        }
        (item_dir / "noise_stats.json").write_text(
            json.dumps(noise_stats, indent=2), encoding="utf-8"
        )

        # Evaluate
        _notify(f"  [{item.item_id}] Evaluating...")
        eval_result = evaluate_predicted_vs_freeform(
            predicted,
            gold,
            overlap_threshold=0.5,
            force_source_match=item.force_source_match,
        )

        # Write per-item eval artifacts
        eval_dir = item_dir / "eval_freeform"
        eval_dir.mkdir(parents=True, exist_ok=True)

        report_json_path = eval_dir / "eval_report.json"
        report_json_path.write_text(
            json.dumps(eval_result["report"], indent=2, sort_keys=True),
            encoding="utf-8",
        )

        report_md = format_freeform_eval_report_md(eval_result["report"])
        (eval_dir / "eval_report.md").write_text(report_md, encoding="utf-8")

        _write_jsonl(eval_dir / "missed_gold_spans.jsonl", eval_result["missed_gold"])
        _write_jsonl(
            eval_dir / "false_positive_preds.jsonl",
            eval_result["false_positive_preds"],
        )

        # Cost estimation for LLM repair of missed/false-positive spans
        cost_estimate = estimate_llm_costs(consolidated)
        (eval_dir / "cost_estimate.json").write_text(
            json.dumps(cost_estimate, indent=2), encoding="utf-8"
        )
        all_cost_estimates.append({
            "item_id": item.item_id,
            **cost_estimate,
        })

        # Escalation queue: predictions that would benefit from LLM review
        write_escalation_queue(
            consolidated,
            eval_dir / "escalation_queue.jsonl",
        )

        pred_manifest_payload: dict[str, Any] = {}
        pred_manifest_path = target_pred / "manifest.json"
        if pred_manifest_path.exists():
            try:
                loaded = json.loads(pred_manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    pred_manifest_payload = loaded
            except (OSError, json.JSONDecodeError):
                pred_manifest_payload = {}

        pred_run_config = pred_manifest_payload.get("run_config")
        if not isinstance(pred_run_config, dict):
            pred_run_config = None
        requested_extractor = None
        effective_extractor = None
        if pred_run_config is not None:
            requested_extractor = (
                str(pred_run_config.get("epub_extractor_requested") or "").strip() or None
            )
            effective_extractor = (
                str(pred_run_config.get("epub_extractor_effective") or "").strip() or None
            )
            if requested_extractor is None:
                requested_extractor = (
                    str(pred_run_config.get("epub_extractor") or "").strip() or None
                )
            if effective_extractor is None:
                effective_extractor = (
                    str(pred_run_config.get("epub_extractor") or "").strip() or None
                )
        item_run_config: dict[str, Any] = {
            "overlap_threshold": 0.5,
            "force_source_match": item.force_source_match,
        }
        if pred_run_config is not None:
            item_run_config["prediction_run_config"] = pred_run_config
        pred_config_hash = str(pred_manifest_payload.get("run_config_hash") or "").strip()
        pred_config_summary = str(
            pred_manifest_payload.get("run_config_summary") or ""
        ).strip()
        if pred_config_hash:
            item_run_config["prediction_run_config_hash"] = pred_config_hash
        if pred_config_summary:
            item_run_config["prediction_run_config_summary"] = pred_config_summary

        item_eval_manifest = RunManifest(
            run_kind="bench_eval",
            run_id=eval_dir.name,
            created_at=dt.datetime.now().isoformat(timespec="seconds"),
            source=RunSource(
                path=str(pred_manifest_payload.get("source_file") or source_path),
                source_hash=str(pred_manifest_payload.get("source_hash") or "") or None,
                importer_name=str(pred_manifest_payload.get("importer_name") or "") or None,
            ),
            run_config=item_run_config,
            artifacts={
                "pred_run_dir": _path_for_manifest(eval_dir, target_pred),
                "gold_spans_jsonl": _path_for_manifest(eval_dir, gold_spans_path),
                "eval_report_json": "eval_report.json",
                "eval_report_md": "eval_report.md",
                "missed_gold_spans_jsonl": "missed_gold_spans.jsonl",
                "false_positive_preds_jsonl": "false_positive_preds.jsonl",
                "cost_estimate_json": "cost_estimate.json",
                "escalation_queue_jsonl": "escalation_queue.jsonl",
            },
        )
        try:
            write_run_manifest(eval_dir, item_eval_manifest)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to write run_manifest.json for bench eval at %s: %s",
                eval_dir,
                exc,
            )

        # Record trace event for this item
        trace.record(
            "item_eval_complete",
            block_index=0,
            details={
                "item_id": item.item_id,
                "recall": eval_result["report"].get("recall", 0),
                "precision": eval_result["report"].get("precision", 0),
                "noise_stats": noise_stats,
                "estimated_llm_cost_usd": cost_estimate.get(
                    "estimated_total_cost_usd", 0
                ),
            },
        )

        per_item_results.append({
            "item_id": item.item_id,
            "report": eval_result["report"],
            "missed_gold": eval_result["missed_gold"],
            "false_positive_preds": eval_result["false_positive_preds"],
            "requested_epub_extractor": requested_extractor,
            "effective_epub_extractor": effective_extractor,
        })
        _notify(
            f"  [{item.item_id}] Done. "
            f"recall={eval_result['report'].get('recall', 0):.3f}, "
            f"precision={eval_result['report'].get('precision', 0):.3f}"
        )

    # Aggregate and write report
    _notify("Aggregating metrics...")
    agg = aggregate_metrics(per_item_results)
    report_md = format_suite_report_md(agg, per_item_results, suite_name=suite.name)

    (run_root / "report.md").write_text(report_md, encoding="utf-8")
    (run_root / "metrics.json").write_text(
        json.dumps(agg, indent=2, sort_keys=True), encoding="utf-8"
    )

    effective_knobs = config or {}
    (run_root / "knobs_effective.json").write_text(
        json.dumps(effective_knobs, indent=2, sort_keys=True), encoding="utf-8"
    )

    # Write aggregate cost estimate
    if all_cost_estimates:
        (run_root / "cost_summary.json").write_text(
            json.dumps(all_cost_estimates, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # Write trace log
    trace.write(run_root / "trace.jsonl")

    suite_manifest = RunManifest(
        run_kind="bench_suite",
        run_id=run_root.name,
        created_at=run_dt.isoformat(timespec="seconds"),
        source=RunSource(path=suite.name),
        run_config=config or {},
        artifacts={
            "suite_used_json": "suite_used.json",
            "report_md": "report.md",
            "metrics_json": "metrics.json",
            "knobs_effective_json": "knobs_effective.json",
            "trace_jsonl": "trace.jsonl",
            "per_item_dir": "per_item",
            "cost_summary_json": "cost_summary.json"
            if (run_root / "cost_summary.json").exists()
            else None,
        },
    )
    try:
        write_run_manifest(run_root, suite_manifest)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to write run_manifest.json for bench suite at %s: %s",
            run_root,
            exc,
        )

    _notify(
        f"Suite complete. recall={agg['recall']:.3f}, precision={agg['precision']:.3f}"
    )
    return run_root, agg
