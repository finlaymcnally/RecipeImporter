from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport.bitter_recipe.paths import (
    bitter_recipe_pulled_root,
    bitter_recipe_sent_root,
    source_slug_for_path,
)
from cookimport.bitter_recipe.settings import (
    BitterRecipeSettings,
    resolve_labelstudio_credentials,
)
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.export import run_labelstudio_export
from cookimport.labelstudio.ingest_flows.upload import run_labelstudio_import


def default_project_name(
    source_path: Path,
    settings: BitterRecipeSettings,
) -> str:
    return f"{source_slug_for_path(source_path)}{settings.project_suffix}"


def preflight_labelstudio_credentials(
    settings: BitterRecipeSettings,
    *,
    label_studio_url: str | None = None,
    label_studio_api_key: str | None = None,
) -> None:
    url, api_key = resolve_labelstudio_credentials(
        settings,
        label_studio_url=label_studio_url,
        label_studio_api_key=label_studio_api_key,
    )
    client = LabelStudioClient(url, api_key)
    client.list_projects()


def list_projects(
    settings: BitterRecipeSettings,
    *,
    label_studio_url: str | None = None,
    label_studio_api_key: str | None = None,
) -> list[dict[str, Any]]:
    url, api_key = resolve_labelstudio_credentials(
        settings,
        label_studio_url=label_studio_url,
        label_studio_api_key=label_studio_api_key,
    )
    client = LabelStudioClient(url, api_key)
    projects = client.list_projects()
    return [project for project in projects if isinstance(project, dict)]


def prepare_import(
    *,
    source_path: Path,
    settings: BitterRecipeSettings,
    project_name: str | None = None,
    prelabel: bool | None = None,
    label_studio_url: str | None = None,
    label_studio_api_key: str | None = None,
) -> dict[str, Any]:
    url, api_key = resolve_labelstudio_credentials(
        settings,
        label_studio_url=label_studio_url,
        label_studio_api_key=label_studio_api_key,
    )
    effective_prelabel = settings.default_prelabel if prelabel is None else prelabel
    project_title = project_name or default_project_name(source_path, settings)
    codex_model = settings.codex_model.strip() or None
    codex_reasoning_effort = settings.codex_reasoning_effort.strip() or None
    return run_labelstudio_import(
        path=source_path,
        output_dir=bitter_recipe_sent_root(settings.bitter_recipe_root_path()),
        pipeline="auto",
        project_name=project_title,
        segment_blocks=settings.segment_blocks,
        segment_overlap=settings.segment_overlap,
        segment_focus_blocks=settings.segment_focus_blocks,
        target_task_count=settings.target_task_count,
        overwrite=False,
        resume=True,
        label_studio_url=url,
        label_studio_api_key=api_key,
        upload_batch_size=settings.upload_batch_size,
        prelabel=effective_prelabel,
        codex_model=codex_model,
        codex_reasoning_effort=codex_reasoning_effort,
        prelabel_allow_partial=settings.prelabel_allow_partial,
        allow_codex=effective_prelabel,
        allow_labelstudio_write=True,
    )


def export_labels(
    *,
    project_name: str,
    settings: BitterRecipeSettings,
    run_dir: Path | None = None,
    label_studio_url: str | None = None,
    label_studio_api_key: str | None = None,
) -> dict[str, Any]:
    url, api_key = resolve_labelstudio_credentials(
        settings,
        label_studio_url=label_studio_url,
        label_studio_api_key=label_studio_api_key,
    )
    return run_labelstudio_export(
        project_name=project_name,
        output_dir=bitter_recipe_pulled_root(settings.bitter_recipe_root_path()),
        label_studio_url=url,
        label_studio_api_key=api_key,
        run_dir=run_dir,
    )


def load_manifest_metadata(run_root: Path) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
