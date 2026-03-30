from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.staging.nonrecipe_stage import NonRecipeStageResult

from ..codex_farm_knowledge_ingest import extract_promotable_knowledge_bundles
from ..codex_exec_runner import (
    DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
    summarize_direct_telemetry_rows,
)
from ..phase_worker_runtime import (
    PhaseManifestV1,
    ShardManifestEntryV1,
    ShardProposalV1,
    WorkerAssignmentV1,
    WorkerExecutionReportV1,
)

_KNOWLEDGE_TASK_STATUS_FILE_NAME = "task_status.jsonl"
_KNOWLEDGE_STAGE_STATUS_FILE_NAME = "stage_status.json"


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_optional_text(path: Path, text: str | None) -> None:
    rendered = str(text or "")
    if not rendered.strip():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _build_review_summary(
    *,
    build_report: Any,
    validated_output_count: int,
    planned_shard_count: int,
    review_rollup: Mapping[str, Any] | None,
    promoted_useful_packet_count: int,
    promoted_snippet_count: int,
) -> dict[str, int]:
    skipped_packet_reason_counts = dict(
        getattr(build_report, "skipped_packet_reason_counts", {}) or {}
    )
    counts = dict(review_rollup or {})
    planned_packet_count = int(getattr(build_report, "packets_written", 0) or 0)
    unreviewed_packet_count = int(counts.get("unreviewed_packet_count") or 0)
    return {
        "seed_nonrecipe_span_count": int(
            getattr(build_report, "seed_nonrecipe_span_count", 0) or 0
        ),
        "candidate_nonrecipe_span_count": int(
            getattr(build_report, "candidate_nonrecipe_span_count", 0) or 0
        ),
        "packet_count_before_partition": int(
            getattr(build_report, "packet_count_before_partition", 0) or 0
        ),
        "planned_packet_count": planned_packet_count,
        "reviewed_packet_count": max(0, planned_packet_count - unreviewed_packet_count),
        "candidate_block_count": int(
            getattr(build_report, "candidate_block_count", 0) or 0
        ),
        "excluded_block_count": int(
            counts.get("excluded_block_count") or 0
        ),
        "skipped_packet_count": int(
            getattr(build_report, "skipped_packet_count", 0) or 0
        ),
        "skipped_packet_reason_counts": dict(
            sorted(skipped_packet_reason_counts.items())
        ),
        "planned_shard_count": int(planned_shard_count),
        "reviewed_shard_count": int(counts.get("meaningfully_reviewed_shard_count") or 0),
        "validated_output_packet_count": int(validated_output_count),
        "validated_shard_count": int(counts.get("validated_shard_count") or 0),
        "invalid_shard_count": int(counts.get("invalid_shard_count") or 0),
        "no_final_output_shard_count": int(counts.get("no_final_output_shard_count") or 0),
        "partially_promoted_shard_count": int(
            counts.get("partially_promoted_shard_count") or 0
        ),
        "wholly_unpromoted_invalid_shard_count": int(
            counts.get("wholly_unpromoted_invalid_shard_count") or 0
        ),
        "reviewed_shards_with_useful_packets": int(
            counts.get("reviewed_shards_with_useful_packets") or 0
        ),
        "reviewed_shards_all_other": int(counts.get("reviewed_shards_all_other") or 0),
        "unreviewed_shard_count": int(counts.get("unreviewed_shard_count") or 0),
        "unreviewed_packet_count": unreviewed_packet_count,
        "unreviewed_block_count": int(counts.get("unreviewed_block_count") or 0),
        "promoted_useful_packet_count": int(promoted_useful_packet_count),
        "promoted_snippet_count": int(promoted_snippet_count),
    }


def _build_knowledge_review_rollup(
    *,
    promotion_report: Mapping[str, Any] | None,
    build_report: Any,
) -> dict[str, int]:
    report = dict(promotion_report or {})
    validated_shard_count = int(report.get("validated_shards") or 0)
    invalid_shard_count = int(report.get("invalid_shards") or 0)
    no_final_output_shard_count = int(report.get("no_final_output_shards") or 0)
    reviewed_shards_with_useful_packets = int(
        report.get("reviewed_shards_with_useful_packets") or 0
    )
    reviewed_shards_all_other = int(report.get("reviewed_shards_all_other") or 0)
    partially_promoted_shard_count = int(report.get("partially_promoted_shards") or 0)
    wholly_unpromoted_invalid_shard_count = int(
        report.get("wholly_unpromoted_invalid_shards") or 0
    )
    unreviewed_packet_count = int(
        report.get("unreviewed_packet_count")
        or (
            int(getattr(build_report, "packets_written", 0) or 0)
            if no_final_output_shard_count > 0 and not report
            else 0
        )
    )
    unreviewed_block_count = int(report.get("unreviewed_block_count") or 0)
    return {
        "validated_shard_count": validated_shard_count,
        "invalid_shard_count": invalid_shard_count,
        "no_final_output_shard_count": no_final_output_shard_count,
        "reviewed_shards_with_useful_packets": reviewed_shards_with_useful_packets,
        "reviewed_shards_all_other": reviewed_shards_all_other,
        "partially_promoted_shard_count": partially_promoted_shard_count,
        "wholly_unpromoted_invalid_shard_count": wholly_unpromoted_invalid_shard_count,
        "meaningfully_reviewed_shard_count": (
            reviewed_shards_with_useful_packets + reviewed_shards_all_other
        ),
        "unreviewed_shard_count": (
            wholly_unpromoted_invalid_shard_count + no_final_output_shard_count
        ),
        "unreviewed_packet_count": unreviewed_packet_count,
        "unreviewed_block_count": unreviewed_block_count,
    }


def _derive_knowledge_review_status(review_rollup: Mapping[str, Any]) -> str:
    reviewed_shard_count = int(review_rollup.get("meaningfully_reviewed_shard_count") or 0)
    unreviewed_shard_count = int(review_rollup.get("unreviewed_shard_count") or 0)
    unreviewed_packet_count = int(review_rollup.get("unreviewed_packet_count") or 0)
    if reviewed_shard_count <= 0 and (
        unreviewed_shard_count > 0 or unreviewed_packet_count > 0
    ):
        return "unreviewed"
    if unreviewed_shard_count > 0 or unreviewed_packet_count > 0:
        return "partial"
    return "complete"


def _derive_knowledge_authority_mode(
    *,
    refined_stage_result: NonRecipeStageResult,
    review_rollup: Mapping[str, Any],
) -> str:
    if int(refined_stage_result.refinement_report.get("changed_block_count") or 0) > 0:
        return "knowledge_refined_final"
    review_status = _derive_knowledge_review_status(review_rollup)
    if review_status == "unreviewed":
        return "knowledge_unreviewed_candidates_kept"
    if review_status == "partial":
        return "knowledge_partially_reviewed_candidates_kept"
    return "knowledge_reviewed_candidates_kept"


def _runtime_artifact_paths(knowledge_stage_dir: Path) -> dict[str, str]:
    return {
        "stage_status_path": str(knowledge_stage_dir / _KNOWLEDGE_STAGE_STATUS_FILE_NAME),
        "phase_manifest_path": str(knowledge_stage_dir / "phase_manifest.json"),
        "shard_manifest_path": str(knowledge_stage_dir / "shard_manifest.jsonl"),
        "task_status_path": str(knowledge_stage_dir / _KNOWLEDGE_TASK_STATUS_FILE_NAME),
        "worker_assignments_path": str(knowledge_stage_dir / "worker_assignments.json"),
        "promotion_report_path": str(knowledge_stage_dir / "promotion_report.json"),
        "telemetry_path": str(knowledge_stage_dir / "telemetry.json"),
        "failures_path": str(knowledge_stage_dir / "failures.json"),
        "proposals_dir": str(knowledge_stage_dir / "proposals"),
    }


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _summarize_direct_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return summarize_direct_telemetry_rows(rows)


def _nonnegative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _ratio_or_none(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _build_knowledge_packet_economics(
    *,
    rows: Sequence[Mapping[str, Any]],
    telemetry_summary: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    packet_count_total = sum(int(row.get("workspace_packet_count") or 0) for row in normalized_rows)
    repair_packet_count_total = sum(
        int(row.get("workspace_repair_packet_count") or 0) for row in normalized_rows
    )
    owned_row_count_total = sum(int(row.get("owned_row_count") or 0) for row in normalized_rows)
    shard_count = len(normalized_rows)
    primary_packet_count_total = max(packet_count_total - repair_packet_count_total, 0)
    visible_input_tokens = _nonnegative_int(telemetry_summary.get("visible_input_tokens"))
    visible_output_tokens = _nonnegative_int(telemetry_summary.get("visible_output_tokens"))
    wrapper_overhead_tokens = _nonnegative_int(telemetry_summary.get("wrapper_overhead_tokens"))
    reasoning_tokens = _nonnegative_int(telemetry_summary.get("tokens_reasoning"))
    billed_total_tokens = _nonnegative_int(telemetry_summary.get("tokens_total"))
    semantic_payload_tokens_total = (
        None
        if visible_input_tokens is None or visible_output_tokens is None
        else visible_input_tokens + visible_output_tokens
    )
    return {
        "packet_count_total": packet_count_total,
        "primary_packet_count_total": primary_packet_count_total,
        "repair_packet_count_total": repair_packet_count_total,
        "owned_row_count_total": owned_row_count_total,
        "packet_churn_count": repair_packet_count_total,
        "packets_per_shard": _ratio_or_none(packet_count_total, shard_count),
        "repair_packet_share": _ratio_or_none(repair_packet_count_total, packet_count_total),
        "packets_per_owned_row": _ratio_or_none(packet_count_total, owned_row_count_total),
        "cost_per_owned_row": _ratio_or_none(billed_total_tokens, owned_row_count_total),
        "visible_input_tokens_per_owned_row": _ratio_or_none(
            visible_input_tokens,
            owned_row_count_total,
        ),
        "visible_output_tokens_per_owned_row": _ratio_or_none(
            visible_output_tokens,
            owned_row_count_total,
        ),
        "wrapper_overhead_tokens_per_owned_row": _ratio_or_none(
            wrapper_overhead_tokens,
            owned_row_count_total,
        ),
        "reasoning_tokens_per_owned_row": _ratio_or_none(
            reasoning_tokens,
            owned_row_count_total,
        ),
        "semantic_payload_tokens_total": semantic_payload_tokens_total,
        "semantic_payload_tokens_per_owned_row": _ratio_or_none(
            semantic_payload_tokens_total,
            owned_row_count_total,
        ),
        "protocol_overhead_tokens_total": wrapper_overhead_tokens,
        "protocol_overhead_share": _ratio_or_none(
            wrapper_overhead_tokens,
            billed_total_tokens,
        ),
    }


def _aggregate_worker_runner_payload(
    *,
    pipeline_id: str,
    worker_runs: list[Mapping[str, Any]],
    stage_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for worker_run in worker_runs:
        telemetry = worker_run.get("telemetry")
        if not isinstance(telemetry, Mapping):
            continue
        worker_rows = telemetry.get("rows")
        if isinstance(worker_rows, list):
            rows.extend([dict(row) for row in worker_rows if isinstance(row, Mapping)])
    if stage_rows is not None:
        rows = [dict(row) for row in stage_rows if isinstance(row, Mapping)]
    uses_workspace_worker = any(
        str(
            ((payload.get("process_payload") or {}) if isinstance(payload, Mapping) else {}).get(
                "prompt_input_mode"
            )
            or ""
        ).strip()
        == "workspace_worker"
        for payload in worker_runs
        if isinstance(payload, Mapping)
    )
    return {
        "runner_kind": "codex_exec_direct",
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "pipeline_id": pipeline_id,
        "worker_runs": [dict(payload) for payload in worker_runs],
        "telemetry": {
            "rows": rows,
            "summary": _summarize_direct_rows(rows),
        },
        "runtime_mode_audit": {
            "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
            "status": "ok",
            "output_schema_enforced": not uses_workspace_worker,
            "tool_affordances_requested": uses_workspace_worker,
        },
    }


def _summarize_knowledge_workspace_relaunches(
    worker_reports: Sequence[WorkerExecutionReportV1],
) -> dict[str, Any]:
    reason_code_counts: dict[str, int] = {}
    workspace_relaunch_count_total = 0
    workspace_premature_clean_exit_count = 0
    workspace_premature_clean_exit_session_count = 0
    workspace_relaunch_cap_reached_session_count = 0
    for report in worker_reports:
        metadata = dict(report.metadata or {})
        history = [
            dict(row)
            for row in (metadata.get("workspace_relaunch_history") or [])
            if isinstance(row, Mapping)
        ]
        reason_codes = [
            str(row.get("reason_code") or "").strip()
            for row in history
            if str(row.get("reason_code") or "").strip()
        ]
        if not reason_codes:
            reason_codes = [
                str(code or "").strip()
                for code in (metadata.get("workspace_relaunch_reason_codes") or [])
                if str(code or "").strip()
            ]
        workspace_relaunch_count = (
            int(metadata.get("workspace_relaunch_count") or 0)
            if metadata.get("workspace_relaunch_count") is not None
            else len(reason_codes)
        )
        workspace_relaunch_count_total += max(workspace_relaunch_count, len(reason_codes))
        premature_clean_exit_count = sum(
            1
            for code in reason_codes
            if code == "workspace_validated_task_queue_premature_clean_exit"
        )
        workspace_premature_clean_exit_count += premature_clean_exit_count
        if premature_clean_exit_count > 0:
            workspace_premature_clean_exit_session_count += 1
        if bool(metadata.get("workspace_relaunch_cap_reached")):
            workspace_relaunch_cap_reached_session_count += 1
        for code in reason_codes:
            reason_code_counts[code] = reason_code_counts.get(code, 0) + 1
    return {
        "workspace_relaunch_count_total": workspace_relaunch_count_total,
        "workspace_relaunch_reason_code_counts": dict(sorted(reason_code_counts.items())),
        "workspace_premature_clean_exit_count": workspace_premature_clean_exit_count,
        "workspace_premature_clean_exit_session_count": (
            workspace_premature_clean_exit_session_count
        ),
        "workspace_relaunch_cap_reached_session_count": (
            workspace_relaunch_cap_reached_session_count
        ),
    }


def _write_knowledge_runtime_summary_artifacts(
    *,
    phase_key: str,
    pipeline_id: str,
    run_root: Path,
    artifacts: Mapping[str, str],
    assignments: Sequence[WorkerAssignmentV1],
    shards: Sequence[ShardManifestEntryV1],
    settings: Mapping[str, Any],
    runtime_metadata: Mapping[str, Any],
    worker_reports: Sequence[WorkerExecutionReportV1],
    all_proposals: Sequence[ShardProposalV1],
    failures: Sequence[Mapping[str, Any]],
    stage_rows: Sequence[Mapping[str, Any]],
) -> PhaseManifestV1:
    def _proposal_has_validation_error_prefix(
        proposal: ShardProposalV1,
        *,
        prefix: str,
    ) -> bool:
        target_prefix = str(prefix).strip()
        if not target_prefix:
            return False
        direct_errors = {
            str(error).strip()
            for error in (proposal.validation_errors or ())
            if str(error).strip()
        }
        if any(error.startswith(target_prefix) for error in direct_errors):
            return True
        task_aggregation = _coerce_dict((proposal.metadata or {}).get("task_aggregation"))
        task_errors_by_task_id = task_aggregation.get("task_validation_errors_by_task_id")
        if not isinstance(task_errors_by_task_id, Mapping):
            return False
        for task_errors in task_errors_by_task_id.values():
            if any(
                str(error).strip().startswith(target_prefix) for error in (task_errors or ())
            ):
                return True
        return False

    def _promotable_bundle_for_proposal(
        proposal: ShardProposalV1,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        return extract_promotable_knowledge_bundles(
            payload=proposal.payload,
            validation_errors=proposal.validation_errors,
            validation_metadata=proposal.metadata,
        )

    def _promoted_rows_are_all_other(bundles: Mapping[str, Any] | None) -> bool:
        if not isinstance(bundles, Mapping) or not bundles:
            return False
        return all(
            bool(getattr(bundle, "block_decisions", ()) or ())
            and not bool(getattr(bundle, "idea_groups", ()) or ())
            and all(
                decision.category == "other"
                for decision in (getattr(bundle, "block_decisions", ()) or ())
            )
            for bundle in bundles.values()
        )

    def _unreviewed_packet_count_for_proposal(
        proposal: ShardProposalV1,
        promotion_info: Mapping[str, Any] | None,
    ) -> int:
        metadata = _coerce_dict(proposal.metadata)
        owned_packet_count = int(metadata.get("owned_packet_count") or 1)
        if proposal.status == "validated":
            return 0
        if proposal.status == "no_final_output":
            return owned_packet_count
        if not promotion_info or not bool(promotion_info.get("partial")):
            return owned_packet_count
        missing_packet_ids = [
            str(packet_id).strip()
            for packet_id in (
                promotion_info.get("missing_packet_ids")
                or metadata.get("missing_packet_ids")
                or []
            )
            if str(packet_id).strip()
        ]
        if missing_packet_ids:
            return len(set(missing_packet_ids))
        return max(0, owned_packet_count - int(promotion_info.get("promoted_packet_count") or 0))

    def _unreviewed_block_count_for_proposal(
        proposal: ShardProposalV1,
        promotion_info: Mapping[str, Any] | None,
    ) -> int:
        metadata = _coerce_dict(proposal.metadata)
        owned_block_count = int(metadata.get("owned_block_count") or 0)
        if proposal.status == "validated":
            return 0
        if proposal.status == "no_final_output":
            return owned_block_count
        if not promotion_info or not bool(promotion_info.get("partial")):
            return owned_block_count
        missing_block_indices = [
            int(value)
            for value in (
                promotion_info.get("missing_owned_block_indices")
                or metadata.get("missing_owned_block_indices")
                or []
            )
            if value is not None
        ]
        if missing_block_indices:
            return len(set(missing_block_indices))
        return owned_block_count

    proposal_promotion_rows: list[dict[str, Any]] = []
    for proposal in all_proposals:
        promoted_bundle = _promotable_bundle_for_proposal(proposal)
        promotion_info = dict(promoted_bundle[1]) if promoted_bundle else {}
        proposal_promotion_rows.append(
            {
                "proposal": proposal,
                "promoted_bundle": promoted_bundle[0] if promoted_bundle else {},
                "promotion_info": promotion_info,
                "partially_promoted": bool(promotion_info.get("partial")),
                "reviewed_with_useful_packets": bool(
                    promoted_bundle is not None
                    and any(bundle.idea_groups for bundle in promoted_bundle[0].values())
                ),
                "reviewed_all_other": _promoted_rows_are_all_other(
                    promoted_bundle[0] if promoted_bundle else None
                )
                if promoted_bundle is not None
                else False,
            }
        )
    no_final_output_reason_code_counts: dict[str, int] = {}
    for proposal in all_proposals:
        if proposal.status != "no_final_output":
            continue
        reason_code = str((proposal.metadata or {}).get("terminal_reason_code") or "").strip()
        if not reason_code:
            reason_code = "no_final_output"
        no_final_output_reason_code_counts[reason_code] = (
            int(no_final_output_reason_code_counts.get(reason_code) or 0) + 1
        )

    promotion_report = {
        "schema_version": "phase_worker_runtime.promotion_report.v2",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "validated_shards": sum(1 for proposal in all_proposals if proposal.status == "validated"),
        "invalid_shards": sum(1 for proposal in all_proposals if proposal.status == "invalid"),
        "no_final_output_shards": sum(
            1 for proposal in all_proposals if proposal.status == "no_final_output"
        ),
        "no_final_output_reason_code_counts": dict(
            sorted(no_final_output_reason_code_counts.items())
        ),
        "partially_promoted_shards": sum(
            1 for row in proposal_promotion_rows if row["partially_promoted"]
        ),
        "wholly_unpromoted_invalid_shards": sum(
            1
            for proposal in all_proposals
            if proposal.status == "invalid"
            and not any(row["proposal"] is proposal and row["partially_promoted"] for row in proposal_promotion_rows)
        ),
        "promoted_packet_count": sum(
            int(row["promotion_info"].get("promoted_packet_count") or 0)
            for row in proposal_promotion_rows
        ),
        "reviewed_shards_with_useful_packets": sum(
            1
            for row in proposal_promotion_rows
            if row["reviewed_with_useful_packets"]
        ),
        "reviewed_shards_all_other": sum(
            1
            for row in proposal_promotion_rows
            if row["reviewed_all_other"]
        ),
        "unreviewed_packet_count": sum(
            _unreviewed_packet_count_for_proposal(row["proposal"], row["promotion_info"])
            for row in proposal_promotion_rows
        ),
        "unreviewed_block_count": sum(
            _unreviewed_block_count_for_proposal(row["proposal"], row["promotion_info"])
            for row in proposal_promotion_rows
        ),
    }
    telemetry_summary = _summarize_direct_rows(list(stage_rows))
    telemetry_summary["packet_economics"] = _build_knowledge_packet_economics(
        rows=stage_rows,
        telemetry_summary=telemetry_summary,
    )
    telemetry_summary.update(_summarize_knowledge_workspace_relaunches(worker_reports))
    telemetry = {
        "schema_version": "phase_worker_runtime.telemetry.v1",
        "phase_key": phase_key,
        "pipeline_id": pipeline_id,
        "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        "worker_count": len(assignments),
        "shard_count": len(shards),
        "proposal_count": sum(report.proposal_count for report in worker_reports),
        "failure_count": len(failures),
        "fresh_agent_count": len(assignments),
        "rows": [dict(row) for row in stage_rows],
        "summary": telemetry_summary,
    }
    _write_json(promotion_report, run_root / artifacts["promotion_report"])
    _write_json(telemetry, run_root / artifacts["telemetry"])
    _write_json([dict(row) for row in failures], run_root / artifacts["failures"])

    manifest = PhaseManifestV1(
        schema_version="phase_worker_runtime.phase_manifest.v1",
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=str(run_root),
        worker_count=len(assignments),
        shard_count=len(shards),
        assignment_strategy="round_robin_v1",
        runtime_mode=DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
        max_turns_per_shard=1,
        settings=dict(settings or {}),
        artifact_paths=dict(artifacts),
        runtime_metadata=dict(runtime_metadata or {}),
    )
    _write_json(asdict(manifest), run_root / artifacts["phase_manifest"])
    return manifest


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True))
            handle.write("\n")
