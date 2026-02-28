from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Literal

import questionary

from cookimport.config.last_run_store import (
    load_last_run_settings,
    load_preferred_run_settings,
    load_qualitysuite_winner_run_settings,
)
from cookimport.config.run_settings import (
    RECIPE_CODEX_FARM_UNLOCK_ENV,
    LlmRecipePipeline,
    RunSettings,
)
from .toggle_editor import edit_run_settings

RunSettingsKind = Literal["import", "benchmark"]
MenuSelect = Callable[..., Any]
PromptConfirm = Callable[..., Any]
_PREFERRED_FORMAT_PATCH: dict[str, Any] = {
    "epub_extractor": "beautifulsoup",
    "instruction_step_segmentation_policy": "off",
}


def _default_preferred_settings(global_defaults: RunSettings) -> RunSettings:
    payload = global_defaults.to_run_config_dict()
    payload.update(_PREFERRED_FORMAT_PATCH)
    return RunSettings.from_dict(payload, warn_context="preferred format defaults")


def _apply_codex_prompt(
    *,
    selected_settings: RunSettings,
    prompt_confirm: PromptConfirm | None,
) -> RunSettings | None:
    if prompt_confirm is None:
        return selected_settings

    codex_pipeline_value = LlmRecipePipeline.codex_farm_3pass_v1.value
    codex_enabled = selected_settings.llm_recipe_pipeline.value == codex_pipeline_value
    unlock_note = ""
    if os.getenv(RECIPE_CODEX_FARM_UNLOCK_ENV, "").strip() != "1":
        unlock_note = f" (requires {RECIPE_CODEX_FARM_UNLOCK_ENV}=1)"
    use_codex = prompt_confirm(
        f"Use Codex Farm recipe pipeline for this run?{unlock_note}",
        default=codex_enabled,
    )
    if use_codex is None:
        return None

    requested_codex = bool(use_codex)
    if requested_codex == codex_enabled:
        return selected_settings

    payload = selected_settings.to_run_config_dict()
    payload["llm_recipe_pipeline"] = (
        codex_pipeline_value if requested_codex else LlmRecipePipeline.off.value
    )
    return RunSettings.from_dict(
        payload,
        warn_context="interactive run settings codex toggle",
    )


def choose_run_settings(
    *,
    kind: RunSettingsKind,
    global_defaults: RunSettings,
    output_dir: Path,
    menu_select: MenuSelect,
    back_action: Any,
    prompt_confirm: PromptConfirm | None = None,
) -> RunSettings | None:
    """Choose run settings: global defaults, last settings, or edited settings."""

    last_settings = load_last_run_settings(kind, output_dir)
    preferred_settings = load_preferred_run_settings(output_dir)
    qualitysuite_winner_settings = load_qualitysuite_winner_run_settings(output_dir)
    if preferred_settings is None:
        preferred_settings = _default_preferred_settings(global_defaults)
    label = "import" if kind == "import" else "benchmark"
    choices: list[Any] = [
        questionary.Choice(
            f"Run with global defaults ({global_defaults.summary()})",
            value="global",
        ),
        questionary.Choice(
            f"Run with preferred format ({preferred_settings.summary()})",
            value="preferred",
        ),
    ]
    if qualitysuite_winner_settings is None:
        choices.append(
            questionary.Choice(
                "Run with quality-suite winner (none saved yet)",
                value="qualitysuite_winner",
                disabled="no saved settings",
            )
        )
    else:
        choices.append(
            questionary.Choice(
                "Run with quality-suite winner "
                f"({qualitysuite_winner_settings.summary()})",
                value="qualitysuite_winner",
            )
        )
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

    selected_settings: RunSettings
    if selection == "global":
        selected_settings = global_defaults
    elif selection == "preferred":
        selected_settings = preferred_settings
    elif selection == "qualitysuite_winner":
        if qualitysuite_winner_settings is not None:
            selected_settings = qualitysuite_winner_settings
        else:
            selected_settings = global_defaults
    elif selection == "last":
        if last_settings is not None:
            selected_settings = last_settings
        else:
            selected_settings = global_defaults
    else:
        initial = last_settings or global_defaults
        edited = edit_run_settings(
            title=f"{label.title()} Run Settings",
            initial=initial,
        )
        if edited is None:
            return None
        selected_settings = edited

    return _apply_codex_prompt(
        selected_settings=selected_settings,
        prompt_confirm=prompt_confirm,
    )
