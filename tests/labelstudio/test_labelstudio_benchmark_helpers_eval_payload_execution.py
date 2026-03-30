from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def test_labelstudio_benchmark_passes_processed_output_root(
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
        extracted_rows=[],
        block_labels={},
    )

    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key")
    )
    _install_noop_benchmark_eval_mocks(monkeypatch)

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
            "stage_block_predictions_path": prediction_run / "stage_block_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
        }

    _patch_cli_attr(monkeypatch, "run_labelstudio_import", fake_run_labelstudio_import)

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

def _run_eval_output_dir_prediction_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, object]:
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

    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("No-upload mode must not resolve Label Studio credentials.")
        ),
    )
    _patch_cli_attr(monkeypatch, "run_labelstudio_import",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("No-upload mode must not call run_labelstudio_import.")
        ),
    )
    _install_noop_benchmark_eval_mocks(monkeypatch)

    captured_generate: dict[str, object] = {}
    llm_manifest_path = prediction_run / "raw" / "llm" / "book" / "llm_manifest.json"
    def fake_generate_pred_run_artifacts(**kwargs):
        captured_generate.update(kwargs)
        llm_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        llm_manifest_path.write_text("{}", encoding="utf-8")
        (prediction_run / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": str(source_file),
                    "source_hash": "fixture-hash",
                    "run_config": {
                        "selective_retry_attempted": True,
                        "selective_retry_recipe_correction_attempts": 1,
                        "selective_retry_recipe_correction_recovered": 1,
                        "selective_retry_final_recipe_attempts": 0,
                        "selective_retry_final_recipe_recovered": 0,
                    },
                    "run_config_hash": "hash-1",
                    "run_config_summary": "selective retry summary",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (prediction_run / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_kind": "bench_pred_run",
                    "artifacts": {
                        "recipe_manifest_json": str(llm_manifest_path),
                    },
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
            "stage_block_predictions_path": prediction_run / "stage_block_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
            "run_config": {
                "selective_retry_attempted": True,
                "selective_retry_recipe_correction_attempts": 1,
                "selective_retry_recipe_correction_recovered": 1,
                "selective_retry_final_recipe_attempts": 0,
                "selective_retry_final_recipe_recovered": 0,
            },
            "run_config_hash": "hash-1",
            "run_config_summary": "selective retry summary",
        }

    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts", fake_generate_pred_run_artifacts)

    eval_root = (
        tmp_path
        / "2026-03-03_10.20.00"
        / "single-profile-benchmark"
        / "01_book"
        / "vanilla"
    )
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
        write_markdown=False,
        write_label_studio_tasks=False,
        pdf_ocr_policy="always",
        pdf_column_gap_ratio=0.21,
    )
    run_manifest_path = eval_root / "run_manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    return {
        "captured_generate": captured_generate,
        "eval_root": eval_root,
        "source_file": source_file,
        "run_manifest_path": run_manifest_path,
        "run_manifest": run_manifest,
    }


def test_labelstudio_benchmark_uses_eval_output_dir_for_prediction_scratch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_eval_output_dir_prediction_fixture(monkeypatch, tmp_path)
    captured_generate = fixture["captured_generate"]
    eval_root = fixture["eval_root"]
    source_file = fixture["source_file"]
    run_manifest_path = fixture["run_manifest_path"]

    assert captured_generate["path"] == source_file
    assert captured_generate["output_dir"] == eval_root
    assert captured_generate["run_manifest_kind"] == "bench_pred_run"
    assert captured_generate["write_markdown"] is False
    assert captured_generate["write_label_studio_tasks"] is False
    assert captured_generate["pdf_ocr_policy"] == "always"
    assert captured_generate["pdf_column_gap_ratio"] == 0.21
    assert captured_generate["llm_recipe_pipeline"] == "off"
    assert captured_generate["allow_codex"] is False
    assert captured_generate["codex_execution_policy"] == "execute"
    assert captured_generate["atomic_block_splitter"] == "off"
    assert captured_generate["line_role_pipeline"] == "off"
    assert run_manifest_path.exists()


def test_labelstudio_benchmark_prediction_run_manifest_records_eval_output_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_eval_output_dir_prediction_fixture(monkeypatch, tmp_path)
    eval_root = fixture["eval_root"]
    run_manifest_path = fixture["run_manifest_path"]
    run_manifest = fixture["run_manifest"]

    assert run_manifest_path.exists()
    assert run_manifest["run_kind"] == "labelstudio_benchmark"
    assert run_manifest["run_config"]["upload"] is False
    assert run_manifest["run_config"]["write_markdown"] is False
    assert run_manifest["run_config"]["write_label_studio_tasks"] is False
    assert run_manifest["run_config"]["llm_recipe_pipeline"] == "off"
    assert run_manifest["run_config"]["codex_execution_policy_requested_mode"] == "execute"
    assert run_manifest["run_config"]["codex_execution_policy_resolved_mode"] == "not_required"
    assert run_manifest["run_config"]["codex_execution_live_llm_allowed"] is False
    assert run_manifest["run_config"]["codex_decision_context"] == "labelstudio_benchmark"
    assert run_manifest["run_config"]["codex_decision_allowed"] is True
    assert run_manifest["run_config"]["codex_decision_codex_surfaces"] == []
    assert run_manifest["run_config"]["atomic_block_splitter"] == "off"
    assert run_manifest["run_config"]["line_role_pipeline"] == "off"
    assert "prediction_codex_execution_plan_json" not in run_manifest["artifacts"]
    assert (
        run_manifest["run_config"]["prediction_run_config"]["selective_retry_attempted"]
        is True
    )
    assert (
        run_manifest["run_config"]["prediction_run_config"][
            "selective_retry_recipe_correction_attempts"
        ]
        == 1
    )
    assert (
        run_manifest["run_config"]["prediction_run_config"][
            "selective_retry_recipe_correction_recovered"
        ]
        == 1
    )
    assert run_manifest["artifacts"]["recipe_manifest_json"].endswith(
        "raw/llm/book/llm_manifest.json"
    )
    assert "eval_report_md" not in run_manifest["artifacts"]
    assert not (eval_root / "eval_report.md").exists()
    upload_bundle_dir = eval_root / cli.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    assert upload_bundle_dir.exists()

def test_labelstudio_benchmark_predictions_out_writes_prediction_record(
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
        extracted_rows=[
            {
                "index": 0,
                "text": "Sample title",
                "location": {"features": {"extraction_backend": "unstructured"}},
            }
        ],
        block_labels={"0": "RECIPE_TITLE"},
        manifest_payload={
            "run_config": {"workers": 1},
            "run_config_hash": "cfg-hash",
            "run_config_summary": "workers=1",
            "recipe_count": 7,
        },
    )
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "stage_block_predictions_path": prediction_run / "stage_block_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
            "timing": {"prediction_seconds": 1.5},
        },
    )
    _install_noop_benchmark_eval_mocks(monkeypatch)

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

def _run_predictions_in_evaluate_only_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, object]:
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

    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("Evaluate-only mode must not resolve Label Studio credentials.")
        ),
    )
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Evaluate-only mode must not regenerate prediction artifacts.")
        ),
    )
    _patch_cli_attr(monkeypatch, "run_labelstudio_import",
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

    _patch_cli_attr(monkeypatch, "evaluate_stage_blocks", _fake_evaluate_stage_blocks)
    _patch_cli_attr(monkeypatch, "format_stage_block_eval_report_md", lambda *_: "report")
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
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    return {
        "captured_eval": captured_eval,
        "replay_dir": replay_dir,
        "replay_stage_payload": replay_stage_payload,
        "run_manifest": run_manifest,
    }


def test_labelstudio_benchmark_predictions_in_replays_stage_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_predictions_in_evaluate_only_fixture(monkeypatch, tmp_path)
    captured_eval = fixture["captured_eval"]
    replay_dir = fixture["replay_dir"]
    replay_stage_payload = fixture["replay_stage_payload"]

    assert captured_eval["stage_predictions_json"] == (
        replay_dir / "stage_block_predictions.from_records.json"
    )
    assert captured_eval["extracted_blocks_json"] == (
        replay_dir / "extracted_archive.from_records.json"
    )
    assert replay_stage_payload["block_labels"] == {"0": "RECIPE_TITLE"}


def test_labelstudio_benchmark_predictions_in_manifest_disables_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _run_predictions_in_evaluate_only_fixture(monkeypatch, tmp_path)
    run_manifest = fixture["run_manifest"]

    assert run_manifest["run_config"]["upload"] is False
    assert "prediction_record_input_jsonl" in run_manifest["artifacts"]

def test_labelstudio_benchmark_predictions_in_rejects_legacy_run_pointer_record(
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

    predictions_in = tmp_path / "saved-prediction-records.jsonl"
    write_prediction_records(
        predictions_in,
        [
            make_prediction_record(
                example_id="saved-example-0",
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

    _patch_cli_attr(monkeypatch, "evaluate_stage_blocks", _fake_evaluate_stage_blocks)
    _patch_cli_attr(monkeypatch, "format_stage_block_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    eval_root = tmp_path / "eval-saved-record"
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(
            gold_spans=gold_spans,
            source_file=source_file,
            output_dir=tmp_path / "golden",
            processed_output_dir=tmp_path / "output",
            eval_output_dir=eval_root,
            predictions_in=predictions_in,
        )

def test_build_prediction_bundle_uses_manifest_canonical_scoring_pointers(
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
                "run_config": {"line_role_pipeline": "deterministic-route-v2"},
                # New contract: manifest's stage/extracted pointers are the one
                # canonical scoring surface regardless of diagnostics artifacts.
                "stage_block_predictions_path": str(line_role_stage_predictions_path),
                "extracted_archive_path": str(line_role_extracted_archive_path),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    import_result = {"run_root": prediction_run}

    bundle = cli._build_prediction_bundle_from_import_result(
        import_result=import_result,
        prediction_phase_seconds=1.0,
    )
    assert bundle.stage_predictions_path == line_role_stage_predictions_path
    assert bundle.extracted_archive_path == line_role_extracted_archive_path
    assert bundle.stage_predictions_path != default_stage_predictions_path
    assert bundle.extracted_archive_path != default_extracted_archive_path

def test_labelstudio_benchmark_manifest_omits_removed_mode_fields(
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
        extracted_rows=[{"index": 0, "text": "Sample title"}],
        block_labels={"0": "RECIPE_TITLE"},
    )
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "stage_block_predictions_path": prediction_run / "stage_block_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
            "timing": {"prediction_seconds": 2.0},
        },
    )
    _install_noop_benchmark_eval_mocks(monkeypatch)
    _patch_cli_attr(monkeypatch, "evaluate_stage_blocks",
        lambda **_kwargs: {
            "report": {
                **_empty_stage_block_eval_result()["report"],
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
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
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
    assert report["overall_block_accuracy"] == pytest.approx(1.0)

    run_manifest = json.loads(
        (eval_root / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert "execution_mode" not in run_manifest["run_config"]

def _run_offline_prediction_stage_fixture(
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
        extracted_rows=[{"index": 0, "text": "Sample title"}],
        block_labels={"0": "RECIPE_TITLE"},
    )
    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts",
        lambda **_kwargs: {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11_00.00.00",
            "processed_report_path": "",
            "stage_block_predictions_path": prediction_run / "stage_block_predictions.json",
            "extracted_archive_path": prediction_run / "extracted_archive.json",
            "timing": {"prediction_seconds": 1.25},
        },
    )
    _patch_cli_attr(monkeypatch, "evaluate_stage_blocks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "internal skip-evaluation mode must not run stage-block evaluation."
            )
        ),
    )
    _patch_cli_attr(monkeypatch, "evaluate_canonical_text",
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
    result = cli._run_offline_benchmark_prediction_stage(
        prediction_generation_kwargs={
            "path": source_file,
            "output_dir": tmp_path / "golden",
            "processed_output_root": tmp_path / "output",
            "pipeline": "auto",
            "segment_blocks": 40,
            "segment_overlap": 5,
            "limit": None,
            "sample": None,
            "workers": 1,
            "pdf_split_workers": 1,
            "epub_split_workers": 1,
            "pdf_pages_per_job": 50,
            "epub_spine_items_per_job": 10,
            "epub_extractor": "unstructured",
            "epub_unstructured_html_parser_version": "v1",
            "epub_unstructured_skip_headers_footers": True,
            "epub_unstructured_preprocess_mode": "br_split_v1",
            "ocr_device": "auto",
            "pdf_ocr_policy": "auto",
            "ocr_batch_size": 1,
            "pdf_column_gap_ratio": 0.12,
            "warm_models": False,
            "section_detector_backend": "shared_v1",
            "multi_recipe_splitter": "rules_v1",
            "multi_recipe_trace": False,
            "multi_recipe_min_ingredient_lines": 1,
            "multi_recipe_min_instruction_lines": 1,
            "multi_recipe_for_the_guardrail": True,
            "instruction_step_segmentation_policy": "auto",
            "instruction_step_segmenter": "heuristic_v1",
            "web_schema_extractor": "builtin_jsonld",
            "web_schema_normalizer": "simple",
            "web_html_text_extractor": "bs4",
            "web_schema_policy": "prefer_schema",
            "web_schema_min_confidence": 0.75,
            "web_schema_min_ingredients": 2,
            "web_schema_min_instruction_steps": 1,
            "ingredient_text_fix_backend": "none",
            "ingredient_pre_normalize_mode": "aggressive_v1",
            "ingredient_packaging_mode": "off",
            "ingredient_parser_backend": "ingredient_parser_nlp",
            "ingredient_unit_canonicalizer": "pint",
            "ingredient_missing_unit_policy": "null",
            "p6_time_backend": "regex_v1",
            "p6_time_total_strategy": "sum_all_v1",
            "p6_temperature_backend": "regex_v1",
            "p6_temperature_unit_backend": "builtin_v1",
            "p6_ovenlike_mode": "keywords_v1",
            "p6_yield_mode": "scored_v1",
            "p6_emit_metadata_debug": False,
            "recipe_scorer_backend": "heuristic_v1",
            "recipe_score_gold_min": 0.75,
            "recipe_score_silver_min": 0.55,
            "recipe_score_bronze_min": 0.35,
            "recipe_score_min_ingredient_lines": 1,
            "recipe_score_min_instruction_lines": 1,
            "llm_recipe_pipeline": "off",
            "llm_knowledge_pipeline": "off",
            "atomic_block_splitter": "off",
            "line_role_pipeline": "off",
            "codex_farm_cmd": None,
            "codex_farm_model": None,
            "codex_farm_reasoning_effort": None,
            "codex_farm_root": None,
            "codex_farm_workspace_root": None,
            "codex_farm_pipeline_knowledge": None,
            "codex_farm_context_blocks": 0,
            "codex_farm_knowledge_context_blocks": 0,
            "codex_farm_recipe_mode": "extract",
            "codex_farm_failure_mode": "fail_closed",
            "allow_codex": False,
            "codex_execution_policy": "execute",
            "write_markdown": True,
            "write_label_studio_tasks": False,
            "scheduler_event_callback": None,
            "progress_callback": None,
            "run_manifest_kind": "bench_pred_run",
        },
        eval_output_dir=eval_root,
        predictions_out_path=predictions_out,
    )
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    records = list(read_prediction_records(predictions_out))
    return {
        "result": result,
        "eval_root": eval_root,
        "run_manifest": run_manifest,
        "records": records,
    }


def test_run_offline_benchmark_prediction_stage_writes_prediction_artifacts_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_offline_prediction_stage_fixture(monkeypatch, tmp_path)
    result = fixture["result"]
    eval_root = fixture["eval_root"]
    records = fixture["records"]
    assert not (eval_root / "eval_report.json").exists()
    assert result.prediction_records
    assert len(records) == 1


def test_run_offline_benchmark_prediction_stage_manifest_omits_removed_mode_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_offline_prediction_stage_fixture(monkeypatch, tmp_path)
    run_manifest = fixture["run_manifest"]

    assert run_manifest["run_kind"] == "labelstudio_benchmark_prediction_stage"
    assert "execution_mode" not in run_manifest["run_config"]
    assert "predict_only" not in run_manifest["run_config"]
    assert "prediction_record_output_jsonl" in run_manifest["artifacts"]


def _run_interrupt_partial_artifacts_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    def _fake_generate_pred_run_artifacts(**kwargs):
        eval_root = Path(kwargs["run_root_override"])
        pred_run = eval_root / "prediction-run"
        pred_run.mkdir(parents=True, exist_ok=True)
        knowledge_stage_root = pred_run / "raw" / "llm" / "book" / "knowledge"
        knowledge_stage_root.mkdir(parents=True, exist_ok=True)
        (knowledge_stage_root / "worker_assignments.json").write_text("[]\n", encoding="utf-8")
        (knowledge_stage_root / "stage_status.json").write_text(
            json.dumps(
                {
                    "schema_version": "knowledge_stage_status.v1",
                    "stage_key": "nonrecipe_knowledge_review",
                    "stage_state": "interrupted",
                    "termination_cause": "operator_interrupt",
                    "finalization_completeness": "interrupted_before_finalization",
                    "artifact_states": {
                        "phase_manifest.json": "skipped_due_to_interrupt",
                        "task_status.jsonl": "skipped_due_to_interrupt",
                        "worker_assignments.json": "present",
                        "promotion_report.json": "skipped_due_to_interrupt",
                        "telemetry.json": "skipped_due_to_interrupt",
                        "failures.json": "skipped_due_to_interrupt",
                        "knowledge_manifest.json": "skipped_due_to_interrupt",
                        "proposals/*": "skipped_due_to_interrupt",
                    },
                    "pre_kill_failure_counts": {
                        "worker_terminal_states": {"watchdog_killed": 1},
                        "worker_reason_codes": {"watchdog_malformed_final_output": 1},
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (pred_run / "extracted_archive.json").write_text(
            json.dumps([{"index": 0, "text": "Sample title"}], sort_keys=True),
            encoding="utf-8",
        )
        (pred_run / "stage_block_predictions.json").write_text(
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
        (pred_run / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": str(source_file),
                    "source_hash": "hash-123",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (eval_root / "processing_timeseries_prediction.jsonl").write_text(
            json.dumps({"event": "started"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "run_root": pred_run,
            "processed_run_root": tmp_path / "processed" / "2026-03-20_12.00.00",
            "processed_report_path": "",
            "stage_block_predictions_path": pred_run / "stage_block_predictions.json",
            "extracted_archive_path": pred_run / "extracted_archive.json",
            "timing": {"prediction_seconds": 1.25},
        }

    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts", _fake_generate_pred_run_artifacts)
    _patch_cli_attr(monkeypatch, "evaluate_stage",
        lambda **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    eval_root = tmp_path / "eval-interrupted"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=tmp_path / "output",
        eval_output_dir=eval_root,
        no_upload=True,
    )

    status_payload = json.loads(
        (eval_root / "benchmark_status.json").read_text(encoding="utf-8")
    )
    partial_summary = json.loads(
        (eval_root / "partial_benchmark_summary.json").read_text(encoding="utf-8")
    )
    run_manifest = json.loads((eval_root / "run_manifest.json").read_text(encoding="utf-8"))
    return {
        "status_payload": status_payload,
        "partial_summary": partial_summary,
        "run_manifest": run_manifest,
    }


def test_labelstudio_benchmark_interrupt_marks_benchmark_status_interrupted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_interrupt_partial_artifacts_fixture(monkeypatch, tmp_path)
    status_payload = fixture["status_payload"]

    assert status_payload["status"] == "interrupted"
    assert status_payload["completed"] is False
    assert status_payload["interruption_cause"] == "operator"


def test_labelstudio_benchmark_interrupt_writes_partial_knowledge_stage_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_interrupt_partial_artifacts_fixture(monkeypatch, tmp_path)
    partial_summary = fixture["partial_summary"]

    assert partial_summary["status"] == "interrupted"
    assert partial_summary["interruption_cause"] == "operator"
    assert partial_summary["prediction_artifacts"]["prediction_run_dir"] == "prediction-run"
    assert (
        partial_summary["prediction_artifacts"]["processing_timeseries_prediction_jsonl"]
        == "processing_timeseries_prediction.jsonl"
    )
    assert partial_summary["knowledge_stage"]["stage_state"] == "interrupted"
    assert partial_summary["knowledge_stage"]["termination_cause"] == "operator_interrupt"
    assert (
        partial_summary["knowledge_stage"]["artifact_states"]["phase_manifest.json"]
        == "skipped_due_to_interrupt"
    )
    assert partial_summary["knowledge_stage"]["pre_kill_failures_observed"] is True


def test_labelstudio_benchmark_interrupt_manifest_points_to_partial_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_interrupt_partial_artifacts_fixture(monkeypatch, tmp_path)
    run_manifest = fixture["run_manifest"]

    assert run_manifest["run_kind"] == "labelstudio_benchmark"
    assert run_manifest["artifacts"]["benchmark_status_json"] == "benchmark_status.json"
    assert (
        run_manifest["artifacts"]["partial_benchmark_summary_json"]
        == "partial_benchmark_summary.json"
    )
