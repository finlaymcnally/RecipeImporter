from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
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
    base_settings = _benchmark_test_run_settings()
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
    base_settings = _benchmark_test_run_settings()
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
    base_settings = _benchmark_test_run_settings()
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
    assert variants[0].slug == "source_pdf"

def test_build_all_method_variants_html_webschema_policy_matrix() -> None:
    base_settings = _benchmark_test_run_settings()
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
    base_settings = _benchmark_test_run_settings()

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
    base_settings = _benchmark_test_run_settings()

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
) -> None:
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
    assert any("__llm_recipe_codex_recipe_shard_v1" in variant.slug for variant in variants)

def test_build_all_method_variants_normalizes_ai_on_baselines_when_codex_enabled() -> None:
    base_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "line_role_pipeline": "codex-line-role-shard-v1",
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
        if "__llm_recipe_codex_recipe_shard_v1" not in variant.slug
    ]
    codex_variants = [
        variant
        for variant in variants
        if "__llm_recipe_codex_recipe_shard_v1" in variant.slug
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
        variant.run_settings.line_role_pipeline.value for variant in baseline_variants
    } == {"off"}
    assert {
        variant.run_settings.atomic_block_splitter.value for variant in baseline_variants
    } == {"off"}
    assert {
        variant.run_settings.llm_recipe_pipeline.value for variant in codex_variants
    } == {"codex-recipe-shard-v1"}
    assert {
        variant.run_settings.line_role_pipeline.value for variant in codex_variants
    } == {"codex-line-role-shard-v1"}
    assert {
        variant.run_settings.llm_knowledge_pipeline.value for variant in codex_variants
    } == {"codex-knowledge-shard-v1"}
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
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "line_role_pipeline": "codex-line-role-shard-v1",
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
        variant.run_settings.line_role_pipeline.value for variant in variants
    } == {"off"}
    assert {
        variant.run_settings.atomic_block_splitter.value for variant in variants
    } == {"off"}


def test_build_all_method_variants_respects_selected_codex_surfaces() -> None:
    base_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "llm_knowledge_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="test baseline codex surfaces",
    )
    selected_codex_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "llm_knowledge_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="test selected codex surfaces",
    )

    variants = cli._build_all_method_variants(
        base_settings=base_settings,
        source_file=Path("book.pdf"),
        include_codex_farm=True,
        codex_variant_settings=selected_codex_settings,
    )

    baseline_variants = [
        variant
        for variant in variants
        if "__llm_recipe_codex_recipe_shard_v1" not in variant.slug
    ]
    codex_variants = [
        variant
        for variant in variants
        if "__llm_recipe_codex_recipe_shard_v1" in variant.slug
    ]

    assert len(baseline_variants) == 1
    assert len(codex_variants) == 1
    assert codex_variants[0].run_settings.llm_recipe_pipeline.value == (
        "codex-recipe-shard-v1"
    )
    assert codex_variants[0].run_settings.line_role_pipeline.value == "off"
    assert codex_variants[0].run_settings.llm_knowledge_pipeline.value == "off"
    assert "__line_role_codex_line_role_v1" not in codex_variants[0].slug
    assert "__llm_knowledge_codex_farm_knowledge_v1" not in codex_variants[0].slug


def test_interactive_all_method_benchmark_uses_shared_codex_surface_menu(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "DinnerFor2CUTDOWN.epub"
    source.write_text("dummy", encoding="utf-8")
    gold_path = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold_path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        cli,
        "_resolve_benchmark_gold_and_source",
        lambda **_kwargs: (gold_path, source),
    )
    monkeypatch.setattr(cli, "_resolve_all_method_markdown_extractors_choice", lambda: False)
    monkeypatch.setattr(cli, "_all_method_optional_module_available", lambda *_: True)
    monkeypatch.setattr(cli, "_ensure_codex_farm_cmd_available", lambda *_args, **_kwargs: None)

    menu_answers = iter(["single"])

    def _fake_menu_select(prompt: str, *_args, **_kwargs):
        if prompt == "Select all method benchmark scope:":
            return next(menu_answers)
        pytest.fail(f"Unexpected menu prompt: {prompt}")

    monkeypatch.setattr(cli, "_menu_select", _fake_menu_select)

    prompt_messages: list[str] = []

    def _fake_prompt_confirm(message: str, *args, **kwargs):
        prompt_messages.append(message)
        if message.startswith("Try deterministic option sweeps too?"):
            return False
        if message.startswith("Proceed with "):
            return False
        if message == "Include Codex Farm permutations?":
            pytest.fail("should use shared CodexFarm process menu")
        pytest.fail(f"Unexpected confirm prompt: {message}")

    monkeypatch.setattr(cli, "_prompt_confirm", _fake_prompt_confirm)

    shared_surface_calls: list[tuple[str, ...]] = []

    def _fake_choose_interactive_codex_surfaces(**kwargs):
        shared_surface_calls.append(tuple(kwargs["surface_options"]))
        return cli.RunSettings.from_dict(
            {
                **kwargs["selected_settings"].model_dump(
                    mode="json", exclude_none=True
                ),
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "llm_knowledge_pipeline": "off",
                "line_role_pipeline": "off",
                "atomic_block_splitter": "off",
            },
            warn_context="test all-method shared codex menu",
        )

    ai_settings_calls: list[dict[str, object]] = []

    def _fake_choose_codex_ai_settings(**kwargs):
        ai_settings_calls.append(dict(kwargs))
        return kwargs["selected_settings"]

    monkeypatch.setattr(
        cli,
        "choose_interactive_codex_surfaces",
        _fake_choose_interactive_codex_surfaces,
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "choose_codex_ai_settings",
        _fake_choose_codex_ai_settings,
        raising=False,
    )

    def _fake_build_all_method_target_variants(**kwargs):
        target = kwargs["targets"][0]
        assert kwargs["include_codex_farm"] is False or kwargs[
            "codex_variant_settings"
        ] is not None
        return [
            (
                target,
                [
                    cli.AllMethodVariant(
                        slug="variant",
                        run_settings=_benchmark_test_run_settings(),
                        dimensions={},
                    )
                ],
            )
        ]

    monkeypatch.setattr(cli, "_build_all_method_target_variants", _fake_build_all_method_target_variants)

    cli._interactive_all_method_benchmark(
        selected_benchmark_settings=_benchmark_test_run_settings(
            {"llm_recipe_pipeline": "off"}
        ),
        benchmark_eval_output=tmp_path / "golden" / "2026-03-16_00.00.00",
        processed_output_root=tmp_path / "processed",
    )

    assert shared_surface_calls == [("recipe", "line_role", "knowledge")]
    assert len(ai_settings_calls) == 1
    assert "Include Codex Farm permutations?" not in prompt_messages

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
