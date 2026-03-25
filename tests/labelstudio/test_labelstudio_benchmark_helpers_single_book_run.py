from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
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
    processed_output_root = tmp_path / "output"
    source_path = str(tmp_path / "book.epub")

    benchmark_calls: list[dict[str, object]] = []
    refresh_calls: list[dict[str, object]] = []

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
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write",
        lambda **kwargs: refresh_calls.append(kwargs),
    )

    _patch_cli_attr(monkeypatch, "_write_single_book_starter_pack",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("starter pack should not run by default for single-book")
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
    return {
        "completed": completed,
        "benchmark_calls": benchmark_calls,
        "refresh_calls": refresh_calls,
        "benchmark_eval_output": benchmark_eval_output,
        "processed_output_root": processed_output_root,
    }


def test_interactive_single_book_codex_enabled_runs_only_codexfarm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_single_book_codex_enabled_fixture(monkeypatch, tmp_path)
    completed = fixture["completed"]
    benchmark_calls = fixture["benchmark_calls"]
    benchmark_eval_output = fixture["benchmark_eval_output"]
    processed_output_root = fixture["processed_output_root"]

    assert completed is True
    assert len(benchmark_calls) == 2
    assert [call["llm_recipe_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-recipe-shard-v1",
    ]
    assert [call["line_role_pipeline"] for call in benchmark_calls] == [
        "off",
        "codex-line-role-shard-v1",
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
    assert [call["eval_output_dir"] for call in benchmark_calls] == [
        benchmark_eval_output / "single-book-benchmark" / "vanilla",
        benchmark_eval_output / "single-book-benchmark" / "codexfarm",
    ]
    assert [call["processed_output_dir"] for call in benchmark_calls] == [
        processed_output_root
        / benchmark_eval_output.name
        / "single-book-benchmark"
        / "vanilla",
        processed_output_root
        / benchmark_eval_output.name
        / "single-book-benchmark"
        / "codexfarm",
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
        / "codex_vs_vanilla_comparison.json"
    )
    comparison_md = (
        benchmark_eval_output
        / "single-book-benchmark"
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

    assert [slug for slug, _settings in variants] == ["vanilla", "codexfarm"]
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
            "line_role_pipeline": "codex-line-role-shard-v1",
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
    assert benchmark_calls[0]["line_role_pipeline"] == "codex-line-role-shard-v1"
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

def test_interactive_single_book_starts_background_oracle_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
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

    session_bundle_dir = (
        benchmark_eval_output
        / "single-book-benchmark"
        / cli.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    _patch_cli_attr(monkeypatch, "_write_benchmark_upload_bundle",
        lambda **_kwargs: session_bundle_dir,
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
    assert launch_calls == [
        {
            "bundle_dir": session_bundle_dir,
            "scope": "single_book",
        }
    ]


def test_interactive_single_book_writes_capped_high_level_upload_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
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
