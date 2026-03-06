from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import questionary

from cookimport.config.codex_decision import (
    TopTierProfileKind,
    apply_top_tier_profile_contract,
)
from cookimport.config.last_run_store import (
    load_qualitysuite_winner_run_settings,
)
from cookimport.config.run_settings import RunSettings
from cookimport.llm.codex_farm_runner import list_codex_farm_models

MenuSelect = Callable[..., Any]
PromptConfirm = Callable[..., Any]
PromptText = Callable[..., Any]
_QUALITY_FIRST_WINNER_STACK_PATCH: dict[str, Any] = {
    "epub_extractor": "unstructured",
    "epub_unstructured_html_parser_version": "v1",
    "epub_unstructured_preprocess_mode": "semantic_v1",
    "epub_unstructured_skip_headers_footers": True,
}
_WORKER_UTILIZATION_ENV = "COOKIMPORT_WORKER_UTILIZATION"
_WORKER_UTILIZATION_DEFAULT = 1.0
_TOP_TIER_PROFILE_ENV = "COOKIMPORT_TOP_TIER_PROFILE"


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


def _default_top_tier_settings(global_defaults: RunSettings) -> RunSettings:
    payload = global_defaults.to_run_config_dict()
    payload.update(_QUALITY_FIRST_WINNER_STACK_PATCH)
    payload = apply_top_tier_profile_contract(payload, "codexfarm")
    return RunSettings.from_dict(
        payload,
        warn_context="top-tier default run settings",
    )


def _default_vanilla_top_tier_settings(global_defaults: RunSettings) -> RunSettings:
    payload = global_defaults.to_run_config_dict()
    payload = apply_top_tier_profile_contract(payload, "vanilla")
    return RunSettings.from_dict(
        payload,
        warn_context="vanilla top-tier default run settings",
    )


def _harmonize_top_tier_pipeline_settings(
    settings: RunSettings,
    *,
    profile: TopTierProfileKind,
    warn_context: str,
) -> RunSettings:
    payload = settings.to_run_config_dict()
    payload = apply_top_tier_profile_contract(payload, profile)
    return RunSettings.from_dict(payload, warn_context=warn_context)


def _normalize_top_tier_profile(value: Any) -> TopTierProfileKind | None:
    raw = str(value or "").strip().lower()
    if raw in {"codexfarm", "codex", "codex_farm"}:
        return "codexfarm"
    if raw in {"vanilla", "deterministic"}:
        return "vanilla"
    return None


def _choose_top_tier_profile(
    *,
    menu_select: MenuSelect,
    back_action: Any,
    prompt_confirm: PromptConfirm | None,
    global_defaults: RunSettings,
) -> TopTierProfileKind | None:
    env_choice = _normalize_top_tier_profile(os.getenv(_TOP_TIER_PROFILE_ENV))
    if env_choice is not None:
        return env_choice
    default_codex_enabled = (
        global_defaults.llm_recipe_pipeline.value.strip().lower()
        == "codex-farm-3pass-v1"
    )
    if prompt_confirm is not None:
        use_codex_farm = prompt_confirm(
            "Use Codex Farm recipe pipeline for this run?",
            default=default_codex_enabled,
            instruction=(
                "Yes: codexfarm top-tier profile (winner settings if available). "
                "No: deterministic vanilla top-tier profile."
            ),
        )
        if use_codex_farm is None:
            return None
        return "codexfarm" if bool(use_codex_farm) else "vanilla"
    selection = menu_select(
        "Select automatic top-tier profile:",
        menu_help=(
            "Choose one deterministic profile family.\n"
            "CodexFarm profile keeps codex recipe + codex line-role + atomic splitter.\n"
            "Vanilla profile keeps codex off and uses deterministic line-role + atomic splitter."
        ),
        choices=[
            questionary.Choice(
                "CodexFarm automatic top-tier (recommended)",
                value="codexfarm",
            ),
            questionary.Choice(
                "Vanilla automatic top-tier",
                value="vanilla",
            ),
        ],
    )
    if selection in {None, back_action}:
        return None
    return _normalize_top_tier_profile(selection) or "codexfarm"


def _choose_codex_ai_settings(
    *,
    selected_settings: RunSettings,
    menu_select: MenuSelect,
    back_action: Any,
) -> RunSettings | None:
    model_default = (
        str(selected_settings.codex_farm_model).strip()
        if selected_settings.codex_farm_model is not None
        else "__pipeline_default__"
    )
    model_choices: list[questionary.Choice] = [
        questionary.Choice("Pipeline default", value="__pipeline_default__"),
    ]
    seen_model_ids: set[str] = {"__pipeline_default__"}
    if selected_settings.codex_farm_model is not None:
        current_override = str(selected_settings.codex_farm_model).strip()
        if current_override:
            model_choices.append(
                questionary.Choice(
                    f"Keep current override ({current_override})",
                    value=current_override,
                )
            )
            seen_model_ids.add(current_override)
            model_default = current_override
    discovered_models = list_codex_farm_models(cmd=selected_settings.codex_farm_cmd)
    for model_row in discovered_models:
        model_id = str(model_row.get("slug") or "").strip()
        if not model_id or model_id in seen_model_ids:
            continue
        description = str(model_row.get("description") or "").strip()
        label = model_id if not description else f"{model_id} - {description}"
        model_choices.append(questionary.Choice(label, value=model_id))
        seen_model_ids.add(model_id)
    if len(model_choices) == 1:
        fallback_model_id = "gpt-5.3-codex"
        model_choices.append(questionary.Choice(fallback_model_id, value=fallback_model_id))

    model_choice = menu_select(
        "Codex Farm model override:",
        menu_help=(
            "Choose a model override for this run.\n"
            "Pipeline default uses the model configured by the selected codex-farm pipelines."
        ),
        default=model_default,
        choices=model_choices,
    )
    if model_choice in {None, back_action}:
        return None
    model_override = (
        None if str(model_choice) == "__pipeline_default__" else str(model_choice).strip()
    ) or None

    effort_default = (
        str(selected_settings.codex_farm_reasoning_effort)
        if selected_settings.codex_farm_reasoning_effort is not None
        else "__default__"
    )
    effort_choice = menu_select(
        "Codex Farm reasoning effort override:",
        menu_help="Blank uses pipeline default. Affects all codex-farm passes.",
        default=effort_default,
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
    reasoning_effort_override = (
        None if effort_choice == "__default__" else str(effort_choice)
    )
    patched_payload = selected_settings.to_run_config_dict()
    patched_payload["codex_farm_model"] = model_override
    patched_payload["codex_farm_reasoning_effort"] = reasoning_effort_override
    return RunSettings.from_dict(
        patched_payload,
        warn_context="interactive codex ai settings",
    )


def choose_run_settings(
    *,
    global_defaults: RunSettings,
    output_dir: Path,
    menu_select: MenuSelect,
    back_action: Any,
    prompt_confirm: PromptConfirm | None = None,
    prompt_text: PromptText | None = None,
    prompt_codex_ai_settings: bool = False,
) -> RunSettings | None:
    """Resolve one interactive top-tier run profile family."""

    selected_profile = _choose_top_tier_profile(
        menu_select=menu_select,
        back_action=back_action,
        prompt_confirm=prompt_confirm,
        global_defaults=global_defaults,
    )
    if selected_profile is None:
        return None

    if selected_profile == "vanilla":
        selected_settings = _default_vanilla_top_tier_settings(global_defaults)
    else:
        qualitysuite_winner_settings = load_qualitysuite_winner_run_settings(output_dir)
        selected_settings = (
            qualitysuite_winner_settings
            if qualitysuite_winner_settings is not None
            else _default_top_tier_settings(global_defaults)
        )
    selected_settings = _harmonize_top_tier_pipeline_settings(
        selected_settings,
        profile=selected_profile,
        warn_context="interactive top-tier pipeline harmonization",
    )
    if selected_profile == "codexfarm" and prompt_codex_ai_settings:
        selected_settings = _choose_codex_ai_settings(
            selected_settings=selected_settings,
            menu_select=menu_select,
            back_action=back_action,
        )
        if selected_settings is None:
            return None
    return _rate_limit_workers(selected_settings)
