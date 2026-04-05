from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _base

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_interactive_benchmark_single_profile_all_matched_mode_routes_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_answers = iter(["labelstudio_benchmark", "all_matched_books", "exit"])
    _patch_cli_attr(monkeypatch, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {})
    chosen_settings = cli.RunSettings.from_dict(
        {
            "epub_extractor": "beautifulsoup",
        },
        warn_context="test single-profile chooser",
    )
    _patch_cli_attr(monkeypatch, "choose_run_settings",
        lambda **_kwargs: chosen_settings,
    )
    _patch_cli_attr(monkeypatch, "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile all-matched mode should not resolve Label Studio credentials."
            )
        ),
    )
    _patch_cli_attr(monkeypatch, "_interactive_all_method_benchmark",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile all-matched mode should not route to all-method runner."
            )
        ),
    )

    captured: dict[str, object] = {}
    _patch_cli_attr(monkeypatch, "_interactive_single_profile_all_matched_benchmark",
        lambda **kwargs: captured.update(kwargs) or True,
    )

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert isinstance(captured.get("selected_benchmark_settings"), cli.RunSettings)
    assert (
        captured["selected_benchmark_settings"].to_run_config_dict()
        == chosen_settings.to_run_config_dict()
    )
    assert captured["processed_output_root"] == cli.DEFAULT_INTERACTIVE_OUTPUT
    assert captured["write_markdown"] is True
    assert captured["write_label_studio_tasks"] is False
    assert captured["allow_subset_selection"] is False


def test_interactive_benchmark_single_profile_selected_matched_mode_routes_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_answers = iter(["labelstudio_benchmark", "selected_matched_books", "exit"])
    _patch_cli_attr(monkeypatch, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {})
    chosen_settings = cli.RunSettings.from_dict(
        {
            "epub_extractor": "beautifulsoup",
        },
        warn_context="test single-profile selected chooser",
    )
    _patch_cli_attr(monkeypatch, "choose_run_settings",
        lambda **_kwargs: chosen_settings,
    )
    _patch_cli_attr(monkeypatch, "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile selected mode should not resolve Label Studio credentials."
            )
        ),
    )
    _patch_cli_attr(monkeypatch, "_interactive_all_method_benchmark",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile selected mode should not route to all-method runner."
            )
        ),
    )

    captured: dict[str, object] = {}
    _patch_cli_attr(monkeypatch, "_interactive_single_profile_all_matched_benchmark",
        lambda **kwargs: captured.update(kwargs) or True,
    )

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert isinstance(captured.get("selected_benchmark_settings"), cli.RunSettings)
    assert (
        captured["selected_benchmark_settings"].to_run_config_dict()
        == chosen_settings.to_run_config_dict()
    )
    assert captured["processed_output_root"] == cli.DEFAULT_INTERACTIVE_OUTPUT
    assert captured["write_markdown"] is True
    assert captured["write_label_studio_tasks"] is False
    assert captured["allow_subset_selection"] is True


def test_interactive_single_profile_all_matched_benchmark_runs_each_target_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b = tmp_path / "Book B.docx"
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_b.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="gold-a",
        ),
        cli.AllMethodTarget(
            gold_spans_path=gold_b,
            source_file=source_b,
            source_file_name=source_b.name,
            gold_display="gold-b",
        ),
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-02-28_03.30.00"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test",
    )

    benchmark_calls: list[dict[str, object]] = []
    publisher, publication_capture = _make_lightweight_single_profile_publisher()
    _patch_cli_attr(
        monkeypatch,
        "_run_prediction_with_reuse",
        lambda **kwargs: (
            kwargs["execute_prediction"]()
            or {
                "prediction_result_source": "executed",
                "prediction_reuse_scope": "executed",
                "prediction_reuse_key": "test-key",
                "prediction_reuse_cache_path": str(tmp_path / ".prediction_reuse_cache" / "test-key.json"),
                "prediction_reuse_copy_seconds": 0.0,
            }
        ),
    )
    _patch_cli_attr(monkeypatch, "labelstudio_benchmark",
        lambda **kwargs: benchmark_calls.append(kwargs),
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
        publisher=publisher,
    )

    assert completed is True
    assert len(benchmark_calls) == 2
    assert benchmark_calls[0]["gold_spans"] == gold_a
    assert benchmark_calls[0]["source_file"] == source_a
    assert benchmark_calls[0]["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
    assert benchmark_calls[0]["no_upload"] is True
    assert benchmark_calls[0]["eval_output_dir"] == (
        benchmark_eval_output / "single-profile-benchmark" / "01_book_a"
    )
    assert benchmark_calls[0]["processed_output_dir"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "single-profile-benchmark"
        / "01_book_a"
    )
    assert benchmark_calls[1]["gold_spans"] == gold_b
    assert benchmark_calls[1]["source_file"] == source_b
    assert benchmark_calls[1]["eval_output_dir"] == (
        benchmark_eval_output / "single-profile-benchmark" / "02_book_b"
    )
    assert publication_capture["results"]


def test_interactive_single_profile_parallel_uses_shared_spinner_dashboard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b = tmp_path / "Book B.docx"
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_b.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="gold-a",
        ),
        cli.AllMethodTarget(
            gold_spans_path=gold_b,
            source_file=source_b,
            source_file_name=source_b.name,
            gold_display="gold-b",
        ),
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-04_02.30.00"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test single-profile slots",
    )

    observed_live_slot_overrides: list[int | None] = []
    observed_suppress_spinner: list[bool] = []
    observed_suppress_summary: list[bool] = []
    observed_suppress_dashboard_refresh: list[bool] = []
    observed_progress_callbacks: list[bool] = []

    def _fake_labelstudio_benchmark(**_kwargs: object) -> None:
        observed_live_slot_overrides.append(cli._BENCHMARK_LIVE_STATUS_SLOTS.get())
        observed_suppress_spinner.append(bool(cli._BENCHMARK_SUPPRESS_SPINNER.get()))
        observed_suppress_summary.append(bool(cli._BENCHMARK_SUPPRESS_SUMMARY.get()))
        observed_suppress_dashboard_refresh.append(
            bool(cli._BENCHMARK_SUPPRESS_DASHBOARD_REFRESH.get())
        )
        progress_callback = cli._BENCHMARK_PROGRESS_CALLBACK.get()
        observed_progress_callbacks.append(callable(progress_callback))
        if callable(progress_callback):
            progress_callback(
                "codex-farm recipe.correction.compact.v1 task 1/2 | "
                "running 1 | active [r0001.json]"
            )
            progress_callback("Evaluating predictions... task 2/2")

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", _fake_labelstudio_benchmark)
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )
    captured_status: dict[str, object] = {}

    def _fake_run_with_progress_status(**kwargs: object):
        captured_status["initial_status"] = kwargs.get("initial_status")
        captured_status["progress_prefix"] = kwargs.get("progress_prefix")
        captured_status["telemetry_path"] = kwargs.get("telemetry_path")
        run_callable = kwargs.get("run")
        assert callable(run_callable)
        snapshots: list[str] = []
        captured_status["snapshots"] = snapshots
        return run_callable(snapshots.append)

    _patch_cli_attr(monkeypatch, "_run_with_progress_status", _fake_run_with_progress_status)
    refresh_calls: list[dict[str, object]] = []
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write",
        lambda **kwargs: refresh_calls.append(dict(kwargs)),
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert completed is True
    assert len(observed_live_slot_overrides) == 2
    assert observed_live_slot_overrides == [None, None]
    assert observed_suppress_spinner == [True, True]
    assert observed_suppress_summary == [True, True]
    assert observed_suppress_dashboard_refresh == [True, True]
    assert observed_progress_callbacks == [True, True]
    assert captured_status["initial_status"] == "Running single-profile benchmark..."
    assert captured_status["progress_prefix"] == "Single-profile benchmark"
    assert captured_status["telemetry_path"] == (
        benchmark_eval_output
        / "single-profile-benchmark"
        / cli.PROCESSING_TIMESERIES_FILENAME
    )
    snapshots = captured_status.get("snapshots")
    assert isinstance(snapshots, list)
    assert snapshots
    assert any("books:" in snapshot for snapshot in snapshots)
    assert any("w01" in snapshot for snapshot in snapshots)
    assert len(refresh_calls) == 1
    assert refresh_calls[0]["csv_path"] == cli.history_csv_for_output(
        processed_output_root
        / benchmark_eval_output.name
        / "single-profile-benchmark"
        / cli._DASHBOARD_REFRESH_SENTINEL_DIRNAME
    )
    assert refresh_calls[0]["output_root"] == processed_output_root
    assert refresh_calls[0]["dashboard_out_dir"] == (
        cli.history_root_for_output(processed_output_root) / "dashboard"
    )
    assert refresh_calls[0]["reason"] == "single-profile benchmark variant batch append"


def test_print_codex_decision_is_suppressed_inside_benchmark_summary_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = cli.resolve_codex_execution_policy(
        "labelstudio_benchmark",
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
        },
        allow_codex=True,
    )
    captured: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: captured.append(str(message)),
    )

    cli._print_codex_decision(policy)
    assert captured

    captured.clear()
    with cli._benchmark_progress_overrides(suppress_summary=True):
        cli._print_codex_decision(policy)

    assert captured == []


def test_interactive_single_profile_all_matched_codex_runs_vanilla_then_codex_exec_per_book(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="gold-a",
        ),
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-04_11.11.11"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "multi_recipe_splitter": "rules_v1",
            "pdf_ocr_policy": "auto",
            "epub_unstructured_html_parser_version": "v2",
            "epub_unstructured_skip_headers_footers": False,
        },
        warn_context="test single-profile codex",
    )

    benchmark_calls: list[dict[str, object]] = []
    prep_bundle_calls: list[dict[str, object]] = []
    prep_bundle = SimpleNamespace(
        manifest_path=tmp_path / "prep-cache" / "bundle.json",
        prep_key="prep-key-123",
        cache_hit=False,
    )
    _patch_cli_attr(monkeypatch, "labelstudio_benchmark",
        lambda **kwargs: benchmark_calls.append(kwargs),
    )
    _patch_cli_attr(
        monkeypatch,
        "resolve_or_build_deterministic_prep_bundle",
        lambda **kwargs: prep_bundle_calls.append(dict(kwargs)) or prep_bundle,
    )

    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

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
    assert [call["section_detector_backend"] for call in benchmark_calls] == [
        "shared_v1",
        "shared_v1",
    ]
    assert [call["multi_recipe_splitter"] for call in benchmark_calls] == [
        "rules_v1",
        "rules_v1",
    ]
    assert [call["instruction_step_segmentation_policy"] for call in benchmark_calls] == [
        "always",
        "always",
    ]
    assert [call["instruction_step_segmenter"] for call in benchmark_calls] == [
        "heuristic_v1",
        "heuristic_v1",
    ]
    assert [call["pdf_ocr_policy"] for call in benchmark_calls] == [
        "off",
        "off",
    ]
    assert [call["epub_unstructured_html_parser_version"] for call in benchmark_calls] == [
        "v1",
        "v1",
    ]
    assert [call["epub_unstructured_skip_headers_footers"] for call in benchmark_calls] == [
        True,
        True,
    ]
    assert [call["eval_output_dir"] for call in benchmark_calls] == [
        benchmark_eval_output / "single-profile-benchmark" / "01_book_a" / "vanilla",
        benchmark_eval_output / "single-profile-benchmark" / "01_book_a" / "codex-exec",
    ]
    assert [call["processed_output_dir"] for call in benchmark_calls] == [
        processed_output_root
        / benchmark_eval_output.name
        / "single-profile-benchmark"
        / "01_book_a"
        / "vanilla",
        processed_output_root
        / benchmark_eval_output.name
        / "single-profile-benchmark"
        / "01_book_a"
        / "codex-exec",
    ]
    assert [call["deterministic_prep_manifest_path"] for call in benchmark_calls] == [
        prep_bundle.manifest_path,
        prep_bundle.manifest_path,
    ]


def test_interactive_single_profile_all_matched_benchmark_writes_group_upload_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b = tmp_path / "Book B.docx"
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_b.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="gold-a",
        ),
        cli.AllMethodTarget(
            gold_spans_path=gold_b,
            source_file=source_b,
            source_file_name=source_b.name,
            gold_display="gold-b",
        ),
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-04_10.00.00"
    processed_output_root = tmp_path / "processed"
    selected_settings = _benchmark_test_run_settings(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test group upload bundle codex",
    )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", lambda **_kwargs: None)
    upload_bundle_calls: list[dict[str, object]] = []

    def _fake_write_benchmark_upload_bundle(**kwargs):
        upload_bundle_calls.append(dict(kwargs))
        return kwargs.get("output_dir")

    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        _fake_write_benchmark_upload_bundle,
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert completed is True
    assert len(upload_bundle_calls) == 3
    group_call = next(
        call
        for call in upload_bundle_calls
        if call.get("source_root")
        == (benchmark_eval_output / "single-profile-benchmark")
    )
    assert group_call.get("high_level_only") is True
    assert group_call.get("target_bundle_size_bytes") == (
        cli.BENCHMARK_GROUP_UPLOAD_BUNDLE_TARGET_BYTES
    )


def test_interactive_single_profile_vanilla_skips_oracle_bundle_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b = tmp_path / "Book B.docx"
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_b.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="gold-a",
        ),
        cli.AllMethodTarget(
            gold_spans_path=gold_b,
            source_file=source_b,
            source_file_name=source_b.name,
            gold_display="gold-b",
        ),
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-05_23.01.17"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="test oracle group upload",
    )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", lambda **_kwargs: None)

    upload_bundle_calls: list[dict[str, object]] = []

    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: upload_bundle_calls.append(dict(kwargs)),
    )
    launch_calls: list[dict[str, object]] = []
    _patch_cli_attr(monkeypatch, "_start_benchmark_bundle_oracle_upload_background",
        lambda **kwargs: launch_calls.append(dict(kwargs)),
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert completed is True
    assert upload_bundle_calls == []
    assert launch_calls == []


def test_interactive_single_profile_codex_uploads_group_oracle_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b = tmp_path / "Book B.docx"
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_b.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="gold-a",
        ),
        cli.AllMethodTarget(
            gold_spans_path=gold_b,
            source_file=source_b,
            source_file_name=source_b.name,
            gold_display="gold-b",
        ),
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-05_23.01.17"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test oracle group upload codex",
    )

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", lambda **_kwargs: None)

    group_bundle_dir = (
        benchmark_eval_output
        / "single-profile-benchmark"
        / cli.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )

    def _fake_write_benchmark_upload_bundle(**kwargs):
        output_dir = kwargs.get("output_dir")
        assert isinstance(output_dir, Path)
        if output_dir == group_bundle_dir:
            return group_bundle_dir
        return output_dir

    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        _fake_write_benchmark_upload_bundle,
    )
    launch_calls: list[dict[str, object]] = []
    _patch_cli_attr(monkeypatch, "_start_benchmark_bundle_oracle_upload_background",
        lambda **kwargs: launch_calls.append(dict(kwargs)),
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert completed is True
    assert launch_calls == [
        {
            "bundle_dir": group_bundle_dir,
            "scope": "single_profile_group",
        }
    ]


def test_interactive_single_profile_selected_matched_benchmark_runs_selected_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b = tmp_path / "Book B.docx"
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_b.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="gold-a",
        ),
        cli.AllMethodTarget(
            gold_spans_path=gold_b,
            source_file=source_b,
            source_file_name=source_b.name,
            gold_display="gold-b",
        ),
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    selection_answers = iter([1, "__run_selected__"])
    _patch_cli_attr(monkeypatch, "_menu_select",
        lambda *_args, **_kwargs: next(selection_answers),
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-02-28_03.30.00"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test",
    )

    benchmark_calls: list[dict[str, object]] = []
    _patch_cli_attr(monkeypatch, "labelstudio_benchmark",
        lambda **kwargs: benchmark_calls.append(kwargs),
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
        allow_subset_selection=True,
    )

    assert completed is True
    assert len(benchmark_calls) == 1
    assert benchmark_calls[0]["gold_spans"] == gold_b
    assert benchmark_calls[0]["source_file"] == source_b
    assert benchmark_calls[0]["eval_output_dir"] == (
        benchmark_eval_output / "single-profile-benchmark" / "01_book_b"
    )
    assert benchmark_calls[0]["processed_output_dir"] == (
        processed_output_root
        / benchmark_eval_output.name
        / "single-profile-benchmark"
        / "01_book_b"
    )


def test_interactive_single_profile_selected_matched_uses_concise_book_labels(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b = tmp_path / "Book B.docx"
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_b.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="dinnerfor2cutdown",
        ),
        cli.AllMethodTarget(
            gold_spans_path=gold_b,
            source_file=source_b,
            source_file_name=source_b.name,
            gold_display="thefoodlabcutdown",
        ),
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    observed_titles: list[str] = []

    def _fake_menu_select(_prompt: str, **kwargs):
        for choice in kwargs.get("choices", []):
            title = getattr(choice, "title", None)
            if isinstance(title, str):
                observed_titles.append(title)
        return cli.BACK_ACTION

    _patch_cli_attr(monkeypatch, "_menu_select", _fake_menu_select)

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=cli.RunSettings.from_dict(
            {"llm_recipe_pipeline": "off"},
            warn_context="test matched label rendering",
        ),
        benchmark_eval_output=tmp_path / "golden" / "2026-03-06_01.02.03",
        processed_output_root=tmp_path / "processed",
        write_markdown=False,
        write_label_studio_tasks=False,
        allow_subset_selection=True,
    )

    assert completed is False
    assert "Run all matched books" in observed_titles
    assert "[ ] 01) dinnerfor2cutdown" in observed_titles
    assert "[ ] 02) thefoodlabcutdown" in observed_titles


def test_interactive_single_profile_selected_matched_codex_runs_pair_for_selected_book(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Book A.epub"
    source_a.write_text("a", encoding="utf-8")
    source_b = tmp_path / "Book B.docx"
    source_b.write_text("b", encoding="utf-8")
    gold_a = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold_a.parent.mkdir(parents=True, exist_ok=True)
    gold_a.write_text("{}\n", encoding="utf-8")
    gold_b = tmp_path / "gold-b" / "exports" / "freeform_span_labels.jsonl"
    gold_b.parent.mkdir(parents=True, exist_ok=True)
    gold_b.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold_a,
            source_file=source_a,
            source_file_name=source_a.name,
            gold_display="gold-a",
        ),
        cli.AllMethodTarget(
            gold_spans_path=gold_b,
            source_file=source_b,
            source_file_name=source_b.name,
            gold_display="gold-b",
        ),
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    selection_answers = iter([1, "__run_selected__"])
    _patch_cli_attr(monkeypatch, "_menu_select",
        lambda *_args, **_kwargs: next(selection_answers),
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-04_11.22.22"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test single-profile selected codex",
    )

    benchmark_calls: list[dict[str, object]] = []
    _patch_cli_attr(monkeypatch, "labelstudio_benchmark",
        lambda **kwargs: benchmark_calls.append(kwargs),
    )
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
        allow_subset_selection=True,
    )

    assert completed is True
    assert len(benchmark_calls) == 2
    assert [call["source_file"] for call in benchmark_calls] == [source_b, source_b]
    assert [call["llm_recipe_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-recipe-shard-v1",
    ]
    assert [call["eval_output_dir"] for call in benchmark_calls] == [
        benchmark_eval_output / "single-profile-benchmark" / "01_book_b" / "vanilla",
        benchmark_eval_output / "single-profile-benchmark" / "01_book_b" / "codex-exec",
    ]


def test_interactive_single_profile_formats_codex_exec_precheck_failure_for_display(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "Book A.epub"
    source.write_text("a", encoding="utf-8")
    gold = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("{}\n", encoding="utf-8")

    targets = [
        cli.AllMethodTarget(
            gold_spans_path=gold,
            source_file=source,
            source_file_name=source.name,
            gold_display="gold-a",
        )
    ]
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **kwargs: kwargs.get("output_dir"),
    )
    _patch_cli_attr(monkeypatch, "_start_benchmark_bundle_oracle_upload_background",
        lambda **_kwargs: None,
    )

    failure_text = (
        "codex-farm failed for recipe.correction.compact.v1 "
        "(subprocess_exit=1, out_dir=/tmp/recipe_correction/out, "
        "stderr_summary=codex execution precheck failed before `process`: "
        "OpenAI Codex v0.111.0 (research preview); "
        "ERROR: You've hit your usage limit for GPT-5.3-Codex-Spark.)"
    )

    def _fake_labelstudio_benchmark(**kwargs):
        if kwargs.get("llm_recipe_pipeline") == "codex-recipe-shard-v1":
            raise RuntimeError(failure_text)
        return None

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark", _fake_labelstudio_benchmark)

    captured_messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: captured_messages.append(str(message)),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda *_args, **_kwargs: None)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-06_15.05.00"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test single-profile codex failure formatting",
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert completed is True
    failure_messages = [
        message
        for message in captured_messages
        if "Single-profile benchmark failed for" in message
    ]
    assert len(failure_messages) == 1
    assert "codex-exec=codex-farm recipe.correction.compact.v1:" in failure_messages[0]
    assert "codex execution precheck failed before `process`" in failure_messages[0]
    assert "usage limit for GPT-5.3-Codex-Spark" in failure_messages[0]
    assert "out_dir=/tmp/recipe_correction/out" not in failure_messages[0]


def test_interactive_single_profile_reuses_prediction_artifacts_across_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "Book A.epub"
    source.write_text("a", encoding="utf-8")
    gold = tmp_path / "gold-a" / "exports" / "freeform_span_labels.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("{}\n", encoding="utf-8")
    target = cli.AllMethodTarget(
        gold_spans_path=gold,
        source_file=source,
        source_file_name=source.name,
        gold_display="gold-a",
    )
    _patch_cli_attr(monkeypatch, "_resolve_all_method_targets", lambda _output_dir: ([target], []))
    _patch_cli_attr(monkeypatch, "_prompt_confirm", lambda *_args, **_kwargs: True)
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

    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test single-profile prediction reuse",
    )
    processed_output_root = tmp_path / "processed"
    publisher, publication_capture = _make_lightweight_single_profile_publisher()

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

    first_output = tmp_path / "golden" / "2026-04-04_23.20.00"
    second_output = tmp_path / "golden" / "2026-04-04_23.21.00"
    first_completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=first_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
        publisher=publisher,
    )
    second_completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=second_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
        publisher=publisher,
    )

    assert first_completed is True
    assert second_completed is True
    assert len(benchmark_calls) == 1
    second_eval_dir = second_output / "single-profile-benchmark" / "01_book_a"
    second_processed_dir = (
        processed_output_root / second_output.name / "single-profile-benchmark" / "01_book_a"
    )
    assert (second_eval_dir / "prediction-records.jsonl").exists()
    assert (second_processed_dir / "processed-marker.txt").exists()
    assert publication_capture["results"]
