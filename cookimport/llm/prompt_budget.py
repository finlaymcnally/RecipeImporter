from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

_TOKEN_KEYS = (
    "tokens_input",
    "tokens_cached_input",
    "tokens_output",
    "tokens_reasoning",
    "tokens_total",
)

_PREVIEW_STAGE_LABELS = {
    "recipe_llm_correct_and_link": "Recipe Correction",
    "extract_knowledge_optional": "Knowledge Harvest",
    "line_role": "Line Role",
}
_PREDICTIVE_STAGE_MODELS: dict[str, dict[str, Any]] = {
    "recipe_llm_correct_and_link": {
        "stage": "recipe_llm_correct_and_link",
        "source": "repo_calibrated_vanilla_to_codex_benchmark",
        "benchmark_ref": "2026-03-17_16.06.55/single-offline-benchmark/saltfatacidheatcutdown",
        "input_tokens_per_request_char": 1.056321,
        "output_tokens_per_request_char": 0.171744,
        "total_tokens_per_request_char": 1.228065,
        "cached_input_share": 0.480193,
        "total_tokens_per_request_char_low": 1.044,
        "total_tokens_per_request_char_high": 1.412,
    },
    "extract_knowledge_optional": {
        "stage": "extract_knowledge_optional",
        "source": "repo_calibrated_vanilla_to_codex_benchmark",
        "benchmark_ref": "2026-03-17_16.06.55/single-offline-benchmark/saltfatacidheatcutdown",
        "input_tokens_per_request_char": 1.949124,
        "output_tokens_per_request_char": 0.168638,
        "total_tokens_per_request_char": 2.117762,
        "cached_input_share": 0.722900,
        "total_tokens_per_request_char_low": 1.800,
        "total_tokens_per_request_char_high": 2.435,
    },
    "line_role": {
        "stage": "line_role",
        "source": "repo_calibrated_vanilla_to_codex_benchmark",
        "benchmark_ref": "2026-03-17_16.06.55/single-offline-benchmark/saltfatacidheatcutdown",
        "input_tokens_per_request_char": 4.027269,
        "output_tokens_per_request_char": 0.145910,
        "total_tokens_per_request_char": 4.173179,
        "cached_input_share": 0.841418,
        "total_tokens_per_request_char_low": 3.547,
        "total_tokens_per_request_char_high": 4.799,
    },
}


def build_prediction_run_prompt_budget_summary(
    pred_manifest: Mapping[str, Any],
    pred_run_dir: Path,
) -> dict[str, Any]:
    by_stage: dict[str, dict[str, Any]] = {}

    llm_payload = pred_manifest.get("llm_codex_farm")
    if isinstance(llm_payload, Mapping):
        process_runs = llm_payload.get("process_runs")
        if isinstance(process_runs, Mapping):
            for stage_name, stage_payload in sorted(process_runs.items()):
                if not isinstance(stage_payload, Mapping):
                    continue
                stage_summary = _build_codex_farm_stage_summary(
                    stage_name=str(stage_name),
                    stage_payload=stage_payload,
                )
                if stage_summary is not None:
                    by_stage[str(stage_name)] = stage_summary
        if "recipe_correction" not in by_stage:
            recipe_summary = _build_codex_farm_stage_summary(
                stage_name="recipe_correction",
                stage_payload=llm_payload,
            )
            if recipe_summary is not None:
                by_stage["recipe_correction"] = recipe_summary
        knowledge_payload = llm_payload.get("knowledge")
        if isinstance(knowledge_payload, Mapping):
            process_run = knowledge_payload.get("process_run")
            if isinstance(process_run, Mapping):
                knowledge_summary = _build_codex_farm_stage_summary(
                    stage_name="knowledge",
                    stage_payload=process_run,
                )
                if knowledge_summary is not None:
                    authority_mode = str(knowledge_payload.get("authority_mode") or "").strip()
                    scored_effect = str(knowledge_payload.get("scored_effect") or "").strip()
                    if authority_mode:
                        knowledge_summary["authority_mode"] = authority_mode
                    if scored_effect:
                        knowledge_summary["scored_effect"] = scored_effect
                    by_stage["knowledge"] = knowledge_summary
            if "knowledge" not in by_stage:
                knowledge_summary = _build_codex_farm_stage_summary(
                    stage_name="knowledge",
                    stage_payload=knowledge_payload,
                )
                if knowledge_summary is not None:
                    authority_mode = str(knowledge_payload.get("authority_mode") or "").strip()
                    scored_effect = str(knowledge_payload.get("scored_effect") or "").strip()
                    if authority_mode:
                        knowledge_summary["authority_mode"] = authority_mode
                    if scored_effect:
                        knowledge_summary["scored_effect"] = scored_effect
                    by_stage["knowledge"] = knowledge_summary

    line_role_summary = _build_line_role_stage_summary(
        pred_manifest=pred_manifest,
        pred_run_dir=pred_run_dir,
    )
    if line_role_summary is not None:
        by_stage["line_role"] = line_role_summary

    totals: dict[str, int | None] = {
        "call_count": None,
        "duration_total_ms": None,
        **{key: None for key in _TOKEN_KEYS},
    }
    for payload in by_stage.values():
        totals["call_count"] = _sum_optional_ints(
            totals.get("call_count"),
            _nonnegative_int(payload.get("call_count")),
        )
        totals["duration_total_ms"] = _sum_optional_ints(
            totals.get("duration_total_ms"),
            _nonnegative_int(payload.get("duration_total_ms")),
        )
        for key in _TOKEN_KEYS:
            totals[key] = _sum_optional_ints(
                totals.get(key),
                _nonnegative_int(payload.get(key)),
            )

    return {
        "schema_version": "prompt_budget_summary.v1",
        "prediction_run_dir": str(pred_run_dir),
        "by_stage": by_stage,
        "totals": totals,
    }


def write_prediction_run_prompt_budget_summary(
    pred_run_dir: Path,
    summary: Mapping[str, Any],
) -> Path:
    target_path = pred_run_dir / "prompt_budget_summary.json"
    target_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target_path


def build_prompt_preview_budget_summary(
    *,
    prompt_rows: list[Mapping[str, Any]],
    preview_dir: Path,
    phase_plans: Mapping[str, Mapping[str, Any]] | None = None,
    live_stage_summaries: Mapping[str, Mapping[str, Any]] | None = None,
    predictive_stage_models: Mapping[str, Mapping[str, Any]] | None = None,
    estimation_mode: str = "predictive",
) -> dict[str, Any]:
    by_stage: dict[str, dict[str, Any]] = {}
    live_telemetry_used = False
    historical_calibration_used = False
    unavailable_stage_count = 0
    normalized_estimation_mode = str(estimation_mode or "predictive").strip().lower() or "predictive"
    for row in prompt_rows:
        stage_key = str(row.get("stage_key") or "").strip()
        if not stage_key:
            stage_key = "unknown"
        rendered_prompt_text = str(row.get("rendered_prompt_text") or "")
        prompt_chars = len(rendered_prompt_text)
        prompt_input_mode = str(row.get("prompt_input_mode") or "path").strip().lower()
        stage_payload = by_stage.setdefault(
            stage_key,
            {
                "stage": stage_key,
                "stage_label": _PREVIEW_STAGE_LABELS.get(stage_key, stage_key.replace("_", " ").title()),
                "kind": "preview",
                "call_count": 0,
                "interaction_count": 0,
                "worker_count": 0,
                "fresh_agent_count": 0,
                "shard_count": 0,
                "owned_id_count": 0,
                "shards_per_worker": {"count": 0, "min": 0, "max": 0, "avg": 0.0},
                "owned_ids_per_shard": {"count": 0, "min": 0, "max": 0, "avg": 0.0},
                "first_turn_payload_chars": {"count": 0, "min": 0, "max": 0, "avg": 0.0},
                "task_payload_chars": {"count": 0, "min": 0, "max": 0, "avg": 0.0},
                "task_prompt_chars_total": 0,
                "task_prompt_chars_avg": 0,
                "prompt_chars_total": 0,
                "prompt_chars_avg": 0,
                "estimated_request_chars_total": 0,
                "transport_overhead_chars_total": 0,
                "estimated_input_tokens": None,
                "estimated_cached_input_tokens": None,
                "estimated_output_tokens": None,
                "estimated_total_tokens": None,
                "estimation_basis": "unavailable",
            },
        )
        task_prompt_text = str(row.get("task_prompt_text") or rendered_prompt_text)
        task_prompt_chars = len(task_prompt_text)
        stage_payload["call_count"] += 1
        stage_payload["task_prompt_chars_total"] += task_prompt_chars
        stage_payload["prompt_chars_total"] += prompt_chars
        stage_payload["estimated_request_chars_total"] += (
            prompt_chars + task_prompt_chars
            if prompt_input_mode == "path"
            else prompt_chars
        )
        stage_payload["transport_overhead_chars_total"] += max(
            prompt_chars - task_prompt_chars,
            0,
        )

    totals = {
        "call_count": 0,
        "task_prompt_chars_total": 0,
        "task_prompt_chars_avg": 0,
        "prompt_chars_total": 0,
        "prompt_chars_avg": 0,
        "estimated_request_chars_total": 0,
        "transport_overhead_chars_total": 0,
        "estimated_input_tokens": None,
        "estimated_cached_input_tokens": None,
        "estimated_output_tokens": None,
        "estimated_total_tokens": None,
    }
    for stage_key, payload in by_stage.items():
        call_count = int(payload.get("call_count") or 0)
        task_prompt_chars_total = int(payload.get("task_prompt_chars_total") or 0)
        prompt_chars_total = int(payload.get("prompt_chars_total") or 0)
        estimated_request_chars_total = int(payload.get("estimated_request_chars_total") or 0)
        estimated_input_tokens: int | None = None
        estimated_output_tokens: int | None = None
        estimated_cached_input_tokens: int | None = None
        estimated_total_tokens: int | None = None
        payload["task_prompt_chars_avg"] = (
            int(round(task_prompt_chars_total / call_count)) if call_count > 0 else 0
        )
        payload["prompt_chars_avg"] = int(round(prompt_chars_total / call_count)) if call_count > 0 else 0
        live_stage = (
            live_stage_summaries.get(stage_key)
            if normalized_estimation_mode == "observed" and isinstance(live_stage_summaries, Mapping)
            else None
        )
        if isinstance(live_stage, Mapping):
            live_input_tokens = _nonnegative_int(live_stage.get("tokens_input"))
            live_cached_input_tokens = _nonnegative_int(live_stage.get("tokens_cached_input"))
            live_output_tokens = _nonnegative_int(live_stage.get("tokens_output"))
            live_total_tokens = _nonnegative_int(live_stage.get("tokens_total"))
            if any(
                value is not None
                for value in (
                    live_input_tokens,
                    live_cached_input_tokens,
                    live_output_tokens,
                    live_total_tokens,
                )
            ):
                live_telemetry_used = True
                payload["estimation_basis"] = "live_telemetry"
                payload["live_telemetry"] = {
                    "call_count": _nonnegative_int(live_stage.get("call_count")),
                    "duration_total_ms": _nonnegative_int(live_stage.get("duration_total_ms")),
                    "tokens_input": live_input_tokens,
                    "tokens_cached_input": live_cached_input_tokens,
                    "tokens_output": live_output_tokens,
                    "tokens_total": live_total_tokens,
                }
                estimated_input_tokens = live_input_tokens or 0
                estimated_output_tokens = live_output_tokens or 0
                estimated_cached_input_tokens = live_cached_input_tokens or 0
                estimated_total_tokens = (
                    live_total_tokens
                    if live_total_tokens is not None
                    else estimated_input_tokens + estimated_output_tokens
                )
            else:
                calibration = (
                    predictive_stage_models.get(stage_key)
                    if isinstance(predictive_stage_models, Mapping)
                    else None
                )
                if isinstance(calibration, Mapping):
                    calibrated_input_ratio = _nonnegative_float(
                        calibration.get("input_tokens_per_request_char")
                    )
                    calibrated_output_ratio = _nonnegative_float(
                        calibration.get("output_tokens_per_request_char")
                    )
                    calibrated_total_ratio = _nonnegative_float(
                        calibration.get("total_tokens_per_request_char")
                    )
                    calibrated_cached_share = _nonnegative_float(
                        calibration.get("cached_input_share")
                    )
                    if (
                        estimated_request_chars_total > 0
                        and calibrated_input_ratio is not None
                        and calibrated_total_ratio is not None
                    ):
                        historical_calibration_used = True
                        payload["estimation_basis"] = "historical_calibration"
                        payload["historical_calibration"] = dict(calibration)
                        estimated_input_tokens = int(
                            round(estimated_request_chars_total * calibrated_input_ratio)
                        )
                        if calibrated_output_ratio is not None:
                            estimated_output_tokens = int(
                                round(estimated_request_chars_total * calibrated_output_ratio)
                            )
                        else:
                            estimated_output_tokens = max(
                                int(round(estimated_request_chars_total * calibrated_total_ratio))
                                - estimated_input_tokens,
                                0,
                            )
                        estimated_cached_input_tokens = int(
                            round(estimated_input_tokens * calibrated_cached_share)
                        ) if calibrated_cached_share is not None else 0
                        estimated_total_tokens = int(
                            round(estimated_request_chars_total * calibrated_total_ratio)
                        )
                        payload["estimated_total_tokens_low"] = int(
                            round(
                                estimated_request_chars_total
                                * float(
                                    calibration.get("total_tokens_per_request_char_low")
                                    or calibrated_total_ratio
                                )
                            )
                        )
                        payload["estimated_total_tokens_high"] = int(
                            round(
                                estimated_request_chars_total
                                * float(
                                    calibration.get("total_tokens_per_request_char_high")
                                    or calibrated_total_ratio
                                )
                            )
                        )
                    else:
                        payload["estimation_basis"] = "unavailable"
        else:
            calibration = (
                predictive_stage_models.get(stage_key)
                if isinstance(predictive_stage_models, Mapping)
                else None
            )
            if isinstance(calibration, Mapping):
                calibrated_input_ratio = _nonnegative_float(
                    calibration.get("input_tokens_per_request_char")
                )
                calibrated_output_ratio = _nonnegative_float(
                    calibration.get("output_tokens_per_request_char")
                )
                calibrated_total_ratio = _nonnegative_float(
                    calibration.get("total_tokens_per_request_char")
                )
                calibrated_cached_share = _nonnegative_float(
                    calibration.get("cached_input_share")
                )
                if (
                    estimated_request_chars_total > 0
                    and calibrated_input_ratio is not None
                    and calibrated_total_ratio is not None
                ):
                    historical_calibration_used = True
                    payload["estimation_basis"] = "historical_calibration"
                    payload["historical_calibration"] = dict(calibration)
                    estimated_input_tokens = int(
                        round(estimated_request_chars_total * calibrated_input_ratio)
                    )
                    if calibrated_output_ratio is not None:
                        estimated_output_tokens = int(
                            round(estimated_request_chars_total * calibrated_output_ratio)
                        )
                    else:
                        estimated_output_tokens = max(
                            int(round(estimated_request_chars_total * calibrated_total_ratio))
                            - estimated_input_tokens,
                            0,
                        )
                    estimated_cached_input_tokens = int(
                        round(estimated_input_tokens * calibrated_cached_share)
                    ) if calibrated_cached_share is not None else 0
                    estimated_total_tokens = int(
                        round(estimated_request_chars_total * calibrated_total_ratio)
                    )
                    payload["estimated_total_tokens_low"] = int(
                        round(
                            estimated_request_chars_total
                            * float(
                                calibration.get("total_tokens_per_request_char_low")
                                or calibrated_total_ratio
                            )
                        )
                    )
                    payload["estimated_total_tokens_high"] = int(
                        round(
                            estimated_request_chars_total
                            * float(
                                calibration.get("total_tokens_per_request_char_high")
                                or calibrated_total_ratio
                            )
                        )
                    )
                else:
                    payload["estimation_basis"] = "unavailable"
            else:
                payload["estimation_basis"] = "unavailable"
        payload["estimated_input_tokens"] = estimated_input_tokens
        payload["estimated_cached_input_tokens"] = estimated_cached_input_tokens
        payload["estimated_output_tokens"] = estimated_output_tokens
        payload["estimated_total_tokens"] = estimated_total_tokens
        if estimated_total_tokens is None:
            unavailable_stage_count += 1
        if isinstance(phase_plans, Mapping):
            phase_plan = phase_plans.get(stage_key)
            if isinstance(phase_plan, Mapping):
                payload["interaction_count"] = _nonnegative_int(
                    phase_plan.get("interaction_count")
                ) or call_count
                payload["worker_count"] = _nonnegative_int(phase_plan.get("worker_count")) or 0
                payload["fresh_agent_count"] = (
                    _nonnegative_int(phase_plan.get("fresh_agent_count")) or 0
                )
                payload["shard_count"] = _nonnegative_int(phase_plan.get("shard_count")) or call_count
                payload["owned_id_count"] = _nonnegative_int(phase_plan.get("owned_id_count")) or 0
                for key in (
                    "shards_per_worker",
                    "owned_ids_per_shard",
                    "first_turn_payload_chars",
                    "task_payload_chars",
                ):
                    distribution = phase_plan.get(key)
                    if isinstance(distribution, Mapping):
                        payload[key] = {
                            "count": int(_nonnegative_int(distribution.get("count")) or 0),
                            "min": int(_nonnegative_int(distribution.get("min")) or 0),
                            "max": int(_nonnegative_int(distribution.get("max")) or 0),
                            "avg": float(distribution.get("avg") or 0.0),
                        }
        totals["call_count"] += call_count
        totals["task_prompt_chars_total"] += task_prompt_chars_total
        totals["prompt_chars_total"] += prompt_chars_total
        totals["estimated_request_chars_total"] += estimated_request_chars_total
        totals["transport_overhead_chars_total"] += int(
            payload.get("transport_overhead_chars_total") or 0
        )
        totals["estimated_input_tokens"] = _sum_optional_ints(
            totals.get("estimated_input_tokens"),
            estimated_input_tokens,
        )
        totals["estimated_cached_input_tokens"] = _sum_optional_ints(
            totals.get("estimated_cached_input_tokens"),
            estimated_cached_input_tokens,
        )
        totals["estimated_output_tokens"] = _sum_optional_ints(
            totals.get("estimated_output_tokens"),
            estimated_output_tokens,
        )
        totals["estimated_total_tokens"] = _sum_optional_ints(
            totals.get("estimated_total_tokens"),
            estimated_total_tokens,
        )
    if totals["call_count"] > 0:
        totals["task_prompt_chars_avg"] = int(
            round(totals["task_prompt_chars_total"] / totals["call_count"])
        )
        totals["prompt_chars_avg"] = int(round(totals["prompt_chars_total"] / totals["call_count"]))

    warnings = _build_prompt_preview_budget_warnings(
        by_stage=by_stage,
        totals=totals,
    )

    return {
        "schema_version": "prompt_preview_budget_summary.v4",
        "preview_dir": str(preview_dir),
        "estimation_method": {
            "type": (
                    "observed_live_telemetry"
                    if live_telemetry_used
                    else (
                    "predictive_stage_model"
                    if historical_calibration_used
                    else "no_token_estimate_available"
                )
            ),
            "mode": normalized_estimation_mode,
            "unavailable_stage_count": unavailable_stage_count,
            "notes": [
                (
                    "Observed mode can reuse exact stage telemetry from a completed processed run, "
                    "but predictive mode intentionally ignores exact live telemetry."
                ),
                (
                    "Predictive estimates use repo-owned stage models calibrated from a paired vanilla-to-Codex benchmark, "
                    "applied to the selected run's vanilla-shaped prompt payloads."
                ),
                "Stages without usable calibration are reported as unavailable instead of guessed from prompt text length.",
                "Warnings are intentionally blunt and also consider raw prompt chars plus call counts, not only token estimates.",
            ],
        },
        "by_stage": by_stage,
        "totals": totals,
        "warnings": warnings,
    }


def write_prompt_preview_budget_summary(
    preview_dir: Path,
    summary: Mapping[str, Any],
) -> tuple[Path, Path]:
    json_path = preview_dir / "prompt_preview_budget_summary.json"
    md_path = preview_dir / "prompt_preview_budget_summary.md"
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        _render_prompt_preview_budget_summary_md(summary),
        encoding="utf-8",
    )
    return json_path, md_path


def _build_codex_farm_stage_summary(
    *,
    stage_name: str,
    stage_payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    telemetry_rows = _extract_telemetry_rows(stage_payload=stage_payload)

    token_totals: dict[str, int | None] = {key: None for key in _TOKEN_KEYS}
    row_count = 0
    if isinstance(telemetry_rows, list):
        for row in telemetry_rows:
            if not isinstance(row, Mapping):
                continue
            row_count += 1
            for key in _TOKEN_KEYS:
                token_totals[key] = _sum_optional_ints(
                    token_totals.get(key),
                    _nonnegative_int(row.get(key)),
                )

    summary_payload = _extract_summary_payload(stage_payload=stage_payload)
    if isinstance(summary_payload, Mapping):
        for key in _TOKEN_KEYS:
            fallback_value = summary_payload.get(key)
            if key == "tokens_reasoning" and fallback_value is None:
                fallback_value = summary_payload.get("tokens_reasoning_total")
            if token_totals.get(key) is None:
                token_totals[key] = _nonnegative_int(fallback_value)

    call_count = (
        _extract_call_count(summary_payload)
        if isinstance(summary_payload, Mapping)
        else None
    )
    if row_count > 0:
        call_count = row_count
    duration_total_ms = (
        _extract_duration_total_ms(summary_payload, call_count=call_count)
        if isinstance(summary_payload, Mapping)
        else None
    )
    if isinstance(telemetry_rows, list):
        duration_total_ms = _extract_duration_total_ms_from_rows(telemetry_rows)

    if (
        call_count is None
        and duration_total_ms is None
        and all(token_totals.get(key) is None for key in _TOKEN_KEYS)
    ):
        return None

    return {
        "stage": stage_name,
        "kind": "codex_farm",
        "call_count": call_count,
        "duration_total_ms": duration_total_ms,
        **token_totals,
    }


def _extract_telemetry_rows(*, stage_payload: Mapping[str, Any]) -> list[Any] | None:
    rows: list[Any] = []
    _collect_telemetry_rows_from_payload(stage_payload, rows)
    return rows or None


def _build_line_role_stage_summary(
    *,
    pred_manifest: Mapping[str, Any],
    pred_run_dir: Path,
) -> dict[str, Any] | None:
    for telemetry_path in _iter_line_role_telemetry_paths(
        pred_manifest=pred_manifest,
        pred_run_dir=pred_run_dir,
    ):
        try:
            payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(payload, Mapping):
            continue
        summary = payload.get("summary")
        if not isinstance(summary, Mapping):
            if _looks_like_summary_payload(payload):
                summary = payload
            else:
                continue

        call_count = _nonnegative_int(summary.get("call_count"))
        batch_count = _nonnegative_int(summary.get("batch_count"))
        if call_count is None:
            call_count = batch_count

        token_totals = {
            key: _nonnegative_int(summary.get(key))
            for key in _TOKEN_KEYS
        }
        duration_total_ms = _nonnegative_int(summary.get("duration_total_ms"))
        if (
            call_count is None
            and duration_total_ms is None
            and all(value is None for value in token_totals.values())
        ):
            continue

        return {
            "stage": "line_role",
            "kind": "line_role",
            "call_count": call_count,
            "batch_count": batch_count,
            "attempt_count": _nonnegative_int(summary.get("attempt_count")),
            "duration_total_ms": duration_total_ms,
            **token_totals,
        }
    return None


def _iter_line_role_telemetry_paths(
    *,
    pred_manifest: Mapping[str, Any],
    pred_run_dir: Path,
) -> list[Path]:
    raw_path = str(pred_manifest.get("line_role_pipeline_telemetry_path") or "").strip()
    candidates: list[Path] = []
    if raw_path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = pred_run_dir / candidate
        candidates.append(candidate)
    candidates.append(pred_run_dir / "line-role-pipeline" / "telemetry_summary.json")
    for manifest_key in ("processed_run_root", "stage_run_root"):
        raw_root = str(pred_manifest.get(manifest_key) or "").strip()
        if not raw_root:
            continue
        candidates.append(Path(raw_root) / "line-role-pipeline" / "telemetry_summary.json")

    resolved: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            resolved.append(candidate)
    return resolved


def _extract_summary_payload(*, stage_payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    candidates: list[Mapping[str, Any]] = []
    _collect_summary_payloads(stage_payload, candidates)
    if not candidates:
        return None
    return max(candidates, key=_summary_payload_score)


def _extract_call_count(summary: Mapping[str, Any]) -> int | None:
    call_count = _nonnegative_int(summary.get("call_count"))
    if call_count is not None:
        return call_count
    status_counts = summary.get("status_counts")
    if isinstance(status_counts, Mapping):
        parsed = [
            _nonnegative_int(value)
            for value in status_counts.values()
        ]
        if any(value is not None for value in parsed):
            return sum(int(value or 0) for value in parsed)
    matched_rows = _nonnegative_int(summary.get("matched_rows"))
    if matched_rows is not None:
        return matched_rows
    return None


def _extract_duration_total_ms(
    summary: Mapping[str, Any],
    *,
    call_count: int | None,
) -> int | None:
    duration_total_ms = _nonnegative_int(summary.get("duration_total_ms"))
    if duration_total_ms is not None:
        return duration_total_ms
    duration_avg_ms = summary.get("duration_avg_ms")
    avg_value = _nonnegative_float(duration_avg_ms)
    if avg_value is not None and call_count is not None and call_count > 0:
        return int(round(avg_value * call_count))
    return None


def _extract_duration_total_ms_from_rows(rows: list[Any]) -> int | None:
    duration_total_ms: int | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        duration_total_ms = _sum_optional_ints(
            duration_total_ms,
            _nonnegative_int(row.get("duration_ms")),
        )
    return duration_total_ms


def _collect_telemetry_rows_from_payload(payload: Mapping[str, Any], rows: list[Any]) -> None:
    process_payload = payload.get("process_payload")
    if isinstance(process_payload, Mapping):
        _collect_telemetry_rows_from_payload(process_payload, rows)

    process_run = payload.get("process_run")
    if isinstance(process_run, Mapping):
        _collect_telemetry_rows_from_payload(process_run, rows)

    telemetry = payload.get("telemetry")
    if isinstance(telemetry, Mapping) and isinstance(telemetry.get("rows"), list):
        rows.extend(telemetry.get("rows") or [])

    worker_runs = payload.get("worker_runs")
    if isinstance(worker_runs, list):
        for worker_run in worker_runs:
            if isinstance(worker_run, Mapping):
                _collect_telemetry_rows_from_payload(worker_run, rows)

    for runtime_key in ("phase_runtime", "phase_worker_runtime"):
        runtime_payload = payload.get(runtime_key)
        if not isinstance(runtime_payload, Mapping):
            continue
        worker_reports = runtime_payload.get("worker_reports")
        if not isinstance(worker_reports, list):
            continue
        for report in worker_reports:
            if not isinstance(report, Mapping):
                continue
            runner_result = report.get("runner_result")
            if isinstance(runner_result, Mapping):
                _collect_telemetry_rows_from_payload(runner_result, rows)


def _collect_summary_payloads(
    payload: Mapping[str, Any],
    summaries: list[Mapping[str, Any]],
) -> None:
    process_payload = payload.get("process_payload")
    if isinstance(process_payload, Mapping):
        _collect_summary_payloads(process_payload, summaries)

    process_run = payload.get("process_run")
    if isinstance(process_run, Mapping):
        _collect_summary_payloads(process_run, summaries)

    telemetry_report = payload.get("telemetry_report")
    if isinstance(telemetry_report, Mapping):
        if isinstance(telemetry_report.get("summary"), Mapping):
            summaries.append(telemetry_report.get("summary"))
        elif _looks_like_summary_payload(telemetry_report):
            summaries.append(telemetry_report)

    telemetry = payload.get("telemetry")
    if isinstance(telemetry, Mapping) and isinstance(telemetry.get("summary"), Mapping):
        summaries.append(telemetry.get("summary"))

    worker_runs = payload.get("worker_runs")
    if isinstance(worker_runs, list):
        for worker_run in worker_runs:
            if isinstance(worker_run, Mapping):
                _collect_summary_payloads(worker_run, summaries)

    for runtime_key in ("phase_runtime", "phase_worker_runtime"):
        runtime_payload = payload.get(runtime_key)
        if not isinstance(runtime_payload, Mapping):
            continue
        telemetry_payload = runtime_payload.get("telemetry")
        if isinstance(telemetry_payload, Mapping) and _looks_like_summary_payload(telemetry_payload):
            summaries.append(telemetry_payload)
        worker_reports = runtime_payload.get("worker_reports")
        if not isinstance(worker_reports, list):
            continue
        for report in worker_reports:
            if not isinstance(report, Mapping):
                continue
            runner_result = report.get("runner_result")
            if isinstance(runner_result, Mapping):
                _collect_summary_payloads(runner_result, summaries)


def _looks_like_summary_payload(payload: Mapping[str, Any]) -> bool:
    if any(_nonnegative_int(payload.get(key)) is not None for key in _TOKEN_KEYS):
        return True
    return any(
        key in payload
        for key in (
            "call_count",
            "duration_total_ms",
            "duration_avg_ms",
            "attempt_count",
            "batch_count",
            "matched_rows",
            "status_counts",
        )
    )


def _summary_payload_score(payload: Mapping[str, Any]) -> tuple[int, int]:
    token_hits = sum(1 for key in _TOKEN_KEYS if _nonnegative_int(payload.get(key)) is not None)
    aux_hits = sum(
        1
        for key in (
            "call_count",
            "duration_total_ms",
            "duration_avg_ms",
            "attempt_count",
            "batch_count",
            "matched_rows",
            "status_counts",
        )
        if payload.get(key) is not None
    )
    return (token_hits, aux_hits)


def _nonnegative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _nonnegative_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _sum_optional_ints(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _build_prompt_preview_budget_warnings(
    *,
    by_stage: Mapping[str, Mapping[str, Any]],
    totals: Mapping[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []

    total_calls = _nonnegative_int(totals.get("call_count")) or 0
    total_prompt_chars = _nonnegative_int(totals.get("prompt_chars_total")) or 0
    total_request_chars = _nonnegative_int(totals.get("estimated_request_chars_total")) or 0
    total_estimated_tokens = _nonnegative_int(totals.get("estimated_total_tokens"))
    unavailable_stages = [
        str(payload.get("stage_label") or stage_key)
        for stage_key, payload in by_stage.items()
        if isinstance(payload, Mapping) and str(payload.get("estimation_basis") or "") == "unavailable"
    ]
    if unavailable_stages:
        warnings.append(
            {
                "severity": "warning",
                "code": "token_estimate_unavailable",
                "message": (
                    "Token estimate unavailable for: "
                    + ", ".join(unavailable_stages)
                    + ". Preview only reports tokens when live telemetry or historical calibration is available."
                ),
            }
        )
    if total_estimated_tokens is None:
        total_estimated_tokens_value = 0
    else:
        total_estimated_tokens_value = total_estimated_tokens
    if (
        total_calls >= 200
        or total_prompt_chars >= 1_500_000
        or total_request_chars >= 1_500_000
        or total_estimated_tokens_value >= 500_000
    ):
        warnings.append(
            {
                "severity": "danger",
                "code": "extreme_prompt_budget",
                "message": (
                    f"EXTREME prompt budget: {total_calls} calls, {total_prompt_chars:,} rendered prompt chars, "
                    f"{total_request_chars:,} estimated request chars, "
                    + (
                        f"~{total_estimated_tokens_value:,} estimated total tokens. "
                        if total_estimated_tokens is not None
                        else "token estimate unavailable. "
                    )
                    + "Treat this as a multi-million-token danger zone."
                ),
            }
        )
    elif (
        total_calls >= 100
        or total_prompt_chars >= 750_000
        or total_request_chars >= 750_000
        or total_estimated_tokens_value >= 250_000
    ):
        warnings.append(
            {
                "severity": "warning",
                "code": "high_prompt_budget",
                "message": (
                    f"High prompt budget: {total_calls} calls, {total_prompt_chars:,} rendered prompt chars, "
                    f"{total_request_chars:,} estimated request chars, "
                    + (
                        f"~{total_estimated_tokens_value:,} estimated total tokens."
                        if total_estimated_tokens is not None
                        else "token estimate unavailable."
                    )
                ),
            }
        )

    recipe_stage = by_stage.get("recipe_llm_correct_and_link")
    if isinstance(recipe_stage, Mapping):
        recipe_calls = _nonnegative_int(recipe_stage.get("call_count")) or 0
        recipe_chars = _nonnegative_int(recipe_stage.get("prompt_chars_total")) or 0
        if recipe_calls >= 100:
            warnings.append(
                {
                    "severity": "danger" if recipe_calls >= 200 else "warning",
                    "code": "recipe_fanout_high",
                    "message": (
                    f"Recipe correction fan-out is very high: {recipe_calls} shard interactions "
                    f"({recipe_chars:,} rendered chars) before any model output."
                ),
            }
        )

    knowledge_stage = by_stage.get("extract_knowledge_optional")
    if isinstance(knowledge_stage, Mapping):
        knowledge_calls = _nonnegative_int(knowledge_stage.get("call_count")) or 0
        if knowledge_calls >= 40:
            warnings.append(
                {
                    "severity": "warning",
                    "code": "knowledge_fanout_high",
                    "message": f"Knowledge extraction fan-out is high: {knowledge_calls} shard interactions.",
                }
            )
    return warnings


def _render_prompt_preview_budget_summary_md(summary: Mapping[str, Any]) -> str:
    totals = summary.get("totals")
    if not isinstance(totals, Mapping):
        totals = {}
    estimation_method = summary.get("estimation_method")
    if not isinstance(estimation_method, Mapping):
        estimation_method = {}
    estimation_type = str(estimation_method.get("type") or "no_token_estimate_available").strip()
    headline_suffix = (
        "observed live telemetry"
        if estimation_type == "observed_live_telemetry"
        else (
            "predictive historical calibration"
            if estimation_type == "predictive_historical_calibration"
            else "no estimate available"
        )
    )
    estimated_total_tokens = _nonnegative_int(totals.get("estimated_total_tokens"))
    estimated_total_tokens_text = (
        f"`~{int(estimated_total_tokens):,}`"
        if estimated_total_tokens is not None
        else "`unavailable`"
    )
    lines = [
        "# Prompt Preview Budget Summary",
        "",
        f"- Preview dir: `{summary.get('preview_dir')}`",
        (
            f"- Estimated total tokens: {estimated_total_tokens_text} "
            f"({headline_suffix})"
        ),
        f"- Total interactions: `{int(_nonnegative_int(totals.get('call_count')) or 0):,}`",
        f"- Task prompt chars: `{int(_nonnegative_int(totals.get('task_prompt_chars_total')) or 0):,}`",
        f"- Rendered prompt chars: `{int(_nonnegative_int(totals.get('prompt_chars_total')) or 0):,}`",
        f"- Estimated request chars: `{int(_nonnegative_int(totals.get('estimated_request_chars_total')) or 0):,}`",
        (
            f"- Transport overhead chars: "
            f"`{int(_nonnegative_int(totals.get('transport_overhead_chars_total')) or 0):,}`"
        ),
        "",
    ]
    cached_input_tokens = _nonnegative_int(totals.get("estimated_cached_input_tokens"))
    if cached_input_tokens is not None and cached_input_tokens > 0:
        lines.append(f"- Cached input tokens observed: `{cached_input_tokens:,}`")
        lines.append("")
    warnings = summary.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            if not isinstance(warning, Mapping):
                continue
            lines.append(f"- [{str(warning.get('severity') or 'warning').upper()}] {str(warning.get('message') or '').strip()}")
        lines.append("")

    lines.append("## By Stage")
    lines.append("")
    lines.append(
        "| Stage | Basis | Workers | Shards | Interactions | Owned IDs / Shard | First-Turn Chars / Shard | Est. Total Tokens | Range |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    by_stage = summary.get("by_stage")
    if isinstance(by_stage, Mapping):
        for stage_key, payload in by_stage.items():
            if not isinstance(payload, Mapping):
                continue
            owned_ids_per_shard = payload.get("owned_ids_per_shard")
            first_turn_chars = payload.get("first_turn_payload_chars")
            if not isinstance(owned_ids_per_shard, Mapping):
                owned_ids_per_shard = {}
            if not isinstance(first_turn_chars, Mapping):
                first_turn_chars = {}
            lines.append(
                "| "
                + f"{str(payload.get('stage_label') or stage_key)} | "
                + f"{str(payload.get('estimation_basis') or 'unavailable')} | "
                + f"{int(_nonnegative_int(payload.get('worker_count')) or 0):,} | "
                + f"{int(_nonnegative_int(payload.get('shard_count')) or 0):,} | "
                + f"{int(_nonnegative_int(payload.get('interaction_count')) or _nonnegative_int(payload.get('call_count')) or 0):,} | "
                + f"{float(owned_ids_per_shard.get('avg') or 0.0):.2f} | "
                + f"{float(first_turn_chars.get('avg') or 0.0):.1f} | "
                + (
                    f"{int(_nonnegative_int(payload.get('estimated_total_tokens'))):,}"
                    if _nonnegative_int(payload.get('estimated_total_tokens')) is not None
                    else "unavailable"
                )
                + " |"
                + (
                    (
                        f" {int(_nonnegative_int(payload.get('estimated_total_tokens_low')) or _nonnegative_int(payload.get('estimated_total_tokens'))):,}"
                        f"-{int(_nonnegative_int(payload.get('estimated_total_tokens_high')) or _nonnegative_int(payload.get('estimated_total_tokens'))):,} |"
                    )
                    if _nonnegative_int(payload.get('estimated_total_tokens')) is not None
                    else " unavailable |"
                )
            )
    lines.append("")
    lines.append("## Prompt Detail")
    lines.append("")
    lines.append(
        "| Stage | Basis | Task Chars | Wrapped Chars | Overhead Chars | Est. Input Tokens |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
    if isinstance(by_stage, Mapping):
        for stage_key, payload in by_stage.items():
            if not isinstance(payload, Mapping):
                continue
            lines.append(
                "| "
                + f"{str(payload.get('stage_label') or stage_key)} | "
                + f"{str(payload.get('estimation_basis') or 'unavailable')} | "
                + f"{int(_nonnegative_int(payload.get('task_prompt_chars_total')) or 0):,} | "
                + f"{int(_nonnegative_int(payload.get('prompt_chars_total')) or 0):,} | "
                + f"{int(_nonnegative_int(payload.get('transport_overhead_chars_total')) or 0):,} | "
                + (
                    f"{int(_nonnegative_int(payload.get('estimated_input_tokens'))):,}"
                    if _nonnegative_int(payload.get('estimated_input_tokens')) is not None
                    else "unavailable"
                )
                + " |"
            )
    lines.append("")
    if estimation_type == "observed_live_telemetry":
        lines.append(
            "_Estimated tokens reuse exact live stage telemetry from the completed processed run when available; this is retrospective, not predictive._"
        )
    elif estimation_type == "predictive_stage_model":
        lines.append(
            "_Estimated tokens are predictive: they ignore exact live telemetry for the selected run, derive workload shape from the selected run's vanilla-style processed output, and apply repo-owned stage models calibrated from a paired vanilla-to-Codex benchmark; the range column reflects the baked-in uncertainty band for each stage model._"
        )
    else:
        lines.append(
            "_No predictive token estimate is shown because this preview had no usable stage calibration to ground the numbers._"
        )
    return "\n".join(lines) + "\n"


def load_prompt_preview_live_stage_summaries(
    *,
    processed_run_dir: Path,
    workbook_slug: str,
) -> dict[str, dict[str, Any]]:
    by_stage: dict[str, dict[str, Any]] = {}

    recipe_summary = _build_phase_worker_status_stage_summary(
        stage_name="recipe_llm_correct_and_link",
        runtime_root=processed_run_dir / "raw" / "llm" / workbook_slug / "recipe_phase_runtime",
    )
    if recipe_summary is not None:
        by_stage["recipe_llm_correct_and_link"] = recipe_summary

    knowledge_summary = _build_phase_worker_status_stage_summary(
        stage_name="extract_knowledge_optional",
        runtime_root=processed_run_dir / "raw" / "llm" / workbook_slug / "knowledge",
    )
    if knowledge_summary is not None:
        by_stage["extract_knowledge_optional"] = knowledge_summary

    line_role_summary = _build_line_role_stage_summary(
        pred_manifest={},
        pred_run_dir=processed_run_dir,
    )
    if line_role_summary is not None:
        by_stage["line_role"] = line_role_summary

    return by_stage


def load_prompt_preview_stage_calibrations(*, repo_root: Path) -> dict[str, dict[str, Any]]:
    del repo_root
    return {
        stage_key: dict(payload)
        for stage_key, payload in _PREDICTIVE_STAGE_MODELS.items()
    }


def _build_phase_worker_status_stage_summary(
    *,
    stage_name: str,
    runtime_root: Path,
) -> dict[str, Any] | None:
    workers_root = runtime_root / "workers"
    if not workers_root.is_dir():
        return None

    aggregated: dict[str, int | None] = {
        "call_count": None,
        "duration_total_ms": None,
        **{key: None for key in _TOKEN_KEYS},
    }
    found = False
    for status_path in sorted(workers_root.glob("*/status.json")):
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(payload, Mapping):
            continue
        summary = _build_codex_farm_stage_summary(stage_name=stage_name, stage_payload=payload)
        if summary is None:
            continue
        found = True
        aggregated["call_count"] = _sum_optional_ints(
            aggregated.get("call_count"),
            _nonnegative_int(summary.get("call_count")),
        )
        aggregated["duration_total_ms"] = _sum_optional_ints(
            aggregated.get("duration_total_ms"),
            _nonnegative_int(summary.get("duration_total_ms")),
        )
        for key in _TOKEN_KEYS:
            aggregated[key] = _sum_optional_ints(
                aggregated.get(key),
                _nonnegative_int(summary.get(key)),
            )
    if not found:
        return None

    return {
        "stage": stage_name,
        "kind": "live_telemetry",
        **aggregated,
    }
