from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def test_labelstudio_ingest_removes_legacy_standalone_tags_knobs() -> None:
    generate_signature = inspect.signature(generate_pred_run_artifacts)
    import_signature = inspect.signature(run_labelstudio_import)

    for signature in (generate_signature, import_signature):
        parameter_names = set(signature.parameters)
        assert "llm_tags_pipeline" not in parameter_names
        assert "tag_catalog_json" not in parameter_names
        assert "codex_farm_pipeline_tags" not in parameter_names

def test_labelstudio_import_prints_processing_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    _patch_cli_attr(monkeypatch, "_run_labelstudio_import_with_status",
        lambda **_kwargs: {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 1,
            "tasks_uploaded": 1,
            "run_root": tmp_path / "out",
        },
    )
    ticks = iter([100.0, 165.0])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))
    secho_messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: secho_messages.append(str(message)),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda *_args, **_kwargs: None)

    cli.labelstudio_import(
        path=source,
        allow_labelstudio_write=True,
        label_studio_url="http://example",
        label_studio_api_key="api-key",
        prelabel=False,
        prelabel_upload_as="annotations",
        prelabel_granularity=cli.PRELABEL_GRANULARITY_BLOCK,
        llm_recipe_pipeline="off",
        codex_farm_failure_mode="fail",
    )

    assert "Processing time: 1m 5s" in secho_messages

def test_labelstudio_import_prints_prelabel_failure_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    _patch_cli_attr(monkeypatch, "_run_labelstudio_import_with_status",
        lambda **_kwargs: {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 9,
            "tasks_uploaded": 9,
            "run_root": tmp_path / "out",
            "prelabel_report_path": str(tmp_path / "prelabel_report.json"),
            "prelabel_inline_annotations_fallback": False,
            "prelabel": {
                "task_count": 9,
                "success_count": 1,
                "failure_count": 8,
                "allow_partial": True,
                "errors_path": str(tmp_path / "prelabel_errors.jsonl"),
                "token_usage_enabled": False,
            },
        },
    )
    secho_messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: secho_messages.append(str(message)),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda *_args, **_kwargs: None)

    cli.labelstudio_import(
        path=source,
        allow_labelstudio_write=True,
        allow_codex=True,
        label_studio_url="http://example",
        label_studio_api_key="api-key",
        segment_blocks=40,
        segment_focus_blocks=40,
        prelabel=True,
        prelabel_allow_partial=True,
        prelabel_upload_as="annotations",
        prelabel_granularity=cli.PRELABEL_GRANULARITY_SPAN,
        llm_recipe_pipeline="off",
        codex_farm_failure_mode="fail",
    )

    assert any("PRELABEL ERRORS: 8/9 tasks failed (1 succeeded)." in line for line in secho_messages)
    assert any("Upload continued because allow-partial mode is enabled." in line for line in secho_messages)
    assert any("For fail-fast behavior, use --no-prelabel-allow-partial." in line for line in secho_messages)
    assert any("Prelabel errors: " in line for line in secho_messages)

def test_labelstudio_import_prints_prelabel_token_usage_with_reasoning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    _patch_cli_attr(monkeypatch, "_run_labelstudio_import_with_status",
        lambda **_kwargs: {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 4,
            "tasks_uploaded": 4,
            "run_root": tmp_path / "out",
            "prelabel_report_path": str(tmp_path / "prelabel_report.json"),
            "prelabel_inline_annotations_fallback": False,
            "prelabel": {
                "task_count": 4,
                "success_count": 4,
                "failure_count": 0,
                "allow_partial": False,
                "token_usage_enabled": True,
                "token_usage": {
                    "input_tokens": 111,
                    "cached_input_tokens": 22,
                    "output_tokens": 33,
                    "reasoning_tokens": 44,
                    "calls_with_usage": 4,
                },
            },
        },
    )
    secho_messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: secho_messages.append(str(message)),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda *_args, **_kwargs: None)

    cli.labelstudio_import(
        path=source,
        allow_labelstudio_write=True,
        allow_codex=True,
        label_studio_url="http://example",
        label_studio_api_key="api-key",
        segment_blocks=40,
        segment_focus_blocks=40,
        prelabel=True,
        prelabel_allow_partial=False,
        prelabel_upload_as="annotations",
        prelabel_granularity=cli.PRELABEL_GRANULARITY_SPAN,
        llm_recipe_pipeline="off",
        codex_farm_failure_mode="fail",
    )

    assert any(
        (
            "Prelabel token usage: input=111 cached_input=22 output=33 "
            "reasoning=44 calls_with_usage=4"
        )
        in line
        for line in secho_messages
    )

def test_labelstudio_import_routes_freeform_focus_and_target_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("dummy", encoding="utf-8")
    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings",
        lambda *_: ("http://example", "api-key"),
    )
    _patch_cli_attr(monkeypatch, "_run_labelstudio_import_with_status",
        lambda **kwargs: kwargs["run_import"](lambda _message: None),
    )
    captured: dict[str, object] = {}

    def _fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 1,
            "tasks_uploaded": 1,
            "run_root": tmp_path / "out",
        }

    _patch_cli_attr(monkeypatch, "run_labelstudio_import", _fake_run_labelstudio_import)
    monkeypatch.setattr(cli.typer, "secho", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli.typer, "echo", lambda *_args, **_kwargs: None)

    cli.labelstudio_import(
        path=source,
        allow_labelstudio_write=True,
        label_studio_url="http://example",
        label_studio_api_key="api-key",
        segment_blocks=40,
        segment_overlap=5,
        segment_focus_blocks=28,
        target_task_count=55,
        prelabel=False,
        prelabel_upload_as="annotations",
        prelabel_granularity=cli.PRELABEL_GRANULARITY_BLOCK,
        llm_recipe_pipeline="off",
        codex_farm_failure_mode="fail",
    )

    assert captured["segment_blocks"] == 40
    assert captured["segment_overlap"] == 5
    assert captured["segment_focus_blocks"] == 28
    assert captured["target_task_count"] == 55
    assert captured["upload_batch_size"] == 200
    assert captured["prelabel_timeout_seconds"] == cli.DEFAULT_PRELABEL_TIMEOUT_SECONDS

def test_discover_freeform_gold_exports_orders_newest_first(tmp_path: Path) -> None:
    older = tmp_path / "2026-01-01-000000" / "labelstudio" / "book" / "exports"
    newer = tmp_path / "2026-01-02-000000" / "labelstudio" / "book" / "exports"
    older.mkdir(parents=True, exist_ok=True)
    newer.mkdir(parents=True, exist_ok=True)
    older_path = older / "freeform_span_labels.jsonl"
    newer_path = newer / "freeform_span_labels.jsonl"
    older_path.write_text("{}\n", encoding="utf-8")
    newer_path.write_text("{}\n", encoding="utf-8")

    discovered = cli._discover_freeform_gold_exports(tmp_path)
    assert discovered[0] == newer_path
    assert discovered[1] == older_path

def test_discover_freeform_gold_exports_includes_golden_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "output"
    golden_root = tmp_path / "golden"
    exports = golden_root / "sample" / "freeform" / "2026-02-10_20:36:41" / "labelstudio" / "book" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    golden_path = exports / "freeform_span_labels.jsonl"
    golden_path.write_text("{}\n", encoding="utf-8")
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)

    discovered = cli._discover_freeform_gold_exports(output_root)
    assert golden_path in discovered

def test_display_gold_export_path_relative_to_golden_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "output"
    golden_root = tmp_path / "golden"
    path = (
        golden_root
        / "pulled-from-labelstudio"
        / "dinnerfor2cutdown"
        / "exports"
        / "freeform_span_labels.jsonl"
    )
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)

    display = cli._display_gold_export_path(path, output_root)
    assert display == "dinnerfor2cutdown"

def test_load_gold_recipe_headers_from_summary_prefers_recipe_counts(tmp_path: Path) -> None:
    exports = tmp_path / "run" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("{}\n", encoding="utf-8")
    (exports / "summary.json").write_text(
        json.dumps(
            {
                "recipe_counts": {"recipe_headers": 9},
                "counts": {"recipe_headers": 2},
            }
        ),
        encoding="utf-8",
    )

    assert cli._load_gold_recipe_headers_from_summary(gold_path) == 9

def test_load_gold_recipe_headers_from_summary_falls_back_to_counts(tmp_path: Path) -> None:
    exports = tmp_path / "run" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("{}\n", encoding="utf-8")
    (exports / "summary.json").write_text(
        json.dumps({"counts": {"recipe_headers": 4}}),
        encoding="utf-8",
    )

    assert cli._load_gold_recipe_headers_from_summary(gold_path) == 4

def test_discover_prediction_runs_orders_newest_first(tmp_path: Path) -> None:
    older = tmp_path / "2026-01-01-000000" / "labelstudio" / "book-a"
    newer = tmp_path / "2026-01-02-000000" / "labelstudio" / "book-b"
    older.mkdir(parents=True, exist_ok=True)
    newer.mkdir(parents=True, exist_ok=True)
    older_marker = older / "label_studio_tasks.jsonl"
    newer_marker = newer / "label_studio_tasks.jsonl"
    older_marker.write_text("{}\n", encoding="utf-8")
    newer_marker.write_text("{}\n", encoding="utf-8")

    discovered = cli._discover_prediction_runs(tmp_path)
    assert discovered[0] == newer
    assert discovered[1] == older

def test_infer_source_file_from_manifest_path(tmp_path: Path) -> None:
    source = tmp_path / "data" / "input" / "book.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x", encoding="utf-8")
    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("{}\n", encoding="utf-8")
    (run_root / "manifest.json").write_text(
        json.dumps({"source_file": str(source)}), encoding="utf-8"
    )

    inferred = cli._infer_source_file_from_freeform_gold(gold_path)
    assert inferred == source

def test_infer_source_file_from_gold_row_uses_default_input(
    tmp_path: Path, monkeypatch
) -> None:
    input_root = tmp_path / "data" / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    source = input_root / "book.epub"
    source.write_text("x", encoding="utf-8")
    _patch_cli_attr(monkeypatch, "DEFAULT_INPUT", input_root)

    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text(
        json.dumps({"source_file": "book.epub", "label": "RECIPE_NOTES"}) + "\n",
        encoding="utf-8",
    )

    inferred = cli._infer_source_file_from_freeform_gold(gold_path)
    assert inferred == source

def test_resolve_benchmark_gold_and_source_auto_uses_inferred_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gold_path = tmp_path / "exports" / "freeform_span_labels.jsonl"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold_path.write_text("{}\n", encoding="utf-8")
    inferred_source = tmp_path / "data" / "input" / "DinnerFor2CUTDOWN.epub"
    inferred_source.parent.mkdir(parents=True, exist_ok=True)
    inferred_source.write_text("x", encoding="utf-8")

    _patch_cli_attr(monkeypatch, "_infer_source_file_from_freeform_gold",
        lambda _path: inferred_source,
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm",
        lambda *_args, **_kwargs: pytest.fail("should not confirm inferred source"),
    )
    _patch_cli_attr(monkeypatch, "_menu_select",
        lambda *_args, **_kwargs: pytest.fail("should not prompt for source selection"),
    )
    _patch_cli_attr(monkeypatch, "_list_importable_files",
        lambda *_args, **_kwargs: pytest.fail("should not list importable files"),
    )
    _patch_cli_attr(monkeypatch, "_require_importer", lambda *_args, **_kwargs: None)

    resolved = cli._resolve_benchmark_gold_and_source(
        gold_spans=gold_path,
        source_file=None,
        output_dir=tmp_path,
        allow_cancel=False,
    )

    assert resolved == (gold_path, inferred_source)

def test_bench_all_method_resolve_benchmark_gold_and_source_uses_stage_importer_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gold_path = tmp_path / "exports" / "freeform_span_labels.jsonl"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold_path.write_text("{}\n", encoding="utf-8")
    inferred_source = tmp_path / "data" / "input" / "saltfatacidheatCUTDOWN.epub"
    inferred_source.parent.mkdir(parents=True, exist_ok=True)
    inferred_source.write_text("x", encoding="utf-8")

    _patch_cli_attr(
        monkeypatch,
        "_infer_source_file_from_freeform_gold",
        lambda _path: inferred_source,
    )
    _patch_cli_attr(
        monkeypatch,
        "_menu_select",
        lambda *_args, **_kwargs: pytest.fail("should not prompt for source selection"),
    )
    _patch_cli_attr(
        monkeypatch,
        "_list_importable_files",
        lambda *_args, **_kwargs: pytest.fail("should not list importable files"),
    )

    import cookimport.cli_support.stage as stage_support

    monkeypatch.setattr(
        stage_support.registry,
        "best_importer_for_path",
        lambda path: (object(), 1) if path == inferred_source else (None, 0),
    )

    resolved = bench_all_method._resolve_benchmark_gold_and_source(
        gold_spans=gold_path,
        source_file=None,
        output_dir=tmp_path,
        allow_cancel=False,
    )

    assert resolved == (gold_path, inferred_source)

def test_resolve_benchmark_gold_and_source_prompts_when_inference_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gold_path = tmp_path / "exports" / "freeform_span_labels.jsonl"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold_path.write_text("{}\n", encoding="utf-8")
    selected_source = tmp_path / "data" / "input" / "DinnerFor2CUTDOWN.epub"
    selected_source.parent.mkdir(parents=True, exist_ok=True)
    selected_source.write_text("x", encoding="utf-8")

    _patch_cli_attr(monkeypatch, "_infer_source_file_from_freeform_gold", lambda _path: None)
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_args, **_kwargs: [selected_source])
    _patch_cli_attr(monkeypatch, "_menu_select",
        lambda *_args, **_kwargs: selected_source,
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm",
        lambda *_args, **_kwargs: pytest.fail("should not confirm when inference is missing"),
    )
    _patch_cli_attr(monkeypatch, "_prompt_text",
        lambda *_args, **_kwargs: pytest.fail("should not prompt for custom source path"),
    )
    _patch_cli_attr(monkeypatch, "_require_importer", lambda *_args, **_kwargs: None)

    resolved = cli._resolve_benchmark_gold_and_source(
        gold_spans=gold_path,
        source_file=None,
        output_dir=tmp_path,
        allow_cancel=False,
    )

    assert resolved == (gold_path, selected_source)

def test_load_source_hint_from_gold_export_falls_back_to_segment_manifest(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("\n", encoding="utf-8")
    segment_manifest = exports / "freeform_segment_manifest.jsonl"
    segment_manifest.write_text(
        json.dumps({"segment_id": "s1", "source_file": "book.epub"}) + "\n",
        encoding="utf-8",
    )

    source_hint = cli._load_source_hint_from_gold_export(gold_path)
    assert source_hint == "book.epub"

def test_infer_scope_from_project_payload_detects_new_freeform_labels() -> None:
    scope = cli._infer_scope_from_project_payload(
        {"label_config": "<View><Label value='RECIPE_VARIANT'/></View>"}
    )
    assert scope == "freeform-spans"

def test_infer_scope_from_project_payload_rejects_removed_old_freeform_labels() -> None:
    scope = cli._infer_scope_from_project_payload(
        {"label_config": "<View><Label value='VARIANT'/></View>"}
    )
    assert scope is None

def test_labelstudio_eval_direct_call_uses_real_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    gold_spans = tmp_path / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    output_dir = tmp_path / "eval"

    _patch_cli_attr(monkeypatch, "load_predicted_labeled_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "load_gold_freeform_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "format_freeform_eval_report_md", lambda *_: "# report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    captured: dict[str, object] = {}

    def fake_eval(*_args, overlap_threshold: float, force_source_match: bool, **_kwargs):
        captured["overlap_threshold"] = overlap_threshold
        captured["force_source_match"] = force_source_match
        return {"report": {}, "missed_gold": [], "false_positive_preds": []}

    _patch_cli_attr(monkeypatch, "evaluate_predicted_vs_freeform", fake_eval)

    cli.labelstudio_eval(
        pred_run=pred_run,
        gold_spans=gold_spans,
        output_dir=output_dir,
    )

    assert captured["overlap_threshold"] == 0.5
    assert isinstance(captured["overlap_threshold"], float)
    assert captured["force_source_match"] is False
    assert isinstance(captured["force_source_match"], bool)

def test_labelstudio_eval_appends_benchmark_recipes_from_pred_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pred_run = tmp_path / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    line_role_telemetry_path = pred_run / "line-role-pipeline" / "telemetry_summary.json"
    line_role_telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    line_role_telemetry_path.write_text(
        json.dumps(
            {
                "summary": {
                    "tokens_input": 4,
                    "tokens_cached_input": 0,
                    "tokens_output": 1,
                    "tokens_reasoning": 0,
                    "tokens_total": 5,
                }
            }
        ),
        encoding="utf-8",
    )
    (pred_run / "manifest.json").write_text(
        json.dumps(
            {
                "recipe_count": 14,
                "source_file": str(tmp_path / "input" / "book.epub"),
                "processed_report_path": str(
                    tmp_path
                    / "output"
                    / "2026-02-16_15.00.00"
                    / "book.excel_import_report.json"
                ),
                "line_role_pipeline_telemetry_path": str(line_role_telemetry_path),
                "llm_codex_farm": {
                    "process_runs": {
                        "recipe_llm_correct_and_link": {
                            "process_payload": {
                                "telemetry": {
                                    "rows": [
                                        {
                                            "tokens_input": 11,
                                            "tokens_cached_input": 2,
                                            "tokens_output": 3,
                                            "tokens_reasoning": 1,
                                            "tokens_total": 14,
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    "knowledge": {
                        "process_run": {
                            "process_payload": {
                                "telemetry": {
                                    "rows": [
                                        {
                                            "tokens_input": 7,
                                            "tokens_cached_input": 1,
                                            "tokens_output": 2,
                                            "tokens_reasoning": 0,
                                            "tokens_total": 9,
                                        }
                                    ]
                                }
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    gold_spans = tmp_path / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    output_dir = tmp_path / "eval"

    _patch_cli_attr(monkeypatch, "load_predicted_labeled_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "load_gold_freeform_ranges", lambda *_: [])
    _patch_cli_attr(monkeypatch, "format_freeform_eval_report_md", lambda *_: "# report")
    _patch_cli_attr(monkeypatch, "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {},
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )

    captured_csv: dict[str, object] = {}
    captured_dashboard: dict[str, object] = {}

    def _capture_append(*args, **kwargs):
        captured_csv.update(kwargs)
        csv_path = Path(args[1])
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(
            "run_timestamp,run_dir,file_name,run_category\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )
    _patch_cli_attr(monkeypatch, "stats_dashboard", lambda **kwargs: captured_dashboard.update(kwargs))
    _patch_cli_attr(
        monkeypatch,
        "_refresh_dashboard_after_history_write",
        lambda *,
        csv_path,
        output_root=None,
        golden_root,
        dashboard_out_dir=None,
        reason=None: cli.stats_dashboard(
            output_root=output_root,
            golden_root=golden_root,
            out_dir=dashboard_out_dir or (csv_path.parent / "dashboard"),
            open_browser=False,
            since_days=None,
            scan_reports=False,
            scan_benchmark_reports=False,
        ),
    )

    cli.labelstudio_eval(
        pred_run=pred_run,
        gold_spans=gold_spans,
        output_dir=output_dir,
    )

    assert captured_csv["recipes"] == 14
    assert captured_csv["source_file"] == str(tmp_path / "input" / "book.epub")
    assert captured_csv["tokens_input"] == 22
    assert captured_csv["tokens_cached_input"] == 3
    assert captured_csv["tokens_output"] == 6
    assert captured_csv["tokens_reasoning"] == 1
    assert captured_csv["tokens_total"] == 28
    assert captured_dashboard["output_root"] == tmp_path / "output"
    assert captured_dashboard["out_dir"] == tmp_path / ".history" / "dashboard"

def test_labelstudio_commands_default_output_roots() -> None:
    import_param = inspect.signature(cli.labelstudio_import).parameters["output_dir"]
    export_param = inspect.signature(cli.labelstudio_export).parameters["output_dir"]
    benchmark_param = inspect.signature(cli.labelstudio_benchmark).parameters["output_dir"]
    eval_overlap_param = inspect.signature(cli.labelstudio_eval).parameters["overlap_threshold"]
    eval_force_match_param = inspect.signature(cli.labelstudio_eval).parameters["force_source_match"]

    assert getattr(import_param.default, "default", None) == cli.DEFAULT_GOLDEN_SENT_TO_LABELSTUDIO
    assert getattr(export_param.default, "default", None) == cli.DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO
    assert benchmark_param.default == cli.DEFAULT_GOLDEN_BENCHMARK
    assert eval_overlap_param.default == 0.5
    assert eval_force_match_param.default is False
