from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def _capture_interactive_single_book_helper(
    monkeypatch: pytest.MonkeyPatch,
    *,
    return_value: bool = True,
) -> list[dict[str, object]]:
    helper_calls: list[dict[str, object]] = []

    def fake_single_book_helper(**kwargs):
        helper_calls.append(dict(kwargs))
        return return_value

    _patch_cli_attr(monkeypatch, "_interactive_single_book_benchmark",
        fake_single_book_helper,
    )
    return helper_calls


def test_resolve_interactive_labelstudio_settings_uses_saved_credentials_without_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = {
        "label_studio_url": "http://localhost:8080",
        "label_studio_api_key": "saved-key",
    }
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("URL prompt should not run when creds are already saved.")
        ),
    )
    monkeypatch.setattr(
        cli.questionary,
        "password",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("API key prompt should not run when creds are already saved.")
        ),
    )
    _patch_cli_attr(monkeypatch, "_preflight_labelstudio_credentials", lambda *_: None)

    url, api_key = cli._resolve_interactive_labelstudio_settings(settings)

    assert url == "http://localhost:8080"
    assert api_key == "saved-key"

def test_resolve_interactive_labelstudio_settings_prompts_and_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings: dict[str, str] = {}
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)

    class _Prompt:
        def __init__(self, value: str):
            self._value = value

        def ask(self):
            return self._value

    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *_args, **_kwargs: _Prompt("http://localhost:8080"),
    )
    monkeypatch.setattr(
        cli.questionary,
        "password",
        lambda *_args, **_kwargs: _Prompt("new-key"),
    )
    saved_snapshots: list[dict[str, str]] = []
    _patch_cli_attr(monkeypatch, "_save_settings",
        lambda payload: saved_snapshots.append(dict(payload)),
    )
    _patch_cli_attr(monkeypatch, "_preflight_labelstudio_credentials", lambda *_: None)

    url, api_key = cli._resolve_interactive_labelstudio_settings(settings)

    assert url == "http://localhost:8080"
    assert api_key == "new-key"
    assert settings["label_studio_url"] == "http://localhost:8080"
    assert settings["label_studio_api_key"] == "new-key"
    assert saved_snapshots[-1]["label_studio_url"] == "http://localhost:8080"
    assert saved_snapshots[-1]["label_studio_api_key"] == "new-key"

def test_resolve_interactive_labelstudio_settings_returns_none_on_prompt_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings: dict[str, str] = {}
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)

    class _Prompt:
        def ask(self):
            return None

    monkeypatch.setattr(cli.questionary, "text", lambda *_args, **_kwargs: _Prompt())
    monkeypatch.setattr(
        cli.questionary,
        "password",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("API key prompt should not run after URL prompt cancel.")
        ),
    )

    assert cli._resolve_interactive_labelstudio_settings(settings) is None

def test_resolve_interactive_labelstudio_settings_reprompts_when_saved_creds_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = {
        "label_studio_url": "http://localhost:8080",
        "label_studio_api_key": "stale-key",
    }
    monkeypatch.delenv("LABEL_STUDIO_URL", raising=False)
    monkeypatch.delenv("LABEL_STUDIO_API_KEY", raising=False)

    class _Prompt:
        def __init__(self, value: str):
            self._value = value

        def ask(self):
            return self._value

    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *_args, **_kwargs: _Prompt("http://localhost:8080"),
    )
    monkeypatch.setattr(
        cli.questionary,
        "password",
        lambda *_args, **_kwargs: _Prompt("fresh-key"),
    )
    probe_calls: list[tuple[str, str]] = []

    def fake_preflight(url: str, api_key: str) -> str | None:
        probe_calls.append((url, api_key))
        if api_key == "stale-key":
            return "Label Studio API error 401 on /api/projects?page=1&page_size=100: unauthorized"
        return None

    _patch_cli_attr(monkeypatch, "_preflight_labelstudio_credentials", fake_preflight)
    saved_snapshots: list[dict[str, str]] = []
    _patch_cli_attr(monkeypatch, "_save_settings",
        lambda payload: saved_snapshots.append(dict(payload)),
    )

    url, api_key = cli._resolve_interactive_labelstudio_settings(settings)

    assert url == "http://localhost:8080"
    assert api_key == "fresh-key"
    assert probe_calls == [
        ("http://localhost:8080", "stale-key"),
        ("http://localhost:8080", "fresh-key"),
    ]
    assert settings["label_studio_api_key"] == "fresh-key"
    assert saved_snapshots[-1]["label_studio_api_key"] == "fresh-key"

def test_is_labelstudio_credential_error() -> None:
    assert cli._is_labelstudio_credential_error("Label Studio API error 401 on /api/projects: unauthorized")
    assert cli._is_labelstudio_credential_error("Label Studio API error 403 on /api/projects: forbidden")
    assert not cli._is_labelstudio_credential_error("timed out connecting to host")

def test_interactive_labelstudio_freeform_scope_routes_to_freeform_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_file = tmp_path / "book.epub"
    selected_file.write_text("dummy", encoding="utf-8")

    menu_answers = iter(
        [
            "labelstudio",
            selected_file,
            (True, "annotations", True),
            "span",
            "__default__",
            "__default_effort__",
            "exit",
        ]
    )

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    text_answers = iter(["", "42", "6", "28", "55"])

    class _Prompt:
        def __init__(self, value: str | bool):
            self._value = value

        def ask(self):
            return self._value

    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [selected_file])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {})
    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)
    _patch_cli_attr(monkeypatch, "default_codex_cmd", lambda: "codex exec -")
    _patch_cli_attr(monkeypatch, "codex_account_summary",
        lambda _cmd=None: "prelabel@example.com (pro)",
    )
    _patch_cli_attr(monkeypatch, "default_codex_model", lambda cmd=None: None)
    _patch_cli_attr(monkeypatch, "list_codex_models", lambda cmd=None: [])
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", tmp_path / "golden")
    _patch_cli_attr(monkeypatch, "_resolve_interactive_labelstudio_settings",
        lambda *_: ("http://example", "api-key"),
    )
    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *args, **kwargs: _Prompt(next(text_answers)),
    )

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 10,
            "tasks_uploaded": 10,
            "run_root": tmp_path / "out",
        }

    _patch_cli_attr(monkeypatch, "run_labelstudio_import", fake_run_labelstudio_import)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["segment_blocks"] == 42
    assert captured["segment_overlap"] == 6
    assert captured["segment_focus_blocks"] == 28
    assert captured["target_task_count"] == 55
    assert captured["prelabel"] is True
    assert captured["prelabel_upload_as"] == "annotations"
    assert captured["prelabel_allow_partial"] is True
    assert captured["prelabel_granularity"] == "span"
    assert captured["prelabel_timeout_seconds"] == cli.DEFAULT_PRELABEL_TIMEOUT_SECONDS
    assert captured["prelabel_workers"] == 15
    assert captured["codex_cmd"] == "codex exec -"
    assert captured["codex_model"] is None
    assert captured["codex_reasoning_effort"] is None
    assert captured["prelabel_track_token_usage"] is True
    assert callable(captured["progress_callback"])
    assert captured["output_dir"] == (tmp_path / "golden" / "sent-to-labelstudio")
    assert captured["overwrite"] is True
    assert captured["resume"] is False

def test_interactive_labelstudio_filters_incompatible_effort_choices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_file = tmp_path / "book.epub"
    selected_file.write_text("dummy", encoding="utf-8")

    menu_answers = iter(
        [
            "labelstudio",
            selected_file,
            (True, "annotations", True),
            "span",
            "gpt-5.3-codex-spark",
            "low",
            "exit",
        ]
    )
    effort_choice_values: list[str] = []

    def fake_menu_select(message: str, *_args, **kwargs):
        if message == "Codex thinking effort for AI prelabeling:":
            for choice in kwargs.get("choices", []):
                value = getattr(choice, "value", None)
                if isinstance(value, str):
                    effort_choice_values.append(value)
        return next(menu_answers)

    text_answers = iter(["", "42", "6", "28", "55"])

    class _Prompt:
        def __init__(self, value: str | bool):
            self._value = value

        def ask(self):
            return self._value

    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [selected_file])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {})
    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)
    _patch_cli_attr(monkeypatch, "default_codex_cmd", lambda: "codex exec -")
    _patch_cli_attr(monkeypatch, "codex_account_summary",
        lambda _cmd=None: "prelabel@example.com (pro)",
    )
    _patch_cli_attr(monkeypatch, "default_codex_model",
        lambda cmd=None: "gpt-5.3-codex-spark",
    )
    _patch_cli_attr(monkeypatch, "default_codex_reasoning_effort",
        lambda cmd=None: "minimal",
    )
    _patch_cli_attr(monkeypatch, "list_codex_models",
        lambda cmd=None: [
            {
                "slug": "gpt-5.3-codex-spark",
                "display_name": "gpt-5.3-codex-spark",
                "description": "Ultra-fast coding model",
                "supported_reasoning_efforts": ["low", "medium", "high", "xhigh"],
            }
        ],
    )
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", tmp_path / "golden")
    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key")
    )
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *args, **kwargs: _Prompt(next(text_answers)),
    )

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 10,
            "tasks_uploaded": 10,
            "run_root": tmp_path / "out",
        }

    _patch_cli_attr(monkeypatch, "run_labelstudio_import", fake_run_labelstudio_import)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["codex_model"] == "gpt-5.3-codex-spark"
    assert captured["codex_reasoning_effort"] == "low"
    assert "__default_effort__" not in effort_choice_values
    assert "minimal" not in effort_choice_values
    assert "none" not in effort_choice_values
    assert effort_choice_values == ["low", "medium", "high", "xhigh"]

def test_interactive_labelstudio_freeform_focus_escape_steps_back_one_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_file = tmp_path / "book.epub"
    selected_file.write_text("dummy", encoding="utf-8")

    menu_answers = iter(
        [
            "labelstudio",
            selected_file,
            (False, "annotations", False),
            "exit",
        ]
    )

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    prompt_answers = iter(
        [
            "",     # project name
            "40",   # segment size
            "5",    # overlap
            None,   # Esc at focus -> back to overlap
            "7",    # overlap after stepping back
            "40",   # focus
            "",     # target task count
        ]
    )
    prompt_messages: list[str] = []

    def fake_prompt_text(message: str, **_kwargs):
        prompt_messages.append(message)
        return next(prompt_answers)

    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [selected_file])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {})
    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)
    _patch_cli_attr(monkeypatch, "_prompt_text", fake_prompt_text)
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", tmp_path / "golden")
    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 10,
            "tasks_uploaded": 10,
            "run_root": tmp_path / "out",
        }

    _patch_cli_attr(monkeypatch, "run_labelstudio_import", fake_run_labelstudio_import)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["segment_blocks"] == 40
    assert captured["segment_overlap"] == 7
    assert captured["segment_focus_blocks"] == 40
    assert prompt_messages.count("Freeform overlap (blocks):") == 2

def test_interactive_benchmark_uses_golden_output_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
            "epub_extractor": "beautifulsoup",
        },
        warn_context="test interactive benchmark vanilla defaults",
    )
    menu_answers = iter(["labelstudio_benchmark", "single_book", "exit"])
    mode_prompts: list[list[str]] = []

    def fake_menu_select(prompt: str, *_args, **_kwargs):
        if prompt == "How would you like to evaluate?":
            mode_prompts.append(
                [str(choice.title) for choice in _kwargs.get("choices", [])]
            )
        return next(menu_answers)

    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings",
        lambda: {"output_dir": str(configured_output), "epub_extractor": "beautifulsoup"},
    )
    _patch_cli_attr(monkeypatch, "choose_run_settings",
        lambda **_kwargs: selected_benchmark_settings,
    )
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)

    def _unexpected_confirm(*_args, **_kwargs):
        raise AssertionError("Interactive benchmark upload should not ask for confirmation.")

    monkeypatch.setattr(cli.questionary, "confirm", _unexpected_confirm)
    helper_calls = _capture_interactive_single_book_helper(monkeypatch)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert len(helper_calls) == 1
    assert helper_calls[0]["benchmark_eval_output"].parent == golden_root / "benchmark-vs-golden"
    assert helper_calls[0]["processed_output_root"] == configured_output
    selected_settings = helper_calls[0]["selected_benchmark_settings"]
    assert isinstance(selected_settings, cli.RunSettings)
    assert selected_settings.llm_recipe_pipeline.value == "off"
    assert selected_settings.line_role_pipeline.value == "off"
    assert selected_settings.atomic_block_splitter.value == "off"
    assert selected_settings.epub_extractor.value == "beautifulsoup"
    assert mode_prompts
    assert not any("offline, no upload" in title for title in mode_prompts[0])
    assert not any("uploads to Label Studio" in title for title in mode_prompts[0])
    assert not any("All method benchmark" in title for title in mode_prompts[0])

def test_interactive_benchmark_single_book_mode_skips_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
            "epub_extractor": "beautifulsoup",
        },
        warn_context="test interactive benchmark vanilla defaults",
    )
    menu_answers = iter(["labelstudio_benchmark", "single_book", "exit"])

    _patch_cli_attr(monkeypatch, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings",
        lambda: {"output_dir": str(configured_output), "epub_extractor": "beautifulsoup"},
    )
    _patch_cli_attr(monkeypatch, "choose_run_settings",
        lambda **_kwargs: selected_benchmark_settings,
    )
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)
    _patch_cli_attr(monkeypatch, "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("Offline benchmark mode should not resolve Label Studio credentials.")
        ),
    )
    helper_calls = _capture_interactive_single_book_helper(monkeypatch)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert len(helper_calls) == 1
    assert helper_calls[0]["benchmark_eval_output"].parent == golden_root / "benchmark-vs-golden"
    assert helper_calls[0]["processed_output_root"] == configured_output


def test_interactive_benchmark_single_book_codex_pipeline_passes_settings_to_helper_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_model": "gpt-5.3-codex-spark",
            "codex_farm_reasoning_effort": "low",
        },
        warn_context="test interactive benchmark codex single-book defaults",
    )
    menu_answers = iter(["labelstudio_benchmark", "single_book", "exit"])

    _patch_cli_attr(monkeypatch, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings",
        lambda: {"output_dir": str(configured_output), "epub_extractor": "beautifulsoup"},
    )
    _patch_cli_attr(monkeypatch, "choose_run_settings",
        lambda **_kwargs: selected_benchmark_settings,
    )
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)
    _patch_cli_attr(monkeypatch, "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("Offline benchmark mode should not resolve Label Studio credentials.")
        ),
    )

    helper_calls = _capture_interactive_single_book_helper(monkeypatch)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert len(helper_calls) == 1
    selected_settings = helper_calls[0]["selected_benchmark_settings"]
    assert isinstance(selected_settings, cli.RunSettings)
    assert selected_settings.llm_recipe_pipeline.value == "codex-recipe-shard-v1"
    assert str(selected_settings.codex_farm_model) == "gpt-5.3-codex-spark"
    assert selected_settings.codex_farm_reasoning_effort is not None
    assert selected_settings.codex_farm_reasoning_effort.value == "low"
    assert helper_calls[0]["benchmark_eval_output"].parent == golden_root / "benchmark-vs-golden"
    assert helper_calls[0]["processed_output_root"] == configured_output


def test_interactive_benchmark_enables_per_surface_codex_toggle_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    menu_answers = iter(["labelstudio_benchmark", "single_book", "exit"])
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test interactive benchmark toggle prompt",
    )
    choose_kwargs: dict[str, object] = {}

    _patch_cli_attr(monkeypatch, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings",
        lambda: {"output_dir": str(configured_output), "epub_extractor": "beautifulsoup"},
    )
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)
    _patch_cli_attr(monkeypatch, "choose_run_settings",
        lambda **kwargs: choose_kwargs.update(kwargs) or selected_benchmark_settings,
    )
    _patch_cli_attr(monkeypatch, "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("Offline benchmark mode should not resolve Label Studio credentials.")
        ),
    )
    helper_calls = _capture_interactive_single_book_helper(monkeypatch)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert choose_kwargs["prompt_recipe_pipeline_menu"] is True
    assert choose_kwargs["prompt_codex_ai_settings"] is True
    assert choose_kwargs["prompt_benchmark_llm_surface_toggles"] is True
    assert len(helper_calls) == 1


def test_interactive_generate_dashboard_runs_without_browser_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    menu_answers = iter(["generate_dashboard", "exit"])

    _patch_cli_attr(monkeypatch, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {"output_dir": str(configured_output)})
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)

    monkeypatch.setattr(
        cli.questionary,
        "confirm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Dashboard flow should not ask to open a browser.")
        ),
    )

    captured: dict[str, object] = {}

    def fake_stats_dashboard(**kwargs):
        captured.update(kwargs)

    _patch_cli_attr(monkeypatch, "_stats_dashboard_command",
        lambda: fake_stats_dashboard,
    )

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["output_root"] == configured_output
    assert captured["golden_root"] == golden_root
    assert captured["out_dir"] == configured_output.parent / ".history" / "dashboard"
    assert captured["open_browser"] is False
    assert captured["since_days"] is None
    assert captured["scan_reports"] is False

def test_interactive_benchmark_ignores_existing_eval_artifacts_and_runs_offline_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    golden_root = tmp_path / "golden"
    pred_run = golden_root / "some-run" / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    gold_spans = golden_root / "some-run" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    menu_answers = iter(["labelstudio_benchmark", "single_book", "exit"])
    mode_prompt_count = 0
    mode_titles: list[str] = []
    selected_benchmark_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="test interactive benchmark vanilla defaults",
    )

    def fake_menu_select(prompt: str, *_args, **_kwargs):
        nonlocal mode_prompt_count
        if prompt == "How would you like to evaluate?":
            mode_prompt_count += 1
            mode_titles.extend(str(choice.title) for choice in _kwargs.get("choices", []))
        return next(menu_answers)

    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {})
    _patch_cli_attr(monkeypatch, "choose_run_settings",
        lambda **_kwargs: selected_benchmark_settings,
    )
    _patch_cli_attr(monkeypatch, "DEFAULT_GOLDEN", golden_root)
    _patch_cli_attr(monkeypatch, "_resolve_interactive_labelstudio_settings",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("Offline benchmark mode should not resolve Label Studio credentials.")
        ),
    )
    _patch_cli_attr(monkeypatch, "_discover_freeform_gold_exports", lambda *_: [gold_spans])
    _patch_cli_attr(monkeypatch, "_discover_prediction_runs", lambda *_: [pred_run])
    eval_calls: list[dict[str, object]] = []
    _patch_cli_attr(monkeypatch, "labelstudio_eval", lambda **kwargs: eval_calls.append(kwargs))
    helper_calls = _capture_interactive_single_book_helper(monkeypatch)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert eval_calls == []
    assert len(helper_calls) == 1
    assert helper_calls[0]["benchmark_eval_output"].parent == golden_root / "benchmark-vs-golden"
    assert mode_prompt_count == 1
    assert not any("uploads to Label Studio" in title for title in mode_titles)

def test_interactive_main_menu_does_not_offer_inspect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_values: list[object] = []

    def fake_menu_select(*_args, **_kwargs):
        choices = _kwargs.get("choices", [])
        captured_values.extend(getattr(choice, "value", choice) for choice in choices)
        return "exit"

    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)
    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {})

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert "inspect" not in captured_values
