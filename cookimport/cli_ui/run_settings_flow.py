from __future__ import annotations

import os
import textwrap
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
    normalize_llm_recipe_pipeline_value,
)
from cookimport.llm.codex_farm_runner import list_codex_farm_models
from cookimport.llm.shard_survivability import default_stage_survivability_budget

MenuSelect = Callable[..., Any]
PromptConfirm = Callable[..., Any]
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
_CODEX_STEP_MODE_OFF = "off"
_CODEX_STEP_MODE_DISPLAY_LABELS: dict[str, str] = {
    _CODEX_STEP_MODE_OFF: "Off",
    CODEX_EXEC_STYLE_INLINE_JSON_V1: "JSON",
    CODEX_EXEC_STYLE_TASKFILE_V1: "Taskfile",
}
_CODEX_STEP_COUNT_COLUMN = "__count__"
_CODEX_STEP_MODE_COLUMN_ORDER: tuple[str, ...] = (
    _CODEX_STEP_MODE_OFF,
    CODEX_EXEC_STYLE_INLINE_JSON_V1,
    CODEX_EXEC_STYLE_TASKFILE_V1,
)
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


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _planning_warning_badge(warnings: Sequence[str] | None) -> str | None:
    warning_list = [str(item).strip() for item in warnings or [] if str(item).strip()]
    if not warning_list:
        return None
    count = len(warning_list)
    return f"warn {count} below"


def _is_budget_native_planning_warning(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return (
        "packet-budget planning would have split" in normalized
        or "requested final shard count" in normalized
        or "rendered preview packet count fallback" in normalized
        or "budget-native packetization" in normalized
    )


def _current_row_warning_messages(row: Mapping[str, Any]) -> list[str]:
    current_count = max(1, int(row.get("current_count") or 1))
    minimum_safe = _coerce_int(row.get("minimum_safe_shard_count"))
    budget_native = _coerce_int(row.get("budget_native_shard_count"))
    binding_limit = str(row.get("binding_limit") or "").strip()
    raw_warnings = [
        str(item).strip()
        for item in row.get("planning_warnings") or []
        if str(item).strip()
    ]
    messages: list[str] = []
    if minimum_safe is not None and current_count < int(minimum_safe):
        messages.append(
            f"Current shard count {current_count} is below the advisory survivability minimum "
            f"of {int(minimum_safe)} for {_binding_limit_label(binding_limit)}."
        )
    if budget_native is not None and int(budget_native) > 0 and current_count < int(budget_native):
        messages.append(
            f"Current shard count {current_count} is below the budget-native plan of "
            f"{int(budget_native)} shards. The rendered preview packetizer naturally split "
            "this work more finely at that count."
        )
    for warning in raw_warnings:
        if _is_budget_native_planning_warning(warning):
            continue
        messages.append(warning)
    return messages


def _build_codex_shard_plan_warning_lines(
    rows: Sequence[Mapping[str, Any]],
    *,
    wrap_width: int = 88,
) -> list[str]:
    lines: list[str] = []
    warning_rows: list[tuple[str, list[str]]] = []
    for row in rows:
        label = str(row.get("label") or row.get("step_id") or "Step").strip() or "Step"
        warnings = _current_row_warning_messages(row)
        if warnings:
            warning_rows.append((label, warnings))
    if not warning_rows:
        return lines
    lines.append("Planner warnings:")
    for label, warnings in warning_rows:
        for warning in warnings:
            initial_indent = f"{label}: "
            wrapped = textwrap.wrap(
                warning,
                width=max(24, wrap_width),
                initial_indent=initial_indent,
                subsequent_indent=" " * len(initial_indent),
                break_long_words=False,
                break_on_hyphens=False,
            )
            if wrapped:
                lines.extend(wrapped)
            else:
                lines.append(initial_indent.rstrip())
    return lines


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


def _available_codex_step_modes(step_id: str) -> tuple[str, ...]:
    if step_id == "recipe":
        return (
            _CODEX_STEP_MODE_OFF,
            CODEX_EXEC_STYLE_INLINE_JSON_V1,
            CODEX_EXEC_STYLE_TASKFILE_V1,
        )
    if step_id in {"line_role", "knowledge"}:
        return (
            _CODEX_STEP_MODE_OFF,
            CODEX_EXEC_STYLE_INLINE_JSON_V1,
            CODEX_EXEC_STYLE_TASKFILE_V1,
        )
    return (_CODEX_STEP_MODE_OFF,)


def _current_codex_step_mode(
    *,
    selected_settings: RunSettings,
    step_id: str,
) -> str:
    if step_id == "recipe":
        if selected_settings.llm_recipe_pipeline.value == "off":
            return _CODEX_STEP_MODE_OFF
        return selected_settings.resolved_recipe_codex_exec_style()
    if step_id == "line_role":
        if selected_settings.line_role_pipeline.value != LINE_ROLE_PIPELINE_ROUTE_V2:
            return _CODEX_STEP_MODE_OFF
        return selected_settings.resolved_line_role_codex_exec_style()
    if step_id == "knowledge":
        if selected_settings.llm_knowledge_pipeline.value == "off":
            return _CODEX_STEP_MODE_OFF
        return selected_settings.resolved_knowledge_codex_exec_style()
    return _CODEX_STEP_MODE_OFF


def _resolve_codex_prompt_target_context(
    *,
    target_context: Mapping[str, Any] | None,
    selected_settings: RunSettings,
    step_ids: Sequence[str],
) -> Mapping[str, Any] | None:
    if not isinstance(target_context, Mapping):
        return target_context
    recommendation_builder = target_context.get("recommendations_builder")
    if not callable(recommendation_builder):
        return target_context
    recommendations_by_step: Mapping[str, Any] | None
    try:
        recommendations_by_step = recommendation_builder(
            selected_settings,
            tuple(step_ids),
        )
    except Exception:  # noqa: BLE001
        return target_context
    if not isinstance(recommendations_by_step, Mapping):
        return target_context
    resolved_target_context = dict(target_context)
    resolved_target_context["recommendations_by_step"] = dict(
        recommendations_by_step
    )
    return resolved_target_context


def _format_shard_budget_value(token_count: int) -> str:
    if token_count >= 1_000_000:
        return f"{token_count / 1_000_000:.1f}m"
    if token_count >= 1_000:
        return f"{token_count // 1_000}k"
    return str(token_count)


def _binding_limit_label(binding_limit: str | None) -> str:
    normalized = str(binding_limit or "").strip().lower()
    return {
        "input": "prompt",
        "output": "output",
        "session_peak": "session",
        "owned_units": "work",
    }.get(normalized, normalized or "limit")


def _estimate_total_from_average(
    average_value: Any,
    *,
    shard_count: Any,
) -> int | None:
    if average_value is None:
        return None
    shard_count_int = max(1, int(shard_count or 1))
    return max(0, int(round(float(average_value) * float(shard_count_int))))


def _estimate_per_shard_from_total(
    total_value: Any,
    *,
    shard_count: Any,
) -> int | None:
    if total_value is None:
        return None
    shard_count_int = max(1, int(shard_count or 1))
    return max(0, int(round(float(total_value) / float(shard_count_int))))


def _render_shard_plan_kpi_summary(
    recommendation_payload: Mapping[str, Any],
    *,
    shard_count: int | None = None,
) -> str:
    baseline_shard_count = max(
        1,
        int(
            recommendation_payload.get("current_shard_count")
            or recommendation_payload.get("current_shard_count_baseline")
            or shard_count
            or 1
        ),
    )
    effective_shard_count = max(1, int(shard_count or baseline_shard_count))
    bits: list[str] = []
    estimated_input_tokens_total = recommendation_payload.get(
        "estimated_input_tokens_total"
    )
    if estimated_input_tokens_total is None:
        estimated_input_tokens_total = _estimate_total_from_average(
            recommendation_payload.get("avg_input_tokens_per_shard"),
            shard_count=baseline_shard_count,
        )
    prompt_tokens_per_shard = _estimate_per_shard_from_total(
        estimated_input_tokens_total,
        shard_count=effective_shard_count,
    )
    if prompt_tokens_per_shard is not None:
        bits.append(
            f"~{_format_shard_budget_value(int(prompt_tokens_per_shard))} prompt"
        )
    estimated_peak_session_tokens_total = recommendation_payload.get(
        "estimated_peak_session_tokens_total"
    )
    if estimated_peak_session_tokens_total is None:
        estimated_peak_session_tokens_total = _estimate_total_from_average(
            recommendation_payload.get("avg_peak_session_tokens_per_shard"),
            shard_count=baseline_shard_count,
        )
    peak_session_tokens_per_shard = _estimate_per_shard_from_total(
        estimated_peak_session_tokens_total,
        shard_count=effective_shard_count,
    )
    if peak_session_tokens_per_shard is not None:
        bits.append(
            f"~{_format_shard_budget_value(int(peak_session_tokens_per_shard))} session"
        )
    owned_unit_count = recommendation_payload.get("owned_unit_count")
    if owned_unit_count is None:
        owned_unit_count = _estimate_total_from_average(
            recommendation_payload.get("owned_units_per_shard_avg"),
            shard_count=baseline_shard_count,
        )
    owned_units_per_shard_avg = _estimate_per_shard_from_total(
        owned_unit_count,
        shard_count=effective_shard_count,
    )
    owned_unit_label = str(recommendation_payload.get("owned_unit_label") or "").strip()
    if owned_units_per_shard_avg is not None and owned_unit_label:
        rounded_units = int(round(float(owned_units_per_shard_avg)))
        bits.append(f"~{rounded_units} {owned_unit_label}/sh")
    return " | ".join(bits)


def _build_codex_shard_plan_rows(
    *,
    selected_settings: RunSettings,
    step_ids: Sequence[str],
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
    for step_id in step_ids:
        if step_id not in _CODEX_SURFACE_PROMPT_TARGET_FIELDS:
            continue
        field_name, label = _CODEX_SURFACE_PROMPT_TARGET_FIELDS[step_id]
        current_value = getattr(selected_settings, field_name, None)
        recommendation = recommendation_lookup.get(step_id)
        recommendation_payload = (
            dict(recommendation) if isinstance(recommendation, Mapping) else {}
        )
        minimum_safe_shard_count = recommendation_payload.get(
            "survivability_recommended_shard_count"
        )
        if minimum_safe_shard_count is None:
            minimum_safe_shard_count = recommendation_payload.get(
                "minimum_safe_shard_count"
            )
        binding_limit = str(recommendation_payload.get("binding_limit") or "").strip() or None
        stage_budget = default_stage_survivability_budget(
            _CODEX_SURFACE_STAGE_KEYS.get(step_id, step_id)
        )
        kpi_summary = _render_shard_plan_kpi_summary(recommendation_payload)
        rows.append(
            {
                "step_id": step_id,
                "label": label,
                "available_modes": _available_codex_step_modes(step_id),
                "current_mode": _current_codex_step_mode(
                    selected_settings=selected_settings,
                    step_id=step_id,
                ),
                "current_count": max(
                    1,
                    int(current_value) if current_value is not None else 5,
                ),
                "minimum_safe_shard_count": (
                    int(minimum_safe_shard_count)
                    if minimum_safe_shard_count is not None
                    else None
                ),
                "survivability_recommended_shard_count": (
                    int(minimum_safe_shard_count)
                    if minimum_safe_shard_count is not None
                    else None
                ),
                "binding_limit": binding_limit,
                "requested_shard_count": recommendation_payload.get("requested_shard_count"),
                "budget_native_shard_count": recommendation_payload.get("budget_native_shard_count"),
                "launch_shard_count": recommendation_payload.get("launch_shard_count"),
                "planning_warnings": list(recommendation_payload.get("planning_warnings") or []),
                "current_shard_count_baseline": recommendation_payload.get(
                    "current_shard_count"
                ),
                "estimated_input_tokens_total": recommendation_payload.get(
                    "estimated_input_tokens_total"
                ),
                "estimated_peak_session_tokens_total": recommendation_payload.get(
                    "estimated_peak_session_tokens_total"
                ),
                "owned_unit_count": recommendation_payload.get("owned_unit_count"),
                "avg_input_tokens_per_shard": recommendation_payload.get(
                    "avg_input_tokens_per_shard"
                ),
                "avg_peak_session_tokens_per_shard": recommendation_payload.get(
                    "avg_peak_session_tokens_per_shard"
                ),
                "worst_peak_session_tokens": recommendation_payload.get(
                    "worst_peak_session_tokens"
                ),
                "owned_units_per_shard_avg": recommendation_payload.get(
                    "owned_units_per_shard_avg"
                ),
                "owned_unit_label": recommendation_payload.get("owned_unit_label"),
                "kpi_summary": kpi_summary,
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
    recommendations_by_step = (
        target_context.get("recommendations_by_step")
        if isinstance(target_context, Mapping)
        else None
    )
    book_summary = (
        recommendations_by_step.get("__book_summary__")
        if isinstance(recommendations_by_step, Mapping)
        and isinstance(recommendations_by_step.get("__book_summary__"), Mapping)
        else None
    )
    if isinstance(book_summary, Mapping):
        block_count = book_summary.get("block_count")
        line_count = book_summary.get("line_count")
        recipe_guess_count = book_summary.get("recipe_guess_count")
        outside_recipe_block_count = book_summary.get("outside_recipe_block_count")
        knowledge_packet_count = book_summary.get("knowledge_packet_count")
        lines.append(
            "Prepared: "
            + ", ".join(
                bit
                for bit in (
                    (
                        f"{int(block_count):,} blocks"
                        if block_count is not None
                        else ""
                    ),
                    (
                        f"{int(line_count):,} lines"
                        if line_count is not None
                        else ""
                    ),
                    (
                        f"{int(recipe_guess_count):,} recipe guesses"
                        if recipe_guess_count is not None
                        else ""
                    ),
                )
                if bit
            )
        )
        extra_bits: list[str] = []
        if outside_recipe_block_count is not None:
            extra_bits.append(f"{int(outside_recipe_block_count):,} outside-recipe blocks")
        if knowledge_packet_count is not None:
            extra_bits.append(f"{int(knowledge_packet_count):,} knowledge packets")
        if extra_bits:
            lines.append("Leftover for knowledge: " + ", ".join(extra_bits))
    lines.append("Each row shows: main limit | avg prompt size | avg session size | avg work per shard")
    lines.append(
        "Shard count is your launch request. min is advisory survivability; row notes stay compact and full planner warnings appear below the table."
    )
    has_recommendations = any(
        row.get("minimum_safe_shard_count") is not None for row in rows
    )
    has_unknown_rows = any(
        row.get("minimum_safe_shard_count") is None for row in rows
    )
    if has_unknown_rows:
        lines.append(
            "Rows with min -- are not verified yet. Treat those shard counts as untrusted."
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
) -> dict[str, dict[str, Any]] | Any:
    label_width = max(
        (len(str(row.get("label") or "")) for row in rows),
        default=0,
    )
    count_inner_width = max(3, len(str(max_value)))
    count_cell_width = len(f">[{max_value:>{count_inner_width}}]<")
    mode_cell_width = max(
        len(f">[{label}]<") for label in _CODEX_STEP_MODE_DISPLAY_LABELS.values()
    )

    def _build_header_line() -> str:
        return (
            f"{'':<{label_width}}  "
            f"{'shards':<{count_cell_width}}  "
            f"{'off':<{mode_cell_width}}  "
            f"{'json':<{mode_cell_width}}  "
            f"{'taskfile':<{mode_cell_width}}  "
            "min  notes"
        ).rstrip()

    header_line = _build_header_line()
    summary_choice_rows: list[questionary.Separator] = [
        questionary.Separator(summary_line)
        for summary_line in summary_lines
    ]
    row_choices: list[questionary.Choice] = [
        questionary.Choice(
            "",
            value=str(row.get("step_id") or ""),
            shortcut_key=False,
        )
        for row in rows
    ]
    continue_choice = questionary.Choice("Continue", value="__done__")
    choices: list[questionary.Choice | questionary.Separator] = list(row_choices) + [
        continue_choice
    ]
    row_lookup = {
        str(row.get("step_id") or ""): row
        for row in rows
        if str(row.get("step_id") or "").strip()
    }
    merged_style = merge_styles_default([])
    initial_choice = row_choices[0] if row_choices else continue_choice

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

    def _rebuild_choice_list() -> None:
        current_value: str | None = None
        if ic.choices:
            current_choice = ic.get_pointed_at()
            if not isinstance(current_choice, questionary.Separator):
                current_value = str(current_choice.value)
        warning_lines = _build_codex_shard_plan_warning_lines(rows)
        rebuilt: list[questionary.Choice | questionary.Separator] = []
        rebuilt.extend(summary_choice_rows)
        if summary_choice_rows:
            rebuilt.append(questionary.Separator())
        rebuilt.append(questionary.Separator(header_line))
        rebuilt.append(questionary.Separator("-" * max(24, len(header_line))))
        rebuilt.extend(row_choices)
        rebuilt.append(questionary.Separator())
        for warning_line in warning_lines:
            rebuilt.append(questionary.Separator(warning_line))
        if warning_lines:
            rebuilt.append(questionary.Separator())
        rebuilt.append(continue_choice)
        ic.choices = rebuilt
        desired_value = current_value or str(initial_choice.value)
        fallback_index = next(
            (
                index
                for index, choice in enumerate(rebuilt)
                if not isinstance(choice, questionary.Separator)
            ),
            0,
        )
        ic.pointed_at = next(
            (
                index
                for index, choice in enumerate(rebuilt)
                if not isinstance(choice, questionary.Separator)
                and str(choice.value) == desired_value
            ),
            fallback_index,
        )

    def _select_next() -> None:
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    def _select_previous() -> None:
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    numeric_entry: dict[str, Any] = {
        "step_id": None,
        "buffer": "",
    }
    current_column: dict[str, str] = {"value": _CODEX_STEP_COUNT_COLUMN}

    def _clear_numeric_entry() -> None:
        numeric_entry["step_id"] = None
        numeric_entry["buffer"] = ""

    def _row_navigable_columns(step_id: str) -> tuple[str, ...]:
        row = row_lookup.get(step_id)
        if row is None:
            return (_CODEX_STEP_COUNT_COLUMN,)
        available_modes = {
            str(mode)
            for mode in row.get("available_modes") or ()
            if str(mode).strip()
        }
        columns = [_CODEX_STEP_COUNT_COLUMN]
        columns.extend(
            mode for mode in _CODEX_STEP_MODE_COLUMN_ORDER if mode in available_modes
        )
        return tuple(columns)

    def _normalize_current_column() -> None:
        current = ic.get_pointed_at()
        step_id = str(current.value)
        if step_id == "__done__":
            return
        navigable_columns = _row_navigable_columns(step_id)
        if current_column["value"] not in navigable_columns:
            current_column["value"] = _CODEX_STEP_COUNT_COLUMN

    def _select_current_mode(mode: str) -> None:
        current = ic.get_pointed_at()
        step_id = str(current.value)
        row = row_lookup.get(step_id)
        if row is None:
            return
        available_modes = {
            str(candidate)
            for candidate in row.get("available_modes") or ()
            if str(candidate).strip()
        }
        if mode not in available_modes:
            return
        row["current_mode"] = mode

    def _move_current_column(delta: int) -> None:
        current = ic.get_pointed_at()
        step_id = str(current.value)
        if step_id == "__done__":
            return
        columns = list(_row_navigable_columns(step_id))
        _normalize_current_column()
        active_column = current_column["value"]
        if active_column == _CODEX_STEP_COUNT_COLUMN and delta > 0:
            row = row_lookup.get(step_id) or {}
            current_mode = str(row.get("current_mode") or "").strip()
            if current_mode in columns:
                current_column["value"] = current_mode
                _select_current_mode(current_mode)
                return
            if len(columns) > 1:
                current_column["value"] = columns[1]
                _select_current_mode(columns[1])
            return
        try:
            column_index = columns.index(active_column)
        except ValueError:
            column_index = 0
        target_index = max(0, min(len(columns) - 1, column_index + delta))
        current_column["value"] = columns[target_index]
        if current_column["value"] != _CODEX_STEP_COUNT_COLUMN:
            _select_current_mode(current_column["value"])

    def _set_current_count(delta: int) -> None:
        current = ic.get_pointed_at()
        step_id = str(current.value)
        row = row_lookup.get(step_id)
        if row is None:
            return
        current_count = int(row.get("current_count") or 1)
        row["current_count"] = max(1, min(max_value, current_count + delta))

    def _set_current_count_from_digits(digit: str) -> None:
        current = ic.get_pointed_at()
        step_id = str(current.value)
        row = row_lookup.get(step_id)
        if row is None:
            return
        if numeric_entry["step_id"] != step_id:
            numeric_entry["step_id"] = step_id
            numeric_entry["buffer"] = ""
        candidate = f"{numeric_entry['buffer']}{digit}"
        normalized_candidate = candidate.lstrip("0")
        if not normalized_candidate:
            numeric_entry["buffer"] = candidate
            return
        parsed = int(normalized_candidate)
        if parsed < 1 or parsed > max_value:
            return
        numeric_entry["buffer"] = candidate
        row["current_count"] = parsed

    def _append_fixed_cell(
        tokens: list[tuple[str, str]],
        *,
        style_class: str,
        text: str,
        width: int,
        gap: int = 2,
    ) -> None:
        tokens.append((style_class, text))
        padding = max(0, width - len(text))
        if padding:
            tokens.append(("class:text", " " * padding))
        if gap:
            tokens.append(("class:text", " " * gap))

    def _sync_titles() -> None:
        _rebuild_choice_list()
        for index, choice in enumerate(ic.choices):
            if isinstance(choice, questionary.Separator):
                continue
            if choice.value == "__done__":
                choice.title = (
                    [("class:highlighted", "Continue")]
                    if index == ic.pointed_at
                    else "Continue"
                )
                continue
            step_id = str(choice.value)
            row = row_lookup.get(step_id) or {}
            label = str(row.get("label") or step_id)
            is_current = index == ic.pointed_at
            if is_current:
                _normalize_current_column()
            current_mode = str(row.get("current_mode") or _CODEX_STEP_MODE_OFF)
            available_modes = tuple(str(mode) for mode in row.get("available_modes") or ())
            count_value = int(row.get("current_count") or 1)
            minimum_safe = row.get("minimum_safe_shard_count")
            budget_native = row.get("budget_native_shard_count")
            launch_shards = row.get("launch_shard_count")
            binding_limit = str(row.get("binding_limit") or "").strip()
            warning_badge = _planning_warning_badge(
                _current_row_warning_messages(row)
            )
            kpi_summary = _render_shard_plan_kpi_summary(
                row,
                shard_count=count_value,
            )
            budget_summary = str(row.get("budget_summary") or "").strip()
            title_tokens: list[tuple[str, str]] = []
            _append_fixed_cell(
                title_tokens,
                style_class="class:highlighted" if is_current else "class:text",
                text=label,
                width=label_width,
            )
            if current_mode == _CODEX_STEP_MODE_OFF:
                recommended_text = (
                    f"min {int(minimum_safe)}" if minimum_safe is not None else "min --"
                )
                note_bits = ["disabled"]
                if budget_native is not None and int(budget_native) > 0:
                    note_bits.append(f"native {int(budget_native)}")
                if warning_badge:
                    note_bits.append(warning_badge)
                if kpi_summary:
                    note_bits.append(kpi_summary)
                elif budget_summary:
                    note_bits.append(budget_summary)
                note_text = " | ".join(note_bits)
                note_class = "class:text"
            elif minimum_safe is not None:
                recommended_text = f"min {int(minimum_safe)}"
                if count_value < int(minimum_safe):
                    note_text = f"too low for {_binding_limit_label(binding_limit)}"
                    note_class = "class:answer"
                else:
                    note_text = f"ok on {_binding_limit_label(binding_limit)}"
                    note_class = "class:selected"
                if budget_native is not None and int(budget_native) > 0:
                    note_text = f"{note_text} | native {int(budget_native)}"
                if (
                    launch_shards is not None
                    and int(launch_shards) > 0
                    and int(launch_shards) != int(count_value)
                ):
                    note_text = f"{note_text} | launch {int(launch_shards)}"
                if warning_badge:
                    note_text = f"{note_text} | {warning_badge}"
                if kpi_summary:
                    note_text = f"{note_text} | {kpi_summary}"
            else:
                recommended_text = "min --"
                note_text = (
                    f"no exact estimate | {kpi_summary}"
                    if kpi_summary and budget_summary
                    else (kpi_summary or budget_summary or "no exact estimate")
                )
                if budget_native is not None and int(budget_native) > 0:
                    note_text = f"{note_text} | native {int(budget_native)}"
                if warning_badge:
                    note_text = f"{note_text} | {warning_badge}"
                note_class = "class:text"
            count_text = f"[{count_value:>{count_inner_width}}]"
            count_class = "class:text"
            if is_current and current_column["value"] == _CODEX_STEP_COUNT_COLUMN:
                count_class = "class:highlighted"
                count_text = f">{count_text}<"
            _append_fixed_cell(
                title_tokens,
                style_class=count_class,
                text=count_text,
                width=count_cell_width,
            )
            for mode in _CODEX_STEP_MODE_COLUMN_ORDER:
                mode_label = _CODEX_STEP_MODE_DISPLAY_LABELS[mode]
                if mode not in available_modes:
                    _append_fixed_cell(
                        title_tokens,
                        style_class="class:text",
                        text="",
                        width=mode_cell_width,
                    )
                    continue
                mode_text = f"[{mode_label}]"
                mode_class = "class:text"
                if is_current and current_column["value"] == mode:
                    mode_class = "class:highlighted"
                    mode_text = f">{mode_text}<"
                elif current_mode == mode:
                    mode_class = "class:selected"
                _append_fixed_cell(
                    title_tokens,
                    style_class=mode_class,
                    text=mode_text,
                    width=mode_cell_width,
                )
            title_tokens.append(("class:text", f"{recommended_text:<7}  "))
            title_tokens.append((note_class, note_text))
            choice.title = title_tokens

    _sync_titles()

    def _get_prompt_tokens() -> list[tuple[str, str]]:
        return [
            ("class:qmark", "?"),
            ("class:question", f" {message} "),
            (
                "class:instruction",
                "(Use up/down to pick a row, left/right to move between shard count and modes, type digits or use +/- to change shard count, Enter on Continue to accept, Esc to go back)",
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
        _clear_numeric_entry()
        _select_next()
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Up, eager=True)
    def _move_up(event: Any) -> None:
        _clear_numeric_entry()
        _select_previous()
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Left, eager=True)
    @bindings.add("h", eager=True)
    def _previous_mode(event: Any) -> None:
        _clear_numeric_entry()
        _move_current_column(-1)
        _sync_titles()
        event.app.invalidate()

    @bindings.add(Keys.Right, eager=True)
    @bindings.add("l", eager=True)
    def _next_mode(event: Any) -> None:
        _clear_numeric_entry()
        _move_current_column(1)
        _sync_titles()
        event.app.invalidate()

    @bindings.add("-", eager=True)
    def _decrement(event: Any) -> None:
        _clear_numeric_entry()
        _set_current_count(-1)
        _sync_titles()
        event.app.invalidate()

    @bindings.add("+", eager=True)
    def _increment(event: Any) -> None:
        _clear_numeric_entry()
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
                    step_id: {
                        "mode": str(row.get("current_mode") or _CODEX_STEP_MODE_OFF),
                        "count": int(row.get("current_count") or 1),
                    }
                    for step_id, row in row_lookup.items()
                }
            )
            return
        if numeric_entry["step_id"] == current_value and numeric_entry["buffer"]:
            _clear_numeric_entry()
            _sync_titles()
            event.app.invalidate()
            return
        _clear_numeric_entry()
        _sync_titles()
        event.app.invalidate()

    def _register_digit_binding(digit: str) -> None:
        @bindings.add(digit, eager=True)
        def _digit_entry(event: Any) -> None:
            _set_current_count_from_digits(digit)
            _sync_titles()
            event.app.invalidate()

    for digit in "0123456789":
        _register_digit_binding(digit)

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
    prompt_codex_shard_plan_menu: PromptCodexShardPlanMenu,
    back_action: Any,
    surface_options: tuple[str, ...],
    target_context: Mapping[str, Any] | None = None,
) -> RunSettings | None:
    step_ids = tuple(
        step_id
        for step_id in surface_options
        if step_id in _CODEX_SURFACE_PROMPT_TARGET_FIELDS
    )
    if not step_ids:
        return selected_settings
    target_context = _resolve_codex_prompt_target_context(
        target_context=target_context,
        selected_settings=selected_settings,
        step_ids=step_ids,
    )
    rows = _build_codex_shard_plan_rows(
        selected_settings=selected_settings,
        step_ids=step_ids,
        target_context=target_context,
    )
    if not rows:
        return selected_settings
    selected_plan = prompt_codex_shard_plan_menu(
        message="Codex Exec step planning for this run:",
        rows=rows,
        summary_lines=_build_codex_shard_plan_summary_lines(
            target_context=target_context,
            rows=rows,
        ),
        back_action=back_action,
    )
    if selected_plan is None or selected_plan is back_action:
        return None
    patched_payload = project_run_config_payload(
        selected_settings.to_run_config_dict(),
        contract=RUN_SETTING_CONTRACT_FULL,
    )
    resolved_recipe_pipeline = (
        _normalize_interactive_recipe_pipeline(selected_settings.llm_recipe_pipeline.value)
        or RECIPE_CODEX_FARM_EXECUTION_PIPELINES[0]
    )
    if "recipe" not in step_ids:
        patched_payload["llm_recipe_pipeline"] = "off"
        patched_payload["recipe_codex_exec_style"] = CODEX_EXEC_STYLE_INLINE_JSON_V1
    if "line_role" not in step_ids:
        patched_payload["line_role_pipeline"] = "off"
        patched_payload["atomic_block_splitter"] = "off"
        patched_payload["line_role_codex_exec_style"] = CODEX_EXEC_STYLE_INLINE_JSON_V1
    if "knowledge" not in step_ids:
        patched_payload["llm_knowledge_pipeline"] = "off"
        patched_payload["knowledge_codex_exec_style"] = CODEX_EXEC_STYLE_INLINE_JSON_V1
    for step_id, row_plan in dict(selected_plan).items():
        mode = str((row_plan or {}).get("mode") or _CODEX_STEP_MODE_OFF)
        prompt_target_count = int((row_plan or {}).get("count") or 1)
        if step_id not in _CODEX_SURFACE_PROMPT_TARGET_FIELDS:
            continue
        field_name, _label = _CODEX_SURFACE_PROMPT_TARGET_FIELDS[step_id]
        patched_payload[field_name] = int(prompt_target_count)
        if step_id == "recipe":
            patched_payload["llm_recipe_pipeline"] = (
                resolved_recipe_pipeline
                if mode != _CODEX_STEP_MODE_OFF
                else "off"
            )
            patched_payload["recipe_codex_exec_style"] = (
                mode
                if mode != _CODEX_STEP_MODE_OFF
                else CODEX_EXEC_STYLE_INLINE_JSON_V1
            )
            continue
        if step_id == "line_role":
            patched_payload["line_role_pipeline"] = (
                LINE_ROLE_PIPELINE_ROUTE_V2
                if mode != _CODEX_STEP_MODE_OFF
                else "off"
            )
            patched_payload["line_role_codex_exec_style"] = (
                mode
                if mode != _CODEX_STEP_MODE_OFF
                else CODEX_EXEC_STYLE_INLINE_JSON_V1
            )
            patched_payload["atomic_block_splitter"] = (
                selected_settings.atomic_block_splitter.value
                if mode != _CODEX_STEP_MODE_OFF
                else "off"
            )
            continue
        if step_id == "knowledge":
            patched_payload["llm_knowledge_pipeline"] = (
                KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2
                if mode != _CODEX_STEP_MODE_OFF
                else "off"
            )
            patched_payload["knowledge_codex_exec_style"] = (
                mode
                if mode != _CODEX_STEP_MODE_OFF
                else CODEX_EXEC_STYLE_INLINE_JSON_V1
            )
    return RunSettings.from_dict(
        patched_payload,
        warn_context="interactive codex step planning",
    )


def choose_interactive_codex_surfaces(
    *,
    selected_settings: RunSettings,
    back_action: Any,
    surface_options: tuple[str, ...],
    prompt_codex_shard_plan_menu: PromptCodexShardPlanMenu | None = None,
    target_context: Mapping[str, Any] | None = None,
) -> RunSettings | None:
    return _choose_interactive_codex_surfaces(
        selected_settings=selected_settings,
        prompt_codex_shard_plan_menu=(
            prompt_codex_shard_plan_menu or _prompt_codex_shard_plan_menu
        ),
        back_action=back_action,
        surface_options=tuple(surface_options),
        target_context=target_context,
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
        recipe_codex_exec_style=CODEX_EXEC_STYLE_INLINE_JSON_V1,
        line_role_codex_exec_style=CODEX_EXEC_STYLE_INLINE_JSON_V1,
        knowledge_codex_exec_style=CODEX_EXEC_STYLE_INLINE_JSON_V1,
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
            prompt_codex_shard_plan_menu=(
                prompt_codex_shard_plan_menu
                if prompt_codex_shard_plan_menu is not None
                else _prompt_codex_shard_plan_menu
            ),
            back_action=back_action,
            surface_options=codex_surface_menu_options,
            target_context=interactive_codex_target_context,
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
