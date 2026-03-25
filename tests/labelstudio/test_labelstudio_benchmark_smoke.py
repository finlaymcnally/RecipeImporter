from __future__ import annotations

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

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

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
