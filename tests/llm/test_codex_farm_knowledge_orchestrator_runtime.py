from __future__ import annotations

import tests.llm.test_codex_farm_knowledge_orchestrator as _base

# Reuse shared imports/helpers from the base knowledge orchestrator test module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def _configure_runtime_codex_home(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("cookimport.llm.codex_exec_runner.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner._resolve_recipeimport_codex_home",
        lambda explicit_env=None: str(tmp_path / ".codex-recipe"),
    )


def _make_runtime_pack_and_run_dirs(tmp_path: Path) -> tuple[Path, Path]:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)

    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    return pack_root, run_root


def _make_runtime_settings(
    *,
    pack_root: Path,
    target_count: int,
    worker_count: int,
    context_blocks: int | None = None,
) -> RunSettings:
    payload: dict[str, object] = {
        "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
        "knowledge_prompt_target_count": target_count,
        "knowledge_worker_count": worker_count,
        "codex_farm_cmd": "codex-farm",
        "codex_farm_root": str(pack_root),
        "codex_farm_pipeline_knowledge": "recipe.knowledge.compact.v1",
    }
    if context_blocks is not None:
        payload["codex_farm_knowledge_context_blocks"] = context_blocks
    return RunSettings.model_validate(payload)


def _make_runtime_conversion_result(block_texts: list[str]) -> ConversionResult:
    return ConversionResult(
        recipes=[],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        nonRecipeBlocks=[
            {"index": index, "text": text}
            for index, text in enumerate(block_texts)
        ],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": index, "text": text}
                        for index, text in enumerate(block_texts)
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )


def _make_runtime_nonrecipe_stage_result(
    *,
    block_indices: list[int],
    span_id: str,
) -> NonRecipeStageResult:
    span = NonRecipeSpan(
        span_id=span_id,
        category="knowledge",
        block_start_index=min(block_indices),
        block_end_index=max(block_indices) + 1,
        block_indices=block_indices,
        block_ids=[f"b{index}" for index in block_indices],
    )
    return NonRecipeStageResult(
        nonrecipe_spans=[span],
        knowledge_spans=[span],
        other_spans=[],
        block_category_by_index={index: "knowledge" for index in block_indices},
    )


def test_knowledge_orchestrator_emits_structured_progress_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, run_root = _make_runtime_pack_and_run_dirs(tmp_path)
    settings = _make_runtime_settings(
        pack_root=pack_root,
        target_count=2,
        worker_count=4,
        context_blocks=1,
    )
    result = _make_runtime_conversion_result(
        [
            "Preface",
            "Toast",
            "1 slice bread",
            "Toast the bread.",
            "Technique: Whisk constantly.",
        ]
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


def _run_live_task_packet_progress_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    _configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

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

    pack_root, run_root = _make_runtime_pack_and_run_dirs(tmp_path)
    settings = _make_runtime_settings(
        pack_root=pack_root,
        target_count=1,
        worker_count=1,
    )
    result = _make_runtime_conversion_result(
        [
            "Always whisk constantly when adding butter.",
            "Salt in layers for better control.",
            "Cool leftovers quickly before refrigeration.",
            "Control the pan temperature carefully.",
        ]
    )

    progress_messages: list[str] = []
    run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=_make_runtime_nonrecipe_stage_result(
            block_indices=[0, 1, 2, 3],
            span_id="nr.knowledge.0.4",
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
    return {
        "payloads": payloads,
    }


def test_knowledge_orchestrator_reports_live_task_packet_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_live_task_packet_progress_fixture(monkeypatch, tmp_path)
    payloads = fixture["payloads"]
    assert payloads
    assert payloads[0]["task_current"] == 0
    assert payloads[0]["task_total"] == 2
    live_payloads = [
        payload
        for payload in payloads
        if 0 < int(payload.get("task_current") or 0) < int(payload.get("task_total") or 0)
    ]
    assert live_payloads
    assert {int(payload["task_current"]) for payload in live_payloads} == {1}
    assert payloads[-1]["task_current"] == 2
    assert payloads[-1]["task_total"] == 2


def test_knowledge_orchestrator_progress_detail_lines_track_live_task_packets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_live_task_packet_progress_fixture(monkeypatch, tmp_path)
    payloads = fixture["payloads"]
    live_payloads = [
        payload
        for payload in payloads
        if 0 < int(payload.get("task_current") or 0) < int(payload.get("task_total") or 0)
    ]

    assert any(
        "book.ks0000.nr (1/2 task packets)" in (payload.get("active_tasks") or [])
        for payload in live_payloads
    )
    assert any(
        "completed shards: 0/1" in (payload.get("detail_lines") or [])
        for payload in live_payloads
    )


def test_knowledge_orchestrator_runs_worker_assignments_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

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

    pack_root, run_root = _make_runtime_pack_and_run_dirs(tmp_path)
    settings = _make_runtime_settings(
        pack_root=pack_root,
        target_count=2,
        worker_count=2,
    )
    result = _make_runtime_conversion_result(
        [
            "Always whisk constantly when adding butter.",
            "Salt in layers for better control.",
            "Cool leftovers quickly before refrigeration.",
            "Control the pan temperature carefully.",
        ]
    )

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=_make_runtime_nonrecipe_stage_result(
            block_indices=[0, 1, 2, 3],
            span_id="nr.knowledge.0.4",
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
    assert process_summary["workspace_worker_row_count"] == 2
    assert process_summary["workspace_worker_session_count"] == 2
    assert process_summary["prompt_input_mode_counts"] == {"workspace_worker": 2}
    assert state["max"] >= 2


def _run_runtime_task_leasing_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    _configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)

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
            current_task_path = working_dir / "current_task.json"

            while True:
                if not current_task_path.exists():
                    break
                current_task = json.loads(current_task_path.read_text(encoding="utf-8"))
                task_metadata = dict(current_task.get("metadata") or {})
                task_id = str(current_task.get("task_id") or "").strip()
                hint_path = working_dir / str(task_metadata.get("hint_path") or "").strip()
                current_hint = hint_path.read_text(encoding="utf-8")
                result_path_text = str(task_metadata.get("result_path") or "").strip()
                result_path = working_dir / result_path_text
                input_path = working_dir / str(task_metadata.get("input_path") or "").strip()
                input_payload = json.loads(input_path.read_text(encoding="utf-8"))
                self.seen_task_ids.append(task_id)
                self.seen_result_paths.append(result_path_text)
                self.seen_hint_prefixes.append(current_hint.splitlines()[0].strip())

                result_path.write_text(
                    json.dumps(
                        build_structural_pipeline_output(
                            "recipe.knowledge.compact.v1",
                            dict(input_payload or {}),
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
                            last_command="/bin/bash -lc 'cat current_task.json'",
                            last_command_repeat_count=1,
                            has_final_agent_message=False,
                            timeout_seconds=kwargs.get("timeout_seconds"),
                        )
                    )
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if not current_task_path.exists():
                        break
                    refreshed_task = json.loads(current_task_path.read_text(encoding="utf-8"))
                    refreshed_task_id = str(refreshed_task.get("task_id") or "").strip()
                    if refreshed_task_id != task_id:
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

    pack_root, run_root = _make_runtime_pack_and_run_dirs(tmp_path)
    settings = _make_runtime_settings(
        pack_root=pack_root,
        target_count=1,
        worker_count=1,
    )
    result = _make_runtime_conversion_result(
        [
            "Always whisk constantly when adding butter.",
            "Salt in layers for better control.",
        ]
    )
    runner = LeasingRunner()

    apply_result = run_codex_farm_nonrecipe_knowledge_review(
        conversion_result=result,
        nonrecipe_stage_result=_make_runtime_nonrecipe_stage_result(
            block_indices=[0, 1],
            span_id="nr.knowledge.0.2",
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
    return {
        "runner": runner,
        "worker_root": worker_root,
        "task_status_rows": task_status_rows,
        "proposal": proposal,
        "apply_result": apply_result,
    }


def test_knowledge_orchestrator_leases_runtime_tasks_one_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_task_leasing_fixture(monkeypatch, tmp_path)
    runner = fixture["runner"]
    worker_root = fixture["worker_root"]
    assert isinstance(runner, FakeCodexExecRunner)
    assert isinstance(worker_root, Path)

    assert runner.seen_task_ids == ["book.ks0000.nr"]
    assert runner.seen_result_paths == ["out/book.ks0000.nr.json"]
    assert all("Knowledge review hints" in prefix for prefix in runner.seen_hint_prefixes)
    assert not (worker_root / "current_task.json").exists()
    assert "No current task is active" in (
        worker_root / "CURRENT_TASK.md"
    ).read_text(encoding="utf-8")
    assert "queue is complete" in (
        worker_root / "CURRENT_TASK_FEEDBACK.md"
    ).read_text(encoding="utf-8").lower()


def test_knowledge_orchestrator_records_validated_runtime_task_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_runtime_task_leasing_fixture(monkeypatch, tmp_path)
    task_status_rows = fixture["task_status_rows"]
    proposal = fixture["proposal"]
    apply_result = fixture["apply_result"]
    assert isinstance(task_status_rows, list)
    assert isinstance(proposal, dict)

    assert [row["state"] for row in task_status_rows] == ["validated"]
    assert proposal["validation_metadata"]["task_aggregation"]["accepted_task_ids"] == [
        "book.ks0000.nr"
    ]
    assert apply_result.llm_report["counts"]["validated_shards"] == 1
