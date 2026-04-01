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


def _build_existing_upload_bundle_fixture(tmp_path: Path) -> dict[str, object]:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-03_10.18.00"
    baseline_run_id = "2026-03-03_10.17.00"

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
    _write_json(
        session_root / "codex_vs_vanilla_comparison.json",
        {"schema_version": "codex_vs_vanilla_comparison.v2"},
    )
    codex_run_dir = session_root / codex_run_id
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(codex_run_dir, "prediction-run")
    seeded_cutdown_dir = tmp_path / "seed_cutdown" / codex_run_id
    module._build_run_cutdown(
        run_dir=codex_run_dir,
        output_run_dir=seeded_cutdown_dir,
        sample_limit=80,
        excerpt_limit=200,
        top_confusions_limit=8,
        top_labels_limit=6,
        prompt_pairs_per_category=3,
        prompt_excerpt_limit=400,
    )
    shutil.copy2(
        seeded_cutdown_dir / "need_to_know_summary.json",
        codex_run_dir / "need_to_know_summary.json",
    )

    bundle_dir = session_root / "upload_bundle_v1"
    metadata = module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    artifact_paths = {
        str(row.get("path") or "")
        for row in index_payload["artifact_index"]
        if isinstance(row, dict)
    }

    return {
        "artifact_paths": artifact_paths,
        "baseline_run_id": baseline_run_id,
        "bundle_dir": bundle_dir,
        "codex_run_id": codex_run_id,
        "index_payload": index_payload,
        "metadata": metadata,
        "module": module,
        "session_root": session_root,
    }


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
    codex_run_id = "codexfarm"
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


def test_build_upload_bundle_uses_single_correction_stage_labels_only(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "codexfarm"
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

    stage_separated = index_payload["analysis"]["stage_separated_comparison"]
    assert stage_separated["recipe_topology_key"] == "single_correction"
    assert stage_separated["recipe_stages"] == [
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

    blame_summary = index_payload["analysis"]["net_error_blame_summary"]
    bucket_definitions = blame_summary["bucket_definitions"]
    assert "explicitly excluded" in str(bucket_definitions["nonrecipe_authority"])
    assert "correction-stage loss" in str(bucket_definitions["recipe_correction"])
    assert "final-stage status" in str(bucket_definitions["final_recipe"])

    overview_text = _read_text(bundle_dir / module.UPLOAD_BUNDLE_OVERVIEW_FILE_NAME)
    assert "## Recipe Pipeline Context" in overview_text
    assert "codex-recipe-shard-v1" in overview_text
    assert "Recipe Build Intermediate" in overview_text
    assert "Recipe Refine" in overview_text
    assert "Recipe Build Final" in overview_text

    payload_rows = _jsonl_rows_by_path(bundle_dir / module.UPLOAD_BUNDLE_PAYLOAD_FILE_NAME)
    casebook = payload_rows[
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/{module.STARTER_PACK_DIR_NAME}/07_casebook.md"
    ]["content_text"]
    assert "recipe_pipeline_id: codex-recipe-shard-v1" in str(casebook)
    assert (
        "recipe_stages: Recipe Build Intermediate, Recipe Refine, Recipe Build Final"
        in str(casebook)
    )
    assert "- Recipe Refine:" in str(casebook)


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
        run_id="codexfarm",
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
    codex_run_dir = session_root / "codexfarm"
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
    assert set(runtime_summary["by_stage"].keys()) == {
        "recipe_refine",
        "nonrecipe_finalize",
        "line_role",
    }
    assert (
        int(runtime_summary["by_stage"]["recipe_refine"]["total_tokens"])
        == 120000
    )
    assert (
        int(runtime_summary["by_stage"]["nonrecipe_finalize"]["total_tokens"])
        == 1141186
    )
    assert int(runtime_summary["by_stage"]["line_role"]["total_tokens"]) == 6535006


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
        run_id="codexfarm",
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
                "request_input_payload": {"blocks_candidate": [{"text": "Mix gently"}]},
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
    codex_run_dir = session_root / "codexfarm"
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
    assert set(runtime_summary["by_stage"].keys()) == {
        "recipe_refine",
        "nonrecipe_finalize",
        "line_role",
    }
    assert (
        int(runtime_summary["by_stage"]["recipe_refine"]["total_tokens"])
        == 120000
    )
    assert (
        int(runtime_summary["by_stage"]["nonrecipe_finalize"]["total_tokens"])
        == 25000
    )
    assert int(runtime_summary["by_stage"]["line_role"]["total_tokens"]) == 6535006

    top_slowest_calls = runtime_payload["top_slowest_calls"]
    assert top_slowest_calls[0]["call_id"] == "recipe-001"

    payload_rows = _jsonl_rows_by_path(bundle_dir / module.UPLOAD_BUNDLE_PAYLOAD_FILE_NAME)
    call_inventory_rows = payload_rows[
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/{module.STARTER_PACK_DIR_NAME}/02_call_inventory.jsonl"
    ]["content_jsonl_rows"]
    assert len(call_inventory_rows) == 3
    line_role_row = next(row for row in call_inventory_rows if row["stage_key"] == "line_role")
    assert line_role_row["duration_ms"] == 600
    assert line_role_row["tokens_input"] == 200
    assert line_role_row["tokens_cached_input"] == 50
    assert line_role_row["tokens_output"] == 100
    assert line_role_row["tokens_total"] == 300
    assert line_role_row["estimated_cost_usd"] is not None
    assert line_role_row["retry_attempt"] == 1
    assert line_role_row["runtime_status"] == "ok"
    assert int(top_slowest_calls[0]["duration_ms"]) == 1200
    top_estimated_cost_calls = runtime_payload["top_estimated_cost_calls"]
    assert top_estimated_cost_calls[0]["call_id"] == "recipe-001"
    assert float(top_estimated_cost_calls[0]["estimated_cost_usd"]) >= 0.42


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
        run_id="codexfarm",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=full_prompt_rows,
        source_path="/tmp/book.epub",
        source_hash="fixture-hash",
    )
    codex_run_dir = session_root / "codexfarm"
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
    assert runtime_summary["by_stage"]["nonrecipe_finalize"]["calls_with_runtime"] == 5
    assert (
        int(runtime_summary["by_stage"]["nonrecipe_finalize"]["total_tokens"]) == 9000
    )
    assert runtime_summary["by_stage"]["line_role"]["calls_with_runtime"] == 5
    assert runtime_summary["by_stage"]["line_role"]["avg_duration_ms"] == 102.0
    assert int(runtime_summary["by_stage"]["line_role"]["total_tokens"]) == 7000


def test_build_upload_bundle_surfaces_knowledge_summary_and_locators(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-profile-benchmark" / "book_a"
    run_id = "codexfarm"

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
    knowledge_summary = index_payload["analysis"]["knowledge"]
    assert knowledge_summary["enabled_run_count"] == 1
    assert knowledge_summary["runs_with_prompt_samples"] == 1
    assert knowledge_summary["runs_with_knowledge_manifest"] == 1
    assert knowledge_summary["total_knowledge_call_count"] == 4
    row = knowledge_summary["rows"][0]
    assert row["run_id"] == run_id
    assert row["enabled"] is True
    assert row["prompt_samples_status"] == "written"
    assert row["prompt_knowledge_status"] == "written"
    assert row["knowledge_manifest_status"] == "written"
    assert row["prompt_budget_summary_status"] == "written"
    assert row["prompt_samples_in_bundle"] is True
    assert row["prompt_knowledge_in_bundle"] is True
    assert row["knowledge_manifest_in_bundle"] is True
    assert row["prompt_budget_summary_in_bundle"] is True

    row_locators = index_payload["navigation"]["row_locators"]["knowledge_by_run"]
    assert isinstance(row_locators, list)
    locator_row = next(
        item for item in row_locators if str(item.get("run_id") or "") == run_id
    )
    assert locator_row["prompt_samples_md"]["path"].endswith(
        "prompts/prompt_type_samples_from_full_prompt_log.md"
    )
    assert locator_row["prompt_knowledge_txt"]["path"].endswith(
        "prompts/prompt_nonrecipe_finalize.txt"
    )
    assert locator_row["knowledge_manifest_json"]["path"].endswith(
        "prediction-run/raw/llm/fixture-slug/knowledge_manifest.json"
    )
    assert locator_row["prompt_budget_summary_json"]["path"].endswith(
        "prediction-run/prompt_budget_summary.json"
    )


def test_build_upload_bundle_discovers_current_single_book_knowledge_layout(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark" / "book_a"
    codex_run_id = "codexfarm"
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
    knowledge_summary = index_payload["analysis"]["knowledge"]
    assert knowledge_summary["enabled_run_count"] == 1
    assert knowledge_summary["runs_with_prompt_samples"] == 1
    assert knowledge_summary["runs_with_knowledge_manifest"] == 1
    assert knowledge_summary["total_knowledge_call_count"] == 4

    codex_row = next(
        row for row in knowledge_summary["rows"] if str(row.get("run_id") or "") == codex_run_id
    )
    assert codex_row["knowledge_call_count"] == 4
    assert codex_row["shards_written"] == 4
    assert codex_row["outputs_parsed"] == 4
    assert codex_row["snippets_written"] == 8
    assert codex_row["prompt_samples_status"] == "written"
    assert codex_row["prompt_knowledge_status"] == "written"
    assert codex_row["knowledge_manifest_status"] == "written"
    assert codex_row["prompt_budget_summary_status"] == "written"
    assert codex_row["prompt_samples_in_bundle"] is True
    assert codex_row["prompt_knowledge_in_bundle"] is True
    assert codex_row["knowledge_manifest_in_bundle"] is True
    assert codex_row["prompt_budget_summary_in_bundle"] is True

    baseline_row = next(
        row
        for row in knowledge_summary["rows"]
        if str(row.get("run_id") or "") == baseline_run_id
    )
    assert baseline_row["prompt_samples_in_bundle"] is False
    assert baseline_row["prompt_knowledge_in_bundle"] is False
    assert baseline_row["knowledge_manifest_in_bundle"] is False
    assert baseline_row["prompt_budget_summary_in_bundle"] is False

    row_locators = index_payload["navigation"]["row_locators"]["knowledge_by_run"]
    assert isinstance(row_locators, list)
    codex_locator_row = next(
        item for item in row_locators if str(item.get("run_id") or "") == codex_run_id
    )
    assert codex_locator_row["prompt_samples_md"]["path"].endswith(
        "prompts/prompt_type_samples_from_full_prompt_log.md"
    )
    assert codex_locator_row["prompt_knowledge_txt"]["path"].endswith(
        "prompts/prompt_nonrecipe_finalize.txt"
    )
    assert codex_locator_row["prompt_budget_summary_json"]["path"].endswith(
        "codexfarm/prompt_budget_summary.json"
    )
    assert codex_locator_row["knowledge_manifest_json"]["path"].endswith(
        "_upload_bundle_derived/runs/codexfarm/knowledge_manifest.json"
    )

    baseline_locator_row = next(
        item for item in row_locators if str(item.get("run_id") or "") == baseline_run_id
    )
    assert baseline_locator_row["prompt_samples_md"] is None
    assert baseline_locator_row["prompt_knowledge_txt"] is None
    assert baseline_locator_row["knowledge_manifest_json"] is None
    assert baseline_locator_row["prompt_budget_summary_json"] is None

    run_diagnostics = index_payload["run_diagnostics"]
    codex_diag = next(
        row for row in run_diagnostics if str(row.get("run_id") or "") == codex_run_id
    )
    assert codex_diag["full_prompt_log_status"] == "complete"
    assert codex_diag["prompt_warning_aggregate_status"] == "written"
    assert codex_diag["projection_trace_status"] == "written"
    assert codex_diag["preprocess_trace_failures_status"] == "written"


def test_resolve_knowledge_prompt_path_supports_dynamic_stage_file_names(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    run_dir = tmp_path / "single-profile-benchmark" / "book_a" / "codexfarm"
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
    run_dir = tmp_path / "single-profile-benchmark" / "book_a" / "codexfarm"
    _make_run_record(
        module,
        run_root=tmp_path / "single-profile-benchmark" / "book_a",
        run_id="codexfarm",
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
    run_id = "codexfarm"

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
    artifact_paths = {
        str(row.get("path") or "")
        for row in index_payload.get("artifact_index", [])
        if isinstance(row, dict)
    }
    assert f"{run_id}/prompts/prompt_type_samples_from_full_prompt_log.md" in artifact_paths
    assert (
        f"{run_id}/prediction-run/raw/llm/fixture-slug/knowledge_manifest.json"
        in artifact_paths
    )
    assert f"{run_id}/prompts/prompt_nonrecipe_finalize.txt" not in artifact_paths

    knowledge_summary = index_payload["analysis"]["knowledge"]["rows"][0]
    assert knowledge_summary["prompt_samples_in_bundle"] is True
    assert knowledge_summary["knowledge_manifest_in_bundle"] is True
    assert knowledge_summary["prompt_knowledge_in_bundle"] is False
