from __future__ import annotations

import tests.bench.benchmark_cutdown_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_main_writes_starter_pack_v1_contract_files(tmp_path: Path) -> None:
    fixture = _build_starter_pack_v1_fixture(tmp_path)
    module = fixture["module"]
    starter_dir = fixture["starter_dir"]
    root_manifest = fixture["root_manifest"]
    starter_manifest = fixture["starter_manifest"]
    starter_comparison = fixture["starter_comparison"]
    root_comparison = fixture["root_comparison"]
    assert isinstance(module, object)
    assert isinstance(starter_dir, Path)
    assert isinstance(root_manifest, dict)
    assert isinstance(starter_manifest, dict)
    assert isinstance(starter_comparison, dict)
    assert isinstance(root_comparison, dict)

    required_files = {
        "README.md",
        "00_run_overview.md",
        "01_recipe_triage.jsonl",
        "01_recipe_triage.packet.jsonl",
        "02_call_inventory.jsonl",
        "03_changed_lines.codex_vs_baseline.jsonl",
        "04_warning_and_trace_summary.json",
        "05_bridge_summary.jsonl",
        "06_selected_recipe_packets.jsonl",
        "07_casebook.md",
        "08_outside_span_trace.sample.jsonl",
        "09_label_policy.md",
        "10_process_manifest.json",
        "11_comparison_summary.json",
        "12_per_recipe_or_per_span_breakdown.json",
        "13_net_error_blame_summary.json",
        "14_config_version_metadata.json",
        "15_explicit_escalation_changed_lines.packet.jsonl",
        "16_baseline_trace_parity.json",
    }
    assert required_files.issubset({path.name for path in starter_dir.iterdir() if path.is_file()})

    assert starter_manifest["starter_pack_version"] == "v1"
    assert "selection_policy" in starter_manifest
    assert "outside_span_inclusion_policy" in starter_manifest
    assert "heavy_artifacts_omitted_by_default" in starter_manifest
    assert starter_manifest["outside_span_trace_sample"]["included"] is True

    assert root_manifest["starter_pack_v1_path"] == "starter_pack_v1"
    assert root_manifest["starter_pack_v1_manifest_file"] == "starter_pack_v1/10_process_manifest.json"
    assert "starter_pack_v1/01_recipe_triage.jsonl" in set(root_manifest["included_files"])
    assert starter_comparison == root_comparison


def test_main_starter_pack_writes_recipe_triage_and_call_inventory(tmp_path: Path) -> None:
    fixture = _build_starter_pack_v1_fixture(tmp_path)
    triage_rows = fixture["starter_triage_rows"]
    call_inventory_rows = fixture["starter_call_inventory_rows"]
    assert isinstance(triage_rows, list)
    assert isinstance(call_inventory_rows, list)

    assert triage_rows
    triage_row = triage_rows[0]
    assert triage_row["build_intermediate_status"] == "ok"
    assert triage_row["correction_status"] == "degraded"
    assert triage_row["build_final_status"] == "fallback"
    assert triage_row["final_mapping_status"] == "fallback"
    assert triage_row["final_mapping_reason"] == "deterministic final assembly kept fallback mapping"
    assert triage_row["structural_status"] == "warning"
    assert triage_row["structural_reason_codes"] == ["missing_instructions"]
    assert triage_row["recipe_warning_count"] == 1
    assert triage_row["recipe_error_count"] == 0

    assert call_inventory_rows
    required_call_inventory_keys = {
        "run_id",
        "source_key",
        "source_file",
        "recipe_id",
        "stage_key",
        "stage_label",
        "call_id",
        "timestamp_utc",
        "model",
        "input_row_count",
        "warning_count",
        "warning_buckets",
        "extracted_ingredient_count",
        "extracted_instruction_count",
        "step_count",
        "mapping_count",
        "input_excerpt",
        "output_excerpt",
        "duration_ms",
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
        "cost_usd",
        "estimated_cost_usd",
        "cost_source",
        "retry_attempt",
        "runtime_status",
    }
    assert required_call_inventory_keys.issubset(call_inventory_rows[0].keys())


def test_main_starter_pack_call_inventory_includes_line_role_rows_with_runtime_fields(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"

    line_role_row = {
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
            "duration_ms": 321,
            "status": "ok",
            "attempt_index": 2,
            "tokens_input": 100,
            "tokens_cached_input": 25,
            "tokens_output": 50,
            "tokens_total": 150,
        },
    }
    _make_run_record(
        module,
        run_root=session_root,
        run_id="codex-exec",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=[line_role_row, *_prompt_rows_for_starter_pack_fixture()],
        source_path="/tmp/book.epub",
        source_hash="fixture-hash",
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id="vanilla",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        source_path="/tmp/book.epub",
        source_hash="fixture-hash",
    )

    module.build_starter_pack_for_existing_runs(
        input_dir=session_root,
        output_dir=session_root,
    )

    call_inventory_rows = _read_jsonl(
        session_root / module.STARTER_PACK_DIR_NAME / module.STARTER_PACK_CALL_INVENTORY_FILE_NAME
    )
    assert len(call_inventory_rows) == 4
    exported_line_role_row = next(
        row for row in call_inventory_rows if row["stage_key"] == "line_role"
    )
    assert exported_line_role_row["input_row_count"] == 2
    assert exported_line_role_row["duration_ms"] == 321
    assert exported_line_role_row["tokens_input"] == 100
    assert exported_line_role_row["tokens_cached_input"] == 25
    assert exported_line_role_row["tokens_output"] == 50
    assert exported_line_role_row["tokens_total"] == 150
    assert exported_line_role_row["cost_usd"] is None
    assert exported_line_role_row["estimated_cost_usd"] is not None
    assert exported_line_role_row["cost_source"] == "estimated_from_tokens_default_pricing"
    assert exported_line_role_row["retry_attempt"] == 2
    assert exported_line_role_row["runtime_status"] == "ok"


def test_main_starter_pack_summarizes_warnings_and_selected_packets(tmp_path: Path) -> None:
    fixture = _build_starter_pack_v1_fixture(tmp_path)
    warning_summary = fixture["warning_summary"]
    selected_packets = fixture["starter_selected_packets"]
    assert isinstance(warning_summary, dict)
    assert isinstance(selected_packets, list)

    assert warning_summary["recipe_stage_status_counts"]["recipe_build_intermediate"]["ok"] == 1
    assert warning_summary["recipe_stage_status_counts"]["recipe_refine"]["degraded"] == 1
    assert warning_summary["recipe_stage_status_counts"]["recipe_build_final"]["fallback"] == 1
    assert warning_summary["final_mapping_status_counts"]["fallback"] == 1
    assert "recipe_stage_status_counts" in warning_summary

    assert selected_packets
    first_packet = selected_packets[0]
    recipe_stage_summaries = {
        str(stage.get("stage_key") or ""): stage
        for stage in first_packet["recipe_stages"]
        if isinstance(stage, dict)
    }
    assert recipe_stage_summaries["recipe_refine"]["status"] == "degraded"
    assert recipe_stage_summaries["recipe_refine"]["warning_count"] == 1
    assert recipe_stage_summaries["recipe_build_final"]["status"] == "fallback"
    assert recipe_stage_summaries["recipe_build_final"]["mapping_status"] == "fallback"
    assert (
        recipe_stage_summaries["recipe_build_final"]["mapping_reason"]
        == "deterministic final assembly kept fallback mapping"
    )
    assert recipe_stage_summaries["recipe_build_final"]["structural_status"] == "warning"
    assert first_packet["transport_summary"] == {}


def test_main_starter_pack_omits_outside_trace_when_threshold_not_met(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    codex_run_id = "2026-03-03_10.12.00"
    baseline_run_id = "2026-03-03_10.11.00"

    _make_run_record(
        module,
        run_root=run_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )
    _make_run_record(
        module,
        run_root=run_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
    )

    codex_run_dir = run_root / codex_run_id
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(codex_run_dir, "prediction-run")

    output_dir = tmp_path / "cutdown_out"
    assert (
        _run_main(
            module,
            [str(run_root), "--output-dir", str(output_dir), "--overwrite", "--no-flatten"],
        )
        == 0
    )

    starter_dir = output_dir / "starter_pack_v1"
    outside_trace_path = starter_dir / "08_outside_span_trace.sample.jsonl"
    assert not outside_trace_path.is_file()

    starter_manifest = _read_json(starter_dir / "10_process_manifest.json")
    outside_trace_manifest = starter_manifest["outside_span_trace_sample"]
    assert outside_trace_manifest["included"] is False
    assert "omitted_reason" in outside_trace_manifest


def test_build_starter_pack_for_existing_runs_writes_into_session_root(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-03_10.14.00"
    baseline_run_id = "2026-03-03_10.13.00"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
        line_role_prediction_rows=[
            {
                "recipe_id": "recipe:c0",
                "line_index": 1,
                "atomic_index": 1,
                "label": "RECIPE_NOTES",
                "decided_by": "rule",
                "escalation_reasons": ["deterministic_unresolved"],
                "text": "1 cup flour",
            }
        ],
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
    )

    metadata = module.build_starter_pack_for_existing_runs(
        input_dir=session_root,
        output_dir=session_root,
    )

    starter_dir = session_root / "starter_pack_v1"
    assert starter_dir.is_dir()
    assert (starter_dir / "00_run_overview.md").is_file()
    assert (starter_dir / "01_recipe_triage.jsonl").is_file()
    assert int(metadata["run_count"]) == 2
    assert int(metadata["pair_count"]) == 1


def test_build_starter_pack_for_existing_runs_writes_flattened_summary_when_enabled(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-03_10.16.00"
    baseline_run_id = "2026-03-03_10.15.00"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
        line_role_prediction_rows=[
            {
                "atomic_index": 0,
                "label": "RECIPE_TITLE",
                "decided_by": "rule",
                "escalation_reasons": [],
                "text": "Dish Title",
            }
        ],
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
    )

    (session_root / "codex_vs_vanilla_comparison.json").write_text(
        json.dumps({"schema_version": "codex_vs_vanilla_comparison.v2"}),
        encoding="utf-8",
    )

    metadata = module.build_starter_pack_for_existing_runs(
        input_dir=session_root,
        output_dir=session_root,
        write_flattened_summary=True,
    )

    summary_path = session_root / module.AGGREGATED_ROOT_SUMMARY_MD
    assert summary_path.is_file()
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "# Benchmark Need-To-Know Package (Flattened)" in summary_text
    assert "## codex_vs_vanilla_comparison.json" in summary_text
    assert "## starter_pack_v1/10_process_manifest.json" in summary_text
    assert metadata["flattened_summary_path"] == module.AGGREGATED_ROOT_SUMMARY_MD


def test_select_starter_pack_recipe_cases_uses_blended_policy() -> None:
    module = _load_cutdown_module()
    triage_rows = [
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": f"recipe:{index}",
            "changed_lines_codex_vs_baseline": 20 - index,
            "delta_codex_minus_baseline": 0.1 - (index * 0.01),
            "build_intermediate_missing_row_count": index % 5,
            "final_recipe_empty_mapping": index in {2, 5, 7},
            "build_intermediate_selected_row_count": 10 if index in {2, 5} else 2,
            "correction_warning_count": 3 if index == 7 else 0,
            "correction_step_count": 0 if index in {2, 7} else 1,
            "outside_span_wrong_line_count": 3 if index == 4 else 0,
            "codex_accuracy": 0.8 - (index * 0.01),
        }
        for index in range(10)
    ]

    selected = module._select_starter_pack_recipe_cases(triage_rows)

    assert 1 <= len(selected) <= 10
    reasons = [str(row.get("selection_reason") or "") for row in selected]
    assert any("top_changed_lines" in reason for reason in reasons)
    assert any("top_row_loss" in reason for reason in reasons)
    assert any("top_empty_mapping_upstream_evidence" in reason for reason in reasons)
    assert any("outside_span_contamination" in reason for reason in reasons)
    assert any("healthy_control" in reason for reason in reasons)


def test_select_starter_pack_recipe_cases_empty_mapping_tiebreak_uses_delta() -> None:
    module = _load_cutdown_module()
    triage_rows = [
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:steady",
            "changed_lines_codex_vs_baseline": 9,
            "delta_codex_minus_baseline": 0.01,
            "build_intermediate_missing_row_count": 0,
            "final_recipe_empty_mapping": False,
            "build_intermediate_selected_row_count": 10,
            "correction_warning_count": 0,
            "correction_step_count": 1,
            "outside_span_wrong_line_count": 0,
            "codex_accuracy": 0.90,
        },
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:empty-high-delta",
            "changed_lines_codex_vs_baseline": 4,
            "delta_codex_minus_baseline": -0.40,
            "build_intermediate_missing_row_count": 1,
            "final_recipe_empty_mapping": True,
            "build_intermediate_selected_row_count": 10,
            "correction_warning_count": 0,
            "correction_step_count": 0,
            "outside_span_wrong_line_count": 0,
            "codex_accuracy": 0.40,
        },
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:empty-low-delta-high-changes",
            "changed_lines_codex_vs_baseline": 20,
            "delta_codex_minus_baseline": -0.05,
            "build_intermediate_missing_row_count": 1,
            "final_recipe_empty_mapping": True,
            "build_intermediate_selected_row_count": 10,
            "correction_warning_count": 0,
            "correction_step_count": 0,
            "outside_span_wrong_line_count": 0,
            "codex_accuracy": 0.50,
        },
    ]

    selected = module._select_starter_pack_recipe_cases(triage_rows)
    selected_by_recipe = {
        str(row.get("recipe_id")): str(row.get("selection_reason") or "")
        for row in selected
    }

    assert "top_empty_mapping_upstream_evidence" in selected_by_recipe["recipe:empty-high-delta"]


def test_select_starter_pack_recipe_cases_keeps_low_change_high_row_loss() -> None:
    module = _load_cutdown_module()
    triage_rows = [
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": f"recipe:high-change-{index}",
            "changed_lines_codex_vs_baseline": 20 - index,
            "delta_codex_minus_baseline": -0.10 - (index * 0.01),
            "build_intermediate_missing_row_count": 2 + index,
            "final_recipe_empty_mapping": False,
            "build_intermediate_selected_row_count": 10,
            "correction_warning_count": 0,
            "correction_step_count": 1,
            "outside_span_wrong_line_count": 0,
            "codex_accuracy": 0.60 - (index * 0.01),
        }
        for index in range(4)
    ]
    triage_rows.append(
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:low-change-high-loss",
            "changed_lines_codex_vs_baseline": 1,
            "delta_codex_minus_baseline": -0.90,
            "build_intermediate_missing_row_count": 99,
            "final_recipe_empty_mapping": False,
            "build_intermediate_selected_row_count": 10,
            "correction_warning_count": 0,
            "correction_step_count": 1,
            "outside_span_wrong_line_count": 0,
            "codex_accuracy": 0.20,
        }
    )

    selected = module._select_starter_pack_recipe_cases(triage_rows)
    selected_by_recipe = {
        str(row.get("recipe_id")): str(row.get("selection_reason") or "")
        for row in selected
    }

    assert "recipe:low-change-high-loss" in selected_by_recipe
    assert "top_row_loss" in selected_by_recipe["recipe:low-change-high-loss"]


def test_select_starter_pack_recipe_cases_outside_pool_uses_metric_not_change_floor() -> None:
    module = _load_cutdown_module()
    triage_rows = [
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:outside-low-change-highest",
            "changed_lines_codex_vs_baseline": 1,
            "delta_codex_minus_baseline": -0.80,
            "build_intermediate_missing_row_count": 0,
            "final_recipe_empty_mapping": False,
            "build_intermediate_selected_row_count": 10,
            "correction_warning_count": 0,
            "correction_step_count": 1,
            "outside_span_wrong_line_count": 50,
            "codex_accuracy": 0.20,
        },
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:outside-higher-change-lower-outside",
            "changed_lines_codex_vs_baseline": 8,
            "delta_codex_minus_baseline": -0.20,
            "build_intermediate_missing_row_count": 0,
            "final_recipe_empty_mapping": False,
            "build_intermediate_selected_row_count": 10,
            "correction_warning_count": 0,
            "correction_step_count": 1,
            "outside_span_wrong_line_count": 5,
            "codex_accuracy": 0.30,
        },
    ]

    selected = module._select_starter_pack_recipe_cases(triage_rows)
    selected_by_recipe = {
        str(row.get("recipe_id")): str(row.get("selection_reason") or "")
        for row in selected
    }

    assert "recipe:outside-low-change-highest" in selected_by_recipe
    assert (
        "outside_span_contamination"
        in selected_by_recipe["recipe:outside-low-change-highest"]
    )
