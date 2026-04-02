from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import questionary
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from questionary import utils
from questionary.prompts import common
from questionary.question import Question
from questionary.styles import merge_styles_default

from cookimport.config.codex_decision import (
    TopTierProfileKind,
    apply_top_tier_profile_contract,
)
from cookimport.config.last_run_store import (
    load_qualitysuite_winner_run_settings,
)
from cookimport.config.run_settings_contracts import (
    RUN_SETTING_CONTRACT_FULL,
    project_run_config_payload,
)
from cookimport.config.run_settings import (
    CODEX_EXEC_STYLE_INLINE_JSON_V1,
    CODEX_EXEC_STYLE_TASKFILE_V1,
    KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
    LINE_ROLE_PIPELINE_ROUTE_V2,
    RECIPE_CODEX_FARM_ALLOWED_PIPELINES,
    RECIPE_CODEX_FARM_EXECUTION_PIPELINES,
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
    RunSettings,
    normalize_codex_exec_style_value,
    normalize_llm_recipe_pipeline_value,
)
from cookimport.llm.codex_farm_runner import list_codex_farm_models
from cookimport.llm.shard_survivability import default_stage_survivability_budget

MenuSelect = Callable[..., Any]
PromptConfirm = Callable[..., Any]
PromptCodexSurfaceMenu = Callable[..., Any]
PromptCodexShardPlanMenu = Callable[..., Any]
PromptText = Callable[..., Any]
_WORKER_UTILIZATION_ENV = "COOKIMPORT_WORKER_UTILIZATION"
_WORKER_UTILIZATION_DEFAULT = 1.0
_TOP_TIER_PROFILE_ENV = "COOKIMPORT_TOP_TIER_PROFILE"
_INTERACTIVE_RECIPE_PIPELINE_LABELS: dict[str, str] = {
    "off": "Vanilla / no Codex",
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1: "Codex Exec",
}
_CODEX_SURFACE_OPTION_LABELS: dict[str, str] = {
    "recipe": "recipe correction",
    "line_role": "block labelling",
    "knowledge": "non-recipe finalize",
}
_CODEX_REASONING_EFFORT_ORDER = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
_CODEX_SURFACE_PROMPT_TARGET_FIELDS: dict[str, tuple[str, str]] = {
    "recipe": ("recipe_prompt_target_count", "Recipe correction"),
    "line_role": ("line_role_prompt_target_count", "Block labelling"),
    "knowledge": ("knowledge_prompt_target_count", "Knowledge"),
}
_CODEX_SURFACE_STAGE_KEYS: dict[str, str] = {
    "recipe": "recipe_refine",
    "line_role": "line_role",
    "knowledge": "nonrecipe_finalize",
}
_CODEX_EXEC_STYLE_LABELS: dict[str, str] = {
    CODEX_EXEC_STYLE_TASKFILE_V1: "Taskfile workers",
    CODEX_EXEC_STYLE_INLINE_JSON_V1: "Inline JSON",
}
INTERACTIVE_BENCHMARK_PRESET_SALT_FAT_ACID_HEAT_CUTDOWN_FAST = (
    "saltfatacidheatcutdown_fast_codex_exec"
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
    payload = apply_top_tier_profile_contract(payload, "codex-exec")
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
    if raw in {"codex-exec", "codex", "codex_farm"}:
        return "codex-exec"
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
    try:
        return normalize_llm_recipe_pipeline_value(value)
    except ValueError:
        return None


def _format_codex_surface_list(surface_options: tuple[str, ...] | None) -> str | None:
    if not surface_options:
        return None
    labels = [
        _CODEX_SURFACE_OPTION_LABELS[option]
        for option in surface_options
        if option in _CODEX_SURFACE_OPTION_LABELS
    ]
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"


def _choose_interactive_recipe_pipeline(
    *,
    menu_select: MenuSelect,
    back_action: Any,
    prompt_confirm: PromptConfirm | None,
    global_defaults: RunSettings,
    codex_surface_menu_options: tuple[str, ...] | None = None,
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
            "Use Codex Exec recipe pipeline for this run?",
            default=default_codex_enabled,
            instruction=(
                "Yes: codex-exec top-tier profile (winner settings if available). "
                "No: fully vanilla top-tier profile."
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
    codex_surface_list = _format_codex_surface_list(codex_surface_menu_options)
    if codex_surface_list:
        menu_help = (
            "Pick the high-level workflow first.\n"
            f"Codex Exec opens one follow-up menu where you can toggle {codex_surface_list} together.\n"
            "Vanilla keeps this run on the fully vanilla top-tier profile."
        )
    else:
        menu_help = (
            "Pick the high-level workflow first.\n"
            "Codex Exec uses the codex top-tier profile.\n"
            "Vanilla keeps every Codex surface off."
        )
    selection = menu_select(
        "Workflow for this run:",
        menu_help=menu_help,
        default=default_pipeline,
        choices=[
            questionary.Choice(
                _INTERACTIVE_RECIPE_PIPELINE_LABELS["off"],
                value="off",
            ),
            questionary.Choice(
                _INTERACTIVE_RECIPE_PIPELINE_LABELS[RECIPE_CODEX_FARM_PIPELINE_SHARD_V1],
                value=RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
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


def _prompt_codex_surface_menu(
    *,
    message: str,
    step_rows: list[tuple[str, str]],
    enabled_by_step: dict[str, bool],
    back_action: Any,
    **kwargs: Any,
) -> dict[str, bool] | Any:
    label_width = max((len(label) for _step_id, label in step_rows), default=0)
    choices: list[questionary.Choice] = [
        questionary.Choice("", value=step_id, shortcut_key=False)
        for step_id, _label in step_rows
    ]
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("Continue", value="__done__"))
    choice_labels = dict(step_rows)
    merged_style = merge_styles_default([])

    ic = common.InquirerControl(
        choices,
        default="__done__",
        pointer="»",
        use_indicator=False,
        use_shortcuts=False,
        show_selected=False,
        show_description=False,
        use_arrow_keys=True,
        initial_choice=choices[0] if step_rows else choices[-1],
    )

    def _sync_titles() -> None:
        for index, choice in enumerate(ic.choices):
            if isinstance(choice, questionary.Separator):
                continue
            if choice.value == "__done__":
                choice.title = "Continue"
                continue
            step_id = str(choice.value)
            label = choice_labels.get(step_id, step_id)
            is_current = index == ic.pointed_at
            is_enabled = bool(enabled_by_step.get(step_id))
            label_class = "class:highlighted" if is_current else "class:text"
            selected_class = "class:selected"
            inactive_class = "class:text"
            yes_class = (
                "class:highlighted"
                if is_current and is_enabled
                else (selected_class if is_enabled else inactive_class)
            )
            no_class = (
                "class:highlighted"
                if is_current and not is_enabled
                else (selected_class if not is_enabled else inactive_class)
            )
            yes_text = (
                ">[Yes]<"
                if is_current and is_enabled
                else (" [Yes] " if is_enabled else " [yes] ")
            )
            no_text = (
                ">[No ]<"
                if is_current and not is_enabled
                else (" [No ] " if not is_enabled else " [no ] ")
            )
            choice.title = [
                (label_class, f"{label.ljust(label_width)}  "),
                (yes_class, yes_text),
                (inactive_class, " "),
                (no_class, no_text),
            ]

    def _select_next() -> None:
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    def _select_previous() -> None:
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    def _set_current_state(enabled: bool) -> None:
        current = ic.get_pointed_at()
        step_id = str(current.value)
        if step_id in enabled_by_step:
            enabled_by_step[step_id] = enabled

    _sync_titles()

    def _get_prompt_tokens() -> list[tuple[str, str]]:
        return [
            ("class:qmark", "?"),
            ("class:question", f" {message} "),
            (
                "class:instruction",
                "(Use up/down to pick a row, left/right to choose Yes/No, Enter to continue, Esc to go back)",
            ),
        ]

    layout = common.create_inquirer_layout(ic, _get_prompt_tokens, **kwargs)
    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _abort(event: Any) -> None:
        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    @bindings.add(Keys.Escape, eager=True)
    def _go_back(event: Any) -> None:
        event.app.exit(result=back_action)

    @bindings.add(Keys.Down, eager=True)
    def _move_down(event: Any) -> None:
        _select_next()
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Up, eager=True)
    def _move_up(event: Any) -> None:
        _select_previous()
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Left, eager=True)
    @bindings.add("h", eager=True)
    def _set_yes(event: Any) -> None:
        _set_current_state(True)
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Right, eager=True)
    @bindings.add("l", eager=True)
    def _set_no(event: Any) -> None:
        _set_current_state(False)
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.ControlM, eager=True)
    def _submit(event: Any) -> None:
        current = ic.get_pointed_at()
        current_value = str(current.value)
        if current_value == "__done__":
            ic.is_answered = True
            event.app.exit(result=dict(enabled_by_step))
            return
        if current_value in enabled_by_step:
            enabled_by_step[current_value] = not enabled_by_step[current_value]
            _sync_titles()
            event.app.invalidate()

    @bindings.add(Keys.Any)
    def _other(event: Any) -> None:
        """Disallow inserting other text."""

    question = Question(
        Application(
            layout=layout,
            key_bindings=bindings,
            style=merged_style,
            **utils.used_kwargs(kwargs, Application.__init__),
        )
    )
    return question.ask()


def _choose_interactive_codex_surfaces(
    *,
    selected_settings: RunSettings,
    prompt_codex_surface_menu: PromptCodexSurfaceMenu,
    prompt_codex_shard_plan_menu: PromptCodexShardPlanMenu | None,
    back_action: Any,
    surface_options: tuple[str, ...],
    target_context: Mapping[str, Any] | None = None,
) -> RunSettings | None:
    step_rows: list[tuple[str, str]] = []
    enabled_by_step: dict[str, bool] = {}
    for step_id in surface_options:
        if step_id == "recipe":
            step_rows.append(
                ("recipe", f"Recipe correction (`{RECIPE_CODEX_FARM_PIPELINE_SHARD_V1}`)")
            )
            enabled_by_step["recipe"] = (
                selected_settings.llm_recipe_pipeline.value != "off"
            )
        elif step_id == "line_role":
            step_rows.append(
                ("line_role", f"Block labelling (`{LINE_ROLE_PIPELINE_ROUTE_V2}`)")
            )
            enabled_by_step["line_role"] = (
                selected_settings.line_role_pipeline.value == LINE_ROLE_PIPELINE_ROUTE_V2
            )
        elif step_id == "knowledge":
            step_rows.append(
                ("knowledge", f"Knowledge harvest (`{KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2}`)")
            )
            enabled_by_step["knowledge"] = (
                selected_settings.llm_knowledge_pipeline.value != "off"
            )

    enabled_by_step = prompt_codex_surface_menu(
        message="Codex Exec options for this run:",
        step_rows=step_rows,
        enabled_by_step=enabled_by_step,
        back_action=back_action,
    )
    if enabled_by_step is None or enabled_by_step is back_action:
        return None

    selected_step_ids = [
        step_id for step_id, _label in step_rows if bool(enabled_by_step.get(step_id))
    ]
    resolved_recipe_pipeline = (
        _normalize_interactive_recipe_pipeline(selected_settings.llm_recipe_pipeline.value)
        or RECIPE_CODEX_FARM_EXECUTION_PIPELINES[0]
    )
    selected_settings = _patch_interactive_settings(
        selected_settings,
        warn_context="interactive benchmark llm surface overrides",
        llm_recipe_pipeline=(
            resolved_recipe_pipeline if "recipe" in selected_step_ids else "off"
        ),
        line_role_pipeline=(
            LINE_ROLE_PIPELINE_ROUTE_V2
            if "line_role" in selected_step_ids
            else "off"
        ),
        llm_knowledge_pipeline=(
            KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2 if "knowledge" in selected_step_ids else "off"
        ),
        atomic_block_splitter=(
            selected_settings.atomic_block_splitter.value
            if "line_role" in selected_step_ids
            else "off"
        ),
    )
    if prompt_codex_shard_plan_menu is None or not selected_step_ids:
        return selected_settings
    return _choose_interactive_codex_prompt_targets(
        selected_settings=selected_settings,
        prompt_codex_shard_plan_menu=prompt_codex_shard_plan_menu,
        back_action=back_action,
        selected_step_ids=selected_step_ids,
        target_context=target_context,
    )


def _prompt_codex_prompt_target_count(
    *,
    prompt_text: PromptText,
    message: str,
    default_value: int,
    back_action: Any,
) -> int | None:
    max_value = 256
    raw_value = prompt_text(
        message,
        default=str(default_value),
        instruction=(
            "Approximate prompts for this task in this run. Use a whole number "
            f"from 1 to {max_value}. Press Esc to go back."
        ),
        validate=lambda text: (
            True
            if (
                str(text or "").strip().isdigit()
                and 1 <= int(str(text).strip()) <= max_value
            )
            else f"Enter a whole number from 1 to {max_value}."
        ),
    )
    if raw_value in {None, back_action}:
        return None
    normalized = str(raw_value).strip()
    if not normalized:
        return int(default_value)
    try:
        parsed = int(normalized)
    except ValueError:
        return None
    return parsed if 1 <= parsed <= max_value else None


def _format_shard_budget_value(token_count: int) -> str:
    if token_count >= 1_000_000:
        return f"{token_count / 1_000_000:.1f}m"
    if token_count >= 1_000:
        return f"{token_count // 1_000}k"
    return str(token_count)


def _build_codex_shard_plan_rows(
    *,
    selected_settings: RunSettings,
    selected_step_ids: Sequence[str],
    target_context: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    recommendations_by_step = (
        target_context.get("recommendations_by_step")
        if isinstance(target_context, Mapping)
        else None
    )
    recommendation_lookup = (
        dict(recommendations_by_step)
        if isinstance(recommendations_by_step, Mapping)
        else {}
    )
    rows: list[dict[str, Any]] = []
    for step_id in selected_step_ids:
        if step_id not in _CODEX_SURFACE_PROMPT_TARGET_FIELDS:
            continue
        field_name, label = _CODEX_SURFACE_PROMPT_TARGET_FIELDS[step_id]
        current_value = getattr(selected_settings, field_name, None)
        recommendation = recommendation_lookup.get(step_id)
        recommendation_payload = (
            dict(recommendation) if isinstance(recommendation, Mapping) else {}
        )
        minimum_safe_shard_count = recommendation_payload.get(
            "minimum_safe_shard_count"
        )
        binding_limit = str(recommendation_payload.get("binding_limit") or "").strip() or None
        stage_budget = default_stage_survivability_budget(
            _CODEX_SURFACE_STAGE_KEYS.get(step_id, step_id)
        )
        rows.append(
            {
                "step_id": step_id,
                "label": label,
                "current_count": max(
                    1,
                    int(current_value) if current_value is not None else 5,
                ),
                "minimum_safe_shard_count": (
                    int(minimum_safe_shard_count)
                    if minimum_safe_shard_count is not None
                    else None
                ),
                "binding_limit": binding_limit,
                "budget_summary": (
                    f"in {_format_shard_budget_value(stage_budget.max_input_tokens)} / "
                    f"out {_format_shard_budget_value(stage_budget.max_output_tokens)} / "
                    f"peak {_format_shard_budget_value(stage_budget.max_session_peak_tokens)}"
                ),
            }
        )
    return rows


def _build_codex_shard_plan_summary_lines(
    *,
    target_context: Mapping[str, Any] | None,
    rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    lines: list[str] = []
    title = str((target_context or {}).get("title") or "").strip()
    if title:
        lines.append(title)
    raw_summary_lines = (
        (target_context or {}).get("summary_lines")
        if isinstance(target_context, Mapping)
        else None
    )
    if isinstance(raw_summary_lines, Sequence) and not isinstance(
        raw_summary_lines, (str, bytes)
    ):
        for line in raw_summary_lines:
            text = str(line or "").strip()
            if text:
                lines.append(text)
    has_recommendations = any(
        row.get("minimum_safe_shard_count") is not None for row in rows
    )
    if not has_recommendations:
        lines.append(
            "Exact survivability estimates appear after deterministic planning. "
            "Live preflight still refuses unsafe shard counts before worker launch."
        )
    return lines


def _prompt_codex_shard_plan_menu(
    *,
    message: str,
    rows: list[dict[str, Any]],
    summary_lines: Sequence[str],
    back_action: Any,
    max_value: int = 256,
    **kwargs: Any,
) -> dict[str, int] | Any:
    choices: list[questionary.Choice | questionary.Separator] = []
    for summary_line in summary_lines:
        choices.append(questionary.Separator(summary_line))
    if summary_lines:
        choices.append(questionary.Separator())
    for row in rows:
        choices.append(
            questionary.Choice(
                "",
                value=str(row.get("step_id") or ""),
                shortcut_key=False,
            )
        )
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("Continue", value="__done__"))
    row_lookup = {
        str(row.get("step_id") or ""): row
        for row in rows
        if str(row.get("step_id") or "").strip()
    }
    label_width = max(
        (len(str(row.get("label") or "")) for row in rows),
        default=0,
    )
    merged_style = merge_styles_default([])
    initial_choice = next(
        (
            choice
            for choice in choices
            if not isinstance(choice, questionary.Separator)
            and str(choice.value) != "__done__"
        ),
        choices[-1],
    )

    ic = common.InquirerControl(
        choices,
        default="__done__",
        pointer="»",
        use_indicator=False,
        use_shortcuts=False,
        show_selected=False,
        show_description=False,
        use_arrow_keys=True,
        initial_choice=initial_choice,
    )

    def _select_next() -> None:
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    def _select_previous() -> None:
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    def _set_current_count(delta: int) -> None:
        current = ic.get_pointed_at()
        step_id = str(current.value)
        row = row_lookup.get(step_id)
        if row is None:
            return
        current_count = int(row.get("current_count") or 1)
        row["current_count"] = max(1, min(max_value, current_count + delta))

    def _adopt_recommendation_or_increment() -> None:
        current = ic.get_pointed_at()
        step_id = str(current.value)
        row = row_lookup.get(step_id)
        if row is None:
            return
        recommended = row.get("minimum_safe_shard_count")
        if recommended is not None and int(row.get("current_count") or 1) != int(
            recommended
        ):
            row["current_count"] = max(1, min(max_value, int(recommended)))
            return
        _set_current_count(1)

    def _sync_titles() -> None:
        for index, choice in enumerate(ic.choices):
            if isinstance(choice, questionary.Separator):
                continue
            if choice.value == "__done__":
                choice.title = "Continue"
                continue
            step_id = str(choice.value)
            row = row_lookup.get(step_id) or {}
            label = str(row.get("label") or step_id)
            is_current = index == ic.pointed_at
            count_value = int(row.get("current_count") or 1)
            minimum_safe = row.get("minimum_safe_shard_count")
            binding_limit = str(row.get("binding_limit") or "").strip()
            budget_summary = str(row.get("budget_summary") or "").strip()
            label_class = "class:highlighted" if is_current else "class:text"
            count_class = "class:highlighted" if is_current else "class:selected"
            if minimum_safe is not None:
                recommended_text = f"min {int(minimum_safe)}"
                if count_value < int(minimum_safe):
                    note_text = (
                        f"unsafe: {binding_limit}"
                        if binding_limit
                        else "unsafe"
                    )
                    note_class = "class:answer"
                else:
                    note_text = (
                        f"safe: {binding_limit}"
                        if binding_limit
                        else "safe"
                    )
                    note_class = "class:selected"
            else:
                recommended_text = "min --"
                note_text = budget_summary
                note_class = "class:text"
            count_text = f"[{count_value:>3}]"
            if is_current:
                count_text = f">[{count_value:>3}]<"
            choice.title = [
                (label_class, f"{label.ljust(label_width)}  "),
                (count_class, f"{count_text}  "),
                ("class:text", f"{recommended_text:<7}  "),
                (note_class, note_text),
            ]

    _sync_titles()

    def _get_prompt_tokens() -> list[tuple[str, str]]:
        return [
            ("class:qmark", "?"),
            ("class:question", f" {message} "),
            (
                "class:instruction",
                "(Use up/down to pick a row, left/right or +/- to change shard count, Enter to continue, Esc to go back)",
            ),
        ]

    layout = common.create_inquirer_layout(ic, _get_prompt_tokens, **kwargs)
    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _abort(event: Any) -> None:
        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    @bindings.add(Keys.Escape, eager=True)
    def _go_back(event: Any) -> None:
        event.app.exit(result=back_action)

    @bindings.add(Keys.Down, eager=True)
    def _move_down(event: Any) -> None:
        _select_next()
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Up, eager=True)
    def _move_up(event: Any) -> None:
        _select_previous()
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Left, eager=True)
    @bindings.add("-", eager=True)
    @bindings.add("h", eager=True)
    def _decrement(event: Any) -> None:
        _set_current_count(-1)
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Right, eager=True)
    @bindings.add("+", eager=True)
    @bindings.add("l", eager=True)
    def _increment(event: Any) -> None:
        _set_current_count(1)
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.ControlM, eager=True)
    def _submit(event: Any) -> None:
        current = ic.get_pointed_at()
        current_value = str(current.value)
        if current_value == "__done__":
            ic.is_answered = True
            event.app.exit(
                result={
                    step_id: int(row.get("current_count") or 1)
                    for step_id, row in row_lookup.items()
                }
            )
            return
        _adopt_recommendation_or_increment()
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Any)
    def _other(event: Any) -> None:
        """Disallow inserting other text."""

    question = Question(
        Application(
            layout=layout,
            key_bindings=bindings,
            style=merged_style,
            **utils.used_kwargs(kwargs, Application.__init__),
        )
    )
    return question.ask()


def _choose_interactive_codex_prompt_targets(
    *,
    selected_settings: RunSettings,
    prompt_codex_shard_plan_menu: PromptCodexShardPlanMenu,
    back_action: Any,
    selected_step_ids: Sequence[str],
    target_context: Mapping[str, Any] | None = None,
) -> RunSettings | None:
    patched_payload = project_run_config_payload(
        selected_settings.to_run_config_dict(),
        contract=RUN_SETTING_CONTRACT_FULL,
    )
    rows = _build_codex_shard_plan_rows(
        selected_settings=selected_settings,
        selected_step_ids=selected_step_ids,
        target_context=target_context,
    )
    if not rows:
        return RunSettings.from_dict(
            patched_payload,
            warn_context="interactive codex prompt targets",
        )
    selected_counts = prompt_codex_shard_plan_menu(
        message="Codex Exec shard planning for this run:",
        rows=rows,
        summary_lines=_build_codex_shard_plan_summary_lines(
            target_context=target_context,
            rows=rows,
        ),
        back_action=back_action,
    )
    if selected_counts is None or selected_counts is back_action:
        return None
    for step_id, prompt_target_count in dict(selected_counts).items():
        if step_id not in _CODEX_SURFACE_PROMPT_TARGET_FIELDS:
            continue
        field_name, _label = _CODEX_SURFACE_PROMPT_TARGET_FIELDS[step_id]
        patched_payload[field_name] = int(prompt_target_count)
    return RunSettings.from_dict(
        patched_payload,
        warn_context="interactive codex prompt targets",
    )


def choose_interactive_codex_surfaces(
    *,
    selected_settings: RunSettings,
    back_action: Any,
    surface_options: tuple[str, ...],
    prompt_codex_surface_menu: PromptCodexSurfaceMenu | None = None,
    prompt_codex_shard_plan_menu: PromptCodexShardPlanMenu | None = None,
    target_context: Mapping[str, Any] | None = None,
) -> RunSettings | None:
    return _choose_interactive_codex_surfaces(
        selected_settings=selected_settings,
        prompt_codex_surface_menu=(
            prompt_codex_surface_menu or _prompt_codex_surface_menu
        ),
        prompt_codex_shard_plan_menu=prompt_codex_shard_plan_menu,
        back_action=back_action,
        surface_options=surface_options,
        target_context=target_context,
    )


def _codex_exec_style_applies(selected_settings: RunSettings) -> bool:
    return any(
        (
            selected_settings.line_role_pipeline.value == LINE_ROLE_PIPELINE_ROUTE_V2,
            selected_settings.llm_knowledge_pipeline.value != "off",
        )
    )


def _choose_interactive_codex_exec_style(
    *,
    selected_settings: RunSettings,
    menu_select: MenuSelect,
    back_action: Any,
) -> RunSettings | None:
    if not _codex_exec_style_applies(selected_settings):
        return selected_settings
    default_style = normalize_codex_exec_style_value(selected_settings.codex_exec_style.value)
    selected_style = menu_select(
        "Codex Exec style for this run:",
        menu_help=(
            "This choice applies only to block labelling and non-recipe finalize.\n"
            "Recipe correction stays on the current taskfile worker contract.\n"
            "Taskfile workers keep the existing editable `task.json` path.\n"
            "Inline JSON uses immutable inline payloads plus `codex exec resume --last` repair/grouping turns."
        ),
        default=default_style,
        choices=[
            questionary.Choice(
                _CODEX_EXEC_STYLE_LABELS[CODEX_EXEC_STYLE_TASKFILE_V1],
                value=CODEX_EXEC_STYLE_TASKFILE_V1,
            ),
            questionary.Choice(
                _CODEX_EXEC_STYLE_LABELS[CODEX_EXEC_STYLE_INLINE_JSON_V1],
                value=CODEX_EXEC_STYLE_INLINE_JSON_V1,
            ),
        ],
    )
    if selected_style in {None, back_action}:
        return None
    return _patch_interactive_settings(
        selected_settings,
        warn_context="interactive codex exec style selection",
        codex_exec_style=normalize_codex_exec_style_value(selected_style),
    )


def _selected_settings_enable_any_codex(selected_settings: RunSettings) -> bool:
    return any(
        (
            selected_settings.llm_recipe_pipeline.value != "off",
            selected_settings.line_role_pipeline.value == LINE_ROLE_PIPELINE_ROUTE_V2,
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
    model_choice = menu_select(
        "Codex Exec model override:",
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
        "Codex Exec reasoning effort override:",
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


def choose_codex_ai_settings(
    *,
    selected_settings: RunSettings,
    menu_select: MenuSelect,
    back_action: Any,
) -> RunSettings | None:
    return _choose_codex_ai_settings(
        selected_settings=selected_settings,
        menu_select=menu_select,
        back_action=back_action,
    )


def build_interactive_benchmark_preset_settings(
    *,
    preset_id: str,
    global_defaults: RunSettings,
    output_dir: Path,
) -> RunSettings:
    normalized_preset_id = str(preset_id or "").strip().lower()
    if normalized_preset_id != INTERACTIVE_BENCHMARK_PRESET_SALT_FAT_ACID_HEAT_CUTDOWN_FAST:
        raise ValueError(f"Unknown interactive benchmark preset: {preset_id}")

    qualitysuite_winner_settings = load_qualitysuite_winner_run_settings(output_dir)
    selected_settings = (
        qualitysuite_winner_settings
        if qualitysuite_winner_settings is not None
        else _default_top_tier_settings(global_defaults)
    )
    selected_settings = _harmonize_top_tier_pipeline_settings(
        selected_settings,
        profile="codex-exec",
        warn_context="interactive benchmark preset top-tier harmonization",
    )
    return _patch_interactive_settings(
        selected_settings,
        warn_context="interactive benchmark preset overrides",
        llm_recipe_pipeline=RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
        line_role_pipeline=LINE_ROLE_PIPELINE_ROUTE_V2,
        llm_knowledge_pipeline=KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
        atomic_block_splitter=selected_settings.atomic_block_splitter.value,
        recipe_prompt_target_count=5,
        line_role_prompt_target_count=5,
        knowledge_prompt_target_count=5,
        codex_farm_model="gpt-5.3-codex-spark",
        codex_farm_reasoning_effort="low",
    )


def choose_run_settings(
    *,
    global_defaults: RunSettings,
    output_dir: Path,
    menu_select: MenuSelect,
    back_action: Any,
    prompt_confirm: PromptConfirm | None = None,
    prompt_codex_surface_menu: PromptCodexSurfaceMenu | None = None,
    prompt_codex_shard_plan_menu: PromptCodexShardPlanMenu | None = None,
    prompt_text: PromptText | None = None,
    prompt_codex_ai_settings: bool = False,
    prompt_recipe_pipeline_menu: bool = False,
    prompt_benchmark_llm_surface_toggles: bool = False,
    interactive_codex_surface_options: tuple[str, ...] | None = None,
    interactive_codex_target_context: Mapping[str, Any] | None = None,
) -> RunSettings | None:
    """Resolve one interactive top-tier run profile family."""

    codex_surface_menu_options = interactive_codex_surface_options
    if codex_surface_menu_options is None and prompt_benchmark_llm_surface_toggles:
        codex_surface_menu_options = ("line_role", "recipe", "knowledge")

    if prompt_recipe_pipeline_menu:
        selected_recipe_pipeline = _choose_interactive_recipe_pipeline(
            menu_select=menu_select,
            back_action=back_action,
            prompt_confirm=None,
            global_defaults=global_defaults,
            codex_surface_menu_options=codex_surface_menu_options,
        )
    else:
        selected_recipe_pipeline = _choose_interactive_recipe_pipeline(
            menu_select=menu_select,
            back_action=back_action,
            prompt_confirm=prompt_confirm,
            global_defaults=global_defaults,
            codex_surface_menu_options=codex_surface_menu_options,
        )
    if selected_recipe_pipeline is None:
        return None
    selected_profile: TopTierProfileKind = (
        "vanilla" if selected_recipe_pipeline == "off" else "codex-exec"
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
    if codex_surface_menu_options is not None and selected_profile == "codex-exec":
        selected_settings = choose_interactive_codex_surfaces(
            selected_settings=selected_settings,
            prompt_codex_surface_menu=prompt_codex_surface_menu,
            prompt_codex_shard_plan_menu=(
                prompt_codex_shard_plan_menu
                if prompt_codex_shard_plan_menu is not None
                else (_prompt_codex_shard_plan_menu if prompt_text is not None else None)
            ),
            back_action=back_action,
            surface_options=codex_surface_menu_options,
            target_context=interactive_codex_target_context,
        )
        if selected_settings is None:
            return None
        selected_settings = _choose_interactive_codex_exec_style(
            selected_settings=selected_settings,
            menu_select=menu_select,
            back_action=back_action,
        )
        if selected_settings is None:
            return None
    if _selected_settings_enable_any_codex(selected_settings) and prompt_codex_ai_settings:
        selected_settings = choose_codex_ai_settings(
            selected_settings=selected_settings,
            menu_select=menu_select,
            back_action=back_action,
        )
        if selected_settings is None:
            return None
    return _rate_limit_workers(selected_settings)
