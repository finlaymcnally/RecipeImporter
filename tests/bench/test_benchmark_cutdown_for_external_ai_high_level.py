from __future__ import annotations

import tests.bench.benchmark_cutdown_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_build_upload_bundle_high_level_only_scales_group_samples_by_run_count(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    target_bundle_size_bytes = 300_000

    def _make_wrong_rows() -> list[dict[str, object]]:
        return [
            {
                "line_index": index,
                "gold_label": "INGREDIENT_LINE",
                "pred_label": "RECIPE_NOTES",
                "line_text": f"Line {index} " + ("x" * 64),
            }
            for index in range(1, 121)
        ]

    single_root = tmp_path / "single-profile-benchmark-single"
    _make_run_record(
        module,
        run_root=single_root,
        run_id="2026-03-04_10.00.00",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=_make_wrong_rows(),
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )
    single_bundle_dir = single_root / "upload_bundle_v1"
    single_metadata = module.build_upload_bundle_for_existing_output(
        source_dir=single_root,
        output_dir=single_bundle_dir,
        overwrite=True,
        prune_output_dir=False,
        high_level_only=True,
        target_bundle_size_bytes=target_bundle_size_bytes,
    )

    multi_root = tmp_path / "single-profile-benchmark-multi"
    for index in range(1, 4):
        _make_run_record(
            module,
            run_root=multi_root,
            run_id=f"2026-03-04_10.0{index}.00",
            llm_recipe_pipeline="codex-recipe-shard-v1",
            line_role_pipeline="codex-line-role-route-v2",
            wrong_label_rows=_make_wrong_rows(),
            full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
        )
        run_dir = multi_root / f"2026-03-04_10.0{index}.00"
        _write_prediction_run(run_dir, with_extracted_archive=False)
        _set_pred_run_artifact(run_dir, "prediction-run")
        _write_json(
            run_dir / "prediction-run" / "prompt_budget_summary.json",
            {
                "schema_version": "prompt_budget_summary.v1",
                "by_stage": {
                    "recipe_correction": {
                        "call_count": 2,
                        "duration_total_ms": 200,
                        "tokens_total": 3000,
                    },
                },
            },
        )
    multi_bundle_dir = multi_root / "upload_bundle_v1"
    multi_metadata = module.build_upload_bundle_for_existing_output(
        source_dir=multi_root,
        output_dir=multi_bundle_dir,
        overwrite=True,
        prune_output_dir=False,
        high_level_only=True,
        target_bundle_size_bytes=target_bundle_size_bytes,
    )

    def _load_group_packet(bundle_dir: Path) -> dict[str, object]:
        payload_rows = _read_jsonl(bundle_dir / module.UPLOAD_BUNDLE_PAYLOAD_FILE_NAME)
        group_path = (
            f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/"
            f"{module.GROUP_UPLOAD_BUNDLE_GROUP_PACKET_FILE_NAME}"
        )
        group_row = next(
            row for row in payload_rows if str(row.get("path") or "") == group_path
        )
        content_json = group_row.get("content_json")
        assert isinstance(content_json, dict)
        return content_json

    single_packet = _load_group_packet(single_bundle_dir)
    multi_packet = _load_group_packet(multi_bundle_dir)

    single_sample_count = int(
        (single_packet.get("runs") or [{}])[0].get("sampled_wrong_line_count") or 0
    )
    multi_sample_counts = [
        int(row.get("sampled_wrong_line_count") or 0)
        for row in (multi_packet.get("runs") or [])
        if isinstance(row, dict)
    ]
    assert single_sample_count > 0
    assert multi_sample_counts
    assert (
        int(single_packet.get("per_run_sample_budget_bytes") or 0)
        > int(multi_packet.get("per_run_sample_budget_bytes") or 0)
    )
    assert max(multi_sample_counts) <= single_sample_count

    single_index_payload = _read_json(single_bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    multi_index_payload = _read_json(multi_bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    single_group_summary = single_index_payload["analysis"]["group_high_level"]
    multi_group_summary = multi_index_payload["analysis"]["group_high_level"]
    assert single_group_summary["enabled"] is True
    assert multi_group_summary["enabled"] is True
    assert int(single_group_summary["target_bundle_size_bytes"]) == target_bundle_size_bytes
    assert int(multi_group_summary["target_bundle_size_bytes"]) == target_bundle_size_bytes
    assert single_metadata["high_level_only"] is True
    assert multi_metadata["high_level_only"] is True

    multi_artifact_paths = set(multi_index_payload["review_packet"]["selected_paths"])
    prompt_budget_summary_paths = sorted(
        path for path in multi_artifact_paths if path.endswith("prompt_budget_summary.json")
    )
    assert prompt_budget_summary_paths == []
    assert not any(path.endswith("full_prompt_log.jsonl") for path in multi_artifact_paths)
    assert "selected_payload_rows" in multi_index_payload.get("navigation", {})


def test_build_upload_bundle_high_level_only_enforces_final_bundle_size(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    target_bundle_size_bytes = 260_000
    session_root = tmp_path / "single-profile-benchmark"
    session_root.mkdir(parents=True, exist_ok=True)

    def _make_large_prompt_rows(run_label: str) -> list[dict[str, object]]:
        return [
            {
                "stage_key": "recipe_build_final",
                "call_id": f"{run_label}-build-final-{index}",
                "recipe_id": f"recipe:{run_label}:{index}",
                "parsed_response": {
                    "warnings": [f"warning {index}"],
                    "ingredient_step_mapping": "{}",
                },
                "request_input_payload": {
                    "blocks_candidate": [
                        {
                            "text": f"{run_label} " + ("x" * 1800),
                        }
                    ]
                },
            }
            for index in range(90)
        ]

    (session_root / module.TARGETED_PROMPT_CASES_FILE_NAME).write_text(
        "targeted\n" + ("y" * 170_000),
        encoding="utf-8",
    )

    for index in range(1, 4):
        run_id = f"2026-03-04_11.0{index}.00"
        _make_run_record(
            module,
            run_root=session_root,
            run_id=run_id,
            llm_recipe_pipeline="codex-recipe-shard-v1",
            line_role_pipeline="codex-line-role-route-v2",
            wrong_label_rows=[
                {
                    "line_index": row_index,
                    "gold_label": "INGREDIENT_LINE",
                    "pred_label": "RECIPE_NOTES",
                    "line_text": f"Run {index} line {row_index} " + ("z" * 120),
                }
                for row_index in range(1, 121)
            ],
            full_prompt_rows=_make_large_prompt_rows(f"run{index}"),
        )

    bundle_dir = session_root / "upload_bundle_v1"
    metadata = module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
        high_level_only=True,
        target_bundle_size_bytes=target_bundle_size_bytes,
    )

    bundle_size_bytes = _bundle_dir_size_bytes(bundle_dir)
    assert bundle_size_bytes <= target_bundle_size_bytes
    assert metadata["high_level_only"] is True

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    artifact_paths = set(index_payload["review_packet"]["selected_paths"])
    group_summary = index_payload["analysis"]["group_high_level"]

    assert group_summary["enabled"] is True
    assert group_summary["serialized_size_capped"] is True
    assert int(group_summary["final_bundle_bytes"]) == bundle_size_bytes
    assert int(group_summary["final_payload_bytes"]) < target_bundle_size_bytes
    omitted_rows = group_summary.get("omitted_artifacts")
    assert isinstance(omitted_rows, list)
    assert any(
        isinstance(row, dict)
        and str(row.get("path") or "").endswith(module.TARGETED_PROMPT_CASES_FILE_NAME)
        and str(row.get("reason") or "") == "final_size_trim"
        for row in omitted_rows
    )
    assert module.TARGETED_PROMPT_CASES_FILE_NAME not in artifact_paths
    assert not any(path.endswith("full_prompt_log.jsonl") for path in artifact_paths)


def _build_high_level_multi_book_upload_bundle_fixture(tmp_path: Path) -> dict[str, object]:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-profile-benchmark"

    def _prompt_rows_with_runtime(
        *,
        duration_values: tuple[int, int, int],
        token_values: tuple[int, int, int],
        cost_values: tuple[float, float, float],
    ) -> list[dict[str, object]]:
        rows = _prompt_rows_for_starter_pack_fixture()
        enriched: list[dict[str, object]] = []
        for index, row in enumerate(rows):
            row_copy = dict(row)
            row_copy["request_telemetry"] = {
                "duration_ms": duration_values[index],
                "tokens_input": token_values[index] - 10,
                "tokens_output": 10,
                "tokens_total": token_values[index],
                "cost_usd": cost_values[index],
            }
            enriched.append(row_copy)
        return enriched

    # Book A (duplicate run ids with book B on purpose: vanilla/codex-exec).
    _make_run_record(
        module,
        run_root=session_root / "book_a",
        run_id="vanilla",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
        source_path="/tmp/book_a.epub",
        source_hash="book-a-hash",
    )
    _make_run_record(
        module,
        run_root=session_root / "book_a",
        run_id="codex-exec",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_with_runtime(
            duration_values=(100, 200, 300),
            token_values=(120, 220, 320),
            cost_values=(0.12, 0.22, 0.32),
        ),
        line_role_prediction_rows=[
            {
                "line_index": 1,
                "label": "INGREDIENT_LINE",
                "decided_by": "llm",
                "escalation_reasons": ["explicit_escalation_reasons"],
                "text": "1 cup flour",
                "within_recipe_span": True,
                "page_type": "recipe_page",
                "chapter_title": "Chapter A",
            }
        ],
        source_path="/tmp/book_a.epub",
        source_hash="book-a-hash",
    )
    _set_eval_report_metrics(
        session_root / "book_a" / "vanilla",
        overall_line_accuracy=0.70,
        macro_f1_excluding_other=0.68,
        practical_f1=0.69,
    )
    _set_eval_report_metrics(
        session_root / "book_a" / "codex-exec",
        overall_line_accuracy=0.62,
        macro_f1_excluding_other=0.61,
        practical_f1=0.60,
    )

    # Book B.
    _make_run_record(
        module,
        run_root=session_root / "book_b",
        run_id="vanilla",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
        source_path="/tmp/book_b.epub",
        source_hash="book-b-hash",
    )
    _make_run_record(
        module,
        run_root=session_root / "book_b",
        run_id="codex-exec",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_with_runtime(
            duration_values=(1000, 2000, 3000),
            token_values=(1120, 1220, 1320),
            cost_values=(1.12, 1.22, 1.32),
        ),
        line_role_prediction_rows=[
            {
                "line_index": 1,
                "label": "INGREDIENT_LINE",
                "decided_by": "llm",
                "escalation_reasons": ["explicit_escalation_reasons"],
                "text": "1 cup flour",
                "within_recipe_span": False,
                "page_type": "front_matter",
                "chapter_title": "Chapter B",
            }
        ],
        source_path="/tmp/book_b.epub",
        source_hash="book-b-hash",
    )
    _set_eval_report_metrics(
        session_root / "book_b" / "vanilla",
        overall_line_accuracy=0.62,
        macro_f1_excluding_other=0.61,
        practical_f1=0.60,
    )
    _set_eval_report_metrics(
        session_root / "book_b" / "codex-exec",
        overall_line_accuracy=0.71,
        macro_f1_excluding_other=0.70,
        practical_f1=0.72,
    )

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
        high_level_only=True,
        target_bundle_size_bytes=300_000,
    )

    return {
        "analysis": _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)["analysis"],
        "index_payload": _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME),
    }


def test_build_upload_bundle_high_level_multi_book_adds_book_level_analysis(
    tmp_path: Path,
) -> None:
    fixture = _build_high_level_multi_book_upload_bundle_fixture(tmp_path)
    analysis = fixture["analysis"]
    assert isinstance(analysis, dict)

    assert analysis["group_high_level"]["enabled"] is True
    pair_inventory = analysis.get("benchmark_pair_inventory")
    assert isinstance(pair_inventory, dict)
    assert int(pair_inventory.get("pair_count") or 0) >= 2
    turn1_summary = analysis.get("turn1_summary")
    assert isinstance(turn1_summary, dict)
    assert isinstance(turn1_summary.get("top_triage_rows"), list)


def test_build_upload_bundle_high_level_multi_book_aggregates_runtime_by_book(
    tmp_path: Path,
) -> None:
    fixture = _build_high_level_multi_book_upload_bundle_fixture(tmp_path)
    analysis = fixture["analysis"]
    assert isinstance(analysis, dict)

    runtime_summary = analysis.get("call_inventory_runtime", {}).get("summary")
    assert isinstance(runtime_summary, dict)
    assert runtime_summary.get("runtime_source") in {
        "call_inventory_rows",
        "call_inventory_rows_plus_prediction_run_prompt_budget_summary",
    }
    assert isinstance(runtime_summary.get("by_stage"), list)
    assert any(
        isinstance(row, dict) and str(row.get("stage_key") or "") == "recipe_refine"
        for row in runtime_summary.get("by_stage", [])
    )


def test_build_upload_bundle_high_level_multi_book_exposes_trace_navigation(
    tmp_path: Path,
) -> None:
    fixture = _build_high_level_multi_book_upload_bundle_fixture(tmp_path)
    analysis = fixture["analysis"]
    index_payload = fixture["index_payload"]
    assert isinstance(analysis, dict)
    assert isinstance(index_payload, dict)

    navigation_payload = index_payload.get("navigation")
    assert isinstance(navigation_payload, dict)
    default_views = navigation_payload.get("recommended_read_order")
    assert isinstance(default_views, list)
    for expected in (
        "analysis.benchmark_pair_inventory",
        "analysis.active_recipe_span_breakout",
        "analysis.net_error_blame_summary",
        "analysis.top_confusion_deltas",
        "analysis.triage_packet",
    ):
        assert expected in default_views

    self_check = index_payload.get("self_check")
    assert isinstance(self_check, dict)
    assert float(self_check.get("critical_row_locators_coverage_ratio") or 0.0) >= 0.75


def test_build_upload_bundle_self_check_flags_inconsistent_advertised_topline(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-03_10.20.00"
    baseline_run_id = "2026-03-03_10.19.00"

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

    _write_json(session_root / "run_index.json", {"runs": []})
    _write_json(
        session_root / "comparison_summary.json",
        {"pairs": [], "changed_lines_total": 0},
    )

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    assert int(index_payload["topline"]["run_count"]) == 2
    assert int(index_payload["topline"]["pair_count"]) == 1
    assert int(index_payload["topline"]["changed_lines_total"]) >= 1
    self_check = index_payload["self_check"]
    assert self_check["run_count_verified"] is False
    assert self_check["pair_count_verified"] is False
    assert self_check["changed_lines_verified"] is False
    assert self_check["topline_consistent"] is False
    assert self_check["critical_row_locators_populated"] >= 1


def test_build_upload_bundle_critical_row_locator_coverage_gate(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-03_10.22.00"
    baseline_run_id = "2026-03-03_10.21.00"

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

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    self_check = index_payload["self_check"]
    coverage = float(self_check.get("critical_row_locators_coverage_ratio") or 0.0)
    # Keep a small floor so future changes don't silently null out every critical locator.
    assert coverage >= 0.14
