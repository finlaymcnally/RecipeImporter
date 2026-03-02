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
from cookimport.config.run_settings import LlmRecipePipeline, RunSettings
from cookimport.llm.codex_farm_runner import list_codex_farm_models
from .toggle_editor import edit_run_settings

RunSettingsKind = Literal["import", "benchmark"]
MenuSelect = Callable[..., Any]
PromptConfirm = Callable[..., Any]
PromptText = Callable[..., Any]
_PREFERRED_FORMAT_PATCH: dict[str, Any] = {
    "epub_extractor": "beautifulsoup",
    "instruction_step_segmentation_policy": "off",
}
_QUALITY_FIRST_WINNER_STACK_PATCH: dict[str, Any] = {
    "epub_extractor": "unstructured",
    "epub_unstructured_html_parser_version": "v1",
    "epub_unstructured_preprocess_mode": "semantic_v1",
    "epub_unstructured_skip_headers_footers": True,
}
_WORKER_UTILIZATION_ENV = "COOKIMPORT_WORKER_UTILIZATION"
_WORKER_UTILIZATION_DEFAULT = 0.9


def _worker_utilization() -> float | None:
    raw = os.getenv(_WORKER_UTILIZATION_ENV)
    if not raw:
        return _WORKER_UTILIZATION_DEFAULT
    try:
        parsed = float(str(raw).strip())
    except (TypeError, ValueError):
        return _WORKER_UTILIZATION_DEFAULT
    if parsed <= 0:
        return _WORKER_UTILIZATION_DEFAULT
    if parsed > 100:
        return 1.0
    if parsed > 1:
        parsed = parsed / 100
    return min(parsed, 1.0)


def _rate_limit_workers(selected_settings: RunSettings) -> RunSettings:
    utilization = _worker_utilization()
    if utilization is None or utilization >= 1.0:
        return selected_settings
    return selected_settings.model_copy(
        update={
            "workers": max(1, int(selected_settings.workers * utilization)),
            "pdf_split_workers": max(
                1,
                int(selected_settings.pdf_split_workers * utilization),
            ),
            "epub_split_workers": max(
                1,
                int(selected_settings.epub_split_workers * utilization),
            ),
        }
    )


def _default_preferred_settings(global_defaults: RunSettings) -> RunSettings:
    payload = global_defaults.to_run_config_dict()
    payload.update(_PREFERRED_FORMAT_PATCH)
    return RunSettings.from_dict(payload, warn_context="preferred format defaults")


def _default_quality_first_winner_settings(global_defaults: RunSettings) -> RunSettings:
    payload = global_defaults.to_run_config_dict()
    payload.update(_QUALITY_FIRST_WINNER_STACK_PATCH)
    return RunSettings.from_dict(
        payload,
        warn_context="quality-first winner stack defaults",
    )


def _codex_farm_model_choices(
    selected_settings: RunSettings,
) -> list[questionary.Choice]:
    current_model = str(selected_settings.codex_farm_model or "").strip() or None
    keep_label = (
        f"Keep current setting ({current_model})"
        if current_model
        else "Keep current setting (pipeline default)"
    )
    choices: list[questionary.Choice] = [
        questionary.Choice(keep_label, value="__keep__"),
    ]
    if current_model:
        choices.append(
            questionary.Choice(
                "Use pipeline default (clear override)",
                value="__pipeline_default__",
            )
        )

    seen_models: set[str] = set()
    if current_model:
        seen_models.add(current_model)
    discovered_models = list_codex_farm_models(cmd=selected_settings.codex_farm_cmd)
    for entry in discovered_models:
        model_id = str(entry.get("slug") or "").strip()
        if not model_id or model_id in seen_models:
            continue
        description = str(entry.get("description") or "").strip()
        label = model_id if not description else f"{model_id} - {description}"
        choices.append(questionary.Choice(label, value=model_id))
        seen_models.add(model_id)
    if not discovered_models and "gpt-5.3-codex" not in seen_models:
        choices.append(questionary.Choice("gpt-5.3-codex", value="gpt-5.3-codex"))

    choices.append(questionary.Choice("custom model id...", value="__custom__"))
    return choices


def _apply_codex_model_prompts(
    *,
    selected_settings: RunSettings,
    menu_select: MenuSelect,
    prompt_text: PromptText,
    back_action: Any,
) -> RunSettings | None:
    current_model = str(selected_settings.codex_farm_model or "").strip() or None
    model_choice = menu_select(
        "Codex Farm model override:",
        menu_help=(
            "Pick a model for this run. Keep current preserves the selected profile value."
        ),
        choices=_codex_farm_model_choices(selected_settings),
    )
    if model_choice in {None, back_action}:
        return None
    if model_choice == "__keep__":
        model_override = current_model
    elif model_choice == "__pipeline_default__":
        model_override = None
    elif model_choice == "__custom__":
        custom_model = prompt_text(
            "Codex Farm model id:",
            default=str(current_model or ""),
        )
        if custom_model is None:
            return None
        model_override = str(custom_model).strip() or None
    else:
        model_override = str(model_choice).strip() or None

    effort_choice = menu_select(
        "Codex Farm reasoning effort override:",
        menu_help="Blank uses pipeline default. Affects all codex-farm passes.",
        choices=[
            questionary.Choice("Pipeline default", value="__default__"),
            questionary.Choice("none", value="none"),
            questionary.Choice("minimal", value="minimal"),
            questionary.Choice("low", value="low"),
            questionary.Choice("medium", value="medium"),
            questionary.Choice("high", value="high"),
            questionary.Choice("xhigh", value="xhigh"),
        ],
    )
    if effort_choice in {None, back_action}:
        return None

    payload = selected_settings.to_run_config_dict()
    payload["codex_farm_model"] = model_override
    payload["codex_farm_reasoning_effort"] = (
        None if effort_choice == "__default__" else str(effort_choice)
    )
    return RunSettings.from_dict(
        payload,
        warn_context="interactive run settings codex model overrides",
    )


def _apply_codex_prompt(
    *,
    selected_settings: RunSettings,
    menu_select: MenuSelect,
    back_action: Any,
    prompt_confirm: PromptConfirm | None,
    prompt_text: PromptText | None,
) -> RunSettings | None:
    if prompt_confirm is None:
        return selected_settings

    codex_pipeline_value = LlmRecipePipeline.codex_farm_3pass_v1.value
    use_codex = prompt_confirm(
        "Use Codex Farm recipe pipeline for this run?",
        default=True,
    )
    if use_codex is None:
        return None

    requested_codex = bool(use_codex)
    payload = selected_settings.to_run_config_dict()
    payload["llm_recipe_pipeline"] = (
        codex_pipeline_value if requested_codex else LlmRecipePipeline.off.value
    )
    resolved_settings = RunSettings.from_dict(
        payload,
        warn_context="interactive run settings codex toggle",
    )

    codex_effective = (
        resolved_settings.llm_recipe_pipeline.value == codex_pipeline_value
    )
    if not codex_effective:
        return resolved_settings
    if prompt_text is None:
        return resolved_settings

    return _apply_codex_model_prompts(
        selected_settings=resolved_settings,
        menu_select=menu_select,
        prompt_text=prompt_text,
        back_action=back_action,
    )


def choose_run_settings(
    *,
    kind: RunSettingsKind,
    global_defaults: RunSettings,
    output_dir: Path,
    menu_select: MenuSelect,
    back_action: Any,
    prompt_confirm: PromptConfirm | None = None,
    prompt_text: PromptText | None = None,
) -> RunSettings | None:
    """Choose run settings: global defaults, last settings, or edited settings."""

    last_settings = load_last_run_settings(kind, output_dir)
    preferred_settings = load_preferred_run_settings(output_dir)
    qualitysuite_winner_settings = load_qualitysuite_winner_run_settings(output_dir)
    quality_first_winner_settings = _default_quality_first_winner_settings(
        global_defaults
    )
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
        questionary.Choice(
            "Run with quality-first winner stack "
            f"({quality_first_winner_settings.summary()})",
            value="quality_first_winner_stack",
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
    elif selection == "quality_first_winner_stack":
        selected_settings = quality_first_winner_settings
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

    selected_settings = _rate_limit_workers(selected_settings)

    return _apply_codex_prompt(
        selected_settings=selected_settings,
        menu_select=menu_select,
        back_action=back_action,
        prompt_confirm=prompt_confirm,
        prompt_text=prompt_text,
    )
