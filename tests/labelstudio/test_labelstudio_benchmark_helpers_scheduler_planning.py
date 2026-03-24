from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def test_plan_all_method_source_jobs_tail_pair_interleaves_heavy_and_light(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = _benchmark_test_run_settings()
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_names = ["alpha", "beta", "gamma", "delta"]
    targets: list[tuple[cli.AllMethodTarget, list[cli.AllMethodVariant]]] = []
    for name in source_names:
        source_file = tmp_path / f"{name}.epub"
        source_file.write_text("x", encoding="utf-8")
        gold_spans = tmp_path / name / "exports" / "freeform_span_labels.jsonl"
        gold_spans.parent.mkdir(parents=True, exist_ok=True)
        gold_spans.write_text("{}\n", encoding="utf-8")
        targets.append(
            (
                cli.AllMethodTarget(
                    gold_spans_path=gold_spans,
                    source_file=source_file,
                    source_file_name=source_file.name,
                    gold_display=name,
                ),
                [variant],
            )
        )

    estimates = {
        "alpha.epub": 400.0,
        "beta.epub": 300.0,
        "gamma.epub": 200.0,
        "delta.epub": 100.0,
    }

    def fake_estimate(*, target, variants, prior_report_root=None):
        _ = variants
        _ = prior_report_root
        return cli._AllMethodSourceEstimate(
            estimated_seconds=estimates[target.source_file_name],
            estimate_basis="test",
            canonical_text_chars=0,
            variant_count=1,
        )

    _patch_cli_attr(monkeypatch, "_estimate_all_method_source_cost", fake_estimate)

    discovery_plans = cli._plan_all_method_source_jobs(
        target_variants=targets,
        scheduling_strategy="discovery",
        shard_threshold_seconds=99999.0,
        shard_max_parts=1,
        shard_min_variants=2,
    )
    assert [plan.source_file.name for plan in discovery_plans] == [
        "alpha.epub",
        "beta.epub",
        "gamma.epub",
        "delta.epub",
    ]

    tail_pair_plans = cli._plan_all_method_source_jobs(
        target_variants=targets,
        scheduling_strategy="tail_pair",
        shard_threshold_seconds=99999.0,
        shard_max_parts=1,
        shard_min_variants=2,
    )
    assert [plan.source_file.name for plan in tail_pair_plans] == [
        "alpha.epub",
        "delta.epub",
        "beta.epub",
        "gamma.epub",
    ]

def test_plan_all_method_source_jobs_shards_heavy_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = _benchmark_test_run_settings()
    variants = [
        cli.AllMethodVariant(
            slug=f"extractor_{index:02d}",
            run_settings=base_settings,
            dimensions={"variant": index},
        )
        for index in range(6)
    ]
    source_file = tmp_path / "heavy.epub"
    source_file.write_text("x", encoding="utf-8")
    gold_spans = tmp_path / "heavy" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_spans,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display="heavy",
            ),
            variants,
        )
    ]

    _patch_cli_attr(monkeypatch, "_estimate_all_method_source_cost",
        lambda **_kwargs: cli._AllMethodSourceEstimate(
            estimated_seconds=3000.0,
            estimate_basis="test",
            canonical_text_chars=0,
            variant_count=6,
        ),
    )

    shard_plans = cli._plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy="discovery",
        shard_threshold_seconds=1000.0,
        shard_max_parts=3,
        shard_min_variants=2,
    )
    assert len(shard_plans) == 3
    assert [len(plan.variants) for plan in shard_plans] == [2, 2, 2]
    assert all(plan.shard_total == 3 for plan in shard_plans)

    unsharded_plans = cli._plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy="discovery",
        shard_threshold_seconds=5000.0,
        shard_max_parts=3,
        shard_min_variants=2,
    )
    assert len(unsharded_plans) == 1
    assert len(unsharded_plans[0].variants) == 6

def test_plan_all_method_global_work_items_tail_pair_interleaves_sharded_sources(
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

    _patch_cli_attr(monkeypatch, "_estimate_all_method_source_cost", fake_estimate)

    work_items = cli._plan_all_method_global_work_items(
        target_variants=target_variants,
        scheduling_strategy=cli.ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR,
        shard_threshold_seconds=1000.0,
        shard_max_parts=2,
        shard_min_variants=2,
        root_output_dir=tmp_path / "run",
        processed_output_root=tmp_path / "processed",
        canonical_alignment_cache_root=tmp_path / "cache",
    )

    assert [item.global_dispatch_index for item in work_items] == [1, 2, 3, 4, 5]
    assert [item.source_file_name for item in work_items] == [
        "heavy.epub",
        "heavy.epub",
        "light.docx",
        "heavy.epub",
        "heavy.epub",
    ]
    heavy_items = [item for item in work_items if item.source_file == heavy_source]
    assert [item.config_index for item in heavy_items] == [1, 2, 3, 4]
    assert all(item.config_total == 4 for item in heavy_items)

def test_resolve_all_method_scheduler_limits_invalid_overrides_fall_back_to_defaults() -> None:
    inflight, split_slots = cli._resolve_all_method_scheduler_limits(
        total_variants=12,
        max_inflight_pipelines=0,
        max_concurrent_split_phases=0,
    )
    assert inflight == 4
    assert split_slots == 4

def test_resolve_all_method_scheduler_runtime_defaults_and_smart_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 9)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=12,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=3,
        smart_scheduler=True,
    )
    assert runtime.configured_inflight_pipelines == 2
    assert runtime.split_phase_slots == 2
    assert runtime.wing_backlog_target == 3
    assert runtime.eval_tail_headroom_mode == "auto"
    assert runtime.eval_tail_headroom_configured == 6
    assert runtime.eval_tail_headroom_effective == 6
    assert runtime.smart_scheduler_enabled is True
    assert runtime.max_active_during_eval == 8
    assert runtime.effective_inflight_pipelines == 8
    assert runtime.cpu_budget_per_source == 8

def test_resolve_all_method_scheduler_runtime_invalid_wing_respects_fixed_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 9)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=12,
        max_inflight_pipelines=3,
        max_concurrent_split_phases=2,
        wing_backlog_target=0,
        smart_scheduler=False,
    )
    assert runtime.configured_inflight_pipelines == 3
    assert runtime.split_phase_slots == 2
    assert runtime.wing_backlog_target == 2
    assert runtime.eval_tail_headroom_mode == "auto"
    assert runtime.eval_tail_headroom_configured == 5
    assert runtime.eval_tail_headroom_effective == 5
    assert runtime.smart_scheduler_enabled is False
    assert runtime.max_active_during_eval == 3
    assert runtime.effective_inflight_pipelines == 3

def test_resolve_all_method_scheduler_runtime_smart_tail_buffer_clamps_to_total() -> None:
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=4,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=3,
        max_eval_tail_pipelines=3,
        smart_scheduler=True,
    )
    assert runtime.configured_inflight_pipelines == 2
    assert runtime.split_phase_slots == 2
    assert runtime.wing_backlog_target == 3
    assert runtime.eval_tail_headroom_mode == "configured"
    assert runtime.eval_tail_headroom_configured == 3
    assert runtime.eval_tail_headroom_effective == 2
    assert runtime.smart_scheduler_enabled is True
    assert runtime.max_active_during_eval == 4
    assert runtime.effective_inflight_pipelines == 4

def test_resolve_all_method_scheduler_runtime_respects_eval_tail_cap_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 9)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=12,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        wing_backlog_target=3,
        max_eval_tail_pipelines=1,
        smart_scheduler=True,
    )
    assert runtime.configured_inflight_pipelines == 2
    assert runtime.split_phase_slots == 2
    assert runtime.wing_backlog_target == 3
    assert runtime.eval_tail_headroom_mode == "configured"
    assert runtime.eval_tail_headroom_configured == 1
    assert runtime.eval_tail_headroom_effective == 1
    assert runtime.smart_scheduler_enabled is True
    assert runtime.max_active_during_eval == 3
    assert runtime.effective_inflight_pipelines == 3

def test_resolve_all_method_scheduler_runtime_bounds_explicit_eval_tail_by_cpu_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 5)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=12,
        max_inflight_pipelines=2,
        max_concurrent_split_phases=2,
        max_eval_tail_pipelines=10,
        smart_scheduler=True,
    )
    assert runtime.eval_tail_headroom_mode == "configured"
    assert runtime.eval_tail_headroom_configured == 10
    assert runtime.cpu_budget_per_source == 4
    assert runtime.eval_tail_headroom_effective == 4
    assert runtime.max_active_during_eval == 6

def test_resolve_all_method_scheduler_runtime_auto_eval_tail_respects_source_parallelism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    _patch_cli_attr(monkeypatch, "_system_total_memory_bytes", lambda: 64 * 1024 * 1024 * 1024)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=40,
        max_inflight_pipelines=4,
        max_concurrent_split_phases=4,
        smart_scheduler=True,
        source_parallelism_effective=4,
    )
    assert runtime.configured_inflight_pipelines == 4
    assert runtime.split_phase_slots == 4
    assert runtime.wing_backlog_target == 4
    assert runtime.eval_tail_headroom_mode == "auto"
    assert runtime.eval_tail_headroom_effective == 0
    assert runtime.smart_scheduler_enabled is True
    assert runtime.max_active_during_eval == 4
    assert runtime.effective_inflight_pipelines == 4

def test_resolve_all_method_scheduler_runtime_caps_split_slots_with_resource_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    _patch_cli_attr(monkeypatch, "_system_total_memory_bytes", lambda: 64 * 1024 * 1024 * 1024)
    runtime = cli._resolve_all_method_scheduler_runtime(
        total_variants=40,
        max_inflight_pipelines=8,
        max_concurrent_split_phases=8,
        smart_scheduler=True,
        source_parallelism_effective=4,
    )
    assert runtime.split_phase_slots_requested == 8
    assert runtime.split_phase_slots == 4
    assert runtime.split_phase_slot_mode == "resource_guard"
    assert runtime.split_phase_slot_cap_by_cpu == 4
    assert runtime.split_phase_slot_cap_by_memory >= 1

def test_resolve_all_method_scheduler_admission_pressure_boosts_when_heavy_slots_starve() -> None:
    decision = cli._resolve_all_method_scheduler_admission(
        counts={
            "heavy_active": 0,
            "split_wait": 0,
            "prep_active": 0,
            "post_active": 0,
            "evaluate_active": 0,
            "wing_backlog": 0,
            "active": 1,
        },
        pending_count=5,
        total_variants=12,
        configured_inflight_pipelines=2,
        split_phase_slots=2,
        wing_backlog_target=2,
        max_active_during_eval=5,
        adaptive_overcommit_limit=2,
        adaptive_max_guard_target=8,
        smart_scheduler_enabled=True,
        cpu_utilization_pct=40.0,
    )
    assert decision.reason == "pressure_boost"
    assert decision.pressure_boost == 0
    assert decision.active_cap == 2
    assert decision.guard_target >= 6

def test_resolve_all_method_scheduler_admission_clamps_when_wing_backlog_is_saturated() -> None:
    decision = cli._resolve_all_method_scheduler_admission(
        counts={
            "heavy_active": 2,
            "split_wait": 3,
            "prep_active": 2,
            "post_active": 0,
            "evaluate_active": 0,
            "wing_backlog": 5,
            "active": 5,
        },
        pending_count=3,
        total_variants=12,
        configured_inflight_pipelines=2,
        split_phase_slots=2,
        wing_backlog_target=2,
        max_active_during_eval=5,
        adaptive_overcommit_limit=2,
        adaptive_max_guard_target=8,
        smart_scheduler_enabled=True,
        cpu_utilization_pct=35.0,
    )
    assert decision.reason == "saturation_clamp"
    assert decision.saturation_clamp is True
    assert decision.active_cap == 2
    assert decision.guard_target == 4

def test_resolve_all_method_scheduler_admission_clamps_when_cpu_hot() -> None:
    decision = cli._resolve_all_method_scheduler_admission(
        counts={
            "heavy_active": 1,
            "split_wait": 1,
            "prep_active": 1,
            "post_active": 0,
            "evaluate_active": 1,
            "wing_backlog": 2,
            "active": 3,
        },
        pending_count=2,
        total_variants=12,
        configured_inflight_pipelines=2,
        split_phase_slots=2,
        wing_backlog_target=2,
        max_active_during_eval=5,
        adaptive_overcommit_limit=2,
        adaptive_max_guard_target=8,
        smart_scheduler_enabled=True,
        cpu_utilization_pct=99.0,
    )
    assert decision.reason == "cpu_hot_clamp"
    assert decision.cpu_hot_clamp is True
    assert decision.active_cap == 4

def test_resolve_all_method_split_worker_cap_uses_cpu_and_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    _patch_cli_attr(monkeypatch, "_system_total_memory_bytes", lambda: 8 * 1024 * 1024 * 1024)

    cap, guard = cli._resolve_all_method_split_worker_cap(
        split_phase_slots=4,
        source_parallelism_effective=1,
    )

    assert cap == 1
    assert guard["split_worker_cap_by_cpu"] == 4
    assert guard["split_worker_cap_by_memory"] == 1
    assert guard["split_worker_cap_per_config"] == 1

def test_all_method_prediction_reuse_summary_detects_safe_and_blocked_split_convert_candidates() -> None:
    rows = [
        {
            "status": "ok",
            "prediction_result_source": "executed",
            "prediction_reuse_key": "pred-a",
            "prediction_split_convert_input_key": "split-a",
        },
        {
            "status": "ok",
            "prediction_result_source": "reused_in_run",
            "prediction_reuse_key": "pred-a",
            "prediction_split_convert_input_key": "split-a",
        },
        {
            "status": "ok",
            "prediction_result_source": "executed",
            "prediction_reuse_key": "pred-b1",
            "prediction_split_convert_input_key": "split-b",
        },
        {
            "status": "ok",
            "prediction_result_source": "executed",
            "prediction_reuse_key": "pred-b2",
            "prediction_split_convert_input_key": "split-b",
        },
        {
            "status": "ok",
            "prediction_result_source": "reused_cross_run",
            "prediction_reuse_key": "pred-c",
            "prediction_split_convert_input_key": "split-c",
        },
    ]

    summary = cli._all_method_prediction_reuse_summary(rows)

    assert summary["prediction_signatures_unique"] == 4
    assert summary["prediction_runs_executed"] == 3
    assert summary["prediction_results_reused_in_run"] == 1
    assert summary["prediction_results_reused_cross_run"] == 1
    assert summary["split_convert_input_groups"] == 3
    assert summary["split_convert_reuse_candidates"] == 2
    assert summary["split_convert_reuse_safe_candidates"] == 1
    assert summary["split_convert_reuse_blocked_by_prediction_variance"] == 1

def test_build_all_method_eval_signature_is_stable_for_same_payload(tmp_path: Path) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_text.txt").write_text("Title", encoding="utf-8")
    (gold_export_root / "canonical_span_labels.jsonl").write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_manifest.json").write_text("{}", encoding="utf-8")

    predictions_path = tmp_path / "prediction-records.jsonl"
    write_prediction_records(
        predictions_path,
        [
            make_prediction_record(
                example_id="sig:stable:0",
                example_index=0,
                prediction={
                    "schema_kind": "stage-block.v1",
                    "block_index": 0,
                    "pred_label": "RECIPE_TITLE",
                    "block_text": "Title",
                    "block_features": {},
                },
                predict_meta={
                    "source_file": str(source_file),
                    "source_hash": "hash-1",
                    "workbook_slug": "book",
                },
            )
        ],
    )

    signature_a = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_path,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )
    signature_b = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_path,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )

    assert signature_a == signature_b

def test_build_all_method_eval_signature_changes_when_inputs_change(tmp_path: Path) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = tmp_path / "gold" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_text.txt").write_text("Title", encoding="utf-8")
    (gold_export_root / "canonical_span_labels.jsonl").write_text("{}\n", encoding="utf-8")
    (gold_export_root / "canonical_manifest.json").write_text("{}", encoding="utf-8")

    predictions_a = tmp_path / "prediction-a.jsonl"
    predictions_b = tmp_path / "prediction-b.jsonl"
    write_prediction_records(
        predictions_a,
        [
            make_prediction_record(
                example_id="sig:a:0",
                example_index=0,
                prediction={
                    "schema_kind": "stage-block.v1",
                    "block_index": 0,
                    "pred_label": "RECIPE_TITLE",
                    "block_text": "Title A",
                    "block_features": {},
                },
                predict_meta={"source_file": str(source_file), "source_hash": "hash-1"},
            )
        ],
    )
    write_prediction_records(
        predictions_b,
        [
            make_prediction_record(
                example_id="sig:b:0",
                example_index=0,
                prediction={
                    "schema_kind": "stage-block.v1",
                    "block_index": 0,
                    "pred_label": "RECIPE_TITLE",
                    "block_text": "Title B",
                    "block_features": {},
                },
                predict_meta={"source_file": str(source_file), "source_hash": "hash-1"},
            )
        ],
    )

    base_signature = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_a,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )
    changed_prediction_signature = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_b,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )
    gold_spans.write_text('{"changed":true}\n', encoding="utf-8")
    changed_gold_signature = cli._build_all_method_eval_signature(
        gold_spans_path=gold_spans,
        prediction_record_path=predictions_a,
        eval_mode=cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        sequence_matcher="dmp",
    )

    assert base_signature != changed_prediction_signature
    assert base_signature != changed_gold_signature
