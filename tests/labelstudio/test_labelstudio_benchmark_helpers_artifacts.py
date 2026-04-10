from __future__ import annotations

import cookimport.cli_support.bench_artifacts as bench_artifacts
import tests.labelstudio.benchmark_helper_support as _support
from cookimport.llm import prompt_artifacts

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_bench_artifacts_loads_string_block_indices_via_shared_int_helper(
    tmp_path: Path,
) -> None:
    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {
                    "index": "7",
                    "text": "Use the finishing salt.",
                    "location": {"features": {"heading_level": "2"}},
                }
            ]
        ),
        encoding="utf-8",
    )

    indexed = bench_artifacts._load_extracted_archive_blocks(extracted_archive_path)

    assert callable(bench_artifacts._coerce_int)
    assert bench_artifacts._coerce_int("7") == 7
    assert bench_artifacts._coerce_int("not-an-int") is None
    assert indexed == {
        7: {
            "text": "Use the finishing salt.",
            "features": {"heading_level": "2"},
        }
    }


def test_bench_artifacts_rebuilds_prediction_bundle_with_string_timing_metrics(
    tmp_path: Path,
) -> None:
    prediction_record = make_prediction_record(
        example_id="labelstudio-benchmark:test:block:0",
        example_index=0,
        prediction={
            "block_index": "0",
            "pred_label": "OTHER",
            "block_text": "Toast the spices.",
            "block_features": {"heading_level": "2"},
        },
        predict_meta={
            "source_file": str(tmp_path / "book.epub"),
            "source_hash": "source-hash",
            "recipes": "3",
            "timing": {"prediction_seconds": "1.25"},
        },
    )

    bundle = bench_artifacts._build_prediction_bundle_from_records(
        predictions_in=tmp_path / "predictions.jsonl",
        prediction_records=[prediction_record],
        replay_output_dir=tmp_path / "replay",
    )

    assert callable(bench_artifacts._report_optional_metric)
    assert bundle.prediction_phase_seconds == pytest.approx(1.25)
    assert bundle.pred_context.recipes == 3
    assert bundle.stage_predictions_path.exists()
    assert bundle.extracted_archive_path.exists()


def test_bench_artifacts_prefers_semantic_line_role_predictions_for_benchmark(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    line_role_dir = pred_run / "line-role-pipeline"
    line_role_dir.mkdir(parents=True, exist_ok=True)
    route_path = line_role_dir / "line_role_predictions.jsonl"
    semantic_path = line_role_dir / "semantic_line_role_predictions.jsonl"
    route_path.write_text('{"label":"NONRECIPE_CANDIDATE"}\n', encoding="utf-8")
    semantic_path.write_text('{"label":"OTHER"}\n', encoding="utf-8")

    resolved = bench_artifacts._resolve_line_role_predictions_for_benchmark(
        import_result={
            "line_role_pipeline_line_role_predictions_path": str(route_path),
            "line_role_pipeline_semantic_predictions_path": str(semantic_path),
        },
        pred_run=pred_run,
    )

    assert resolved == semantic_path


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


def _build_codex_farm_prompt_log_fixture(tmp_path: Path) -> dict[str, object]:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    recipe_phase_runtime_dir = run_dir / "recipe_phase_runtime"
    correction_in = recipe_phase_runtime_dir / "inputs"
    correction_out = recipe_phase_runtime_dir / "proposals"
    knowledge_in = run_dir / "nonrecipe_finalize" / "in"
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
    correction_worker_root = recipe_phase_runtime_dir / "workers" / "worker-recipe-correction"
    correction_worker_root.mkdir(parents=True, exist_ok=True)
    correction_events = correction_worker_root / "events.jsonl"
    correction_events.write_text(
        "\n".join(
            [
                json.dumps({"type": "thread.started"}, sort_keys=True),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_0",
                            "type": "command_execution",
                            "command": "rg -n trace_path cookimport/llm/prompt_artifacts.py",
                            "exit_code": 0,
                        },
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "type": "response.reasoning_summary_text.delta",
                        "delta": "candidate span tightened",
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_0b",
                            "type": "file_change",
                            "changes": [
                                {
                                    "kind": "update",
                                    "path": str(
                                        correction_worker_root
                                        / "scratch"
                                        / "recipe-correction.json"
                                    ),
                                }
                            ],
                        },
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_1",
                            "type": "agent_message",
                            "text": "Final activity trace message.",
                        },
                    },
                    sort_keys=True,
                ),
                json.dumps({"type": "turn.completed"}, sort_keys=True),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (correction_worker_root / "last_message.json").write_text(
        json.dumps({"text": "Final activity trace message."}, sort_keys=True),
        encoding="utf-8",
    )
    (correction_worker_root / "usage.json").write_text(
        json.dumps({"input_tokens": 111, "output_tokens": 22}, sort_keys=True),
        encoding="utf-8",
    )
    (correction_worker_root / "live_status.json").write_text(
        json.dumps({"state": "completed"}, sort_keys=True),
        encoding="utf-8",
    )
    (correction_worker_root / "workspace_manifest.json").write_text(
        json.dumps({"execution_working_dir": "/tmp/workspace"}, sort_keys=True),
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
                "events_path",
                "last_message_path",
                "usage_path",
                "live_status_path",
                "workspace_manifest_path",
                "stdout_path",
                "stderr_path",
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
                "events_path": str(correction_worker_root / "events.jsonl"),
                "last_message_path": str(correction_worker_root / "last_message.json"),
                "usage_path": str(correction_worker_root / "usage.json"),
                "live_status_path": str(correction_worker_root / "live_status.json"),
                "workspace_manifest_path": str(
                    correction_worker_root / "workspace_manifest.json"
                ),
                "stdout_path": "",
                "stderr_path": "",
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

    return {
        "attached": attached,
        "eval_output_dir": eval_output_dir,
        "log_path": log_path,
    }


def _build_nonrecipe_structured_session_prompt_log_fixture(
    tmp_path: Path,
) -> dict[str, object]:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    runtime_stage_root = run_dir / "nonrecipe_finalize"
    knowledge_in = runtime_stage_root / "in"
    knowledge_out = run_dir / "knowledge" / "out"
    for folder in (knowledge_in, knowledge_out):
        folder.mkdir(parents=True, exist_ok=True)

    shard_id = "book.ks0000.nr"
    worker_id = "worker-001"
    input_file = knowledge_in / "s0000.json"
    output_file = knowledge_out / "s0000.json"
    input_file.write_text(
        json.dumps({"bid": shard_id, "prompt_text": "legacy knowledge prompt"}),
        encoding="utf-8",
    )
    output_file.write_text(
        json.dumps({"result": "legacy knowledge response"}),
        encoding="utf-8",
    )

    (runtime_stage_root / "phase_manifest.json").write_text(
        json.dumps({"pipeline_id": "recipe.knowledge.packet.v1"}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (runtime_stage_root / "worker_assignments.json").write_text(
        json.dumps([{"worker_id": worker_id, "shard_ids": [shard_id]}], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (runtime_stage_root / "shard_manifest.jsonl").write_text(
        json.dumps(
            {
                "shard_id": shard_id,
                "owned_ids": [shard_id],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (runtime_stage_root / "telemetry.json").write_text(
        json.dumps({"rows": []}, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    session_root = (
        runtime_stage_root / "workers" / worker_id / "shards" / shard_id / "structured_session"
    )
    session_root.mkdir(parents=True, exist_ok=True)

    turn_specs = [
        ("classification_initial", {"b": [{"i": 1, "t": "Salt is flavor."}]}, {"rows": [{"block_index": 1, "category": "knowledge"}]}),
        ("grouping_1", {"rows": [{"block_index": 1, "category": "knowledge"}]}, {"rows": [{"block_index": 1, "group_key": "salt"}]}),
        ("grouping_2", {"rows": [{"block_index": 2, "category": "knowledge"}]}, {"rows": [{"block_index": 2, "group_key": "heat"}]}),
    ]
    lineage_turns: list[dict[str, object]] = []
    for index, (turn_kind, packet_payload, response_payload) in enumerate(turn_specs, start=1):
        prompt_path = session_root / f"{turn_kind}_prompt.txt"
        packet_path = session_root / f"{turn_kind}_packet.json"
        response_path = session_root / f"{turn_kind}_response.json"
        events_path = session_root / f"{turn_kind}_events.jsonl"
        last_message_path = session_root / f"{turn_kind}_last_message.json"
        usage_path = session_root / f"{turn_kind}_usage.json"
        workspace_manifest_path = session_root / f"{turn_kind}_workspace_manifest.json"
        prompt_path.write_text(f"{turn_kind} prompt body", encoding="utf-8")
        packet_path.write_text(
            json.dumps(packet_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        response_path.write_text(
            json.dumps(response_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        events_path.write_text(
            "\n".join(
                [
                    json.dumps({"type": "thread.started"}, sort_keys=True),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "agent_message",
                                "text": f"{turn_kind} final message",
                            },
                        },
                        sort_keys=True,
                    ),
                    json.dumps({"type": "turn.completed"}, sort_keys=True),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        last_message_path.write_text(
            json.dumps({"text": f"{turn_kind} final message"}, sort_keys=True),
            encoding="utf-8",
        )
        usage_path.write_text(
            json.dumps(
                {
                    "input_tokens": 100 + index,
                    "cached_input_tokens": 10 * index,
                    "output_tokens": 20 + index,
                    "reasoning_tokens": 0,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        workspace_manifest_path.write_text(
            json.dumps({"execution_working_dir": f"/tmp/{turn_kind}"}, sort_keys=True),
            encoding="utf-8",
        )
        lineage_turns.append(
            {
                "turn_index": index,
                "turn_kind": turn_kind,
                "packet_path": str(packet_path.resolve()),
                "prompt_path": str(prompt_path.resolve()),
                "response_path": str(response_path.resolve()),
            }
        )

    (session_root / "session_lineage.json").write_text(
        json.dumps(
            {
                "schema_version": "structured_session_lineage.v1",
                "assignment_id": f"{worker_id}:{shard_id}",
                "execution_working_dir": str(session_root.resolve()),
                "session_lineage_count": 1,
                "turn_count": len(lineage_turns),
                "turns": lineage_turns,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    (run_dir / "knowledge_manifest.json").write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.knowledge.packet.v1",
                "paths": {
                    "knowledge_in_dir": str(knowledge_in),
                    "proposals_dir": str(knowledge_out),
                },
                "process_run": {
                    "run_id": "run-knowledge-structured",
                },
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
                "codex_farm_model": "manifest-model",
                "codex_farm_reasoning_effort": "low",
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

    return {
        "eval_output_dir": eval_output_dir,
        "log_path": log_path,
    }


def test_build_codex_farm_prompt_response_log_writes_task_category_logs(
    tmp_path: Path,
) -> None:
    fixture = _build_codex_farm_prompt_log_fixture(tmp_path)
    eval_output_dir = fixture["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)
    log_path = fixture["log_path"]
    assert isinstance(log_path, Path)
    attached = fixture["attached"]
    assert isinstance(attached, Path)

    assert log_path == eval_output_dir / "prompts" / "prompt_request_response_log.txt"
    assert log_path is not None and log_path.exists()
    combined = log_path.read_text(encoding="utf-8")
    assert "INPUT recipe_refine => r0000.json" in combined
    recipe_path = eval_output_dir / "prompts" / "prompt_recipe_refine.txt"
    knowledge_path = eval_output_dir / "prompts" / "prompt_nonrecipe_finalize.txt"
    for category_path in (recipe_path, knowledge_path):
        assert category_path.exists()

    recipe_text = recipe_path.read_text(encoding="utf-8")
    assert "ATTACHMENT recipe_refine =>" in recipe_text
    assert str(attached) in recipe_text
    assert "attachment content" in recipe_text

    manifest_path = eval_output_dir / "prompts" / "prompt_category_logs_manifest.txt"
    assert manifest_path.exists()
    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert manifest_lines == [
        str(recipe_path),
        str(knowledge_path),
    ]


def test_build_codex_farm_prompt_response_log_backfills_full_prompt_rows_from_telemetry(
    tmp_path: Path,
) -> None:
    fixture = _build_codex_farm_prompt_log_fixture(tmp_path)
    eval_output_dir = fixture["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)

    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    assert full_prompt_log_path.exists()
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 2
    assert {str(row.get("stage_key") or "") for row in full_prompt_rows} == {
        "recipe_refine",
        "nonrecipe_finalize",
    }
    correction_row = next(
        row
        for row in full_prompt_rows
        if row.get("stage_key") == "recipe_refine"
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
    assert correction_row["request_telemetry"]["events_path"].endswith("events.jsonl")
    assert correction_row["request_telemetry"]["activity_trace_path"].endswith("r0000.json")
    assert correction_row["activity_trace"]["path"].endswith(
        "prompts/activity_traces/r0000.json"
    )
    assert correction_row["activity_trace"]["available"] is True
    assert correction_row["activity_trace"]["command_count"] == 1
    assert correction_row["activity_trace"]["agent_message_count"] == 1
    assert correction_row["activity_trace"]["reasoning_event_count"] == 1
    activity_trace_entries = correction_row["activity_trace"]["entries"]
    assert any(
        str(entry.get("summary") or "").startswith("Ran `rg -n")
        for entry in activity_trace_entries
    )
    assert any(
        entry.get("summary") == "Reasoning summary: candidate span tightened"
        for entry in activity_trace_entries
    )
    file_change_entry = next(
        entry
        for entry in activity_trace_entries
        if entry.get("kind") == "file_change"
    )
    assert "recipe-correction.json" in str(file_change_entry.get("summary") or "")
    assert correction_row["parsed_response"] == {"result": "recipe correction response"}
    assert correction_row["raw_response"]["output_file"].endswith("r0000.json")


def test_build_codex_farm_prompt_response_log_exports_prompt_type_samples(
    tmp_path: Path,
) -> None:
    fixture = _build_codex_farm_prompt_log_fixture(tmp_path)
    eval_output_dir = fixture["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)

    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    assert prompt_samples_path.exists()
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## recipe_refine (Recipe Refine)" in prompt_samples
    assert "## nonrecipe_finalize (Non-Recipe Finalize)" in prompt_samples
    assert "call_id: `r0000`" in prompt_samples
    assert "Telemetry prompt body" in prompt_samples
    assert "Activity Trace:" in prompt_samples
    assert "command_count: `1`" in prompt_samples
    assert "candidate span tightened" in prompt_samples


def test_build_codex_farm_prompt_response_log_writes_activity_trace_summary(
    tmp_path: Path,
) -> None:
    fixture = _build_codex_farm_prompt_log_fixture(tmp_path)
    eval_output_dir = fixture["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)

    activity_trace_summary_jsonl_path = (
        eval_output_dir / "prompts" / "activity_trace_summary.jsonl"
    )
    activity_trace_summary_md_path = (
        eval_output_dir / "prompts" / "activity_trace_summary.md"
    )
    assert activity_trace_summary_jsonl_path.exists()
    assert activity_trace_summary_md_path.exists()
    trace_rows = [
        json.loads(line)
        for line in activity_trace_summary_jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(trace_rows) == 2
    correction_trace_row = next(
        row for row in trace_rows if row.get("stage_key") == "recipe_refine"
    )
    assert correction_trace_row["activity_trace_exists"] is True
    assert correction_trace_row["command_count"] == 1
    assert correction_trace_row["agent_message_count"] == 1
    assert correction_trace_row["reasoning_event_count"] == 1
    assert "candidate span tightened" in str(correction_trace_row["entry_excerpt_lines"])
    trace_summary_md = activity_trace_summary_md_path.read_text(encoding="utf-8")
    assert "# Codex Exec Activity Trace Summary" in trace_summary_md
    assert "- total_rows: `2`" in trace_summary_md
    assert "## recipe_refine (Recipe Refine)" in trace_summary_md


def test_build_codex_farm_prompt_response_log_expands_structured_session_turns(
    tmp_path: Path,
) -> None:
    fixture = _build_nonrecipe_structured_session_prompt_log_fixture(tmp_path)
    eval_output_dir = fixture["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)

    full_prompt_rows = [
        json.loads(line)
        for line in (eval_output_dir / "prompts" / "full_prompt_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 3
    assert [row["runtime_turn_kind"] for row in full_prompt_rows] == [
        "classification_initial",
        "grouping_1",
        "grouping_2",
    ]
    assert [row["runtime_turn_index"] for row in full_prompt_rows] == [1, 2, 3]
    assert {row["runtime_shard_id"] for row in full_prompt_rows} == {"book.ks0000.nr"}
    assert all(row["stage_key"] == "nonrecipe_finalize" for row in full_prompt_rows)
    assert full_prompt_rows[0]["call_id"] == (
        "book.ks0000.nr__turn_01_classification_initial"
    )
    assert (
        full_prompt_rows[0]["request_messages"][0]["content"]
        == "classification_initial prompt body"
    )
    assert full_prompt_rows[0]["request_payload_source"] == "structured_session_prompt_artifact"
    assert full_prompt_rows[0]["request_input_payload"] == {
        "b": [{"i": 1, "t": "Salt is flavor."}]
    }
    assert full_prompt_rows[1]["parsed_response"] == {
        "rows": [{"block_index": 1, "group_key": "salt"}]
    }
    assert full_prompt_rows[2]["request_telemetry"]["tokens_total"] == 156
    assert full_prompt_rows[2]["request_telemetry"]["events_path"].endswith(
        "grouping_2_events.jsonl"
    )
    assert full_prompt_rows[2]["activity_trace"]["available"] is True
    assert full_prompt_rows[2]["activity_trace"]["agent_message_count"] == 1

    summary = json.loads(
        (eval_output_dir / "prompts" / "prompt_log_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["full_prompt_log_rows"] == 3
    assert summary["runtime_shard_count"] == 1
    assert summary["by_stage"]["nonrecipe_finalize"]["row_count"] == 3
    assert summary["by_stage"]["nonrecipe_finalize"]["runtime_shard_count"] == 1

    trace_rows = [
        json.loads(line)
        for line in (eval_output_dir / "prompts" / "activity_trace_summary.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(trace_rows) == 3
    assert [row["call_id"] for row in trace_rows] == [
        "book.ks0000.nr__turn_01_classification_initial",
        "book.ks0000.nr__turn_02_grouping_1",
        "book.ks0000.nr__turn_03_grouping_2",
    ]

    category_log = (
        eval_output_dir / "prompts" / "prompt_nonrecipe_finalize.txt"
    ).read_text(encoding="utf-8")
    assert "PROMPT nonrecipe_finalize => classification_initial" in category_log
    assert "classification_initial prompt body" in category_log
    assert "PACKET nonrecipe_finalize => classification_initial" in category_log
    assert '"Salt is flavor."' in category_log
    assert "OUTPUT nonrecipe_finalize => grouping_2" in category_log


def test_build_codex_farm_activity_trace_summary_reads_exported_trace_json(
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    activity_traces_dir = prompts_dir / "activity_traces"
    activity_traces_dir.mkdir(parents=True, exist_ok=True)

    exported_trace_path = activity_traces_dir / "r0000.json"
    exported_trace_path.write_text(
        json.dumps(
            {
                "schema_version": "prompt_activity_trace.v1",
                "path": str(exported_trace_path),
                "available": True,
                "call_id": "r0000",
                "stage_key": "recipe_refine",
                "command_count": 3,
                "agent_message_count": 1,
                "reasoning_event_count": 0,
                "event_count": 5,
                "entries": [
                    {"summary": "Updated `.../out/r0000.json`"},
                    {"summary": "Agent message: done"},
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    full_prompt_log_path = prompts_dir / "full_prompt_log.jsonl"
    full_prompt_log_path.write_text(
        json.dumps(
            {
                "call_id": "r0000",
                "recipe_id": "recipe:0",
                "stage_key": "recipe_refine",
                "activity_trace": {
                    "path": str(exported_trace_path),
                    "available": False,
                    "command_count": 0,
                    "agent_message_count": 0,
                    "reasoning_event_count": 9,
                    "entries": [{"summary": "stale embedded payload"}],
                },
                "request_telemetry": {
                    "activity_trace_path": str(exported_trace_path),
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    output_jsonl_path = prompts_dir / "activity_trace_summary.jsonl"
    output_md_path = prompts_dir / "activity_trace_summary.md"
    prompt_artifacts.build_codex_farm_activity_trace_summaries(
        full_prompt_log_path=full_prompt_log_path,
        output_jsonl_path=output_jsonl_path,
        output_md_path=output_md_path,
    )

    summary_rows = [
        json.loads(line)
        for line in output_jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(summary_rows) == 1
    summary_row = summary_rows[0]
    assert summary_row["activity_trace_exists"] is True
    assert summary_row["command_count"] == 3
    assert summary_row["agent_message_count"] == 1
    assert summary_row["reasoning_event_count"] == 0
    assert summary_row["entry_excerpt_lines"] == [
        "Updated `.../out/r0000.json`",
        "Agent message: done",
    ]


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


def test_build_codex_farm_prompt_response_log_skips_reconstructed_rows_without_runtime_call_evidence(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    run_dir = pred_run / "raw" / "llm" / "book"
    recipe_phase_runtime_dir = run_dir / "recipe_phase_runtime"
    correction_in = recipe_phase_runtime_dir / "inputs"
    correction_out = recipe_phase_runtime_dir / "proposals"
    worker_001_in = recipe_phase_runtime_dir / "workers" / "worker-001" / "in"
    worker_002_in = recipe_phase_runtime_dir / "workers" / "worker-002" / "in"
    worker_002_root = recipe_phase_runtime_dir / "workers" / "worker-002"
    worker_001_shard_root = (
        recipe_phase_runtime_dir
        / "workers"
        / "worker-001"
        / "shards"
        / "recipe-shard-0000"
    )
    worker_002_shard_root = (
        recipe_phase_runtime_dir
        / "workers"
        / "worker-002"
        / "shards"
        / "recipe-shard-0001"
    )
    for folder in (
        correction_in,
        correction_out,
        worker_001_in,
        worker_002_in,
        worker_001_shard_root,
        worker_002_shard_root,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    (correction_in / "recipe-shard-0000.json").write_text(
        json.dumps({"recipe_id": "recipe:c0", "evidence_rows": [[0, "Dish 0"]]}),
        encoding="utf-8",
    )
    (correction_out / "recipe-shard-0000.json").write_text(
        json.dumps({"recipe_id": "recipe:c0", "canonical_recipe": {"title": "Dish 0"}}),
        encoding="utf-8",
    )
    (correction_in / "recipe-shard-0001.json").write_text(
        json.dumps({"recipe_id": "recipe:c1", "evidence_rows": [[0, "Dish 1"]]}),
        encoding="utf-8",
    )
    (correction_out / "recipe-shard-0001.json").write_text(
        json.dumps({"recipe_id": "recipe:c1", "canonical_recipe": {"title": "Dish 1"}}),
        encoding="utf-8",
    )

    (worker_001_shard_root / "status.json").write_text(
        json.dumps({"finalization_path": "proposals/recipe-shard-0000.json"}, sort_keys=True),
        encoding="utf-8",
    )
    (worker_002_shard_root / "status.json").write_text(
        json.dumps({"finalization_path": "proposals/recipe-shard-0001.json"}, sort_keys=True),
        encoding="utf-8",
    )
    (worker_002_root / "task.json").write_text(
        json.dumps({"stage_key": "recipe_refine"}, sort_keys=True),
        encoding="utf-8",
    )
    (worker_002_root / "prompt.txt").write_text(
        "Observed runtime prompt body\n",
        encoding="utf-8",
    )
    (worker_002_root / "usage.json").write_text(
        json.dumps({"tokens_total": 111}, sort_keys=True),
        encoding="utf-8",
    )
    (worker_002_root / "events.jsonl").write_text(
        json.dumps({"type": "thread.started"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (worker_002_shard_root / "prompt.txt").write_text(
        "Observed shard prompt body\n",
        encoding="utf-8",
    )

    (recipe_phase_runtime_dir / "phase_manifest.json").write_text(
        json.dumps({"pipeline_id": "recipe.correction.compact.v1"}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (recipe_phase_runtime_dir / "worker_assignments.json").write_text(
        json.dumps(
            [
                {"worker_id": "worker-001", "shard_ids": ["recipe-shard-0000"]},
                {"worker_id": "worker-002", "shard_ids": ["recipe-shard-0001"]},
            ],
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (recipe_phase_runtime_dir / "shard_manifest.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "shard_id": "recipe-shard-0000",
                        "owned_ids": ["recipe:c0"],
                        "metadata": {},
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "shard_id": "recipe-shard-0001",
                        "owned_ids": ["recipe:c1"],
                        "metadata": {},
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (recipe_phase_runtime_dir / "telemetry.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "task_id": "recipe-shard-0001",
                        "worker_id": "worker-002",
                        "status": "ok",
                        "duration_ms": 321,
                        "tokens_input": 90,
                        "tokens_cached_input": 9,
                        "tokens_output": 12,
                        "tokens_reasoning": 0,
                        "tokens_total": 111,
                        "prompt_text": "Observed runtime prompt body",
                        "finished_at_utc": "2026-03-19T12:35:56Z",
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
    full_prompt_rows = [
        json.loads(line)
        for line in (eval_output_dir / "prompts" / "full_prompt_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    assert full_prompt_rows[0]["runtime_shard_id"] == "recipe-shard-0001"
    assert full_prompt_rows[0]["request_payload_source"] == "runtime_telemetry"

    summary = json.loads(
        (eval_output_dir / "prompts" / "prompt_log_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["full_prompt_log_rows"] == 1
    assert summary["runtime_shard_count"] == 1
    assert summary["by_stage"]["recipe_refine"]["row_count"] == 1
    assert summary["by_stage"]["recipe_refine"]["runtime_shard_count"] == 1


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
    assert (eval_output_dir / "prompts" / "prompt_recipe_refine.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_nonrecipe_finalize.txt").exists()
    assert not (eval_output_dir / "prompts" / "prompt_tags.txt").exists()
    full_prompt_log_path = eval_output_dir / "prompts" / "full_prompt_log.jsonl"
    full_prompt_rows = [
        json.loads(line)
        for line in full_prompt_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(full_prompt_rows) == 1
    assert full_prompt_rows[0]["stage_key"] == "recipe_refine"
    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    assert prompt_samples_path.exists()
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## recipe_refine (Recipe Refine)" in prompt_samples
    assert "## nonrecipe_finalize (Non-Recipe Finalize)" in prompt_samples
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
    correction_path = eval_output_dir / "prompts" / "prompt_recipe_refine.txt"
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
        if row.get("stage_key") == "recipe_refine"
    )
    assert correction_row["stage_key"] == "recipe_refine"
    assert correction_row["stage_artifact_stem"] == "recipe_refine"
    assert correction_row["stage_label"] == "Recipe Refine"

    prompt_samples_path = (
        eval_output_dir
        / "prompts"
        / "prompt_type_samples_from_full_prompt_log.md"
    )
    prompt_samples = prompt_samples_path.read_text(encoding="utf-8")
    assert "## recipe_refine (Recipe Refine)" in prompt_samples
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
    assert (eval_output_dir / "prompts" / "prompt_recipe_refine.txt").exists()


def _build_line_role_only_prompt_log_fixture(tmp_path: Path) -> dict[str, object]:
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
                "codex_backend": "codex-exec",
                "codex_farm_pipeline_id": "line-role.canonical.v1",
                "phases": [
                    {
                        "phase_key": "line_role",
                        "rows": [
                            {
                                "task_id": "line-role-shard-0001",
                                "events_path": str(
                                    processed_run
                                    / "line-role-pipeline"
                                    / "runtime"
                                    / "line_role"
                                    / "workers"
                                    / "worker-001"
                                    / "events.jsonl"
                                ),
                                "last_message_path": str(
                                    processed_run
                                    / "line-role-pipeline"
                                    / "runtime"
                                    / "line_role"
                                    / "workers"
                                    / "worker-001"
                                    / "last_message.json"
                                ),
                                "usage_path": str(
                                    processed_run
                                    / "line-role-pipeline"
                                    / "runtime"
                                    / "line_role"
                                    / "workers"
                                    / "worker-001"
                                    / "usage.json"
                                ),
                                "live_status_path": str(
                                    processed_run
                                    / "line-role-pipeline"
                                    / "runtime"
                                    / "line_role"
                                    / "workers"
                                    / "worker-001"
                                    / "live_status.json"
                                ),
                                "workspace_manifest_path": str(
                                    processed_run
                                    / "line-role-pipeline"
                                    / "runtime"
                                    / "line_role"
                                    / "workers"
                                    / "worker-001"
                                    / "workspace_manifest.json"
                                ),
                                "stdout_path": str(
                                    processed_run
                                    / "line-role-pipeline"
                                    / "runtime"
                                    / "line_role"
                                    / "workers"
                                    / "worker-001"
                                    / "stdout.txt"
                                ),
                                "stderr_path": str(
                                    processed_run
                                    / "line-role-pipeline"
                                    / "runtime"
                                    / "line_role"
                                    / "workers"
                                    / "worker-001"
                                    / "stderr.txt"
                                ),
                                "duration_ms": 17,
                                "tokens_total": 16,
                                "prompt_input_mode": "taskfile",
                            }
                        ],
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
                                                "events_path": str(
                                                    processed_run
                                                    / "line-role-pipeline"
                                                    / "runtime"
                                                    / "line_role"
                                                    / "workers"
                                                    / "worker-001"
                                                    / "events.jsonl"
                                                ),
                                                "last_message_path": str(
                                                    processed_run
                                                    / "line-role-pipeline"
                                                    / "runtime"
                                                    / "line_role"
                                                    / "workers"
                                                    / "worker-001"
                                                    / "last_message.json"
                                                ),
                                                "usage_path": str(
                                                    processed_run
                                                    / "line-role-pipeline"
                                                    / "runtime"
                                                    / "line_role"
                                                    / "workers"
                                                    / "worker-001"
                                                    / "usage.json"
                                                ),
                                                "live_status_path": str(
                                                    processed_run
                                                    / "line-role-pipeline"
                                                    / "runtime"
                                                    / "line_role"
                                                    / "workers"
                                                    / "worker-001"
                                                    / "live_status.json"
                                                ),
                                                "workspace_manifest_path": str(
                                                    processed_run
                                                    / "line-role-pipeline"
                                                    / "runtime"
                                                    / "line_role"
                                                    / "workers"
                                                    / "worker-001"
                                                    / "workspace_manifest.json"
                                                ),
                                                "stdout_path": str(
                                                    processed_run
                                                    / "line-role-pipeline"
                                                    / "runtime"
                                                    / "line_role"
                                                    / "workers"
                                                    / "worker-001"
                                                    / "stdout.txt"
                                                ),
                                                "stderr_path": str(
                                                    processed_run
                                                    / "line-role-pipeline"
                                                    / "runtime"
                                                    / "line_role"
                                                    / "workers"
                                                    / "worker-001"
                                                    / "stderr.txt"
                                                ),
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
    line_role_worker_root = (
        processed_run / "line-role-pipeline" / "runtime" / "line_role" / "workers" / "worker-001"
    )
    line_role_worker_root.mkdir(parents=True, exist_ok=True)
    (line_role_worker_root / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "thread.started"}, sort_keys=True),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_0",
                            "type": "command_execution",
                            "command": "sed -n '1,10p' prompt.txt",
                            "exit_code": 0,
                        },
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_1",
                            "type": "agent_message",
                            "text": '[{"atomic_index": 1, "label": "RECIPE_TITLE"}]',
                        },
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (line_role_worker_root / "last_message.json").write_text(
        json.dumps(
            {"text": '[{"atomic_index": 1, "label": "RECIPE_TITLE"}]'},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (line_role_worker_root / "usage.json").write_text(
        json.dumps({"tokens_total": 16}, sort_keys=True),
        encoding="utf-8",
    )
    (line_role_worker_root / "live_status.json").write_text(
        json.dumps({"state": "completed"}, sort_keys=True),
        encoding="utf-8",
    )
    (line_role_worker_root / "workspace_manifest.json").write_text(
        json.dumps({"execution_working_dir": "/tmp/line-role"}, sort_keys=True),
        encoding="utf-8",
    )
    (line_role_worker_root / "stdout.txt").write_text("", encoding="utf-8")
    (line_role_worker_root / "stderr.txt").write_text("", encoding="utf-8")

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

    return {
        "eval_output_dir": eval_output_dir,
        "full_prompt_rows": [
            json.loads(line)
            for line in (eval_output_dir / "prompts" / "full_prompt_log.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ],
        "log_path": log_path,
        "manifest_lines": (
            eval_output_dir / "prompts" / "prompt_category_logs_manifest.txt"
        ).read_text(encoding="utf-8").splitlines(),
        "trace_rows": [
            json.loads(line)
            for line in (eval_output_dir / "prompts" / "activity_trace_summary.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ],
    }


def test_build_codex_farm_prompt_response_log_exports_line_role_only_stage_run(
    tmp_path: Path,
) -> None:
    fixture = _build_line_role_only_prompt_log_fixture(tmp_path)
    eval_output_dir = fixture["eval_output_dir"]
    log_path = fixture["log_path"]
    assert isinstance(eval_output_dir, Path)
    assert isinstance(log_path, Path)

    assert log_path == eval_output_dir / "prompts" / "prompt_request_response_log.txt"
    assert log_path.exists()
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


def test_build_codex_farm_prompt_response_log_records_line_role_only_prompt_rows(
    tmp_path: Path,
) -> None:
    fixture = _build_line_role_only_prompt_log_fixture(tmp_path)
    eval_output_dir = fixture["eval_output_dir"]
    full_prompt_rows = fixture["full_prompt_rows"]
    trace_rows = fixture["trace_rows"]
    manifest_lines = fixture["manifest_lines"]
    assert isinstance(eval_output_dir, Path)
    assert isinstance(full_prompt_rows, list)
    assert isinstance(trace_rows, list)
    assert isinstance(manifest_lines, list)

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
    assert row["request_telemetry"]["events_path"].endswith("events.jsonl")
    assert row["activity_trace"]["command_count"] == 1
    assert row["activity_trace"]["agent_message_count"] == 1
    assert row["raw_response"]["output_text"].startswith("[{")
    assert len(trace_rows) == 1
    assert trace_rows[0]["stage_key"] == "line_role"
    assert trace_rows[0]["activity_trace_exists"] is True
    assert trace_rows[0]["activity_trace_path"].endswith(
        "prompts/activity_traces/line_role_prompt_0001.json"
    )
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
        "prompt_recipe_refine.txt\n",
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
    (prompts_dir / "activity_trace_summary.jsonl").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (prompts_dir / "activity_trace_summary.md").write_text(
        "# activity trace summary\n",
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
    assert artifacts["activity_trace_summary_jsonl"] == (
        "prompts/activity_trace_summary.jsonl"
    )
    assert artifacts["activity_trace_summary_md"] == (
        "prompts/activity_trace_summary.md"
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
                        "stage_key": "recipe_refine",
                        "stage_artifact_stem": "recipe_refine",
                        "runtime_shard_id": "recipe-shard-0000",
                        "runtime_worker_id": "worker-001",
                        "runtime_owned_ids": ["recipe:0"],
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "stage_key": "recipe_refine",
                        "stage_artifact_stem": "recipe_refine",
                        "runtime_shard_id": "recipe-shard-0000",
                        "runtime_worker_id": "worker-001",
                        "runtime_owned_ids": ["recipe:1"],
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "stage_key": "recipe_refine",
                        "stage_artifact_stem": "recipe_refine",
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
    assert summary["by_stage"]["recipe_refine"]["row_count"] == 3
    assert (
        summary["by_stage"]["recipe_refine"]["runtime_shard_count"] == 2
    )
    assert (
        summary["by_stage"]["recipe_refine"]["runtime_owned_id_count"] == 3
    )
    assert summary["by_stage"]["line_role"]["row_count"] == 1
    assert summary["by_stage"]["line_role"]["runtime_shard_count"] == 1


def test_write_prompt_log_summary_backfills_line_role_sidecar_stage(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "benchmark-run"
    prompts_dir = run_root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    full_prompt_log_path = prompts_dir / "full_prompt_log.jsonl"
    full_prompt_log_path.write_text(
        json.dumps(
            {
                "stage_key": "recipe_refine",
                "stage_artifact_stem": "recipe_refine",
                "runtime_shard_id": "recipe-shard-0000",
                "runtime_worker_id": "worker-001",
                "runtime_owned_ids": ["recipe:0"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    telemetry_summary_path = run_root / "line-role-pipeline" / "telemetry_summary.json"
    telemetry_summary_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry_summary_path.write_text(
        json.dumps(
            {
                "schema_version": "line_role_final_authority_projection.v1",
                "mode": "final_authority_projection",
                "changed_block_count": 0,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    summary_path = prompt_artifacts.write_prompt_log_summary(
        full_prompt_log_path=full_prompt_log_path,
    )

    assert summary_path == prompts_dir / "prompt_log_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["full_prompt_log_rows"] == 1
    assert summary["by_stage"]["line_role"]["row_count"] == 0
    assert summary["by_stage"]["line_role"]["artifact_presence"] == "sidecar_only"
    assert summary["by_stage"]["line_role"]["artifact_evidence_mode"] == (
        "final_authority_projection"
    )
    assert summary["by_stage"]["line_role"]["artifact_evidence_path"] == str(
        telemetry_summary_path
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
    _patch_cli_attr(monkeypatch, "default_codex_reasoning_effort", lambda cmd=None: None)

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
                        "recipe_refine": {
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
