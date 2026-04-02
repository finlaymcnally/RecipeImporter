from __future__ import annotations
import csv
import datetime as dt
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, cast
from cookimport.core.slug import slugify_name
from cookimport.runs import (
    KNOWLEDGE_MANIFEST_FILE_NAME,
    RECIPE_MANIFEST_FILE_NAME,
    stage_label,
    stage_artifact_stem,
)
from cookimport.runs.stage_names import canonical_stage_key
PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION = "prompt_run_descriptor.v1"
PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION = "prompt_stage_descriptor.v1"
PROMPT_CALL_RECORD_SCHEMA_VERSION = "prompt_call_record.v1"
PROMPT_LOG_SUMMARY_SCHEMA_VERSION = "prompt_log_summary.v1"
PROMPT_ACTIVITY_TRACE_SCHEMA_VERSION = "prompt_activity_trace.v1"
PROMPT_ACTIVITY_TRACE_SUMMARY_SCHEMA_VERSION = "prompt_activity_trace_summary.v1"
PROMPT_LOG_SUMMARY_JSON_NAME = "prompt_log_summary.json"
PROMPT_TYPE_SAMPLES_MD_NAME = "prompt_type_samples_from_full_prompt_log.md"
ACTIVITY_TRACES_DIR_NAME = "activity_traces"
ACTIVITY_TRACE_SUMMARY_JSONL_NAME = "activity_trace_summary.jsonl"
ACTIVITY_TRACE_SUMMARY_MD_NAME = "activity_trace_summary.md"
_CODEXFARM_STAGE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "stage_key": "recipe_refine",
        "stage_order": 1,
        "stage_label": stage_label("recipe_refine"),
        "stage_artifact_stem": stage_artifact_stem("recipe_refine"),
        "default_pipeline_id": "recipe.correction.compact.v1",
        "manifest_name": RECIPE_MANIFEST_FILE_NAME,
    },
    {
        "stage_key": "nonrecipe_finalize",
        "stage_order": 4,
        "stage_label": stage_label("nonrecipe_finalize"),
        "stage_artifact_stem": stage_artifact_stem("nonrecipe_finalize"),
        "default_pipeline_id": "recipe.knowledge.packet.v1",
        "manifest_name": KNOWLEDGE_MANIFEST_FILE_NAME,
    },
)
_CODEXFARM_STAGE_SPEC_BY_KEY: dict[str, dict[str, Any]] = {
    str(spec["stage_key"]): spec for spec in _CODEXFARM_STAGE_SPECS
}
_PROMPT_STAGE_LABELS_BY_KEY = {
    **{
        str(spec["stage_key"]): str(spec["stage_label"])
        for spec in _CODEXFARM_STAGE_SPECS
    },
    "recipe_correction": stage_label("recipe_refine"),
    "knowledge": stage_label("nonrecipe_finalize"),
}
_TEXT_ATTACHMENT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".csv",
}
_ACTIVITY_TRACE_MAX_ENTRIES = 25
_ACTIVITY_TRACE_SUMMARY_ENTRY_LIMIT = 3
__all__ = [
    "ACTIVITY_TRACES_DIR_NAME",
    "ACTIVITY_TRACE_SUMMARY_JSONL_NAME",
    "ACTIVITY_TRACE_SUMMARY_MD_NAME",
    "PROMPT_CALL_RECORD_SCHEMA_VERSION",
    "PROMPT_ACTIVITY_TRACE_SCHEMA_VERSION",
    "PROMPT_ACTIVITY_TRACE_SUMMARY_SCHEMA_VERSION",
    "PROMPT_LOG_SUMMARY_JSON_NAME",
    "PROMPT_LOG_SUMMARY_SCHEMA_VERSION",
    "PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION",
    "PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION",
    "PROMPT_TYPE_SAMPLES_MD_NAME",
    "build_codex_farm_activity_trace_summaries",
    "PromptCallRecord",
    "PromptRunDescriptorDiscoverer",
    "PromptRunDescriptor",
    "PromptStageDescriptor",
    "build_codex_farm_prompt_response_log",
    "build_prompt_response_log",
    "build_codex_farm_prompt_type_samples_markdown",
    "discover_prompt_run_descriptors",
    "discover_codex_exec_prompt_run_descriptors",
    "render_prompt_artifacts_from_descriptors",
    "summarize_prompt_log",
    "write_prompt_log_summary",
]

def _load_jsonl_events(*, events_path: Path | None) -> list[dict[str, Any]]:
    if events_path is None or not events_path.exists() or not events_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for raw_line in events_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parsed = _parse_json_text(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
    except OSError:
        return []
    return rows
def _load_message_text(*, message_path: Path | None) -> str | None:
    if message_path is None or not message_path.exists() or not message_path.is_file():
        return None
    parsed = _parse_json_text(_safe_read_text(message_path))
    if isinstance(parsed, dict):
        text = _clean_text(parsed.get("text"))
        if text is not None:
            return text
    raw_text = _safe_read_text(message_path).strip()
    return raw_text or None
def _activity_excerpt(value: Any, *, max_chars: int = 220) -> str | None:
    if isinstance(value, str):
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            return None
        if len(cleaned) > max_chars:
            return cleaned[: max_chars - 3].rstrip() + "..."
        return cleaned
    return None
def _activity_path_excerpt(value: Any, *, max_parts: int = 4, max_chars: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    path_parts = [part for part in Path(cleaned).parts if part not in {"/", "\\"}]
    if path_parts and len(path_parts) > max_parts:
        cleaned = ".../" + "/".join(path_parts[-max_parts:])
    return _activity_excerpt(cleaned, max_chars=max_chars)
def _extract_visible_reasoning_text(payload: Mapping[str, Any]) -> str | None:
    for key in ("summary_text", "summary", "text", "delta", "content"):
        excerpt = _activity_excerpt(payload.get(key))
        if excerpt is not None:
            return excerpt
    return None
def _summarize_activity_entry_lines(
    entries: Sequence[Mapping[str, Any]],
    *,
    max_entries: int = _ACTIVITY_TRACE_SUMMARY_ENTRY_LIMIT,
) -> list[str]:
    lines: list[str] = []
    for entry in entries[:max_entries]:
        summary = _clean_text(entry.get("summary")) if isinstance(entry, Mapping) else None
        if summary is not None:
            lines.append(summary)
    return lines
def _build_activity_trace_from_events(
    *,
    events: Sequence[Mapping[str, Any]],
    last_message_text: str | None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    reasoning_events: list[dict[str, Any]] = []
    action_event_types: list[str] = []
    reasoning_event_types: list[str] = []
    seen_action_event_types: set[str] = set()
    seen_reasoning_event_types: set[str] = set()
    command_count = 0
    agent_message_count = 0
    reasoning_event_count = 0
    lifecycle_event_count = 0

    def _append_entry(entry: dict[str, Any]) -> None:
        if len(entries) < _ACTIVITY_TRACE_MAX_ENTRIES:
            entries.append(entry)

    def _append_visible_item_entry(item: Mapping[str, Any], *, payload_type: str) -> None:
        item_type = str(item.get("type") or "").strip()
        if not item_type:
            return
        if item_type not in seen_action_event_types:
            seen_action_event_types.add(item_type)
            action_event_types.append(item_type)
        if item_type == "file_change":
            changes = item.get("changes")
            normalized_changes = (
                [change for change in changes if isinstance(change, Mapping)]
                if isinstance(changes, list)
                else []
            )
            if not normalized_changes:
                _append_entry(
                    {
                        "kind": "file_change",
                        "event_type": payload_type,
                        "summary": "Updated files",
                    }
                )
                return
            verb_map = {
                "add": "Created",
                "create": "Created",
                "delete": "Deleted",
                "remove": "Deleted",
                "rename": "Renamed",
                "update": "Updated",
            }
            if len(normalized_changes) == 1:
                change = normalized_changes[0]
                raw_kind = _clean_text(change.get("kind")) or "update"
                summary_verb = verb_map.get(raw_kind, raw_kind.capitalize())
                path_excerpt = _activity_path_excerpt(change.get("path"))
                summary = (
                    f"{summary_verb} `{path_excerpt}`"
                    if path_excerpt is not None
                    else f"{summary_verb} file"
                )
                _append_entry(
                    {
                        "kind": "file_change",
                        "event_type": payload_type,
                        "summary": summary,
                        "changes": [dict(change)],
                    }
                )
                return
            rendered_changes: list[str] = []
            for change in normalized_changes[:3]:
                raw_kind = _clean_text(change.get("kind")) or "update"
                summary_verb = verb_map.get(raw_kind, raw_kind.capitalize())
                path_excerpt = _activity_path_excerpt(change.get("path"))
                if path_excerpt is not None:
                    rendered_changes.append(f"{summary_verb.lower()} `{path_excerpt}`")
                else:
                    rendered_changes.append(summary_verb.lower())
            if len(normalized_changes) > 3:
                rendered_changes.append(f"... ({len(normalized_changes) - 3} more)")
            _append_entry(
                {
                    "kind": "file_change",
                    "event_type": payload_type,
                    "summary": "File changes: " + ", ".join(rendered_changes),
                    "changes": [dict(change) for change in normalized_changes],
                }
            )
            return

        descriptor = (
            _activity_excerpt(item.get("text"))
            or _activity_excerpt(item.get("summary"))
            or _activity_excerpt(item.get("delta"))
            or _activity_excerpt(item.get("content"))
            or _activity_excerpt(item.get("query"))
            or _activity_path_excerpt(item.get("path"))
            or _activity_excerpt(item.get("url"))
            or _activity_excerpt(item.get("title"))
        )
        summary = (
            f"Completed `{item_type}`: {descriptor}"
            if descriptor is not None
            else f"Completed `{item_type}`"
        )
        entry: dict[str, Any] = {
            "kind": "visible_item",
            "event_type": payload_type,
            "item_type": item_type,
            "summary": summary,
        }
        path_excerpt = _activity_path_excerpt(item.get("path"))
        if path_excerpt is not None:
            entry["path"] = path_excerpt
        query_excerpt = _activity_excerpt(item.get("query"))
        if query_excerpt is not None:
            entry["query"] = query_excerpt
        _append_entry(entry)

    for event in events:
        payload_type = str(event.get("type") or "").strip()
        if not payload_type:
            continue
        if payload_type in {"thread.started", "thread.completed", "turn.completed", "turn.failed"}:
            lifecycle_event_count += 1
            if payload_type not in seen_action_event_types:
                seen_action_event_types.add(payload_type)
                action_event_types.append(payload_type)
            if payload_type == "thread.started":
                _append_entry(
                    {
                        "kind": "lifecycle",
                        "event_type": payload_type,
                        "summary": "Session started",
                    }
                )
            elif payload_type == "turn.completed":
                _append_entry(
                    {
                        "kind": "lifecycle",
                        "event_type": payload_type,
                        "summary": "Turn completed",
                    }
                )
            elif payload_type == "turn.failed":
                error_payload = event.get("error")
                error_excerpt = None
                if isinstance(error_payload, Mapping):
                    error_excerpt = _activity_excerpt(
                        error_payload.get("message") or error_payload.get("detail")
                    )
                elif isinstance(error_payload, str):
                    error_excerpt = _activity_excerpt(error_payload)
                summary = (
                    f"Turn failed: {error_excerpt}"
                    if error_excerpt is not None
                    else "Turn failed"
                )
                _append_entry(
                    {
                        "kind": "lifecycle",
                        "event_type": payload_type,
                        "summary": summary,
                    }
                )
            continue
        if "reasoning_summary" in payload_type or payload_type.startswith("response.reasoning"):
            reasoning_event_count += 1
            if payload_type not in seen_reasoning_event_types:
                seen_reasoning_event_types.add(payload_type)
                reasoning_event_types.append(payload_type)
            reasoning_payload = dict(event)
            reasoning_events.append(reasoning_payload)
            excerpt = _extract_visible_reasoning_text(reasoning_payload)
            if excerpt is not None:
                _append_entry(
                    {
                        "kind": "reasoning_summary",
                        "event_type": payload_type,
                        "summary": f"Reasoning summary: {excerpt}",
                    }
                )
            continue
        if payload_type not in {"item.started", "item.completed"}:
            continue
        item = event.get("item")
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "").strip()
        if not item_type:
            continue
        if payload_type == "item.completed" and item_type == "command_execution":
            command_count += 1
            if item_type not in seen_action_event_types:
                seen_action_event_types.add(item_type)
                action_event_types.append(item_type)
            command_text = _activity_excerpt(item.get("command"), max_chars=260)
            exit_code = _coerce_int(item.get("exit_code"))
            if command_text is None:
                summary = "Ran command"
            elif exit_code is not None and exit_code != 0:
                summary = f"Ran `{command_text}` (exit {exit_code})"
            else:
                summary = f"Ran `{command_text}`"
            _append_entry(
                {
                    "kind": "command",
                    "event_type": payload_type,
                    "summary": summary,
                    "command": _clean_text(item.get("command")),
                    "exit_code": exit_code,
                }
            )
            continue
        if payload_type == "item.completed" and item_type == "agent_message":
            agent_message_count += 1
            if item_type not in seen_action_event_types:
                seen_action_event_types.add(item_type)
                action_event_types.append(item_type)
            excerpt = _activity_excerpt(item.get("text"))
            summary = (
                f"Agent message: {excerpt}"
                if excerpt is not None
                else "Agent message emitted"
            )
            _append_entry(
                {
                    "kind": "agent_message",
                    "event_type": payload_type,
                    "summary": summary,
                    "excerpt": excerpt,
                }
            )
            continue
        if payload_type == "item.completed" and item_type == "reasoning":
            reasoning_event_count += 1
            if item_type not in seen_reasoning_event_types:
                seen_reasoning_event_types.add(item_type)
                reasoning_event_types.append(item_type)
            reasoning_payload = dict(item)
            reasoning_payload.setdefault("type", item_type)
            reasoning_events.append(reasoning_payload)
            excerpt = _extract_visible_reasoning_text(reasoning_payload)
            if excerpt is not None:
                _append_entry(
                    {
                        "kind": "reasoning_summary",
                        "event_type": payload_type,
                        "summary": f"Reasoning summary: {excerpt}",
                    }
                )
            continue
        if payload_type == "item.completed":
            _append_visible_item_entry(item, payload_type=payload_type)

    if agent_message_count <= 0 and last_message_text is not None:
        agent_message_count = 1
        excerpt = _activity_excerpt(last_message_text)
        _append_entry(
            {
                "kind": "agent_message",
                "event_type": "last_message.json",
                "summary": (
                    f"Final agent message: {excerpt}"
                    if excerpt is not None
                    else "Final agent message captured"
                ),
                "excerpt": excerpt,
            }
        )

    return {
        "event_count": len(events),
        "command_count": command_count,
        "agent_message_count": agent_message_count,
        "reasoning_event_count": reasoning_event_count,
        "lifecycle_event_count": lifecycle_event_count,
        "action_event_count": command_count + agent_message_count + lifecycle_event_count,
        "action_event_types": action_event_types,
        "reasoning_event_types": reasoning_event_types,
        "reasoning_events": reasoning_events,
        "entries": entries,
        "entries_truncated": len(entries) >= _ACTIVITY_TRACE_MAX_ENTRIES,
    }
def _export_prompt_activity_trace(
    *,
    row_payload: dict[str, Any],
    prompts_dir: Path,
    repo_root: Path,
) -> dict[str, Any] | None:
    request_telemetry = (
        row_payload.get("request_telemetry")
        if isinstance(row_payload.get("request_telemetry"), dict)
        else {}
    )
    call_id = _clean_text(row_payload.get("call_id")) or "call"
    stage_key = _clean_text(row_payload.get("stage_key"))
    events_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("events_path")),
        repo_root=repo_root,
    )
    last_message_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("last_message_path")),
        repo_root=repo_root,
    )
    usage_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("usage_path")),
        repo_root=repo_root,
    )
    live_status_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("live_status_path")),
        repo_root=repo_root,
    )
    workspace_manifest_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("workspace_manifest_path")),
        repo_root=repo_root,
    )
    stdout_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("stdout_path")),
        repo_root=repo_root,
    )
    stderr_path = _resolve_saved_artifact_path(
        raw_path=_clean_text(request_telemetry.get("stderr_path")),
        repo_root=repo_root,
    )
    events = _load_jsonl_events(events_path=events_path)
    last_message_text = _load_message_text(message_path=last_message_path)
    if events:
        computed = _build_activity_trace_from_events(
            events=events,
            last_message_text=last_message_text,
        )
    elif last_message_text is not None:
        computed = _build_activity_trace_from_events(events=(), last_message_text=last_message_text)
    else:
        return None

    activity_traces_dir = prompts_dir / ACTIVITY_TRACES_DIR_NAME
    activity_traces_dir.mkdir(parents=True, exist_ok=True)
    exported_path = activity_traces_dir / f"{slugify_name(call_id)}.json"
    payload = {
        "schema_version": PROMPT_ACTIVITY_TRACE_SCHEMA_VERSION,
        "path": str(exported_path),
        "available": True,
        "call_id": call_id,
        "run_id": _clean_text(row_payload.get("run_id")),
        "recipe_id": _clean_text(row_payload.get("recipe_id")),
        "stage_key": stage_key,
        "stage_label": _clean_text(row_payload.get("stage_label")),
        "model": _clean_text(row_payload.get("model"))
        or _clean_text(request_telemetry.get("model")),
        "reasoning_effort": _clean_text(request_telemetry.get("reasoning_effort"))
        or _clean_text((row_payload.get("decoding_params") or {}).get("reasoning_effort"))
        if isinstance(row_payload.get("decoding_params"), dict)
        else _clean_text(request_telemetry.get("reasoning_effort")),
        "task_id": _clean_text(request_telemetry.get("task_id")),
        "worker_id": _clean_text(row_payload.get("runtime_worker_id"))
        or _clean_text(request_telemetry.get("worker_id")),
        "runtime_shard_id": _clean_text(row_payload.get("runtime_shard_id"))
        or _clean_text(request_telemetry.get("shard_id")),
        "source_events_path": str(events_path) if events_path is not None else None,
        "source_last_message_path": (
            str(last_message_path) if last_message_path is not None else None
        ),
        "source_usage_path": str(usage_path) if usage_path is not None else None,
        "source_live_status_path": (
            str(live_status_path) if live_status_path is not None else None
        ),
        "source_workspace_manifest_path": (
            str(workspace_manifest_path) if workspace_manifest_path is not None else None
        ),
        "source_stdout_path": str(stdout_path) if stdout_path is not None else None,
        "source_stderr_path": str(stderr_path) if stderr_path is not None else None,
        **computed,
    }
    exported_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload
def _resolve_prompt_local_activity_trace_path(*, raw_path: str | None, prompts_dir: Path) -> Path | None:
    cleaned = _clean_text(raw_path)
    if cleaned is None:
        return None
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = (prompts_dir / candidate).resolve(strict=False)
    return candidate.resolve(strict=False)
def _load_exported_activity_trace_payload(
    *,
    trace_path: Path | None,
) -> dict[str, Any] | None:
    if trace_path is None or not trace_path.exists() or not trace_path.is_file():
        return None
    parsed = _parse_json_text(_safe_read_text(trace_path))
    if not isinstance(parsed, dict):
        return None
    return dict(parsed)
def _effective_activity_trace_payload(
    *,
    row: Mapping[str, Any],
    prompts_dir: Path,
) -> dict[str, Any]:
    row_payload = row.get("activity_trace") if isinstance(row.get("activity_trace"), dict) else {}
    request_telemetry = (
        row.get("request_telemetry") if isinstance(row.get("request_telemetry"), dict) else {}
    )
    raw_path = _clean_text(row_payload.get("path")) or _clean_text(
        request_telemetry.get("activity_trace_path")
    )
    exported_path = _resolve_prompt_local_activity_trace_path(raw_path=raw_path, prompts_dir=prompts_dir)
    exported_payload = _load_exported_activity_trace_payload(trace_path=exported_path)
    if isinstance(exported_payload, dict):
        return exported_payload
    return dict(row_payload) if isinstance(row_payload, Mapping) else {}
def _extract_reasoning_excerpt(
    reasoning_events: list[dict[str, Any]],
    *,
    max_events: int = 3,
    max_chars: int = 3000,
) -> str | None:
    if not reasoning_events:
        return None
    snippets: list[str] = []
    for event in reasoning_events[:max_events]:
        if not isinstance(event, dict):
            continue
        for key in ("summary_text", "summary", "text", "delta", "content"):
            value = event.get(key)
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    snippets.append(cleaned)
                    break
    if snippets:
        joined = "\n\n".join(snippets)
        if len(joined) > max_chars:
            return joined[: max_chars - 3].rstrip() + "..."
        return joined
    try:
        serialized = json.dumps(
            reasoning_events[:max_events],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    except TypeError:
        return None
    if len(serialized) > max_chars:
        return serialized[: max_chars - 3].rstrip() + "..."
    return serialized
def build_codex_farm_activity_trace_summaries(
    *,
    full_prompt_log_path: Path,
    output_jsonl_path: Path,
    output_md_path: Path,
    examples_per_stage: int = 3,
) -> tuple[Path | None, Path | None]:
    rows = _load_prompt_rows(full_prompt_log_path)
    if not rows:
        output_jsonl_path.unlink(missing_ok=True)
        output_md_path.unlink(missing_ok=True)
        return None, None

    summary_rows: list[dict[str, Any]] = []
    stage_summary: dict[str, dict[str, Any]] = {}
    stage_examples: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        stage_metadata = _prompt_stage_metadata_from_row(row)
        stage_key = str(stage_metadata.get("heading_key") or stage_metadata.get("stage_key") or "stage")
        stage_label = str(stage_metadata.get("label") or "Prompt Stage")
        activity_trace_payload = _effective_activity_trace_payload(
            row=row,
            prompts_dir=full_prompt_log_path.parent,
        )
        activity_trace_path = _clean_text(activity_trace_payload.get("path"))
        activity_trace_exists = bool(
            activity_trace_path and Path(activity_trace_path).exists()
        )
        trace_available = bool(activity_trace_payload.get("available"))
        command_count = _coerce_int(activity_trace_payload.get("command_count")) or 0
        agent_message_count = (
            _coerce_int(activity_trace_payload.get("agent_message_count")) or 0
        )
        reasoning_event_count = (
            _coerce_int(activity_trace_payload.get("reasoning_event_count")) or 0
        )
        event_count = _coerce_int(activity_trace_payload.get("event_count")) or 0
        entries = activity_trace_payload.get("entries")
        normalized_entries = (
            [dict(entry) for entry in entries if isinstance(entry, Mapping)]
            if isinstance(entries, list)
            else []
        )
        entry_excerpt_lines = _summarize_activity_entry_lines(
            normalized_entries,
            max_entries=_ACTIVITY_TRACE_SUMMARY_ENTRY_LIMIT,
        )
        summary_row = {
            "schema_version": PROMPT_ACTIVITY_TRACE_SUMMARY_SCHEMA_VERSION,
            "run_id": row.get("run_id"),
            "call_id": row.get("call_id"),
            "recipe_id": row.get("recipe_id"),
            "stage_key": stage_key,
            "stage_label": stage_label,
            "stage_order": stage_metadata.get("stage_order"),
            "activity_trace_path": activity_trace_path,
            "activity_trace_exists": activity_trace_exists,
            "activity_trace_available": trace_available,
            "process_run_id": row.get("process_run_id"),
            "event_count": event_count,
            "command_count": command_count,
            "agent_message_count": agent_message_count,
            "reasoning_event_count": reasoning_event_count,
            "reasoning_event_types": list(
                activity_trace_payload.get("reasoning_event_types") or []
            )
            if isinstance(activity_trace_payload.get("reasoning_event_types"), list)
            else [],
            "action_event_count": _coerce_int(activity_trace_payload.get("action_event_count")),
            "action_event_types": list(
                activity_trace_payload.get("action_event_types") or []
            )
            if isinstance(activity_trace_payload.get("action_event_types"), list)
            else [],
            "source_events_path": _clean_text(activity_trace_payload.get("source_events_path")),
            "entry_excerpt_lines": entry_excerpt_lines,
        }
        summary_rows.append(summary_row)

        stage_state = stage_summary.setdefault(
            stage_key,
            {
                "stage_label": stage_label,
                "stage_order": int(stage_metadata.get("stage_order") or 999),
                "rows": 0,
                "activity_trace_present": 0,
                "activity_trace_exists": 0,
                "activity_trace_available": 0,
                "command_rows": 0,
                "agent_message_rows": 0,
                "reasoning_event_rows": 0,
            },
        )
        stage_state["rows"] += 1
        if activity_trace_path is not None:
            stage_state["activity_trace_present"] += 1
        if activity_trace_exists:
            stage_state["activity_trace_exists"] += 1
        if trace_available:
            stage_state["activity_trace_available"] += 1
        if command_count > 0:
            stage_state["command_rows"] += 1
        if agent_message_count > 0:
            stage_state["agent_message_rows"] += 1
        if reasoning_event_count and reasoning_event_count > 0:
            stage_state["reasoning_event_rows"] += 1

        stage_examples.setdefault(stage_key, [])
        if len(stage_examples[stage_key]) < examples_per_stage:
            stage_examples[stage_key].append(summary_row)

    output_jsonl_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in summary_rows),
        encoding="utf-8",
    )

    total_rows = len(summary_rows)
    total_activity_trace_present = sum(
        int(stage["activity_trace_present"]) for stage in stage_summary.values()
    )
    total_activity_trace_exists = sum(
        int(stage["activity_trace_exists"]) for stage in stage_summary.values()
    )
    total_activity_trace_available = sum(
        int(stage["activity_trace_available"]) for stage in stage_summary.values()
    )
    total_command_rows = sum(int(stage["command_rows"]) for stage in stage_summary.values())
    total_agent_message_rows = sum(
        int(stage["agent_message_rows"]) for stage in stage_summary.values()
    )
    total_reasoning_event_rows = sum(
        int(stage["reasoning_event_rows"]) for stage in stage_summary.values()
    )
    generated_timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    lines: list[str] = [
        "# Codex Exec Activity Trace Summary",
        "",
        f"Generated: {generated_timestamp}",
        "Source:",
        f"- {full_prompt_log_path}",
        "",
        "Overall:",
        f"- total_rows: `{total_rows}`",
        f"- rows_with_activity_trace: `{total_activity_trace_present}`",
        f"- rows_with_existing_activity_trace_file: `{total_activity_trace_exists}`",
        f"- rows_with_available_activity_trace_payload: `{total_activity_trace_available}`",
        f"- rows_with_commands: `{total_command_rows}`",
        f"- rows_with_agent_messages: `{total_agent_message_rows}`",
        f"- rows_with_reasoning_events: `{total_reasoning_event_rows}`",
        "",
    ]
    for stage_key, stage_state in sorted(
        stage_summary.items(),
        key=lambda item: (
            int(item[1].get("stage_order") or 999),
            item[0],
        ),
    ):
        lines.extend(
            [
                f"## {stage_key} ({stage_state['stage_label']})",
                "",
                f"- rows: `{stage_state['rows']}`",
                f"- rows_with_activity_trace: `{stage_state['activity_trace_present']}`",
                f"- rows_with_existing_activity_trace_file: `{stage_state['activity_trace_exists']}`",
                f"- rows_with_available_activity_trace_payload: `{stage_state['activity_trace_available']}`",
                f"- rows_with_commands: `{stage_state['command_rows']}`",
                f"- rows_with_agent_messages: `{stage_state['agent_message_rows']}`",
                f"- rows_with_reasoning_events: `{stage_state['reasoning_event_rows']}`",
                "",
                "### Sample Rows",
                "",
            ]
        )
        examples = stage_examples.get(stage_key, [])
        if not examples:
            lines.append("_No rows captured for this stage._")
            lines.append("")
            continue
        for example in examples:
            lines.append(f"- call_id: `{example.get('call_id') or '<unknown>'}`")
            lines.append(f"  recipe_id: `{example.get('recipe_id') or '<unknown>'}`")
            lines.append(
                f"  activity_trace_exists: `{example.get('activity_trace_exists')}`"
            )
            lines.append(f"  command_count: `{example.get('command_count')}`")
            lines.append(
                f"  agent_message_count: `{example.get('agent_message_count')}`"
            )
            lines.append(
                f"  reasoning_event_count: `{example.get('reasoning_event_count')}`"
            )
            activity_trace_path = _clean_text(example.get("activity_trace_path"))
            if activity_trace_path is not None:
                lines.append(f"  activity_trace_path: `{activity_trace_path}`")
            excerpt_lines = example.get("entry_excerpt_lines")
            if isinstance(excerpt_lines, list) and excerpt_lines:
                lines.append("  sample_entries:")
                for excerpt_line in excerpt_lines:
                    lines.append(f"  - {excerpt_line}")
            lines.append("")

    output_md_path.write_text("\n".join(lines), encoding="utf-8")
    return output_jsonl_path, output_md_path
