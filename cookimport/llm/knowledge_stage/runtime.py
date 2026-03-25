from __future__ import annotations

import sys

runtime = sys.modules["cookimport.llm.knowledge_stage"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)


def _runtime_attr(name: str, default: Any) -> Any:
    return getattr(runtime, name, default)


def run_codex_farm_nonrecipe_knowledge_review(
    *,
    conversion_result: ConversionResult,
    nonrecipe_stage_result: NonRecipeStageResult,
    recipe_spans: list[RecipeSpan],
    run_settings: RunSettings,
    run_root: Path,
    workbook_slug: str,
    overrides: ParsingOverrides | None = None,
    runner: CodexExecRunner | None = None,
    full_blocks: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> CodexFarmNonrecipeKnowledgeReviewResult:
    """Optional Stage 7 review over non-recipe chunks via codex-farm."""
    llm_raw_dir = run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug)
    manifest_path = llm_raw_dir / KNOWLEDGE_MANIFEST_FILE_NAME

    if run_settings.llm_knowledge_pipeline.value == "off":
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report={"enabled": False, "pipeline": "off"},
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
        )

    knowledge_stage_dir = llm_raw_dir / stage_artifact_stem("nonrecipe_knowledge_review")
    knowledge_in_dir = knowledge_stage_dir / "in"
    knowledge_in_dir.mkdir(parents=True, exist_ok=True)

    pipeline_id = _non_empty(
        run_settings.codex_farm_pipeline_knowledge,
        fallback=DEFAULT_KNOWLEDGE_PIPELINE_ID,
    )
    routing = nonrecipe_stage_result.routing
    all_nonrecipe_spans = list(nonrecipe_stage_result.seed.seed_nonrecipe_spans)
    review_candidate_spans = list(routing.review_eligible_nonrecipe_spans)
    seed_nonrecipe_span_count = len(all_nonrecipe_spans)
    review_eligible_nonrecipe_span_count = len(review_candidate_spans)
    review_eligible_block_count = len(routing.review_eligible_block_indices)
    review_excluded_block_count = len(routing.review_excluded_block_indices)
    if not all_nonrecipe_spans:
        llm_report = _build_noop_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=None,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="no_nonrecipe_spans",
            seed_nonrecipe_span_count=seed_nonrecipe_span_count,
            review_eligible_nonrecipe_span_count=review_eligible_nonrecipe_span_count,
            review_eligible_block_count=review_eligible_block_count,
            review_excluded_block_count=review_excluded_block_count,
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )
    if not review_candidate_spans:
        llm_report = _build_noop_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=None,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="no_review_eligible_nonrecipe_spans",
            seed_nonrecipe_span_count=seed_nonrecipe_span_count,
            review_eligible_nonrecipe_span_count=review_eligible_nonrecipe_span_count,
            review_eligible_block_count=review_eligible_block_count,
            review_excluded_block_count=review_excluded_block_count,
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )

    full_blocks_payload = _prepare_full_blocks(
        full_blocks if full_blocks is not None else _extract_full_blocks(conversion_result)
    )
    if not full_blocks_payload:
        raise CodexFarmRunnerError(
            "Cannot run codex-farm non-recipe knowledge review: no full_text blocks available."
        )
    full_blocks_by_index = {int(block["index"]): block for block in full_blocks_payload}

    pipeline_root = _resolve_pipeline_root(run_settings)
    workspace_root = _resolve_workspace_root(run_settings)
    env = {"CODEX_FARM_ROOT": str(pipeline_root)}
    configured_runner_cmd = str(run_settings.codex_farm_cmd or "").strip()
    if runner is None:
        codex_runner: CodexExecRunner = SubprocessCodexExecRunner(
            cmd=configured_runner_cmd
            if Path(configured_runner_cmd).name == "fake-codex-farm.py"
            else "codex exec"
        )
    else:
        codex_runner = runner
    codex_model = run_settings.codex_farm_model
    codex_reasoning_effort = _effort_override_value(
        run_settings.codex_farm_reasoning_effort
    )
    output_schema_path: str | None = None
    if runner is None:
        ensure_codex_farm_pipelines_exist(
            cmd=run_settings.codex_farm_cmd,
            root_dir=pipeline_root,
            pipeline_ids=(pipeline_id,),
            env=env,
        )
        output_schema_path = str(
            resolve_codex_farm_output_schema_path(
                root_dir=pipeline_root,
                pipeline_id=pipeline_id,
            )
        )

    started = time.perf_counter()
    build_report = build_knowledge_jobs(
        full_blocks=full_blocks_payload,
        candidate_spans=review_candidate_spans,
        recipe_spans=recipe_spans,
        workbook_slug=workbook_slug,
        source_hash=_resolve_source_hash(conversion_result),
        out_dir=knowledge_in_dir,
        context_blocks=run_settings.codex_farm_knowledge_context_blocks,
        overrides=overrides,
        prompt_target_count=run_settings.knowledge_prompt_target_count,
    )
    for warning in build_report.planning_warnings:
        logger.warning("Knowledge planning warning for %s: %s", workbook_slug, warning)

    if build_report.shards_written == 0:
        llm_report = _build_noop_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=output_schema_path,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="all_chunks_skipped",
            seed_nonrecipe_span_count=seed_nonrecipe_span_count,
            review_eligible_nonrecipe_span_count=review_eligible_nonrecipe_span_count,
            chunk_count_before_pruning=build_report.chunk_count_before_pruning,
            review_eligible_block_count=review_eligible_block_count,
            review_excluded_block_count=review_excluded_block_count,
            skipped_chunk_count=build_report.skipped_chunk_count,
            skipped_lane_counts=dict(build_report.skipped_lane_counts),
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )

    worker_count = resolve_phase_worker_count(
        requested_worker_count=run_settings.knowledge_worker_count,
        shard_count=len(build_report.shard_entries),
    )
    configured_worker_total = (
        max(1, int(run_settings.knowledge_worker_count))
        if run_settings.knowledge_worker_count is not None
        else worker_count
    )
    phase_manifest = None
    worker_reports: list[dict[str, Any]] = []
    process_run_payload: dict[str, Any] | None = None
    try:
        phase_manifest, phase_worker_reports, process_run_payload = _runtime_attr(
            "_run_direct_knowledge_workers_v1",
            _run_direct_knowledge_workers_v1,
        )(
            phase_key="nonrecipe_knowledge_review",
            pipeline_id=pipeline_id,
            run_root=knowledge_stage_dir,
            shards=build_report.shard_entries,
            runner=codex_runner,
            worker_count=worker_count,
            env=env,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
            output_schema_path=Path(output_schema_path) if output_schema_path else None,
            settings={
                "llm_knowledge_pipeline": run_settings.llm_knowledge_pipeline.value,
                "knowledge_prompt_target_count": run_settings.knowledge_prompt_target_count,
                "knowledge_worker_count": run_settings.knowledge_worker_count,
                "knowledge_shard_max_turns": run_settings.knowledge_shard_max_turns,
                "codex_farm_pipeline_knowledge": pipeline_id,
            },
            runtime_metadata={
                "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
                "input_mode": "stage7_review_eligible_nonrecipe_spans",
                "workspace_root": str(workspace_root) if workspace_root is not None else None,
                "configured_prompt_target_count": run_settings.knowledge_prompt_target_count,
            },
            progress_worker_total=configured_worker_total,
            progress_callback=progress_callback,
        )
        worker_reports = [
            {
                "worker_id": report.worker_id,
                "shard_ids": list(report.shard_ids),
                "status": report.status,
                "proposal_count": report.proposal_count,
                "failure_count": report.failure_count,
                "runtime_mode_audit": dict(report.runtime_mode_audit or {}),
                "workspace_root": report.workspace_root,
                "metadata": dict(report.metadata),
                "runner_result": dict(report.runner_result or {}),
            }
            for report in phase_worker_reports
        ]
    except KeyboardInterrupt:
        _mark_running_knowledge_status_files_interrupted(knowledge_stage_dir)
        _write_knowledge_stage_status(
            stage_root=knowledge_stage_dir,
            manifest_path=manifest_path,
            stage_state="interrupted",
            termination_cause="operator_interrupt",
            finalization_completeness="interrupted_before_finalization",
        )
        raise
    except CodexFarmRunnerError as exc:
        elapsed_seconds = round(time.perf_counter() - started, 3)
        llm_report = _build_runtime_failed_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=output_schema_path,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            build_report=build_report,
            seed_nonrecipe_span_count=seed_nonrecipe_span_count,
            review_eligible_nonrecipe_span_count=review_eligible_nonrecipe_span_count,
            review_excluded_block_count=review_excluded_block_count,
            elapsed_seconds=elapsed_seconds,
            error=str(exc),
        )
        _write_json(llm_report, manifest_path)
        _write_knowledge_stage_status(
            stage_root=knowledge_stage_dir,
            manifest_path=manifest_path,
            stage_state="runtime_failed",
            termination_cause="runtime_error",
            finalization_completeness="complete",
        )
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )

    try:
        outputs, _ = read_validated_knowledge_outputs_from_proposals(
            knowledge_stage_dir / "proposals"
        )
        missing_packet_ids = sorted(set(build_report.packet_ids) - set(outputs))
        (
            block_category_updates,
            reviewer_categories_by_block,
            applied_chunk_ids_by_block,
            conflicts,
            ignored_block_indices,
        ) = _collect_block_category_updates(
            outputs=outputs,
            allowed_block_indices={
                int(block_index): "review_candidate"
                for block_index in routing.review_eligible_block_indices
            },
        )
        refined_stage_result = refine_nonrecipe_stage_result(
            stage_result=nonrecipe_stage_result,
            full_blocks=full_blocks_payload,
            block_category_updates=block_category_updates,
            reviewer_categories_by_block=reviewer_categories_by_block,
            applied_chunk_ids_by_block=applied_chunk_ids_by_block,
            conflicts=conflicts,
            ignored_block_indices=ignored_block_indices,
        )

        write_report = write_knowledge_artifacts(
            run_root=run_root,
            workbook_slug=workbook_slug,
            outputs=outputs,
            full_blocks_by_index=full_blocks_by_index,
        )

        elapsed_seconds = round(time.perf_counter() - started, 3)
        promotion_report = _load_json_dict(knowledge_stage_dir / "promotion_report.json")
        telemetry = _load_json_dict(knowledge_stage_dir / "telemetry.json")
        useful_chunk_count = sum(1 for output in outputs.values() if bool(output.is_useful))
        review_rollup = _build_knowledge_review_rollup(
            promotion_report=promotion_report,
            build_report=build_report,
        )
        review_rollup["review_excluded_block_count"] = review_excluded_block_count
        authority_mode = _derive_knowledge_authority_mode(
            refined_stage_result=refined_stage_result,
            review_rollup=review_rollup,
        )
        review_status = _derive_knowledge_review_status(review_rollup)
        refined_report = {
            **dict(refined_stage_result.refinement_report),
            "authority_mode": authority_mode,
            "review_status": review_status,
            "reviewed_shards_with_useful_packets": review_rollup["reviewed_shards_with_useful_packets"],
            "reviewed_shards_all_other": review_rollup["reviewed_shards_all_other"],
            "partially_promoted_shard_count": review_rollup["partially_promoted_shard_count"],
            "wholly_unpromoted_invalid_shard_count": review_rollup[
                "wholly_unpromoted_invalid_shard_count"
            ],
            "semantic_rejection_shard_count": review_rollup["semantic_rejection_shard_count"],
            "unreviewed_shard_count": review_rollup["unreviewed_shard_count"],
            "unreviewed_packet_count": review_rollup["unreviewed_packet_count"],
            "unreviewed_block_count": review_rollup["unreviewed_block_count"],
        }
        refined_stage_result = replace(
            refined_stage_result,
            refinement_report=refined_report,
        )
        review_summary = _build_review_summary(
            build_report=build_report,
            validated_output_count=len(outputs),
            planned_shard_count=(
                int(phase_manifest.shard_count)
                if phase_manifest is not None
                else build_report.shards_written
            ),
            review_rollup=review_rollup,
            promoted_useful_packet_count=useful_chunk_count,
            promoted_snippet_count=write_report.snippets_written,
        )
        llm_report = {
            "enabled": True,
            "pipeline": run_settings.llm_knowledge_pipeline.value,
            "pipeline_id": pipeline_id,
            "input_mode": "stage7_review_eligible_nonrecipe_spans",
            "authority_mode": authority_mode,
            "scored_effect": str(
                refined_stage_result.refinement_report.get("scored_effect")
                or "seed_only"
            ),
            "output_schema_path": output_schema_path,
            "counts": {
                "seed_nonrecipe_span_count": seed_nonrecipe_span_count,
                "review_eligible_nonrecipe_span_count": review_eligible_nonrecipe_span_count,
                "chunks_built_before_pruning": build_report.chunk_count_before_pruning,
                "shards_written": build_report.shards_written,
                "chunks_written": build_report.chunks_written,
                "review_eligible_block_count": review_eligible_block_count,
                "review_excluded_block_count": review_excluded_block_count,
                "skipped_chunk_count": build_report.skipped_chunk_count,
                "outputs_parsed": len(outputs),
                "packets_missing": len(missing_packet_ids),
                "useful_packets_promoted": useful_chunk_count,
                "snippets_written": write_report.snippets_written,
                "decisions_applied": len(block_category_updates),
                "changed_blocks": int(
                    refined_stage_result.refinement_report.get("changed_block_count") or 0
                ),
                "worker_count": (
                    int(phase_manifest.worker_count)
                    if phase_manifest is not None
                    else worker_count
                ),
                "validated_shards": int(promotion_report.get("validated_shards") or 0),
                "invalid_shards": int(promotion_report.get("invalid_shards") or 0),
                "missing_output_shards": int(promotion_report.get("missing_output_shards") or 0),
                "partially_promoted_shards": review_rollup["partially_promoted_shard_count"],
                "wholly_unpromoted_invalid_shards": review_rollup[
                    "wholly_unpromoted_invalid_shard_count"
                ],
                "promoted_packet_count": int(promotion_report.get("promoted_packet_count") or 0),
                "reviewed_shards_with_useful_packets": review_rollup["reviewed_shards_with_useful_packets"],
                "reviewed_shards_all_other": review_rollup["reviewed_shards_all_other"],
                "semantic_rejection_shard_count": review_rollup["semantic_rejection_shard_count"],
                "unreviewed_shard_count": review_rollup["unreviewed_shard_count"],
                "unreviewed_packet_count": review_rollup["unreviewed_packet_count"],
                "unreviewed_block_count": review_rollup["unreviewed_block_count"],
            },
            "timing": {"total_seconds": elapsed_seconds},
            "paths": {
                "nonrecipe_seed_routing_path": str(
                    run_root / NONRECIPE_SEED_ROUTING_FILE_NAME
                ),
                "nonrecipe_authority_path": str(
                    run_root / NONRECIPE_AUTHORITY_FILE_NAME
                ),
                "nonrecipe_review_status_path": str(
                    run_root / NONRECIPE_REVIEW_STATUS_FILE_NAME
                ),
                "knowledge_in_dir": str(knowledge_in_dir),
                "knowledge_phase_dir": str(knowledge_stage_dir),
                "knowledge_groups_path": str(write_report.groups_path),
                "snippets_path": str(write_report.snippets_path),
                "preview_path": str(write_report.preview_path),
                "manifest_path": str(manifest_path),
                **_runtime_artifact_paths(knowledge_stage_dir),
            },
            "missing_packet_ids": missing_packet_ids,
            "skipped_lane_counts": dict(build_report.skipped_lane_counts),
            "planning_warnings": list(build_report.planning_warnings),
            "review_summary": review_summary,
            "refinement_report": refined_report,
            "process_run": process_run_payload,
            "phase_worker_runtime": {
                "phase_key": "nonrecipe_knowledge_review",
                "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
                "configured_prompt_target_count": run_settings.knowledge_prompt_target_count,
                "configured_worker_count": run_settings.knowledge_worker_count,
                "worker_count": (
                    int(phase_manifest.worker_count)
                    if phase_manifest is not None
                    else worker_count
                ),
                "shard_count": (
                    int(phase_manifest.shard_count)
                    if phase_manifest is not None
                    else build_report.shards_written
                ),
                "assignment_strategy": (
                    str(phase_manifest.assignment_strategy)
                    if phase_manifest is not None
                    else "round_robin_v1"
                ),
                "task_total": int(
                    (phase_manifest.runtime_metadata or {}).get("task_total")
                    or (phase_manifest.runtime_metadata or {}).get("task_packet_total")
                    or 0
                )
                if phase_manifest is not None
                else 0,
                "task_packet_total": int(
                    (phase_manifest.runtime_metadata or {}).get("task_packet_total") or 0
                )
                if phase_manifest is not None
                else 0,
                "bundle_policy": str(
                    (phase_manifest.runtime_metadata or {}).get("bundle_policy") or ""
                ).strip()
                or "shard_round_robin_chunk_bundle_tasks_v1",
                "worker_task_counts": dict(
                    (phase_manifest.runtime_metadata or {}).get("worker_task_counts")
                    or (phase_manifest.runtime_metadata or {}).get("worker_task_packet_counts")
                    or {}
                )
                if phase_manifest is not None
                else {},
                "worker_task_packet_counts": dict(
                    (phase_manifest.runtime_metadata or {}).get("worker_task_packet_counts")
                    or {}
                )
                if phase_manifest is not None
                else {},
                "max_tasks_per_worker": int(
                    (phase_manifest.runtime_metadata or {}).get("max_tasks_per_worker")
                    or (phase_manifest.runtime_metadata or {}).get("max_task_packets_per_worker")
                    or 0
                )
                if phase_manifest is not None
                else 0,
                "max_task_packets_per_worker": int(
                    (phase_manifest.runtime_metadata or {}).get("max_task_packets_per_worker")
                    or 0
                )
                if phase_manifest is not None
                else 0,
                "min_tasks_per_worker": int(
                    (phase_manifest.runtime_metadata or {}).get("min_tasks_per_worker")
                    or (phase_manifest.runtime_metadata or {}).get("min_task_packets_per_worker")
                    or 0
                )
                if phase_manifest is not None
                else 0,
                "min_task_packets_per_worker": int(
                    (phase_manifest.runtime_metadata or {}).get("min_task_packets_per_worker")
                    or 0
                )
                if phase_manifest is not None
                else 0,
                "telemetry": telemetry,
                "promotion_report": promotion_report,
                "worker_reports": worker_reports,
            },
            "review_status": review_status,
            "stage_status": (
                "completed_with_failures"
                if int(promotion_report.get("invalid_shards") or 0) > 0
                or int(promotion_report.get("missing_output_shards") or 0) > 0
                else "completed"
            ),
        }
        _write_json(llm_report, manifest_path)
    except KeyboardInterrupt:
        _mark_running_knowledge_status_files_interrupted(knowledge_stage_dir)
        _write_knowledge_stage_status(
            stage_root=knowledge_stage_dir,
            manifest_path=manifest_path,
            stage_state="interrupted",
            termination_cause="operator_interrupt",
            finalization_completeness="interrupted_before_finalization",
        )
        raise
    except Exception:
        _write_knowledge_stage_status(
            stage_root=knowledge_stage_dir,
            manifest_path=manifest_path,
            stage_state="failed",
            termination_cause="unexpected_exception",
            finalization_completeness="stopped_before_finalization",
        )
        raise

    _write_knowledge_stage_status(
        stage_root=knowledge_stage_dir,
        manifest_path=manifest_path,
        stage_state=str(llm_report["stage_status"]),
        termination_cause="completed",
        finalization_completeness="complete",
    )

    return CodexFarmNonrecipeKnowledgeReviewResult(
        llm_report=llm_report,
        llm_raw_dir=llm_raw_dir,
        manifest_path=manifest_path,
        refined_stage_result=refined_stage_result,
        write_report=write_report,
    )




def _run_direct_knowledge_workers_v1(
    *,
    phase_key: str,
    pipeline_id: str,
    run_root: Path,
    shards: list[ShardManifestEntryV1],
    runner: CodexExecRunner,
    worker_count: int,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    settings: Mapping[str, Any],
    runtime_metadata: Mapping[str, Any],
    progress_worker_total: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[PhaseManifestV1, list[WorkerExecutionReportV1], dict[str, Any]]:
    artifacts = {
        "phase_manifest": "phase_manifest.json",
        "shard_manifest": "shard_manifest.jsonl",
        "task_manifest": "task_manifest.jsonl",
        "task_status": _KNOWLEDGE_TASK_STATUS_FILE_NAME,
        "worker_assignments": "worker_assignments.json",
        "promotion_report": "promotion_report.json",
        "telemetry": "telemetry.json",
        "failures": "failures.json",
        "proposals_dir": "proposals",
    }
    run_root.mkdir(parents=True, exist_ok=True)
    shard_by_id = {shard.shard_id: shard for shard in shards}
    task_plans_by_shard_id = {
        shard.shard_id: _build_knowledge_task_plans(shard)
        for shard in shards
    }
    task_entries = [
        task_entry
        for shard in shards
        for task_entry in _knowledge_task_runtime_entries_for_shard(
            shard=shard,
            task_plans_by_shard_id=task_plans_by_shard_id,
        )
    ]
    _write_jsonl(
        run_root / artifacts["shard_manifest"],
        [asdict(shard) for shard in shards],
    )
    _write_jsonl(
        run_root / artifacts["task_manifest"],
        [asdict(task_entry) for task_entry in task_entries],
    )
    task_status_tracker = _build_knowledge_task_status_tracker(
        path=run_root / artifacts["task_status"],
        task_entries=task_entries,
    )

    all_proposals: list[ShardProposalV1] = []
    failures: list[dict[str, Any]] = []
    worker_reports: list[WorkerExecutionReportV1] = []
    stage_rows: list[dict[str, Any]] = []
    bypassed_shard_ids: set[str] = set()
    runnable_shards = list(shards)
    assignments = _assign_workers_v1(
        run_root=run_root,
        shards=runnable_shards,
        worker_count=worker_count,
    )
    _write_json(
        [asdict(assignment) for assignment in assignments],
        run_root / artifacts["worker_assignments"],
    )
    total_shards = len(shards)
    total_task_packets = sum(
        len(_progress_task_ids_for_knowledge_shard(
            shard_id=shard.shard_id,
            task_plans_by_shard_id=task_plans_by_shard_id,
        ))
        for shard in shards
    )
    packet_distribution = _summarize_knowledge_task_packet_distribution(
        assignments=assignments,
        task_plans_by_shard_id=task_plans_by_shard_id,
    )
    displayed_worker_total = (
        max(0, int(progress_worker_total))
        if progress_worker_total is not None
        else worker_count
    )
    progress_state = _KnowledgePhaseProgressState(
        progress_callback=progress_callback,
        total_shards=len(runnable_shards),
        total_task_packets=max(total_task_packets - len(bypassed_shard_ids), 0),
        worker_total=displayed_worker_total,
        worker_order=tuple(assignment.worker_id for assignment in assignments),
        worker_states={
            assignment.worker_id: _KnowledgeWorkerProgressState(
                worker_id=assignment.worker_id,
                shard_ids=assignment.shard_ids,
                pending_shard_ids=list(assignment.shard_ids),
                total_task_packets=sum(
                    len(
                        _progress_task_ids_for_knowledge_shard(
                            shard_id=shard_id,
                            task_plans_by_shard_id=task_plans_by_shard_id,
                        )
                    )
                    for shard_id in assignment.shard_ids
                ),
            )
            for assignment in assignments
        },
    )
    progress_state.emit(force=True)
    cohort_watchdog_state = _KnowledgeCohortWatchdogState()
    recovery_governor = _KnowledgeRecoveryGovernor()
    interruption_requested = threading.Event()

    def _mark_shard_completed(*, worker_id: str, shard_id: str) -> None:
        progress_state.mark_shard_completed(worker_id=worker_id, shard_id=shard_id)

    runtime_metadata_payload = {
        **dict(runtime_metadata or {}),
        "task_total": total_task_packets,
        "task_packet_total": total_task_packets,
        "deterministic_bypass_packet_total": 0,
        "llm_review_packet_total": total_task_packets,
        **packet_distribution,
    }
    manifest = _write_knowledge_runtime_summary_artifacts(
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=run_root,
        artifacts=artifacts,
        assignments=assignments,
        shards=shards,
        settings=settings,
        runtime_metadata=runtime_metadata_payload,
        worker_reports=worker_reports,
        all_proposals=all_proposals,
        failures=failures,
        stage_rows=stage_rows,
    )
    executor = ThreadPoolExecutor(
        max_workers=max(1, len(assignments)),
        thread_name_prefix="knowledge-worker",
    )
    try:
        futures_by_worker_id = {
            assignment.worker_id: executor.submit(
                _runtime_attr(
                    "_run_direct_knowledge_worker_assignment_v1",
                    _run_direct_knowledge_worker_assignment_v1,
                ),
                run_root=run_root,
                assignment=assignment,
                artifacts=artifacts,
                shard_by_id=shard_by_id,
                runner=runner,
                pipeline_id=pipeline_id,
                env=env,
                model=model,
                reasoning_effort=reasoning_effort,
                output_schema_path=output_schema_path,
                cohort_watchdog_state=cohort_watchdog_state,
                recovery_governor=recovery_governor,
                shard_completed_callback=_mark_shard_completed,
                progress_state=progress_state,
                task_status_tracker=task_status_tracker,
                interruption_requested=interruption_requested,
            )
            for assignment in assignments
        }
        try:
            for assignment in assignments:
                result = futures_by_worker_id[assignment.worker_id].result()
                worker_reports.append(result.report)
                all_proposals.extend(result.proposals)
                failures.extend(result.failures)
                stage_rows.extend(result.stage_rows)
        except KeyboardInterrupt:
            interruption_requested.set()
            task_status_tracker.mark_interrupted()
            _mark_running_knowledge_status_files_interrupted(run_root)
            _write_knowledge_runtime_summary_artifacts(
                phase_key=phase_key,
                pipeline_id=pipeline_id,
                run_root=run_root,
                artifacts=artifacts,
                assignments=assignments,
                shards=shards,
                settings=settings,
                runtime_metadata=runtime_metadata_payload,
                worker_reports=worker_reports,
                all_proposals=all_proposals,
                failures=failures,
                stage_rows=stage_rows,
            )
            for future in futures_by_worker_id.values():
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
    finally:
        if not interruption_requested.is_set():
            executor.shutdown(wait=True, cancel_futures=False)
    manifest = _write_knowledge_runtime_summary_artifacts(
        phase_key=phase_key,
        pipeline_id=pipeline_id,
        run_root=run_root,
        artifacts=artifacts,
        assignments=assignments,
        shards=shards,
        settings=settings,
        runtime_metadata=runtime_metadata_payload,
        worker_reports=worker_reports,
        all_proposals=all_proposals,
        failures=failures,
        stage_rows=stage_rows,
    )
    process_run_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=[
            dict(report.runner_result or {})
            for report in worker_reports
            if isinstance(report.runner_result, Mapping)
        ],
        stage_rows=stage_rows,
    )
    process_run_summary = process_run_payload.get("telemetry", {}).get("summary")
    if isinstance(process_run_summary, dict):
        process_run_summary.update(
            _summarize_knowledge_workspace_relaunches(worker_reports)
        )
    return manifest, worker_reports, process_run_payload


def _assign_workers_v1(
    *,
    run_root: Path,
    shards: list[ShardManifestEntryV1],
    worker_count: int,
) -> list[WorkerAssignmentV1]:
    effective_workers = resolve_phase_worker_count(
        requested_worker_count=worker_count,
        shard_count=len(shards),
    )
    buckets: list[list[str]] = [[] for _ in range(effective_workers)]
    for index, shard in enumerate(shards):
        buckets[index % effective_workers].append(shard.shard_id)
    return [
        WorkerAssignmentV1(
            worker_id=f"worker-{index + 1:03d}",
            shard_ids=tuple(bucket),
            workspace_root=str(run_root / "workers" / f"worker-{index + 1:03d}"),
        )
        for index, bucket in enumerate(buckets)
    ]




def _run_knowledge_workspace_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    assigned_shards: Sequence[ShardManifestEntryV1],
    worker_root: Path,
    in_dir: Path,
    hints_dir: Path,
    shard_dir: Path,
    logs_dir: Path,
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    recovery_governor: _KnowledgeRecoveryGovernor,
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
    interruption_requested: threading.Event | None,
) -> _DirectKnowledgeWorkerResult:
    task_plans_by_shard_id = {
        shard.shard_id: _build_knowledge_task_plans(shard)
        for shard in assigned_shards
    }
    if any(task_plans for task_plans in task_plans_by_shard_id.values()):
        return _run_knowledge_workspace_worker_assignment_taskized_v1(
            run_root=run_root,
            assignment=assignment,
            artifacts=artifacts,
            assigned_shards=assigned_shards,
            task_plans_by_shard_id=task_plans_by_shard_id,
            worker_root=worker_root,
            in_dir=in_dir,
            hints_dir=hints_dir,
            shard_dir=shard_dir,
            logs_dir=logs_dir,
            runner=runner,
            pipeline_id=pipeline_id,
            env=env,
            model=model,
            reasoning_effort=reasoning_effort,
            output_schema_path=output_schema_path,
            cohort_watchdog_state=cohort_watchdog_state,
            recovery_governor=recovery_governor,
            shard_completed_callback=shard_completed_callback,
            progress_state=progress_state,
            task_status_tracker=task_status_tracker,
            interruption_requested=interruption_requested,
        )
    out_dir = worker_root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    runnable_shards: list[ShardManifestEntryV1] = []

    for shard in assigned_shards:
        input_path = in_dir / f"{shard.shard_id}.json"
        hint_path = hints_dir / f"{shard.shard_id}.md"
        _write_worker_input(path=input_path, payload=shard.input_payload, input_text=shard.input_text)
        _write_knowledge_worker_hint(path=hint_path, shard=shard)
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        shard_prompt_text = build_knowledge_direct_prompt(_coerce_dict(shard.input_payload))
        preflight_failure = _preflight_knowledge_shard(shard)
        if preflight_failure is None:
            runnable_shards.append(shard)
            continue
        (shard_root / "prompt.txt").write_text(shard_prompt_text, encoding="utf-8")
        preflight_result = _build_preflight_rejected_run_result(
            prompt_text=shard_prompt_text,
            output_schema_path=output_schema_path,
            working_dir=worker_root,
            reason_code=str(preflight_failure.get("reason_code") or "preflight_rejected"),
            reason_detail=str(
                preflight_failure.get("reason_detail") or "knowledge shard failed preflight"
            ),
        )
        _write_live_status(
            shard_root / "live_status.json",
            {
                "state": "preflight_rejected",
                "reason_code": preflight_result.supervision_reason_code,
                "reason_detail": preflight_result.supervision_reason_detail,
                "retryable": preflight_result.supervision_retryable,
                "watchdog_policy": "workspace_worker_v1",
                "elapsed_seconds": 0.0,
                "last_event_seconds_ago": None,
                "command_execution_count": 0,
                "reasoning_item_count": 0,
            },
        )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": None,
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "repair_attempted": False,
                "repair_status": "not_attempted",
            },
            proposal_path,
        )
        _write_json(
            {
                "error": "missing_output",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
            },
            shard_root / "proposal.json",
        )
        _write_json(
            {
                "status": "missing_output",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "repair_attempted": False,
                "repair_status": "not_attempted",
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                "retryable": False,
            },
            shard_root / "status.json",
        )
        worker_failure_count += 1
        worker_failures.append(
            {
                "worker_id": assignment.worker_id,
                "shard_id": shard.shard_id,
                "reason": "preflight_rejected",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
            }
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status="missing_output",
                proposal_path=_relative_path(run_root, proposal_path),
                payload=None,
                validation_errors=(str(preflight_failure.get("reason_code") or "preflight_rejected"),),
                metadata={
                    "watchdog_retry_attempted": False,
                    "watchdog_retry_status": "not_attempted",
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "repair_attempted": False,
                    "repair_status": "not_attempted",
                },
            )
        )
        if task_status_tracker is not None:
            task_status_tracker.mark_terminal(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                terminal_state="preflight_rejected",
                attempt_type="preflight",
                proposal_status="missing_output",
                validation_errors=(str(preflight_failure.get("reason_code") or "preflight_rejected"),),
                metadata={
                    "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                },
            )
        if progress_state is not None:
            progress_state.mark_task_packet_terminal(
                worker_id=assignment.worker_id,
                task_id=shard.shard_id,
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    if runnable_shards:
        workspace_prompt_tasks = _build_knowledge_workspace_task_runtime_entries(
            tuple(
                _KnowledgeTaskPlan(
                    task_id=shard.shard_id,
                    parent_shard_id=shard.shard_id,
                    manifest_entry=shard,
                )
                for shard in runnable_shards
            )
        )
        worker_prompt_text = _build_knowledge_workspace_worker_prompt(
            tasks=workspace_prompt_tasks
        )
        worker_prompt_path = worker_root / "prompt.txt"
        worker_prompt_path.write_text(worker_prompt_text, encoding="utf-8")
        worker_live_status_path = worker_root / "live_status.json"
        shard_live_status_paths = [
            shard_dir / shard.shard_id / "live_status.json" for shard in runnable_shards
        ]
        for shard in runnable_shards:
            shard_root = shard_dir / shard.shard_id
            (shard_root / "prompt.txt").write_text(worker_prompt_text, encoding="utf-8")
        if task_status_tracker is not None:
            for task_entry in workspace_prompt_tasks:
                task_metadata = dict(task_entry.metadata or {})
                task_status_tracker.start_attempt(
                    task_id=task_entry.task_id,
                    worker_id=assignment.worker_id,
                    attempt_type="main_worker",
                    metadata={
                        "lease_sequence": int(task_metadata.get("lease_sequence") or 0),
                        "lease_total": int(task_metadata.get("lease_total") or len(workspace_prompt_tasks)),
                        "input_path": task_metadata.get("input_path"),
                        "hint_path": task_metadata.get("hint_path"),
                        "result_path": task_metadata.get("result_path"),
                        "workspace_processing_contract": task_metadata.get(
                            "workspace_processing_contract"
                        ),
                    },
                )
        run_result = runner.run_workspace_worker(
            prompt_text=worker_prompt_text,
            working_dir=worker_root,
            env=env,
            model=model,
            reasoning_effort=reasoning_effort,
            workspace_task_label="knowledge worker session",
            supervision_callback=_runtime_attr(
                "_build_strict_json_watchdog_callback",
                _build_strict_json_watchdog_callback,
            )(
                live_status_path=worker_live_status_path,
                live_status_paths=shard_live_status_paths,
                cohort_watchdog_state=cohort_watchdog_state,
                watchdog_policy="workspace_worker_v1",
                allow_workspace_commands=True,
                execution_workspace_root=worker_root,
                forbid_inline_python_heredocs=False,
                expected_workspace_output_paths=[
                    out_dir / f"{shard.shard_id}.json" for shard in runnable_shards
                ],
                workspace_output_observer=(
                    None
                    if progress_state is None
                    else lambda present_count, expected_count, _worker_id=assignment.worker_id: (
                        progress_state.observe_workspace_outputs(
                            worker_id=_worker_id,
                            present_count=present_count,
                            expected_count=expected_count,
                        )
                    )
                ),
            ),
        )
        _finalize_live_status(
            worker_live_status_path,
            run_result=run_result,
            watchdog_policy="workspace_worker_v1",
        )
        for live_status_path in shard_live_status_paths:
            _finalize_live_status(
                live_status_path,
                run_result=run_result,
                watchdog_policy="workspace_worker_v1",
            )
        (worker_root / "events.jsonl").write_text(
            _render_events_jsonl(run_result.events),
            encoding="utf-8",
        )
        _write_json({"text": run_result.response_text}, worker_root / "last_message.json")
        _write_json(dict(run_result.usage or {}), worker_root / "usage.json")
        _write_json(run_result.workspace_manifest(), worker_root / "workspace_manifest.json")
        _write_optional_text(worker_root / "stdout.txt", run_result.stdout_text)
        _write_optional_text(worker_root / "stderr.txt", run_result.stderr_text)

        task_count = len(runnable_shards)
        for task_index, shard in enumerate(runnable_shards):
            shard_root = shard_dir / shard.shard_id
            input_path = in_dir / f"{shard.shard_id}.json"
            output_path = out_dir / f"{shard.shard_id}.json"
            response_text = (
                output_path.read_text(encoding="utf-8")
                if output_path.exists()
                else None
            )
            runner_payload = _build_knowledge_workspace_task_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=shard.shard_id,
                runtime_task_id=shard.shard_id,
                run_result=run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                request_input_file=input_path,
                worker_prompt_path=worker_prompt_path,
                task_count=task_count,
                task_index=task_index,
            )
            worker_runner_results.append(dict(runner_payload))
            telemetry = runner_payload.get("telemetry")
            row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
            if isinstance(row_payloads, list):
                for row_payload in row_payloads:
                    if isinstance(row_payload, dict):
                        stage_rows.append(dict(row_payload))
            primary_row = stage_rows[-1] if stage_rows else None
            primary_runner_row = (
                row_payloads[0]
                if isinstance(row_payloads, list)
                and row_payloads
                and isinstance(row_payloads[0], dict)
                else None
            )
            if interruption_requested is not None and interruption_requested.is_set():
                break
            payload, validation_errors, validation_metadata, proposal_status = (
                _evaluate_knowledge_response(
                    shard=shard,
                    response_text=response_text,
                )
            )
            active_response_text = str(response_text or "")
            active_run_result = run_result
            final_success_run_result = run_result
            initial_proposal_status = proposal_status
            main_failure_signature = _knowledge_failure_signature(
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                run_result=run_result,
            )
            if proposal_status != "validated":
                poisoned_worker_reason = recovery_governor.observe_main_failure(
                    worker_id=assignment.worker_id,
                    failure_signature=main_failure_signature,
                )
                if poisoned_worker_reason is not None:
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "poisoned_worker_reason_code": poisoned_worker_reason["reason_code"],
                        "poisoned_worker_reason_detail": poisoned_worker_reason["reason_detail"],
                    }
            watchdog_retry_attempted = False
            watchdog_retry_status = "not_attempted"
            watchdog_retry_skip_reason_code: str | None = None
            watchdog_retry_skip_reason_detail: str | None = None
            watchdog_retry_examples: list[dict[str, Any]] = []
            retry_followup_decision = _KnowledgeFollowupDecision(allowed=False)
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and _should_attempt_knowledge_watchdog_retry(run_result=run_result)
            ):
                retry_followup_decision = recovery_governor.allow_followup(
                    kind="retry",
                    worker_id=assignment.worker_id,
                    failure_signature=main_failure_signature,
                )
                if not retry_followup_decision.allowed:
                    watchdog_retry_status = "skipped"
                    watchdog_retry_skip_reason_code = retry_followup_decision.reason_code
                    watchdog_retry_skip_reason_detail = retry_followup_decision.reason_detail
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    }
                elif bool(_classify_knowledge_watchdog_retry_size(shard=shard).get("oversized")):
                    watchdog_retry_size = _classify_knowledge_watchdog_retry_size(shard=shard)
                    watchdog_retry_status = "oversized_skipped"
                    watchdog_retry_skip_reason_code = str(
                        watchdog_retry_size.get("reason_code") or "watchdog_retry_oversized_skipped"
                    )
                    watchdog_retry_skip_reason_detail = str(
                        watchdog_retry_size.get("reason_detail") or ""
                    )
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                        "watchdog_retry_packet_block_count": int(
                            watchdog_retry_size.get("packet_block_count") or 0
                        ),
                        "watchdog_retry_char_count": int(watchdog_retry_size.get("char_count") or 0),
                    }
                else:
                    watchdog_retry_attempted = True
                    watchdog_retry_examples = (
                        cohort_watchdog_state.snapshot().get("successful_examples") or []
                    )
                    watchdog_retry_root = shard_root / "watchdog_retry"
                    watchdog_retry_root.mkdir(parents=True, exist_ok=True)
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=shard.shard_id,
                                attempt_label="watchdog retry",
                            ),
                            followup_kind="retry",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=shard.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="watchdog_retry",
                        )
                    try:
                        watchdog_retry_run_result = _run_knowledge_watchdog_retry_attempt(
                            runner=runner,
                            worker_root=worker_root,
                            shard=shard,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            reason_code=str(run_result.supervision_reason_code or ""),
                            reason_detail=str(run_result.supervision_reason_detail or ""),
                            successful_examples=watchdog_retry_examples,
                            live_status_path=watchdog_retry_root / "live_status.json",
                        )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="retry",
                            )
                    _finalize_live_status(
                        watchdog_retry_root / "live_status.json",
                        run_result=watchdog_retry_run_result,
                    )
                    watchdog_retry_payload = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=shard.shard_id,
                        run_result=watchdog_retry_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode="inline_watchdog_retry",
                    )
                    worker_runner_results.append(dict(watchdog_retry_payload))
                    watchdog_retry_runner_rows = (
                        watchdog_retry_payload.get("telemetry", {}).get("rows")
                        if isinstance(watchdog_retry_payload.get("telemetry"), dict)
                        else None
                    )
                    watchdog_retry_row = None
                    if isinstance(watchdog_retry_runner_rows, list):
                        for row_payload in watchdog_retry_runner_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["is_watchdog_retry_attempt"] = True
                            row_payload["watchdog_retry_attempt_index"] = 1
                            watchdog_retry_row = dict(row_payload)
                            stage_rows.append(watchdog_retry_row)
                    (watchdog_retry_root / "events.jsonl").write_text(
                        _render_events_jsonl(watchdog_retry_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json(
                        {"text": watchdog_retry_run_result.response_text},
                        watchdog_retry_root / "last_message.json",
                    )
                    _write_json(
                        dict(watchdog_retry_run_result.usage or {}),
                        watchdog_retry_root / "usage.json",
                    )
                    _write_json(
                        watchdog_retry_run_result.workspace_manifest(),
                        watchdog_retry_root / "workspace_manifest.json",
                    )
                    (
                        payload,
                        validation_errors,
                        validation_metadata,
                        proposal_status,
                    ) = _evaluate_knowledge_response(
                        shard=shard,
                        response_text=watchdog_retry_run_result.response_text,
                    )
                    if watchdog_retry_row is not None:
                        watchdog_retry_row["proposal_status"] = proposal_status
                    if isinstance(watchdog_retry_runner_rows, list) and watchdog_retry_runner_rows:
                        first_watchdog_retry_runner_row = watchdog_retry_runner_rows[0]
                        if isinstance(first_watchdog_retry_runner_row, dict):
                            first_watchdog_retry_runner_row["proposal_status"] = proposal_status
                    _write_json(
                        {
                            "status": proposal_status,
                            "validation_errors": list(validation_errors),
                            "validation_metadata": dict(validation_metadata or {}),
                            "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                            "watchdog_retry_reason_code": run_result.supervision_reason_code,
                            "watchdog_retry_reason_detail": run_result.supervision_reason_detail,
                            "state": watchdog_retry_run_result.supervision_state or "completed",
                            "reason_code": watchdog_retry_run_result.supervision_reason_code,
                            "reason_detail": watchdog_retry_run_result.supervision_reason_detail,
                            "retryable": watchdog_retry_run_result.supervision_retryable,
                        },
                        watchdog_retry_root / "status.json",
                    )
                    watchdog_retry_status = (
                        "recovered" if proposal_status == "validated" else "failed"
                    )
                    recovery_governor.record_followup_outcome(
                        kind="retry",
                        failure_signature=main_failure_signature,
                        recovered=proposal_status == "validated",
                    )
                    active_run_result = watchdog_retry_run_result
                    active_response_text = str(watchdog_retry_run_result.response_text or "")
                    final_success_run_result = watchdog_retry_run_result
            retry_attempted = False
            retry_status = "not_attempted"
            retry_child_shard_ids: list[str] = []
            retry_failure_rows: list[dict[str, Any]] = []
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and _should_retry_knowledge_shard_split(
                    shard=shard,
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    response_text=active_response_text,
                )
            ):
                retry_attempted = True
                retry_shards = _split_failed_knowledge_shard_for_retry(
                    shard,
                    max_retry_chunk_count=_KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD,
                    max_retry_chars=_KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD,
                )
                retry_child_shard_ids = [retry_shard.shard_id for retry_shard in retry_shards]
                retry_results_by_shard_id: dict[str, dict[str, Any]] = {}
                retry_all_validated = bool(retry_shards)
                for retry_index, retry_shard in enumerate(retry_shards, start=1):
                    retry_root = shard_root / "retry_shards" / retry_shard.shard_id
                    retry_root.mkdir(parents=True, exist_ok=True)
                    retry_input_path = retry_root / "input.json"
                    _write_worker_input(
                        path=retry_input_path,
                        payload=retry_shard.input_payload,
                        input_text=retry_shard.input_text,
                    )
                    retry_prompt_text = build_knowledge_direct_prompt(
                        _coerce_dict(retry_shard.input_payload)
                    )
                    (retry_root / "prompt.txt").write_text(retry_prompt_text, encoding="utf-8")
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=shard.shard_id,
                                attempt_label="retry",
                                task_id=retry_shard.shard_id,
                            ),
                            followup_kind="retry",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=shard.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="retry_split",
                        )
                    try:
                        retry_run_result = runner.run_structured_prompt(
                            prompt_text=retry_prompt_text,
                            input_payload=_coerce_dict(retry_shard.input_payload),
                            working_dir=worker_root,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            workspace_task_label="knowledge review retry shard",
                            supervision_callback=_runtime_attr(
                                "_build_strict_json_watchdog_callback",
                                _build_strict_json_watchdog_callback,
                            )(
                                live_status_path=retry_root / "live_status.json",
                            ),
                        )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="retry",
                            )
                    _finalize_live_status(
                        retry_root / "live_status.json",
                        run_result=retry_run_result,
                    )
                    retry_payload_wrapper = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=retry_shard.shard_id,
                        run_result=retry_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode="inline_retry",
                    )
                    worker_runner_results.append(dict(retry_payload_wrapper))
                    retry_runner_rows = (
                        retry_payload_wrapper.get("telemetry", {}).get("rows")
                        if isinstance(retry_payload_wrapper.get("telemetry"), dict)
                        else None
                    )
                    retry_row = None
                    if isinstance(retry_runner_rows, list):
                        for row_payload in retry_runner_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["is_retry_attempt"] = True
                            row_payload["retry_attempt_index"] = retry_index
                            row_payload["retry_parent_shard_id"] = shard.shard_id
                            retry_row = dict(row_payload)
                            stage_rows.append(retry_row)
                    (retry_root / "events.jsonl").write_text(
                        _render_events_jsonl(retry_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json(
                        {"text": retry_run_result.response_text},
                        retry_root / "last_message.json",
                    )
                    _write_json(dict(retry_run_result.usage or {}), retry_root / "usage.json")
                    _write_json(
                        retry_run_result.workspace_manifest(),
                        retry_root / "workspace_manifest.json",
                    )
                    (
                        retry_payload_candidate,
                        retry_errors,
                        retry_metadata,
                        retry_proposal_status,
                    ) = _evaluate_knowledge_response(
                        shard=retry_shard,
                        response_text=retry_run_result.response_text,
                    )
                    if retry_row is not None:
                        retry_row["proposal_status"] = retry_proposal_status
                    if isinstance(retry_runner_rows, list) and retry_runner_rows:
                        first_retry_runner_row = retry_runner_rows[0]
                        if isinstance(first_retry_runner_row, dict):
                            first_retry_runner_row["proposal_status"] = retry_proposal_status
                    _write_json(
                        {
                            "status": retry_proposal_status,
                            "validation_errors": list(retry_errors),
                            "validation_metadata": dict(retry_metadata or {}),
                            "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                            "retry_parent_shard_id": shard.shard_id,
                            "state": retry_run_result.supervision_state or "completed",
                            "reason_code": retry_run_result.supervision_reason_code,
                            "reason_detail": retry_run_result.supervision_reason_detail,
                            "retryable": retry_run_result.supervision_retryable,
                        },
                        retry_root / "status.json",
                    )
                    if retry_proposal_status != "validated" or retry_payload_candidate is None:
                        retry_all_validated = False
                        retry_failure_rows.append(
                            {
                                "shard_id": retry_shard.shard_id,
                                "proposal_status": retry_proposal_status,
                                "validation_errors": list(retry_errors),
                                "validation_metadata": dict(retry_metadata or {}),
                            }
                        )
                        continue
                    retry_results_by_shard_id[retry_shard.shard_id] = retry_payload_candidate
                if retry_all_validated:
                    combined_retry_rows: list[dict[str, Any]] = []
                    for retry_shard in retry_shards:
                        retry_payload_candidate = (
                            retry_results_by_shard_id.get(retry_shard.shard_id) or {}
                        )
                        chunk_rows = retry_payload_candidate.get("r")
                        if isinstance(chunk_rows, list):
                            combined_retry_rows.extend(
                                dict(row) for row in chunk_rows if isinstance(row, Mapping)
                            )
                    combined_retry_payload = {
                        "v": "2",
                        "bid": shard.shard_id,
                        "r": combined_retry_rows,
                    }
                    (
                        payload,
                        validation_errors,
                        validation_metadata,
                        proposal_status,
                    ) = _evaluate_knowledge_response(
                        shard=shard,
                        response_text=json.dumps(combined_retry_payload, sort_keys=True),
                    )
                    if proposal_status == "validated":
                        retry_status = "recovered"
                    else:
                        retry_status = "failed"
                        retry_failure_rows.append(
                            {
                                "shard_id": shard.shard_id,
                                "proposal_status": proposal_status,
                                "validation_errors": list(validation_errors),
                                "validation_metadata": dict(validation_metadata or {}),
                            }
                        )
                else:
                    retry_status = "failed"
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "retry_failures": retry_failure_rows,
                    }

            repair_attempted = False
            repair_status = "not_attempted"
            repair_mode: str | None = None
            repair_skip_reason_code: str | None = None
            repair_skip_reason_detail: str | None = None
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and proposal_status == "invalid"
            ):
                snippet_repair_applicable = _should_attempt_knowledge_snippet_repair(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                )
                current_failure_signature = _knowledge_failure_signature(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    run_result=active_run_result,
                )
                repair_followup_decision = recovery_governor.allow_followup(
                    kind="repair",
                    worker_id=assignment.worker_id,
                    failure_signature=current_failure_signature,
                    near_miss=_is_knowledge_near_miss(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                    ),
                )
                if not repair_followup_decision.allowed:
                    repair_status = "skipped"
                    repair_skip_reason_code = repair_followup_decision.reason_code
                    repair_skip_reason_detail = repair_followup_decision.reason_detail
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "repair_skip_reason_code": repair_skip_reason_code,
                        "repair_skip_reason_detail": repair_skip_reason_detail,
                    }
                else:
                    repair_attempted = True
                    repair_mode = "snippet_only" if snippet_repair_applicable else "general"
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=shard.shard_id,
                                attempt_label="repair",
                            ),
                            followup_kind="repair",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=shard.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="repair",
                        )
                    try:
                        if snippet_repair_applicable:
                            repair_run_result = _run_knowledge_snippet_repair_attempt(
                                runner=runner,
                                worker_root=worker_root,
                                shard=shard,
                                env=env,
                                output_schema_path=output_schema_path,
                                model=model,
                                reasoning_effort=reasoning_effort,
                                original_response_text=active_response_text,
                                validation_errors=validation_errors,
                                validation_metadata=validation_metadata,
                                live_status_path=shard_root / "repair_live_status.json",
                            )
                        else:
                            repair_run_result = _run_knowledge_repair_attempt(
                                runner=runner,
                                worker_root=worker_root,
                                shard=shard,
                                env=env,
                                output_schema_path=output_schema_path,
                                model=model,
                                reasoning_effort=reasoning_effort,
                                original_response_text=active_response_text,
                                validation_errors=validation_errors,
                                validation_metadata=validation_metadata,
                                live_status_path=shard_root / "repair_live_status.json",
                            )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="repair",
                            )
                    _finalize_live_status(
                        shard_root / "repair_live_status.json",
                        run_result=repair_run_result,
                    )
                    repair_payload = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=shard.shard_id,
                        run_result=repair_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode=(
                            "inline_snippet_repair"
                            if snippet_repair_applicable
                            else "inline_repair"
                        ),
                    )
                    worker_runner_results.append(dict(repair_payload))
                    repair_runner_rows = (
                        repair_payload.get("telemetry", {}).get("rows")
                        if isinstance(repair_payload.get("telemetry"), dict)
                        else None
                    )
                    repair_row = None
                    if isinstance(repair_runner_rows, list):
                        for row_payload in repair_runner_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["is_repair_attempt"] = True
                            row_payload["repair_attempt_index"] = 1
                            repair_row = dict(row_payload)
                            stage_rows.append(repair_row)
                    (shard_root / "repair_events.jsonl").write_text(
                        _render_events_jsonl(repair_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json(
                        {"text": repair_run_result.response_text},
                        shard_root / "repair_last_message.json",
                    )
                    _write_json(
                        dict(repair_run_result.usage or {}),
                        shard_root / "repair_usage.json",
                    )
                    _write_json(
                        repair_run_result.workspace_manifest(),
                        shard_root / "repair_workspace_manifest.json",
                    )
                    repair_payload_candidate, repair_errors, repair_metadata, repair_proposal_status = (
                        _evaluate_knowledge_response(
                            shard=shard,
                            response_text=repair_run_result.response_text,
                        )
                    )
                    repair_status = (
                        "repaired" if repair_proposal_status == "validated" else "failed"
                    )
                    recovery_governor.record_followup_outcome(
                        kind="repair",
                        failure_signature=current_failure_signature,
                        recovered=repair_proposal_status == "validated",
                    )
                    if repair_row is not None:
                        repair_row["proposal_status"] = repair_proposal_status
                        repair_row["repair_attempted"] = True
                        repair_row["repair_status"] = repair_status
                    if isinstance(repair_runner_rows, list) and repair_runner_rows:
                        repair_runner_row = repair_runner_rows[0]
                        if isinstance(repair_runner_row, dict):
                            repair_runner_row["proposal_status"] = repair_proposal_status
                            repair_runner_row["repair_attempted"] = True
                            repair_runner_row["repair_status"] = repair_status
                    _write_json(
                        {
                            "attempted": True,
                            "status": repair_status,
                            "repair_mode": repair_mode,
                            "original_validation_errors": list(validation_errors),
                            "repair_validation_errors": list(repair_errors),
                            "state": repair_run_result.supervision_state or "completed",
                            "reason_code": repair_run_result.supervision_reason_code,
                            "reason_detail": repair_run_result.supervision_reason_detail,
                            "retryable": repair_run_result.supervision_retryable,
                        },
                        shard_root / "repair_status.json",
                    )
                    if repair_proposal_status == "validated":
                        payload = repair_payload_candidate
                        validation_errors = repair_errors
                        validation_metadata = dict(repair_metadata or {})
                        proposal_status = "validated"
                        final_success_run_result = repair_run_result
                    else:
                        validation_metadata = {
                            **dict(validation_metadata or {}),
                            "repair_validation_errors": list(repair_errors),
                        }
            if primary_row is not None:
                primary_row["proposal_status"] = (
                    initial_proposal_status
                    if watchdog_retry_attempted or retry_attempted or repair_attempted
                    else proposal_status
                )
                primary_row["final_proposal_status"] = proposal_status
                primary_row["watchdog_retry_attempted"] = watchdog_retry_attempted
                primary_row["watchdog_retry_status"] = watchdog_retry_status
                primary_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
                primary_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
                primary_row["retry_attempted"] = retry_attempted
                primary_row["retry_status"] = retry_status
                primary_row["retry_child_shard_ids"] = list(retry_child_shard_ids)
                primary_row["repair_attempted"] = repair_attempted
                primary_row["repair_status"] = repair_status
                primary_row["repair_mode"] = repair_mode
                primary_row["repair_skip_reason_code"] = repair_skip_reason_code
                primary_row["repair_skip_reason_detail"] = repair_skip_reason_detail
            if primary_runner_row is not None:
                primary_runner_row["proposal_status"] = (
                    initial_proposal_status
                    if watchdog_retry_attempted or retry_attempted or repair_attempted
                    else proposal_status
                )
                primary_runner_row["final_proposal_status"] = proposal_status
                primary_runner_row["watchdog_retry_attempted"] = watchdog_retry_attempted
                primary_runner_row["watchdog_retry_status"] = watchdog_retry_status
                primary_runner_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
                primary_runner_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
                primary_runner_row["retry_attempted"] = retry_attempted
                primary_runner_row["retry_status"] = retry_status
                primary_runner_row["retry_child_shard_ids"] = list(retry_child_shard_ids)
                primary_runner_row["repair_attempted"] = repair_attempted
                primary_runner_row["repair_status"] = repair_status
                primary_runner_row["repair_mode"] = repair_mode
                primary_runner_row["repair_skip_reason_code"] = repair_skip_reason_code
                primary_runner_row["repair_skip_reason_detail"] = repair_skip_reason_detail
            proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
            _write_json(
                {
                    "shard_id": shard.shard_id,
                    "worker_id": assignment.worker_id,
                    "payload": payload,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    "retry_attempted": retry_attempted,
                    "retry_status": retry_status,
                    "retry_child_shard_ids": list(retry_child_shard_ids),
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "repair_mode": repair_mode,
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                },
                proposal_path,
            )
            _write_json(
                payload
                if payload is not None
                else {
                    "error": proposal_status,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                },
                shard_root / "proposal.json",
            )
            _write_json(
                {
                    "status": proposal_status,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    "retry_attempted": retry_attempted,
                    "retry_status": retry_status,
                    "retry_child_shard_ids": list(retry_child_shard_ids),
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                    "state": run_result.supervision_state or "completed",
                    "reason_code": run_result.supervision_reason_code,
                    "reason_detail": run_result.supervision_reason_detail,
                    "retryable": run_result.supervision_retryable,
                },
                shard_root / "status.json",
            )
            if task_status_tracker is not None:
                task_status_tracker.mark_terminal(
                    task_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    terminal_state=_terminal_knowledge_task_state(
                        proposal_status=proposal_status,
                        supervision_state=run_result.supervision_state,
                        watchdog_retry_status=watchdog_retry_status,
                        retry_status=retry_status,
                        repair_status=repair_status,
                    ),
                    attempt_type=_terminal_knowledge_attempt_type(
                        watchdog_retry_status=watchdog_retry_status,
                        retry_status=retry_status,
                        repair_status=repair_status,
                    ),
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    metadata={
                        "watchdog_retry_status": watchdog_retry_status,
                        "retry_status": retry_status,
                        "repair_status": repair_status,
                    },
                    terminal_reason_code=_terminal_reason_for_knowledge_task(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                        run_result=active_run_result,
                        retry_skip_reason_code=watchdog_retry_skip_reason_code,
                        retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                        repair_skip_reason_code=repair_skip_reason_code,
                        repair_skip_reason_detail=repair_skip_reason_detail,
                    )[0],
                    terminal_reason_detail=_terminal_reason_for_knowledge_task(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                        run_result=active_run_result,
                        retry_skip_reason_code=watchdog_retry_skip_reason_code,
                        retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                        repair_skip_reason_code=repair_skip_reason_code,
                        repair_skip_reason_detail=repair_skip_reason_detail,
                    )[1],
                )
            _finalize_terminal_followups_for_task_root(
                shard_root,
                terminal_reason_code="superseded_by_terminal_packet",
                terminal_reason_detail="packet reached a terminal state before older follow-up work could finish",
            )
            if proposal_status != "validated":
                worker_failure_count += 1
                worker_failures.append(
                    {
                        "worker_id": assignment.worker_id,
                        "shard_id": shard.shard_id,
                        "reason": _failure_reason_from_run_result(
                            run_result=run_result,
                            proposal_status=proposal_status,
                        ),
                        "validation_errors": list(validation_errors),
                        "state": run_result.supervision_state or "completed",
                        "reason_code": run_result.supervision_reason_code,
                    }
                )
            else:
                worker_proposal_count += 1
            worker_proposals.append(
                ShardProposalV1(
                    shard_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    status=proposal_status,
                    proposal_path=_relative_path(run_root, proposal_path),
                    payload=payload,
                    validation_errors=validation_errors,
                    metadata={
                        **dict(validation_metadata or {}),
                        "watchdog_retry_attempted": watchdog_retry_attempted,
                        "watchdog_retry_status": watchdog_retry_status,
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                        "retry_attempted": retry_attempted,
                        "retry_status": retry_status,
                        "retry_child_shard_ids": list(retry_child_shard_ids),
                        "repair_attempted": repair_attempted,
                        "repair_status": repair_status,
                        "repair_skip_reason_code": repair_skip_reason_code,
                        "repair_skip_reason_detail": repair_skip_reason_detail,
                    },
                )
            )
            if progress_state is not None:
                progress_state.mark_task_packet_terminal(
                    worker_id=assignment.worker_id,
                    task_id=shard.shard_id,
                )
            if shard_completed_callback is not None:
                shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)
            if proposal_status == "validated":
                cohort_watchdog_state.record_validated_result(
                    duration_ms=final_success_run_result.duration_ms,
                    example_payload=_build_knowledge_watchdog_example(
                        shard=shard,
                        payload=payload,
                    ),
                )

    worker_runner_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
    )
    _write_json(worker_runner_payload, worker_root / "status.json")
    return _DirectKnowledgeWorkerResult(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_path(run_root, worker_root),
            status="ok" if worker_failure_count == 0 else "partial_failure",
            proposal_count=worker_proposal_count,
            failure_count=worker_failure_count,
            runtime_mode_audit={
                "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "status": "ok",
                "output_schema_enforced": False,
                "tool_affordances_requested": True,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_path(run_root, in_dir),
                "hints_dir": _relative_path(run_root, hints_dir),
                "out_dir": _relative_path(run_root, out_dir),
                "scratch_dir": _relative_path(
                    run_root,
                    worker_root / _KNOWLEDGE_SCRATCH_DIR_NAME,
                ),
                "shards_dir": _relative_path(run_root, shard_dir),
                "log_dir": _relative_path(run_root, logs_dir),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )


def _run_knowledge_workspace_worker_assignment_taskized_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    assigned_shards: Sequence[ShardManifestEntryV1],
    task_plans_by_shard_id: Mapping[str, tuple[_KnowledgeTaskPlan, ...]],
    worker_root: Path,
    in_dir: Path,
    hints_dir: Path,
    shard_dir: Path,
    logs_dir: Path,
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    recovery_governor: _KnowledgeRecoveryGovernor,
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
    interruption_requested: threading.Event | None,
) -> _DirectKnowledgeWorkerResult:
    out_dir = worker_root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    runnable_shards: list[ShardManifestEntryV1] = []
    runnable_tasks: list[_KnowledgeTaskPlan] = []

    for shard in assigned_shards:
        shard_root = shard_dir / shard.shard_id
        shard_root.mkdir(parents=True, exist_ok=True)
        preflight_failure = _preflight_knowledge_shard(shard)
        if preflight_failure is None:
            task_plans = task_plans_by_shard_id.get(shard.shard_id, ())
            if task_plans:
                runnable_shards.append(shard)
                runnable_tasks.extend(task_plans)
            continue
        preflight_result = _build_preflight_rejected_run_result(
            prompt_text="knowledge worker preflight rejected",
            output_schema_path=output_schema_path,
            working_dir=worker_root,
            reason_code=str(preflight_failure.get("reason_code") or "preflight_rejected"),
            reason_detail=str(preflight_failure.get("reason_detail") or "knowledge shard failed preflight"),
        )
        _write_live_status(
            shard_root / "live_status.json",
            {
                "state": "preflight_rejected",
                "reason_code": preflight_result.supervision_reason_code,
                "reason_detail": preflight_result.supervision_reason_detail,
                "retryable": preflight_result.supervision_retryable,
                "watchdog_policy": "workspace_worker_v1",
                "elapsed_seconds": 0.0,
                "last_event_seconds_ago": None,
                "command_execution_count": 0,
                "reasoning_item_count": 0,
            },
        )
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": None,
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "retry_child_shard_ids": [],
                "repair_attempted": False,
                "repair_status": "not_attempted",
            },
            proposal_path,
        )
        _write_json(
            {
                "status": "missing_output",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "validation_metadata": {},
                "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "watchdog_retry_attempted": False,
                "watchdog_retry_status": "not_attempted",
                "retry_attempted": False,
                "retry_status": "not_attempted",
                "retry_child_shard_ids": [],
                "repair_attempted": False,
                "repair_status": "not_attempted",
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
                "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                "retryable": False,
            },
            shard_root / "status.json",
        )
        worker_failure_count += 1
        worker_failures.append(
            {
                "worker_id": assignment.worker_id,
                "shard_id": shard.shard_id,
                "reason": "preflight_rejected",
                "validation_errors": [str(preflight_failure.get("reason_code") or "preflight_rejected")],
                "state": "preflight_rejected",
                "reason_code": str(preflight_failure.get("reason_code") or "preflight_rejected"),
            }
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status="missing_output",
                proposal_path=_relative_path(run_root, proposal_path),
                payload=None,
                validation_errors=(str(preflight_failure.get("reason_code") or "preflight_rejected"),),
                metadata={
                    "watchdog_retry_attempted": False,
                    "watchdog_retry_status": "not_attempted",
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "repair_attempted": False,
                    "repair_status": "not_attempted",
                },
            )
        )
        if task_status_tracker is not None:
            for task_id in _progress_task_ids_for_knowledge_shard(
                shard_id=shard.shard_id,
                task_plans_by_shard_id=task_plans_by_shard_id,
            ):
                task_status_tracker.mark_terminal(
                    task_id=task_id,
                    worker_id=assignment.worker_id,
                    terminal_state="preflight_rejected",
                    attempt_type="preflight",
                    proposal_status="missing_output",
                    validation_errors=(str(preflight_failure.get("reason_code") or "preflight_rejected"),),
                    metadata={
                        "reason_detail": str(preflight_failure.get("reason_detail") or ""),
                    },
                )
        if progress_state is not None:
            progress_state.mark_task_packets_terminal(
                worker_id=assignment.worker_id,
                task_ids=_progress_task_ids_for_knowledge_shard(
                    shard_id=shard.shard_id,
                    task_plans_by_shard_id=task_plans_by_shard_id,
                ),
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    workspace_task_entries = _build_knowledge_workspace_task_runtime_entries(runnable_tasks)
    inventory_task_rows = [
        build_workspace_inventory_task_row(asdict(task_entry))
        for task_entry in workspace_task_entries
    ]
    _write_json(
        inventory_task_rows,
        worker_root / "assigned_tasks.json",
    )
    (worker_root / _KNOWLEDGE_SCRATCH_DIR_NAME).mkdir(parents=True, exist_ok=True)
    write_knowledge_workspace_sidecars(
        worker_root=worker_root,
        tasks=[asdict(task_entry) for task_entry in workspace_task_entries],
    )
    for task in runnable_tasks:
        task_manifest = task.manifest_entry
        _write_worker_input(
            in_dir / f"{task_manifest.shard_id}.json",
            payload=task_manifest.input_payload,
            input_text=task_manifest.input_text,
        )
        _write_knowledge_worker_hint(
            path=hints_dir / f"{task_manifest.shard_id}.md",
            shard=task_manifest,
        )

    task_queue_controller = _KnowledgeWorkspaceTaskQueueController(
        worker_root=worker_root,
        task_entries=tuple(workspace_task_entries),
        worker_id=assignment.worker_id,
        task_status_tracker=task_status_tracker,
    )

    if runnable_shards and runnable_tasks:
        worker_prompt_text = _build_knowledge_workspace_worker_prompt(
            tasks=workspace_task_entries
        )
        worker_prompt_path = worker_root / "prompt.txt"
        worker_prompt_path.write_text(worker_prompt_text, encoding="utf-8")
        worker_live_status_path = worker_root / "live_status.json"
        shard_live_status_paths = [
            shard_dir / shard.shard_id / "live_status.json" for shard in runnable_shards
        ]
        for shard in runnable_shards:
            (shard_dir / shard.shard_id / "prompt.txt").write_text(worker_prompt_text, encoding="utf-8")
        if task_status_tracker is not None:
            for task_entry in workspace_task_entries:
                task_metadata = dict(task_entry.metadata or {})
                task_status_tracker.start_attempt(
                    task_id=task_entry.task_id,
                    worker_id=assignment.worker_id,
                    attempt_type="main_worker",
                    metadata={
                        "lease_sequence": int(task_metadata.get("lease_sequence") or 0),
                        "lease_total": int(task_metadata.get("lease_total") or len(workspace_task_entries)),
                        "input_path": task_metadata.get("input_path"),
                        "hint_path": task_metadata.get("hint_path"),
                        "result_path": task_metadata.get("result_path"),
                        "workspace_processing_contract": task_metadata.get(
                            "workspace_processing_contract"
                        ),
                    },
                )
        workspace_session_results: list[CodexExecRunResult] = []
        workspace_relaunch_count = 0
        workspace_relaunch_history: list[dict[str, Any]] = []
        cap_reached_payload: dict[str, Any] | None = None
        while True:
            current_task_id_before_run = task_queue_controller.current_task_id()
            validated_task_count_before_run = task_queue_controller.validated_task_count
            session_result = runner.run_workspace_worker(
                prompt_text=worker_prompt_text,
                working_dir=worker_root,
                env=env,
                model=model,
                reasoning_effort=reasoning_effort,
                workspace_task_label="knowledge worker session",
                supervision_callback=_runtime_attr(
                    "_build_strict_json_watchdog_callback",
                    _build_strict_json_watchdog_callback,
                )(
                live_status_path=worker_live_status_path,
                live_status_paths=shard_live_status_paths,
                cohort_watchdog_state=cohort_watchdog_state,
                watchdog_policy="workspace_worker_v1",
                allow_workspace_commands=True,
                execution_workspace_root=worker_root,
                forbid_inline_python_heredocs=False,
                expected_workspace_output_paths=[
                    out_dir / f"{task.task_id}.json" for task in runnable_tasks
                ],
                task_queue_controller=task_queue_controller,
                workspace_output_observer=(
                        None
                        if progress_state is None
                        else lambda present_count, expected_count, _worker_id=assignment.worker_id: (
                            progress_state.observe_workspace_outputs(
                                worker_id=_worker_id,
                                present_count=present_count,
                                expected_count=expected_count,
                            )
                        )
                    ),
                ),
            )
            workspace_session_results.append(session_result)
            relaunch_payload = _detect_knowledge_workspace_premature_clean_exit(
                run_result=session_result,
                task_queue_controller=task_queue_controller,
                current_task_id_before_run=current_task_id_before_run,
                validated_task_count_before_run=validated_task_count_before_run,
            )
            if relaunch_payload is None:
                break
            if workspace_relaunch_count >= _runtime_attr(
                "_KNOWLEDGE_WORKSPACE_PREMATURE_EXIT_MAX_RELAUNCHES",
                _KNOWLEDGE_WORKSPACE_PREMATURE_EXIT_MAX_RELAUNCHES,
            ):
                cap_reached_payload = _build_knowledge_workspace_relaunch_cap_reached_payload(
                    premature_clean_exit_payload=relaunch_payload,
                    task_queue_controller=task_queue_controller,
                )
                break
            workspace_relaunch_count += 1
            workspace_relaunch_history.append(
                _knowledge_workspace_relaunch_history_entry(relaunch_payload)
            )
            relaunch_status_metadata = _knowledge_workspace_relaunch_metadata(
                workspace_relaunch_history,
            )
            _write_live_status(
                worker_live_status_path,
                {
                    **relaunch_payload,
                    **relaunch_status_metadata,
                },
            )
            for live_status_path in shard_live_status_paths:
                _write_live_status(
                    live_status_path,
                    {
                        **relaunch_payload,
                        **relaunch_status_metadata,
                    },
                )
        run_result = _combine_workspace_worker_run_results(workspace_session_results)
        _finalize_live_status(
            worker_live_status_path,
            run_result=run_result,
            watchdog_policy="workspace_worker_v1",
        )
        for live_status_path in shard_live_status_paths:
            _finalize_live_status(
                live_status_path,
                run_result=run_result,
                watchdog_policy="workspace_worker_v1",
            )
        relaunch_status_metadata = _knowledge_workspace_relaunch_metadata(
            workspace_relaunch_history,
            cap_reached=cap_reached_payload is not None,
        )
        if relaunch_status_metadata["workspace_relaunch_count"] > 0:
            _merge_live_status_metadata(
                worker_live_status_path,
                payload=relaunch_status_metadata,
            )
            for live_status_path in shard_live_status_paths:
                _merge_live_status_metadata(
                    live_status_path,
                    payload=relaunch_status_metadata,
                )
        if str(run_result.supervision_state or "completed").strip() == "completed" and task_queue_controller.is_complete():
            completed_payload = {
                "state": "completed",
                "reason_code": "workspace_validated_task_queue_completed",
                "reason_detail": (
                    "knowledge workspace worker produced repo-validated outputs for "
                    "every assigned current task"
                ),
                "retryable": False,
                "watchdog_policy": "workspace_worker_v1",
                "workspace_relaunch_count": workspace_relaunch_count,
                **relaunch_status_metadata,
                **task_queue_controller.status_payload(),
            }
            _write_live_status(worker_live_status_path, completed_payload)
            for live_status_path in shard_live_status_paths:
                _write_live_status(live_status_path, completed_payload)
        elif (
            str(run_result.supervision_state or "completed").strip() == "completed"
            and cap_reached_payload is not None
        ):
            capped_payload = {
                **cap_reached_payload,
                **relaunch_status_metadata,
                **task_queue_controller.status_payload(),
            }
            _write_live_status(worker_live_status_path, capped_payload)
            for live_status_path in shard_live_status_paths:
                _write_live_status(live_status_path, capped_payload)
        elif str(run_result.supervision_state or "completed").strip() == "completed":
            incomplete_reason_detail = (
                "knowledge workspace worker exited before every current task "
                "was individually validated by the repo-owned checker"
            )
            incomplete_payload = {
                "state": "completed_with_failures",
                "reason_code": "workspace_validated_task_queue_incomplete",
                "reason_detail": incomplete_reason_detail,
                "retryable": True,
                "watchdog_policy": "workspace_worker_v1",
                "workspace_relaunch_count": workspace_relaunch_count,
                **relaunch_status_metadata,
                **task_queue_controller.status_payload(),
            }
            _write_live_status(worker_live_status_path, incomplete_payload)
            for live_status_path in shard_live_status_paths:
                _write_live_status(live_status_path, incomplete_payload)
        (worker_root / "events.jsonl").write_text(
            _render_events_jsonl(run_result.events),
            encoding="utf-8",
        )
        _write_json({"text": run_result.response_text}, worker_root / "last_message.json")
        _write_json(dict(run_result.usage or {}), worker_root / "usage.json")
        _write_json(run_result.workspace_manifest(), worker_root / "workspace_manifest.json")
        _write_optional_text(worker_root / "stdout.txt", run_result.stdout_text)
        _write_optional_text(worker_root / "stderr.txt", run_result.stderr_text)
        if task_status_tracker is not None:
            for task_entry in workspace_task_entries:
                task_metadata = dict(task_entry.metadata or {})
                result_path = str(task_metadata.get("result_path") or "").strip()
                if not result_path:
                    continue
                output_path = worker_root / result_path
                if output_path.exists():
                    task_status_tracker.mark_main_output_written(
                        task_id=task_entry.task_id,
                        metadata={
                            "leased_packet_result_path": result_path,
                        },
                    )

        task_count = len(runnable_tasks)
        task_payloads_by_shard_id: dict[str, dict[str, dict[str, Any]]] = {}
        task_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
        task_watchdog_retry_status_by_shard_id: dict[str, dict[str, str]] = {}
        task_watchdog_retry_skip_reason_by_shard_id: dict[str, dict[str, str]] = {}
        task_repair_status_by_shard_id: dict[str, dict[str, str]] = {}
        task_repair_mode_by_shard_id: dict[str, dict[str, str]] = {}
        task_repair_skip_reason_by_shard_id: dict[str, dict[str, str]] = {}
        task_repair_validation_errors_by_shard_id: dict[str, dict[str, tuple[str, ...]]] = {}
        for task_index, task in enumerate(runnable_tasks):
            task_manifest = task.manifest_entry
            parent_shard_id = task.parent_shard_id
            task_root = shard_dir / task_manifest.shard_id
            task_root.mkdir(parents=True, exist_ok=True)
            input_path = in_dir / f"{task_manifest.shard_id}.json"
            output_path = out_dir / f"{task_manifest.shard_id}.json"
            response_text = output_path.read_text(encoding="utf-8") if output_path.exists() else None
            runner_payload = _build_knowledge_workspace_task_runner_payload(
                pipeline_id=pipeline_id,
                worker_id=assignment.worker_id,
                shard_id=parent_shard_id,
                runtime_task_id=task_manifest.shard_id,
                run_result=run_result,
                model=model,
                reasoning_effort=reasoning_effort,
                request_input_file=input_path,
                worker_prompt_path=worker_prompt_path,
                task_count=task_count,
                task_index=task_index,
            )
            worker_runner_results.append(dict(runner_payload))
            telemetry = runner_payload.get("telemetry")
            row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
            if isinstance(row_payloads, list):
                for row_payload in row_payloads:
                    if isinstance(row_payload, dict):
                        stage_rows.append(dict(row_payload))
            primary_row = stage_rows[-1] if stage_rows else None
            primary_runner_row = (
                row_payloads[0]
                if isinstance(row_payloads, list)
                and row_payloads
                and isinstance(row_payloads[0], dict)
                else None
            )
            if interruption_requested is not None and interruption_requested.is_set():
                break
            payload, validation_errors, validation_metadata, proposal_status = _evaluate_knowledge_response(
                shard=task_manifest,
                response_text=response_text,
            )
            initial_proposal_status = proposal_status
            active_response_text = response_text
            main_failure_signature = _knowledge_failure_signature(
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                run_result=run_result,
            )
            if proposal_status != "validated":
                poisoned_worker_reason = recovery_governor.observe_main_failure(
                    worker_id=assignment.worker_id,
                    failure_signature=main_failure_signature,
                )
                if poisoned_worker_reason is not None:
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "poisoned_worker_reason_code": poisoned_worker_reason["reason_code"],
                        "poisoned_worker_reason_detail": poisoned_worker_reason["reason_detail"],
                    }
            watchdog_retry_attempted = False
            watchdog_retry_status = "not_attempted"
            watchdog_retry_skip_reason_code: str | None = None
            watchdog_retry_skip_reason_detail: str | None = None
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and _should_attempt_knowledge_watchdog_retry(run_result=run_result)
            ):
                retry_followup_decision = recovery_governor.allow_followup(
                    kind="retry",
                    worker_id=assignment.worker_id,
                    failure_signature=main_failure_signature,
                )
                if not retry_followup_decision.allowed:
                    watchdog_retry_status = "skipped"
                    watchdog_retry_skip_reason_code = retry_followup_decision.reason_code
                    watchdog_retry_skip_reason_detail = retry_followup_decision.reason_detail
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    }
                else:
                    watchdog_retry_attempted = True
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=parent_shard_id,
                                attempt_label="watchdog retry",
                                task_id=task_manifest.shard_id,
                            ),
                            followup_kind="retry",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=task_manifest.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="watchdog_retry",
                        )
                    try:
                        watchdog_retry_run_result = _run_knowledge_watchdog_retry_attempt(
                            runner=runner,
                            worker_root=worker_root,
                            shard=task_manifest,
                            env=env,
                            output_schema_path=output_schema_path,
                            model=model,
                            reasoning_effort=reasoning_effort,
                            reason_code=str(run_result.supervision_reason_code or ""),
                            reason_detail=str(run_result.supervision_reason_detail or ""),
                            successful_examples=cohort_watchdog_state.snapshot().get("successful_examples") or [],
                            live_status_path=task_root / "watchdog_retry" / "live_status.json",
                        )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="retry",
                            )
                    retry_root = task_root / "watchdog_retry"
                    _finalize_live_status(
                        retry_root / "live_status.json",
                        run_result=watchdog_retry_run_result,
                    )
                    retry_payload_wrapper = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=parent_shard_id,
                        run_result=watchdog_retry_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode="inline_watchdog_retry",
                    )
                    retry_payload_wrapper["process_payload"]["runtime_task_id"] = task_manifest.shard_id
                    retry_payload_wrapper["process_payload"]["runtime_parent_shard_id"] = parent_shard_id
                    worker_runner_results.append(dict(retry_payload_wrapper))
                    retry_rows = (
                        retry_payload_wrapper.get("telemetry", {}).get("rows")
                        if isinstance(retry_payload_wrapper.get("telemetry"), dict)
                        else None
                    )
                    if isinstance(retry_rows, list):
                        for row_payload in retry_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["watchdog_retry_attempted"] = True
                            row_payload["runtime_task_id"] = task_manifest.shard_id
                            row_payload["runtime_parent_shard_id"] = parent_shard_id
                            stage_rows.append(dict(row_payload))
                    (retry_root / "events.jsonl").write_text(
                        _render_events_jsonl(watchdog_retry_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json({"text": watchdog_retry_run_result.response_text}, retry_root / "last_message.json")
                    _write_json(dict(watchdog_retry_run_result.usage or {}), retry_root / "usage.json")
                    _write_json(watchdog_retry_run_result.workspace_manifest(), retry_root / "workspace_manifest.json")
                    payload, validation_errors, validation_metadata, proposal_status = _evaluate_knowledge_response(
                        shard=task_manifest,
                        response_text=watchdog_retry_run_result.response_text,
                    )
                    watchdog_retry_status = "recovered" if proposal_status == "validated" else "failed"
                    recovery_governor.record_followup_outcome(
                        kind="retry",
                        failure_signature=main_failure_signature,
                        recovered=proposal_status == "validated",
                    )
                    _write_json(
                        {
                            "status": proposal_status,
                            "watchdog_retry_reason_code": run_result.supervision_reason_code,
                            "validation_errors": list(validation_errors),
                            "validation_metadata": dict(validation_metadata or {}),
                        },
                        retry_root / "status.json",
                    )
                    active_response_text = watchdog_retry_run_result.response_text
                    task_watchdog_retry_status_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = watchdog_retry_status
                if watchdog_retry_skip_reason_code:
                    task_watchdog_retry_skip_reason_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = watchdog_retry_skip_reason_code

            repair_attempted = False
            repair_status = "not_attempted"
            repair_mode: str | None = None
            repair_skip_reason_code: str | None = None
            repair_skip_reason_detail: str | None = None
            if (
                (interruption_requested is None or not interruption_requested.is_set())
                and proposal_status == "invalid"
            ):
                snippet_repair_applicable = _should_attempt_knowledge_snippet_repair(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                )
                current_failure_signature = _knowledge_failure_signature(
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                    run_result=run_result,
                )
                repair_followup_decision = recovery_governor.allow_followup(
                    kind="repair",
                    worker_id=assignment.worker_id,
                    failure_signature=current_failure_signature,
                    near_miss=_is_knowledge_near_miss(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                    ),
                )
                if not repair_followup_decision.allowed:
                    repair_status = "skipped"
                    repair_skip_reason_code = repair_followup_decision.reason_code
                    repair_skip_reason_detail = repair_followup_decision.reason_detail
                    validation_metadata = {
                        **dict(validation_metadata or {}),
                        "repair_skip_reason_code": repair_skip_reason_code,
                        "repair_skip_reason_detail": repair_skip_reason_detail,
                    }
                else:
                    repair_attempted = True
                    repair_mode = "snippet_only" if snippet_repair_applicable else "general"
                    if progress_state is not None:
                        progress_state.begin_followup(
                            worker_id=assignment.worker_id,
                            label=_format_knowledge_followup_label(
                                parent_shard_id=parent_shard_id,
                                attempt_label="repair",
                                task_id=task_manifest.shard_id,
                            ),
                            followup_kind="repair",
                        )
                    if task_status_tracker is not None:
                        task_status_tracker.start_attempt(
                            task_id=task_manifest.shard_id,
                            worker_id=assignment.worker_id,
                            attempt_type="repair",
                        )
                    try:
                        if snippet_repair_applicable:
                            repair_run_result = _run_knowledge_snippet_repair_attempt(
                                runner=runner,
                                worker_root=worker_root,
                                shard=task_manifest,
                                env=env,
                                output_schema_path=output_schema_path,
                                model=model,
                                reasoning_effort=reasoning_effort,
                                original_response_text=active_response_text,
                                validation_errors=validation_errors,
                                validation_metadata=validation_metadata,
                                live_status_path=task_root / "repair_live_status.json",
                            )
                        else:
                            repair_run_result = _run_knowledge_repair_attempt(
                                runner=runner,
                                worker_root=worker_root,
                                shard=task_manifest,
                                env=env,
                                output_schema_path=output_schema_path,
                                model=model,
                                reasoning_effort=reasoning_effort,
                                original_response_text=active_response_text,
                                validation_errors=validation_errors,
                                validation_metadata=validation_metadata,
                                live_status_path=task_root / "repair_live_status.json",
                            )
                    finally:
                        if progress_state is not None:
                            progress_state.end_followup(
                                worker_id=assignment.worker_id,
                                followup_kind="repair",
                            )
                    _finalize_live_status(
                        task_root / "repair_live_status.json",
                        run_result=repair_run_result,
                    )
                    repair_payload = _build_knowledge_inline_attempt_runner_payload(
                        pipeline_id=pipeline_id,
                        worker_id=assignment.worker_id,
                        shard_id=parent_shard_id,
                        run_result=repair_run_result,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        prompt_input_mode=(
                            "inline_snippet_repair"
                            if snippet_repair_applicable
                            else "inline_repair"
                        ),
                    )
                    repair_payload["process_payload"]["runtime_task_id"] = task_manifest.shard_id
                    repair_payload["process_payload"]["runtime_parent_shard_id"] = parent_shard_id
                    worker_runner_results.append(dict(repair_payload))
                    repair_runner_rows = (
                        repair_payload.get("telemetry", {}).get("rows")
                        if isinstance(repair_payload.get("telemetry"), dict)
                        else None
                    )
                    if isinstance(repair_runner_rows, list):
                        for row_payload in repair_runner_rows:
                            if not isinstance(row_payload, dict):
                                continue
                            row_payload["repair_attempted"] = True
                            row_payload["runtime_task_id"] = task_manifest.shard_id
                            row_payload["runtime_parent_shard_id"] = parent_shard_id
                            stage_rows.append(dict(row_payload))
                    (task_root / "repair_events.jsonl").write_text(
                        _render_events_jsonl(repair_run_result.events),
                        encoding="utf-8",
                    )
                    _write_json({"text": repair_run_result.response_text}, task_root / "repair_last_message.json")
                    _write_json(dict(repair_run_result.usage or {}), task_root / "repair_usage.json")
                    _write_json(repair_run_result.workspace_manifest(), task_root / "repair_workspace_manifest.json")
                    payload, repair_errors, repair_metadata, repair_proposal_status = _evaluate_knowledge_response(
                        shard=task_manifest,
                        response_text=repair_run_result.response_text,
                    )
                    repair_status = "repaired" if repair_proposal_status == "validated" else "failed"
                    recovery_governor.record_followup_outcome(
                        kind="repair",
                        failure_signature=current_failure_signature,
                        recovered=repair_proposal_status == "validated",
                    )
                    validation_errors = repair_errors
                    validation_metadata = dict(repair_metadata or {})
                    proposal_status = repair_proposal_status
                    active_response_text = repair_run_result.response_text
                    _write_json(
                        {
                            "attempted": True,
                            "status": repair_status,
                            "repair_mode": repair_mode,
                            "repair_validation_errors": list(repair_errors),
                            "state": repair_run_result.supervision_state or "completed",
                            "reason_code": repair_run_result.supervision_reason_code,
                            "reason_detail": repair_run_result.supervision_reason_detail,
                            "retryable": repair_run_result.supervision_retryable,
                        },
                        task_root / "repair_status.json",
                    )
                    task_repair_status_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = repair_status
                    if repair_mode:
                        task_repair_mode_by_shard_id.setdefault(parent_shard_id, {})[
                            task_manifest.shard_id
                        ] = repair_mode
                    task_repair_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = tuple(repair_errors if repair_status == "failed" else ())
                if repair_skip_reason_code:
                    task_repair_skip_reason_by_shard_id.setdefault(parent_shard_id, {})[
                        task_manifest.shard_id
                    ] = repair_skip_reason_code

            if primary_row is not None:
                primary_row["proposal_status"] = (
                    initial_proposal_status if watchdog_retry_attempted or repair_attempted else proposal_status
                )
                primary_row["final_proposal_status"] = proposal_status
                primary_row["watchdog_retry_attempted"] = watchdog_retry_attempted
                primary_row["watchdog_retry_status"] = watchdog_retry_status
                primary_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
                primary_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
                primary_row["repair_attempted"] = repair_attempted
                primary_row["repair_status"] = repair_status
                primary_row["repair_mode"] = repair_mode
                primary_row["repair_skip_reason_code"] = repair_skip_reason_code
                primary_row["repair_skip_reason_detail"] = repair_skip_reason_detail
            if primary_runner_row is not None:
                primary_runner_row["proposal_status"] = (
                    initial_proposal_status if watchdog_retry_attempted or repair_attempted else proposal_status
                )
                primary_runner_row["final_proposal_status"] = proposal_status
                primary_runner_row["watchdog_retry_attempted"] = watchdog_retry_attempted
                primary_runner_row["watchdog_retry_status"] = watchdog_retry_status
                primary_runner_row["watchdog_retry_skip_reason_code"] = watchdog_retry_skip_reason_code
                primary_runner_row["watchdog_retry_skip_reason_detail"] = watchdog_retry_skip_reason_detail
                primary_runner_row["repair_attempted"] = repair_attempted
                primary_runner_row["repair_status"] = repair_status
                primary_runner_row["repair_mode"] = repair_mode
                primary_runner_row["repair_skip_reason_code"] = repair_skip_reason_code
                primary_runner_row["repair_skip_reason_detail"] = repair_skip_reason_detail
            task_validation_errors_by_shard_id.setdefault(parent_shard_id, {})[
                task_manifest.shard_id
            ] = tuple(validation_errors)
            if task_status_tracker is not None:
                task_status_tracker.mark_terminal(
                    task_id=task_manifest.shard_id,
                    worker_id=assignment.worker_id,
                    terminal_state=_terminal_knowledge_task_state(
                        proposal_status=proposal_status,
                        supervision_state=run_result.supervision_state,
                        watchdog_retry_status=watchdog_retry_status,
                        repair_status=repair_status,
                    ),
                    attempt_type=_terminal_knowledge_attempt_type(
                        watchdog_retry_status=watchdog_retry_status,
                        repair_status=repair_status,
                    ),
                    proposal_status=proposal_status,
                    validation_errors=validation_errors,
                    metadata={
                        "watchdog_retry_status": watchdog_retry_status,
                        "repair_status": repair_status,
                    },
                    terminal_reason_code=_terminal_reason_for_knowledge_task(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                        run_result=run_result,
                        retry_skip_reason_code=watchdog_retry_skip_reason_code,
                        retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                        repair_skip_reason_code=repair_skip_reason_code,
                        repair_skip_reason_detail=repair_skip_reason_detail,
                    )[0],
                    terminal_reason_detail=_terminal_reason_for_knowledge_task(
                        proposal_status=proposal_status,
                        validation_errors=validation_errors,
                        validation_metadata=validation_metadata,
                        run_result=run_result,
                        retry_skip_reason_code=watchdog_retry_skip_reason_code,
                        retry_skip_reason_detail=watchdog_retry_skip_reason_detail,
                        repair_skip_reason_code=repair_skip_reason_code,
                        repair_skip_reason_detail=repair_skip_reason_detail,
                    )[1],
                )
            _finalize_terminal_followups_for_task_root(
                task_root,
                terminal_reason_code="superseded_by_terminal_packet",
                terminal_reason_detail="packet reached a terminal state before older follow-up work could finish",
            )
            if progress_state is not None:
                progress_state.mark_task_packet_terminal(
                    worker_id=assignment.worker_id,
                    task_id=task_manifest.shard_id,
                )
            if payload is not None and proposal_status == "validated":
                semantic_payload, _ = _load_knowledge_response_json_object(
                    str(active_response_text or "")
                )
                task_payloads_by_shard_id.setdefault(parent_shard_id, {})[
                    task_manifest.shard_id
                ] = semantic_payload

        for shard in runnable_shards:
            if interruption_requested is not None and interruption_requested.is_set():
                break
            shard_root = shard_dir / shard.shard_id
            task_payloads = task_payloads_by_shard_id.get(shard.shard_id, {})
            task_errors = task_validation_errors_by_shard_id.get(shard.shard_id, {})
            task_watchdog_statuses = task_watchdog_retry_status_by_shard_id.get(shard.shard_id, {})
            task_watchdog_skip_reasons = task_watchdog_retry_skip_reason_by_shard_id.get(shard.shard_id, {})
            task_repair_statuses = task_repair_status_by_shard_id.get(shard.shard_id, {})
            task_repair_modes = task_repair_mode_by_shard_id.get(shard.shard_id, {})
            task_repair_skip_reasons = task_repair_skip_reason_by_shard_id.get(shard.shard_id, {})
            task_repair_errors = task_repair_validation_errors_by_shard_id.get(shard.shard_id, {})
            payload, aggregation_metadata = _aggregate_knowledge_task_payloads(
                shard=shard,
                task_payloads_by_task_id=task_payloads,
                task_validation_errors_by_task_id=task_errors,
            )
            payload_candidate, validation_errors, validation_metadata, proposal_status = _evaluate_knowledge_response(
                shard=shard,
                response_text=json.dumps(payload, sort_keys=True),
            )
            watchdog_retry_attempted = bool(task_watchdog_statuses)
            watchdog_retry_status = (
                "recovered"
                if any(status == "recovered" for status in task_watchdog_statuses.values())
                else ("failed" if watchdog_retry_attempted else "not_attempted")
            )
            watchdog_retry_skip_reason_code = (
                sorted({reason for reason in task_watchdog_skip_reasons.values() if reason})[0]
                if task_watchdog_skip_reasons
                else None
            )
            watchdog_retry_skip_reason_detail = (
                f"task-level skip reasons: {dict(sorted(task_watchdog_skip_reasons.items()))}"
                if task_watchdog_skip_reasons
                else None
            )
            repair_attempted = any(
                str(status).strip() != "not_attempted"
                for status in task_repair_statuses.values()
            )
            repair_status = (
                "repaired"
                if any(str(status).strip() == "repaired" for status in task_repair_statuses.values())
                else ("failed" if repair_attempted else "not_attempted")
            )
            repair_skip_reason_code = (
                sorted({reason for reason in task_repair_skip_reasons.values() if reason})[0]
                if task_repair_skip_reasons
                else None
            )
            repair_mode = (
                "snippet_only"
                if any(str(mode).strip() == "snippet_only" for mode in task_repair_modes.values())
                else (
                    "general"
                    if any(str(mode).strip() == "general" for mode in task_repair_modes.values())
                    else None
                )
            )
            repair_skip_reason_detail = (
                f"task-level skip reasons: {dict(sorted(task_repair_skip_reasons.items()))}"
                if task_repair_skip_reasons
                else None
            )
            validation_metadata = {
                "task_aggregation": aggregation_metadata,
                **dict(validation_metadata or {}),
            }
            if task_watchdog_statuses:
                validation_metadata["task_watchdog_retry_status_by_task_id"] = {
                    task_id: status
                    for task_id, status in sorted(task_watchdog_statuses.items())
                }
            if task_watchdog_skip_reasons:
                validation_metadata["task_watchdog_retry_skip_reason_by_task_id"] = {
                    task_id: reason_code
                    for task_id, reason_code in sorted(task_watchdog_skip_reasons.items())
                }
            if task_repair_statuses:
                validation_metadata["task_repair_status_by_task_id"] = {
                    task_id: status
                    for task_id, status in sorted(task_repair_statuses.items())
                }
            if task_repair_modes:
                validation_metadata["task_repair_mode_by_task_id"] = {
                    task_id: mode
                    for task_id, mode in sorted(task_repair_modes.items())
                }
            if task_repair_skip_reasons:
                validation_metadata["task_repair_skip_reason_by_task_id"] = {
                    task_id: reason_code
                    for task_id, reason_code in sorted(task_repair_skip_reasons.items())
                }
            repair_validation_errors = sorted(
                {
                    str(error).strip()
                    for errors in task_repair_errors.values()
                    for error in errors
                    if str(error).strip()
                }
            )
            if repair_validation_errors:
                validation_metadata["repair_validation_errors"] = repair_validation_errors
            promotable_invalid_bundle = (
                extract_promotable_knowledge_bundle(
                    payload=payload_candidate,
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                )
                if proposal_status != "validated"
                else None
            )
            final_payload = (
                payload_candidate
                if proposal_status == "validated" or promotable_invalid_bundle is not None
                else None
            )
            proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
            _write_json(
                {
                    "shard_id": shard.shard_id,
                    "worker_id": assignment.worker_id,
                    "payload": final_payload,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "retry_child_shard_ids": [],
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "repair_mode": repair_mode,
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                },
                proposal_path,
            )
            _write_json(
                {
                    "status": proposal_status,
                    "validation_errors": list(validation_errors),
                    "validation_metadata": dict(validation_metadata or {}),
                    "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                    "watchdog_retry_attempted": watchdog_retry_attempted,
                    "watchdog_retry_status": watchdog_retry_status,
                    "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                    "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                    "retry_attempted": False,
                    "retry_status": "not_attempted",
                    "retry_child_shard_ids": [],
                    "repair_attempted": repair_attempted,
                    "repair_status": repair_status,
                    "repair_skip_reason_code": repair_skip_reason_code,
                    "repair_skip_reason_detail": repair_skip_reason_detail,
                    "state": run_result.supervision_state or "completed",
                    "reason_code": run_result.supervision_reason_code,
                    "reason_detail": run_result.supervision_reason_detail,
                    "retryable": run_result.supervision_retryable,
                },
                shard_root / "status.json",
            )
            if proposal_status != "validated":
                worker_failure_count += 1
                worker_failures.append(
                    {
                        "worker_id": assignment.worker_id,
                        "shard_id": shard.shard_id,
                        "reason": _failure_reason_from_run_result(
                            run_result=run_result,
                            proposal_status=proposal_status,
                        ),
                        "validation_errors": list(validation_errors),
                        "state": run_result.supervision_state or "completed",
                        "reason_code": run_result.supervision_reason_code,
                    }
                )
            else:
                worker_proposal_count += 1
                cohort_watchdog_state.record_validated_result(
                    duration_ms=run_result.duration_ms,
                    example_payload=_build_knowledge_watchdog_example(
                        shard=shard,
                        payload=final_payload,
                    ),
                )
            worker_proposals.append(
                ShardProposalV1(
                    shard_id=shard.shard_id,
                    worker_id=assignment.worker_id,
                    status=proposal_status,
                    proposal_path=_relative_path(run_root, proposal_path),
                    payload=final_payload,
                    validation_errors=validation_errors,
                    metadata={
                        **dict(validation_metadata or {}),
                        "watchdog_retry_attempted": watchdog_retry_attempted,
                        "watchdog_retry_status": watchdog_retry_status,
                        "watchdog_retry_skip_reason_code": watchdog_retry_skip_reason_code,
                        "watchdog_retry_skip_reason_detail": watchdog_retry_skip_reason_detail,
                        "retry_attempted": False,
                        "retry_status": "not_attempted",
                        "retry_child_shard_ids": [],
                        "repair_attempted": repair_attempted,
                        "repair_status": repair_status,
                        "repair_skip_reason_code": repair_skip_reason_code,
                        "repair_skip_reason_detail": repair_skip_reason_detail,
                    },
                )
            )
            if progress_state is not None:
                progress_state.mark_task_packets_terminal(
                    worker_id=assignment.worker_id,
                    task_ids=_progress_task_ids_for_knowledge_shard(
                        shard_id=shard.shard_id,
                        task_plans_by_shard_id=task_plans_by_shard_id,
                    ),
                )
            if shard_completed_callback is not None:
                shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    worker_runner_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
        stage_rows=stage_rows,
    )
    _write_json(worker_runner_payload, worker_root / "status.json")
    return _DirectKnowledgeWorkerResult(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_path(run_root, worker_root),
            status="ok" if worker_failure_count == 0 else "partial_failure",
            proposal_count=worker_proposal_count,
            failure_count=worker_failure_count,
            runtime_mode_audit={
                "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "status": "ok",
                "output_schema_enforced": False,
                "tool_affordances_requested": True,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_path(run_root, in_dir),
                "hints_dir": _relative_path(run_root, hints_dir),
                "out_dir": _relative_path(run_root, out_dir),
                "shards_dir": _relative_path(run_root, shard_dir),
                "log_dir": _relative_path(run_root, logs_dir),
                **relaunch_status_metadata,
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )


def _run_direct_knowledge_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    shard_by_id: Mapping[str, ShardManifestEntryV1],
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    output_schema_path: Path | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    recovery_governor: _KnowledgeRecoveryGovernor,
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
    interruption_requested: threading.Event | None,
) -> _DirectKnowledgeWorkerResult:
    worker_root = Path(assignment.workspace_root)
    in_dir = worker_root / "in"
    hints_dir = worker_root / "hints"
    shard_dir = worker_root / "shards"
    logs_dir = worker_root / "logs"
    in_dir.mkdir(parents=True, exist_ok=True)
    hints_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (worker_root / _KNOWLEDGE_SCRATCH_DIR_NAME).mkdir(parents=True, exist_ok=True)
    assigned_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]
    _write_json([asdict(shard) for shard in assigned_shards], worker_root / "assigned_shards.json")
    task_plans = tuple(
        task_plan
        for shard in assigned_shards
        for task_plan in _build_knowledge_task_plans(shard)
    )
    _write_json(
        [asdict(task_entry) for task_entry in _build_knowledge_workspace_task_runtime_entries(task_plans)],
        worker_root / "assigned_tasks.json",
    )
    return _run_knowledge_workspace_worker_assignment_v1(
        run_root=run_root,
        assignment=assignment,
        artifacts=artifacts,
        assigned_shards=assigned_shards,
        worker_root=worker_root,
        in_dir=in_dir,
        hints_dir=hints_dir,
        shard_dir=shard_dir,
        logs_dir=logs_dir,
        runner=runner,
        pipeline_id=pipeline_id,
        env=env,
        model=model,
        reasoning_effort=reasoning_effort,
        output_schema_path=output_schema_path,
        cohort_watchdog_state=cohort_watchdog_state,
        recovery_governor=recovery_governor,
        shard_completed_callback=shard_completed_callback,
        progress_state=progress_state,
        task_status_tracker=task_status_tracker,
        interruption_requested=interruption_requested,
    )




def _render_events_jsonl(events: tuple[dict[str, Any], ...]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
