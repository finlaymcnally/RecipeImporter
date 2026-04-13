from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_single_book_module_binds_cross_owner_helpers() -> None:
    assert callable(bench_single_book._all_method_apply_baseline_contract)
    assert callable(bench_single_book._all_method_apply_codex_contract_from_baseline)
    assert (
        bench_single_book._resolve_benchmark_gold_and_source
        is bench_all_method._resolve_benchmark_gold_and_source
    )
    assert callable(bench_single_book._normalize_single_book_split_cache_mode)
    assert callable(bench_single_book._build_single_book_split_cache_key)
    assert callable(bench_single_book.resolve_or_build_deterministic_prep_bundle)
    assert callable(bench_single_book.build_shard_recommendations_from_prep_bundle)


def test_labelstudio_benchmark_command_accepts_transport_kwargs_from_run_settings() -> None:
    signature = inspect.signature(bench_single_book._labelstudio_benchmark_command())

    assert "recipe_codex_exec_style" in signature.parameters
    assert "line_role_codex_exec_style" in signature.parameters
    assert "knowledge_codex_exec_style" in signature.parameters
    assert "knowledge_inline_repair_transcript_mode" in signature.parameters


def test_build_single_book_interactive_shard_recommendations_reads_preview_phase_plans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("book", encoding="utf-8")
    processed_output_root = tmp_path / "output"
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "recipe_prompt_target_count": 5,
            "line_role_prompt_target_count": 5,
            "knowledge_prompt_target_count": 5,
        },
        warn_context="test single-book shard recommendations",
    )
    captured_bundle_kwargs: dict[str, object] = {}
    captured_recommendation_kwargs: dict[str, object] = {}
    prep_bundle = SimpleNamespace(
        manifest_path=tmp_path / "bundle" / "manifest.json",
        prep_key="prep-key-123",
    )
    _patch_cli_attr(
        monkeypatch,
        "resolve_or_build_deterministic_prep_bundle",
        lambda **kwargs: (
            captured_bundle_kwargs.update(kwargs) or prep_bundle
        ),
    )
    _patch_cli_attr(
        monkeypatch,
        "build_shard_recommendations_from_prep_bundle",
        lambda **kwargs: (
            captured_recommendation_kwargs.update(kwargs)
            or {
                "line_role": {
                    "minimum_safe_shard_count": 4,
                    "binding_limit": "input",
                    "requested_shard_count": 5,
                    "budget_native_shard_count": 5,
                    "launch_shard_count": 5,
                },
                "recipe": {
                    "minimum_safe_shard_count": 3,
                    "binding_limit": "session_peak",
                    "requested_shard_count": 5,
                    "budget_native_shard_count": 5,
                    "launch_shard_count": 5,
                },
                "knowledge": {
                    "minimum_safe_shard_count": 2,
                    "binding_limit": "output",
                    "requested_shard_count": 5,
                    "budget_native_shard_count": 7,
                    "launch_shard_count": 5,
                    "planning_warnings": ["budget planning wanted 7 shards"],
                },
            }
        ),
    )

    recommendations = bench_single_book._build_single_book_interactive_shard_recommendations(
        source_file=source_file,
        selected_settings=selected_settings,
        processed_output_root=processed_output_root,
    )

    baseline_settings = captured_bundle_kwargs["run_settings"]
    assert isinstance(baseline_settings, cli.RunSettings)
    assert baseline_settings.llm_recipe_pipeline.value == "off"
    assert baseline_settings.line_role_pipeline.value == "off"
    assert baseline_settings.llm_knowledge_pipeline.value == "off"
    assert captured_bundle_kwargs["source_file"] == source_file
    assert captured_bundle_kwargs["processed_output_root"] == processed_output_root
    assert captured_recommendation_kwargs["prep_bundle"] is prep_bundle
    assert captured_recommendation_kwargs["selected_settings"] == selected_settings
    assert recommendations == {
        "line_role": {
            "minimum_safe_shard_count": 4,
            "binding_limit": "input",
            "requested_shard_count": 5,
            "budget_native_shard_count": 5,
            "launch_shard_count": 5,
        },
        "recipe": {
            "minimum_safe_shard_count": 3,
            "binding_limit": "session_peak",
            "requested_shard_count": 5,
            "budget_native_shard_count": 5,
            "launch_shard_count": 5,
        },
        "knowledge": {
            "minimum_safe_shard_count": 2,
            "binding_limit": "output",
            "requested_shard_count": 5,
            "budget_native_shard_count": 7,
            "launch_shard_count": 5,
            "planning_warnings": ["budget planning wanted 7 shards"],
        },
    }


def test_build_shard_recommendations_from_prep_bundle_exposes_context_and_book_kpis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import cookimport.staging.deterministic_prep as deterministic_prep
    from cookimport.staging.book_cache import preview_cache_manifest_path

    artifact_root = tmp_path / "prep-cache" / "prep-key-123"
    book_cache_root = tmp_path / "book-cache"
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "recipe_prompt_target_count": 5,
            "line_role_prompt_target_count": 5,
            "knowledge_prompt_target_count": 5,
        },
        warn_context="test deterministic prep shard recommendation KPIs",
    )
    preview_manifest_path = preview_cache_manifest_path(
        book_cache_root=book_cache_root,
        source_hash="hash-123",
        prep_key="prep-key-123",
        selected_settings=selected_settings,
    )
    preview_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    preview_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "codex_prompt_preview.v3",
                "phase_plans": {
                    "line_role": {
                        "shard_count": 5,
                        "requested_shard_count": 5,
                        "budget_native_shard_count": 5,
                        "launch_shard_count": 5,
                        "owned_id_count": 1245,
                        "owned_ids_per_shard": {"avg": 249.0},
                        "minimum_safe_shard_count": 4,
                        "binding_limit": "input",
                        "survivability": {
                            "current_shard_count": 5,
                            "totals": {
                                "estimated_input_tokens": 290_000,
                                "estimated_output_tokens": 42_000,
                                "estimated_followup_tokens": 21_000,
                                "estimated_peak_session_tokens": 353_000,
                                "owned_unit_count": 1245,
                            },
                            "worst_shard": {
                                "estimated_peak_session_tokens": 82_000,
                            },
                        },
                    },
                    "recipe_refine": {
                        "shard_count": 5,
                        "requested_shard_count": 5,
                        "budget_native_shard_count": 5,
                        "launch_shard_count": 5,
                        "owned_id_count": 27,
                        "owned_ids_per_shard": {"avg": 5.4},
                        "minimum_safe_shard_count": 3,
                        "binding_limit": "session_peak",
                        "survivability": {
                            "current_shard_count": 5,
                            "totals": {
                                "estimated_input_tokens": 210_000,
                                "estimated_output_tokens": 55_000,
                                "estimated_followup_tokens": 19_000,
                                "estimated_peak_session_tokens": 284_000,
                                "owned_unit_count": 27,
                            },
                            "worst_shard": {
                                "estimated_peak_session_tokens": 71_000,
                            },
                        },
                    },
                    "nonrecipe_finalize": {
                        "shard_count": 5,
                        "requested_shard_count": 5,
                        "budget_native_shard_count": 9,
                        "launch_shard_count": 5,
                        "owned_id_count": 38,
                        "owned_ids_per_shard": {"avg": 7.6},
                        "work_unit_label": "chars",
                        "work_unit_count": 62_000,
                        "work_units_per_shard": {"avg": 12_400.0},
                        "minimum_safe_shard_count": 2,
                        "binding_limit": "output",
                        "survivability": {
                            "current_shard_count": 5,
                            "totals": {
                                "estimated_input_tokens": 165_000,
                                "estimated_output_tokens": 61_000,
                                "estimated_followup_tokens": 61_000,
                                "estimated_peak_session_tokens": 287_000,
                                "owned_unit_count": 38,
                            },
                            "worst_shard": {
                                "estimated_peak_session_tokens": 74_000,
                            },
                        },
                    },
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        deterministic_prep,
        "load_recipe_boundary_result_from_deterministic_prep_bundle",
        lambda _prep_bundle: SimpleNamespace(
            extracted_bundle=SimpleNamespace(archive_blocks=[{}] * 312),
            label_first_result=SimpleNamespace(
                labeled_lines=[{}] * 1245,
                recipe_spans=[{}] * 27,
            ),
            recipe_owned_blocks=[{}] * 188,
            outside_recipe_blocks=[{}] * 124,
        ),
    )
    prep_bundle = deterministic_prep.DeterministicPrepBundleResult(
        prep_key="prep-key-123",
        source_file=tmp_path / "book.epub",
        source_hash="hash-123",
        workbook_slug="book",
        importer_name="epub",
        artifact_root=artifact_root,
        manifest_path=artifact_root / "deterministic_prep_bundle_manifest.json",
        processed_run_root=artifact_root / "processed-output" / "book",
        prediction_run_root=artifact_root / "prediction-run",
        conversion_result_path=artifact_root / "conversion_result.json",
        processed_report_path=None,
        stage_block_predictions_path=None,
        cache_hit=True,
        timing={},
        deterministic_settings={},
        book_cache_root=book_cache_root,
    )

    recommendations = deterministic_prep.build_shard_recommendations_from_prep_bundle(
        prep_bundle=prep_bundle,
        selected_settings=selected_settings,
    )

    assert recommendations["line_role"]["avg_input_tokens_per_shard"] == 58_000
    assert recommendations["line_role"]["avg_peak_session_tokens_per_shard"] == 70_600
    assert recommendations["line_role"]["owned_units_per_shard_avg"] == 249.0
    assert recommendations["line_role"]["owned_unit_label"] == "lines"
    assert recommendations["line_role"]["requested_shard_count"] == 5
    assert recommendations["recipe"]["owned_units_per_shard_avg"] == 5.4
    assert recommendations["recipe"]["owned_unit_label"] == "recipes"
    assert recommendations["recipe"]["launch_shard_count"] == 5
    assert recommendations["knowledge"]["avg_peak_session_tokens_per_shard"] == 57_400
    assert recommendations["knowledge"]["owned_units_per_shard_avg"] == 12_400.0
    assert recommendations["knowledge"]["owned_unit_label"] == "chars"
    assert recommendations["knowledge"]["budget_native_shard_count"] == 9
    assert recommendations["__book_summary__"] == {
        "block_count": 312,
        "line_count": 1245,
        "recipe_guess_count": 27,
        "recipe_owned_block_count": 188,
        "outside_recipe_block_count": 124,
        "knowledge_packet_count": 38,
    }


def test_build_shard_recommendations_from_prep_bundle_rebuilds_stale_preview_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import cookimport.staging.deterministic_prep as deterministic_prep
    from cookimport.staging.book_cache import preview_cache_manifest_path

    artifact_root = tmp_path / "prep-cache" / "prep-key-123"
    book_cache_root = tmp_path / "book-cache"
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "recipe_prompt_target_count": 5,
            "line_role_prompt_target_count": 5,
            "knowledge_prompt_target_count": 5,
        },
        warn_context="test stale preview manifest rebuild",
    )
    preview_manifest_path = preview_cache_manifest_path(
        book_cache_root=book_cache_root,
        source_hash="hash-123",
        prep_key="prep-key-123",
        selected_settings=selected_settings,
    )
    preview_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    preview_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "codex_prompt_preview.v2",
                "phase_plans": {
                    "line_role": {
                        "shard_count": 5,
                        "minimum_safe_shard_count": 4,
                        "binding_limit": "input",
                    }
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    rebuilt_manifest = {
        "schema_version": "codex_prompt_preview.v3",
        "phase_plans": {
            "line_role": {
                "shard_count": 5,
                "requested_shard_count": 5,
                "budget_native_shard_count": 5,
                "launch_shard_count": 5,
                "owned_id_count": 1245,
                "owned_ids_per_shard": {"avg": 249.0},
                "minimum_safe_shard_count": 4,
                "binding_limit": "input",
                "survivability": {
                    "current_shard_count": 5,
                    "totals": {
                        "estimated_input_tokens": 290_000,
                        "estimated_peak_session_tokens": 353_000,
                        "owned_unit_count": 1245,
                    },
                    "worst_shard": {
                        "estimated_peak_session_tokens": 82_000,
                    },
                },
            }
        },
    }
    generated_manifest_path = artifact_root / "prompt-preview" / "prompt_preview_manifest.json"
    generated_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    generated_manifest_path.write_text(
        json.dumps(rebuilt_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        deterministic_prep,
        "write_prompt_preview_for_existing_run",
        lambda **kwargs: generated_manifest_path,
    )
    monkeypatch.setattr(
        deterministic_prep,
        "load_recipe_boundary_result_from_deterministic_prep_bundle",
        lambda _prep_bundle: SimpleNamespace(
            extracted_bundle=SimpleNamespace(archive_blocks=[]),
            label_first_result=SimpleNamespace(
                labeled_lines=[],
                recipe_spans=[],
            ),
            recipe_owned_blocks=[],
            outside_recipe_blocks=[],
        ),
    )
    prep_bundle = deterministic_prep.DeterministicPrepBundleResult(
        prep_key="prep-key-123",
        source_file=tmp_path / "book.epub",
        source_hash="hash-123",
        workbook_slug="book",
        importer_name="epub",
        artifact_root=artifact_root,
        manifest_path=artifact_root / "deterministic_prep_bundle_manifest.json",
        processed_run_root=artifact_root / "processed-output" / "book",
        prediction_run_root=artifact_root / "prediction-run",
        conversion_result_path=artifact_root / "conversion_result.json",
        processed_report_path=None,
        stage_block_predictions_path=None,
        cache_hit=True,
        timing={},
        deterministic_settings={},
        book_cache_root=book_cache_root,
    )

    recommendations = deterministic_prep.build_shard_recommendations_from_prep_bundle(
        prep_bundle=prep_bundle,
        selected_settings=selected_settings,
    )

    assert recommendations["line_role"]["budget_native_shard_count"] == 5
    cached_manifest = json.loads(preview_manifest_path.read_text(encoding="utf-8"))
    assert cached_manifest["schema_version"] == "codex_prompt_preview.v3"


def test_deterministic_prep_key_ignores_llm_only_settings(tmp_path: Path) -> None:
    from cookimport.staging.import_session import build_deterministic_prep_key

    source_file = tmp_path / "book.epub"
    source_file.write_text("book", encoding="utf-8")
    shared_payload = {
        "epub_extractor": "unstructured",
        "multi_recipe_splitter": "rules_v1",
        "pdf_ocr_policy": "off",
    }
    baseline = cli.RunSettings.from_dict(
        {
            **shared_payload,
            "llm_recipe_pipeline": "off",
            "codex_farm_model": "gpt-5.4",
            "codex_farm_reasoning_effort": "high",
            "recipe_prompt_target_count": 4,
        },
        warn_context="test deterministic prep key baseline",
    )
    llm_only_changed = cli.RunSettings.from_dict(
        {
            **shared_payload,
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "codex_farm_model": "gpt-5.3-codex-spark",
            "codex_farm_reasoning_effort": "low",
            "recipe_prompt_target_count": 12,
            "knowledge_prompt_target_count": 9,
        },
        warn_context="test deterministic prep key llm-only changes",
    )

    baseline_key = build_deterministic_prep_key(
        source_file=source_file,
        source_hash="hash-123",
        run_settings=baseline,
    )
    llm_only_changed_key = build_deterministic_prep_key(
        source_file=source_file,
        source_hash="hash-123",
        run_settings=llm_only_changed,
    )

    assert baseline_key == llm_only_changed_key


def test_deterministic_prep_key_uses_source_hash_not_path(tmp_path: Path) -> None:
    from cookimport.core.reporting import compute_file_hash
    from cookimport.staging.import_session import build_deterministic_prep_key

    source_a = tmp_path / "book-a.epub"
    source_b = tmp_path / "nested" / "book-b.epub"
    source_b.parent.mkdir(parents=True, exist_ok=True)
    source_a.write_text("same book bytes", encoding="utf-8")
    source_b.write_text("same book bytes", encoding="utf-8")
    source_hash = compute_file_hash(source_a)
    settings = cli.RunSettings.from_dict(
        {
            "epub_extractor": "unstructured",
            "multi_recipe_splitter": "rules_v1",
        },
        warn_context="test deterministic prep content-addressed key",
    )

    key_a = build_deterministic_prep_key(
        source_file=source_a,
        source_hash=source_hash,
        run_settings=settings,
    )
    key_b = build_deterministic_prep_key(
        source_file=source_b,
        source_hash=source_hash,
        run_settings=settings,
    )

    assert key_a == key_b


def test_load_deterministic_prep_bundle_normalizes_legacy_manifest_workbook_slug(
    tmp_path: Path,
) -> None:
    import cookimport.staging.deterministic_prep as deterministic_prep

    artifact_root = tmp_path / "prep-cache" / "entry"
    processed_run_root = artifact_root / "processed-output" / "2026-04-04_22.27.40"
    normalized_slug = "saltfatacidheatcutdown"
    legacy_slug = "saltfatacidheatCUTDOWN"
    (processed_run_root / "raw" / "source" / normalized_slug).mkdir(parents=True, exist_ok=True)
    conversion_result_path = artifact_root / "conversion_result.json"
    conversion_result_path.parent.mkdir(parents=True, exist_ok=True)
    conversion_result_path.write_text("{}", encoding="utf-8")
    manifest_path = artifact_root / "deterministic_prep_bundle_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "deterministic_prep_bundle.v2",
                "prep_key": "prep-key",
                "source_file": str(tmp_path / "SaltFat.epub"),
                "source_hash": "hash-123",
                "workbook_slug": legacy_slug,
                "importer_name": "epub",
                "processed_run_root": str(processed_run_root),
                "prediction_run_root": str(artifact_root / "prediction-run"),
                "conversion_result_path": str(conversion_result_path),
                "timing": {},
                "deterministic_settings": {},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    bundle = deterministic_prep.load_deterministic_prep_bundle(manifest_path)

    assert bundle.workbook_slug == normalized_slug


def test_resolve_or_build_deterministic_prep_bundle_writes_slugified_workbook_slug(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import cookimport.staging.deterministic_prep as deterministic_prep

    source_file = tmp_path / "SaltFat.epub"
    source_file.write_text("book", encoding="utf-8")
    run_settings = cli.RunSettings.from_dict(
        {
            "epub_extractor": "unstructured",
            "multi_recipe_splitter": "rules_v1",
        },
        warn_context="test deterministic prep manifest workbook slug",
    )
    artifact_root = tmp_path / "book-cache"
    processed_run_root = (
        artifact_root
        / "deterministic-prep"
        / deterministic_prep.compute_file_hash(source_file)
        / deterministic_prep.build_deterministic_prep_key(
            source_file=source_file,
            source_hash=deterministic_prep.compute_file_hash(source_file),
            run_settings=run_settings,
        )
        / "processed-output"
        / "2026-04-04_22.27.40"
    )

    import cookimport.labelstudio.ingest_flows.prediction_run as prediction_run

    def _fake_generate_pred_run_artifacts(**_kwargs: object) -> dict[str, object]:
        processed_run_root.mkdir(parents=True, exist_ok=True)
        return {
            "processed_run_root": processed_run_root,
            "conversion_result": {},
            "book_id": "Salt Fat Acid Heat CUTDOWN",
            "importer_name": "epub",
            "run_root": processed_run_root.parent.parent / "prediction-run",
            "book_cache": {},
            "timing": {},
        }

    monkeypatch.setattr(
        prediction_run,
        "generate_pred_run_artifacts",
        _fake_generate_pred_run_artifacts,
    )

    bundle = deterministic_prep.resolve_or_build_deterministic_prep_bundle(
        source_file=source_file,
        run_settings=run_settings,
        processed_output_root=tmp_path / "ignored",
        book_cache_root=artifact_root,
    )

    assert bundle.workbook_slug == "salt_fat_acid_heat_cutdown"
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert manifest["workbook_slug"] == "salt_fat_acid_heat_cutdown"


def test_normalize_authoritative_labeled_line_row_accepts_stage_artifact_shapes() -> None:
    import cookimport.staging.deterministic_prep as deterministic_prep

    deterministic_row = deterministic_prep._normalize_authoritative_labeled_line_row(
        {
            "source_block_id": "b1",
            "source_block_index": 1,
            "atomic_index": 1,
            "text": "det row",
            "label": "NONRECIPE_CANDIDATE",
            "final_label": "NONRECIPE_EXCLUDE",
            "decided_by": "fallback",
            "reason_tags": ["x"],
            "escalation_reasons": ["y"],
        }
    )
    refined_row = deterministic_prep._normalize_authoritative_labeled_line_row(
        {
            "source_block_id": "b2",
            "source_block_index": 2,
            "atomic_index": 2,
            "text": "refined row",
            "deterministic_label": "NONRECIPE_CANDIDATE",
            "label": "NONRECIPE_EXCLUDE",
            "decided_by": "codex",
            "reason_tags": ["a"],
            "escalation_reasons": ["b"],
        }
    )

    assert deterministic_row.deterministic_label == "NONRECIPE_CANDIDATE"
    assert deterministic_row.final_label == "NONRECIPE_EXCLUDE"
    assert refined_row.deterministic_label == "NONRECIPE_CANDIDATE"
    assert refined_row.final_label == "NONRECIPE_EXCLUDE"


def test_load_recipe_boundary_result_from_deterministic_prep_bundle_prefers_source_model_indices(
    tmp_path: Path,
) -> None:
    import cookimport.staging.deterministic_prep as deterministic_prep
    from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate

    artifact_root = tmp_path / "prep-cache" / "entry"
    processed_run_root = artifact_root / "processed-output" / "2026-04-04_22.27.40"
    workbook_slug = "book"
    source_dir = processed_run_root / "raw" / "source" / workbook_slug
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "source_blocks.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "blockId": "b0",
                        "orderIndex": 0,
                        "text": "Toast",
                        "sourceText": "Toast",
                        "location": {},
                        "features": {},
                        "provenance": {},
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "blockId": "b1",
                        "orderIndex": 1,
                        "text": "1 slice bread",
                        "sourceText": "1 slice bread",
                        "location": {},
                        "features": {},
                        "provenance": {},
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "blockId": "b2",
                        "orderIndex": 2,
                        "text": "Toast the bread.",
                        "sourceText": "Toast the bread.",
                        "location": {},
                        "features": {},
                        "provenance": {},
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "source_support.json").write_text("[]\n", encoding="utf-8")

    raw_full_text_dir = processed_run_root / "raw" / "epub" / "hash-123"
    raw_full_text_dir.mkdir(parents=True, exist_ok=True)
    (raw_full_text_dir / "full_text.json").write_text(
        json.dumps(
            {
                "blocks": [
                    {"index": 100, "block_id": "b100", "text": "Wrong tail"},
                    {"index": 101, "block_id": "b101", "text": "Wrong tail 2"},
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    label_dir = processed_run_root / "label_deterministic" / workbook_slug
    label_dir.mkdir(parents=True, exist_ok=True)
    (label_dir / "labeled_lines.jsonl").write_text(
        json.dumps(
            {
                "source_block_id": "b0",
                "source_block_index": 0,
                "atomic_index": 0,
                "text": "Toast",
                "label": "RECIPE_TITLE",
                "final_label": "RECIPE_TITLE",
                "decided_by": "rule",
                "reason_tags": [],
                "escalation_reasons": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    boundary_dir = processed_run_root / "recipe_boundary" / workbook_slug
    boundary_dir.mkdir(parents=True, exist_ok=True)
    (boundary_dir / "authoritative_block_labels.json").write_text(
        json.dumps(
            {
                "block_labels": [
                    {
                        "source_block_id": "b0",
                        "source_block_index": 0,
                        "supporting_atomic_indices": [0],
                        "deterministic_label": "RECIPE_TITLE",
                        "final_label": "RECIPE_TITLE",
                        "decided_by": "rule",
                        "reason_tags": [],
                        "escalation_reasons": [],
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (boundary_dir / "recipe_spans.json").write_text(
        json.dumps(
            {
                "recipe_spans": [
                    {
                        "span_id": "recipe_span_0",
                        "start_block_index": 0,
                        "end_block_index": 2,
                        "block_indices": [0, 1, 2],
                        "source_block_ids": ["b0", "b1", "b2"],
                        "start_atomic_index": 0,
                        "end_atomic_index": 2,
                        "atomic_indices": [0, 1, 2],
                        "title_block_index": 0,
                        "title_atomic_index": 0,
                        "warnings": [],
                        "escalation_reasons": [],
                        "decision_notes": [],
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (boundary_dir / "span_decisions.json").write_text(
        json.dumps({"span_decisions": []}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    ownership_dir = processed_run_root / "recipe_authority" / workbook_slug
    ownership_dir.mkdir(parents=True, exist_ok=True)
    (ownership_dir / "recipe_block_ownership.json").write_text(
        json.dumps(
            {
                "ownership_mode": "recipe_boundary",
                "recipes": [
                    {
                        "recipe_id": "urn:recipe:test:toast",
                        "recipe_span_id": "recipe_span_0",
                        "owned_block_indices": [0, 1, 2],
                        "divested_block_indices": [],
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    conversion_result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
            )
        ],
        rawArtifacts=[],
        report=ConversionReport(),
        workbook=workbook_slug,
        workbookPath=str(tmp_path / "book.epub"),
        sourceBlocks=[
            {
                "blockId": "b0",
                "orderIndex": 0,
                "text": "Toast",
                "sourceText": "Toast",
                "location": {},
                "features": {},
                "provenance": {},
            },
            {
                "blockId": "b1",
                "orderIndex": 1,
                "text": "1 slice bread",
                "sourceText": "1 slice bread",
                "location": {},
                "features": {},
                "provenance": {},
            },
            {
                "blockId": "b2",
                "orderIndex": 2,
                "text": "Toast the bread.",
                "sourceText": "Toast the bread.",
                "location": {},
                "features": {},
                "provenance": {},
            },
        ],
    )
    conversion_result_path = artifact_root / "conversion_result.json"
    conversion_result_path.parent.mkdir(parents=True, exist_ok=True)
    conversion_result_path.write_text(
        json.dumps(conversion_result.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    prep_bundle = deterministic_prep.DeterministicPrepBundleResult(
        prep_key="prep-key",
        source_file=tmp_path / "book.epub",
        source_hash="hash-123",
        workbook_slug=workbook_slug,
        importer_name="epub",
        artifact_root=artifact_root,
        manifest_path=artifact_root / "deterministic_prep_bundle_manifest.json",
        processed_run_root=processed_run_root,
        prediction_run_root=artifact_root / "prediction-run",
        conversion_result_path=conversion_result_path,
        processed_report_path=None,
        stage_block_predictions_path=None,
        cache_hit=True,
        timing={},
        deterministic_settings={},
    )

    result = deterministic_prep.load_recipe_boundary_result_from_deterministic_prep_bundle(
        prep_bundle
    )

    assert [row["index"] for row in result.extracted_bundle.archive_blocks] == [0, 1, 2]
    assert result.recipe_ownership_result.owned_block_indices == [0, 1, 2]


def test_load_recipe_boundary_result_from_deterministic_prep_bundle_reads_line_role_authority_file(
    tmp_path: Path,
) -> None:
    import cookimport.staging.deterministic_prep as deterministic_prep
    from cookimport.core.models import ConversionReport, ConversionResult

    artifact_root = tmp_path / "prep-cache" / "entry"
    processed_run_root = artifact_root / "processed-output" / "2026-04-09_16.45.00"
    workbook_slug = "book"
    source_dir = processed_run_root / "raw" / "source" / workbook_slug
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "source_blocks.jsonl").write_text(
        json.dumps(
            {
                "blockId": "b0",
                "orderIndex": 0,
                "text": "Toast",
                "sourceText": "Toast",
                "location": {},
                "features": {},
                "provenance": {},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "source_support.json").write_text("[]\n", encoding="utf-8")
    line_role_dir = processed_run_root / "line-role-pipeline"
    line_role_dir.mkdir(parents=True, exist_ok=True)
    (line_role_dir / "authoritative_labeled_lines.jsonl").write_text(
        json.dumps(
            {
                "source_block_id": "b0",
                "source_block_index": 0,
                "atomic_index": 0,
                "text": "Toast",
                "deterministic_label": "NONRECIPE_CANDIDATE",
                "label": "RECIPE_TITLE",
                "decided_by": "codex",
                "reason_tags": [],
                "escalation_reasons": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    boundary_dir = processed_run_root / "recipe_boundary" / workbook_slug
    boundary_dir.mkdir(parents=True, exist_ok=True)
    (boundary_dir / "authoritative_block_labels.json").write_text(
        json.dumps(
            {
                "block_labels": [
                    {
                        "source_block_id": "b0",
                        "source_block_index": 0,
                        "supporting_atomic_indices": [0],
                        "deterministic_label": "NONRECIPE_CANDIDATE",
                        "final_label": "RECIPE_TITLE",
                        "decided_by": "codex",
                        "reason_tags": [],
                        "escalation_reasons": [],
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (boundary_dir / "recipe_spans.json").write_text(
        json.dumps(
            {
                "recipe_spans": [
                    {
                        "span_id": "span-1",
                        "start_block_index": 0,
                        "end_block_index": 0,
                        "block_indices": [0],
                        "source_block_ids": ["b0"],
                        "atomic_indices": [0],
                        "title_block_index": 0,
                        "title_atomic_index": 0,
                        "warnings": [],
                        "escalation_reasons": [],
                        "decision_notes": [],
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (boundary_dir / "span_decisions.json").write_text(
        json.dumps(
            {
                "span_decisions": [
                    {
                        "span_id": "span-1",
                        "decision": "accepted_recipe_span",
                        "rejection_reason": None,
                        "start_block_index": 0,
                        "end_block_index": 0,
                        "block_indices": [0],
                        "source_block_ids": ["b0"],
                        "atomic_indices": [0],
                        "title_block_index": 0,
                        "title_atomic_index": 0,
                        "warnings": [],
                        "escalation_reasons": [],
                        "decision_notes": [],
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    recipe_authority_dir = processed_run_root / "recipe_authority" / workbook_slug
    recipe_authority_dir.mkdir(parents=True, exist_ok=True)
    (recipe_authority_dir / "recipe_block_ownership.json").write_text(
        json.dumps(
            {
                "ownership_mode": "recipe_boundary",
                "recipes": [
                    {
                        "recipe_id": "urn:test:toast",
                        "recipe_span_id": "span-1",
                        "owned_block_indices": [0],
                        "divested_block_indices": [],
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    conversion_result_path = artifact_root / "conversion_result.json"
    conversion_result_path.parent.mkdir(parents=True, exist_ok=True)
    conversion_result_path.write_text(
        ConversionResult(
            recipes=[],
            report=ConversionReport(),
            sourceBlocks=[],
            rawArtifacts=[],
        ).model_dump_json(indent=2, by_alias=True),
        encoding="utf-8",
    )

    prep_bundle = deterministic_prep.DeterministicPrepBundleResult(
        prep_key="prep-key",
        source_file=tmp_path / "book.txt",
        source_hash="hash-123",
        workbook_slug=workbook_slug,
        importer_name="text",
        artifact_root=artifact_root,
        manifest_path=artifact_root / "deterministic_prep_bundle_manifest.json",
        processed_run_root=processed_run_root,
        prediction_run_root=artifact_root / "prediction-run",
        conversion_result_path=conversion_result_path,
        processed_report_path=None,
        stage_block_predictions_path=None,
        cache_hit=True,
        timing={},
        deterministic_settings={},
    )

    result = deterministic_prep.load_recipe_boundary_result_from_deterministic_prep_bundle(
        prep_bundle
    )

    assert result.label_first_result.authoritative_label_stage_key == "line_role"
    assert result.label_first_result.labeled_lines[0].final_label == "RECIPE_TITLE"
    assert result.label_first_result.labeled_lines[0].deterministic_label == "NONRECIPE_CANDIDATE"


def test_interactive_single_book_benchmark_reuses_prediction_artifacts_across_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("book", encoding="utf-8")
    gold = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("{}\n", encoding="utf-8")
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test single-book prediction reuse",
    )
    prep_bundle = SimpleNamespace(
        manifest_path=tmp_path / "prep-cache" / "bundle.json",
        prep_key="test-prep-bundle",
        cache_hit=True,
    )
    prep_bundle.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    prep_bundle.manifest_path.write_text("{}", encoding="utf-8")
    _patch_cli_attr(
        monkeypatch,
        "resolve_or_build_deterministic_prep_bundle",
        lambda **_kwargs: prep_bundle,
    )
    publisher, publication_capture = _make_lightweight_single_book_publisher()

    benchmark_calls: list[Path] = []

    def _fake_labelstudio_benchmark(**kwargs: object) -> None:
        eval_output_dir = Path(kwargs["eval_output_dir"])
        processed_output_dir = Path(kwargs["processed_output_dir"])
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        processed_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "prediction-records.jsonl").write_text("{}\n", encoding="utf-8")
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "source": {"path": str(kwargs["source_file"])},
                    "run_config": {},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (processed_output_dir / "processed-marker.txt").write_text(
            "processed",
            encoding="utf-8",
        )
        benchmark_calls.append(eval_output_dir)

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", _fake_labelstudio_benchmark)

    first_output = tmp_path / "golden" / "2026-04-04_23.10.00"
    second_output = tmp_path / "golden" / "2026-04-04_23.11.00"
    first_completed = bench_single_book._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=first_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
        preselected_gold_spans=gold,
        preselected_source_file=source,
        publisher=publisher,
    )
    second_completed = bench_single_book._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=second_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
        preselected_gold_spans=gold,
        preselected_source_file=source,
        publisher=publisher,
    )

    assert first_completed is True
    assert second_completed is True
    assert len(benchmark_calls) == 1
    second_eval_dir = second_output / "single-book-benchmark" / "book" / "vanilla"
    second_processed_dir = (
        processed_output_root / second_output.name / "single-book-benchmark" / "book" / "vanilla"
    )
    assert (second_eval_dir / "prediction-records.jsonl").exists()
    assert (second_processed_dir / "processed-marker.txt").exists()
    assert publication_capture["results"]


def test_preview_cache_key_ignores_model_only_changes(tmp_path: Path) -> None:
    from cookimport.staging.deterministic_prep import _preview_manifest_key

    del tmp_path
    baseline = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "recipe_prompt_target_count": 5,
            "line_role_prompt_target_count": 5,
            "knowledge_prompt_target_count": 5,
            "codex_farm_model": "gpt-5.4",
            "codex_farm_reasoning_effort": "high",
        },
        warn_context="test preview cache baseline",
    )
    model_only_changed = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "recipe_prompt_target_count": 5,
            "line_role_prompt_target_count": 5,
            "knowledge_prompt_target_count": 5,
            "codex_farm_model": "gpt-5.3-codex-spark",
            "codex_farm_reasoning_effort": "low",
        },
        warn_context="test preview cache model-only changes",
    )
    prompt_target_changed = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "recipe_prompt_target_count": 7,
            "line_role_prompt_target_count": 5,
            "knowledge_prompt_target_count": 5,
        },
        warn_context="test preview cache planning changes",
    )

    assert _preview_manifest_key(baseline) == _preview_manifest_key(model_only_changed)
    assert _preview_manifest_key(baseline) != _preview_manifest_key(prompt_target_changed)


def _run_single_book_codex_enabled_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "recipe_prompt_target_count": 10,
            "knowledge_prompt_target_count": 4,
            "line_role_prompt_target_count": 5,
        },
        warn_context="test codex-enabled",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    golden_root = tmp_path / "golden"
    processed_output_root = tmp_path / "output"
    source_file = tmp_path / "book.epub"
    source_file.write_text("book", encoding="utf-8")
    source_path = str(source_file)
    gold_spans = golden_root / "fixture" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    publisher, publication_capture = _make_lightweight_single_book_publisher()

    benchmark_calls: list[dict[str, object]] = []
    refresh_calls: list[dict[str, object]] = []
    prep_bundle_calls: list[dict[str, object]] = []
    prep_bundle = SimpleNamespace(
        manifest_path=tmp_path / "prep-cache" / "bundle.json",
        prep_key="prep-key-123",
        cache_hit=False,
    )

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        llm_pipeline = str(kwargs.get("llm_recipe_pipeline") or "").strip().lower()
        metrics = {
            "precision": 0.42 if llm_pipeline == "codex-recipe-shard-v1" else 0.39,
            "recall": 0.33 if llm_pipeline == "codex-recipe-shard-v1" else 0.30,
            "f1": 0.37 if llm_pipeline == "codex-recipe-shard-v1" else 0.34,
            "practical_precision": None,
            "practical_recall": None,
            "practical_f1": None,
        }
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps(metrics),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "source": {"path": source_path},
                    "run_config": {
                        "llm_recipe_pipeline": llm_pipeline,
                        "codex_farm_model": (
                            "gpt-5.3-codex-spark"
                            if llm_pipeline == "codex-recipe-shard-v1"
                            else None
                        ),
                        "codex_farm_reasoning_effort": (
                            "low" if llm_pipeline == "codex-recipe-shard-v1" else None
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(
        monkeypatch,
        "resolve_or_build_deterministic_prep_bundle",
        lambda **kwargs: prep_bundle_calls.append(dict(kwargs)) or prep_bundle,
    )
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write",
        lambda **kwargs: refresh_calls.append(kwargs),
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        golden_root=golden_root,
        preselected_gold_spans=gold_spans,
        preselected_source_file=source_file,
        publisher=publisher,
    )
    return {
        "completed": completed,
        "benchmark_calls": benchmark_calls,
        "refresh_calls": refresh_calls,
        "prep_bundle_calls": prep_bundle_calls,
        "prep_bundle": prep_bundle,
        "benchmark_eval_output": benchmark_eval_output,
        "processed_output_root": processed_output_root,
        "publication_capture": publication_capture,
    }


def test_interactive_single_book_codex_enabled_runs_only_codex_exec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_single_book_codex_enabled_fixture(monkeypatch, tmp_path)
    completed = fixture["completed"]
    benchmark_calls = fixture["benchmark_calls"]
    prep_bundle_calls = fixture["prep_bundle_calls"]
    prep_bundle = fixture["prep_bundle"]
    benchmark_eval_output = fixture["benchmark_eval_output"]
    processed_output_root = fixture["processed_output_root"]

    assert completed is True
    assert len(prep_bundle_calls) == 1
    assert len(benchmark_calls) == 2
    assert [call["llm_recipe_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-recipe-shard-v1",
    ]
    assert [call["line_role_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-line-role-route-v2",
    ]
    assert [call["atomic_block_splitter"] for call in benchmark_calls] == [
        "off",
        "off",
    ]
    assert [call["allow_codex"] for call in benchmark_calls] == [False, True]
    assert [call["recipe_prompt_target_count"] for call in benchmark_calls] == [10, 10]
    assert [call["knowledge_prompt_target_count"] for call in benchmark_calls] == [4, 4]
    assert [call["line_role_prompt_target_count"] for call in benchmark_calls] == [5, 5]
    assert [call["single_book_split_cache_mode"] for call in benchmark_calls] == [
        "auto",
        "auto",
    ]
    assert [call.get("deterministic_prep_manifest_path") for call in benchmark_calls] == [
        prep_bundle.manifest_path,
        None,
    ]
    assert [call["eval_output_dir"] for call in benchmark_calls] == [
        benchmark_eval_output / "single-book-benchmark" / "book" / "vanilla",
        benchmark_eval_output / "single-book-benchmark" / "book" / "codex-exec",
    ]
    assert [call["processed_output_dir"] for call in benchmark_calls] == [
        processed_output_root
        / benchmark_eval_output.name
        / "single-book-benchmark"
        / "book"
        / "vanilla",
        processed_output_root
        / benchmark_eval_output.name
        / "single-book-benchmark"
        / "book"
        / "codex-exec",
    ]


def test_interactive_single_book_codex_enabled_writes_comparison_and_refreshes_dashboard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_single_book_codex_enabled_fixture(monkeypatch, tmp_path)
    refresh_calls = fixture["refresh_calls"]
    benchmark_eval_output = fixture["benchmark_eval_output"]
    processed_output_root = fixture["processed_output_root"]

    comparison_json = (
        benchmark_eval_output
        / "single-book-benchmark"
        / "book"
        / "codex_vs_vanilla_comparison.json"
    )
    comparison_md = (
        benchmark_eval_output
        / "single-book-benchmark"
        / "book"
        / "codex_vs_vanilla_comparison.md"
    )
    assert comparison_json.exists()
    assert not comparison_md.exists()
    assert refresh_calls == []


def test_interactive_single_book_preserves_selected_codex_recipe_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test merged-prototype benchmark",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.40, "recall": 0.31, "f1": 0.35}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "source": {"path": str(tmp_path / "book.epub")},
                    "run_config": {
                        "llm_recipe_pipeline": kwargs.get("llm_recipe_pipeline"),
                    },
                }
            ),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write", lambda **_kwargs: None)
    _patch_cli_attr(monkeypatch, "_write_single_book_starter_pack", lambda **_kwargs: None)
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        golden_root=tmp_path / "golden",
    )

    assert completed is True
    assert [call["llm_recipe_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-recipe-shard-v1",
    ]


def test_interactive_single_book_preserves_selected_atomic_splitter_across_variants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "atomic_block_splitter": "atomic-v1",
        },
        warn_context="test single-book shared atomic splitter",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.40, "recall": 0.31, "f1": 0.35}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "source": {"path": str(tmp_path / "book.epub")},
                    "run_config": {
                        "atomic_block_splitter": kwargs.get("atomic_block_splitter"),
                    },
                }
            ),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write", lambda **_kwargs: None)
    _patch_cli_attr(monkeypatch, "_write_single_book_starter_pack", lambda **_kwargs: None)
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert [call["atomic_block_splitter"] for call in benchmark_calls] == [
        "atomic-v1",
        "atomic-v1",
    ]


def test_interactive_single_book_variants_ignore_persistence_only_metadata() -> None:
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_model": "gpt-5.3-codex-spark",
            "codex_farm_reasoning_effort": "low",
        },
        warn_context="test metadata-safe single-book variants",
    )

    variants = cli._interactive_single_book_variants(selected_settings)

    assert [slug for slug, _settings in variants] == ["vanilla", "codex-exec"]
    assert [settings.llm_recipe_pipeline.value for _, settings in variants] == [
        "off",
        "codex-recipe-shard-v1",
    ]
    assert [str(settings.codex_farm_model) for _, settings in variants] == [
        "gpt-5.3-codex-spark",
        "gpt-5.3-codex-spark",
    ]
    assert [
        (
            settings.codex_farm_reasoning_effort.value
            if settings.codex_farm_reasoning_effort is not None
            else None
        )
        for _, settings in variants
    ] == [
        "low",
        "low",
    ]

def test_interactive_single_book_uses_book_slug_in_session_root_when_source_selected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test source-slugged-single-book-root",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"
    source_file = tmp_path / "The Book Name.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    class _FakeStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli.sys, "stdin", _FakeStdin())
    _patch_cli_attr(monkeypatch, "_resolve_benchmark_gold_and_source",
        lambda **_kwargs: (gold_spans, source_file),
    )

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.20, "recall": 0.30, "f1": 0.24}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(source_file)}}),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert len(benchmark_calls) == 1
    source_slug = cli.slugify_name(source_file.stem)
    assert benchmark_calls[0]["eval_output_dir"] == (
        benchmark_eval_output
        / "single-book-benchmark"
        / source_slug
        / "vanilla"
    )
    assert benchmark_calls[0]["processed_output_dir"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "single-book-benchmark"
        / source_slug
        / "vanilla"
    )


def test_interactive_single_book_uses_preselected_gold_when_resolving_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test preselected single-book gold",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"
    source_file = tmp_path / "The Book Name.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = (
        tmp_path
        / "gold"
        / "pulled-from-labelstudio"
        / "saltfatacidheatcutdown"
        / "exports"
        / "freeform_span_labels.jsonl"
    )
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")
    resolve_kwargs: dict[str, object] = {}

    class _FakeStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli.sys, "stdin", _FakeStdin())
    _patch_cli_attr(monkeypatch, "_resolve_benchmark_gold_and_source",
        lambda **kwargs: resolve_kwargs.update(kwargs) or (gold_spans, source_file),
    )

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.20, "recall": 0.30, "f1": 0.24}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(source_file)}}),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        preselected_gold_spans=gold_spans,
    )

    assert completed is True
    assert resolve_kwargs["gold_spans"] == gold_spans
    assert resolve_kwargs["source_file"] is None
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["gold_spans"] == gold_spans


def test_interactive_single_book_codex_disabled_runs_only_vanilla_and_skips_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test codex-off",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"

    benchmark_calls: list[dict[str, object]] = []
    refresh_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.20, "recall": 0.30, "f1": 0.24}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write",
        lambda **kwargs: refresh_calls.append(kwargs),
    )
    _patch_cli_attr(monkeypatch, "_write_single_book_starter_pack",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("starter pack should not run for vanilla-only single-book")
        ),
    )
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )
    _patch_cli_attr(monkeypatch, "_start_benchmark_bundle_oracle_upload_background",
        lambda **_kwargs: None,
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["llm_recipe_pipeline"] == "off"
    assert benchmark_calls[0]["eval_output_dir"] == (
        benchmark_eval_output / "single-book-benchmark" / "vanilla"
    )
    assert not (
        benchmark_eval_output
        / "single-book-benchmark"
        / "codex_vs_vanilla_comparison.json"
    ).exists()
    assert not (
        benchmark_eval_output
        / "single-book-benchmark"
        / "codex_vs_vanilla_comparison.md"
    ).exists()
    assert len(refresh_calls) == 1
    assert refresh_calls[0]["reason"] == "single-book benchmark variant batch append"
    assert refresh_calls[0]["csv_path"] == cli.history_csv_for_output(
        processed_output_root
        / benchmark_eval_output.name
        / "single-book-benchmark"
        / cli._DASHBOARD_REFRESH_SENTINEL_DIRNAME
    )
    assert refresh_calls[0]["output_root"] == processed_output_root
    assert (
        refresh_calls[0]["dashboard_out_dir"]
        == cli.history_root_for_output(processed_output_root) / "dashboard"
    )


def test_interactive_single_book_fully_vanilla_still_uses_vanilla_slug(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="test fully-vanilla slug",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.22, "recall": 0.31, "f1": 0.26}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write",
        lambda **_kwargs: None,
    )
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )
    _patch_cli_attr(monkeypatch, "_start_benchmark_bundle_oracle_upload_background",
        lambda **_kwargs: None,
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["llm_recipe_pipeline"] == "off"
    assert benchmark_calls[0]["line_role_pipeline"] == "off"
    assert benchmark_calls[0]["atomic_block_splitter"] == "off"
    assert benchmark_calls[0]["eval_output_dir"] == (
        benchmark_eval_output / "single-book-benchmark" / "vanilla"
    )
    assert benchmark_calls[0]["processed_output_dir"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "single-book-benchmark"
        / "vanilla"
    )

def test_interactive_single_book_hybrid_run_uses_profile_slug_not_vanilla(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "codex-line-role-route-v2",
            "atomic_block_splitter": "atomic-v1",
        },
        warn_context="test line-role-only single-book",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.25, "recall": 0.35, "f1": 0.29}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write",
        lambda **_kwargs: None,
    )
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )
    _patch_cli_attr(monkeypatch, "_start_benchmark_bundle_oracle_upload_background",
        lambda **_kwargs: None,
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=True,
    )

    assert completed is True
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["llm_recipe_pipeline"] == "off"
    assert benchmark_calls[0]["line_role_pipeline"] == "codex-line-role-route-v2"
    assert benchmark_calls[0]["atomic_block_splitter"] == "atomic-v1"
    assert benchmark_calls[0]["eval_output_dir"] == (
        benchmark_eval_output / "single-book-benchmark" / "line_role_only"
    )
    assert benchmark_calls[0]["processed_output_dir"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "single-book-benchmark"
        / "line_role_only"
    )
    summary_text = (
        benchmark_eval_output / "single-book-benchmark" / "single_book_summary.md"
    ).read_text(encoding="utf-8")
    assert "line_role_only" in summary_text
    assert not (
        benchmark_eval_output
        / "single-book-benchmark"
        / "codex_vs_vanilla_comparison.json"
    ).exists()

def test_interactive_single_book_markdown_enabled_writes_one_top_level_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test markdown-summary",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"
    source_path = str(tmp_path / "book.epub")

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        llm_pipeline = str(kwargs.get("llm_recipe_pipeline") or "").strip().lower()
        metrics = {
            "overall_line_accuracy": 0.71 if llm_pipeline == "codex-recipe-shard-v1" else 0.68,
            "precision": 0.42 if llm_pipeline == "codex-recipe-shard-v1" else 0.39,
            "recall": 0.41 if llm_pipeline == "codex-recipe-shard-v1" else 0.38,
            "f1": 0.40 if llm_pipeline == "codex-recipe-shard-v1" else 0.37,
            "macro_f1_excluding_other": 0.52
            if llm_pipeline == "codex-recipe-shard-v1"
            else 0.49,
            "practical_precision": 0.31 if llm_pipeline == "codex-recipe-shard-v1" else 0.29,
            "practical_recall": 0.30 if llm_pipeline == "codex-recipe-shard-v1" else 0.28,
            "practical_f1": 0.29 if llm_pipeline == "codex-recipe-shard-v1" else 0.27,
        }
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps(metrics),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": source_path}}),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)

    _patch_cli_attr(monkeypatch, "_write_single_book_starter_pack",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("starter pack should not run by default")
        ),
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=True,
    )

    assert completed is True
    assert len(benchmark_calls) == 2
    assert all(call["write_markdown"] is False for call in benchmark_calls)
    session_root = benchmark_eval_output / "single-book-benchmark"
    summary_path = session_root / "single_book_summary.md"
    assert summary_path.exists()
    md_files = sorted(session_root.rglob("*.md"))
    assert summary_path in md_files
    upload_bundle_dir = session_root / cli.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    assert upload_bundle_dir.is_dir()
    assert {
        path.name
        for path in upload_bundle_dir.iterdir()
        if path.is_file()
    } == set(cli.BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES)
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "Single Book Benchmark Summary" in summary_text
    assert "Codex vs Vanilla" in summary_text
    assert "codex_vs_vanilla_comparison.json" in summary_text
    assert not (session_root / "codex_vs_vanilla_comparison.md").exists()

def test_interactive_single_book_vanilla_skips_background_oracle_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="test oracle single-book",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-05_23.01.17"
    )
    processed_output_root = tmp_path / "output"

    def fake_labelstudio_benchmark(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.20, "recall": 0.30, "f1": 0.24}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write",
        lambda **_kwargs: None,
    )

    upload_bundle_calls: list[dict[str, object]] = []
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: upload_bundle_calls.append(dict(kwargs)),
    )
    launch_calls: list[dict[str, object]] = []
    _patch_cli_attr(monkeypatch, "_start_benchmark_bundle_oracle_upload_background",
        lambda **kwargs: launch_calls.append(dict(kwargs)),
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert upload_bundle_calls == []
    assert launch_calls == []


def test_interactive_single_book_codex_writes_capped_high_level_upload_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test capped single-book upload bundle",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-22_10.00.00"
    )
    processed_output_root = tmp_path / "output"

    def fake_labelstudio_benchmark(**kwargs):
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps({"precision": 0.20, "recall": 0.30, "f1": 0.24}),
            encoding="utf-8",
        )
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write",
        lambda **_kwargs: None,
    )

    upload_bundle_calls: list[dict[str, object]] = []
    session_bundle_dir = (
        benchmark_eval_output
        / "single-book-benchmark"
        / cli.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )

    def _fake_write_benchmark_upload_bundle(**kwargs):
        upload_bundle_calls.append(dict(kwargs))
        return session_bundle_dir

    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle", _fake_write_benchmark_upload_bundle)
    _patch_cli_attr(monkeypatch, "_start_benchmark_bundle_oracle_upload_background",
        lambda **_kwargs: None,
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is True
    assert len(upload_bundle_calls) == 1
    call = upload_bundle_calls[0]
    assert call["high_level_only"] is True
    assert (
        call["target_bundle_size_bytes"]
        == cli.BENCHMARK_SINGLE_BOOK_UPLOAD_BUNDLE_TARGET_BYTES
    )

def test_interactive_single_book_codex_failure_returns_unsuccessful_without_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test codex-fails",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-03-02_12.34.56"
    )
    processed_output_root = tmp_path / "output"

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(kwargs)
        raise cli.typer.Exit(2)

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_write_single_book_starter_pack",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("starter pack should not run when codex variant fails")
        ),
    )
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )

    completed = cli._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
    )

    assert completed is False
    assert len(benchmark_calls) == 2
    assert benchmark_calls[0]["llm_recipe_pipeline"] == "off"
    assert benchmark_calls[1]["llm_recipe_pipeline"] == "codex-recipe-shard-v1"
    assert not (
        benchmark_eval_output
        / "single-book-benchmark"
        / "codex_vs_vanilla_comparison.json"
    ).exists()
