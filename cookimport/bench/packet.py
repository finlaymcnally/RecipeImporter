"""Iteration packet: ranked failure cases + context for debugging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_LABEL_IMPORTANCE = {
    "RECIPE_TITLE": 1.0,
    "INGREDIENT_LINE": 0.95,
    "INSTRUCTION_LINE": 0.90,
    "NOTES": 0.50,
    "TIP": 0.45,
    "VARIANT": 0.40,
    "YIELD_LINE": 0.35,
    "TIME_LINE": 0.30,
    "OTHER": 0.15,
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _load_archive(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _block_text_window(
    archive: list[dict[str, Any]],
    start: int,
    end: int,
    *,
    context: int = 2,
) -> list[str]:
    """Extract block texts around [start, end] with context."""
    lo = max(0, start - context)
    hi = min(len(archive), end + context + 1)
    return [
        archive[i].get("text", "") for i in range(lo, hi) if i < len(archive)
    ]


def _severity(label: str, case_type: str) -> float:
    base = _LABEL_IMPORTANCE.get(label, 0.2)
    if case_type == "missed_gold":
        return base * 1.0
    if case_type == "false_positive":
        return base * 0.7
    return base * 0.5


def build_iteration_packet(
    run_root: Path,
    *,
    baseline_run_dir: Path | None = None,
    top_n: int = 20,
) -> None:
    """Build an iteration packet from a bench suite run.

    Reads per-item eval artifacts and produces a self-contained packet
    with ranked failure cases and context windows.
    """
    packet_dir = run_root / "iteration_packet"
    packet_dir.mkdir(parents=True, exist_ok=True)

    per_item_dir = run_root / "per_item"
    if not per_item_dir.exists():
        return

    all_cases: list[dict[str, Any]] = []
    item_summaries: list[dict[str, Any]] = []

    for item_dir in sorted(per_item_dir.iterdir()):
        if not item_dir.is_dir():
            continue
        item_id = item_dir.name
        eval_dir = item_dir / "eval_freeform"
        pred_dir = item_dir / "pred_run"

        missed = _load_jsonl(eval_dir / "missed_gold_spans.jsonl")
        fps = _load_jsonl(eval_dir / "false_positive_preds.jsonl")
        archive = _load_archive(pred_dir / "extracted_archive.json")

        eval_report = {}
        report_path = eval_dir / "eval_report.json"
        if report_path.exists():
            eval_report = json.loads(report_path.read_text(encoding="utf-8"))

        item_summaries.append({
            "item_id": item_id,
            "gold_total": eval_report.get("counts", {}).get("gold_total", 0),
            "recall": eval_report.get("recall", 0),
            "precision": eval_report.get("precision", 0),
            "missed_count": len(missed),
            "fp_count": len(fps),
        })

        for span in missed:
            label = span.get("label", "OTHER")
            start = span.get("start_block_index", 0)
            end = span.get("end_block_index", start)
            case = {
                "case_type": "missed_gold",
                "item_id": item_id,
                "label": label,
                "gold_range": [start, end],
                "pred_range": None,
                "block_text_window": _block_text_window(archive, start, end),
                "severity": _severity(label, "missed_gold"),
            }
            all_cases.append(case)

        # Group false positives by label
        for span in fps:
            label = span.get("label", "OTHER")
            start = span.get("start_block_index", 0)
            end = span.get("end_block_index", start)
            case = {
                "case_type": "false_positive",
                "item_id": item_id,
                "label": label,
                "gold_range": None,
                "pred_range": [start, end],
                "block_text_window": _block_text_window(archive, start, end),
                "severity": _severity(label, "false_positive"),
            }
            all_cases.append(case)

    # Sort by severity descending
    all_cases.sort(key=lambda c: c["severity"], reverse=True)

    # Write cases.jsonl
    cases_path = packet_dir / "cases.jsonl"
    lines = [json.dumps(case) for case in all_cases]
    cases_path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")

    # Compute metric deltas if baseline provided
    deltas: dict[str, Any] = {}
    if baseline_run_dir and (baseline_run_dir / "metrics.json").exists():
        baseline_metrics = json.loads(
            (baseline_run_dir / "metrics.json").read_text(encoding="utf-8")
        )
        current_metrics_path = run_root / "metrics.json"
        if current_metrics_path.exists():
            current_metrics = json.loads(
                current_metrics_path.read_text(encoding="utf-8")
            )
            deltas = {
                "recall_delta": current_metrics.get("recall", 0) - baseline_metrics.get("recall", 0),
                "precision_delta": current_metrics.get("precision", 0) - baseline_metrics.get("precision", 0),
                "gold_matched_delta": (
                    current_metrics.get("counts", {}).get("gold_matched", 0)
                    - baseline_metrics.get("counts", {}).get("gold_matched", 0)
                ),
            }

    # Write summary.md
    summary_lines = ["# Iteration Packet Summary", ""]
    if deltas:
        summary_lines.extend([
            "## Metric Deltas (vs baseline)",
            f"- Recall delta: {deltas['recall_delta']:+.3f}",
            f"- Precision delta: {deltas['precision_delta']:+.3f}",
            f"- Gold matched delta: {deltas['gold_matched_delta']:+d}",
            "",
        ])
    summary_lines.extend([
        f"Total cases: {len(all_cases)}",
        f"- Missed gold spans: {sum(1 for c in all_cases if c['case_type'] == 'missed_gold')}",
        f"- False positives: {sum(1 for c in all_cases if c['case_type'] == 'false_positive')}",
        "",
        "## Per-Item",
        "",
    ])
    for s in item_summaries:
        summary_lines.append(
            f"- **{s['item_id']}**: recall={s['recall']:.3f}, "
            f"precision={s['precision']:.3f}, "
            f"missed={s['missed_count']}, fp={s['fp_count']}"
        )
    summary_lines.append("")
    (packet_dir / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    # Write top_failures.md
    top = all_cases[:top_n]
    failure_lines = [f"# Top {len(top)} Failures", ""]
    for i, case in enumerate(top, 1):
        rng = case.get("gold_range") or case.get("pred_range") or []
        failure_lines.extend([
            f"## {i}. [{case['case_type']}] {case['label']} in {case['item_id']}",
            f"Range: {rng}  Severity: {case['severity']:.2f}",
            "",
            "```",
            *case.get("block_text_window", []),
            "```",
            "",
        ])
    (packet_dir / "top_failures.md").write_text(
        "\n".join(failure_lines), encoding="utf-8"
    )

    # Write README.md
    readme = (
        "# Iteration Packet\n\n"
        "This packet contains ranked failure cases from the most recent bench run.\n\n"
        "- `summary.md` — metric overview + deltas vs baseline\n"
        "- `cases.jsonl` — all failure cases, sorted by severity\n"
        "- `top_failures.md` — top N failures with block text context\n\n"
        "Use these to identify the highest-impact parsing improvements.\n"
    )
    (packet_dir / "README.md").write_text(readme, encoding="utf-8")
