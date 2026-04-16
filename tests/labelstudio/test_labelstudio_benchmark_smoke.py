from __future__ import annotations

import cookimport.cli_support.bench_artifacts as bench_artifacts
import cookimport.cli_support.bench_single_book as bench_single_book
import cookimport.cli_support.progress as progress_support
import cookimport.cli_commands.labelstudio as labelstudio_commands
import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def _patch_single_book_smoke_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cli_module,
    tmp_path: Path,
    configured_output: Path,
    golden_root: Path,
    selected_benchmark_settings,
) -> list[dict[str, object]]:
    benchmark_root = golden_root / "benchmark-vs-golden"
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = golden_root / "book" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    (gold_export_root / "row_gold_labels.jsonl").write_text(
        "{\"row_id\":\"row:0\",\"row_index\":0,\"text\":\"Title\",\"labels\":[\"RECIPE_TITLE\"]}\n"
        "{\"row_id\":\"row:1\",\"row_index\":1,\"text\":\"Body\",\"labels\":[\"OTHER\"]}\n",
        encoding="utf-8",
    )

    menu_answers = iter(["labelstudio_benchmark", "single_book", "exit"])

    _patch_cli_attr(
        monkeypatch,
        "_menu_select",
        lambda *_args, **_kwargs: next(menu_answers),
    )
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(
        monkeypatch,
        "_load_settings",
        lambda: {"output_dir": str(configured_output), "epub_extractor": "beautifulsoup"},
    )
    _patch_cli_attr(
        monkeypatch,
        "choose_run_settings",
        lambda **_kwargs: selected_benchmark_settings,
    )
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)
    _patch_cli_attr(monkeypatch, "_golden_benchmark_root", lambda: benchmark_root)
    _patch_cli_attr(
        monkeypatch,
        "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError(
                "Offline benchmark smoke should not resolve Label Studio credentials."
            )
        ),
    )
    _patch_cli_attr(
        monkeypatch,
        "_resolve_benchmark_gold_and_source",
        lambda **_kwargs: (gold_spans, source_file),
    )
    _patch_cli_attr(
        monkeypatch,
        "_refresh_dashboard_after_history_write",
        lambda **_kwargs: None,
    )
    _patch_cli_attr(
        monkeypatch,
        "history_csv_for_output",
        lambda *_args, **_kwargs: tmp_path / ".history" / "performance_history.csv",
    )
    _patch_cli_attr(
        monkeypatch,
        "_enforce_live_labelstudio_benchmark_codex_guardrails",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        progress_support,
        "_enforce_live_labelstudio_benchmark_codex_guardrails",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(progress_support, "_is_agent_execution_environment", lambda: False)
    publisher, _publisher_capture = _make_lightweight_single_book_publisher()
    _patch_cli_attr(
        monkeypatch,
        "_make_single_book_benchmark_publisher",
        lambda **_kwargs: publisher,
    )
    _patch_cli_attr(
        monkeypatch,
        "_write_single_book_starter_pack",
        lambda **_kwargs: None,
    )

    benchmark_calls: list[dict[str, object]] = []

    def fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(dict(kwargs))
        eval_output_dir = kwargs["eval_output_dir"]
        assert isinstance(eval_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        llm_recipe_pipeline = str(kwargs.get("llm_recipe_pipeline") or "off")
        metrics = {
            "precision": 0.45 if llm_recipe_pipeline != "off" else 0.40,
            "recall": 0.35 if llm_recipe_pipeline != "off" else 0.30,
            "f1": 0.39 if llm_recipe_pipeline != "off" else 0.34,
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
                    "source": {"path": str(tmp_path / "book.epub")},
                    "run_config": {
                        "llm_recipe_pipeline": llm_recipe_pipeline,
                        "codex_farm_model": kwargs.get("codex_farm_model"),
                        "codex_farm_reasoning_effort": kwargs.get(
                            "codex_farm_reasoning_effort"
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", fake_labelstudio_benchmark)
    return benchmark_calls


def test_interactive_benchmark_single_book_vanilla_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured_output = tmp_path / "output"
    golden_root = tmp_path / "golden"
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
            "epub_extractor": "beautifulsoup",
        },
        warn_context="single-book vanilla smoke",
    )

    benchmark_calls = _patch_single_book_smoke_runtime(
        monkeypatch,
        cli_module=cli,
        tmp_path=tmp_path,
        configured_output=configured_output,
        golden_root=golden_root,
        selected_benchmark_settings=selected_benchmark_settings,
    )

    interactive_mode_token = cli._INTERACTIVE_CLI_ACTIVE.set(True)
    try:
        with pytest.raises(cli.typer.Exit):
            cli._interactive_mode()
    finally:
        cli._INTERACTIVE_CLI_ACTIVE.reset(interactive_mode_token)

    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["llm_recipe_pipeline"] == "off"
    assert benchmark_calls[0]["no_upload"] is True
    assert benchmark_calls[0]["eval_mode"] == cli.BENCHMARK_EVAL_MODE_SOURCE_ROWS


def test_interactive_benchmark_single_book_codex_shaped_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured_output = tmp_path / "output"
    golden_root = tmp_path / "golden"
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_model": "gpt-5.3-codex-spark",
            "codex_farm_reasoning_effort": "low",
        },
        warn_context="single-book codex-shaped smoke",
    )

    benchmark_calls = _patch_single_book_smoke_runtime(
        monkeypatch,
        cli_module=cli,
        tmp_path=tmp_path,
        configured_output=configured_output,
        golden_root=golden_root,
        selected_benchmark_settings=selected_benchmark_settings,
    )

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert len(benchmark_calls) == 1
    assert [call["llm_recipe_pipeline"] for call in benchmark_calls] == [
        "codex-recipe-shard-v1",
    ]
    assert [call["allow_codex"] for call in benchmark_calls] == [True]
    assert [call["codex_farm_model"] for call in benchmark_calls] == [
        "gpt-5.3-codex-spark",
    ]
    assert [call["codex_farm_reasoning_effort"] for call in benchmark_calls] == [
        "low",
    ]


def _simulated_canonical_eval_report(*, eval_output_dir: Path) -> dict[str, object]:
    variant_slug = eval_output_dir.name
    codex_enabled = variant_slug == "codex-exec"
    if codex_enabled:
        precision = 0.47
        recall = 0.38
        f1 = 0.42
        macro_f1 = 0.41
        line_accuracy = 0.63
    else:
        precision = 0.40
        recall = 0.30
        f1 = 0.34
        macro_f1 = 0.33
        line_accuracy = 0.57
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
            "overall_line_accuracy": line_accuracy,
            "overall_block_accuracy": line_accuracy,
            "macro_f1_excluding_other": macro_f1,
            "worst_label_recall": {"label": "RECIPE_TITLE", "recall": recall},
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "practical_precision": precision,
            "practical_recall": recall,
            "practical_f1": f1,
            "per_label": {
                "RECIPE_TITLE": {
                    "precision": 1.0,
                    "recall": 1.0,
                    "gold_total": 1,
                    "pred_total": 1,
                },
                "OTHER": {
                    "precision": precision,
                    "recall": recall,
                    "gold_total": 1,
                    "pred_total": 1,
                },
            },
        },
        "missed_gold": [],
        "false_positive_preds": [],
    }


def _run_interactive_single_book_simulated_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    selected_benchmark_settings,
) -> dict[str, object]:
    configured_output = tmp_path / "output"
    golden_root = tmp_path / "golden"
    benchmark_root = golden_root / "benchmark-vs-golden"
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_export_root = golden_root / "book" / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_export_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    menu_answers = iter(["labelstudio_benchmark", "single_book", "exit"])
    _patch_cli_attr(
        monkeypatch,
        "_menu_select",
        lambda *_args, **_kwargs: next(menu_answers),
    )
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(
        monkeypatch,
        "_load_settings",
        lambda: {"output_dir": str(configured_output), "epub_extractor": "beautifulsoup"},
    )
    _patch_cli_attr(
        monkeypatch,
        "choose_run_settings",
        lambda **_kwargs: selected_benchmark_settings,
    )
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)
    _patch_cli_attr(monkeypatch, "_golden_benchmark_root", lambda: benchmark_root)
    _patch_cli_attr(
        monkeypatch,
        "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError(
                "Offline benchmark sim should not resolve Label Studio credentials."
            )
        ),
    )
    _patch_cli_attr(
        monkeypatch,
        "_resolve_benchmark_gold_and_source",
        lambda **_kwargs: (gold_spans, source_file),
    )
    _patch_cli_attr(
        monkeypatch,
        "_refresh_dashboard_after_history_write",
        lambda **_kwargs: None,
    )
    _patch_cli_attr(
        monkeypatch,
        "history_csv_for_output",
        lambda *_args, **_kwargs: tmp_path / ".history" / "performance_history.csv",
    )
    _patch_cli_attr(
        monkeypatch,
        "_enforce_live_labelstudio_benchmark_codex_guardrails",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        progress_support,
        "_enforce_live_labelstudio_benchmark_codex_guardrails",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(progress_support, "_is_agent_execution_environment", lambda: False)
    monkeypatch.setattr(
        labelstudio_commands,
        "_enforce_live_labelstudio_benchmark_codex_guardrails",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        bench_single_book,
        "_labelstudio_benchmark_command",
        lambda: labelstudio_commands.labelstudio_benchmark,
    )
    _patch_cli_attr(
        monkeypatch,
        "_write_single_book_starter_pack",
        lambda **_kwargs: None,
    )
    publisher, publication_capture = _make_lightweight_single_book_publisher()
    _patch_cli_attr(
        monkeypatch,
        "_make_single_book_benchmark_publisher",
        lambda **_kwargs: publisher,
    )

    def _fail_upload_path(**_kwargs):
        raise AssertionError("Offline benchmark sim should not call run_labelstudio_import.")

    _patch_cli_attr(monkeypatch, "run_labelstudio_import", _fail_upload_path)
    _install_noop_benchmark_eval_mocks(monkeypatch)

    generate_calls: list[dict[str, object]] = []
    eval_calls: list[dict[str, object]] = []

    def _fake_generate_pred_run_artifacts(**kwargs):
        generate_calls.append(dict(kwargs))
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        prediction_run = output_dir / "prediction-run"
        variant_slug = output_dir.name
        manifest_payload = {
            "run_config": {
                "llm_recipe_pipeline": kwargs.get("llm_recipe_pipeline"),
                "codex_farm_model": kwargs.get("codex_farm_model"),
                "codex_farm_reasoning_effort": kwargs.get("codex_farm_reasoning_effort"),
            },
            "run_config_hash": f"hash-{variant_slug}",
            "run_config_summary": f"variant={variant_slug}",
        }
        fixture_paths = _write_benchmark_prediction_run_fixture(
            prediction_run=prediction_run,
            source_file=source_file,
            row_labels={"0": "RECIPE_TITLE", "1": "OTHER"},
            extracted_rows=[
                {
                    "index": 0,
                    "text": "Title",
                    "location": {"features": {"heading_level": "1"}},
                },
                {
                    "index": 1,
                    "text": "Body",
                    "location": {"features": {"heading_level": "0"}},
                },
            ],
            manifest_payload=manifest_payload,
        )
        return {
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / variant_slug,
            "processed_report_path": "",
            "semantic_row_predictions_path": fixture_paths["stage_predictions_path"],
            "extracted_archive_path": fixture_paths["extracted_archive_path"],
            "timing": {"prediction_seconds": 0.25 if variant_slug == "codex-exec" else 0.15},
        }

    def _fake_evaluate_source_rows(**kwargs):
        eval_calls.append(dict(kwargs))
        eval_output_dir = kwargs["out_dir"]
        assert isinstance(eval_output_dir, Path)
        return _simulated_canonical_eval_report(eval_output_dir=eval_output_dir)

    def _fake_build_codex_farm_prompt_response_log(*, pred_run: Path, eval_output_dir: Path, repo_root: Path):
        del pred_run, repo_root
        log_path = eval_output_dir / "codex_farm_prompt_response_log.md"
        log_path.write_text("# Simulated prompt log\n", encoding="utf-8")
        return log_path

    _patch_cli_attr(monkeypatch, "generate_pred_run_artifacts", _fake_generate_pred_run_artifacts)
    monkeypatch.setattr(bench_artifacts, "evaluate_source_rows", _fake_evaluate_source_rows)
    monkeypatch.setattr(bench_artifacts, "format_source_row_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        cli.llm_prompt_artifacts,
        "build_codex_farm_prompt_response_log",
        _fake_build_codex_farm_prompt_response_log,
    )

    interactive_mode_token = cli._INTERACTIVE_CLI_ACTIVE.set(True)
    try:
        with pytest.raises(cli.typer.Exit):
            cli._interactive_mode()
    finally:
        cli._INTERACTIVE_CLI_ACTIVE.reset(interactive_mode_token)

    return {
        "generate_calls": generate_calls,
        "eval_calls": eval_calls,
        "benchmark_root": benchmark_root,
        "configured_output": configured_output,
        "publication_capture": publication_capture,
    }


def test_interactive_benchmark_single_book_vanilla_simulated_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
            "epub_extractor": "beautifulsoup",
        },
        warn_context="single-book vanilla simulated runtime",
    )

    fixture = _run_interactive_single_book_simulated_runtime(
        monkeypatch,
        tmp_path=tmp_path,
        selected_benchmark_settings=selected_benchmark_settings,
    )

    generate_calls = fixture["generate_calls"]
    benchmark_root = fixture["benchmark_root"]

    assert len(generate_calls) == 1
    assert generate_calls[0]["llm_recipe_pipeline"] == "off"
    assert generate_calls[0]["allow_codex"] is False

    summary_paths = list(benchmark_root.rglob("single_book_summary.md"))
    assert len(summary_paths) == 1
    summary_text = summary_paths[0].read_text(encoding="utf-8")
    assert "- Status: `ok`" in summary_text
    assert "### `vanilla`" in summary_text
    assert "Comparison JSON:" not in summary_text


def test_interactive_benchmark_single_book_codex_shaped_simulated_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_model": "gpt-5.3-codex-spark",
            "codex_farm_reasoning_effort": "low",
            "recipe_prompt_target_count": 4,
        },
        warn_context="single-book codex simulated runtime",
    )

    fixture = _run_interactive_single_book_simulated_runtime(
        monkeypatch,
        tmp_path=tmp_path,
        selected_benchmark_settings=selected_benchmark_settings,
    )

    generate_calls = fixture["generate_calls"]
    benchmark_root = fixture["benchmark_root"]

    assert len(generate_calls) == 1
    assert [call["llm_recipe_pipeline"] for call in generate_calls] == [
        "codex-recipe-shard-v1",
    ]
    assert [call["allow_codex"] for call in generate_calls] == [True]
    assert [call["codex_farm_model"] for call in generate_calls] == [
        "gpt-5.3-codex-spark",
    ]
    assert [call["codex_farm_reasoning_effort"] for call in generate_calls] == [
        "low",
    ]
    assert [call["recipe_codex_exec_style"] for call in generate_calls] == [
        "inline-json-v1",
    ]

    comparison_paths = list(benchmark_root.rglob("benchmark_comparison.json"))
    assert comparison_paths == []

    summary_paths = list(benchmark_root.rglob("single_book_summary.md"))
    assert len(summary_paths) == 1
    summary_text = summary_paths[0].read_text(encoding="utf-8")
    assert "### `recipe_only`" in summary_text


def _run_real_vanilla_single_book_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    run_count: int,
) -> dict[str, object]:
    import cookimport.staging.deterministic_prep as deterministic_prep

    monkeypatch.setenv("COOKIMPORT_BOOK_CACHE_ROOT", str(tmp_path / ".book-cache"))

    source_file = tmp_path / "book.txt"
    source_file.write_text("Toast\n\n1 slice bread\nToast the bread.\n", encoding="utf-8")
    gold_root = tmp_path / "golden" / "book" / "exports"
    gold_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        bench_artifacts,
        "evaluate_source_rows",
        lambda **kwargs: _simulated_canonical_eval_report(eval_output_dir=kwargs["out_dir"]),
    )
    monkeypatch.setattr(bench_artifacts, "format_source_row_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )

    def _fake_build_codex_farm_prompt_response_log(
        *,
        pred_run: Path,
        eval_output_dir: Path,
        repo_root: Path,
    ) -> Path:
        del pred_run, repo_root
        log_path = eval_output_dir / "codex_farm_prompt_response_log.md"
        log_path.write_text("# prompt log\n", encoding="utf-8")
        return log_path

    monkeypatch.setattr(
        "cookimport.cli_commands.labelstudio.llm_prompt_artifacts.build_codex_farm_prompt_response_log",
        _fake_build_codex_farm_prompt_response_log,
    )

    original_resolve = deterministic_prep.resolve_or_build_deterministic_prep_bundle
    cache_hits: list[bool] = []

    def _tracking_resolve(**kwargs):
        bundle = original_resolve(**kwargs)
        cache_hits.append(bool(bundle.cache_hit))
        return bundle

    _patch_cli_attr(
        monkeypatch,
        "resolve_or_build_deterministic_prep_bundle",
        _tracking_resolve,
    )

    publisher, publication_capture = _make_lightweight_single_book_publisher()
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="real offline vanilla single-book smoke",
    )

    completed_results: list[bool] = []
    benchmark_eval_outputs: list[Path] = []
    for run_index in range(run_count):
        benchmark_eval_output = tmp_path / "golden" / "benchmark-vs-golden" / (
            f"2026-04-04_23.20.0{run_index}"
        )
        benchmark_eval_outputs.append(benchmark_eval_output)
        completed = bench_single_book._interactive_single_book_benchmark(
            selected_benchmark_settings=selected_benchmark_settings,
            benchmark_eval_output=benchmark_eval_output,
            processed_output_root=tmp_path / "processed-output",
            write_markdown=True,
            write_label_studio_tasks=False,
            preselected_gold_spans=gold_spans,
            preselected_source_file=source_file,
            publisher=publisher,
        )
        completed_results.append(completed)

    return {
        "cache_hits": cache_hits,
        "completed_results": completed_results,
        "benchmark_eval_outputs": benchmark_eval_outputs,
        "publication_capture": publication_capture,
    }


def test_interactive_single_book_vanilla_real_runtime_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_real_vanilla_single_book_runtime(
        monkeypatch,
        tmp_path=tmp_path,
        run_count=1,
    )

    benchmark_eval_output = fixture["benchmark_eval_outputs"][0]
    session_root = benchmark_eval_output / "single-book-benchmark" / "book"
    variant_root = session_root / "vanilla"
    run_manifest = json.loads((variant_root / "run_manifest.json").read_text(encoding="utf-8"))
    summary_text = (session_root / "single_book_summary.md").read_text(encoding="utf-8")

    assert fixture["completed_results"] == [True]
    assert fixture["cache_hits"] == [False]
    assert run_manifest["run_kind"] == "labelstudio_benchmark"
    assert run_manifest["run_config"]["llm_recipe_pipeline"] == "off"
    assert (variant_root / "eval_report.json").exists()
    assert (variant_root / "codex_farm_prompt_response_log.md").exists()
    assert "- Status: `ok`" in summary_text
    assert "### `vanilla`" in summary_text


def test_interactive_single_book_vanilla_real_runtime_hits_deterministic_prep_cache_on_rerun(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_real_vanilla_single_book_runtime(
        monkeypatch,
        tmp_path=tmp_path,
        run_count=2,
    )

    second_benchmark_eval_output = fixture["benchmark_eval_outputs"][1]
    second_variant_root = (
        second_benchmark_eval_output / "single-book-benchmark" / "book" / "vanilla"
    )
    second_run_manifest = json.loads(
        (second_variant_root / "run_manifest.json").read_text(encoding="utf-8")
    )

    assert fixture["completed_results"] == [True, True]
    assert fixture["cache_hits"] == [False, True]
    assert second_run_manifest["run_config"]["llm_recipe_pipeline"] == "off"


def test_interactive_single_book_codex_shaped_real_prep_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import cookimport.staging.deterministic_prep as deterministic_prep

    monkeypatch.setenv("COOKIMPORT_BOOK_CACHE_ROOT", str(tmp_path / ".book-cache"))

    source_file = tmp_path / "book.txt"
    source_file.write_text("Toast\n\n1 slice bread\nToast the bread.\n", encoding="utf-8")
    gold_root = tmp_path / "golden" / "book" / "exports"
    gold_root.mkdir(parents=True, exist_ok=True)
    gold_spans = gold_root / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")

    original_resolve = deterministic_prep.resolve_or_build_deterministic_prep_bundle
    prep_run_settings: list[cli.RunSettings] = []
    benchmark_calls: list[dict[str, object]] = []

    def _tracking_resolve(**kwargs):
        prep_run_settings.append(kwargs["run_settings"])
        return original_resolve(**kwargs)

    def _fake_labelstudio_benchmark(**kwargs):
        benchmark_calls.append(dict(kwargs))
        eval_output_dir = kwargs["eval_output_dir"]
        processed_output_dir = kwargs["processed_output_dir"]
        assert isinstance(eval_output_dir, Path)
        assert isinstance(processed_output_dir, Path)
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        processed_output_dir.mkdir(parents=True, exist_ok=True)
        (eval_output_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_kind": "labelstudio_benchmark",
                    "source": {"path": str(source_file)},
                    "run_config": {
                        "llm_recipe_pipeline": kwargs.get("llm_recipe_pipeline"),
                        "line_role_pipeline": kwargs.get("line_role_pipeline"),
                        "llm_knowledge_pipeline": kwargs.get("llm_knowledge_pipeline"),
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (eval_output_dir / "eval_report.json").write_text(
            json.dumps(_simulated_canonical_eval_report(eval_output_dir=eval_output_dir))
            + "\n",
            encoding="utf-8",
        )

    _patch_cli_attr(
        monkeypatch,
        "resolve_or_build_deterministic_prep_bundle",
        _tracking_resolve,
    )
    _patch_cli_attr(
        monkeypatch,
        "_run_prediction_with_reuse",
        lambda *, execute_prediction, **_kwargs: (
            execute_prediction() or {"prediction_result_source": "fresh"}
        ),
    )
    _patch_cli_attr(
        monkeypatch,
        "_labelstudio_benchmark_command",
        lambda: _fake_labelstudio_benchmark,
    )

    publisher, publication_capture = _make_lightweight_single_book_publisher()
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "codex_farm_model": "gpt-5.4-mini",
            "codex_farm_reasoning_effort": "low",
            "recipe_prompt_target_count": 4,
            "line_role_prompt_target_count": 6,
            "knowledge_prompt_target_count": 7,
        },
        warn_context="single-book codex-shaped real prep smoke",
    )
    benchmark_eval_output = (
        tmp_path / "golden" / "benchmark-vs-golden" / "2026-04-15_12.22.26"
    )

    completed = bench_single_book._interactive_single_book_benchmark(
        selected_benchmark_settings=selected_benchmark_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=tmp_path / "processed-output",
        write_markdown=True,
        write_label_studio_tasks=False,
        preselected_gold_spans=gold_spans,
        preselected_source_file=source_file,
        publisher=publisher,
    )

    session_root = benchmark_eval_output / "single-book-benchmark" / "book"
    summary_text = (session_root / "single_book_summary.md").read_text(encoding="utf-8")

    assert completed is True
    assert publication_capture["results"]
    assert len(prep_run_settings) == 1
    assert prep_run_settings[0].llm_recipe_pipeline.value == "off"
    assert prep_run_settings[0].line_role_pipeline.value == "off"
    assert prep_run_settings[0].llm_knowledge_pipeline.value == "off"
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["allow_codex"] is True
    assert benchmark_calls[0]["llm_recipe_pipeline"] == "codex-recipe-shard-v1"
    assert benchmark_calls[0]["line_role_pipeline"] == "codex-line-role-route-v2"
    assert benchmark_calls[0]["llm_knowledge_pipeline"] == "codex-knowledge-candidate-v2"
    assert "### `codex-exec`" in summary_text
    assert "- Status: `ok`" in summary_text
