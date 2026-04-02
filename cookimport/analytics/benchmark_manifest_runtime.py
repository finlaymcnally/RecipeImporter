from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

TOKEN_USAGE_KEYS = (
    "tokens_input",
    "tokens_cached_input",
    "tokens_output",
    "tokens_reasoning",
    "tokens_total",
)

_RUNTIME_PLACEHOLDER_VALUES = {"none", "null", "n/a"}
_DEFAULT_REASONING_PLACEHOLDER_VALUES = {
    "<default>",
    "default",
    "(default)",
}
_CODEX_REASONING_EFFORT_VALUES = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
}
_RUNTIME_MODEL_KEYS = (
    "codex_farm_model",
    "codex_model",
    "provider_model",
    "model",
)
_RUNTIME_EFFORT_KEYS = (
    "codex_farm_reasoning_effort",
    "codex_farm_thinking_effort",
    "codex_reasoning_effort",
    "model_reasoning_effort",
    "thinking_effort",
    "reasoning_effort",
)


def clean_runtime_text(
    value: Any,
    *,
    treat_default_missing: bool = False,
) -> str | None:
    text = _normalize_optional_text(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in _RUNTIME_PLACEHOLDER_VALUES:
        return None
    if treat_default_missing and lowered in _DEFAULT_REASONING_PLACEHOLDER_VALUES:
        return None
    return text


def normalize_reasoning_effort(value: Any) -> str | None:
    cleaned = clean_runtime_text(value, treat_default_missing=True)
    if cleaned is None:
        return None
    lowered = cleaned.lower()
    if lowered in _CODEX_REASONING_EFFORT_VALUES:
        return lowered
    return cleaned


def default_codex_reasoning_effort_for_model(model: str | None) -> str | None:
    target = clean_runtime_text(model)
    if target is None:
        return None
    target_lower = target.lower()

    for cache_path in _codex_models_cache_paths():
        if not cache_path.exists() or not cache_path.is_file():
            continue
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = payload.get("models")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            slug = clean_runtime_text(row.get("slug"))
            if slug is None or slug.lower() != target_lower:
                continue
            effort = normalize_reasoning_effort(row.get("default_reasoning_level"))
            if effort is not None:
                return effort
    return None


def explicit_runtime_from_run_config(
    run_config: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    if not isinstance(run_config, dict):
        return (None, None)
    model = None
    for key in _RUNTIME_MODEL_KEYS:
        model = clean_runtime_text(run_config.get(key))
        if model is not None:
            break
    effort = None
    for key in _RUNTIME_EFFORT_KEYS:
        effort = normalize_reasoning_effort(run_config.get(key))
        if effort is not None:
            break
    return (model, effort)


def runtime_from_run_config(
    run_config: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    model, effort = explicit_runtime_from_run_config(run_config)
    if effort is None and model is not None:
        effort = default_codex_reasoning_effort_for_model(model)
    return (model, effort)


def merge_missing_run_config_fields(
    base: dict[str, Any],
    incoming: dict[str, Any] | None,
) -> bool:
    if not isinstance(incoming, dict) or not incoming:
        return False
    changed = False
    runtime_keys = set(_RUNTIME_MODEL_KEYS) | set(_RUNTIME_EFFORT_KEYS)
    for key, incoming_value in incoming.items():
        if key not in base:
            base[key] = incoming_value
            changed = True
            continue
        if key in runtime_keys:
            existing_clean = clean_runtime_text(
                base.get(key),
                treat_default_missing=True,
            )
            incoming_clean = clean_runtime_text(
                incoming_value,
                treat_default_missing=True,
            )
            if existing_clean is None and incoming_clean is not None:
                base[key] = incoming_clean
                changed = True
    return changed


def parse_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None


def nonnegative_int_or_none(value: Any) -> int | None:
    parsed = parse_int_or_none(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def token_usage_has_values(
    *,
    tokens_input: int | None,
    tokens_cached_input: int | None,
    tokens_output: int | None,
    tokens_reasoning: int | None,
    tokens_total: int | None,
) -> bool:
    return any(
        value is not None
        for value in (
            tokens_input,
            tokens_cached_input,
            tokens_output,
            tokens_reasoning,
            tokens_total,
        )
    )


def extract_codex_runtime_from_manifest(
    payload: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return (None, None)

    llm_codex_farm = payload.get("llm_codex_farm")
    if not isinstance(llm_codex_farm, dict):
        if any(
            key in payload for key in ("process_runs", "codex_farm_model", "codex_model")
        ):
            llm_codex_farm = payload
        else:
            return (None, None)

    model_candidates: list[str] = []
    effort_candidates: list[str] = []

    def _collect(model_value: Any, effort_value: Any) -> None:
        model = clean_runtime_text(model_value)
        effort = clean_runtime_text(effort_value)
        if model is not None:
            model_candidates.append(model)
        if effort is not None:
            effort_candidates.append(effort)

    def _collect_from_telemetry(telemetry: Any) -> None:
        if not isinstance(telemetry, dict):
            return
        insights = telemetry.get("insights")
        if not isinstance(insights, dict):
            return
        breakdown = insights.get("model_reasoning_breakdown")
        if not isinstance(breakdown, list):
            return
        for row in breakdown:
            if not isinstance(row, dict):
                continue
            _collect(row.get("model"), row.get("reasoning_effort"))

    _collect(
        llm_codex_farm.get("codex_farm_model") or llm_codex_farm.get("codex_model"),
        llm_codex_farm.get("codex_farm_reasoning_effort")
        or llm_codex_farm.get("codex_reasoning_effort"),
    )
    _collect_from_telemetry(llm_codex_farm.get("telemetry_report"))

    process_runs = llm_codex_farm.get("process_runs")
    if isinstance(process_runs, dict):
        for pass_name in sorted(process_runs):
            run_entry = process_runs.get(pass_name)
            if not isinstance(run_entry, dict):
                continue
            process_payload = run_entry.get("process_payload")
            if not isinstance(process_payload, dict):
                continue
            _collect(
                process_payload.get("codex_model"),
                process_payload.get("codex_reasoning_effort"),
            )
            _collect_from_telemetry(process_payload.get("telemetry_report"))
            _collect_from_telemetry(process_payload.get("llm_report"))

    model = model_candidates[0] if model_candidates else None
    effort = effort_candidates[0] if effort_candidates else None
    return (model, effort)


def extract_codex_runtime_error_from_manifest(
    payload: dict[str, Any] | None,
) -> str | None:
    if not isinstance(payload, dict):
        return None
    llm_codex_farm = payload.get("llm_codex_farm")
    if not isinstance(llm_codex_farm, dict):
        return None
    for key in ("fatalError", "fatal_error", "error", "last_error"):
        text = clean_runtime_text(llm_codex_farm.get(key))
        if text is not None:
            return text
    return None


def extract_codex_token_usage_from_manifest(
    payload: dict[str, Any] | None,
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    if not isinstance(payload, dict):
        return (None, None, None, None, None)

    llm_codex_farm = payload.get("llm_codex_farm")
    if not isinstance(llm_codex_farm, dict):
        if isinstance(payload.get("process_runs"), dict):
            llm_codex_farm = payload
        else:
            return (None, None, None, None, None)

    process_runs = llm_codex_farm.get("process_runs")
    if not isinstance(process_runs, dict):
        return _token_usage_from_process_payload(llm_codex_farm)

    totals: dict[str, int | None] = {key: None for key in TOKEN_USAGE_KEYS}
    for pass_name in sorted(process_runs):
        pass_payload = process_runs.get(pass_name)
        if not isinstance(pass_payload, dict):
            continue
        for key, value in zip(
            TOKEN_USAGE_KEYS,
            _token_usage_from_process_payload(pass_payload),
        ):
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value

    knowledge_payload = llm_codex_farm.get("knowledge")
    knowledge_tokens = (None, None, None, None, None)
    if isinstance(knowledge_payload, dict):
        process_run_payload = knowledge_payload.get("process_run")
        if isinstance(process_run_payload, dict):
            knowledge_tokens = _token_usage_from_process_payload(process_run_payload)
        if all(value is None for value in knowledge_tokens):
            knowledge_tokens = _token_usage_from_process_payload(knowledge_payload)
    for key, value in zip(TOKEN_USAGE_KEYS, knowledge_tokens):
        if value is None:
            continue
        current = totals.get(key)
        totals[key] = value if current is None else current + value

    return tuple(totals.get(key) for key in TOKEN_USAGE_KEYS)


def extract_line_role_token_usage_from_manifest(
    payload: dict[str, Any] | None,
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    if not isinstance(payload, dict):
        return (None, None, None, None, None)
    for telemetry_path in _line_role_telemetry_candidate_paths(payload):
        try:
            telemetry_payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(telemetry_payload, dict):
            continue
        summary = telemetry_payload.get("summary")
        direct_tokens = (
            nonnegative_int_or_none(summary.get("tokens_input"))
            if isinstance(summary, dict)
            else None,
            nonnegative_int_or_none(summary.get("tokens_cached_input"))
            if isinstance(summary, dict)
            else None,
            nonnegative_int_or_none(summary.get("tokens_output"))
            if isinstance(summary, dict)
            else None,
            nonnegative_int_or_none(summary.get("tokens_reasoning"))
            if isinstance(summary, dict)
            else None,
            nonnegative_int_or_none(summary.get("tokens_total"))
            if isinstance(summary, dict)
            else None,
        )
        nested_summaries = _line_role_token_summaries_from_attempts(telemetry_payload)
        fallback_tokens = _token_usage_from_summary_payloads(nested_summaries)
        summary_looks_incomplete = False
        if isinstance(summary, dict):
            direct_has_positive_usage = any(
                value is not None and value > 0 for value in direct_tokens
            )
            attempts_without_usage = nonnegative_int_or_none(
                summary.get("attempts_without_usage")
            )
            visible_input_tokens = nonnegative_int_or_none(
                summary.get("visible_input_tokens")
            )
            visible_output_tokens = nonnegative_int_or_none(
                summary.get("visible_output_tokens")
            )
            command_execution_count_total = nonnegative_int_or_none(
                summary.get("command_execution_count_total")
            )
            summary_looks_incomplete = bool(
                (attempts_without_usage is not None and attempts_without_usage > 0)
                or (
                    not direct_has_positive_usage
                    and any(
                        value is not None and value > 0
                        for value in (
                            visible_input_tokens,
                            visible_output_tokens,
                            command_execution_count_total,
                        )
                    )
                )
            )
        if summary_looks_incomplete:
            return (None, None, None, None, None)
        resolved_tokens = tuple(
            direct if direct is not None else fallback
            for direct, fallback in zip(direct_tokens, fallback_tokens)
        )
        if any(value is not None for value in resolved_tokens):
            return resolved_tokens
    return (None, None, None, None, None)


def sum_token_usage(
    *token_sets: tuple[int | None, int | None, int | None, int | None, int | None],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    totals: dict[str, int | None] = {key: None for key in TOKEN_USAGE_KEYS}
    for token_values in token_sets:
        for key, value in zip(TOKEN_USAGE_KEYS, token_values):
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return tuple(totals.get(key) for key in TOKEN_USAGE_KEYS)


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _codex_models_cache_paths() -> list[Path]:
    roots: list[Path] = []
    env_root = (os.environ.get("CODEX_HOME") or "").strip()
    if env_root:
        roots.append(Path(env_root).expanduser())
    roots.extend([Path.home() / ".codex", Path.home() / ".codex-alt"])
    for path in sorted(Path.home().glob(".codex*")):
        if path.is_dir():
            roots.append(path)

    unique_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_roots.append(root)
    return [root / "models_cache.json" for root in unique_roots]


def _token_usage_from_process_payload(
    pass_payload: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    process_payload = (
        pass_payload.get("process_payload")
        if isinstance(pass_payload.get("process_payload"), dict)
        else None
    )
    telemetry_payload = (
        process_payload.get("telemetry")
        if isinstance(process_payload, dict)
        and isinstance(process_payload.get("telemetry"), dict)
        else None
    )
    if telemetry_payload is None and isinstance(pass_payload.get("telemetry"), dict):
        telemetry_payload = pass_payload.get("telemetry")
    telemetry_rows = (
        telemetry_payload.get("rows")
        if isinstance(telemetry_payload, dict)
        and isinstance(telemetry_payload.get("rows"), list)
        else None
    )

    totals: dict[str, int | None] = {key: None for key in TOKEN_USAGE_KEYS}
    if isinstance(telemetry_rows, list):
        for raw_row in telemetry_rows:
            if not isinstance(raw_row, dict):
                continue
            for key in TOKEN_USAGE_KEYS:
                value = nonnegative_int_or_none(raw_row.get(key))
                if value is None:
                    continue
                current = totals.get(key)
                totals[key] = value if current is None else current + value

    telemetry_report = None
    if isinstance(process_payload, dict) and isinstance(
        process_payload.get("telemetry_report"), dict
    ):
        telemetry_report = process_payload.get("telemetry_report")
    elif isinstance(pass_payload.get("telemetry_report"), dict):
        telemetry_report = pass_payload.get("telemetry_report")
    summary = (
        telemetry_report.get("summary")
        if isinstance(telemetry_report, dict)
        and isinstance(telemetry_report.get("summary"), dict)
        else None
    )
    if isinstance(summary, dict):
        summary_value_map = {
            "tokens_input": summary.get("tokens_input"),
            "tokens_cached_input": summary.get("tokens_cached_input"),
            "tokens_output": summary.get("tokens_output"),
            "tokens_reasoning": (
                summary.get("tokens_reasoning")
                if summary.get("tokens_reasoning") is not None
                else summary.get("tokens_reasoning_total")
            ),
            "tokens_total": summary.get("tokens_total"),
        }
        for key, raw_value in summary_value_map.items():
            if totals.get(key) is not None:
                continue
            parsed_value = nonnegative_int_or_none(raw_value)
            if parsed_value is not None:
                totals[key] = parsed_value

    return tuple(totals.get(key) for key in TOKEN_USAGE_KEYS)


def _append_token_summary_payload(
    summary: dict[str, Any],
    summaries: list[dict[str, Any]],
    seen: set[int],
) -> None:
    summary_id = id(summary)
    if summary_id in seen:
        return
    seen.add(summary_id)
    summaries.append(summary)


def _collect_token_summary_payloads(
    payload: Any,
    summaries: list[dict[str, Any]],
    seen: set[int],
) -> None:
    if isinstance(payload, dict):
        summary = payload.get("summary")
        if isinstance(summary, dict):
            _append_token_summary_payload(summary, summaries, seen)
        telemetry_report = payload.get("telemetry_report")
        if isinstance(telemetry_report, dict):
            nested_summary = telemetry_report.get("summary")
            if isinstance(nested_summary, dict):
                _append_token_summary_payload(nested_summary, summaries, seen)
        for value in payload.values():
            _collect_token_summary_payloads(value, summaries, seen)
    elif isinstance(payload, list):
        for value in payload:
            _collect_token_summary_payloads(value, summaries, seen)


def _token_usage_from_summary_payloads(
    summaries: list[dict[str, Any]],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    totals: dict[str, int | None] = {key: None for key in TOKEN_USAGE_KEYS}
    for summary in summaries:
        summary_value_map = {
            "tokens_input": summary.get("tokens_input"),
            "tokens_cached_input": summary.get("tokens_cached_input"),
            "tokens_output": summary.get("tokens_output"),
            "tokens_reasoning": (
                summary.get("tokens_reasoning")
                if summary.get("tokens_reasoning") is not None
                else summary.get("tokens_reasoning_total")
            ),
            "tokens_total": summary.get("tokens_total"),
        }
        for key, raw_value in summary_value_map.items():
            value = nonnegative_int_or_none(raw_value)
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return tuple(totals.get(key) for key in TOKEN_USAGE_KEYS)


def _line_role_token_summaries_from_attempts(
    telemetry_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    batches = telemetry_payload.get("batches")
    if not isinstance(batches, list):
        return summaries
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        attempts = batch.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            process_run = attempt.get("process_run")
            if isinstance(process_run, dict):
                process_payload = process_run.get("process_payload")
                if isinstance(process_payload, dict):
                    telemetry_report = process_payload.get("telemetry_report")
                    if (
                        isinstance(telemetry_report, dict)
                        and isinstance(telemetry_report.get("summary"), dict)
                    ):
                        summaries.append(telemetry_report.get("summary"))
                        continue
                telemetry_report = process_run.get("telemetry_report")
                if (
                    isinstance(telemetry_report, dict)
                    and isinstance(telemetry_report.get("summary"), dict)
                ):
                    summaries.append(telemetry_report.get("summary"))
                    continue
            telemetry_report = attempt.get("telemetry_report")
            if (
                isinstance(telemetry_report, dict)
                and isinstance(telemetry_report.get("summary"), dict)
            ):
                summaries.append(telemetry_report.get("summary"))
    return summaries


def _line_role_telemetry_candidate_paths(payload: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _append_candidate(raw_path: Any) -> None:
        text = str(raw_path or "").strip()
        if not text:
            return
        candidate = Path(text)
        if candidate in seen:
            return
        seen.add(candidate)
        candidates.append(candidate)

    _append_candidate(payload.get("line_role_pipeline_telemetry_path"))
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        _append_candidate(artifacts.get("line_role_pipeline_telemetry_json"))
    for root_key in ("processed_run_root", "stage_run_root"):
        root_value = str(payload.get(root_key) or "").strip()
        if not root_value:
            continue
        _append_candidate(Path(root_value) / "line-role-pipeline" / "telemetry_summary.json")
    return [candidate for candidate in candidates if candidate.is_file()]
