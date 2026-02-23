from __future__ import annotations

from types import SimpleNamespace

import questionary
import pytest
import typer
from prompt_toolkit.keys import Keys

from cookimport import cli


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


def test_ask_with_escape_back_registers_escape_binding() -> None:
    class _FakeBindings:
        def __init__(self) -> None:
            self.handlers: dict[tuple[object, bool], object] = {}

        def add(self, key: object, eager: bool = False):
            def _decorator(func: object) -> object:
                self.handlers[(key, eager)] = func
                return func

            return _decorator

    class _FakeApp:
        def __init__(self) -> None:
            self.key_bindings = _FakeBindings()
            self.exit_result: object | None = None

        def exit(self, *, result: object | None = None) -> None:
            self.exit_result = result

    class _FakeQuestion:
        def __init__(self) -> None:
            self.application = _FakeApp()
            self.ask_calls = 0

        def ask(self) -> str:
            self.ask_calls += 1
            return "ok"

    question = _FakeQuestion()
    result = cli._ask_with_escape_back(question, back_result="back")

    assert result == "ok"
    assert question.ask_calls == 1
    handler = question.application.key_bindings.handlers[(Keys.Escape, True)]
    handler(SimpleNamespace(app=question.application))
    assert question.application.exit_result == "back"


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
