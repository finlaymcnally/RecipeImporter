from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import questionary
import pytest
import typer
from prompt_toolkit.keys import Keys
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cookimport import cli
from cookimport.cli_ui import run_settings_flow
from cookimport.config.last_run_store import (
    load_qualitysuite_winner_run_settings,
    save_qualitysuite_winner_run_settings,
)
from cookimport.config.run_settings import CodexReasoningEffort
from cookimport import entrypoint


def test_menu_shortcuts_assign_numeric_keys():
    choices = [
        questionary.Choice("Import", value="import"),
        questionary.Separator(),
        questionary.Choice("Exit", value="exit"),
    ]

    option_count = cli._menu_option_count(choices)
    shortcuts = cli._menu_shortcut_bindings(choices)
    assert option_count == 2
    assert shortcuts["1"] == "import"
    assert shortcuts["2"] == "exit"


def test_interactive_main_menu_includes_generate_dashboard(monkeypatch):
    captured_choice_values: list[str] = []

    def fake_menu_select(*args, choices, **kwargs):
        for choice in choices:
            if isinstance(choice, questionary.Separator):
                continue
            captured_choice_values.append(str(choice.value))
        return "exit"

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])

    with pytest.raises(typer.Exit):
        cli._interactive_mode()

    assert "generate_dashboard" in captured_choice_values


def test_stats_dashboard_direct_call_unwraps_typer_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured_collect_kwargs: dict[str, object] = {}
    out_dir = tmp_path / "dashboard"

    def _fake_collect_dashboard_data(**kwargs):
        captured_collect_kwargs.update(kwargs)
        return SimpleNamespace(collector_warnings=[])

    def _fake_render_dashboard(render_out_dir, _data):
        assert render_out_dir == out_dir
        return render_out_dir / "index.html"

    def _unexpected_server_start(**_kwargs):
        pytest.fail("start_dashboard_server should not be called when --serve is omitted")

    monkeypatch.setattr(
        "cookimport.analytics.dashboard_collect.collect_dashboard_data",
        _fake_collect_dashboard_data,
    )
    monkeypatch.setattr(
        "cookimport.analytics.dashboard_render.render_dashboard",
        _fake_render_dashboard,
    )
    monkeypatch.setattr(
        "cookimport.analytics.dashboard_state_server.start_dashboard_server",
        _unexpected_server_start,
    )

    cli.stats_dashboard(
        output_root=tmp_path / "output",
        golden_root=tmp_path / "golden",
        out_dir=out_dir,
    )

    assert captured_collect_kwargs["since_days"] is None
    assert captured_collect_kwargs["scan_reports"] is False
    assert captured_collect_kwargs["scan_benchmark_reports"] is False


def test_interactive_main_menu_does_not_include_epub_race_when_epub_available(
    monkeypatch,
    tmp_path,
):
    captured_choice_values: list[str] = []
    epub_path = tmp_path / "book.epub"
    epub_path.write_text("dummy", encoding="utf-8")

    def fake_menu_select(*args, choices, **kwargs):
        for choice in choices:
            if isinstance(choice, questionary.Separator):
                continue
            captured_choice_values.append(str(choice.value))
        return "exit"

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [epub_path])

    with pytest.raises(typer.Exit):
        cli._interactive_mode()

    assert "epub_race" not in captured_choice_values


def test_ask_with_escape_back_handles_real_text_prompt() -> None:
    result: dict[str, str | None] = {"value": None}
    error: dict[str, BaseException] = {}

    with create_pipe_input() as pipe_input:
        question = questionary.text(
            "Type value:",
            default="",
            input=pipe_input,
            output=DummyOutput(),
        )

        def _run_prompt() -> None:
            try:
                result["value"] = cli._ask_with_escape_back(question, back_result="back")
            except BaseException as exc:  # noqa: BLE001
                error["exc"] = exc

        worker = threading.Thread(target=_run_prompt, daemon=True)
        worker.start()
        pipe_input.send_text("\x1b")
        worker.join(timeout=2)

    assert "exc" not in error, f"Prompt crashed instead of handling Esc: {error.get('exc')}"
    assert result["value"] == "back"


def test_menu_select_instruction_uses_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_instruction: list[str] = []

    class _FakeBindings:
        def __init__(self) -> None:
            self.handlers: dict[tuple[object, bool], object] = {}

        def add(self, key: object, eager: bool = False):
            def _decorator(func: object) -> object:
                self.handlers[(key, eager)] = func
                return func

            return _decorator

    class _FakeQuestion:
        def __init__(self) -> None:
            self.application = SimpleNamespace(key_bindings=_FakeBindings())

        def ask(self) -> str:
            return "selected"

    fake_question = _FakeQuestion()

    def fake_select(*_args, **kwargs):
        captured_instruction.append(str(kwargs.get("instruction") or ""))
        return fake_question

    monkeypatch.setattr(cli.questionary, "select", fake_select)

    result = cli._menu_select(
        "Pick one:",
        choices=[questionary.Choice("Choice A", value="a")],
    )

    assert result == "selected"
    assert "Esc to go back" in captured_instruction[0]
    assert "Backspace" not in captured_instruction[0]
    assert (Keys.Escape, True) in fake_question.application.key_bindings.handlers


def test_prompt_text_escape_returns_none() -> None:
    result: dict[str, str | None] = {"value": "sentinel"}
    error: dict[str, BaseException] = {}

    with create_pipe_input() as pipe_input:
        def _run_prompt() -> None:
            try:
                result["value"] = cli._prompt_text(
                    "Freeform focus size (blocks to label per task):",
                    default="40",
                    input=pipe_input,
                    output=DummyOutput(),
                )
            except BaseException as exc:  # noqa: BLE001
                error["exc"] = exc

        worker = threading.Thread(target=_run_prompt, daemon=True)
        worker.start()
        pipe_input.send_text("\x1b")
        worker.join(timeout=2)

    assert "exc" not in error, f"Prompt crashed instead of handling Esc: {error.get('exc')}"
    assert result["value"] is None


def test_load_settings_ignores_retired_sequence_matcher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "cookimport.json"
    config_path.write_text(
        json.dumps({"benchmark_sequence_matcher": "fallback"}, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", config_path)
    settings = cli._load_settings()

    assert "benchmark_sequence_matcher" not in settings


def test_load_settings_migrates_legacy_epub_extractor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "cookimport.json"
    config_path.write_text(
        json.dumps({"epub_extractor": "legacy"}, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", config_path)

    with caplog.at_level("WARNING", logger="cookimport.cli"):
        settings = cli._load_settings()

    assert settings["epub_extractor"] == "beautifulsoup"
    assert (
        "Migrating epub_extractor=legacy to beautifulsoup in cookimport.json."
        in caplog.text
    )


def test_load_settings_migrates_auto_epub_extractor_to_unstructured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "cookimport.json"
    config_path.write_text(
        json.dumps({"epub_extractor": "auto"}, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", config_path)

    with caplog.at_level("WARNING", logger="cookimport.cli"):
        settings = cli._load_settings()

    assert settings["epub_extractor"] == "unstructured"
    assert (
        "Forcing epub_extractor=unstructured in cookimport.json because auto "
        "extractor mode was removed."
        in caplog.text
    )


def test_choose_run_settings_uses_saved_qualitysuite_winner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict({}, warn_context="test global defaults")
    winner_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-farm-3pass-v1",
            "line_role_pipeline": "codex-line-role-v1",
            "atomic_block_splitter": "atomic-v1",
            "epub_extractor": "unstructured",
        },
        warn_context="test qualitysuite winner settings",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: winner_settings,
    )

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=lambda *_args, **_kwargs: pytest.fail(
            "top-tier menu should not be shown when codex confirm prompt is available"
        ),
        back_action=object(),
        prompt_confirm=lambda *_args, **_kwargs: True,
    )

    assert selected is not None
    expected = run_settings_flow._harmonize_top_tier_pipeline_settings(
        winner_settings,
        profile="codexfarm",
        warn_context="test expected saved winner settings",
    )
    assert selected.to_run_config_dict() == expected.to_run_config_dict()


def test_choose_run_settings_falls_back_to_builtin_top_tier_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict(
        {
            "epub_extractor": "beautifulsoup",
            "epub_unstructured_html_parser_version": "v2",
            "epub_unstructured_preprocess_mode": "none",
            "epub_unstructured_skip_headers_footers": False,
            "codex_farm_pass1_pattern_hints_enabled": True,
            "codex_farm_pass3_skip_pass2_ok": False,
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
        },
        warn_context="test global defaults",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: None,
    )

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=lambda *_args, **_kwargs: pytest.fail(
            "top-tier menu should not be shown when codex confirm prompt is available"
        ),
        back_action=object(),
        prompt_confirm=lambda *_args, **_kwargs: True,
    )

    assert selected is not None
    expected = run_settings_flow._harmonize_top_tier_pipeline_settings(
        run_settings_flow._default_top_tier_settings(global_defaults),
        profile="codexfarm",
        warn_context="test expected codex top-tier settings",
    )
    assert selected.to_run_config_dict() == expected.to_run_config_dict()
    assert selected.llm_knowledge_pipeline.value == "codex-farm-knowledge-v1"


def test_choose_run_settings_harmonizes_saved_qualitysuite_winner_to_latest_top_tier_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict({}, warn_context="test global defaults")
    stale_winner_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
            "codex_farm_pass1_pattern_hints_enabled": True,
            "codex_farm_pass3_skip_pass2_ok": False,
            "epub_extractor": "beautifulsoup",
            "epub_unstructured_html_parser_version": "v2",
            "epub_unstructured_preprocess_mode": "br_split_v1",
            "epub_unstructured_skip_headers_footers": False,
            "section_detector_backend": "legacy",
            "multi_recipe_splitter": "legacy",
            "instruction_step_segmentation_policy": "auto",
            "pdf_ocr_policy": "auto",
            "codex_farm_pipeline_pass2": "recipe.schemaorg.v1",
            "codex_farm_pipeline_pass3": "recipe.final.v1",
        },
        warn_context="test stale qualitysuite winner settings",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: stale_winner_settings,
    )

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=lambda *_args, **_kwargs: pytest.fail(
            "top-tier menu should not be shown when codex confirm prompt is available"
        ),
        back_action=object(),
        prompt_confirm=lambda *_args, **_kwargs: True,
    )

    assert selected is not None
    expected = run_settings_flow._harmonize_top_tier_pipeline_settings(
        stale_winner_settings,
        profile="codexfarm",
        warn_context="test expected harmonized winner settings",
    )
    assert selected.to_run_config_dict() == expected.to_run_config_dict()
    assert selected.llm_knowledge_pipeline.value == "codex-farm-knowledge-v1"


def test_choose_run_settings_vanilla_profile_uses_vanilla_top_tier_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict(
        {
            "codex_farm_pass1_pattern_hints_enabled": True,
            "codex_farm_pass3_skip_pass2_ok": False,
        },
        warn_context="test global defaults",
    )
    winner_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-farm-3pass-v1",
            "line_role_pipeline": "codex-line-role-v1",
            "atomic_block_splitter": "atomic-v1",
            "epub_unstructured_html_parser_version": "v2",
            "epub_unstructured_preprocess_mode": "semantic_v1",
        },
        warn_context="test qualitysuite winner settings",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: winner_settings,
    )

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=lambda *_args, **_kwargs: pytest.fail(
            "top-tier menu should not be shown when codex confirm prompt is available"
        ),
        back_action=object(),
        prompt_confirm=lambda *_args, **_kwargs: False,
    )

    assert selected is not None
    expected = run_settings_flow._harmonize_top_tier_pipeline_settings(
        run_settings_flow._default_vanilla_top_tier_settings(global_defaults),
        profile="vanilla",
        warn_context="test expected vanilla top-tier settings",
    )
    assert selected.to_run_config_dict() == expected.to_run_config_dict()


def test_choose_run_settings_codex_prompt_default_follows_global_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "off"},
        warn_context="test global defaults",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: pytest.fail(
            "winner lookup should not run when codex is disabled"
        ),
    )
    seen_default: dict[str, bool] = {}

    def _prompt_confirm(*_args, **kwargs):
        seen_default["value"] = bool(kwargs.get("default"))
        return kwargs.get("default")

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=lambda *_args, **_kwargs: pytest.fail(
            "top-tier menu should not be shown when codex confirm prompt is available"
        ),
        back_action=object(),
        prompt_confirm=_prompt_confirm,
    )

    assert seen_default["value"] is False
    assert selected is not None
    expected = run_settings_flow._harmonize_top_tier_pipeline_settings(
        run_settings_flow._default_vanilla_top_tier_settings(global_defaults),
        profile="vanilla",
        warn_context="test expected codex-prompt-default settings",
    )
    assert selected.to_run_config_dict() == expected.to_run_config_dict()


def test_choose_run_settings_recipe_pipeline_menu_can_select_merged_prototype(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-farm-2stage-repair-v1"},
        warn_context="test global defaults",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: None,
    )

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=lambda message, *_args, **_kwargs: (
            "codex-farm-2stage-repair-v1"
            if message == "Recipe pipeline for this run:"
            else pytest.fail(f"unexpected menu prompt: {message}")
        ),
        back_action=object(),
        prompt_confirm=lambda *_args, **_kwargs: pytest.fail(
            "yes/no codex prompt should not run when explicit recipe pipeline menu is enabled"
        ),
        prompt_recipe_pipeline_menu=True,
    )

    assert selected is not None
    assert selected.llm_recipe_pipeline.value == "codex-farm-2stage-repair-v1"
    assert selected.line_role_pipeline.value == "codex-line-role-v1"
    assert selected.atomic_block_splitter.value == "atomic-v1"
    assert selected.llm_knowledge_pipeline.value == "codex-farm-knowledge-v1"


def test_choose_run_settings_codex_profile_prompts_for_ai_settings_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict({}, warn_context="test global defaults")
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        run_settings_flow,
        "list_codex_farm_models",
        lambda **_kwargs: [
            {"slug": "gpt-5-codex", "description": "Balanced"},
            {"slug": "gpt-5.3-codex", "description": ""},
        ],
    )
    effort_prompt_seen: dict[str, bool] = {"value": False}
    model_choice_values: list[str] = []

    def _menu_select(message, *args, **kwargs):
        if message == "Codex Farm model override:":
            model_choice_values.extend(
                [str(choice.value) for choice in kwargs.get("choices", [])]
            )
            return "gpt-5-codex"
        if message == "Codex Farm reasoning effort override:":
            effort_prompt_seen["value"] = True
            return "high"
        pytest.fail(f"unexpected menu prompt: {message}")

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=_menu_select,
        back_action=object(),
        prompt_confirm=lambda *_args, **_kwargs: True,
        prompt_text=lambda *_args, **_kwargs: pytest.fail(
            "freeform model text prompt should not be used"
        ),
        prompt_codex_ai_settings=True,
    )

    assert selected is not None
    assert effort_prompt_seen["value"] is True
    assert model_choice_values == [
        "__pipeline_default__",
        "gpt-5-codex",
        "gpt-5.3-codex",
    ]
    assert selected.codex_farm_model == "gpt-5-codex"
    assert selected.codex_farm_reasoning_effort == "high"
    assert selected.codex_farm_reasoning_effort is CodexReasoningEffort.high


def test_choose_run_settings_codex_profile_filters_reasoning_efforts_by_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict({}, warn_context="test global defaults")
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        run_settings_flow,
        "list_codex_farm_models",
        lambda **_kwargs: [
            {
                "slug": "gpt-5.1-codex-mini",
                "description": "Cheap and fast",
                "supported_reasoning_efforts": ["medium", "high"],
            }
        ],
    )
    effort_choice_values: list[str] = []

    def _menu_select(message, *args, **kwargs):
        if message == "Codex Farm model override:":
            return "gpt-5.1-codex-mini"
        if message == "Codex Farm reasoning effort override:":
            effort_choice_values.extend(
                [str(choice.value) for choice in kwargs.get("choices", [])]
            )
            assert kwargs.get("default") == "__default__"
            return "high"
        pytest.fail(f"unexpected menu prompt: {message}")

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=_menu_select,
        back_action=object(),
        prompt_confirm=lambda *_args, **_kwargs: True,
        prompt_text=lambda *_args, **_kwargs: pytest.fail(
            "freeform model text prompt should not be used"
        ),
        prompt_codex_ai_settings=True,
    )

    assert selected is not None
    assert effort_choice_values == ["__default__", "medium", "high"]
    assert selected.codex_farm_model == "gpt-5.1-codex-mini"
    assert selected.codex_farm_reasoning_effort is CodexReasoningEffort.high


def test_build_codex_farm_reasoning_effort_choices_resets_invalid_saved_default() -> None:
    choices, default = run_settings_flow.build_codex_farm_reasoning_effort_choices(
        selected_model="gpt-5.1-codex-mini",
        selected_effort=CodexReasoningEffort.low,
        supported_efforts_by_model={
            "gpt-5.1-codex-mini": ("medium", "high"),
        },
    )

    assert [str(choice.value) for choice in choices] == [
        "__default__",
        "medium",
        "high",
    ]
    assert default == "__default__"


def test_choose_run_settings_codex_ai_settings_prompt_cancel_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict({}, warn_context="test global defaults")
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        run_settings_flow,
        "list_codex_farm_models",
        lambda **_kwargs: [{"slug": "gpt-5-codex", "description": ""}],
    )
    back_action = object()

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=lambda message, *_args, **_kwargs: (
            back_action
            if message == "Codex Farm model override:"
            else pytest.fail("effort menu should not run after model prompt cancel")
        ),
        back_action=back_action,
        prompt_confirm=lambda *_args, **_kwargs: True,
        prompt_text=lambda *_args, **_kwargs: pytest.fail(
            "freeform model text prompt should not be used"
        ),
        prompt_codex_ai_settings=True,
    )

    assert selected is None


def test_qualitysuite_winner_run_settings_roundtrip(tmp_path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    winner_settings = cli.RunSettings.from_dict(
        {
            "epub_extractor": "unstructured",
            "epub_unstructured_html_parser_version": "v2",
            "epub_unstructured_preprocess_mode": "semantic_v1",
        },
        warn_context="test qualitysuite winner roundtrip",
    )

    save_qualitysuite_winner_run_settings(output_dir, winner_settings)
    loaded = load_qualitysuite_winner_run_settings(output_dir)

    assert loaded is not None
    assert loaded.to_run_config_dict() == winner_settings.to_run_config_dict()


def test_interactive_import_passes_knowledge_pipeline_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    selected_file = tmp_path / "Hix written.docx"
    selected_file.write_text("dummy", encoding="utf-8")
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
            "llm_tags_pipeline": "codex-farm-tags-v1",
            "codex_farm_pipeline_pass4_knowledge": "recipe.knowledge.custom.v9",
            "codex_farm_pipeline_pass5_tags": "recipe.tags.custom.v3",
            "codex_farm_knowledge_context_blocks": 37,
            "tag_catalog_json": "data/tagging/custom_catalog.json",
        },
        warn_context="test settings",
    )
    menu_answers = iter(["import", selected_file, "exit"])
    captured: dict[str, object] = {}

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    def fake_stage(*, path, **kwargs):
        captured["path"] = path
        captured.update(kwargs)
        return tmp_path / "out" / "2026-02-23_13.00.00"

    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [selected_file])
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "choose_run_settings", lambda **_kwargs: selected_settings)
    monkeypatch.setattr(cli, "stage", fake_stage)

    with pytest.raises(typer.Exit):
        cli._interactive_mode()

    assert captured["path"] == selected_file
    assert captured["llm_knowledge_pipeline"] == "codex-farm-knowledge-v1"
    assert captured["llm_tags_pipeline"] == "codex-farm-tags-v1"
    assert captured["codex_farm_pipeline_pass4_knowledge"] == "recipe.knowledge.compact.v1"
    assert captured["codex_farm_pipeline_pass5_tags"] == "recipe.tags.v1"
    assert captured["codex_farm_knowledge_context_blocks"] == 37
    assert captured["tag_catalog_json"] == "data/tagging/custom_catalog.json"


def test_import_entrypoint_passes_extended_stage_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    settings = {
        "epub_extractor": "beautifulsoup",
        "epub_unstructured_html_parser_version": "v2",
        "epub_unstructured_skip_headers_footers": True,
        "epub_unstructured_preprocess_mode": "semantic_v1",
        "llm_recipe_pipeline": "off",
        "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
        "llm_tags_pipeline": "codex-farm-tags-v1",
        "codex_farm_pipeline_pass4_knowledge": "recipe.knowledge.custom.v9",
        "codex_farm_pipeline_pass5_tags": "recipe.tags.custom.v3",
        "codex_farm_knowledge_context_blocks": 42,
        "tag_catalog_json": "data/tagging/custom_catalog.json",
    }

    def fake_stage(*, path, limit, **kwargs):
        captured["path"] = path
        captured["limit"] = limit
        captured.update(kwargs)

    monkeypatch.setattr(entrypoint, "DEFAULT_INPUT", input_dir)
    monkeypatch.setattr(entrypoint, "DEFAULT_OUTPUT", output_dir)
    monkeypatch.setattr(entrypoint, "_load_settings", lambda: settings)
    monkeypatch.setattr(entrypoint, "stage", fake_stage)
    monkeypatch.setattr(
        entrypoint,
        "app",
        lambda: (_ for _ in ()).throw(AssertionError("entrypoint.app should not run")),
    )
    monkeypatch.setattr(entrypoint.sys, "argv", ["import"])

    entrypoint.main()

    assert captured["path"] == input_dir
    assert captured["limit"] is None
    assert captured["out"] == output_dir
    assert captured["epub_extractor"] == "beautifulsoup"
    assert captured["epub_unstructured_html_parser_version"] == "v2"
    assert captured["epub_unstructured_skip_headers_footers"] is True
    assert captured["epub_unstructured_preprocess_mode"] == "semantic_v1"
    assert captured["llm_knowledge_pipeline"] == "codex-farm-knowledge-v1"
    assert captured["llm_tags_pipeline"] == "codex-farm-tags-v1"
    assert captured["codex_farm_pipeline_pass4_knowledge"] == "recipe.knowledge.compact.v1"
    assert captured["codex_farm_pipeline_pass5_tags"] == "recipe.tags.v1"
    assert captured["codex_farm_knowledge_context_blocks"] == 42
    assert captured["tag_catalog_json"] == "data/tagging/custom_catalog.json"


def test_stage_direct_call_uses_plain_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_file = tmp_path / "source.txt"
    source_file.write_text("hello", encoding="utf-8")
    output_root = tmp_path / "output"

    monkeypatch.setattr(cli, "_iter_files", lambda _path: [])

    run_folder = cli.stage(path=source_file, out=output_root)

    assert run_folder.parent == output_root
