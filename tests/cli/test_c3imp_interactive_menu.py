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
from cookimport.paths import history_root_for_output
from cookimport import entrypoint

REMOVED_EXTRACTOR_VALUE = "leg" "acy"


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


def test_load_settings_preserves_stale_sequence_matcher_key(
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

    assert settings["benchmark_sequence_matcher"] == "fallback"


def test_load_settings_includes_expanded_operator_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "cookimport.json"
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", config_path)

    settings = cli._load_settings()

    assert settings["pdf_ocr_policy"] == "auto"
    assert settings["web_schema_extractor"] == "builtin_jsonld"
    assert settings["web_schema_policy"] == "prefer_schema"
    assert settings["llm_knowledge_pipeline"] == "off"
    assert settings["codex_farm_cmd"] == "codex-farm"
    assert settings["codex_farm_context_blocks"] == 30
    assert settings["codex_farm_knowledge_context_blocks"] == 0
    assert settings["label_studio_url"] == ""
    assert settings["label_studio_api_key"] == ""


def test_settings_menu_includes_expanded_operator_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_choice_values: list[str] = []

    def fake_menu_select(*_args, choices, **_kwargs):
        for choice in choices:
            if isinstance(choice, questionary.Separator):
                continue
            captured_choice_values.append(str(choice.value))
        return "back"

    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)

    cli._settings_menu(cli._load_settings())

    assert "pdf_ocr_policy" in captured_choice_values
    assert "web_schema_extractor" in captured_choice_values
    assert "web_schema_policy" in captured_choice_values
    assert "llm_recipe_pipeline" in captured_choice_values
    assert "llm_knowledge_pipeline" in captured_choice_values
    assert "codex_farm_cmd" in captured_choice_values
    assert "codex_farm_root" in captured_choice_values
    assert "codex_farm_workspace_root" in captured_choice_values
    assert "codex_farm_model" in captured_choice_values
    assert "codex_farm_reasoning_effort" in captured_choice_values
    assert "codex_farm_context_blocks" in captured_choice_values
    assert "codex_farm_knowledge_context_blocks" in captured_choice_values
    assert "label_studio_url" in captured_choice_values
    assert "label_studio_api_key" in captured_choice_values


def test_settings_menu_can_update_new_operator_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = cli._load_settings()
    menu_answers = iter(
        [
            "pdf_ocr_policy",
            "always",
            "web_schema_policy",
            "schema_only",
            "codex_farm_reasoning_effort",
            "high",
            "codex_farm_cmd",
            "label_studio_url",
            "label_studio_api_key",
            "back",
        ]
    )
    text_answers = iter(
        [
            "codex-farm --profile test",
            "http://localhost:8080",
        ]
    )
    password_answers = iter(["fresh-key"])
    saved_snapshots: list[dict[str, object]] = []

    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_prompt_text", lambda *_args, **_kwargs: next(text_answers))
    monkeypatch.setattr(
        cli,
        "_prompt_password",
        lambda *_args, **_kwargs: next(password_answers),
    )
    monkeypatch.setattr(
        cli,
        "_save_settings",
        lambda payload: saved_snapshots.append(dict(payload)),
    )

    cli._settings_menu(settings)

    assert settings["pdf_ocr_policy"] == "always"
    assert settings["web_schema_policy"] == "schema_only"
    assert settings["codex_farm_reasoning_effort"] == "high"
    assert settings["codex_farm_cmd"] == "codex-farm --profile test"
    assert settings["label_studio_url"] == "http://localhost:8080"
    assert settings["label_studio_api_key"] == "fresh-key"
    assert saved_snapshots[-1]["label_studio_api_key"] == "fresh-key"


def test_run_settings_payload_filter_rejects_removed_removed_epub_extractor_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "cookimport.json"
    config_path.write_text(
        json.dumps({"epub_extractor": REMOVED_EXTRACTOR_VALUE}, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", config_path)
    settings = cli._load_settings()

    with pytest.raises(Exception):
        cli.RunSettings.from_dict(
            cli._run_settings_payload_from_settings(settings),
            warn_context="test filtered cookimport.json",
        )


def test_run_settings_payload_filter_rejects_removed_auto_epub_extractor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "cookimport.json"
    config_path.write_text(
        json.dumps({"epub_extractor": "auto"}, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", config_path)
    settings = cli._load_settings()

    with pytest.raises(Exception):
        cli.RunSettings.from_dict(
            cli._run_settings_payload_from_settings(settings),
            warn_context="test filtered cookimport.json",
        )


def test_choose_run_settings_uses_saved_qualitysuite_winner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict({}, warn_context="test global defaults")
    winner_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-shard-v1",
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
    assert selected.llm_knowledge_pipeline.value == "codex-knowledge-shard-v1"


def test_choose_run_settings_harmonizes_saved_qualitysuite_winner_to_latest_top_tier_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict({}, warn_context="test global defaults")
    saved_winner_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "off",
            "atomic_block_splitter": "off",
            "epub_extractor": "beautifulsoup",
            "epub_unstructured_html_parser_version": "v2",
            "epub_unstructured_preprocess_mode": "br_split_v1",
            "epub_unstructured_skip_headers_footers": False,
            "multi_recipe_splitter": "rules_v1",
            "pdf_ocr_policy": "auto",
        },
        warn_context="test saved qualitysuite winner settings",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: saved_winner_settings,
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
        saved_winner_settings,
        profile="codexfarm",
        warn_context="test expected harmonized winner settings",
    )
    assert selected.to_run_config_dict() == expected.to_run_config_dict()
    assert selected.llm_knowledge_pipeline.value == "codex-knowledge-shard-v1"


def test_choose_run_settings_does_not_warn_for_fixed_behavior_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    global_defaults = cli.RunSettings.from_dict({}, warn_context="test global defaults")
    winner_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-shard-v1",
            "atomic_block_splitter": "atomic-v1",
            "codex_farm_model": "gpt-5.3-codex",
        },
        warn_context="test qualitysuite winner settings",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: winner_settings,
    )

    def _menu_select(message: str, **_kwargs):
        if message == "Workflow for this run:":
            return "codex-recipe-shard-v1"
        if message == "Codex Farm model override:":
            return "__pipeline_default__"
        if message == "Codex Farm reasoning effort override:":
            return "__default__"
        pytest.fail(f"unexpected menu prompt: {message}")

    with caplog.at_level("WARNING", logger="cookimport.config.run_settings"):
        selected = run_settings_flow.choose_run_settings(
            global_defaults=global_defaults,
            output_dir=tmp_path,
            menu_select=_menu_select,
            back_action=object(),
            prompt_recipe_pipeline_menu=True,
            prompt_codex_ai_settings=True,
        )

    assert selected is not None
    assert (
        "Ignoring unknown interactive top-tier pipeline harmonization keys"
        not in caplog.text
    )
    assert "Ignoring unknown interactive codex ai settings keys" not in caplog.text
    assert (
        "Ignoring unknown interactive recipe pipeline selection override keys"
        not in caplog.text
    )


def test_choose_run_settings_vanilla_profile_uses_vanilla_top_tier_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict({}, warn_context="test global defaults")
    winner_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "line_role_pipeline": "codex-line-role-shard-v1",
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


def test_choose_run_settings_recipe_pipeline_menu_normalizes_legacy_pipeline_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
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
            "codex-recipe-shard-v1"
            if message == "Workflow for this run:"
            else pytest.fail(f"unexpected menu prompt: {message}")
        ),
        back_action=object(),
        prompt_confirm=lambda *_args, **_kwargs: pytest.fail(
            "yes/no codex prompt should not run when explicit recipe pipeline menu is enabled"
        ),
        prompt_recipe_pipeline_menu=True,
    )

    assert selected is not None
    assert selected.llm_recipe_pipeline.value == "codex-recipe-shard-v1"
    assert selected.line_role_pipeline.value == "codex-line-role-shard-v1"
    assert selected.atomic_block_splitter.value == "atomic-v1"
    assert selected.llm_knowledge_pipeline.value == "codex-knowledge-shard-v1"


def test_choose_run_settings_workflow_menu_uses_family_labels_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test global defaults",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: None,
    )
    captured_titles: list[str] = []

    def _menu_select(message, *_args, **kwargs):
        if message == "Workflow for this run:":
            captured_titles.extend(str(choice.title) for choice in kwargs.get("choices", []))
            return "codex-recipe-shard-v1"
        pytest.fail(f"unexpected menu prompt: {message}")

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=_menu_select,
        back_action=object(),
        prompt_codex_surface_menu=lambda **_kwargs: {
            "recipe": True,
            "line_role": True,
            "knowledge": True,
        },
        prompt_recipe_pipeline_menu=True,
        prompt_benchmark_llm_surface_toggles=True,
    )

    assert selected is not None
    assert captured_titles == ["Vanilla / no Codex", "CodexFarm"]


def test_choose_run_settings_benchmark_surface_toggles_apply_independently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
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
            "codex-recipe-shard-v1"
            if message == "Workflow for this run:"
            else pytest.fail(f"unexpected menu prompt: {message}")
        ),
        back_action=object(),
        prompt_codex_surface_menu=lambda **_kwargs: {
            "recipe": True,
            "line_role": False,
            "knowledge": False,
        },
        prompt_recipe_pipeline_menu=True,
        prompt_benchmark_llm_surface_toggles=True,
    )

    assert selected is not None
    assert selected.llm_recipe_pipeline.value == "codex-recipe-shard-v1"
    assert selected.line_role_pipeline.value == "off"
    assert selected.atomic_block_splitter.value == "off"
    assert selected.llm_knowledge_pipeline.value == "off"


def test_choose_run_settings_prompts_for_enabled_codex_prompt_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test global defaults",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: None,
    )
    prompt_messages: list[str] = []

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=lambda message, *_args, **_kwargs: (
            "codex-recipe-shard-v1"
            if message == "Workflow for this run:"
            else pytest.fail(f"unexpected menu prompt: {message}")
        ),
        back_action=object(),
        prompt_codex_surface_menu=lambda **_kwargs: {
            "recipe": True,
            "line_role": False,
            "knowledge": True,
        },
        prompt_text=lambda message, **_kwargs: (
            prompt_messages.append(message)
            or (
                "3"
                if message == "Recipe correction shard count for this run:"
                else "6"
            )
        ),
        prompt_recipe_pipeline_menu=True,
        prompt_benchmark_llm_surface_toggles=True,
    )

    assert selected is not None
    assert prompt_messages == [
        "Recipe correction shard count for this run:",
        "Non-recipe knowledge review shard count for this run:",
    ]
    assert selected.recipe_prompt_target_count == 3
    assert selected.knowledge_prompt_target_count == 6
    assert selected.line_role_prompt_target_count == 5


def test_choose_interactive_codex_surfaces_line_role_only_prompts_only_for_line_role_target() -> None:
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_recipe_pipeline": "off",
            "line_role_pipeline": "codex-line-role-shard-v1",
            "llm_knowledge_pipeline": "off",
            "line_role_prompt_target_count": 5,
        },
        warn_context="test line-role-only prompt targets",
    )
    prompt_messages: list[str] = []

    result = run_settings_flow.choose_interactive_codex_surfaces(
        selected_settings=selected_settings,
        back_action=object(),
        surface_options=("recipe", "line_role", "knowledge"),
        prompt_codex_surface_menu=lambda **_kwargs: {
            "recipe": False,
            "line_role": True,
            "knowledge": False,
        },
        prompt_text=lambda message, **_kwargs: prompt_messages.append(message) or "4",
    )

    assert result is not None
    assert prompt_messages == ["Block labelling shard count for this run:"]
    assert result.recipe_prompt_target_count == selected_settings.recipe_prompt_target_count
    assert result.line_role_prompt_target_count == 4
    assert result.knowledge_prompt_target_count == selected_settings.knowledge_prompt_target_count


def test_choose_run_settings_line_role_only_codex_still_prompts_for_ai_settings(
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
    seen_model_prompt = {"value": False}

    def _menu_select(message, *_args, **_kwargs):
        if message == "Workflow for this run:":
            return "codex-recipe-shard-v1"
        if message == "Codex Farm model override:":
            seen_model_prompt["value"] = True
            return "__pipeline_default__"
        if message == "Codex Farm reasoning effort override:":
            return "__default__"
        pytest.fail(f"unexpected menu prompt: {message}")

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=_menu_select,
        back_action=object(),
        prompt_codex_surface_menu=lambda **_kwargs: {
            "recipe": False,
            "line_role": True,
            "knowledge": False,
        },
        prompt_recipe_pipeline_menu=True,
        prompt_codex_ai_settings=True,
        prompt_benchmark_llm_surface_toggles=True,
    )

    assert selected is not None
    assert seen_model_prompt["value"] is True
    assert selected.llm_recipe_pipeline.value == "off"
    assert selected.line_role_pipeline.value == "codex-line-role-shard-v1"
    assert selected.llm_knowledge_pipeline.value == "off"
    assert selected.atomic_block_splitter.value == "atomic-v1"


def test_choose_run_settings_stage_codex_surface_menu_applies_recipe_and_knowledge_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    global_defaults = cli.RunSettings.from_dict(
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        warn_context="test global defaults",
    )
    monkeypatch.setattr(
        run_settings_flow,
        "load_qualitysuite_winner_run_settings",
        lambda *_args, **_kwargs: None,
    )

    def _menu_select(message, *_args, **_kwargs):
        if message == "Workflow for this run:":
            return "codex-recipe-shard-v1"
        pytest.fail(f"unexpected menu prompt: {message}")

    selected = run_settings_flow.choose_run_settings(
        global_defaults=global_defaults,
        output_dir=tmp_path,
        menu_select=_menu_select,
        back_action=object(),
        prompt_codex_surface_menu=lambda **_kwargs: {
            "recipe": False,
            "knowledge": True,
        },
        prompt_recipe_pipeline_menu=True,
        interactive_codex_surface_options=("recipe", "knowledge"),
    )

    assert selected is not None
    assert selected.llm_recipe_pipeline.value == "off"
    assert selected.llm_knowledge_pipeline.value == "codex-knowledge-shard-v1"
    assert selected.line_role_pipeline.value == "off"
    assert selected.atomic_block_splitter.value == "off"


def test_prompt_codex_surface_menu_uses_arrow_keys_to_toggle_without_leaving_screen() -> None:
    result: dict[str, dict[str, bool] | None] = {"value": None}
    error: dict[str, BaseException] = {}

    with create_pipe_input() as pipe_input:
        def _run_prompt() -> None:
            try:
                result["value"] = run_settings_flow._prompt_codex_surface_menu(
                    message="CodexFarm steps for this run:",
                    step_rows=[
                        ("recipe", "Recipe correction (`codex-recipe-shard-v1`)"),
                        ("knowledge", "Knowledge harvest (`codex-knowledge-shard-v1`)"),
                    ],
                    enabled_by_step={"recipe": True, "knowledge": True},
                    back_action="back",
                    input=pipe_input,
                    output=DummyOutput(),
                )
            except BaseException as exc:  # noqa: BLE001
                error["exc"] = exc

        worker = threading.Thread(target=_run_prompt, daemon=True)
        worker.start()
        pipe_input.send_bytes(b"\x1b[B")  # Down
        pipe_input.send_bytes(b"\x1b[C")  # Right -> No
        pipe_input.send_bytes(b"\x1b[B")  # Down to Continue
        pipe_input.send_bytes(b"\r")      # Enter
        worker.join(timeout=2)

    assert "exc" not in error, f"Prompt crashed instead of handling arrows: {error.get('exc')}"
    assert result["value"] == {"recipe": True, "knowledge": False}


def test_prompt_codex_surface_menu_allows_left_and_right_to_move_current_choice() -> None:
    result: dict[str, dict[str, bool] | None] = {"value": None}
    error: dict[str, BaseException] = {}

    with create_pipe_input() as pipe_input:
        def _run_prompt() -> None:
            try:
                result["value"] = run_settings_flow._prompt_codex_surface_menu(
                    message="CodexFarm options for this run:",
                    step_rows=[
                        ("recipe", "Recipe correction (`codex-recipe-shard-v1`)"),
                        ("knowledge", "Knowledge harvest (`codex-knowledge-shard-v1`)"),
                    ],
                    enabled_by_step={"recipe": True, "knowledge": True},
                    back_action="back",
                    input=pipe_input,
                    output=DummyOutput(),
                )
            except BaseException as exc:  # noqa: BLE001
                error["exc"] = exc

        worker = threading.Thread(target=_run_prompt, daemon=True)
        worker.start()
        pipe_input.send_bytes(b"\x1b[B")  # Down to knowledge
        pipe_input.send_bytes(b"\x1b[C")  # Right -> No
        pipe_input.send_bytes(b"\x1b[D")  # Left -> Yes
        pipe_input.send_bytes(b"\x1b[B")  # Down to Continue
        pipe_input.send_bytes(b"\r")      # Enter
        worker.join(timeout=2)

    assert "exc" not in error, f"Prompt crashed instead of handling arrows: {error.get('exc')}"
    assert result["value"] == {"recipe": True, "knowledge": True}


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
    payload = json.loads(
        (
            history_root_for_output(output_dir)
            / "qualitysuite_winner_run_settings.json"
        ).read_text(encoding="utf-8")
    )

    assert loaded is not None
    assert loaded.to_run_config_dict() == winner_settings.to_run_config_dict()
    assert payload["schema_version"] == 2
    assert payload["run_settings"] == winner_settings.model_dump(mode="json", exclude_none=True)
    assert "epub_extractor=unstructured" in payload["run_settings_summary"]
    assert "epub_unstructured_html_parser_version=v2" in payload["run_settings_summary"]


def test_load_qualitysuite_winner_run_settings_ignores_stale_payload(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    output_dir = tmp_path / "output"
    winner_path = history_root_for_output(output_dir) / "qualitysuite_winner_run_settings.json"
    winner_path.parent.mkdir(parents=True, exist_ok=True)
    winner_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "saved_at": "2026-03-01T11:03:46",
                "run_settings": {
                    "benchmark_sequence_matcher": "dmp",
                    "codex_farm_pipeline_pass1": "recipe.chunking.v1",
                    "codex_farm_pipeline_pass2": "recipe.schemaorg.v1",
                    "codex_farm_pipeline_pass3": "recipe.final.v1",
                    "instruction_step_segmentation_policy": "auto",
                    "instruction_step_segmenter": "heuristic_v1",
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "multi_recipe_splitter": "rules_v1",
                    "section_detector_backend": "shared_v1",
                    "table_extraction": "off",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with caplog.at_level("WARNING", logger="cookimport.config.run_settings"):
        loaded = load_qualitysuite_winner_run_settings(output_dir)

    assert loaded is None

    with caplog.at_level("WARNING", logger="cookimport.config.last_run_store"):
        loaded = load_qualitysuite_winner_run_settings(output_dir)

    assert loaded is None
    assert "Ignoring stale qualitysuite winner settings file" in caplog.text


def test_interactive_import_passes_knowledge_pipeline_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    selected_file = tmp_path / "Hix written.docx"
    selected_file.write_text("dummy", encoding="utf-8")
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "codex_farm_knowledge_context_blocks": 37,
        },
        warn_context="test settings",
    )
    menu_answers = iter(["import", selected_file, "exit"])
    captured: dict[str, object] = {}
    choose_kwargs: dict[str, object] = {}

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    def fake_stage(*, path, **kwargs):
        captured["path"] = path
        captured.update(kwargs)
        return tmp_path / "out" / "2026-02-23_13.00.00"

    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [selected_file])
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(
        cli,
        "choose_run_settings",
        lambda **kwargs: choose_kwargs.update(kwargs) or selected_settings,
    )
    monkeypatch.setattr(cli, "stage", fake_stage)

    with pytest.raises(typer.Exit):
        cli._interactive_mode()

    assert choose_kwargs["prompt_recipe_pipeline_menu"] is True
    assert choose_kwargs["prompt_codex_ai_settings"] is True
    assert choose_kwargs["interactive_codex_surface_options"] == (
        "recipe",
        "knowledge",
    )
    assert captured["path"] == selected_file
    assert captured["llm_knowledge_pipeline"] == "codex-knowledge-shard-v1"
    assert captured["codex_farm_pipeline_knowledge"] == "recipe.knowledge.compact.v1"
    assert captured["codex_farm_knowledge_context_blocks"] == 37


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
        "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
        "codex_farm_pipeline_knowledge": "recipe.knowledge.custom.v9",
        "codex_farm_knowledge_context_blocks": 42,
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
    assert captured["llm_knowledge_pipeline"] == "codex-knowledge-shard-v1"
    assert captured["codex_farm_pipeline_knowledge"] == "recipe.knowledge.compact.v1"
    assert captured["codex_farm_knowledge_context_blocks"] == 42


def test_stage_direct_call_uses_plain_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_file = tmp_path / "source.txt"
    source_file.write_text("hello", encoding="utf-8")
    output_root = tmp_path / "output"

    monkeypatch.setattr(cli, "_iter_files", lambda _path: [])

    run_folder = cli.stage(path=source_file, out=output_root)

    assert run_folder.parent == output_root
