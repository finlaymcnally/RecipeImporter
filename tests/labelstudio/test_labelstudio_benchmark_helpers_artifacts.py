from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support
from cookimport.llm import prompt_artifacts

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})

def test_build_codex_farm_prompt_response_log_writes_task_category_logs(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    pass1_in = run_dir / "chunking" / "in"
    pass1_out = run_dir / "chunking" / "out"
    pass2_in = run_dir / "schemaorg" / "in"
    pass2_out = run_dir / "schemaorg" / "out"
    pass3_in = run_dir / "final" / "in"
    pass3_out = run_dir / "final" / "out"
    pass4_in = run_dir / "knowledge" / "in"
    pass4_out = run_dir / "knowledge" / "out"
    pass5_in = run_dir / "tags" / "in"
    pass5_out = run_dir / "tags" / "out"
    for folder in (
        pass1_in,
        pass1_out,
        pass2_in,
        pass2_out,
        pass3_in,
        pass3_out,
        pass4_in,
        pass4_out,
        pass5_in,
        pass5_out,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    attached = run_dir / "attachments" / "task1_notes.txt"
    attached.parent.mkdir(parents=True, exist_ok=True)
    attached.write_text("attachment content\n", encoding="utf-8")

    (pass1_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass1 prompt", "attachment_file_path": str(attached)}),
        encoding="utf-8",
    )
    (pass1_out / "r0000.json").write_text(
        json.dumps({"result": "pass1 response"}),
        encoding="utf-8",
    )
    (pass2_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass2 prompt"}),
        encoding="utf-8",
    )
    (pass2_out / "r0000.json").write_text(
        json.dumps({"result": "pass2 response"}),
        encoding="utf-8",
    )
    (pass3_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass3 prompt"}),
        encoding="utf-8",
    )
    (pass3_out / "r0000.json").write_text(
        json.dumps({"result": "pass3 response"}),
        encoding="utf-8",
    )
    (pass4_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass4 prompt"}),
        encoding="utf-8",
    )
    (pass4_out / "r0000.json").write_text(
        json.dumps({"result": "pass4 response"}),
        encoding="utf-8",
    )
    (pass5_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass5 prompt"}),
        encoding="utf-8",
    )
    (pass5_out / "r0000.json").write_text(
        json.dumps({"result": "pass5 response"}),
        encoding="utf-8",
    )
    pass1_trace_dir = pass1_out / ".codex-farm-traces" / "task-pass1"
    pass1_trace_dir.mkdir(parents=True, exist_ok=True)
    pass1_trace = pass1_trace_dir / "trace-pass1.trace.json"
    pass1_trace.write_text(
        json.dumps(
            {
                "captured_at_utc": "2026-03-02T23:59:01Z",
                "run_id": "run-pass1",
                "pipeline_id": "recipe.chunking.v1",
                "task_id": "task-pass1",
                "reasoning_event_count": 1,
                "reasoning_event_types": ["response.reasoning_summary_text.delta"],
                "reasoning_events": [
                    {
                        "type": "response.reasoning_summary_text.delta",
                        "delta": "candidate span tightened",
                    }
                ],
                "action_event_count": 2,
                "action_event_types": ["thread.started", "item.completed"],
            }
        ),
        encoding="utf-8",
    )

    telemetry_csv = tmp_path / "var" / "codex_exec_activity.csv"
    telemetry_csv.parent.mkdir(parents=True, exist_ok=True)
    with telemetry_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_id",
                "input_path",
                "prompt_text",
                "model",
                "reasoning_effort",
                "sandbox",
                "ask_for_approval",
                "web_search",
                "output_schema_path",
                "task_id",
                "worker_id",
                "status",
                "duration_ms",
                "attempt_index",
                "execution_attempt_index",
                "lease_claim_index",
                "prompt_chars",
                "prompt_sha256",
                "output_bytes",
                "output_sha256",
                "output_payload_present",
                "output_preview_chars",
                "output_preview_truncated",
                "output_preview",
                "tokens_input",
                "tokens_cached_input",
                "tokens_output",
                "tokens_reasoning",
                "tokens_total",
                "usage_json",
                "finished_at_utc",
                "trace_path",
                "trace_action_count",
                "trace_action_types_json",
                "trace_reasoning_count",
                "trace_reasoning_types_json",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "run_id": "run-pass1",
                "input_path": str(pass1_in / "r0000.json"),
                "prompt_text": "Telemetry prompt body",
                "model": "gpt-5-test",
                "reasoning_effort": "high",
                "sandbox": "workspace-write",
                "ask_for_approval": "true",
                "web_search": "false",
                "output_schema_path": "/tmp/schema-pass1.json",
                "task_id": "task-pass1",
                "worker_id": "worker-pass1",
                "status": "ok",
                "duration_ms": "321",
                "attempt_index": "1",
                "execution_attempt_index": "1",
                "lease_claim_index": "1",
                "prompt_chars": "20",
                "prompt_sha256": "sha-prompt",
                "output_bytes": "21",
                "output_sha256": "sha-output",
                "output_payload_present": "true",
                "output_preview_chars": "21",
                "output_preview_truncated": "false",
                "output_preview": "response-preview",
                "tokens_input": "111",
                "tokens_cached_input": "11",
                "tokens_output": "22",
                "tokens_reasoning": "5",
                "tokens_total": "133",
                "usage_json": "{\"tokens\":123}",
                "finished_at_utc": "2026-03-02T23:59:00Z",
                # Simulate stale source-root telemetry paths; loader should resolve
                # local trace files under pass out dir by task id.
                "trace_path": str(
                    Path("/tmp/old-run/.codex-farm-traces/task-pass1")
                    / pass1_trace.name
                ),
                "trace_action_count": "2",
                "trace_action_types_json": json.dumps(
                    ["thread.started", "item.completed"],
                    sort_keys=True,
                ),
                "trace_reasoning_count": "1",
                "trace_reasoning_types_json": json.dumps(
                    ["response.reasoning_summary_text.delta"],
                    sort_keys=True,
                ),
            }
        )

    (run_dir / "recipe_manifest.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "pipeline": "codex-farm-3pass-v1",
                "codex_farm_model": "manifest-model",
                "codex_farm_reasoning_effort": "medium",
                "process_runs": {
                    "pass1": {
                        "run_id": "run-pass1",
                        "telemetry": {"csv_path": str(telemetry_csv)},
                    },
                    "pass2": {
                        "run_id": "run-pass2",
                        "telemetry": {"csv_path": str(telemetry_csv)},
                    },
                    "pass3": {
                        "run_id": "run-pass3",
                        "telemetry": {"csv_path": str(telemetry_csv)},
                    },
                },
                "paths": {
                    "pass1_in": str(pass1_in),
                    "pass1_out": str(pass1_out),
                    "pass2_in": str(pass2_in),
                    "pass2_out": str(pass2_out),
                    "pass3_in": str(pass3_in),
                    "pass3_out": str(pass3_out),
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (run_dir / "knowledge_manifest.json").write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.knowledge.compact.v1",
                "paths": {
                    "pass4_in_dir": str(pass4_in),
                    "pass4_out_dir": str(pass4_out),
                },
                "process_run": {
                    "run_id": "run-pass4",
                    "telemetry": {"csv_path": str(telemetry_csv)},
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (run_dir / "tags_manifest.json").write_text(
        json.dumps(
            {
                "llm_report": {
                    "pipeline_id": "recipe.tags.v1",
                    "paths": {"in_dir": str(pass5_in), "out_dir": str(pass5_out)},
                    "process_run": {
                        "run_id": "run-pass5",
                        "telemetry": {"csv_path": str(telemetry_csv)},
                    },
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    eval_output_dir = tmp_path / "eval"
    log_path = prompt_artifacts.build_codex_farm_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
        repo_root=tmp_path,
    )

    assert log_path == eval_output_dir / "prompts" / "prompt_request_response_log.txt"
    assert log_path is not None and log_path.exists()
    combined = log_path.read_text(encoding="utf-8")
    assert "INPUT chunking => r0000.json" in combined
    assert "OUTPUT final => r0000.json" in combined

    task1_path = eval_output_dir / "prompts" / "prompt_task1_chunking.txt"
    task2_path = eval_output_dir / "prompts" / "prompt_task2_schemaorg.txt"
    task3_path = eval_output_dir / "prompts" / "prompt_task3_final.txt"
    task4_path = eval_output_dir / "prompts" / "prompt_task4_knowledge.txt"
    task5_path = eval_output_dir / "prompts" / "prompt_task5_tags.txt"
    for category_path in (task1_path, task2_path, task3_path, task4_path, task5_path):
        assert category_path.exists()

    task1_text = task1_path.read_text(encoding="utf-8")
    assert "ATTACHMENT task1 =>" in task1_text
    assert str(attached) in task1_text
    assert "attachment content" in task1_text

    manifest_path = eval_output_dir / "prompts" / "prompt_category_logs_manifest.txt"
    assert manifest_path.exists()
    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert manifest_lines == [
        str(task1_path),
        str(task2_path),
        str(task3_path),
        str(task4_path),
        str(task5_path),
    ]

    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    assert full_prompt_log_path.exists()
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 5
    assert {str(row.get("stage_key") or "") for row in full_prompt_rows} == {
        "chunking",
        "schemaorg",
        "final",
        "knowledge",
        "tags",
    }
    pass1_row = next(
        row for row in full_prompt_rows if row.get("stage_key") == "chunking"
    )
    assert pass1_row["call_id"] == "r0000"
    assert pass1_row["request_messages"][0]["role"] == "user"
    assert pass1_row["request_payload_source"] == "telemetry_csv"
    assert pass1_row["request_messages"][0]["content"] == "Telemetry prompt body"
    assert pass1_row["request"]["model"] == "gpt-5-test"
    assert pass1_row["request"]["reasoning_effort"] == "high"
    assert pass1_row["request"]["sandbox"] == "workspace-write"
    assert pass1_row["request"]["ask_for_approval"] is True
    assert pass1_row["request"]["web_search"] is False
    assert pass1_row["request"]["output_schema_path"] == "/tmp/schema-pass1.json"
    assert pass1_row["timestamp_utc"] == "2026-03-02T23:59:00Z"
    assert pass1_row["request_telemetry"]["task_id"] == "task-pass1"
    assert pass1_row["request_telemetry"]["prompt_chars"] == 20
    assert pass1_row["request_telemetry"]["tokens_total"] == 133
    assert pass1_row["request_telemetry"]["usage_json"] == {"tokens": 123}
    assert pass1_row["request_telemetry"]["trace_action_count"] == 2
    assert pass1_row["request_telemetry"]["trace_reasoning_count"] == 1
    assert pass1_row["request_telemetry"]["trace_reasoning_types"] == [
        "response.reasoning_summary_text.delta"
    ]
    assert pass1_row["request_telemetry"]["trace_resolved_path"] == str(pass1_trace)
    assert pass1_row["thinking_trace"]["path"] == str(pass1_trace)
    assert pass1_row["thinking_trace"]["available"] is True
    assert pass1_row["thinking_trace"]["reasoning_event_count"] == 1
    assert pass1_row["thinking_trace"]["reasoning_events"] == [
        {
            "type": "response.reasoning_summary_text.delta",
            "delta": "candidate span tightened",
        }
    ]
    assert pass1_row["parsed_response"] == {"result": "pass1 response"}
    assert pass1_row["raw_response"]["output_file"].endswith("r0000.json")

    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    assert prompt_samples_path.exists()
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## chunking (Chunking)" in prompt_samples
    assert "## schemaorg (Schema.org Extraction)" in prompt_samples
    assert "## final (Final Draft)" in prompt_samples
    assert "## knowledge (Knowledge Harvest)" in prompt_samples
    assert "## tags (Tag Suggestions)" in prompt_samples
    assert "call_id: `r0000`" in prompt_samples
    assert "Telemetry prompt body" in prompt_samples
    assert "Thinking Trace:" in prompt_samples
    assert "candidate span tightened" in prompt_samples

def test_build_codex_farm_prompt_response_log_handles_missing_pass_dirs(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    pass1_in = run_dir / "chunking" / "in"
    pass1_out = run_dir / "chunking" / "out"
    pass1_in.mkdir(parents=True, exist_ok=True)
    pass1_out.mkdir(parents=True, exist_ok=True)
    (pass1_in / "r0000.json").write_text(json.dumps({"prompt_text": "ok"}), encoding="utf-8")
    (pass1_out / "r0000.json").write_text(json.dumps({"result": "ok"}), encoding="utf-8")

    (run_dir / "recipe_manifest.json").write_text(
        json.dumps(
            {
                "paths": {
                    "pass1_in": str(pass1_in),
                    "pass1_out": str(pass1_out),
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    eval_output_dir = tmp_path / "eval"
    log_path = prompt_artifacts.build_codex_farm_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
        repo_root=tmp_path,
    )
    assert log_path is not None and log_path.exists()
    assert (eval_output_dir / "prompts" / "prompt_task1_chunking.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_task2_schemaorg.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_task3_final.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_task4_knowledge.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_task5_tags.txt").exists()
    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    assert full_prompt_rows[0]["stage_key"] == "chunking"
    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    assert prompt_samples_path.exists()
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## chunking (Chunking)" in prompt_samples
    assert "## schemaorg (Schema.org Extraction)" in prompt_samples
    assert "## knowledge (Knowledge Harvest)" in prompt_samples
    assert "## tags (Tag Suggestions)" in prompt_samples
    assert "_No rows captured for this stage._" in prompt_samples


def test_build_codex_farm_prompt_response_log_uses_dynamic_stage_labels_for_merged_repair(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    pass1_in = run_dir / "chunking" / "in"
    pass1_out = run_dir / "chunking" / "out"
    pass2_in = run_dir / "merged_repair" / "in"
    pass2_out = run_dir / "merged_repair" / "out"
    for folder in (pass1_in, pass1_out, pass2_in, pass2_out):
        folder.mkdir(parents=True, exist_ok=True)

    (pass1_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "pass1 prompt"}),
        encoding="utf-8",
    )
    (pass1_out / "r0000.json").write_text(
        json.dumps({"result": "pass1 response"}),
        encoding="utf-8",
    )
    (pass2_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "merged repair prompt"}),
        encoding="utf-8",
    )
    (pass2_out / "r0000.json").write_text(
        json.dumps({"result": "merged repair response"}),
        encoding="utf-8",
    )

    (run_dir / "recipe_manifest.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "pipeline": "codex-farm-2stage-repair-v1",
                "process_runs": {
                    "pass1": {
                        "run_id": "run-pass1",
                        "pipeline_id": "recipe.chunking.v1",
                    },
                    "pass2": {
                        "run_id": "run-pass2",
                        "pipeline_id": "recipe.merged-repair.compact.v1",
                    },
                },
                "paths": {
                    "pass1_in": str(pass1_in),
                    "pass1_out": str(pass1_out),
                    "pass2_in": str(pass2_in),
                    "pass2_out": str(pass2_out),
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    eval_output_dir = tmp_path / "eval"
    log_path = prompt_artifacts.build_codex_farm_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
        repo_root=tmp_path,
    )

    assert log_path is not None and log_path.exists()
    assert (eval_output_dir / "prompts" / "prompt_task1_chunking.txt").exists()
    merged_repair_path = eval_output_dir / "prompts" / "prompt_task2_merged_repair.txt"
    assert merged_repair_path.exists()
    assert not (eval_output_dir / "prompts" / "prompt_task2_schemaorg.txt").exists()

    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    merged_repair_row = next(
        row for row in full_prompt_rows if row.get("stage_key") == "merged_repair"
    )
    assert merged_repair_row["stage_key"] == "merged_repair"
    assert merged_repair_row["stage_artifact_stem"] == "merged_repair"
    assert merged_repair_row["stage_label"] == "Merged Repair"
    assert merged_repair_row["stage_matches_legacy"] is False

    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## merged_repair (Merged Repair)" in prompt_samples
    assert "## pass2 (Schema.org Extraction)" not in prompt_samples
    assert "merged repair prompt" in prompt_samples


def test_prompt_artifact_renderer_supports_non_pass_stage_descriptors(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "run_manifest.json").write_text(
        json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
        encoding="utf-8",
    )

    run_dir = tmp_path / "synthetic-run"
    stage1_in = run_dir / "segmentation_stage" / "in"
    stage1_out = run_dir / "segmentation_stage" / "out"
    stage2_in = run_dir / "repair_stage" / "in"
    stage2_out = run_dir / "repair_stage" / "out"
    for folder in (stage1_in, stage1_out, stage2_in, stage2_out):
        folder.mkdir(parents=True, exist_ok=True)

    (stage1_in / "r0000.json").write_text(
        json.dumps({"recipe_id": "recipe:c0", "prompt_text": "segment prompt"}),
        encoding="utf-8",
    )
    (stage1_out / "r0000.json").write_text(
        json.dumps({"recipe_id": "recipe:c0", "result": "segment response"}),
        encoding="utf-8",
    )
    (stage2_in / "r0000.json").write_text(
        json.dumps({"recipe_id": "recipe:c0", "prompt_text": "repair prompt"}),
        encoding="utf-8",
    )
    (stage2_out / "r0000.json").write_text(
        json.dumps({"recipe_id": "recipe:c0", "result": "repair response"}),
        encoding="utf-8",
    )

    stage1 = prompt_artifacts.PromptStageDescriptor(
        schema_version=prompt_artifacts.PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION,
        legacy_pass="slot_a",
        task_name="task_a",
        slot_index=11,
        stage_dir_name="segmentation_stage",
        stage_key="segmentation",
        stage_heading_key="segmentation",
        stage_label="Segmentation",
        stage_artifact_stem="segmentation",
        stage_matches_legacy=False,
        pipeline_id="recipe.segmenter.v1",
        manifest_name="synthetic_manifest.json",
        manifest_path=None,
        manifest_payload={},
        process_run_payload=None,
        input_dir=stage1_in,
        output_dir=stage1_out,
    )
    stage2 = prompt_artifacts.PromptStageDescriptor(
        schema_version=prompt_artifacts.PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION,
        legacy_pass="slot_b",
        task_name="task_b",
        slot_index=12,
        stage_dir_name="repair_stage",
        stage_key="repair",
        stage_heading_key="repair",
        stage_label="Repair",
        stage_artifact_stem="repair",
        stage_matches_legacy=False,
        pipeline_id="recipe.repair.v1",
        manifest_name="synthetic_manifest.json",
        manifest_path=None,
        manifest_payload={},
        process_run_payload=None,
        input_dir=stage2_in,
        output_dir=stage2_out,
    )
    run_descriptor = prompt_artifacts.PromptRunDescriptor(
        schema_version=prompt_artifacts.PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION,
        run_dir=run_dir,
        manifest_payload_by_name={"synthetic_manifest.json": {"enabled": True}},
        manifest_path_by_name={},
        stages=(stage1, stage2),
        codex_farm_pipeline="synthetic-topology.v1",
        codex_farm_model="model-test",
        codex_farm_reasoning_effort=None,
    )

    eval_output_dir = tmp_path / "eval"
    log_path = prompt_artifacts.build_codex_farm_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
        repo_root=tmp_path,
        run_descriptors=[run_descriptor],
    )

    assert log_path is not None and log_path.exists()
    assert (eval_output_dir / "prompts" / "prompt_task_a_segmentation.txt").exists()
    assert (eval_output_dir / "prompts" / "prompt_task_b_repair.txt").exists()

    full_prompt_rows = [
        json.loads(line)
        for line in (eval_output_dir / "prompts" / "full_prompt_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 2
    assert {row["stage_key"] for row in full_prompt_rows} == {"segmentation", "repair"}
    assert {row["schema_version"] for row in full_prompt_rows} == {
        prompt_artifacts.PROMPT_CALL_RECORD_SCHEMA_VERSION
    }

    prompt_samples = (
        eval_output_dir / "prompts" / "prompt_type_samples_from_full_prompt_log.md"
    ).read_text(encoding="utf-8")
    assert "## segmentation (Segmentation)" in prompt_samples
    assert "## repair (Repair)" in prompt_samples


def test_prompt_artifact_builder_accepts_custom_descriptor_discoverer(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "run_manifest.json").write_text(
        json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
        encoding="utf-8",
    )

    run_dir = tmp_path / "synthetic-run"
    stage_in = run_dir / "linkage_stage" / "in"
    stage_out = run_dir / "linkage_stage" / "out"
    stage_in.mkdir(parents=True, exist_ok=True)
    stage_out.mkdir(parents=True, exist_ok=True)
    (stage_in / "r0000.json").write_text(
        json.dumps({"recipe_id": "recipe:c0", "prompt_text": "linkage prompt"}),
        encoding="utf-8",
    )
    (stage_out / "r0000.json").write_text(
        json.dumps({"recipe_id": "recipe:c0", "result": "linkage response"}),
        encoding="utf-8",
    )

    stage = prompt_artifacts.PromptStageDescriptor(
        schema_version=prompt_artifacts.PROMPT_STAGE_DESCRIPTOR_SCHEMA_VERSION,
        legacy_pass="slot_linkage",
        task_name="task_linkage",
        slot_index=21,
        stage_dir_name="linkage_stage",
        stage_key="linkage",
        stage_heading_key="linkage",
        stage_label="Linkage",
        stage_artifact_stem="linkage",
        stage_matches_legacy=False,
        pipeline_id="recipe.linkage.v1",
        manifest_name="synthetic_manifest.json",
        manifest_path=None,
        manifest_payload={},
        process_run_payload=None,
        input_dir=stage_in,
        output_dir=stage_out,
    )
    run_descriptor = prompt_artifacts.PromptRunDescriptor(
        schema_version=prompt_artifacts.PROMPT_RUN_DESCRIPTOR_SCHEMA_VERSION,
        run_dir=run_dir,
        manifest_payload_by_name={"synthetic_manifest.json": {"enabled": True}},
        manifest_path_by_name={},
        stages=(stage,),
        codex_farm_pipeline="synthetic-topology.v1",
        codex_farm_model="model-test",
        codex_farm_reasoning_effort=None,
    )

    discover_calls: list[Path] = []

    def _discover(*, pred_run: Path) -> list[prompt_artifacts.PromptRunDescriptor]:
        discover_calls.append(pred_run)
        return [run_descriptor]

    eval_output_dir = tmp_path / "eval"
    log_path = prompt_artifacts.build_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
        repo_root=tmp_path,
        discoverers=(_discover,),
    )

    assert discover_calls == [pred_run]
    assert log_path is not None and log_path.exists()
    assert (eval_output_dir / "prompts" / "prompt_task_linkage_linkage.txt").exists()

    full_prompt_rows = [
        json.loads(line)
        for line in (eval_output_dir / "prompts" / "full_prompt_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    assert full_prompt_rows[0]["stage_key"] == "linkage"
    assert full_prompt_rows[0]["stage_key"] == "linkage"


def test_write_stage_run_manifest_includes_prompt_artifacts(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    output_root = tmp_path / "output"
    run_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    requested_path = tmp_path / "source.txt"
    requested_path.write_text("hello\n", encoding="utf-8")
    (run_root / "source.excel_import_report.json").write_text(
        json.dumps({"importerName": "text"}, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    prompts_dir = run_root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "prompt_request_response_log.txt").write_text(
        "prompt log\n",
        encoding="utf-8",
    )
    (prompts_dir / "prompt_category_logs_manifest.txt").write_text(
        "prompt_task1_chunking.txt\n",
        encoding="utf-8",
    )
    (prompts_dir / "full_prompt_log.jsonl").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (prompts_dir / "prompt_type_samples_from_full_prompt_log.md").write_text(
        "# samples\n",
        encoding="utf-8",
    )

    cli._write_stage_run_manifest(
        run_root=run_root,
        output_root=output_root,
        requested_path=requested_path,
        run_dt=dt.datetime(2026, 3, 3, 12, 0, 0),
        run_config={"llm_recipe_pipeline": "codex-farm-3pass-v1"},
    )

    run_manifest_payload = json.loads(
        (run_root / "run_manifest.json").read_text(encoding="utf-8")
    )
    artifacts = run_manifest_payload.get("artifacts")
    assert isinstance(artifacts, dict)
    assert artifacts["prompts_dir"] == "prompts"
    assert artifacts["prompt_request_response_txt"] == (
        "prompts/prompt_request_response_log.txt"
    )
    assert artifacts["prompt_category_logs_manifest_txt"] == (
        "prompts/prompt_category_logs_manifest.txt"
    )
    assert artifacts["full_prompt_log_jsonl"] == (
        "prompts/full_prompt_log.jsonl"
    )
    assert artifacts["prompt_type_samples_from_full_prompt_log_md"] == (
        "prompts/prompt_type_samples_from_full_prompt_log.md"
    )

def test_pred_run_context_enriches_codex_runtime_from_llm_manifest_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.3-codex-spark",
                        "default_reasoning_level": "high",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(cli, "default_codex_reasoning_effort", lambda cmd=None: None)

    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    line_role_telemetry_path = pred_run / "line-role-pipeline" / "telemetry_summary.json"
    line_role_telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    line_role_telemetry_path.write_text(
        json.dumps(
            {
                "summary": {
                    "tokens_input": 50,
                    "tokens_cached_input": 5,
                    "tokens_output": 7,
                    "tokens_reasoning": 2,
                    "tokens_total": 57,
                }
            }
        ),
        encoding="utf-8",
    )
    (pred_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(tmp_path / "book.epub"),
                "source_hash": "source-hash",
                "recipe_count": 7,
                "run_config": {
                    "llm_recipe_pipeline": "codex-farm-3pass-v1",
                    "codex_farm_cmd": "codex-farm",
                    "workers": 1,
                },
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
                "line_role_pipeline_telemetry_path": str(line_role_telemetry_path),
                "llm_codex_farm": {
                    "process_runs": {
                        "pass1": {
                            "process_payload": {
                                "codex_model": "gpt-5.3-codex-spark",
                                "codex_reasoning_effort": None,
                                "telemetry": {
                                    "rows": [
                                        {
                                            "tokens_input": 101,
                                            "tokens_cached_input": 9,
                                            "tokens_output": 12,
                                            "tokens_reasoning": 1,
                                            "tokens_total": 114,
                                        }
                                    ]
                                },
                            },
                            "telemetry_report": {
                                "insights": {
                                    "model_reasoning_breakdown": [
                                        {
                                            "model": "gpt-5.3-codex-spark",
                                            "reasoning_effort": "<default>",
                                        }
                                    ]
                                }
                            },
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    context = cli._load_pred_run_recipe_context(pred_run)

    assert context.run_config is not None
    assert context.run_config.get("codex_farm_model") == "gpt-5.3-codex-spark"
    assert context.run_config.get("codex_farm_reasoning_effort") == "high"
    assert context.run_config_hash is None
    assert context.run_config_summary is None
    assert context.tokens_input == 151
    assert context.tokens_cached_input == 14
    assert context.tokens_output == 19
    assert context.tokens_reasoning == 3
    assert context.tokens_total == 171

def test_pred_run_context_preserves_selective_retry_summary_fields(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": "book.epub",
                "source_hash": "hash-1",
                "run_config": {
                    "selective_retry_attempted": True,
                    "selective_retry_pass2_attempts": 1,
                    "selective_retry_pass2_recovered": 1,
                    "selective_retry_pass3_attempts": 1,
                    "selective_retry_pass3_recovered": 0,
                },
                "run_config_hash": "cfg-hash",
                "run_config_summary": "selective retry summary",
            }
        ),
        encoding="utf-8",
    )

    context = cli._load_pred_run_recipe_context(pred_run)

    assert context.run_config is not None
    assert context.run_config["selective_retry_attempted"] is True
    assert context.run_config["selective_retry_pass2_attempts"] == 1
    assert context.run_config["selective_retry_pass2_recovered"] == 1
    assert context.run_config["selective_retry_pass3_attempts"] == 1
    assert context.run_config["selective_retry_pass3_recovered"] == 0
    assert context.run_config_hash == "cfg-hash"
    assert context.run_config_summary == "selective retry summary"

def test_prompt_budget_summary_merges_codex_and_line_role_telemetry(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    telemetry_path = pred_run / "line-role-pipeline" / "telemetry_summary.json"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry_path.write_text(
        json.dumps(
            {
                "summary": {
                    "batch_count": 2,
                    "attempt_count": 3,
                    "tokens_input": 50,
                    "tokens_cached_input": 5,
                    "tokens_output": 7,
                    "tokens_reasoning": 2,
                    "tokens_total": 64,
                }
            }
        ),
        encoding="utf-8",
    )
    pred_manifest = {
        "line_role_pipeline_telemetry_path": str(telemetry_path),
        "llm_codex_farm": {
            "process_runs": {
                "pass1": {
                    "telemetry_report": {
                        "summary": {
                            "call_count": 2,
                            "duration_total_ms": 1200,
                            "tokens_input": 101,
                            "tokens_cached_input": 9,
                            "tokens_output": 12,
                            "tokens_reasoning": 1,
                            "tokens_total": 123,
                        }
                    }
                },
                "pass2": {
                    "telemetry_report": {
                        "summary": {
                            "call_count": 1,
                            "duration_total_ms": 2200,
                            "tokens_input": 80,
                            "tokens_cached_input": 0,
                            "tokens_output": 20,
                            "tokens_reasoning": 4,
                            "tokens_total": 104,
                        }
                    }
                },
            },
            "knowledge": {
                "process_run": {
                    "telemetry_report": {
                        "summary": {
                            "call_count": 4,
                            "duration_total_ms": 4200,
                            "tokens_input": 300,
                            "tokens_cached_input": 25,
                            "tokens_output": 60,
                            "tokens_reasoning": 0,
                            "tokens_total": 360,
                        }
                    }
                }
            },
        },
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)
    summary_path = write_prediction_run_prompt_budget_summary(pred_run, summary)

    written = json.loads(summary_path.read_text(encoding="utf-8"))
    assert written["by_pass"]["pass1"]["call_count"] == 2
    assert written["by_pass"]["pass2"]["tokens_total"] == 104
    assert written["by_pass"]["pass4"]["call_count"] == 4
    assert written["by_pass"]["pass4"]["tokens_total"] == 360
    assert written["by_pass"]["line_role"]["call_count"] == 2
    assert written["by_pass"]["line_role"]["attempt_count"] == 3
    assert written["totals"]["tokens_total"] == 651

def test_copy_line_role_pass4_merge_artifacts_for_benchmark_writes_summary(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_line_role_dir = pred_run / "line-role-pipeline"
    pred_line_role_dir.mkdir(parents=True, exist_ok=True)
    (pred_line_role_dir / "pass4_merge_report.json").write_text(
        json.dumps(
            {
                "schema_version": "line_role_pass4_merge_report.v1",
                "merge_mode": "block_classifications",
                "usable_evidence": True,
                "selected_block_count": 1,
                "selected_line_count": 1,
                "upgraded_other_to_knowledge_count": 1,
                "downgraded_knowledge_to_other_count": 0,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (pred_line_role_dir / "pass4_merge_changed_rows.jsonl").write_text(
        json.dumps(
            {
                "line_index": 7,
                "old_label": "OTHER",
                "new_label": "KNOWLEDGE",
                "selection_reason": "block_classification_knowledge",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    eval_output_dir = tmp_path / "eval"
    line_role_output_dir = eval_output_dir / "line-role-pipeline"
    line_role_output_dir.mkdir(parents=True, exist_ok=True)
    joined_line_rows = [
        {
            "line_index": 7,
            "gold_label": "KNOWLEDGE",
            "pred_label": "KNOWLEDGE",
            "within_recipe_span": False,
        }
    ]

    artifacts = cli._copy_line_role_pass4_merge_artifacts_for_benchmark(
        pred_run=pred_run,
        line_role_output_dir=line_role_output_dir,
        joined_line_rows=joined_line_rows,
        eval_output_dir=eval_output_dir,
    )

    assert artifacts == {
        "pass4_merge_report_json": "line-role-pipeline/pass4_merge_report.json",
        "pass4_merge_changed_rows_jsonl": "line-role-pipeline/pass4_merge_changed_rows.jsonl",
        "pass4_merge_summary_json": "line-role-pipeline/pass4_merge_summary.json",
    }
    summary = json.loads(
        (line_role_output_dir / "pass4_merge_summary.json").read_text(encoding="utf-8")
    )
    assert summary["changed_line_count"] == 1
    assert summary["changed_lines_matching_gold"] == 1
    assert summary["changed_lines_wrong"] == 0
    assert summary["changed_to_knowledge_gold_knowledge"] == 1
    assert summary["merge_report"]["merge_mode"] == "block_classifications"
