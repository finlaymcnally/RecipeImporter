from __future__ import annotations

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


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


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

    summary, changed_lines, pair_breakdowns, targeted_cases = module._build_comparison_summary(
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
