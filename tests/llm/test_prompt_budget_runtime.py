from __future__ import annotations

from pathlib import Path

from cookimport.llm.prompt_budget_runtime import build_prediction_run_prompt_budget_summary


def test_prompt_budget_knowledge_stage_recovers_from_empty_top_level_telemetry() -> None:
    pred_manifest = {
        "llm_codex_farm": {
            "knowledge": {
                "phase_worker_runtime": {
                    "shard_count": 5,
                    "telemetry": {
                        "rows": [],
                        "summary": {
                            "call_count": 0,
                            "duration_total_ms": 0,
                            "tokens_input": 0,
                            "tokens_cached_input": 0,
                            "tokens_output": 0,
                            "tokens_reasoning": 0,
                            "tokens_total": 0,
                            "visible_input_tokens": 0,
                            "visible_output_tokens": 0,
                            "wrapper_overhead_tokens": 0,
                        },
                    },
                    "worker_reports": [
                        {
                            "runner_result": {
                                "worker_runs": [
                                    {
                                        "telemetry": {
                                            "summary": {
                                                "call_count": 1,
                                                "tokens_input": 42000,
                                                "tokens_output": 24000,
                                                "tokens_total": 76000,
                                            }
                                        }
                                    },
                                    {
                                        "telemetry": {
                                            "summary": {
                                                "call_count": 1,
                                                "tokens_input": 119000,
                                                "tokens_output": 27000,
                                                "tokens_total": 166000,
                                            }
                                        }
                                    },
                                ]
                            }
                        }
                    ],
                }
            }
        }
    }

    summary = build_prediction_run_prompt_budget_summary(pred_manifest, Path("/tmp/pred-run"))
    stage = summary["by_stage"]["nonrecipe_finalize"]

    assert stage["call_count"] == 2
    assert stage["tokens_input"] == 161000
    assert stage["tokens_output"] == 51000
    assert stage["tokens_total"] == 242000
    assert stage.get("token_usage_status") == "complete"
    assert stage.get("token_usage_available_call_count") == 2
    assert stage.get("token_usage_missing_call_count") == 0
