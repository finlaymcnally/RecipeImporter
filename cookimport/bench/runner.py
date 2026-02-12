"""Suite runner: orchestrates pred-run + eval for each bench item."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any, Callable

from cookimport.bench.pred_run import build_pred_run_for_source
from cookimport.bench.report import aggregate_metrics, format_suite_report_md
from cookimport.bench.suite import BenchSuite
from cookimport.labelstudio.eval_freeform import (
    evaluate_predicted_vs_freeform,
    format_freeform_eval_report_md,
    load_gold_freeform_ranges,
    load_predicted_labeled_ranges,
)


def _write_jsonl(path: Path, records: list[dict[str, Any] | Any]) -> None:
    lines = []
    for rec in records:
        if hasattr(rec, "__dict__") and not isinstance(rec, dict):
            from dataclasses import asdict
            rec = asdict(rec)
        lines.append(json.dumps(rec))
    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


def run_suite(
    suite: BenchSuite,
    out_dir: Path,
    *,
    repo_root: Path,
    config: dict | None = None,
    baseline_run_dir: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    """Run the full benchmark suite and write aggregate results.

    Returns the run root directory.
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

    per_item_results: list[dict[str, Any]] = []

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

        per_item_results.append({
            "item_id": item.item_id,
            "report": eval_result["report"],
            "missed_gold": eval_result["missed_gold"],
            "false_positive_preds": eval_result["false_positive_preds"],
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

    _notify(
        f"Suite complete. recall={agg['recall']:.3f}, precision={agg['precision']:.3f}"
    )
    return run_root
