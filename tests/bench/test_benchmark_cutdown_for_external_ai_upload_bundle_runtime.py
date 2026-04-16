from __future__ import annotations

import tests.bench.benchmark_cutdown_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def _runtime_stage_summary_map(runtime_summary: dict[str, object]) -> dict[str, dict[str, object]]:
    by_stage = runtime_summary.get("by_stage")
    if isinstance(by_stage, dict):
        return {
            str(key): value
            for key, value in by_stage.items()
            if isinstance(value, dict)
        }
    return {
        str(row.get("stage_key") or ""): row
        for row in by_stage or []
        if isinstance(row, dict) and str(row.get("stage_key") or "")
    }


def test_build_upload_bundle_uses_single_correction_stage_labels_only(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "codex-exec"
    baseline_run_id = "vanilla"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
    )
    _write_json(
        session_root / "codex_vs_vanilla_comparison.json",
        {"schema_version": "codex_vs_vanilla_comparison.v2"},
    )

    codex_run_dir = session_root / codex_run_id
    _write_prediction_run(
        codex_run_dir,
        with_extracted_archive=True,
        llm_manifest_recipes={
            "recipe:c0": _semantic_recipe_manifest_row(
                correction_status="ok",
                build_final_status="ok",
                mapping_status="ok",
                mapping_reason="",
                structural_status="ok",
            )
        },
    )
    _set_pred_run_artifact(codex_run_dir, "prediction-run")

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    recipe_pipeline_context = index_payload["analysis"]["recipe_pipeline_context"]
    assert recipe_pipeline_context["recipe_topology_key"] == "single_correction"
    assert recipe_pipeline_context["codex_recipe_pipelines"] == [
        "codex-recipe-shard-v1"
    ]
    assert recipe_pipeline_context["recipe_stages"] == [
        {
            "stage_key": "recipe_build_intermediate",
            "stage_label": "Recipe Build Intermediate",
        },
        {
            "stage_key": "recipe_refine",
            "stage_label": "Recipe Refine",
        },
        {
            "stage_key": "recipe_build_final",
            "stage_label": "Recipe Build Final",
        },
    ]
    assert "historical_recipe_stages" not in recipe_pipeline_context
    assert "historical_recipe_topology_key" not in recipe_pipeline_context
    assert "historical_recipe_pipeline_aliases" not in recipe_pipeline_context

    assert "stage_separated_comparison" not in index_payload["analysis"]

    blame_summary = index_payload["analysis"]["net_error_blame_summary"]
    bucket_names = {
        str(row.get("bucket") or "")
        for row in blame_summary["bucket_rows"]
        if isinstance(row, dict)
    }
    assert {"nonrecipe_authority", "recipe_correction", "final_recipe"} <= bucket_names

    overview_text = _read_text(bundle_dir / module.UPLOAD_BUNDLE_OVERVIEW_FILE_NAME)
    assert "## Recipe Pipeline Context" in overview_text
    assert "codex-recipe-shard-v1" in overview_text
    assert "Recipe Build Intermediate" in overview_text
    assert "Recipe Refine" in overview_text
    assert "Recipe Build Final" in overview_text

    selected_paths = set(index_payload["review_packet"]["selected_paths"])
    assert (
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/group_high_level_packet.json"
        in selected_paths
    )
    assert (
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/01_recipe_triage.packet.jsonl"
        in selected_paths
    )
    assert not any(
        f"/{module.STARTER_PACK_DIR_NAME}/" in path for path in selected_paths
    )


def test_build_upload_bundle_for_existing_output_backfills_call_runtime_from_prediction_manifest(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    run_id = "codex-standalone"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=None,
        line_role_pipeline="codex-line-role-route-v2",
    )
    codex_run_dir = session_root / run_id
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _write_json(
        codex_run_dir / "prediction-run" / "manifest.json",
        {
            "llm_codex_farm": {
                "process_runs": {
                    "recipe_correction": {
                        "telemetry_report": {
                            "summary": {
                                "tokens_total": 120000,
                                "duration_avg_ms": 1100,
                                "status_counts": {"ok": 2, "failed": 0, "timeout": 0},
                            }
                        }
                    },
                }
            }
        },
    )

    runtime_inventory = module._upload_bundle_build_call_runtime_inventory_from_prediction_manifest(
        run_dirs=[codex_run_dir],
        run_dir_by_id={run_id: codex_run_dir},
    )
    assert isinstance(runtime_inventory, dict)
    runtime_summary = runtime_inventory["summary"]
    assert runtime_summary["runtime_source"] == "prediction_run_manifest_telemetry"
    assert int(runtime_summary["call_count"]) == 2
    assert int(runtime_summary["calls_with_runtime"]) == 2
    assert int(runtime_summary["total_tokens"]) == 120000
    assert float(runtime_summary["recipe_refine_token_share"]) == 1.0
    by_stage = runtime_summary["by_stage"]
    assert int(by_stage["recipe_refine"]["total_tokens"]) == 120000
    assert runtime_summary["estimated_cost_signal"]["available"] is False


def test_build_upload_bundle_prefers_prompt_budget_summary_and_includes_line_role(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    run_id = "2026-03-04_10.00.00"
    session_root = tmp_path / "single-profile-benchmark"
    _make_run_record(
        module,
        run_root=session_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=None,
        line_role_pipeline="codex-line-role-route-v2",
    )
    codex_run_dir = session_root / run_id
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _write_json(codex_run_dir / "prediction-run" / "manifest.json", {})
    _write_json(
        codex_run_dir / "prediction-run" / "prompt_budget_summary.json",
        {
            "schema_version": "prompt_budget_summary.v1",
            "by_stage": {
                "recipe_correction": {
                    "call_count": 2,
                    "duration_total_ms": 2200,
                    "tokens_total": 120000,
                },
                "line_role": {
                    "call_count": 3,
                    "duration_total_ms": 900,
                    "tokens_total": 50000,
                },
            },
        },
    )

    runtime_inventory = module._upload_bundle_build_call_runtime_inventory_from_prediction_manifest(
        run_dirs=[codex_run_dir],
        run_dir_by_id={run_id: codex_run_dir},
    )
    assert isinstance(runtime_inventory, dict)
    runtime_summary = runtime_inventory["summary"]
    assert runtime_summary["runtime_source"] == "prediction_run_prompt_budget_summary"
    assert int(runtime_summary["call_count"]) == 5
    assert int(runtime_summary["total_tokens"]) == 170000
    assert float(runtime_summary["line_role_token_share"]) == round(50000 / 170000, 4)
    assert int(runtime_summary["by_stage"]["line_role"]["total_tokens"]) == 50000
    assert (
        int(runtime_summary["by_stage"]["recipe_refine"]["total_tokens"]) == 120000
    )


def test_build_upload_bundle_merges_prompt_budget_summary_when_call_rows_lack_runtime_signal(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"

    _make_run_record(
        module,
        run_root=session_root,
        run_id="vanilla",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
        source_path="/tmp/book.epub",
        source_hash="fixture-hash",
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id="codex-exec",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=[
            {
                "stage_key": "recipe_refine",
                "call_id": "recipe-001",
                "recipe_id": "recipe:c0",
                "timestamp_utc": "2026-03-03T10:00:05Z",
                "model": "gpt-test",
                "parsed_response": {"canonical_recipe": {"ingredients": [], "steps": []}},
                "request_input_payload": {"evidence_rows": [[0, "Dish Title"]]},
                "request_telemetry": None,
            },
            {
                "stage_key": "nonrecipe_finalize",
                "call_id": "knowledge-001",
                "recipe_id": "knowledge:c0",
                "timestamp_utc": "2026-03-03T10:00:10Z",
                "model": "gpt-test",
                "parsed_response": {},
                "request_input_payload": {"bid": "bundle-001"},
                "request_telemetry": None,
            },
        ],
        source_path="/tmp/book.epub",
        source_hash="fixture-hash",
    )
    codex_run_dir = session_root / "codex-exec"
    _write_json(
        codex_run_dir / "prompt_budget_summary.json",
        {
            "schema_version": "prompt_budget_summary.v1",
            "by_stage": {
                "recipe_correction": {
                    "call_count": 5,
                    "duration_total_ms": None,
                    "tokens_total": 120000,
                },
                "knowledge": {
                    "call_count": 37,
                    "duration_total_ms": None,
                    "tokens_total": 1141186,
                },
                "line_role": {
                    "call_count": 5,
                    "duration_total_ms": None,
                    "tokens_total": 6535006,
                },
            },
        },
    )
    _write_json(
        session_root / "codex_vs_vanilla_comparison.json",
        {"schema_version": "codex_vs_vanilla_comparison.v2"},
    )

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    runtime_summary = index_payload["analysis"]["call_inventory_runtime"]["summary"]
    assert (
        runtime_summary["runtime_source"]
        == "call_inventory_rows_plus_prediction_run_prompt_budget_summary"
    )
    assert int(runtime_summary["call_count"]) == 47
    assert int(runtime_summary["calls_with_runtime"]) == 0
    assert int(runtime_summary["total_tokens"]) == 7796192
    by_stage = _runtime_stage_summary_map(runtime_summary)
    assert set(by_stage.keys()) == {
        "recipe_refine",
        "nonrecipe_finalize",
        "line_role",
    }
    assert int(by_stage["recipe_refine"]["total_tokens"]) == 120000
    assert int(by_stage["nonrecipe_finalize"]["total_tokens"]) == 1141186
    assert int(by_stage["line_role"]["total_tokens"]) == 6535006


def test_build_upload_bundle_merges_realistic_codex_call_telemetry_with_prompt_budget_summary(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"

    _make_run_record(
        module,
        run_root=session_root,
        run_id="vanilla",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
        source_path="/tmp/book.epub",
        source_hash="fixture-hash",
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id="codex-exec",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=[
            {
                "stage_key": "line_role",
                "call_id": "line-role-001",
                "recipe_id": "line_role_001",
                "timestamp_utc": "2026-03-03T10:00:01Z",
                "model": "gpt-test",
                "parsed_response": {
                    "response_payload": {
                        "rows": [
                            {"atomic_index": 0, "label": "OTHER"},
                            {"atomic_index": 1, "label": "RECIPE_TITLE"},
                        ]
                    }
                },
                "request_input_payload": {
                    "rows": [
                        {"atomic_index": 0, "text": "Front matter"},
                        {"atomic_index": 1, "text": "Dish Title"},
                    ]
                },
                "request_telemetry": {
                    "duration_ms": 600,
                    "status": "ok",
                    "attempt_index": 1,
                    "tokens_input": 200,
                    "tokens_cached_input": 50,
                    "tokens_output": 100,
                    "tokens_total": 300,
                },
            },
            {
                "stage_key": "recipe_refine",
                "call_id": "recipe-001",
                "recipe_id": "recipe:c0",
                "timestamp_utc": "2026-03-03T10:00:05Z",
                "model": "gpt-test",
                "parsed_response": {"canonical_recipe": {"ingredients": [], "steps": []}},
                "request_input_payload": {"evidence_rows": [[0, "Dish Title"]]},
                "request_telemetry": {
                    "duration_ms": 1200,
                    "status": "ok",
                    "attempt_index": 0,
                    "usage_json": {
                        "input_tokens": 1000,
                        "cached_input_tokens": 500,
                        "output_tokens": 300,
                        "total_tokens": 1800,
                        "output_tokens_details": {"reasoning_tokens": 120},
                        "cost_usd": 0.42,
                    },
                },
            },
            {
                "stage_key": "recipe_build_final",
                "call_id": "final-001",
                "recipe_id": "recipe:c0",
                "timestamp_utc": "2026-03-03T10:00:09Z",
                "model": "gpt-test",
                "parsed_response": {"draft_v1": {"recipe": {"title": "Dish Title"}}},
                "request_input_payload": {"rows_candidate": [{"text": "Mix gently"}]},
                "request_telemetry": {
                    "duration_ms": 900,
                    "status": "ok",
                    "attempt_index": 0,
                    "usage_json": {
                        "input_tokens": 800,
                        "output_tokens": 250,
                        "completion_tokens_details": {"reasoning_tokens": 75},
                    },
                },
            },
        ],
        source_path="/tmp/book.epub",
        source_hash="fixture-hash",
    )
    codex_run_dir = session_root / "codex-exec"
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _write_json(
        codex_run_dir / "prediction-run" / "manifest.json",
        {
            "llm_codex_farm": {
                "process_runs": {
                    "recipe_correction": {
                        "telemetry_report": {
                            "summary": {
                                "tokens_total": 120000,
                                "duration_total_ms": 4000,
                                "status_counts": {"ok": 5},
                            }
                        }
                    },
                    "nonrecipe_finalize": {
                        "telemetry_report": {
                            "summary": {
                                "tokens_total": 25000,
                                "duration_total_ms": 1500,
                                "status_counts": {"ok": 2},
                            }
                        }
                    },
                }
            }
        },
    )
    _write_json(
        codex_run_dir / "prediction-run" / "prompt_budget_summary.json",
        {
            "schema_version": "prompt_budget_summary.v1",
            "by_stage": {
                "recipe_correction": {
                    "call_count": 5,
                    "duration_total_ms": 4000,
                    "tokens_total": 120000,
                },
                "knowledge": {
                    "call_count": 2,
                    "duration_total_ms": 1500,
                    "tokens_total": 25000,
                },
                "line_role": {
                    "call_count": 7,
                    "duration_total_ms": 2100,
                    "tokens_total": 6535006,
                },
            },
        },
    )
    _write_json(
        session_root / "codex_vs_vanilla_comparison.json",
        {"schema_version": "codex_vs_vanilla_comparison.v2"},
    )

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    runtime_payload = index_payload["analysis"]["call_inventory_runtime"]
    runtime_summary = runtime_payload["summary"]

    assert (
        runtime_summary["runtime_source"]
        == "call_inventory_rows_plus_prediction_run_prompt_budget_summary"
    )
    assert int(runtime_summary["call_count"]) == 14
    assert int(runtime_summary["calls_with_runtime"]) == 14
    assert int(runtime_summary["total_tokens"]) == 6680006
    assert runtime_summary["cost_signal"]["available"] is True
    assert runtime_summary["estimated_cost_signal"]["available"] is True
    assert float(runtime_summary["total_cost_usd"]) == 0.42
    assert float(runtime_summary["total_estimated_cost_usd"]) > 0.42
    by_stage = _runtime_stage_summary_map(runtime_summary)
    assert set(by_stage.keys()) == {
        "recipe_refine",
        "nonrecipe_finalize",
        "line_role",
    }
    assert int(by_stage["recipe_refine"]["total_tokens"]) == 120000
    assert int(by_stage["nonrecipe_finalize"]["total_tokens"]) == 25000
    assert int(by_stage["line_role"]["total_tokens"]) == 6535006

    selected_paths = set(index_payload["review_packet"]["selected_paths"])
    assert (
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/config_version_metadata.json"
        in selected_paths
    )
    assert (
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/group_high_level_packet.json"
        in selected_paths
    )
    assert not any(
        f"/{module.STARTER_PACK_DIR_NAME}/" in path for path in selected_paths
    )


def test_build_upload_bundle_backfills_missing_stage_telemetry_from_prompt_budget_summary(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"

    _make_run_record(
        module,
        run_root=session_root,
        run_id="vanilla",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
        source_path="/tmp/book.epub",
        source_hash="fixture-hash",
    )

    full_prompt_rows: list[dict[str, Any]] = []
    for idx in range(5):
        full_prompt_rows.append(
            {
                "stage_key": "line_role",
                "call_id": f"line-role-{idx:03d}",
                "recipe_id": f"line_role_{idx:03d}",
                "timestamp_utc": f"2026-03-03T10:00:{idx:02d}Z",
                "model": "gpt-test",
                "parsed_response": {
                    "response_payload": {
                        "rows": [
                            {"atomic_index": idx, "label": "OTHER"},
                            {"atomic_index": idx + 1, "label": "RECIPE_TITLE"},
                        ]
                    }
                },
                "request_input_payload": {
                    "rows": [
                        {"atomic_index": idx, "text": "Front matter"},
                        {"atomic_index": idx + 1, "text": "Dish Title"},
                    ]
                },
                "request_telemetry": {
                    "duration_ms": 100 + idx,
                    "status": "ok",
                    "attempt_index": 0,
                    "tokens_input": 1000 + idx,
                    "tokens_cached_input": 400 + idx,
                    "tokens_output": 50 + idx,
                    "tokens_total": 1050 + (2 * idx),
                },
            }
        )
    for idx in range(5):
        full_prompt_rows.append(
            {
                "stage_key": "recipe_refine",
                "call_id": f"recipe-{idx:03d}",
                "recipe_id": f"recipe:c{idx}",
                "timestamp_utc": f"2026-03-03T10:01:{idx:02d}Z",
                "model": "gpt-test",
                "parsed_response": {
                    "canonical_recipe": {
                        "ingredients": [],
                        "steps": [],
                    }
                },
                "request_input_payload": {
                    "evidence_rows": [[idx, "Dish Title"]],
                },
                "request_telemetry": {
                    "duration_ms": 200 + idx,
                    "status": "ok",
                    "attempt_index": 0,
                    "tokens_input": 500 + idx,
                    "tokens_cached_input": 200 + idx,
                    "tokens_output": 25 + idx,
                    "tokens_total": 525 + (2 * idx),
                },
            }
        )
    for idx in range(5):
        full_prompt_rows.append(
            {
                "stage_key": "nonrecipe_finalize",
                "call_id": f"knowledge-{idx:03d}",
                "recipe_id": f"book.ks{idx:04d}.nr",
                "timestamp_utc": f"2026-03-03T10:02:{idx:02d}Z",
                "model": "gpt-test",
                "parsed_response": {
                    "payload": {
                        "bid": f"book.ks{idx:04d}.nr",
                        "d": [{"i": idx, "c": "other"}],
                    }
                },
                "request_input_payload": {"bid": f"book.ks{idx:04d}.nr"},
            }
        )

    _make_run_record(
        module,
        run_root=session_root,
        run_id="codex-exec",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=full_prompt_rows,
        source_path="/tmp/book.epub",
        source_hash="fixture-hash",
    )
    codex_run_dir = session_root / "codex-exec"
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _write_json(
        codex_run_dir / "prediction-run" / "prompt_budget_summary.json",
        {
            "schema_version": "prompt_budget_summary.v1",
            "by_stage": {
                "recipe_refine": {
                    "call_count": 5,
                    "duration_total_ms": 1010,
                    "tokens_total": 4000,
                },
                "nonrecipe_finalize": {
                    "call_count": 5,
                    "duration_total_ms": 5000,
                    "tokens_total": 9000,
                },
                "line_role": {
                    "call_count": 5,
                    "duration_total_ms": None,
                    "tokens_total": 7000,
                },
            },
        },
    )
    _write_json(
        session_root / "codex_vs_vanilla_comparison.json",
        {"schema_version": "codex_vs_vanilla_comparison.v2"},
    )

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    runtime_summary = index_payload["analysis"]["call_inventory_runtime"]["summary"]

    assert (
        runtime_summary["runtime_source"]
        == "call_inventory_rows_plus_prediction_run_prompt_budget_summary"
    )
    assert int(runtime_summary["call_count"]) == 15
    assert int(runtime_summary["calls_with_runtime"]) == 15
    assert int(runtime_summary["calls_with_estimated_cost"]) == 10
    assert int(runtime_summary["total_tokens"]) == 20000
    assert runtime_summary["estimated_cost_signal"]["available"] is True
    by_stage = _runtime_stage_summary_map(runtime_summary)
    assert by_stage["nonrecipe_finalize"]["call_count"] == 5
    assert int(by_stage["nonrecipe_finalize"]["total_tokens"]) == 9000
    assert by_stage["line_role"]["call_count"] == 5
    assert int(by_stage["line_role"]["total_tokens"]) == 7000


def test_build_upload_bundle_surfaces_knowledge_summary_and_locators(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-profile-benchmark" / "book_a"
    run_id = "codex-exec"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )
    run_dir = session_root / run_id
    _write_prediction_run(run_dir, with_extracted_archive=False)
    _set_pred_run_artifact(run_dir, "prediction-run")
    _write_knowledge_artifacts(run_dir, workbook_slug="fixture-slug", knowledge_call_count=4)

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    assert "knowledge" not in index_payload["analysis"]
    assert "row_locators" not in index_payload["navigation"]
    selected_paths = set(index_payload["review_packet"]["selected_paths"])
    assert f"{run_id}/prompts/prompt_type_samples_from_full_prompt_log.md" in selected_paths
    assert not any(path.endswith("prompt_nonrecipe_finalize.txt") for path in selected_paths)
    assert not any(path.endswith("knowledge_manifest.json") for path in selected_paths)


def test_build_upload_bundle_discovers_current_single_book_knowledge_layout(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark" / "book_a"
    codex_run_id = "codex-exec"
    baseline_run_id = "vanilla"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[
            {"line_index": 1, "gold_label": "INGREDIENT_LINE", "pred_label": "RECIPE_NOTES"},
        ],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
    )

    codex_run_dir = session_root / codex_run_id
    _write_knowledge_artifacts(
        codex_run_dir,
        workbook_slug="fixture-slug",
        knowledge_call_count=4,
        prompt_budget_at_run_root=True,
        include_prediction_run_files=False,
    )
    _write_replay_extracted_archive(codex_run_dir)
    _write_processed_output_knowledge_artifacts(
        codex_run_dir,
        processed_output_root=tmp_path / "processed-output" / codex_run_id,
        workbook_slug="fixture-slug",
        knowledge_call_count=4,
    )

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    assert "knowledge" not in index_payload["analysis"]
    assert "row_locators" not in index_payload["navigation"]
    selected_paths = set(index_payload["review_packet"]["selected_paths"])
    assert (
        f"{codex_run_id}/prompts/prompt_type_samples_from_full_prompt_log.md"
        in selected_paths
    )
    assert not any(path.endswith("prompt_nonrecipe_finalize.txt") for path in selected_paths)
    assert not any(path.endswith("knowledge_manifest.json") for path in selected_paths)


def test_build_upload_bundle_does_not_guess_processed_output_knowledge_manifest_path(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark" / "book_a"
    run_id = "codex-exec"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )

    run_dir = session_root / run_id
    _write_knowledge_artifacts(
        run_dir,
        workbook_slug="fixture-slug",
        knowledge_call_count=4,
        prompt_budget_at_run_root=True,
        include_prediction_run_files=False,
    )
    processed_output_root = tmp_path / "processed-output" / run_id
    _write_json(
        processed_output_root / "raw" / "llm" / "fixture-slug" / "knowledge_manifest.json",
        {
            "pipeline_id": "recipe.knowledge.compact.v1",
            "counts": {
                "shards_written": 4,
                "outputs_parsed": 4,
                "snippets_written": 8,
            },
        },
    )
    _set_run_artifact(run_dir, "processed_output_run_dir", str(processed_output_root))

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    assert "knowledge" not in index_payload["analysis"]
    assert "row_locators" not in index_payload["navigation"]
    selected_paths = set(index_payload["review_packet"]["selected_paths"])
    assert not any(path.endswith("knowledge_manifest.json") for path in selected_paths)


def test_resolve_knowledge_prompt_path_supports_dynamic_stage_file_names(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    run_dir = tmp_path / "single-profile-benchmark" / "book_a" / "codex-exec"
    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    dynamic_path = prompts_dir / "prompt_nonrecipe_finalize_stage.txt"
    dynamic_path.write_text("dynamic knowledge content\n", encoding="utf-8")
    (prompts_dir / "prompt_category_logs_manifest.txt").write_text(
        str(dynamic_path) + "\n",
        encoding="utf-8",
    )

    resolved = module._resolve_knowledge_prompt_path(run_dir)

    assert resolved == dynamic_path


def test_reconstruct_full_prompt_log_includes_knowledge_rows(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    run_dir = tmp_path / "single-profile-benchmark" / "book_a" / "codex-exec"
    _make_run_record(
        module,
        run_root=tmp_path / "single-profile-benchmark" / "book_a",
        run_id="codex-exec",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=[],
    )
    prediction_run = _write_prediction_run(run_dir, with_extracted_archive=False)
    _set_pred_run_artifact(run_dir, "prediction-run")
    _write_prediction_run_knowledge_stage_outputs(prediction_run, workbook_slug="fixture-slug")

    output_path = tmp_path / "reconstructed" / "full_prompt_log.jsonl"
    rows_written = module._reconstruct_full_prompt_log(
        run_dir=run_dir,
        run_manifest=_read_json(run_dir / "run_manifest.json"),
        output_path=output_path,
    )

    assert rows_written == 1
    rows = _read_jsonl(output_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["stage_key"] == "nonrecipe_finalize"
    assert row["pipeline_id"] == "recipe.knowledge.compact.v1"
    assert row["process_run_id"] == "run-knowledge-reconstruct"
    assert row["recipe_id"] is None
    assert row["request_input_payload"]["c"] == [
        {
            "cid": "knowledge:c0",
            "b": [
                {"i": 1, "t": "Roast until deeply browned."},
                {"i": 2, "t": "Let the pan stay hot for 2 minutes."},
            ],
            "h": {"l": "knowledge", "f": "prose_like"},
        }
    ]
    assert row["parsed_response"] == {
        "bundle_version": "2",
        "bundle_id": "knowledge:bundle0",
        "chunk_results": [
            {
                "chunk_id": "knowledge:c0",
                "is_useful": True,
                "block_decisions": [
                    {"block_index": 1, "category": "knowledge"},
                    {"block_index": 2, "category": "other"},
                ],
                "snippets": [
                    {
                        "title": "Browning",
                        "body": "Roast until deeply browned.",
                        "tags": ["fixture"],
                        "evidence": [
                            {"block_index": 1, "quote": "Roast until deeply browned."}
                        ],
                    },
                ],
            }
        ],
    }


def test_build_upload_bundle_high_level_includes_lightweight_knowledge_artifacts(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-profile-benchmark"
    run_id = "codex-exec"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )
    run_dir = session_root / run_id
    _write_prediction_run(run_dir, with_extracted_archive=False)
    _set_pred_run_artifact(run_dir, "prediction-run")
    _write_knowledge_artifacts(run_dir, workbook_slug="fixture-slug", knowledge_call_count=3)

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
        high_level_only=True,
        target_bundle_size_bytes=300_000,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    artifact_paths = set(index_payload["review_packet"]["selected_paths"])
    assert f"{run_id}/prompts/prompt_type_samples_from_full_prompt_log.md" in artifact_paths
    assert not any(path.endswith("knowledge_manifest.json") for path in artifact_paths)
    assert f"{run_id}/prompts/prompt_nonrecipe_finalize.txt" not in artifact_paths

    assert "knowledge" not in index_payload["analysis"]
