from __future__ import annotations

import tests.bench.benchmark_cutdown_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_summarize_prompt_warning_aggregate_counts_warnings(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    full_prompt_log_path = tmp_path / "full_prompt_log.jsonl"
    _write_jsonl(
        full_prompt_log_path,
        [
            {
                "stage_key": "recipe_refine",
                "recipe_id": "r0",
                "parsed_response": {
                    "warnings": [
                        "Serving information is split across two lines.",
                        "A page marker was excluded.",
                    ]
                },
            },
            {
                "stage_key": "recipe_build_final",
                "recipe_id": "r0",
                "parsed_response": {"warnings": [], "ingredient_step_mapping": "{}"},
            },
            {
                "stage_key": "recipe_build_final",
                "recipe_id": "r1",
                "parsed_response": {
                    "warnings": ["No explicit cooking instructions were provided."],
                    "ingredient_step_mapping": {},
                },
            },
        ],
    )

    summary = module._summarize_prompt_warning_aggregate(full_prompt_log_path)

    assert summary["total_calls"] == 3
    assert summary["calls_with_warnings"] == 2
    assert summary["warnings_total"] == 3
    assert summary["correction_empty_ingredient_step_mapping_calls"] == 2
    assert summary["warning_buckets"]["split_line_boundary"] >= 1
    assert summary["warning_buckets"]["missing_instructions"] >= 1


def test_build_pair_diagnostics_emits_changed_lines_and_breakdowns(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    codex_prompt_rows = [
        {
            "stage_key": "recipe_build_intermediate",
            "call_id": "c0-build-intermediate",
            "recipe_id": "recipe:c0",
            "parsed_response": {
                "is_recipe": True,
                "recipe_id": "recipe:c0",
                "start_block_index": 0,
                "end_block_index": 2,
                "title": "Dish Title",
            },
            "request_input_payload": {"blocks_candidate": [{"text": "Dish Title"}]},
        },
        {
            "stage_key": "recipe_build_final",
            "call_id": "c0-build-final",
            "recipe_id": "recipe:c0",
            "parsed_response": {
                "warnings": ["No explicit cooking instructions were provided."],
                "ingredient_step_mapping": "{}",
            },
            "request_input_payload": {"blocks_candidate": [{"text": "Mix gently"}]},
        },
    ]

    codex_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_10.00.00",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[
            {"line_index": 1, "pred_label": "RECIPE_NOTES"},
            {"line_index": 3, "pred_label": "KNOWLEDGE"},
        ],
        full_prompt_rows=codex_prompt_rows,
    )
    baseline_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_09.59.00",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
    )

    diagnostics = module._build_pair_diagnostics(
        source_key="source-hash",
        source_file="book.epub",
        codex_run=codex_record,
        baseline_run=baseline_record,
        excerpt_limit=120,
        targeted_case_limit=10,
    )

    changed_indices = {int(row["line_index"]) for row in diagnostics.changed_line_rows}
    assert changed_indices == {1, 3}
    assert all("current_line" in row for row in diagnostics.changed_line_rows)
    assert diagnostics.pair_breakdown["recipe_span_count"] == 1
    inside_row = next(
        row for row in diagnostics.pair_breakdown["region_breakdown"] if row["region"] == "inside_active_recipe_span"
    )
    outside_row = next(
        row
        for row in diagnostics.pair_breakdown["region_breakdown"]
        if row["region"] == "outside_active_recipe_span"
    )
    assert inside_row["line_total"] == 3
    assert outside_row["line_total"] == 1
    assert diagnostics.confusion_delta_codex_minus_baseline["RECIPE_NOTES"]["KNOWLEDGE"] == 1
    assert diagnostics.targeted_prompt_case_rows
    assert diagnostics.targeted_prompt_case_rows[0]["empty_ingredient_step_mapping"] is True


def test_build_pair_diagnostics_projects_recipe_spans_from_projected_spans(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    codex_prompt_rows = [
        {
            "stage_key": "recipe_build_intermediate",
            "call_id": "c0-build-intermediate",
            "recipe_id": "recipe:c0",
            "parsed_response": {
                "is_recipe": True,
                "recipe_id": "recipe:c0",
                "start_block_index": 10,
                "end_block_index": 12,
                "title": "Dish Title",
            },
            "request_input_payload": {"blocks_candidate": [{"text": "Dish Title"}]},
        },
        {
            "stage_key": "recipe_refine",
            "call_id": "c0-correction",
            "recipe_id": "recipe:c0",
            "parsed_response": {
                "warnings": ["No explicit cooking instructions were provided."],
                "canonical_recipe": {
                    "title": "Dish Title",
                    "ingredients": ["1 cup flour"],
                    "steps": ["Mix gently"],
                },
                "ingredient_step_mapping": {},
            },
            "request_input_payload": {
                "evidence_rows": [
                    [10, "Dish Title"],
                    [11, "1 cup flour"],
                    [12, "Mix gently"],
                ],
                "canonical_text": "Dish Title\n1 cup flour\nMix gently\nChef note\n",
            },
        },
        {
            "stage_key": "recipe_build_final",
            "call_id": "c0-build-final",
            "recipe_id": "recipe:c0",
            "parsed_response": {
                "warnings": ["No extracted instructions were provided."],
                "ingredient_step_mapping": "{}",
            },
            "request_input_payload": {"blocks_candidate": [{"text": "Mix gently"}]},
        },
    ]

    codex_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_10.00.00",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[
            {"line_index": 1, "pred_label": "RECIPE_NOTES"},
            {"line_index": 3, "pred_label": "KNOWLEDGE"},
        ],
        full_prompt_rows=codex_prompt_rows,
        projected_span_rows=[
            {
                "atomic_index": 100,
                "block_id": "b10",
                "block_index": 10,
                "label": "RECIPE_TITLE",
                "line_index": 0,
                "recipe_id": "recipe:0",
                "recipe_index": 0,
                "text": "Dish Title",
                "within_recipe_span": True,
            },
            {
                "atomic_index": 101,
                "block_id": "b11",
                "block_index": 11,
                "label": "INGREDIENT_LINE",
                "line_index": 1,
                "recipe_id": "recipe:0",
                "recipe_index": 0,
                "text": "1 cup flour",
                "within_recipe_span": True,
            },
            {
                "atomic_index": 102,
                "block_id": "b12",
                "block_index": 12,
                "label": "INSTRUCTION_LINE",
                "line_index": 2,
                "recipe_id": "recipe:0",
                "recipe_index": 0,
                "text": "Mix gently",
                "within_recipe_span": True,
            },
            {
                "atomic_index": 103,
                "block_id": "b13",
                "block_index": 13,
                "label": "RECIPE_NOTES",
                "line_index": 3,
                "recipe_id": None,
                "recipe_index": None,
                "text": "Chef note",
                "within_recipe_span": False,
            },
        ],
    )
    baseline_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_09.59.00",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
    )

    diagnostics = module._build_pair_diagnostics(
        source_key="source-hash",
        source_file="book.epub",
        codex_run=codex_record,
        baseline_run=baseline_record,
        excerpt_limit=120,
        targeted_case_limit=10,
    )

    inside_row = next(
        row
        for row in diagnostics.pair_breakdown["region_breakdown"]
        if row["region"] == "inside_active_recipe_span"
    )
    outside_row = next(
        row
        for row in diagnostics.pair_breakdown["region_breakdown"]
        if row["region"] == "outside_active_recipe_span"
    )
    triage_row = next(
        row for row in diagnostics.recipe_triage_rows if row["recipe_id"] == "recipe:c0"
    )

    assert inside_row["line_total"] == 3
    assert outside_row["line_total"] == 1
    assert triage_row["line_total"] == 3
    assert triage_row["changed_lines_codex_vs_baseline"] == 1
    assert triage_row["codex_accuracy"] is not None
    assert triage_row["baseline_accuracy"] is not None


def test_build_recipe_spans_from_full_prompt_rows_supports_sharded_recipe_payloads() -> None:
    module = _load_cutdown_module()

    spans = module._build_recipe_spans_from_full_prompt_rows(
        _prompt_rows_for_sharded_recipe_fixture()
    )

    assert spans == [
        {
            "recipe_id": "recipe:a0",
            "start_block_index": 0,
            "end_block_index": 1,
            "title": "Dish Title",
            "call_id": "recipe-shard-0000-r0000-r0001",
        },
        {
            "recipe_id": "recipe:b0",
            "start_block_index": 2,
            "end_block_index": 3,
            "title": "Chef Note Dish",
            "call_id": "recipe-shard-0000-r0000-r0001",
        },
    ]


def test_build_upload_bundle_reconciles_sharded_recipe_ids_to_per_recipe_counts(
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
            {"line_index": 1, "gold_label": "INGREDIENT_LINE", "pred_label": "RECIPE_NOTES"},
            {"line_index": 3, "gold_label": "RECIPE_NOTES", "pred_label": "KNOWLEDGE"},
        ],
        full_prompt_rows=_prompt_rows_for_sharded_recipe_fixture(),
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "gold_label": "INGREDIENT_LINE", "pred_label": "YIELD_LINE"}],
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
            "recipe:a0": _semantic_recipe_manifest_row(
                correction_status="error",
                build_final_status="error",
                structural_status="ok",
            ),
            "recipe:b0": _semantic_recipe_manifest_row(
                correction_status="error",
                build_final_status="error",
                structural_status="ok",
            ),
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
    active_span_breakout = index_payload["analysis"]["active_recipe_span_breakout"]
    assert active_span_breakout["recipe_span_count"] == 2
    assert active_span_breakout["pairs_with_zero_recipe_spans"] == 0

    stage_observability = index_payload["analysis"]["stage_observability_summary"]["by_stage"]
    assert stage_observability["recipe_refine"]["recipe_count"] == 2
    assert stage_observability["recipe_build_final"]["recipe_count"] == 2


def test_build_upload_bundle_uses_projected_spans_for_recipe_stage_blame(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "codex-exec"
    baseline_run_id = "vanilla"
    codex_prompt_rows = [
        {
            "stage_key": "recipe_build_intermediate",
            "call_id": "starter-build-intermediate",
            "recipe_id": "recipe:c0",
            "timestamp_utc": "2026-03-03T10:00:00Z",
            "model": "gpt-test",
            "parsed_response": {
                "is_recipe": True,
                "recipe_id": "recipe:c0",
                "start_block_index": 10,
                "end_block_index": 12,
                "title": "Dish Title",
                "excluded_block_ids": [],
            },
            "request_input_payload": {
                "blocks_candidate": [
                    {"index": 10, "block_id": "b10", "text": "Dish Title"},
                    {"index": 11, "block_id": "b11", "text": "1 cup flour"},
                    {"index": 12, "block_id": "b12", "text": "Mix gently"},
                    {"index": 13, "block_id": "b13", "text": "Chef note"},
                ],
                "blocks_after": [],
                "blocks_before": [],
            },
        },
        {
            "stage_key": "recipe_refine",
            "call_id": "starter-correction",
            "recipe_id": "recipe:c0",
            "timestamp_utc": "2026-03-03T10:00:05Z",
            "model": "gpt-test",
            "parsed_response": {
                "warnings": ["No explicit cooking instructions were provided."],
                "canonical_recipe": {
                    "title": "Dish Title",
                    "ingredients": ["1 cup flour"],
                    "steps": ["Mix gently"],
                },
                "ingredient_step_mapping": {},
            },
            "request_input_payload": {
                "evidence_rows": [
                    [10, "Dish Title"],
                    [11, "1 cup flour"],
                    [12, "Mix gently"],
                ],
                "canonical_text": "Dish Title\n1 cup flour\nMix gently\nChef note\n",
            },
        },
        {
            "stage_key": "recipe_build_final",
            "call_id": "starter-build-final",
            "recipe_id": "recipe:c0",
            "timestamp_utc": "2026-03-03T10:00:10Z",
            "model": "gpt-test",
            "parsed_response": {
                "warnings": ["No extracted instructions were provided."],
                "ingredient_step_mapping": "{}",
                "draft_v1": json.dumps(
                    {
                        "schema_v": 1,
                        "recipe": {"title": "Dish Title"},
                        "steps": [],
                    }
                ),
            },
            "request_input_payload": {
                "extracted_ingredients": [{"text": "1 cup flour"}],
                "extracted_instructions": [],
            },
        },
    ]

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=codex_prompt_rows,
        projected_span_rows=[
            {
                "atomic_index": 100,
                "block_id": "b10",
                "block_index": 10,
                "label": "RECIPE_TITLE",
                "line_index": 0,
                "recipe_id": "recipe:0",
                "recipe_index": 0,
                "text": "Dish Title",
                "within_recipe_span": True,
            },
            {
                "atomic_index": 101,
                "block_id": "b11",
                "block_index": 11,
                "label": "INGREDIENT_LINE",
                "line_index": 1,
                "recipe_id": "recipe:0",
                "recipe_index": 0,
                "text": "1 cup flour",
                "within_recipe_span": True,
            },
            {
                "atomic_index": 102,
                "block_id": "b12",
                "block_index": 12,
                "label": "INSTRUCTION_LINE",
                "line_index": 2,
                "recipe_id": "recipe:0",
                "recipe_index": 0,
                "text": "Mix gently",
                "within_recipe_span": True,
            },
            {
                "atomic_index": 103,
                "block_id": "b13",
                "block_index": 13,
                "label": "RECIPE_NOTES",
                "line_index": 3,
                "recipe_id": None,
                "recipe_index": None,
                "text": "Chef note",
                "within_recipe_span": False,
            },
        ],
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[],
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
    active_span_breakout = index_payload["analysis"]["active_recipe_span_breakout"]
    blame_rows = index_payload["analysis"]["net_error_blame_summary"]["bucket_rows"]
    blame_by_bucket = {
        str(row.get("bucket") or ""): row for row in blame_rows if isinstance(row, dict)
    }

    assert active_span_breakout["inside_active_recipe_span"]["line_total"] == 3
    assert active_span_breakout["outside_active_recipe_span"]["line_total"] == 1
    assert int(blame_by_bucket["final_recipe"]["new_error_count"]) == 1
    assert int(blame_by_bucket["line_role"]["new_error_count"]) == 0


def test_build_pair_diagnostics_enriches_triage_with_manifest_diagnostics(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    codex_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_12.00.00",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )
    baseline_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_11.59.00",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
    )

    codex_run_dir = Path(str(codex_record.run_dir))
    _write_prediction_run(
        codex_run_dir,
        with_extracted_archive=True,
        llm_manifest_recipes={
            "recipe:c0": _semantic_recipe_manifest_row(
                warnings=["No explicit cooking instructions were provided."],
                structural_reason_codes=["missing_instructions"],
            )
        },
    )
    _set_pred_run_artifact(codex_run_dir, "prediction-run")

    diagnostics = module._build_pair_diagnostics(
        source_key="source-hash",
        source_file="book.epub",
        codex_run=codex_record,
        baseline_run=baseline_record,
        excerpt_limit=120,
        targeted_case_limit=10,
    )

    triage_row = next(row for row in diagnostics.recipe_triage_rows if row["recipe_id"] == "recipe:c0")
    assert triage_row["build_intermediate_status"] == "ok"
    assert triage_row["correction_status"] == "degraded"
    assert triage_row["build_final_status"] == "fallback"
    assert triage_row["final_mapping_status"] == "fallback"
    assert triage_row["final_mapping_reason"] == "deterministic final assembly kept fallback mapping"
    assert triage_row["structural_status"] == "warning"
    assert triage_row["structural_reason_codes"] == ["missing_instructions"]
    assert triage_row["recipe_warning_count"] == 1
    assert triage_row["recipe_error_count"] == 0

    summary = module._build_warning_and_trace_summary(
        call_inventory_rows=diagnostics.call_inventory_rows,
        recipe_triage_rows=diagnostics.recipe_triage_rows,
        outside_span_trace_rows=diagnostics.outside_span_trace_rows,
    )
    assert summary["recipe_stage_status_counts"]["recipe_build_intermediate"]["ok"] == 1
    assert summary["recipe_stage_status_counts"]["recipe_refine"]["degraded"] == 1
    assert summary["recipe_stage_status_counts"]["recipe_build_final"]["fallback"] == 1
    assert summary["final_mapping_status_counts"]["fallback"] == 1
    assert summary["structural_status_counts"]["warning"] == 1


def test_build_pair_diagnostics_keeps_correction_empty_mapping_out_of_final_recipe_flag(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    codex_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_12.05.00",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture()[:2],
    )
    baseline_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_12.04.00",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
    )

    diagnostics = module._build_pair_diagnostics(
        source_key="source-hash",
        source_file="book.epub",
        codex_run=codex_record,
        baseline_run=baseline_record,
        excerpt_limit=120,
        targeted_case_limit=10,
    )

    triage_row = next(
        row for row in diagnostics.recipe_triage_rows if row["recipe_id"] == "recipe:c0"
    )
    assert triage_row["correction_empty_mapping"] is True
    assert triage_row["final_recipe_empty_mapping"] is False
    assert triage_row["build_final_call_id"] == ""


def test_build_pair_diagnostics_parses_compact_recipe_correction_outputs_per_recipe(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    codex_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_12.06.00",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[
            {"line_index": 1, "pred_label": "RECIPE_NOTES"},
            {"line_index": 4, "pred_label": "KNOWLEDGE"},
        ],
        full_prompt_rows=_prompt_rows_for_compact_recipe_correction_fixture(),
    )
    baseline_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_12.05.00",
        llm_recipe_pipeline="off",
        wrong_label_rows=[
            {"line_index": 1, "pred_label": "YIELD_LINE"},
            {"line_index": 4, "pred_label": "OTHER"},
        ],
    )

    diagnostics = module._build_pair_diagnostics(
        source_key="source-hash",
        source_file="book.epub",
        codex_run=codex_record,
        baseline_run=baseline_record,
        excerpt_limit=120,
        targeted_case_limit=10,
    )

    triage_by_id = {
        str(row["recipe_id"]): row for row in diagnostics.recipe_triage_rows
    }
    assert triage_by_id["recipe:a0"]["correction_input_block_count"] == 3
    assert triage_by_id["recipe:a0"]["correction_ingredient_count"] == 1
    assert triage_by_id["recipe:a0"]["correction_step_count"] == 1
    assert triage_by_id["recipe:a0"]["correction_mapping_count"] == 1
    assert triage_by_id["recipe:a0"]["correction_empty_mapping"] is False
    assert triage_by_id["recipe:a0"]["correction_empty_output"] is False

    assert triage_by_id["recipe:b0"]["correction_input_block_count"] == 3
    assert triage_by_id["recipe:b0"]["correction_ingredient_count"] == 1
    assert triage_by_id["recipe:b0"]["correction_step_count"] == 1
    assert triage_by_id["recipe:b0"]["correction_mapping_count"] == 0
    assert triage_by_id["recipe:b0"]["correction_empty_mapping"] is True
    assert triage_by_id["recipe:b0"]["correction_empty_output"] is False

    call_row = next(
        row
        for row in diagnostics.call_inventory_rows
        if row["stage_key"] == "recipe_refine"
    )
    assert call_row["input_block_count"] == 6
    assert call_row["extracted_ingredient_count"] == 2
    assert call_row["step_count"] == 2
    assert call_row["mapping_count"] == 1

    failure_ledger = module._upload_bundle_build_failure_ledger(
        recipe_triage_rows=diagnostics.recipe_triage_rows,
        call_inventory_rows=diagnostics.call_inventory_rows,
    )
    correction_rows = [
        row
        for row in failure_ledger["rows"]
        if row["stage_key"] == "recipe_refine"
    ]
    assert len(correction_rows) == 2
    assert all(row["output_signal"] is True for row in correction_rows)
    assert all(row["empty_output_signal"] is False for row in correction_rows)
    assert all(
        row["status_semantics"] == "nonempty_output_without_manifest_status"
        for row in correction_rows
    )

    stage_observability = module._upload_bundle_build_stage_observability_summary(
        failure_ledger
    )
    correction_stage = stage_observability["by_stage"]["recipe_refine"]
    assert correction_stage["recipe_count"] == 2
    assert correction_stage["output_signal_count"] == 2
    assert correction_stage["empty_output_signal_count"] == 0
    assert correction_stage["status_semantics_counts"] == {
        "nonempty_output_without_manifest_status": 2
    }

    warning_summary = module._build_warning_and_trace_summary(
        call_inventory_rows=diagnostics.call_inventory_rows,
        recipe_triage_rows=diagnostics.recipe_triage_rows,
        outside_span_trace_rows=diagnostics.outside_span_trace_rows,
    )
    assert warning_summary["correction_empty_mapping_count"] == 1
    assert warning_summary["correction_empty_output_count"] == 0
    assert warning_summary["correction_empty_mapping_with_nonempty_output_count"] == 1
    assert (
        warning_summary["recipe_stage_status_counts"]["recipe_refine"][
            "nonempty_output_without_manifest_status"
        ]
        == 2
    )


def test_build_pair_diagnostics_reads_recipe_manifest_from_processed_output_run_dir(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    codex_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_12.00.00",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )
    baseline_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_11.59.00",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
    )

    codex_run_dir = Path(str(codex_record.run_dir))
    processed_output_root = codex_run_dir / "processed-output"
    _write_processed_output_recipe_manifest(
        codex_run_dir,
        processed_output_root=processed_output_root,
        llm_manifest_recipes={
            "recipe:c0": _semantic_recipe_manifest_row(
                build_intermediate_status="ok",
                correction_status="ok",
                build_final_status="ok",
                mapping_status="not_needed",
                mapping_reason="not_needed_single_step",
                structural_status="ok",
            )
        },
    )

    diagnostics = module._build_pair_diagnostics(
        source_key=str(codex_record.source_key),
        source_file=str(codex_record.source_file),
        codex_run=codex_record,
        baseline_run=baseline_record,
        excerpt_limit=module.DEFAULT_EXCERPT_LIMIT,
        targeted_case_limit=module.DEFAULT_TARGETED_PROMPT_CASES,
    )

    triage_row = next(row for row in diagnostics.recipe_triage_rows if row["recipe_id"] == "recipe:c0")
    assert triage_row["build_final_status"] == "ok"
    assert triage_row["final_mapping_status"] == "not_needed"
    assert triage_row["final_mapping_reason"] == "not_needed_single_step"
    assert triage_row["structural_status"] == "ok"

    failure_ledger = module._upload_bundle_build_failure_ledger(
        recipe_triage_rows=diagnostics.recipe_triage_rows,
        call_inventory_rows=diagnostics.call_inventory_rows,
    )
    final_row = next(
        row
        for row in failure_ledger["rows"]
        if row["recipe_id"] == "recipe:c0" and row["stage_key"] == "recipe_build_final"
    )
    assert final_row["status"] == "ok"
    assert final_row["status_semantics"] == "recorded_status_with_empty_output_signal"


def test_build_comparison_summary_includes_pair_diagnostics(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    codex_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_11.00.00",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[
            {"line_index": 1, "pred_label": "RECIPE_NOTES"},
            {"line_index": 3, "pred_label": "KNOWLEDGE"},
        ],
        full_prompt_rows=[
            {
                "stage_key": "recipe_build_intermediate",
                "call_id": "case-build-intermediate",
                "recipe_id": "recipe:c0",
                "parsed_response": {
                    "is_recipe": True,
                    "recipe_id": "recipe:c0",
                    "start_block_index": 0,
                    "end_block_index": 2,
                },
                "request_input_payload": {"blocks_candidate": [{"text": "Dish Title"}]},
            },
            {
                "stage_key": "recipe_build_final",
                "call_id": "case-build-final",
                "recipe_id": "recipe:c0",
                "parsed_response": {
                    "warnings": ["No explicit cooking instructions were provided."],
                    "ingredient_step_mapping": "{}",
                },
            },
        ],
    )
    baseline_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_10.59.00",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
    )

    (
        summary,
        changed_lines,
        pair_breakdowns,
        targeted_cases,
        recipe_triage_rows,
        call_inventory_rows,
        outside_span_trace_rows,
    ) = module._build_comparison_summary(
        records=[codex_record, baseline_record],
        excerpt_limit=140,
        targeted_prompt_case_limit=10,
    )

    assert summary["pairs"][0]["changed_line_count"] == 2
    assert summary["pairs"][0]["confusion_matrix"]["delta_codex_minus_baseline"]["RECIPE_NOTES"][
        "KNOWLEDGE"
    ] == 1
    assert len(changed_lines) == 2
    assert len(pair_breakdowns) == 1
    assert targeted_cases
    assert recipe_triage_rows
    assert call_inventory_rows
    assert isinstance(outside_span_trace_rows, list)


def test_build_run_cutdown_writes_new_gzip_artifacts(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    run_id = "2026-03-03_10.00.00"
    _make_run_record(
        module,
        run_root=run_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[
            {"line_index": 1, "gold_label": "INGREDIENT_LINE", "pred_label": "RECIPE_NOTES"},
            {"line_index": 3, "gold_label": "RECIPE_NOTES", "pred_label": "KNOWLEDGE"},
        ],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )
    run_dir = run_root / run_id
    _write_prediction_run(run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(run_dir, "prediction-run")

    output_run_dir = tmp_path / "cutdown" / run_id
    module._build_run_cutdown(
        run_dir=run_dir,
        output_run_dir=output_run_dir,
        sample_limit=80,
        excerpt_limit=200,
        top_confusions_limit=8,
        top_labels_limit=6,
        prompt_pairs_per_category=3,
        prompt_excerpt_limit=400,
    )

    summary = _read_json(output_run_dir / "need_to_know_summary.json")
    sample_counts = summary["sample_counts"]
    assert sample_counts[module.WRONG_LABEL_FULL_CONTEXT_FILE_NAME]["status"] == "written"
    assert sample_counts[module.PREPROCESS_TRACE_FAILURES_FILE_NAME]["status"] == "written"

    wrong_context_rows = _read_jsonl_gzip(
        output_run_dir / module.WRONG_LABEL_FULL_CONTEXT_FILE_NAME
    )
    preprocess_rows = _read_jsonl_gzip(
        output_run_dir / module.PREPROCESS_TRACE_FAILURES_FILE_NAME
    )
    assert len(wrong_context_rows) == 2
    assert len(preprocess_rows) == 2
    assert all("current_line" in row for row in wrong_context_rows)
    assert all("raw_block_excerpt" in row for row in preprocess_rows)
    assert preprocess_rows[0]["trace_status"] in {
        "joined_with_prompt_and_archive",
        "joined_with_archive_only",
        "joined_with_prompt_only",
        "missing_prompt_and_archive_context",
        "outside_span_joined_with_prompt_and_archive",
        "outside_span_archive_only",
        "outside_span_prompt_only",
        "outside_span_unattributed",
    }


def test_build_run_cutdown_preprocess_trace_status_fallbacks(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"

    missing_pred_run_id = "2026-03-03_10.01.00"
    _make_run_record(
        module,
        run_root=run_root,
        run_id=missing_pred_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )
    missing_pred_output = tmp_path / "out_missing_pred" / missing_pred_run_id
    module._build_run_cutdown(
        run_dir=run_root / missing_pred_run_id,
        output_run_dir=missing_pred_output,
        sample_limit=80,
        excerpt_limit=200,
        top_confusions_limit=8,
        top_labels_limit=6,
        prompt_pairs_per_category=3,
        prompt_excerpt_limit=400,
    )
    missing_pred_summary = _read_json(missing_pred_output / "need_to_know_summary.json")
    assert (
        missing_pred_summary["sample_counts"][module.PREPROCESS_TRACE_FAILURES_FILE_NAME]["status"]
        == "missing_prediction_run"
    )

    missing_archive_run_id = "2026-03-03_10.02.00"
    _make_run_record(
        module,
        run_root=run_root,
        run_id=missing_archive_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )
    missing_archive_dir = run_root / missing_archive_run_id
    _write_prediction_run(missing_archive_dir, with_extracted_archive=False)
    _set_pred_run_artifact(missing_archive_dir, "prediction-run")
    missing_archive_output = tmp_path / "out_missing_archive" / missing_archive_run_id
    module._build_run_cutdown(
        run_dir=missing_archive_dir,
        output_run_dir=missing_archive_output,
        sample_limit=80,
        excerpt_limit=200,
        top_confusions_limit=8,
        top_labels_limit=6,
        prompt_pairs_per_category=3,
        prompt_excerpt_limit=400,
    )
    missing_archive_summary = _read_json(missing_archive_output / "need_to_know_summary.json")
    assert (
        missing_archive_summary["sample_counts"][module.PREPROCESS_TRACE_FAILURES_FILE_NAME][
            "status"
        ]
        == "missing_extracted_archive"
    )

    missing_full_prompt_run_id = "2026-03-03_10.03.00"
    _make_run_record(
        module,
        run_root=run_root,
        run_id=missing_full_prompt_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=None,
    )
    missing_full_prompt_dir = run_root / missing_full_prompt_run_id
    _write_prediction_run(missing_full_prompt_dir, with_extracted_archive=True)
    _set_pred_run_artifact(missing_full_prompt_dir, "prediction-run")
    missing_full_prompt_output = tmp_path / "out_missing_full_prompt" / missing_full_prompt_run_id
    module._build_run_cutdown(
        run_dir=missing_full_prompt_dir,
        output_run_dir=missing_full_prompt_output,
        sample_limit=80,
        excerpt_limit=200,
        top_confusions_limit=8,
        top_labels_limit=6,
        prompt_pairs_per_category=3,
        prompt_excerpt_limit=400,
    )
    missing_full_prompt_summary = _read_json(
        missing_full_prompt_output / "need_to_know_summary.json"
    )
    assert (
        missing_full_prompt_summary["sample_counts"][module.PREPROCESS_TRACE_FAILURES_FILE_NAME][
            "status"
        ]
        == "missing_full_prompt_log"
    )


def test_preprocess_trace_outside_span_does_not_borrow_fallback_prompt_row(
    tmp_path: Path,
) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    run_id = "2026-03-03_10.03.30"
    _make_run_record(
        module,
        run_root=run_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 99, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )
    run_dir = run_root / run_id
    _write_prediction_run(run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(run_dir, "prediction-run")

    output_run_dir = tmp_path / "cutdown" / run_id
    module._build_run_cutdown(
        run_dir=run_dir,
        output_run_dir=output_run_dir,
        sample_limit=80,
        excerpt_limit=200,
        top_confusions_limit=8,
        top_labels_limit=6,
        prompt_pairs_per_category=3,
        prompt_excerpt_limit=400,
    )

    preprocess_rows = _read_jsonl_gzip(
        output_run_dir / module.PREPROCESS_TRACE_FAILURES_FILE_NAME
    )
    outside_rows = [
        row
        for row in preprocess_rows
        if int(row.get("line_index") or -1) == 99
    ]
    assert outside_rows
    assert outside_rows[0]["span_region"] == "outside_active_recipe_span"
    assert outside_rows[0]["trace_status"] == "outside_span_unattributed"
    assert outside_rows[0]["call_id"] is None
    assert outside_rows[0]["stage_key"] is None


def test_main_process_manifest_includes_new_nested_gzip_paths(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    run_id = "2026-03-03_10.04.00"
    _make_run_record(
        module,
        run_root=run_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )
    run_dir = run_root / run_id
    _write_prediction_run(run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(run_dir, "prediction-run")

    output_dir = tmp_path / "cutdown_out"
    exit_code = _run_main(
        module,
        [
            str(run_root),
            "--output-dir",
            str(output_dir),
            "--overwrite",
            "--no-flatten",
        ],
    )
    assert exit_code == 0

    manifest = _read_json(output_dir / "process_manifest.json")
    included_files = set(manifest["included_files"])
    assert f"{run_id}/{module.WRONG_LABEL_FULL_CONTEXT_FILE_NAME}" in included_files
    assert f"{run_id}/{module.PREPROCESS_TRACE_FAILURES_FILE_NAME}" in included_files


def test_main_upload_3_files_only_consolidates_and_preserves_artifacts(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    codex_run_id = "2026-03-03_10.10.00"
    baseline_run_id = "2026-03-03_10.09.00"

    _make_run_record(
        module,
        run_root=run_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )
    _make_run_record(
        module,
        run_root=run_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "INGREDIENT_LINE"}],
        full_prompt_rows=None,
    )

    codex_run_dir = run_root / codex_run_id
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(codex_run_dir, "prediction-run")

    output_dir = tmp_path / "cutdown_out"
    exit_code = _run_main(
        module,
        [
            str(run_root),
            "--output-dir",
            str(output_dir),
            "--overwrite",
            "--no-flatten",
            "--upload-3-files",
            "--upload-3-files-only",
        ],
    )
    assert exit_code == 0

    output_files = sorted(path.name for path in output_dir.iterdir())
    assert output_files == sorted(module.UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES)
    for review_dir in module.UPLOAD_BUNDLE_REVIEW_PROFILE_DIR_NAMES:
        lane_files = sorted(path.name for path in (output_dir / review_dir).iterdir())
        assert lane_files == sorted(module.UPLOAD_BUNDLE_FILE_NAMES)
    assert all(not name.endswith(".csv") for name in output_files)

    index_payload = _read_json(output_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    artifact_paths = set(index_payload["review_packet"]["selected_paths"])
    assert (
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/01_recipe_triage.packet.jsonl"
        in artifact_paths
    )

    payload_rows = _jsonl_rows_by_path(output_dir / module.UPLOAD_BUNDLE_PAYLOAD_FILE_NAME)
    triage_payload = payload_rows[
        f"{module.UPLOAD_BUNDLE_DERIVED_DIR_NAME}/root/01_recipe_triage.packet.jsonl"
    ]
    assert triage_payload["content_type"] == "jsonl"
    assert isinstance(triage_payload["content_jsonl_rows"], list)

    overview_text = _read_text(output_dir / module.UPLOAD_BUNDLE_OVERVIEW_FILE_NAME)
    assert "## Topline" in overview_text
    assert "## Run Diagnostics" in overview_text


def test_main_includes_project_context_digest_and_metadata(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    codex_run_id = "2026-03-03_10.06.00"
    baseline_run_id = "2026-03-03_10.05.00"

    _make_run_record(
        module,
        run_root=run_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )
    _make_run_record(
        module,
        run_root=run_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "INGREDIENT_LINE"}],
        full_prompt_rows=None,
    )

    codex_run_dir = run_root / codex_run_id
    _write_prediction_run(
        codex_run_dir,
        with_extracted_archive=True,
        llm_manifest_recipes={
            "recipe:c0": _semantic_recipe_manifest_row(
                warnings=["No explicit cooking instructions were provided."],
                structural_reason_codes=["missing_instructions"],
            )
        },
    )
    _set_pred_run_artifact(codex_run_dir, "prediction-run")

    output_dir = tmp_path / "cutdown_out"
    assert (
        _run_main(
            module,
            [str(run_root), "--output-dir", str(output_dir), "--overwrite", "--no-flatten"],
        )
        == 0
    )

    readme = (output_dir / "README.md").read_text(encoding="utf-8")
    assert "## Project Context Digest" in readme
    assert "- benchmark_contract:" in readme
    assert "- label_ontology_cheat_sheet:" in readme
    assert "- projection_bridge:" in readme
    assert "- artifact_legend:" in readme
    assert "- sampling_caveat:" in readme

    context_path = Path(__file__).resolve().parents[2] / "docs" / "AI_context.md"
    expected_hash = hashlib.sha256(context_path.read_bytes()).hexdigest()

    manifest = _read_json(output_dir / "process_manifest.json")
    assert manifest["project_context_path"] == "docs/AI_context.md"
    assert manifest["project_context_digest_included"] is True
    assert manifest["project_context_hash"] == expected_hash
    assert manifest["project_context_title"] != "missing"
    assert manifest["project_context_version_or_date"] != "missing"

    comparison = _read_json(output_dir / "comparison_summary.json")
    project_context = comparison["project_context"]
    assert project_context["project_context_path"] == "docs/AI_context.md"
    assert project_context["project_context_hash"] == expected_hash
    assert project_context["project_context_title"] == manifest["project_context_title"]
    assert (
        project_context["project_context_version_or_date"]
        == manifest["project_context_version_or_date"]
    )


def test_main_flattened_summary_includes_project_context_digest(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    codex_run_id = "2026-03-03_10.08.00"
    baseline_run_id = "2026-03-03_10.07.00"

    _make_run_record(
        module,
        run_root=run_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )
    _make_run_record(
        module,
        run_root=run_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "INGREDIENT_LINE"}],
        full_prompt_rows=None,
    )

    output_dir = tmp_path / "cutdown_out"
    assert _run_main(module, [str(run_root), "--output-dir", str(output_dir), "--overwrite"]) == 0

    flattened_dir = output_dir.parent / f"{output_dir.name}_md"
    benchmark_summary = flattened_dir / module.AGGREGATED_ROOT_SUMMARY_MD
    assert benchmark_summary.is_file()
    summary_text = benchmark_summary.read_text(encoding="utf-8")
    assert "## README" in summary_text
    assert "## Project Context Digest" in summary_text
    assert "- benchmark_contract:" in summary_text
    assert "- label_ontology_cheat_sheet:" in summary_text
    assert "- projection_bridge:" in summary_text


def test_main_project_context_metadata_fallback_when_context_missing(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    module.PROJECT_CONTEXT_REL_PATH = Path("docs/DOES_NOT_EXIST_FOR_CONTEXT_TEST.md")
    run_root = tmp_path / "runs"
    run_id = "2026-03-03_10.09.00"

    _make_run_record(
        module,
        run_root=run_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )

    output_dir = tmp_path / "cutdown_out"
    assert (
        _run_main(
            module,
            [str(run_root), "--output-dir", str(output_dir), "--overwrite", "--no-flatten"],
        )
        == 0
    )

    manifest = _read_json(output_dir / "process_manifest.json")
    assert manifest["project_context_path"] == "docs/DOES_NOT_EXIST_FOR_CONTEXT_TEST.md"
    assert manifest["project_context_title"] == "missing"
    assert manifest["project_context_version_or_date"] == "missing"
    assert manifest["project_context_hash"] == "missing"
    assert manifest["project_context_digest_included"] is True

    comparison = _read_json(output_dir / "comparison_summary.json")
    project_context = comparison["project_context"]
    assert project_context["project_context_path"] == "docs/DOES_NOT_EXIST_FOR_CONTEXT_TEST.md"
    assert project_context["project_context_title"] == "missing"
    assert project_context["project_context_version_or_date"] == "missing"
    assert project_context["project_context_hash"] == "missing"

    readme = (output_dir / "README.md").read_text(encoding="utf-8")
    assert "- context_pointer: `docs/DOES_NOT_EXIST_FOR_CONTEXT_TEST.md`" in readme
    assert "title=`missing`" in readme
    assert "version_or_date=`missing`" in readme
    assert "sha256=`missing`" in readme


def test_main_gzip_exports_are_byte_stable_across_repeated_runs(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    run_id = "2026-03-03_10.05.00"
    _make_run_record(
        module,
        run_root=run_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_cutdown_fixture(),
    )
    run_dir = run_root / run_id
    _write_prediction_run(run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(run_dir, "prediction-run")

    out_a = tmp_path / "out_a"
    out_b = tmp_path / "out_b"
    assert (
        _run_main(
            module,
            [str(run_root), "--output-dir", str(out_a), "--overwrite", "--no-flatten"],
        )
        == 0
    )
    assert (
        _run_main(
            module,
            [str(run_root), "--output-dir", str(out_b), "--overwrite", "--no-flatten"],
        )
        == 0
    )

    wrong_context_bytes_a = (
        out_a / run_id / module.WRONG_LABEL_FULL_CONTEXT_FILE_NAME
    ).read_bytes()
    wrong_context_bytes_b = (
        out_b / run_id / module.WRONG_LABEL_FULL_CONTEXT_FILE_NAME
    ).read_bytes()
    preprocess_bytes_a = (out_a / run_id / module.PREPROCESS_TRACE_FAILURES_FILE_NAME).read_bytes()
    preprocess_bytes_b = (out_b / run_id / module.PREPROCESS_TRACE_FAILURES_FILE_NAME).read_bytes()

    assert wrong_context_bytes_a == wrong_context_bytes_b
    assert preprocess_bytes_a == preprocess_bytes_b

    manifest_a = _read_json(out_a / "process_manifest.json")
    manifest_b = _read_json(out_b / "process_manifest.json")
    for key in (
        "project_context_path",
        "project_context_title",
        "project_context_version_or_date",
        "project_context_hash",
        "project_context_digest_included",
    ):
        assert manifest_a[key] == manifest_b[key]

    comparison_a = _read_json(out_a / "comparison_summary.json")
    comparison_b = _read_json(out_b / "comparison_summary.json")
    assert comparison_a["project_context"] == comparison_b["project_context"]
