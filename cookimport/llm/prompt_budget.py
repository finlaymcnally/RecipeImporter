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

_PREVIEW_STAGE_LABELS = {
    "recipe_llm_correct_and_link": "Recipe Correction",
    "extract_knowledge_optional": "Knowledge Harvest",
    "line_role": "Line Role",
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
