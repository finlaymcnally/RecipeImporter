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
def _legacy_prediction_stage_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_prediction_stage(**kwargs):  # type: ignore[no-untyped-def]
        prediction_generation_kwargs = kwargs["prediction_generation_kwargs"]
        source_path = Path(str(prediction_generation_kwargs.get("path")))
        return _dispatch_fake_prediction_stage_via_legacy_benchmark_double(
            fake_labelstudio_benchmark=cli.labelstudio_benchmark,
            prediction_generation_kwargs=prediction_generation_kwargs,
            eval_output_dir=kwargs["eval_output_dir"],
            predictions_out_path=kwargs["predictions_out_path"],
            source_file=source_path,
            extractor=str(prediction_generation_kwargs.get("epub_extractor") or "unstructured"),
        )

    _patch_cli_attr(monkeypatch, "_run_offline_benchmark_prediction_stage", _fake_prediction_stage)


def test_run_all_method_prediction_once_reuses_cached_prediction_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    variant = cli.AllMethodVariant(
        slug="reuse-check",
        run_settings=_benchmark_test_run_settings(),
        dimensions={"epub_extractor": "unstructured"},
    )

    benchmark_calls = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal benchmark_calls
        benchmark_calls += 1
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor="unstructured",
            prediction_seconds=1.5,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)

    root_output_dir = tmp_path / "all-method"
    scratch_root = root_output_dir / ".scratch"
    processed_output_root = tmp_path / "processed-output"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    first_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )
    second_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=2,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )

    assert benchmark_calls == 1
    assert first_row["prediction_result_source"] == "executed"
    assert first_row["prediction_reuse_scope"] == "executed"
    assert second_row["prediction_result_source"] == "reused_in_run"
    assert second_row["prediction_reuse_scope"] == "in_run"
    assert second_row["prediction_representative_config_dir"] == first_row["config_dir"]
    assert second_row["prediction_reuse_key"] == first_row["prediction_reuse_key"]
    assert (
        second_row["prediction_split_convert_input_key"]
        == first_row["prediction_split_convert_input_key"]
    )

    second_timing = cli._normalize_timing_payload(second_row.get("timing"))
    second_checkpoints = second_timing.get("checkpoints")
    assert isinstance(second_checkpoints, dict)
    assert second_checkpoints["all_method_prediction_reused_in_run"] == pytest.approx(1.0)
    assert second_checkpoints["all_method_prediction_reuse_copy_seconds"] >= 0.0

    second_prediction_record = root_output_dir / str(second_row["prediction_record_jsonl"])
    assert second_prediction_record.exists()

def test_run_all_method_prediction_once_reuses_across_runtime_only_setting_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    base_settings = _benchmark_test_run_settings()
    variant_a = cli.AllMethodVariant(
        slug="reuse-workers-a",
        run_settings=cli.RunSettings.from_dict(
            {
                **base_settings.model_dump(mode="json", exclude_none=True),
                "workers": 1,
                "pdf_split_workers": 1,
                "epub_split_workers": 1,
                "pdf_pages_per_job": 1,
                "epub_spine_items_per_job": 1,
                "warm_models": False,
            },
            warn_context="test",
        ),
        dimensions={"workers": 1},
    )
    variant_b = cli.AllMethodVariant(
        slug="reuse-workers-b",
        run_settings=cli.RunSettings.from_dict(
            {
                **base_settings.model_dump(mode="json", exclude_none=True),
                "workers": 8,
                "pdf_split_workers": 4,
                "epub_split_workers": 3,
                "pdf_pages_per_job": 10,
                "epub_spine_items_per_job": 6,
                "warm_models": True,
            },
            warn_context="test",
        ),
        dimensions={"workers": 8},
    )

    benchmark_calls = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal benchmark_calls
        benchmark_calls += 1
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor="unstructured",
            prediction_seconds=1.5,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)

    root_output_dir = tmp_path / "all-method"
    scratch_root = root_output_dir / ".scratch"
    processed_output_root = tmp_path / "processed-output"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    first_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant_a,
        config_index=1,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )
    second_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant_b,
        config_index=2,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )

    assert benchmark_calls == 1
    assert first_row["prediction_result_source"] == "executed"
    assert second_row["prediction_result_source"] == "reused_in_run"
    assert first_row["prediction_reuse_key"] == second_row["prediction_reuse_key"]
    assert (
        first_row["prediction_split_convert_input_key"]
        == second_row["prediction_split_convert_input_key"]
    )

def test_run_all_method_prediction_once_misses_reuse_when_prediction_shape_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    base_settings = _benchmark_test_run_settings()
    variant_a = cli.AllMethodVariant(
        slug="reuse-shape-a",
        run_settings=cli.RunSettings.from_dict(
            {
                **base_settings.model_dump(mode="json", exclude_none=True),
                "line_role_pipeline": "off",
            },
            warn_context="test",
        ),
        dimensions={"line_role_pipeline": "off"},
    )
    variant_b = cli.AllMethodVariant(
        slug="reuse-shape-b",
        run_settings=cli.RunSettings.from_dict(
            {
                **base_settings.model_dump(mode="json", exclude_none=True),
                "line_role_pipeline": "codex-line-role-route-v2",
            },
            warn_context="test",
        ),
        dimensions={"line_role_pipeline": "codex-line-role-route-v2"},
    )

    benchmark_calls = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal benchmark_calls
        benchmark_calls += 1
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor="unstructured",
            prediction_seconds=1.5,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)

    root_output_dir = tmp_path / "all-method"
    scratch_root = root_output_dir / ".scratch"
    processed_output_root = tmp_path / "processed-output"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    first_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant_a,
        config_index=1,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )
    second_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant_b,
        config_index=2,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )

    assert benchmark_calls == 2
    assert first_row["prediction_result_source"] == "executed"
    assert second_row["prediction_result_source"] == "executed"
    assert first_row["prediction_reuse_key"] != second_row["prediction_reuse_key"]

def test_run_all_method_prediction_once_reuses_cached_prediction_artifacts_across_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    variant = cli.AllMethodVariant(
        slug="reuse-check",
        run_settings=_benchmark_test_run_settings(),
        dimensions={"epub_extractor": "unstructured"},
    )

    benchmark_calls = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal benchmark_calls
        benchmark_calls += 1
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor="unstructured",
            prediction_seconds=1.5,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)

    shared_prediction_reuse_cache = tmp_path / "shared-prediction-reuse-cache"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    first_root_output_dir = tmp_path / "all-method-a"
    first_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=1,
        root_output_dir=first_root_output_dir,
        scratch_root=first_root_output_dir / ".scratch",
        processed_output_root=tmp_path / "processed-output-a",
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        prediction_reuse_cache_dir=shared_prediction_reuse_cache,
        split_worker_cap_per_config=None,
    )
    second_root_output_dir = tmp_path / "all-method-b"
    second_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=1,
        root_output_dir=second_root_output_dir,
        scratch_root=second_root_output_dir / ".scratch",
        processed_output_root=tmp_path / "processed-output-b",
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        prediction_reuse_cache_dir=shared_prediction_reuse_cache,
        split_worker_cap_per_config=None,
    )

    assert benchmark_calls == 1
    assert first_row["prediction_result_source"] == "executed"
    assert second_row["prediction_result_source"] == "reused_cross_run"
    assert second_row["prediction_reuse_scope"] == "cross_run"
    assert second_row["prediction_representative_config_dir"] == first_row["config_dir"]
    second_prediction_record = second_root_output_dir / str(
        second_row["prediction_record_jsonl"]
    )
    assert second_prediction_record.exists()

def test_run_all_method_prediction_once_reuse_falls_back_when_hardlink_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    variant = cli.AllMethodVariant(
        slug="reuse-check",
        run_settings=_benchmark_test_run_settings(),
        dimensions={"epub_extractor": "unstructured"},
    )

    benchmark_calls = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal benchmark_calls
        benchmark_calls += 1
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor="unstructured",
            prediction_seconds=1.5,
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)

    def _failing_link(_src: str, _dst: str, *args, **kwargs) -> None:
        raise OSError("simulated hardlink failure")

    monkeypatch.setattr(cli.os, "link", _failing_link)

    root_output_dir = tmp_path / "all-method"
    scratch_root = root_output_dir / ".scratch"
    processed_output_root = tmp_path / "processed-output"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    first_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )
    second_row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=2,
        total_variants=2,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )

    assert benchmark_calls == 1
    assert first_row["prediction_result_source"] == "executed"
    assert second_row["prediction_result_source"] == "reused_in_run"
    second_prediction_record = root_output_dir / str(second_row["prediction_record_jsonl"])
    assert second_prediction_record.exists()

def test_run_all_method_prediction_once_uses_adapter_forwarding_surface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.html"
    source_file.write_text("<html></html>", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    settings = cli.RunSettings.from_dict(
        {
            "workers": 6,
            "pdf_split_workers": 5,
            "epub_split_workers": 4,
            "multi_recipe_splitter": "rules_v1",
            "multi_recipe_min_ingredient_lines": 3,
            "multi_recipe_min_instruction_lines": 2,
            "multi_recipe_for_the_guardrail": False,
            "web_schema_extractor": "extruct",
            "web_schema_normalizer": "pyld",
            "web_html_text_extractor": "trafilatura",
            "web_schema_policy": "schema_only",
            "web_schema_min_confidence": 0.82,
            "web_schema_min_ingredients": 4,
            "web_schema_min_instruction_steps": 3,
            "ingredient_text_fix_backend": "ftfy",
            "ingredient_pre_normalize_mode": "aggressive_v1",
            "ingredient_packaging_mode": "regex_v1",
            "ingredient_parser_backend": "hybrid_nlp_then_quantulum3",
            "ingredient_unit_canonicalizer": "pint",
            "ingredient_missing_unit_policy": "each",
            "p6_time_backend": "quantulum3_v1",
            "p6_time_total_strategy": "selective_sum_v1",
            "p6_temperature_backend": "hybrid_regex_quantulum3_v1",
            "p6_temperature_unit_backend": "pint_v1",
            "p6_ovenlike_mode": "off",
            "p6_yield_mode": "scored_v1",
            "recipe_scorer_backend": "heuristic_v1",
            "recipe_score_gold_min": 0.8,
            "recipe_score_silver_min": 0.6,
            "recipe_score_bronze_min": 0.4,
            "recipe_score_min_ingredient_lines": 2,
            "recipe_score_min_instruction_lines": 2,
        },
        warn_context="test",
    )
    variant = cli.AllMethodVariant(
        slug="forwarding-check",
        run_settings=settings,
        dimensions={"source_extension": "html"},
    )

    captured_kwargs: dict[str, object] = {}

    def fake_prediction_stage(**kwargs):
        captured_kwargs.update(kwargs)
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs={
                **kwargs["prediction_generation_kwargs"],
                "eval_output_dir": kwargs["eval_output_dir"],
                "predictions_out": kwargs["predictions_out_path"],
            },
            source_file=source_file,
            extractor=str(
                kwargs["prediction_generation_kwargs"].get("epub_extractor")
                or "unstructured"
            ),
        )
        return _fake_offline_prediction_stage(
            prediction_generation_kwargs=kwargs["prediction_generation_kwargs"],
            eval_output_dir=kwargs["eval_output_dir"],
            predictions_out_path=kwargs["predictions_out_path"],
            source_file=source_file,
            extractor=str(
                kwargs["prediction_generation_kwargs"].get("epub_extractor")
                or "unstructured"
            ),
        )

    _patch_cli_attr(monkeypatch, "_run_offline_benchmark_prediction_stage", fake_prediction_stage)

    root_output_dir = tmp_path / "all-method"
    scratch_root = root_output_dir / ".scratch"
    processed_output_root = tmp_path / "processed-output"
    scheduler_events_dir = tmp_path / "events"
    split_phase_gate_dir = tmp_path / "split-gate"

    row = cli._run_all_method_prediction_once(
        gold_spans_path=gold_spans,
        source_file=source_file,
        variant=variant,
        config_index=1,
        total_variants=1,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_concurrent_split_phases=1,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=None,
        split_worker_cap_per_config=None,
    )

    assert row["status"] == "ok"
    config_dir_name = cli._all_method_config_dir_name(1, variant)
    expected_kwargs = cli.build_benchmark_call_kwargs_from_run_settings(
        settings,
        output_dir=scratch_root / config_dir_name,
        processed_output_dir=processed_output_root / config_dir_name,
        eval_output_dir=root_output_dir / config_dir_name,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        no_upload=True,
        write_markdown=False,
        write_label_studio_tasks=False,
    )
    assert captured_kwargs["eval_output_dir"] == root_output_dir / config_dir_name
    assert captured_kwargs["predictions_out_path"] == (
        root_output_dir / config_dir_name / "prediction-records.jsonl"
    )
    generation_kwargs = captured_kwargs["prediction_generation_kwargs"]
    assert isinstance(generation_kwargs, dict)
    assert generation_kwargs["path"] == source_file
    assert generation_kwargs["output_dir"] == scratch_root / config_dir_name
    assert generation_kwargs["processed_output_root"] == (
        processed_output_root / config_dir_name
    )
    for key, value in expected_kwargs.items():
        if key in {
            "eval_output_dir",
            "eval_mode",
            "no_upload",
            "sequence_matcher",
            "recipe_prompt_target_count",
            "knowledge_prompt_target_count",
            "line_role_prompt_target_count",
        }:
            continue
        if key == "processed_output_dir":
            assert generation_kwargs["processed_output_root"] == value
            continue
        if key == "source_file":
            assert generation_kwargs["path"] == value
            continue
        assert key in generation_kwargs
        assert generation_kwargs[key] == value
