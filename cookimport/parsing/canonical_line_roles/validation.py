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
    *,
    frozen_rows_by_atomic_index: Mapping[int, Mapping[str, Any]]
    | Sequence[Mapping[str, Any]]
    | None = None,
) -> tuple[bool, Sequence[str], dict[str, Any] | None]:
    errors, metadata = validate_line_role_output_payload(
        {"input_payload": shard.input_payload},
        payload,
        frozen_rows_by_atomic_index=frozen_rows_by_atomic_index,
    )
    mapped_errors: list[str] = []
    row_errors_by_atomic_index = {
        int(key): list(value)
        for key, value in (metadata or {}).get("row_errors_by_atomic_index", {}).items()
        if str(key).strip()
    }
    for error in errors:
        cleaned = str(error).strip()
        if not cleaned:
            continue
        if cleaned == "payload_not_object":
            mapped_errors.append("proposal_not_a_json_object")
        elif cleaned == "rows_not_list":
            mapped_errors.append("rows_missing_or_not_a_list")
        elif cleaned == "invalid_atomic_index":
            mapped_errors.append("atomic_index_missing")
        elif cleaned == "row_not_object":
            mapped_errors.append("row_not_a_json_object")
        else:
            mapped_errors.append(cleaned)
    rows_payload = payload.get("rows") if isinstance(payload, Mapping) else []
    for atomic_index, row_errors in sorted(row_errors_by_atomic_index.items()):
        row_payload = next(
            (
                row
                for row in rows_payload
                if isinstance(row, Mapping)
                and row.get("atomic_index") is not None
                and str(row.get("atomic_index")).strip()
                and int(row.get("atomic_index")) == atomic_index
            ),
            {},
        )
        for row_error in row_errors:
            if row_error == "invalid_label":
                mapped_errors.append(
                    f"invalid_label:{atomic_index}:{str(row_payload.get('label') or '').strip()}"
                )
            elif row_error == "review_exclusion_reason_requires_other":
                mapped_errors.append(
                    f"review_exclusion_reason_requires_other:{atomic_index}"
                )
            elif row_error == "invalid_review_exclusion_reason":
                review_exclusion_reason = str(
                    row_payload.get("review_exclusion_reason") or ""
                ).strip()
                mapped_errors.append(
                    f"invalid_review_exclusion_reason:{atomic_index}:{review_exclusion_reason or '<blank>'}"
                )
            elif row_error == "unowned_atomic_index":
                mapped_errors.append(f"unowned_atomic_index:{atomic_index}")
            elif row_error == "duplicate_atomic_index":
                mapped_errors.append(f"duplicate_atomic_index:{atomic_index}")
    missing_owned = [
        int(value)
        for value in (metadata or {}).get("expected_atomic_indices", [])
        if str(value).strip()
        and int(value)
        not in {
            int(index)
            for index in (metadata or {}).get("accepted_atomic_indices", [])
            if str(index).strip()
        }
        and int(value)
        not in {
            int(index)
            for index in (metadata or {}).get("invalid_row_atomic_indices", [])
            if str(index).strip()
        }
    ]
    if missing_owned:
        mapped_errors.append(
            "missing_owned_atomic_indices:" + ",".join(str(value) for value in missing_owned)
        )
    deduped_errors = tuple(dict.fromkeys(mapped_errors))
    runtime_metadata = dict(metadata or {})
    runtime_metadata["validated_row_count"] = len(
        runtime_metadata.get("accepted_atomic_indices") or []
    )
    return len(deduped_errors) == 0, deduped_errors, runtime_metadata

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
            "semantic_rejected": True,
        }
        validation_errors = tuple([*validation_errors, *semantic_errors])
        proposal_status = "invalid"
    return payload, validation_errors, validation_metadata, proposal_status


def _evaluate_line_role_workspace_response_with_pathology_guard(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
    frozen_rows_by_atomic_index: Mapping[int, Mapping[str, Any]]
    | Sequence[Mapping[str, Any]]
    | None = None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    payload, validation_errors, validation_metadata, proposal_status = (
        _evaluate_line_role_response(
            shard=shard,
            response_text=response_text,
            validator=lambda proposal_shard, proposal_payload: _validate_line_role_shard_proposal(
                proposal_shard,
                proposal_payload,
                frozen_rows_by_atomic_index=frozen_rows_by_atomic_index,
            ),
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
            "semantic_rejected": True,
        }
        validation_errors = tuple([*validation_errors, *semantic_errors])
        proposal_status = "invalid"
    return payload, validation_errors, validation_metadata, proposal_status

def _build_line_role_row_resolution(
    *,
    shard: ShardManifestEntryV1,
    validation_metadata: Mapping[str, Any] | None,
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered_atomic_indices = [int(value) for value in shard.owned_ids]
    accepted_rows = []
    if not bool((validation_metadata or {}).get("semantic_rejected")):
        accepted_rows = [
            dict(row)
            for row in (validation_metadata or {}).get("accepted_rows", [])
            if isinstance(row, Mapping)
        ]
    accepted_by_atomic_index = {
        int(row["atomic_index"]): dict(row)
        for row in accepted_rows
        if row.get("atomic_index") is not None and str(row.get("atomic_index")).strip()
    }
    final_rows: list[dict[str, Any]] = []
    accepted_atomic_indices: list[int] = []
    fallback_atomic_indices: list[int] = []
    for atomic_index in ordered_atomic_indices:
        accepted_row = accepted_by_atomic_index.get(atomic_index)
        if accepted_row is not None:
            final_rows.append(dict(accepted_row))
            accepted_atomic_indices.append(atomic_index)
            continue
        baseline_prediction = deterministic_baseline_by_atomic_index.get(atomic_index)
        fallback_row = {
            "atomic_index": atomic_index,
            "label": str(
                (baseline_prediction.label if baseline_prediction is not None else "OTHER")
                or "OTHER"
            ).strip()
            or "OTHER",
        }
        normalized_review_exclusion_reason = _normalize_review_exclusion_reason(
            baseline_prediction.review_exclusion_reason
            if baseline_prediction is not None
            else None
        )
        if normalized_review_exclusion_reason is not None:
            fallback_row["review_exclusion_reason"] = normalized_review_exclusion_reason
        final_rows.append(fallback_row)
        fallback_atomic_indices.append(atomic_index)
    resolution_metadata = {
        "accepted_atomic_indices": accepted_atomic_indices,
        "fallback_atomic_indices": fallback_atomic_indices,
        "accepted_row_count": len(accepted_atomic_indices),
        "fallback_row_count": len(fallback_atomic_indices),
        "semantic_rejected": bool((validation_metadata or {}).get("semantic_rejected")),
    }
    return {"rows": final_rows}, resolution_metadata

def _build_line_role_shard_status_row(
    *,
    shard: ShardManifestEntryV1,
    worker_id: str,
    state: str,
    last_attempt_type: str,
    output_path: Path | None,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    row_resolution_metadata: Mapping[str, Any] | None,
    repair_attempted: bool,
    repair_status: str,
    resumed_from_existing_output: bool,
) -> dict[str, Any]:
    semantic_diagnostics = [
        str(value).strip()
        for value in (validation_metadata or {}).get("semantic_diagnostics", [])
        if str(value).strip()
    ]
    owned_row_count = len(tuple(shard.owned_ids))
    llm_authoritative_row_count = int(
        (row_resolution_metadata or {}).get("accepted_row_count") or 0
    )
    fallback_row_count = int(
        (row_resolution_metadata or {}).get("fallback_row_count") or 0
    )
    metadata = {
        "repair_attempted": bool(repair_attempted),
        "repair_status": str(repair_status or "not_attempted"),
        "output_path": str(output_path) if output_path is not None else None,
        "owned_row_count": owned_row_count,
        "llm_authoritative_row_count": llm_authoritative_row_count,
        "fallback_row_count": fallback_row_count,
        "suspicious_row_count": (
            owned_row_count if semantic_diagnostics else fallback_row_count
        ),
        "suspicious_shard": bool(semantic_diagnostics),
        "semantic_diagnostics": semantic_diagnostics,
        "resumed_from_existing_output": bool(resumed_from_existing_output),
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ],
    }
    if validation_metadata:
        metadata["validation_metadata"] = dict(validation_metadata)
    if row_resolution_metadata:
        metadata["row_resolution"] = dict(row_resolution_metadata)
    return {
        "shard_id": shard.shard_id,
        "worker_id": worker_id,
        "owned_ids": [str(value).strip() for value in shard.owned_ids if str(value).strip()],
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
    row_resolution_metadata: Mapping[str, Any] | None = None,
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
    fallback_row_count = int(
        ((row_resolution_metadata or {}).get("fallback_row_count") or 0)
    )

    if proposal_status == "validated":
        if (
            str(raw_supervision_state or "").lower() == "watchdog_killed"
            and fallback_row_count > 0
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
        if fallback_row_count > 0:
            return {
                "state": "completed_with_fallback",
                "reason_code": (
                    "repair_partial_fallback"
                    if str(repair_status).strip() not in {"", "not_attempted"}
                    else "row_fallback"
                ),
                "reason_detail": (
                    "The final shard ledger preserved validated rows and kept unresolved rows on the deterministic baseline."
                ),
                "retryable": False,
                "finalization_path": "row_fallback",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
        if str(repair_status).strip() == "repaired":
            detail = "line-role shard validated after a repair attempt corrected the final shard ledger."
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
                "line-role shard validated after a watchdog retry recovered a missing shard ledger."
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
                "line-role shard validated using a durable shard ledger even though the main "
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
        if fallback_row_count > 0:
            return {
                "state": "completed_with_fallback",
                "reason_code": "resumed_with_row_fallback",
                "reason_detail": "validated existing workspace outputs with deterministic fallback for unresolved rows",
                "retryable": False,
                "finalization_path": "resumed_with_row_fallback",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            }
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
