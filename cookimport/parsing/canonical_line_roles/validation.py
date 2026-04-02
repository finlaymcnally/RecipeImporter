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
            elif row_error == "exclusion_reason_requires_nonrecipe_exclude":
                mapped_errors.append(
                    f"exclusion_reason_requires_nonrecipe_exclude:{atomic_index}"
                )
            elif row_error == "invalid_exclusion_reason":
                exclusion_reason = str(
                    row_payload.get("exclusion_reason") or ""
                ).strip()
                mapped_errors.append(
                    f"invalid_exclusion_reason:{atomic_index}:{exclusion_reason or '<blank>'}"
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
    del payload, deterministic_baseline_by_atomic_index
    return (), {
        "guard_applied": False,
        "reason": "runtime_baseline_semantic_guard_disabled",
    }


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
    del deterministic_baseline_by_atomic_index
    return _evaluate_line_role_response(
        shard=shard,
        response_text=response_text,
        validator=validator,
    )


def _evaluate_line_role_workspace_response_with_pathology_guard(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
    deterministic_baseline_by_atomic_index: Mapping[int, CanonicalLineRolePrediction],
    frozen_rows_by_atomic_index: Mapping[int, Mapping[str, Any]]
    | Sequence[Mapping[str, Any]]
    | None = None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    del deterministic_baseline_by_atomic_index
    return _evaluate_line_role_response(
        shard=shard,
        response_text=response_text,
        validator=lambda proposal_shard, proposal_payload: _validate_line_role_shard_proposal(
            proposal_shard,
            proposal_payload,
            frozen_rows_by_atomic_index=frozen_rows_by_atomic_index,
        ),
    )

def _build_line_role_row_resolution(
    *,
    shard: ShardManifestEntryV1,
    validation_metadata: Mapping[str, Any] | None,
 ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
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
    for atomic_index in ordered_atomic_indices:
        accepted_row = accepted_by_atomic_index.get(atomic_index)
        if accepted_row is not None:
            final_rows.append(dict(accepted_row))
            accepted_atomic_indices.append(atomic_index)
    unresolved_atomic_indices = [
        atomic_index
        for atomic_index in ordered_atomic_indices
        if atomic_index not in set(accepted_atomic_indices)
    ]
    all_rows_resolved = not unresolved_atomic_indices and not bool(
        (validation_metadata or {}).get("semantic_rejected")
    )
    resolution_metadata = {
        "accepted_atomic_indices": accepted_atomic_indices,
        "unresolved_atomic_indices": unresolved_atomic_indices,
        "accepted_row_count": len(accepted_atomic_indices),
        "unresolved_row_count": len(unresolved_atomic_indices),
        "semantic_rejected": bool((validation_metadata or {}).get("semantic_rejected")),
        "all_rows_resolved": all_rows_resolved,
    }
    return (
        {"rows": final_rows} if all_rows_resolved else None,
        resolution_metadata,
    )

def _build_line_role_shard_status_row(
    *,
    shard: ShardManifestEntryV1,
    worker_id: str,
    state: str,
    last_attempt_type: str,
    output_path: Path | None,
    repair_path: Path | None,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any] | None,
    row_resolution_metadata: Mapping[str, Any] | None,
    repair_attempted: bool,
    repair_status: str,
    resumed_from_existing_output: bool,
    fresh_session_recovery_metadata: Mapping[str, Any] | None = None,
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
    unresolved_row_count = int(
        (row_resolution_metadata or {}).get("unresolved_row_count") or 0
    )
    metadata = {
        "repair_attempted": bool(repair_attempted),
        "repair_status": str(repair_status or "not_attempted"),
        "output_path": str(output_path) if output_path is not None else None,
        "repair_path": str(repair_path) if repair_path is not None else None,
        "owned_row_count": owned_row_count,
        "llm_authoritative_row_count": llm_authoritative_row_count,
        "unresolved_row_count": unresolved_row_count,
        "suspicious_row_count": (
            owned_row_count if semantic_diagnostics else unresolved_row_count
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
    if fresh_session_recovery_metadata:
        metadata["fresh_session_recovery"] = dict(fresh_session_recovery_metadata)
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
    fresh_session_recovery_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    def _with_fresh_session_recovery(result: dict[str, Any]) -> dict[str, Any]:
        if not fresh_session_recovery_metadata:
            return result
        return {
            **result,
            **{
                key: value
                for key, value in dict(fresh_session_recovery_metadata).items()
                if key
                in {
                    "fresh_session_recovery_attempted",
                    "fresh_session_recovery_status",
                    "fresh_session_recovery_count",
                    "fresh_session_recovery_skipped_reason",
                    "shared_retry_budget_spent",
                    "prior_session_reason_code",
                    "diagnosis_code",
                    "recommended_command",
                    "resume_summary",
                    "assessment_path",
                }
            },
        }

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
    recovery_status = str(
        (fresh_session_recovery_metadata or {}).get("fresh_session_recovery_status") or ""
    ).strip()
    prior_session_reason_code = str(
        (fresh_session_recovery_metadata or {}).get("prior_session_reason_code") or ""
    ).strip()
    unresolved_row_count = int(
        ((row_resolution_metadata or {}).get("unresolved_row_count") or 0)
    )
    unresolved_atomic_indices = [
        int(value)
        for value in ((row_resolution_metadata or {}).get("unresolved_atomic_indices") or [])
        if str(value).strip()
    ]
    unresolved_suffix = ""
    if unresolved_atomic_indices:
        unresolved_suffix = " Unresolved atomic indices: " + ", ".join(
            str(value) for value in unresolved_atomic_indices
        ) + "."

    if proposal_status == "validated":
        if str(repair_status).strip() == "repaired":
            detail = "line-role shard validated after a repair attempt corrected the final shard ledger."
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": "repair_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "repair_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        if str(watchdog_retry_status).strip() == "recovered":
            detail = (
                "line-role shard validated after a watchdog retry recovered a missing shard ledger."
            )
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": "watchdog_retry_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "watchdog_retry_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        if recovery_status == "recovered":
            detail = (
                "line-role shard validated after one fresh-session recovery resumed the preserved workspace."
            )
            if prior_session_reason_code:
                detail += f" Prior workspace reason: {prior_session_reason_code}."
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": "fresh_session_recovery_recovered",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "fresh_session_recovery_recovered",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        if run_result is None:
            reason_code, reason_detail = _line_role_resume_reason_fields(
                resumed_from_existing_outputs=resumed_from_existing_outputs
            )
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": reason_code,
                "reason_detail": reason_detail,
                "retryable": False,
                "finalization_path": reason_code,
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        if str(raw_supervision_state or "").lower() == "watchdog_killed":
            detail = (
                "line-role shard validated using a durable shard ledger even though the main "
                "taskfile worker was killed before it terminated cleanly."
            )
            if raw_supervision_reason_code:
                detail += f" Original workspace reason: {raw_supervision_reason_code}."
            return _with_fresh_session_recovery({
                "state": "completed",
                "reason_code": "validated_after_watchdog_kill",
                "reason_detail": detail,
                "retryable": False,
                "finalization_path": "validated_after_watchdog_kill",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        return _with_fresh_session_recovery({
            "state": str(raw_supervision_state or "completed"),
            "reason_code": raw_supervision_reason_code,
            "reason_detail": raw_supervision_reason_detail,
            "retryable": False,
            "finalization_path": "session_completed",
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        })

    if run_result is None:
        if unresolved_row_count > 0:
            return _with_fresh_session_recovery({
                "state": "repair_failed" if str(repair_status).strip() == "failed" else "invalid_output",
                "reason_code": (
                    "same_session_repair_failed"
                    if str(repair_status).strip() == "failed"
                    else "line_role_install_required"
                ),
                "reason_detail": (
                    "line-role shard stopped without a clean installed ledger."
                    " The active worker repair loop must install a fully valid `out/<shard_id>.json` ledger"
                    " before the shard can succeed."
                    f"{unresolved_suffix}"
                ),
                "retryable": False,
                "finalization_path": "fail_closed_missing_install",
                "raw_supervision_state": raw_supervision_state,
                "raw_supervision_reason_code": raw_supervision_reason_code,
                "raw_supervision_reason_detail": raw_supervision_reason_detail,
                "raw_supervision_retryable": raw_supervision_retryable,
            })
        reason_code, reason_detail = _line_role_resume_reason_fields(
            resumed_from_existing_outputs=resumed_from_existing_outputs
        )
        return _with_fresh_session_recovery({
            "state": "completed",
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "retryable": False,
            "finalization_path": reason_code,
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        })

    if unresolved_row_count > 0:
        detail = (
            "line-role shard stopped without a clean installed ledger."
            " The active worker repair loop must install a fully valid `out/<shard_id>.json` ledger"
            " before the shard can succeed."
            f"{unresolved_suffix}"
        )
        if raw_supervision_reason_detail:
            detail += f" Workspace detail: {raw_supervision_reason_detail}"
        return _with_fresh_session_recovery({
            "state": (
                "repair_failed"
                if str(repair_status).strip() == "failed"
                else (
                    str(raw_supervision_state)
                    if str(raw_supervision_state or "").strip()
                    and str(raw_supervision_state or "").strip() != "completed"
                    else "invalid_output"
                )
            ),
            "reason_code": (
                "same_session_repair_failed"
                if str(repair_status).strip() == "failed"
                else str(raw_supervision_reason_code or "line_role_install_required")
            ),
            "reason_detail": detail,
            "retryable": raw_supervision_retryable,
            "finalization_path": "fail_closed_missing_install",
            "raw_supervision_state": raw_supervision_state,
            "raw_supervision_reason_code": raw_supervision_reason_code,
            "raw_supervision_reason_detail": raw_supervision_reason_detail,
            "raw_supervision_retryable": raw_supervision_retryable,
        })

    return _with_fresh_session_recovery({
        "state": str(raw_supervision_state or "completed"),
        "reason_code": raw_supervision_reason_code,
        "reason_detail": raw_supervision_reason_detail,
        "retryable": raw_supervision_retryable,
        "finalization_path": "session_result",
        "raw_supervision_state": raw_supervision_state,
        "raw_supervision_reason_code": raw_supervision_reason_code,
        "raw_supervision_reason_detail": raw_supervision_reason_detail,
        "raw_supervision_retryable": raw_supervision_retryable,
    })


def _annotate_line_role_final_outcome_row(
    row: dict[str, Any],
    *,
    normalized_outcome: Mapping[str, Any],
    repair_attempted: bool | None = None,
    repair_status: str | None = None,
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
    for key in (
        "fresh_session_recovery_attempted",
        "fresh_session_recovery_status",
        "fresh_session_recovery_count",
        "fresh_session_recovery_skipped_reason",
        "shared_retry_budget_spent",
        "prior_session_reason_code",
        "diagnosis_code",
        "recommended_command",
        "resume_summary",
        "assessment_path",
    ):
        if key in normalized_outcome:
            row[key] = normalized_outcome.get(key)
    if repair_attempted is not None:
        row["repair_attempted"] = bool(repair_attempted)
    if repair_status is not None:
        row["repair_status"] = str(repair_status or "not_attempted")


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
    repair_attempted: bool | None = None,
    repair_status: str | None = None,
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
            if str(row_payload.get("prompt_input_mode") or "").strip() != "taskfile":
                continue
            _annotate_line_role_final_outcome_row(
                row_payload,
                normalized_outcome=normalized_outcome,
                repair_attempted=repair_attempted,
                repair_status=repair_status,
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
        if normalized_label not in CANONICAL_LINE_ROLE_ALLOWED_LABELS:
            return [], f"unknown_label:{normalized_label}"
        candidate = requested_by_index[atomic_index]
        exclusion_reason = row.get("exclusion_reason")
        try:
            normalized_exclusion_reason = _normalize_exclusion_reason(exclusion_reason)
        except ValueError as exc:
            return [], str(exc)
        if normalized_exclusion_reason is not None:
            if normalized_label != "NONRECIPE_EXCLUDE":
                return [], "exclusion_reason_requires_nonrecipe_exclude"
            if _is_within_recipe_span(candidate):
                return [], "exclusion_reason_requires_outside_recipe"
        seen.add(atomic_index)
        parsed.append(
            {
                "atomic_index": atomic_index,
                "label": normalized_label,
                "exclusion_reason": normalized_exclusion_reason,
            }
        )

    if seen != set(requested_indices):
        return [], "missing_atomic_index_rows"
    ordered_parsed = sorted(parsed, key=lambda row: requested_indices.index(row["atomic_index"]))
    return ordered_parsed, None
