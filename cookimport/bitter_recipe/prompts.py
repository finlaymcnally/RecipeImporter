from __future__ import annotations

import os
from typing import Any

import questionary
from prompt_toolkit.key_binding.key_bindings import KeyBindings, merge_key_bindings
from prompt_toolkit.keys import Keys


BACK_ACTION = "__back__"


def _ensure_prompt_toolkit_terminal_defaults() -> None:
    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")


def _ask_with_escape_back(question: Any, *, back_result: Any = BACK_ACTION) -> Any:
    application = getattr(question, "application", None)
    if application is not None:
        escape_bindings = KeyBindings()

        @escape_bindings.add(Keys.Escape, eager=True)
        def _go_back(event: Any) -> None:
            event.app.exit(result=back_result)

        existing_bindings = getattr(application, "key_bindings", None)
        if existing_bindings is None:
            application.key_bindings = escape_bindings
        else:
            application.key_bindings = merge_key_bindings(
                [escape_bindings, existing_bindings]
            )
    return question.ask()


def menu_select(
    message: str,
    *,
    choices: list[Any],
    menu_help: str | None = None,
) -> Any:
    _ensure_prompt_toolkit_terminal_defaults()
    if menu_help:
        import typer

        typer.secho(menu_help, fg=typer.colors.BRIGHT_BLACK)
    question = questionary.select(
        message,
        choices=choices,
        instruction="(Enter to select, Esc to go back)",
    )
    return _ask_with_escape_back(question, back_result=BACK_ACTION)


def prompt_text(
    message: str,
    *,
    default: str = "",
    password: bool = False,
) -> str | None:
    _ensure_prompt_toolkit_terminal_defaults()
    factory = questionary.password if password else questionary.text
    question = factory(message, default=default)
    result = _ask_with_escape_back(question, back_result=None)
    if result is None:
        return None
    return str(result)


def prompt_confirm(
    message: str,
    *,
    default: bool = True,
) -> bool | None:
    _ensure_prompt_toolkit_terminal_defaults()
    question = questionary.confirm(message, default=default)
    result = _ask_with_escape_back(question, back_result=None)
    if result is None:
        return None
    return bool(result)
