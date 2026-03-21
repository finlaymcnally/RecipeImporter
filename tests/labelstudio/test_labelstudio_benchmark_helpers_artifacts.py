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


def test_source_debug_artifact_status_reads_recipe_phase_runtime_paths(
    tmp_path: Path,
) -> None:
    eval_dir = tmp_path / "eval"
    prediction_run_dir = eval_dir / "prediction-run"
    prediction_run_dir.mkdir(parents=True, exist_ok=True)

    aligned_path = eval_dir / "aligned_prediction_blocks.jsonl"
    aligned_path.write_text("{}\n", encoding="utf-8")
    prompt_inputs_manifest = prediction_run_dir / "prompt_inputs_manifest.txt"
    prompt_outputs_manifest = prediction_run_dir / "prompt_outputs_manifest.txt"
    recipe_phase_runtime_dir = prediction_run_dir / "llm" / "recipe_phase_runtime"
    recipe_phase_input_dir = recipe_phase_runtime_dir / "inputs"
    recipe_phase_proposals_dir = recipe_phase_runtime_dir / "proposals"
    for path in (recipe_phase_input_dir, recipe_phase_proposals_dir):
        path.mkdir(parents=True, exist_ok=True)
    prompt_request_path = recipe_phase_input_dir / "prompt_request_0.json"
    prompt_response_path = recipe_phase_proposals_dir / "prompt_response_0.json"
    prompt_request_path.write_text("{}", encoding="utf-8")
    prompt_response_path.write_text("{}", encoding="utf-8")
    prompt_inputs_manifest.write_text(f"{prompt_request_path}\n", encoding="utf-8")
    prompt_outputs_manifest.write_text(f"{prompt_response_path}\n", encoding="utf-8")

    recipe_manifest_path = prediction_run_dir / "recipe_manifest.json"
    recipe_manifest_path.write_text(
        json.dumps(
            {
                "paths": {
                    "recipe_phase_runtime_dir": str(recipe_phase_runtime_dir),
                    "recipe_phase_input_dir": str(recipe_phase_input_dir),
                    "recipe_phase_proposals_dir": str(recipe_phase_proposals_dir),
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    prediction_run_manifest = {
        "artifacts": {
            "prompt_inputs_manifest_txt": str(prompt_inputs_manifest),
            "prompt_outputs_manifest_txt": str(prompt_outputs_manifest),
            "recipe_manifest_json": str(recipe_manifest_path),
        }
    }
    (prediction_run_dir / "run_manifest.json").write_text(
        json.dumps(prediction_run_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    status = cli._build_source_debug_artifact_status(
        eval_report_path=eval_dir / "eval_report.json",
        eval_report={"artifacts": {"aligned_prediction_blocks_jsonl": str(aligned_path)}},
        codex_farm_recipe_mode="benchmark",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        prediction_run_dir=prediction_run_dir,
    )

    assert status["all_present"] is True
    assert status["required"] is True
    assert "recipe_phase_input_json" in status["required_checks"]
    assert "recipe_phase_proposal_json" in status["required_checks"]

def test_build_codex_farm_prompt_response_log_writes_task_category_logs(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    recipe_phase_runtime_dir = run_dir / "recipe_phase_runtime"
    correction_in = recipe_phase_runtime_dir / "inputs"
    correction_out = recipe_phase_runtime_dir / "proposals"
    knowledge_in = run_dir / "knowledge" / "in"
    knowledge_out = run_dir / "knowledge" / "out"
    tags_in = run_dir / "tags" / "in"
    tags_out = run_dir / "tags" / "out"
    for folder in (
        correction_in,
        correction_out,
        knowledge_in,
        knowledge_out,
        tags_in,
        tags_out,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    attached = run_dir / "attachments" / "task1_notes.txt"
    attached.parent.mkdir(parents=True, exist_ok=True)
    attached.write_text("attachment content\n", encoding="utf-8")

    (correction_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "recipe correction prompt", "attachment_file_path": str(attached)}),
        encoding="utf-8",
    )
    (correction_out / "r0000.json").write_text(
        json.dumps({"result": "recipe correction response"}),
        encoding="utf-8",
    )
    (knowledge_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "knowledge prompt"}),
        encoding="utf-8",
    )
    (knowledge_out / "r0000.json").write_text(
        json.dumps({"result": "knowledge response"}),
        encoding="utf-8",
    )
    (tags_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "tags prompt"}),
        encoding="utf-8",
    )
    (tags_out / "r0000.json").write_text(
        json.dumps({"result": "tags response"}),
        encoding="utf-8",
    )
    correction_trace_dir = correction_out / ".codex-farm-traces" / "task-recipe-correction"
    correction_trace_dir.mkdir(parents=True, exist_ok=True)
    correction_trace = correction_trace_dir / "trace-recipe-correction.trace.json"
    correction_trace.write_text(
        json.dumps(
            {
                "captured_at_utc": "2026-03-02T23:59:01Z",
                "run_id": "run-recipe-correction",
                "pipeline_id": "recipe.correction.compact.v1",
                "task_id": "task-recipe-correction",
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
                "run_id": "run-recipe-correction",
                "input_path": str(correction_in / "r0000.json"),
                "prompt_text": "Telemetry prompt body",
                "model": "gpt-5-test",
                "reasoning_effort": "high",
                "sandbox": "workspace-write",
                "ask_for_approval": "true",
                "web_search": "false",
                "output_schema_path": "/tmp/schema-recipe-correction.json",
                "task_id": "task-recipe-correction",
                "worker_id": "worker-recipe-correction",
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
                # local trace files under the current stage out dir by task id.
                "trace_path": str(
                    Path("/tmp/old-run/.codex-farm-traces/task-recipe-correction")
                    / correction_trace.name
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
                "pipeline": "codex-recipe-shard-v1",
                "codex_farm_model": "manifest-model",
                "codex_farm_reasoning_effort": "medium",
                "process_runs": {
                    "recipe_correction": {
                        "run_id": "run-recipe-correction",
                        "pipeline_id": "recipe.correction.compact.v1",
                        "telemetry": {"csv_path": str(telemetry_csv)},
                    },
                },
                "pipelines": {
                    "recipe_correction": "recipe.correction.compact.v1",
                },
                "paths": {
                    "recipe_phase_runtime_dir": str(recipe_phase_runtime_dir),
                    "recipe_phase_input_dir": str(correction_in),
                    "recipe_phase_proposals_dir": str(correction_out),
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
                    "knowledge_in_dir": str(knowledge_in),
                    "proposals_dir": str(knowledge_out),
                },
                "process_run": {
                    "run_id": "run-knowledge",
                    "telemetry": {"csv_path": str(telemetry_csv)},
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

    assert log_path == eval_output_dir / "prompts" / "prompt_request_response_log.txt"
    assert log_path is not None and log_path.exists()
    combined = log_path.read_text(encoding="utf-8")
    assert "INPUT recipe_llm_correct_and_link => r0000.json" in combined
    recipe_path = eval_output_dir / "prompts" / "prompt_recipe_llm_correct_and_link.txt"
    knowledge_path = eval_output_dir / "prompts" / "prompt_nonrecipe_knowledge_review.txt"
    for category_path in (recipe_path, knowledge_path):
        assert category_path.exists()

    recipe_text = recipe_path.read_text(encoding="utf-8")
    assert "ATTACHMENT recipe_llm_correct_and_link =>" in recipe_text
    assert str(attached) in recipe_text
    assert "attachment content" in recipe_text

    manifest_path = eval_output_dir / "prompts" / "prompt_category_logs_manifest.txt"
    assert manifest_path.exists()
    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert manifest_lines == [
        str(recipe_path),
        str(knowledge_path),
    ]

    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    assert full_prompt_log_path.exists()
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 2
    assert {str(row.get("stage_key") or "") for row in full_prompt_rows} == {
        "recipe_llm_correct_and_link",
        "nonrecipe_knowledge_review",
    }
    correction_row = next(
        row
        for row in full_prompt_rows
        if row.get("stage_key") == "recipe_llm_correct_and_link"
    )
    assert correction_row["call_id"] == "r0000"
    assert correction_row["request_messages"][0]["role"] == "user"
    assert correction_row["request_payload_source"] == "telemetry_csv"
    assert correction_row["request_messages"][0]["content"] == "Telemetry prompt body"
    assert correction_row["request"]["model"] == "gpt-5-test"
    assert correction_row["request"]["reasoning_effort"] == "high"
    assert correction_row["request"]["sandbox"] == "workspace-write"
    assert correction_row["request"]["ask_for_approval"] is True
    assert correction_row["request"]["web_search"] is False
    assert correction_row["request"]["output_schema_path"] == "/tmp/schema-recipe-correction.json"
    assert correction_row["timestamp_utc"] == "2026-03-02T23:59:00Z"
    assert correction_row["request_telemetry"]["task_id"] == "task-recipe-correction"
    assert correction_row["request_telemetry"]["prompt_chars"] == 20
    assert correction_row["request_telemetry"]["tokens_total"] == 133
    assert correction_row["request_telemetry"]["usage_json"] == {"tokens": 123}
    assert correction_row["request_telemetry"]["trace_action_count"] == 2
    assert correction_row["request_telemetry"]["trace_reasoning_count"] == 1
    assert correction_row["request_telemetry"]["trace_reasoning_types"] == [
        "response.reasoning_summary_text.delta"
    ]
    assert correction_row["request_telemetry"]["trace_resolved_path"] == str(correction_trace)
    assert correction_row["thinking_trace"]["path"] == str(correction_trace)
    assert correction_row["thinking_trace"]["available"] is True
    assert correction_row["thinking_trace"]["reasoning_event_count"] == 1
    assert correction_row["thinking_trace"]["reasoning_events"] == [
        {
            "type": "response.reasoning_summary_text.delta",
            "delta": "candidate span tightened",
        }
    ]
    assert correction_row["parsed_response"] == {"result": "recipe correction response"}
    assert correction_row["raw_response"]["output_file"].endswith("r0000.json")

    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    assert prompt_samples_path.exists()
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## recipe_llm_correct_and_link (Recipe Correction)" in prompt_samples
    assert "## nonrecipe_knowledge_review (Non-Recipe Knowledge Review)" in prompt_samples
    assert "call_id: `r0000`" in prompt_samples
    assert "Telemetry prompt body" in prompt_samples
    assert "Thinking Trace:" in prompt_samples
    assert "candidate span tightened" in prompt_samples

    thinking_trace_summary_jsonl_path = (
        eval_output_dir / "prompts" / "thinking_trace_summary.jsonl"
    )
    thinking_trace_summary_md_path = (
        eval_output_dir / "prompts" / "thinking_trace_summary.md"
    )
    assert thinking_trace_summary_jsonl_path.exists()
    assert thinking_trace_summary_md_path.exists()
    trace_rows = [
        json.loads(line)
        for line in thinking_trace_summary_jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(trace_rows) == 2
    correction_trace_row = next(
        row for row in trace_rows if row.get("stage_key") == "recipe_llm_correct_and_link"
    )
    assert correction_trace_row["trace_exists"] is True
    assert correction_trace_row["reasoning_event_count"] == 1
    assert "candidate span tightened" in str(correction_trace_row["reasoning_excerpt"])
    trace_summary_md = thinking_trace_summary_md_path.read_text(encoding="utf-8")
    assert "# CodexFarm Thinking Trace Summary" in trace_summary_md
    assert "- total_rows: `2`" in trace_summary_md
    assert "## recipe_llm_correct_and_link (Recipe Correction)" in trace_summary_md


def test_build_codex_farm_prompt_response_log_backfills_direct_runtime_telemetry_without_csv(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    recipe_phase_runtime_dir = run_dir / "recipe_phase_runtime"
    correction_in = recipe_phase_runtime_dir / "inputs"
    correction_out = recipe_phase_runtime_dir / "proposals"
    worker_in = recipe_phase_runtime_dir / "workers" / "worker-001" / "in"
    worker_debug = recipe_phase_runtime_dir / "workers" / "worker-001" / "debug"
    for folder in (correction_in, correction_out, worker_in, worker_debug):
        folder.mkdir(parents=True, exist_ok=True)

    (correction_in / "r0000.json").write_text(
        json.dumps(
            {
                "recipe_id": "recipe:c0",
                "evidence_rows": [[0, "Dish Title"], [1, "1 cup flour"]],
            }
        ),
        encoding="utf-8",
    )
    (correction_out / "r0000.json").write_text(
        json.dumps({"recipe_id": "recipe:c0", "canonical_recipe": {"title": "Dish Title"}}),
        encoding="utf-8",
    )
    (worker_in / "recipe-shard-0000.json").write_text(
        json.dumps({"ids": ["recipe:c0"]}),
        encoding="utf-8",
    )
    (worker_debug / "recipe-shard-0000.json").write_text(
        json.dumps({"ids": ["recipe:c0"], "phase": "recipe"}),
        encoding="utf-8",
    )
    (recipe_phase_runtime_dir / "phase_manifest.json").write_text(
        json.dumps({"pipeline_id": "recipe.correction.compact.v1"}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (recipe_phase_runtime_dir / "worker_assignments.json").write_text(
        json.dumps([{"worker_id": "worker-001", "shard_ids": ["recipe-shard-0000"]}]),
        encoding="utf-8",
    )
    (recipe_phase_runtime_dir / "shard_manifest.jsonl").write_text(
        json.dumps(
            {
                "shard_id": "recipe-shard-0000",
                "owned_ids": ["recipe:c0"],
                "metadata": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (recipe_phase_runtime_dir / "telemetry.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "task_id": "recipe-shard-0000",
                        "worker_id": "worker-001",
                        "status": "ok",
                        "duration_ms": 456,
                        "tokens_input": 700,
                        "tokens_cached_input": 70,
                        "tokens_output": 89,
                        "tokens_reasoning": 0,
                        "tokens_total": 859,
                        "prompt_text": "Runtime telemetry prompt body",
                        "finished_at_utc": "2026-03-19T12:34:56Z",
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    (run_dir / "recipe_manifest.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "pipeline": "codex-recipe-shard-v1",
                "process_runs": {
                    "recipe_correction": {
                        "run_id": "run-recipe-correction",
                        "pipeline_id": "recipe.correction.compact.v1",
                    }
                },
                "paths": {
                    "recipe_phase_runtime_dir": str(recipe_phase_runtime_dir),
                    "recipe_phase_input_dir": str(correction_in),
                    "recipe_phase_proposals_dir": str(correction_out),
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

    assert log_path == eval_output_dir / "prompts" / "prompt_request_response_log.txt"
    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    row = full_prompt_rows[0]
    assert row["request_payload_source"] == "runtime_telemetry"
    assert row["request_messages"][0]["content"] == "Runtime telemetry prompt body"
    assert row["timestamp_utc"] == "2026-03-19T12:34:56Z"
    assert row["runtime_shard_id"] == "recipe-shard-0000"
    assert row["request_telemetry"]["duration_ms"] == 456
    assert row["request_telemetry"]["tokens_total"] == 859
    assert row["request_telemetry"]["worker_id"] == "worker-001"

def test_build_codex_farm_prompt_response_log_handles_missing_pass_dirs(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    recipe_phase_runtime_dir = run_dir / "recipe_phase_runtime"
    correction_in = recipe_phase_runtime_dir / "inputs"
    correction_out = recipe_phase_runtime_dir / "proposals"
    correction_in.mkdir(parents=True, exist_ok=True)
    correction_out.mkdir(parents=True, exist_ok=True)
    (correction_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "ok"}),
        encoding="utf-8",
    )
    (correction_out / "r0000.json").write_text(
        json.dumps({"result": "ok"}),
        encoding="utf-8",
    )

    (run_dir / "recipe_manifest.json").write_text(
        json.dumps(
            {
                "process_runs": {
                    "recipe_correction": {
                        "run_id": "run-recipe-correction",
                        "pipeline_id": "recipe.correction.compact.v1",
                    },
                },
                "pipelines": {
                    "recipe_correction": "recipe.correction.compact.v1",
                },
                "paths": {
                    "recipe_phase_runtime_dir": str(recipe_phase_runtime_dir),
                    "recipe_phase_input_dir": str(correction_in),
                    "recipe_phase_proposals_dir": str(correction_out),
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
    assert (eval_output_dir / "prompts" / "prompt_recipe_llm_correct_and_link.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_nonrecipe_knowledge_review.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_tags.txt").exists()
    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    assert full_prompt_rows[0]["stage_key"] == "recipe_llm_correct_and_link"
    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    assert prompt_samples_path.exists()
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## recipe_llm_correct_and_link (Recipe Correction)" in prompt_samples
    assert "## nonrecipe_knowledge_review (Non-Recipe Knowledge Review)" in prompt_samples
    assert "_No rows captured for this stage._" in prompt_samples


def test_build_codex_farm_prompt_response_log_uses_recipe_correction_stage_labels(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    recipe_phase_runtime_dir = run_dir / "recipe_phase_runtime"
    correction_in = recipe_phase_runtime_dir / "inputs"
    correction_out = recipe_phase_runtime_dir / "proposals"
    for folder in (correction_in, correction_out):
        folder.mkdir(parents=True, exist_ok=True)

    (correction_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "recipe correction prompt"}),
        encoding="utf-8",
    )
    (correction_out / "r0000.json").write_text(
        json.dumps({"result": "recipe correction response"}),
        encoding="utf-8",
    )

    (run_dir / "recipe_manifest.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "pipeline": "codex-recipe-shard-v1",
                "process_runs": {
                    "recipe_correction": {
                        "run_id": "run-recipe-correction",
                        "pipeline_id": "recipe.correction.compact.v1",
                    },
                },
                "pipelines": {
                    "recipe_correction": "recipe.correction.compact.v1",
                },
                "paths": {
                    "recipe_phase_runtime_dir": str(recipe_phase_runtime_dir),
                    "recipe_phase_input_dir": str(correction_in),
                    "recipe_phase_proposals_dir": str(correction_out),
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
    correction_path = eval_output_dir / "prompts" / "prompt_recipe_llm_correct_and_link.txt"
    assert correction_path.exists()

    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    correction_row = next(
        row
        for row in full_prompt_rows
        if row.get("stage_key") == "recipe_llm_correct_and_link"
    )
    assert correction_row["stage_key"] == "recipe_llm_correct_and_link"
    assert correction_row["stage_artifact_stem"] == "recipe_correction"
    assert correction_row["stage_label"] == "Recipe Correction"

    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## recipe_llm_correct_and_link (Recipe Correction)" in prompt_samples
    assert "recipe correction prompt" in prompt_samples


def test_build_codex_farm_prompt_response_log_follows_benchmark_stage_run_pointer(
    tmp_path: Path,
) -> None:
    processed_run = tmp_path / "processed" / "2026-03-16_18.11.25"
    run_dir = processed_run / "raw" / "llm" / "book"
    recipe_phase_runtime_dir = run_dir / "recipe_phase_runtime"
    correction_in = recipe_phase_runtime_dir / "inputs"
    correction_out = recipe_phase_runtime_dir / "proposals"
    correction_in.mkdir(parents=True, exist_ok=True)
    correction_out.mkdir(parents=True, exist_ok=True)
    (correction_in / "r0000.json").write_text(
        json.dumps({"prompt_text": "recipe correction prompt"}),
        encoding="utf-8",
    )
    (correction_out / "r0000.json").write_text(
        json.dumps({"result": "recipe correction response"}),
        encoding="utf-8",
    )
    (run_dir / "recipe_manifest.json").write_text(
        json.dumps(
            {
                "pipeline": "codex-recipe-shard-v1",
                "pipelines": {
                    "recipe_correction": "recipe.correction.compact.v1",
                },
                "paths": {
                    "recipe_phase_runtime_dir": str(recipe_phase_runtime_dir),
                    "recipe_phase_input_dir": str(correction_in),
                    "recipe_phase_proposals_dir": str(correction_out),
                },
                "process_runs": {
                    "recipe_correction": {
                        "run_id": "run-recipe-correction",
                        "pipeline_id": "recipe.correction.compact.v1",
                    }
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    eval_output_dir = tmp_path / "eval"
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    (eval_output_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "artifacts": {
                    "stage_run_dir": str(processed_run),
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    log_path = prompt_artifacts.build_codex_farm_prompt_response_log(
        pred_run=eval_output_dir,
        eval_output_dir=eval_output_dir,
        repo_root=tmp_path,
    )

    assert log_path == eval_output_dir / "prompts" / "prompt_request_response_log.txt"
    assert log_path is not None and log_path.exists()
    assert (eval_output_dir / "prompts" / "full_prompt_log.jsonl").exists()
    assert (eval_output_dir / "prompts" / "prompt_recipe_llm_correct_and_link.txt").exists()


def test_build_codex_farm_prompt_response_log_exports_line_role_only_stage_run(
    tmp_path: Path,
) -> None:
    processed_run = tmp_path / "processed" / "2026-03-16_18.11.25"
    prompt_dir = processed_run / "line-role-pipeline" / "prompts" / "line_role"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "line_role_prompt_0001.txt").write_text(
        "line role prompt body\n",
        encoding="utf-8",
    )
    (prompt_dir / "line_role_prompt_response_0001.txt").write_text(
        '[{"atomic_index": 1, "label": "RECIPE_TITLE"}]\n',
        encoding="utf-8",
    )
    (prompt_dir / "line_role_prompt_parsed_0001.json").write_text(
        json.dumps([{"atomic_index": 1, "label": "RECIPE_TITLE"}], indent=2),
        encoding="utf-8",
    )
    (prompt_dir / "parse_errors.json").write_text(
        json.dumps({"parse_error_count": 0, "parse_error_present": False}, indent=2),
        encoding="utf-8",
    )
    schema_path = tmp_path / "line-role.schema.json"
    schema_path.write_text(
        json.dumps({"type": "array"}, indent=2),
        encoding="utf-8",
    )
    (processed_run / "line-role-pipeline" / "telemetry_summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex_backend": "codexfarm",
                "codex_farm_pipeline_id": "line-role.canonical.v1",
                "phases": [
                    {
                        "phase_key": "line_role",
                        "batches": [
                            {
                                "prompt_index": 1,
                                "candidate_count": 3,
                                "requested_atomic_indices": [1, 2, 3],
                                "parse_error": False,
                                "codex_failure": None,
                                "attempt_count": 1,
                                "attempts_with_usage": 1,
                                "attempts": [
                                    {
                                        "attempt_index": 1,
                                        "response_present": True,
                                        "returncode": 0,
                                        "turn_failed_message": None,
                                        "usage": {
                                            "tokens_input": 10,
                                            "tokens_cached_input": 1,
                                            "tokens_output": 2,
                                            "tokens_reasoning": 3,
                                            "tokens_total": 16,
                                        },
                                        "process_run": {
                                            "pipeline_id": "line-role.canonical.v1",
                                            "output_schema_path": str(schema_path),
                                            "process_payload": {
                                                "run_id": "line-role-run-1",
                                                "status": "done",
                                                "pipeline_id": "line-role.canonical.v1",
                                                "codex_model": "gpt-5.3-codex-spark",
                                                "codex_reasoning_effort": "low",
                                            },
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    eval_output_dir = tmp_path / "eval"
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    (eval_output_dir / "line-role-pipeline").mkdir(parents=True, exist_ok=True)
    (eval_output_dir / "line-role-pipeline" / "telemetry_summary.json").write_text(
        json.dumps({"batches": [], "note": "benchmark-root diagnostics only"}, indent=2),
        encoding="utf-8",
    )
    (eval_output_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "source": {"path": str(tmp_path / "book.epub")},
                "artifacts": {
                    "stage_run_dir": str(processed_run),
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    log_path = prompt_artifacts.build_codex_farm_prompt_response_log(
        pred_run=eval_output_dir,
        eval_output_dir=eval_output_dir,
        repo_root=tmp_path,
    )

    assert log_path == eval_output_dir / "prompts" / "prompt_request_response_log.txt"
    assert log_path is not None and log_path.exists()
    assert (eval_output_dir / "prompts" / "prompt_line_role.txt").exists()
    assert (
        eval_output_dir
        / "prompts"
        / "line-role-pipeline"
        / "line_role"
        / "line_role_prompt_0001.txt"
    ).exists()
    assert (
        eval_output_dir
        / "prompts"
        / "line-role-pipeline"
        / "line_role"
        / "line_role_prompt_response_0001.txt"
    ).exists()
    assert (
        eval_output_dir / "prompts" / "line-role-pipeline" / "telemetry_summary.json"
    ).exists()

    full_prompt_rows = [
        json.loads(line)
        for line in (eval_output_dir / "prompts" / "full_prompt_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    row = full_prompt_rows[0]
    assert row["stage_key"] == "line_role"
    assert row["process_run_id"] == "line-role-run-1"
    assert row["request_telemetry"]["tokens_total"] == 16
    assert row["raw_response"]["output_text"].startswith("[{")
    trace_rows = [
        json.loads(line)
        for line in (eval_output_dir / "prompts" / "thinking_trace_summary.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(trace_rows) == 1
    assert trace_rows[0]["stage_key"] == "line_role"
    assert trace_rows[0]["trace_exists"] is False
    assert trace_rows[0]["trace_path"] is None
    manifest_lines = (
        eval_output_dir / "prompts" / "prompt_category_logs_manifest.txt"
    ).read_text(encoding="utf-8").splitlines()
    assert manifest_lines == [str(eval_output_dir / "prompts" / "prompt_line_role.txt")]


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
        stage_order=11,
        stage_dir_name="segmentation_stage",
        stage_key="segmentation",
        stage_heading_key="segmentation",
        stage_label="Segmentation",
        stage_artifact_stem="segmentation",
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
        stage_order=12,
        stage_dir_name="repair_stage",
        stage_key="repair",
        stage_heading_key="repair",
        stage_label="Repair",
        stage_artifact_stem="repair",
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
    assert (eval_output_dir / "prompts" / "prompt_segmentation.txt").exists()
    assert (eval_output_dir / "prompts" / "prompt_repair.txt").exists()

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
        stage_order=21,
        stage_dir_name="linkage_stage",
        stage_key="linkage",
        stage_heading_key="linkage",
        stage_label="Linkage",
        stage_artifact_stem="linkage",
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
    assert (eval_output_dir / "prompts" / "prompt_linkage.txt").exists()

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
        "prompt_recipe_llm_correct_and_link.txt\n",
        encoding="utf-8",
    )
    (prompts_dir / "full_prompt_log.jsonl").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (prompts_dir / "prompt_log_summary.json").write_text(
        json.dumps({"full_prompt_log_rows": 1}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (prompts_dir / "prompt_type_samples_from_full_prompt_log.md").write_text(
        "# samples\n",
        encoding="utf-8",
    )
    (prompts_dir / "thinking_trace_summary.jsonl").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (prompts_dir / "thinking_trace_summary.md").write_text(
        "# trace summary\n",
        encoding="utf-8",
    )

    cli._write_stage_run_manifest(
        run_root=run_root,
        output_root=output_root,
        requested_path=requested_path,
        run_dt=dt.datetime(2026, 3, 3, 12, 0, 0),
        run_config={"llm_recipe_pipeline": "codex-recipe-shard-v1"},
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
    assert artifacts["prompt_log_summary_json"] == (
        "prompts/prompt_log_summary.json"
    )
    assert artifacts["prompt_type_samples_from_full_prompt_log_md"] == (
        "prompts/prompt_type_samples_from_full_prompt_log.md"
    )
    assert artifacts["thinking_trace_summary_jsonl"] == (
        "prompts/thinking_trace_summary.jsonl"
    )
    assert artifacts["thinking_trace_summary_md"] == (
        "prompts/thinking_trace_summary.md"
    )


def test_write_prompt_log_summary_tracks_rows_separately_from_runtime_shards(
    tmp_path: Path,
) -> None:
    full_prompt_log_path = tmp_path / "full_prompt_log.jsonl"
    full_prompt_log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "stage_key": "recipe_llm_correct_and_link",
                        "stage_artifact_stem": "recipe_correction",
                        "runtime_shard_id": "recipe-shard-0000",
                        "runtime_worker_id": "worker-001",
                        "runtime_owned_ids": ["recipe:0"],
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "stage_key": "recipe_llm_correct_and_link",
                        "stage_artifact_stem": "recipe_correction",
                        "runtime_shard_id": "recipe-shard-0000",
                        "runtime_worker_id": "worker-001",
                        "runtime_owned_ids": ["recipe:1"],
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "stage_key": "recipe_llm_correct_and_link",
                        "stage_artifact_stem": "recipe_correction",
                        "runtime_shard_id": "recipe-shard-0001",
                        "runtime_worker_id": "worker-002",
                        "runtime_owned_ids": ["recipe:2"],
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "stage_key": "line_role",
                        "stage_artifact_stem": "line_role",
                        "runtime_shard_id": "line-role-shard-0000",
                        "runtime_worker_id": "worker-003",
                        "runtime_owned_ids": ["line:1", "line:2"],
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary_path = prompt_artifacts.write_prompt_log_summary(
        full_prompt_log_path=full_prompt_log_path,
    )

    assert summary_path == tmp_path / "prompt_log_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["full_prompt_log_rows"] == 4
    assert summary["runtime_shard_count"] == 3
    assert summary["runtime_shard_count_status"] == "complete"
    assert summary["by_stage"]["recipe_llm_correct_and_link"]["row_count"] == 3
    assert (
        summary["by_stage"]["recipe_llm_correct_and_link"]["runtime_shard_count"] == 2
    )
    assert (
        summary["by_stage"]["recipe_llm_correct_and_link"]["runtime_owned_id_count"] == 3
    )
    assert summary["by_stage"]["line_role"]["row_count"] == 1
    assert summary["by_stage"]["line_role"]["runtime_shard_count"] == 1

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
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "codex_farm_cmd": "codex-farm",
                    "workers": 1,
                },
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
                "line_role_pipeline_telemetry_path": str(line_role_telemetry_path),
                "llm_codex_farm": {
                    "process_runs": {
                        "recipe_llm_correct_and_link": {
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
                    "selective_retry_recipe_correction_attempts": 1,
                    "selective_retry_recipe_correction_recovered": 1,
                    "selective_retry_final_recipe_attempts": 1,
                    "selective_retry_final_recipe_recovered": 0,
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
    assert context.run_config["selective_retry_recipe_correction_attempts"] == 1
    assert context.run_config["selective_retry_recipe_correction_recovered"] == 1
    assert context.run_config["selective_retry_final_recipe_attempts"] == 1
    assert context.run_config["selective_retry_final_recipe_recovered"] == 0
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
                "recipe_llm_correct_and_link": {
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
                "build_intermediate_det": {
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
    assert written["by_stage"]["recipe_llm_correct_and_link"]["call_count"] == 2
    assert written["by_stage"]["build_intermediate_det"]["tokens_total"] == 104
    assert written["by_stage"]["knowledge"]["call_count"] == 4
    assert written["by_stage"]["knowledge"]["tokens_total"] == 360
    assert written["by_stage"]["line_role"]["call_count"] == 2
    assert written["by_stage"]["line_role"]["attempt_count"] == 3
    assert written["totals"]["tokens_total"] == 651


def test_prompt_budget_summary_recovers_line_role_tokens_from_nested_batch_summaries(
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
                    "attempt_count": 2,
                },
                "batches": [
                    {
                        "attempts": [
                            {
                                "process_run": {
                                    "process_payload": {
                                        "telemetry_report": {
                                            "summary": {
                                                "matched_rows": 1,
                                                "duration_avg_ms": 1200,
                                                "tokens_total": 17,
                                            }
                                        }
                                    }
                                }
                            }
                        ]
                    },
                    {
                        "attempts": [
                            {
                                "process_run": {
                                    "process_payload": {
                                        "telemetry_report": {
                                            "summary": {
                                                "matched_rows": 1,
                                                "duration_avg_ms": 800,
                                                "tokens_total": 19,
                                            }
                                        }
                                    }
                                }
                            }
                        ]
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = build_prediction_run_prompt_budget_summary(
        {"line_role_pipeline_telemetry_path": str(telemetry_path)},
        pred_run,
    )

    assert summary["by_stage"]["line_role"]["call_count"] == 2
    assert summary["by_stage"]["line_role"]["attempt_count"] == 2
    assert summary["by_stage"]["line_role"]["duration_total_ms"] == 2000
    assert summary["by_stage"]["line_role"]["tokens_total"] == 36
    assert summary["totals"]["tokens_total"] == 36


def test_prompt_budget_summary_reads_top_level_codex_farm_telemetry_rows(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)

    pred_manifest = {
        "llm_codex_farm": {
            "process_runs": {
                "recipe_correction": {
                    "telemetry": {
                        "rows": [
                            {
                                "tokens_input": 100,
                                "tokens_cached_input": 20,
                                "tokens_output": 10,
                                "tokens_reasoning": 0,
                                "tokens_total": 110,
                            },
                            {
                                "tokens_input": 200,
                                "tokens_cached_input": 30,
                                "tokens_output": 15,
                                "tokens_reasoning": 0,
                                "tokens_total": 215,
                            },
                        ]
                    },
                    "telemetry_report": {
                        "summary": {
                            "call_count": 2,
                            "duration_total_ms": 1234,
                            "tokens_total": 325,
                        }
                    },
                }
            },
            "knowledge": {
                "process_run": {
                    "telemetry": {
                        "rows": [
                            {
                                "tokens_input": 50,
                                "tokens_cached_input": 5,
                                "tokens_output": 8,
                                "tokens_reasoning": 1,
                                "tokens_total": 58,
                            }
                        ]
                    },
                    "telemetry_report": {
                        "summary": {
                            "call_count": 1,
                            "duration_total_ms": 456,
                            "tokens_total": 58,
                        }
                    },
                }
            },
        }
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    assert summary["by_stage"]["recipe_correction"]["tokens_input"] == 300
    assert summary["by_stage"]["recipe_correction"]["tokens_cached_input"] == 50
    assert summary["by_stage"]["recipe_correction"]["tokens_output"] == 25
    assert summary["by_stage"]["recipe_correction"]["tokens_total"] == 325
    assert summary["by_stage"]["knowledge"]["tokens_input"] == 50
    assert summary["by_stage"]["knowledge"]["tokens_cached_input"] == 5
    assert summary["by_stage"]["knowledge"]["tokens_output"] == 8
    assert summary["by_stage"]["knowledge"]["tokens_total"] == 58
    assert summary["totals"]["tokens_input"] == 350
    assert summary["totals"]["tokens_cached_input"] == 55
    assert summary["totals"]["tokens_output"] == 33
    assert summary["totals"]["tokens_total"] == 383


def test_prompt_budget_summary_surfaces_pathological_spend_metrics(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)

    pred_manifest = {
        "llm_codex_farm": {
            "knowledge": {
                "counts": {
                    "validated_shards": 1,
                    "invalid_shards": 0,
                    "missing_output_shards": 0,
                },
                "process_run": {
                    "telemetry": {
                        "rows": [
                            {
                                "task_id": "knowledge.ks0001",
                                "tokens_input": 100,
                                "tokens_cached_input": 10,
                                "tokens_output": 20,
                                "tokens_total": 130,
                                "command_execution_count": 2,
                                "reasoning_item_count": 1,
                                "proposal_status": "invalid",
                                "repair_status": "repaired",
                            },
                            {
                                "task_id": "knowledge.ks0001",
                                "tokens_input": 20,
                                "tokens_cached_input": 0,
                                "tokens_output": 5,
                                "tokens_total": 25,
                                "command_execution_count": 0,
                                "reasoning_item_count": 0,
                                "proposal_status": "validated",
                                "repair_status": "repaired",
                                "is_repair_attempt": True,
                            },
                        ]
                    },
                    "telemetry_report": {
                        "summary": {
                            "call_count": 2,
                            "duration_total_ms": 500,
                            "tokens_total": 155,
                        }
                    },
                },
            }
        }
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    knowledge = summary["by_stage"]["knowledge"]
    assert knowledge["command_executing_shard_count"] == 1
    assert knowledge["reasoning_heavy_shard_count"] == 1
    assert knowledge["invalid_output_shard_count"] == 1
    assert knowledge["invalid_output_tokens_total"] == 130
    assert knowledge["repaired_shard_count"] == 1
    assert knowledge["validated_shard_count"] == 1
    assert knowledge["invalid_shard_count"] == 0
    assert "command_execution_detected" in knowledge["pathological_flags"]
    assert summary["totals"]["command_executing_shard_count"] == 1
    assert summary["totals"]["invalid_output_tokens_total"] == 130


def test_prompt_budget_summary_recovers_current_shard_runtime_recipe_and_processed_line_role(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "benchmark-run"
    pred_run.mkdir(parents=True, exist_ok=True)

    benchmark_line_role_path = pred_run / "line-role-pipeline" / "telemetry_summary.json"
    benchmark_line_role_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_line_role_path.write_text(
        json.dumps(
            {
                "schema_version": "line_role_projection.summary.v1",
                "mode": "canonical_projection",
            }
        ),
        encoding="utf-8",
    )

    processed_run_root = tmp_path / "processed-output"
    processed_line_role_path = processed_run_root / "line-role-pipeline" / "telemetry_summary.json"
    processed_line_role_path.parent.mkdir(parents=True, exist_ok=True)
    processed_line_role_path.write_text(
        json.dumps(
            {
                "summary": {
                    "batch_count": 2,
                    "attempt_count": 2,
                    "tokens_input": 500,
                    "tokens_cached_input": 50,
                    "tokens_output": 60,
                    "tokens_reasoning": 0,
                    "tokens_total": 560,
                }
            }
        ),
        encoding="utf-8",
    )

    pred_manifest = {
        "processed_run_root": str(processed_run_root),
        "line_role_pipeline_telemetry_path": str(benchmark_line_role_path),
        "llm_codex_farm": {
            "process_runs": {
                "recipe_correction": {
                    "telemetry_report": {
                        "phase_key": "recipe_llm_correct_and_link",
                        "worker_count": 1,
                        "shard_count": 2,
                    },
                    "worker_runs": [
                        {
                            "telemetry": {
                                "rows": [
                                    {
                                        "duration_ms": 1000,
                                        "tokens_input": 100,
                                        "tokens_cached_input": 10,
                                        "tokens_output": 20,
                                        "tokens_reasoning": 0,
                                        "tokens_total": 120,
                                    },
                                    {
                                        "duration_ms": 1200,
                                        "tokens_input": 150,
                                        "tokens_cached_input": 15,
                                        "tokens_output": 25,
                                        "tokens_reasoning": 0,
                                        "tokens_total": 175,
                                    },
                                ]
                            },
                            "telemetry_report": {
                                "summary": {
                                    "call_count": 2,
                                    "duration_total_ms": 2200,
                                    "tokens_input": 250,
                                    "tokens_cached_input": 25,
                                    "tokens_output": 45,
                                    "tokens_reasoning": 0,
                                    "tokens_total": 295,
                                }
                            },
                        }
                    ],
                }
            },
            "knowledge": {
                "authority_mode": "knowledge_refined_final",
                "scored_effect": "final_authority",
                "process_run": {
                    "telemetry": {
                        "rows": [
                            {
                                "duration_ms": 900,
                                "tokens_input": 200,
                                "tokens_cached_input": 20,
                                "tokens_output": 30,
                                "tokens_reasoning": 0,
                                "tokens_total": 230,
                            }
                        ]
                    },
                    "telemetry_report": {
                        "summary": {
                            "call_count": 1,
                            "duration_total_ms": 900,
                            "tokens_input": 200,
                            "tokens_cached_input": 20,
                            "tokens_output": 30,
                            "tokens_reasoning": 0,
                            "tokens_total": 230,
                        }
                    },
                },
            },
        },
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    assert summary["by_stage"]["recipe_correction"]["call_count"] == 2
    assert summary["by_stage"]["recipe_correction"]["duration_total_ms"] == 2200
    assert summary["by_stage"]["recipe_correction"]["tokens_input"] == 250
    assert summary["by_stage"]["recipe_correction"]["tokens_cached_input"] == 25
    assert summary["by_stage"]["recipe_correction"]["tokens_output"] == 45
    assert summary["by_stage"]["recipe_correction"]["tokens_total"] == 295

    assert summary["by_stage"]["knowledge"]["call_count"] == 1
    assert summary["by_stage"]["knowledge"]["tokens_total"] == 230
    assert summary["by_stage"]["knowledge"]["authority_mode"] == "knowledge_refined_final"
    assert summary["by_stage"]["knowledge"]["scored_effect"] == "final_authority"

    assert summary["by_stage"]["line_role"]["call_count"] == 2
    assert summary["by_stage"]["line_role"]["attempt_count"] == 2
    assert summary["by_stage"]["line_role"]["tokens_input"] == 500
    assert summary["by_stage"]["line_role"]["tokens_total"] == 560

    assert summary["totals"]["call_count"] == 5
    assert summary["totals"]["tokens_input"] == 950
    assert summary["totals"]["tokens_cached_input"] == 95
    assert summary["totals"]["tokens_output"] == 135
    assert summary["totals"]["tokens_total"] == 1085


def test_prompt_budget_summary_sums_call_count_and_duration_across_worker_rows(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)

    pred_manifest = {
        "llm_codex_farm": {
            "process_runs": {
                "recipe_correction": {
                    "telemetry_report": {
                        "phase_key": "recipe_llm_correct_and_link",
                        "worker_count": 2,
                        "shard_count": 2,
                    },
                    "worker_runs": [
                        {
                            "telemetry": {
                                "rows": [
                                    {
                                        "duration_ms": 1100,
                                        "tokens_input": 100,
                                        "tokens_cached_input": 10,
                                        "tokens_output": 20,
                                        "tokens_total": 120,
                                    }
                                ]
                            },
                            "telemetry_report": {
                                "summary": {
                                    "call_count": 1,
                                    "duration_total_ms": 1100,
                                    "tokens_input": 100,
                                    "tokens_cached_input": 10,
                                    "tokens_output": 20,
                                    "tokens_total": 120,
                                }
                            },
                        },
                        {
                            "telemetry": {
                                "rows": [
                                    {
                                        "duration_ms": 1300,
                                        "tokens_input": 150,
                                        "tokens_cached_input": 15,
                                        "tokens_output": 25,
                                        "tokens_total": 175,
                                    }
                                ]
                            },
                            "telemetry_report": {
                                "summary": {
                                    "call_count": 1,
                                    "duration_total_ms": 1300,
                                    "tokens_input": 150,
                                    "tokens_cached_input": 15,
                                    "tokens_output": 25,
                                    "tokens_total": 175,
                                }
                            },
                        },
                    ],
                }
            }
        }
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    assert summary["by_stage"]["recipe_correction"]["call_count"] == 2
    assert summary["by_stage"]["recipe_correction"]["duration_total_ms"] == 2400
    assert summary["by_stage"]["recipe_correction"]["tokens_input"] == 250
    assert summary["by_stage"]["recipe_correction"]["tokens_cached_input"] == 25
    assert summary["by_stage"]["recipe_correction"]["tokens_output"] == 45
    assert summary["by_stage"]["recipe_correction"]["tokens_total"] == 295


def test_prompt_budget_summary_prefers_top_level_knowledge_telemetry_over_worker_duplicates(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)

    duplicated_row = {
        "duration_ms": 900,
        "tokens_input": 200,
        "tokens_cached_input": 20,
        "tokens_output": 30,
        "tokens_reasoning": 0,
        "tokens_total": 230,
    }
    pred_manifest = {
        "llm_codex_farm": {
            "knowledge": {
                "authority_mode": "knowledge_refined_final",
                "scored_effect": "final_authority",
                "process_run": {
                    "telemetry": {
                        "rows": [duplicated_row],
                        "summary": {
                            "call_count": 1,
                            "duration_total_ms": 900,
                            "tokens_input": 200,
                            "tokens_cached_input": 20,
                            "tokens_output": 30,
                            "tokens_reasoning": 0,
                            "tokens_total": 230,
                        },
                    },
                    "worker_runs": [
                        {
                            "telemetry": {"rows": [duplicated_row]},
                            "telemetry_report": {
                                "summary": {
                                    "call_count": 1,
                                    "duration_total_ms": 900,
                                    "tokens_input": 200,
                                    "tokens_cached_input": 20,
                                    "tokens_output": 30,
                                    "tokens_reasoning": 0,
                                    "tokens_total": 230,
                                }
                            },
                        }
                    ],
                },
            }
        }
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    assert summary["by_stage"]["knowledge"]["call_count"] == 1
    assert summary["by_stage"]["knowledge"]["duration_total_ms"] == 900
    assert summary["by_stage"]["knowledge"]["tokens_input"] == 200
    assert summary["by_stage"]["knowledge"]["tokens_cached_input"] == 20
    assert summary["by_stage"]["knowledge"]["tokens_output"] == 30
    assert summary["by_stage"]["knowledge"]["tokens_total"] == 230


def test_prompt_budget_summary_surfaces_knowledge_packet_worker_and_followup_summary(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    stage_root = pred_run / "raw" / "llm" / "book" / "knowledge"
    (stage_root / "proposals").mkdir(parents=True, exist_ok=True)
    (stage_root / "worker_assignments.json").write_text("[]\n", encoding="utf-8")
    (stage_root.parent / "knowledge_manifest.json").write_text(
        json.dumps({"pipeline_id": "recipe.knowledge.compact.v1"}, sort_keys=True),
        encoding="utf-8",
    )
    (stage_root / "task_status.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "task_id": "book.ks0000.nr.task-001",
                        "state": "validated",
                        "last_attempt_type": "main_worker",
                        "terminal_reason_code": "validated",
                        "metadata": {
                            "watchdog_retry_status": "not_attempted",
                            "retry_status": "not_attempted",
                            "repair_status": "not_attempted",
                        },
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "task_id": "book.ks0000.nr.task-002",
                        "state": "retry_recovered",
                        "last_attempt_type": "watchdog_retry",
                        "terminal_reason_code": "validated",
                        "metadata": {
                            "watchdog_retry_status": "recovered",
                            "retry_status": "not_attempted",
                            "repair_status": "not_attempted",
                        },
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "task_id": "book.ks0000.nr.task-003",
                        "state": "repair_failed",
                        "last_attempt_type": "repair",
                        "terminal_reason_code": "repair_skipped_circuit_breaker",
                        "metadata": {
                            "watchdog_retry_status": "not_attempted",
                            "retry_status": "not_attempted",
                            "repair_status": "skipped",
                            "repair_skip_reason_code": "repair_skipped_circuit_breaker",
                        },
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (stage_root / "shard_manifest.jsonl").write_text(
        json.dumps({"shard_id": "book.ks0000.nr"}) + "\n",
        encoding="utf-8",
    )
    (stage_root / "workers" / "worker-001").mkdir(parents=True, exist_ok=True)
    (stage_root / "workers" / "worker-001" / "live_status.json").write_text(
        json.dumps(
            {"state": "completed", "reason_code": "workspace_outputs_stabilized"},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (stage_root / "workers" / "worker-001" / "assigned_tasks.json").write_text(
        json.dumps(
            [
                {"task_id": "book.ks0000.nr.task-001"},
                {"task_id": "book.ks0000.nr.task-002"},
                {"task_id": "book.ks0000.nr.task-003"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (stage_root / "workers" / "worker-001" / "out").mkdir(parents=True, exist_ok=True)
    (stage_root / "workers" / "worker-001" / "out" / "book.ks0000.nr.task-001.json").write_text(
        json.dumps({"v": "2", "bid": "book.ks0000.nr.task-001", "r": []}, sort_keys=True),
        encoding="utf-8",
    )
    (stage_root / "workers" / "worker-001" / "shards" / "book.ks0000.nr.task-001").mkdir(
        parents=True,
        exist_ok=True,
    )
    (stage_root / "workers" / "worker-001" / "shards" / "book.ks0000.nr.task-001" / "proposal.json").write_text(
        json.dumps(
            {
                "status": "validated",
                "validation_metadata": {"response_trailing_eof_trimmed": True},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (stage_root / "workers" / "worker-001" / "shards" / "book.ks0000.nr.task-002" / "watchdog_retry").mkdir(
        parents=True,
        exist_ok=True,
    )
    (stage_root / "workers" / "worker-001" / "shards" / "book.ks0000.nr.task-002" / "watchdog_retry" / "status.json").write_text(
        json.dumps({"status": "validated"}, sort_keys=True),
        encoding="utf-8",
    )
    (stage_root / "workers" / "worker-001" / "shards" / "book.ks0000.nr.task-003").mkdir(
        parents=True,
        exist_ok=True,
    )
    (stage_root / "workers" / "worker-001" / "shards" / "book.ks0000.nr.task-003" / "repair_live_status.json").write_text(
        json.dumps({"state": "running"}, sort_keys=True),
        encoding="utf-8",
    )
    (stage_root / "stage_status.json").write_text(
        json.dumps(
            {
                "schema_version": "knowledge_stage_status.v1",
                "stage_key": "nonrecipe_knowledge_review",
                "stage_state": "completed_with_failures",
                "termination_cause": "completed",
                "finalization_completeness": "complete",
                "artifact_states": {
                    "phase_manifest.json": "present",
                    "shard_manifest.jsonl": "present",
                    "task_manifest.jsonl": "present",
                    "task_status.jsonl": "present",
                    "worker_assignments.json": "present",
                    "promotion_report.json": "present",
                    "telemetry.json": "present",
                    "failures.json": "present",
                    "knowledge_manifest.json": "present",
                    "proposals/*": "present",
                },
                "pre_kill_failure_counts": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    pred_manifest = {
        "llm_codex_farm": {
            "knowledge": {
                "stage_status_path": str(stage_root / "stage_status.json"),
                "task_status_path": str(stage_root / "task_status.jsonl"),
                "worker_assignments_path": str(stage_root / "worker_assignments.json"),
                "process_run": {
                    "telemetry": {
                        "rows": [
                            {
                                "task_id": "book.ks0000.nr.task-001",
                                "prompt_input_mode": "workspace_worker",
                                "worker_session_primary_row": True,
                                "duration_ms": 900,
                                "tokens_input": 100,
                                "tokens_cached_input": 10,
                                "tokens_output": 20,
                                "tokens_total": 130,
                            },
                            {
                                "task_id": "book.ks0000.nr.task-002",
                                "prompt_input_mode": "inline_watchdog_retry",
                                "duration_ms": 400,
                                "tokens_input": 30,
                                "tokens_cached_input": 0,
                                "tokens_output": 15,
                                "tokens_total": 45,
                            },
                        ],
                        "summary": {
                            "call_count": 2,
                            "duration_total_ms": 1300,
                            "tokens_input": 130,
                            "tokens_cached_input": 10,
                            "tokens_output": 35,
                            "tokens_total": 175,
                        },
                    }
                },
            }
        }
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    knowledge_stage = summary["by_stage"]["knowledge"]
    assert knowledge_stage["task_packet_total"] == 3
    assert knowledge_stage["packet_state_counts"] == {
        "repair_failed": 1,
        "retry_recovered": 1,
        "validated": 1,
    }
    assert knowledge_stage["packet_terminal_outcome_counts"] == {
        "repair_failed": 1,
        "retry_recovered": 1,
        "validated": 1,
    }
    assert knowledge_stage["worker_outcome_counts"] == {
        "completed_outputs_stabilized": 1,
    }
    assert knowledge_stage["followup_attempt_counts"] == {
        "repair": 1,
        "watchdog_retry": 1,
    }
    assert knowledge_stage["followup_accepted_counts"] == {"watchdog_retry": 1}
    assert knowledge_stage["stale_followup_count"] == 1
    assert knowledge_stage["circuit_breaker_activation_count"] == 1
    assert knowledge_stage["salvage_success_count"] == 1
    assert knowledge_stage["execution_mode_summary"]["main_workspace_workers"]["call_count"] == 1
    assert knowledge_stage["execution_mode_summary"]["structured_followups"]["call_count"] == 1
    assert knowledge_stage["prompt_input_mode_counts"] == {
        "inline_watchdog_retry": 1,
        "workspace_worker": 1,
    }
    assert summary["totals"]["structured_followup_call_count"] == 1


def test_prompt_budget_summary_reports_recipe_run_count_deviation_from_requested_target(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)

    pred_manifest = {
        "run_config": {
            "recipe_prompt_target_count": 5,
            "recipe_worker_count": 5,
        },
        "llm_codex_farm": {
            "process_runs": {
                "recipe_correction": {
                    "telemetry_report": {
                        "phase_key": "recipe_llm_correct_and_link",
                        "worker_count": 2,
                        "shard_count": 2,
                    },
                    "worker_runs": [
                        {
                            "telemetry": {
                                "rows": [
                                    {
                                        "duration_ms": 1100,
                                        "tokens_input": 100,
                                        "tokens_cached_input": 10,
                                        "tokens_output": 20,
                                        "tokens_total": 120,
                                    },
                                    {
                                        "duration_ms": 1200,
                                        "tokens_input": 140,
                                        "tokens_cached_input": 14,
                                        "tokens_output": 22,
                                        "tokens_total": 176,
                                    },
                                ]
                            },
                            "telemetry_report": {
                                "summary": {
                                    "call_count": 2,
                                    "duration_total_ms": 2300,
                                    "tokens_input": 240,
                                    "tokens_cached_input": 24,
                                    "tokens_output": 42,
                                    "tokens_total": 296,
                                }
                            },
                        }
                    ],
                }
            }
        },
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    recipe_stage = summary["by_stage"]["recipe_correction"]
    assert recipe_stage["requested_run_count"] == 5
    assert recipe_stage["actual_run_count"] == 2
    assert recipe_stage["run_count_status"] == "below_target"
    assert "fit into fewer shards" in recipe_stage["run_count_explanation"]
    assert recipe_stage["requested_worker_count"] == 5
    assert recipe_stage["actual_worker_count"] == 2
    assert len(summary["run_count_deviations"]) == 1
    assert summary["run_count_deviations"][0]["stage"] == "recipe_correction"


def test_prompt_budget_summary_reports_line_role_surface_target_separately_from_total_calls(
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
                    "batch_count": 5,
                    "attempt_count": 5,
                    "tokens_input": 500,
                    "tokens_cached_input": 50,
                    "tokens_output": 60,
                    "tokens_reasoning": 0,
                    "tokens_total": 610,
                },
                "phases": [
                    {
                        "phase_key": "line_role",
                        "summary": {"batch_count": 5},
                        "runtime_artifacts": {"worker_count": 5},
                    },
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    pred_manifest = {
        "run_config": {
            "line_role_prompt_target_count": 5,
            "line_role_worker_count": 5,
        },
        "line_role_pipeline_telemetry_path": str(telemetry_path),
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    line_role_stage = summary["by_stage"]["line_role"]
    assert line_role_stage["requested_run_count"] == 5
    assert line_role_stage["actual_run_count"] == 5
    assert line_role_stage["run_count_status"] == "matched"
    assert line_role_stage["requested_worker_count"] == 5
    assert line_role_stage["actual_worker_count"] == 5
    assert line_role_stage["internal_phase_count"] == 1
    assert line_role_stage["internal_phase_run_counts"] == {"line_role": 5}
    assert line_role_stage["run_count_explanation"] == (
        "Requested 5 run(s) and Line Role used 5 shard(s)."
    )
    assert summary["run_count_deviations"] == []
