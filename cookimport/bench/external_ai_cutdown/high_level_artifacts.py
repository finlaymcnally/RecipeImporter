from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from .artifact_paths import (
    _resolve_full_prompt_log_path as _resolve_full_prompt_log_path_impl,
    _resolve_knowledge_manifest_path as _resolve_knowledge_manifest_path_impl,
    _resolve_knowledge_prompt_path as _resolve_knowledge_prompt_path_impl,
    _resolve_prediction_run_dir as _resolve_prediction_run_dir_impl,
    _resolve_processed_output_run_dir as _resolve_processed_output_run_dir_impl,
    _resolve_prompt_type_samples_path as _resolve_prompt_type_samples_path_impl,
)
from .io import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _excerpt,
    _iter_jsonl,
    _load_json,
    _sample_rows_evenly,
)

GROUP_UPLOAD_BUNDLE_ROOT_ARTIFACT_BUDGET_SHARE = 0.8
GROUP_UPLOAD_BUNDLE_MIN_ARTIFACT_BUDGET_BYTES = 4 * 1024 * 1024
GROUP_UPLOAD_BUNDLE_ROOT_PRIORITY_FILES = (
    "run_index.json",
    "comparison_summary.json",
    "process_manifest.json",
    "README.md",
    "changed_lines.benchmark_comparison.jsonl",
    "changed_lines.codex_vs_vanilla.jsonl",
    "per_recipe_or_per_span_breakdown.json",
    "targeted_prompt_cases.md",
    "label_policy_adjudication_notes.md",
)
GROUP_UPLOAD_BUNDLE_RUN_PRIORITY_FILES: tuple[tuple[str, bool], ...] = (
    ("run_manifest.json", True),
    ("eval_report.json", False),
    ("need_to_know_summary.json", False),
)
GROUP_UPLOAD_BUNDLE_RUN_CONTEXT_FILES: tuple[str, ...] = (
    "prompts/prompt_request_response_log.txt",
    "prediction-run/extracted_archive.json",
    "prediction-run/line-role-pipeline/extracted_archive.json",
)
FULL_PROMPT_LOG_FILE_NAME = "full_prompt_log.jsonl"
FULL_PROMPT_LOG_MANIFEST_ARTIFACT_KEYS = (
    "full_prompt_log_path",
    "full_prompt_log_jsonl",
)
PROMPT_TYPE_SAMPLES_FILE_NAME = "prompt_type_samples_from_full_prompt_log.md"
PROMPT_TYPE_SAMPLES_MANIFEST_ARTIFACT_KEYS = (
    "prompt_type_samples_from_full_prompt_log_md",
)
KNOWLEDGE_PROMPT_FILE_NAME = "prompt_nonrecipe_finalize.txt"
KNOWLEDGE_MANIFEST_FILE_NAME = "knowledge_manifest.json"
WRONG_LABEL_FULL_CONTEXT_FILE_NAME = "wrong_label_lines.with_context.full.jsonl.gz"
PREPROCESS_TRACE_FAILURES_FILE_NAME = "preprocess_trace_failures.jsonl.gz"


def _upload_bundle_load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return _load_json(path)
    except Exception:  # noqa: BLE001
        return {}


def _resolve_prompt_budget_summary_path(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    pred_run_dir: Path | None,
    pred_manifest: dict[str, Any],
) -> Path | None:
    candidates: list[Path] = []
    manifest_artifacts = run_manifest.get("artifacts")
    if isinstance(manifest_artifacts, dict):
        for key in ("prompt_budget_summary_json", "actual_costs_json"):
            manifest_path = str(manifest_artifacts.get(key) or "").strip()
            if not manifest_path:
                continue
            candidate = Path(manifest_path)
            candidates.append(candidate if candidate.is_absolute() else run_dir / candidate)
    manifest_path = str(pred_manifest.get("prompt_budget_summary_path") or "").strip()
    if manifest_path:
        candidate = Path(manifest_path)
        if not candidate.is_absolute() and pred_run_dir is not None:
            candidate = pred_run_dir / candidate
        candidates.append(candidate)
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen or not candidate.is_file():
            continue
        seen.add(resolved)
        payload = _upload_bundle_load_json_object(candidate)
        if isinstance(payload.get("by_stage"), dict):
            return candidate
    return None


def _upload_bundle_select_high_level_artifact_paths(
    *,
    source_root: Path,
    discovered_run_dirs: list[Path],
    target_bundle_size_bytes: int,
) -> tuple[list[Path], dict[str, Any]]:
    target_bytes = max(int(target_bundle_size_bytes), 1)
    minimum_budget_bytes = min(GROUP_UPLOAD_BUNDLE_MIN_ARTIFACT_BUDGET_BYTES, target_bytes)
    artifact_budget_bytes = max(
        int(target_bytes * GROUP_UPLOAD_BUNDLE_ROOT_ARTIFACT_BUDGET_SHARE),
        minimum_budget_bytes,
    )
    artifact_budget_bytes = min(artifact_budget_bytes, target_bytes)
    selected: list[Path] = []
    selected_set: set[Path] = set()
    selected_bytes = 0

    def _path_size(path: Path) -> int:
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0

    def _append_if_allowed(path: Path, *, required: bool) -> bool:
        nonlocal selected_bytes
        if path in selected_set or not path.is_file():
            return False
        path_bytes = _path_size(path)
        if not required and selected_bytes + path_bytes > artifact_budget_bytes:
            return False
        selected.append(path)
        selected_set.add(path)
        selected_bytes += path_bytes
        return True

    for relative_path in GROUP_UPLOAD_BUNDLE_ROOT_PRIORITY_FILES:
        _append_if_allowed(source_root / relative_path, required=False)

    included_run_rows: list[dict[str, Any]] = []
    policy_omitted_artifacts: list[dict[str, Any]] = []

    def _record_policy_omission(path: Path, *, reason: str) -> None:
        try:
            relative_path = str(path.relative_to(source_root).as_posix())
        except ValueError:
            relative_path = str(path)
        policy_omitted_artifacts.append(
            {
                "path": relative_path,
                "reason": reason,
                "source_bytes": _path_size(path),
            }
        )

    for run_dir in discovered_run_dirs:
        run_rel = ""
        try:
            run_rel = str(run_dir.relative_to(source_root).as_posix())
        except ValueError:
            run_rel = run_dir.name
        included_files: list[str] = []
        omitted_files: list[dict[str, Any]] = []
        run_manifest_payload = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
        for file_name, required in GROUP_UPLOAD_BUNDLE_RUN_PRIORITY_FILES:
            candidate = run_dir / file_name
            if _append_if_allowed(candidate, required=required):
                included_files.append(file_name)
            elif candidate.is_file():
                omitted_files.append(
                    {
                        "path": file_name,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(candidate),
                    }
                )
        pred_run_dir = _resolve_prediction_run_dir_impl(run_dir, run_manifest_payload)
        pred_manifest = (
            _upload_bundle_load_json_object(pred_run_dir / "manifest.json")
            if pred_run_dir is not None
            else {}
        )
        prompt_budget_summary_path = _resolve_prompt_budget_summary_path(
            run_dir=run_dir,
            run_manifest=run_manifest_payload,
            pred_run_dir=pred_run_dir,
            pred_manifest=pred_manifest,
        )
        if prompt_budget_summary_path is not None:
            if _append_if_allowed(prompt_budget_summary_path, required=False):
                try:
                    included_files.append(
                        str(prompt_budget_summary_path.relative_to(run_dir).as_posix())
                    )
                except ValueError:
                    included_files.append(str(prompt_budget_summary_path))
            else:
                try:
                    omitted_path = str(prompt_budget_summary_path.relative_to(run_dir).as_posix())
                except ValueError:
                    omitted_path = str(prompt_budget_summary_path)
                omitted_files.append(
                    {
                        "path": omitted_path,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(prompt_budget_summary_path),
                    }
                )
        prompt_type_samples_path = _resolve_prompt_type_samples_path_impl(
            run_dir=run_dir,
            run_manifest=run_manifest_payload,
            prompt_type_samples_manifest_artifact_keys=(
                PROMPT_TYPE_SAMPLES_MANIFEST_ARTIFACT_KEYS
            ),
            prompt_type_samples_file_name=PROMPT_TYPE_SAMPLES_FILE_NAME,
        )
        if prompt_type_samples_path is not None:
            try:
                prompt_type_samples_path.relative_to(source_root)
            except ValueError:
                prompt_type_samples_path = None
        if prompt_type_samples_path is not None:
            if _append_if_allowed(prompt_type_samples_path, required=False):
                try:
                    included_files.append(
                        str(prompt_type_samples_path.relative_to(run_dir).as_posix())
                    )
                except ValueError:
                    included_files.append(str(prompt_type_samples_path))
            else:
                try:
                    omitted_path = str(prompt_type_samples_path.relative_to(run_dir).as_posix())
                except ValueError:
                    omitted_path = str(prompt_type_samples_path)
                omitted_files.append(
                    {
                        "path": omitted_path,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(prompt_type_samples_path),
                    }
                )
        knowledge_manifest_path = _resolve_knowledge_manifest_path_impl(
            run_dir=run_dir,
            run_manifest=run_manifest_payload,
            knowledge_manifest_file_name=KNOWLEDGE_MANIFEST_FILE_NAME,
        )
        if knowledge_manifest_path is not None:
            try:
                knowledge_manifest_path.relative_to(source_root)
            except ValueError:
                knowledge_manifest_path = None
        if knowledge_manifest_path is not None:
            if _append_if_allowed(knowledge_manifest_path, required=False):
                try:
                    included_files.append(
                        str(knowledge_manifest_path.relative_to(run_dir).as_posix())
                    )
                except ValueError:
                    included_files.append(str(knowledge_manifest_path))
            else:
                try:
                    omitted_path = str(knowledge_manifest_path.relative_to(run_dir).as_posix())
                except ValueError:
                    omitted_path = str(knowledge_manifest_path)
                omitted_files.append(
                    {
                        "path": omitted_path,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(knowledge_manifest_path),
                    }
                )
        for relative_path in GROUP_UPLOAD_BUNDLE_RUN_CONTEXT_FILES:
            candidate = run_dir / relative_path
            if _append_if_allowed(candidate, required=False):
                included_files.append(relative_path)
            elif candidate.is_file():
                omitted_files.append(
                    {
                        "path": relative_path,
                        "reason": "artifact_budget_exceeded",
                        "source_bytes": _path_size(candidate),
                    }
                )
        full_prompt_log_path = _resolve_full_prompt_log_path_impl(
            run_dir=run_dir,
            run_manifest=run_manifest_payload,
            full_prompt_log_manifest_artifact_keys=(
                FULL_PROMPT_LOG_MANIFEST_ARTIFACT_KEYS
            ),
            full_prompt_log_file_name=FULL_PROMPT_LOG_FILE_NAME,
        )
        if full_prompt_log_path is not None and full_prompt_log_path.is_file():
            try:
                full_prompt_log_path.relative_to(source_root)
            except ValueError:
                full_prompt_log_path = None
        if full_prompt_log_path is not None:
            try:
                omitted_path = str(full_prompt_log_path.relative_to(run_dir).as_posix())
            except ValueError:
                omitted_path = str(full_prompt_log_path)
            omitted_files.append(
                {
                    "path": omitted_path,
                    "reason": "followup_only_heavy_prompt_log",
                    "source_bytes": _path_size(full_prompt_log_path),
                }
            )
            _record_policy_omission(
                full_prompt_log_path,
                reason="followup_only_heavy_prompt_log",
            )
        knowledge_prompt_path = _resolve_knowledge_prompt_path_impl(
            run_dir=run_dir,
            knowledge_prompt_file_name=KNOWLEDGE_PROMPT_FILE_NAME,
        )
        if knowledge_prompt_path is not None and knowledge_prompt_path.is_file():
            try:
                omitted_path = str(knowledge_prompt_path.relative_to(run_dir).as_posix())
            except ValueError:
                omitted_path = str(knowledge_prompt_path)
            omitted_files.append(
                {
                    "path": omitted_path,
                    "reason": "followup_only_heavy_prompt_context",
                    "source_bytes": _path_size(knowledge_prompt_path),
                }
            )
            _record_policy_omission(
                knowledge_prompt_path,
                reason="followup_only_heavy_prompt_context",
            )
        for heavy_name, omission_reason in (
            (WRONG_LABEL_FULL_CONTEXT_FILE_NAME, "followup_only_full_context_trace"),
            (PREPROCESS_TRACE_FAILURES_FILE_NAME, "followup_only_full_context_trace"),
        ):
            heavy_path = run_dir / heavy_name
            if not heavy_path.is_file():
                continue
            omitted_files.append(
                {
                    "path": heavy_name,
                    "reason": omission_reason,
                    "source_bytes": _path_size(heavy_path),
                }
            )
            _record_policy_omission(heavy_path, reason=omission_reason)
        included_run_rows.append(
            {
                "run_dir": run_rel,
                "included_files": included_files,
                "omitted_files": omitted_files,
            }
        )

    metadata = {
        "mode": "high_level_only",
        "target_bundle_size_bytes": target_bytes,
        "artifact_budget_bytes": artifact_budget_bytes,
        "selected_artifact_count": len(selected),
        "selected_artifact_bytes": selected_bytes,
        "discovered_run_count": len(discovered_run_dirs),
        "per_run_included_files": included_run_rows,
        "policy_omitted_artifacts": policy_omitted_artifacts,
        "policy_omitted_artifact_count": len(policy_omitted_artifacts),
    }
    return selected, metadata


def _upload_bundle_content_type_impl(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name.endswith(".jsonl.gz"):
        return "jsonl_gzip"
    if suffix == ".json":
        return "json"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".md":
        return "markdown"
    if suffix == ".txt":
        return "text"
    if suffix == ".csv":
        return "csv"
    if suffix == ".gz":
        return "gzip"
    return "binary"


def _upload_bundle_parse_jsonl_text_impl(text: str) -> list[Any]:
    rows: list[Any] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append(
                {
                    "_parse_error": "invalid_json",
                    "_line_number": line_number,
                    "_raw_line": raw_line,
                }
            )
    return rows


def _upload_bundle_parse_csv_text_impl(text: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    return {
        "fieldnames": list(reader.fieldnames or []),
        "rows": rows,
    }


def _upload_bundle_category_impl(
    relative_path: str,
    run_output_dirs: set[str],
    *,
    starter_pack_dir_name: str,
) -> tuple[str, str | None]:
    parts = relative_path.split("/")
    if not parts:
        return ("other", None)
    first = parts[0]
    if first == starter_pack_dir_name:
        return ("starter_pack", None)
    if first in run_output_dirs:
        return ("run_artifact", first)
    if len(parts) == 1:
        return ("root_artifact", None)
    return ("other", None)


def _upload_bundle_load_csv_rows_impl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            if isinstance(row, dict):
                rows.append(dict(row))
    except csv.Error:
        return []
    return rows


def _upload_bundle_load_recipe_triage_rows_impl(
    starter_pack_dir: Path,
    *,
    starter_pack_triage_file_name: str,
    starter_pack_triage_legacy_csv_file_name: str,
) -> list[dict[str, Any]]:
    jsonl_rows = _iter_jsonl(starter_pack_dir / starter_pack_triage_file_name)
    if jsonl_rows:
        return [row for row in jsonl_rows if isinstance(row, dict)]
    return _upload_bundle_load_csv_rows_impl(
        starter_pack_dir / starter_pack_triage_legacy_csv_file_name
    )


def _json_size_bytes_impl(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    except Exception:  # noqa: BLE001
        return 0


def _json_dump_bytes_impl(
    value: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=indent,
        sort_keys=sort_keys,
    ).encode("utf-8")


def _upload_bundle_payload_row_line_bytes_impl(payload_row: dict[str, Any]) -> int:
    return len(_json_dump_bytes_impl(payload_row)) + 1


def _upload_bundle_high_level_final_reserve_bytes_impl(
    target_bundle_size_bytes: int,
    *,
    final_reserve_share: float,
    final_reserve_min_bytes: int,
) -> int:
    target_bytes = max(int(target_bundle_size_bytes), 1)
    reserve_bytes = max(
        int(target_bytes * final_reserve_share),
        int(final_reserve_min_bytes),
    )
    return min(reserve_bytes, max(target_bytes - 1, 0))


def _upload_bundle_high_level_trim_priority_impl(
    path: str,
    *,
    prompt_request_response_log_name: str,
    targeted_prompt_cases_file_name: str,
    label_policy_notes_file_name: str,
    starter_pack_casebook_file_name: str,
    starter_pack_selected_packets_file_name: str,
    starter_pack_bridge_summary_file_name: str,
    starter_pack_explicit_escalation_changed_lines_file_name: str,
    starter_pack_baseline_trace_parity_file_name: str,
    starter_pack_config_version_metadata_file_name: str,
    starter_pack_net_error_blame_file_name: str,
    changed_lines_file_name: str,
    upload_bundle_derived_dir_name: str,
    starter_pack_dir_name: str,
) -> tuple[int, str] | None:
    normalized = str(path or "").strip().lower()
    if not normalized:
        return None
    direct_suffixes = (
        (
            (
                FULL_PROMPT_LOG_FILE_NAME,
                WRONG_LABEL_FULL_CONTEXT_FILE_NAME,
                PREPROCESS_TRACE_FAILURES_FILE_NAME,
                prompt_request_response_log_name,
                "recipe_manifest.json",
            ),
            0,
        ),
        (
            (
                targeted_prompt_cases_file_name,
                label_policy_notes_file_name,
                starter_pack_casebook_file_name,
                starter_pack_selected_packets_file_name,
                starter_pack_bridge_summary_file_name,
            ),
            1,
        ),
        (
            (
                starter_pack_explicit_escalation_changed_lines_file_name,
                "explicit_escalation_changed_lines.packet.jsonl",
                starter_pack_baseline_trace_parity_file_name,
                "baseline_trace_parity.json",
                starter_pack_config_version_metadata_file_name,
                "config_version_metadata.json",
                starter_pack_net_error_blame_file_name,
                "net_error_blame_summary.json",
                PROMPT_TYPE_SAMPLES_FILE_NAME,
                KNOWLEDGE_MANIFEST_FILE_NAME,
                changed_lines_file_name.rsplit("/", 1)[-1],
                "prediction-run/extracted_archive.json",
                "prediction-run/line-role-pipeline/extracted_archive.json",
                "extracted_archive.json",
            ),
            2,
        ),
        (
            (
                "need_to_know_summary.json",
                "eval_report.json",
                "prompt_budget_summary.json",
            ),
            3,
        ),
    )
    for suffixes, priority in direct_suffixes:
        if normalized.endswith(suffixes):
            return (priority, "final_size_trim")
    if f"/{upload_bundle_derived_dir_name}/{starter_pack_dir_name}/" in normalized:
        return (1, "final_size_trim")
    if f"/{starter_pack_dir_name}/" in normalized:
        return (2, "final_size_trim")
    return None


def _upload_bundle_trim_high_level_payload_rows_impl(
    *,
    payload_rows: list[dict[str, Any]],
    target_payload_bytes: int,
    preserve_paths: set[str],
    prompt_request_response_log_name: str,
    targeted_prompt_cases_file_name: str,
    label_policy_notes_file_name: str,
    starter_pack_casebook_file_name: str,
    starter_pack_selected_packets_file_name: str,
    starter_pack_bridge_summary_file_name: str,
    starter_pack_explicit_escalation_changed_lines_file_name: str,
    starter_pack_baseline_trace_parity_file_name: str,
    starter_pack_config_version_metadata_file_name: str,
    starter_pack_net_error_blame_file_name: str,
    changed_lines_file_name: str,
    upload_bundle_derived_dir_name: str,
    starter_pack_dir_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current_payload_bytes = sum(
        _upload_bundle_payload_row_line_bytes_impl(row)
        for row in payload_rows
        if isinstance(row, dict)
    )
    omitted_rows: list[dict[str, Any]] = []
    if current_payload_bytes <= max(int(target_payload_bytes), 0):
        return payload_rows, {
            "target_payload_bytes": max(int(target_payload_bytes), 0),
            "final_payload_bytes": current_payload_bytes,
            "omitted_artifact_count": 0,
            "omitted_bytes_estimate": 0,
            "omitted_artifacts": [],
        }

    candidate_rows: list[tuple[int, str, int, int]] = []
    for index, row in enumerate(payload_rows):
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip()
        if not path or path in preserve_paths:
            continue
        priority = _upload_bundle_high_level_trim_priority_impl(
            path,
            prompt_request_response_log_name=prompt_request_response_log_name,
            targeted_prompt_cases_file_name=targeted_prompt_cases_file_name,
            label_policy_notes_file_name=label_policy_notes_file_name,
            starter_pack_casebook_file_name=starter_pack_casebook_file_name,
            starter_pack_selected_packets_file_name=starter_pack_selected_packets_file_name,
            starter_pack_bridge_summary_file_name=starter_pack_bridge_summary_file_name,
            starter_pack_explicit_escalation_changed_lines_file_name=(
                starter_pack_explicit_escalation_changed_lines_file_name
            ),
            starter_pack_baseline_trace_parity_file_name=(
                starter_pack_baseline_trace_parity_file_name
            ),
            starter_pack_config_version_metadata_file_name=(
                starter_pack_config_version_metadata_file_name
            ),
            starter_pack_net_error_blame_file_name=starter_pack_net_error_blame_file_name,
            changed_lines_file_name=changed_lines_file_name,
            upload_bundle_derived_dir_name=upload_bundle_derived_dir_name,
            starter_pack_dir_name=starter_pack_dir_name,
        )
        if priority is None:
            continue
        candidate_rows.append(
            (
                int(priority[0]),
                path,
                _upload_bundle_payload_row_line_bytes_impl(row),
                index,
            )
        )

    candidate_rows.sort(
        key=lambda item: (
            int(item[0]),
            -int(item[2]),
            str(item[1]),
        )
    )

    dropped_paths: set[str] = set()
    omitted_bytes_estimate = 0
    for priority, path, estimated_payload_bytes, _index in candidate_rows:
        if current_payload_bytes <= target_payload_bytes:
            break
        dropped_paths.add(path)
        current_payload_bytes -= estimated_payload_bytes
        omitted_bytes_estimate += estimated_payload_bytes
        omitted_rows.append(
            {
                "path": path,
                "reason": "final_size_trim",
                "trim_priority": priority,
                "estimated_payload_bytes": estimated_payload_bytes,
            }
        )

    if not dropped_paths:
        return payload_rows, {
            "target_payload_bytes": max(int(target_payload_bytes), 0),
            "final_payload_bytes": current_payload_bytes,
            "omitted_artifact_count": 0,
            "omitted_bytes_estimate": 0,
            "omitted_artifacts": [],
        }

    trimmed_rows = [
        row
        for row in payload_rows
        if isinstance(row, dict) and str(row.get("path") or "").strip() not in dropped_paths
    ]
    return trimmed_rows, {
        "target_payload_bytes": max(int(target_payload_bytes), 0),
        "final_payload_bytes": sum(
            _upload_bundle_payload_row_line_bytes_impl(row) for row in trimmed_rows
        ),
        "omitted_artifact_count": len(omitted_rows),
        "omitted_bytes_estimate": omitted_bytes_estimate,
        "omitted_artifacts": omitted_rows,
    }


def _source_file_name(path_raw: str | None) -> str | None:
    if not isinstance(path_raw, str) or not path_raw.strip():
        return None
    return Path(path_raw).name


def _upload_bundle_build_group_high_level_packet_impl(
    *,
    source_root: Path,
    discovered_run_dirs: list[Path],
    run_rows: list[dict[str, Any]],
    run_diagnostics: list[dict[str, Any]],
    target_bundle_size_bytes: int,
    payload_bytes_before_packet: int,
    artifact_selection: dict[str, Any],
    group_upload_bundle_reserved_bytes: int,
    group_upload_bundle_min_wrong_line_samples_per_run: int,
    group_upload_bundle_max_wrong_line_samples_per_run: int,
    timestamp_now: callable,
) -> dict[str, Any]:
    run_row_by_id: dict[str, dict[str, Any]] = {}
    run_row_by_subdir: dict[str, dict[str, Any]] = {}
    for row in run_rows:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "").strip()
        if run_id:
            run_row_by_id.setdefault(run_id, row)
        output_subdir = str(row.get("output_subdir") or "").strip()
        if output_subdir:
            run_row_by_subdir.setdefault(output_subdir, row)

    run_diag_by_id: dict[str, dict[str, Any]] = {}
    run_diag_by_subdir: dict[str, dict[str, Any]] = {}
    for row in run_diagnostics:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "").strip()
        if run_id:
            run_diag_by_id.setdefault(run_id, row)
        output_subdir = str(row.get("output_subdir") or "").strip()
        if output_subdir:
            run_diag_by_subdir.setdefault(output_subdir, row)

    run_payloads: list[dict[str, Any]] = []
    run_count = len(discovered_run_dirs)
    target_bytes = max(int(target_bundle_size_bytes), 1)
    reserved_bytes = min(
        max(int(group_upload_bundle_reserved_bytes), target_bytes // 8),
        max(target_bytes // 2, 1),
    )
    budget_for_samples = max(target_bytes - int(payload_bytes_before_packet) - reserved_bytes, 0)
    per_run_sample_budget_bytes = (
        max(budget_for_samples // run_count, 0) if run_count > 0 else 0
    )

    sampled_wrong_line_rows_total = 0
    sampled_wrong_line_bytes_total = 0
    runs_with_sampled_rows = 0

    for run_dir in discovered_run_dirs:
        run_manifest = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
        eval_report = _upload_bundle_load_json_object(run_dir / "eval_report.json")
        run_id = str(run_manifest.get("run_id") or run_dir.name).strip() or run_dir.name
        try:
            output_subdir = str(run_dir.relative_to(source_root).as_posix())
        except ValueError:
            output_subdir = run_dir.name

        run_row = run_row_by_id.get(run_id) or run_row_by_subdir.get(output_subdir) or {}
        run_diag = run_diag_by_id.get(run_id) or run_diag_by_subdir.get(output_subdir) or {}
        source_payload = (
            run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
        )
        source_path = source_payload.get("path") if isinstance(source_payload, dict) else None
        source_file = source_path if isinstance(source_path, str) else None

        wrong_line_candidates: list[dict[str, Any]] = []
        wrong_line_rows = _iter_jsonl(run_dir / "wrong_label_lines.jsonl")
        for row in wrong_line_rows:
            if not isinstance(row, dict):
                continue
            line_index = _coerce_int(row.get("line_index"))
            if line_index is None:
                continue
            text_value = ""
            for key in ("current_line", "line_text", "text"):
                candidate_text = row.get(key)
                if isinstance(candidate_text, str) and candidate_text.strip():
                    text_value = candidate_text.strip()
                    break
            wrong_line_candidates.append(
                {
                    "line_index": int(line_index),
                    "recipe_id": str(row.get("recipe_id") or ""),
                    "gold_label": str(row.get("gold_label") or ""),
                    "pred_label": str(row.get("pred_label") or ""),
                    "line_excerpt": _excerpt(text_value, max_len=160),
                }
            )

        wrong_line_samples: list[dict[str, Any]] = []
        if wrong_line_candidates and per_run_sample_budget_bytes > 0:
            probe_rows = wrong_line_candidates[: min(12, len(wrong_line_candidates))]
            average_row_bytes = max(
                int(
                    sum(_json_size_bytes_impl(item) for item in probe_rows)
                    / max(len(probe_rows), 1)
                ),
                1,
            )
            max_rows_by_budget = max(per_run_sample_budget_bytes // average_row_bytes, 0)
            max_rows = min(
                len(wrong_line_candidates),
                int(group_upload_bundle_max_wrong_line_samples_per_run),
            )
            if max_rows_by_budget > 0:
                max_rows = min(max_rows, int(max_rows_by_budget))
            if max_rows <= 0:
                max_rows = min(
                    int(group_upload_bundle_min_wrong_line_samples_per_run),
                    len(wrong_line_candidates),
                )
            wrong_line_samples = _sample_rows_evenly(wrong_line_candidates, max_rows)
            while (
                len(wrong_line_samples) > 1
                and _json_size_bytes_impl(wrong_line_samples) > per_run_sample_budget_bytes
            ):
                wrong_line_samples = wrong_line_samples[:-1]

        sampled_wrong_line_rows_total += len(wrong_line_samples)
        sampled_wrong_line_bytes_total += _json_size_bytes_impl(wrong_line_samples)
        if wrong_line_samples:
            runs_with_sampled_rows += 1

        run_payloads.append(
            {
                "run_id": run_id,
                "output_subdir": output_subdir,
                "source_file": _source_file_name(source_file),
                "llm_recipe_pipeline": str(
                    run_row.get("llm_recipe_pipeline")
                    or ((run_manifest.get("run_config") or {}).get("llm_recipe_pipeline"))
                    or "unknown"
                ),
                "line_role_pipeline": str(
                    run_row.get("line_role_pipeline")
                    or ((run_manifest.get("run_config") or {}).get("line_role_pipeline"))
                    or "off"
                ),
                "overall_line_accuracy": _coerce_float(
                    run_row.get("overall_line_accuracy")
                    if isinstance(run_row, dict)
                    else eval_report.get("overall_line_accuracy")
                ),
                "macro_f1_excluding_other": _coerce_float(
                    run_row.get("macro_f1_excluding_other")
                    if isinstance(run_row, dict)
                    else eval_report.get("macro_f1_excluding_other")
                ),
                "practical_f1": _coerce_float(
                    run_row.get("practical_f1")
                    if isinstance(run_row, dict)
                    else eval_report.get("practical_f1")
                ),
                "full_prompt_log_status": str(
                    run_diag.get("full_prompt_log_status")
                    if isinstance(run_diag, dict)
                    else run_row.get("full_prompt_log_status")
                    or "unknown"
                ),
                "wrong_line_total": len(wrong_line_rows),
                "sampled_wrong_line_count": len(wrong_line_samples),
                "sampled_wrong_lines": wrong_line_samples,
            }
        )

    return {
        "schema_version": "upload_bundle_group_high_level.v1",
        "generated_at": timestamp_now(),
        "source_root": str(source_root),
        "run_count": run_count,
        "target_bundle_size_bytes": target_bytes,
        "target_bundle_size_mb": round(target_bytes / (1024 * 1024), 3),
        "payload_bytes_before_group_packet": int(payload_bytes_before_packet),
        "reserved_bytes_for_index_overview": reserved_bytes,
        "budget_for_group_samples_bytes": budget_for_samples,
        "per_run_sample_budget_bytes": per_run_sample_budget_bytes,
        "artifact_selection": artifact_selection,
        "runs_with_sampled_rows": runs_with_sampled_rows,
        "sampled_wrong_line_rows_total": sampled_wrong_line_rows_total,
        "sampled_wrong_line_bytes_total": sampled_wrong_line_bytes_total,
        "runs": run_payloads,
    }


def _upload_bundle_optional_artifact_status_impl(*, path: Path | None, enabled: bool) -> str:
    if isinstance(path, Path) and path.is_file():
        return "written"
    return "missing" if enabled else "not_applicable"


def _upload_bundle_relative_path_within_root_impl(
    *,
    source_root: Path,
    candidate: Path | None,
) -> str | None:
    if not isinstance(candidate, Path):
        return None
    try:
        return str(candidate.resolve().relative_to(source_root).as_posix())
    except Exception:  # noqa: BLE001
        return None


def _upload_bundle_derived_run_artifact_path_impl(
    *,
    output_subdir: str,
    file_name: str,
    upload_bundle_derived_dir_name: str,
) -> str:
    normalized_subdir = str(output_subdir or "").strip().strip("/")
    normalized_subdir = normalized_subdir or "unknown_run"
    return f"{upload_bundle_derived_dir_name}/runs/{normalized_subdir}/{file_name}"


def _upload_bundle_load_prompt_budget_summary_impl(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    pred_run_dir: Path | None,
    pred_manifest: dict[str, Any],
) -> dict[str, Any]:
    prompt_budget_summary_path = _resolve_prompt_budget_summary_path(
        run_dir=run_dir,
        run_manifest=run_manifest,
        pred_run_dir=pred_run_dir,
        pred_manifest=pred_manifest,
    )
    if prompt_budget_summary_path is None:
        return {}
    return _upload_bundle_load_json_object(prompt_budget_summary_path)


def _upload_bundle_build_knowledge_summary_impl(
    *,
    source_root: Path,
    discovered_run_dirs: list[Path],
    upload_bundle_derived_dir_name: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    locator_rows: list[dict[str, Any]] = []
    enabled_run_count = 0
    runs_with_prompt_samples = 0
    runs_with_knowledge_manifest = 0
    total_knowledge_call_count = 0
    shards_written_total = 0
    outputs_parsed_total = 0
    snippets_written_total = 0

    for run_dir in discovered_run_dirs:
        run_manifest = _upload_bundle_load_json_object(run_dir / "run_manifest.json")
        run_id = str(run_manifest.get("run_id") or run_dir.name).strip() or run_dir.name
        try:
            output_subdir = str(run_dir.resolve().relative_to(source_root).as_posix())
        except Exception:  # noqa: BLE001
            output_subdir = run_dir.name

        run_config = run_manifest.get("run_config")
        run_config = run_config if isinstance(run_config, dict) else {}
        prediction_run_config = run_config.get("prediction_run_config")
        prediction_run_config = (
            prediction_run_config if isinstance(prediction_run_config, dict) else {}
        )
        llm_knowledge_pipeline = str(
            prediction_run_config.get("llm_knowledge_pipeline")
            or run_config.get("llm_knowledge_pipeline")
            or ""
        ).strip()

        pred_run_dir = _resolve_prediction_run_dir_impl(run_dir, run_manifest)
        pred_manifest = (
            _upload_bundle_load_json_object(pred_run_dir / "manifest.json")
            if pred_run_dir is not None
            else {}
        )
        processed_output_dir = _resolve_processed_output_run_dir_impl(run_dir, run_manifest)
        knowledge_outputs: dict[str, Any] = {}
        if processed_output_dir is not None:
            for candidate in (
                processed_output_dir / "09_knowledge_outputs.json",
                processed_output_dir / "09_nonrecipe_finalize_status.json",
            ):
                if not candidate.is_file():
                    continue
                knowledge_outputs = _upload_bundle_load_json_object(candidate)
                break
        llm_payload = (
            pred_manifest.get("llm_codex_farm") if isinstance(pred_manifest, dict) else {}
        )
        llm_payload = llm_payload if isinstance(llm_payload, dict) else {}
        knowledge_payload = llm_payload.get("knowledge")
        knowledge_payload = knowledge_payload if isinstance(knowledge_payload, dict) else {}
        manifest_knowledge_counts = (
            knowledge_payload.get("counts")
            if isinstance(knowledge_payload.get("counts"), dict)
            else {}
        )
        outputs_knowledge_counts = (
            knowledge_outputs.get("counts")
            if isinstance(knowledge_outputs.get("counts"), dict)
            else {}
        )
        knowledge_counts = (
            manifest_knowledge_counts if manifest_knowledge_counts else outputs_knowledge_counts
        )

        prompt_budget_summary = _upload_bundle_load_prompt_budget_summary_impl(
            run_dir=run_dir,
            run_manifest=run_manifest,
            pred_run_dir=pred_run_dir,
            pred_manifest=pred_manifest,
        )
        prompt_budget_by_stage = (
            prompt_budget_summary.get("by_stage")
            if isinstance(prompt_budget_summary, dict)
            else {}
        )
        prompt_budget_by_stage = (
            prompt_budget_by_stage if isinstance(prompt_budget_by_stage, dict) else {}
        )
        knowledge_budget = (
            prompt_budget_by_stage.get("knowledge")
            if isinstance(prompt_budget_by_stage.get("knowledge"), dict)
            else {}
        )
        knowledge_call_count = _coerce_int(knowledge_budget.get("call_count"))
        knowledge_token_total = _coerce_int(knowledge_budget.get("tokens_total"))

        prompt_samples_path = _resolve_prompt_type_samples_path_impl(
            run_dir=run_dir,
            run_manifest=run_manifest,
            prompt_type_samples_manifest_artifact_keys=(
                PROMPT_TYPE_SAMPLES_MANIFEST_ARTIFACT_KEYS
            ),
            prompt_type_samples_file_name=PROMPT_TYPE_SAMPLES_FILE_NAME,
        )
        knowledge_prompt_path = _resolve_knowledge_prompt_path_impl(
            run_dir=run_dir,
            knowledge_prompt_file_name=KNOWLEDGE_PROMPT_FILE_NAME,
        )
        knowledge_manifest_path = _resolve_knowledge_manifest_path_impl(
            run_dir=run_dir,
            run_manifest=run_manifest,
            knowledge_manifest_file_name=KNOWLEDGE_MANIFEST_FILE_NAME,
        )
        prompt_budget_path = _resolve_prompt_budget_summary_path(
            run_dir=run_dir,
            run_manifest=run_manifest,
            pred_run_dir=pred_run_dir,
            pred_manifest=pred_manifest,
        )
        knowledge_manifest_locator_path = _upload_bundle_relative_path_within_root_impl(
            source_root=source_root,
            candidate=knowledge_manifest_path,
        )
        knowledge_manifest_source_path: Path | None = None
        if knowledge_manifest_locator_path is None and isinstance(knowledge_manifest_path, Path):
            knowledge_manifest_locator_path = _upload_bundle_derived_run_artifact_path_impl(
                output_subdir=output_subdir,
                file_name=KNOWLEDGE_MANIFEST_FILE_NAME,
                upload_bundle_derived_dir_name=upload_bundle_derived_dir_name,
            )
            knowledge_manifest_source_path = knowledge_manifest_path

        knowledge_enabled = bool(
            _coerce_bool(knowledge_payload.get("enabled"))
            or _coerce_bool(knowledge_outputs.get("enabled"))
        )
        enabled = bool(
            knowledge_enabled
            or (knowledge_call_count is not None and knowledge_call_count > 0)
            or isinstance(knowledge_manifest_path, Path)
            or llm_knowledge_pipeline not in {"", "off", "none"}
        )

        if enabled:
            enabled_run_count += 1
        if isinstance(prompt_samples_path, Path) and prompt_samples_path.is_file():
            runs_with_prompt_samples += 1
        if isinstance(knowledge_manifest_path, Path) and knowledge_manifest_path.is_file():
            runs_with_knowledge_manifest += 1
        total_knowledge_call_count += int(knowledge_call_count or 0)
        shards_written_total += int(_coerce_int(knowledge_counts.get("shards_written")) or 0)
        outputs_parsed_total += int(_coerce_int(knowledge_counts.get("outputs_parsed")) or 0)
        snippets_written_total += int(_coerce_int(knowledge_counts.get("snippets_written")) or 0)

        rows.append(
            {
                "run_id": run_id,
                "output_subdir": output_subdir,
                "enabled": enabled,
                "llm_knowledge_pipeline": llm_knowledge_pipeline or "off",
                "pipeline": str(knowledge_payload.get("pipeline") or "").strip(),
                "pipeline_id": str(knowledge_payload.get("pipeline_id") or "").strip(),
                "knowledge_call_count": int(knowledge_call_count or 0),
                "knowledge_token_total": int(knowledge_token_total or 0),
                "shards_written": int(_coerce_int(knowledge_counts.get("shards_written")) or 0),
                "outputs_parsed": int(_coerce_int(knowledge_counts.get("outputs_parsed")) or 0),
                "snippets_written": int(_coerce_int(knowledge_counts.get("snippets_written")) or 0),
                "prompt_samples_status": _upload_bundle_optional_artifact_status_impl(
                    path=prompt_samples_path,
                    enabled=enabled,
                ),
                "prompt_knowledge_status": _upload_bundle_optional_artifact_status_impl(
                    path=knowledge_prompt_path,
                    enabled=enabled,
                ),
                "knowledge_manifest_status": _upload_bundle_optional_artifact_status_impl(
                    path=knowledge_manifest_path,
                    enabled=enabled,
                ),
                "prompt_budget_summary_status": _upload_bundle_optional_artifact_status_impl(
                    path=prompt_budget_path,
                    enabled=enabled,
                ),
            }
        )
        locator_rows.append(
            {
                "run_id": run_id,
                "output_subdir": output_subdir,
                "prompt_samples_path": _upload_bundle_relative_path_within_root_impl(
                    source_root=source_root,
                    candidate=prompt_samples_path,
                ),
                "prompt_knowledge_path": _upload_bundle_relative_path_within_root_impl(
                    source_root=source_root,
                    candidate=knowledge_prompt_path,
                ),
                "prompt_budget_summary_path": _upload_bundle_relative_path_within_root_impl(
                    source_root=source_root,
                    candidate=prompt_budget_path,
                ),
                "knowledge_manifest_path": knowledge_manifest_locator_path,
                "knowledge_manifest_source_path": knowledge_manifest_source_path,
            }
        )

    summary = {
        "schema_version": "upload_bundle_knowledge.v1",
        "run_count": len(rows),
        "enabled_run_count": enabled_run_count,
        "runs_with_prompt_samples": runs_with_prompt_samples,
        "runs_with_knowledge_manifest": runs_with_knowledge_manifest,
        "total_knowledge_call_count": total_knowledge_call_count,
        "shards_written_total": shards_written_total,
        "outputs_parsed_total": outputs_parsed_total,
        "snippets_written_total": snippets_written_total,
        "rows": rows,
    }
    return summary, locator_rows
