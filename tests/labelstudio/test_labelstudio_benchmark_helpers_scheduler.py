from __future__ import annotations

import tests.labelstudio.test_labelstudio_benchmark_helpers as _base

# Reuse shared imports/helpers from the base benchmark helpers module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_resolve_all_method_targets_uses_segment_manifest_when_gold_rows_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "data" / "input" / "book.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x", encoding="utf-8")

    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("\n", encoding="utf-8")
    (exports / "freeform_segment_manifest.jsonl").write_text(
        json.dumps({"segment_id": "s1", "source_file": "book.epub"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "_discover_freeform_gold_exports", lambda *_: [gold_path])
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [source])

    matched, unmatched = cli._resolve_all_method_targets(tmp_path)

    assert len(matched) == 1
    assert matched[0].gold_spans_path == gold_path
    assert matched[0].source_file == source
    assert unmatched == []


def test_resolve_all_method_targets_returns_matched_and_unmatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "data" / "input" / "book.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x", encoding="utf-8")

    matched_gold = tmp_path / "matched" / "exports" / "freeform_span_labels.jsonl"
    matched_gold.parent.mkdir(parents=True, exist_ok=True)
    matched_gold.write_text(
        json.dumps({"source_file": "book.epub", "label": "RECIPE_TITLE"}) + "\n",
        encoding="utf-8",
    )

    missing_hint_gold = tmp_path / "missing-hint" / "exports" / "freeform_span_labels.jsonl"
    missing_hint_gold.parent.mkdir(parents=True, exist_ok=True)
    missing_hint_gold.write_text("{}\n", encoding="utf-8")

    missing_input_gold = tmp_path / "missing-input" / "exports" / "freeform_span_labels.jsonl"
    missing_input_gold.parent.mkdir(parents=True, exist_ok=True)
    missing_input_gold.write_text(
        json.dumps({"source_file": "unknown.epub", "label": "RECIPE_TITLE"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_discover_freeform_gold_exports",
        lambda *_: [matched_gold, missing_hint_gold, missing_input_gold],
    )
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [source])

    matched, unmatched = cli._resolve_all_method_targets(tmp_path)

    assert [row.gold_spans_path for row in matched] == [matched_gold]
    assert [row.source_file for row in matched] == [source]
    assert len(unmatched) == 2
    assert "Missing source hint" in unmatched[0].reason
    assert unmatched[0].gold_spans_path == missing_hint_gold
    assert unmatched[0].source_hint is None
    assert "No importable file named `unknown.epub`" in unmatched[1].reason
    assert unmatched[1].gold_spans_path == missing_input_gold
    assert unmatched[1].source_hint == "unknown.epub"


def test_build_all_method_variants_epub_expected_count() -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.epub"),
        include_codex_farm=False,
    )
    assert len(variants) == 13
    assert len({variant.run_settings.stable_hash() for variant in variants}) == 13
    assert any("extractor_unstructured" in variant.slug for variant in variants)
    assert not any("extractor_markdown" in variant.slug for variant in variants)
    assert not any("extractor_markitdown" in variant.slug for variant in variants)


def test_build_all_method_variants_epub_includes_markdown_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.epub"),
        include_codex_farm=False,
        include_markdown_extractors=True,
    )
    assert len(variants) == 15
    assert len({variant.run_settings.stable_hash() for variant in variants}) == 15
    assert any("extractor_markdown" in variant.slug for variant in variants)
    assert any("extractor_markitdown" in variant.slug for variant in variants)


def test_build_all_method_variants_non_epub_single_variant() -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.pdf"),
        include_codex_farm=False,
    )
    assert len(variants) == 1
    assert variants[0].dimensions["source_extension"] == ".pdf"


def test_build_all_method_variants_include_multi_recipe_dimension_when_non_legacy() -> None:
    base_settings = cli.RunSettings.from_dict(
        {"multi_recipe_splitter": "rules_v1"},
        warn_context="test",
    )
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.pdf"),
        include_codex_farm=False,
    )

    assert len(variants) == 1
    assert variants[0].dimensions["multi_recipe_splitter"] == "rules_v1"
    assert "__multi_recipe_rules_v1" in variants[0].slug


def test_build_all_method_variants_html_webschema_policy_matrix() -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("page.html"),
        include_codex_farm=False,
    )

    assert len(variants) == 3
    assert {variant.dimensions["web_schema_policy"] for variant in variants} == {
        "prefer_schema",
        "schema_only",
        "heuristic_only",
    }


def test_build_all_method_variants_non_schema_json_single_variant(
    tmp_path: Path,
) -> None:
    source = tmp_path / "payload.json"
    source.write_text('{"kind":"not-a-recipe"}', encoding="utf-8")
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")

    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=source,
        include_codex_farm=False,
    )

    assert len(variants) == 1
    assert variants[0].dimensions["source_extension"] == ".json"


def test_build_all_method_variants_schema_json_webschema_policy_matrix(
    tmp_path: Path,
) -> None:
    source = tmp_path / "schema.json"
    source.write_text(
        json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "Recipe",
                "name": "Toast",
                "recipeIngredient": ["1 slice bread"],
                "recipeInstructions": ["Toast bread."],
            }
        ),
        encoding="utf-8",
    )
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")

    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=source,
        include_codex_farm=False,
    )

    assert len(variants) == 3
    assert {variant.dimensions["web_schema_policy"] for variant in variants} == {
        "prefer_schema",
        "schema_only",
        "heuristic_only",
    }


def test_resolve_all_method_codex_choice_when_requested() -> None:
    include_effective, warning = cli._resolve_all_method_codex_choice(True)
    assert include_effective is True
    assert warning is None


def test_build_all_method_variants_epub_includes_codex_farm_when_unlocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(cli.ALL_METHOD_CODEX_FARM_UNLOCK_ENV, "1")
    base_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="test",
    )
    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.epub"),
        include_codex_farm=True,
    )
    assert len(variants) == 26
    assert len({variant.run_settings.stable_hash() for variant in variants}) == 26
    assert any("__llm_recipe_codex_farm_3pass_v1" in variant.slug for variant in variants)


def test_build_all_method_variants_normalizes_ai_on_baselines_when_codex_enabled() -> None:
    base_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-farm-3pass-v1",
            "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
            "llm_tags_pipeline": "codex-farm-tags-v1",
            "line_role_pipeline": "codex-line-role-v1",
            "atomic_block_splitter": "atomic-v1",
        },
        warn_context="test",
    )

    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.epub"),
        include_codex_farm=True,
    )

    baseline_variants = [
        variant
        for variant in variants
        if "__llm_recipe_codex_farm_3pass_v1" not in variant.slug
    ]
    codex_variants = [
        variant
        for variant in variants
        if "__llm_recipe_codex_farm_3pass_v1" in variant.slug
    ]

    assert len(baseline_variants) == 13
    assert len(codex_variants) == 13
    assert {
        variant.run_settings.llm_recipe_pipeline.value for variant in baseline_variants
    } == {"off"}
    assert {
        variant.run_settings.llm_knowledge_pipeline.value for variant in baseline_variants
    } == {"off"}
    assert {
        variant.run_settings.llm_tags_pipeline.value for variant in baseline_variants
    } == {"off"}
    assert {
        variant.run_settings.line_role_pipeline.value for variant in baseline_variants
    } == {"deterministic-v1"}
    assert {
        variant.run_settings.atomic_block_splitter.value for variant in baseline_variants
    } == {"atomic-v1"}
    assert {
        variant.run_settings.llm_recipe_pipeline.value for variant in codex_variants
    } == {"codex-farm-3pass-v1"}
    assert {
        variant.run_settings.line_role_pipeline.value for variant in codex_variants
    } == {"codex-line-role-v1"}
    assert {
        variant.run_settings.llm_knowledge_pipeline.value for variant in codex_variants
    } == {"codex-farm-knowledge-v1"}
    assert {
        variant.run_settings.atomic_block_splitter.value for variant in codex_variants
    } == {"atomic-v1"}
    assert {variant.run_settings.epub_extractor.value for variant in baseline_variants} == {
        "beautifulsoup",
        "unstructured",
    }
    assert {
        variant.run_settings.epub_unstructured_html_parser_version.value
        for variant in baseline_variants
        if variant.run_settings.epub_extractor.value == "unstructured"
    } == {"v1", "v2"}


def test_build_all_method_variants_normalizes_ai_on_baselines_without_codex() -> None:
    base_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-farm-3pass-v1",
            "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
            "llm_tags_pipeline": "codex-farm-tags-v1",
            "line_role_pipeline": "codex-line-role-v1",
            "atomic_block_splitter": "atomic-v1",
        },
        warn_context="test",
    )

    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.epub"),
        include_codex_farm=False,
    )

    assert len(variants) == 13
    assert {
        variant.run_settings.llm_recipe_pipeline.value for variant in variants
    } == {"off"}
    assert {
        variant.run_settings.llm_knowledge_pipeline.value for variant in variants
    } == {"off"}
    assert {
        variant.run_settings.llm_tags_pipeline.value for variant in variants
    } == {"off"}
    assert {
        variant.run_settings.line_role_pipeline.value for variant in variants
    } == {"deterministic-v1"}
    assert {
        variant.run_settings.atomic_block_splitter.value for variant in variants
    } == {"atomic-v1"}


def test_resolve_all_method_markdown_extractors_requires_policy_unlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(cli.ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV, "1")
    monkeypatch.delenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", raising=False)
    assert cli._resolve_all_method_markdown_extractors_choice() is False

    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    assert cli._resolve_all_method_markdown_extractors_choice() is True


def test_resolve_all_method_scheduler_limits_defaults_raise_split_slots_to_four() -> None:
    inflight, split_slots = cli._resolve_all_method_scheduler_limits(total_variants=12)
    assert inflight == 4
    assert split_slots == 4


def test_resolve_all_method_source_parallelism_defaults_scale_with_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 17)
    resolved = cli._resolve_all_method_source_parallelism(total_sources=7)
    assert resolved == 4


def test_resolve_all_method_source_parallelism_invalid_override_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 8)
    resolved = cli._resolve_all_method_source_parallelism(
        total_sources=5,
        requested=0,
    )
    assert resolved == 2


def test_resolve_all_method_source_parallelism_requested_cap_respects_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 6)
    resolved = cli._resolve_all_method_source_parallelism(
        total_sources=10,
        requested=12,
    )
    assert resolved == 6


def test_resolve_all_method_canonical_alignment_cache_root_uses_shared_benchmark_root(
    tmp_path: Path,
) -> None:
    benchmark_root = tmp_path / "golden" / "benchmark-vs-golden"
    run_root = benchmark_root / "2026-02-27_17.54.41" / "all-method-benchmark"
    source_root = run_root / "seaandsmokecutdown"
    expected = benchmark_root / ".cache" / "canonical_alignment"

    assert cli._resolve_all_method_canonical_alignment_cache_root(
        root_output_dir=run_root
    ) == expected
    assert cli._resolve_all_method_canonical_alignment_cache_root(
        root_output_dir=source_root
    ) == expected


def test_resolve_all_method_canonical_alignment_cache_root_honors_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    override_root = tmp_path / "cache-override"
    monkeypatch.setenv(
        cli.ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV,
        str(override_root),
    )

    resolved = cli._resolve_all_method_canonical_alignment_cache_root(
        root_output_dir=tmp_path / "run" / "all-method-benchmark"
    )

    assert resolved == override_root


def test_plan_all_method_source_jobs_tail_pair_interleaves_heavy_and_light(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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

    monkeypatch.setattr(cli, "_estimate_all_method_source_cost", fake_estimate)

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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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

    monkeypatch.setattr(
        cli,
        "_estimate_all_method_source_cost",
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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

    monkeypatch.setattr(cli, "_estimate_all_method_source_cost", fake_estimate)

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


def test_run_all_method_benchmark_global_queue_interleaves_sharded_heavy_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
    settings = cli.RunSettings.from_dict({}, warn_context="test")
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
    monkeypatch.setattr(cli, "_system_total_memory_bytes", lambda: 64 * 1024 * 1024 * 1024)
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
    monkeypatch.setattr(cli, "_system_total_memory_bytes", lambda: 64 * 1024 * 1024 * 1024)
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
    monkeypatch.setattr(cli, "_system_total_memory_bytes", lambda: 8 * 1024 * 1024 * 1024)

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


def test_run_all_method_evaluate_prediction_record_once_preserves_fail_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_error = "Unable to load prediction record from /tmp/preds.jsonl: malformed record"

    def fake_labelstudio_benchmark(**_kwargs):
        cli._fail(expected_error)

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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
    settings = cli.RunSettings.from_dict({}, warn_context="test")
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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
        run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

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

    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variant_a = cli.AllMethodVariant(
        slug="reuse-workers-a",
        run_settings=cli.RunSettings.from_dict(
            {
                **base_settings.to_run_config_dict(),
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
                **base_settings.to_run_config_dict(),
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

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

    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    variant_a = cli.AllMethodVariant(
        slug="reuse-shape-a",
        run_settings=cli.RunSettings.from_dict(
            {
                **base_settings.to_run_config_dict(),
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
                **base_settings.to_run_config_dict(),
                "line_role_pipeline": "deterministic-v1",
            },
            warn_context="test",
        ),
        dimensions={"line_role_pipeline": "deterministic-v1"},
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

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
        run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

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
        run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

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
            "multi_recipe_trace": True,
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
            "p6_emit_metadata_debug": True,
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

    def fake_labelstudio_benchmark(**kwargs):
        captured_kwargs.update(kwargs)
        _write_fake_all_method_prediction_phase_artifacts(
            kwargs=kwargs,
            source_file=source_file,
            extractor=str(kwargs.get("epub_extractor") or "unstructured"),
        )

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

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
        execution_mode=cli.BENCHMARK_EXECUTION_MODE_PREDICT_ONLY,
        no_upload=True,
        write_markdown=False,
        write_label_studio_tasks=False,
        sequence_matcher_override=settings.benchmark_sequence_matcher,
    )
    expected_kwargs.update(
        {
            "gold_spans": gold_spans,
            "source_file": source_file,
            "predictions_out": root_output_dir / config_dir_name / "prediction-records.jsonl",
            "overlap_threshold": 0.5,
            "force_source_match": False,
            "alignment_cache_dir": None,
        }
    )

    for key, value in expected_kwargs.items():
        assert key in captured_kwargs
        assert captured_kwargs[key] == value


def test_run_all_method_benchmark_writes_ranked_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    markdown_settings = cli.RunSettings.from_dict(
        {
            **base_settings.to_run_config_dict(),
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

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
    assert payload["winner_by_f1"]["run_config_hash"] == "hash-markdown"
    assert payload["timing_summary"]["source_wall_seconds"] >= 0.0
    assert payload["timing_summary"]["config_total_seconds"] == pytest.approx(13.0)
    assert payload["timing_summary"]["slowest_config_dir"] == payload["winner_by_f1"]["config_dir"]
    assert payload["variants"][0]["rank"] == 1
    assert payload["variants"][0]["run_config_hash"] == "hash-markdown"
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
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
            if str(kwargs.get("execution_mode") or "") == "predict-only":
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
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
    assert max_active <= 3
    assert max_active >= 2
    assert payload["successful_variants"] == 4
    assert payload["failed_variants"] == 0
    assert payload["winner_by_f1"]["run_config_hash"] == "hash-markitdown"
    ranked_hashes = [
        row["run_config_hash"]
        for row in payload["variants"]
        if row.get("status") == "ok"
    ]
    assert ranked_hashes == [
        "hash-markitdown",
        "hash-markdown",
        "hash-beautifulsoup",
        "hash-unstructured",
    ]


def test_run_all_method_benchmark_marks_timeout_and_finishes_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS", "1")
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
            call_counts[extractor] = call_counts.get(extractor, 0) + 1
        if (
            str(kwargs.get("execution_mode") or "") == "predict-only"
            and extractor == "beautifulsoup"
            and call_counts[extractor] == 1
        ):
            raise RuntimeError("synthetic transient failure")

        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
    monkeypatch.setattr(cli, "ProcessPoolExecutor", ThreadPoolExecutor)

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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
    base_payload = base_settings.to_run_config_dict()
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

    monkeypatch.setattr(cli, "ProcessPoolExecutor", BrokenExecutor)

    call_count = 0

    def fake_labelstudio_benchmark(**kwargs):
        nonlocal call_count
        extractor = str(kwargs.get("epub_extractor") or "")
        if str(kwargs.get("execution_mode") or "") == "predict-only":
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
    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)
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


def test_run_all_method_benchmark_multi_source_writes_combined_summary_with_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
    base_settings = cli.RunSettings.from_dict({}, warn_context="test")
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
                    run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
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
                    run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
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
                run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
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
        selected_benchmark_settings=cli.RunSettings.from_dict({}, warn_context="test"),
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
        run_settings=cli.RunSettings.from_dict({}, warn_context="test"),
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
        selected_benchmark_settings=cli.RunSettings.from_dict({}, warn_context="test"),
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
