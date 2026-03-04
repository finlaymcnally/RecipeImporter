from __future__ import annotations

import tests.labelstudio.test_labelstudio_benchmark_helpers as _base

# Reuse shared imports/helpers from the base benchmark helpers module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_interactive_benchmark_single_profile_all_matched_mode_routes_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_answers = iter(["labelstudio_benchmark", "single_offline_all_matched", "exit"])
    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    chosen_settings = cli.RunSettings.from_dict(
        {
            "epub_extractor": "beautifulsoup",
            "instruction_step_segmentation_policy": "off",
        },
        warn_context="test single-profile chooser",
    )
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **_kwargs: chosen_settings,
    )
    monkeypatch.setattr(
        cli,
        "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile all-matched mode should not resolve Label Studio credentials."
            )
        ),
    )
    monkeypatch.setattr(
        cli,
        "_interactive_all_method_benchmark",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile all-matched mode should not route to all-method runner."
            )
        ),
    )

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "_interactive_single_profile_all_matched_benchmark",
        lambda **kwargs: captured.update(kwargs) or True,
    )

    saved_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        cli,
        "save_last_run_settings",
        lambda *args, **_kwargs: saved_calls.append(args),
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
    assert len(saved_calls) == 1
    assert saved_calls[0][0] == "benchmark"


def test_interactive_benchmark_single_profile_selected_matched_mode_routes_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_answers = iter(["labelstudio_benchmark", "single_offline_selected_matched", "exit"])
    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    chosen_settings = cli.RunSettings.from_dict(
        {
            "epub_extractor": "beautifulsoup",
            "instruction_step_segmentation_policy": "off",
        },
        warn_context="test single-profile selected chooser",
    )
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **_kwargs: chosen_settings,
    )
    monkeypatch.setattr(
        cli,
        "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile selected mode should not resolve Label Studio credentials."
            )
        ),
    )
    monkeypatch.setattr(
        cli,
        "_interactive_all_method_benchmark",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "Single-profile selected mode should not route to all-method runner."
            )
        ),
    )

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "_interactive_single_profile_all_matched_benchmark",
        lambda **kwargs: captured.update(kwargs) or True,
    )

    saved_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        cli,
        "save_last_run_settings",
        lambda *args, **_kwargs: saved_calls.append(args),
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
    assert len(saved_calls) == 1
    assert saved_calls[0][0] == "benchmark"


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
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    monkeypatch.setattr(cli, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-02-28_03.30.00"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict({}, warn_context="test")

    benchmark_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "labelstudio_benchmark",
        lambda **kwargs: benchmark_calls.append(kwargs),
    )

    completed = cli._interactive_single_profile_all_matched_benchmark(
        selected_benchmark_settings=selected_settings,
        benchmark_eval_output=benchmark_eval_output,
        processed_output_root=processed_output_root,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert completed is True
    assert len(benchmark_calls) == 2
    assert benchmark_calls[0]["gold_spans"] == gold_a
    assert benchmark_calls[0]["source_file"] == source_a
    assert benchmark_calls[0]["eval_mode"] == cli.BENCHMARK_EVAL_MODE_CANONICAL_TEXT
    assert benchmark_calls[0]["execution_mode"] == cli.BENCHMARK_EXECUTION_MODE_LEGACY
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


def test_interactive_single_profile_all_matched_codex_runs_vanilla_then_codex_per_book(
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
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    monkeypatch.setattr(cli, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-04_11.11.11"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-farm-3pass-v1"},
        warn_context="test single-profile codex",
    )

    benchmark_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "labelstudio_benchmark",
        lambda **kwargs: benchmark_calls.append(kwargs),
    )

    comparison_calls: list[dict[str, object]] = []

    def _fake_write_single_offline_comparison_artifacts(**kwargs):
        comparison_calls.append(dict(kwargs))
        session_root = kwargs["session_root"]
        assert isinstance(session_root, Path)
        return session_root / "codex_vs_vanilla_comparison.json", None

    monkeypatch.setattr(
        cli,
        "_write_single_offline_comparison_artifacts",
        _fake_write_single_offline_comparison_artifacts,
    )
    monkeypatch.setattr(
        cli,
        "_write_benchmark_upload_bundle",
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
    assert len(benchmark_calls) == 2
    assert [call["llm_recipe_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-farm-3pass-v1",
    ]
    assert [call["line_role_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-line-role-v1",
    ]
    assert [call["atomic_block_splitter"] for call in benchmark_calls] == [
        "off",
        "atomic-v1",
    ]
    assert [call["eval_output_dir"] for call in benchmark_calls] == [
        benchmark_eval_output / "single-profile-benchmark" / "01_book_a" / "vanilla",
        benchmark_eval_output / "single-profile-benchmark" / "01_book_a" / "codexfarm",
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
        / "codexfarm",
    ]

    assert len(comparison_calls) == 1
    assert comparison_calls[0]["run_timestamp"] == benchmark_eval_output.name
    assert comparison_calls[0]["session_root"] == (
        benchmark_eval_output / "single-profile-benchmark" / "01_book_a"
    )
    assert comparison_calls[0]["source_file"] == str(source_a)
    assert comparison_calls[0]["vanilla_eval_output_dir"] == (
        benchmark_eval_output / "single-profile-benchmark" / "01_book_a" / "vanilla"
    )
    assert comparison_calls[0]["codex_eval_output_dir"] == (
        benchmark_eval_output / "single-profile-benchmark" / "01_book_a" / "codexfarm"
    )


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
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    monkeypatch.setattr(cli, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-04_10.00.00"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict({}, warn_context="test")

    monkeypatch.setattr(cli, "labelstudio_benchmark", lambda **_kwargs: None)
    upload_bundle_calls: list[dict[str, object]] = []

    def _fake_write_benchmark_upload_bundle(**kwargs):
        upload_bundle_calls.append(dict(kwargs))
        return kwargs.get("output_dir")

    monkeypatch.setattr(
        cli,
        "_write_benchmark_upload_bundle",
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
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    selection_answers = iter([1, "__run_selected__"])
    monkeypatch.setattr(
        cli,
        "_menu_select",
        lambda *_args, **_kwargs: next(selection_answers),
    )
    monkeypatch.setattr(cli, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-02-28_03.30.00"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict({}, warn_context="test")

    benchmark_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "labelstudio_benchmark",
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
    monkeypatch.setattr(
        cli,
        "_resolve_all_method_targets",
        lambda _output_dir: (targets, []),
    )
    selection_answers = iter([1, "__run_selected__"])
    monkeypatch.setattr(
        cli,
        "_menu_select",
        lambda *_args, **_kwargs: next(selection_answers),
    )
    monkeypatch.setattr(cli, "_prompt_confirm", lambda *_args, **_kwargs: True)

    benchmark_eval_output = tmp_path / "golden" / "2026-03-04_11.22.22"
    processed_output_root = tmp_path / "processed"
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-farm-3pass-v1"},
        warn_context="test single-profile selected codex",
    )

    benchmark_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "labelstudio_benchmark",
        lambda **kwargs: benchmark_calls.append(kwargs),
    )
    monkeypatch.setattr(
        cli,
        "_write_single_offline_comparison_artifacts",
        lambda **kwargs: (kwargs["session_root"] / "codex_vs_vanilla_comparison.json", None),
    )
    monkeypatch.setattr(
        cli,
        "_write_benchmark_upload_bundle",
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
        "codex-farm-3pass-v1",
    ]
    assert [call["eval_output_dir"] for call in benchmark_calls] == [
        benchmark_eval_output / "single-profile-benchmark" / "01_book_b" / "vanilla",
        benchmark_eval_output / "single-profile-benchmark" / "01_book_b" / "codexfarm",
    ]
