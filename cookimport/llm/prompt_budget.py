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

_PREVIEW_INPUT_CHARS_PER_TOKEN = 3.2
_PREVIEW_STAGE_OUTPUT_RATIO = {
    "recipe_llm_correct_and_link": 0.18,
    "extract_knowledge_optional": 0.12,
    "line_role": 0.20,
}
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
    for row in prompt_rows:
        stage_key = str(row.get("stage_key") or "").strip()
        if not stage_key:
            stage_key = "unknown"
        rendered_prompt_text = str(row.get("rendered_prompt_text") or "")
        prompt_chars = len(rendered_prompt_text)
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
                "transport_overhead_chars_total": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_total_tokens": 0,
            },
        )
        task_prompt_text = str(row.get("task_prompt_text") or rendered_prompt_text)
        task_prompt_chars = len(task_prompt_text)
        stage_payload["call_count"] += 1
        stage_payload["task_prompt_chars_total"] += task_prompt_chars
        stage_payload["prompt_chars_total"] += prompt_chars
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
        "transport_overhead_chars_total": 0,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "estimated_total_tokens": 0,
    }
    for stage_key, payload in by_stage.items():
        call_count = int(payload.get("call_count") or 0)
        task_prompt_chars_total = int(payload.get("task_prompt_chars_total") or 0)
        prompt_chars_total = int(payload.get("prompt_chars_total") or 0)
        estimated_input_tokens = _estimate_preview_input_tokens(prompt_chars_total)
        estimated_output_tokens = _estimate_preview_output_tokens(
            stage_key=stage_key,
            call_count=call_count,
            estimated_input_tokens=estimated_input_tokens,
        )
        payload["task_prompt_chars_avg"] = (
            int(round(task_prompt_chars_total / call_count)) if call_count > 0 else 0
        )
        payload["prompt_chars_avg"] = int(round(prompt_chars_total / call_count)) if call_count > 0 else 0
        payload["estimated_input_tokens"] = estimated_input_tokens
        payload["estimated_output_tokens"] = estimated_output_tokens
        payload["estimated_total_tokens"] = estimated_input_tokens + estimated_output_tokens
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
        totals["transport_overhead_chars_total"] += int(
            payload.get("transport_overhead_chars_total") or 0
        )
        totals["estimated_input_tokens"] += estimated_input_tokens
        totals["estimated_output_tokens"] += estimated_output_tokens
        totals["estimated_total_tokens"] += estimated_input_tokens + estimated_output_tokens
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
        "schema_version": "prompt_preview_budget_summary.v2",
        "preview_dir": str(preview_dir),
        "estimation_method": {
            "type": "heuristic_char_based",
            "estimated_input_chars_per_token": _PREVIEW_INPUT_CHARS_PER_TOKEN,
            "notes": [
                "Estimated tokens are derived from rendered prompt text length because preview runs do not have live tokenizer telemetry.",
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
    if call_count is None and row_count > 0:
        call_count = row_count
    duration_total_ms = (
        _extract_duration_total_ms(summary_payload, call_count=call_count)
        if isinstance(summary_payload, Mapping)
        else None
    )

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
    process_payload = stage_payload.get("process_payload")
    if isinstance(process_payload, Mapping):
        telemetry = process_payload.get("telemetry")
        if isinstance(telemetry, Mapping) and isinstance(telemetry.get("rows"), list):
            return telemetry.get("rows")
    telemetry = stage_payload.get("telemetry")
    if isinstance(telemetry, Mapping) and isinstance(telemetry.get("rows"), list):
        return telemetry.get("rows")
    return None


def _build_line_role_stage_summary(
    *,
    pred_manifest: Mapping[str, Any],
    pred_run_dir: Path,
) -> dict[str, Any] | None:
    telemetry_path = _resolve_line_role_telemetry_path(
        pred_manifest=pred_manifest,
        pred_run_dir=pred_run_dir,
    )
    if telemetry_path is None:
        return None
    try:
        payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, Mapping):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return None

    call_count = _nonnegative_int(summary.get("call_count"))
    batch_count = _nonnegative_int(summary.get("batch_count"))
    if call_count is None:
        call_count = batch_count

    token_totals = {
        key: _nonnegative_int(summary.get(key))
        for key in _TOKEN_KEYS
    }
    if (
        call_count is None
        and _nonnegative_int(summary.get("duration_total_ms")) is None
        and all(value is None for value in token_totals.values())
    ):
        return None

    return {
        "stage": "line_role",
        "kind": "line_role",
        "call_count": call_count,
        "batch_count": batch_count,
        "attempt_count": _nonnegative_int(summary.get("attempt_count")),
        "duration_total_ms": _nonnegative_int(summary.get("duration_total_ms")),
        **token_totals,
    }


def _resolve_line_role_telemetry_path(
    *,
    pred_manifest: Mapping[str, Any],
    pred_run_dir: Path,
) -> Path | None:
    raw_path = str(pred_manifest.get("line_role_pipeline_telemetry_path") or "").strip()
    candidates: list[Path] = []
    if raw_path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = pred_run_dir / candidate
        candidates.append(candidate)
    candidates.append(pred_run_dir / "line-role-pipeline" / "telemetry_summary.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _extract_summary_payload(*, stage_payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    process_payload = stage_payload.get("process_payload")
    if isinstance(process_payload, Mapping):
        telemetry_report = process_payload.get("telemetry_report")
        if isinstance(telemetry_report, Mapping) and isinstance(
            telemetry_report.get("summary"), Mapping
        ):
            return telemetry_report.get("summary")
    telemetry_report = stage_payload.get("telemetry_report")
    if isinstance(telemetry_report, Mapping) and isinstance(
        telemetry_report.get("summary"), Mapping
    ):
        return telemetry_report.get("summary")
    return None


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


def _estimate_preview_input_tokens(prompt_chars_total: int) -> int:
    if prompt_chars_total <= 0:
        return 0
    return int(round(prompt_chars_total / _PREVIEW_INPUT_CHARS_PER_TOKEN))


def _estimate_preview_output_tokens(
    *,
    stage_key: str,
    call_count: int,
    estimated_input_tokens: int,
) -> int:
    if call_count <= 0 or estimated_input_tokens <= 0:
        return 0
    ratio = _PREVIEW_STAGE_OUTPUT_RATIO.get(stage_key, 0.10)
    return int(round(estimated_input_tokens * ratio))


def _build_prompt_preview_budget_warnings(
    *,
    by_stage: Mapping[str, Mapping[str, Any]],
    totals: Mapping[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []

    total_calls = _nonnegative_int(totals.get("call_count")) or 0
    total_prompt_chars = _nonnegative_int(totals.get("prompt_chars_total")) or 0
    total_estimated_tokens = _nonnegative_int(totals.get("estimated_total_tokens")) or 0
    if total_calls >= 200 or total_prompt_chars >= 1_500_000 or total_estimated_tokens >= 500_000:
        warnings.append(
            {
                "severity": "danger",
                "code": "extreme_prompt_budget",
                "message": (
                    f"EXTREME prompt budget: {total_calls} calls, {total_prompt_chars:,} rendered prompt chars, "
                    f"~{total_estimated_tokens:,} estimated total tokens. Treat this as a multi-million-token danger zone."
                ),
            }
        )
    elif total_calls >= 100 or total_prompt_chars >= 750_000 or total_estimated_tokens >= 250_000:
        warnings.append(
            {
                "severity": "warning",
                "code": "high_prompt_budget",
                "message": (
                    f"High prompt budget: {total_calls} calls, {total_prompt_chars:,} rendered prompt chars, "
                    f"~{total_estimated_tokens:,} estimated total tokens."
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
    lines = [
        "# Prompt Preview Budget Summary",
        "",
        f"- Preview dir: `{summary.get('preview_dir')}`",
        (
            f"- Estimated total tokens: `~{int(_nonnegative_int(totals.get('estimated_total_tokens')) or 0):,}` "
            "(heuristic)"
        ),
        f"- Total interactions: `{int(_nonnegative_int(totals.get('call_count')) or 0):,}`",
        f"- Task prompt chars: `{int(_nonnegative_int(totals.get('task_prompt_chars_total')) or 0):,}`",
        f"- Rendered prompt chars: `{int(_nonnegative_int(totals.get('prompt_chars_total')) or 0):,}`",
        (
            f"- Transport overhead chars: "
            f"`{int(_nonnegative_int(totals.get('transport_overhead_chars_total')) or 0):,}`"
        ),
        "",
    ]
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
        "| Stage | Workers | Shards | Interactions | Owned IDs / Shard | First-Turn Chars / Shard | Est. Total Tokens |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
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
                + f"{int(_nonnegative_int(payload.get('worker_count')) or 0):,} | "
                + f"{int(_nonnegative_int(payload.get('shard_count')) or 0):,} | "
                + f"{int(_nonnegative_int(payload.get('interaction_count')) or _nonnegative_int(payload.get('call_count')) or 0):,} | "
                + f"{float(owned_ids_per_shard.get('avg') or 0.0):.2f} | "
                + f"{float(first_turn_chars.get('avg') or 0.0):.1f} | "
                + f"{int(_nonnegative_int(payload.get('estimated_total_tokens')) or 0):,} |"
            )
    lines.append("")
    lines.append("## Prompt Detail")
    lines.append("")
    lines.append(
        "| Stage | Task Chars | Wrapped Chars | Overhead Chars | Est. Input Tokens |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    if isinstance(by_stage, Mapping):
        for stage_key, payload in by_stage.items():
            if not isinstance(payload, Mapping):
                continue
            lines.append(
                "| "
                + f"{str(payload.get('stage_label') or stage_key)} | "
                + f"{int(_nonnegative_int(payload.get('task_prompt_chars_total')) or 0):,} | "
                + f"{int(_nonnegative_int(payload.get('prompt_chars_total')) or 0):,} | "
                + f"{int(_nonnegative_int(payload.get('transport_overhead_chars_total')) or 0):,} | "
                + f"{int(_nonnegative_int(payload.get('estimated_input_tokens')) or 0):,} |"
            )
    lines.append("")
    lines.append(
        "_Estimated tokens are derived from rendered prompt text length because preview runs do not have live tokenizer telemetry._"
    )
    return "\n".join(lines) + "\n"
