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
import time
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_EXPERIMENTS_FILE = (
    "data/golden/bench/quality/experiments/"
    "2026-03-01_01.00.00_qualitysuite-parsing-phase-a-candidates.json"
)
DEFAULT_THRESHOLDS_FILE = (
    "data/golden/bench/quality/thresholds/"
    "2026-03-01_01.00.00_qualitysuite-parsing-phase-a-fast.json"
)
_ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV = "COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT"
_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV = (
    "COOKIMPORT_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT"
)
_SUPPORTED_SEARCH_STRATEGIES = {"race", "exhaustive"}
_QUICK_PARSING_CANDIDATE_IDS = (
    "pre_br_split",
    "pre_none",
    "skip_headers_false",
    "parser_v2_pre_br_skiphf_false",
)
_PHASE_A_TOP_TWO_CLOSE_PRACTICAL_DELTA = 0.003
_PHASE_A_CLEAR_WINNER_MIN_FOLDS = 2


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


def _load_json_object_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


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


def _merge_command_env(env: dict[str, str] | None = None) -> dict[str, str] | None:
    if not env:
        return None
    merged_env = dict(os.environ)
    merged_env.update(env)
    return merged_env


def _read_quality_run_subprogress(run_dir: Path) -> dict[str, Any] | None:
    checkpoint_payload = _load_json_object_if_exists(run_dir / "checkpoint.json")
    partial_summary_payload = _load_json_object_if_exists(run_dir / "summary.partial.json")
    if checkpoint_payload is None and partial_summary_payload is None:
        return None

    total = None
    completed = None
    pending = None
    status = None
    if isinstance(checkpoint_payload, dict):
        total_raw = checkpoint_payload.get("experiment_count_total")
        completed_raw = checkpoint_payload.get("experiment_count_completed")
        pending_ids_raw = checkpoint_payload.get("pending_experiment_ids")
        status = str(checkpoint_payload.get("status") or "").strip() or None
        if total_raw is not None:
            total = int(total_raw)
        if completed_raw is not None:
            completed = int(completed_raw)
        if isinstance(pending_ids_raw, list):
            pending = len(pending_ids_raw)
    if isinstance(partial_summary_payload, dict):
        partial_count_raw = partial_summary_payload.get("experiment_count")
        if partial_count_raw is not None:
            partial_count = int(partial_count_raw)
            if completed is None:
                completed = partial_count
            elif partial_count > completed:
                completed = partial_count
    if total is not None and completed is not None and pending is None:
        pending = max(0, total - completed)
    if completed is None or total is None:
        return None
    return {
        "run_dir": str(run_dir),
        "quality_run_status": status,
        "experiment_count_completed": completed,
        "experiment_count_total": total,
        "pending_experiment_count": pending if pending is not None else 0,
    }


def _run_quality_run_with_subprogress(
    *,
    cmd: list[str],
    dry_run: bool,
    env: dict[str, str] | None,
    fold_index: int,
    configured_folds: int,
    run_out_dir: Path,
    resume_run_dir: Path | None,
    progress_callback: Any | None,
    poll_seconds: float = 1.0,
) -> Path | None:
    rendered = " ".join(shlex.quote(str(part)) for part in cmd)
    print(f"$ {rendered}")
    if dry_run:
        return resume_run_dir

    process = subprocess.Popen(cmd, env=_merge_command_env(env))
    active_run_dir = resume_run_dir
    last_state: tuple[Any, ...] | None = None
    sleep_seconds = max(0.1, float(poll_seconds))

    while True:
        if active_run_dir is None:
            active_run_dir = _latest_partial_quality_run_dir(run_out_dir)
            if active_run_dir is None and run_out_dir.exists() and run_out_dir.is_dir():
                try:
                    active_run_dir = _latest_timestamp_dir(run_out_dir)
                except Exception:  # noqa: BLE001
                    active_run_dir = None

        if active_run_dir is not None:
            progress_row = _read_quality_run_subprogress(active_run_dir)
            if progress_row is not None:
                state = (
                    str(progress_row.get("run_dir") or ""),
                    int(progress_row.get("experiment_count_completed") or 0),
                    int(progress_row.get("experiment_count_total") or 0),
                    int(progress_row.get("pending_experiment_count") or 0),
                    str(progress_row.get("quality_run_status") or ""),
                )
                if state != last_state:
                    print(
                        "[fold "
                        f"{fold_index}/{configured_folds}] "
                        "quality-run progress: "
                        f"experiments {state[1]}/{state[2]} "
                        f"pending={state[3]} "
                        f"run_dir={state[0]}"
                    )
                    if progress_callback is not None:
                        progress_callback(dict(progress_row))
                    last_state = state

        returncode = process.poll()
        if returncode is not None:
            if returncode != 0:
                raise subprocess.CalledProcessError(returncode, cmd)
            break
        time.sleep(sleep_seconds)

    if active_run_dir is None and run_out_dir.exists() and run_out_dir.is_dir():
        try:
            active_run_dir = _latest_timestamp_dir(run_out_dir)
        except Exception:  # noqa: BLE001
            active_run_dir = None
    return active_run_dir


def _latest_timestamp_dir(path: Path) -> Path:
    candidates = [entry for entry in path.iterdir() if entry.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No run directories found under {path}")
    return sorted(candidates, key=lambda entry: entry.name)[-1]


def _latest_partial_quality_run_dir(path: Path) -> Path | None:
    if not path.exists() or not path.is_dir():
        return None
    candidates = sorted(
        [entry for entry in path.iterdir() if entry.is_dir()],
        key=lambda entry: entry.name,
        reverse=True,
    )
    for candidate in candidates:
        has_summary = (candidate / "summary.json").exists() and (
            candidate / "report.md"
        ).exists()
        if has_summary:
            continue
        has_runner_metadata = (candidate / "experiments_resolved.json").exists()
        if has_runner_metadata:
            return candidate
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_id_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        cleaned = str(raw_value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _candidate_sort_key(candidate_id: str, row: dict[str, Any]) -> tuple[float, float, float, str]:
    mean_practical = _coerce_float(row.get("mean_practical_f1_delta"))
    mean_strict = _coerce_float(row.get("mean_strict_f1_delta"))
    passed = bool(row.get("passed"))
    return (
        0.0 if passed else 1.0,
        -mean_practical if mean_practical is not None else 999.0,
        -mean_strict if mean_strict is not None else 999.0,
        str(candidate_id),
    )


def _extract_candidate_rows_from_summary(summary_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = summary_payload.get("candidates")
    if not isinstance(rows, dict):
        return {}
    parsed: dict[str, dict[str, Any]] = {}
    for raw_candidate_id, raw_row in rows.items():
        candidate_id = str(raw_candidate_id or "").strip()
        if not candidate_id or not isinstance(raw_row, dict):
            continue
        parsed[candidate_id] = dict(raw_row)
    return parsed


def _extract_evaluated_fold_rows(folds_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(folds_payload, dict):
        return []
    folds_raw = folds_payload.get("folds")
    if not isinstance(folds_raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for raw_fold in folds_raw:
        if not isinstance(raw_fold, dict):
            continue
        if bool(raw_fold.get("duplicate_suite_skipped")):
            continue
        included = raw_fold.get("included_in_gates")
        if included is False:
            continue
        comparisons = raw_fold.get("comparisons")
        if not isinstance(comparisons, dict):
            continue
        rows.append(raw_fold)
    return rows


def _count_winner_or_tied_top_folds(
    *,
    candidate_id: str,
    fold_rows: list[dict[str, Any]],
    epsilon: float = 1e-12,
) -> dict[str, Any]:
    evaluated_folds = 0
    winner_or_tied_top_folds = 0
    for fold in fold_rows:
        comparisons = fold.get("comparisons")
        if not isinstance(comparisons, dict):
            continue
        practical_by_candidate: dict[str, float] = {}
        for raw_id, raw_row in comparisons.items():
            row_id = str(raw_id or "").strip()
            if not row_id or not isinstance(raw_row, dict):
                continue
            if not bool(raw_row.get("completed")):
                continue
            practical_delta = _coerce_float(raw_row.get("practical_f1_delta"))
            if practical_delta is None:
                continue
            practical_by_candidate[row_id] = practical_delta
        if not practical_by_candidate:
            continue
        evaluated_folds += 1
        candidate_value = practical_by_candidate.get(candidate_id)
        if candidate_value is None:
            continue
        best_value = max(practical_by_candidate.values())
        if candidate_value >= best_value - float(epsilon):
            winner_or_tied_top_folds += 1
    return {
        "evaluated_unique_folds": evaluated_folds,
        "winner_or_tied_top_folds": winner_or_tied_top_folds,
    }


def _recommend_phase_b_candidates(
    *,
    candidate_rows: dict[str, dict[str, Any]],
    fold_rows: list[dict[str, Any]],
    close_practical_delta_threshold: float = _PHASE_A_TOP_TWO_CLOSE_PRACTICAL_DELTA,
) -> dict[str, Any]:
    if not candidate_rows:
        raise ValueError("No candidate rows available for phase recommendation.")

    ranked = sorted(
        candidate_rows.items(),
        key=lambda item: _candidate_sort_key(item[0], item[1]),
    )
    top_candidate_id, top_candidate_row = ranked[0]
    runner_up_candidate_id = ranked[1][0] if len(ranked) > 1 else None
    runner_up_row = ranked[1][1] if len(ranked) > 1 else None

    top_practical_delta = _coerce_float(top_candidate_row.get("mean_practical_f1_delta"))
    runner_up_practical_delta = (
        _coerce_float(runner_up_row.get("mean_practical_f1_delta"))
        if isinstance(runner_up_row, dict)
        else None
    )
    practical_gap_top_two = None
    if top_practical_delta is not None and runner_up_practical_delta is not None:
        practical_gap_top_two = abs(top_practical_delta - runner_up_practical_delta)

    fold_winner_summary = _count_winner_or_tied_top_folds(
        candidate_id=top_candidate_id,
        fold_rows=fold_rows,
    )
    evaluated_unique_folds = int(fold_winner_summary["evaluated_unique_folds"])
    winner_or_tied_top_folds = int(fold_winner_summary["winner_or_tied_top_folds"])
    winner_or_tied_top_all_folds = (
        evaluated_unique_folds > 0
        and winner_or_tied_top_folds == evaluated_unique_folds
    )
    clear_winner = (
        evaluated_unique_folds >= _PHASE_A_CLEAR_WINNER_MIN_FOLDS
        and winner_or_tied_top_folds >= _PHASE_A_CLEAR_WINNER_MIN_FOLDS
        and winner_or_tied_top_all_folds
    )
    top_two_close = (
        practical_gap_top_two is not None
        and practical_gap_top_two <= float(close_practical_delta_threshold)
        and runner_up_candidate_id is not None
    )

    selected_candidate_ids = [top_candidate_id]
    recommendation_reason_code = "fallback_top_candidate"
    recommendation_rationale = (
        "Sparse or noisy evidence; selected deterministic top-ranked candidate only."
    )
    warning = None
    if clear_winner:
        recommendation_reason_code = "clear_winner_or_tied_top_all_unique_folds"
        recommendation_rationale = (
            "Top candidate is winner or tied-top on all evaluated unique folds."
        )
    elif top_two_close:
        selected_candidate_ids = [top_candidate_id, str(runner_up_candidate_id)]
        recommendation_reason_code = "top_two_close_mean_practical_delta"
        recommendation_rationale = (
            "Top two candidates are within close practical-delta threshold."
        )
    elif evaluated_unique_folds < _PHASE_A_CLEAR_WINNER_MIN_FOLDS:
        recommendation_reason_code = "sparse_unique_fold_evidence"
        recommendation_rationale = (
            "Fewer than two evaluated unique folds; selected top-ranked fallback candidate."
        )
        warning = (
            "Sparse fold evidence in source summary/folds. Review manually before promotion."
        )
    else:
        recommendation_reason_code = "no_clear_winner_and_not_close"
        recommendation_rationale = (
            "No clear fold winner and top-two gap exceeded close threshold."
        )
        warning = (
            "Heuristic fallback to top candidate. Review full fold metrics before promotion."
        )

    recommendation = {
        "selected_candidate_ids": selected_candidate_ids,
        "reason_code": recommendation_reason_code,
        "rationale": recommendation_rationale,
        "close_practical_delta_threshold": float(close_practical_delta_threshold),
        "evaluated_unique_folds": evaluated_unique_folds,
        "top_candidate_id": top_candidate_id,
        "runner_up_candidate_id": runner_up_candidate_id,
        "top_candidate_winner_or_tied_top_folds": winner_or_tied_top_folds,
        "top_candidate_winner_or_tied_top_all_folds": winner_or_tied_top_all_folds,
        "top_mean_practical_f1_delta": top_practical_delta,
        "runner_up_mean_practical_f1_delta": runner_up_practical_delta,
        "top_two_mean_practical_delta_gap": practical_gap_top_two,
        "ranked_candidates_by_practical_then_strict": [
            candidate_id for candidate_id, _ in ranked
        ],
    }
    if warning:
        recommendation["warning"] = warning
    return recommendation


def _select_phase_b_candidates_from_phase_a_summary(
    *,
    summary_payload: dict[str, Any],
    folds_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_rows = _extract_candidate_rows_from_summary(summary_payload)
    if not candidate_rows:
        raise ValueError(
            "Source summary.json does not contain candidate rows under 'candidates'."
        )
    fold_rows = _extract_evaluated_fold_rows(folds_payload)
    recommendation = _recommend_phase_b_candidates(
        candidate_rows=candidate_rows,
        fold_rows=fold_rows,
    )
    recommendation["source_candidate_count"] = len(candidate_rows)
    recommendation["source_baseline_experiment_id"] = str(
        summary_payload.get("baseline_experiment_id") or "baseline"
    ).strip() or "baseline"
    recommendation["source_total_folds"] = int(
        summary_payload.get("total_folds") or len(fold_rows)
    )
    return recommendation


def _latest_tournament_dir_with_summary(path: Path) -> Path:
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"Tournament root does not exist: {path}")
    candidates = sorted(
        [entry for entry in path.iterdir() if entry.is_dir()],
        key=lambda entry: entry.name,
        reverse=True,
    )
    for candidate in candidates:
        summary_path = candidate / "summary.json"
        if summary_path.exists() and summary_path.is_file():
            return candidate
    raise FileNotFoundError(f"No tournament directory with summary.json found under {path}")


def _resolve_auto_candidate_selection(
    *,
    auto_candidates_from_summary: str,
    auto_candidates_from_latest_in: str,
    all_experiment_ids: list[str],
    baseline_experiment_id: str,
) -> dict[str, Any] | None:
    summary_arg = str(auto_candidates_from_summary or "").strip()
    latest_arg = str(auto_candidates_from_latest_in or "").strip()
    if not summary_arg and not latest_arg:
        return None
    if summary_arg and latest_arg:
        raise ValueError(
            "Use only one of --auto-candidates-from-summary or "
            "--auto-candidates-from-latest-in."
        )

    source_mode = "summary_path"
    source_input = summary_arg
    if latest_arg:
        source_mode = "latest_in"
        source_input = latest_arg

    if source_mode == "summary_path":
        source_path = Path(source_input).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(
                "Auto-candidate summary path not found: "
                f"{source_path}"
            )
        if source_path.is_dir():
            source_tournament_dir = source_path
            summary_path = source_tournament_dir / "summary.json"
        else:
            summary_path = source_path
            source_tournament_dir = summary_path.parent
    else:
        latest_root = Path(source_input).expanduser()
        source_tournament_dir = _latest_tournament_dir_with_summary(latest_root)
        summary_path = source_tournament_dir / "summary.json"

    if not summary_path.exists() or not summary_path.is_file():
        raise FileNotFoundError(
            "Auto-candidate summary.json not found: "
            f"{summary_path}"
        )
    folds_path = source_tournament_dir / "folds.json"
    folds_payload = _load_json_object_if_exists(folds_path)
    summary_payload = _load_json_object(summary_path)
    recommendation = _select_phase_b_candidates_from_phase_a_summary(
        summary_payload=summary_payload,
        folds_payload=folds_payload,
    )

    requested_candidate_ids = [
        str(candidate_id).strip()
        for candidate_id in recommendation.get("selected_candidate_ids") or []
        if str(candidate_id).strip()
    ]
    selected_candidate_ids: list[str] = []
    omitted_candidate_ids: list[str] = []
    for candidate_id in requested_candidate_ids:
        if candidate_id == baseline_experiment_id:
            omitted_candidate_ids.append(candidate_id)
            continue
        if candidate_id not in all_experiment_ids:
            omitted_candidate_ids.append(candidate_id)
            continue
        selected_candidate_ids.append(candidate_id)
    selected_candidate_ids = _normalize_id_list(selected_candidate_ids)
    if not selected_candidate_ids:
        available = ", ".join(all_experiment_ids) or "<none>"
        omitted = ", ".join(omitted_candidate_ids) or "<none>"
        raise ValueError(
            "Auto-candidate selection produced no usable candidates for this experiments file. "
            f"omitted={omitted} available={available}"
        )

    return {
        "candidate_source": "auto_phase_a_summary",
        "mode": source_mode,
        "source_input": source_input,
        "resolved_tournament_dir": str(source_tournament_dir),
        "source_summary_path": str(summary_path),
        "source_folds_path": str(folds_path) if folds_path.exists() else None,
        "selected_candidate_ids": selected_candidate_ids,
        "omitted_candidate_ids": omitted_candidate_ids,
        "recommendation": recommendation,
    }


def _resolve_max_parallel_experiments_plan(
    *,
    cli_value: int | None,
    threshold_default_value: Any,
) -> dict[str, Any]:
    threshold_default = None
    if threshold_default_value is not None:
        threshold_default = int(threshold_default_value)
        if threshold_default < 1:
            raise ValueError(
                "thresholds quality_run.max_parallel_experiments_default must be >= 1"
            )
    if cli_value is not None:
        cli_int = int(cli_value)
        if cli_int < 1:
            raise ValueError("--max-parallel-experiments must be >= 1 when provided")
        return {
            "effective": cli_int,
            "source": "cli",
            "cli_value": cli_int,
            "threshold_default": threshold_default,
        }
    if threshold_default is not None:
        return {
            "effective": threshold_default,
            "source": "thresholds_default",
            "cli_value": None,
            "threshold_default": threshold_default,
        }
    return {
        "effective": None,
        "source": "quality_run_auto",
        "cli_value": None,
        "threshold_default": None,
    }


def _parse_seed_list(seed_list_raw: str) -> list[int]:
    cleaned_raw = str(seed_list_raw or "").strip()
    if not cleaned_raw:
        return []
    values: list[int] = []
    for token in cleaned_raw.split(","):
        cleaned_token = str(token or "").strip()
        if not cleaned_token:
            raise ValueError(
                "Invalid --seed-list value: empty token found. "
                "Use comma-separated integers like '42,2718,4242'."
            )
        try:
            values.append(int(cleaned_token))
        except ValueError as exc:
            raise ValueError(
                "Invalid --seed-list token "
                f"{cleaned_token!r}; expected integer seeds."
            ) from exc
    return values


def _dedupe_preserving_order(values: list[int]) -> list[int]:
    deduped: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _resolve_seed_plan(
    *,
    threshold_seeds: list[int],
    quick_parsing: bool,
    max_seeds: int | None,
    seed_values: list[int],
    seed_list_raw: str,
) -> dict[str, Any]:
    if not threshold_seeds:
        raise ValueError("thresholds.suite.seeds must include at least one integer seed")
    explicit_seed_list = _parse_seed_list(seed_list_raw)
    explicit_seed_values = [int(seed) for seed in list(seed_values or [])]
    explicit_requested = bool(explicit_seed_values) or bool(str(seed_list_raw).strip())
    quick_mode_default_seed_cap = 3 if quick_parsing else None
    max_seeds_effective = int(max_seeds) if max_seeds is not None else None
    if max_seeds_effective is not None and max_seeds_effective < 1:
        raise ValueError("--max-seeds must be >= 1 when provided")
    if explicit_requested:
        resolved_explicit = _dedupe_preserving_order(
            [*explicit_seed_values, *explicit_seed_list]
        )
        if max_seeds_effective is not None:
            resolved_explicit = resolved_explicit[:max_seeds_effective]
        if not resolved_explicit:
            raise ValueError(
                "Explicit seed selection resolved to zero seeds after dedupe/cap. "
                "Provide at least one integer with --seed/--seed-list or relax --max-seeds."
            )
        return {
            "resolved_seeds": resolved_explicit,
            "seed_source": "explicit_cli",
            "quick_mode_default_seed_cap": quick_mode_default_seed_cap,
            "max_seeds_effective": max_seeds_effective,
            "seed_resolution": {
                "threshold_seeds": list(threshold_seeds),
                "seed_values_cli": explicit_seed_values,
                "seed_list_cli_raw": str(seed_list_raw or "").strip() or None,
                "seed_list_cli_values": explicit_seed_list,
                "seed_source": "explicit_cli",
                "resolved_seeds": resolved_explicit,
                "max_seeds_cli": int(max_seeds) if max_seeds is not None else None,
                "max_seeds_effective": max_seeds_effective,
                "max_seeds_applied_to": "explicit_cli"
                if max_seeds_effective is not None
                else None,
                "quick_mode_default_seed_cap": quick_mode_default_seed_cap,
            },
        }

    max_seeds_effective_thresholds = (
        max_seeds_effective if max_seeds_effective is not None else quick_mode_default_seed_cap
    )
    resolved_threshold_seeds = (
        list(threshold_seeds[:max_seeds_effective_thresholds])
        if max_seeds_effective_thresholds is not None
        else list(threshold_seeds)
    )
    if not resolved_threshold_seeds:
        raise ValueError("No fold seeds remain after --max-seeds filtering.")
    return {
        "resolved_seeds": resolved_threshold_seeds,
        "seed_source": "thresholds",
        "quick_mode_default_seed_cap": quick_mode_default_seed_cap,
        "max_seeds_effective": max_seeds_effective_thresholds,
        "seed_resolution": {
            "threshold_seeds": list(threshold_seeds),
            "seed_values_cli": [],
            "seed_list_cli_raw": str(seed_list_raw or "").strip() or None,
            "seed_list_cli_values": [],
            "seed_source": "thresholds",
            "resolved_seeds": resolved_threshold_seeds,
            "max_seeds_cli": int(max_seeds) if max_seeds is not None else None,
            "max_seeds_effective": max_seeds_effective_thresholds,
            "max_seeds_applied_to": "thresholds"
            if max_seeds_effective_thresholds is not None
            else None,
            "quick_mode_default_seed_cap": quick_mode_default_seed_cap,
        },
    }


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
    candidate_selection = payload.get("candidate_selection") or {}
    candidate_source = str(payload.get("candidate_source") or "unknown")
    quality_run_parallel_source = str(
        payload.get("quality_run_max_parallel_experiments_source") or "unknown"
    )
    quality_run_parallel_value = payload.get("quality_run_max_parallel_experiments")
    quality_run_parallel_rendered = (
        str(quality_run_parallel_value)
        if quality_run_parallel_value is not None
        else "auto"
    )
    lines.append(f"- Generated at: {payload.get('generated_at')}")
    lines.append(f"- Tournament root: {payload.get('tournament_root')}")
    lines.append(f"- Experiments file: {payload.get('experiments_file')}")
    lines.append(f"- Thresholds file: {payload.get('thresholds_file')}")
    lines.append(f"- Baseline experiment: {payload.get('baseline_experiment_id')}")
    lines.append(
        f"- Candidate experiments: {', '.join(payload.get('candidate_experiment_ids') or [])}"
    )
    lines.append(f"- Candidate source: {candidate_source}")
    if isinstance(candidate_selection, dict) and candidate_selection:
        source_summary_path = candidate_selection.get("source_summary_path")
        if source_summary_path:
            lines.append(f"- Candidate auto-source summary: {source_summary_path}")
    lines.append(
        "- quality-run max parallel experiments: "
        f"{quality_run_parallel_rendered} ({quality_run_parallel_source})"
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
    lines.append(
        "- Shared prediction reuse cache root: "
        f"{payload.get('shared_prediction_reuse_cache_root')}"
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

    recommendation = payload.get("phase_a_promotion_recommendation") or {}
    lines.append("## Phase A Promotion Recommendation")
    lines.append("")
    if not isinstance(recommendation, dict) or not recommendation:
        lines.append("- None")
    else:
        selected_ids = recommendation.get("selected_candidate_ids") or []
        lines.append(f"- selected_candidate_ids: {', '.join(str(item) for item in selected_ids)}")
        lines.append(f"- reason_code: {recommendation.get('reason_code')}")
        lines.append(f"- rationale: {recommendation.get('rationale')}")
        lines.append(
            "- top_two_mean_practical_delta_gap: "
            f"{_render_metric(_coerce_float(recommendation.get('top_two_mean_practical_delta_gap')))}"
        )
        lines.append(
            "- evaluated_unique_folds: "
            f"{recommendation.get('evaluated_unique_folds')}"
        )
        warning = recommendation.get("warning")
        if warning:
            lines.append(f"- warning: {warning}")
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
        "--resume-tournament-dir",
        default="",
        help=(
            "Optional existing tournament directory to resume. "
            "When set, reuse fold artifacts in that directory instead of creating a new timestamp."
        ),
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
            "Forwarded to bench quality-run. If omitted, thresholds "
            "quality_run.max_parallel_experiments_default is used when present; "
            "otherwise quality-run auto mode is used."
        ),
    )
    parser.add_argument(
        "--candidate-experiment-id",
        action="append",
        default=[],
        help=(
            "Optional candidate experiment id filter (repeatable). "
            "When set, only these candidates are tested (baseline is still included). "
            "This takes precedence over auto-candidate flags."
        ),
    )
    parser.add_argument(
        "--auto-candidates-from-summary",
        default="",
        help=(
            "Auto-select one or two candidate ids from a prior Phase A summary. "
            "Accepts either summary.json path or a tournament directory."
        ),
    )
    parser.add_argument(
        "--auto-candidates-from-latest-in",
        default="",
        help=(
            "Auto-select candidates using the newest tournament directory under this root "
            "(expects <dir>/<timestamp>/summary.json)."
        ),
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help=(
            "Optional cap on candidate experiment count (after all filters) "
            "to keep tournaments short."
        ),
    )
    parser.add_argument(
        "--max-seeds",
        type=int,
        default=None,
        help=(
            "Optional cap on number of seeds/folds from thresholds.suite.seeds. "
            "Uses the first N seeds for thresholds/default mode, or caps explicit "
            "--seed/--seed-list values after dedupe when explicit seeds are provided."
        ),
    )
    parser.add_argument(
        "--seed",
        action="append",
        type=int,
        default=[],
        help=(
            "Explicit seed (repeatable). When provided, overrides thresholds seed order."
        ),
    )
    parser.add_argument(
        "--seed-list",
        default="",
        help=(
            "Comma-separated explicit seeds (e.g., '42,2718,4242'). "
            "Combined with --seed values in provided order."
        ),
    )
    parser.add_argument(
        "--force-no-deterministic-sweeps",
        action="store_true",
        help=(
            "Override thresholds quality_run.include_deterministic_sweeps=false "
            "for faster tournament runs."
        ),
    )
    parser.add_argument(
        "--quality-search-strategy",
        default="",
        help="Optional quality-run search strategy override: race or exhaustive.",
    )
    parser.add_argument(
        "--quick-parsing",
        action="store_true",
        help=(
            "Fast parsing-tools mode: parser-focused candidate subset, sweeps off, "
            "exhaustive search, and a default 3-seed cap (unless explicit seeds or "
            "--max-seeds are set)."
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

    suite_config = dict(thresholds_payload.get("suite") or {})
    quality_run_config = dict(thresholds_payload.get("quality_run") or {})
    comparison_config = dict(thresholds_payload.get("comparison") or {})
    gates = dict(thresholds_payload.get("gates") or {})

    seeds_raw = suite_config.get("seeds") or []
    if not isinstance(seeds_raw, list) or not seeds_raw:
        raise ValueError("thresholds.suite.seeds must be a non-empty array")
    threshold_seeds = [int(seed) for seed in seeds_raw]
    seed_plan = _resolve_seed_plan(
        threshold_seeds=threshold_seeds,
        quick_parsing=bool(args.quick_parsing),
        max_seeds=(
            int(args.max_seeds) if args.max_seeds is not None else None
        ),
        seed_values=[int(seed) for seed in list(args.seed or [])],
        seed_list_raw=str(args.seed_list or ""),
    )
    seeds = list(seed_plan["resolved_seeds"])
    seed_source = str(seed_plan["seed_source"])
    max_seeds_effective = seed_plan["max_seeds_effective"]
    quick_mode_default_seed_cap = seed_plan["quick_mode_default_seed_cap"]
    seed_resolution = dict(seed_plan["seed_resolution"])

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
        candidate_source = "thresholds_comparison_config"
    else:
        candidate_experiment_ids = [
            item for item in all_experiment_ids if item != baseline_experiment_id
        ]
        candidate_source = "experiments_file_all_minus_baseline"
    candidate_experiment_ids = _normalize_id_list(
        [item for item in candidate_experiment_ids if item]
    )

    if bool(args.quick_parsing):
        quick_ids = [
            experiment_id
            for experiment_id in _QUICK_PARSING_CANDIDATE_IDS
            if experiment_id in all_experiment_ids
            and experiment_id != baseline_experiment_id
        ]
        if quick_ids:
            candidate_experiment_ids = _normalize_id_list(quick_ids)
            candidate_source = "quick_parsing_defaults"
        quality_run_config["include_deterministic_sweeps"] = False
        quality_run_config["search_strategy"] = "exhaustive"

    cli_candidate_ids = _normalize_id_list(
        [str(item or "").strip() for item in list(args.candidate_experiment_id or [])]
    )
    if cli_candidate_ids:
        invalid_ids = [
            experiment_id
            for experiment_id in cli_candidate_ids
            if experiment_id not in all_experiment_ids
        ]
        if invalid_ids:
            invalid_joined = ", ".join(invalid_ids)
            available = ", ".join(all_experiment_ids) or "<none>"
            raise ValueError(
                "Unknown --candidate-experiment-id value(s): "
                f"{invalid_joined} (available: {available})"
            )
        if baseline_experiment_id in cli_candidate_ids:
            raise ValueError(
                "--candidate-experiment-id should list candidate ids only; "
                f"baseline '{baseline_experiment_id}' is always included automatically."
            )
        candidate_experiment_ids = list(cli_candidate_ids)
        candidate_source = "explicit_cli"

    auto_candidates_from_summary_raw = str(args.auto_candidates_from_summary or "").strip()
    auto_candidates_from_latest_in_raw = str(
        args.auto_candidates_from_latest_in or ""
    ).strip()
    auto_requested = bool(auto_candidates_from_summary_raw) or bool(
        auto_candidates_from_latest_in_raw
    )
    auto_candidate_selection = None
    if not cli_candidate_ids:
        auto_candidate_selection = _resolve_auto_candidate_selection(
            auto_candidates_from_summary=auto_candidates_from_summary_raw,
            auto_candidates_from_latest_in=auto_candidates_from_latest_in_raw,
            all_experiment_ids=all_experiment_ids,
            baseline_experiment_id=baseline_experiment_id,
        )
        if auto_candidate_selection is not None:
            candidate_experiment_ids = list(
                auto_candidate_selection["selected_candidate_ids"]
            )
            candidate_source = str(auto_candidate_selection["candidate_source"])
            recommendation_warning = (
                (auto_candidate_selection.get("recommendation") or {}).get("warning")
            )
            if recommendation_warning:
                print(f"warning: {recommendation_warning}")

    max_candidates_effective = None
    if args.max_candidates is not None:
        max_candidates_effective = int(args.max_candidates)
        if max_candidates_effective < 1:
            raise ValueError("--max-candidates must be >= 1 when provided")
        candidate_experiment_ids = candidate_experiment_ids[:max_candidates_effective]

    if bool(args.force_no_deterministic_sweeps):
        quality_run_config["include_deterministic_sweeps"] = False

    quality_search_strategy_override = str(args.quality_search_strategy or "").strip().lower()
    if quality_search_strategy_override:
        if quality_search_strategy_override not in _SUPPORTED_SEARCH_STRATEGIES:
            supported = ", ".join(sorted(_SUPPORTED_SEARCH_STRATEGIES))
            raise ValueError(
                "Unsupported --quality-search-strategy value: "
                f"{quality_search_strategy_override!r} (supported: {supported})"
            )
        quality_run_config["search_strategy"] = quality_search_strategy_override

    quality_parallel_plan = _resolve_max_parallel_experiments_plan(
        cli_value=(
            int(args.max_parallel_experiments)
            if args.max_parallel_experiments is not None
            else None
        ),
        threshold_default_value=quality_run_config.get("max_parallel_experiments_default"),
    )
    max_parallel_experiments_effective = quality_parallel_plan["effective"]
    max_parallel_experiments_source = str(quality_parallel_plan["source"])

    if not candidate_experiment_ids:
        raise ValueError("No candidate experiments configured/resolved.")

    candidate_selection_payload: dict[str, Any] = {
        "candidate_source": candidate_source,
        "selected_candidate_ids": list(candidate_experiment_ids),
    }
    if auto_candidate_selection is not None:
        candidate_selection_payload.update(auto_candidate_selection)
    elif auto_requested and cli_candidate_ids:
        candidate_selection_payload["auto_candidate_selection_ignored"] = {
            "reason": "explicit_candidate_experiment_ids_cli_provided",
            "auto_candidates_from_summary": auto_candidates_from_summary_raw or None,
            "auto_candidates_from_latest_in": (
                auto_candidates_from_latest_in_raw or None
            ),
        }

    output_root = Path(args.output_root)
    resume_tournament_dir_raw = str(
        getattr(args, "resume_tournament_dir", "") or ""
    ).strip()
    resume_requested = bool(resume_tournament_dir_raw)
    if resume_requested:
        tournament_root = Path(resume_tournament_dir_raw).expanduser()
        if not tournament_root.exists() or not tournament_root.is_dir():
            raise FileNotFoundError(
                "Resume tournament directory not found or not a directory: "
                f"{tournament_root}"
            )
        timestamp = str(tournament_root.name or "").strip() or _timestamp()
    else:
        timestamp = _timestamp()
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
    configured_prediction_cache_root = str(
        quality_run_config.get("prediction_reuse_cache_root") or ""
    ).strip()
    if configured_prediction_cache_root:
        shared_prediction_reuse_cache_root = str(
            Path(configured_prediction_cache_root).expanduser()
        )
    else:
        shared_prediction_reuse_cache_root = str(
            (output_root.parent / ".cache" / "prediction_reuse").resolve()
        )
    quality_run_env = {
        _ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV: shared_alignment_cache_root,
        _ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV: (
            shared_prediction_reuse_cache_root
        ),
    }

    resolved_payload = {
        "generated_at": timestamp,
        "tournament_root": str(tournament_root),
        "experiments_file": str(experiments_file),
        "thresholds_file": str(thresholds_file),
        "baseline_experiment_id": baseline_experiment_id,
        "candidate_experiment_ids": candidate_experiment_ids,
        "candidate_source": candidate_source,
        "candidate_selection": candidate_selection_payload,
        "suite": {
            "seeds": seeds,
            "seed_source": seed_source,
            "seed_resolution": seed_resolution,
            "max_targets": max_targets_int,
            "prefer_curated": prefer_curated,
        },
        "quality_run": quality_run_config,
        "quality_run_max_parallel_experiments": max_parallel_experiments_effective,
        "quality_run_max_parallel_experiments_source": max_parallel_experiments_source,
        "configured_fold_count": len(seeds),
        "shared_alignment_cache_root": shared_alignment_cache_root,
        "shared_alignment_cache_env_var": _ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV,
        "shared_prediction_reuse_cache_root": shared_prediction_reuse_cache_root,
        "shared_prediction_reuse_cache_env_var": (
            _ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV
        ),
        "duplicate_suite_fold_dedup": True,
        "gate_impossibility_pruning": True,
        "gates": gates,
        "resume_requested": resume_requested,
        "resume_tournament_dir": str(tournament_root) if resume_requested else None,
        "dry_run": bool(args.dry_run),
        "overrides": {
            "quick_parsing": bool(args.quick_parsing),
            "candidate_experiment_ids_cli": cli_candidate_ids,
            "auto_candidates_from_summary": auto_candidates_from_summary_raw or None,
            "auto_candidates_from_latest_in": auto_candidates_from_latest_in_raw
            or None,
            "seed_values_cli": [int(seed) for seed in list(args.seed or [])],
            "seed_list_cli_raw": str(args.seed_list or "").strip() or None,
            "seed_source": seed_source,
            "max_candidates": max_candidates_effective,
            "max_seeds": max_seeds_effective,
            "max_parallel_experiments_cli": quality_parallel_plan["cli_value"],
            "max_parallel_experiments_threshold_default": quality_parallel_plan[
                "threshold_default"
            ],
            "max_parallel_experiments_effective": max_parallel_experiments_effective,
            "max_parallel_experiments_source": max_parallel_experiments_source,
            "force_no_deterministic_sweeps": bool(
                args.force_no_deterministic_sweeps
            ),
            "quality_search_strategy": quality_search_strategy_override
            if quality_search_strategy_override
            else None,
        },
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
        existing_fold_result_path = fold_root / "fold_result.json"

        if (
            resume_requested
            and not args.dry_run
            and existing_fold_result_path.exists()
            and existing_fold_result_path.is_file()
        ):
            existing_fold_payload = _load_json_object(existing_fold_result_path)
            existing_suite_signature = str(
                existing_fold_payload.get("suite_signature") or ""
            ).strip()
            if existing_suite_signature:
                seen_suite_signatures.setdefault(existing_suite_signature, index)
            fold_rows.append(existing_fold_payload)
            if bool(existing_fold_payload.get("duplicate_suite_skipped")):
                duplicate_suite_folds_skipped += 1
                continue
            if bool(existing_fold_payload.get("included_in_gates")):
                evaluated_fold_rows.append(existing_fold_payload)
                continue

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
            "resume_run_dir": None,
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

    total_unique_folds_planned = len(executable_folds) + len(evaluated_fold_rows)
    active_candidate_ids = list(candidate_experiment_ids)
    pruned_candidates: dict[str, dict[str, Any]] = {}
    quality_runs_executed = sum(
        1 for row in evaluated_fold_rows if bool(row.get("executed_quality_run"))
    )
    if evaluated_fold_rows:
        latest_evaluated = sorted(
            evaluated_fold_rows,
            key=lambda row: int(row.get("fold_index", 0) or 0),
        )[-1]
        active_after = latest_evaluated.get("active_candidate_ids_after_fold")
        if isinstance(active_after, list):
            active_candidate_ids = [
                str(candidate_id).strip()
                for candidate_id in active_after
                if str(candidate_id).strip()
            ]
        for evaluated_row in evaluated_fold_rows:
            pruned_after = evaluated_row.get("pruned_candidates_after_fold")
            if not isinstance(pruned_after, dict):
                continue
            for candidate_id, prune_payload in pruned_after.items():
                if not isinstance(prune_payload, dict):
                    continue
                pruned_candidates[str(candidate_id)] = dict(prune_payload)
    early_stop_triggered = False
    tournament_checkpoint_path = tournament_root / "tournament_checkpoint.json"
    last_tournament_checkpoint_signature = ""

    def _write_tournament_checkpoint(
        *,
        status: str,
        current_fold: dict[str, Any] | None = None,
    ) -> None:
        nonlocal last_tournament_checkpoint_signature
        checkpoint_payload = {
            "schema_version": 1,
            "updated_at": _timestamp(),
            "status": str(status),
            "configured_fold_count": len(seeds),
            "planned_unique_fold_count": int(total_unique_folds_planned),
            "evaluated_fold_count": len(evaluated_fold_rows),
            "quality_runs_executed": int(quality_runs_executed),
            "duplicate_suite_folds_skipped": int(duplicate_suite_folds_skipped),
            "active_candidate_count": len(active_candidate_ids),
            "active_candidate_ids": sorted(active_candidate_ids),
            "dry_run": bool(args.dry_run),
            "current_fold": current_fold,
        }
        signature = json.dumps(checkpoint_payload, sort_keys=True)
        if signature == last_tournament_checkpoint_signature:
            return
        _write_json(tournament_checkpoint_path, checkpoint_payload)
        last_tournament_checkpoint_signature = signature

    _write_tournament_checkpoint(status="running", current_fold=None)

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
        if max_parallel_experiments_effective is not None:
            quality_run_cmd.extend(
                [
                    "--max-parallel-experiments",
                    str(int(max_parallel_experiments_effective)),
                ]
            )
        fold_payload["quality_run_max_parallel_experiments"] = (
            int(max_parallel_experiments_effective)
            if max_parallel_experiments_effective is not None
            else None
        )
        fold_payload["quality_run_max_parallel_experiments_source"] = (
            max_parallel_experiments_source
        )
        resume_run_dir = None
        if not args.dry_run:
            resume_run_dir = _latest_partial_quality_run_dir(run_out_dir)
            if resume_run_dir is not None:
                quality_run_cmd.extend(["--resume-run-dir", str(resume_run_dir)])
                fold_payload["resume_run_dir"] = str(resume_run_dir)
        else:
            fold_payload["resume_run_dir"] = None

        current_fold_progress: dict[str, Any] = {
            "fold_index": fold_index,
            "configured_folds": len(seeds),
            "seed": int(fold_payload.get("seed") or 0),
            "state": "running",
            "run_out_dir": str(run_out_dir),
            "run_dir": str(resume_run_dir) if resume_run_dir is not None else None,
            "experiment_count_completed": 0,
            "experiment_count_total": 0,
            "pending_experiment_count": 0,
        }
        _write_tournament_checkpoint(
            status="running",
            current_fold=dict(current_fold_progress),
        )

        def _on_fold_subprogress(progress_row: dict[str, Any]) -> None:
            current_fold_progress.update(
                {
                    "run_dir": str(progress_row.get("run_dir") or "")
                    or current_fold_progress.get("run_dir"),
                    "experiment_count_completed": int(
                        progress_row.get("experiment_count_completed") or 0
                    ),
                    "experiment_count_total": int(
                        progress_row.get("experiment_count_total") or 0
                    ),
                    "pending_experiment_count": int(
                        progress_row.get("pending_experiment_count") or 0
                    ),
                    "quality_run_status": str(
                        progress_row.get("quality_run_status") or ""
                    ).strip()
                    or None,
                }
            )
            _write_tournament_checkpoint(
                status="running",
                current_fold=dict(current_fold_progress),
            )

        run_dir_from_monitor = _run_quality_run_with_subprogress(
            cmd=quality_run_cmd,
            dry_run=bool(args.dry_run),
            env=quality_run_env,
            fold_index=fold_index,
            configured_folds=len(seeds),
            run_out_dir=run_out_dir,
            resume_run_dir=resume_run_dir,
            progress_callback=_on_fold_subprogress,
        )
        fold_payload["executed_quality_run"] = True

        if args.dry_run:
            _write_json(fold_root / "fold_result.json", fold_payload)
            current_fold_progress["state"] = "dry_run"
            _write_tournament_checkpoint(
                status="running",
                current_fold=dict(current_fold_progress),
            )
            continue

        quality_runs_executed += 1
        run_dir = run_dir_from_monitor or _latest_timestamp_dir(run_out_dir)
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
        current_fold_progress.update(
            {
                "state": "completed",
                "run_dir": str(run_dir),
                "experiment_count_completed": current_fold_progress.get(
                    "experiment_count_total",
                    0,
                ),
                "pending_experiment_count": 0,
            }
        )
        _write_tournament_checkpoint(
            status="running",
            current_fold=dict(current_fold_progress),
        )

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
    phase_a_promotion_recommendation = _recommend_phase_b_candidates(
        candidate_rows=aggregated_candidates,
        fold_rows=evaluated_fold_rows,
    )
    phase_a_promotion_recommendation["generated_from_current_tournament"] = True
    phase_a_promotion_recommendation["source_summary_path"] = str(
        tournament_root / "summary.json"
    )
    phase_a_promotion_recommendation["source_folds_path"] = str(
        tournament_root / "folds.json"
    )

    tournament_summary = {
        "generated_at": _timestamp(),
        "tournament_root": str(tournament_root),
        "experiments_file": str(experiments_file),
        "thresholds_file": str(thresholds_file),
        "baseline_experiment_id": baseline_experiment_id,
        "candidate_experiment_ids": candidate_experiment_ids,
        "candidate_source": candidate_source,
        "candidate_selection": candidate_selection_payload,
        "configured_folds": len(seeds),
        "planned_unique_folds": total_unique_folds_planned,
        "total_folds": effective_fold_count,
        "duplicate_suite_folds_skipped": duplicate_suite_folds_skipped,
        "shared_alignment_cache_root": shared_alignment_cache_root,
        "shared_prediction_reuse_cache_root": shared_prediction_reuse_cache_root,
        "quality_run_max_parallel_experiments": max_parallel_experiments_effective,
        "quality_run_max_parallel_experiments_source": max_parallel_experiments_source,
        "quality_runs_executed": quality_runs_executed,
        "gate_impossibility_pruning_enabled": True,
        "pruned_candidates": pruned_candidates,
        "active_candidates_final": sorted(active_candidate_ids),
        "early_stop_triggered": bool(early_stop_triggered),
        "dry_run": bool(args.dry_run),
        "gates": gates,
        "candidates": aggregated_candidates,
        "top_tier_candidates": top_tier_candidates,
        "phase_a_promotion_recommendation": phase_a_promotion_recommendation,
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
    _write_tournament_checkpoint(status="complete", current_fold=None)

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
