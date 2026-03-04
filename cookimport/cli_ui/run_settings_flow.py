from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Literal

from cookimport.config.last_run_store import (
    load_qualitysuite_winner_run_settings,
)
from cookimport.config.run_settings import RunSettings

RunSettingsKind = Literal["import", "benchmark"]
MenuSelect = Callable[..., Any]
PromptConfirm = Callable[..., Any]
PromptText = Callable[..., Any]
_QUALITY_FIRST_WINNER_STACK_PATCH: dict[str, Any] = {
    "epub_extractor": "unstructured",
    "epub_unstructured_html_parser_version": "v1",
    "epub_unstructured_preprocess_mode": "semantic_v1",
    "epub_unstructured_skip_headers_footers": True,
}
_TOP_TIER_DEFAULT_PATCH: dict[str, Any] = {
    "llm_recipe_pipeline": "codex-farm-3pass-v1",
    "line_role_pipeline": "codex-line-role-v1",
    "atomic_block_splitter": "atomic-v1",
}
_WORKER_UTILIZATION_ENV = "COOKIMPORT_WORKER_UTILIZATION"
_WORKER_UTILIZATION_DEFAULT = 1.0


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
    payload.update(_TOP_TIER_DEFAULT_PATCH)
    return RunSettings.from_dict(
        payload,
        warn_context="top-tier default run settings",
    )


def _harmonize_top_tier_pipeline_settings(
    settings: RunSettings,
    *,
    warn_context: str,
) -> RunSettings:
    payload = settings.to_run_config_dict()
    payload.update(_TOP_TIER_DEFAULT_PATCH)
    return RunSettings.from_dict(payload, warn_context=warn_context)


def choose_run_settings(
    *,
    kind: RunSettingsKind,
    global_defaults: RunSettings,
    output_dir: Path,
    menu_select: MenuSelect,
    back_action: Any,
    show_summary: bool = True,
    prompt_confirm: PromptConfirm | None = None,
    prompt_text: PromptText | None = None,
) -> RunSettings | None:
    """Resolve one interactive top-tier run profile without per-run menu prompts."""

    _ = kind
    _ = menu_select
    _ = back_action
    _ = show_summary
    _ = prompt_confirm
    _ = prompt_text

    qualitysuite_winner_settings = load_qualitysuite_winner_run_settings(output_dir)
    selected_settings = (
        qualitysuite_winner_settings
        if qualitysuite_winner_settings is not None
        else _default_top_tier_settings(global_defaults)
    )
    selected_settings = _harmonize_top_tier_pipeline_settings(
        selected_settings,
        warn_context="interactive top-tier pipeline harmonization",
    )
    return _rate_limit_workers(selected_settings)
