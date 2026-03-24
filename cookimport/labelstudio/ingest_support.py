from __future__ import annotations

import datetime as dt
import json
import logging
import os
import shlex
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

from cookimport.core.models import ConversionResult
from cookimport.core.progress_messages import format_task_counter
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.prelabel import (
    CodexFarmProvider,
    codex_cmd_with_model,
    codex_cmd_with_reasoning_effort,
    codex_model_from_cmd,
    codex_reasoning_effort_from_cmd,
    default_codex_cmd,
    normalize_codex_reasoning_effort,
    resolve_codex_model,
)
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate, atomize_blocks

logger = logging.getLogger(__name__)


def _notify_progress_callback(
    progress_callback: Callable[[str], None] | None,
    message: str,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ignoring progress callback failure: %s", exc)


def _notify_scheduler_event_callback(
    scheduler_event_callback: Callable[[dict[str, Any]], None] | None,
    *,
    event: str,
    **payload: Any,
) -> None:
    if scheduler_event_callback is None:
        return
    event_name = str(event or "").strip()
    if not event_name:
        return
    event_payload: dict[str, Any] = {
        "event": event_name,
        "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(
            timespec="milliseconds"
        ),
    }
    event_payload.update(payload)
    try:
        scheduler_event_callback(event_payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ignoring scheduler event callback failure: %s", exc)


def _task_progress_message(phase: str, current: int, total: int) -> str:
    return format_task_counter(phase, current, total, noun="task")


def _format_prelabel_prompt_log_entry_markdown(payload: dict[str, Any]) -> str:
    task_index = payload.get("task_index")
    task_total = payload.get("task_total")
    try:
        task_label = f"{int(task_index)}/{int(task_total)}"
    except (TypeError, ValueError):
        task_label = "?"
    segment_id = str(payload.get("segment_id") or "<unknown>")
    included_with_prompt = payload.get("included_with_prompt")
    if not isinstance(included_with_prompt, dict):
        included_with_prompt = {}
    included_json = json.dumps(
        included_with_prompt,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    prompt_text = str(payload.get("prompt") or "")
    if not prompt_text:
        prompt_text = "(empty prompt)"
    description = str(payload.get("included_with_prompt_description") or "").strip()
    if not description:
        description = "No additional prompt context description provided."
    lines = [
        f"## Task {task_label} - `{segment_id}`",
        "",
        f"- Logged at (UTC): `{payload.get('logged_at') or ''}`",
        f"- Task scope: `{payload.get('task_scope') or ''}`",
        f"- Granularity: `{payload.get('granularity') or ''}`",
        f"- Prompt template: `{payload.get('prompt_template') or ''}`",
        f"- Prompt hash: `{payload.get('prompt_hash') or ''}`",
        f"- Codex cmd: `{payload.get('codex_cmd') or ''}`",
        f"- Codex model: `{payload.get('codex_model') or ''}`",
        f"- Codex reasoning effort: `{payload.get('codex_reasoning_effort') or ''}`",
        f"- Codex account: `{payload.get('codex_account') or ''}`",
        f"- Source file: `{payload.get('source_file') or ''}`",
        "",
        "### What Else Was Included",
        "",
        description,
        "",
        "```json",
        included_json,
        "```",
        "",
        "### Prompt",
        "",
        "````text",
        prompt_text,
        "````",
        "",
    ]
    return "\n".join(lines)


@contextmanager
def _temporary_epub_runtime_env(
    *,
    extractor: str,
    html_parser_version: str,
    skip_headers_footers: bool,
    preprocess_mode: str,
) -> Iterable[None]:
    keys = (
        "C3IMP_EPUB_EXTRACTOR",
        "C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION",
        "C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS",
        "C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE",
    )
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["C3IMP_EPUB_EXTRACTOR"] = extractor
    os.environ["C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION"] = html_parser_version
    os.environ["C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS"] = (
        "true" if skip_headers_footers else "false"
    )
    os.environ["C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE"] = preprocess_mode
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timing_payload(
    *,
    total_seconds: float,
    prediction_seconds: float,
    parsing_seconds: float | None = None,
    writing_seconds: float | None = None,
    ocr_seconds: float | None = None,
    artifact_write_seconds: float | None = None,
    checkpoints: dict[str, float] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "total_seconds": float(max(0.0, total_seconds)),
        "prediction_seconds": float(max(0.0, prediction_seconds)),
        "checkpoints": {},
    }
    if parsing_seconds is not None:
        payload["parsing_seconds"] = float(max(0.0, parsing_seconds))
    if writing_seconds is not None:
        payload["writing_seconds"] = float(max(0.0, writing_seconds))
    if ocr_seconds is not None:
        payload["ocr_seconds"] = float(max(0.0, ocr_seconds))
    if artifact_write_seconds is not None:
        payload["artifact_write_seconds"] = float(max(0.0, artifact_write_seconds))

    checkpoint_map: dict[str, float] = {}
    if checkpoints:
        for key, value in checkpoints.items():
            numeric = _safe_float(value)
            if numeric is None or numeric < 0:
                continue
            checkpoint_map[str(key)] = float(numeric)
    payload["checkpoints"] = checkpoint_map
    return payload


def _write_processed_report_timing_best_effort(
    *,
    processed_report_path: Path | None,
    timing: dict[str, Any] | None,
    notify: Callable[[str], None] | None = None,
) -> None:
    if processed_report_path is None or timing is None:
        return
    if not processed_report_path.exists() or not processed_report_path.is_file():
        return

    try:
        payload = json.loads(processed_report_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _notify_progress_callback(
            notify,
            f"Warning: failed reading processed report timing from {processed_report_path}: {exc}",
        )
        return
    if not isinstance(payload, dict):
        return

    existing_timing = payload.get("timing")
    existing_timing_dict = existing_timing if isinstance(existing_timing, dict) else {}
    existing_checkpoints = existing_timing_dict.get("checkpoints")
    checkpoint_payload = (
        dict(existing_checkpoints) if isinstance(existing_checkpoints, dict) else {}
    )
    raw_checkpoints = timing.get("checkpoints")
    if isinstance(raw_checkpoints, dict):
        for key, value in raw_checkpoints.items():
            numeric = _safe_float(value)
            if numeric is None:
                continue
            checkpoint_payload[str(key)] = float(max(0.0, numeric))

    parsing_seconds = _safe_float(timing.get("parsing_seconds"))
    if parsing_seconds is None:
        parsing_seconds = _safe_float(existing_timing_dict.get("parsing_seconds"))
    if parsing_seconds is None:
        parsing_seconds = _safe_float(checkpoint_payload.get("conversion_seconds"))

    writing_seconds = _safe_float(timing.get("writing_seconds"))
    if writing_seconds is None:
        writing_seconds = _safe_float(existing_timing_dict.get("writing_seconds"))
    if writing_seconds is None:
        writing_seconds = _safe_float(
            checkpoint_payload.get("processed_output_write_seconds")
        )

    ocr_seconds = _safe_float(timing.get("ocr_seconds"))
    if ocr_seconds is None:
        ocr_seconds = _safe_float(existing_timing_dict.get("ocr_seconds"))

    prediction_seconds = _safe_float(timing.get("prediction_seconds"))
    total_seconds = _safe_float(timing.get("total_seconds"))
    if total_seconds is None:
        total_seconds = _safe_float(existing_timing_dict.get("total_seconds"))
    if total_seconds is None and prediction_seconds is not None:
        total_seconds = prediction_seconds

    merged_timing: dict[str, Any] = {
        "total_seconds": float(max(0.0, total_seconds or 0.0)),
        "parsing_seconds": float(max(0.0, parsing_seconds or 0.0)),
        "writing_seconds": float(max(0.0, writing_seconds or 0.0)),
        "ocr_seconds": float(max(0.0, ocr_seconds or 0.0)),
        "checkpoints": checkpoint_payload,
    }
    if prediction_seconds is not None:
        merged_timing["prediction_seconds"] = float(max(0.0, prediction_seconds))
    artifact_write_seconds = _safe_float(timing.get("artifact_write_seconds"))
    if artifact_write_seconds is not None:
        merged_timing["artifact_write_seconds"] = float(
            max(0.0, artifact_write_seconds)
        )

    payload["timing"] = merged_timing
    try:
        processed_report_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        _notify_progress_callback(
            notify,
            f"Warning: failed writing processed report timing to {processed_report_path}: {exc}",
        )


def _slugify_name(name: str) -> str:
    import re

    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug or "unknown"


def _dedupe_project_name(base_name: str, existing_titles: set[str]) -> str:
    candidate = base_name
    suffix = 1
    while candidate in existing_titles:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    return candidate


def _resolve_project_name(
    path: Path,
    project_name: str | None,
    client: LabelStudioClient,
) -> str:
    if project_name:
        return project_name

    base_name = path.stem.strip() or _slugify_name(path.stem)
    existing_titles = {
        str(project.get("title", ""))
        for project in client.list_projects()
        if isinstance(project, dict) and project.get("title")
    }
    return _dedupe_project_name(base_name, existing_titles)


def _find_latest_manifest(output_root: Path, project_name: str) -> Path | None:
    manifests = list(output_root.glob("**/labelstudio/**/manifest.json"))
    candidates = []
    for path in manifests:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("project_name") == project_name:
            candidates.append((path.stat().st_mtime, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _task_id_key() -> str:
    return "segment_id"


def _task_id_value(task: dict[str, Any]) -> str | None:
    key = _task_id_key()
    data = task.get("data")
    if not isinstance(data, dict):
        return None
    value = data.get(key)
    if not value:
        return None
    return str(value)


def _strip_task_annotations(task: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(task)
    cleaned.pop("annotations", None)
    cleaned.pop("predictions", None)
    return cleaned


def _task_annotation_pairs_for_upload(
    tasks: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    pairs: list[tuple[str, dict[str, Any]]] = []
    for task in tasks:
        task_id = _task_id_value(task)
        if not task_id:
            continue
        annotations = task.get("annotations")
        if not isinstance(annotations, list) or not annotations:
            continue
        annotation = annotations[0]
        if not isinstance(annotation, dict):
            continue
        pairs.append((task_id, annotation))
    return pairs


def _load_task_ids_from_jsonl(path: Path, key: str) -> set[str]:
    task_ids: set[str] = set()
    if not path.exists():
        return task_ids
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        value = data.get(key)
        if value:
            task_ids.add(str(value))
    return task_ids


def _annotations_to_predictions(task: dict[str, Any]) -> dict[str, Any]:
    converted = _strip_task_annotations(task)
    annotations = task.get("annotations")
    if not isinstance(annotations, list) or not annotations:
        return converted
    annotation = annotations[0]
    if not isinstance(annotation, dict):
        return converted
    result = annotation.get("result")
    if not isinstance(result, list) or not result:
        return converted
    prediction = {
        "model_version": "cookimport-prelabel",
        "score": 1.0,
        "result": result,
    }
    meta = annotation.get("meta")
    if isinstance(meta, dict):
        prediction["meta"] = meta
    converted["predictions"] = [prediction]
    return converted


def _build_prelabel_provider(
    *,
    prelabel_provider: str,
    codex_cmd: str | None,
    codex_model: str | None,
    codex_reasoning_effort: str | None,
    codex_farm_root: Path | str | None,
    codex_farm_workspace_root: Path | str | None,
    prelabel_timeout_seconds: int,
    prelabel_cache_dir: Path | None,
    prelabel_track_token_usage: bool,
) -> CodexFarmProvider:
    normalized_provider = prelabel_provider.strip().lower().replace("_", "-")
    if normalized_provider in {"", "off"}:
        normalized_provider = "codex-farm"
    if normalized_provider != "codex-farm":
        raise ValueError("prelabel_provider must be 'codex-farm'")
    base_cmd = (codex_cmd or default_codex_cmd()).strip()
    try:
        base_argv = shlex.split(base_cmd)
    except ValueError:
        base_argv = []
    if base_argv:
        executable = Path(base_argv[0]).name.lower().strip()
        if executable.startswith("codex") and "farm" not in executable:
            raise ValueError(
                "prelabel --codex-cmd must point at codex-farm (direct local Codex CLI is unsupported)."
            )
    normalized_effort = normalize_codex_reasoning_effort(codex_reasoning_effort)
    resolved_model = resolve_codex_model(codex_model, cmd=base_cmd)
    resolved_cmd = codex_cmd_with_model(base_cmd, resolved_model)
    resolved_cmd = codex_cmd_with_reasoning_effort(resolved_cmd, normalized_effort)
    effective_model = codex_model_from_cmd(resolved_cmd) or resolved_model
    effective_reasoning_effort = (
        codex_reasoning_effort_from_cmd(resolved_cmd) or normalized_effort
    )
    return CodexFarmProvider(
        cmd=resolved_cmd,
        timeout_s=prelabel_timeout_seconds,
        cache_dir=prelabel_cache_dir,
        track_usage=prelabel_track_token_usage,
        model=effective_model,
        reasoning_effort=effective_reasoning_effort,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
    )


def _path_for_manifest(run_root: Path, path_like: Path | str | None) -> str | None:
    if path_like is None:
        return None
    candidate = Path(path_like)
    try:
        return str(candidate.relative_to(run_root))
    except ValueError:
        return str(candidate)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_line_role_candidates_from_archive(
    *,
    archive_payload: list[dict[str, Any]],
    result: ConversionResult,
    atomic_block_splitter: str,
) -> list[AtomicLineCandidate]:
    del result
    staged: list[dict[str, Any]] = []
    for row in sorted(
        archive_payload,
        key=lambda payload: _coerce_int(payload.get("index")) or 0,
    ):
        block_index = _coerce_int(row.get("index"))
        if block_index is None:
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        atomized = atomize_blocks(
            [
                {
                    "block_id": f"block:{block_index}",
                    "block_index": block_index,
                    "text": text,
                }
            ],
            recipe_id=None,
            within_recipe_span=None,
            atomic_block_splitter=atomic_block_splitter,
        )
        for candidate in atomized:
            staged.append(
                {
                    "recipe_id": candidate.recipe_id,
                    "block_id": candidate.block_id,
                    "block_index": candidate.block_index,
                    "text": candidate.text,
                    "within_recipe_span": candidate.within_recipe_span,
                    "rule_tags": list(candidate.rule_tags),
                }
            )

    output: list[AtomicLineCandidate] = []
    for atomic_index, row in enumerate(staged):
        output.append(
            AtomicLineCandidate(
                recipe_id=row["recipe_id"],
                block_id=str(row["block_id"]),
                block_index=int(row["block_index"]),
                atomic_index=atomic_index,
                text=str(row["text"]),
                within_recipe_span=row["within_recipe_span"],
                rule_tags=list(row["rule_tags"]),
            )
        )
    return output
