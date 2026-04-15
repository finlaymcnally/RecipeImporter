from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def _run_prune_after_csv_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, object]:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "semantic_row_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "semantic_row_predictions.v1",
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
    _patch_cli_attr(monkeypatch, "load_predicted_labeled_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "load_gold_freeform_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "evaluate_predicted_vs_freeform",
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
    _patch_cli_attr(monkeypatch, "format_freeform_eval_report_md", lambda *_: "report")
    _patch_cli_attr(monkeypatch, "_write_jsonl_rows", lambda *_: None)
    _patch_cli_attr(monkeypatch, "evaluate_source_rows",
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
    _patch_cli_attr(monkeypatch, "format_stage_block_eval_report_md", lambda *_: "report")
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write", lambda **_kwargs: None)

    processed_run_root = tmp_path / "output" / "2026-03-03_02.10.00_foodlab-line-role-gated-fix7"
    processed_run_root.mkdir(parents=True, exist_ok=True)
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": processed_run_root,
            "processed_report_path": "",
            "semantic_row_predictions_path": prediction_run / "semantic_row_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
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

    _patch_cli_attr(monkeypatch, "_prune_benchmark_outputs", _prune_with_order)

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
    csv_path = cli.history_csv_for_output(tmp_path / "output")
    return {
        "call_order": call_order,
        "eval_root": eval_root,
        "processed_run_root": processed_run_root,
        "csv_path": csv_path,
    }


def test_labelstudio_benchmark_prunes_transient_artifacts_only_after_csv_append(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_prune_after_csv_fixture(monkeypatch, tmp_path)
    call_order = fixture["call_order"]

    assert call_order.count("append_csv") == 1
    assert call_order.count("prune") >= 1
    assert call_order.index("append_csv") < call_order.index("prune")


def test_labelstudio_benchmark_prune_preserves_history_csv_before_removing_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_prune_after_csv_fixture(monkeypatch, tmp_path)
    eval_root = fixture["eval_root"]
    processed_run_root = fixture["processed_run_root"]
    csv_path = fixture["csv_path"]

    assert not eval_root.exists()
    assert not processed_run_root.exists()
    assert csv_path.exists()
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    matching_row = next((row for row in rows if row.get("run_dir") == str(eval_root)), None)
    assert matching_row is not None
    assert float(matching_row["precision"]) == pytest.approx(1.0)
    assert float(matching_row["recall"]) == pytest.approx(1.0)

def _run_interactive_prune_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, object]:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (prediction_run / "extracted_archive.json").write_text("[]\n", encoding="utf-8")
    (prediction_run / "semantic_row_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "semantic_row_predictions.v1",
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
    _patch_cli_attr(monkeypatch, "load_predicted_labeled_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "load_gold_freeform_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "evaluate_predicted_vs_freeform",
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
    _patch_cli_attr(monkeypatch, "format_freeform_eval_report_md", lambda *_: "report")
    _patch_cli_attr(monkeypatch, "_write_jsonl_rows", lambda *_: None)
    _patch_cli_attr(monkeypatch, "evaluate_source_rows",
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
    _patch_cli_attr(monkeypatch, "format_stage_block_eval_report_md", lambda *_: "report")
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write", lambda **_kwargs: None)

    processed_run_root = tmp_path / "output" / "2026-03-03_02.10.00_foodlab-line-role-gated-fix7"
    processed_run_root.mkdir(parents=True, exist_ok=True)
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": processed_run_root,
            "processed_report_path": "",
            "semantic_row_predictions_path": prediction_run / "semantic_row_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
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

    _patch_cli_attr(monkeypatch, "_prune_benchmark_outputs", _capture_prune)

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
    return {
        "prune_calls": prune_calls,
        "eval_root": eval_root,
        "processed_run_root": processed_run_root,
    }


def test_labelstudio_benchmark_disables_prune_when_interactive_cli_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_interactive_prune_fixture(monkeypatch, tmp_path)
    prune_calls = fixture["prune_calls"]
    assert prune_calls
    assert all(bool(call["suppress_output_prune"]) for call in prune_calls)


def test_labelstudio_benchmark_keeps_artifacts_when_interactive_cli_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_interactive_prune_fixture(monkeypatch, tmp_path)
    eval_root = fixture["eval_root"]
    processed_run_root = fixture["processed_run_root"]
    assert eval_root.exists()
    assert processed_run_root.exists()

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
    (prediction_run / "semantic_row_predictions.json").write_text(
        json.dumps(
            {
                "schema_version": "semantic_row_predictions.v1",
                "block_count": 0,
                "block_labels": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "unstructured")
    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key")
    )
    _patch_cli_attr(monkeypatch, "load_predicted_labeled_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "load_gold_freeform_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "evaluate_predicted_vs_freeform",
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
    _patch_cli_attr(monkeypatch, "format_freeform_eval_report_md", lambda *_: "report")
    _patch_cli_attr(monkeypatch, "_write_jsonl_rows", lambda *_: None)
    _patch_cli_attr(monkeypatch, "evaluate_source_rows",
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
    _patch_cli_attr(monkeypatch, "format_stage_block_eval_report_md", lambda *_: "report")

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
            "semantic_row_predictions_path": prediction_run / "semantic_row_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
        }

    _patch_cli_attr(monkeypatch, "run_labelstudio_import", fake_run_labelstudio_import)

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
    assert captured["multi_recipe_trace"] is False
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
