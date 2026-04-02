from __future__ import annotations

import tests.bench.benchmark_cutdown_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_build_upload_bundle_for_existing_output_writes_three_files(tmp_path: Path) -> None:
    fixture = _build_existing_upload_bundle_fixture(tmp_path)
    module = fixture["module"]
    session_root = fixture["session_root"]
    bundle_dir = fixture["bundle_dir"]
    index_payload = fixture["index_payload"]
    artifact_paths = fixture["artifact_paths"]
    codex_run_id = fixture["codex_run_id"]
    baseline_run_id = fixture["baseline_run_id"]
    assert isinstance(session_root, Path)
    assert isinstance(bundle_dir, Path)
    assert isinstance(index_payload, dict)
    assert isinstance(artifact_paths, set)
    assert isinstance(codex_run_id, str)
    assert isinstance(baseline_run_id, str)

    assert fixture["metadata"]["source_dir"] == str(session_root.resolve())
    assert fixture["metadata"]["output_dir"] == str(bundle_dir.resolve())
    assert {
        path.name
        for path in bundle_dir.iterdir()
        if path.is_dir()
    } == set(module.UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES)
    assert f"{codex_run_id}/run_manifest.json" in artifact_paths
    assert f"{baseline_run_id}/run_manifest.json" in artifact_paths
    assert int(index_payload["topline"]["run_count"]) == 2
    assert int(index_payload["topline"]["pair_count"]) == 1
    assert int(index_payload["topline"]["changed_lines_total"]) >= 1
    assert int(index_payload["topline"]["additional_pairs_needed_for_generalization"]) == 1
    assert index_payload["topline"]["full_prompt_log_status"] == "complete"
    assert index_payload["topline"]["full_prompt_log_status_source"] in {
        "process_manifest",
        "derived_from_run_diagnostics",
    }
    assert index_payload["topline"]["worst_pair_delta_overall_line_accuracy"] is not None
    assert index_payload["topline"]["worst_pair_delta_macro_f1_excluding_other"] is not None
    assert isinstance(index_payload["topline"].get("active_recipe_span_breakout"), dict)
    self_check = index_payload.get("self_check")
    assert isinstance(self_check, dict)
    assert set(
        [
            "starter_pack_present",
            "starter_pack_physical_dir_present",
            "pair_count_verified",
            "changed_lines_verified",
            "topline_consistent",
        ]
    ).issubset(self_check.keys())
    assert self_check["starter_pack_present"] is True
    assert self_check["starter_pack_physical_dir_present"] is False


def test_build_upload_bundle_explicit_escalation_packet_matches_atomic_index_only_rows(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-22_16.52.22"
    baseline_run_id = "2026-03-22_16.40.00"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "OTHER"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
        line_role_prediction_rows=[
            {
                "atomic_index": 1,
                "label": "OTHER",
                "decided_by": "codex",
                "escalation_reasons": ["nonrecipe_finalize_excluded"],
                "text": "1 cup flour",
                "within_recipe_span": True,
                "page_type": "recipe_page",
                "chapter_title": "Recipe Chapter",
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
    _set_eval_report_metrics(
        session_root / codex_run_id,
        overall_line_accuracy=0.75,
        macro_f1_excluding_other=0.70,
        practical_f1=0.72,
    )
    _set_eval_report_metrics(
        session_root / baseline_run_id,
        overall_line_accuracy=0.70,
        macro_f1_excluding_other=0.65,
        practical_f1=0.67,
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
    escalation_packet = index_payload["analysis"]["explicit_escalation_changed_lines_packet"]
    assert escalation_packet["available"] is True
    assert escalation_packet["row_count"] == 1
    sample_row = escalation_packet["sample_rows"][0]
    assert sample_row["line_index"] == 1
    assert sample_row["atomic_index"] == 1
    assert sample_row["escalation_reasons"] == ["nonrecipe_finalize_excluded"]
    assert sample_row["attribution_bucket_hint"] == "line_role"
    assert sample_row["issue_kind"] is None


def test_build_upload_bundle_flags_exclusion_leak_as_nonrecipe_authority(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-31_13.18.44"
    baseline_run_id = "2026-03-31_13.00.00"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[
            {
                "line_index": 87,
                "gold_label": "OTHER",
                "pred_label": "KNOWLEDGE",
                "line_text": "Winter: Roasted Radicchio and Roquefort",
            }
        ],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
        line_role_prediction_rows=[
            {
                "atomic_index": 87,
                "label": "NONRECIPE_EXCLUDE",
                "decided_by": "codex",
                "escalation_reasons": ["nonrecipe_excluded"],
                "text": "Winter: Roasted Radicchio and Roquefort",
                "within_recipe_span": False,
                "page_type": "front_matter",
                "chapter_title": "Contents",
            }
        ],
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 87, "pred_label": "OTHER"}],
        full_prompt_rows=None,
    )
    _set_eval_report_metrics(
        session_root / codex_run_id,
        overall_line_accuracy=0.60,
        macro_f1_excluding_other=0.55,
        practical_f1=0.58,
    )
    _set_eval_report_metrics(
        session_root / baseline_run_id,
        overall_line_accuracy=0.70,
        macro_f1_excluding_other=0.68,
        practical_f1=0.69,
    )
    _write_json(
        session_root / "codex_vs_vanilla_comparison.json",
        {"schema_version": "codex_vs_vanilla_comparison.v2"},
    )
    changed_line_rows = [
        {
            "source_key": "source-hash",
            "codex_run_id": codex_run_id,
            "baseline_run_id": baseline_run_id,
            "recipe_id": "",
            "line_index": 87,
            "gold_label": "OTHER",
            "vanilla_pred": "OTHER",
            "codex_pred": "KNOWLEDGE",
            "current_line": "Winter: Roasted Radicchio and Roquefort",
            "previous_line": "Autumn: Roasted Squash, Sage, and Hazelnut",
            "next_line": "Spring: Asparagus and Feta with Mint",
        }
    ]

    escalation_packet, escalation_rows = (
        module._upload_bundle_build_explicit_escalation_changed_lines_packet(
            source_root=session_root,
            run_dir_by_id={
                codex_run_id: session_root / codex_run_id,
                baseline_run_id: session_root / baseline_run_id,
            },
            changed_line_rows=changed_line_rows,
        )
    )
    assert escalation_packet["available"] is True
    assert escalation_packet["issue_kind_counts"] == {
        "exclusion_leak_into_final_knowledge": 1
    }
    sample_row = escalation_packet["sample_rows"][0]
    assert sample_row["line_index"] == 87
    assert sample_row["issue_kind"] == "exclusion_leak_into_final_knowledge"
    assert sample_row["attribution_bucket_hint"] == "nonrecipe_authority"
    assert "final authority still surfaced KNOWLEDGE" in str(
        sample_row["issue_note"]
    )

    blame_summary = module._upload_bundle_build_net_error_blame_summary(
        changed_line_rows=changed_line_rows,
        recipe_triage_rows=[],
        comparison_pairs=[
            {
                "codex_run": {
                    "run_id": codex_run_id,
                    "line_role_pipeline": "codex-line-role-route-v2",
                }
            }
        ],
        explicit_escalation_rows=escalation_rows,
    )
    bucket_rows = {
        str(row.get("bucket") or ""): row
        for row in blame_summary["bucket_rows"]
        if isinstance(row, dict)
    }
    assert int(bucket_rows["nonrecipe_authority"]["new_error_count"] or 0) == 1
    assert int(bucket_rows["line_role"]["new_error_count"] or 0) == 0


def test_explicit_escalation_packet_uses_joined_line_table_not_raw_index_alias(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-31_19.51.54"
    baseline_run_id = "2026-03-31_19.00.00"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
        line_role_prediction_rows=[
            {
                "atomic_index": 208,
                "label": "NONRECIPE_EXCLUDE",
                "decided_by": "codex",
                "escalation_reasons": ["nonrecipe_excluded"],
                "text": "Excluded memoir row",
                "within_recipe_span": False,
            },
            {
                "atomic_index": 213,
                "label": "NONRECIPE_CANDIDATE",
                "decided_by": "codex",
                "escalation_reasons": [],
                "text": "Real changed line at canonical 208",
                "within_recipe_span": False,
            },
        ],
        joined_line_rows=[
            {
                "line_index": 203,
                "line_role_prediction_atomic_index": 208,
                "line_role_match_kind": "exact_text_occurrence",
            },
            {
                "line_index": 208,
                "line_role_prediction_atomic_index": 213,
                "line_role_match_kind": "exact_text_occurrence",
            },
        ],
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[],
        full_prompt_rows=None,
    )

    escalation_packet, escalation_rows = (
        module._upload_bundle_build_explicit_escalation_changed_lines_packet(
            source_root=session_root,
            run_dir_by_id={
                codex_run_id: session_root / codex_run_id,
                baseline_run_id: session_root / baseline_run_id,
            },
            changed_line_rows=[
                {
                    "source_key": "source-hash",
                    "codex_run_id": codex_run_id,
                    "baseline_run_id": baseline_run_id,
                    "recipe_id": "",
                    "line_index": 203,
                    "gold_label": "OTHER",
                    "vanilla_pred": "OTHER",
                    "codex_pred": "OTHER",
                    "current_line": "Excluded memoir row",
                    "previous_line": "Previous 203",
                    "next_line": "Next 203",
                },
                {
                    "source_key": "source-hash",
                    "codex_run_id": codex_run_id,
                    "baseline_run_id": baseline_run_id,
                    "recipe_id": "",
                    "line_index": 208,
                    "gold_label": "OTHER",
                    "vanilla_pred": "OTHER",
                    "codex_pred": "KNOWLEDGE",
                    "current_line": "Real changed line at canonical 208",
                    "previous_line": "Previous 208",
                    "next_line": "Next 208",
                },
            ],
        )
    )

    assert escalation_packet["available"] is True
    assert escalation_packet["row_count"] == 1
    assert len(escalation_rows) == 1
    sample_row = escalation_packet["sample_rows"][0]
    assert sample_row["line_index"] == 203
    assert sample_row["atomic_index"] == 208
    assert sample_row["label"] == "NONRECIPE_EXCLUDE"
    assert sample_row["issue_kind"] is None
    assert sample_row["attribution_bucket_hint"] == "line_role"


def test_build_upload_bundle_for_existing_output_includes_analysis_payloads(
    tmp_path: Path,
) -> None:
    fixture = _build_existing_upload_bundle_fixture(tmp_path)
    index_payload = fixture["index_payload"]
    codex_run_id = fixture["codex_run_id"]
    assert isinstance(index_payload, dict)
    assert isinstance(codex_run_id, str)

    assert isinstance(index_payload.get("analysis"), dict)
    assert isinstance(index_payload["analysis"].get("triage_packet"), dict)
    turn1_summary = index_payload["analysis"].get("turn1_summary")
    assert isinstance(turn1_summary, dict)
    assert isinstance(turn1_summary.get("recommended_read_order"), list)
    assert turn1_summary["recommended_read_order"][0] == "analysis.benchmark_pair_inventory"
    assert isinstance(turn1_summary.get("targeted_regression_affordance"), dict)
    blame_summary = index_payload["analysis"].get("net_error_blame_summary")
    assert isinstance(blame_summary, dict)
    share_semantics = blame_summary.get("share_semantics")
    assert isinstance(share_semantics, dict)
    bucket_rows = blame_summary.get("bucket_rows")
    assert isinstance(bucket_rows, list)
    assert {row.get("bucket") for row in bucket_rows if isinstance(row, dict)} == {
        "nonrecipe_authority",
        "line_role",
        "recipe_correction",
        "final_recipe",
        "routing_or_fallback",
    }
    new_error_lines = int(blame_summary.get("new_error_lines") or 0)
    fixed_error_lines = int(blame_summary.get("fixed_error_lines") or 0)
    net_error_delta_lines = int(blame_summary.get("net_error_delta_lines") or 0)
    assert net_error_delta_lines == (new_error_lines - fixed_error_lines)
    summed_new_counts = 0
    summed_fixed_counts = 0
    summed_net_counts = 0
    for row in bucket_rows:
        if not isinstance(row, dict):
            continue
        assert "new_error_count" in row
        assert "fixed_error_count" in row
        assert "net_error_count" in row
        assert "share_of_new_errors" in row
        assert "share_of_fixed_errors" in row
        assert "share_of_net_error" in row
        row_new = int(row.get("new_error_count") or 0)
        row_fixed = int(row.get("fixed_error_count") or 0)
        row_net = int(row.get("net_error_count") or 0)
        assert row_net == (row_new - row_fixed)
        summed_new_counts += row_new
        summed_fixed_counts += row_fixed
        summed_net_counts += row_net
    assert summed_new_counts == new_error_lines
    assert summed_fixed_counts == fixed_error_lines
    assert summed_net_counts == net_error_delta_lines
    config_meta = index_payload["analysis"].get("config_version_metadata")
    assert isinstance(config_meta, dict)
    assert isinstance(config_meta.get("pair_comparability"), dict)
    recipe_pipeline_context = index_payload["analysis"].get("recipe_pipeline_context")
    assert isinstance(recipe_pipeline_context, dict)
    assert recipe_pipeline_context.get("recipe_topology_key") == "single_correction"
    assert recipe_pipeline_context.get("recipe_stages") == [
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
    run_settings_rows = config_meta.get("runs")
    assert isinstance(run_settings_rows, list)
    codex_settings = next(
        row for row in run_settings_rows if str(row.get("run_id") or "") == codex_run_id
    )
    assert (
        codex_settings["llm_recipe_pipeline"]
        == "codex-recipe-shard-v1"
    )
    assert codex_settings["line_role_pipeline"] == "codex-line-role-route-v2"
    assert isinstance(index_payload["analysis"].get("stage_separated_comparison"), dict)
    structure_report = index_payload["analysis"].get("structure_label_report")
    assert isinstance(structure_report, dict)
    assert structure_report.get("schema_version") == "benchmark_structure_label_report.v1"
    assert isinstance(structure_report.get("slices"), dict)
    assert isinstance(structure_report.get("boundary"), dict)
    assert isinstance(index_payload["analysis"].get("failure_ledger"), dict)
    assert isinstance(index_payload["analysis"].get("regression_casebook"), dict)
    escalation_packet = index_payload["analysis"].get("explicit_escalation_changed_lines_packet")
    assert isinstance(escalation_packet, dict)
    assert escalation_packet.get("available") is True
    escalation_row_count = int(escalation_packet.get("row_count") or 0)
    assert escalation_row_count >= 0
    if escalation_row_count == 0:
        assert "No changed lines intersected" in str(
            escalation_packet.get("empty_packet_note") or ""
        )
    assert isinstance(index_payload["analysis"].get("call_inventory_runtime"), dict)
    line_role_signal = index_payload["analysis"].get("line_role_escalation")
    assert isinstance(line_role_signal, dict)
    assert "candidate_label_signal" not in line_role_signal
    assert isinstance(line_role_signal.get("selective_escalation_signal"), dict)
    runtime_summary = index_payload["analysis"]["call_inventory_runtime"]["summary"]
    assert isinstance(runtime_summary.get("cost_signal"), dict)
    assert runtime_summary["cost_signal"]["available"] is False
    assert "recipe_build_final" in runtime_summary["by_stage"]
    assert "recipe_refine" in runtime_summary["by_stage"]
    assert "recipe_build_final" in runtime_summary["by_stage"]
    assert (
        "recognized cost fields"
        in str(runtime_summary["cost_signal"]["unavailable_reason"])
    )
    assert isinstance(runtime_summary.get("estimated_cost_signal"), dict)
    if runtime_summary["estimated_cost_signal"]["available"] is True:
        assert int(runtime_summary.get("calls_with_estimated_cost") or 0) >= 1
        assert runtime_summary.get("total_estimated_cost_usd") is not None
    else:
        assert (
            "token telemetry is missing"
            in str(runtime_summary["estimated_cost_signal"].get("note") or "")
        )
    pair_inventory = index_payload["analysis"]["benchmark_pair_inventory"]
    assert isinstance(pair_inventory.get("delta_summary"), dict)
    assert isinstance(pair_inventory.get("generalization_readiness"), dict)
    assert (
        pair_inventory["generalization_readiness"][
            "additional_pairs_needed_for_generalization"
        ]
        == 1
    )
    active_span_breakout = index_payload["analysis"]["active_recipe_span_breakout"]
    assert isinstance(active_span_breakout, dict)
    assert active_span_breakout["pair_count"] == 1
    assert isinstance(active_span_breakout.get("inside_active_recipe_span"), dict)
    assert isinstance(active_span_breakout.get("outside_active_recipe_span"), dict)
    stage_observability = index_payload["analysis"]["stage_observability_summary"]
    assert isinstance(stage_observability, dict)
    assert isinstance(stage_observability.get("by_stage"), dict)
    correction_stage = stage_observability["by_stage"]["recipe_refine"]
    assert isinstance(correction_stage.get("status_semantics_counts"), dict)


def test_build_upload_bundle_for_existing_output_includes_navigation_and_locators(
    tmp_path: Path,
) -> None:
    fixture = _build_existing_upload_bundle_fixture(tmp_path)
    module = fixture["module"]
    index_payload = fixture["index_payload"]
    artifact_paths = fixture["artifact_paths"]
    assert isinstance(index_payload, dict)
    assert isinstance(artifact_paths, set)

    navigation_payload = index_payload.get("navigation")
    assert isinstance(navigation_payload, dict)
    default_views = navigation_payload.get("default_initial_views")
    assert isinstance(default_views, list)
    assert default_views.index("analysis.turn1_summary") < default_views.index(
        "analysis.benchmark_pair_inventory"
    )
    assert default_views.index("analysis.benchmark_pair_inventory") < default_views.index(
        "analysis.triage_packet"
    )
    assert default_views.index("analysis.active_recipe_span_breakout") < default_views.index(
        "analysis.triage_packet"
    )
    assert "analysis.triage_packet" in default_views
    assert "analysis.explicit_escalation_changed_lines_packet" in default_views
    assert "analysis.recipe_pipeline_context" in default_views
    assert "analysis.structure_label_report" in default_views
    row_locators = navigation_payload.get("row_locators")
    assert isinstance(row_locators, dict)
    root_locators = row_locators.get("root_files")
    assert isinstance(root_locators, dict)
    assert all(isinstance(locator, dict) for locator in root_locators.values())
    comparison_locator = root_locators.get("comparison_summary_json")
    assert isinstance(comparison_locator, dict)
    assert comparison_locator.get("path") in {
        "codex_vs_vanilla_comparison.json",
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/comparison_summary.json",
    }
    starter_locators = row_locators.get("starter_pack")
    assert isinstance(starter_locators, dict)
    for key in (
        "triage_jsonl",
        "triage_packet_jsonl",
        "call_inventory_jsonl",
        "changed_lines_jsonl",
        "warning_trace_summary_json",
        "bridge_summary_jsonl",
        "selected_packets_jsonl",
        "casebook_md",
        "manifest_json",
    ):
        assert isinstance(starter_locators.get(key), dict)
    triage_packet_locator = root_locators.get("triage_packet_jsonl")
    assert isinstance(triage_packet_locator, dict)
    assert triage_packet_locator.get("path") == (
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/{module.STARTER_PACK_TRIAGE_PACKET_FILE_NAME}"
    )
    assert triage_packet_locator.get("alias_path") == (
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/{module.STARTER_PACK_DIR_NAME}/{module.STARTER_PACK_TRIAGE_PACKET_FILE_NAME}"
    )
    assert isinstance(root_locators.get("net_error_blame_summary_json"), dict)
    assert isinstance(root_locators.get("config_version_metadata_json"), dict)
    assert isinstance(root_locators.get("explicit_escalation_changed_lines_packet_jsonl"), dict)
    alias_dedupe = navigation_payload.get("alias_dedupe")
    assert isinstance(alias_dedupe, dict)
    assert int(alias_dedupe.get("content_equivalent_group_count") or 0) >= 1
    derived_root_run_index = (
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/run_index.json"
    )
    assert derived_root_run_index in artifact_paths
    self_check = index_payload.get("self_check")
    assert isinstance(self_check, dict)
    assert float(self_check.get("critical_row_locators_coverage_ratio") or 0.0) >= 0.9


def test_regression_casebook_uses_signal_fallback_when_no_negative_delta() -> None:
    module = _load_cutdown_module()

    casebook = module._upload_bundle_build_regression_casebook(
        recipe_triage_rows=[
            {
                "recipe_id": "recipe:quiet",
                "delta_codex_minus_baseline": 0.0,
                "changed_lines_codex_vs_baseline": 0,
                "outside_span_wrong_line_count": 0,
                "recipe_error_count": 0,
                "recipe_warning_count": 0,
            },
            {
                "recipe_id": "recipe:span-heavy",
                "delta_codex_minus_baseline": 0.0,
                "changed_lines_codex_vs_baseline": 1,
                "outside_span_wrong_line_count": 12,
                "recipe_error_count": 1,
                "recipe_warning_count": 0,
            },
            {
                "recipe_id": "recipe:changed-lines",
                "delta_codex_minus_baseline": 0.0,
                "changed_lines_codex_vs_baseline": 5,
                "outside_span_wrong_line_count": 3,
                "recipe_error_count": 0,
                "recipe_warning_count": 1,
            },
        ],
        changed_line_rows=[],
    )

    assert casebook["suggested_target_source"] == "top_signal_recipes"
    assert casebook["suggested_targets"][:2] == [
        "recipe:span-heavy",
        "recipe:changed-lines",
    ]
    assert casebook["packets"][0]["selection_reason"] == "top_signal_fill"


def test_recipe_correction_output_accounting_check_rejects_nonempty_compact_outputs_marked_empty() -> None:
    module = _load_cutdown_module()

    with pytest.raises(ValueError, match="recipe correction output accounting mismatch"):
        module._upload_bundle_assert_recipe_correction_output_accounting(
            correction_prompt_rows=_prompt_rows_for_compact_recipe_correction_fixture(),
            stage_observability_summary={
                "by_stage": {
                    "recipe_refine": {
                        "recipe_count": 2,
                        "output_signal_count": 0,
                        "empty_output_signal_count": 2,
                    }
                }
            },
        )


def test_build_upload_bundle_for_existing_output_surfaces_run_diagnostics_and_overview(
    tmp_path: Path,
) -> None:
    fixture = _build_existing_upload_bundle_fixture(tmp_path)
    module = fixture["module"]
    bundle_dir = fixture["bundle_dir"]
    index_payload = fixture["index_payload"]
    codex_run_id = fixture["codex_run_id"]
    baseline_run_id = fixture["baseline_run_id"]
    assert isinstance(bundle_dir, Path)
    assert isinstance(index_payload, dict)
    assert isinstance(codex_run_id, str)
    assert isinstance(baseline_run_id, str)

    run_diagnostics = index_payload.get("run_diagnostics")
    assert isinstance(run_diagnostics, list)
    codex_diag = next(
        row for row in run_diagnostics if str(row.get("run_id") or "") == codex_run_id
    )
    assert codex_diag["prompt_warning_aggregate_status"] == "written"
    assert codex_diag["projection_trace_status"] == "written"
    assert codex_diag["wrong_label_full_context_status"] == "written"
    assert codex_diag["preprocess_trace_failures_status"] == "written"
    baseline_diag = next(
        row for row in run_diagnostics if str(row.get("run_id") or "") == baseline_run_id
    )
    assert baseline_diag["prompt_warning_aggregate_status"] == "not_applicable"
    assert baseline_diag["projection_trace_status"] == "not_applicable"
    assert baseline_diag["preprocess_trace_failures_status"] == "not_applicable"
    overview_text = _read_text(bundle_dir / module.UPLOAD_BUNDLE_OVERVIEW_FILE_NAME)
    assert "## Turn-1 Summary" in overview_text
    assert "## Active Recipe Span Breakout" in overview_text
    assert "## Runtime / Cost Snapshot" in overview_text
    assert "## Stage Observability" in overview_text
    assert "## Top Confusion Deltas" in overview_text
    assert "suggested_available_targets" in overview_text


def test_build_upload_bundle_for_existing_output_derives_diagnostics_without_cutdown_summary(
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
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[
            {
                "line_index": 1,
                "gold_label": "INGREDIENT_LINE",
                "pred_label": "RECIPE_NOTES",
            },
            {
                "line_index": 3,
                "gold_label": "RECIPE_NOTES",
                "pred_label": "KNOWLEDGE",
            },
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
    _write_json(
        session_root / "codex_vs_vanilla_comparison.json",
        {"schema_version": "codex_vs_vanilla_comparison.v2"},
    )

    codex_run_dir = session_root / codex_run_id
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(codex_run_dir, "prediction-run")

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    assert index_payload["topline"]["full_prompt_log_status"] == "complete"
    assert (
        index_payload["topline"]["full_prompt_log_status_source"]
        == "derived_from_run_diagnostics"
    )
    regression_casebook = index_payload["analysis"]["regression_casebook"]
    assert regression_casebook["target_request_status"] == "none_found"
    assert isinstance(regression_casebook.get("suggested_targets"), list)
    assert regression_casebook["suggested_target_source"] == "top_negative_delta_recipes"
    run_diagnostics = index_payload.get("run_diagnostics")
    assert isinstance(run_diagnostics, list)
    codex_diag = next(
        row for row in run_diagnostics if str(row.get("run_id") or "") == codex_run_id
    )
    assert codex_diag["prompt_warning_aggregate_status"] == "written"
    assert codex_diag["projection_trace_status"] == "written"
    assert codex_diag["wrong_label_full_context_status"] == "written"
    assert codex_diag["preprocess_trace_failures_status"] == "written"
    payload_rows = _read_jsonl(bundle_dir / module.UPLOAD_BUNDLE_PAYLOAD_FILE_NAME)
    baseline_trace_parity = next(
        row["content_json"]
        for row in payload_rows
        if row.get("path")
        == f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/16_baseline_trace_parity.json"
    )
    pair_row = baseline_trace_parity["pair_rows"][0]
    assert pair_row["codex_statuses"][module.PROMPT_WARNING_AGGREGATE_FILE_NAME] == "present"
    assert pair_row["codex_statuses"][module.PROJECTION_TRACE_FILE_NAME] == "present"
    assert pair_row["codex_statuses"][module.PREPROCESS_TRACE_FAILURES_FILE_NAME] == "present"
    assert pair_row["parity_flags"]["codex_only_trace_fields_present_for_codex"] is True

    artifact_index = index_payload.get("artifact_index")
    assert isinstance(artifact_index, list)
    artifact_paths = {
        str(row.get("path") or "")
        for row in artifact_index
        if isinstance(row, dict)
    }
    derived_prefix = f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/runs/{codex_run_id}/"
    assert f"{derived_prefix}{module.PROMPT_WARNING_AGGREGATE_FILE_NAME}" in artifact_paths
    assert f"{derived_prefix}{module.PROJECTION_TRACE_FILE_NAME}" in artifact_paths
    assert (
        f"{derived_prefix}{module.WRONG_LABEL_FULL_CONTEXT_FILE_NAME.replace('.gz', '')}"
        in artifact_paths
    )
    assert (
        f"{derived_prefix}{module.PREPROCESS_TRACE_FAILURES_FILE_NAME.replace('.gz', '')}"
        in artifact_paths
    )


def test_upload_bundle_sort_recipe_triage_rows_deprioritizes_zero_change_empty_mapping_rows() -> None:
    module = _load_cutdown_module()
    triage_rows = [
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:empty-zero",
            "changed_lines_codex_vs_baseline": 0,
            "delta_codex_minus_baseline": 0.0,
            "final_recipe_empty_mapping": True,
            "correction_empty_mapping": True,
            "outside_span_wrong_line_count": 0,
            "line_total": 0,
            "correction_warning_count": 0,
            "recipe_warning_count": 0,
            "final_recipe_warning_count": 0,
        },
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:changed",
            "changed_lines_codex_vs_baseline": 3,
            "delta_codex_minus_baseline": -0.25,
            "final_recipe_empty_mapping": False,
            "correction_empty_mapping": False,
            "outside_span_wrong_line_count": 1,
            "line_total": 10,
            "correction_warning_count": 1,
            "recipe_warning_count": 0,
            "final_recipe_warning_count": 0,
        },
    ]

    sorted_rows = module._upload_bundle_sort_recipe_triage_rows(triage_rows)

    assert [row["recipe_id"] for row in sorted_rows] == [
        "recipe:changed",
        "recipe:empty-zero",
    ]


def test_upload_bundle_select_triage_packet_sample_rows_omits_zero_signal_rows() -> None:
    module = _load_cutdown_module()
    triage_packet_rows = [
        {
            "recipe_id": "recipe:empty-zero",
            "changed_lines_codex_vs_baseline": 0,
            "outside_span_wrong_line_count": 0,
            "delta_codex_minus_baseline": None,
            "line_total": 0,
            "correction_warning_count": 0,
            "final_recipe_warning_count": 0,
            "final_recipe_empty_mapping": True,
        }
    ]

    sample_rows, sample_note = module._upload_bundle_select_triage_packet_sample_rows(
        triage_packet_rows,
        pair_count=1,
    )

    assert sample_rows == []
    assert "No triage rows had recipe-local signal" in sample_note


def test_build_upload_bundle_stage_separated_comparison_scores_recipe_correction_and_final_recipe(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-03_10.40.00"
    baseline_run_id = "2026-03-03_10.39.00"

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

    for run_id in (codex_run_id, baseline_run_id):
        _set_eval_report_per_label(
            session_root / run_id,
            per_label={
                "INGREDIENT_LINE": {
                    "precision": 0.5,
                    "recall": 0.5,
                    "f1": 0.5,
                    "gold_total": 1,
                    "pred_total": 1,
                }
            },
        )

    codex_prediction_run = _write_prediction_run(
        session_root / codex_run_id,
        with_extracted_archive=True,
    )
    _write_prediction_run_stage_outputs(codex_prediction_run, recipe_id="recipe:c0")
    _set_pred_run_artifact(session_root / codex_run_id, "prediction-run")

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    stage_separated = index_payload["analysis"]["stage_separated_comparison"]
    per_label_rows = stage_separated["per_label"]
    ingredient_row = next(
        row for row in per_label_rows if str(row.get("label") or "") == "INGREDIENT_LINE"
    )
    recipe_stages = {
        str(stage.get("stage_key") or ""): stage
        for stage in ingredient_row["recipe_stages"]
        if isinstance(stage, dict)
    }
    correction_stage = recipe_stages["recipe_refine"]
    final_stage = recipe_stages["recipe_build_final"]
    intermediate_stage = recipe_stages["recipe_build_intermediate"]

    assert correction_stage["label_scored"] is True
    assert final_stage["label_scored"] is True
    assert intermediate_stage["label_scored"] is False
    assert int(correction_stage["runs_scored"]) == 1
    assert int(final_stage["runs_scored"]) == 1
    assert "unavailable_reason" not in correction_stage
    assert "unavailable_reason" not in final_stage
    assert "unavailable_reason" in intermediate_stage
    assert float(correction_stage["f1_avg"]) > 0.0
    assert float(final_stage["f1_avg"]) > 0.0
