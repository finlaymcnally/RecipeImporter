"""Aggregate per-source all-method variant results into a global leaderboard."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from cookimport.config.run_settings import (
    RUN_SETTING_CONTRACT_FULL,
    RunSettings,
    project_run_config_payload,
)


_MULTI_SOURCE_REPORT_JSON = "all_method_benchmark_multi_source_report.json"


def resolve_latest_timestamp_dir(root: Path) -> Path | None:
    if not root.exists() or not root.is_dir():
        return None
    candidates: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        candidates.append(child)
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.name)[-1]


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[float]) -> float | None:
    items = [float(v) for v in values]
    if not items:
        return None
    return float(sum(items) / len(items))


def _median(values: Iterable[float]) -> float | None:
    items = [float(v) for v in values]
    if not items:
        return None
    return float(statistics.median(items))


def _stable_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _short_id_from_dimensions(dimensions: dict[str, Any]) -> str:
    raw = _stable_json(dimensions).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def _short_id_from_hash(config_hash: str) -> str:
    cleaned = str(config_hash or "").strip().lower()
    if not cleaned:
        return ""
    return cleaned[:12]


def _dimension_key(
    *,
    dimensions: dict[str, Any],
    ignore_keys: set[str],
) -> tuple[str, dict[str, Any]]:
    cleaned = {
        str(key): dimensions[key]
        for key in sorted(dimensions)
        if str(key) not in ignore_keys
    }
    return _stable_json(cleaned), cleaned


def _pareto_frontier(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return non-dominated rows for (min duration, max quality)."""
    points: list[tuple[float, float, dict[str, Any]]] = []
    for row in rows:
        duration = _as_float(row.get("median_duration_seconds"))
        quality = _as_float(row.get("mean_practical_f1"))
        if duration is None or quality is None:
            continue
        points.append((duration, quality, row))
    points.sort(key=lambda item: (item[0], -item[1]))

    frontier: list[dict[str, Any]] = []
    best_quality_so_far: float | None = None
    for duration, quality, row in points:
        if best_quality_so_far is None or quality > best_quality_so_far:
            frontier.append(row)
            best_quality_so_far = quality
    return frontier


@dataclass(frozen=True)
class LeaderboardPaths:
    out_dir: Path
    leaderboard_json: Path
    leaderboard_csv: Path
    pareto_json: Path
    pareto_csv: Path
    winner_run_settings_json: Path
    winner_dimensions_json: Path
    leaderboard_by_source_extension_json: Path | None = None
    leaderboard_by_source_extension_csv: Path | None = None


def _normalize_source_extension(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return "__none__"
    if not cleaned.startswith("."):
        cleaned = f".{cleaned}"
    return cleaned


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load_json_object_or_none(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _extract_line_role_artifacts(
    *,
    eval_output_dir: Path,
    run_root: Path,
) -> dict[str, Any] | None:
    """Best-effort extraction of optional line-role diagnostic artifacts."""
    line_role_dir = eval_output_dir / "line-role-pipeline"
    if not line_role_dir.exists() or not line_role_dir.is_dir():
        return None

    joined_path = line_role_dir / "joined_line_table.jsonl"
    flips_path = line_role_dir / "line_role_flips_vs_baseline.jsonl"
    slice_path = line_role_dir / "slice_metrics.json"
    routing_path = line_role_dir / "routing_summary.json"
    gates_path = line_role_dir / "regression_gates.json"

    slice_payload = _load_json_object_or_none(slice_path) or {}
    routing_payload = _load_json_object_or_none(routing_path) or {}
    gates_payload = _load_json_object_or_none(gates_path) or {}

    gates_verdict = str(
        ((gates_payload.get("overall") or {}).get("verdict")) or ""
    ).strip().upper()

    slice_summary: dict[str, Any] = {}
    slices_payload = slice_payload.get("slices")
    if isinstance(slices_payload, dict):
        for slice_name in sorted(slices_payload):
            row = slices_payload.get(slice_name)
            if not isinstance(row, dict):
                continue
            slice_summary[str(slice_name)] = {
                "line_count": row.get("line_count"),
                "overall_line_accuracy": row.get("overall_line_accuracy"),
                "macro_f1_excluding_other": row.get("macro_f1_excluding_other"),
            }

    routing_summary = {}
    if routing_payload:
        routing_summary = {
            "inside_recipe_line_count": routing_payload.get("inside_recipe_line_count"),
            "outside_recipe_line_count": routing_payload.get("outside_recipe_line_count"),
            "unknown_recipe_status_line_count": routing_payload.get(
                "unknown_recipe_status_line_count"
            ),
            "recipe_local_label_count": routing_payload.get("recipe_local_label_count"),
            "outside_recipe_structured_count": routing_payload.get(
                "outside_recipe_structured_count"
            ),
            "outside_recipe_review_eligible_count": routing_payload.get(
                "outside_recipe_review_eligible_count"
            ),
            "outside_recipe_review_excluded_count": routing_payload.get(
                "outside_recipe_review_excluded_count"
            ),
            "review_exclusion_reason_counts": routing_payload.get(
                "review_exclusion_reason_counts"
            ),
        }

    return {
        "schema_version": "qualitysuite_line_role_artifacts.v1",
        "eval_output_dir": _relative_to_root(eval_output_dir, run_root),
        "line_role_dir": _relative_to_root(line_role_dir, run_root),
        "joined_line_table_jsonl": _relative_to_root(joined_path, run_root)
        if joined_path.exists()
        else None,
        "line_role_flips_vs_baseline_jsonl": _relative_to_root(flips_path, run_root)
        if flips_path.exists()
        else None,
        "slice_metrics_json": _relative_to_root(slice_path, run_root)
        if slice_path.exists()
        else None,
        "routing_summary_json": _relative_to_root(routing_path, run_root)
        if routing_path.exists()
        else None,
        "regression_gates_json": _relative_to_root(gates_path, run_root)
        if gates_path.exists()
        else None,
        "regression_gates_verdict": gates_verdict or None,
        "slice_metrics_summary": slice_summary,
        "routing_summary": routing_summary,
    }


def _source_group_count_for_groups(groups: dict[str, dict[str, Any]]) -> int:
    source_group_keys: set[str] = set()
    for group in groups.values():
        by_source_group = (
            group.get("by_source_group")
            if isinstance(group.get("by_source_group"), dict)
            else {}
        )
        for source_group_key in by_source_group:
            cleaned = str(source_group_key or "").strip()
            if cleaned:
                source_group_keys.add(cleaned)
    return len(source_group_keys)


def _build_ranked_rows(
    *,
    groups: dict[str, dict[str, Any]],
    total_source_groups: int,
    allow_partial_coverage: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    config_rows: list[dict[str, Any]] = []
    for config_key, group in groups.items():
        run_config_hash = str(group.get("run_config_hash") or "").strip() or None
        run_config_summary = str(group.get("run_config_summary") or "").strip() or None
        dimensions = group.get("dimensions") if isinstance(group.get("dimensions"), dict) else {}
        by_source_group = (
            group.get("by_source_group")
            if isinstance(group.get("by_source_group"), dict)
            else {}
        )
        source_group_keys = sorted(
            str(key) for key in by_source_group.keys() if str(key).strip()
        )
        if not source_group_keys:
            continue

        per_source_practical: list[float] = []
        per_source_strict: list[float] = []
        per_source_duration: list[float] = []
        for source_group_key in source_group_keys:
            contrib_rows = by_source_group.get(source_group_key)
            if not isinstance(contrib_rows, list) or not contrib_rows:
                continue
            practical_values = [
                float(row.get("practical_f1"))
                for row in contrib_rows
                if _as_float(row.get("practical_f1")) is not None
            ]
            strict_values = [
                float(row.get("strict_f1"))
                for row in contrib_rows
                if _as_float(row.get("strict_f1")) is not None
            ]
            duration_values = [
                float(row.get("duration_seconds"))
                for row in contrib_rows
                if _as_float(row.get("duration_seconds")) is not None
            ]
            practical_mean = _mean(practical_values)
            strict_mean = _mean(strict_values)
            duration_median = _median(duration_values)
            if practical_mean is None or strict_mean is None:
                continue
            per_source_practical.append(float(practical_mean))
            per_source_strict.append(float(strict_mean))
            if duration_median is not None:
                per_source_duration.append(float(duration_median))

        mean_practical = _mean(per_source_practical)
        mean_strict = _mean(per_source_strict)
        median_duration = _median(per_source_duration)
        mean_duration = _mean(per_source_duration)
        if mean_practical is None or mean_strict is None:
            continue

        coverage_count = len(source_group_keys)
        coverage_ratio = (
            float(coverage_count) / float(total_source_groups)
            if total_source_groups > 0
            else 0.0
        )
        config_rows.append(
            {
                "config_key": config_key,
                "config_id": (
                    _short_id_from_hash(run_config_hash)
                    or _short_id_from_dimensions(dimensions)
                ),
                "run_config_hash": run_config_hash,
                "run_config_summary": run_config_summary,
                "dimensions": dimensions,
                "representative_run_manifest_path": group.get(
                    "representative_run_manifest_path"
                ),
                "line_role": group.get("line_role")
                if isinstance(group.get("line_role"), dict)
                else None,
                "line_role_gates_verdict": str(group.get("line_role_gates_verdict") or "").strip().upper()
                or None,
                "coverage_sources": coverage_count,
                "coverage_ratio": coverage_ratio,
                "mean_practical_f1": float(mean_practical),
                "mean_strict_f1": float(mean_strict),
                "median_duration_seconds": float(median_duration)
                if median_duration is not None
                else None,
                "mean_duration_seconds": float(mean_duration)
                if mean_duration is not None
                else None,
            }
        )

    full_coverage_rows = [
        row for row in config_rows if row.get("coverage_sources") == total_source_groups
    ]
    ranked_input = (
        full_coverage_rows
        if (full_coverage_rows and not allow_partial_coverage)
        else config_rows
    )
    ranked = sorted(
        ranked_input,
        key=lambda row: (
            -float(row.get("mean_practical_f1") or 0.0),
            -float(row.get("mean_strict_f1") or 0.0),
            -int(row.get("coverage_sources") or 0),
            float(row.get("median_duration_seconds") or 0.0),
            str(row.get("run_config_hash") or ""),
            str(row.get("config_id") or ""),
        ),
    )
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    winner = ranked[0] if ranked else None
    return config_rows, full_coverage_rows, ranked, winner


def build_quality_leaderboard(
    *,
    run_dir: Path,
    experiment_id: str,
    allow_partial_coverage: bool = False,
    ignore_dimension_keys: set[str] | None = None,
    include_by_source_extension: bool = False,
) -> dict[str, Any]:
    if ignore_dimension_keys is None:
        ignore_dimension_keys = {"source_extension"}

    run_dir = run_dir.expanduser().resolve()
    experiments_resolved_path = run_dir / "experiments_resolved.json"
    if not experiments_resolved_path.exists():
        raise FileNotFoundError(f"Missing experiments_resolved.json: {experiments_resolved_path}")

    experiment_dir = run_dir / "experiments" / experiment_id
    if not experiment_dir.exists() or not experiment_dir.is_dir():
        raise FileNotFoundError(f"Experiment directory not found: {experiment_dir}")

    multi_source_report_path = experiment_dir / _MULTI_SOURCE_REPORT_JSON
    if not multi_source_report_path.exists() or not multi_source_report_path.is_file():
        raise FileNotFoundError(f"Missing multi-source report: {multi_source_report_path}")

    experiments_resolved = _load_json_dict(experiments_resolved_path)
    experiments = experiments_resolved.get("experiments")
    if not isinstance(experiments, list):
        raise ValueError("experiments_resolved.json missing experiments list")
    base_run_settings_payload: dict[str, Any] | None = None
    for item in experiments:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") == experiment_id:
            payload = item.get("run_settings")
            if isinstance(payload, dict):
                base_run_settings_payload = dict(payload)
            break
    if base_run_settings_payload is None:
        raise ValueError(
            f"Experiment id {experiment_id!r} not found in experiments_resolved.json"
        )

    multi_source_report = _load_json_dict(multi_source_report_path)
    sources_payload = multi_source_report.get("sources")
    if not isinstance(sources_payload, list) or not sources_payload:
        raise ValueError("Multi-source report has no sources list")

    source_groups_expected = [
        str(row.get("source_group_key") or "").strip()
        for row in sources_payload
        if isinstance(row, dict) and str(row.get("source_group_key") or "").strip()
    ]
    total_source_groups = len(sorted(set(source_groups_expected)))
    if total_source_groups <= 0:
        total_source_groups = len(sources_payload)

    # groups[config_key]["by_source_group"][source_group_key] -> list[contrib]
    groups: dict[str, dict[str, Any]] = {}
    groups_by_source_extension: dict[str, dict[str, dict[str, Any]]] = {}

    def record_contribution(
        *,
        group_map: dict[str, dict[str, Any]],
        config_key: str,
        run_config_hash: str | None,
        run_config_summary: str | None,
        dimensions: dict[str, Any],
        run_manifest_path: str | None,
        source_group_key: str,
        practical_f1: float,
        strict_f1: float,
        duration_seconds: float | None,
        line_role: dict[str, Any] | None = None,
    ) -> None:
        group = group_map.setdefault(
            config_key,
            {
                "run_config_hash": str(run_config_hash or "").strip() or None,
                "run_config_summary": str(run_config_summary or "").strip() or None,
                "dimensions": dict(dimensions),
                "representative_run_manifest_path": (
                    str(run_manifest_path).strip() if run_manifest_path else None
                ),
                "by_source_group": {},
            },
        )
        if group.get("representative_run_manifest_path") is None and run_manifest_path:
            group["representative_run_manifest_path"] = str(run_manifest_path).strip()
        if (
            line_role is not None
            and isinstance(line_role, dict)
            and group.get("line_role") is None
        ):
            group["line_role"] = dict(line_role)
            verdict = str(line_role.get("regression_gates_verdict") or "").strip().upper()
            if verdict:
                group["line_role_gates_verdict"] = verdict
        by_source = group["by_source_group"].setdefault(source_group_key, [])
        by_source.append(
            {
                "practical_f1": practical_f1,
                "strict_f1": strict_f1,
                "duration_seconds": duration_seconds,
            }
        )

    for source_row in sources_payload:
        if not isinstance(source_row, dict):
            continue
        source_group_key = str(source_row.get("source_group_key") or "").strip()
        if not source_group_key:
            continue

        report_paths: list[str] = []
        list_payload = source_row.get("report_json_paths")
        if isinstance(list_payload, list):
            for item in list_payload:
                candidate = str(item or "").strip()
                if candidate:
                    report_paths.append(candidate)
        single_payload = str(source_row.get("report_json_path") or "").strip()
        if single_payload:
            report_paths.append(single_payload)
        if not report_paths:
            continue

        for rel_path in report_paths:
            report_path = Path(rel_path)
            if not report_path.is_absolute():
                report_path = experiment_dir / report_path
            if not report_path.exists() or not report_path.is_file():
                continue
            report = _load_json_dict(report_path)
            variants = report.get("variants")
            if not isinstance(variants, list) or not variants:
                continue
            for variant_row in variants:
                if not isinstance(variant_row, dict):
                    continue
                status = str(variant_row.get("status") or "").strip().lower()
                if status != "ok":
                    continue
                dimensions_raw = variant_row.get("dimensions")
                if not isinstance(dimensions_raw, dict) or not dimensions_raw:
                    continue
                dimension_config_key, cleaned_dimensions = _dimension_key(
                    dimensions=dict(dimensions_raw),
                    ignore_keys=ignore_dimension_keys,
                )
                run_config_hash = str(variant_row.get("run_config_hash") or "").strip()
                run_config_summary = str(variant_row.get("run_config_summary") or "").strip()
                config_key = (
                    f"hash:{run_config_hash}" if run_config_hash else f"dims:{dimension_config_key}"
                )
                practical_f1 = _as_float(variant_row.get("practical_f1"))
                strict_f1 = _as_float(variant_row.get("f1"))
                if practical_f1 is None or strict_f1 is None:
                    continue
                duration_seconds = _as_float(variant_row.get("duration_seconds"))
                config_dir_name = str(variant_row.get("config_dir") or "").strip()
                run_manifest_path: str | None = None
                line_role_payload: dict[str, Any] | None = None
                if config_dir_name:
                    candidate_manifest = report_path.parent / config_dir_name / "run_manifest.json"
                    if candidate_manifest.exists() and candidate_manifest.is_file():
                        run_manifest_path = str(candidate_manifest)
                    line_role_payload = _extract_line_role_artifacts(
                        eval_output_dir=report_path.parent / config_dir_name,
                        run_root=run_dir,
                    )
                record_contribution(
                    group_map=groups,
                    config_key=config_key,
                    run_config_hash=run_config_hash,
                    run_config_summary=run_config_summary,
                    dimensions=cleaned_dimensions,
                    run_manifest_path=run_manifest_path,
                    source_group_key=source_group_key,
                    practical_f1=float(practical_f1),
                    strict_f1=float(strict_f1),
                    duration_seconds=float(duration_seconds)
                    if duration_seconds is not None
                    else None,
                    line_role=line_role_payload,
                )
                if include_by_source_extension:
                    source_extension = _normalize_source_extension(
                        dimensions_raw.get("source_extension")
                    )
                    extension_groups = groups_by_source_extension.setdefault(
                        source_extension,
                        {},
                    )
                    record_contribution(
                        group_map=extension_groups,
                        config_key=config_key,
                        run_config_hash=run_config_hash,
                        run_config_summary=run_config_summary,
                        dimensions=cleaned_dimensions,
                        run_manifest_path=run_manifest_path,
                        source_group_key=source_group_key,
                        practical_f1=float(practical_f1),
                        strict_f1=float(strict_f1),
                        duration_seconds=float(duration_seconds)
                        if duration_seconds is not None
                        else None,
                        line_role=line_role_payload,
                    )

    _, full_coverage_rows, ranked, winner = _build_ranked_rows(
        groups=groups,
        total_source_groups=total_source_groups,
        allow_partial_coverage=allow_partial_coverage,
    )

    leaderboard_by_source_extension: dict[str, Any] = {}
    if include_by_source_extension and groups_by_source_extension:
        for source_extension in sorted(groups_by_source_extension):
            extension_groups = groups_by_source_extension[source_extension]
            extension_total_sources = _source_group_count_for_groups(extension_groups)
            if extension_total_sources <= 0:
                continue
            (
                _,
                extension_full_coverage_rows,
                extension_ranked,
                extension_winner,
            ) = _build_ranked_rows(
                groups=extension_groups,
                total_source_groups=extension_total_sources,
                allow_partial_coverage=allow_partial_coverage,
            )
            leaderboard_by_source_extension[source_extension] = {
                "source_extension": source_extension,
                "total_source_groups": extension_total_sources,
                "leaderboard": extension_ranked,
                "winner": extension_winner,
                "pareto_frontier": {
                    "full_coverage": _pareto_frontier(extension_full_coverage_rows),
                    "ranked_set": _pareto_frontier(extension_ranked),
                },
            }

    compatibility_passthrough_keys = {
        "section_detector_backend",
        "instruction_step_segmentation_policy",
        "instruction_step_segmenter",
    }

    def compute_winner_settings() -> dict[str, Any] | None:
        if not isinstance(winner, dict):
            return None
        run_manifest_path = winner.get("representative_run_manifest_path")
        if isinstance(run_manifest_path, str) and run_manifest_path.strip():
            manifest_path = Path(run_manifest_path)
            if manifest_path.exists() and manifest_path.is_file():
                try:
                    manifest = _load_json_dict(manifest_path)
                    run_config_payload = (
                        manifest.get("run_config")
                        if isinstance(manifest.get("run_config"), dict)
                        else {}
                    )
                    # For benchmark replay manifests, the variant-specific settings live
                    # under run_config.prediction_run_config. Prefer those when available.
                    if isinstance(run_config_payload.get("prediction_run_config"), dict):
                        run_config_payload = dict(run_config_payload["prediction_run_config"])
                    compatibility_values = {
                        key: run_config_payload.get(key)
                        for key in compatibility_passthrough_keys
                        if key in run_config_payload
                    }
                    runtime_derived_keys = {
                        "effective_workers",
                        "workers",
                        "pdf_split_workers",
                        "epub_split_workers",
                    }
                    run_settings_payload = {
                        key: value
                        for key, value in run_config_payload.items()
                        if key in RunSettings.model_fields and key not in runtime_derived_keys
                    }
                    if run_settings_payload:
                        run_settings_payload.update(
                            {
                                key: value
                                for key, value in (base_run_settings_payload or {}).items()
                                if key in runtime_derived_keys
                            }
                        )
                        run_settings = RunSettings.from_dict(
                            project_run_config_payload(
                                run_settings_payload,
                                contract=RUN_SETTING_CONTRACT_FULL,
                            ),
                            warn_context="quality-leaderboard winner",
                        )
                        winner_settings = run_settings.to_run_config_dict()
                        winner_settings.update(
                            {
                                key: value
                                for key, value in compatibility_values.items()
                                if value is not None
                            }
                        )
                        return winner_settings
                except Exception:  # noqa: BLE001
                    pass

        dimensions = winner.get("dimensions")
        if not isinstance(dimensions, dict):
            return None
        merged = dict(base_run_settings_payload)
        for key, value in dimensions.items():
            cleaned_key = str(key)
            if cleaned_key in {"deterministic_sweep", "source_extension"}:
                continue
            if cleaned_key not in RunSettings.model_fields:
                continue
            merged[cleaned_key] = value
        run_settings = RunSettings.from_dict(
            project_run_config_payload(
                merged,
                contract=RUN_SETTING_CONTRACT_FULL,
            ),
            warn_context="quality-leaderboard winner",
        )
        return run_settings.to_run_config_dict()

    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
        "run_dir": str(run_dir),
        "experiment_id": str(experiment_id),
        "total_source_groups": total_source_groups,
        "allow_partial_coverage": bool(allow_partial_coverage),
        "dimension_ignore_keys": sorted(ignore_dimension_keys),
        "include_by_source_extension": bool(include_by_source_extension),
        "leaderboard": ranked,
        "winner": winner,
        "winner_run_settings": compute_winner_settings(),
        "pareto_frontier": {
            "full_coverage": _pareto_frontier(full_coverage_rows),
            "ranked_set": _pareto_frontier(ranked),
        },
    }
    if leaderboard_by_source_extension:
        payload["leaderboard_by_source_extension"] = leaderboard_by_source_extension
    return payload


def write_quality_leaderboard_artifacts(
    payload: dict[str, Any],
    *,
    out_dir: Path,
) -> LeaderboardPaths:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    leaderboard_json = out_dir / "leaderboard.json"
    leaderboard_csv = out_dir / "leaderboard.csv"
    pareto_json = out_dir / "pareto_frontier.json"
    pareto_csv = out_dir / "pareto_frontier.csv"
    winner_run_settings_json = out_dir / "winner_run_settings.json"
    winner_dimensions_json = out_dir / "winner_dimensions.json"
    leaderboard_by_source_extension_json: Path | None = None
    leaderboard_by_source_extension_csv: Path | None = None

    leaderboard_json.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    rows = payload.get("leaderboard")
    if not isinstance(rows, list):
        rows = []
    fieldnames = [
        "rank",
        "config_id",
        "run_config_hash",
        "coverage_sources",
        "coverage_ratio",
        "mean_practical_f1",
        "mean_strict_f1",
        "median_duration_seconds",
        "mean_duration_seconds",
        "line_role_gates_verdict",
        "dimensions_json",
        "line_role_json",
    ]
    with leaderboard_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            if not isinstance(row, dict):
                continue
            dimensions = row.get("dimensions") if isinstance(row.get("dimensions"), dict) else {}
            line_role = row.get("line_role") if isinstance(row.get("line_role"), dict) else {}
            writer.writerow(
                {
                    "rank": row.get("rank"),
                    "config_id": row.get("config_id"),
                    "run_config_hash": row.get("run_config_hash"),
                    "coverage_sources": row.get("coverage_sources"),
                    "coverage_ratio": row.get("coverage_ratio"),
                    "mean_practical_f1": row.get("mean_practical_f1"),
                    "mean_strict_f1": row.get("mean_strict_f1"),
                    "median_duration_seconds": row.get("median_duration_seconds"),
                    "mean_duration_seconds": row.get("mean_duration_seconds"),
                    "line_role_gates_verdict": row.get("line_role_gates_verdict"),
                    "dimensions_json": _stable_json(dimensions),
                    "line_role_json": _stable_json(line_role) if line_role else "",
                }
            )

    pareto_payload = payload.get("pareto_frontier") if isinstance(payload.get("pareto_frontier"), dict) else {}
    pareto_json.write_text(
        json.dumps(pareto_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    pareto_rows = pareto_payload.get("ranked_set")
    if not isinstance(pareto_rows, list):
        pareto_rows = []
    with pareto_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "rank",
                "config_id",
                "mean_practical_f1",
                "mean_strict_f1",
                "median_duration_seconds",
                "coverage_sources",
            ],
        )
        writer.writeheader()
        for row in pareto_rows:
            if not isinstance(row, dict):
                continue
            writer.writerow(
                {
                    "rank": row.get("rank"),
                    "config_id": row.get("config_id"),
                    "mean_practical_f1": row.get("mean_practical_f1"),
                    "mean_strict_f1": row.get("mean_strict_f1"),
                    "median_duration_seconds": row.get("median_duration_seconds"),
                    "coverage_sources": row.get("coverage_sources"),
                }
            )

    winner_payload = payload.get("winner_run_settings")
    if isinstance(winner_payload, dict):
        winner_run_settings_json.write_text(
            json.dumps(winner_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    winner = payload.get("winner")
    winner_dimensions = {}
    if isinstance(winner, dict) and isinstance(winner.get("dimensions"), dict):
        winner_dimensions = dict(winner["dimensions"])
    winner_dimensions_json.write_text(
        json.dumps(winner_dimensions, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    by_extension_payload = (
        payload.get("leaderboard_by_source_extension")
        if isinstance(payload.get("leaderboard_by_source_extension"), dict)
        else {}
    )
    if by_extension_payload:
        leaderboard_by_source_extension_json = (
            out_dir / "leaderboard_by_source_extension.json"
        )
        leaderboard_by_source_extension_csv = (
            out_dir / "leaderboard_by_source_extension.csv"
        )
        leaderboard_by_source_extension_json.write_text(
            json.dumps(by_extension_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        with leaderboard_by_source_extension_csv.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "source_extension",
                    "rank",
                    "config_id",
                    "run_config_hash",
                    "coverage_sources",
                    "coverage_ratio",
                    "mean_practical_f1",
                    "mean_strict_f1",
                    "median_duration_seconds",
                    "mean_duration_seconds",
                    "dimensions_json",
                ],
            )
            writer.writeheader()
            for source_extension in sorted(by_extension_payload):
                row_payload = by_extension_payload[source_extension]
                if not isinstance(row_payload, dict):
                    continue
                leaderboard_rows = row_payload.get("leaderboard")
                if not isinstance(leaderboard_rows, list):
                    continue
                for row in leaderboard_rows:
                    if not isinstance(row, dict):
                        continue
                    dimensions = (
                        row.get("dimensions")
                        if isinstance(row.get("dimensions"), dict)
                        else {}
                    )
                    writer.writerow(
                        {
                            "source_extension": source_extension,
                            "rank": row.get("rank"),
                            "config_id": row.get("config_id"),
                            "run_config_hash": row.get("run_config_hash"),
                            "coverage_sources": row.get("coverage_sources"),
                            "coverage_ratio": row.get("coverage_ratio"),
                            "mean_practical_f1": row.get("mean_practical_f1"),
                            "mean_strict_f1": row.get("mean_strict_f1"),
                            "median_duration_seconds": row.get(
                                "median_duration_seconds"
                            ),
                            "mean_duration_seconds": row.get("mean_duration_seconds"),
                            "dimensions_json": _stable_json(dimensions),
                        }
                    )

    return LeaderboardPaths(
        out_dir=out_dir,
        leaderboard_json=leaderboard_json,
        leaderboard_csv=leaderboard_csv,
        pareto_json=pareto_json,
        pareto_csv=pareto_csv,
        winner_run_settings_json=winner_run_settings_json,
        winner_dimensions_json=winner_dimensions_json,
        leaderboard_by_source_extension_json=leaderboard_by_source_extension_json,
        leaderboard_by_source_extension_csv=leaderboard_by_source_extension_csv,
    )
