from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def test_run_all_method_benchmark_writes_ranked_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = _benchmark_test_run_settings()
    markdown_settings = cli.RunSettings.from_dict(
        {
            **_run_settings_model_payload(base_settings),
            "epub_extractor": "markdown",
        },
        warn_context="test",
    )
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=base_settings,
            dimensions={"epub_extractor": "unstructured"},
        ),
        cli.AllMethodVariant(
            slug="extractor_markdown",
            run_settings=markdown_settings,
            dimensions={"epub_extractor": "markdown"},
        ),
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    captured_processed_dirs: list[Path] = []
    captured_alignment_cache_dirs: list[Path] = []

    def fake_labelstudio_benchmark(**kwargs):
        progress_callback = cli._BENCHMARK_PROGRESS_CALLBACK.get()
        assert callable(progress_callback)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        processed_output_dir = kwargs["processed_output_dir"]
        assert isinstance(processed_output_dir, Path)
        captured_processed_dirs.append(processed_output_dir)
        alignment_cache_dir = kwargs["alignment_cache_dir"]
        assert isinstance(alignment_cache_dir, Path)
        captured_alignment_cache_dirs.append(alignment_cache_dir)
        extractor = str(kwargs.get("epub_extractor") or "")
        if bool(kwargs.get("prediction_stage_only")):
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor or "unstructured",
            )
            return
        f1 = 0.82 if extractor == "markdown" else 0.40
        total_seconds = 8.0 if extractor == "markdown" else 5.0
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=f1,
            total_seconds=total_seconds,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_run_offline_benchmark_prediction_stage",
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

    processed_root = tmp_path / "processed-output"
    report_md_path = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method",
        processed_output_root=processed_root,
        overlap_threshold=0.5,
        force_source_match=False,
    )

    assert report_md_path.exists()
    report_json_path = report_md_path.with_suffix(".json")
    payload = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert payload["variant_count"] == 2
    assert payload["successful_variants"] == 2
    assert payload["winner_by_f1"]["slug"] == "extractor_markdown"
    assert payload["timing_summary"]["source_wall_seconds"] >= 0.0
    assert payload["timing_summary"]["config_total_seconds"] == pytest.approx(13.0)
    assert payload["timing_summary"]["slowest_config_dir"] == payload["winner_by_f1"]["config_dir"]
    assert payload["variants"][0]["rank"] == 1
    assert payload["variants"][0]["slug"] == "extractor_markdown"
    assert payload["variants"][0]["timing"]["total_seconds"] == pytest.approx(8.0)
    assert captured_processed_dirs
    assert captured_alignment_cache_dirs
    for processed_dir in captured_processed_dirs:
        assert str(processed_dir).startswith(str(processed_root))
    for cache_dir in captured_alignment_cache_dirs:
        assert cache_dir == (tmp_path / "all-method" / ".cache" / "canonical_alignment")

def test_run_all_method_benchmark_parallel_queue_respects_inflight_and_rank_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = _benchmark_test_run_settings()
    base_payload = _run_settings_model_payload(base_settings)
    extractors = ("unstructured", "beautifulsoup", "markdown", "markitdown")
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
    scores = {
        "unstructured": 0.44,
        "beautifulsoup": 0.62,
        "markdown": 0.71,
        "markitdown": 0.89,
    }
    delays = {
        "unstructured": 0.03,
        "beautifulsoup": 0.015,
        "markdown": 0.02,
        "markitdown": 0.005,
    }
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    active_count = 0
    max_active = 0
    state_lock = threading.Lock()

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal active_count, max_active
        with state_lock:
            active_count += 1
            max_active = max(max_active, active_count)
        try:
            extractor = str(kwargs.get("epub_extractor") or "")
            eval_output_dir = kwargs["eval_output_dir"]
            assert isinstance(eval_output_dir, Path)
            if bool(kwargs.get("prediction_stage_only")):
                assert cli._BENCHMARK_SPLIT_PHASE_SLOTS.get() == 2
                assert cli._BENCHMARK_SPLIT_PHASE_GATE_DIR.get()
                time.sleep(delays[extractor])
                _write_fake_all_method_prediction_phase_artifacts(
                    kwargs=kwargs,
                    source_file=source_file,
                    extractor=extractor,
                )
                return
            f1 = scores[extractor]
            _write_fake_all_method_eval_artifacts(
                eval_output_dir=eval_output_dir,
                score=f1,
            )
        finally:
            with state_lock:
                active_count -= 1

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_run_offline_benchmark_prediction_stage",
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
    _patch_cli_attr(monkeypatch, "ProcessPoolExecutor", ThreadPoolExecutor)

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
    assert max_active <= 3
    assert max_active >= 2
    assert payload["successful_variants"] == 4
    assert payload["failed_variants"] == 0
    assert payload["winner_by_f1"]["slug"] == "extractor_markitdown"
    ranked_slugs = [
        row["slug"]
        for row in payload["variants"]
        if row.get("status") == "ok"
    ]
    assert ranked_slugs == [
        "extractor_markitdown",
        "extractor_markdown",
        "extractor_beautifulsoup",
        "extractor_unstructured",
    ]

def test_run_all_method_benchmark_marks_timeout_and_finishes_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = _benchmark_test_run_settings()
    base_payload = _run_settings_model_payload(base_settings)
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "unstructured"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "unstructured"},
        ),
        cli.AllMethodVariant(
            slug="extractor_markdown",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "markdown"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "markdown"},
        ),
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    def fake_labelstudio_benchmark(**kwargs):
        extractor = str(kwargs.get("epub_extractor") or "")
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        if bool(kwargs.get("prediction_stage_only")):
            if extractor == "unstructured":
                time.sleep(1.2)
            else:
                time.sleep(0.01)
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        score = 0.9 if extractor == "markdown" else 0.2
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=score,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_run_offline_benchmark_prediction_stage",
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
    _patch_cli_attr(monkeypatch, "ProcessPoolExecutor", ThreadPoolExecutor)

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
        max_inflight_pipelines=2,
        max_concurrent_split_phases=1,
        config_timeout_seconds=1,
        retry_failed_configs=0,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["successful_variants"] == 1
    assert payload["failed_variants"] == 1
    failed_rows = [row for row in payload["variants"] if row.get("status") != "ok"]
    assert len(failed_rows) == 1
    assert "timed out after 1s" in str(failed_rows[0].get("error", "")).lower()

def test_run_all_method_benchmark_retries_only_failed_configs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = _benchmark_test_run_settings()
    base_payload = _run_settings_model_payload(base_settings)
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "unstructured"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "unstructured"},
        ),
        cli.AllMethodVariant(
            slug="extractor_beautifulsoup",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "beautifulsoup"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "beautifulsoup"},
        ),
        cli.AllMethodVariant(
            slug="extractor_markdown",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "markdown"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "markdown"},
        ),
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    call_counts: dict[str, int] = {}

    def fake_labelstudio_benchmark(**kwargs):
        extractor = str(kwargs.get("epub_extractor") or "")
        if bool(kwargs.get("prediction_stage_only")):
            call_counts[extractor] = call_counts.get(extractor, 0) + 1
        if (
            bool(kwargs.get("prediction_stage_only"))
            and extractor == "beautifulsoup"
            and call_counts[extractor] == 1
        ):
            raise RuntimeError("synthetic transient failure")

        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        if bool(kwargs.get("prediction_stage_only")):
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        score = {
            "unstructured": 0.5,
            "beautifulsoup": 0.75,
            "markdown": 0.9,
        }[extractor]
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=score,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_run_offline_benchmark_prediction_stage",
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
    _patch_cli_attr(monkeypatch, "ProcessPoolExecutor", ThreadPoolExecutor)

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
        retry_failed_configs=1,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert call_counts["beautifulsoup"] == 2
    assert call_counts["unstructured"] == 1
    assert call_counts["markdown"] == 1
    assert payload["successful_variants"] == 3
    assert payload["failed_variants"] == 0
    assert payload["retry_failed_configs_requested"] == 1
    assert payload["retry_passes_executed"] == 1
    assert payload["retry_recovered_configs"] == 1

def test_run_all_method_benchmark_smart_scheduler_improves_heavy_slot_utilization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = _benchmark_test_run_settings()
    base_payload = _run_settings_model_payload(base_settings)
    variants = [
        cli.AllMethodVariant(
            slug=f"config_{index:02d}",
            run_settings=cli.RunSettings.from_dict(
                {
                    **base_payload,
                    # Keep scheduler test focused on admission/slot behavior by
                    # forcing unique prediction signatures per config.
                    "ocr_batch_size": index,
                },
                warn_context="test",
            ),
            dimensions={"index": index},
        )
        for index in range(1, 7)
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    phase_profile = {
        "prep": 0.12,
        "split_wait": 0.02,
        "split_active": 0.16,
        "post": 0.10,
        "evaluate": 0.16,
    }
    split_gate = threading.Semaphore(2)

    def fake_labelstudio_benchmark(**kwargs):
        callback = cli._BENCHMARK_SCHEDULER_EVENT_CALLBACK.get()
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        if bool(kwargs.get("prediction_stage_only")):
            if callback is not None:
                callback({"event": "prep_started"})
                time.sleep(phase_profile["prep"])
                callback({"event": "prep_finished"})
                callback({"event": "split_wait_started"})
                time.sleep(phase_profile["split_wait"])
                split_gate.acquire()
                try:
                    callback({"event": "split_wait_finished"})
                    callback({"event": "split_active_started"})
                    time.sleep(phase_profile["split_active"])
                    callback({"event": "split_active_finished"})
                finally:
                    split_gate.release()
                callback({"event": "post_started"})
                time.sleep(phase_profile["post"])
                callback({"event": "post_finished"})
                callback({"event": "evaluate_started"})
                time.sleep(phase_profile["evaluate"])
                callback({"event": "evaluate_finished"})
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        config_parts = eval_output_dir.name.split("_", 2)
        config_index = int(config_parts[1]) if len(config_parts) > 1 else 0
        score = 0.5 + (config_index * 0.01)
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=score,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_run_offline_benchmark_prediction_stage",
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
    _patch_cli_attr(monkeypatch, "ProcessPoolExecutor", ThreadPoolExecutor)

    fixed_report = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-fixed",
        processed_output_root=tmp_path / "processed-fixed",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=2,
        smart_scheduler=False,
    )
    fixed_payload = json.loads(fixed_report.with_suffix(".json").read_text(encoding="utf-8"))
    fixed_scheduler = fixed_payload["scheduler"]

    smart_report = cli._run_all_method_benchmark(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variants=variants,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-smart",
        processed_output_root=tmp_path / "processed-smart",
        overlap_threshold=0.5,
        force_source_match=False,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=2,
        smart_scheduler=True,
    )
    smart_payload = json.loads(smart_report.with_suffix(".json").read_text(encoding="utf-8"))
    smart_scheduler = smart_payload["scheduler"]

    assert smart_scheduler["heavy_slot_utilization_pct"] > (
        fixed_scheduler["heavy_slot_utilization_pct"] + 8.0
    )
    assert smart_scheduler["max_active_pipelines_observed"] <= smart_scheduler[
        "effective_inflight_pipelines"
    ]
    assert smart_scheduler["eval_tail_headroom_mode"] == "auto"
    assert smart_scheduler["eval_tail_headroom_effective"] >= 1
    assert smart_scheduler["max_active_during_eval"] == smart_scheduler[
        "effective_inflight_pipelines"
    ]
    assert smart_scheduler["max_active_pipelines_observed"] >= 3
    assert smart_scheduler["max_eval_active_observed"] >= 1

def test_run_all_method_benchmark_writes_scheduler_timeseries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = _benchmark_test_run_settings()
    variants = [
        cli.AllMethodVariant(
            slug=f"config_{index:02d}",
            run_settings=base_settings,
            dimensions={"index": index},
        )
        for index in range(1, 3)
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    def fake_labelstudio_benchmark(**kwargs):
        callback = cli._BENCHMARK_SCHEDULER_EVENT_CALLBACK.get()
        extractor = str(kwargs.get("epub_extractor") or "unstructured")
        if bool(kwargs.get("prediction_stage_only")):
            if callback is not None:
                callback({"event": "prep_started"})
                time.sleep(0.01)
                callback({"event": "split_wait_started"})
                time.sleep(0.01)
                callback({"event": "split_wait_finished"})
                callback({"event": "split_active_started"})
                time.sleep(0.01)
                callback({"event": "split_active_finished"})
                callback({"event": "post_started"})
                time.sleep(0.01)
                callback({"event": "post_finished"})
                callback({"event": "evaluate_started"})
                time.sleep(0.01)
                callback({"event": "evaluate_finished"})
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=0.7,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_run_offline_benchmark_prediction_stage",
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
    _patch_cli_attr(monkeypatch, "ProcessPoolExecutor", ThreadPoolExecutor)

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
        max_inflight_pipelines=2,
        max_concurrent_split_phases=1,
        smart_scheduler=True,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    scheduler = payload["scheduler"]
    timeseries_path = Path(str(scheduler["timeseries_path"]))
    assert timeseries_path.exists()
    assert timeseries_path.name == cli.ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    assert scheduler["snapshot_poll_seconds"] == cli.ALL_METHOD_SCHEDULER_POLL_SECONDS
    assert scheduler["timeseries_heartbeat_seconds"] >= cli.ALL_METHOD_SCHEDULER_POLL_SECONDS

    rows = [
        json.loads(line)
        for line in timeseries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    assert scheduler["timeseries_row_count"] == len(rows)
    assert any(int(row.get("active", 0)) == 0 and int(row.get("pending", 0)) == 0 for row in rows)
    first = rows[0]
    assert "snapshot" in first
    assert "cpu_utilization_pct" in first
    assert "heavy_active" in first
    assert "heavy_capacity" in first
    assert "wing_backlog" in first
    assert "evaluate_active" in first
    assert "active" in first
    assert "pending" in first
    assert "admission_active_cap" in first
    assert "admission_guard_target" in first
    assert "admission_wing_target" in first
    assert "admission_reason" in first
    assert "elapsed_seconds" in first
    assert scheduler["adaptive_admission_adjustments"] >= 0
    assert scheduler["split_phase_slots_requested"] >= scheduler["split_phase_slots"]

def test_run_all_method_benchmark_falls_back_to_thread_executor_when_process_workers_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = _benchmark_test_run_settings()
    base_payload = _run_settings_model_payload(base_settings)
    variants = [
        cli.AllMethodVariant(
            slug="extractor_unstructured",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "unstructured"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "unstructured"},
        ),
        cli.AllMethodVariant(
            slug="extractor_markdown",
            run_settings=cli.RunSettings.from_dict(
                {**base_payload, "epub_extractor": "markdown"},
                warn_context="test",
            ),
            dimensions={"epub_extractor": "markdown"},
        ),
    ]
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    class BrokenExecutor:
        def __init__(self, *_args, **_kwargs) -> None:
            raise PermissionError("denied")

    _patch_cli_attr(monkeypatch, "ProcessPoolExecutor", BrokenExecutor)

    call_count = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal call_count
        extractor = str(kwargs.get("epub_extractor") or "")
        if bool(kwargs.get("prediction_stage_only")):
            call_count += 1
            _write_fake_all_method_prediction_phase_artifacts(
                kwargs=kwargs,
                source_file=source_file,
                extractor=extractor,
            )
            return
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        _write_fake_all_method_eval_artifacts(
            eval_output_dir=eval_output_dir,
            score=0.7,
        )

    messages: list[str] = []
    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_run_offline_benchmark_prediction_stage",
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
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: messages.append(str(message)),
    )

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
        max_inflight_pipelines=4,
        max_concurrent_split_phases=2,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert call_count == len(variants)
    assert payload["successful_variants"] == len(variants)
    assert any(
        "using thread-based config concurrency" in message.lower()
        for message in messages
    )
