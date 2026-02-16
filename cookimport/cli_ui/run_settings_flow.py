from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal

import questionary

from cookimport.config.last_run_store import load_last_run_settings
from cookimport.config.run_settings import RunSettings
from .toggle_editor import edit_run_settings

RunSettingsKind = Literal["import", "benchmark"]
MenuSelect = Callable[..., Any]


def choose_run_settings(
    *,
    kind: RunSettingsKind,
    global_defaults: RunSettings,
    output_dir: Path,
    menu_select: MenuSelect,
    back_action: Any,
) -> RunSettings | None:
    """Choose run settings: global defaults, last settings, or edited settings."""

    last_settings = load_last_run_settings(kind, output_dir)
    label = "import" if kind == "import" else "benchmark"
    choices: list[Any] = [
        questionary.Choice(
            f"Run with global defaults ({global_defaults.summary()})",
            value="global",
        ),
    ]
    if last_settings is None:
        choices.append(
            questionary.Choice(
                f"Run with last {label} settings (none saved yet)",
                value="last",
                disabled="no saved settings",
            )
        )
    else:
        choices.append(
            questionary.Choice(
                f"Run with last {label} settings ({last_settings.summary()})",
                value="last",
            )
        )
    choices.append(questionary.Choice("Change run settings...", value="edit"))

    selection = menu_select(
        "Run settings",
        menu_help=(
            "Choose global defaults, reuse last run settings, or edit settings for this run only. "
            "Global settings are not modified here."
        ),
        choices=choices,
    )
    if selection in {None, back_action}:
        return None
    if selection == "global":
        return global_defaults
    if selection == "last":
        if last_settings is not None:
            return last_settings
        return global_defaults

    initial = last_settings or global_defaults
    edited = edit_run_settings(
        title=f"{label.title()} Run Settings",
        initial=initial,
    )
    return edited
