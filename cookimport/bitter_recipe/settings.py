from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cookimport.bitter_recipe.paths import (
    BITTER_RECIPE_ROOT,
    BITTER_RECIPE_SETTINGS_PATH,
)
from cookimport.paths import INPUT_ROOT


@dataclass
class BitterRecipeSettings:
    input_root: str = str(INPUT_ROOT)
    bitter_recipe_root: str = str(BITTER_RECIPE_ROOT)
    label_studio_url: str = ""
    label_studio_api_key: str = ""
    segment_blocks: int = 40
    segment_overlap: int = 5
    segment_focus_blocks: int = 30
    target_task_count: int | None = None
    upload_batch_size: int = 200
    project_suffix: str = " source_rows_gold"
    default_prelabel: bool = False
    prelabel_allow_partial: bool = False
    codex_model: str = ""
    codex_reasoning_effort: str = ""

    def input_root_path(self) -> Path:
        return Path(self.input_root).expanduser()

    def bitter_recipe_root_path(self) -> Path:
        return Path(self.bitter_recipe_root).expanduser()


def settings_path(path: Path | str | None = None) -> Path:
    return Path(path).expanduser() if path is not None else BITTER_RECIPE_SETTINGS_PATH


def _coerce_int(value: Any, *, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _normalize_payload(payload: dict[str, Any]) -> BitterRecipeSettings:
    defaults = BitterRecipeSettings()
    settings = BitterRecipeSettings(
        input_root=str(payload.get("input_root") or defaults.input_root),
        bitter_recipe_root=str(
            payload.get("bitter_recipe_root") or defaults.bitter_recipe_root
        ),
        label_studio_url=str(payload.get("label_studio_url") or ""),
        label_studio_api_key=str(payload.get("label_studio_api_key") or ""),
        segment_blocks=_coerce_int(
            payload.get("segment_blocks"),
            default=defaults.segment_blocks,
            minimum=1,
        ),
        segment_overlap=_coerce_int(
            payload.get("segment_overlap"),
            default=defaults.segment_overlap,
            minimum=0,
        ),
        segment_focus_blocks=_coerce_int(
            payload.get("segment_focus_blocks"),
            default=defaults.segment_focus_blocks,
            minimum=1,
        ),
        target_task_count=(
            None
            if payload.get("target_task_count") in {None, ""}
            else _coerce_int(
                payload.get("target_task_count"),
                default=defaults.target_task_count or defaults.segment_blocks,
                minimum=1,
            )
        ),
        upload_batch_size=_coerce_int(
            payload.get("upload_batch_size"),
            default=defaults.upload_batch_size,
            minimum=1,
        ),
        project_suffix=str(payload.get("project_suffix") or defaults.project_suffix),
        default_prelabel=bool(payload.get("default_prelabel", defaults.default_prelabel)),
        prelabel_allow_partial=bool(
            payload.get("prelabel_allow_partial", defaults.prelabel_allow_partial)
        ),
        codex_model=str(payload.get("codex_model") or ""),
        codex_reasoning_effort=str(payload.get("codex_reasoning_effort") or ""),
    )
    if settings.segment_focus_blocks > settings.segment_blocks:
        settings.segment_focus_blocks = settings.segment_blocks
    return settings


def load_settings(path: Path | str | None = None) -> BitterRecipeSettings:
    resolved = settings_path(path)
    if not resolved.exists():
        return BitterRecipeSettings()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return BitterRecipeSettings()
    if not isinstance(payload, dict):
        return BitterRecipeSettings()
    return _normalize_payload(payload)


def save_settings(
    settings: BitterRecipeSettings,
    path: Path | str | None = None,
) -> Path:
    resolved = settings_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(asdict(settings), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return resolved


def resolve_labelstudio_credentials(
    settings: BitterRecipeSettings,
    *,
    label_studio_url: str | None = None,
    label_studio_api_key: str | None = None,
) -> tuple[str, str]:
    url = (
        label_studio_url
        or settings.label_studio_url
        or os.getenv("LABEL_STUDIO_URL")
        or ""
    ).strip()
    api_key = (
        label_studio_api_key
        or settings.label_studio_api_key
        or os.getenv("LABEL_STUDIO_API_KEY")
        or ""
    ).strip()
    if not url:
        raise RuntimeError(
            "Label Studio URL missing. Set it in bitter-recipe settings or LABEL_STUDIO_URL."
        )
    if not api_key:
        raise RuntimeError(
            "Label Studio API key missing. Set it in bitter-recipe settings or LABEL_STUDIO_API_KEY."
        )
    return url, api_key
