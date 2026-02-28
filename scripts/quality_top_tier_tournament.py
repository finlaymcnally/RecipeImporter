#!/usr/bin/env python3
"""Run multi-seed QualitySuite tournaments and gate candidates with fixed certainty thresholds."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import shlex
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_EXPERIMENTS_FILE = (
    "data/golden/bench/quality/experiments/"
    "2026-02-28_10.31.55_qualitysuite-top-tier-tournament.json"
)
DEFAULT_THRESHOLDS_FILE = (
    "data/golden/bench/quality/thresholds/"
    "2026-02-28_10.31.55_qualitysuite-top-tier-gates.json"
)
_ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV = "COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT"


def _timestamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _run_command(
    cmd: list[str],
    *,
    dry_run: bool,
    env: dict[str, str] | None = None,
) -> None:
    rendered = " ".join(shlex.quote(str(part)) for part in cmd)
    print(f"$ {rendered}")
    if dry_run:
        return
    effective_env = None
    if env:
        merged_env = dict(os.environ)
        merged_env.update(env)
        effective_env = merged_env
    subprocess.run(cmd, check=True, env=effective_env)


def _latest_timestamp_dir(path: Path) -> Path:
    candidates = [entry for entry in path.iterdir() if entry.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No run directories found under {path}")
    return sorted(candidates, key=lambda entry: entry.name)[-1]


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_experiment_ids(experiments_payload: dict[str, Any]) -> list[str]:
    schema_version = int(experiments_payload.get("schema_version", 1))
    ids: list[str] = []
    if schema_version == 2:
        include_baseline = bool(experiments_payload.get("include_baseline", True))
        baseline_id = str(experiments_payload.get("baseline_id") or "baseline").strip()
        if include_baseline and baseline_id:
            ids.append(baseline_id)
        include_all_on = bool(experiments_payload.get("include_all_on", False))
        all_on_id = str(experiments_payload.get("all_on_id") or "all_on").strip()
        if include_all_on and all_on_id:
            ids.append(all_on_id)
    rows = experiments_payload.get("experiments") or []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            experiment_id = str(row.get("id") or "").strip()
            if experiment_id:
                ids.append(experiment_id)
    deduped: list[str] = []
    seen: set[str] = set()
    for experiment_id in ids:
        if experiment_id in seen:
            continue
        seen.add(experiment_id)
        deduped.append(experiment_id)
    return deduped


def _find_summary_row(summary: dict[str, Any], experiment_id: str) -> dict[str, Any] | None:
    rows = summary.get("experiments")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").strip() == experiment_id:
            return row
    return None


def _metric_delta(candidate: dict[str, Any], baseline: dict[str, Any], key: str) -> float | None:
    baseline_value = _coerce_float(baseline.get(key))
    candidate_value = _coerce_float(candidate.get(key))
    if baseline_value is None or candidate_value is None:
        return None
    return candidate_value - baseline_value


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _render_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.4f}"


def _suite_signature(payload: dict[str, Any]) -> str:
    selection = payload.get("selection")
    if not isinstance(selection, dict):
        selection = {}
    selected_ids_raw = payload.get("selected_target_ids")
    selected_ids = (
        sorted(str(item) for item in selected_ids_raw)
        if isinstance(selected_ids_raw, list)
        else []
    )
    signature_payload = {
        "selected_target_ids": selected_ids,
        "selection_mode": str(selection.get("selection_mode") or "").strip(),
        "target_count_selected": len(selected_ids),
    }
    canonical = json.dumps(
        signature_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_filtered_experiments_payload(
    *,
    source_payload: dict[str, Any],
    source_experiments_file: Path,
    selected_experiment_ids: set[str],
) -> dict[str, Any]:
    filtered = copy.deepcopy(source_payload)
    schema_version = int(filtered.get("schema_version", 1))

    base_settings_file_raw = str(filtered.get("base_run_settings_file") or "").strip()
    if base_settings_file_raw:
        base_settings_candidate = Path(base_settings_file_raw)
        if not base_settings_candidate.is_absolute():
            base_settings_candidate = (
                source_experiments_file.parent / base_settings_candidate
            ).resolve()
        filtered["base_run_settings_file"] = str(base_settings_candidate)

    if schema_version == 1:
        rows = filtered.get("experiments")
        if isinstance(rows, list):
            filtered["experiments"] = [
                row
                for row in rows
                if isinstance(row, dict)
                and str(row.get("id") or "").strip() in selected_experiment_ids
            ]
        return filtered

    if schema_version != 2:
        return filtered

    baseline_id = str(filtered.get("baseline_id") or "baseline").strip()
    include_baseline = bool(filtered.get("include_baseline", True))
    filtered["include_baseline"] = (
        include_baseline
        and baseline_id in selected_experiment_ids
    )

    experiment_rows = filtered.get("experiments")
    if isinstance(experiment_rows, list):
        filtered["experiments"] = [
            row
            for row in experiment_rows
            if isinstance(row, dict)
            and str(row.get("id") or "").strip() in selected_experiment_ids
        ]

    all_on_id = str(filtered.get("all_on_id") or "all_on").strip()
    include_all_on = bool(filtered.get("include_all_on", False))
    filtered["include_all_on"] = (
        include_all_on and all_on_id in selected_experiment_ids
    )

    lever_rows = filtered.get("levers")
    if isinstance(lever_rows, list):
        if bool(filtered.get("include_all_on", False)):
            filtered["levers"] = [
                row for row in lever_rows if isinstance(row, dict)
            ]
        else:
            filtered["levers"] = [
                row
                for row in lever_rows
                if isinstance(row, dict)
                and str(row.get("id") or "").strip() in selected_experiment_ids
            ]
    return filtered


def _candidate_comparison_rows(
    *,
    fold_rows: list[dict[str, Any]],
    candidate_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fold in fold_rows:
        comparisons = fold.get("comparisons")
        if not isinstance(comparisons, dict):
            continue
        row = comparisons.get(candidate_id)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _optimistic_mean_upper_bound(
    *,
    observed_values: list[float],
    remaining_folds: int,
) -> float | None:
    count = len(observed_values) + max(0, int(remaining_folds))
    if count <= 0:
        return None
    return (float(sum(observed_values)) + float(max(0, int(remaining_folds)))) / float(
        count
    )


def _candidate_pruning_decision(
    *,
    candidate_id: str,
    fold_rows: list[dict[str, Any]],
    gates: dict[str, Any],
    total_unique_folds: int,
) -> dict[str, Any]:
    comparison_rows = _candidate_comparison_rows(
        fold_rows=fold_rows,
        candidate_id=candidate_id,
    )
    evaluated_folds = len(fold_rows)
    remaining_folds = max(0, int(total_unique_folds) - evaluated_folds)
    completed_rows = [row for row in comparison_rows if bool(row.get("completed"))]
    completed_count = len(completed_rows)
    non_regression_count = sum(
        1 for row in comparison_rows if bool(row.get("non_regression"))
    )
    uplift_count = sum(1 for row in comparison_rows if bool(row.get("uplift")))

    strict_deltas = [
        float(row["strict_f1_delta"])
        for row in completed_rows
        if row.get("strict_f1_delta") is not None
    ]
    practical_deltas = [
        float(row["practical_f1_delta"])
        for row in completed_rows
        if row.get("practical_f1_delta") is not None
    ]
    source_deltas = [
        float(row["source_success_rate_delta"])
        for row in completed_rows
        if row.get("source_success_rate_delta") is not None
    ]

    min_completed_folds = int(gates.get("min_completed_folds", total_unique_folds))
    min_non_reg_ratio = float(gates.get("min_non_regression_fold_ratio", 1.0))
    min_uplift_ratio = float(gates.get("min_uplift_fold_ratio", 1.0))
    min_mean_strict = float(gates.get("min_mean_strict_f1_delta", 0.0))
    min_mean_practical = float(gates.get("min_mean_practical_f1_delta", 0.0))
    min_mean_source = float(gates.get("min_mean_source_success_rate_delta", 0.0))

    max_completed = completed_count + remaining_folds
    max_non_reg_ratio = _safe_ratio(
        non_regression_count + remaining_folds,
        max(1, int(total_unique_folds)),
    )
    max_uplift_ratio = _safe_ratio(
        uplift_count + remaining_folds,
        max(1, int(total_unique_folds)),
    )
    max_mean_strict = _optimistic_mean_upper_bound(
        observed_values=strict_deltas,
        remaining_folds=remaining_folds,
    )
    max_mean_practical = _optimistic_mean_upper_bound(
        observed_values=practical_deltas,
        remaining_folds=remaining_folds,
    )
    max_mean_source = _optimistic_mean_upper_bound(
        observed_values=source_deltas,
        remaining_folds=remaining_folds,
    )

    reasons: list[str] = []
    if max_completed < min_completed_folds:
        reasons.append(
            f"max_completed={max_completed} < min_completed_folds={min_completed_folds}"
        )
    if max_non_reg_ratio < min_non_reg_ratio:
        reasons.append(
            "max_non_regression_ratio="
            f"{max_non_reg_ratio:.3f} < {min_non_reg_ratio:.3f}"
        )
    if max_uplift_ratio < min_uplift_ratio:
        reasons.append(
            f"max_uplift_ratio={max_uplift_ratio:.3f} < {min_uplift_ratio:.3f}"
        )

    if max_mean_strict is None or max_mean_strict < min_mean_strict:
        rendered = "n/a" if max_mean_strict is None else f"{max_mean_strict:.4f}"
        reasons.append(f"max_mean_strict_delta={rendered} < {min_mean_strict:.4f}")
    if max_mean_practical is None or max_mean_practical < min_mean_practical:
        rendered = "n/a" if max_mean_practical is None else f"{max_mean_practical:.4f}"
        reasons.append(f"max_mean_practical_delta={rendered} < {min_mean_practical:.4f}")
    if max_mean_source is None or max_mean_source < min_mean_source:
        rendered = "n/a" if max_mean_source is None else f"{max_mean_source:.4f}"
        reasons.append(f"max_mean_source_delta={rendered} < {min_mean_source:.4f}")

    return {
        "candidate_id": candidate_id,
        "impossible": bool(reasons),
        "reasons": reasons,
        "evaluated_folds": evaluated_folds,
        "remaining_folds": remaining_folds,
        "optimistic_bounds": {
            "max_completed_folds": max_completed,
            "max_non_regression_ratio": max_non_reg_ratio,
            "max_uplift_ratio": max_uplift_ratio,
            "max_mean_strict_f1_delta": max_mean_strict,
            "max_mean_practical_f1_delta": max_mean_practical,
            "max_mean_source_success_rate_delta": max_mean_source,
        },
    }


def _compare_candidate(
    *,
    candidate_id: str,
    candidate_row: dict[str, Any] | None,
    baseline_row: dict[str, Any],
    gates: dict[str, Any],
) -> dict[str, Any]:
    status = str((candidate_row or {}).get("status") or "missing").strip().lower()
    baseline_status = str(baseline_row.get("status") or "").strip().lower()

    strict_delta = _metric_delta(candidate_row or {}, baseline_row, "strict_f1_macro")
    practical_delta = _metric_delta(candidate_row or {}, baseline_row, "practical_f1_macro")
    source_delta = _metric_delta(candidate_row or {}, baseline_row, "source_success_rate")

    strict_drop_max = float(gates.get("strict_f1_drop_max_per_fold", 0.0))
    practical_drop_max = float(gates.get("practical_f1_drop_max_per_fold", 0.0))
    source_drop_max = float(gates.get("source_success_rate_drop_max_per_fold", 0.0))

    strict_uplift_min = float(gates.get("strict_f1_uplift_min_per_fold", 0.0))
    practical_uplift_min = float(gates.get("practical_f1_uplift_min_per_fold", 0.0))
    source_uplift_min = float(gates.get("source_success_rate_uplift_min_per_fold", 0.0))

    strict_drop = None if strict_delta is None else max(0.0, 0.0 - strict_delta)
    practical_drop = None if practical_delta is None else max(0.0, 0.0 - practical_delta)
    source_drop = None if source_delta is None else max(0.0, 0.0 - source_delta)

    completed = (
        candidate_row is not None
        and status == "ok"
        and baseline_status == "ok"
        and strict_delta is not None
        and practical_delta is not None
        and source_delta is not None
    )

    non_regression = (
        completed
        and strict_drop is not None
        and strict_drop <= strict_drop_max
        and practical_drop is not None
        and practical_drop <= practical_drop_max
        and source_drop is not None
        and source_drop <= source_drop_max
    )
    uplift = (
        completed
        and strict_delta is not None
        and strict_delta >= strict_uplift_min
        and practical_delta is not None
        and practical_delta >= practical_uplift_min
        and source_delta is not None
        and source_delta >= source_uplift_min
    )

    return {
        "candidate_id": candidate_id,
        "candidate_status": status,
        "completed": completed,
        "non_regression": non_regression,
        "uplift": uplift,
        "strict_f1_delta": strict_delta,
        "practical_f1_delta": practical_delta,
        "source_success_rate_delta": source_delta,
        "strict_f1_drop": strict_drop,
        "practical_f1_drop": practical_drop,
        "source_success_rate_drop": source_drop,
    }


def _run_leaderboard(
    *,
    cookimport_cmd: str,
    run_dir: Path,
    experiment_id: str,
    out_dir: Path,
    dry_run: bool,
) -> dict[str, Any] | None:
    _run_command(
        [
            cookimport_cmd,
            "bench",
            "quality-leaderboard",
            "--run-dir",
            str(run_dir),
            "--experiment-id",
            experiment_id,
            "--out-dir",
            str(out_dir),
            "--top-n",
            "1",
        ],
        dry_run=dry_run,
    )
    if dry_run:
        return None
    leaderboard_path = out_dir / "leaderboard.json"
    payload = _load_json_object(leaderboard_path)
    rows = payload.get("leaderboard")
    if not isinstance(rows, list) or not rows:
        return {
            "leaderboard_json_path": str(leaderboard_path),
            "winner": None,
        }
    first_row = rows[0]
    if not isinstance(first_row, dict):
        return {
            "leaderboard_json_path": str(leaderboard_path),
            "winner": None,
        }
    return {
        "leaderboard_json_path": str(leaderboard_path),
        "winner": {
            "run_config_hash": first_row.get("run_config_hash"),
            "mean_strict_f1": first_row.get("mean_strict_f1"),
            "mean_practical_f1": first_row.get("mean_practical_f1"),
            "mean_duration_seconds": first_row.get("mean_duration_seconds"),
            "dimensions": first_row.get("dimensions"),
        },
    }


def _aggregate_candidates(
    *,
    fold_rows: list[dict[str, Any]],
    candidate_ids: list[str],
    gates: dict[str, Any],
    total_folds: int,
) -> dict[str, Any]:
    min_completed_folds = int(gates.get("min_completed_folds", total_folds))
    min_non_reg_ratio = float(gates.get("min_non_regression_fold_ratio", 1.0))
    min_uplift_ratio = float(gates.get("min_uplift_fold_ratio", 1.0))
    min_mean_strict = float(gates.get("min_mean_strict_f1_delta", 0.0))
    min_mean_practical = float(gates.get("min_mean_practical_f1_delta", 0.0))
    min_mean_source = float(gates.get("min_mean_source_success_rate_delta", 0.0))

    aggregated: dict[str, Any] = {}
    for candidate_id in candidate_ids:
        comparisons = [
            fold.get("comparisons", {}).get(candidate_id)
            for fold in fold_rows
            if isinstance(fold, dict)
        ]
        comparison_rows = [row for row in comparisons if isinstance(row, dict)]

        completed_rows = [row for row in comparison_rows if bool(row.get("completed"))]
        non_regression_count = sum(
            1 for row in comparison_rows if bool(row.get("non_regression"))
        )
        uplift_count = sum(1 for row in comparison_rows if bool(row.get("uplift")))

        strict_deltas = [
            float(row["strict_f1_delta"])
            for row in completed_rows
            if row.get("strict_f1_delta") is not None
        ]
        practical_deltas = [
            float(row["practical_f1_delta"])
            for row in completed_rows
            if row.get("practical_f1_delta") is not None
        ]
        source_deltas = [
            float(row["source_success_rate_delta"])
            for row in completed_rows
            if row.get("source_success_rate_delta") is not None
        ]

        mean_strict = statistics.fmean(strict_deltas) if strict_deltas else None
        mean_practical = statistics.fmean(practical_deltas) if practical_deltas else None
        mean_source = statistics.fmean(source_deltas) if source_deltas else None

        winner_hashes: list[str] = []
        winner_dimensions_by_hash: dict[str, dict[str, Any]] = {}
        for fold in fold_rows:
            experiment_payload = (fold.get("experiments") or {}).get(candidate_id)
            if not isinstance(experiment_payload, dict):
                continue
            leaderboard = experiment_payload.get("leaderboard") or {}
            winner = leaderboard.get("winner") or {}
            run_config_hash = str(winner.get("run_config_hash") or "").strip()
            if not run_config_hash:
                continue
            winner_hashes.append(run_config_hash)
            dimensions = winner.get("dimensions")
            if isinstance(dimensions, dict):
                winner_dimensions_by_hash.setdefault(run_config_hash, dimensions)

        winner_hash_counter = Counter(winner_hashes)
        winner_mode_hash = None
        winner_mode_count = 0
        winner_mode_dimensions = None
        if winner_hash_counter:
            winner_mode_hash, winner_mode_count = winner_hash_counter.most_common(1)[0]
            winner_mode_dimensions = winner_dimensions_by_hash.get(winner_mode_hash)

        completed_count = len(completed_rows)
        non_regression_ratio = _safe_ratio(non_regression_count, total_folds)
        uplift_ratio = _safe_ratio(uplift_count, total_folds)

        passed = (
            completed_count >= min_completed_folds
            and non_regression_ratio >= min_non_reg_ratio
            and uplift_ratio >= min_uplift_ratio
            and mean_strict is not None
            and mean_strict >= min_mean_strict
            and mean_practical is not None
            and mean_practical >= min_mean_practical
            and mean_source is not None
            and mean_source >= min_mean_source
        )

        aggregated[candidate_id] = {
            "passed": passed,
            "completed_folds": completed_count,
            "non_regression_folds": non_regression_count,
            "uplift_folds": uplift_count,
            "non_regression_ratio": non_regression_ratio,
            "uplift_ratio": uplift_ratio,
            "mean_strict_f1_delta": mean_strict,
            "mean_practical_f1_delta": mean_practical,
            "mean_source_success_rate_delta": mean_source,
            "winner_hash_mode": winner_mode_hash,
            "winner_hash_mode_count": winner_mode_count,
            "winner_hash_mode_ratio": _safe_ratio(winner_mode_count, total_folds),
            "winner_hash_mode_dimensions": winner_mode_dimensions,
            "winner_hash_counts": dict(sorted(winner_hash_counter.items())),
        }
    return aggregated


def _render_report(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Quality Top-Tier Tournament Report")
    lines.append("")
    lines.append(f"- Generated at: {payload.get('generated_at')}")
    lines.append(f"- Tournament root: {payload.get('tournament_root')}")
    lines.append(f"- Experiments file: {payload.get('experiments_file')}")
    lines.append(f"- Thresholds file: {payload.get('thresholds_file')}")
    lines.append(f"- Baseline experiment: {payload.get('baseline_experiment_id')}")
    lines.append(
        f"- Candidate experiments: {', '.join(payload.get('candidate_experiment_ids') or [])}"
    )
    lines.append(f"- Configured folds: {payload.get('configured_folds')}")
    lines.append(f"- Effective folds (gated): {payload.get('total_folds')}")
    lines.append(
        f"- Duplicate-suite folds skipped: {payload.get('duplicate_suite_folds_skipped')}"
    )
    lines.append(
        "- Shared alignment cache root: "
        f"{payload.get('shared_alignment_cache_root')}"
    )
    lines.append(f"- Planned unique folds: {payload.get('planned_unique_folds')}")
    lines.append(f"- Quality runs executed: {payload.get('quality_runs_executed')}")
    lines.append(
        "- Gate-impossibility pruning enabled: "
        f"{payload.get('gate_impossibility_pruning_enabled')}"
    )
    lines.append(f"- Dry run: {payload.get('dry_run')}")
    lines.append("")
    lines.append("## Gate Thresholds")
    lines.append("")
    for key, value in sorted((payload.get("gates") or {}).items()):
        lines.append(f"- {key}: {value}")
    lines.append("")

    lines.append("## Candidate Verdicts")
    lines.append("")
    candidates = payload.get("candidates") or {}
    for candidate_id in sorted(candidates):
        row = candidates[candidate_id]
        verdict = "PASS" if row.get("passed") else "FAIL"
        lines.append(
            "- "
            f"{candidate_id}: {verdict} | "
            f"completed={row.get('completed_folds')}/{payload.get('total_folds')} | "
            f"non_reg={row.get('non_regression_folds')}/{payload.get('total_folds')} "
            f"({row.get('non_regression_ratio', 0.0):.2f}) | "
            f"uplift={row.get('uplift_folds')}/{payload.get('total_folds')} "
            f"({row.get('uplift_ratio', 0.0):.2f}) | "
            f"mean_delta(strict={_render_metric(row.get('mean_strict_f1_delta'))}, "
            f"practical={_render_metric(row.get('mean_practical_f1_delta'))}, "
            f"source={_render_metric(row.get('mean_source_success_rate_delta'))})"
        )
        mode_hash = row.get("winner_hash_mode")
        mode_ratio = row.get("winner_hash_mode_ratio")
        if mode_hash:
            lines.append(
                f"  winner hash mode: {mode_hash} ({mode_ratio:.2f} of folds)"
            )
        mode_dimensions = row.get("winner_hash_mode_dimensions")
        if isinstance(mode_dimensions, dict) and mode_dimensions:
            lines.append(
                "  winner dimensions mode: "
                f"{json.dumps(mode_dimensions, sort_keys=True)}"
            )
    lines.append("")

    top_tier = payload.get("top_tier_candidates") or []
    lines.append("## Top-Tier Set")
    lines.append("")
    if not top_tier:
        lines.append("- None")
    else:
        lines.append(f"- {', '.join(top_tier)}")
    lines.append("")

    pruned_candidates = payload.get("pruned_candidates") or {}
    lines.append("## Pruned Candidates")
    lines.append("")
    if not isinstance(pruned_candidates, dict) or not pruned_candidates:
        lines.append("- None")
    else:
        for candidate_id in sorted(pruned_candidates):
            row = pruned_candidates[candidate_id]
            fold_index = row.get("pruned_after_fold_index")
            reasons = row.get("reasons")
            if isinstance(reasons, list) and reasons:
                rendered_reasons = "; ".join(str(reason) for reason in reasons)
            else:
                rendered_reasons = "n/a"
            lines.append(
                f"- {candidate_id}: fold={fold_index}, reasons={rendered_reasons}"
            )
    lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run multi-seed quality tournaments and compute PASS/FAIL certainty gates "
            "for candidate experiment profiles."
        )
    )
    parser.add_argument(
        "--experiments-file",
        default=DEFAULT_EXPERIMENTS_FILE,
        help="Experiments JSON (schema v1/v2) used by bench quality-run.",
    )
    parser.add_argument(
        "--thresholds-file",
        default=DEFAULT_THRESHOLDS_FILE,
        help="Threshold and fold config JSON.",
    )
    parser.add_argument(
        "--gold-root",
        default="data/golden/pulled-from-labelstudio",
        help="Gold root passed to bench quality-discover.",
    )
    parser.add_argument(
        "--input-root",
        default="data/input",
        help="Input root passed to bench quality-discover.",
    )
    parser.add_argument(
        "--output-root",
        default="data/golden/bench/quality/tournaments",
        help="Output root for tournament artifacts.",
    )
    parser.add_argument(
        "--cookimport-cmd",
        default=".venv/bin/cookimport",
        help="Cookimport executable path.",
    )
    parser.add_argument(
        "--max-parallel-experiments",
        type=int,
        default=None,
        help=(
            "Forwarded to bench quality-run. Omit to use quality-run auto mode "
            "(CPU/load-aware adaptive parallelism)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands and write resolved config without executing quality jobs.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    experiments_file = Path(args.experiments_file)
    thresholds_file = Path(args.thresholds_file)
    if not experiments_file.exists():
        raise FileNotFoundError(f"Missing experiments file: {experiments_file}")
    if not thresholds_file.exists():
        raise FileNotFoundError(f"Missing thresholds file: {thresholds_file}")

    experiments_payload = _load_json_object(experiments_file)
    thresholds_payload = _load_json_object(thresholds_file)

    suite_config = thresholds_payload.get("suite") or {}
    quality_run_config = thresholds_payload.get("quality_run") or {}
    comparison_config = thresholds_payload.get("comparison") or {}
    gates = thresholds_payload.get("gates") or {}

    seeds_raw = suite_config.get("seeds") or []
    if not isinstance(seeds_raw, list) or not seeds_raw:
        raise ValueError("thresholds.suite.seeds must be a non-empty array")
    seeds = [int(seed) for seed in seeds_raw]

    max_targets = suite_config.get("max_targets")
    max_targets_int = int(max_targets) if max_targets is not None else None
    prefer_curated = bool(suite_config.get("prefer_curated", True))

    baseline_experiment_id = str(
        comparison_config.get("baseline_experiment_id") or "baseline"
    ).strip()
    all_experiment_ids = _extract_experiment_ids(experiments_payload)
    if baseline_experiment_id not in all_experiment_ids:
        available = ", ".join(all_experiment_ids) or "<none>"
        raise ValueError(
            "Baseline experiment id is missing from experiments file: "
            f"{baseline_experiment_id} (available: {available})"
        )

    configured_candidates = comparison_config.get("candidate_experiment_ids") or []
    if configured_candidates:
        candidate_experiment_ids = [str(item).strip() for item in configured_candidates]
    else:
        candidate_experiment_ids = [
            item for item in all_experiment_ids if item != baseline_experiment_id
        ]
    candidate_experiment_ids = [item for item in candidate_experiment_ids if item]
    if not candidate_experiment_ids:
        raise ValueError("No candidate experiments configured/resolved.")

    timestamp = _timestamp()
    output_root = Path(args.output_root)
    tournament_root = output_root / timestamp
    tournament_root.mkdir(parents=True, exist_ok=True)
    configured_alignment_cache_root = str(
        quality_run_config.get("canonical_alignment_cache_root") or ""
    ).strip()
    if configured_alignment_cache_root:
        shared_alignment_cache_root = str(
            Path(configured_alignment_cache_root).expanduser()
        )
    else:
        shared_alignment_cache_root = str(
            (output_root.parent / ".cache" / "canonical_alignment").resolve()
        )
    quality_run_env = {
        _ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV: shared_alignment_cache_root
    }

    resolved_payload = {
        "generated_at": timestamp,
        "tournament_root": str(tournament_root),
        "experiments_file": str(experiments_file),
        "thresholds_file": str(thresholds_file),
        "baseline_experiment_id": baseline_experiment_id,
        "candidate_experiment_ids": candidate_experiment_ids,
        "suite": {
            "seeds": seeds,
            "max_targets": max_targets_int,
            "prefer_curated": prefer_curated,
        },
        "quality_run": quality_run_config,
        "configured_fold_count": len(seeds),
        "shared_alignment_cache_root": shared_alignment_cache_root,
        "shared_alignment_cache_env_var": _ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV,
        "duplicate_suite_fold_dedup": True,
        "gate_impossibility_pruning": True,
        "gates": gates,
        "dry_run": bool(args.dry_run),
    }
    _write_json(tournament_root / "tournament_resolved.json", resolved_payload)

    fold_rows: list[dict[str, Any]] = []
    evaluated_fold_rows: list[dict[str, Any]] = []
    executable_folds: list[dict[str, Any]] = []
    seen_suite_signatures: dict[str, int] = {}
    duplicate_suite_folds_skipped = 0

    # Phase 1: discover suites and dedupe folds before executing any quality runs.
    for index, seed in enumerate(seeds, start=1):
        fold_slug = f"fold_{index:02d}_seed_{seed}"
        fold_root = tournament_root / fold_slug
        fold_root.mkdir(parents=True, exist_ok=True)
        suite_path = fold_root / "suite.json"
        run_out_dir = fold_root / "quality_runs"
        leaderboard_root = fold_root / "leaderboards"

        discover_cmd = [
            args.cookimport_cmd,
            "bench",
            "quality-discover",
            "--gold-root",
            args.gold_root,
            "--input-root",
            args.input_root,
            "--out",
            str(suite_path),
            "--seed",
            str(seed),
        ]
        if max_targets_int is not None:
            discover_cmd.extend(["--max-targets", str(max_targets_int)])
        if prefer_curated:
            discover_cmd.append("--prefer-curated")
        else:
            discover_cmd.append("--no-prefer-curated")
        _run_command(discover_cmd, dry_run=args.dry_run)

        suite_signature = None
        duplicate_suite_of_fold_index = None
        if not args.dry_run:
            suite_payload = _load_json_object(suite_path)
            suite_signature = _suite_signature(suite_payload)
            duplicate_suite_of_fold_index = seen_suite_signatures.get(suite_signature)
            if duplicate_suite_of_fold_index is None:
                seen_suite_signatures[suite_signature] = index

        fold_payload: dict[str, Any] = {
            "fold_index": index,
            "seed": seed,
            "suite_path": str(suite_path),
            "suite_signature": suite_signature,
            "duplicate_suite_of_fold_index": duplicate_suite_of_fold_index,
            "duplicate_suite_skipped": False,
            "run_out_dir": str(run_out_dir),
            "leaderboard_root": str(leaderboard_root),
            "run_dir": None,
            "executed_quality_run": False,
            "included_in_gates": False,
            "baseline": {},
            "experiments": {},
            "comparisons": {},
        }

        if duplicate_suite_of_fold_index is not None:
            fold_payload["duplicate_suite_skipped"] = True
            fold_payload["note"] = (
                "Skipped quality-run; suite signature duplicates fold "
                f"{duplicate_suite_of_fold_index}."
            )
            duplicate_suite_folds_skipped += 1
            _write_json(fold_root / "fold_result.json", fold_payload)
            fold_rows.append(fold_payload)
            continue

        fold_rows.append(fold_payload)
        executable_folds.append(fold_payload)

    total_unique_folds_planned = len(executable_folds)
    active_candidate_ids = list(candidate_experiment_ids)
    pruned_candidates: dict[str, dict[str, Any]] = {}
    quality_runs_executed = 0
    early_stop_triggered = False

    # Phase 2: run quality experiments only for unique folds, pruning impossible candidates.
    for fold_payload in executable_folds:
        fold_index = int(fold_payload.get("fold_index", 0))
        fold_root = tournament_root / f"fold_{fold_index:02d}_seed_{fold_payload.get('seed')}"
        run_out_dir = Path(str(fold_payload.get("run_out_dir")))
        leaderboard_root = Path(str(fold_payload.get("leaderboard_root")))
        suite_path = Path(str(fold_payload.get("suite_path")))

        if not args.dry_run and not active_candidate_ids:
            early_stop_triggered = True
            fold_payload["note"] = (
                "Skipped quality-run; all candidates are already gate-impossible."
            )
            _write_json(fold_root / "fold_result.json", fold_payload)
            continue

        selected_experiment_ids = set(active_candidate_ids)
        selected_experiment_ids.add(baseline_experiment_id)
        filtered_experiments_payload = _build_filtered_experiments_payload(
            source_payload=experiments_payload,
            source_experiments_file=experiments_file,
            selected_experiment_ids=selected_experiment_ids,
        )
        effective_experiments_file = fold_root / "experiments_effective.json"
        _write_json(effective_experiments_file, filtered_experiments_payload)
        fold_payload["effective_experiments_file"] = str(effective_experiments_file)
        fold_payload["active_candidate_ids_before_fold"] = sorted(active_candidate_ids)

        quality_run_cmd = [
            args.cookimport_cmd,
            "bench",
            "quality-run",
            "--suite",
            str(suite_path),
            "--experiments-file",
            str(effective_experiments_file),
            "--out-dir",
            str(run_out_dir),
            "--search-strategy",
            str(quality_run_config.get("search_strategy", "race")),
            "--race-probe-targets",
            str(int(quality_run_config.get("race_probe_targets", 2))),
            "--race-mid-targets",
            str(int(quality_run_config.get("race_mid_targets", 4))),
            "--race-keep-ratio",
            str(float(quality_run_config.get("race_keep_ratio", 0.35))),
            "--race-finalists",
            str(int(quality_run_config.get("race_finalists", 64))),
        ]
        if bool(quality_run_config.get("include_deterministic_sweeps", False)):
            quality_run_cmd.append("--include-deterministic-sweeps")
        if args.max_parallel_experiments is not None:
            quality_run_cmd.extend(
                [
                    "--max-parallel-experiments",
                    str(int(args.max_parallel_experiments)),
                ]
            )

        _run_command(
            quality_run_cmd,
            dry_run=args.dry_run,
            env=quality_run_env,
        )
        fold_payload["executed_quality_run"] = True

        if args.dry_run:
            _write_json(fold_root / "fold_result.json", fold_payload)
            continue

        quality_runs_executed += 1
        run_dir = _latest_timestamp_dir(run_out_dir)
        fold_payload["run_dir"] = str(run_dir)
        summary = _load_json_object(run_dir / "summary.json")
        baseline_row = _find_summary_row(summary, baseline_experiment_id)
        if baseline_row is None:
            raise ValueError(
                f"Baseline row '{baseline_experiment_id}' not found in {run_dir / 'summary.json'}"
            )
        fold_payload["baseline"] = {
            "status": baseline_row.get("status"),
            "strict_f1_macro": baseline_row.get("strict_f1_macro"),
            "practical_f1_macro": baseline_row.get("practical_f1_macro"),
            "source_success_rate": baseline_row.get("source_success_rate"),
        }

        selected_ids_in_order = [baseline_experiment_id, *sorted(active_candidate_ids)]
        for experiment_id in selected_ids_in_order:
            row = _find_summary_row(summary, experiment_id)
            leaderboard_dir = leaderboard_root / experiment_id
            leaderboard_payload = None
            leaderboard_error = None
            try:
                leaderboard_payload = _run_leaderboard(
                    cookimport_cmd=args.cookimport_cmd,
                    run_dir=run_dir,
                    experiment_id=experiment_id,
                    out_dir=leaderboard_dir,
                    dry_run=False,
                )
            except Exception as exc:  # noqa: BLE001
                leaderboard_error = str(exc)
            fold_payload["experiments"][experiment_id] = {
                "status": (row or {}).get("status"),
                "strict_f1_macro": (row or {}).get("strict_f1_macro"),
                "practical_f1_macro": (row or {}).get("practical_f1_macro"),
                "source_success_rate": (row or {}).get("source_success_rate"),
                "leaderboard": leaderboard_payload,
                "leaderboard_error": leaderboard_error,
            }
            if experiment_id == baseline_experiment_id:
                continue
            fold_payload["comparisons"][experiment_id] = _compare_candidate(
                candidate_id=experiment_id,
                candidate_row=row,
                baseline_row=baseline_row,
                gates=gates,
            )

        # Fill non-executed candidates for fold visibility and stable downstream aggregation.
        for experiment_id in candidate_experiment_ids:
            if experiment_id in fold_payload["comparisons"]:
                continue
            placeholder = _compare_candidate(
                candidate_id=experiment_id,
                candidate_row=None,
                baseline_row=baseline_row,
                gates=gates,
            )
            if experiment_id in pruned_candidates:
                placeholder["candidate_status"] = "pruned"
                placeholder["pruned"] = True
                placeholder["prune_reasons"] = list(
                    pruned_candidates[experiment_id].get("reasons") or []
                )
                fold_payload["experiments"][experiment_id] = {
                    "status": "pruned",
                    "leaderboard": None,
                    "leaderboard_error": None,
                }
            else:
                placeholder["candidate_status"] = "not_run"
                placeholder["not_run"] = True
                fold_payload["experiments"][experiment_id] = {
                    "status": "not_run",
                    "leaderboard": None,
                    "leaderboard_error": None,
                }
            fold_payload["comparisons"][experiment_id] = placeholder

        fold_payload["included_in_gates"] = True
        evaluated_fold_rows.append(fold_payload)

        remaining_unique_folds = max(0, total_unique_folds_planned - len(evaluated_fold_rows))
        pruned_after_fold: dict[str, dict[str, Any]] = {}
        for candidate_id in list(active_candidate_ids):
            decision = _candidate_pruning_decision(
                candidate_id=candidate_id,
                fold_rows=evaluated_fold_rows,
                gates=gates,
                total_unique_folds=total_unique_folds_planned,
            )
            if not bool(decision.get("impossible")):
                continue
            reason_rows = decision.get("reasons") or []
            pruned_payload = {
                "pruned_after_fold_index": fold_index,
                "remaining_unique_folds_at_prune": remaining_unique_folds,
                "reasons": [str(item) for item in reason_rows],
                "optimistic_bounds": decision.get("optimistic_bounds") or {},
            }
            pruned_candidates[candidate_id] = pruned_payload
            pruned_after_fold[candidate_id] = pruned_payload
            active_candidate_ids.remove(candidate_id)

        if pruned_after_fold:
            fold_payload["pruned_candidates_after_fold"] = pruned_after_fold
            for candidate_id, row in sorted(pruned_after_fold.items()):
                reasons_rendered = "; ".join(str(item) for item in row.get("reasons") or [])
                print(
                    f"Pruned candidate {candidate_id} after fold {fold_index}: "
                    f"{reasons_rendered}"
                )

        fold_payload["active_candidate_ids_after_fold"] = sorted(active_candidate_ids)
        _write_json(fold_root / "fold_result.json", fold_payload)

    effective_fold_count = len(evaluated_fold_rows)
    aggregated_candidates = _aggregate_candidates(
        fold_rows=evaluated_fold_rows,
        candidate_ids=candidate_experiment_ids,
        gates=gates,
        total_folds=effective_fold_count,
    )

    def _sort_value(value: Any) -> float:
        numeric = _coerce_float(value)
        if numeric is None:
            return -999.0
        return numeric

    top_tier_candidates = [
        candidate_id
        for candidate_id, row in sorted(
            aggregated_candidates.items(),
            key=lambda item: (
                not bool(item[1].get("passed")),
                -_sort_value(item[1].get("mean_strict_f1_delta")),
                -_sort_value(item[1].get("mean_practical_f1_delta")),
                item[0],
            ),
        )
        if bool(row.get("passed"))
    ]

    tournament_summary = {
        "generated_at": _timestamp(),
        "tournament_root": str(tournament_root),
        "experiments_file": str(experiments_file),
        "thresholds_file": str(thresholds_file),
        "baseline_experiment_id": baseline_experiment_id,
        "candidate_experiment_ids": candidate_experiment_ids,
        "configured_folds": len(seeds),
        "planned_unique_folds": total_unique_folds_planned,
        "total_folds": effective_fold_count,
        "duplicate_suite_folds_skipped": duplicate_suite_folds_skipped,
        "shared_alignment_cache_root": shared_alignment_cache_root,
        "quality_runs_executed": quality_runs_executed,
        "gate_impossibility_pruning_enabled": True,
        "pruned_candidates": pruned_candidates,
        "active_candidates_final": sorted(active_candidate_ids),
        "early_stop_triggered": bool(early_stop_triggered),
        "dry_run": bool(args.dry_run),
        "gates": gates,
        "candidates": aggregated_candidates,
        "top_tier_candidates": top_tier_candidates,
        "fold_result_paths": [
            str(tournament_root / f"fold_{index:02d}_seed_{seed}" / "fold_result.json")
            for index, seed in enumerate(seeds, start=1)
        ],
    }

    _write_json(tournament_root / "summary.json", tournament_summary)
    (tournament_root / "report.md").write_text(
        _render_report(tournament_summary),
        encoding="utf-8",
    )
    _write_json(tournament_root / "folds.json", {"folds": fold_rows})

    print("")
    print(f"Tournament root: {tournament_root}")
    print(f"Summary JSON: {tournament_root / 'summary.json'}")
    print(f"Report: {tournament_root / 'report.md'}")
    if top_tier_candidates:
        print(f"Top-tier candidates: {', '.join(top_tier_candidates)}")
    else:
        print("Top-tier candidates: <none>")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
