from __future__ import annotations

import os
from typing import Any

import questionary
import typer
from prompt_toolkit.key_binding.key_bindings import KeyBindings, merge_key_bindings
from prompt_toolkit.keys import Keys
from questionary.prompts.common import Choice as QuestionaryChoice, Separator as QuestionarySeparator


def _runtime():
    from cookimport import cli_support as runtime

    return runtime


def _ensure_prompt_toolkit_terminal_defaults() -> None:
    # Some WSL/Windows terminal paths never answer prompt_toolkit's CPR probe,
    # which adds a visible two-second stall before interactive prompts settle.
    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")


def _menu_option_count(choices: list[Any]) -> int:
    return sum(
        1
        for raw_choice in choices
        if not isinstance(QuestionaryChoice.build(raw_choice), QuestionarySeparator)
    )


def _menu_shortcut_bindings(choices: list[Any]) -> dict[str, Any]:
    runtime = _runtime()
    selectable_choices: list[QuestionaryChoice] = []
    for raw_choice in choices:
        built_choice = QuestionaryChoice.build(raw_choice)
        if isinstance(built_choice, QuestionarySeparator) or built_choice.disabled:
            continue
        selectable_choices.append(built_choice)

    available_shortcuts = list(runtime._MENU_SHORTCUT_KEYS)
    bindings: dict[str, Any] = {}

    for built_choice in selectable_choices:
        shortcut_key = built_choice.shortcut_key
        if isinstance(shortcut_key, str) and shortcut_key:
            if shortcut_key in available_shortcuts:
                available_shortcuts.remove(shortcut_key)
            bindings[shortcut_key] = built_choice.value

    for built_choice in selectable_choices:
        shortcut_key = built_choice.shortcut_key
        if isinstance(shortcut_key, str):
            continue
        if shortcut_key is False:
            continue
        if not available_shortcuts:
            break
        assigned = available_shortcuts.pop(0)
        bindings[assigned] = built_choice.value

    return bindings


def _menu_select(
    message: str,
    *,
    choices: list[Any],
    menu_help: str | None = None,
    **kwargs: Any,
) -> Any:
    _ensure_prompt_toolkit_terminal_defaults()
    runtime = _runtime()
    option_count = _menu_option_count(choices)
    use_shortcuts = option_count <= len(runtime._MENU_SHORTCUT_KEYS)
    shortcut_bindings = _menu_shortcut_bindings(choices) if use_shortcuts else {}
    if menu_help:
        typer.secho(menu_help, fg=typer.colors.BRIGHT_BLACK)
    question = questionary.select(
        message,
        choices=choices,
        instruction=(
            "(Type number shortcut to select, Enter to select, Esc to go back)"
            if use_shortcuts
            else "(Enter to select, Esc to go back)"
        ),
        use_shortcuts=use_shortcuts,
        **kwargs,
    )

    @question.application.key_bindings.add(Keys.Escape, eager=True)
    def _go_back(event: Any) -> None:
        event.app.exit(result=runtime.BACK_ACTION)

    if use_shortcuts:
        for key, value in shortcut_bindings.items():
            if key not in "0123456789":
                continue

            def _register_numeric_shortcut(shortcut: str, selected_value: Any) -> None:
                @question.application.key_bindings.add(shortcut, eager=True)
                def _select_by_shortcut(event: Any) -> None:
                    event.app.exit(result=selected_value)

            _register_numeric_shortcut(key, value)

    return question.ask()


def _ask_with_escape_back(question: Any, *, back_result: Any = None) -> Any:
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


def _prompt_text(
    message: str,
    *,
    default: str = "",
    instruction: str | None = None,
    **kwargs: Any,
) -> str | None:
    _ensure_prompt_toolkit_terminal_defaults()
    question = questionary.text(
        message,
        default=default,
        instruction=instruction,
        **kwargs,
    )
    return _ask_with_escape_back(question, back_result=None)


def _prompt_password(
    message: str,
    *,
    default: str = "",
    **kwargs: Any,
) -> str | None:
    _ensure_prompt_toolkit_terminal_defaults()
    question = questionary.password(
        message,
        default=default,
        **kwargs,
    )
    return _ask_with_escape_back(question, back_result=None)


def _prompt_confirm(
    message: str,
    *,
    default: bool = True,
    instruction: str | None = None,
    **kwargs: Any,
) -> bool | None:
    _ensure_prompt_toolkit_terminal_defaults()
    question = questionary.confirm(
        message,
        default=default,
        instruction=instruction,
        **kwargs,
    )
    return _ask_with_escape_back(question, back_result=None)


def _prompt_freeform_segment_settings(
    *,
    segment_blocks_default: int,
    segment_overlap_default: int,
    segment_focus_blocks_default: int,
    target_task_count_default: int | None,
) -> tuple[int, int, int, int | None] | None:
    segment_blocks = max(1, int(segment_blocks_default))
    segment_overlap = max(0, int(segment_overlap_default))
    segment_focus_blocks = max(
        1,
        min(int(segment_focus_blocks_default), segment_blocks),
    )
    target_task_count = (
        None if target_task_count_default is None else int(target_task_count_default)
    )

    step = "segment_blocks"
    while True:
        if step == "segment_blocks":
            segment_blocks_raw = _runtime()._prompt_text(
                "Freeform segment size (blocks per task):",
                default=str(segment_blocks),
            )
            if segment_blocks_raw is None:
                return None
            try:
                parsed_segment_blocks = int(segment_blocks_raw.strip())
            except ValueError:
                typer.secho("Segment size must be an integer >= 1.", fg=typer.colors.RED)
                continue
            if parsed_segment_blocks < 1:
                typer.secho("Segment size must be >= 1.", fg=typer.colors.RED)
                continue
            segment_blocks = parsed_segment_blocks
            if segment_focus_blocks > segment_blocks:
                segment_focus_blocks = segment_blocks
            step = "segment_overlap"
            continue

        if step == "segment_overlap":
            segment_overlap_raw = _runtime()._prompt_text(
                "Freeform overlap (blocks):",
                default=str(segment_overlap),
            )
            if segment_overlap_raw is None:
                step = "segment_blocks"
                continue
            try:
                parsed_segment_overlap = int(segment_overlap_raw.strip())
            except ValueError:
                typer.secho("Segment overlap must be an integer >= 0.", fg=typer.colors.RED)
                continue
            if parsed_segment_overlap < 0:
                typer.secho("Segment overlap must be >= 0.", fg=typer.colors.RED)
                continue
            segment_overlap = parsed_segment_overlap
            step = "segment_focus_blocks"
            continue

        if step == "segment_focus_blocks":
            segment_focus_blocks_raw = _runtime()._prompt_text(
                "Freeform focus size (blocks to label per task):",
                default=str(segment_focus_blocks),
            )
            if segment_focus_blocks_raw is None:
                step = "segment_overlap"
                continue
            try:
                parsed_focus_blocks = int(segment_focus_blocks_raw.strip())
            except ValueError:
                typer.secho("Focus size must be an integer >= 1.", fg=typer.colors.RED)
                continue
            if parsed_focus_blocks < 1:
                typer.secho("Focus size must be >= 1.", fg=typer.colors.RED)
                continue
            if parsed_focus_blocks > segment_blocks:
                typer.secho("Focus size must be <= segment size.", fg=typer.colors.RED)
                continue
            segment_focus_blocks = parsed_focus_blocks
            step = "target_task_count"
            continue

        target_task_count_raw = _runtime()._prompt_text(
            "Target task count (optional, blank to disable):",
            default="" if target_task_count is None else str(target_task_count),
        )
        if target_task_count_raw is None:
            step = "segment_focus_blocks"
            continue

        target_task_count = None
        target_task_count_text = target_task_count_raw.strip()
        if target_task_count_text:
            try:
                parsed_target_task_count = int(target_task_count_text)
            except ValueError:
                typer.secho(
                    "Target task count must be an integer >= 1.",
                    fg=typer.colors.RED,
                )
                continue
            if parsed_target_task_count < 1:
                typer.secho("Target task count must be >= 1.", fg=typer.colors.RED)
                continue
            target_task_count = parsed_target_task_count

        return (
            segment_blocks,
            segment_overlap,
            segment_focus_blocks,
            target_task_count,
        )
