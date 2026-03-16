from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

import questionary

from cookimport.config.codex_decision import (
    TopTierProfileKind,
    apply_top_tier_profile_contract,
)
from cookimport.config.last_run_store import (
    load_qualitysuite_winner_run_settings,
)
from cookimport.config.run_settings import (
    RECIPE_CODEX_FARM_ALLOWED_PIPELINES,
    RECIPE_CODEX_FARM_EXECUTION_PIPELINES,
    RUN_SETTING_CONTRACT_FULL,
    RunSettings,
    project_run_config_payload,
)
from cookimport.llm.codex_farm_runner import list_codex_farm_models

MenuSelect = Callable[..., Any]
PromptConfirm = Callable[..., Any]
PromptText = Callable[..., Any]
_WORKER_UTILIZATION_ENV = "COOKIMPORT_WORKER_UTILIZATION"
_WORKER_UTILIZATION_DEFAULT = 1.0
_TOP_TIER_PROFILE_ENV = "COOKIMPORT_TOP_TIER_PROFILE"
_INTERACTIVE_RECIPE_PIPELINE_LABELS: dict[str, str] = {
    "off": "Vanilla / deterministic only",
    "codex-farm-single-correction-v1": "CodexFarm single correction",
}
_INTERACTIVE_BLOCK_LABEL_PIPELINE_LABELS: dict[str, str] = {
    "deterministic-v1": "Deterministic line-role baseline",
    "codex-line-role-v1": "Codex line-role block labelling",
}
_INTERACTIVE_KNOWLEDGE_PIPELINE_LABELS: dict[str, str] = {
    "off": "Off",
    "codex-farm-knowledge-v1": "CodexFarm knowledge extraction",
}
_CODEX_REASONING_EFFORT_ORDER = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)


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
    payload = global_defaults.model_dump(mode="json", exclude_none=True)
    payload = apply_top_tier_profile_contract(payload, "codexfarm")
    return RunSettings.from_dict(
        payload,
        warn_context="top-tier default run settings",
    )


def _default_vanilla_top_tier_settings(global_defaults: RunSettings) -> RunSettings:
    payload = global_defaults.model_dump(mode="json", exclude_none=True)
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
    payload = project_run_config_payload(
        settings.to_run_config_dict(),
        contract=RUN_SETTING_CONTRACT_FULL,
    )
    payload = apply_top_tier_profile_contract(payload, profile)
    return RunSettings.from_dict(payload, warn_context=warn_context)


def _normalize_top_tier_profile(value: Any) -> TopTierProfileKind | None:
    raw = str(value or "").strip().lower()
    if raw in {"codexfarm", "codex", "codex_farm"}:
        return "codexfarm"
    if raw in {"vanilla", "deterministic"}:
        return "vanilla"
    return None


def _default_codex_recipe_pipeline(global_defaults: RunSettings) -> str:
    current_pipeline = str(global_defaults.llm_recipe_pipeline.value).strip().lower()
    if current_pipeline in RECIPE_CODEX_FARM_EXECUTION_PIPELINES:
        return current_pipeline
    default_codex_settings = _default_top_tier_settings(global_defaults)
    resolved_pipeline = str(default_codex_settings.llm_recipe_pipeline.value).strip().lower()
    if resolved_pipeline in RECIPE_CODEX_FARM_EXECUTION_PIPELINES:
        return resolved_pipeline
    return RECIPE_CODEX_FARM_EXECUTION_PIPELINES[0]


def _normalize_interactive_recipe_pipeline(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in RECIPE_CODEX_FARM_ALLOWED_PIPELINES:
        return raw
    return None


def _normalize_interactive_block_label_pipeline(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in _INTERACTIVE_BLOCK_LABEL_PIPELINE_LABELS:
        return raw
    return None


def _normalize_interactive_knowledge_pipeline(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in _INTERACTIVE_KNOWLEDGE_PIPELINE_LABELS:
        return raw
    return None


def _choose_interactive_recipe_pipeline(
    *,
    menu_select: MenuSelect,
    back_action: Any,
    prompt_confirm: PromptConfirm | None,
    global_defaults: RunSettings,
) -> str | None:
    env_choice = _normalize_top_tier_profile(os.getenv(_TOP_TIER_PROFILE_ENV))
    if env_choice is not None:
        if env_choice == "vanilla":
            return "off"
        return _default_codex_recipe_pipeline(global_defaults)
    default_codex_enabled = (
        global_defaults.llm_recipe_pipeline.value.strip().lower() != "off"
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
        return (
            _default_codex_recipe_pipeline(global_defaults)
            if bool(use_codex_farm)
            else "off"
        )
    default_pipeline = _normalize_interactive_recipe_pipeline(
        global_defaults.llm_recipe_pipeline.value
    ) or "off"
    selection = menu_select(
        "Recipe pipeline for this run:",
        menu_help=(
            "Pick the recipe pipeline explicitly.\n"
            "Any CodexFarm choice still uses the codex top-tier parsing, line-role, and splitter contract.\n"
            "Vanilla keeps recipe Codex off and uses the deterministic top-tier profile."
        ),
        default=default_pipeline,
        choices=[
            questionary.Choice(
                f"{_INTERACTIVE_RECIPE_PIPELINE_LABELS['off']} (`off`)",
                value="off",
            ),
            questionary.Choice(
                (
                    f"{_INTERACTIVE_RECIPE_PIPELINE_LABELS['codex-farm-single-correction-v1']} "
                    "(`codex-farm-single-correction-v1`)"
                ),
                value="codex-farm-single-correction-v1",
            ),
        ],
    )
    if selection in {None, back_action}:
        return None
    return _normalize_interactive_recipe_pipeline(selection)


def _patch_interactive_settings(
    selected_settings: RunSettings,
    *,
    warn_context: str,
    **updates: Any,
) -> RunSettings:
    patched_payload = project_run_config_payload(
        selected_settings.to_run_config_dict(),
        contract=RUN_SETTING_CONTRACT_FULL,
    )
    patched_payload.update(updates)
    return RunSettings.from_dict(
        patched_payload,
        warn_context=warn_context,
    )


def _choose_interactive_benchmark_llm_surfaces(
    *,
    selected_settings: RunSettings,
    menu_select: MenuSelect,
    back_action: Any,
) -> RunSettings | None:
    line_role_default = _normalize_interactive_block_label_pipeline(
        selected_settings.line_role_pipeline.value
    ) or "deterministic-v1"
    line_role_choice = menu_select(
        "Block labelling for this run:",
        menu_help=(
            "Use deterministic line-role for the non-Codex baseline, or enable Codex "
            "line-role to benchmark the block-labelling LLM pass separately."
        ),
        default=line_role_default,
        choices=[
            questionary.Choice(
                (
                    f"{_INTERACTIVE_BLOCK_LABEL_PIPELINE_LABELS['deterministic-v1']} "
                    "(`deterministic-v1`)"
                ),
                value="deterministic-v1",
            ),
            questionary.Choice(
                (
                    f"{_INTERACTIVE_BLOCK_LABEL_PIPELINE_LABELS['codex-line-role-v1']} "
                    "(`codex-line-role-v1`)"
                ),
                value="codex-line-role-v1",
            ),
        ],
    )
    if line_role_choice in {None, back_action}:
        return None
    normalized_line_role = _normalize_interactive_block_label_pipeline(line_role_choice)
    if normalized_line_role is None:
        return None
    selected_settings = _patch_interactive_settings(
        selected_settings,
        warn_context="interactive benchmark llm surface overrides",
        line_role_pipeline=normalized_line_role,
        atomic_block_splitter="atomic-v1",
    )

    knowledge_default = _normalize_interactive_knowledge_pipeline(
        selected_settings.llm_knowledge_pipeline.value
    ) or "off"
    knowledge_choice = menu_select(
        "Knowledge harvest for this run:",
        menu_help=(
            "Turn knowledge extraction on only when you want Codex to classify "
            "non-recipe knowledge blocks for this benchmark run."
        ),
        default=knowledge_default,
        choices=[
            questionary.Choice(
                f"{_INTERACTIVE_KNOWLEDGE_PIPELINE_LABELS['off']} (`off`)",
                value="off",
            ),
            questionary.Choice(
                (
                    f"{_INTERACTIVE_KNOWLEDGE_PIPELINE_LABELS['codex-farm-knowledge-v1']} "
                    "(`codex-farm-knowledge-v1`)"
                ),
                value="codex-farm-knowledge-v1",
            ),
        ],
    )
    if knowledge_choice in {None, back_action}:
        return None
    normalized_knowledge = _normalize_interactive_knowledge_pipeline(knowledge_choice)
    if normalized_knowledge is None:
        return None
    return _patch_interactive_settings(
        selected_settings,
        warn_context="interactive benchmark llm surface overrides",
        llm_knowledge_pipeline=normalized_knowledge,
    )


def _selected_settings_enable_any_codex(selected_settings: RunSettings) -> bool:
    return any(
        (
            selected_settings.llm_recipe_pipeline.value != "off",
            selected_settings.line_role_pipeline.value == "codex-line-role-v1",
            selected_settings.llm_knowledge_pipeline.value != "off",
        )
    )


def _normalize_codex_reasoning_effort_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        candidate = str(value.value).strip().lower()
    else:
        candidate = str(value).strip().lower()
    return candidate or None


def supported_codex_farm_efforts_by_model(
    *,
    cmd: str | None = None,
    model_rows: Iterable[dict[str, Any]] | None = None,
) -> dict[str, tuple[str, ...]]:
    discovered_models = (
        list(model_rows)
        if model_rows is not None
        else list_codex_farm_models(cmd=cmd)
    )
    supported_by_model: dict[str, tuple[str, ...]] = {}
    for model_row in discovered_models:
        model_id = str(model_row.get("slug") or "").strip()
        if not model_id:
            continue
        raw_efforts = model_row.get("supported_reasoning_efforts")
        if not isinstance(raw_efforts, list):
            continue
        normalized_efforts: list[str] = []
        seen_efforts: set[str] = set()
        for raw_effort in raw_efforts:
            normalized_effort = _normalize_codex_reasoning_effort_value(raw_effort)
            if (
                normalized_effort is None
                or normalized_effort not in _CODEX_REASONING_EFFORT_ORDER
                or normalized_effort in seen_efforts
            ):
                continue
            normalized_efforts.append(normalized_effort)
            seen_efforts.add(normalized_effort)
        if normalized_efforts:
            supported_by_model[model_id] = tuple(normalized_efforts)
    return supported_by_model


def build_codex_farm_reasoning_effort_choices(
    *,
    selected_model: str | None,
    selected_effort: Any,
    supported_efforts_by_model: dict[str, tuple[str, ...]],
    default_label: str = "Pipeline default",
    default_value: str = "__default__",
    include_minimal: bool = True,
) -> tuple[list[questionary.Choice], str]:
    allowed_efforts = [
        effort
        for effort in _CODEX_REASONING_EFFORT_ORDER
        if include_minimal or effort != "minimal"
    ]
    normalized_model = str(selected_model or "").strip()
    model_supported_efforts = supported_efforts_by_model.get(normalized_model)
    if model_supported_efforts:
        supported_set = set(model_supported_efforts)
        allowed_efforts = [
            effort for effort in allowed_efforts if effort in supported_set
        ]

    resolved_default = _normalize_codex_reasoning_effort_value(selected_effort)
    choice_values = {default_value, *allowed_efforts}
    if resolved_default not in choice_values:
        resolved_default = default_value

    choices = [questionary.Choice(default_label, value=default_value)]
    choices.extend(
        questionary.Choice(effort, value=effort) for effort in allowed_efforts
    )
    return choices, resolved_default


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
    supported_efforts_by_model = supported_codex_farm_efforts_by_model(
        model_rows=discovered_models
    )
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

    effort_choices, effort_default = build_codex_farm_reasoning_effort_choices(
        selected_model=model_override,
        selected_effort=selected_settings.codex_farm_reasoning_effort,
        supported_efforts_by_model=supported_efforts_by_model,
    )
    effort_choice = menu_select(
        "Codex Farm reasoning effort override:",
        menu_help="Blank uses pipeline default. Affects all codex-farm passes.",
        default=effort_default,
        choices=effort_choices,
    )
    if effort_choice in {None, back_action}:
        return None
    reasoning_effort_override = (
        None if effort_choice == "__default__" else str(effort_choice)
    )
    patched_payload = project_run_config_payload(
        selected_settings.to_run_config_dict(),
        contract=RUN_SETTING_CONTRACT_FULL,
    )
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
    prompt_recipe_pipeline_menu: bool = False,
    prompt_benchmark_llm_surface_toggles: bool = False,
) -> RunSettings | None:
    """Resolve one interactive top-tier run profile family."""

    if prompt_recipe_pipeline_menu:
        selected_recipe_pipeline = _choose_interactive_recipe_pipeline(
            menu_select=menu_select,
            back_action=back_action,
            prompt_confirm=None,
            global_defaults=global_defaults,
        )
    else:
        selected_recipe_pipeline = _choose_interactive_recipe_pipeline(
            menu_select=menu_select,
            back_action=back_action,
            prompt_confirm=prompt_confirm,
            global_defaults=global_defaults,
        )
    if selected_recipe_pipeline is None:
        return None
    selected_profile: TopTierProfileKind = (
        "vanilla" if selected_recipe_pipeline == "off" else "codexfarm"
    )

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
    if selected_recipe_pipeline != selected_settings.llm_recipe_pipeline.value:
        selected_settings = _patch_interactive_settings(
            selected_settings,
            warn_context="interactive recipe pipeline selection override",
            llm_recipe_pipeline=selected_recipe_pipeline,
        )
    if prompt_benchmark_llm_surface_toggles:
        selected_settings = _choose_interactive_benchmark_llm_surfaces(
            selected_settings=selected_settings,
            menu_select=menu_select,
            back_action=back_action,
        )
        if selected_settings is None:
            return None
    if _selected_settings_enable_any_codex(selected_settings) and prompt_codex_ai_settings:
        selected_settings = _choose_codex_ai_settings(
            selected_settings=selected_settings,
            menu_select=menu_select,
            back_action=back_action,
        )
        if selected_settings is None:
            return None
    return _rate_limit_workers(selected_settings)
