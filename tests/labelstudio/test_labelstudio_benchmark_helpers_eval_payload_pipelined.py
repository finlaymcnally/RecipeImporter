from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def test_labelstudio_benchmark_pipelined_mode_skips_canonical_prewarm_for_row_eval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    _write_benchmark_prediction_run_fixture(
        prediction_run=prediction_run,
        source_file=source_file,
    )

    prewarm_started = threading.Event()
    producer_observed_prewarm: dict[str, bool] = {"value": False}

    def _fake_generate_pred_run_artifacts(**_kwargs):
        producer_observed_prewarm["value"] = prewarm_started.wait(timeout=1.0)
        return {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "semantic_row_predictions_path": prediction_run / "semantic_row_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
            "timing": {"prediction_seconds": 0.4},
        }
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts", _fake_generate_pred_run_artifacts)

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_source_rows(**kwargs):
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

    _patch_cli_attr(monkeypatch, "evaluate_source_rows", _fake_evaluate_source_rows)
    _patch_cli_attr(monkeypatch, "format_source_row_eval_report_md", lambda *_: "report")
    _install_noop_benchmark_eval_mocks(monkeypatch)

    eval_root = tmp_path / "eval-pipelined"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        eval_mode="source-rows",
    )

    assert producer_observed_prewarm["value"] is False
    assert captured_eval["gold_export_root"] == gold_export_root

def _run_pipelined_streaming_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    _write_benchmark_prediction_run_fixture(
        prediction_run=prediction_run,
        source_file=source_file,
    )
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "semantic_row_predictions_path": prediction_run / "semantic_row_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
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

    _patch_cli_attr(monkeypatch, "_prediction_record_stage_row",
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
                "schema_kind": "semantic-row.v1",
                "row_index": 0,
                "pred_label": "RECIPE_TITLE",
                "row_text": "Title",
                "row_features": {"extraction_backend": "unstructured"},
            },
            predict_meta=predict_meta,
        )
        assert consumer_saw_first_record.wait(timeout=1.0)
        yield make_prediction_record(
            example_id="labelstudio-benchmark:hash-123:block:1",
            example_index=1,
            prediction={
                "schema_kind": "semantic-row.v1",
                "row_index": 1,
                "pred_label": "OTHER",
                "row_text": "Body",
                "row_features": {"extraction_backend": "unstructured"},
            },
            predict_meta=predict_meta,
        )
        producer_finished.set()

    _patch_cli_attr(monkeypatch, "predict_stage", _streaming_predict_stage)

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_source_rows(**kwargs):
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

    _install_noop_benchmark_eval_mocks(monkeypatch)
    _patch_cli_attr(monkeypatch, "evaluate_source_rows", _fake_evaluate_source_rows)
    _patch_cli_attr(monkeypatch, "format_stage_block_eval_report_md", lambda *_: "report")

    eval_root = tmp_path / "eval-pipelined-streaming"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
    )
    replay_dir = eval_root / ".prediction-record-replay" / "pipelined"
    return {
        "consumer_saw_first_record": consumer_saw_first_record,
        "producer_finished": producer_finished,
        "captured_eval": captured_eval,
        "replay_dir": replay_dir,
    }


def test_labelstudio_benchmark_pipelined_mode_streams_records_before_producer_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_pipelined_streaming_fixture(monkeypatch, tmp_path)
    consumer_saw_first_record = fixture["consumer_saw_first_record"]
    producer_finished = fixture["producer_finished"]
    assert consumer_saw_first_record.is_set()
    assert producer_finished.is_set()


def test_labelstudio_benchmark_pipelined_mode_replays_streamed_records_without_using_them_for_eval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_pipelined_streaming_fixture(monkeypatch, tmp_path)
    replay_dir = fixture["replay_dir"]
    captured_eval = fixture["captured_eval"]
    prediction_run = tmp_path / "pred-run"

    assert captured_eval["stage_predictions_json"] == (
        prediction_run / "semantic_row_predictions.json"
    )
    assert captured_eval["extracted_blocks_json"] == (
        prediction_run / "extracted_archive.json"
    )
    assert (replay_dir / "semantic_row_predictions.from_records.json").exists()
    replay_payload = json.loads(
        (replay_dir / "semantic_row_predictions.from_records.json").read_text(
            encoding="utf-8"
        )
    )
    assert replay_payload["row_labels"] == {"0": "RECIPE_TITLE", "1": "OTHER"}

def test_labelstudio_benchmark_pipelined_mode_propagates_consumer_stream_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    _write_benchmark_prediction_run_fixture(
        prediction_run=prediction_run,
        source_file=source_file,
    )
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "semantic_row_predictions_path": prediction_run / "semantic_row_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
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
                "row_index": 0,
                "pred_label": "RECIPE_TITLE",
                "row_text": "Title",
                "row_features": {},
            },
            predict_meta=predict_meta,
        )

    _patch_cli_attr(monkeypatch, "predict_stage", _invalid_streaming_predict_stage)
    _install_noop_benchmark_eval_mocks(monkeypatch)
    _patch_cli_attr(monkeypatch, "evaluate_source_rows",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Evaluation should not run when streaming consumer fails.")
        ),
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

def _run_canonical_text_pipelined_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, object]:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    prediction_run = tmp_path / "pred-run"
    line_role_dir = prediction_run / "line-role-pipeline"
    line_role_paths = _write_benchmark_prediction_run_fixture(
        prediction_run=prediction_run,
        source_file=source_file,
        stage_subdir="line-role-pipeline",
        row_labels={"0": "OTHER"},
        manifest_payload={
            "run_config": {"workers": 1, "line_role_pipeline": "deterministic-route-v2"},
            "run_config_hash": "cfg-hash",
            "run_config_summary": "workers=1",
        },
    )
    _write_benchmark_prediction_run_fixture(
        prediction_run=prediction_run,
        source_file=source_file,
        row_labels={"0": "RECIPE_TITLE"},
        manifest_payload={
            "run_config": {"workers": 1, "line_role_pipeline": "deterministic-route-v2"},
            "run_config_hash": "cfg-hash",
            "run_config_summary": "workers=1",
            "semantic_row_predictions_path": str(line_role_paths["stage_predictions_path"]),
            "extracted_archive_path": str(line_role_paths["extracted_archive_path"]),
        },
    )
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "semantic_row_predictions_path": line_role_paths["stage_predictions_path"],
            "extracted_archive_path": line_role_paths["extracted_archive_path"],
        },
    )
    _patch_cli_attr(monkeypatch, "evaluate_source_rows",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Canonical mode should not call source-row evaluator.")
        ),
    )

    captured_eval: dict[str, object] = {}

    def _fake_evaluate_source_rows(**kwargs):
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

    _patch_cli_attr(monkeypatch, "evaluate_source_rows", _fake_evaluate_source_rows)
    _patch_cli_attr(monkeypatch, "format_source_row_eval_report_md", lambda *_: "report")

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
            eval_mode="source-rows",
            line_role_pipeline="off",
            sequence_matcher="dmp",
        )
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    return {
        "captured_eval": captured_eval,
        "captured_csv": captured_csv,
        "scheduler_events": scheduler_events,
        "eval_root": eval_root,
        "line_role_stage_predictions_path": line_role_paths["stage_predictions_path"],
        "run_manifest": run_manifest,
    }


def test_labelstudio_benchmark_source_rows_mode_uses_row_evaluator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_canonical_text_pipelined_fixture(monkeypatch, tmp_path)
    captured_eval = fixture["captured_eval"]
    eval_root = fixture["eval_root"]
    line_role_stage_predictions_path = fixture["line_role_stage_predictions_path"]

    assert captured_eval["gold_export_root"] == (tmp_path / "gold" / "exports")
    replay_stage_predictions_path = (
        eval_root
        / ".prediction-record-replay"
        / "pipelined"
        / "semantic_row_predictions.from_records.json"
    )
    assert captured_eval["stage_predictions_json"] == line_role_stage_predictions_path
    assert replay_stage_predictions_path.exists()
    replay_payload = json.loads(
        replay_stage_predictions_path.read_text(encoding="utf-8")
    )
    assert replay_payload["row_labels"] == {"0": "OTHER"}


def test_labelstudio_benchmark_source_rows_mode_records_timing_and_scheduler_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_canonical_text_pipelined_fixture(monkeypatch, tmp_path)
    captured_csv = fixture["captured_csv"]
    scheduler_events = fixture["scheduler_events"]
    run_manifest = fixture["run_manifest"]

    assert captured_csv["eval_scope"] == "source-rows"
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
    assert run_manifest["run_config"]["eval_mode"] == "source-rows"
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
    _write_benchmark_prediction_run_fixture(
        prediction_run=prediction_run,
        source_file=source_file,
    )

    monkeypatch.setenv("COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS", "0.001")
    monkeypatch.setenv("COOKIMPORT_BENCHMARK_EVAL_PROFILE_TOP_N", "5")
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "semantic_row_predictions_path": prediction_run / "semantic_row_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
        },
    )
    _patch_cli_attr(monkeypatch, "evaluate_source_rows",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Canonical mode should not call source-row evaluator.")
        ),
    )

    def _fake_eval_source_rows(**_kwargs):
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

    _patch_cli_attr(monkeypatch, "evaluate_source_rows", _fake_eval_source_rows)
    _patch_cli_attr(monkeypatch, "format_source_row_eval_report_md", lambda *_: "report")

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
        eval_mode="source-rows",
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
    _write_benchmark_prediction_run_fixture(
        prediction_run=prediction_run,
        source_file=source_file,
        include_label_studio_tasks=True,
        manifest_payload={
            "run_config": {"workers": 1},
            "run_config_hash": "cfg-hash",
            "run_config_summary": "workers=1",
        },
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

    captured_csv: dict[str, object] = {}

    def _capture_append(*_args, **kwargs):
        captured_csv.update(kwargs)

    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        _capture_append,
    )

    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "semantic_row_predictions_path": prediction_run / "semantic_row_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
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
