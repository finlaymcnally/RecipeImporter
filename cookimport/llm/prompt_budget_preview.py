from __future__ import annotations
import functools
import json
from pathlib import Path
from typing import Any, Mapping
import tiktoken
from cookimport.llm.codex_exec_runner import summarize_direct_telemetry_rows
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from cookimport.llm.shard_survivability import evaluate_stage_survivability
from cookimport.runs.stage_names import canonical_stage_key, stage_label
from cookimport.runs.stage_observability import (
    build_knowledge_stage_summary,
    build_line_role_stage_summary as build_stage_observability_line_role_summary,
    build_recipe_stage_summary,
)
from .prompt_budget_runtime import (
    _nonnegative_float,
    _nonnegative_int,
    _rows_for_stage,
    _sum_optional_ints,
)
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
_PATHOLOGY_KEYS = (
    "preflight_rejected_shard_count",
    "watchdog_killed_shard_count",
    "watchdog_recovered_shard_count",
    "command_execution_count_total",
    "command_executing_shard_count",
    "command_execution_tokens_total",
    "reasoning_item_count_total",
    "reasoning_heavy_shard_count",
    "reasoning_heavy_tokens_total",
    "invalid_output_shard_count",
    "invalid_output_tokens_total",
    "repaired_shard_count",
    "pathological_shard_count",
)
_STATUS_COUNT_KEYS = (
    "validated_shard_count",
    "invalid_shard_count",
    "no_final_output_shard_count",
    "missing_output_shard_count",
)
_EXECUTION_MODE_COUNT_KEYS = (
    "taskfile_session_count",
    "structured_followup_call_count",
    "structured_followup_tokens_total",
)
_PREVIEW_STAGE_LABELS = {
    "recipe_refine": stage_label("recipe_refine"),
    "nonrecipe_finalize": stage_label("nonrecipe_finalize"),
    "line_role": stage_label("line_role"),
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
        survivability_report = _build_preview_stage_survivability(
            stage_key=stage_key,
            stage_rows=_rows_for_stage(prompt_rows=prompt_rows, stage_key=stage_key),
            phase_plan=(phase_plans or {}).get(stage_key)
            if isinstance(phase_plans, Mapping)
            else None,
        )
        if survivability_report is not None:
            payload["survivability"] = survivability_report
            payload["minimum_safe_shard_count"] = int(
                survivability_report.get("minimum_safe_shard_count") or 1
            )
            payload["binding_limit"] = survivability_report.get("binding_limit")
            payload["survivability_verdict"] = survivability_report.get(
                "survivability_verdict"
            )
            worst_shard = survivability_report.get("worst_shard")
            if isinstance(worst_shard, Mapping):
                payload["worst_shard_id"] = str(worst_shard.get("shard_id") or "")
                payload["estimated_peak_session_tokens"] = _nonnegative_int(
                    worst_shard.get("estimated_peak_session_tokens")
                )
                payload["estimated_followup_tokens"] = _nonnegative_int(
                    worst_shard.get("estimated_followup_tokens")
                )
                payload["estimated_input_tokens_max"] = _nonnegative_int(
                    worst_shard.get("estimated_input_tokens")
                )
                payload["estimated_output_tokens_max"] = _nonnegative_int(
                    worst_shard.get("estimated_output_tokens")
                )
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
        "schema_version": "prompt_preview_budget_summary.v6",
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
def _build_preview_stage_survivability(
    *,
    stage_key: str,
    stage_rows: list[Mapping[str, Any]],
    phase_plan: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not stage_rows:
        return None
    shard_estimates: list[dict[str, Any]] = []
    shard_rows = {
        str(row.get("runtime_shard_id") or row.get("call_id") or ""): row
        for row in stage_rows
    }
    if isinstance(phase_plan, Mapping) and isinstance(phase_plan.get("shards"), list):
        plan_shards = phase_plan.get("shards") or []
    else:
        plan_shards = []
    if not plan_shards:
        plan_shards = [
            {
                "shard_id": str(row.get("runtime_shard_id") or row.get("call_id") or ""),
                "owned_ids": list(row.get("runtime_owned_ids") or []),
            }
            for row in stage_rows
        ]
    for shard in plan_shards:
        if not isinstance(shard, Mapping):
            continue
        shard_id = str(shard.get("shard_id") or "").strip()
        row = shard_rows.get(shard_id)
        if row is None:
            call_ids = shard.get("call_ids")
            if isinstance(call_ids, list):
                for call_id in call_ids:
                    row = next(
                        (
                            candidate
                            for candidate in stage_rows
                            if str(candidate.get("call_id") or "") == str(call_id)
                        ),
                        None,
                    )
                    if row is not None:
                        break
        if row is None:
            continue
        estimated_input_tokens = _count_structural_input_tokens(row)
        estimated_output_tokens = _count_structural_output_tokens(row)
        if estimated_input_tokens is None or estimated_output_tokens is None:
            return None
        shard_estimates.append(
            {
                "shard_id": shard_id or str(row.get("call_id") or ""),
                "owned_unit_count": len(list(shard.get("owned_ids") or [])),
                "estimated_input_tokens": estimated_input_tokens,
                "estimated_output_tokens": estimated_output_tokens,
                "metadata": {
                    "call_id": str(row.get("call_id") or ""),
                },
            }
        )
    if not shard_estimates:
        return None
    requested_shard_count = (
        _nonnegative_int(phase_plan.get("shard_count"))
        if isinstance(phase_plan, Mapping)
        else None
    ) or len(shard_estimates)
    return evaluate_stage_survivability(
        stage_key=stage_key,
        shard_estimates=shard_estimates,
        requested_shard_count=requested_shard_count,
        stage_label_override=_PREVIEW_STAGE_LABELS.get(
            stage_key,
            stage_key.replace("_", " ").title(),
        ),
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
def _count_tokens_cached(model_name: str, text: str) -> int:
    return len(_encoding_for_model(model_name).encode(text))
def _chunk_tokenization_text(text: str, *, chunk_size: int = 50_000) -> tuple[str, ...]:
    if len(text) <= chunk_size:
        return (text,)
    return tuple(
        text[index : index + chunk_size]
        for index in range(0, len(text), chunk_size)
    )
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

    recipe_stage = by_stage.get("recipe_refine")
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

    knowledge_stage = by_stage.get("nonrecipe_finalize")
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
    for stage_key, payload in by_stage.items():
        if not isinstance(payload, Mapping):
            continue
        minimum_safe_shard_count = _nonnegative_int(payload.get("minimum_safe_shard_count"))
        current_shard_count = _nonnegative_int(payload.get("shard_count"))
        if (
            minimum_safe_shard_count is None
            or current_shard_count is None
            or minimum_safe_shard_count <= current_shard_count
        ):
            continue
        warnings.append(
            {
                "severity": "danger",
                "code": "unsafe_shard_count",
                "stage": stage_key,
                "message": (
                    f"{payload.get('stage_label') or stage_key} is planned for {current_shard_count} shard(s), "
                    f"but the deterministic safe floor is {minimum_safe_shard_count}. "
                    f"Binding limit: {payload.get('binding_limit') or 'unknown'}."
                ),
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
        "| Stage | Basis | Workers | Shards | Min Safe | Binding | Interactions | Owned IDs / Shard | Peak / Shard | Est. Total Tokens | Range |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |")
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
                + f"{int(_nonnegative_int(payload.get('minimum_safe_shard_count')) or 0):,} | "
                + f"{str(payload.get('binding_limit') or 'unavailable')} | "
                + f"{int(_nonnegative_int(payload.get('interaction_count')) or _nonnegative_int(payload.get('call_count')) or 0):,} | "
                + f"{float(owned_ids_per_shard.get('avg') or 0.0):.2f} | "
                + (
                    f"{int(_nonnegative_int(payload.get('estimated_peak_session_tokens'))):,}"
                    if _nonnegative_int(payload.get('estimated_peak_session_tokens')) is not None
                    else "unavailable"
                )
                + " | "
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
        "| Stage | Basis | Task Chars | Wrapped Chars | Overhead Chars | Est. Input Tokens | Est. Output Tokens | Est. Followup Tokens |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
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
                + " | "
                + (
                    f"{int(_nonnegative_int(payload.get('estimated_output_tokens'))):,}"
                    if _nonnegative_int(payload.get('estimated_output_tokens')) is not None
                    else "unavailable"
                )
                + " | "
                + (
                    f"{int(_nonnegative_int(payload.get('estimated_followup_tokens'))):,}"
                    if _nonnegative_int(payload.get('estimated_followup_tokens')) is not None
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
