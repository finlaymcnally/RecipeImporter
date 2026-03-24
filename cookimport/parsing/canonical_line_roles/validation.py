from __future__ import annotations

import sys

runtime = sys.modules["cookimport.parsing.canonical_line_roles"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)

def _validate_line_role_shard_proposal(
    shard: ShardManifestEntryV1,
    payload: dict[str, Any],
) -> tuple[bool, Sequence[str], dict[str, Any] | None]:
    if not isinstance(payload, dict):
        return False, ("proposal_not_a_json_object",), None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return False, ("rows_missing_or_not_a_list",), None
    owned_atomic_indices = [int(value) for value in shard.owned_ids]
    expected_owned = set(owned_atomic_indices)
    seen_owned: set[int] = set()
    errors: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append("row_not_a_json_object")
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            errors.append("atomic_index_missing")
            continue
        label = str(row.get("label") or "").strip()
        if not label:
            errors.append(f"missing_label:{atomic_index}")
        elif label not in FREEFORM_ALLOWED_LABELS:
            errors.append(f"invalid_label:{atomic_index}:{label}")
        review_exclusion_reason = row.get("review_exclusion_reason")
        try:
            normalized_review_exclusion_reason = _normalize_review_exclusion_reason(
                review_exclusion_reason
            )
        except ValueError as exc:
            errors.append(f"invalid_review_exclusion_reason:{atomic_index}:{exc}")
            normalized_review_exclusion_reason = None
        if normalized_review_exclusion_reason is not None and label != "OTHER":
            errors.append(f"review_exclusion_reason_requires_other:{atomic_index}")
        if atomic_index not in expected_owned:
            errors.append(f"unowned_atomic_index:{atomic_index}")
            continue
        if atomic_index in seen_owned:
            errors.append(f"duplicate_atomic_index:{atomic_index}")
            continue
        seen_owned.add(atomic_index)
    missing_owned = sorted(expected_owned - seen_owned)
    if missing_owned:
        errors.append(
            "missing_owned_atomic_indices:" + ",".join(str(value) for value in missing_owned)
        )
    metadata = {
        "owned_row_count": len(expected_owned),
        "returned_row_count": len(rows),
        "validated_row_count": len(seen_owned),
    }
    return len(errors) == 0, tuple(errors), metadata

def _aggregate_line_role_task_payloads(
    *,
    shard: ShardManifestEntryV1,
    task_payloads_by_task_id: Mapping[str, dict[str, Any] | None],
    task_validation_errors_by_task_id: Mapping[str, Sequence[str]],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered_atomic_indices = [int(value) for value in shard.owned_ids]
    output_rows: list[dict[str, Any]] = []
    accepted_task_ids: list[str] = []
    fallback_task_ids: list[str] = []
    task_payload_row_by_atomic_index: dict[int, dict[str, Any]] = {}
    task_id_by_atomic_index: dict[int, str] = {}
    for task_id, payload in task_payloads_by_task_id.items():
        rows = payload.get("rows") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            continue
        accepted_task_ids.append(task_id)
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            try:
                atomic_index = int(row.get("atomic_index"))
            except (TypeError, ValueError):
                continue
            task_payload_row_by_atomic_index[atomic_index] = {
                "atomic_index": atomic_index,
                "label": str(row.get("label") or "").strip(),
            }
            task_id_by_atomic_index[atomic_index] = task_id
    missing_atomic_indices: list[int] = []
    baseline_fallback_atomic_indices: list[int] = []
    for atomic_index in ordered_atomic_indices:
        task_row = task_payload_row_by_atomic_index.get(atomic_index)
        if task_row is not None and str(task_row.get("label") or "").strip():
            output_rows.append(dict(task_row))
            continue
        baseline_prediction = deterministic_baseline_by_atomic_index.get(atomic_index)
        if baseline_prediction is None:
            missing_atomic_indices.append(atomic_index)
            continue
        output_rows.append(
            {
                "atomic_index": atomic_index,
                "label": str(baseline_prediction.label or "OTHER").strip() or "OTHER",
            }
        )
        baseline_fallback_atomic_indices.append(atomic_index)
    fallback_task_ids = sorted(
        {
            str(task_id).strip()
            for task_id, errors in task_validation_errors_by_task_id.items()
            if errors or task_id not in accepted_task_ids
        }
    )
    all_task_ids = sorted(
        {
            str(task_id).strip()
            for task_id in [*task_payloads_by_task_id.keys(), *task_validation_errors_by_task_id.keys()]
            if str(task_id).strip()
        }
    )
    metadata = {
        "task_count": len(all_task_ids),
        "accepted_task_count": len(accepted_task_ids),
        "fallback_task_count": len(fallback_task_ids),
        "accepted_task_ids": sorted(accepted_task_ids),
        "task_ids": all_task_ids,
        "fallback_task_ids": fallback_task_ids,
        "baseline_fallback_atomic_indices": baseline_fallback_atomic_indices,
        "missing_atomic_indices": missing_atomic_indices,
        "task_validation_errors_by_task_id": {
            task_id: list(errors)
            for task_id, errors in task_validation_errors_by_task_id.items()
            if errors
        },
        "task_id_by_atomic_index": {
            str(atomic_index): task_id
            for atomic_index, task_id in sorted(task_id_by_atomic_index.items())
        },
    }
    return {"rows": output_rows}, metadata


def _line_role_task_aggregation_validation_errors(
    aggregation_metadata: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if not isinstance(aggregation_metadata, Mapping):
        return ()
    task_errors_by_task_id = aggregation_metadata.get("task_validation_errors_by_task_id")
    if not isinstance(task_errors_by_task_id, Mapping):
        return ()
    errors: list[str] = []
    seen_errors: set[str] = set()
    for task_id in sorted(task_errors_by_task_id):
        task_errors = task_errors_by_task_id.get(task_id)
        if not isinstance(task_errors, list | tuple):
            continue
        for error in task_errors:
            cleaned = str(error).strip()
            if not cleaned or cleaned in seen_errors:
                continue
            seen_errors.add(cleaned)
            errors.append(cleaned)
    return tuple(errors)

def _validate_line_role_payload_semantics(
    *,
    payload: Mapping[str, Any],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> tuple[tuple[str, ...], dict[str, Any]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return (), {}
    candidate_label_by_atomic_index: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            continue
        label = str(row.get("label") or "").strip().upper()
        if label:
            candidate_label_by_atomic_index[atomic_index] = label
    total_rows = len(candidate_label_by_atomic_index)
    if total_rows < _LINE_ROLE_PATHOLOGY_MIN_ROWS:
        return (
            (),
            {
                "guard_applied": False,
                "reason": "too_few_rows",
                "candidate_row_count": total_rows,
            },
        )

    candidate_counts: dict[str, int] = {}
    baseline_counts: dict[str, int] = {}
    for atomic_index, label in candidate_label_by_atomic_index.items():
        candidate_counts[label] = candidate_counts.get(label, 0) + 1
        baseline_prediction = deterministic_baseline_by_atomic_index.get(atomic_index)
        if baseline_prediction is None:
            continue
        baseline_label = str(baseline_prediction.label or "").strip().upper()
        if baseline_label:
            baseline_counts[baseline_label] = baseline_counts.get(baseline_label, 0) + 1

    if not candidate_counts or not baseline_counts:
        return (
            (),
            {
                "guard_applied": False,
                "reason": "missing_label_counts",
                "candidate_row_count": total_rows,
            },
        )

    dominant_label, dominant_count = max(
        candidate_counts.items(),
        key=lambda item: (item[1], item[0]),
    )
    baseline_same_label_count = baseline_counts.get(dominant_label, 0)
    metadata = {
        "guard_applied": True,
        "candidate_row_count": total_rows,
        "candidate_distinct_label_count": len(candidate_counts),
        "candidate_dominant_label": dominant_label,
        "candidate_dominant_count": dominant_count,
        "baseline_distinct_label_count": len(baseline_counts),
        "baseline_matching_label_count": baseline_same_label_count,
    }

    if (
        len(candidate_counts) == 1
        and len(baseline_counts) >= _LINE_ROLE_PATHOLOGY_MIN_BASELINE_DISTINCT_LABELS
        and baseline_same_label_count <= (total_rows - 2)
    ):
        return (
            (f"pathological_uniform_label_output:{dominant_label}",),
            metadata,
        )

    if (
        dominant_count >= total_rows - 1
        and total_rows >= _LINE_ROLE_PATHOLOGY_NEAR_UNIFORM_MIN_ROWS
        and len(baseline_counts)
        >= (_LINE_ROLE_PATHOLOGY_MIN_BASELINE_DISTINCT_LABELS + 1)
        and baseline_same_label_count <= (total_rows - 3)
    ):
        return (
            (f"pathological_near_uniform_label_output:{dominant_label}",),
            metadata,
        )

    return (), metadata


def _evaluate_line_role_response_with_pathology_guard(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
    validator: Callable[
        [ShardManifestEntryV1, dict[str, Any]],
        tuple[bool, Sequence[str], dict[str, Any] | None],
    ],
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload, validation_errors, validation_metadata, proposal_status = (
        _evaluate_line_role_response(
            shard=shard,
            response_text=response_text,
            validator=validator,
        )
    )
    if proposal_status != "validated" or payload is None:
        return payload, validation_errors, validation_metadata, proposal_status
    semantic_errors, semantic_metadata = _validate_line_role_payload_semantics(
        payload=payload,
        deterministic_baseline_by_atomic_index=deterministic_baseline_by_atomic_index,
    )
    if semantic_metadata:
        validation_metadata = {
            **dict(validation_metadata or {}),
            "semantic_validation": semantic_metadata,
        }
    if semantic_errors:
        validation_metadata = {
            **dict(validation_metadata or {}),
            "semantic_diagnostics": list(semantic_errors),
        }
    return payload, validation_errors, validation_metadata, proposal_status

def _build_line_role_task_status_row(
    *,
    task_manifest: ShardManifestEntryV1,
    worker_id: str,
    state: str,
    last_attempt_type: str,
    output_path: Path | None,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    repair_attempted: bool,
    repair_status: str,
    resumed_from_existing_output: bool,
) -> dict[str, Any]:
    semantic_diagnostics = [
        str(value).strip()
        for value in (validation_metadata or {}).get("semantic_diagnostics", [])
        if str(value).strip()
    ]
    owned_row_count = len(tuple(task_manifest.owned_ids))
    llm_authoritative = state in {"validated", "repair_recovered"}
    fallback_row_count = 0 if llm_authoritative else owned_row_count
    metadata = {
        "repair_attempted": bool(repair_attempted),
        "repair_status": str(repair_status or "not_attempted"),
        "output_path": str(output_path) if output_path is not None else None,
        "owned_row_count": owned_row_count,
        "llm_authoritative_row_count": owned_row_count if llm_authoritative else 0,
        "fallback_row_count": fallback_row_count,
        "suspicious_row_count": owned_row_count if semantic_diagnostics else 0,
        "suspicious_packet": bool(semantic_diagnostics),
        "semantic_diagnostics": semantic_diagnostics,
        "resumed_from_existing_output": bool(resumed_from_existing_output),
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ],
    }
    if validation_metadata:
        metadata["validation_metadata"] = dict(validation_metadata)
    return {
        "task_id": task_manifest.shard_id,
        "parent_shard_id": str(
            (task_manifest.metadata or {}).get("parent_shard_id") or task_manifest.shard_id
        ),
        "worker_id": worker_id,
        "owned_ids": [str(value).strip() for value in task_manifest.owned_ids if str(value).strip()],
        "state": state,
        "terminal_outcome": state,
        "last_attempt_type": last_attempt_type,
        "metadata": metadata,
    }

def _summarize_direct_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return summarize_direct_telemetry_rows(rows)


def _render_codex_events_jsonl(events: Sequence[dict[str, Any]]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _coerce_mapping_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _evaluate_line_role_response(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
    validator: Callable[[ShardManifestEntryV1, dict[str, Any]], tuple[bool, Sequence[str], dict[str, Any] | None]],
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload: dict[str, Any] | None = None
    validation_errors: tuple[str, ...] = ()
    validation_metadata: dict[str, Any] = {}
    proposal_status = "validated"
    cleaned_response_text = str(response_text or "").strip()
    if not cleaned_response_text:
        return None, ("missing_output_file",), {}, "missing_output"
    try:
        parsed_payload = json.loads(cleaned_response_text)
    except json.JSONDecodeError as exc:
        return None, ("response_json_invalid",), {"parse_error": str(exc)}, "invalid"
    if not isinstance(parsed_payload, dict):
        return (
            None,
            ("response_not_json_object",),
            {"response_type": type(parsed_payload).__name__},
            "invalid",
        )
    payload = parsed_payload
    valid, validation_errors, validation_metadata = validator(
        shard,
        parsed_payload,
    )
    proposal_status = "validated" if valid else "invalid"
    return payload, tuple(validation_errors), dict(validation_metadata or {}), proposal_status


def _line_role_resume_reason_fields(*, resumed_from_existing_outputs: bool) -> tuple[str, str]:
    if resumed_from_existing_outputs:
        return "resumed_from_existing_outputs", "validated existing workspace outputs"
    return "completed", "validated worker output"


def _normalize_line_role_shard_outcome(
    *,
    run_result: CodexExecRunResult | None,
    proposal_status: str,
    watchdog_retry_status: str,
    repair_status: str,
    resumed_from_existing_outputs: bool,
    aggregation_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    raw_supervision_state = (
        str(run_result.supervision_state or "").strip() or None
        if run_result is not None
        else None
    )
    raw_supervision_reason_code = (
        str(run_result.supervision_reason_code or "").strip() or None
        if run_result is not None
        else None
    )
    raw_supervision_reason_detail = (
        str(run_result.supervision_reason_detail or "").strip() or None
        if run_result is not None
        else None
    )
    raw_supervision_retryable = (
        bool(run_result.supervision_retryable)
        if run_result is not None
        else False
    )
    fallback_task_count = int(
        (
            aggregation_metadata.get("fallback_task_count")
            if isinstance(aggregation_metadata, Mapping)
            else 0
        )
        or 0
    )

    if proposal_status == "validated":
        if (
            str(raw_supervision_state or "").lower() == "watchdog_killed"
            and fallback_task_count > 0
        ):
            return {
                "state": str(raw_supervision_state or "watchdog_killed"),
                "reason_code": raw_supervision_reason_code,
                "reason_detail": raw_supervision_reason_detail,
                "retryable": raw_supervision_retryable,
                "finalization_path": "session_result",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        if str(repair_status).strip() == "repaired":
            detail = "line-role shard validated after a repair attempt corrected the final packet output."
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return {
                "state": "completed",
                "reason_code": "repair_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "repair_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        if str(watchdog_retry_status).strip() == "recovered":
            detail = (
                "line-role shard validated after a watchdog retry recovered missing packet outputs."
            )
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return {
                "state": "completed",
                "reason_code": "watchdog_retry_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "watchdog_retry_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        if run_result is None:
            reason_code, reason_detail = _line_role_resume_reason_fields(
                resumed_from_existing_outputs=resumed_from_existing_outputs
            )
            return {
                "state": "completed",
                "reason_code": reason_code,
                "reason_detail": reason_detail,
                "retryable": False,
                "finalization_path": reason_code,
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        if str(raw_supervision_state or "").lower() == "watchdog_killed":
            detail = (
                "line-role shard validated using durable packet outputs even though the main "
                "workspace worker was killed before it terminated cleanly."
            )
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return {
                "state": "completed",
                "reason_code": "validated_after_watchdog_kill",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "validated_after_watchdog_kill",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        return {
            "state": str(raw_supervision_state or "completed"),
            "reason_code": raw_supervision_reason_code,
            "reason_detail": raw_supervision_reason_detail,
            "retryable": False,
            "finalization_path": "session_completed",
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        }

    if run_result is None:
        reason_code, reason_detail = _line_role_resume_reason_fields(
            resumed_from_existing_outputs=resumed_from_existing_outputs
        )
        return {
            "state": "completed",
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "retryable": False,
            "finalization_path": reason_code,
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        }

    return {
        "state": str(raw_supervision_state or "completed"),
        "reason_code": raw_supervision_reason_code,
        "reason_detail": raw_supervision_reason_detail,
        "retryable": raw_supervision_retryable,
        "finalization_path": "session_result",
        "raw_supervision_state": raw_supervision_state,
        "raw_supervision_reason_code": raw_supervision_reason_code,
        "raw_supervision_reason_detail": raw_supervision_reason_detail,
        "raw_supervision_retryable": raw_supervision_retryable,
    }


def _annotate_line_role_final_outcome_row(
    row: dict[str, Any],
    *,
    normalized_outcome: Mapping[str, Any],
) -> None:
    row["final_supervision_state"] = normalized_outcome.get("state")
    row["final_supervision_reason_code"] = normalized_outcome.get("reason_code")
    row["final_supervision_reason_detail"] = normalized_outcome.get("reason_detail")
    row["final_supervision_retryable"] = normalized_outcome.get("retryable")
    row["finalization_path"] = normalized_outcome.get("finalization_path")
    row["raw_supervision_state"] = normalized_outcome.get("raw_supervision_state")
    row["raw_supervision_reason_code"] = normalized_outcome.get(
        "raw_supervision_reason_code"
    )
    row["raw_supervision_reason_detail"] = normalized_outcome.get(
        "raw_supervision_reason_detail"
    )
    row["raw_supervision_retryable"] = normalized_outcome.get(
        "raw_supervision_retryable"
    )


def _annotate_line_role_final_proposal_status(
    row: dict[str, Any],
    *,
    final_proposal_status: str,
) -> None:
    raw_proposal_status = str(row.get("proposal_status") or "").strip()
    row["raw_proposal_status"] = raw_proposal_status or None
    row["final_proposal_status"] = str(final_proposal_status or "").strip() or None


def _apply_line_role_final_outcome_to_runner_payload(
    payload: dict[str, Any],
    *,
    shard_id: str,
    normalized_outcome: Mapping[str, Any],
) -> None:
    telemetry = payload.get("telemetry")
    row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
    changed = False
    if isinstance(row_payloads, list):
        for row_payload in row_payloads:
            if not isinstance(row_payload, dict):
                continue
            if str(row_payload.get("task_id") or "").strip() != str(shard_id).strip():
                continue
            if str(row_payload.get("prompt_input_mode") or "").strip() != "workspace_worker":
                continue
            _annotate_line_role_final_outcome_row(
                row_payload,
                normalized_outcome=normalized_outcome,
            )
            changed = True
        if changed:
            telemetry["summary"] = _summarize_direct_rows(row_payloads)


def _safe_int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sum_runtime_usage(rows: Sequence[dict[str, Any]]) -> dict[str, int | None]:
    totals: dict[str, int | None] = {
        "tokens_input": None,
        "tokens_cached_input": None,
        "tokens_output": None,
        "tokens_reasoning": None,
        "tokens_total": None,
        "visible_input_tokens": None,
        "visible_output_tokens": None,
        "wrapper_overhead_tokens": None,
        "request_input_file_bytes_total": None,
    }
    for row in rows:
        tokens_input = _safe_int_value(row.get("tokens_input"))
        tokens_cached_input = _safe_int_value(row.get("tokens_cached_input"))
        tokens_output = _safe_int_value(row.get("tokens_output"))
        tokens_reasoning = _safe_int_value(row.get("tokens_reasoning"))
        values = {
            "tokens_input": tokens_input,
            "tokens_cached_input": tokens_cached_input,
            "tokens_output": tokens_output,
            "tokens_reasoning": tokens_reasoning,
            "tokens_total": _safe_int_value(row.get("tokens_total"))
            or (
                tokens_input + tokens_cached_input + tokens_output + tokens_reasoning
                if all(
                    value is not None
                    for value in (
                        tokens_input,
                        tokens_cached_input,
                        tokens_output,
                        tokens_reasoning,
                    )
                )
                else None
            ),
            "visible_input_tokens": _safe_int_value(row.get("visible_input_tokens")),
            "visible_output_tokens": _safe_int_value(row.get("visible_output_tokens")),
            "wrapper_overhead_tokens": _safe_int_value(row.get("wrapper_overhead_tokens")),
            "request_input_file_bytes_total": _safe_int_value(
                row.get("request_input_file_bytes")
            ),
        }
        for key, value in values.items():
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return totals


def _line_role_usage_present(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    return any(
        _safe_int_value(payload.get(key)) is not None
        for key in (
            "tokens_input",
            "tokens_cached_input",
            "tokens_output",
            "tokens_reasoning",
            "tokens_total",
        )
    )

def _parse_codex_line_role_response(
    raw_response: str,
    *,
    requested: Sequence[AtomicLineCandidate],
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return [], f"invalid_json:{exc.msg}"
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            payload = rows
    if not isinstance(payload, list):
        return [], "payload_not_list"

    requested_indices = [int(candidate.atomic_index) for candidate in requested]
    requested_by_index = {
        int(candidate.atomic_index): candidate for candidate in requested
    }
    seen: set[int] = set()
    parsed: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            return [], "row_not_object"
        raw_index = row.get("atomic_index")
        try:
            atomic_index = int(raw_index)
        except (TypeError, ValueError):
            return [], "missing_or_invalid_atomic_index"
        if atomic_index in seen:
            return [], "duplicate_atomic_index"
        if atomic_index not in requested_indices:
            return [], "unexpected_atomic_index"
        normalized_label = normalize_freeform_label(str(row.get("label") or ""))
        if normalized_label not in FREEFORM_ALLOWED_LABELS:
            return [], f"unknown_label:{normalized_label}"
        candidate = requested_by_index[atomic_index]
        review_exclusion_reason = row.get("review_exclusion_reason")
        try:
            normalized_review_exclusion_reason = _normalize_review_exclusion_reason(
                review_exclusion_reason
            )
        except ValueError as exc:
            return [], str(exc)
        if normalized_review_exclusion_reason is not None:
            if normalized_label != "OTHER":
                return [], "review_exclusion_reason_requires_other"
            if _is_within_recipe_span(candidate):
                return [], "review_exclusion_reason_requires_outside_recipe"
        seen.add(atomic_index)
        parsed.append(
            {
                "atomic_index": atomic_index,
                "label": normalized_label,
                "review_exclusion_reason": normalized_review_exclusion_reason,
            }
        )

    if seen != set(requested_indices):
        return [], "missing_atomic_index_rows"
    ordered_parsed = sorted(parsed, key=lambda row: requested_indices.index(row["atomic_index"]))
    return ordered_parsed, None
