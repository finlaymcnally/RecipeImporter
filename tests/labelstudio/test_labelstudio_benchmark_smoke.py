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
    assert benchmark_calls[0]["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT


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

    assert len(benchmark_calls) == 2
    assert [call["llm_recipe_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-recipe-shard-v1",
    ]
    assert [call["allow_codex"] for call in benchmark_calls] == [False, True]
    assert [call["codex_farm_model"] for call in benchmark_calls] == [
        "gpt-5.3-codex-spark",
        "gpt-5.3-codex-spark",
    ]
    assert [call["codex_farm_reasoning_effort"] for call in benchmark_calls] == [
        "low",
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
    canonical_text_path = gold_export_root / "canonical_text.txt"
    canonical_span_labels_path = gold_export_root / "canonical_span_labels.jsonl"
    canonical_text_path.write_text("Title\nBody\n", encoding="utf-8")
    canonical_span_labels_path.write_text("{}\n", encoding="utf-8")

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
            block_labels={"0": "RECIPE_TITLE", "1": "OTHER"},
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
            "stage_block_predictions_path": fixture_paths["stage_predictions_path"],
            "extracted_archive_path": fixture_paths["extracted_archive_path"],
            "timing": {"prediction_seconds": 0.25 if variant_slug == "codex-exec" else 0.15},
        }

    def _fake_ensure_canonical_gold_artifacts(*, export_root: Path):
        assert export_root == gold_export_root
        return {
            "canonical_text_path": canonical_text_path,
            "canonical_span_labels_path": canonical_span_labels_path,
        }

    def _fake_evaluate_canonical_text(**kwargs):
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
    _patch_cli_attr(
        monkeypatch,
        "ensure_canonical_gold_artifacts",
        _fake_ensure_canonical_gold_artifacts,
    )
    monkeypatch.setattr(bench_artifacts, "evaluate_canonical_text", _fake_evaluate_canonical_text)
    monkeypatch.setattr(bench_artifacts, "format_canonical_eval_report_md", lambda *_: "report")
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

    assert len(generate_calls) == 2
    assert [call["llm_recipe_pipeline"] for call in generate_calls] == [
        "off",
        "codex-recipe-shard-v1",
    ]
    assert [call["allow_codex"] for call in generate_calls] == [False, True]
    assert [call["codex_farm_model"] for call in generate_calls] == [
        "gpt-5.3-codex-spark",
        "gpt-5.3-codex-spark",
    ]
    assert [call["codex_farm_reasoning_effort"] for call in generate_calls] == [
        "low",
        "low",
    ]

    comparison_paths = list(benchmark_root.rglob("codex_vs_vanilla_comparison.json"))
    assert len(comparison_paths) == 1
    comparison_payload = json.loads(comparison_paths[0].read_text(encoding="utf-8"))
    assert Path(comparison_payload["variants"]["codex-exec"]["eval_output_dir"]).name == "codex-exec"
    assert Path(comparison_payload["variants"]["vanilla"]["eval_output_dir"]).name == "vanilla"

    summary_paths = list(benchmark_root.rglob("single_book_summary.md"))
    assert len(summary_paths) == 1
    summary_text = summary_paths[0].read_text(encoding="utf-8")
    assert "### `vanilla`" in summary_text
    assert "### `codex-exec`" in summary_text
