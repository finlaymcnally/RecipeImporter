from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def test_co_locate_prediction_run_for_benchmark_moves_into_eval_dir(tmp_path: Path) -> None:
    timestamp_root = tmp_path / "output" / "2026-02-10_21:09:52"
    pred_run = timestamp_root / "labelstudio" / "book"
    pred_run.mkdir(parents=True, exist_ok=True)
    marker = pred_run / "label_studio_tasks.jsonl"
    marker.write_text("{}\n", encoding="utf-8")
    eval_output_dir = tmp_path / "golden" / "sample" / "freeform" / "eval-vs-pipeline" / "2026-02-10_21:09:52"
    eval_output_dir.mkdir(parents=True, exist_ok=True)

    moved = cli._co_locate_prediction_run_for_benchmark(pred_run, eval_output_dir)

    assert moved == eval_output_dir / "prediction-run"
    assert moved.exists()
    assert (moved / "label_studio_tasks.jsonl").exists()
    assert not pred_run.exists()
    assert not (timestamp_root / "labelstudio").exists()
    assert not timestamp_root.exists()

def test_co_locate_prediction_run_for_benchmark_overwrites_existing_target(tmp_path: Path) -> None:
    pred_run = tmp_path / "output" / "2026-02-10_21:09:52" / "labelstudio" / "book"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "new.txt").write_text("new\n", encoding="utf-8")

    eval_output_dir = tmp_path / "golden" / "sample" / "freeform" / "eval-vs-pipeline" / "2026-02-10_21:09:52"
    existing_target = eval_output_dir / "prediction-run"
    existing_target.mkdir(parents=True, exist_ok=True)
    (existing_target / "old.txt").write_text("old\n", encoding="utf-8")

    moved = cli._co_locate_prediction_run_for_benchmark(pred_run, eval_output_dir)

    assert moved.exists()
    assert (moved / "new.txt").exists()
    assert not (moved / "old.txt").exists()

def test_build_codex_farm_prompt_response_log_writes_task_category_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    pass1_in = run_dir / "pass1_chunking" / "in"
    pass1_out = run_dir / "pass1_chunking" / "out"
    pass2_in = run_dir / "pass2_schemaorg" / "in"
    pass2_out = run_dir / "pass2_schemaorg" / "out"
    pass3_in = run_dir / "pass3_final" / "in"
    pass3_out = run_dir / "pass3_final" / "out"
    pass4_in = run_dir / "pass4_knowledge" / "in"
    pass4_out = run_dir / "pass4_knowledge" / "out"
    pass5_in = run_dir / "pass5_tags" / "in"
    pass5_out = run_dir / "pass5_tags" / "out"
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

    (run_dir / "llm_manifest.json").write_text(
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
    (run_dir / "pass4_knowledge_manifest.json").write_text(
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
    (run_dir / "pass5_tags_manifest.json").write_text(
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
    log_path = cli._build_codex_farm_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
    )

    assert log_path == eval_output_dir / "prompts" / "prompt_request_response_log.txt"
    assert log_path is not None and log_path.exists()
    combined = log_path.read_text(encoding="utf-8")
    assert "INPUT pass1 => r0000.json" in combined
    assert "OUTPUT pass3 => r0000.json" in combined

    task1_path = eval_output_dir / "prompts" / "prompt_task1_pass1_chunking.txt"
    task2_path = eval_output_dir / "prompts" / "prompt_task2_pass2_schemaorg.txt"
    task3_path = eval_output_dir / "prompts" / "prompt_task3_pass3_final.txt"
    task4_path = eval_output_dir / "prompts" / "prompt_task4_pass4_knowledge.txt"
    task5_path = eval_output_dir / "prompts" / "prompt_task5_pass5_tags.txt"
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
    assert {str(row.get("pass") or "") for row in full_prompt_rows} == {
        "pass1",
        "pass2",
        "pass3",
        "pass4",
        "pass5",
    }
    pass1_row = next(row for row in full_prompt_rows if row.get("pass") == "pass1")
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
    assert "## pass1 (Chunking)" in prompt_samples
    assert "## pass2 (Schema.org Extraction)" in prompt_samples
    assert "## pass3 (Final Draft)" in prompt_samples
    assert "## pass4 (Knowledge Harvest)" in prompt_samples
    assert "## pass5 (Tag Suggestions)" in prompt_samples
    assert "call_id: `r0000`" in prompt_samples
    assert "Telemetry prompt body" in prompt_samples
    assert "Thinking Trace:" in prompt_samples
    assert "candidate span tightened" in prompt_samples

def test_build_codex_farm_prompt_response_log_handles_missing_pass_dirs(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    pass1_in = run_dir / "pass1_chunking" / "in"
    pass1_out = run_dir / "pass1_chunking" / "out"
    pass1_in.mkdir(parents=True, exist_ok=True)
    pass1_out.mkdir(parents=True, exist_ok=True)
    (pass1_in / "r0000.json").write_text(json.dumps({"prompt_text": "ok"}), encoding="utf-8")
    (pass1_out / "r0000.json").write_text(json.dumps({"result": "ok"}), encoding="utf-8")

    (run_dir / "llm_manifest.json").write_text(
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
    log_path = cli._build_codex_farm_prompt_response_log(
        pred_run=pred_run,
        eval_output_dir=eval_output_dir,
    )
    assert log_path is not None and log_path.exists()
    assert (eval_output_dir / "prompts" / "prompt_task1_pass1_chunking.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_task2_pass2_schemaorg.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_task3_pass3_final.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_task4_pass4_knowledge.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_task5_pass5_tags.txt").exists()
    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    assert full_prompt_rows[0]["pass"] == "pass1"
    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    assert prompt_samples_path.exists()
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## pass1 (Chunking)" in prompt_samples
    assert "## pass2 (Schema.org Extraction)" in prompt_samples
    assert "## pass4 (Knowledge Harvest)" in prompt_samples
    assert "## pass5 (Tag Suggestions)" in prompt_samples
    assert "_No rows captured for this pass._" in prompt_samples

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
        "prompt_task1_pass1_chunking.txt\n",
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
    assert artifacts["codexfarm_dir"] == "prompts"
    assert artifacts["codexfarm_prompt_request_response_txt"] == (
        "prompts/prompt_request_response_log.txt"
    )
    assert artifacts["codexfarm_prompt_category_logs_manifest_txt"] == (
        "prompts/prompt_category_logs_manifest.txt"
    )
    assert artifacts["codexfarm_full_prompt_log_jsonl"] == (
        "prompts/full_prompt_log.jsonl"
    )
    assert artifacts["codexfarm_prompt_type_samples_from_full_prompt_log_md"] == (
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
