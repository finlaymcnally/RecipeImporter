from __future__ import annotations

import threading
from types import SimpleNamespace

import questionary
import pytest
import typer
from prompt_toolkit.keys import Keys
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cookimport import cli
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


def test_interactive_main_menu_includes_epub_race_when_epub_available(monkeypatch, tmp_path):
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

    assert "epub_race" in captured_choice_values


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


def test_interactive_import_passes_knowledge_pipeline_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    selected_file = tmp_path / "Hix written.docx"
    selected_file.write_text("dummy", encoding="utf-8")
    selected_settings = cli.RunSettings.from_dict(
        {
            "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
            "codex_farm_pipeline_pass4_knowledge": "recipe.knowledge.custom.v9",
            "codex_farm_knowledge_context_blocks": 37,
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
    monkeypatch.setattr(cli, "save_last_run_settings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "stage", fake_stage)

    with pytest.raises(typer.Exit):
        cli._interactive_mode()

    assert captured["path"] == selected_file
    assert captured["llm_knowledge_pipeline"] == "codex-farm-knowledge-v1"
    assert captured["codex_farm_pipeline_pass4_knowledge"] == "recipe.knowledge.custom.v9"
    assert captured["codex_farm_knowledge_context_blocks"] == 37


def test_import_entrypoint_passes_extended_stage_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    settings = {
        "epub_extractor": "legacy",
        "epub_unstructured_html_parser_version": "v2",
        "epub_unstructured_skip_headers_footers": True,
        "epub_unstructured_preprocess_mode": "semantic_v1",
        "llm_recipe_pipeline": "off",
        "llm_knowledge_pipeline": "codex-farm-knowledge-v1",
        "codex_farm_pipeline_pass4_knowledge": "recipe.knowledge.custom.v9",
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
    assert captured["epub_extractor"] == "legacy"
    assert captured["epub_unstructured_html_parser_version"] == "v2"
    assert captured["epub_unstructured_skip_headers_footers"] is True
    assert captured["epub_unstructured_preprocess_mode"] == "semantic_v1"
    assert captured["llm_knowledge_pipeline"] == "codex-farm-knowledge-v1"
    assert captured["codex_farm_pipeline_pass4_knowledge"] == "recipe.knowledge.custom.v9"
    assert captured["codex_farm_knowledge_context_blocks"] == 42


def test_stage_direct_call_uses_plain_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_file = tmp_path / "source.txt"
    source_file.write_text("hello", encoding="utf-8")
    output_root = tmp_path / "output"

    monkeypatch.setattr(cli, "_iter_files", lambda _path: [])

    run_folder = cli.stage(path=source_file, out=output_root)

    assert run_folder.parent == output_root
