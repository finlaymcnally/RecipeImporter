from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Mapping

import tiktoken

from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output

_TOKEN_KEYS = (
    "tokens_input",
    "tokens_cached_input",
    "tokens_output",
    "tokens_reasoning",
    "tokens_total",
)
_BREAKDOWN_KEYS = (
    "visible_input_tokens",
    "visible_output_tokens",
    "wrapper_overhead_tokens",
)

_PREVIEW_STAGE_LABELS = {
    "recipe_llm_correct_and_link": "Recipe Correction",
    "extract_knowledge_optional": "Non-Recipe Knowledge Review",
    "line_role": "Line Role",
}

_SURFACE_CONFIG_BY_KEY = {
    "recipe": {
        "prompt_target_key": "recipe_prompt_target_count",
        "worker_key": "recipe_worker_count",
    },
    "knowledge": {
        "prompt_target_key": "knowledge_prompt_target_count",
        "worker_key": "knowledge_worker_count",
    },
    "line_role": {
        "prompt_target_key": "line_role_prompt_target_count",
        "worker_key": "line_role_worker_count",
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

    run_count_summary: dict[str, dict[str, Any]] = {}
    run_count_deviations: list[dict[str, Any]] = []
    for stage_name, stage_payload in by_stage.items():
        if not isinstance(stage_payload, dict):
            continue
        run_count_payload = _build_stage_run_count_summary(
            stage_key=stage_name,
            stage_payload=stage_payload,
            pred_manifest=pred_manifest,
        )
        if run_count_payload is None:
            continue
        stage_payload.update(run_count_payload)
        run_count_summary[stage_name] = {
            key: stage_payload.get(key)
            for key in (
                "stage",
                "stage_label",
                "requested_run_count",
                "actual_run_count",
                "run_count_status",
                "run_count_explanation",
                "requested_worker_count",
                "actual_worker_count",
                "call_count",
                "internal_phase_count",
                "internal_phase_run_counts",
            )
            if key in stage_payload
        }
        if str(stage_payload.get("run_count_status") or "").strip() in {
            "below_target",
            "above_target",
            "unavailable",
        }:
            run_count_deviations.append(dict(run_count_summary[stage_name]))

    totals: dict[str, int | None] = {
        "call_count": None,
        "duration_total_ms": None,
        **{key: None for key in _TOKEN_KEYS},
        **{key: None for key in _BREAKDOWN_KEYS},
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
        for key in _BREAKDOWN_KEYS:
            totals[key] = _sum_optional_ints(
                totals.get(key),
                _nonnegative_int(payload.get(key)),
            )
    totals["cost_breakdown"] = {
        "visible_input_tokens": totals.get("visible_input_tokens"),
        "cached_input_tokens": totals.get("tokens_cached_input"),
        "visible_output_tokens": totals.get("visible_output_tokens"),
        "wrapper_overhead_tokens": totals.get("wrapper_overhead_tokens"),
        "reasoning_tokens": totals.get("tokens_reasoning"),
        "billed_total_tokens": totals.get("tokens_total"),
    }

    return {
        "schema_version": "prompt_budget_summary.v1",
        "prediction_run_dir": str(pred_run_dir),
        "by_stage": by_stage,
        "run_count_summary": run_count_summary,
        "run_count_deviations": run_count_deviations,
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
) -> dict[str, Any]:
    by_stage: dict[str, dict[str, Any]] = {}
    structural_estimate_used = False
    unavailable_stage_count = 0
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
                "visible_input_tokens": None,
                "visible_output_tokens": None,
                "wrapper_overhead_tokens": None,
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
        "visible_input_tokens": None,
        "visible_output_tokens": None,
        "wrapper_overhead_tokens": None,
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
        (
            estimated_input_tokens,
            estimated_cached_input_tokens,
            estimated_output_tokens,
            estimated_total_tokens,
            structural_payload,
        ) = _build_structural_stage_estimate(
            stage_rows=_rows_for_stage(prompt_rows=prompt_rows, stage_key=stage_key),
        )
        if structural_payload is not None:
            structural_estimate_used = True
            payload["estimation_basis"] = "structural_prompt_tokenization"
            payload["structural_token_estimate"] = structural_payload
            payload["estimated_total_tokens_low"] = _nonnegative_int(
                structural_payload.get("estimated_total_tokens_low")
            )
            payload["estimated_total_tokens_high"] = _nonnegative_int(
                structural_payload.get("estimated_total_tokens_high")
            )
        else:
            payload["estimation_basis"] = "unavailable"
        payload["estimated_input_tokens"] = estimated_input_tokens
        payload["estimated_cached_input_tokens"] = estimated_cached_input_tokens
        payload["estimated_output_tokens"] = estimated_output_tokens
        payload["estimated_total_tokens"] = estimated_total_tokens
        payload["visible_input_tokens"] = estimated_input_tokens
        payload["visible_output_tokens"] = estimated_output_tokens
        payload["wrapper_overhead_tokens"] = 0 if estimated_total_tokens is not None else None
        payload["cost_breakdown"] = {
            "visible_input_tokens": payload.get("visible_input_tokens"),
            "cached_input_tokens": payload.get("estimated_cached_input_tokens"),
            "visible_output_tokens": payload.get("visible_output_tokens"),
            "wrapper_overhead_tokens": payload.get("wrapper_overhead_tokens"),
            "reasoning_tokens": 0,
            "billed_total_tokens": estimated_total_tokens,
        }
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
        totals["visible_input_tokens"] = _sum_optional_ints(
            totals.get("visible_input_tokens"),
            estimated_input_tokens,
        )
        totals["visible_output_tokens"] = _sum_optional_ints(
            totals.get("visible_output_tokens"),
            estimated_output_tokens,
        )
        totals["wrapper_overhead_tokens"] = _sum_optional_ints(
            totals.get("wrapper_overhead_tokens"),
            0 if estimated_total_tokens is not None else None,
        )
    if totals["call_count"] > 0:
        totals["task_prompt_chars_avg"] = int(
            round(totals["task_prompt_chars_total"] / totals["call_count"])
        )
        totals["prompt_chars_avg"] = int(round(totals["prompt_chars_total"] / totals["call_count"]))
    totals["cost_breakdown"] = {
        "visible_input_tokens": totals.get("visible_input_tokens"),
        "cached_input_tokens": totals.get("estimated_cached_input_tokens"),
        "visible_output_tokens": totals.get("visible_output_tokens"),
        "wrapper_overhead_tokens": totals.get("wrapper_overhead_tokens"),
        "reasoning_tokens": 0,
        "billed_total_tokens": totals.get("estimated_total_tokens"),
    }

    warnings = _build_prompt_preview_budget_warnings(
        by_stage=by_stage,
        totals=totals,
    )

    return {
        "schema_version": "prompt_preview_budget_summary.v5",
        "preview_dir": str(preview_dir),
        "estimation_method": {
            "type": (
                "structural_prompt_tokenization"
                if structural_estimate_used
                else "no_token_estimate_available"
            ),
            "mode": "predictive",
            "unavailable_stage_count": unavailable_stage_count,
            "notes": [
                (
                    "Predictive estimates tokenize the locally reconstructed wrapper prompt text plus deposited task-file text for each planned shard."
                ),
                "Predictive output tokens are structural best guesses derived from the planned shard inputs and repo-owned fake pipeline output builders.",
                "Predictive preview assumes zero cached-input reuse before a live run.",
                "Stages without reconstructable prompt or output structure are reported as unavailable instead of guessed from prompt text length.",
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
    preview_dir.mkdir(parents=True, exist_ok=True)
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
    breakdown_totals: dict[str, int | None] = {key: None for key in _BREAKDOWN_KEYS}
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
            for key in _BREAKDOWN_KEYS:
                breakdown_totals[key] = _sum_optional_ints(
                    breakdown_totals.get(key),
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
        for key in _BREAKDOWN_KEYS:
            if breakdown_totals.get(key) is None:
                breakdown_totals[key] = _nonnegative_int(summary_payload.get(key))

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

    worker_count, shard_count = _extract_runtime_worker_and_shard_counts(stage_payload)

    return {
        "stage": stage_name,
        "kind": "codex_farm",
        "call_count": call_count,
        "duration_total_ms": duration_total_ms,
        "worker_count": worker_count,
        "shard_count": shard_count,
        **token_totals,
        **breakdown_totals,
        "cost_breakdown": {
            "visible_input_tokens": breakdown_totals.get("visible_input_tokens"),
            "cached_input_tokens": token_totals.get("tokens_cached_input"),
            "visible_output_tokens": breakdown_totals.get("visible_output_tokens"),
            "wrapper_overhead_tokens": breakdown_totals.get("wrapper_overhead_tokens"),
            "reasoning_tokens": token_totals.get("tokens_reasoning"),
            "billed_total_tokens": token_totals.get("tokens_total"),
        },
    }


def _extract_telemetry_rows(*, stage_payload: Mapping[str, Any]) -> list[Any] | None:
    direct_telemetry = stage_payload.get("telemetry")
    if isinstance(direct_telemetry, Mapping) and isinstance(direct_telemetry.get("rows"), list):
        return list(direct_telemetry.get("rows") or [])

    process_run = stage_payload.get("process_run")
    if isinstance(process_run, Mapping):
        process_run_rows = _extract_telemetry_rows(stage_payload=process_run)
        if process_run_rows:
            return process_run_rows

    process_payload = stage_payload.get("process_payload")
    if isinstance(process_payload, Mapping):
        process_payload_rows = _extract_telemetry_rows(stage_payload=process_payload)
        if process_payload_rows:
            return process_payload_rows

    for runtime_key in ("phase_runtime", "phase_worker_runtime"):
        runtime_payload = stage_payload.get(runtime_key)
        if not isinstance(runtime_payload, Mapping):
            continue
        runtime_telemetry = runtime_payload.get("telemetry")
        if isinstance(runtime_telemetry, Mapping) and isinstance(runtime_telemetry.get("rows"), list):
            return list(runtime_telemetry.get("rows") or [])

    rows: list[Any] = []
    _collect_telemetry_rows_from_worker_children(stage_payload, rows)
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
                summary = None

        direct_token_totals = (
            {
                key: _nonnegative_int(summary.get(key))
                for key in _TOKEN_KEYS
            }
            if isinstance(summary, Mapping)
            else {key: None for key in _TOKEN_KEYS}
        )
        nested_summaries = _collect_line_role_attempt_summaries(payload)
        fallback_token_totals = _aggregate_token_totals_from_summaries(
            [
                item
                for item in nested_summaries
                if not isinstance(summary, Mapping) or item is not summary
            ]
        )
        token_totals = {
            key: (
                direct_token_totals.get(key)
                if direct_token_totals.get(key) is not None
                else fallback_token_totals.get(key)
            )
            for key in _TOKEN_KEYS
        }
        breakdown_totals = {
            key: _nonnegative_int(summary.get(key)) if isinstance(summary, Mapping) else None
            for key in _BREAKDOWN_KEYS
        }

        call_count = _nonnegative_int(summary.get("call_count")) if isinstance(summary, Mapping) else None
        batch_count = _nonnegative_int(summary.get("batch_count")) if isinstance(summary, Mapping) else None
        attempt_count = _nonnegative_int(summary.get("attempt_count")) if isinstance(summary, Mapping) else None
        if call_count is None:
            call_count = batch_count
        if call_count is None:
            call_count = _aggregate_call_count_from_summaries(nested_summaries)
        if attempt_count is None:
            attempt_count = call_count

        duration_total_ms = (
            _nonnegative_int(summary.get("duration_total_ms"))
            if isinstance(summary, Mapping)
            else None
        )
        if duration_total_ms is None:
            duration_total_ms = _aggregate_duration_total_ms_from_summaries(nested_summaries)
        if (
            call_count is None
            and duration_total_ms is None
            and all(value is None for value in token_totals.values())
        ):
            continue

        phase_rows = payload.get("phases")
        internal_phase_run_counts: dict[str, int] = {}
        internal_phase_worker_counts: dict[str, int] = {}
        if isinstance(phase_rows, list):
            for phase_payload in phase_rows:
                if not isinstance(phase_payload, Mapping):
                    continue
                phase_key = str(phase_payload.get("phase_key") or "").strip()
                if not phase_key:
                    continue
                phase_summary = phase_payload.get("summary")
                if not isinstance(phase_summary, Mapping):
                    phase_summary = {}
                phase_runtime_artifacts = phase_payload.get("runtime_artifacts")
                if not isinstance(phase_runtime_artifacts, Mapping):
                    phase_runtime_artifacts = {}
                phase_batch_count = _nonnegative_int(phase_summary.get("batch_count"))
                phase_worker_count = _nonnegative_int(
                    phase_runtime_artifacts.get("worker_count")
                )
                if phase_batch_count is not None:
                    internal_phase_run_counts[phase_key] = phase_batch_count
                if phase_worker_count is not None:
                    internal_phase_worker_counts[phase_key] = phase_worker_count
        surface_shard_count = _common_int_value(internal_phase_run_counts.values())
        surface_worker_count = _common_int_value(internal_phase_worker_counts.values())

        return {
            "stage": "line_role",
            "kind": "line_role",
            "call_count": call_count,
            "batch_count": batch_count,
            "attempt_count": attempt_count,
            "duration_total_ms": duration_total_ms,
            "worker_count": surface_worker_count,
            "shard_count": surface_shard_count,
            "internal_phase_count": len(internal_phase_run_counts),
            "internal_phase_run_counts": (
                dict(sorted(internal_phase_run_counts.items()))
                if internal_phase_run_counts
                else None
            ),
            "internal_phase_worker_counts": (
                dict(sorted(internal_phase_worker_counts.items()))
                if internal_phase_worker_counts
                else None
            ),
            "prompt_input_mode": (
                str(summary.get("prompt_input_mode") or "").strip()
                if isinstance(summary, Mapping)
                else None
            )
            or "path",
            "request_input_file_bytes_total": (
                _nonnegative_int(summary.get("request_input_file_bytes_total"))
                if isinstance(summary, Mapping)
                else None
            ),
            **token_totals,
            **breakdown_totals,
            "cost_breakdown": {
                "visible_input_tokens": breakdown_totals.get("visible_input_tokens"),
                "cached_input_tokens": token_totals.get("tokens_cached_input"),
                "visible_output_tokens": breakdown_totals.get("visible_output_tokens"),
                "wrapper_overhead_tokens": breakdown_totals.get("wrapper_overhead_tokens"),
                "reasoning_tokens": token_totals.get("tokens_reasoning"),
                "billed_total_tokens": token_totals.get("tokens_total"),
            },
        }
    return None


def _prediction_run_config(pred_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    run_config = pred_manifest.get("run_config")
    if not isinstance(run_config, Mapping):
        return {}
    nested_prediction_config = run_config.get("prediction_run_config")
    if isinstance(nested_prediction_config, Mapping):
        return nested_prediction_config
    return run_config


def _surface_key_for_stage(stage_key: str) -> str | None:
    normalized = str(stage_key or "").strip()
    if normalized in {"recipe_correction", "recipe_llm_correct_and_link"}:
        return "recipe"
    if normalized in {"knowledge", "extract_knowledge_optional"}:
        return "knowledge"
    if normalized == "line_role" or normalized.startswith("line_role_"):
        return "line_role"
    return None


def _stage_requested_counts(
    *,
    stage_key: str,
    pred_manifest: Mapping[str, Any],
) -> tuple[int | None, int | None]:
    surface_key = _surface_key_for_stage(stage_key)
    if surface_key is None:
        return None, None
    surface_config = _SURFACE_CONFIG_BY_KEY.get(surface_key) or {}
    run_config = _prediction_run_config(pred_manifest)
    requested_run_count = _nonnegative_int(
        run_config.get(surface_config.get("prompt_target_key", ""))
    )
    requested_worker_count = _nonnegative_int(
        run_config.get(surface_config.get("worker_key", ""))
    )
    return requested_run_count, requested_worker_count


def _extract_runtime_worker_and_shard_counts(
    stage_payload: Mapping[str, Any],
) -> tuple[int | None, int | None]:
    priority_paths = (
        (),
        ("phase_worker_runtime",),
        ("phase_runtime",),
        ("phase_manifest",),
        ("process_run", "phase_manifest"),
        ("telemetry_report",),
        ("process_run", "telemetry_report"),
        ("process_payload", "telemetry_report"),
    )
    worker_count: int | None = None
    shard_count: int | None = None
    for path in priority_paths:
        current: Any = stage_payload
        for segment in path:
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(segment)
        if not isinstance(current, Mapping):
            continue
        worker_count = worker_count if worker_count is not None else _nonnegative_int(
            current.get("worker_count")
        )
        shard_count = shard_count if shard_count is not None else _nonnegative_int(
            current.get("shard_count")
        )
        if worker_count is not None and shard_count is not None:
            break
    return worker_count, shard_count


def _common_int_value(values: Any) -> int | None:
    normalized = [int(value) for value in values if value is not None]
    if not normalized:
        return None
    first = normalized[0]
    if all(value == first for value in normalized):
        return first
    return None


def _build_stage_run_count_summary(
    *,
    stage_key: str,
    stage_payload: Mapping[str, Any],
    pred_manifest: Mapping[str, Any],
) -> dict[str, Any] | None:
    requested_run_count, requested_worker_count = _stage_requested_counts(
        stage_key=stage_key,
        pred_manifest=pred_manifest,
    )
    if requested_run_count is None and requested_worker_count is None:
        return None

    stage_label = str(stage_payload.get("stage_label") or stage_key.replace("_", " ").title())
    actual_worker_count = _nonnegative_int(stage_payload.get("worker_count"))
    actual_run_count = _nonnegative_int(stage_payload.get("shard_count"))
    call_count = _nonnegative_int(stage_payload.get("call_count"))
    internal_phase_count = _nonnegative_int(stage_payload.get("internal_phase_count"))
    internal_phase_run_counts = (
        dict(stage_payload.get("internal_phase_run_counts"))
        if isinstance(stage_payload.get("internal_phase_run_counts"), Mapping)
        else None
    )

    if actual_run_count is None and _surface_key_for_stage(stage_key) != "line_role":
        actual_run_count = call_count

    if requested_run_count is None:
        run_count_status = "unconfigured"
        explanation = (
            f"No prompt-target run count was configured for {stage_label} in this run config."
        )
    elif actual_run_count is None:
        run_count_status = "unavailable"
        explanation = (
            f"Requested {requested_run_count} run(s) for {stage_label}, but the finished artifacts "
            "do not expose a stable actual shard count."
        )
    elif actual_run_count == requested_run_count:
        run_count_status = "matched"
        explanation = (
            f"Requested {requested_run_count} run(s) and {stage_label} used {actual_run_count} shard(s)."
        )
    elif actual_run_count < requested_run_count:
        run_count_status = "below_target"
        explanation = (
            f"Requested {requested_run_count} run(s), but {stage_label} only used {actual_run_count} shard(s) "
            "because the available work fit into fewer shards."
        )
    else:
        run_count_status = "above_target"
        explanation = (
            f"Requested {requested_run_count} run(s), but {stage_label} used {actual_run_count} shard(s). "
            "This usually means a lower-level shard-sizing rule or planning seam split the work more than the prompt target alone."
        )

    if (
        requested_worker_count is not None
        and actual_worker_count is not None
        and requested_worker_count != actual_worker_count
    ):
        explanation += (
            f" Worker count also differed: requested {requested_worker_count}, actual {actual_worker_count}."
        )

    if _surface_key_for_stage(stage_key) == "line_role":
        if internal_phase_count is not None and internal_phase_count > 1 and call_count is not None:
            explanation += (
                f" Line-role runs {internal_phase_count} internal phases, so total model calls were {call_count}."
            )
        if internal_phase_run_counts:
            unique_phase_counts = sorted({int(value) for value in internal_phase_run_counts.values()})
            if len(unique_phase_counts) > 1:
                phase_bits = ", ".join(
                    f"{phase_key}={int(count)}"
                    for phase_key, count in sorted(internal_phase_run_counts.items())
                )
                explanation += f" Internal phase shard counts diverged: {phase_bits}."

    return {
        "stage_label": stage_label,
        "requested_run_count": requested_run_count,
        "actual_run_count": actual_run_count,
        "run_count_status": run_count_status,
        "run_count_explanation": explanation,
        "requested_worker_count": requested_worker_count,
        "actual_worker_count": actual_worker_count,
    }


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
    candidates = _preferred_summary_payloads(stage_payload)
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


def _collect_telemetry_rows_from_worker_children(payload: Mapping[str, Any], rows: list[Any]) -> None:
    worker_runs = payload.get("worker_runs")
    if isinstance(worker_runs, list):
        for worker_run in worker_runs:
            if isinstance(worker_run, Mapping):
                worker_rows = _extract_telemetry_rows(stage_payload=worker_run)
                if worker_rows:
                    rows.extend(worker_rows)

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
                worker_rows = _extract_telemetry_rows(stage_payload=runner_result)
                if worker_rows:
                    rows.extend(worker_rows)


def _collect_summary_payloads(
    payload: Mapping[str, Any],
    summaries: list[Mapping[str, Any]],
    seen: set[int] | None = None,
) -> None:
    if seen is None:
        seen = set()

    def _append_summary(summary_payload: Mapping[str, Any]) -> None:
        summary_id = id(summary_payload)
        if summary_id in seen:
            return
        seen.add(summary_id)
        summaries.append(summary_payload)

    process_payload = payload.get("process_payload")
    if isinstance(process_payload, Mapping):
        _collect_summary_payloads(process_payload, summaries, seen)

    process_run = payload.get("process_run")
    if isinstance(process_run, Mapping):
        _collect_summary_payloads(process_run, summaries, seen)

    telemetry_report = payload.get("telemetry_report")
    if isinstance(telemetry_report, Mapping):
        if isinstance(telemetry_report.get("summary"), Mapping):
            _append_summary(telemetry_report.get("summary"))
        elif _looks_like_summary_payload(telemetry_report):
            _append_summary(telemetry_report)

    telemetry = payload.get("telemetry")
    if isinstance(telemetry, Mapping) and isinstance(telemetry.get("summary"), Mapping):
        _append_summary(telemetry.get("summary"))

    worker_runs = payload.get("worker_runs")
    if isinstance(worker_runs, list):
        for worker_run in worker_runs:
            if isinstance(worker_run, Mapping):
                _collect_summary_payloads(worker_run, summaries, seen)

    for runtime_key in ("phase_runtime", "phase_worker_runtime"):
        runtime_payload = payload.get(runtime_key)
        if not isinstance(runtime_payload, Mapping):
            continue
        telemetry_payload = runtime_payload.get("telemetry")
        if isinstance(telemetry_payload, Mapping) and _looks_like_summary_payload(telemetry_payload):
            _append_summary(telemetry_payload)
        worker_reports = runtime_payload.get("worker_reports")
        if not isinstance(worker_reports, list):
            continue
        for report in worker_reports:
            if not isinstance(report, Mapping):
                continue
            runner_result = report.get("runner_result")
            if isinstance(runner_result, Mapping):
                _collect_summary_payloads(runner_result, summaries, seen)

    batches = payload.get("batches")
    if isinstance(batches, list):
        for batch in batches:
            if isinstance(batch, Mapping):
                _collect_summary_payloads(batch, summaries, seen)

    attempts = payload.get("attempts")
    if isinstance(attempts, list):
        for attempt in attempts:
            if isinstance(attempt, Mapping):
                _collect_summary_payloads(attempt, summaries, seen)


def _collect_line_role_attempt_summaries(
    payload: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    summaries: list[Mapping[str, Any]] = []
    batches = payload.get("batches")
    if not isinstance(batches, list):
        return summaries
    for batch in batches:
        if not isinstance(batch, Mapping):
            continue
        attempts = batch.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, Mapping):
                continue
            process_run = attempt.get("process_run")
            if isinstance(process_run, Mapping):
                process_payload = process_run.get("process_payload")
                if isinstance(process_payload, Mapping):
                    telemetry_report = process_payload.get("telemetry_report")
                    if (
                        isinstance(telemetry_report, Mapping)
                        and isinstance(telemetry_report.get("summary"), Mapping)
                    ):
                        summaries.append(telemetry_report.get("summary"))
                        continue
                telemetry_report = process_run.get("telemetry_report")
                if (
                    isinstance(telemetry_report, Mapping)
                    and isinstance(telemetry_report.get("summary"), Mapping)
                ):
                    summaries.append(telemetry_report.get("summary"))
                    continue
            telemetry_report = attempt.get("telemetry_report")
            if (
                isinstance(telemetry_report, Mapping)
                and isinstance(telemetry_report.get("summary"), Mapping)
            ):
                summaries.append(telemetry_report.get("summary"))
    return summaries


def _preferred_summary_payloads(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    summaries: list[Mapping[str, Any]] = []
    telemetry_report = payload.get("telemetry_report")
    if isinstance(telemetry_report, Mapping):
        if isinstance(telemetry_report.get("summary"), Mapping):
            summaries.append(telemetry_report.get("summary"))
        elif _looks_like_summary_payload(telemetry_report):
            summaries.append(telemetry_report)

    telemetry = payload.get("telemetry")
    if isinstance(telemetry, Mapping) and isinstance(telemetry.get("summary"), Mapping):
        summaries.append(telemetry.get("summary"))

    if summaries:
        return summaries

    process_run = payload.get("process_run")
    if isinstance(process_run, Mapping):
        process_run_summaries = _preferred_summary_payloads(process_run)
        if process_run_summaries:
            return process_run_summaries

    process_payload = payload.get("process_payload")
    if isinstance(process_payload, Mapping):
        process_payload_summaries = _preferred_summary_payloads(process_payload)
        if process_payload_summaries:
            return process_payload_summaries

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
                summaries.extend(_preferred_summary_payloads(runner_result))

    worker_runs = payload.get("worker_runs")
    if isinstance(worker_runs, list):
        for worker_run in worker_runs:
            if isinstance(worker_run, Mapping):
                summaries.extend(_preferred_summary_payloads(worker_run))
    return summaries


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


def _aggregate_token_totals_from_summaries(
    summaries: list[Mapping[str, Any]],
) -> dict[str, int | None]:
    totals: dict[str, int | None] = {key: None for key in _TOKEN_KEYS}
    for summary in summaries:
        for key in _TOKEN_KEYS:
            raw_value = summary.get(key)
            if key == "tokens_reasoning" and raw_value is None:
                raw_value = summary.get("tokens_reasoning_total")
            value = _nonnegative_int(raw_value)
            if value is None:
                continue
            totals[key] = _sum_optional_ints(totals.get(key), value)
    return totals


def _aggregate_call_count_from_summaries(
    summaries: list[Mapping[str, Any]],
) -> int | None:
    call_count: int | None = None
    for summary in summaries:
        call_count = _sum_optional_ints(call_count, _extract_call_count(summary))
    return call_count


def _aggregate_duration_total_ms_from_summaries(
    summaries: list[Mapping[str, Any]],
) -> int | None:
    duration_total_ms: int | None = None
    for summary in summaries:
        summary_call_count = _extract_call_count(summary)
        duration_total_ms = _sum_optional_ints(
            duration_total_ms,
            _extract_duration_total_ms(summary, call_count=summary_call_count),
        )
    return duration_total_ms


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


def _rows_for_stage(
    *,
    prompt_rows: list[Mapping[str, Any]],
    stage_key: str,
) -> list[Mapping[str, Any]]:
    return [
        row
        for row in prompt_rows
        if str(row.get("stage_key") or "").strip() == stage_key
    ]


def _build_structural_stage_estimate(
    *,
    stage_rows: list[Mapping[str, Any]],
) -> tuple[int | None, int | None, int | None, int | None, dict[str, Any] | None]:
    if not stage_rows:
        return None, None, None, None, None

    estimated_input_tokens = 0
    estimated_output_tokens = 0
    tokenizer_names: set[str] = set()
    pipeline_ids: set[str] = set()
    counted_rows = 0

    for row in stage_rows:
        row_input_tokens = _count_structural_input_tokens(row)
        row_output_tokens = _count_structural_output_tokens(row)
        if row_input_tokens is None or row_output_tokens is None:
            return None, None, None, None, None
        estimated_input_tokens += row_input_tokens
        estimated_output_tokens += row_output_tokens
        estimated_pipeline_id = str(row.get("pipeline_id") or "").strip()
        if estimated_pipeline_id:
            pipeline_ids.add(estimated_pipeline_id)
        tokenizer_names.add(_tokenizer_name_for_model(str(row.get("model") or "")))
        counted_rows += 1

    estimated_total_tokens = estimated_input_tokens + estimated_output_tokens
    structural_payload = {
        "row_count": counted_rows,
        "tokenizer_names": sorted(tokenizer_names),
        "pipeline_ids": sorted(pipeline_ids),
        "cached_input_assumption": "zero_pre_run",
        "estimated_total_tokens_low": estimated_total_tokens,
        "estimated_total_tokens_high": estimated_total_tokens,
    }
    return (
        estimated_input_tokens,
        0,
        estimated_output_tokens,
        estimated_total_tokens,
        structural_payload,
    )


def _count_structural_input_tokens(row: Mapping[str, Any]) -> int | None:
    rendered_prompt_text = str(row.get("rendered_prompt_text") or "")
    if not rendered_prompt_text:
        return None

    model_name = str(row.get("model") or "")
    prompt_input_mode = str(row.get("prompt_input_mode") or "path").strip().lower()
    total = _count_tokens(rendered_prompt_text, model_name=model_name)

    if prompt_input_mode == "path":
        task_prompt_text = str(
            row.get("task_prompt_text") or row.get("request_input_text") or ""
        )
        if not task_prompt_text:
            return None
        total += _count_tokens(task_prompt_text, model_name=model_name)
    return total


def _count_structural_output_tokens(row: Mapping[str, Any]) -> int | None:
    pipeline_id = str(row.get("pipeline_id") or "").strip()
    if not pipeline_id:
        return None
    request_input_payload = row.get("request_input_payload")
    if not isinstance(request_input_payload, dict | str):
        return None
    try:
        output_payload = build_structural_pipeline_output(
            pipeline_id,
            request_input_payload,
        )
    except Exception:  # noqa: BLE001
        return None
    compact_output = json.dumps(
        output_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _count_tokens(compact_output, model_name=str(row.get("model") or ""))


def _count_tokens(text: str, *, model_name: str) -> int:
    if not text:
        return 0
    if len(text) <= 100_000:
        return _count_tokens_cached(model_name, text)
    return sum(
        _count_tokens_cached(model_name, chunk)
        for chunk in _chunk_tokenization_text(text)
    )


@functools.lru_cache(maxsize=None)
def _count_tokens_cached(model_name: str, text: str) -> int:
    return len(_encoding_for_model(model_name).encode(text))


def _chunk_tokenization_text(text: str, *, chunk_size: int = 50_000) -> tuple[str, ...]:
    if len(text) <= chunk_size:
        return (text,)
    return tuple(
        text[index : index + chunk_size]
        for index in range(0, len(text), chunk_size)
    )


@functools.lru_cache(maxsize=None)
def _encoding_for_model(model_name: str):
    normalized_model = str(model_name or "").strip()
    if normalized_model:
        try:
            return tiktoken.encoding_for_model(normalized_model)
        except KeyError:
            pass
    return tiktoken.get_encoding("o200k_base")


def _tokenizer_name_for_model(model_name: str) -> str:
    return _encoding_for_model(model_name).name


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
                    + ". Preview only reports tokens when it can tokenize the reconstructed prompt inputs and build structural output estimates."
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
        "structural prompt tokenization"
        if estimation_type == "structural_prompt_tokenization"
        else "no estimate available"
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
    if estimation_type == "structural_prompt_tokenization":
        lines.append(
            "_Estimated tokens are predictive: they tokenize the locally reconstructed wrapper prompts plus deposited task files and use schema-shaped structural output guesses from the planned shard inputs. Predictive preview assumes zero cached-input reuse before the live run._"
        )
    else:
        lines.append(
            "_No predictive token estimate is shown because this preview could not reconstruct enough local prompt/output structure to ground the numbers._"
        )
    return "\n".join(lines) + "\n"
