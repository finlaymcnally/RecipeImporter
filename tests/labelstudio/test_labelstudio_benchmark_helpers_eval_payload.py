from __future__ import annotations

import tests.labelstudio.test_labelstudio_benchmark_helpers as _base

# Reuse shared imports/helpers from the base benchmark helpers module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_labelstudio_benchmark_direct_call_uses_real_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "k"))
    monkeypatch.setattr(cli, "_discover_freeform_gold_exports", lambda *_: [])
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(output_dir=tmp_path / "empty-golden")


def test_labelstudio_benchmark_compare_payload_passes_with_required_debug_artifacts(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["schema_version"] == "labelstudio_benchmark_compare.v1"
    assert payload["overall"]["verdict"] == "PASS"
    gates_by_name = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates_by_name["foodlab_debug_artifacts_present"]["passed"] is True
    assert gates_by_name["sea_debug_artifacts_present"]["passed"] is True
    assert gates_by_name["foodlab_variant_recall_nonzero"]["passed"] is True


def test_labelstudio_benchmark_compare_payload_fails_when_required_debug_artifacts_missing(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "FAIL"
    gates_by_name = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates_by_name["foodlab_debug_artifacts_present"]["passed"] is False


def test_labelstudio_benchmark_compare_payload_fails_when_benchmark_mode_metadata_is_missing(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
                write_prompt_manifests=False,
                include_prediction_run_config=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "FAIL"
    gates_by_name = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates_by_name["foodlab_debug_artifacts_present"]["passed"] is False
    assert (
        "Missing required debug artifacts:"
        in str(gates_by_name["foodlab_debug_artifacts_present"]["reason"])
    )
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any(
        "inferred benchmark mode from artifacts (metadata missing)" in str(warning)
        for warning in warnings
    )


def test_labelstudio_benchmark_compare_payload_infers_benchmark_mode_from_artifacts_and_passes(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-farm-3pass-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
                include_prediction_run_config=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "PASS"
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any(
        (
            "Running benchmark-only debug checks for thefoodlabcutdown using "
            "inferred benchmark mode from artifacts (metadata missing)"
        ) in str(warning)
        for warning in warnings
    )
    foodlab_debug_gate = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }["foodlab_debug_artifacts_present"]
    assert foodlab_debug_gate["passed"] is True


def test_labelstudio_benchmark_compare_payload_skips_debug_checks_when_mode_unknown(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
                include_prediction_run_config=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
                include_prediction_run_config=False,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "PASS"
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any(
        "Could not confirm benchmark mode for seaandsmokecutdown: "
        "mode metadata is missing and artifact signals are not conclusive."
        in str(warning)
        for warning in warnings
    )
    source_row = payload["sources"]["seaandsmokecutdown"]
    assert isinstance(source_row, dict)
    candidate_context = source_row.get("candidate")
    assert isinstance(candidate_context, dict)
    debug_payload = candidate_context.get("debug_artifacts")
    assert isinstance(debug_payload, dict)
    assert debug_payload.get("required") is False
    foodlab_debug_gate = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }["sea_debug_artifacts_present"]
    assert foodlab_debug_gate["passed"] is True


def test_labelstudio_benchmark_action_compare_dispatches_to_compare_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    compare_out = tmp_path / "compare-out"
    captured: dict[str, object] = {}

    def fake_compare(**kwargs):
        captured.update(kwargs)
        return {"overall": {"verdict": "PASS"}}

    monkeypatch.setattr(cli, "labelstudio_benchmark_compare", fake_compare)

    cli.labelstudio_benchmark(
        action="compare",
        baseline=baseline,
        candidate=candidate,
        compare_out=compare_out,
        fail_on_regression=True,
    )

    assert captured["baseline"] == baseline
    assert captured["candidate"] == candidate
    assert captured["out_dir"] == compare_out
    assert captured["fail_on_regression"] is True


def test_labelstudio_benchmark_compare_accepts_single_eval_report_inputs(
    tmp_path: Path,
) -> None:
    def _write_single_eval_run(
        run_dir: Path,
        *,
        source_file: str,
        practical_f1: float,
        line_accuracy: float,
        ingredient_recall: float,
        variant_recall: float,
    ) -> Path:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "aligned_prediction_blocks.jsonl").write_text("{}\n", encoding="utf-8")
        (run_dir / "prediction-run").mkdir(parents=True, exist_ok=True)
        (run_dir / "prediction-run" / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_config": {
                        "prediction_run_config": {
                            "llm_recipe_pipeline": "off",
                            "codex_farm_recipe_mode": "extract",
                        }
                    },
                    "artifacts": {},
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (run_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "source": {"path": source_file},
                    "run_config": {
                        "llm_recipe_pipeline": "off",
                        "codex_farm_recipe_mode": "extract",
                        "prediction_run_config": {
                            "llm_recipe_pipeline": "off",
                            "codex_farm_recipe_mode": "extract",
                        },
                    },
                    "artifacts": {"pred_run_dir": "prediction-run"},
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_path = run_dir / "eval_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "source_file": source_file,
                    "practical_f1": practical_f1,
                    "overall_line_accuracy": line_accuracy,
                    "per_label": {
                        "INGREDIENT_LINE": {"recall": ingredient_recall},
                        "RECIPE_VARIANT": {"recall": variant_recall},
                    },
                    "artifacts": {
                        "aligned_prediction_blocks_jsonl": "aligned_prediction_blocks.jsonl",
                    },
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return report_path

    baseline_eval_report = _write_single_eval_run(
        tmp_path / "baseline-eval",
        source_file="data/input/thefoodlabCUTDOWN.epub",
        practical_f1=0.40,
        line_accuracy=0.50,
        ingredient_recall=0.30,
        variant_recall=0.10,
    )
    candidate_eval_report = _write_single_eval_run(
        tmp_path / "candidate-eval",
        source_file="data/input/thefoodlabCUTDOWN.epub",
        practical_f1=0.50,
        line_accuracy=0.60,
        ingredient_recall=0.35,
        variant_recall=0.15,
    )

    payload = cli.labelstudio_benchmark_compare(
        baseline=baseline_eval_report,
        candidate=candidate_eval_report,
        out_dir=tmp_path / "compare-out",
    )

    assert payload["comparison_mode"] == "single_eval_report"
    assert payload["overall"]["verdict"] == "PASS"
    gates = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates["practical_f1_no_regression"]["passed"] is True
    assert gates["overall_line_accuracy_no_regression"]["passed"] is True
    assert gates["debug_artifacts_present"]["passed"] is True


def test_labelstudio_benchmark_passes_processed_output_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps(
            [
                {
                    "index": 0,
                    "text": "Sample title",
                    "location": {"features": {"extraction_backend": "unstructured"}},
                }
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps([{"index": 0, "text": "Sample title"}], sort_keys=True),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key")
    )
    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "recall": 0.0,
                "precision": 0.0,
                "boundary": {"correct": 0, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 1,
            "tasks_uploaded": 1,
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11-00-00-00",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", fake_run_labelstudio_import)

    processed_root = tmp_path / "output"
    eval_root = tmp_path / "2026-03-03_10.20.00"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=processed_root,
        eval_output_dir=eval_root,
        allow_labelstudio_write=True,
    )

    assert captured["processed_output_root"] == processed_root
    assert captured["auto_project_name_on_scope_mismatch"] is True


def test_labelstudio_benchmark_no_upload_uses_offline_pred_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
                "run_config": {"workers": 1},
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_resolve_labelstudio_settings",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("No-upload mode must not resolve Label Studio credentials.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_labelstudio_import",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("No-upload mode must not call run_labelstudio_import.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "recall": 0.0,
                "precision": 0.0,
                "boundary": {"correct": 0, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    captured_generate: dict[str, object] = {}

    def fake_generate_pred_run_artifacts(**kwargs):
        captured_generate.update(kwargs)
        (prediction_run / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": str(source_file),
                    "source_hash": "fixture-hash",
                    "run_config": {
                        "selective_retry_attempted": True,
                        "selective_retry_pass2_attempts": 1,
                        "selective_retry_pass2_recovered": 1,
                        "selective_retry_pass3_attempts": 0,
                        "selective_retry_pass3_recovered": 0,
                    },
                    "run_config_hash": "hash-1",
                    "run_config_summary": "selective retry summary",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
        }

    monkeypatch.setattr(cli, "generate_pred_run_artifacts", fake_generate_pred_run_artifacts)

    eval_root = tmp_path / "2026-03-03_10.20.00"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        allow_codex=True,
        llm_recipe_pipeline="codex-farm-3pass-v1",
        codex_farm_model="gpt-5.3-codex-spark",
        codex_farm_reasoning_effort="low",
        codex_farm_benchmark_selective_retry_enabled=False,
        codex_farm_benchmark_selective_retry_max_attempts=3,
        write_markdown=False,
        write_label_studio_tasks=False,
        pdf_ocr_policy="always",
        pdf_column_gap_ratio=0.21,
    )

    assert captured_generate["path"] == source_file
    assert captured_generate["run_manifest_kind"] == "bench_pred_run"
    assert captured_generate["write_markdown"] is False
    assert captured_generate["write_label_studio_tasks"] is False
    assert captured_generate["pdf_ocr_policy"] == "always"
    assert captured_generate["pdf_column_gap_ratio"] == 0.21
    assert captured_generate["llm_recipe_pipeline"] == "codex-farm-3pass-v1"
    assert captured_generate["allow_codex"] is True
    assert captured_generate["codex_farm_model"] == "gpt-5.3-codex-spark"
    assert captured_generate["codex_farm_reasoning_effort"] == "low"
    assert captured_generate["codex_farm_benchmark_selective_retry_enabled"] is False
    assert captured_generate["codex_farm_benchmark_selective_retry_max_attempts"] == 3
    assert captured_generate["atomic_block_splitter"] == "off"
    assert captured_generate["line_role_pipeline"] == "off"
    run_manifest_path = eval_root / "run_manifest.json"
    assert run_manifest_path.exists()
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    assert run_manifest["run_kind"] == "labelstudio_benchmark"
    assert run_manifest["run_config"]["upload"] is False
    assert run_manifest["run_config"]["write_markdown"] is False
    assert run_manifest["run_config"]["write_label_studio_tasks"] is False
    assert run_manifest["run_config"]["pdf_ocr_policy"] == "always"
    assert run_manifest["run_config"]["pdf_column_gap_ratio"] == 0.21
    assert run_manifest["run_config"]["llm_recipe_pipeline"] == "codex-farm-3pass-v1"
    assert run_manifest["run_config"]["codex_execution_policy_requested_mode"] == "execute"
    assert run_manifest["run_config"]["codex_execution_policy_resolved_mode"] == "execute"
    assert run_manifest["run_config"]["codex_execution_live_llm_allowed"] is True
    assert run_manifest["run_config"]["codex_decision_context"] == "labelstudio_benchmark"
    assert run_manifest["run_config"]["codex_decision_allowed"] is True
    assert run_manifest["run_config"]["codex_decision_codex_surfaces"] == ["recipe"]
    assert run_manifest["run_config"]["codex_farm_model"] == "gpt-5.3-codex-spark"
    assert run_manifest["run_config"]["codex_farm_reasoning_effort"] == "low"
    assert run_manifest["run_config"]["atomic_block_splitter"] == "off"
    assert run_manifest["run_config"]["line_role_pipeline"] == "off"
    assert run_manifest["run_config"]["selective_retry_attempted"] is True
    assert run_manifest["run_config"]["selective_retry_pass2_attempts"] == 1
    assert run_manifest["run_config"]["selective_retry_pass2_recovered"] == 1
    assert (
        run_manifest["run_config"]["prediction_run_config"]["selective_retry_attempted"]
        is True
    )
    assert "eval_report_md" not in run_manifest["artifacts"]
    assert not (eval_root / "eval_report.md").exists()
    upload_bundle_dir = eval_root / cli.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    assert upload_bundle_dir.is_dir()
    assert {
        path.name
        for path in upload_bundle_dir.iterdir()
        if path.is_file()
    } == set(cli.BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES)


def test_labelstudio_benchmark_predictions_out_writes_prediction_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps(
            [
                {
                    "index": 0,
                    "text": "Sample title",
                    "location": {"features": {"extraction_backend": "unstructured"}},
                }
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
                "run_config": {"workers": 1},
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
                "recipe_count": 7,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {"prediction_seconds": 1.5},
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "practical_precision": 0.0,
                "practical_recall": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    predictions_out = tmp_path / "prediction-records.jsonl"
    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        predictions_out=predictions_out,
    )

    records = list(read_prediction_records(predictions_out))
    assert len(records) == 1
    record = records[0]
    assert record.prediction["schema_kind"] == "stage-block.v1"
    assert record.prediction["block_index"] == 0
    assert record.prediction["pred_label"] == "RECIPE_TITLE"
    assert record.prediction["block_text"] == "Sample title"
    assert record.predict_meta["source_file"] == str(source_file)
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert "prediction_record_output_jsonl" in run_manifest["artifacts"]


def test_labelstudio_benchmark_predictions_in_runs_evaluate_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    predictions_in = tmp_path / "prediction-records.jsonl"
    write_prediction_records(
        predictions_in,
        [
            make_prediction_record(
                example_id="labelstudio-benchmark:hash-123:block:0",
                example_index=0,
                prediction={
                    "schema_kind": "stage-block.v1",
                    "block_index": 0,
                    "pred_label": "RECIPE_TITLE",
                    "block_text": "Sample title",
                    "block_features": {"extraction_backend": "unstructured"},
                },
                predict_meta={
                    "source_file": str(source_file),
                    "source_hash": "hash-123",
                    "workbook_slug": "book",
                    "run_config": {"workers": 1},
                    "run_config_hash": "cfg-hash",
                    "run_config_summary": "workers=1",
                    "timing": {"prediction_seconds": 4.2},
                },
            )
        ],
    )

    monkeypatch.setattr(
        cli,
        "_resolve_labelstudio_settings",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("Evaluate-only mode must not resolve Label Studio credentials.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Evaluate-only mode must not regenerate prediction artifacts.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_labelstudio_import",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Evaluate-only mode must not upload prediction artifacts.")
        ),
    )

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_stage_blocks(**kwargs):
        captured_eval.update(kwargs)
        return {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "practical_precision": 0.0,
                "practical_recall": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_stage_blocks", _fake_evaluate_stage_blocks)
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        predictions_in=predictions_in,
    )

    replay_dir = eval_root / ".prediction-record-replay"
    assert captured_eval["stage_predictions_json"] == (
        replay_dir / "stage_block_predictions.from_records.json"
    )
    assert captured_eval["extracted_blocks_json"] == (
        replay_dir / "extracted_archive.from_records.json"
    )
    replay_stage_payload = json.loads(
        (replay_dir / "stage_block_predictions.from_records.json").read_text(
            encoding="utf-8"
        )
    )
    assert replay_stage_payload["block_labels"] == {"0": "RECIPE_TITLE"}
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["run_config"]["upload"] is False
    assert "prediction_record_input_jsonl" in run_manifest["artifacts"]


def test_labelstudio_benchmark_predictions_in_supports_legacy_run_pointer_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    stage_predictions_path = prediction_run / "stage_block_predictions.json"
    extracted_archive_path = prediction_run / "extracted_archive.json"
    stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "OTHER"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_archive_path.write_text(
        json.dumps([{"index": 0, "text": "Sample"}], sort_keys=True),
        encoding="utf-8",
    )

    predictions_in = tmp_path / "legacy-prediction-records.jsonl"
    write_prediction_records(
        predictions_in,
        [
            make_prediction_record(
                example_id="legacy-example-0",
                example_index=0,
                prediction={
                    "pred_run_dir": str(prediction_run),
                    "stage_block_predictions_path": str(stage_predictions_path),
                    "extracted_archive_path": str(extracted_archive_path),
                },
                predict_meta={
                    "source_file": str(source_file),
                    "source_hash": "hash-123",
                    "timing": {"prediction_seconds": 1.0},
                },
            )
        ],
    )

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_stage_blocks(**kwargs):
        captured_eval.update(kwargs)
        return {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "practical_precision": 0.0,
                "practical_recall": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_stage_blocks", _fake_evaluate_stage_blocks)
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    eval_root = tmp_path / "eval-legacy-record"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        predictions_in=predictions_in,
    )

    assert captured_eval["stage_predictions_json"] == stage_predictions_path
    assert captured_eval["extracted_blocks_json"] == extracted_archive_path


def test_build_prediction_bundle_prefers_line_role_projection_for_canonical_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    prediction_run = tmp_path / "prediction-run"
    prediction_run.mkdir(parents=True, exist_ok=True)

    default_stage_predictions_path = prediction_run / "stage_block_predictions.json"
    default_stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "OTHER"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    default_extracted_archive_path = prediction_run / "extracted_archive.json"
    default_extracted_archive_path.write_text(
        json.dumps([{"index": 0, "text": "default"}], sort_keys=True),
        encoding="utf-8",
    )

    line_role_dir = prediction_run / "line-role-pipeline"
    line_role_dir.mkdir(parents=True, exist_ok=True)
    line_role_stage_predictions_path = line_role_dir / "stage_block_predictions.json"
    line_role_stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    line_role_extracted_archive_path = line_role_dir / "extracted_archive.json"
    line_role_extracted_archive_path.write_text(
        json.dumps([{"index": 0, "text": "line-role"}], sort_keys=True),
        encoding="utf-8",
    )

    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
                "stage_block_predictions_path": str(default_stage_predictions_path),
                "line_role_pipeline_stage_block_predictions_path": str(
                    line_role_stage_predictions_path
                ),
                "line_role_pipeline_extracted_archive_path": str(
                    line_role_extracted_archive_path
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    import_result = {"run_root": prediction_run}

    default_bundle = cli._build_prediction_bundle_from_import_result(
        import_result=import_result,
        eval_output_dir=tmp_path / "eval-default",
        prediction_phase_seconds=1.0,
        prefer_line_role_projection=False,
    )
    assert default_bundle.stage_predictions_path == default_stage_predictions_path
    assert default_bundle.extracted_archive_path == default_extracted_archive_path

    line_role_bundle = cli._build_prediction_bundle_from_import_result(
        import_result=import_result,
        eval_output_dir=tmp_path / "eval-line-role",
        prediction_phase_seconds=1.0,
        prefer_line_role_projection=True,
    )
    assert line_role_bundle.stage_predictions_path == line_role_stage_predictions_path
    assert line_role_bundle.extracted_archive_path == line_role_extracted_archive_path


def test_labelstudio_benchmark_writes_pipelined_execution_mode_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps([{"index": 0, "text": "Sample title"}], sort_keys=True),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {"prediction_seconds": 2.0},
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    eval_root = tmp_path / "eval-pipelined"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
    )

    report = json.loads(
        (eval_root / "eval_report.json").read_text(encoding="utf-8")
    )
    assert report["report"]["overall_block_accuracy"] == pytest.approx(1.0)

    run_manifest = json.loads(
        (eval_root / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert run_manifest["run_config"]["execution_mode"] == "pipelined"


def test_labelstudio_benchmark_internal_skip_evaluation_writes_prediction_artifacts_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text(
        json.dumps([{"index": 0, "text": "Sample title"}], sort_keys=True),
        encoding="utf-8",
    )
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {"prediction_seconds": 1.25},
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "internal skip-evaluation mode must not run stage-block evaluation."
            )
        ),
    )
    monkeypatch.setattr(
        cli,
        "evaluate_canonical_text",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "internal skip-evaluation mode must not run canonical evaluation."
            )
        ),
    )
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "internal skip-evaluation mode must not append benchmark CSV."
            )
        ),
    )

    eval_root = tmp_path / "eval-skip-evaluation"
    predictions_out = tmp_path / "prediction-records.jsonl"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        skip_evaluation_internal=True,
        predictions_out=predictions_out,
    )

    assert not (eval_root / "eval_report.json").exists()
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["run_config"]["execution_mode"] == "pipelined"
    assert run_manifest["run_config"]["predict_only"] is True
    assert "prediction_record_output_jsonl" in run_manifest["artifacts"]
    records = list(read_prediction_records(predictions_out))
    assert len(records) == 1


def test_labelstudio_benchmark_pipelined_mode_overlaps_prediction_with_eval_prewarm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    canonical_text_path = gold_export_root / "canonical_text.txt"
    canonical_spans_path = gold_export_root / "canonical_span_labels.jsonl"
    canonical_text_path.write_text("Title", encoding="utf-8")
    canonical_spans_path.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    prewarm_started = threading.Event()
    producer_observed_prewarm: dict[str, bool] = {"value": False}

    def _fake_generate_pred_run_artifacts(**_kwargs):
        producer_observed_prewarm["value"] = prewarm_started.wait(timeout=1.0)
        return {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {"prediction_seconds": 0.4},
        }

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "generate_pred_run_artifacts", _fake_generate_pred_run_artifacts)

    def _fake_ensure_canonical_gold_artifacts(*, export_root: Path):
        assert export_root == gold_export_root
        prewarm_started.set()
        return {
            "canonical_text_path": canonical_text_path,
            "canonical_span_labels_path": canonical_spans_path,
        }

    monkeypatch.setattr(
        cli,
        "ensure_canonical_gold_artifacts",
        _fake_ensure_canonical_gold_artifacts,
    )

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_canonical_text(**kwargs):
        captured_eval.update(kwargs)
        return {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_line_accuracy": 0.0,
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "practical_precision": 0.0,
                "practical_recall": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold_blocks": [],
            "wrong_label_blocks": [],
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_canonical_text", _fake_evaluate_canonical_text)
    monkeypatch.setattr(cli, "format_canonical_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    eval_root = tmp_path / "eval-pipelined"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        eval_mode="canonical-text",
    )

    assert producer_observed_prewarm["value"] is True
    assert isinstance(captured_eval.get("canonical_paths"), dict)


def test_labelstudio_benchmark_pipelined_mode_streams_records_before_producer_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {"prediction_seconds": 0.2},
        },
    )

    consumer_saw_first_record = threading.Event()
    producer_finished = threading.Event()
    original_prediction_record_stage_row = cli._prediction_record_stage_row

    def _wrapped_prediction_record_stage_row(record):
        row = original_prediction_record_stage_row(record)
        if row is not None and int(row[0]) == 0:
            consumer_saw_first_record.set()
        return row

    monkeypatch.setattr(
        cli,
        "_prediction_record_stage_row",
        _wrapped_prediction_record_stage_row,
    )

    def _streaming_predict_stage(*, bundle, selected_source):
        predict_meta = cli._prediction_record_meta_from_bundle(
            bundle=bundle,
            selected_source=selected_source,
            workbook_slug="book",
        )
        yield make_prediction_record(
            example_id="labelstudio-benchmark:hash-123:block:0",
            example_index=0,
            prediction={
                "schema_kind": "stage-block.v1",
                "block_index": 0,
                "pred_label": "RECIPE_TITLE",
                "block_text": "Title",
                "block_features": {"extraction_backend": "unstructured"},
            },
            predict_meta=predict_meta,
        )
        assert consumer_saw_first_record.wait(timeout=1.0)
        yield make_prediction_record(
            example_id="labelstudio-benchmark:hash-123:block:1",
            example_index=1,
            prediction={
                "schema_kind": "stage-block.v1",
                "block_index": 1,
                "pred_label": "OTHER",
                "block_text": "Body",
                "block_features": {"extraction_backend": "unstructured"},
            },
            predict_meta=predict_meta,
        )
        producer_finished.set()

    monkeypatch.setattr(cli, "predict_stage", _streaming_predict_stage)

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_stage_blocks(**kwargs):
        captured_eval.update(kwargs)
        return {
            "report": {
                "counts": {
                    "gold_total": 2,
                    "pred_total": 2,
                    "gold_matched": 2,
                    "pred_matched": 2,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_stage_blocks", _fake_evaluate_stage_blocks)
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    eval_root = tmp_path / "eval-pipelined-streaming"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
    )

    assert consumer_saw_first_record.is_set()
    assert producer_finished.is_set()
    replay_dir = eval_root / ".prediction-record-replay" / "pipelined"
    assert captured_eval["stage_predictions_json"] == (
        replay_dir / "stage_block_predictions.from_records.json"
    )
    replay_payload = json.loads(
        (replay_dir / "stage_block_predictions.from_records.json").read_text(
            encoding="utf-8"
        )
    )
    assert replay_payload["block_labels"] == {"0": "RECIPE_TITLE", "1": "OTHER"}


def test_labelstudio_benchmark_pipelined_mode_propagates_consumer_stream_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {"prediction_seconds": 0.2},
        },
    )

    def _invalid_streaming_predict_stage(*, bundle, selected_source):
        predict_meta = cli._prediction_record_meta_from_bundle(
            bundle=bundle,
            selected_source=selected_source,
            workbook_slug="book",
        )
        yield make_prediction_record(
            example_id="labelstudio-benchmark:hash-123:block:0",
            example_index=0,
            prediction={
                "schema_kind": "unsupported-kind.v1",
                "block_index": 0,
                "pred_label": "RECIPE_TITLE",
                "block_text": "Title",
                "block_features": {},
            },
            predict_meta=predict_meta,
        )

    monkeypatch.setattr(cli, "predict_stage", _invalid_streaming_predict_stage)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Evaluation should not run when streaming consumer fails.")
        ),
    )
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "output",
            eval_output_dir=tmp_path / "eval-pipelined-error",
            no_upload=True,
        )


def test_labelstudio_benchmark_canonical_text_mode_uses_canonical_evaluator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
                "run_config": {"workers": 1},
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Canonical mode should not call stage-block evaluator.")
        ),
    )

    captured_eval: dict[str, object] = {}

    def _fake_eval_canonical_text(**kwargs):
        captured_eval.update(kwargs)
        captured_eval["sequence_matcher_env"] = os.environ.get(cli.SEQUENCE_MATCHER_ENV)
        return {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_line_accuracy": 1.0,
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "per_label": {},
                "evaluation_telemetry": {
                    "total_seconds": 1.5,
                    "subphases": {
                        "load_prediction_seconds": 0.12,
                        "load_gold_seconds": 0.34,
                        "alignment_seconds": 0.56,
                        "alignment_sequence_matcher_seconds": 0.45,
                    },
                    "resources": {
                        "process_cpu_seconds": 0.2,
                        "peak_ru_maxrss_kib": 123.0,
                    },
                    "work_units": {
                        "prediction_block_count": 10,
                        "prediction_text_char_count": 4567,
                    },
                },
            },
            "missed_gold_blocks": [],
            "wrong_label_blocks": [],
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_canonical_text", _fake_eval_canonical_text)
    monkeypatch.setattr(cli, "format_canonical_eval_report_md", lambda *_: "report")

    captured_csv: dict[str, object] = {}

    def _capture_append(*_args, **kwargs):
        captured_csv.update(kwargs)

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )

    eval_root = tmp_path / "eval"
    scheduler_events: list[dict[str, object]] = []
    with cli._benchmark_scheduler_event_overrides(
        scheduler_event_callback=lambda payload: scheduler_events.append(dict(payload))
    ):
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "output",
            eval_output_dir=eval_root,
            no_upload=True,
            eval_mode="canonical-text",
            sequence_matcher="dmp",
        )

    assert captured_eval["gold_export_root"] == gold_spans.parent
    assert captured_eval["sequence_matcher_env"] == "dmp"
    assert captured_csv["eval_scope"] == "canonical-text"
    timing = captured_csv.get("timing")
    assert isinstance(timing, dict)
    checkpoints = timing.get("checkpoints")
    assert isinstance(checkpoints, dict)
    assert checkpoints["prediction_load_seconds"] == pytest.approx(0.12)
    assert checkpoints["gold_load_seconds"] == pytest.approx(0.34)
    assert checkpoints["evaluate_alignment_seconds"] == pytest.approx(0.56)
    assert checkpoints["evaluate_alignment_sequence_matcher_seconds"] == pytest.approx(0.45)
    assert checkpoints["evaluate_resource_process_cpu_seconds"] == pytest.approx(0.2)
    assert checkpoints["evaluate_work_prediction_block_count"] == pytest.approx(10.0)
    assert checkpoints["evaluate_work_prediction_text_char_count"] == pytest.approx(4567.0)
    event_names = [str(row.get("event") or "") for row in scheduler_events]
    assert "evaluate_started" in event_names
    assert "evaluate_finished" in event_names
    evaluate_finished_events = [
        row for row in scheduler_events if str(row.get("event") or "") == "evaluate_finished"
    ]
    assert evaluate_finished_events
    assert evaluate_finished_events[-1]["prediction_load_seconds"] == pytest.approx(0.12)
    assert evaluate_finished_events[-1]["gold_load_seconds"] == pytest.approx(0.34)
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["run_config"]["eval_mode"] == "canonical-text"
    assert run_manifest["run_config"]["sequence_matcher"] == "dmp"


def test_labelstudio_benchmark_captures_eval_profile_artifacts_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS", "0.001")
    monkeypatch.setenv("COOKIMPORT_BENCHMARK_EVAL_PROFILE_TOP_N", "5")
    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
        },
    )
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Canonical mode should not call stage-block evaluator.")
        ),
    )

    def _fake_eval_canonical_text(**_kwargs):
        time.sleep(0.01)
        return {
            "report": {
                "counts": {"gold_total": 1, "pred_total": 1},
                "overall_line_accuracy": 1.0,
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "per_label": {},
                "evaluation_telemetry": {
                    "subphases": {
                        "load_prediction_seconds": 0.01,
                        "load_gold_seconds": 0.01,
                    }
                },
                "artifacts": {},
            },
            "missed_gold_blocks": [],
            "wrong_label_blocks": [],
            "missed_gold": [],
            "false_positive_preds": [],
        }

    monkeypatch.setattr(cli, "evaluate_canonical_text", _fake_eval_canonical_text)
    monkeypatch.setattr(cli, "format_canonical_eval_report_md", lambda *_: "report")

    captured_csv: dict[str, object] = {}

    def _capture_append(*_args, **kwargs):
        captured_csv.update(kwargs)

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )

    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        eval_mode="canonical-text",
    )

    assert (eval_root / "eval_profile.pstats").exists()
    assert (eval_root / "eval_profile_top.txt").exists()
    assert (eval_root / "eval_profile_top.txt").read_text(encoding="utf-8").strip()
    timing = captured_csv.get("timing")
    assert isinstance(timing, dict)
    checkpoints = timing.get("checkpoints")
    assert isinstance(checkpoints, dict)
    assert checkpoints["evaluate_profile_captured"] == pytest.approx(1.0)
    assert checkpoints["evaluate_profile_threshold_seconds"] == pytest.approx(0.001)
    assert checkpoints["evaluate_profile_artifact_write_seconds"] >= 0.0
    report = json.loads((eval_root / "eval_report.json").read_text(encoding="utf-8"))
    profiling = report["evaluation_telemetry"]["profiling"]
    assert profiling["enabled"] is True
    assert profiling["captured"] is True
    assert profiling["top_n"] == pytest.approx(5.0)
    assert profiling["threshold_seconds"] == pytest.approx(0.001)
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert "eval_profile_pstats" in run_manifest["artifacts"]
    assert "eval_profile_top" in run_manifest["artifacts"]


def test_labelstudio_benchmark_writes_eval_timing_and_passes_csv_timing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
                "run_config": {"workers": 1},
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "boundary": {"correct": 1, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")

    captured_csv: dict[str, object] = {}

    def _capture_append(*_args, **kwargs):
        captured_csv.update(kwargs)

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )

    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "timing": {
                "total_seconds": 9.0,
                "prediction_seconds": 9.0,
                "parsing_seconds": 6.0,
                "writing_seconds": 2.0,
                "ocr_seconds": 0.5,
                "checkpoints": {"split_wait_seconds": 0.2},
            },
        },
    )

    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
    )

    report_payload = json.loads((eval_root / "eval_report.json").read_text(encoding="utf-8"))
    timing = report_payload.get("timing")
    assert isinstance(timing, dict)
    assert timing["prediction_seconds"] == pytest.approx(9.0)
    assert timing["evaluation_seconds"] >= 0.0
    assert timing["artifact_write_seconds"] >= 0.0
    assert timing["history_append_seconds"] >= 0.0
    assert timing["total_seconds"] >= timing["prediction_seconds"]
    assert timing["checkpoints"]["prediction_load_seconds"] >= 0.0
    assert timing["checkpoints"]["evaluate_seconds"] >= 0.0
    assert isinstance(captured_csv.get("timing"), dict)
    assert captured_csv["timing"]["prediction_seconds"] == pytest.approx(9.0)


def test_labelstudio_benchmark_prunes_transient_artifacts_only_after_csv_append(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
                "run_config": {"workers": 1},
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "boundary": {"correct": 1, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "_refresh_dashboard_after_history_write", lambda **_kwargs: None)

    processed_run_root = tmp_path / "output" / "2026-03-03_02.10.00_foodlab-line-role-gated-fix7"
    processed_run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": processed_run_root,
            "processed_report_path": "",
            "timing": {"prediction_seconds": 2.5},
        },
    )

    call_order: list[str] = []
    from cookimport.analytics import perf_report as _perf_report

    real_append = _perf_report.append_benchmark_csv

    def _append_with_order(*args, **kwargs):
        call_order.append("append_csv")
        return real_append(*args, **kwargs)

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _append_with_order,
    )

    real_prune = cli._prune_benchmark_outputs

    def _prune_with_order(*, eval_output_dir, processed_run_root, suppress_summary, suppress_output_prune):
        call_order.append("prune")
        return real_prune(
            eval_output_dir=eval_output_dir,
            processed_run_root=processed_run_root,
            suppress_summary=suppress_summary,
            suppress_output_prune=suppress_output_prune,
        )

    monkeypatch.setattr(cli, "_prune_benchmark_outputs", _prune_with_order)

    eval_root = (
        tmp_path
        / "golden"
        / "benchmark-vs-golden"
        / "2026-03-03_02.10.00_foodlab-line-role-gated-fix7"
    )
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
    )

    assert call_order.count("append_csv") == 1
    assert call_order.count("prune") >= 1
    assert call_order.index("append_csv") < call_order.index("prune")
    assert not eval_root.exists()
    assert not processed_run_root.exists()

    csv_path = cli.history_csv_for_output(tmp_path / "output")
    assert csv_path.exists()
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    matching_row = next((row for row in rows if row.get("run_dir") == str(eval_root)), None)
    assert matching_row is not None
    assert float(matching_row["precision"]) == pytest.approx(1.0)
    assert float(matching_row["recall"]) == pytest.approx(1.0)


def test_labelstudio_benchmark_disables_prune_when_interactive_cli_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (prediction_run / "manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source_file),
                "source_hash": "hash-123",
                "run_config": {"workers": 1},
                "run_config_hash": "cfg-hash",
                "run_config_summary": "workers=1",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "boundary": {"correct": 1, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 1,
                    "pred_total": 1,
                    "gold_matched": 1,
                    "pred_matched": 1,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 1.0,
                "macro_f1_excluding_other": 1.0,
                "worst_label_recall": {"label": "RECIPE_TITLE", "recall": 1.0},
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "practical_precision": 1.0,
                "practical_recall": 1.0,
                "practical_f1": 1.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "_refresh_dashboard_after_history_write", lambda **_kwargs: None)

    processed_run_root = tmp_path / "output" / "2026-03-03_02.10.00_foodlab-line-role-gated-fix7"
    processed_run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        cli,
        "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": processed_run_root,
            "processed_report_path": "",
            "timing": {"prediction_seconds": 2.5},
        },
    )

    prune_calls: list[dict[str, object]] = []

    def _capture_prune(
        *,
        eval_output_dir: Path,
        processed_run_root: Path | None,
        suppress_summary: bool,
        suppress_output_prune: bool,
    ) -> None:
        prune_calls.append(
            {
                "eval_output_dir": eval_output_dir,
                "processed_run_root": processed_run_root,
                "suppress_summary": suppress_summary,
                "suppress_output_prune": suppress_output_prune,
            }
        )

    monkeypatch.setattr(cli, "_prune_benchmark_outputs", _capture_prune)

    eval_root = (
        tmp_path
        / "golden"
        / "benchmark-vs-golden"
        / "2026-03-03_02.10.00_foodlab-line-role-gated-fix7"
    )
    interactive_token = cli._INTERACTIVE_CLI_ACTIVE.set(True)
    try:
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "output",
            eval_output_dir=eval_root,
            no_upload=True,
        )
    finally:
        cli._INTERACTIVE_CLI_ACTIVE.reset(interactive_token)

    assert prune_calls
    assert all(bool(call["suppress_output_prune"]) for call in prune_calls)


def test_labelstudio_benchmark_applies_epub_extractor_for_prediction_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "stage_block_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "unstructured")
    monkeypatch.setattr(
        cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key")
    )
    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "recall": 0.0,
                "precision": 0.0,
                "boundary": {"correct": 0, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "_write_jsonl_rows", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "overall_block_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": 0.0},
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "practical_recall": 0.0,
                "practical_precision": 0.0,
                "practical_f1": 0.0,
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_stage_block_eval_report_md", lambda *_: "report")

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured["runtime_epub_extractor"] = os.environ.get("C3IMP_EPUB_EXTRACTOR")
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 1,
            "tasks_uploaded": 1,
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11-00-00-00",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", fake_run_labelstudio_import)

    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        eval_output_dir=tmp_path / "eval",
        allow_labelstudio_write=True,
        epub_extractor="beautifulsoup",
        pdf_ocr_policy="off",
        pdf_column_gap_ratio=0.14,
        section_detector_backend="shared_v1",
        multi_recipe_splitter="rules_v1",
        multi_recipe_trace=True,
        multi_recipe_min_ingredient_lines=2,
        multi_recipe_min_instruction_lines=2,
        multi_recipe_for_the_guardrail=False,
    )

    assert captured["runtime_epub_extractor"] == "beautifulsoup"
    assert captured["section_detector_backend"] == "shared_v1"
    assert captured["multi_recipe_splitter"] == "rules_v1"
    assert captured["multi_recipe_trace"] is True
    assert captured["multi_recipe_min_ingredient_lines"] == 2
    assert captured["multi_recipe_min_instruction_lines"] == 2
    assert captured["multi_recipe_for_the_guardrail"] is False
    assert captured["pdf_ocr_policy"] == "off"
    assert captured["pdf_column_gap_ratio"] == 0.14
    assert os.environ.get("C3IMP_EPUB_EXTRACTOR") == "unstructured"


def test_labelstudio_benchmark_rejects_invalid_epub_extractor() -> None:
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(epub_extractor="invalid")


def test_labelstudio_benchmark_rejects_policy_locked_markdown_extractor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", raising=False)
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(epub_extractor="markdown")
