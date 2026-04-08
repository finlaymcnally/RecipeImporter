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
                    "visible_input_tokens": 20,
                    "visible_output_tokens": 7,
                    "wrapper_overhead_tokens": 37,
                }
            }
        ),
        encoding="utf-8",
    )
    pred_manifest = {
        "line_role_pipeline_telemetry_path": str(telemetry_path),
        "llm_codex_farm": {
            "process_runs": {
                "recipe_refine": {
                    "telemetry_report": {
                        "summary": {
                            "call_count": 2,
                            "duration_total_ms": 1200,
                            "tokens_input": 101,
                            "tokens_cached_input": 9,
                            "tokens_output": 12,
                            "tokens_reasoning": 1,
                            "tokens_total": 123,
                            "visible_input_tokens": 60,
                            "visible_output_tokens": 12,
                            "wrapper_overhead_tokens": 51,
                        }
                    }
                },
                "recipe_build_intermediate": {
                    "telemetry_report": {
                        "summary": {
                            "call_count": 1,
                            "duration_total_ms": 2200,
                            "tokens_input": 80,
                            "tokens_cached_input": 0,
                            "tokens_output": 20,
                            "tokens_reasoning": 4,
                            "tokens_total": 104,
                            "visible_input_tokens": 45,
                            "visible_output_tokens": 20,
                            "wrapper_overhead_tokens": 39,
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
                            "visible_input_tokens": 140,
                            "visible_output_tokens": 60,
                            "wrapper_overhead_tokens": 160,
                        }
                    }
                }
            },
        },
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)
    summary_path = write_prediction_run_prompt_budget_summary(pred_run, summary)

    written = json.loads(summary_path.read_text(encoding="utf-8"))
    assert written["by_stage"]["recipe_refine"]["call_count"] == 2
    assert written["by_stage"]["recipe_refine"]["semantic_payload_tokens_total"] == 72
    assert written["by_stage"]["recipe_refine"]["protocol_overhead_tokens_total"] == 51
    assert written["by_stage"]["recipe_build_intermediate"]["tokens_total"] == 104
    assert written["by_stage"]["nonrecipe_finalize"]["call_count"] == 4
    assert written["by_stage"]["nonrecipe_finalize"]["tokens_total"] == 360
    assert written["by_stage"]["nonrecipe_finalize"]["semantic_payload_tokens_total"] == 200
    assert written["by_stage"]["line_role"]["call_count"] == 2
    assert written["by_stage"]["line_role"]["attempt_count"] == 3
    assert written["by_stage"]["line_role"]["semantic_payload_tokens_total"] == 27
    assert written["by_stage"]["line_role"]["protocol_overhead_tokens_total"] == 37
    assert written["totals"]["tokens_total"] == 651
    assert written["totals"]["semantic_payload_tokens_total"] == 364
    assert written["totals"]["protocol_overhead_tokens_total"] == 287


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


def test_prompt_budget_summary_marks_line_role_partial_token_usage_unavailable(
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
                    "attempts_with_usage": 1,
                    "attempts_without_usage": 1,
                    "tokens_input": 40,
                    "tokens_cached_input": 3,
                    "tokens_output": 5,
                    "tokens_reasoning": 0,
                    "tokens_total": 48,
                    "visible_input_tokens": 90,
                    "visible_output_tokens": 8,
                    "command_execution_count_total": 2,
                }
            }
        ),
        encoding="utf-8",
    )

    summary = build_prediction_run_prompt_budget_summary(
        {"line_role_pipeline_telemetry_path": str(telemetry_path)},
        pred_run,
    )

    assert summary["by_stage"]["line_role"]["token_usage_status"] == "partial"
    assert summary["by_stage"]["line_role"]["token_usage_available_call_count"] == 1
    assert summary["by_stage"]["line_role"]["token_usage_missing_call_count"] == 1
    assert summary["by_stage"]["line_role"]["tokens_total"] is None
    assert summary["by_stage"]["line_role"]["visible_input_tokens"] is None
    assert "token_usage_incomplete" in summary["by_stage"]["line_role"]["pathological_flags"]
    assert summary["totals"]["token_usage_status"] == "partial"
    assert summary["totals"]["tokens_total"] is None


def test_prompt_budget_summary_marks_bad_line_role_zero_tokens_unavailable(
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
                    "attempts_with_usage": 2,
                    "attempts_without_usage": 0,
                    "tokens_input": 0,
                    "tokens_cached_input": 0,
                    "tokens_output": 0,
                    "tokens_reasoning": 0,
                    "tokens_total": 0,
                    "visible_input_tokens": 90,
                    "visible_output_tokens": 8,
                    "command_execution_count_total": 2,
                }
            }
        ),
        encoding="utf-8",
    )

    summary = build_prediction_run_prompt_budget_summary(
        {"line_role_pipeline_telemetry_path": str(telemetry_path)},
        pred_run,
    )

    assert summary["by_stage"]["line_role"]["token_usage_status"] == "unavailable"
    assert summary["by_stage"]["line_role"]["token_usage_available_call_count"] == 0
    assert summary["by_stage"]["line_role"]["token_usage_missing_call_count"] == 2
    assert summary["by_stage"]["line_role"]["tokens_total"] is None
    assert summary["totals"]["token_usage_status"] == "unavailable"
    assert summary["totals"]["tokens_total"] is None


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

    assert summary["by_stage"]["recipe_refine"]["tokens_input"] == 300
    assert summary["by_stage"]["recipe_refine"]["tokens_cached_input"] == 50
    assert summary["by_stage"]["recipe_refine"]["tokens_output"] == 25
    assert summary["by_stage"]["recipe_refine"]["tokens_total"] == 325
    assert summary["by_stage"]["nonrecipe_finalize"]["tokens_input"] == 50
    assert summary["by_stage"]["nonrecipe_finalize"]["tokens_cached_input"] == 5
    assert summary["by_stage"]["nonrecipe_finalize"]["tokens_output"] == 8
    assert summary["by_stage"]["nonrecipe_finalize"]["tokens_total"] == 58
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
                    "no_final_output_shards": 0,
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

    knowledge = summary["by_stage"]["nonrecipe_finalize"]
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


def _build_current_shard_runtime_budget_summary_fixture(tmp_path: Path) -> dict[str, object]:
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
                        "phase_key": "recipe_refine",
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
    return {"summary": summary}


def test_prompt_budget_summary_recovers_current_shard_runtime_recipe_and_knowledge(
    tmp_path: Path,
) -> None:
    fixture = _build_current_shard_runtime_budget_summary_fixture(tmp_path)
    summary = fixture["summary"]
    assert isinstance(summary, dict)

    assert summary["by_stage"]["recipe_refine"]["call_count"] == 2
    assert summary["by_stage"]["recipe_refine"]["duration_total_ms"] == 2200
    assert summary["by_stage"]["recipe_refine"]["tokens_input"] == 250
    assert summary["by_stage"]["recipe_refine"]["tokens_cached_input"] == 25
    assert summary["by_stage"]["recipe_refine"]["tokens_output"] == 45
    assert summary["by_stage"]["recipe_refine"]["tokens_total"] == 295

    assert summary["by_stage"]["nonrecipe_finalize"]["call_count"] == 1
    assert summary["by_stage"]["nonrecipe_finalize"]["tokens_total"] == 230
    assert summary["by_stage"]["nonrecipe_finalize"]["authority_mode"] == "knowledge_refined_final"
    assert summary["by_stage"]["nonrecipe_finalize"]["scored_effect"] == "final_authority"


def test_prompt_budget_summary_recovers_processed_line_role_and_totals(
    tmp_path: Path,
) -> None:
    fixture = _build_current_shard_runtime_budget_summary_fixture(tmp_path)
    summary = fixture["summary"]
    assert isinstance(summary, dict)

    assert summary["by_stage"]["line_role"]["call_count"] == 2
    assert summary["by_stage"]["line_role"]["attempt_count"] == 2
    assert summary["by_stage"]["line_role"]["tokens_input"] == 500
    assert summary["by_stage"]["line_role"]["tokens_total"] == 560

    assert summary["totals"]["call_count"] == 5
    assert summary["totals"]["tokens_input"] == 950
    assert summary["totals"]["tokens_cached_input"] == 95
    assert summary["totals"]["tokens_output"] == 135
    assert summary["totals"]["tokens_total"] == 1085


def test_prompt_budget_summary_attaches_recipe_runtime_guardrails(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    stage_root = pred_run / "raw" / "llm" / "book" / "recipe_phase_runtime"
    (stage_root / "proposals").mkdir(parents=True, exist_ok=True)
    (stage_root / "workers" / "worker-001" / "out").mkdir(parents=True, exist_ok=True)
    (stage_root / "workers" / "worker-001" / "shards" / "recipe-shard-0001").mkdir(
        parents=True, exist_ok=True
    )
    (stage_root / "worker_assignments.json").write_text("[]\n", encoding="utf-8")
    (stage_root / "task_manifest.jsonl").write_text(
        json.dumps({"task_id": "recipe-shard-0001.task-001"}) + "\n",
        encoding="utf-8",
    )
    (stage_root / "workers" / "worker-001" / "out" / "recipe-shard-0001.task-001.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (stage_root / "workers" / "worker-001" / "shards" / "recipe-shard-0001" / "status.json").write_text(
        json.dumps({"status": "validated"}, sort_keys=True),
        encoding="utf-8",
    )
    (stage_root / "phase_manifest.json").write_text(
        json.dumps(
            {
                "worker_count": 1,
                "shard_count": 1,
                "runtime_metadata": {
                    "worker_session_guardrails": {
                        "planned_happy_path_worker_cap": 1,
                        "actual_happy_path_worker_sessions": 1,
                        "repair_worker_session_count": 0,
                        "repair_followup_call_count": 0,
                        "cap_exceeded": False,
                        "happy_path_within_cap": True,
                        "status": "within_cap",
                    },
                    "task_file_guardrails": {
                        "assignment_count": 1,
                        "warning_count": 1,
                        "largest_assignment": {
                            "worker_id": "worker-001",
                            "task_file_bytes": 24576,
                            "task_file_estimated_tokens": 5000,
                        },
                    },
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (stage_root / "promotion_report.json").write_text(
        json.dumps(
            {
                "invalid_shards": 0,
                "missing_output_shards": 0,
                "recipe_result_counts": {"repaired": 1, "fragmentary": 0, "not_a_recipe": 0},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (stage_root.parent / "recipe_manifest.json").write_text(
        json.dumps(
            {
                "counts": {
                    "recipes_total": 1,
                    "recipe_correction_error": 0,
                    "final_recipe_authority_promoted": 1,
                    "final_recipe_authority_not_promoted": 0,
                    "final_recipe_authority_error": 0,
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    pred_manifest = {
        "run_config": {
            "recipe_prompt_target_count": 1,
            "recipe_worker_count": 1,
        },
        "llm_codex_farm": {
            "process_runs": {
                "recipe_correction": {
                    "phase_manifest_path": str(stage_root / "phase_manifest.json"),
                    "worker_assignments_path": str(stage_root / "worker_assignments.json"),
                    "promotion_report_path": str(stage_root / "promotion_report.json"),
                    "proposals_dir": str(stage_root / "proposals"),
                    "telemetry": {
                        "rows": [
                            {
                                "duration_ms": 1200,
                                "tokens_input": 100,
                                "tokens_cached_input": 10,
                                "tokens_output": 20,
                                "tokens_reasoning": 0,
                                "tokens_total": 130,
                                "prompt_input_mode": "taskfile",
                                "worker_session_primary_row": True,
                            }
                        ]
                    },
                    "telemetry_report": {
                        "summary": {
                            "call_count": 1,
                            "duration_total_ms": 1200,
                            "tokens_input": 100,
                            "tokens_cached_input": 10,
                            "tokens_output": 20,
                            "tokens_total": 130,
                        }
                    },
                }
            }
        },
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    recipe_stage = summary["by_stage"]["recipe_refine"]
    assert recipe_stage["planned_happy_path_worker_cap"] == 1
    assert recipe_stage["actual_happy_path_worker_sessions"] == 1
    assert recipe_stage["task_file_guardrails"]["warning_count"] == 1


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
                        "phase_key": "recipe_refine",
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
                                        "codex_transport": "inline-json-v1",
                                        "codex_policy_mode": "shell_disabled",
                                        "codex_shell_tool_enabled": False,
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
                                        "codex_transport": "inline-json-v1",
                                        "codex_policy_mode": "shell_disabled",
                                        "codex_shell_tool_enabled": False,
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

    assert summary["by_stage"]["recipe_refine"]["call_count"] == 2
    assert summary["by_stage"]["recipe_refine"]["duration_total_ms"] == 2400
    assert summary["by_stage"]["recipe_refine"]["tokens_input"] == 250
    assert summary["by_stage"]["recipe_refine"]["tokens_cached_input"] == 25
    assert summary["by_stage"]["recipe_refine"]["tokens_output"] == 45
    assert summary["by_stage"]["recipe_refine"]["tokens_total"] == 295
    assert summary["by_stage"]["recipe_refine"]["codex_transport"] == "inline-json-v1"
    assert summary["by_stage"]["recipe_refine"]["codex_policy_mode"] == "shell_disabled"
    assert summary["by_stage"]["recipe_refine"]["codex_shell_tool_enabled"] is False


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

    assert summary["by_stage"]["nonrecipe_finalize"]["call_count"] == 1
    assert summary["by_stage"]["nonrecipe_finalize"]["duration_total_ms"] == 900
    assert summary["by_stage"]["nonrecipe_finalize"]["tokens_input"] == 200
    assert summary["by_stage"]["nonrecipe_finalize"]["tokens_cached_input"] == 20
    assert summary["by_stage"]["nonrecipe_finalize"]["tokens_output"] == 30
    assert summary["by_stage"]["nonrecipe_finalize"]["tokens_total"] == 230


def test_prompt_budget_summary_marks_partial_taskfile_worker_token_usage_unavailable(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)

    pred_manifest = {
        "llm_codex_farm": {
            "knowledge": {
                "process_run": {
                    "worker_runs": [
                        {
                            "telemetry": {
                                "summary": {
                                    "call_count": 1,
                                    "duration_total_ms": 900,
                                    "tokens_input": 200,
                                    "tokens_cached_input": 20,
                                    "tokens_output": 30,
                                    "tokens_reasoning": 0,
                                    "tokens_total": 250,
                                    "visible_input_tokens": 40,
                                    "visible_output_tokens": 8,
                                    "wrapper_overhead_tokens": 2,
                                    "prompt_input_mode_counts": {"taskfile": 1},
                                }
                            }
                        },
                        {
                            "telemetry": {
                                "summary": {
                                    "call_count": 1,
                                    "duration_total_ms": 1200,
                                    "tokens_input": 0,
                                    "tokens_cached_input": 0,
                                    "tokens_output": 0,
                                    "tokens_reasoning": 0,
                                    "tokens_total": 0,
                                    "visible_input_tokens": 55,
                                    "visible_output_tokens": 5,
                                    "wrapper_overhead_tokens": 0,
                                    "command_execution_count_total": 12,
                                    "prompt_input_mode_counts": {"taskfile": 1},
                                }
                            }
                        },
                    ]
                }
            }
        }
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    knowledge = summary["by_stage"]["nonrecipe_finalize"]
    assert knowledge["call_count"] == 2
    assert knowledge["token_usage_status"] == "partial"
    assert knowledge["token_usage_available_call_count"] == 1
    assert knowledge["token_usage_missing_call_count"] == 1
    assert knowledge["tokens_input"] is None
    assert knowledge["tokens_cached_input"] is None
    assert knowledge["tokens_output"] is None
    assert knowledge["tokens_total"] is None
    assert knowledge["cost_breakdown"]["billed_total_tokens"] is None
    assert "token_usage_incomplete" in knowledge["pathological_flags"]

    assert summary["totals"]["token_usage_status"] == "partial"
    assert summary["totals"]["token_usage_available_call_count"] == 1
    assert summary["totals"]["token_usage_missing_call_count"] == 1
    assert summary["totals"]["tokens_total"] is None
    assert summary["totals"]["cost_breakdown"]["billed_total_tokens"] is None
    assert "token_usage_incomplete" in summary["totals"]["pathological_flags"]


def _build_knowledge_prompt_budget_summary_fixture(tmp_path: Path) -> dict[str, object]:
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
                        "last_attempt_type": "deterministic_bypass",
                        "terminal_reason_code": "deterministic_other_bypass",
                        "metadata": {
                            "deterministic_bypass_reason_code": "book_framing_or_marketing",
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
                "stage_key": "nonrecipe_finalize",
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
    (stage_root / "telemetry.json").write_text(
        json.dumps(
            {
                "summary": {
                    "visible_input_tokens": 90,
                    "visible_output_tokens": 30,
                    "wrapper_overhead_tokens": 60,
                    "tokens_reasoning": 0,
                    "tokens_total": 180,
                    "packet_economics": {
                        "packet_count_total": 3,
                        "primary_packet_count_total": 2,
                        "repair_packet_count_total": 1,
                        "owned_row_count_total": 3,
                        "packet_churn_count": 1,
                        "packets_per_shard": 3.0,
                        "repair_packet_share": 0.3333,
                        "packets_per_owned_row": 1.0,
                        "cost_per_owned_row": 60.0,
                        "visible_input_tokens_per_owned_row": 30.0,
                        "visible_output_tokens_per_owned_row": 10.0,
                        "wrapper_overhead_tokens_per_owned_row": 20.0,
                        "reasoning_tokens_per_owned_row": 0.0,
                        "semantic_payload_tokens_total": 120,
                        "semantic_payload_tokens_per_owned_row": 40.0,
                        "protocol_overhead_tokens_total": 60,
                        "protocol_overhead_share": 0.3333,
                    },
                }
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (stage_root / "phase_plan.json").write_text(
        json.dumps(
            {
                "schema_version": "codex_phase_plan.v1",
                "stage_key": "nonrecipe_finalize",
                "stage_label": "Nonrecipe Finalize",
                "requested_shard_count": 10,
                "budget_native_shard_count": 24,
                "launch_shard_count": 10,
                "survivability_recommended_shard_count": 12,
                "planning_warnings": [
                    "knowledge_prompt_target_count is using the requested final shard count of 10; packet-budget planning would have split the queue into 24 shards."
                ],
                "survivability": {
                    "totals": {
                        "estimated_input_tokens": 150,
                        "estimated_output_tokens": 30,
                        "estimated_followup_tokens": 20,
                        "estimated_peak_session_tokens": 200,
                    }
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (stage_root / "phase_plan_summary.json").write_text(
        json.dumps(
            {
                "schema_version": "codex_phase_plan_summary.v1",
                "requested_shard_count": 10,
                "budget_native_shard_count": 24,
                "launch_shard_count": 10,
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
                                "prompt_input_mode": "taskfile",
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
    return {
        "knowledge_stage": summary["by_stage"]["nonrecipe_finalize"],
        "summary": summary,
    }


def test_prompt_budget_summary_surfaces_knowledge_packet_and_followup_counts(
    tmp_path: Path,
) -> None:
    fixture = _build_knowledge_prompt_budget_summary_fixture(tmp_path)
    knowledge_stage = fixture["knowledge_stage"]
    assert isinstance(knowledge_stage, dict)

    assert knowledge_stage["task_packet_total"] == 3
    assert knowledge_stage["deterministic_bypass_total"] == 1
    assert knowledge_stage["llm_review_task_packet_total"] == 2
    assert knowledge_stage["deterministic_bypass_reason_code_counts"] == {
        "book_framing_or_marketing": 1,
    }
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
    assert knowledge_stage["no_final_output_shard_count"] == 0
    assert knowledge_stage["no_final_output_reason_code_counts"] == {}
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


def test_prompt_budget_summary_surfaces_knowledge_execution_mode_rollups(
    tmp_path: Path,
) -> None:
    fixture = _build_knowledge_prompt_budget_summary_fixture(tmp_path)
    knowledge_stage = fixture["knowledge_stage"]
    summary = fixture["summary"]
    assert isinstance(knowledge_stage, dict)
    assert isinstance(summary, dict)

    assert knowledge_stage["execution_mode_summary"]["main_taskfile_workers"]["call_count"] == 1
    assert knowledge_stage["execution_mode_summary"]["structured_followups"]["call_count"] == 1
    assert knowledge_stage["prompt_input_mode_counts"] == {
        "inline_watchdog_retry": 1,
        "taskfile": 1,
    }
    assert summary["totals"]["structured_followup_call_count"] == 1
    assert knowledge_stage["packet_count_total"] == 3
    assert knowledge_stage["repair_packet_count_total"] == 1
    assert knowledge_stage["cost_per_owned_row"] == 60.0
    assert knowledge_stage["protocol_overhead_share"] == 0.3333
    assert knowledge_stage["packet_economics"]["semantic_payload_tokens_total"] == 120
    assert knowledge_stage["requested_shard_count"] == 10
    assert knowledge_stage["budget_native_shard_count"] == 24
    assert knowledge_stage["launch_shard_count"] == 10
    assert knowledge_stage["survivability_recommended_shard_count"] == 12
    assert knowledge_stage["phase_plan_path"].endswith("phase_plan.json")
    assert knowledge_stage["phase_plan_summary_path"].endswith("phase_plan_summary.json")
    assert knowledge_stage["prediction_drift"] == {
        "predicted_input_tokens": 150,
        "observed_input_tokens": 130,
        "input_token_delta": -20,
        "predicted_output_tokens": 30,
        "observed_output_tokens": 35,
        "output_token_delta": 5,
        "predicted_followup_tokens": 20,
        "predicted_peak_session_tokens": 200,
        "observed_billed_total_tokens": 175,
        "billed_total_minus_predicted_peak_session_tokens": -25,
    }


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
                        "phase_key": "recipe_refine",
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
                                    {
                                        "duration_ms": 900,
                                        "tokens_input": 90,
                                        "tokens_cached_input": 9,
                                        "tokens_output": 18,
                                        "tokens_total": 117,
                                    },
                                ]
                            },
                            "telemetry_report": {
                                "summary": {
                                    "call_count": 3,
                                    "duration_total_ms": 3200,
                                    "tokens_input": 330,
                                    "tokens_cached_input": 33,
                                    "tokens_output": 60,
                                    "tokens_total": 413,
                                }
                            },
                        }
                    ],
                }
            }
        },
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)

    recipe_stage = summary["by_stage"]["recipe_refine"]
    assert recipe_stage["requested_run_count"] == 5
    assert recipe_stage["actual_run_count"] == 2
    assert recipe_stage["call_count"] == 3
    assert recipe_stage["run_count_status"] == "below_target"
    assert "fit into fewer shards" in recipe_stage["run_count_explanation"]
    assert recipe_stage["requested_worker_count"] == 5
    assert recipe_stage["actual_worker_count"] == 2
    assert len(summary["run_count_deviations"]) == 1
    assert summary["run_count_deviations"][0]["stage"] == "recipe_refine"


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


def test_prompt_budget_summary_uses_top_level_llm_runtime_for_recipe_phase_plan(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    recipe_root = pred_run / "raw" / "llm" / "book" / "recipe_phase_runtime"
    recipe_root.mkdir(parents=True, exist_ok=True)
    (recipe_root / "phase_plan.json").write_text(
        json.dumps(
            {
                "schema_version": "codex_phase_plan.v1",
                "stage_key": "recipe_refine",
                "requested_shard_count": 5,
                "budget_native_shard_count": 5,
                "launch_shard_count": 5,
                "survivability_recommended_shard_count": 4,
                "planning_warnings": [],
                "survivability": {
                    "totals": {
                        "estimated_input_tokens": 100,
                        "estimated_output_tokens": 20,
                        "estimated_followup_tokens": 10,
                        "estimated_peak_session_tokens": 140,
                    }
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (recipe_root / "phase_plan_summary.json").write_text(
        json.dumps(
            {
                "schema_version": "codex_phase_plan_summary.v1",
                "requested_shard_count": 5,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    pred_manifest = {
        "llm_codex_farm": {
            "llmRawDir": str(pred_run / "raw" / "llm" / "book"),
            "phase_runtime": {
                "phase_plan_path": str(recipe_root / "phase_plan.json"),
                "phase_plan_summary_path": str(recipe_root / "phase_plan_summary.json"),
            },
            "process_runs": {
                "recipe_correction": {
                    "telemetry": {
                        "rows": [
                            {
                                "task_id": "recipe-001",
                                "duration_ms": 1000,
                                "tokens_input": 90,
                                "tokens_output": 30,
                                "tokens_total": 120,
                            }
                        ]
                    }
                }
            },
        }
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)
    recipe_stage = summary["by_stage"]["recipe_refine"]

    assert recipe_stage["requested_shard_count"] == 5
    assert recipe_stage["survivability_recommended_shard_count"] == 4
    assert recipe_stage["phase_plan_path"].endswith("phase_plan.json")


def test_prompt_budget_summary_uses_stage_run_root_for_line_role_phase_plan(
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "prediction-run"
    line_role_root = pred_run / "line-role-pipeline" / "runtime" / "line_role"
    line_role_root.mkdir(parents=True, exist_ok=True)
    (line_role_root / "phase_plan.json").write_text(
        json.dumps(
            {
                "schema_version": "codex_phase_plan.v1",
                "stage_key": "line_role",
                "requested_shard_count": 5,
                "budget_native_shard_count": 5,
                "launch_shard_count": 5,
                "survivability_recommended_shard_count": 4,
                "planning_warnings": [],
                "survivability": {
                    "totals": {
                        "estimated_input_tokens": 200,
                        "estimated_output_tokens": 40,
                        "estimated_followup_tokens": 0,
                        "estimated_peak_session_tokens": 240,
                    }
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (line_role_root / "phase_plan_summary.json").write_text(
        json.dumps(
            {
                "schema_version": "codex_phase_plan_summary.v1",
                "requested_shard_count": 5,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    telemetry_path = pred_run / "line-role-pipeline" / "telemetry_summary.json"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry_path.write_text(
        json.dumps(
            {
                "summary": {
                    "call_count": 1,
                    "duration_total_ms": 500,
                    "tokens_input": 180,
                    "tokens_output": 20,
                    "tokens_total": 200,
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    pred_manifest = {
        "stage_run_root": str(pred_run),
        "processed_run_root": str(pred_run),
        "line_role_pipeline_telemetry_path": str(telemetry_path),
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, pred_run)
    line_role_stage = summary["by_stage"]["line_role"]

    assert line_role_stage["requested_shard_count"] == 5
    assert line_role_stage["survivability_recommended_shard_count"] == 4
    assert "line-role-pipeline/runtime/line_role/phase_plan.json" in line_role_stage["phase_plan_path"]
