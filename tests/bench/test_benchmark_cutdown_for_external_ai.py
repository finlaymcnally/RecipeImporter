from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def _load_cutdown_module():
    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "benchmark_cutdown_for_external_ai.py"
    )
    spec = importlib.util.spec_from_file_location(
        "benchmark_cutdown_for_external_ai",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


def _read_jsonl_gzip(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _run_main(module, argv: list[str]) -> int:
    prior_argv = list(sys.argv)
    try:
        sys.argv = ["benchmark_cutdown_for_external_ai.py", *argv]
        return int(module.main())
    finally:
        sys.argv = prior_argv


def _set_pred_run_artifact(run_dir: Path, pred_run_value: str) -> None:
    run_manifest_path = run_dir / "run_manifest.json"
    payload = _read_json(run_manifest_path)
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    artifacts["pred_run_dir"] = pred_run_value
    payload["artifacts"] = artifacts
    _write_json(run_manifest_path, payload)


def _write_prediction_run(
    run_dir: Path,
    *,
    with_extracted_archive: bool,
) -> Path:
    prediction_run = run_dir / "prediction-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    if with_extracted_archive:
        _write_json(
            prediction_run / "extracted_archive.json",
            [
                {
                    "index": 1,
                    "text": "1 cup flour (raw block)",
                    "location": {
                        "features": {
                            "unstructured_preprocess_mode": "semantic_v1",
                            "unstructured_stable_key": "block-1",
                        }
                    },
                },
                {
                    "index": 3,
                    "text": "Chef note (raw block)",
                    "location": {
                        "features": {
                            "unstructured_preprocess_mode": "semantic_v1",
                            "unstructured_stable_key": "block-3",
                        }
                    },
                },
            ],
        )
    return prediction_run


def _prompt_rows_for_cutdown_fixture() -> list[dict[str, object]]:
    return [
        {
            "pass": "pass1",
            "call_id": "fixture-pass1",
            "recipe_id": "recipe:c0",
            "parsed_response": {
                "is_recipe": True,
                "recipe_id": "recipe:c0",
                "start_block_index": 0,
                "end_block_index": 3,
            },
            "request_input_payload": {"blocks_candidate": [{"text": "Dish Title"}]},
        },
        {
            "pass": "pass3",
            "call_id": "fixture-pass3",
            "recipe_id": "recipe:c0",
            "parsed_response": {
                "warnings": ["Serving information is split across two lines."],
                "ingredient_step_mapping": "{}",
            },
            "request_input_payload": {"blocks_candidate": [{"text": "Mix gently"}]},
        },
    ]


def _prompt_rows_for_starter_pack_fixture() -> list[dict[str, object]]:
    return [
        {
            "pass": "pass1",
            "call_id": "starter-pass1",
            "recipe_id": "recipe:c0",
            "timestamp_utc": "2026-03-03T10:00:00Z",
            "model": "gpt-test",
            "parsed_response": {
                "is_recipe": True,
                "recipe_id": "recipe:c0",
                "start_block_index": 0,
                "end_block_index": 2,
                "title": "Dish Title",
                "excluded_block_ids": [],
            },
            "request_input_payload": {
                "blocks_candidate": [
                    {"index": 0, "block_id": "b0", "text": "Dish Title"},
                    {"index": 1, "block_id": "b1", "text": "1 cup flour"},
                    {"index": 2, "block_id": "b2", "text": "Mix gently"},
                    {"index": 3, "block_id": "b3", "text": "Chef note"},
                ],
                "blocks_after": [],
                "blocks_before": [],
            },
        },
        {
            "pass": "pass2",
            "call_id": "starter-pass2",
            "recipe_id": "recipe:c0",
            "timestamp_utc": "2026-03-03T10:00:05Z",
            "model": "gpt-test",
            "parsed_response": {
                "warnings": ["No explicit cooking instructions were provided."],
                "extracted_ingredients": [{"text": "1 cup flour"}],
                "extracted_instructions": [],
            },
            "request_input_payload": {
                "blocks": [
                    {"index": 0, "block_id": "b0", "text": "Dish Title"},
                    {"index": 1, "block_id": "b1", "text": "1 cup flour"},
                ],
                "canonical_text": "Dish Title\n1 cup flour\nMix gently\nChef note\n",
            },
        },
        {
            "pass": "pass3",
            "call_id": "starter-pass3",
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


def _build_eval_artifacts(module, run_dir: Path) -> tuple[Path, Path]:
    canonical_text = "Dish Title\n1 cup flour\nMix gently\nChef note\n"
    canonical_text_path = run_dir / "canonical_text.txt"
    canonical_spans_path = run_dir / "canonical_span_labels.jsonl"
    canonical_text_path.write_text(canonical_text, encoding="utf-8")

    lines = module._build_canonical_lines(canonical_text)
    labels_by_index = {
        0: "RECIPE_TITLE",
        1: "INGREDIENT_LINE",
        2: "INSTRUCTION_LINE",
        3: "RECIPE_NOTES",
    }
    span_rows = [
        {
            "label": labels_by_index[int(line["line_index"])],
            "start_char": int(line["start_char"]),
            "end_char": int(line["end_char"]),
        }
        for line in lines
    ]
    _write_jsonl(canonical_spans_path, span_rows)
    return canonical_text_path, canonical_spans_path


def _make_run_record(
    module,
    *,
    run_root: Path,
    run_id: str,
    llm_recipe_pipeline: str,
    wrong_label_rows: list[dict[str, object]],
    full_prompt_rows: list[dict[str, object]] | None = None,
) -> object:
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    canonical_text_path, canonical_spans_path = _build_eval_artifacts(module, run_dir)

    _write_jsonl(run_dir / "wrong_label_lines.jsonl", wrong_label_rows)
    _write_jsonl(run_dir / "missed_gold_lines.jsonl", [])
    _write_jsonl(run_dir / "unmatched_pred_blocks.jsonl", [])
    _write_jsonl(run_dir / "aligned_prediction_blocks.jsonl", [])
    _write_jsonl(run_dir / "alignment_gaps.jsonl", [])

    artifacts: dict[str, object] = {}
    full_prompt_log_rows = 0
    full_prompt_log_path: str | None = None
    if full_prompt_rows is not None:
        full_prompt_rel_path = "codexfarm/full_prompt_log.jsonl"
        _write_jsonl(run_dir / full_prompt_rel_path, full_prompt_rows)
        artifacts["full_prompt_log_path"] = full_prompt_rel_path
        full_prompt_log_rows = len(full_prompt_rows)
        full_prompt_log_path = f"{run_id}/full_prompt_log.jsonl"

    run_manifest = {
        "run_id": run_id,
        "source": {"path": "/tmp/book.epub", "source_hash": "source-hash"},
        "artifacts": artifacts,
        "run_config": {
            "llm_recipe_pipeline": llm_recipe_pipeline,
            "atomic_block_splitter": "off",
            "line_role_pipeline": "off",
            "prediction_run_config_hash": "hash-a",
        },
    }
    eval_report = {
        "canonical": {
            "canonical_text_path": str(canonical_text_path),
            "canonical_span_labels_path": str(canonical_spans_path),
        },
        "alignment": {
            "canonical_char_coverage": 0.995,
            "prediction_block_match_ratio": 0.996,
        },
        "counts": {"gold_total": 4, "pred_total": 4},
        "confusion": {},
        "per_label": {},
        "worst_label_recall": {},
        "overall_line_accuracy": 0.0,
        "macro_f1_excluding_other": 0.0,
        "practical_f1": 0.0,
    }
    _write_json(run_dir / "run_manifest.json", run_manifest)
    _write_json(run_dir / "eval_report.json", eval_report)

    return module.RunRecord(
        run_id=run_id,
        source_key="source-hash",
        source_file="book.epub",
        source_hash="source-hash",
        llm_recipe_pipeline=llm_recipe_pipeline,
        atomic_block_splitter="off",
        line_role_pipeline="off",
        codex_enabled=llm_recipe_pipeline not in {"off", "none", ""},
        metric_overall_line_accuracy=0.0,
        metric_macro_f1_excluding_other=0.0,
        metric_practical_f1=0.0,
        worst_label_recall={},
        run_timestamp=module._parse_run_timestamp(run_id),
        output_subdir=run_id,
        config_snapshot=module._config_snapshot(run_manifest),
        top_confusions=[],
        summary_path=str(run_dir / "need_to_know_summary.json"),
        run_dir=str(run_dir),
        full_prompt_log_status="complete" if full_prompt_rows is not None else "not_applicable",
        full_prompt_log_rows=full_prompt_log_rows,
        full_prompt_log_path=full_prompt_log_path,
    )


def test_summarize_prompt_warning_aggregate_counts_warnings(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    full_prompt_log_path = tmp_path / "full_prompt_log.jsonl"
    _write_jsonl(
        full_prompt_log_path,
        [
            {
                "pass": "pass2",
                "recipe_id": "r0",
                "parsed_response": {
                    "warnings": [
                        "Serving information is split across two lines.",
                        "A page marker was excluded.",
                    ]
                },
            },
            {
                "pass": "pass3",
                "recipe_id": "r0",
                "parsed_response": {"warnings": [], "ingredient_step_mapping": "{}"},
            },
            {
                "pass": "pass3",
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
    assert summary["pass3_empty_ingredient_step_mapping_calls"] == 2
    assert summary["warning_buckets"]["split_line_boundary"] >= 1
    assert summary["warning_buckets"]["missing_instructions"] >= 1


def test_build_pair_diagnostics_emits_changed_lines_and_breakdowns(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    codex_prompt_rows = [
        {
            "pass": "pass1",
            "call_id": "c0-pass1",
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
            "pass": "pass3",
            "call_id": "c0-pass3",
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
        llm_recipe_pipeline="codex-farm-3pass-v1",
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


def test_build_comparison_summary_includes_pair_diagnostics(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    codex_record = _make_run_record(
        module,
        run_root=tmp_path,
        run_id="2026-03-02_11.00.00",
        llm_recipe_pipeline="codex-farm-3pass-v1",
        wrong_label_rows=[
            {"line_index": 1, "pred_label": "RECIPE_NOTES"},
            {"line_index": 3, "pred_label": "KNOWLEDGE"},
        ],
        full_prompt_rows=[
            {
                "pass": "pass1",
                "call_id": "case-pass1",
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
                "pass": "pass3",
                "call_id": "case-pass3",
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
        llm_recipe_pipeline="codex-farm-3pass-v1",
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
        llm_recipe_pipeline="codex-farm-3pass-v1",
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
        llm_recipe_pipeline="codex-farm-3pass-v1",
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
        llm_recipe_pipeline="codex-farm-3pass-v1",
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
        llm_recipe_pipeline="codex-farm-3pass-v1",
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
    assert outside_rows[0]["pass"] is None


def test_main_process_manifest_includes_new_nested_gzip_paths(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    run_id = "2026-03-03_10.04.00"
    _make_run_record(
        module,
        run_root=run_root,
        run_id=run_id,
        llm_recipe_pipeline="codex-farm-3pass-v1",
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


def test_main_includes_project_context_digest_and_metadata(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    codex_run_id = "2026-03-03_10.06.00"
    baseline_run_id = "2026-03-03_10.05.00"

    _make_run_record(
        module,
        run_root=run_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-farm-3pass-v1",
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

    context_path = Path(__file__).resolve().parents[2] / "docs" / "AI_Context.md"
    expected_hash = hashlib.sha256(context_path.read_bytes()).hexdigest()

    manifest = _read_json(output_dir / "process_manifest.json")
    assert manifest["project_context_path"] == "docs/AI_Context.md"
    assert manifest["project_context_digest_included"] is True
    assert manifest["project_context_hash"] == expected_hash
    assert manifest["project_context_title"] != "missing"
    assert manifest["project_context_version_or_date"] != "missing"

    comparison = _read_json(output_dir / "comparison_summary.json")
    project_context = comparison["project_context"]
    assert project_context["project_context_path"] == "docs/AI_Context.md"
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
        llm_recipe_pipeline="codex-farm-3pass-v1",
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
        llm_recipe_pipeline="codex-farm-3pass-v1",
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
        llm_recipe_pipeline="codex-farm-3pass-v1",
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


def test_main_writes_starter_pack_v1_contract_files(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    codex_run_id = "2026-03-03_10.10.00"
    baseline_run_id = "2026-03-03_10.09.00"

    _make_run_record(
        module,
        run_root=run_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-farm-3pass-v1",
        wrong_label_rows=[
            {"line_index": 1, "pred_label": "RECIPE_NOTES"},
            {"line_index": 3, "pred_label": "KNOWLEDGE"},
        ],
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

    original_preprocess = module._build_preprocess_trace_failure_rows

    def _fake_preprocess_rows(**kwargs):
        rows = []
        for index in range(10):
            rows.append(
                {
                    "span_region": "outside_active_recipe_span",
                    "line_index": index + 100,
                    "recipe_id": "recipe:c0",
                    "gold_label": "RECIPE_NOTES",
                    "pred_label": "KNOWLEDGE",
                    "trace_status": "joined_with_archive_only",
                    "warning_buckets": ["ocr_or_page_artifact"],
                    "raw_block_stable_key": f"block-{index}",
                    "raw_block_excerpt": f"raw excerpt {index}",
                    "prompt_candidate_block_excerpt": f"prompt excerpt {index}",
                    "call_id": "starter-pass2",
                }
            )
        return rows, "ready"

    module._build_preprocess_trace_failure_rows = _fake_preprocess_rows
    try:
        output_dir = tmp_path / "cutdown_out"
        assert (
            _run_main(
                module,
                [str(run_root), "--output-dir", str(output_dir), "--overwrite", "--no-flatten"],
            )
            == 0
        )
    finally:
        module._build_preprocess_trace_failure_rows = original_preprocess

    starter_dir = output_dir / "starter_pack_v1"
    required_files = {
        "README.md",
        "00_run_overview.md",
        "01_recipe_triage.csv",
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
    }
    assert required_files.issubset({path.name for path in starter_dir.iterdir() if path.is_file()})

    triage_header = (starter_dir / "01_recipe_triage.csv").read_text(encoding="utf-8").splitlines()[0]
    assert triage_header == ",".join(module.STARTER_PACK_TRIAGE_HEADER)

    call_inventory_rows = _read_jsonl(starter_dir / "02_call_inventory.jsonl")
    assert call_inventory_rows
    required_call_inventory_keys = {
        "run_id",
        "source_key",
        "recipe_id",
        "pass",
        "call_id",
        "timestamp_utc",
        "model",
        "input_block_count",
        "warning_count",
        "warning_buckets",
        "extracted_ingredient_count",
        "extracted_instruction_count",
        "step_count",
        "mapping_count",
        "input_excerpt",
        "output_excerpt",
    }
    assert required_call_inventory_keys.issubset(call_inventory_rows[0].keys())

    starter_manifest = _read_json(starter_dir / "10_process_manifest.json")
    assert starter_manifest["starter_pack_version"] == "v1"
    assert "selection_policy" in starter_manifest
    assert "outside_span_inclusion_policy" in starter_manifest
    assert "heavy_artifacts_omitted_by_default" in starter_manifest
    assert "legacy_to_starter_mapping" in starter_manifest
    assert starter_manifest["outside_span_trace_sample"]["included"] is True

    root_manifest = _read_json(output_dir / "process_manifest.json")
    assert root_manifest["starter_pack_v1_path"] == "starter_pack_v1"
    assert root_manifest["starter_pack_v1_manifest_file"] == "starter_pack_v1/10_process_manifest.json"
    assert "starter_pack_v1/01_recipe_triage.csv" in set(root_manifest["included_files"])

    root_comparison = _read_json(output_dir / "comparison_summary.json")
    starter_comparison = _read_json(starter_dir / "11_comparison_summary.json")
    assert starter_comparison == root_comparison


def test_main_starter_pack_omits_outside_trace_when_threshold_not_met(tmp_path: Path) -> None:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    codex_run_id = "2026-03-03_10.12.00"
    baseline_run_id = "2026-03-03_10.11.00"

    _make_run_record(
        module,
        run_root=run_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-farm-3pass-v1",
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
    session_root = tmp_path / "single-offline-benchmark"
    codex_run_id = "2026-03-03_10.14.00"
    baseline_run_id = "2026-03-03_10.13.00"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-farm-3pass-v1",
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

    metadata = module.build_starter_pack_for_existing_runs(
        input_dir=session_root,
        output_dir=session_root,
    )

    starter_dir = session_root / "starter_pack_v1"
    assert starter_dir.is_dir()
    assert (starter_dir / "00_run_overview.md").is_file()
    assert (starter_dir / "01_recipe_triage.csv").is_file()
    assert int(metadata["run_count"]) == 2
    assert int(metadata["pair_count"]) == 1


def test_select_starter_pack_recipe_cases_uses_blended_policy() -> None:
    module = _load_cutdown_module()
    triage_rows = [
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": f"recipe:{index}",
            "changed_lines_codex_vs_baseline": 20 - index,
            "delta_codex_minus_baseline": 0.1 - (index * 0.01),
            "pass1_vs_pass2_missing_block_count": index % 5,
            "pass3_empty_mapping": index in {2, 5, 7},
            "pass1_selected_block_count": 10 if index in {2, 5} else 2,
            "pass2_warning_count": 3 if index == 7 else 0,
            "pass2_extracted_instruction_count": 0 if index in {2, 7} else 1,
            "outside_span_wrong_line_count": 3 if index == 4 else 0,
            "codex_accuracy": 0.8 - (index * 0.01),
        }
        for index in range(10)
    ]

    selected = module._select_starter_pack_recipe_cases(triage_rows)

    assert 1 <= len(selected) <= 10
    reasons = [str(row.get("selection_reason") or "") for row in selected]
    assert any("top_changed_lines" in reason for reason in reasons)
    assert any("top_block_loss" in reason for reason in reasons)
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
            "pass1_vs_pass2_missing_block_count": 0,
            "pass3_empty_mapping": False,
            "pass1_selected_block_count": 10,
            "pass2_warning_count": 0,
            "pass2_extracted_instruction_count": 1,
            "outside_span_wrong_line_count": 0,
            "codex_accuracy": 0.90,
        },
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:empty-high-delta",
            "changed_lines_codex_vs_baseline": 4,
            "delta_codex_minus_baseline": -0.40,
            "pass1_vs_pass2_missing_block_count": 1,
            "pass3_empty_mapping": True,
            "pass1_selected_block_count": 10,
            "pass2_warning_count": 0,
            "pass2_extracted_instruction_count": 0,
            "outside_span_wrong_line_count": 0,
            "codex_accuracy": 0.40,
        },
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:empty-low-delta-high-changes",
            "changed_lines_codex_vs_baseline": 20,
            "delta_codex_minus_baseline": -0.05,
            "pass1_vs_pass2_missing_block_count": 1,
            "pass3_empty_mapping": True,
            "pass1_selected_block_count": 10,
            "pass2_warning_count": 0,
            "pass2_extracted_instruction_count": 0,
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


def test_select_starter_pack_recipe_cases_keeps_low_change_high_block_loss() -> None:
    module = _load_cutdown_module()
    triage_rows = [
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": f"recipe:high-change-{index}",
            "changed_lines_codex_vs_baseline": 20 - index,
            "delta_codex_minus_baseline": -0.10 - (index * 0.01),
            "pass1_vs_pass2_missing_block_count": 2 + index,
            "pass3_empty_mapping": False,
            "pass1_selected_block_count": 10,
            "pass2_warning_count": 0,
            "pass2_extracted_instruction_count": 1,
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
            "pass1_vs_pass2_missing_block_count": 99,
            "pass3_empty_mapping": False,
            "pass1_selected_block_count": 10,
            "pass2_warning_count": 0,
            "pass2_extracted_instruction_count": 1,
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
    assert "top_block_loss" in selected_by_recipe["recipe:low-change-high-loss"]


def test_select_starter_pack_recipe_cases_outside_pool_uses_metric_not_change_floor() -> None:
    module = _load_cutdown_module()
    triage_rows = [
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:outside-low-change-highest",
            "changed_lines_codex_vs_baseline": 1,
            "delta_codex_minus_baseline": -0.80,
            "pass1_vs_pass2_missing_block_count": 0,
            "pass3_empty_mapping": False,
            "pass1_selected_block_count": 10,
            "pass2_warning_count": 0,
            "pass2_extracted_instruction_count": 1,
            "outside_span_wrong_line_count": 50,
            "codex_accuracy": 0.20,
        },
        {
            "source_key": "s",
            "codex_run_id": "c",
            "recipe_id": "recipe:outside-higher-change-lower-outside",
            "changed_lines_codex_vs_baseline": 8,
            "delta_codex_minus_baseline": -0.20,
            "pass1_vs_pass2_missing_block_count": 0,
            "pass3_empty_mapping": False,
            "pass1_selected_block_count": 10,
            "pass2_warning_count": 0,
            "pass2_extracted_instruction_count": 1,
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
