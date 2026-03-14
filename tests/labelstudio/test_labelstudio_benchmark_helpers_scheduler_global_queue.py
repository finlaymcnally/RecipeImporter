from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


@pytest.fixture(autouse=True)
def _benchmark_codex_execution_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_benchmark_call_kwargs_codex_policy(monkeypatch)


def test_run_all_method_benchmark_global_queue_interleaves_sharded_heavy_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = _benchmark_test_run_settings()
    heavy_variants = [
        cli.AllMethodVariant(
            slug=f"heavy_{index:02d}",
            run_settings=base_settings,
            dimensions={"variant": index},
        )
        for index in range(4)
    ]
    light_variant = cli.AllMethodVariant(
        slug="light_01",
        run_settings=base_settings,
        dimensions={"variant": 1},
    )
    heavy_source = tmp_path / "heavy.epub"
    light_source = tmp_path / "light.docx"
    heavy_source.write_text("x", encoding="utf-8")
    light_source.write_text("x", encoding="utf-8")
    heavy_gold = tmp_path / "gold-heavy" / "exports" / "freeform_span_labels.jsonl"
    light_gold = tmp_path / "gold-light" / "exports" / "freeform_span_labels.jsonl"
    heavy_gold.parent.mkdir(parents=True, exist_ok=True)
    light_gold.parent.mkdir(parents=True, exist_ok=True)
    heavy_gold.write_text("{}\n", encoding="utf-8")
    light_gold.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=heavy_gold,
                source_file=heavy_source,
                source_file_name=heavy_source.name,
                gold_display="heavy",
            ),
            heavy_variants,
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=light_gold,
                source_file=light_source,
                source_file_name=light_source.name,
                gold_display="light",
            ),
            [light_variant],
        ),
    ]

    def fake_estimate(*, target, variants, prior_report_root=None):
        _ = variants
        _ = prior_report_root
        estimated = 3000.0 if target.source_file == heavy_source else 100.0
        return cli._AllMethodSourceEstimate(
            estimated_seconds=estimated,
            estimate_basis="test",
            canonical_text_chars=0,
            variant_count=len(variants),
        )

    call_order: list[str] = []

    def fake_prediction_once(**kwargs):
        source_file = kwargs["source_file"]
        variant = kwargs["variant"]
        config_index = int(kwargs["config_index"])
        root_output_dir = kwargs["root_output_dir"]
        assert isinstance(source_file, Path)
        assert isinstance(root_output_dir, Path)
        call_order.append(source_file.name)

        config_dir_name = cli._all_method_config_dir_name(config_index, variant)
        eval_output_dir = root_output_dir / config_dir_name
        prediction_record_path = eval_output_dir / "prediction-records.jsonl"
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        write_prediction_records(
            prediction_record_path,
            [
                make_prediction_record(
                    example_id=f"global:{source_file.name}:{config_index}",
                    example_index=0,
                    prediction={
                        "schema_kind": "stage-block.v1",
                        "block_index": 0,
                        "pred_label": "RECIPE_TITLE",
                        "block_text": f"{source_file.name}:{variant.slug}",
                        "block_features": {},
                    },
                    predict_meta={
                        "source_file": str(source_file),
                        "source_hash": f"source-{source_file.stem}",
                    },
                )
            ],
        )

        return {
            "config_index": config_index,
            "config_dir": config_dir_name,
            "slug": variant.slug,
            "status": "ok",
            "error": "",
            "run_config_hash": variant.run_settings.stable_hash(),
            "run_config_summary": variant.run_settings.summary(),
            "prediction_record_jsonl": str(
                prediction_record_path.relative_to(root_output_dir)
            ),
            "benchmark_sequence_matcher": variant.run_settings.benchmark_sequence_matcher,
            "duration_seconds": 0.01,
            "timing": {"total_seconds": 0.01, "checkpoints": {}},
            "dimensions": dict(variant.dimensions),
        }

    def fake_eval_once(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        report_json_path = eval_output_dir / "eval_report.json"
        report_md_path = eval_output_dir / "eval_report.md"
        report_json_path.write_text(
            json.dumps(
                {
                    "precision": 0.8,
                    "recall": 0.8,
                    "f1": 0.8,
                    "practical_precision": 0.8,
                    "practical_recall": 0.8,
                    "practical_f1": 0.8,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_md_path.write_text("ok", encoding="utf-8")
        return {
            "status": "ok",
            "error": "",
            "precision": 0.8,
            "recall": 0.8,
            "f1": 0.8,
            "practical_precision": 0.8,
            "practical_recall": 0.8,
            "practical_f1": 0.8,
            "timing": {
                "total_seconds": 0.01,
                "prediction_seconds": 0.0,
                "evaluation_seconds": 0.01,
                "checkpoints": {},
            },
            "report": {
                "precision": 0.8,
                "recall": 0.8,
                "f1": 0.8,
                "practical_precision": 0.8,
                "practical_recall": 0.8,
                "practical_f1": 0.8,
            },
            "report_md_text": "ok",
            "eval_report_json_path": report_json_path,
            "eval_report_md_path": report_md_path,
            "duration_seconds": 0.01,
        }

    monkeypatch.setattr(cli, "_estimate_all_method_source_cost", fake_estimate)
    monkeypatch.setattr(cli, "_run_all_method_prediction_once", fake_prediction_once)
    monkeypatch.setattr(cli, "_run_all_method_evaluate_prediction_record_once", fake_eval_once)

    report_md_path = cli._run_all_method_benchmark_global_queue(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed",
        overlap_threshold=0.5,
        force_source_match=False,
        max_parallel_sources=1,
        max_inflight_pipelines=1,
        max_concurrent_split_phases=1,
        source_scheduling=cli.ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR,
        source_shard_threshold_seconds=1000.0,
        source_shard_max_parts=2,
        source_shard_min_variants=2,
        smart_scheduler=False,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["scheduler_scope"] == "global_config_queue"
    assert payload["source_job_count_planned"] == 3
    assert payload["source_schedule_plan"][1]["source_file_name"] == light_source.name
    assert len(call_order) == 5
    assert call_order.index(light_source.name) < 4

def test_run_all_method_benchmark_global_queue_smart_eval_tail_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = _benchmark_test_run_settings()
    variants = [
        cli.AllMethodVariant(
            slug=f"cfg_{index}",
            run_settings=base_settings,
            dimensions={"variant": index},
        )
        for index in (1, 2, 3)
    ]
    source_file = tmp_path / "book.docx"
    source_file.write_text("x", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_spans,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display="gold",
            ),
            variants,
        )
    ]

    started_at: dict[int, float] = {}
    evaluate_started_at: dict[int, float] = {}
    finished_at: dict[int, float] = {}
    state_lock = threading.Lock()

    def fake_prediction_once(**kwargs):
        source_file_local = kwargs["source_file"]
        variant = kwargs["variant"]
        config_index = int(kwargs["config_index"])
        root_output_dir = kwargs["root_output_dir"]
        scheduler_events_dir = kwargs["scheduler_events_dir"]
        assert isinstance(source_file_local, Path)
        assert isinstance(root_output_dir, Path)
        assert isinstance(scheduler_events_dir, Path)

        config_dir_name = cli._all_method_config_dir_name(config_index, variant)
        eval_output_dir = root_output_dir / config_dir_name
        prediction_record_path = eval_output_dir / "prediction-records.jsonl"
        eval_output_dir.mkdir(parents=True, exist_ok=True)

        def emit(event_name: str) -> None:
            event_path = scheduler_events_dir / f"config_{config_index:03d}.jsonl"
            with event_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "event": event_name,
                            "config_index": config_index,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )

        with state_lock:
            started_at[config_index] = time.monotonic()
        emit("config_started")
        emit("split_active_started")
        time.sleep(0.03)
        emit("split_active_finished")
        emit("post_started")
        emit("post_finished")
        emit("evaluate_started")
        with state_lock:
            evaluate_started_at[config_index] = time.monotonic()
        time.sleep(0.35 if config_index == 1 else 0.2)
        emit("evaluate_finished")
        emit("config_finished")
        with state_lock:
            finished_at[config_index] = time.monotonic()

        write_prediction_records(
            prediction_record_path,
            [
                make_prediction_record(
                    example_id=f"tail:{source_file_local.name}:{config_index}",
                    example_index=0,
                    prediction={
                        "schema_kind": "stage-block.v1",
                        "block_index": 0,
                        "pred_label": "RECIPE_TITLE",
                        "block_text": f"{source_file_local.name}:{config_index}",
                        "block_features": {},
                    },
                    predict_meta={
                        "source_file": str(source_file_local),
                        "source_hash": f"source-{source_file_local.stem}",
                    },
                )
            ],
        )

        return {
            "config_index": config_index,
            "config_dir": config_dir_name,
            "slug": variant.slug,
            "status": "ok",
            "error": "",
            "run_config_hash": variant.run_settings.stable_hash(),
            "run_config_summary": variant.run_settings.summary(),
            "prediction_record_jsonl": str(
                prediction_record_path.relative_to(root_output_dir)
            ),
            "benchmark_sequence_matcher": variant.run_settings.benchmark_sequence_matcher,
            "duration_seconds": 0.01,
            "timing": {"total_seconds": 0.01, "checkpoints": {}},
            "dimensions": dict(variant.dimensions),
        }

    def fake_eval_once(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        report_json_path = eval_output_dir / "eval_report.json"
        report_md_path = eval_output_dir / "eval_report.md"
        report_json_path.write_text(
            json.dumps(
                {
                    "precision": 0.8,
                    "recall": 0.8,
                    "f1": 0.8,
                    "practical_precision": 0.8,
                    "practical_recall": 0.8,
                    "practical_f1": 0.8,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_md_path.write_text("ok", encoding="utf-8")
        return {
            "status": "ok",
            "error": "",
            "precision": 0.8,
            "recall": 0.8,
            "f1": 0.8,
            "practical_precision": 0.8,
            "practical_recall": 0.8,
            "practical_f1": 0.8,
            "timing": {
                "total_seconds": 0.01,
                "prediction_seconds": 0.0,
                "evaluation_seconds": 0.01,
                "checkpoints": {},
            },
            "report": {
                "precision": 0.8,
                "recall": 0.8,
                "f1": 0.8,
                "practical_precision": 0.8,
                "practical_recall": 0.8,
                "practical_f1": 0.8,
            },
            "report_md_text": "ok",
            "eval_report_json_path": report_json_path,
            "eval_report_md_path": report_md_path,
            "duration_seconds": 0.01,
        }

    monkeypatch.setattr(cli, "_run_all_method_prediction_once", fake_prediction_once)
    monkeypatch.setattr(cli, "_run_all_method_evaluate_prediction_record_once", fake_eval_once)
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

    report_md_path = cli._run_all_method_benchmark_global_queue(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed",
        overlap_threshold=0.5,
        force_source_match=False,
        max_parallel_sources=1,
        max_inflight_pipelines=1,
        max_concurrent_split_phases=1,
        max_eval_tail_pipelines=1,
        source_scheduling=cli.ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY,
        smart_scheduler=True,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    scheduler = payload["scheduler_summary"]
    assert scheduler["configured_inflight_pipelines"] == 1
    assert scheduler["eval_tail_headroom_effective"] == 1
    assert scheduler["max_active_pipelines_observed"] >= 2
    assert evaluate_started_at[1] <= started_at[2]
    assert started_at[2] < finished_at[1]

def test_run_all_method_benchmark_global_queue_non_epub_eval_uses_default_extractor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _benchmark_test_run_settings()
    variant = cli.AllMethodVariant(
        slug="source_docx",
        run_settings=settings,
        dimensions={"source_extension": ".docx"},
    )
    source_file = tmp_path / "book.docx"
    source_file.write_text("x", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_spans,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display="gold",
            ),
            [variant],
        )
    ]

    def fake_prediction_once(**kwargs):
        source_file_local = kwargs["source_file"]
        variant_local = kwargs["variant"]
        config_index = int(kwargs["config_index"])
        root_output_dir = kwargs["root_output_dir"]
        config_dir_name = cli._all_method_config_dir_name(config_index, variant_local)
        eval_output_dir = root_output_dir / config_dir_name
        prediction_record_path = eval_output_dir / "prediction-records.jsonl"
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        write_prediction_records(
            prediction_record_path,
            [
                make_prediction_record(
                    example_id=f"default-extractor:{config_index}",
                    example_index=0,
                    prediction={
                        "schema_kind": "stage-block.v1",
                        "block_index": 0,
                        "pred_label": "RECIPE_TITLE",
                        "block_text": f"{source_file_local.name}:{config_index}",
                        "block_features": {},
                    },
                    predict_meta={
                        "source_file": str(source_file_local),
                        "source_hash": f"source-{source_file_local.stem}",
                    },
                )
            ],
        )
        return {
            "config_index": config_index,
            "config_dir": config_dir_name,
            "slug": variant_local.slug,
            "status": "ok",
            "error": "",
            "run_config_hash": variant_local.run_settings.stable_hash(),
            "run_config_summary": variant_local.run_settings.summary(),
            "prediction_record_jsonl": str(
                prediction_record_path.relative_to(root_output_dir)
            ),
            "benchmark_sequence_matcher": variant_local.run_settings.benchmark_sequence_matcher,
            "duration_seconds": 0.01,
            "timing": {"total_seconds": 0.01, "checkpoints": {}},
            "dimensions": dict(variant_local.dimensions),
        }

    captured_epub_extractors: list[str | None] = []

    def fake_eval_once(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        captured_epub_extractors.append(kwargs.get("epub_extractor"))
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        report_json_path = eval_output_dir / "eval_report.json"
        report_md_path = eval_output_dir / "eval_report.md"
        report_json_path.write_text(
            json.dumps(
                {
                    "precision": 0.8,
                    "recall": 0.8,
                    "f1": 0.8,
                    "practical_precision": 0.8,
                    "practical_recall": 0.8,
                    "practical_f1": 0.8,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_md_path.write_text("ok", encoding="utf-8")
        return {
            "status": "ok",
            "error": "",
            "precision": 0.8,
            "recall": 0.8,
            "f1": 0.8,
            "practical_precision": 0.8,
            "practical_recall": 0.8,
            "practical_f1": 0.8,
            "timing": {
                "total_seconds": 0.01,
                "prediction_seconds": 0.0,
                "evaluation_seconds": 0.01,
                "checkpoints": {},
            },
            "report": {
                "precision": 0.8,
                "recall": 0.8,
                "f1": 0.8,
                "practical_precision": 0.8,
                "practical_recall": 0.8,
                "practical_f1": 0.8,
            },
            "report_md_text": "ok",
            "eval_report_json_path": report_json_path,
            "eval_report_md_path": report_md_path,
            "duration_seconds": 0.01,
        }

    monkeypatch.setattr(cli, "_run_all_method_prediction_once", fake_prediction_once)
    monkeypatch.setattr(cli, "_run_all_method_evaluate_prediction_record_once", fake_eval_once)

    cli._run_all_method_benchmark_global_queue(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=1,
        max_concurrent_split_phases=1,
        smart_scheduler=False,
    )

    assert captured_epub_extractors == [None]

def test_run_all_method_evaluate_prediction_record_once_preserves_fail_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_error = "Unable to load prediction record from /tmp/preds.jsonl: malformed record"

    def fake_labelstudio_benchmark(**_kwargs):
        cli._fail(expected_error)

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(
        cli,
        "_run_offline_benchmark_prediction_stage",
        lambda **kwargs: _dispatch_fake_prediction_stage_via_legacy_benchmark_double(
            fake_labelstudio_benchmark=fake_labelstudio_benchmark,
            prediction_generation_kwargs=kwargs["prediction_generation_kwargs"],
            eval_output_dir=kwargs["eval_output_dir"],
            predictions_out_path=kwargs["predictions_out_path"],
            source_file=source_file,
            extractor=str(
                kwargs["prediction_generation_kwargs"].get("epub_extractor")
                or "unstructured"
            ),
            extra_kwargs={
                "workers": kwargs["prediction_generation_kwargs"].get("workers"),
                "pdf_split_workers": kwargs["prediction_generation_kwargs"].get(
                    "pdf_split_workers"
                ),
                "epub_split_workers": kwargs["prediction_generation_kwargs"].get(
                    "epub_split_workers"
                ),
            },
        ),
    )
    monkeypatch.setattr(
        cli,
        "_run_offline_benchmark_prediction_stage",
        lambda **kwargs: _dispatch_fake_prediction_stage_via_legacy_benchmark_double(
            fake_labelstudio_benchmark=fake_labelstudio_benchmark,
            prediction_generation_kwargs=kwargs["prediction_generation_kwargs"],
            eval_output_dir=kwargs["eval_output_dir"],
            predictions_out_path=kwargs["predictions_out_path"],
            source_file=source_file,
            extractor=str(
                kwargs["prediction_generation_kwargs"].get("epub_extractor")
                or "unstructured"
            ),
            signature_seed=signature_seed_by_extractor[
                str(
                    kwargs["prediction_generation_kwargs"].get("epub_extractor")
                    or "unstructured"
                )
            ],
        ),
    )

    summary = cli._run_all_method_evaluate_prediction_record_once(
        gold_spans_path=tmp_path / "gold.jsonl",
        source_file=tmp_path / "book.epub",
        prediction_record_path=tmp_path / "predictions.jsonl",
        eval_output_dir=tmp_path / "eval",
        processed_output_dir=tmp_path / "processed",
        sequence_matcher="dmp",
        epub_extractor="unstructured",
        overlap_threshold=0.5,
        force_source_match=False,
        alignment_cache_dir=None,
    )

    assert summary["status"] == "failed"
    assert summary["error"] == expected_error
    assert summary["error"] != "1"

def test_run_all_method_benchmark_dedupes_eval_by_signature(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = _benchmark_test_run_settings()
    base_payload = base_settings.to_run_config_dict()
    extractors = ("unstructured", "beautifulsoup", "markdown")
    variants = [
        cli.AllMethodVariant(
            slug=f"extractor_{extractor}",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": extractor},
                warn_context="test",
            ),
            dimensions={"epub_extractor": extractor},
        )
        for extractor in extractors
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_text.txt").write_text("Title", encoding="utf-8")
    (gold_export_root / "canonical_span_labels.jsonl").write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_manifest.json").write_text("{}", encoding="utf-8")

    signature_seed_by_extractor = {
        "unstructured": "shared",
        "beautifulsoup": "shared",
        "markdown": "unique",
    }
    score_by_extractor = {
        "unstructured": 0.55,
        "beautifulsoup": 0.33,
        "markdown": 0.88,
    }
    eval_calls: list[str] = []

    def fake_labelstudio_benchmark(**kwargs):
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        if bool(kwargs.get("prediction_stage_only")):
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
                signature_seed=signature_seed_by_extractor[extractor],
            )
            return
        eval_calls.append(extractor)
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=score_by_extractor[extractor],
            total_seconds=2.0,
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(
        cli,
        "_run_offline_benchmark_prediction_stage",
        lambda **kwargs: _dispatch_fake_prediction_stage_via_legacy_benchmark_double(
            fake_labelstudio_benchmark=fake_labelstudio_benchmark,
            prediction_generation_kwargs=kwargs["prediction_generation_kwargs"],
            eval_output_dir=kwargs["eval_output_dir"],
            predictions_out_path=kwargs["predictions_out_path"],
            source_file=source_file,
            extractor=str(
                kwargs["prediction_generation_kwargs"].get("epub_extractor")
                or "unstructured"
            ),
            signature_seed="shared",
        ),
    )
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

    report_md_path = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed-output",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=3,
        max_concurrent_split_phases=2,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["evaluation_signatures_unique"] == 2
    assert payload["evaluation_runs_executed"] == 2
    assert payload["evaluation_results_reused_in_run"] == 1
    assert payload["evaluation_results_reused_cross_run"] == 0
    assert len(eval_calls) == 2

    rows_by_slug = {
        row.get("slug"): row
        for row in payload["variants"]
        if row.get("status") == "ok"
    }
    shared_rep = rows_by_slug["extractor_unstructured"]
    shared_dup = rows_by_slug["extractor_beautifulsoup"]
    assert shared_rep["evaluation_result_source"] == "executed"
    assert shared_dup["evaluation_result_source"] == "reused_in_run"
    assert shared_rep["eval_signature"] == shared_dup["eval_signature"]
    assert shared_rep["evaluation_representative_config_dir"] == shared_rep["config_dir"]
    assert shared_dup["evaluation_representative_config_dir"] == shared_rep["config_dir"]
    assert shared_rep["f1"] == pytest.approx(shared_dup["f1"])

def test_run_all_method_benchmark_reuses_signature_cache_across_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _benchmark_test_run_settings()
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=settings,
            dimensions={"epub_extractor": "unstructured"},
        )
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_text.txt").write_text("Title", encoding="utf-8")
    (gold_export_root / "canonical_span_labels.jsonl").write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_manifest.json").write_text("{}", encoding="utf-8")

    eval_call_count = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal eval_call_count
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        if bool(kwargs.get("prediction_stage_only")):
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
                signature_seed="shared",
            )
            return
        eval_call_count += 1
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=0.77,
            total_seconds=1.5,
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(
        cli,
        "_run_offline_benchmark_prediction_stage",
        lambda **kwargs: _dispatch_fake_prediction_stage_via_legacy_benchmark_double(
            fake_labelstudio_benchmark=fake_labelstudio_benchmark,
            prediction_generation_kwargs=kwargs["prediction_generation_kwargs"],
            eval_output_dir=kwargs["eval_output_dir"],
            predictions_out_path=kwargs["predictions_out_path"],
            source_file=source_file,
            extractor=str(
                kwargs["prediction_generation_kwargs"].get("epub_extractor")
                or "unstructured"
            ),
        ),
    )
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

    shared_alignment_cache_dir = (
        tmp_path / "shared-cache" / "canonical_alignment" / "book_source"
    )

    first_report_md = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-run-1",
        processed_output_root=tmp_path / "processed-1",
        overlap_threshold=0.5,
        force_source_match=False,
        canonical_alignment_cache_dir_override=shared_alignment_cache_dir,
    )
    first_payload = json.loads(first_report_md.with_suffix(".json").read_text(encoding="utf-8"))
    assert first_payload["evaluation_runs_executed"] == 1
    assert first_payload["evaluation_results_reused_cross_run"] == 0

    second_report_md = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-run-2",
        processed_output_root=tmp_path / "processed-2",
        overlap_threshold=0.5,
        force_source_match=False,
        canonical_alignment_cache_dir_override=shared_alignment_cache_dir,
    )
    second_payload = json.loads(second_report_md.with_suffix(".json").read_text(encoding="utf-8"))

    assert eval_call_count == 1
    assert second_payload["evaluation_runs_executed"] == 0
    assert second_payload["evaluation_results_reused_cross_run"] == 1
    second_rows = [
        row
        for row in second_payload["variants"]
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    assert len(second_rows) == 1
    second_row = second_rows[0]
    assert second_row["evaluation_result_source"] == "reused_cross_run"
    assert second_row["evaluation_representative_config_dir"] == second_row["config_dir"]
    cache_root = tmp_path / "shared-cache" / "eval_signature_results" / "book_source"
    assert cache_root.exists()
    assert list(cache_root.glob("*.json"))

def test_run_all_method_benchmark_resource_guard_caps_split_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = cli.RunSettings.from_dict(
        {
            "workers": 10,
            "pdf_split_workers": 10,
            "epub_split_workers": 10,
            "epub_extractor": "unstructured",
        },
        warn_context="test",
    )
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=settings,
            dimensions={"epub_extractor": "unstructured"},
        )
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    captured_workers: list[tuple[int, int, int]] = []

    def fake_labelstudio_benchmark(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        if bool(kwargs.get("prediction_stage_only")):
            captured_workers.append(
                (
                    int(kwargs.get("workers") or 0),
                    int(kwargs.get("pdf_split_workers") or 0),
                    int(kwargs.get("epub_split_workers") or 0),
                )
            )
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=0.7,
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(
        cli,
        "_run_offline_benchmark_prediction_stage",
        lambda **kwargs: _dispatch_fake_prediction_stage_via_legacy_benchmark_double(
            fake_labelstudio_benchmark=fake_labelstudio_benchmark,
            prediction_generation_kwargs=kwargs["prediction_generation_kwargs"],
            eval_output_dir=kwargs["eval_output_dir"],
            predictions_out_path=kwargs["predictions_out_path"],
            source_file=source_file,
            extractor=str(
                kwargs["prediction_generation_kwargs"].get("epub_extractor")
                or "unstructured"
            ),
            extra_kwargs={
                "workers": kwargs["prediction_generation_kwargs"].get("workers"),
                "pdf_split_workers": kwargs["prediction_generation_kwargs"].get(
                    "pdf_split_workers"
                ),
                "epub_split_workers": kwargs["prediction_generation_kwargs"].get(
                    "epub_split_workers"
                ),
            },
        ),
    )
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 5)
    monkeypatch.setattr(cli, "_system_total_memory_bytes", lambda: 64 * 1024 * 1024 * 1024)

    report_md_path = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=tmp_path / "processed-output",
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=2,
        max_inflight_pipelines=2,
        smart_scheduler=False,
    )

    assert captured_workers == [(4, 4, 4)]
    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    scheduler = payload["scheduler"]
    assert scheduler["split_worker_cap_per_config"] == 4
    assert scheduler["split_worker_cap_by_cpu"] == 4
    assert scheduler["split_worker_cap_by_memory"] >= 4
