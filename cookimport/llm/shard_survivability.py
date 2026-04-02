from __future__ import annotations

import functools
import json
from dataclasses import asdict, dataclass
from math import ceil
from typing import Any, Mapping, Sequence

import tiktoken

from cookimport.llm.codex_exec_runner import summarize_direct_telemetry_rows
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from cookimport.runs.stage_names import canonical_stage_key, stage_label


@dataclass(frozen=True, slots=True)
class StageSurvivabilityBudget:
    stage_key: str
    max_input_tokens: int
    max_output_tokens: int
    max_session_peak_tokens: int
    max_owned_units: int
    output_followup_multiplier: float = 0.0


@dataclass(frozen=True, slots=True)
class ShardSurvivabilityEstimate:
    stage_key: str
    shard_id: str
    owned_unit_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_followup_tokens: int
    estimated_peak_session_tokens: int
    verdict: str
    binding_limit: str | None
    metadata: dict[str, Any]


class ShardSurvivabilityPreflightError(RuntimeError):
    def __init__(self, report: Mapping[str, Any]) -> None:
        self.report = dict(report)
        super().__init__(format_shard_survivability_error(report))


_DEFAULT_STAGE_BUDGETS: dict[str, StageSurvivabilityBudget] = {
    "recipe_refine": StageSurvivabilityBudget(
        stage_key="recipe_refine",
        max_input_tokens=240_000,
        max_output_tokens=88_000,
        max_session_peak_tokens=320_000,
        max_owned_units=16,
        output_followup_multiplier=0.35,
    ),
    "nonrecipe_finalize": StageSurvivabilityBudget(
        stage_key="nonrecipe_finalize",
        max_input_tokens=220_000,
        max_output_tokens=80_000,
        max_session_peak_tokens=300_000,
        max_owned_units=80,
        output_followup_multiplier=1.0,
    ),
    "line_role": StageSurvivabilityBudget(
        stage_key="line_role",
        max_input_tokens=220_000,
        max_output_tokens=80_000,
        max_session_peak_tokens=300_000,
        max_owned_units=400,
        output_followup_multiplier=0.5,
    ),
}


def normalize_survivability_stage_key(stage_key: str) -> str:
    normalized = canonical_stage_key(stage_key)
    if normalized == "recipe_correction":
        return "recipe_refine"
    if normalized == "knowledge":
        return "nonrecipe_finalize"
    return normalized


def default_stage_survivability_budget(stage_key: str) -> StageSurvivabilityBudget:
    normalized = normalize_survivability_stage_key(stage_key)
    return _DEFAULT_STAGE_BUDGETS.get(
        normalized,
        StageSurvivabilityBudget(
            stage_key=normalized,
            max_input_tokens=220_000,
            max_output_tokens=80_000,
            max_session_peak_tokens=300_000,
            max_owned_units=256,
            output_followup_multiplier=0.5,
        ),
    )


def count_tokens_for_model(text: str, *, model_name: str = "") -> int:
    if not text:
        return 0
    if len(text) <= 100_000:
        return _count_tokens_cached(model_name, text)
    return sum(
        _count_tokens_cached(model_name, chunk)
        for chunk in _chunk_text(text)
    )


@functools.lru_cache(maxsize=None)
def _count_tokens_cached(model_name: str, text: str) -> int:
    return len(_encoding_for_model(model_name).encode(text))


def _chunk_text(text: str, *, chunk_size: int = 50_000) -> tuple[str, ...]:
    if len(text) <= chunk_size:
        return (text,)
    return tuple(text[index : index + chunk_size] for index in range(0, len(text), chunk_size))


@functools.lru_cache(maxsize=None)
def _encoding_for_model(model_name: str):
    normalized_model = str(model_name or "").strip()
    if normalized_model:
        try:
            return tiktoken.encoding_for_model(normalized_model)
        except KeyError:
            pass
    return tiktoken.get_encoding("o200k_base")


def count_structural_output_tokens(
    *,
    pipeline_id: str,
    input_payload: Mapping[str, Any] | str,
    model_name: str = "",
) -> int:
    output_payload = build_structural_pipeline_output(pipeline_id, input_payload)
    compact_output = json.dumps(
        output_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return count_tokens_for_model(compact_output, model_name=model_name)


def estimate_shard_survivability(
    *,
    stage_key: str,
    shard_id: str,
    owned_unit_count: int,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    estimated_followup_tokens: int | None = None,
    budget: StageSurvivabilityBudget | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_budget = budget or default_stage_survivability_budget(stage_key)
    normalized_stage_key = normalize_survivability_stage_key(stage_key)
    input_tokens = max(0, int(estimated_input_tokens))
    output_tokens = max(0, int(estimated_output_tokens))
    owned_units = max(0, int(owned_unit_count))
    followup_tokens = (
        max(0, int(estimated_followup_tokens))
        if estimated_followup_tokens is not None
        else int(ceil(output_tokens * float(resolved_budget.output_followup_multiplier)))
    )
    peak_session_tokens = input_tokens + output_tokens + followup_tokens
    pressure = {
        "input": _pressure_ratio(input_tokens, resolved_budget.max_input_tokens),
        "output": _pressure_ratio(output_tokens, resolved_budget.max_output_tokens),
        "session_peak": _pressure_ratio(
            peak_session_tokens,
            resolved_budget.max_session_peak_tokens,
        ),
        "owned_units": _pressure_ratio(owned_units, resolved_budget.max_owned_units),
    }
    binding_limit = _binding_limit_from_pressure(pressure)
    verdict = "safe"
    if any(
        (
            input_tokens > resolved_budget.max_input_tokens,
            output_tokens > resolved_budget.max_output_tokens,
            peak_session_tokens > resolved_budget.max_session_peak_tokens,
            owned_units > resolved_budget.max_owned_units,
        )
    ):
        verdict = "unsafe"
    estimate = ShardSurvivabilityEstimate(
        stage_key=normalized_stage_key,
        shard_id=str(shard_id).strip() or "unknown-shard",
        owned_unit_count=owned_units,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_followup_tokens=followup_tokens,
        estimated_peak_session_tokens=peak_session_tokens,
        verdict=verdict,
        binding_limit=binding_limit,
        metadata=dict(metadata or {}),
    )
    payload = asdict(estimate)
    payload["budget"] = asdict(resolved_budget)
    payload["pressure"] = pressure
    return payload


def evaluate_stage_survivability(
    *,
    stage_key: str,
    shard_estimates: Sequence[Mapping[str, Any]],
    requested_shard_count: int | None = None,
    stage_label_override: str | None = None,
    budget: StageSurvivabilityBudget | None = None,
) -> dict[str, Any]:
    normalized_stage_key = normalize_survivability_stage_key(stage_key)
    resolved_budget = budget or default_stage_survivability_budget(normalized_stage_key)
    normalized_estimates = [
        estimate_shard_survivability(
            stage_key=normalized_stage_key,
            shard_id=str(row.get("shard_id") or row.get("bundle_id") or "unknown-shard"),
            owned_unit_count=int(row.get("owned_unit_count") or 0),
            estimated_input_tokens=int(row.get("estimated_input_tokens") or 0),
            estimated_output_tokens=int(row.get("estimated_output_tokens") or 0),
            estimated_followup_tokens=(
                int(row["estimated_followup_tokens"])
                if row.get("estimated_followup_tokens") is not None
                else None
            ),
            budget=resolved_budget,
            metadata=row.get("metadata") if isinstance(row.get("metadata"), Mapping) else None,
        )
        for row in shard_estimates
    ]
    current_shard_count = len(normalized_estimates)
    effective_requested_shards = max(1, int(requested_shard_count or current_shard_count or 1))
    total_input_tokens = sum(int(row["estimated_input_tokens"]) for row in normalized_estimates)
    total_output_tokens = sum(int(row["estimated_output_tokens"]) for row in normalized_estimates)
    total_followup_tokens = sum(int(row["estimated_followup_tokens"]) for row in normalized_estimates)
    total_peak_session_tokens = sum(
        int(row["estimated_peak_session_tokens"]) for row in normalized_estimates
    )
    total_owned_units = sum(int(row["owned_unit_count"]) for row in normalized_estimates)

    worst_input = _worst_estimate(normalized_estimates, "estimated_input_tokens")
    worst_output = _worst_estimate(normalized_estimates, "estimated_output_tokens")
    worst_peak = _worst_estimate(normalized_estimates, "estimated_peak_session_tokens")
    worst_units = _worst_estimate(normalized_estimates, "owned_unit_count")

    required_by_limit = {
        "input": _required_shard_count(
            total=total_input_tokens,
            current_worst=int(worst_input.get("estimated_input_tokens") or 0),
            current_shard_count=current_shard_count,
            budget_value=resolved_budget.max_input_tokens,
        ),
        "output": _required_shard_count(
            total=total_output_tokens,
            current_worst=int(worst_output.get("estimated_output_tokens") or 0),
            current_shard_count=current_shard_count,
            budget_value=resolved_budget.max_output_tokens,
        ),
        "session_peak": _required_shard_count(
            total=total_peak_session_tokens,
            current_worst=int(worst_peak.get("estimated_peak_session_tokens") or 0),
            current_shard_count=current_shard_count,
            budget_value=resolved_budget.max_session_peak_tokens,
        ),
        "owned_units": _required_shard_count(
            total=total_owned_units,
            current_worst=int(worst_units.get("owned_unit_count") or 0),
            current_shard_count=current_shard_count,
            budget_value=resolved_budget.max_owned_units,
        ),
    }
    minimum_safe_shard_count = max(required_by_limit.values(), default=1)
    binding_limit = _binding_limit_for_required_counts(required_by_limit)
    safe = (
        effective_requested_shards >= minimum_safe_shard_count
        and all(str(row.get("verdict") or "") == "safe" for row in normalized_estimates)
    )
    worst_offender = _worst_offender_for_limit(
        binding_limit=binding_limit,
        worst_input=worst_input,
        worst_output=worst_output,
        worst_peak=worst_peak,
        worst_units=worst_units,
    )
    return {
        "stage_key": normalized_stage_key,
        "stage_label": stage_label_override or stage_label(normalized_stage_key),
        "requested_shard_count": effective_requested_shards,
        "current_shard_count": current_shard_count,
        "minimum_safe_shard_count": minimum_safe_shard_count,
        "survivability_verdict": "safe" if safe else "unsafe",
        "binding_limit": binding_limit,
        "required_by_limit": required_by_limit,
        "budget": asdict(resolved_budget),
        "totals": {
            "estimated_input_tokens": total_input_tokens,
            "estimated_output_tokens": total_output_tokens,
            "estimated_followup_tokens": total_followup_tokens,
            "estimated_peak_session_tokens": total_peak_session_tokens,
            "owned_unit_count": total_owned_units,
        },
        "worst_shard": worst_offender,
        "shards": normalized_estimates,
    }


def format_shard_survivability_error(report: Mapping[str, Any]) -> str:
    stage_label_text = str(report.get("stage_label") or report.get("stage_key") or "stage")
    requested = int(report.get("requested_shard_count") or 0)
    minimum_safe = int(report.get("minimum_safe_shard_count") or 0)
    binding_limit = str(report.get("binding_limit") or "unknown").strip() or "unknown"
    worst_shard = report.get("worst_shard")
    if not isinstance(worst_shard, Mapping):
        worst_shard = {}
    shard_id = str(worst_shard.get("shard_id") or "").strip()
    detail_bits = [
        f"requested {requested} shard(s)",
        f"minimum safe count is {minimum_safe}",
        f"binding limit is {binding_limit}",
    ]
    if shard_id:
        detail_bits.append(f"worst shard is {shard_id}")
    return (
        f"Unsafe Codex Exec shard plan for {stage_label_text}: "
        + ", ".join(detail_bits)
        + "."
    )


def _pressure_ratio(value: int, budget_value: int) -> float:
    if budget_value <= 0:
        return 0.0
    return round(float(value) / float(budget_value), 6)


def _binding_limit_from_pressure(pressure: Mapping[str, float]) -> str | None:
    winner = None
    winner_ratio = -1.0
    for key in ("session_peak", "output", "input", "owned_units"):
        ratio = float(pressure.get(key) or 0.0)
        if ratio > winner_ratio:
            winner = key
            winner_ratio = ratio
    return winner


def _required_shard_count(
    *,
    total: int,
    current_worst: int,
    current_shard_count: int,
    budget_value: int,
) -> int:
    if budget_value <= 0:
        return 1
    if total <= 0:
        return 1
    if current_shard_count <= 0 or current_worst <= 0:
        return max(1, int(ceil(float(total) / float(budget_value))))
    skew = max(
        1.0,
        (float(current_worst) * float(current_shard_count)) / float(total),
    )
    return max(1, int(ceil((float(total) * skew) / float(budget_value))))


def _binding_limit_for_required_counts(required_by_limit: Mapping[str, int]) -> str:
    best_key = "session_peak"
    best_value = -1
    for key in ("session_peak", "output", "input", "owned_units"):
        value = int(required_by_limit.get(key) or 1)
        if value > best_value:
            best_key = key
            best_value = value
    return best_key


def _worst_estimate(
    estimates: Sequence[Mapping[str, Any]],
    field_name: str,
) -> dict[str, Any]:
    if not estimates:
        return {}
    return dict(max(estimates, key=lambda row: int(row.get(field_name) or 0)))


def _worst_offender_for_limit(
    *,
    binding_limit: str,
    worst_input: Mapping[str, Any],
    worst_output: Mapping[str, Any],
    worst_peak: Mapping[str, Any],
    worst_units: Mapping[str, Any],
) -> dict[str, Any]:
    if binding_limit == "input":
        return dict(worst_input)
    if binding_limit == "output":
        return dict(worst_output)
    if binding_limit == "owned_units":
        return dict(worst_units)
    return dict(worst_peak)


def attach_observed_telemetry_to_survivability_report(
    report: Mapping[str, Any],
    *,
    telemetry_rows: Sequence[Mapping[str, Any]] | None = None,
    observed_overrides_by_shard_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    updated_report = dict(report)
    shard_rows = updated_report.get("shards")
    if not isinstance(shard_rows, list):
        return updated_report
    rows_by_shard_id: dict[str, list[Mapping[str, Any]]] = {}
    for row in telemetry_rows or ():
        if not isinstance(row, Mapping):
            continue
        shard_id = str(row.get("task_id") or row.get("shard_id") or "").strip()
        if not shard_id:
            continue
        rows_by_shard_id.setdefault(shard_id, []).append(row)
    override_lookup = (
        {
            str(shard_id): dict(payload)
            for shard_id, payload in observed_overrides_by_shard_id.items()
            if str(shard_id).strip() and isinstance(payload, Mapping)
        }
        if isinstance(observed_overrides_by_shard_id, Mapping)
        else {}
    )

    enriched_shards: list[dict[str, Any]] = []
    for shard_row in shard_rows:
        if not isinstance(shard_row, Mapping):
            continue
        shard_payload = dict(shard_row)
        shard_id = str(shard_payload.get("shard_id") or "").strip()
        matching_rows = rows_by_shard_id.get(shard_id, [])
        observed_summary = (
            summarize_direct_telemetry_rows(matching_rows)
            if matching_rows
            else {
                "call_count": 0,
                "token_usage_status": "unavailable",
            }
        )
        first_row = matching_rows[0] if matching_rows else {}
        observed_payload: dict[str, Any] = {
            "attempt_count": int(observed_summary.get("call_count") or 0),
            "token_usage_status": str(
                observed_summary.get("token_usage_status") or "unavailable"
            ),
            "initial_input_tokens": (
                int(first_row.get("tokens_input") or 0)
                if isinstance(first_row, Mapping)
                else None
            ),
            "initial_output_tokens": (
                int(first_row.get("tokens_output") or 0)
                if isinstance(first_row, Mapping)
                else None
            ),
            "initial_total_tokens": (
                int(first_row.get("tokens_total") or 0)
                if isinstance(first_row, Mapping)
                else None
            ),
            "total_billed_tokens": int(observed_summary.get("tokens_total") or 0),
            "structured_followup_call_count": int(
                observed_summary.get("structured_followup_call_count") or 0
            ),
            "structured_followup_tokens_total": int(
                observed_summary.get("structured_followup_tokens_total") or 0
            ),
            "final_supervision_state": (
                str(
                    (
                        first_row.get("final_supervision_state")
                        or first_row.get("supervision_state")
                        or ""
                    )
                ).strip()
                if isinstance(first_row, Mapping)
                else ""
            ),
            "proposal_status": (
                str(
                    (
                        first_row.get("final_proposal_status")
                        or first_row.get("proposal_status")
                        or ""
                    )
                ).strip()
                if isinstance(first_row, Mapping)
                else ""
            ),
            "watchdog_killed": bool(
                int(observed_summary.get("watchdog_killed_shard_count") or 0) > 0
            ),
            "missing_output": bool(
                int(observed_summary.get("missing_output_shard_count") or 0) > 0
            ),
            "invalid_output": bool(
                int(observed_summary.get("invalid_output_shard_count") or 0) > 0
            ),
            "repaired": bool(
                int(observed_summary.get("repaired_shard_count") or 0) > 0
            ),
            "pathological": bool(
                int(observed_summary.get("pathological_shard_count") or 0) > 0
            ),
        }
        if shard_id in override_lookup:
            observed_payload.update(dict(override_lookup[shard_id]))
        shard_payload["observed"] = observed_payload
        shard_payload["predicted_vs_observed"] = {
            "initial_input_tokens": {
                "predicted": int(shard_payload.get("estimated_input_tokens") or 0),
                "observed": observed_payload.get("initial_input_tokens"),
                "delta": (
                    int(observed_payload["initial_input_tokens"])
                    - int(shard_payload.get("estimated_input_tokens") or 0)
                    if observed_payload.get("initial_input_tokens") is not None
                    else None
                ),
            },
            "initial_output_tokens": {
                "predicted": int(shard_payload.get("estimated_output_tokens") or 0),
                "observed": observed_payload.get("initial_output_tokens"),
                "delta": (
                    int(observed_payload["initial_output_tokens"])
                    - int(shard_payload.get("estimated_output_tokens") or 0)
                    if observed_payload.get("initial_output_tokens") is not None
                    else None
                ),
            },
            "followup_tokens": {
                "predicted": int(shard_payload.get("estimated_followup_tokens") or 0),
                "observed": int(
                    observed_payload.get("structured_followup_tokens_total") or 0
                ),
                "delta": int(observed_payload.get("structured_followup_tokens_total") or 0)
                - int(shard_payload.get("estimated_followup_tokens") or 0),
            },
            "billed_total_tokens_vs_predicted_peak": {
                "predicted_peak_session_tokens": int(
                    shard_payload.get("estimated_peak_session_tokens") or 0
                ),
                "observed_billed_total_tokens": int(
                    observed_payload.get("total_billed_tokens") or 0
                ),
                "delta": int(observed_payload.get("total_billed_tokens") or 0)
                - int(shard_payload.get("estimated_peak_session_tokens") or 0),
            },
        }
        enriched_shards.append(shard_payload)
    updated_report["shards"] = enriched_shards
    updated_report["observed_summary"] = summarize_direct_telemetry_rows(
        [row for row in telemetry_rows or () if isinstance(row, Mapping)]
    )
    return updated_report


__all__ = [
    "attach_observed_telemetry_to_survivability_report",
    "ShardSurvivabilityPreflightError",
    "StageSurvivabilityBudget",
    "count_structural_output_tokens",
    "count_tokens_for_model",
    "default_stage_survivability_budget",
    "estimate_shard_survivability",
    "evaluate_stage_survivability",
    "format_shard_survivability_error",
    "normalize_survivability_stage_key",
]
