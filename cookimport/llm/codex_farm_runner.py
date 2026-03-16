from __future__ import annotations

import csv
import json
import logging
import os
import re
import shlex
import subprocess
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

logger = logging.getLogger(__name__)
_CODEX_FARM_PROGRESS_PREFIX = "__codex_farm_progress__ "
_CODEX_FARM_RECIPE_MODE_ENV = "COOKIMPORT_CODEX_FARM_RECIPE_MODE"
_CODEX_FARM_RECIPE_MODE_EXTRACT = "extract"
_CODEX_FARM_RECIPE_MODE_BENCHMARK = "benchmark"
_BENCHMARK_RECOVERABLE_PARTIAL_MAX_MISSING_OUTPUTS = 3
_BENCHMARK_RECOVERABLE_PARTIAL_MIN_SUCCESS_RATIO = 0.8
_RUNTIME_AGENTIC_FLAG_PREFIXES = (
    "--approval",
    "--sandbox",
    "--tool",
    "--mcp",
)


class CodexFarmRunnerError(RuntimeError):
    """Raised when codex-farm subprocess execution fails."""


@dataclass(frozen=True)
class CodexFarmPipelineRunResult:
    """Structured metadata returned by one codex-farm `process` invocation."""

    pipeline_id: str
    run_id: str | None
    subprocess_exit_code: int
    process_exit_code: int | None
    output_schema_path: str | None
    process_payload: dict[str, Any] | None
    telemetry_report: dict[str, Any] | None = None
    autotune_report: dict[str, Any] | None = None
    telemetry: dict[str, Any] | None = None
    runtime_mode_audit: dict[str, Any] | None = None
    error_summary: str | None = None

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "run_id": self.run_id,
            "subprocess_exit_code": self.subprocess_exit_code,
            "process_exit_code": self.process_exit_code,
            "output_schema_path": self.output_schema_path,
            "process_payload": dict(self.process_payload) if self.process_payload is not None else None,
            "telemetry_report": (
                dict(self.telemetry_report) if self.telemetry_report is not None else None
            ),
            "autotune_report": (
                dict(self.autotune_report) if self.autotune_report is not None else None
            ),
            "telemetry": dict(self.telemetry) if self.telemetry is not None else None,
            "runtime_mode_audit": (
                dict(self.runtime_mode_audit)
                if self.runtime_mode_audit is not None
                else None
            ),
            "error_summary": self.error_summary,
        }


class CodexFarmRunner(Protocol):
    def run_pipeline(
        self,
        pipeline_id: str,
        in_dir: Path,
        out_dir: Path,
        env: Mapping[str, str],
        *,
        root_dir: Path | None = None,
        workspace_root: Path | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> CodexFarmPipelineRunResult | None:
        """Run a codex-farm pipeline over input/output directories."""


def as_pipeline_run_result_payload(value: object) -> dict[str, Any] | None:
    if isinstance(value, CodexFarmPipelineRunResult):
        return value.to_manifest_dict()
    if isinstance(value, dict):
        return dict(value)
    return None


def _merge_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    merged = os.environ.copy()
    if not env:
        return merged
    for key, value in env.items():
        merged[str(key)] = str(value)
    return merged


def _command_prefix(cmd: str) -> list[str]:
    prefix = shlex.split(cmd)
    return prefix or ["codex-farm"]


def _run_codex_farm_command(
    command: list[str],
    *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            env=_merge_env(env),
        )
    except FileNotFoundError as exc:
        binary = command[0] if command else "codex-farm"
        raise CodexFarmRunnerError(
            f"codex-farm command not found: {binary!r}. "
            "Install codex-farm or disable llm_recipe_pipeline."
        ) from exc
    except OSError as exc:
        binary = command[0] if command else "codex-farm"
        raise CodexFarmRunnerError(
            f"Failed to execute codex-farm command {binary!r}: {exc}"
        ) from exc


def _run_codex_farm_command_streaming(
    command: list[str],
    *,
    env: Mapping[str, str] | None = None,
    stderr_line_handler: Callable[[str], bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_merge_env(env),
            bufsize=1,
        )
    except FileNotFoundError as exc:
        binary = command[0] if command else "codex-farm"
        raise CodexFarmRunnerError(
            f"codex-farm command not found: {binary!r}. "
            "Install codex-farm or disable llm_recipe_pipeline."
        ) from exc
    except OSError as exc:
        binary = command[0] if command else "codex-farm"
        raise CodexFarmRunnerError(
            f"Failed to execute codex-farm command {binary!r}: {exc}"
        ) from exc

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _read_stdout() -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            stdout_lines.append(line)

    def _read_stderr() -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            keep_line = True
            if stderr_line_handler is not None:
                try:
                    keep_line = not bool(stderr_line_handler(line.rstrip("\r\n")))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Ignoring codex-farm stderr handler failure: %s", exc)
                    keep_line = True
            if keep_line:
                stderr_lines.append(line)

    stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    return_code = proc.wait()
    stdout_thread.join()
    stderr_thread.join()
    return subprocess.CompletedProcess(
        args=command,
        returncode=return_code,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
    )


def _parse_json_stdout(
    completed: subprocess.CompletedProcess[str],
    *,
    command_label: str,
) -> Any | None:
    raw_stdout = (completed.stdout or "").strip()
    if not raw_stdout:
        raise CodexFarmRunnerError(
            f"codex-farm {command_label} returned empty stdout despite --json."
        )
    try:
        return json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        raise CodexFarmRunnerError(
            f"codex-farm {command_label} returned non-JSON stdout despite --json."
        ) from exc


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _progress_events_option_unsupported(stderr_text: str) -> bool:
    lowered = str(stderr_text or "").strip().lower()
    if not lowered or "--progress-events" not in lowered:
        return False
    return any(
        marker in lowered
        for marker in (
            "no such option",
            "unrecognized arguments",
            "unknown option",
            "invalid option",
        )
    )


def _benchmark_mode_option_unsupported(stderr_text: str) -> bool:
    lowered = str(stderr_text or "").strip().lower()
    if not lowered or "--benchmark-mode" not in lowered:
        return False
    return any(
        marker in lowered
        for marker in (
            "no such option",
            "unrecognized arguments",
            "unknown option",
            "invalid option",
        )
    )


def _normalize_codex_farm_recipe_mode(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if not normalized:
        return None
    if normalized in {
        _CODEX_FARM_RECIPE_MODE_EXTRACT,
        _CODEX_FARM_RECIPE_MODE_BENCHMARK,
    }:
        return normalized
    raise CodexFarmRunnerError(
        "Invalid codex-farm recipe mode from environment "
        f"{_CODEX_FARM_RECIPE_MODE_ENV}={value!r}. "
        "Expected one of: extract, benchmark."
    )


def _remove_benchmark_mode_option(command: Sequence[str]) -> list[str]:
    tokens = list(command)
    while "--benchmark-mode" in tokens:
        index = tokens.index("--benchmark-mode")
        delete_end = index + 2 if index + 1 < len(tokens) else index + 1
        del tokens[index:delete_end]
    return tokens


def _parse_progress_event(stderr_line: str) -> dict[str, Any] | None:
    line = str(stderr_line or "").strip()
    if not line.startswith(_CODEX_FARM_PROGRESS_PREFIX):
        return None
    raw_payload = line[len(_CODEX_FARM_PROGRESS_PREFIX) :].strip()
    if not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    return dict(payload) if isinstance(payload, dict) else None


_LEGACY_PROGRESS_TOKEN_RE = re.compile(r"(?P<key>[a-z_]+)=(?P<value>\S+)")
_LEGACY_PROGRESS_COUNT_KEYS = ("queued", "running", "done", "error", "canceled")


def _parse_legacy_progress_line(stderr_line: str) -> dict[str, Any] | None:
    line = str(stderr_line or "").strip()
    if not line:
        return None
    pairs = {
        str(match.group("key") or "").strip().lower(): str(match.group("value") or "").strip()
        for match in _LEGACY_PROGRESS_TOKEN_RE.finditer(line)
    }
    if not pairs:
        return None

    run_id = _clean_text(pairs.get("run"))
    counts: dict[str, int] = {}
    for key in _LEGACY_PROGRESS_COUNT_KEYS:
        raw_value = pairs.get(key)
        if raw_value is None:
            continue
        try:
            counts[key] = max(0, int(raw_value))
        except ValueError:
            return None

    has_all_counts = all(key in counts for key in _LEGACY_PROGRESS_COUNT_KEYS)
    if not has_all_counts:
        if run_id:
            return {"event": "run_started", "run_id": run_id}
        return None

    total = sum(counts[key] for key in _LEGACY_PROGRESS_COUNT_KEYS)
    status = "done" if counts["running"] <= 0 and counts["queued"] <= 0 else "running"
    payload: dict[str, Any] = {
        "event": "run_progress",
        "status": status,
        "counts": {
            **counts,
            "total": total,
        },
        "progress": {
            "completed": counts["done"] + counts["error"] + counts["canceled"],
        },
    }
    if run_id:
        payload["run_id"] = run_id
    return payload


_CODEX_FARM_CREATED_RUN_PATTERN = re.compile(
    r"^Created run (?P<run_id>\S+) with (?P<total_tasks>-?\d+) tasks$"
)


def _parse_created_run_line(stderr_line: str) -> dict[str, int | str] | None:
    line = str(stderr_line or "").strip()
    match = _CODEX_FARM_CREATED_RUN_PATTERN.match(line)
    if match is None:
        return None
    run_id = str(match.group("run_id") or "").strip()
    if not run_id:
        return None
    try:
        total_tasks = int(match.group("total_tasks"))
    except (TypeError, ValueError):
        return None
    return {"run_id": run_id, "total_tasks": total_tasks}


def _format_created_run_progress_message(
    *,
    payload: Mapping[str, Any],
    pipeline_id: str,
) -> str:
    run_id = str(payload.get("run_id") or "").strip()
    total_tasks = payload.get("total_tasks")
    if total_tasks is None:
        if run_id:
            return f"codex-farm {pipeline_id}: {run_id}"
        return f"codex-farm {pipeline_id}: run started"
    return (
        f"codex-farm {pipeline_id} run {run_id} started with {total_tasks} tasks"
    )


def _extract_non_progress_stderr_lines(stderr_text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in str(stderr_text or "").splitlines():
        if not raw_line.strip():
            continue
        if _parse_progress_event(raw_line) is not None:
            continue
        if _parse_legacy_progress_line(raw_line) is not None:
            continue
        if _parse_created_run_line(raw_line) is not None:
            continue
        lines.append(raw_line.rstrip("\r\n"))
    return lines


_STDERR_SUMMARY_SKIP_PREFIXES = (
    "workdir:",
    "model:",
    "provider:",
    "approval:",
    "sandbox:",
    "reasoning effort:",
    "reasoning summaries:",
    "session id:",
    "mcp startup:",
)


def _summarize_failure_stderr(stderr_text: str) -> str | None:
    raw_lines = _extract_non_progress_stderr_lines(stderr_text)
    if not raw_lines:
        return None

    summary_lines: list[str] = []
    for raw_line in raw_lines:
        line = str(raw_line).strip()
        lowered = line.lower()
        if not line or line == "--------":
            continue
        if lowered == "user":
            continue
        if line == "Reply with exactly: OK":
            continue
        if any(lowered.startswith(prefix) for prefix in _STDERR_SUMMARY_SKIP_PREFIXES):
            continue
        summary_lines.append(line)

    if not summary_lines:
        return None

    precheck_line = next(
        (
            line
            for line in summary_lines
            if line.startswith("codex execution precheck failed before")
        ),
        None,
    )
    error_line = next(
        (
            line
            for line in summary_lines
            if line.startswith("ERROR:")
        ),
        None,
    )
    auth_or_hint_line = next(
        (
            line
            for line in summary_lines
            if "run `codex` once" in line.lower()
            or "sign in with chatgpt" in line.lower()
            or "usage limit" in line.lower()
        ),
        None,
    )

    if precheck_line and error_line:
        return f"{precheck_line}; {error_line}"
    if precheck_line and auth_or_hint_line and auth_or_hint_line != precheck_line:
        return f"{precheck_line}; {auth_or_hint_line}"
    if error_line:
        return error_line

    condensed = summary_lines[:2]
    return "; ".join(condensed)


def _collect_progress_task_label(task: Any) -> str | None:
    if isinstance(task, str):
        candidate = task.strip()
        return candidate or None

    if not isinstance(task, Mapping):
        return None

    for key in (
        "input_path",
        "output_path",
        "path",
        "name",
        "file",
        "source",
        "task_id",
        "id",
    ):
        value = _clean_text(task.get(key))
        if value:
            return value
    return None


def _format_progress_task_labels(payload: Mapping[str, Any]) -> list[str]:
    running_tasks: Any = None
    for candidate in (
        payload.get("running_tasks"),
        payload.get("running_task_ids"),
        payload.get("active_tasks"),
        payload.get("inflight_tasks"),
        payload.get("tasks"),
    ):
        if isinstance(candidate, list):
            running_tasks = candidate
            if running_tasks:
                break

    if not isinstance(running_tasks, list):
        return []
    labels: list[str] = []
    seen: set[str] = set()
    for task in running_tasks:
        label = _collect_progress_task_label(task)
        if not label:
            continue
        normalized = Path(label).name if ("/" in label or "\\" in label) else label
        if normalized in seen:
            continue
        seen.add(normalized)
        labels.append(normalized)
    return labels


def _format_progress_event_message(
    payload: Mapping[str, Any],
    *,
    pipeline_id: str,
) -> str | None:
    counts_raw = payload.get("counts")
    progress_raw = payload.get("progress")
    counts = counts_raw if isinstance(counts_raw, Mapping) else {}
    progress = progress_raw if isinstance(progress_raw, Mapping) else {}

    total = _coerce_int(counts.get("total"))
    done = _coerce_int(counts.get("done")) or 0
    error = _coerce_int(counts.get("error")) or 0
    canceled = _coerce_int(counts.get("canceled")) or 0
    running = _coerce_int(counts.get("running")) or 0
    completed = _coerce_int(progress.get("completed"))
    if completed is None:
        completed = done + error + canceled

    task_labels = _format_progress_task_labels(payload)
    if total is not None and total > 0:
        safe_total = max(0, int(total))
        safe_completed = max(0, min(int(completed), safe_total))
        parts = [f"codex-farm {pipeline_id} task {safe_completed}/{safe_total}"]
        if running > 0:
            parts.append(f"running {running}")
            if task_labels:
                shown_labels = task_labels[: running]
                if shown_labels:
                    parts.append(f"active [{', '.join(shown_labels)}]")
        elif task_labels:
            parts.append(f"active [{', '.join(task_labels)}]")
        if error > 0:
            parts.append(f"errors {error}")
        return " | ".join(parts)

    status = _clean_text(payload.get("status"))
    if status:
        return f"codex-farm {pipeline_id}: {status}"
    event = _clean_text(payload.get("event"))
    if event:
        return f"codex-farm {pipeline_id}: {event.replace('_', ' ')}"
    return None


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _as_existing_file(path: Path) -> Path:
    if not path.exists() or not path.is_file():
        raise CodexFarmRunnerError(f"Expected file path does not exist: {path}")
    return path


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _build_runtime_mode_audit(
    *,
    command: Sequence[str],
    output_schema_path: str | None,
) -> dict[str, Any]:
    tool_affordances_requested = any(
        any(token == prefix or token.startswith(f"{prefix}=") for prefix in _RUNTIME_AGENTIC_FLAG_PREFIXES)
        for token in command
    )
    reason_codes: list[str] = []
    if not str(output_schema_path or "").strip():
        reason_codes.append("runtime_output_schema_missing")
    if tool_affordances_requested:
        reason_codes.append("runtime_agentic_flag_present")
    return {
        "mode": "structured_output_non_agentic",
        "status": "ok" if not reason_codes else "invalid",
        "output_schema_enforced": bool(str(output_schema_path or "").strip()),
        "tool_affordances_requested": tool_affordances_requested,
        "reason_codes": reason_codes,
    }


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return list(parsed) if isinstance(parsed, list) else []


def _parse_json_string_list(value: Any) -> list[str]:
    rows: list[str] = []
    for item in _parse_json_list(value):
        cleaned = _clean_text(item)
        if cleaned:
            rows.append(cleaned)
    return rows


def _parse_json_float_list(value: Any) -> list[float]:
    rows: list[float] = []
    for item in _parse_json_list(value):
        try:
            rows.append(float(item))
        except (TypeError, ValueError):
            continue
    return rows


def _trim_text(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return value[:max_chars]
    return value[: max_chars - 3] + "..."


def _option_value_from_tokens(tokens: Sequence[str], name: str) -> str | None:
    exact = f"--{name}"
    prefix = f"--{name}="
    for index, token in enumerate(tokens):
        if token == exact and index + 1 < len(tokens):
            candidate = _clean_text(tokens[index + 1])
            if candidate:
                return candidate
        if token.startswith(prefix):
            candidate = _clean_text(token.split("=", 1)[1])
            if candidate:
                return candidate
    return None


def _resolve_codex_exec_activity_csv_path(cmd: str) -> Path:
    tokens = _command_prefix(cmd)
    data_dir_value = _option_value_from_tokens(tokens, "data-dir")
    if data_dir_value:
        data_dir = Path(data_dir_value).expanduser()
        if not data_dir.is_absolute():
            data_dir = (Path.cwd() / data_dir).resolve()
        return data_dir / "codex_exec_activity.csv"
    return (Path.cwd() / "var" / "codex_exec_activity.csv").resolve()


def _collect_codex_exec_run_telemetry(
    *,
    cmd: str,
    run_id: str,
    pipeline_id: str,
    max_rows: int = 50,
) -> dict[str, Any] | None:
    csv_path = _resolve_codex_exec_activity_csv_path(cmd)
    warnings: list[str] = []
    if not csv_path.exists():
        warnings.append(f"Telemetry CSV does not exist: {csv_path}")
        return {
            "csv_path": str(csv_path),
            "row_count": 0,
            "rows_returned": 0,
            "rows_truncated": False,
            "summary": {
                "status_counts": {},
                "failure_category_counts": {},
                "attempt_index_counts": {},
                "retry_context_applied_rows": 0,
                "heads_up_applied_rows": 0,
                "rate_limit_suspected_rows": 0,
                "output_preview_truncated_rows": 0,
                "output_payload_missing_rows": 0,
                "unique_output_sha256_count": 0,
                "unique_retry_previous_error_sha256_count": 0,
                "codex_event_count_total": 0,
                "codex_event_types_counts": {},
            },
            "rows": [],
            "warnings": warnings,
        }

    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            matched_rows = [dict(row) for row in reader if _clean_text(row.get("run_id")) == run_id]
    except OSError as exc:
        warnings.append(f"Failed to read telemetry CSV {csv_path}: {exc}")
        matched_rows = []

    normalized_rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    failure_category_counts: dict[str, int] = {}
    attempt_index_counts: dict[str, int] = {}
    codex_event_types_counts: dict[str, int] = {}
    unique_output_sha256: set[str] = set()
    unique_retry_error_sha: set[str] = set()
    retry_context_applied_rows = 0
    heads_up_applied_rows = 0
    rate_limit_rows = 0
    output_preview_truncated_rows = 0
    output_payload_missing_rows = 0
    codex_event_count_total = 0

    for row in matched_rows:
        row_pipeline_id = _clean_text(row.get("pipeline_id"))
        if row_pipeline_id and row_pipeline_id != pipeline_id:
            continue

        status = _clean_text(row.get("status")) or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

        failure_category = _clean_text(row.get("failure_category"))
        if failure_category:
            failure_category_counts[failure_category] = (
                failure_category_counts.get(failure_category, 0) + 1
            )

        attempt_index = _coerce_int(row.get("attempt_index"))
        if attempt_index is not None and attempt_index >= 1:
            attempt_key = str(attempt_index)
            attempt_index_counts[attempt_key] = attempt_index_counts.get(attempt_key, 0) + 1

        retry_context_applied = _coerce_bool(row.get("retry_context_applied"))
        heads_up_applied = _coerce_bool(row.get("heads_up_applied"))
        rate_limit_suspected = _coerce_bool(row.get("rate_limit_suspected"))
        output_payload_present = _coerce_bool(row.get("output_payload_present"))
        output_preview_truncated = _coerce_bool(row.get("output_preview_truncated"))

        if retry_context_applied:
            retry_context_applied_rows += 1
        if heads_up_applied:
            heads_up_applied_rows += 1
        if rate_limit_suspected:
            rate_limit_rows += 1
        if output_preview_truncated:
            output_preview_truncated_rows += 1
        if not output_payload_present:
            output_payload_missing_rows += 1

        output_sha = _clean_text(row.get("output_sha256"))
        if output_sha:
            unique_output_sha256.add(output_sha)
        retry_error_sha = _clean_text(row.get("retry_previous_error_sha256"))
        if retry_error_sha:
            unique_retry_error_sha.add(retry_error_sha)

        codex_event_count = _coerce_int(row.get("codex_event_count")) or 0
        codex_event_count_total += codex_event_count
        codex_event_types = _parse_json_string_list(row.get("codex_event_types_json"))
        for event_type in codex_event_types:
            codex_event_types_counts[event_type] = codex_event_types_counts.get(event_type, 0) + 1

        output_preview = _clean_text(row.get("output_preview"))
        retry_previous_error = _clean_text(row.get("retry_previous_error"))
        stderr_tail = _clean_text(row.get("stderr_tail"))
        stdout_tail = _clean_text(row.get("stdout_tail"))

        normalized_rows.append(
            {
                "logged_at_utc": _clean_text(row.get("logged_at_utc")),
                "started_at_utc": _clean_text(row.get("started_at_utc")),
                "finished_at_utc": _clean_text(row.get("finished_at_utc")),
                "duration_ms": _coerce_int(row.get("duration_ms")),
                "status": status,
                "exit_code": _coerce_int(row.get("exit_code")),
                "accepted_nonzero_exit": _coerce_bool(row.get("accepted_nonzero_exit")),
                "failure_category": failure_category,
                "rate_limit_suspected": rate_limit_suspected,
                "task_id": _clean_text(row.get("task_id")),
                "worker_id": _clean_text(row.get("worker_id")),
                "input_path": _clean_text(row.get("input_path")),
                "output_path": _clean_text(row.get("output_path")),
                "prompt_sha256": _clean_text(row.get("prompt_sha256")),
                "prompt_chars": _coerce_int(row.get("prompt_chars")),
                "attempt_index": attempt_index,
                "retry_context_applied": retry_context_applied,
                "retry_previous_error_sha256": retry_error_sha,
                "retry_previous_error_chars": _coerce_int(row.get("retry_previous_error_chars")),
                "retry_previous_error": _trim_text(retry_previous_error, max_chars=280),
                "heads_up_applied": heads_up_applied,
                "heads_up_tip_count": _coerce_int(row.get("heads_up_tip_count")),
                "heads_up_input_signature": _clean_text(row.get("heads_up_input_signature")),
                "heads_up_tip_ids": _parse_json_string_list(row.get("heads_up_tip_ids_json")),
                "heads_up_tip_texts": _parse_json_string_list(row.get("heads_up_tip_texts_json")),
                "heads_up_tip_scores": _parse_json_float_list(row.get("heads_up_tip_scores_json")),
                "output_payload_present": output_payload_present,
                "output_bytes": _coerce_int(row.get("output_bytes")),
                "output_sha256": output_sha,
                "output_preview": _trim_text(output_preview, max_chars=500),
                "output_preview_chars": _coerce_int(row.get("output_preview_chars")),
                "output_preview_truncated": output_preview_truncated,
                "codex_event_count": codex_event_count,
                "codex_event_types": codex_event_types,
                "tokens_input": _coerce_int(row.get("tokens_input")),
                "tokens_cached_input": _coerce_int(row.get("tokens_cached_input")),
                "tokens_output": _coerce_int(row.get("tokens_output")),
                "tokens_total": _coerce_int(row.get("tokens_total")),
                "stderr_tail": _trim_text(stderr_tail, max_chars=320),
                "stdout_tail": _trim_text(stdout_tail, max_chars=320),
            }
        )

    normalized_rows.sort(
        key=lambda row: (
            _clean_text(row.get("logged_at_utc")),
            _clean_text(row.get("task_id")),
        )
    )

    rows_truncated = len(normalized_rows) > max_rows
    rows_to_return = normalized_rows[-max_rows:] if rows_truncated else normalized_rows

    return {
        "csv_path": str(csv_path),
        "row_count": len(normalized_rows),
        "rows_returned": len(rows_to_return),
        "rows_truncated": rows_truncated,
        "summary": {
            "status_counts": dict(sorted(status_counts.items())),
            "failure_category_counts": dict(sorted(failure_category_counts.items())),
            "attempt_index_counts": dict(
                sorted(attempt_index_counts.items(), key=lambda item: int(item[0]))
            ),
            "retry_context_applied_rows": retry_context_applied_rows,
            "heads_up_applied_rows": heads_up_applied_rows,
            "rate_limit_suspected_rows": rate_limit_rows,
            "output_preview_truncated_rows": output_preview_truncated_rows,
            "output_payload_missing_rows": output_payload_missing_rows,
            "unique_output_sha256_count": len(unique_output_sha256),
            "unique_retry_previous_error_sha256_count": len(unique_retry_error_sha),
            "codex_event_count_total": codex_event_count_total,
            "codex_event_types_counts": dict(sorted(codex_event_types_counts.items())),
        },
        "rows": rows_to_return,
        "warnings": warnings,
    }


@lru_cache(maxsize=512)
def _resolve_pipeline_output_schema_path(
    *,
    root_dir_str: str,
    pipeline_id: str,
) -> Path:
    root_dir = Path(root_dir_str)
    pipelines_dir = root_dir / "pipelines"
    if not pipelines_dir.exists() or not pipelines_dir.is_dir():
        raise CodexFarmRunnerError(
            f"Invalid codex-farm pipeline root {root_dir}: missing pipelines directory."
        )

    matching_defs: list[tuple[Path, dict[str, Any]]] = []
    for definition_path in sorted(pipelines_dir.rglob("*.json")):
        payload = _read_json_dict(definition_path)
        if payload is None:
            continue
        found_pipeline_id = str(payload.get("pipeline_id") or "").strip()
        if found_pipeline_id != pipeline_id:
            continue
        matching_defs.append((definition_path, payload))

    if not matching_defs:
        raise CodexFarmRunnerError(
            "Unable to resolve codex-farm output schema override: "
            f"pipeline definition for {pipeline_id!r} not found under {pipelines_dir}."
        )
    if len(matching_defs) > 1:
        paths = ", ".join(str(path) for path, _payload in matching_defs)
        raise CodexFarmRunnerError(
            "Unable to resolve codex-farm output schema override: "
            f"pipeline id {pipeline_id!r} is defined multiple times ({paths})."
        )

    definition_path, payload = matching_defs[0]
    raw_schema_path = str(payload.get("output_schema_path") or "").strip()
    if not raw_schema_path:
        raise CodexFarmRunnerError(
            "Unable to resolve codex-farm output schema override: "
            f"{definition_path} is missing output_schema_path."
        )

    schema_path = Path(raw_schema_path).expanduser()
    if not schema_path.is_absolute():
        schema_path = root_dir / schema_path
    return _as_existing_file(schema_path)


def resolve_codex_farm_output_schema_path(
    *,
    root_dir: Path,
    pipeline_id: str,
) -> Path:
    """Resolve a pipeline's output schema path from pack metadata."""

    return _resolve_pipeline_output_schema_path(
        root_dir_str=str(root_dir),
        pipeline_id=str(pipeline_id),
    )


def _normalize_model_row(row: dict[str, Any]) -> dict[str, Any] | None:
    slug = str(row.get("slug") or "").strip()
    if not slug:
        return None
    display_name = str(row.get("display_name") or slug).strip() or slug
    description = str(row.get("description") or "").strip()
    normalized: dict[str, Any] = {
        "slug": slug,
        "display_name": display_name,
        "description": description,
    }
    raw_efforts = row.get("supported_reasoning_efforts")
    if isinstance(raw_efforts, list):
        efforts = [item.strip() for item in raw_efforts if isinstance(item, str) and item.strip()]
        if efforts:
            normalized["supported_reasoning_efforts"] = efforts
    return normalized


def list_codex_farm_models(
    *,
    cmd: str = "codex-farm",
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Best-effort model discovery via `codex-farm models list --json`."""

    command = [*_command_prefix(cmd), "models", "list", "--json"]
    try:
        completed = _run_codex_farm_command(command, env=env)
    except CodexFarmRunnerError as exc:
        logger.warning("Unable to list codex-farm models: %s", exc)
        return []

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        logger.warning(
            "codex-farm models list failed (exit=%s): %s",
            completed.returncode,
            stderr or "no stderr",
        )
        return []

    try:
        payload = _parse_json_stdout(completed, command_label="models list")
    except CodexFarmRunnerError as exc:
        logger.warning("%s", exc)
        return []

    if not isinstance(payload, list):
        return []

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_model_row(row)
        if normalized is None:
            continue
        slug = normalized["slug"]
        if slug in seen:
            continue
        models.append(normalized)
        seen.add(slug)
    return models


def list_codex_farm_pipelines(
    *,
    cmd: str = "codex-farm",
    root_dir: Path,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Strict pipeline discovery via `codex-farm pipelines list --root ... --json`."""

    command = [
        *_command_prefix(cmd),
        "pipelines",
        "list",
        "--root",
        str(root_dir),
        "--json",
    ]
    completed = _run_codex_farm_command(command, env=env)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise CodexFarmRunnerError(
            "codex-farm pipelines list failed for "
            f"{root_dir} (exit={completed.returncode}): {stderr or 'no stderr'}"
        )

    payload = _parse_json_stdout(completed, command_label="pipelines list")
    if not isinstance(payload, list):
        raise CodexFarmRunnerError(
            "codex-farm pipelines list returned unexpected JSON payload."
        )

    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        pipeline_id = str(item.get("pipeline_id") or "").strip()
        if not pipeline_id:
            continue
        rows.append(
            {
                "pipeline_id": pipeline_id,
                "description": str(item.get("description") or "").strip(),
            }
        )
    return rows


def ensure_codex_farm_pipelines_exist(
    *,
    cmd: str,
    root_dir: Path,
    pipeline_ids: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> None:
    """Fail early when configured pipeline ids are missing from a pack root."""

    requested = [str(item).strip() for item in pipeline_ids if str(item).strip()]
    if not requested:
        return
    discovered = list_codex_farm_pipelines(cmd=cmd, root_dir=root_dir, env=env)
    available = {str(row.get("pipeline_id") or "").strip() for row in discovered}
    missing = sorted({item for item in requested if item not in available})
    if not missing:
        return
    raise CodexFarmRunnerError(
        "Configured codex-farm pipeline id(s) not found under "
        f"{root_dir}: {', '.join(missing)}. "
        "Verify pipeline ids with `codex-farm pipelines list --root <pack> --json`."
    )


def _extract_run_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    run_id = str(payload.get("run_id") or "").strip()
    return run_id or None


def _extract_exit_code(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    return _coerce_int(payload.get("exit_code"))


def _extract_output_schema_path(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    rendered = str(payload.get("output_schema_path") or "").strip()
    return rendered or None


def _extract_telemetry_report(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    report = payload.get("telemetry_report")
    if not isinstance(report, dict):
        return None
    return dict(report)


def _summarize_run_errors_payload(payload: Any) -> str | None:
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                for key in ("message", "error", "detail"):
                    text = str(first.get(key) or "").strip()
                    if text:
                        return text
            text = str(first).strip()
            if text:
                return text
        for key in ("message", "error", "detail"):
            text = str(payload.get(key) or "").strip()
            if text:
                return text
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            for key in ("message", "error", "detail"):
                text = str(first.get(key) or "").strip()
                if text:
                    return text
        text = str(first).strip()
        if text:
            return text
    return None


def _fetch_run_errors_summary(
    *,
    cmd: str,
    run_id: str,
    env: Mapping[str, str] | None = None,
) -> str | None:
    command = [*_command_prefix(cmd), "run", "errors", "--run-id", run_id, "--json"]
    try:
        completed = _run_codex_farm_command(command, env=env)
    except CodexFarmRunnerError as exc:
        logger.warning("Unable to fetch codex-farm run errors for %s: %s", run_id, exc)
        return None
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        logger.warning(
            "codex-farm run errors failed for %s (exit=%s): %s",
            run_id,
            completed.returncode,
            stderr or "no stderr",
        )
        return None
    try:
        payload = _parse_json_stdout(completed, command_label="run errors")
    except CodexFarmRunnerError as exc:
        logger.warning("%s", exc)
        return None
    return _summarize_run_errors_payload(payload)


def _count_json_bundle_files(path: Path) -> int:
    try:
        return sum(1 for child in path.iterdir() if child.is_file() and child.suffix == ".json")
    except FileNotFoundError:
        return 0


def _is_recoverable_no_last_agent_message_failure(
    *,
    error_summary: str | None,
    telemetry_payload: dict[str, Any] | None,
    recipe_mode: str | None,
    input_bundle_count: int,
    output_bundle_count: int,
) -> bool:
    summary_text = str(error_summary or "").strip().lower()
    if "no last agent message" not in summary_text:
        return False
    nonzero_failure_categories: set[str] = set()
    if telemetry_payload is not None:
        telemetry_summary = telemetry_payload.get("summary")
        if isinstance(telemetry_summary, dict):
            failure_counts = telemetry_summary.get("failure_category_counts")
            if isinstance(failure_counts, dict):
                nonzero_failure_categories = {
                    str(key)
                    for key, value in failure_counts.items()
                    if (_coerce_int(value) or 0) > 0
                }
    if not nonzero_failure_categories:
        return True
    if nonzero_failure_categories <= {"nonzero_exit_no_payload"}:
        return True
    if recipe_mode != _CODEX_FARM_RECIPE_MODE_BENCHMARK:
        return False
    if not nonzero_failure_categories <= {"nonzero_exit_no_payload", "timeout"}:
        return False
    if input_bundle_count <= 0 or output_bundle_count <= 0:
        return False
    missing_bundle_count = max(input_bundle_count - output_bundle_count, 0)
    if missing_bundle_count <= 0:
        return False
    success_ratio = output_bundle_count / input_bundle_count
    return (
        missing_bundle_count <= _BENCHMARK_RECOVERABLE_PARTIAL_MAX_MISSING_OUTPUTS
        and success_ratio >= _BENCHMARK_RECOVERABLE_PARTIAL_MIN_SUCCESS_RATIO
    )


def _format_recoverable_partial_output_message(
    *,
    pipeline_id: str,
    run_id: str | None,
    error_summary: str | None,
    input_bundle_count: int,
    output_bundle_count: int,
) -> str:
    summary = re.sub(r"\s+", " ", str(error_summary or "").strip())
    if len(summary) > 220:
        summary = summary[:217].rstrip() + "..."
    message = (
        f"codex-farm {pipeline_id}: recoverable non-zero exit; continuing with partial outputs"
    )
    if input_bundle_count > 0:
        missing_bundle_count = max(input_bundle_count - output_bundle_count, 0)
        message += (
            f" ({output_bundle_count}/{input_bundle_count} bundles written; "
            f"{missing_bundle_count} missing)"
        )
    if run_id:
        message += f" [run_id={run_id}]"
    if summary:
        message += f" | {summary}"
    return message


def _fetch_run_autotune_payload(
    *,
    cmd: str,
    run_id: str,
    pipeline_id: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    command = [*_command_prefix(cmd), "run", "autotune", "--run-id", run_id, "--json"]
    if pipeline_id:
        command.extend(["--pipeline", pipeline_id])
    try:
        completed = _run_codex_farm_command(command, env=env)
    except CodexFarmRunnerError as exc:
        logger.debug(
            "Unable to fetch codex-farm autotune payload for run %s: %s",
            run_id,
            exc,
        )
        return None
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        logger.debug(
            "codex-farm run autotune failed for %s (exit=%s): %s",
            run_id,
            completed.returncode,
            stderr or "no stderr",
        )
        return None
    try:
        payload = _parse_json_stdout(completed, command_label="run autotune")
    except CodexFarmRunnerError as exc:
        logger.debug("%s", exc)
        return None
    return dict(payload) if isinstance(payload, dict) else None


@dataclass(frozen=True)
class SubprocessCodexFarmRunner:
    cmd: str = "codex-farm"
    progress_callback: Callable[[str], None] | None = None

    def run_pipeline(
        self,
        pipeline_id: str,
        in_dir: Path,
        out_dir: Path,
        env: Mapping[str, str],
        *,
        root_dir: Path | None = None,
        workspace_root: Path | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> CodexFarmPipelineRunResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        expected_schema_path: Path | None = None
        selected_recipe_mode = _normalize_codex_farm_recipe_mode(
            env.get(_CODEX_FARM_RECIPE_MODE_ENV)
        )
        command = [
            *_command_prefix(self.cmd),
            "process",
            "--pipeline",
            pipeline_id,
            "--in",
            str(in_dir),
            "--out",
            str(out_dir),
        ]
        if model:
            command.extend(["--model", str(model)])
        if reasoning_effort:
            command.extend(["--reasoning-effort", str(reasoning_effort)])
        if root_dir is not None:
            expected_schema_path = resolve_codex_farm_output_schema_path(
                root_dir=root_dir,
                pipeline_id=pipeline_id,
            )
            command.extend(["--output-schema", str(expected_schema_path)])
        if selected_recipe_mode is not None:
            command.extend(["--benchmark-mode", selected_recipe_mode])
        command.append("--json")
        if self.progress_callback is not None:
            command.append("--progress-events")
        if root_dir is not None:
            command.extend(["--root", str(root_dir)])
        if workspace_root is not None:
            command.extend(["--workspace-root", str(workspace_root)])
        progress_callback = self.progress_callback
        last_progress_message = ""

        def _emit_progress(message: str) -> None:
            nonlocal last_progress_message
            if progress_callback is None:
                return
            cleaned = str(message or "").strip()
            if not cleaned or cleaned == last_progress_message:
                return
            last_progress_message = cleaned
            try:
                progress_callback(cleaned)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ignoring codex-farm progress callback failure: %s", exc)

        def _run_process_command(command_tokens: list[str]) -> subprocess.CompletedProcess[str]:
            if progress_callback is None:
                return _run_codex_farm_command(command_tokens, env=env)

            def _handle_stderr_line(line: str) -> bool:
                progress_payload = _parse_progress_event(line)
                if progress_payload is None:
                    progress_payload = _parse_legacy_progress_line(line)
                if progress_payload is None:
                    created_payload = _parse_created_run_line(line)
                    if created_payload is not None:
                        _emit_progress(
                            _format_created_run_progress_message(
                                payload=created_payload,
                                pipeline_id=pipeline_id,
                            )
                        )
                        return True
                    return False
                if progress_payload.get("event") == "run_started" and progress_payload.get("run_id"):
                    _emit_progress(
                        _format_created_run_progress_message(
                            payload=progress_payload,
                            pipeline_id=pipeline_id,
                        )
                    )
                    return True
                message = _format_progress_event_message(
                    progress_payload,
                    pipeline_id=pipeline_id,
                )
                if message:
                    _emit_progress(message)
                return True

            completed_stream = _run_codex_farm_command_streaming(
                command_tokens,
                env=env,
                stderr_line_handler=_handle_stderr_line,
            )
            if (
                completed_stream.returncode != 0
                and _progress_events_option_unsupported(completed_stream.stderr)
            ):
                _emit_progress(
                    f"codex-farm {pipeline_id}: live progress events unavailable; retrying without --progress-events."
                )
                fallback_command = list(command_tokens)
                if "--progress-events" in fallback_command:
                    fallback_command.remove("--progress-events")
                return _run_codex_farm_command(fallback_command, env=env)
            return completed_stream

        completed = _run_process_command(command)
        if (
            completed.returncode != 0
            and _benchmark_mode_option_unsupported(completed.stderr)
            and selected_recipe_mode == _CODEX_FARM_RECIPE_MODE_EXTRACT
        ):
            _emit_progress(
                "codex-farm benchmark-mode flag unavailable; retrying extract mode without --benchmark-mode."
            )
            fallback_command = _remove_benchmark_mode_option(command)
            completed = _run_process_command(fallback_command)
        elif (
            completed.returncode != 0
            and _benchmark_mode_option_unsupported(completed.stderr)
            and selected_recipe_mode == _CODEX_FARM_RECIPE_MODE_BENCHMARK
        ):
            raise CodexFarmRunnerError(
                "codex-farm benchmark mode requested but this codex-farm build does "
                "not support --benchmark-mode. Upgrade codex-farm or use "
                "codex_farm_recipe_mode=extract."
            )

        if completed.stdout.strip():
            logger.info(
                "codex-farm stdout (%s): %s",
                pipeline_id,
                completed.stdout.strip(),
            )
        stderr_lines = _extract_non_progress_stderr_lines(completed.stderr)
        if stderr_lines:
            if progress_callback is None:
                logger.warning(
                    "codex-farm stderr (%s): %s",
                    pipeline_id,
                    "\n".join(stderr_lines),
                )
            else:
                logger.debug(
                    "codex-farm stderr (%s): %s",
                    pipeline_id,
                    "\n".join(stderr_lines),
                )
        elif completed.stderr.strip():
            logger.debug(
                "codex-farm stderr (%s): progress-only output suppressed.",
                pipeline_id,
            )

        if completed.returncode != 0 and not completed.stdout.strip():
            process_payload = None
        else:
            process_payload = _parse_json_stdout(completed, command_label="process")

        process_payload_dict = dict(process_payload) if isinstance(process_payload, dict) else None
        if process_payload is not None and expected_schema_path is not None:
            reported_schema_path = _extract_output_schema_path(process_payload)
            if not reported_schema_path:
                raise CodexFarmRunnerError(
                    "codex-farm process --json response is missing output_schema_path."
                )
            reported_schema = Path(reported_schema_path).expanduser()
            if not reported_schema.is_absolute() and root_dir is not None:
                reported_schema = root_dir / reported_schema
            if reported_schema != expected_schema_path:
                raise CodexFarmRunnerError(
                    "codex-farm process output_schema_path mismatch: "
                    f"expected={expected_schema_path} reported={reported_schema}"
                )

        run_id = _extract_run_id(process_payload)
        payload_exit_code = _extract_exit_code(process_payload)
        telemetry_report_payload = _extract_telemetry_report(process_payload)
        telemetry_payload: dict[str, Any] | None = None
        error_summary: str | None = None
        input_bundle_count = _count_json_bundle_files(in_dir)
        output_bundle_count = _count_json_bundle_files(out_dir)
        if run_id:
            telemetry_payload = _collect_codex_exec_run_telemetry(
                cmd=self.cmd,
                run_id=run_id,
                pipeline_id=pipeline_id,
            )
        failed = completed.returncode != 0 or (payload_exit_code not in {None, 0})
        if failed:
            stderr_summary = _summarize_failure_stderr(completed.stderr)
            if run_id:
                error_summary = _fetch_run_errors_summary(cmd=self.cmd, run_id=run_id, env=env)
            details: list[str] = []
            if run_id:
                details.append(f"run_id={run_id}")
            if payload_exit_code is not None:
                details.append(f"process_exit_code={payload_exit_code}")
            details.append(f"subprocess_exit={completed.returncode}")
            details.append(f"out_dir={out_dir}")
            if input_bundle_count > 0:
                details.append(f"input_bundles={input_bundle_count}")
                details.append(f"output_bundles={output_bundle_count}")
                details.append(
                    f"missing_output_bundles={max(input_bundle_count - output_bundle_count, 0)}"
                )
            if telemetry_payload is not None:
                details.append(f"telemetry_rows={_coerce_int(telemetry_payload.get('row_count')) or 0}")
                summary = telemetry_payload.get("summary")
                if isinstance(summary, dict):
                    rate_limit_rows = _coerce_int(summary.get("rate_limit_suspected_rows")) or 0
                    if rate_limit_rows > 0:
                        details.append(f"rate_limit_suspected_rows={rate_limit_rows}")
                    failure_counts = summary.get("failure_category_counts")
                    if isinstance(failure_counts, dict) and failure_counts:
                        details.append(
                            "failure_categories="
                            + ",".join(
                                f"{str(key)}:{int(value)}"
                                for key, value in sorted(
                                    failure_counts.items(),
                                    key=lambda item: str(item[0]),
                                )
                                if _coerce_int(value) is not None
                            )
                        )
            if error_summary:
                details.append(f"first_error={error_summary}")
            elif stderr_summary:
                details.append(f"stderr_summary={stderr_summary}")
            if _is_recoverable_no_last_agent_message_failure(
                error_summary=error_summary,
                telemetry_payload=telemetry_payload,
                recipe_mode=selected_recipe_mode,
                input_bundle_count=input_bundle_count,
                output_bundle_count=output_bundle_count,
            ):
                recoverable_message = _format_recoverable_partial_output_message(
                    pipeline_id=pipeline_id,
                    run_id=run_id,
                    error_summary=error_summary,
                    input_bundle_count=input_bundle_count,
                    output_bundle_count=output_bundle_count,
                )
                if progress_callback is not None:
                    _emit_progress(recoverable_message)
                    logger.debug(
                        "codex-farm returned non-zero for %s; continuing with partial outputs (%s)",
                        pipeline_id,
                        ", ".join(details),
                    )
                else:
                    logger.warning(
                        "codex-farm returned non-zero for %s; continuing with partial outputs (%s)",
                        pipeline_id,
                        ", ".join(details),
                    )
            else:
                raise CodexFarmRunnerError(
                    f"codex-farm failed for {pipeline_id} ({', '.join(details)})"
                )
        autotune_report_payload: dict[str, Any] | None = None
        if run_id:
            autotune_report_payload = _fetch_run_autotune_payload(
                cmd=self.cmd,
                run_id=run_id,
                pipeline_id=pipeline_id,
                env=env,
            )
        output_schema_path = _extract_output_schema_path(process_payload)
        runtime_mode_audit = _build_runtime_mode_audit(
            command=command,
            output_schema_path=output_schema_path,
        )

        return CodexFarmPipelineRunResult(
            pipeline_id=pipeline_id,
            run_id=run_id,
            subprocess_exit_code=completed.returncode,
            process_exit_code=payload_exit_code,
            output_schema_path=output_schema_path,
            process_payload=process_payload_dict,
            telemetry_report=telemetry_report_payload,
            autotune_report=autotune_report_payload,
            telemetry=telemetry_payload,
            runtime_mode_audit=runtime_mode_audit,
            error_summary=error_summary,
        )
