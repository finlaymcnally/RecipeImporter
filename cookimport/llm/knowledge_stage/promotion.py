from __future__ import annotations

from . import _shared as _shared_module

globals().update(
    {
        name: value
        for name, value in vars(_shared_module).items()
        if not name.startswith("__")
    }
)

def _build_noop_knowledge_llm_report(
    *,
    run_settings: RunSettings,
    pipeline_id: str,
    output_schema_path: str | None,
    manifest_path: Path,
    run_root: Path,
    knowledge_in_dir: Path,
    knowledge_stage_dir: Path,
    stage_status: str,
    seed_nonrecipe_span_count: int = 0,
    candidate_nonrecipe_span_count: int = 0,
    packet_count_before_partition: int = 0,
    candidate_block_count: int = 0,
    excluded_block_count: int = 0,
    skipped_packet_count: int = 0,
    skipped_packet_reason_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    authority_mode = (
        "knowledge_not_run_no_nonrecipe_spans"
        if stage_status == "no_nonrecipe_spans"
        else "knowledge_not_run_no_candidate_nonrecipe_spans"
        if stage_status == "no_candidate_nonrecipe_spans"
        else "knowledge_not_run_all_packets_skipped"
    )
    return {
        "enabled": True,
        "pipeline": run_settings.llm_knowledge_pipeline.value,
        "pipeline_id": pipeline_id,
        "input_mode": "nonrecipe_candidate_spans",
        "authority_mode": authority_mode,
        "scored_effect": "route_only",
        "output_schema_path": output_schema_path,
        "counts": {
            "seed_nonrecipe_span_count": int(seed_nonrecipe_span_count),
            "candidate_nonrecipe_span_count": int(candidate_nonrecipe_span_count),
            "packet_count_before_partition": int(packet_count_before_partition),
            "shards_written": 0,
            "packets_written": 0,
            "candidate_block_count": int(candidate_block_count),
            "excluded_block_count": int(excluded_block_count),
            "skipped_packet_count": int(skipped_packet_count),
            "outputs_parsed": 0,
            "packets_missing": 0,
            "useful_packets_promoted": 0,
            "snippets_written": 0,
            "decisions_applied": 0,
            "changed_blocks": 0,
            "worker_count": 0,
            "validated_shards": 0,
            "invalid_shards": 0,
            "no_final_output_shards": 0,
            "partially_promoted_shards": 0,
            "wholly_unpromoted_invalid_shards": 0,
            "promoted_packet_count": 0,
            "reviewed_shards_with_useful_packets": 0,
            "reviewed_shards_all_other": 0,
            "unreviewed_shard_count": 0,
            "unreviewed_packet_count": 0,
            "unreviewed_block_count": 0,
        },
        "timing": {"total_seconds": 0.0},
        "paths": {
            "nonrecipe_route_path": str(
                run_root / NONRECIPE_ROUTE_FILE_NAME
            ),
            "nonrecipe_authority_path": str(run_root / NONRECIPE_AUTHORITY_FILE_NAME),
            "nonrecipe_finalize_status_path": str(
                run_root / NONRECIPE_FINALIZE_STATUS_FILE_NAME
            ),
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_packet_ids": [],
        "skipped_packet_reason_counts": dict(skipped_packet_reason_counts or {}),
        "candidate_summary": {
            "seed_nonrecipe_span_count": int(seed_nonrecipe_span_count),
            "candidate_nonrecipe_span_count": int(candidate_nonrecipe_span_count),
            "packet_count_before_partition": int(packet_count_before_partition),
            "planned_packet_count": 0,
            "reviewed_packet_count": 0,
            "candidate_block_count": int(candidate_block_count),
            "excluded_block_count": int(excluded_block_count),
            "skipped_packet_count": int(skipped_packet_count),
            "skipped_packet_reason_counts": dict(
                sorted((skipped_packet_reason_counts or {}).items())
            ),
            "planned_shard_count": 0,
            "reviewed_shard_count": 0,
            "validated_output_packet_count": 0,
            "validated_shard_count": 0,
            "invalid_shard_count": 0,
            "no_final_output_shard_count": 0,
            "partially_promoted_shard_count": 0,
            "wholly_unpromoted_invalid_shard_count": 0,
            "reviewed_shards_with_useful_packets": 0,
            "reviewed_shards_all_other": 0,
            "unreviewed_shard_count": 0,
            "unreviewed_packet_count": 0,
            "unreviewed_block_count": 0,
            "promoted_useful_packet_count": 0,
            "promoted_snippet_count": 0,
        },
        "candidate_status": "complete",
        "stage_status": stage_status,
        "phase_worker_runtime": {
            "phase_key": "nonrecipe_finalize",
            "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
            "worker_count": 0,
            "shard_count": 0,
            "worker_reports": [],
        },
    }


def _build_runtime_failed_knowledge_llm_report(
    *,
    run_settings: RunSettings,
    pipeline_id: str,
    output_schema_path: str | None,
    manifest_path: Path,
    run_root: Path,
    knowledge_in_dir: Path,
    knowledge_stage_dir: Path,
    build_report: Any,
    seed_nonrecipe_span_count: int,
    candidate_nonrecipe_span_count: int,
    excluded_block_count: int,
    elapsed_seconds: float,
    error: str,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "pipeline": run_settings.llm_knowledge_pipeline.value,
        "pipeline_id": pipeline_id,
        "input_mode": "nonrecipe_candidate_spans",
        "authority_mode": "knowledge_not_run_runtime_failed",
        "scored_effect": "route_only",
        "output_schema_path": output_schema_path,
        "counts": {
            "seed_nonrecipe_span_count": int(seed_nonrecipe_span_count),
            "candidate_nonrecipe_span_count": int(
                candidate_nonrecipe_span_count
            ),
            "packet_count_before_partition": int(build_report.packet_count_before_partition),
            "shards_written": int(build_report.shards_written),
            "packets_written": int(build_report.packets_written),
            "candidate_block_count": int(
                getattr(build_report, "candidate_block_count", 0) or 0
            ),
            "excluded_block_count": int(excluded_block_count),
            "skipped_packet_count": int(build_report.skipped_packet_count),
            "outputs_parsed": 0,
            "packets_missing": int(build_report.packets_written),
            "useful_packets_promoted": 0,
            "snippets_written": 0,
            "decisions_applied": 0,
            "changed_blocks": 0,
            "worker_count": 0,
            "validated_shards": 0,
            "invalid_shards": 0,
            "no_final_output_shards": int(build_report.shards_written),
            "partially_promoted_shards": 0,
            "wholly_unpromoted_invalid_shards": 0,
            "promoted_packet_count": 0,
            "reviewed_shards_with_useful_packets": 0,
            "reviewed_shards_all_other": 0,
            "unreviewed_shard_count": int(build_report.shards_written),
            "unreviewed_packet_count": int(build_report.packets_written),
            "unreviewed_block_count": 0,
        },
        "timing": {"total_seconds": elapsed_seconds},
        "paths": {
            "nonrecipe_route_path": str(
                run_root / NONRECIPE_ROUTE_FILE_NAME
            ),
            "nonrecipe_authority_path": str(run_root / NONRECIPE_AUTHORITY_FILE_NAME),
            "nonrecipe_finalize_status_path": str(
                run_root / NONRECIPE_FINALIZE_STATUS_FILE_NAME
            ),
            "knowledge_in_dir": str(knowledge_in_dir),
            "knowledge_phase_dir": str(knowledge_stage_dir),
            "manifest_path": str(manifest_path),
            **_runtime_artifact_paths(knowledge_stage_dir),
        },
        "missing_packet_ids": list(build_report.packet_ids),
        "skipped_packet_reason_counts": dict(build_report.skipped_packet_reason_counts),
        "planning_warnings": list(build_report.planning_warnings),
        "candidate_summary": _build_review_summary(
            build_report=build_report,
            validated_output_count=0,
            planned_shard_count=int(build_report.shards_written),
            review_rollup={
                "validated_shard_count": 0,
                "invalid_shard_count": 0,
                "no_final_output_shard_count": int(build_report.shards_written),
                "partially_promoted_shard_count": 0,
                "wholly_unpromoted_invalid_shard_count": 0,
                "reviewed_shards_with_useful_packets": 0,
                "reviewed_shards_all_other": 0,
                "meaningfully_reviewed_shard_count": 0,
                "unreviewed_shard_count": int(build_report.shards_written),
                "unreviewed_packet_count": int(build_report.packets_written),
                "unreviewed_block_count": 0,
                "excluded_block_count": 0,
            },
            promoted_useful_packet_count=0,
            promoted_snippet_count=0,
        ),
        "candidate_status": "unreviewed",
        "stage_status": "runtime_failed",
        "error": error,
        "phase_worker_runtime": {
            "phase_key": "nonrecipe_finalize",
            "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
            "worker_count": 0,
            "shard_count": int(build_report.shards_written),
            "worker_reports": [],
        },
    }

def _extract_full_blocks(result: ConversionResult) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    for artifact in result.raw_artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        blocks = content.get("blocks")
        if not isinstance(blocks, list):
            continue
        for raw_block in blocks:
            if not isinstance(raw_block, dict):
                continue
            index = _coerce_int(raw_block.get("index"))
            if index is None:
                continue
            if index in by_index:
                continue
            by_index[index] = dict(raw_block)
    return [by_index[index] for index in sorted(by_index)]


def _prepare_full_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        index = _coerce_int(block.get("index"))
        if index is None:
            continue
        payload = dict(block)
        payload["index"] = index
        block_id = payload.get("block_id") or payload.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f"b{index}"
        payload["block_id"] = block_id.strip()
        prepared.append(payload)
    prepared.sort(key=lambda item: int(item["index"]))
    return prepared


def _resolve_pipeline_root(run_settings: RunSettings) -> Path:
    if run_settings.codex_farm_root:
        root = Path(run_settings.codex_farm_root).expanduser()
    else:
        root = Path(__file__).resolve().parents[3] / "llm_pipelines"
    required = ("pipelines", "prompts", "schemas")
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise CodexFarmRunnerError(
            "Invalid codex-farm pipeline root "
            f"{root}: missing {', '.join(missing)}."
        )
    return root


def _resolve_workspace_root(run_settings: RunSettings) -> Path | None:
    value = run_settings.codex_farm_workspace_root
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.exists() or not root.is_dir():
        raise CodexFarmRunnerError(
            "Invalid codex-farm workspace root "
            f"{root}: path does not exist or is not a directory."
        )
    return root


def _non_empty(value: object, *, fallback: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    return rendered or fallback


def _resolve_source_hash(result: ConversionResult) -> str:
    for artifact in result.raw_artifacts:
        if artifact.source_hash:
            return str(artifact.source_hash)
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        source_hash = provenance.get("file_hash") or provenance.get("fileHash")
        if source_hash:
            return str(source_hash)
    return "unknown"


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _collect_block_category_updates(
    *,
    outputs: Mapping[str, Any],
    allowed_block_indices: Mapping[int, str],
) -> tuple[
    dict[int, str],
    dict[int, str],
    dict[int, list[str]],
    list[dict[str, Any]],
    list[int],
]:
    normalized_allowed = {
        int(block_index): str(category or "other")
        for block_index, category in allowed_block_indices.items()
    }
    decisions_by_block: dict[int, list[tuple[str, str, str | None]]] = {}
    ignored_block_indices: list[int] = []
    for packet_id, output in outputs.items():
        for decision in output.block_decisions:
            block_index = int(decision.block_index)
            if block_index not in normalized_allowed:
                ignored_block_indices.append(block_index)
                continue
            decisions_by_block.setdefault(block_index, []).append(
                (
                    str(packet_id),
                    str(decision.category),
                    str(decision.reviewer_category or "").strip() or None,
                )
            )

    block_category_updates: dict[int, str] = {}
    reviewer_categories_by_block: dict[int, str] = {}
    applied_packet_ids_by_block: dict[int, list[str]] = {}
    conflicts: list[dict[str, Any]] = []
    for block_index, decision_rows in sorted(decisions_by_block.items()):
        categories = {category for _, category, _ in decision_rows}
        if len(categories) > 1:
            conflicts.append(
                {
                            "block_index": int(block_index),
                            "seed_category": normalized_allowed.get(block_index),
                            "decisions": [
                                {
                                    "packet_id": packet_id,
                                    "category": category,
                                    "reviewer_category": reviewer_category,
                                }
                        for packet_id, category, reviewer_category in decision_rows
                            ],
                            "resolution": "kept_seed_category",
                        }
            )
            continue
        block_category_updates[block_index] = next(iter(categories))
        reviewer_categories = [
            reviewer_category
            for _, _, reviewer_category in decision_rows
            if reviewer_category is not None
        ]
        if reviewer_categories:
            reviewer_categories_by_block[block_index] = reviewer_categories[0]
        applied_packet_ids_by_block[block_index] = [
            packet_id for packet_id, _, _ in decision_rows
        ]
    return (
        block_category_updates,
        reviewer_categories_by_block,
        applied_packet_ids_by_block,
        conflicts,
        ignored_block_indices,
    )


def _serialize_decision_grounding(decision: Any) -> dict[str, Any]:
    grounding = getattr(decision, "grounding", None)
    tag_keys = [
        str(value).strip()
        for value in (getattr(grounding, "tag_keys", ()) or ())
        if str(value).strip()
    ]
    category_keys = [
        str(value).strip()
        for value in (getattr(grounding, "category_keys", ()) or ())
        if str(value).strip()
    ]
    proposed_tags = [
        {
            "key": str(tag.key).strip(),
            "display_name": str(tag.display_name).strip(),
            "category_key": str(tag.category_key).strip(),
        }
        for tag in (getattr(grounding, "proposed_tags", ()) or ())
        if str(getattr(tag, "key", "")).strip()
    ]
    return {
        "tag_keys": tag_keys,
        "category_keys": category_keys,
        "proposed_tags": proposed_tags,
    }


def _collect_block_grounding_details(
    *,
    outputs: Mapping[str, Any],
    allowed_block_indices: Mapping[int, str],
) -> tuple[dict[int, dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    normalized_allowed = {int(block_index) for block_index in allowed_block_indices}
    grounding_by_block: dict[int, dict[str, Any]] = {}
    proposal_rollups: dict[tuple[str, str], dict[str, Any]] = {}
    counts = {
        "kept_knowledge_block_count": 0,
        "retrieval_gate_rejected_block_count": 0,
        "knowledge_blocks_grounded_to_existing_tags": 0,
        "knowledge_blocks_using_proposed_tags": 0,
    }
    for packet_id, output in outputs.items():
        for decision in getattr(output, "block_decisions", ()) or ():
            block_index = int(getattr(decision, "block_index", 0) or 0)
            if block_index not in normalized_allowed:
                continue
            category = str(getattr(decision, "category", "") or "").strip()
            if category != "knowledge":
                counts["retrieval_gate_rejected_block_count"] += 1
                continue
            counts["kept_knowledge_block_count"] += 1
            retrieval_concept = str(
                getattr(decision, "retrieval_concept", "") or ""
            ).strip() or None
            grounding = _serialize_decision_grounding(decision)
            if grounding["tag_keys"]:
                counts["knowledge_blocks_grounded_to_existing_tags"] += 1
            if grounding["proposed_tags"]:
                counts["knowledge_blocks_using_proposed_tags"] += 1
            grounding_by_block[block_index] = {
                "packet_id": str(packet_id),
                "retrieval_concept": retrieval_concept,
                "grounding": grounding,
            }
            for proposed_tag in grounding["proposed_tags"]:
                proposal_key = (
                    str(proposed_tag.get("key") or ""),
                    str(proposed_tag.get("category_key") or ""),
                )
                proposal_rollups.setdefault(
                    proposal_key,
                    {
                        "key": proposal_key[0],
                        "display_name": str(proposed_tag.get("display_name") or ""),
                        "category_key": proposal_key[1],
                        "occurrence_count": 0,
                        "packet_ids": set(),
                        "block_indices": [],
                        "retrieval_concepts": set(),
                    },
                )
                proposal_rollup = proposal_rollups[proposal_key]
                proposal_rollup["occurrence_count"] += 1
                proposal_rollup["packet_ids"].add(str(packet_id))
                proposal_rollup["block_indices"].append(block_index)
                if retrieval_concept is not None:
                    proposal_rollup["retrieval_concepts"].add(retrieval_concept)
    proposal_rows = [
        {
            "key": row["key"],
            "display_name": row["display_name"],
            "category_key": row["category_key"],
            "occurrence_count": int(row["occurrence_count"]),
            "packet_ids": sorted(row["packet_ids"]),
            "block_indices": sorted(set(int(value) for value in row["block_indices"])),
            "retrieval_concepts": sorted(row["retrieval_concepts"]),
        }
        for row in sorted(
            proposal_rollups.values(),
            key=lambda row: (row["category_key"], row["key"]),
        )
    ]
    counts["tag_proposal_count"] = len(proposal_rows)
    return grounding_by_block, counts, proposal_rows
