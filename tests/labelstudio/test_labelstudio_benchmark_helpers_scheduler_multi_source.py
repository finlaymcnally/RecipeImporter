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


def test_run_all_method_benchmark_multi_source_writes_combined_summary_with_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = _benchmark_test_run_settings()
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_a = tmp_path / "book-a.epub"
    source_b = tmp_path / "book-b.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_a,
                source_file=source_a,
                source_file_name=source_a.name,
                gold_display="gold-a",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_b,
                source_file=source_b,
                source_file_name=source_b.name,
                gold_display="gold-b",
            ),
            [variant],
        ),
    ]
    unmatched = [
        cli.AllMethodUnmatchedGold(
            gold_spans_path=tmp_path / "gold-missing" / "exports" / "freeform_span_labels.jsonl",
            reason="Missing source hint in manifest, freeform_span_labels.jsonl, and freeform_segment_manifest.jsonl.",
            source_hint=None,
            gold_display="gold-missing",
        )
    ]

    def fake_run_all_method_benchmark(**kwargs):
        source_file = kwargs["source_file"]
        if source_file == source_b:
            raise RuntimeError("synthetic source failure")

        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        report_payload = {
            "successful_variants": 1,
            "failed_variants": 0,
            "winner_by_f1": {
                "precision": 0.9,
                "recall": 0.8,
                "f1": 0.85,
            },
            "timing_summary": {
                "source_wall_seconds": 7.5,
                "config_total_seconds": 7.5,
                "slowest_config_dir": "config_001",
                "slowest_config_seconds": 7.5,
            },
        }
        report_md_path.with_suffix(".json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=unmatched,
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["matched_target_count"] == 2
    assert payload["unmatched_target_count"] == 1
    assert payload["total_config_runs_planned"] == 2
    assert payload["total_config_runs_completed"] == 1
    assert payload["total_config_runs_successful"] == 1
    assert payload["successful_source_count"] == 1
    assert payload["failed_source_count"] == 1
    assert payload["sources"][0]["status"] == "ok"
    assert payload["sources"][1]["status"] == "failed"
    assert payload["sources"][0]["timing_summary"]["source_wall_seconds"] == pytest.approx(7.5)
    assert payload["timing_summary"]["source_total_seconds"] == pytest.approx(7.5)
    assert payload["timing_summary"]["slowest_source"] == str(source_a)
    assert payload["timing_summary"]["slowest_config"] == "book_a/config_001"

def test_run_all_method_benchmark_multi_source_forwards_dashboard_snapshots_without_rewrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = _benchmark_test_run_settings()
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    gold = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold,
                source_file=source,
                source_file_name=source.name,
                gold_display="gold",
            ),
            [variant],
        )
    ]
    dashboard = cli._AllMethodProgressDashboard.from_target_variants(target_variants)
    emitted_messages: list[str] = []

    def fake_run_all_method_benchmark(**kwargs):
        progress_callback = kwargs["progress_callback"]
        assert callable(progress_callback)
        progress_callback(
            "\n".join(
                [
                    "overall source 0/1 | config 0/1",
                    f"current source: {source.name} (0 of 1 configs; ok 0, fail 0)",
                    "current config 1/1: extractor_unstructured",
                    "queue:",
                    f"  [>] {source.name} - 0 of 1 (ok 0, fail 0)",
                ]
            )
        )

        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        report_payload = {
            "successful_variants": 1,
            "failed_variants": 0,
            "winner_by_f1": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "timing_summary": {"source_wall_seconds": 1.0, "config_total_seconds": 1.0},
        }
        report_md_path.with_suffix(".json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)

    cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        progress_callback=emitted_messages.append,
        dashboard=dashboard,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
    )

    assert any(message.startswith("overall source ") for message in emitted_messages)
    assert not any("task: overall source" in message for message in emitted_messages)

def test_run_all_method_benchmark_multi_source_rerenders_partial_dashboard_snapshots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = _benchmark_test_run_settings()
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_a = tmp_path / "book-a.epub"
    source_b = tmp_path / "book-b.epub"
    source_a.write_text("x", encoding="utf-8")
    source_b.write_text("x", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_a,
                source_file=source_a,
                source_file_name=source_a.name,
                gold_display="gold-a",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_b,
                source_file=source_b,
                source_file_name=source_b.name,
                gold_display="gold-b",
            ),
            [variant],
        ),
    ]
    dashboard = cli._AllMethodProgressDashboard.from_target_variants(target_variants)
    emitted_messages: list[str] = []

    def fake_run_all_method_benchmark(**kwargs):
        progress_callback = kwargs["progress_callback"]
        assert callable(progress_callback)
        # Simulate a stale/partial snapshot from a nested callback. The wrapper
        # should rerender from the shared dashboard state instead.
        progress_callback(
            "\n".join(
                [
                    "overall source 0/2 | config 0/2",
                    f"current source: {source_a.name} (0 of 1 configs; ok 0, fail 0)",
                    "current config 1/1: extractor_unstructured",
                    "queue:",
                    f"  [>] {source_a.name} - 0 of 1 (ok 0, fail 0)",
                ]
            )
        )

        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        report_payload = {
            "successful_variants": 1,
            "failed_variants": 0,
            "winner_by_f1": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "timing_summary": {"source_wall_seconds": 1.0, "config_total_seconds": 1.0},
        }
        report_md_path.with_suffix(".json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)

    cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        progress_callback=emitted_messages.append,
        dashboard=dashboard,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
    )

    dashboard_messages = [
        message for message in emitted_messages if message.startswith("overall source ")
    ]
    assert dashboard_messages
    for message in dashboard_messages:
        assert source_a.name in message
        assert source_b.name in message

def test_run_all_method_benchmark_multi_source_parallel_cap_and_ordering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = _benchmark_test_run_settings()
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_a = tmp_path / "book-a.epub"
    source_b = tmp_path / "book-b.epub"
    source_c = tmp_path / "book-c.epub"
    source_a.write_text("x", encoding="utf-8")
    source_b.write_text("x", encoding="utf-8")
    source_c.write_text("x", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_c = tmp_path / "gold-c" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_c.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b.write_text("{}\n", encoding="utf-8")
    gold_c.write_text("{}\n", encoding="utf-8")

    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_a,
                source_file=source_a,
                source_file_name=source_a.name,
                gold_display="gold-a",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_b,
                source_file=source_b,
                source_file_name=source_b.name,
                gold_display="gold-b",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_c,
                source_file=source_c,
                source_file_name=source_c.name,
                gold_display="gold-c",
            ),
            [variant],
        ),
    ]
    delays = {
        source_a: 0.04,
        source_b: 0.01,
        source_c: 0.02,
    }
    active_sources = 0
    max_active_sources = 0
    state_lock = threading.Lock()

    def fake_run_all_method_benchmark(**kwargs):
        nonlocal active_sources, max_active_sources
        with state_lock:
            active_sources += 1
            max_active_sources = max(max_active_sources, active_sources)
        try:
            source_file = kwargs["source_file"]
            root_output_dir = kwargs["root_output_dir"]
            assert kwargs["source_parallelism_effective"] == 2
            assert isinstance(source_file, Path)
            assert isinstance(root_output_dir, Path)
            time.sleep(delays[source_file])
            root_output_dir.mkdir(parents=True, exist_ok=True)
            report_md_path = root_output_dir / "all_method_benchmark_report.md"
            report_md_path.write_text("ok", encoding="utf-8")
            report_payload = {
                "successful_variants": 1,
                "failed_variants": 0,
                "winner_by_f1": {"precision": 0.9, "recall": 0.8, "f1": 0.85},
                "timing_summary": {
                    "source_wall_seconds": delays[source_file],
                    "config_total_seconds": delays[source_file],
                    "slowest_config_dir": "config_001",
                    "slowest_config_seconds": delays[source_file],
                },
                "scheduler": {
                    "mode": "smart",
                    "split_phase_slots": 2,
                    "smart_tail_buffer_slots": 2,
                    "effective_inflight_pipelines": 4,
                    "heavy_slot_capacity_seconds": 1.0,
                    "heavy_slot_busy_seconds": 1.0,
                    "idle_gap_seconds": 0.0,
                    "avg_wing_backlog": 1.0,
                    "max_wing_backlog": 2,
                    "max_active_pipelines_observed": 4,
                },
            }
            report_md_path.with_suffix(".json").write_text(
                json.dumps(report_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return report_md_path
        finally:
            with state_lock:
                active_sources -= 1

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        max_parallel_sources=2,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
    )

    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["source_parallelism_configured"] == 2
    assert payload["source_parallelism_effective"] == 2
    assert payload["source_schedule_strategy"] == cli.ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR
    assert payload["source_job_count_planned"] == 3
    assert len(payload["source_schedule_plan"]) == 3
    assert max_active_sources <= 2
    assert max_active_sources >= 2
    assert [row["source_file_name"] for row in payload["sources"]] == [
        source_a.name,
        source_b.name,
        source_c.name,
    ]
    assert all(row["source_shard_total"] == 1 for row in payload["sources"])

def test_run_all_method_benchmark_multi_source_shards_source_and_reuses_cache_override(
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
    source = tmp_path / "heavy-source.epub"
    source.write_text("x", encoding="utf-8")
    gold = tmp_path / "gold-heavy" / "exports" / "freeform_span_labels.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold,
                source_file=source,
                source_file_name=source.name,
                gold_display="gold-heavy",
            ),
            variants,
        )
    ]

    monkeypatch.setattr(
        cli,
        "_estimate_all_method_source_cost",
        lambda **_kwargs: cli._AllMethodSourceEstimate(
            estimated_seconds=3600.0,
            estimate_basis="test",
            canonical_text_chars=0,
            variant_count=6,
        ),
    )

    cache_overrides: list[Path] = []

    def fake_run_all_method_benchmark(**kwargs):
        cache_override = kwargs["canonical_alignment_cache_dir_override"]
        assert isinstance(cache_override, Path)
        cache_overrides.append(cache_override)
        shard_variants = kwargs["variants"]
        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        variant_count = len(shard_variants)
        f1 = 0.5 + (variant_count * 0.05)
        report_payload = {
            "successful_variants": variant_count,
            "failed_variants": 0,
            "winner_by_f1": {"precision": f1, "recall": f1, "f1": f1},
            "timing_summary": {
                "source_wall_seconds": float(variant_count),
                "config_total_seconds": float(variant_count),
                "slowest_config_dir": "config_001",
                "slowest_config_seconds": float(variant_count),
            },
            "scheduler": {
                "mode": "smart",
                "split_phase_slots": 2,
                "smart_tail_buffer_slots": 2,
                "effective_inflight_pipelines": 4,
                "heavy_slot_capacity_seconds": 1.0,
                "heavy_slot_busy_seconds": 1.0,
                "idle_gap_seconds": 0.0,
                "avg_wing_backlog": 1.0,
                "max_wing_backlog": 2,
                "max_active_pipelines_observed": 4,
            },
        }
        report_md_path.with_suffix(".json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        source_scheduling="discovery",
        source_shard_threshold_seconds=1000.0,
        source_shard_max_parts=3,
        source_shard_min_variants=2,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
    )

    assert len(cache_overrides) == 3
    assert len({path.as_posix() for path in cache_overrides}) == 1
    payload = json.loads(report_md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["source_job_count_planned"] == 3
    assert payload["source_schedule_strategy"] == "discovery"
    assert len(payload["sources"]) == 1
    source_row = payload["sources"][0]
    assert source_row["status"] == "ok"
    assert source_row["source_shard_total"] == 3
    assert source_row["variant_count_planned"] == 6
    assert source_row["variant_count_successful"] == 6
    assert len(source_row["source_shards"]) == 3

def test_run_all_method_benchmark_multi_source_batches_dashboard_refresh_when_parallel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = _benchmark_test_run_settings()
    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=base_settings,
        dimensions={"epub_extractor": "unstructured"},
    )
    source_a = tmp_path / "book-a.epub"
    source_b = tmp_path / "book-b.epub"
    source_a.write_text("x", encoding="utf-8")
    source_b.write_text("x", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_a,
                source_file=source_a,
                source_file_name=source_a.name,
                gold_display="gold-a",
            ),
            [variant],
        ),
        (
            cli.AllMethodTarget(
                gold_spans_path=gold_b,
                source_file=source_b,
                source_file_name=source_b.name,
                gold_display="gold-b",
            ),
            [variant],
        ),
    ]

    per_source_refresh_values: list[bool] = []
    batch_refresh_calls: list[dict[str, object]] = []
    dashboard_output_root = tmp_path / "dashboard-output-root"

    def fake_run_all_method_benchmark(**kwargs):
        per_source_refresh_values.append(bool(kwargs["refresh_dashboard_after_source"]))
        assert kwargs["source_parallelism_effective"] == 2
        root_output_dir = kwargs["root_output_dir"]
        root_output_dir.mkdir(parents=True, exist_ok=True)
        report_md_path = root_output_dir / "all_method_benchmark_report.md"
        report_md_path.write_text("ok", encoding="utf-8")
        report_payload = {
            "successful_variants": 1,
            "failed_variants": 0,
            "winner_by_f1": {"precision": 0.9, "recall": 0.8, "f1": 0.85},
            "timing_summary": {
                "source_wall_seconds": 1.0,
                "config_total_seconds": 1.0,
                "slowest_config_dir": "config_001",
                "slowest_config_seconds": 1.0,
            },
            "scheduler": {
                "mode": "smart",
                "split_phase_slots": 2,
                "smart_tail_buffer_slots": 2,
                "effective_inflight_pipelines": 4,
                "heavy_slot_capacity_seconds": 1.0,
                "heavy_slot_busy_seconds": 1.0,
                "idle_gap_seconds": 0.0,
                "avg_wing_backlog": 1.0,
                "max_wing_backlog": 2,
                "max_active_pipelines_observed": 4,
            },
        }
        report_md_path.with_suffix(".json").write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark", fake_run_all_method_benchmark)
    monkeypatch.setattr(
        cli,
        "_refresh_dashboard_after_history_write",
        lambda **kwargs: batch_refresh_calls.append(kwargs),
    )

    cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        max_parallel_sources=2,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
        dashboard_output_root=dashboard_output_root,
    )

    assert per_source_refresh_values == [False, False]
    assert len(batch_refresh_calls) == 1
    assert batch_refresh_calls[0]["reason"] == "all-method benchmark multi-source batch append"
    assert batch_refresh_calls[0]["output_root"] == dashboard_output_root
    assert (
        batch_refresh_calls[0]["dashboard_out_dir"]
        == cli.history_root_for_output(dashboard_output_root) / "dashboard"
    )

def test_run_all_method_benchmark_multi_source_defaults_to_global_scheduler_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    gold = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold,
                source_file=source,
                source_file_name=source.name,
                gold_display="gold",
            ),
            [
                cli.AllMethodVariant(
                    slug="extractor_unstructured",
                    run_settings=_benchmark_test_run_settings(),
                    dimensions={"epub_extractor": "unstructured"},
                )
            ],
        )
    ]

    expected_report_path = tmp_path / "global.md"
    captured: dict[str, object] = {}

    def fake_global_queue(**kwargs):
        captured.update(kwargs)
        return expected_report_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark_global_queue", fake_global_queue)
    monkeypatch.setattr(
        cli,
        "_run_all_method_benchmark_multi_source_legacy",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Default scheduler scope should dispatch to global queue.")
        ),
    )

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        dashboard_output_root=tmp_path / "dashboard-root",
    )

    assert report_md_path == expected_report_path
    assert captured["target_variants"] == target_variants
    assert captured["dashboard_output_root"] == tmp_path / "dashboard-root"

def test_run_all_method_benchmark_multi_source_dispatches_legacy_scheduler_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    gold = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("{}\n", encoding="utf-8")
    target_variants = [
        (
            cli.AllMethodTarget(
                gold_spans_path=gold,
                source_file=source,
                source_file_name=source.name,
                gold_display="gold",
            ),
            [
                cli.AllMethodVariant(
                    slug="extractor_unstructured",
                    run_settings=_benchmark_test_run_settings(),
                    dimensions={"epub_extractor": "unstructured"},
                )
            ],
        )
    ]

    expected_report_path = tmp_path / "legacy.md"
    captured: dict[str, object] = {}

    def fake_legacy(**kwargs):
        captured.update(kwargs)
        return expected_report_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark_multi_source_legacy", fake_legacy)
    monkeypatch.setattr(
        cli,
        "_run_all_method_benchmark_global_queue",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Legacy scheduler scope should not dispatch to global queue.")
        ),
    )

    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=False,
        root_output_dir=tmp_path / "all-method-root",
        processed_output_root=tmp_path / "processed-root",
        overlap_threshold=0.5,
        force_source_match=False,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_LEGACY,
        dashboard_output_root=tmp_path / "dashboard-root",
    )

    assert report_md_path == expected_report_path
    assert captured["target_variants"] == target_variants
    assert captured["dashboard_output_root"] == tmp_path / "dashboard-root"

def test_interactive_all_method_benchmark_uses_timestamped_output_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "Book Name.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    benchmark_eval_output = tmp_path / "golden" / "2026-02-24_01.02.03"
    processed_output_root = tmp_path / "output"
    source_slug = cli.slugify_name(source_file.stem)

    monkeypatch.setattr(
        cli,
        "_resolve_benchmark_gold_and_source",
        lambda **_kwargs: (gold_spans, source_file),
    )
    scope_messages: list[str] = []

    def fake_menu_select(message: str, **_kwargs):
        scope_messages.append(message)
        return "single"

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(
        cli,
        "_build_all_method_variants",
        lambda **_kwargs: [
            cli.AllMethodVariant(
                slug="extractor_unstructured",
                run_settings=_benchmark_test_run_settings(),
                dimensions={"epub_extractor": "unstructured"},
            )
        ],
    )
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_codex_choice",
        lambda _include_requested: (False, None),
    )

    confirm_answers = iter([False, False, True])
    monkeypatch.setattr(
        cli,
        "_prompt_confirm",
        lambda *_args, **_kwargs: next(confirm_answers),
    )

    captured: dict[str, object] = {}
    report_md_path = (
        benchmark_eval_output
        / "all-method-benchmark"
        / source_slug
        / "all_method_benchmark_report.md"
    )

    def fake_run_all_method_benchmark(**kwargs):
        captured.update(kwargs)
        return report_md_path

    monkeypatch.setattr(
        cli,
        "_run_all_method_benchmark",
        fake_run_all_method_benchmark,
    )

    cli._interactive_all_method_benchmark(
        selected_benchmark_settings=_benchmark_test_run_settings(),
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert scope_messages == ["Select all method benchmark scope:"]
    assert captured["processed_output_root"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "all-method-benchmark"
        / source_slug
    )
    assert captured["dashboard_output_root"] == processed_output_root

def test_interactive_all_method_benchmark_all_matched_scope_routes_to_multi_source_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "Book Name.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    benchmark_eval_output = tmp_path / "golden" / "2026-02-24_01.02.03"
    processed_output_root = tmp_path / "output"

    captured_scope_messages: list[str] = []

    def fake_menu_select(message: str, **_kwargs):
        captured_scope_messages.append(message)
        return "all_matched"

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(
        cli,
        "_resolve_benchmark_gold_and_source",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("All-matched scope should not use single-pair resolver.")
        ),
    )
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_targets",
        lambda _output_dir: (
            [
                cli.AllMethodTarget(
                    gold_spans_path=gold_spans,
                    source_file=source_file,
                    source_file_name=source_file.name,
                    gold_display="gold",
                )
            ],
            [],
        ),
    )

    variant = cli.AllMethodVariant(
        slug="extractor_unstructured",
        run_settings=_benchmark_test_run_settings(),
        dimensions={"epub_extractor": "unstructured"},
    )

    def fake_build_target_variants(*, targets, **_kwargs):
        return [(target, [variant]) for target in targets]

    monkeypatch.setattr(cli, "_build_all_method_target_variants", fake_build_target_variants)
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_codex_choice",
        lambda _include_requested: (False, None),
    )
    confirm_answers = iter([False, False, True])
    monkeypatch.setattr(
        cli,
        "_prompt_confirm",
        lambda *_args, **_kwargs: next(confirm_answers),
    )

    captured: dict[str, object] = {}
    report_md_path = (
        benchmark_eval_output
        / "all-method-benchmark"
        / "all_method_benchmark_multi_source_report.md"
    )

    def fake_run_multi_source(**kwargs):
        captured.update(kwargs)
        return report_md_path

    monkeypatch.setattr(cli, "_run_all_method_benchmark_multi_source", fake_run_multi_source)
    monkeypatch.setattr(
        cli,
        "_run_all_method_benchmark",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("All-matched scope should not call single-source runner.")
        ),
    )

    cli._interactive_all_method_benchmark(
        selected_benchmark_settings=_benchmark_test_run_settings(),
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert captured_scope_messages == ["Select all method benchmark scope:"]
    assert "target_variants" in captured
    assert captured["processed_output_root"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "all-method-benchmark"
    )
    assert captured["dashboard_output_root"] == processed_output_root
