from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .codex_exec_types import (
    CodexExecLiveSnapshot,
    CodexExecRecentCommandCompletion,
    DirectExecWorkspaceMode,
    FinalAgentMessageAssessment,
)


def _runner_attr(name: str, default: Any = None) -> Any:
    runner_module = importlib.import_module("cookimport.llm.codex_exec_runner")
    return getattr(runner_module, name, default)


def summarize_direct_telemetry_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summary = {
        "call_count": len(rows),
        "duration_total_ms": 0,
        "tokens_input": 0,
        "tokens_cached_input": 0,
        "tokens_output": 0,
        "tokens_reasoning": 0,
        "tokens_total": 0,
        "visible_input_tokens": 0,
        "visible_output_tokens": 0,
        "wrapper_overhead_tokens": 0,
        "command_execution_count_total": 0,
        "reasoning_item_count_total": 0,
        "command_execution_tokens_total": 0,
        "reasoning_heavy_tokens_total": 0,
        "invalid_output_tokens_total": 0,
        "taskfile_row_count": 0,
        "taskfile_session_count": 0,
        "structured_followup_call_count": 0,
        "structured_repair_followup_call_count": 0,
        "watchdog_retry_call_count": 0,
        "structured_followup_tokens_total": 0,
        "command_policy_counts": {},
        "watchdog_recovered_shard_count": 0,
    }
    prompt_input_mode_counts: dict[str, int] = {}
    command_executing_shards: set[str] = set()
    reasoning_heavy_shards: set[str] = set()
    invalid_output_shards: set[str] = set()
    no_final_output_shards: set[str] = set()
    missing_output_shards: set[str] = set()
    repaired_shards: set[str] = set()
    preflight_rejected_shards: set[str] = set()
    watchdog_killed_shards: set[str] = set()
    watchdog_recovered_shards: set[str] = set()
    pathological_shards: set[str] = set()
    token_usage_available_call_count = 0
    token_usage_missing_call_count = 0
    for row in rows:
        summary["duration_total_ms"] += int(row.get("duration_ms") or 0)
        summary["tokens_input"] += int(row.get("tokens_input") or 0)
        summary["tokens_cached_input"] += int(row.get("tokens_cached_input") or 0)
        summary["tokens_output"] += int(row.get("tokens_output") or 0)
        summary["tokens_reasoning"] += int(row.get("tokens_reasoning") or 0)
        summary["tokens_total"] += int(row.get("tokens_total") or 0)
        summary["visible_input_tokens"] += int(row.get("visible_input_tokens") or 0)
        summary["visible_output_tokens"] += int(row.get("visible_output_tokens") or 0)
        summary["wrapper_overhead_tokens"] += int(row.get("wrapper_overhead_tokens") or 0)
        shard_id = str(row.get("task_id") or "").strip()
        tokens_total = int(row.get("tokens_total") or 0)
        prompt_input_mode = str(row.get("prompt_input_mode") or "path").strip().lower() or "path"
        prompt_input_mode_counts[prompt_input_mode] = (
            int(prompt_input_mode_counts.get(prompt_input_mode) or 0) + 1
        )
        if _row_has_any_token_usage(row):
            token_usage_available_call_count += 1
        elif _row_looks_like_missing_token_usage(row):
            token_usage_missing_call_count += 1
        if prompt_input_mode == "taskfile":
            summary["taskfile_row_count"] += 1
            if bool(row.get("worker_session_primary_row")):
                summary["taskfile_session_count"] += 1
        if _prompt_input_mode_is_watchdog_retry(prompt_input_mode):
            summary["structured_followup_call_count"] += 1
            summary["watchdog_retry_call_count"] += 1
            summary["structured_followup_tokens_total"] += tokens_total
        elif _prompt_input_mode_is_structured_repair_followup(prompt_input_mode):
            summary["structured_followup_call_count"] += 1
            summary["structured_repair_followup_call_count"] += 1
            summary["structured_followup_tokens_total"] += tokens_total
        command_execution_count = int(row.get("command_execution_count") or 0)
        command_policy_counts = row.get("command_execution_policy_counts")
        if isinstance(command_policy_counts, Mapping):
            aggregate = dict(summary.get("command_policy_counts") or {})
            for key, value in command_policy_counts.items():
                policy = str(key or "").strip()
                if not policy:
                    continue
                aggregate[policy] = int(aggregate.get(policy) or 0) + int(value or 0)
            summary["command_policy_counts"] = aggregate
        reasoning_item_count = int(row.get("reasoning_item_count") or 0)
        summary["command_execution_count_total"] += command_execution_count
        summary["reasoning_item_count_total"] += reasoning_item_count
        if command_execution_count > 0:
            summary["command_execution_tokens_total"] += tokens_total
            if shard_id:
                command_executing_shards.add(shard_id)
                pathological_shards.add(shard_id)
        if reasoning_item_count > 0 or int(row.get("tokens_reasoning") or 0) > 0:
            summary["reasoning_heavy_tokens_total"] += tokens_total
            if shard_id:
                reasoning_heavy_shards.add(shard_id)
                pathological_shards.add(shard_id)
        proposal_status = str(
            row.get("final_proposal_status") or row.get("proposal_status") or ""
        ).strip().lower()
        if proposal_status == "invalid":
            summary["invalid_output_tokens_total"] += tokens_total
            if shard_id:
                invalid_output_shards.add(shard_id)
                pathological_shards.add(shard_id)
        if proposal_status == "no_final_output" and shard_id:
            no_final_output_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if proposal_status == "missing_output" and shard_id:
            missing_output_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if str(row.get("repair_status") or "").strip().lower() == "repaired" and shard_id:
            repaired_shards.add(shard_id)
        effective_supervision_state = str(
            row.get("final_supervision_state") or row.get("supervision_state") or ""
        ).strip().lower()
        raw_supervision_state = str(
            row.get("raw_supervision_state") or row.get("supervision_state") or ""
        ).strip().lower()
        if effective_supervision_state == "preflight_rejected" and shard_id:
            preflight_rejected_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if effective_supervision_state == "watchdog_killed" and shard_id:
            watchdog_killed_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if (
            raw_supervision_state == "watchdog_killed"
            and effective_supervision_state != "watchdog_killed"
            and shard_id
        ):
            watchdog_recovered_shards.add(shard_id)
            pathological_shards.add(shard_id)
    summary["cost_breakdown"] = {
        "visible_input_tokens": summary["visible_input_tokens"],
        "cached_input_tokens": summary["tokens_cached_input"],
        "visible_output_tokens": summary["visible_output_tokens"],
        "wrapper_overhead_tokens": summary["wrapper_overhead_tokens"],
        "reasoning_tokens": summary["tokens_reasoning"],
        "billed_total_tokens": summary["tokens_total"],
    }
    summary["command_executing_shard_count"] = len(command_executing_shards)
    summary["reasoning_heavy_shard_count"] = len(reasoning_heavy_shards)
    summary["invalid_output_shard_count"] = len(invalid_output_shards)
    summary["no_final_output_shard_count"] = len(no_final_output_shards)
    summary["missing_output_shard_count"] = len(missing_output_shards)
    summary["repaired_shard_count"] = len(repaired_shards)
    summary["preflight_rejected_shard_count"] = len(preflight_rejected_shards)
    summary["watchdog_killed_shard_count"] = len(watchdog_killed_shards)
    summary["watchdog_recovered_shard_count"] = len(watchdog_recovered_shards)
    summary["pathological_shard_count"] = len(pathological_shards)
    summary["command_policy_counts"] = dict(
        sorted(dict(summary.get("command_policy_counts") or {}).items())
    )
    summary["prompt_input_mode_counts"] = dict(sorted(prompt_input_mode_counts.items()))
    token_usage_status = _token_usage_status_from_counts(
        available_call_count=token_usage_available_call_count,
        missing_call_count=token_usage_missing_call_count,
    )
    if token_usage_status is not None:
        summary["token_usage_status"] = token_usage_status
        summary["token_usage_available_call_count"] = token_usage_available_call_count
        summary["token_usage_missing_call_count"] = token_usage_missing_call_count
        if token_usage_status != "complete":
            for key in (
                "tokens_input",
                "tokens_cached_input",
                "tokens_output",
                "tokens_reasoning",
                "tokens_total",
                "wrapper_overhead_tokens",
                "command_execution_tokens_total",
                "reasoning_heavy_tokens_total",
                "invalid_output_tokens_total",
                "structured_followup_tokens_total",
            ):
                summary[key] = None
            summary["cost_breakdown"] = {
                "visible_input_tokens": summary["visible_input_tokens"],
                "cached_input_tokens": None,
                "visible_output_tokens": summary["visible_output_tokens"],
                "wrapper_overhead_tokens": None,
                "reasoning_tokens": None,
                "billed_total_tokens": None,
            }
    summary["pathological_flags"] = _summary_pathological_flags(summary)
    return summary


def _prompt_input_mode_is_watchdog_retry(prompt_input_mode: str) -> bool:
    return prompt_input_mode in {"inline_watchdog_retry", "structured_session_watchdog_retry"}


def _prompt_input_mode_is_structured_repair_followup(prompt_input_mode: str) -> bool:
    if prompt_input_mode in {"inline_retry", "inline_repair", "inline_snippet_repair"}:
        return True
    if prompt_input_mode == "structured_session_repair":
        return True
    return prompt_input_mode.startswith("structured_session_") and prompt_input_mode.endswith(
        "_repair"
    )


def _row_has_any_token_usage(row: Mapping[str, Any]) -> bool:
    for field in (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    ):
        value = _coerce_nonnegative_int(row.get(field))
        if value is not None and value > 0:
            return True
    return False


def _row_looks_like_missing_token_usage(row: Mapping[str, Any]) -> bool:
    if _row_has_any_token_usage(row):
        return False
    return any(
        value not in (None, "", 0, False)
        for value in (
            _coerce_nonnegative_int(row.get("duration_ms")),
            _coerce_nonnegative_int(row.get("visible_input_tokens")),
            _coerce_nonnegative_int(row.get("visible_output_tokens")),
            _coerce_nonnegative_int(row.get("codex_event_count")),
            _coerce_nonnegative_int(row.get("command_execution_count")),
            _coerce_nonnegative_int(row.get("reasoning_item_count")),
            row.get("started_at_utc"),
            row.get("finished_at_utc"),
            row.get("prompt_text"),
            row.get("output_payload_present"),
            row.get("prompt_input_mode"),
        )
    )


def _token_usage_status_from_counts(
    *,
    available_call_count: int,
    missing_call_count: int,
) -> str | None:
    if missing_call_count > 0:
        return "partial" if available_call_count > 0 else "unavailable"
    if available_call_count > 0:
        return "complete"
    return None


def _token_usage_status_from_direct_rows(rows: Sequence[Mapping[str, Any]]) -> str | None:
    available_call_count = 0
    missing_call_count = 0
    for row in rows:
        if _row_has_any_token_usage(row):
            available_call_count += 1
        elif _row_looks_like_missing_token_usage(row):
            missing_call_count += 1
    return _token_usage_status_from_counts(
        available_call_count=available_call_count,
        missing_call_count=missing_call_count,
    )


def _parse_codex_json_events(
    stdout_text: str | None,
    stderr_text: str | None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for stream in (stdout_text or "", stderr_text or ""):
        for raw_line in stream.splitlines():
            payload = _parse_codex_json_line(raw_line)
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _parse_codex_json_line(line: str | None) -> dict[str, Any] | None:
    rendered = str(line or "").strip()
    if not rendered or not rendered.startswith("{"):
        return None
    try:
        payload = json.loads(rendered)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_last_agent_message(
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]]
) -> str | None:
    response: str | None = None
    for payload in events:
        if payload.get("type") != "item.completed":
            continue
        item = payload.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        text = str(item.get("text") or "").strip()
        if text:
            response = text
    return response


def assess_final_agent_message(
    message_text: str | None,
    *,
    workspace_mode: DirectExecWorkspaceMode = "packet",
) -> FinalAgentMessageAssessment:
    cleaned = str(message_text or "").strip()
    if not cleaned:
        return FinalAgentMessageAssessment(state="absent", text=None)
    if workspace_mode == "taskfile" and not cleaned.startswith("{"):
        return FinalAgentMessageAssessment(
            state="informational",
            reason="taskfile worker final message is informational only",
            text=cleaned,
        )
    if not cleaned.startswith("{"):
        return FinalAgentMessageAssessment(
            state="malformed",
            reason="final agent message did not start with `{`",
            text=cleaned,
        )
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return FinalAgentMessageAssessment(
            state="malformed",
            reason=f"final agent message was not valid JSON: {exc.msg}",
            text=cleaned,
        )
    if not isinstance(payload, dict):
        return FinalAgentMessageAssessment(
            state="malformed",
            reason="final agent message was valid JSON but not a JSON object",
            text=cleaned,
        )
    return FinalAgentMessageAssessment(
        state="json_object",
        reason=None,
        text=cleaned,
    )


def _extract_turn_completed_usage(
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]]
) -> Mapping[str, Any] | None:
    usage_payload: Mapping[str, Any] | None = None
    for payload in events:
        if payload.get("type") == "turn.completed" and isinstance(payload.get("usage"), Mapping):
            usage_payload = payload.get("usage")
    return usage_payload


def _normalize_usage(payload: Mapping[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(payload, Mapping):
        return None
    return {
        "input_tokens": max(0, int(payload.get("input_tokens") or 0)),
        "cached_input_tokens": max(0, int(payload.get("cached_input_tokens") or 0)),
        "output_tokens": max(0, int(payload.get("output_tokens") or 0)),
        "reasoning_tokens": max(
            0,
            int(
                payload.get("reasoning_tokens")
                or payload.get("output_tokens_reasoning")
                or 0
            ),
        ),
    }


def _usage_missing_or_zero(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return True
    return all(
        int(payload.get(field) or 0) <= 0
        for field in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
        )
    )


def _extract_usage_from_text_streams(
    stdout_text: str | None,
    stderr_text: str | None,
) -> dict[str, int] | None:
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    total_pattern = re.compile(r"\btotal=\s*(\d[\d,]*)\b", re.IGNORECASE)
    input_pattern = re.compile(r"\binput=\s*(\d[\d,]*)\b", re.IGNORECASE)
    output_pattern = re.compile(r"\boutput=\s*(\d[\d,]*)\b", re.IGNORECASE)
    reasoning_pattern = re.compile(r"\breasoning\s+(\d[\d,]*)\b", re.IGNORECASE)
    cached_paren_pattern = re.compile(r"\(\+\s*(\d[\d,]*)\s+cached\)", re.IGNORECASE)
    cached_named_pattern = re.compile(r"\bcached(?:_input)?=\s*(\d[\d,]*)\b", re.IGNORECASE)
    for stream in (stdout_text or "", stderr_text or ""):
        for raw_line in reversed(stream.splitlines()):
            cleaned_line = ansi_escape.sub("", raw_line).strip()
            if "Token usage:" not in cleaned_line:
                continue
            input_match = input_pattern.search(cleaned_line)
            output_match = output_pattern.search(cleaned_line)
            if input_match is None or output_match is None:
                continue
            cached_match = cached_paren_pattern.search(cleaned_line) or cached_named_pattern.search(
                cleaned_line
            )
            reasoning_match = reasoning_pattern.search(cleaned_line)
            usage = {
                "input_tokens": int(input_match.group(1).replace(",", "")),
                "cached_input_tokens": int(cached_match.group(1).replace(",", ""))
                if cached_match is not None
                else 0,
                "output_tokens": int(output_match.group(1).replace(",", "")),
                "reasoning_tokens": int(reasoning_match.group(1).replace(",", ""))
                if reasoning_match is not None
                else 0,
            }
            total_match = total_pattern.search(cleaned_line)
            if total_match is not None:
                observed_total = int(total_match.group(1).replace(",", ""))
                component_total = (
                    usage["input_tokens"]
                    + usage["cached_input_tokens"]
                    + usage["output_tokens"]
                    + usage["reasoning_tokens"]
                )
                if observed_total <= 0 and component_total <= 0:
                    continue
            if _usage_missing_or_zero(usage):
                continue
            return usage
    return None


def _extract_turn_failed_message(
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]]
) -> str | None:
    for payload in events:
        if payload.get("type") != "turn.failed":
            continue
        error_payload = payload.get("error")
        if isinstance(error_payload, Mapping):
            message = str(
                error_payload.get("message") or error_payload.get("detail") or ""
            ).strip()
            if message:
                return message
        if isinstance(error_payload, str):
            cleaned = error_payload.strip()
            if cleaned:
                return cleaned
    return None


def _summarize_failure_text(stderr_text: str | None, stdout_text: str | None) -> str | None:
    for text in (stderr_text, stdout_text):
        cleaned = str(text or "").strip()
        if cleaned:
            first_line = cleaned.splitlines()[0].strip()
            if first_line:
                return first_line
    return None


def _coerce_nonnegative_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _sum_ints(*values: int | None) -> int | None:
    total = 0
    seen = False
    for value in values:
        if value is None:
            continue
        total += int(value)
        seen = True
    return total if seen else None


def _summarize_codex_events(
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    classify_taskfile_worker_command = _runner_attr("classify_taskfile_worker_command")
    command_execution_count = 0
    reasoning_item_count = 0
    command_execution_commands: list[str] = []
    command_execution_policy_counts: dict[str, int] = {}
    command_execution_policy_by_command: list[dict[str, Any]] = []
    reasoning_item_types: list[str] = []
    seen_commands: set[str] = set()
    seen_reasoning_types: set[str] = set()
    for payload in events:
        if payload.get("type") != "item.completed":
            continue
        item = payload.get("item")
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type == "command_execution":
            command_execution_count += 1
            command_text = str(item.get("command") or "").strip()
            if command_text and command_text not in seen_commands:
                seen_commands.add(command_text)
                command_execution_commands.append(command_text)
                verdict = classify_taskfile_worker_command(
                    command_text,
                    allowed_absolute_roots=allowed_absolute_roots,
                )
                command_execution_policy_counts[verdict.policy] = (
                    int(command_execution_policy_counts.get(verdict.policy) or 0) + 1
                )
                command_execution_policy_by_command.append(
                    {
                        "command": command_text,
                        "allowed": verdict.allowed,
                        "policy": verdict.policy,
                        "reason": verdict.reason,
                    }
                )
            continue
        if item_type == "reasoning":
            reasoning_item_count += 1
            outer_type = str(payload.get("type") or "").strip()
            if outer_type and outer_type not in seen_reasoning_types:
                seen_reasoning_types.add(outer_type)
                reasoning_item_types.append(outer_type)
    return {
        "command_execution_count": command_execution_count,
        "command_execution_commands": command_execution_commands,
        "command_execution_policy_counts": dict(sorted(command_execution_policy_counts.items())),
        "command_execution_policy_by_command": command_execution_policy_by_command,
        "reasoning_item_count": reasoning_item_count,
        "reasoning_item_types": reasoning_item_types,
    }


def _summarize_live_codex_events(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    stage_helper_modules = _runner_attr(
        "_SINGLE_FILE_WORKSPACE_STAGE_HELPER_MODULES",
        (),
    )
    command_item_ids: set[str] = set()
    command_texts: list[str] = []
    reasoning_item_count = 0
    agent_message_count = 0
    turn_completed_count = 0
    last_command: str | None = None
    last_command_repeat_count = 0
    last_completed_command: CodexExecRecentCommandCompletion | None = None
    last_completed_stage_helper_command: CodexExecRecentCommandCompletion | None = None
    for payload in events:
        payload_type = str(payload.get("type") or "").strip()
        if payload_type == "turn.completed":
            turn_completed_count += 1
            continue
        if payload_type not in {"item.started", "item.completed"}:
            continue
        item = payload.get("item")
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "").strip()
        if payload_type == "item.completed" and item_type == "agent_message":
            agent_message_count += 1
            continue
        if item_type == "command_execution":
            item_id = str(item.get("id") or "").strip()
            if item_id:
                command_item_ids.add(item_id)
            command_text = str(item.get("command") or "").strip()
            if command_text:
                command_texts.append(command_text)
                if command_text == last_command:
                    last_command_repeat_count += 1
                else:
                    last_command = command_text
                    last_command_repeat_count = 1
            if payload_type == "item.completed":
                last_completed_command = _summarize_completed_command_item(item)
                if (
                    last_completed_command is not None
                    and str(last_completed_command.python_module or "").strip()
                    in stage_helper_modules
                ):
                    last_completed_stage_helper_command = last_completed_command
            continue
        if payload_type == "item.completed" and item_type == "reasoning":
            reasoning_item_count += 1
    return {
        "command_execution_count": (
            len(command_item_ids) if command_item_ids else len(command_texts)
        ),
        "reasoning_item_count": reasoning_item_count,
        "agent_message_count": agent_message_count,
        "turn_completed_count": turn_completed_count,
        "last_command": last_command,
        "last_command_repeat_count": last_command_repeat_count,
        "last_completed_command": last_completed_command,
        "last_completed_stage_helper_command": last_completed_stage_helper_command,
    }


def _summarize_completed_command_item(
    item: Mapping[str, Any],
) -> CodexExecRecentCommandCompletion | None:
    command_text = str(item.get("command") or "").strip()
    if not command_text:
        return None
    parsed_output = _parse_command_aggregated_output(item.get("aggregated_output"))
    reported_final_status = None
    reported_completed = False
    if isinstance(parsed_output, Mapping):
        reported_final_status = (
            str(parsed_output.get("final_status") or parsed_output.get("status") or "").strip()
            or None
        )
        reported_completed = bool(parsed_output.get("completed")) or (
            reported_final_status == "completed"
        )
    return CodexExecRecentCommandCompletion(
        command=command_text,
        exit_code=_coerce_nonnegative_int(item.get("exit_code")),
        status=str(item.get("status") or "").strip() or None,
        python_module=_extract_python_module_from_command(command_text),
        parsed_output=(dict(parsed_output) if isinstance(parsed_output, Mapping) else None),
        reported_completed=reported_completed,
        reported_final_status=reported_final_status,
    )


def _parse_command_aggregated_output(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    parsed = _parse_possible_json_mapping(cleaned)
    if parsed is not None:
        return parsed
    for line in reversed(cleaned.splitlines()):
        parsed = _parse_possible_json_mapping(line.strip())
        if parsed is not None:
            return parsed
    return None


def _parse_possible_json_mapping(value: str) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _extract_python_module_from_command(command_text: str | None) -> str | None:
    command_tokens_for_watchdog = _runner_attr("_command_tokens_for_watchdog")
    tokens = command_tokens_for_watchdog(command_text)
    if len(tokens) < 3:
        return None
    executable = Path(str(tokens[0] or "")).name.lower()
    if executable not in {"python", "python3"}:
        return None
    if str(tokens[1] or "").strip() != "-m":
        return None
    module = str(tokens[2] or "").strip()
    return module or None


def _live_activity_excerpt(
    value: Any,
    *,
    max_words: int = 10,
    max_chars: int = 96,
) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return None
    words = cleaned.split(" ")
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(".,;:") + "..."
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned or None


def _summarize_live_item_activity(
    *,
    payload_type: str,
    item: Mapping[str, Any],
    workspace_mode: DirectExecWorkspaceMode,
) -> str | None:
    item_type = str(item.get("type") or "").strip()
    if not item_type:
        return None
    if item_type == "command_execution":
        command_excerpt = _live_activity_excerpt(item.get("command"))
        if command_excerpt is None:
            return "Running command" if payload_type == "item.started" else "Ran command"
        if payload_type == "item.started":
            return f"Running `{command_excerpt}`"
        return f"Ran `{command_excerpt}`"
    if item_type == "agent_message":
        text_excerpt = _live_activity_excerpt(item.get("text"))
        if text_excerpt is None:
            return "Agent message" if payload_type == "item.completed" else None
        if workspace_mode == "taskfile" and text_excerpt.startswith("{"):
            return None
        return f"Message: {text_excerpt}"
    if item_type == "reasoning":
        reasoning_excerpt = (
            _live_activity_excerpt(item.get("summary_text"))
            or _live_activity_excerpt(item.get("summary"))
            or _live_activity_excerpt(item.get("text"))
            or _live_activity_excerpt(item.get("delta"))
            or _live_activity_excerpt(item.get("content"))
        )
        if reasoning_excerpt is not None:
            return f"Reasoning: {reasoning_excerpt}"
        return "Reasoning"
    if item_type == "file_change":
        changes = item.get("changes")
        if isinstance(changes, list) and changes:
            first_change = changes[0] if isinstance(changes[0], Mapping) else None
            path_excerpt = (
                _live_activity_excerpt(first_change.get("path")) if first_change else None
            )
            if path_excerpt is not None:
                return f"Updated {path_excerpt}"
        return "Updated files"
    descriptor = (
        _live_activity_excerpt(item.get("text"))
        or _live_activity_excerpt(item.get("summary"))
        or _live_activity_excerpt(item.get("delta"))
        or _live_activity_excerpt(item.get("content"))
        or _live_activity_excerpt(item.get("query"))
        or _live_activity_excerpt(item.get("path"))
        or _live_activity_excerpt(item.get("url"))
        or _live_activity_excerpt(item.get("title"))
    )
    verb = "Working on" if payload_type == "item.started" else "Completed"
    if descriptor is not None:
        return f"{verb} `{item_type}`: {descriptor}"
    return f"{verb} `{item_type}`"


def _summarize_live_activity(
    *,
    events: Sequence[Mapping[str, Any]],
    workspace_mode: DirectExecWorkspaceMode,
) -> str | None:
    lifecycle_fallback: str | None = None
    for payload in reversed(list(events)):
        payload_type = str(payload.get("type") or "").strip()
        if not payload_type:
            continue
        if "reasoning_summary" in payload_type or payload_type.startswith("response.reasoning"):
            excerpt = (
                _live_activity_excerpt(payload.get("summary_text"))
                or _live_activity_excerpt(payload.get("summary"))
                or _live_activity_excerpt(payload.get("text"))
                or _live_activity_excerpt(payload.get("delta"))
                or _live_activity_excerpt(payload.get("content"))
            )
            if excerpt is not None:
                return f"Reasoning summary: {excerpt}"
            continue
        if payload_type in {"thread.started", "thread.completed", "turn.completed", "turn.failed"}:
            if lifecycle_fallback is None:
                if payload_type == "thread.started":
                    lifecycle_fallback = "Session started"
                elif payload_type == "thread.completed":
                    lifecycle_fallback = "Session completed"
                elif payload_type == "turn.completed":
                    lifecycle_fallback = "Turn completed"
                elif payload_type == "turn.failed":
                    error_payload = payload.get("error")
                    error_excerpt = None
                    if isinstance(error_payload, Mapping):
                        error_excerpt = _live_activity_excerpt(
                            error_payload.get("message") or error_payload.get("detail")
                        )
                    else:
                        error_excerpt = _live_activity_excerpt(error_payload)
                    lifecycle_fallback = (
                        f"Turn failed: {error_excerpt}"
                        if error_excerpt is not None
                        else "Turn failed"
                    )
            continue
        if payload_type not in {"item.started", "item.completed"}:
            continue
        item = payload.get("item")
        if not isinstance(item, Mapping):
            continue
        summary = _summarize_live_item_activity(
            payload_type=payload_type,
            item=item,
            workspace_mode=workspace_mode,
        )
        if summary is not None:
            return summary
    return lifecycle_fallback


def _pathological_flags_for_row(
    *,
    command_execution_count: int,
    reasoning_item_count: int,
    wrapper_overhead_tokens: int,
    visible_input_tokens: int,
    visible_output_tokens: int,
) -> list[str]:
    flags: list[str] = []
    if command_execution_count > 0:
        flags.append("command_execution_detected")
    if reasoning_item_count > 0:
        flags.append("reasoning_items_detected")
    visible_total = max(0, int(visible_input_tokens) + int(visible_output_tokens))
    if wrapper_overhead_tokens > visible_total and wrapper_overhead_tokens > 0:
        flags.append("wrapper_overhead_dominant")
    return flags


def _summary_pathological_flags(summary: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    if int(summary.get("preflight_rejected_shard_count") or 0) > 0:
        flags.append("preflight_rejections_detected")
    if int(summary.get("watchdog_killed_shard_count") or 0) > 0:
        flags.append("watchdog_kills_detected")
    if int(summary.get("command_executing_shard_count") or 0) > 0:
        flags.append("command_execution_detected")
    if int(summary.get("reasoning_heavy_shard_count") or 0) > 0:
        flags.append("reasoning_heavy_detected")
    if int(summary.get("invalid_output_shard_count") or 0) > 0:
        flags.append("invalid_output_detected")
    tokens_total = int(summary.get("tokens_total") or 0)
    invalid_tokens_total = int(summary.get("invalid_output_tokens_total") or 0)
    if tokens_total > 0 and invalid_tokens_total * 2 >= tokens_total:
        flags.append("majority_invalid_output_spend")
    return flags


def format_watchdog_command_reason_detail(
    *,
    stage_label: str,
    last_command: str | None,
) -> str:
    base = f"{stage_label} attempted tool use"
    cleaned_command = str(last_command or "").strip()
    if not cleaned_command:
        return base
    if len(cleaned_command) > 160:
        cleaned_command = cleaned_command[:157].rstrip() + "..."
    return f"{base}: {cleaned_command}"


def format_watchdog_command_loop_reason_detail(
    *,
    stage_label: str,
    snapshot: CodexExecLiveSnapshot,
) -> str:
    base = f"{stage_label} spent too many shell commands without reaching final output"
    cleaned_command = str(snapshot.last_command or "").strip()
    parts = [base, f"command_count={int(snapshot.command_execution_count or 0)}"]
    if int(snapshot.last_command_repeat_count or 0) > 0:
        parts.append(f"last_command_repeat_count={int(snapshot.last_command_repeat_count or 0)}")
    if cleaned_command:
        if len(cleaned_command) > 160:
            cleaned_command = cleaned_command[:157].rstrip() + "..."
        parts.append(f"last_command={cleaned_command}")
    return "; ".join(parts)


def should_terminate_workspace_command_loop(
    *,
    snapshot: CodexExecLiveSnapshot,
    max_command_count: int | None = None,
    max_repeat_count: int | None = None,
    recent_output_progress: bool = False,
    completed_output_count: int = 0,
) -> bool:
    if max_command_count is None:
        max_command_count = _runner_attr("_WORKSPACE_COMMAND_LOOP_MAX_COMMAND_COUNT", 180)
    if max_repeat_count is None:
        max_repeat_count = _runner_attr("_WORKSPACE_COMMAND_LOOP_MAX_REPEAT_COUNT", 12)
    if int(snapshot.command_execution_count or 0) <= 0:
        return False
    if snapshot.has_final_agent_message:
        return False
    progress_command_bonus = min(
        180,
        max(0, int(completed_output_count or 0)) * 20 + (80 if recent_output_progress else 0),
    )
    progress_repeat_bonus = min(
        12,
        max(0, int(completed_output_count or 0)) + (6 if recent_output_progress else 0),
    )
    effective_max_command_count = max(1, int(max_command_count)) + progress_command_bonus
    effective_max_repeat_count = max(1, int(max_repeat_count)) + progress_repeat_bonus
    if int(snapshot.command_execution_count or 0) >= effective_max_command_count:
        return True
    return int(snapshot.last_command_repeat_count or 0) >= effective_max_repeat_count
