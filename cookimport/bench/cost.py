"""LLM cost estimator — counting only, no actual LLM calls.

Estimates how many tokens/dollars would be consumed if the current
prediction set were sent to an LLM for repair/verification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Average chars per token for typical recipe text
_CHARS_PER_TOKEN = 4

# Default pricing per 1M tokens (USD)
_DEFAULT_PRICING = {
    "input_per_1m": 3.0,
    "output_per_1m": 15.0,
}

# Estimated template overhead per repair call (tokens)
_TEMPLATE_OVERHEAD_TOKENS = 200


def estimate_llm_costs(
    predictions: list[dict[str, Any]],
    *,
    pricing: dict[str, float] | None = None,
    avg_row_chars: int = 120,
) -> dict[str, Any]:
    """Estimate LLM costs for repairing/verifying predictions.

    No actual LLM calls are made. This is purely a counting exercise
    based on prediction volume and estimated text sizes.
    """
    price = pricing or _DEFAULT_PRICING
    input_per_1m = price.get("input_per_1m", _DEFAULT_PRICING["input_per_1m"])
    output_per_1m = price.get("output_per_1m", _DEFAULT_PRICING["output_per_1m"])

    total_calls = len(predictions)
    total_input_chars = 0
    total_output_chars = 0

    for pred in predictions:
        start = int(pred.get("start_row_index", 0))
        end = int(pred.get("end_row_index", start))
        span_rows = max(1, end - start + 1)
        input_chars = span_rows * avg_row_chars + _TEMPLATE_OVERHEAD_TOKENS * _CHARS_PER_TOKEN
        output_chars = max(50, span_rows * avg_row_chars // 2)
        total_input_chars += input_chars
        total_output_chars += output_chars

    input_tokens = total_input_chars / _CHARS_PER_TOKEN
    output_tokens = total_output_chars / _CHARS_PER_TOKEN

    input_cost = (input_tokens / 1_000_000) * input_per_1m
    output_cost = (output_tokens / 1_000_000) * output_per_1m
    total_cost = input_cost + output_cost

    return {
        "total_calls": total_calls,
        "estimated_input_tokens": int(input_tokens),
        "estimated_output_tokens": int(output_tokens),
        "estimated_total_tokens": int(input_tokens + output_tokens),
        "estimated_input_cost_usd": round(input_cost, 4),
        "estimated_output_cost_usd": round(output_cost, 4),
        "estimated_total_cost_usd": round(total_cost, 4),
        "pricing_used": {
            "input_per_1m": input_per_1m,
            "output_per_1m": output_per_1m,
        },
    }


def write_escalation_queue(
    predictions: list[dict[str, Any]],
    path: Path,
    *,
    labels: set[str] | None = None,
) -> None:
    """Write predictions that would be escalated to LLM review.

    If labels is provided, only predictions with those labels are included.
    Otherwise all predictions are included.
    """
    queue = predictions
    if labels:
        queue = [p for p in predictions if str(p.get("label") or "") in labels]

    lines = [json.dumps(p) for p in queue]
    path.write_text(
        "\n".join(lines) + "\n" if lines else "", encoding="utf-8"
    )
