from __future__ import annotations

import tests.llm.test_codex_farm_knowledge_orchestrator as _base

# Reuse shared imports/helpers from the base knowledge orchestrator test module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_knowledge_orchestrator_emits_structured_progress_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("cookimport.llm.codex_exec_runner.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner._resolve_recipeimport_codex_home",
        lambda explicit_env=None: str(tmp_path / ".codex-recipe"),
    )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 2,
            "knowledge_worker_count": 4,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
            "codex_farm_knowledge_context_blocks": 1,
        }
    )

    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[
            {"index": 0, "text": "Preface"},
            {"index": 4, "text": "Technique: Whisk constantly."},
        ],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Preface"},
                        {"index": 1, "text": "Toast"},
                        {"index": 2, "text": "1 slice bread"},
                        {"index": 3, "text": "Toast the bread."},
                        {"index": 4, "text": "Technique: Whisk constantly."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    progress_messages: list[str] = []
    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.other.0.1",
                    category="other",
                    block_start_index=0,
                    block_end_index=1,
                    block_indices=[0],
                    block_ids=["b0"],
                ),
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                ),
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.4.5",
                    category="knowledge",
                    block_start_index=4,
                    block_end_index=5,
                    block_indices=[4],
                    block_ids=["b4"],
                )
            ],
            other_spans=[
                NonRecipeSpan(
                    span_id="nr.other.0.1",
                    category="other",
                    block_start_index=0,
                    block_end_index=1,
                    block_indices=[0],
                    block_ids=["b0"],
                )
            ],
            block_category_by_index={0: "other", 4: "knowledge"},
        ),
        recipe_spans=[
            RecipeSpan(
                span_id="recipe.0",
                start_block_index=1,
                end_block_index=4,
                block_indices=[1, 2, 3],
                source_block_ids=["b1", "b2", "b3"],
            )
        ],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=FakeCodexExecRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
                dict(payload or {}),
            )
        ),
        progress_callback=progress_messages.append,
    )

    payloads = [
        payload
        for message in progress_messages
        for payload in [parse_stage_progress(message)]
        if payload is not None
    ]
    assert payloads
    assert payloads[0]["stage_label"] == "non-recipe knowledge review"
    assert payloads[0]["task_current"] == 0
    assert payloads[0]["task_total"] == apply_result.llm_report["review_summary"]["planned_chunk_count"]
    assert int(payloads[0]["worker_total"] or 0) == 4
    assert any(
        any(line.startswith("configured workers: ") for line in (payload.get("detail_lines") or []))
        for payload in payloads
    )
    assert payloads[-1]["task_current"] == payloads[-1]["task_total"]
    assert payloads[-1]["task_total"] == apply_result.llm_report["review_summary"]["planned_chunk_count"]


def test_knowledge_orchestrator_reports_live_task_packet_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("cookimport.llm.codex_exec_runner.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner._resolve_recipeimport_codex_home",
        lambda explicit_env=None: str(tmp_path / ".codex-recipe"),
    )

    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Seasoning",
                text="Salt in layers for better control.",
                blockIds=[1],
            ),
            KnowledgeChunk(
                id="chunk-2",
                lane=ChunkLane.KNOWLEDGE,
                title="Storage",
                text="Cool leftovers quickly before refrigeration.",
                blockIds=[2],
            ),
            KnowledgeChunk(
                id="chunk-3",
                lane=ChunkLane.KNOWLEDGE,
                title="Heat",
                text="Control the pan temperature carefully.",
                blockIds=[3],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    class _LiveProgressRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            working_dir = Path(kwargs.get("working_dir"))
            out_dir = working_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            supervision_callback = kwargs.get("supervision_callback")
            assigned_tasks = json.loads(
                (working_dir / "assigned_tasks.json").read_text(encoding="utf-8")
            )
            for index, task_row in enumerate(assigned_tasks, start=1):
                if not isinstance(task_row, dict):
                    continue
                task_id = str(task_row.get("task_id") or "")
                if not task_id:
                    continue
                input_payload = json.loads(
                    (working_dir / "in" / f"{task_id}.json").read_text(encoding="utf-8")
                )
                output_payload = build_structural_pipeline_output(
                    "recipe.knowledge.compact.v1",
                    dict(input_payload or {}),
                )
                (out_dir / f"{task_id}.json").write_text(
                    json.dumps(output_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                if supervision_callback is not None and index < len(assigned_tasks):
                    supervision_callback(
                        CodexExecLiveSnapshot(
                            elapsed_seconds=index * 0.1,
                            last_event_seconds_ago=0.0,
                            event_count=index,
                            command_execution_count=index,
                            reasoning_item_count=0,
                            last_command=f"/bin/bash -lc cat out/{task_id}.json",
                            last_command_repeat_count=1,
                            has_final_agent_message=False,
                            timeout_seconds=kwargs.get("timeout_seconds"),
                        )
                    )

            response_text = json.dumps({"status": "worker_completed"}, sort_keys=True)
            events = (
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": response_text},
                },
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
                response_text=response_text,
                turn_failed_message=None,
                events=events,
                usage={
                    "input_tokens": 10,
                    "cached_input_tokens": 0,
                    "output_tokens": 4,
                    "reasoning_tokens": 0,
                },
                stderr_text=None,
                stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
                source_working_dir=str(working_dir),
                execution_working_dir=str(working_dir),
                execution_agents_path=None,
                duration_ms=25,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:01Z",
                supervision_state="completed",
            )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "knowledge_worker_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )

    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Always whisk constantly when adding butter."},
                        {"index": 1, "text": "Salt in layers for better control."},
                        {"index": 2, "text": "Cool leftovers quickly before refrigeration."},
                        {"index": 3, "text": "Control the pan temperature carefully."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    progress_messages: list[str] = []
    run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.4",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=4,
                    block_indices=[0, 1, 2, 3],
                    block_ids=["b0", "b1", "b2", "b3"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.4",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=4,
                    block_indices=[0, 1, 2, 3],
                    block_ids=["b0", "b1", "b2", "b3"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge", 2: "knowledge", 3: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=_LiveProgressRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
                dict(payload or {}),
            )
        ),
        progress_callback=progress_messages.append,
    )

    payloads = [
        payload
        for message in progress_messages
        for payload in [parse_stage_progress(message)]
        if payload is not None
    ]

    assert payloads
    assert payloads[0]["task_current"] == 0
    assert payloads[0]["task_total"] == 4
    live_payloads = [
        payload
        for payload in payloads
        if 0 < int(payload.get("task_current") or 0) < int(payload.get("task_total") or 0)
    ]
    assert live_payloads
    assert {int(payload["task_current"]) for payload in live_payloads} == {1, 2, 3}
    assert any(
        "book.ks0000.nr (1/4 task packets)" in (payload.get("active_tasks") or [])
        for payload in live_payloads
    )
    assert any(
        "completed shards: 0/1" in (payload.get("detail_lines") or [])
        for payload in live_payloads
    )
    assert payloads[-1]["task_current"] == 4
    assert payloads[-1]["task_total"] == 4


def test_knowledge_orchestrator_runs_worker_assignments_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("cookimport.llm.codex_exec_runner.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner._resolve_recipeimport_codex_home",
        lambda explicit_env=None: str(tmp_path / ".codex-recipe"),
    )

    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Seasoning",
                text="Salt in layers for better control.",
                blockIds=[1],
            ),
            KnowledgeChunk(
                id="chunk-2",
                lane=ChunkLane.KNOWLEDGE,
                title="Storage",
                text="Cool leftovers quickly before refrigeration.",
                blockIds=[2],
            ),
            KnowledgeChunk(
                id="chunk-3",
                lane=ChunkLane.KNOWLEDGE,
                title="Heat",
                text="Control the pan temperature carefully.",
                blockIds=[3],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    barrier = threading.Barrier(2)
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    class _ConcurrentRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            barrier.wait(timeout=1.0)
            time.sleep(0.05)
            try:
                return super().run_workspace_worker(*args, **kwargs)
            finally:
                with lock:
                    state["current"] -= 1

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 2,
            "knowledge_worker_count": 2,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Always whisk constantly when adding butter."},
                        {"index": 1, "text": "Salt in layers for better control."},
                        {"index": 2, "text": "Cool leftovers quickly before refrigeration."},
                        {"index": 3, "text": "Control the pan temperature carefully."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.4",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=4,
                    block_indices=[0, 1, 2, 3],
                    block_ids=["b0", "b1", "b2", "b3"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.4",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=4,
                    block_indices=[0, 1, 2, 3],
                    block_ids=["b0", "b1", "b2", "b3"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge", 2: "knowledge", 3: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=_ConcurrentRunner(
            output_builder=lambda payload: build_structural_pipeline_output(
                "recipe.knowledge.compact.v1",
                dict(payload or {}),
            )
        ),
    )

    process_summary = apply_result.llm_report["process_run"]["telemetry"]["summary"]
    assert apply_result.llm_report["phase_worker_runtime"]["shard_count"] == 2
    assert apply_result.llm_report["phase_worker_runtime"]["worker_count"] == 2
    assert process_summary["workspace_worker_row_count"] == 4
    assert process_summary["workspace_worker_session_count"] == 2
    assert process_summary["prompt_input_mode_counts"] == {"workspace_worker": 4}
    assert state["max"] >= 2


def test_knowledge_orchestrator_leases_one_current_packet_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("cookimport.llm.codex_exec_runner.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner._resolve_recipeimport_codex_home",
        lambda explicit_env=None: str(tmp_path / ".codex-recipe"),
    )

    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Seasoning",
                text="Salt in layers for better control.",
                blockIds=[1],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    class LeasingRunner(FakeCodexExecRunner):
        def __init__(self) -> None:
            super().__init__(
                output_builder=lambda payload: build_structural_pipeline_output(
                    "recipe.knowledge.compact.v1",
                    dict(payload or {}),
                )
            )
            self.seen_task_ids: list[str] = []
            self.seen_result_paths: list[str] = []
            self.seen_hint_prefixes: list[str] = []

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            working_dir = Path(kwargs.get("working_dir"))
            out_dir = working_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            supervision_callback = kwargs.get("supervision_callback")

            while True:
                lease_status = json.loads(
                    (working_dir / "packet_lease_status.json").read_text(encoding="utf-8")
                )
                if lease_status["worker_state"] == "all_packets_settled":
                    break
                current_packet = json.loads(
                    (working_dir / "current_packet.json").read_text(encoding="utf-8")
                )
                current_hint = (working_dir / "current_hint.md").read_text(encoding="utf-8")
                result_path_text = (
                    working_dir / "current_result_path.txt"
                ).read_text(encoding="utf-8").strip()
                result_path = working_dir / result_path_text
                self.seen_task_ids.append(current_packet["task_id"])
                self.seen_result_paths.append(result_path_text)
                self.seen_hint_prefixes.append(current_hint.splitlines()[0].strip())

                result_path.write_text(
                    json.dumps(
                        build_structural_pipeline_output(
                            "recipe.knowledge.compact.v1",
                            dict(current_packet["input_payload"] or {}),
                        ),
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                if supervision_callback is not None:
                    supervision_callback(
                        CodexExecLiveSnapshot(
                            elapsed_seconds=max(0.1, len(self.seen_task_ids) * 0.1),
                            last_event_seconds_ago=0.0,
                            event_count=len(self.seen_task_ids),
                            command_execution_count=len(self.seen_task_ids),
                            reasoning_item_count=0,
                            last_command="/bin/bash -lc 'cat current_packet.json'",
                            last_command_repeat_count=1,
                            has_final_agent_message=False,
                            timeout_seconds=kwargs.get("timeout_seconds"),
                        )
                    )
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    refreshed_status = json.loads(
                        (working_dir / "packet_lease_status.json").read_text(encoding="utf-8")
                    )
                    if (
                        refreshed_status["worker_state"] == "all_packets_settled"
                        or refreshed_status["current_task_id"] != current_packet["task_id"]
                    ):
                        break
                    time.sleep(0.05)

            response_text = json.dumps({"status": "worker_completed"}, sort_keys=True)
            events = (
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": response_text},
                },
            )
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
                response_text=response_text,
                turn_failed_message=None,
                events=events,
                usage={
                    "input_tokens": 100,
                    "cached_input_tokens": 0,
                    "output_tokens": 10,
                    "reasoning_tokens": 0,
                },
                duration_ms=250,
                started_at_utc="2026-03-20T22:45:20Z",
                finished_at_utc="2026-03-20T22:45:21Z",
                supervision_state="completed",
            )

    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)

    settings = RunSettings.model_validate(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "knowledge_prompt_target_count": 1,
            "knowledge_worker_count": 1,
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(pack_root),
            "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
        }
    )
    result = ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Always whisk constantly when adding butter."},
                        {"index": 1, "text": "Salt in layers for better control."},
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )
    runner = LeasingRunner()

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=NonRecipeStageResult(
            nonrecipe_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            knowledge_spans=[
                NonRecipeSpan(
                    span_id="nr.knowledge.0.2",
                    category="knowledge",
                    block_start_index=0,
                    block_end_index=2,
                    block_indices=[0, 1],
                    block_ids=["b0", "b1"],
                )
            ],
            other_spans=[],
            block_category_by_index={0: "knowledge", 1: "knowledge"},
        ),
        recipe_spans=[],
        run_settings=settings,
        run_root=run_root,
        workbook_slug="book",
        runner=runner,
    )

    phase_dir = run_root / "raw" / "llm" / "book" / "knowledge"
    worker_root = phase_dir / "workers" / "worker-001"
    task_status_rows = [
        json.loads(line)
        for line in (phase_dir / "task_status.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    proposal = json.loads((phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8"))
    final_current_packet = json.loads(
        (worker_root / "current_packet.json").read_text(encoding="utf-8")
    )

    assert runner.seen_task_ids == [
        "book.ks0000.nr.task-001",
        "book.ks0000.nr.task-002",
    ]
    assert runner.seen_result_paths == [
        "out/book.ks0000.nr.task-001.json",
        "out/book.ks0000.nr.task-002.json",
    ]
    assert all("Knowledge review hints" in prefix for prefix in runner.seen_hint_prefixes)
    assert json.loads(
        (worker_root / "packet_lease_status.json").read_text(encoding="utf-8")
    )["worker_state"] == "all_packets_settled"
    assert final_current_packet["task_id"] is None
    assert [row["state"] for row in task_status_rows] == ["validated", "validated"]
    assert proposal["validation_metadata"]["task_aggregation"]["accepted_task_ids"] == (
        runner.seen_task_ids
    )
    assert apply_result.llm_report["counts"]["validated_shards"] == 1
