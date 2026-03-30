from __future__ import annotations

from . import _shared as _shared_module
from . import planning as _planning_module
from . import promotion as _promotion_module
from . import recovery as _recovery_module
from . import workspace_run as _workspace_run_module

for _module in (
    _shared_module,
    _planning_module,
    _promotion_module,
    _recovery_module,
):
    globals().update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        }
    )


def _runtime_attr(name: str, default: Any) -> Any:
    return getattr(_shared_module, name, default)


def run_codex_farm_nonrecipe_finalize(
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
    """Optional non-recipe finalize review over non-recipe chunks via codex-farm."""
    llm_raw_dir = run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug)
    manifest_path = llm_raw_dir / KNOWLEDGE_MANIFEST_FILE_NAME

    if run_settings.llm_knowledge_pipeline.value == "off":
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report={"enabled": False, "pipeline": "off"},
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
        )

    knowledge_stage_dir = llm_raw_dir / stage_artifact_stem("nonrecipe_finalize")
    knowledge_in_dir = knowledge_stage_dir / "in"
    knowledge_in_dir.mkdir(parents=True, exist_ok=True)

    pipeline_id = _non_empty(
        run_settings.codex_farm_pipeline_knowledge,
        fallback=DEFAULT_KNOWLEDGE_PIPELINE_ID,
    )
    routing = nonrecipe_stage_result.routing
    all_nonrecipe_spans = list(nonrecipe_stage_result.seed.seed_nonrecipe_spans)
    candidate_spans = list(routing.candidate_nonrecipe_spans)
    seed_nonrecipe_span_count = len(all_nonrecipe_spans)
    candidate_nonrecipe_span_count = len(candidate_spans)
    candidate_block_count = len(routing.candidate_block_indices)
    excluded_block_count = len(routing.excluded_block_indices)
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
            candidate_nonrecipe_span_count=candidate_nonrecipe_span_count,
            candidate_block_count=candidate_block_count,
            excluded_block_count=excluded_block_count,
        )
        _write_json(llm_report, manifest_path)
        return CodexFarmNonrecipeKnowledgeReviewResult(
            llm_report=llm_report,
            llm_raw_dir=llm_raw_dir,
            manifest_path=manifest_path,
            refined_stage_result=nonrecipe_stage_result,
            write_report=None,
        )
    if not candidate_spans:
        llm_report = _build_noop_knowledge_llm_report(
            run_settings=run_settings,
            pipeline_id=pipeline_id,
            output_schema_path=None,
            manifest_path=manifest_path,
            run_root=run_root,
            knowledge_in_dir=knowledge_in_dir,
            knowledge_stage_dir=knowledge_stage_dir,
            stage_status="no_candidate_nonrecipe_spans",
            seed_nonrecipe_span_count=seed_nonrecipe_span_count,
            candidate_nonrecipe_span_count=candidate_nonrecipe_span_count,
            candidate_block_count=candidate_block_count,
            excluded_block_count=excluded_block_count,
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
        candidate_spans=candidate_spans,
        recipe_spans=recipe_spans,
        workbook_slug=workbook_slug,
        out_dir=knowledge_in_dir,
        context_blocks=run_settings.codex_farm_knowledge_context_blocks,
        prompt_target_count=run_settings.knowledge_prompt_target_count,
        input_char_budget=run_settings.knowledge_packet_input_char_budget,
        output_char_budget=run_settings.knowledge_packet_output_char_budget,
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
            stage_status="all_packets_skipped",
            seed_nonrecipe_span_count=seed_nonrecipe_span_count,
            candidate_nonrecipe_span_count=candidate_nonrecipe_span_count,
            packet_count_before_partition=build_report.packet_count_before_partition,
            candidate_block_count=candidate_block_count,
            excluded_block_count=excluded_block_count,
            skipped_packet_count=build_report.skipped_packet_count,
            skipped_packet_reason_counts=dict(build_report.skipped_packet_reason_counts),
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
            phase_key="nonrecipe_finalize",
            pipeline_id=pipeline_id,
            run_root=knowledge_stage_dir,
            shards=build_report.shard_entries,
            runner=codex_runner,
            worker_count=worker_count,
            env=env,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
            settings={
                "llm_knowledge_pipeline": run_settings.llm_knowledge_pipeline.value,
                "knowledge_prompt_target_count": run_settings.knowledge_prompt_target_count,
                "knowledge_packet_input_char_budget": run_settings.knowledge_packet_input_char_budget,
                "knowledge_packet_output_char_budget": run_settings.knowledge_packet_output_char_budget,
                "knowledge_worker_count": run_settings.knowledge_worker_count,
                "knowledge_shard_max_turns": run_settings.knowledge_shard_max_turns,
                "codex_farm_pipeline_knowledge": pipeline_id,
            },
            runtime_metadata={
                "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
                "input_mode": "nonrecipe_candidate_spans",
                "workspace_root": str(workspace_root) if workspace_root is not None else None,
                "configured_prompt_target_count": run_settings.knowledge_prompt_target_count,
                "configured_packet_input_char_budget": run_settings.knowledge_packet_input_char_budget,
                "configured_packet_output_char_budget": run_settings.knowledge_packet_output_char_budget,
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
            candidate_nonrecipe_span_count=candidate_nonrecipe_span_count,
            excluded_block_count=excluded_block_count,
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
            applied_packet_ids_by_block,
            conflicts,
            ignored_block_indices,
        ) = _collect_block_category_updates(
            outputs=outputs,
            allowed_block_indices={
                int(block_index): "candidate"
                for block_index in routing.candidate_block_indices
            },
        )
        refined_stage_result = refine_nonrecipe_stage_result(
            stage_result=nonrecipe_stage_result,
            full_blocks=full_blocks_payload,
            block_category_updates=block_category_updates,
            reviewer_categories_by_block=reviewer_categories_by_block,
            applied_packet_ids_by_block=applied_packet_ids_by_block,
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
        review_rollup["excluded_block_count"] = excluded_block_count
        authority_mode = _derive_knowledge_authority_mode(
            refined_stage_result=refined_stage_result,
            review_rollup=review_rollup,
        )
        candidate_status = _derive_knowledge_review_status(review_rollup)
        refined_report = {
            **dict(refined_stage_result.refinement_report),
            "authority_mode": authority_mode,
            "candidate_status": candidate_status,
            "reviewed_shards_with_useful_packets": review_rollup["reviewed_shards_with_useful_packets"],
            "reviewed_shards_all_other": review_rollup["reviewed_shards_all_other"],
            "partially_promoted_shard_count": review_rollup["partially_promoted_shard_count"],
            "wholly_unpromoted_invalid_shard_count": review_rollup[
                "wholly_unpromoted_invalid_shard_count"
            ],
            "unreviewed_shard_count": review_rollup["unreviewed_shard_count"],
            "unreviewed_packet_count": review_rollup["unreviewed_packet_count"],
            "unreviewed_block_count": review_rollup["unreviewed_block_count"],
        }
        refined_stage_result = replace(
            refined_stage_result,
            refinement_report=refined_report,
        )
        candidate_summary = _build_review_summary(
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
            "input_mode": "nonrecipe_candidate_spans",
            "authority_mode": authority_mode,
            "scored_effect": str(
                refined_stage_result.refinement_report.get("scored_effect")
                or "route_only"
            ),
            "output_schema_path": output_schema_path,
            "counts": {
                "seed_nonrecipe_span_count": seed_nonrecipe_span_count,
                "candidate_nonrecipe_span_count": candidate_nonrecipe_span_count,
                "packet_count_before_partition": build_report.packet_count_before_partition,
                "shards_written": build_report.shards_written,
                "packets_written": build_report.packets_written,
                "candidate_block_count": candidate_block_count,
                "excluded_block_count": excluded_block_count,
                "skipped_packet_count": build_report.skipped_packet_count,
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
                "no_final_output_shards": int(
                    promotion_report.get("no_final_output_shards") or 0
                ),
                "partially_promoted_shards": review_rollup["partially_promoted_shard_count"],
                "wholly_unpromoted_invalid_shards": review_rollup[
                    "wholly_unpromoted_invalid_shard_count"
                ],
                "promoted_packet_count": int(promotion_report.get("promoted_packet_count") or 0),
                "reviewed_shards_with_useful_packets": review_rollup["reviewed_shards_with_useful_packets"],
                "reviewed_shards_all_other": review_rollup["reviewed_shards_all_other"],
                "unreviewed_shard_count": review_rollup["unreviewed_shard_count"],
                "unreviewed_packet_count": review_rollup["unreviewed_packet_count"],
                "unreviewed_block_count": review_rollup["unreviewed_block_count"],
            },
            "timing": {"total_seconds": elapsed_seconds},
            "paths": {
                "nonrecipe_route_path": str(
                    run_root / NONRECIPE_ROUTE_FILE_NAME
                ),
                "nonrecipe_authority_path": str(
                    run_root / NONRECIPE_AUTHORITY_FILE_NAME
                ),
                "nonrecipe_finalize_status_path": str(
                    run_root / NONRECIPE_FINALIZE_STATUS_FILE_NAME
                ),
                "knowledge_in_dir": str(knowledge_in_dir),
                "knowledge_phase_dir": str(knowledge_stage_dir),
                "knowledge_groups_path": str(write_report.groups_path),
                "snippets_path": (
                    str(write_report.snippets_path)
                    if write_report.snippets_path is not None
                    else None
                ),
                "preview_path": str(write_report.preview_path),
                "manifest_path": str(manifest_path),
                **_runtime_artifact_paths(knowledge_stage_dir),
            },
            "missing_packet_ids": missing_packet_ids,
            "skipped_packet_reason_counts": dict(build_report.skipped_packet_reason_counts),
            "planning_warnings": list(build_report.planning_warnings),
            "candidate_summary": candidate_summary,
            "refinement_report": refined_report,
            "process_run": process_run_payload,
            "phase_worker_runtime": {
                "phase_key": "nonrecipe_finalize",
                "surface_pipeline": run_settings.llm_knowledge_pipeline.value,
                "configured_prompt_target_count": run_settings.knowledge_prompt_target_count,
                "configured_packet_input_char_budget": run_settings.knowledge_packet_input_char_budget,
                "configured_packet_output_char_budget": run_settings.knowledge_packet_output_char_budget,
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
                    (phase_manifest.runtime_metadata or {}).get("task_total") or 0
                )
                if phase_manifest is not None
                else 0,
                "bundle_policy": str(
                    (phase_manifest.runtime_metadata or {}).get("bundle_policy") or ""
                ).strip()
                or "shard_round_robin_phase_workers_v1",
                "worker_task_counts": dict(
                    (phase_manifest.runtime_metadata or {}).get("worker_task_counts") or {}
                )
                if phase_manifest is not None
                else {},
                "max_tasks_per_worker": int(
                    (phase_manifest.runtime_metadata or {}).get("max_tasks_per_worker")
                    or 0
                )
                if phase_manifest is not None
                else 0,
                "min_tasks_per_worker": int(
                    (phase_manifest.runtime_metadata or {}).get("min_tasks_per_worker")
                    or 0
                )
                if phase_manifest is not None
                else 0,
                "telemetry": telemetry,
                "promotion_report": promotion_report,
                "worker_reports": worker_reports,
            },
            "candidate_status": candidate_status,
            "stage_status": (
                "completed_with_failures"
                if int(promotion_report.get("invalid_shards") or 0) > 0
                or int(promotion_report.get("no_final_output_shards") or 0) > 0
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
    task_entries = [
        _build_knowledge_task_manifest_entry(shard)
        for shard in shards
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
    shard_distribution = _summarize_knowledge_shard_distribution(
        assignments=assignments,
    )
    displayed_worker_total = (
        max(0, int(progress_worker_total))
        if progress_worker_total is not None
        else worker_count
    )
    progress_state = _KnowledgePhaseProgressState(
        progress_callback=progress_callback,
        total_shards=len(runnable_shards),
        total_task_packets=max(total_shards - len(bypassed_shard_ids), 0),
        worker_total=displayed_worker_total,
        worker_order=tuple(assignment.worker_id for assignment in assignments),
        worker_states={
            assignment.worker_id: _KnowledgeWorkerProgressState(
                worker_id=assignment.worker_id,
                shard_ids=assignment.shard_ids,
                pending_shard_ids=list(assignment.shard_ids),
                total_task_packets=len(assignment.shard_ids),
            )
            for assignment in assignments
        },
    )
    progress_state.emit(force=True)
    cohort_watchdog_state = _KnowledgeCohortWatchdogState()
    interruption_requested = threading.Event()

    def _mark_shard_completed(*, worker_id: str, shard_id: str) -> None:
        progress_state.mark_shard_completed(worker_id=worker_id, shard_id=shard_id)

    runtime_metadata_payload = {
        **dict(runtime_metadata or {}),
        "task_total": total_shards,
        "deterministic_bypass_packet_total": 0,
        "llm_review_shard_total": total_shards,
        **shard_distribution,
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
                _workspace_run_module._run_phase_knowledge_worker_assignment_v1,
                run_root=run_root,
                assignment=assignment,
                artifacts=artifacts,
                shard_by_id=shard_by_id,
                runner=runner,
                pipeline_id=pipeline_id,
                env=env,
                model=model,
                reasoning_effort=reasoning_effort,
                cohort_watchdog_state=cohort_watchdog_state,
                shard_completed_callback=_mark_shard_completed,
                progress_state=progress_state,
                task_status_tracker=task_status_tracker,
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
