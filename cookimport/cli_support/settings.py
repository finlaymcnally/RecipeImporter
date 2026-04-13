from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping

from cookimport.config.runtime_support import serialized_run_setting_default
from cookimport.epub_extractor_names import (
    EPUB_EXTRACTOR_CANONICAL_SET,
    is_policy_locked_epub_extractor_name,
    normalize_epub_extractor_name,
)
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.plugins import registry

_LOCAL_ONLY_SETTINGS_KEYS = ("label_studio_api_key",)


def _runtime():
    from cookimport import cli_support as runtime

    return runtime


def _load_json_object(path: Path) -> Dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except Exception:
        return None
    if isinstance(loaded, dict):
        return dict(loaded)
    return None


def _load_settings() -> Dict[str, Any]:
    runtime = _runtime()
    source_parallel_default = _all_method_default_parallel_sources_from_cpu()
    run_setting_keys = (
        "workers",
        "pdf_split_workers",
        "epub_split_workers",
        "epub_extractor",
        "epub_unstructured_html_parser_version",
        "epub_unstructured_skip_headers_footers",
        "epub_unstructured_preprocess_mode",
        "web_schema_extractor",
        "web_schema_normalizer",
        "web_html_text_extractor",
        "web_schema_policy",
        "web_schema_min_confidence",
        "web_schema_min_ingredients",
        "web_schema_min_instruction_steps",
        "llm_recipe_pipeline",
        "llm_knowledge_pipeline",
        "line_role_pipeline",
        "atomic_block_splitter",
        "pdf_ocr_policy",
        "codex_farm_cmd",
        "codex_farm_root",
        "codex_farm_workspace_root",
        "codex_farm_model",
        "codex_farm_reasoning_effort",
        "codex_farm_context_blocks",
        "codex_farm_knowledge_context_blocks",
        "ocr_device",
        "ocr_batch_size",
        "pdf_pages_per_job",
        "epub_spine_items_per_job",
        "warm_models",
    )
    defaults = {
        **{
            key: serialized_run_setting_default(key)
            for key in run_setting_keys
        },
        runtime.ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY: source_parallel_default,
        runtime.ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY: runtime.ALL_METHOD_SCHEDULER_SCOPE_DEFAULT,
        runtime.ALL_METHOD_MAX_INFLIGHT_SETTING_KEY: runtime.ALL_METHOD_MAX_INFLIGHT_DEFAULT,
        runtime.ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY: runtime.ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
        runtime.ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY: runtime.ALL_METHOD_MAX_EVAL_TAIL_DEFAULT,
        runtime.ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY: runtime.ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT,
        runtime.ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY: runtime.ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT,
        runtime.ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY: runtime.ALL_METHOD_SOURCE_SCHEDULING_DEFAULT,
        runtime.ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY: (
            runtime.ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
        ),
        runtime.ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY: (
            runtime.ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
        ),
        runtime.ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY: (
            runtime.ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
        ),
        runtime.ALL_METHOD_SMART_SCHEDULER_SETTING_KEY: True,
        "label_studio_url": "",
        "label_studio_api_key": "",
        "output_dir": str(runtime.DEFAULT_INTERACTIVE_OUTPUT),
    }
    tracked_loaded = _load_json_object(runtime.DEFAULT_CONFIG_PATH)
    local_loaded = _load_json_object(runtime.DEFAULT_LOCAL_CONFIG_PATH)

    if tracked_loaded is None and not runtime.DEFAULT_CONFIG_PATH.exists():
        defaults[runtime.ALL_METHOD_WING_BACKLOG_SETTING_KEY] = defaults[
            runtime.ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
        defaults[runtime.ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY] = defaults[
            runtime.ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
        tracked_loaded = None

    if tracked_loaded is None:
        defaults[runtime.ALL_METHOD_WING_BACKLOG_SETTING_KEY] = defaults[
            runtime.ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
        defaults[runtime.ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY] = defaults[
            runtime.ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
        tracked_loaded = {}

    merged = {**defaults, **tracked_loaded}
    if isinstance(local_loaded, dict):
        merged.update(local_loaded)
    if runtime.ALL_METHOD_WING_BACKLOG_SETTING_KEY not in tracked_loaded:
        merged[runtime.ALL_METHOD_WING_BACKLOG_SETTING_KEY] = _resolve_positive_int_setting(
            merged,
            key=runtime.ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
            fallback=runtime.ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
        )
    if runtime.ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY not in tracked_loaded:
        merged[runtime.ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY] = _resolve_positive_int_setting(
            merged,
            key=runtime.ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
            fallback=runtime.ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
        )
    merged[runtime.ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY] = (
        _normalize_all_method_scheduler_scope(
            merged.get(runtime.ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY)
        )
    )
    return merged


def _run_settings_payload_from_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _runtime()
    return runtime.project_run_config_payload(
        settings,
        contract=runtime.RUN_SETTING_CONTRACT_FULL,
    )


def _save_settings(settings: Dict[str, Any]) -> None:
    runtime = _runtime()
    runtime.DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tracked_settings = dict(settings)
    existing_local_settings = _load_json_object(runtime.DEFAULT_LOCAL_CONFIG_PATH) or {}
    local_settings = dict(existing_local_settings)
    for key in _LOCAL_ONLY_SETTINGS_KEYS:
        if key in tracked_settings:
            value = tracked_settings.pop(key)
            cleaned = str(value or "").strip()
            if cleaned:
                local_settings[key] = cleaned
            else:
                local_settings.pop(key, None)
    with open(runtime.DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(tracked_settings, handle, indent=2)
    if local_settings:
        runtime.DEFAULT_LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(runtime.DEFAULT_LOCAL_CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(local_settings, handle, indent=2)
    elif runtime.DEFAULT_LOCAL_CONFIG_PATH.exists():
        runtime.DEFAULT_LOCAL_CONFIG_PATH.unlink()


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _coerce_non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _coerce_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _coerce_float_between(
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed


def _display_optional_setting(value: Any, *, empty_label: str) -> str:
    cleaned = str(value or "").strip()
    return cleaned or empty_label


def _coerce_bool_setting(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _resolve_positive_int_setting(
    settings: Dict[str, Any],
    *,
    key: str,
    fallback: int,
) -> int:
    parsed = _coerce_positive_int(settings.get(key))
    if parsed is None:
        return fallback
    return parsed


def _resolve_non_negative_int_setting(
    settings: Dict[str, Any],
    *,
    key: str,
    fallback: int,
) -> int:
    parsed = _coerce_non_negative_int(settings.get(key))
    if parsed is None:
        return fallback
    return parsed


def _resolve_positive_float_setting(
    settings: Dict[str, Any],
    *,
    key: str,
    fallback: float,
) -> float:
    parsed = _coerce_positive_float(settings.get(key))
    if parsed is None:
        return fallback
    return parsed


def _normalize_all_method_source_scheduling(value: Any) -> str:
    runtime = _runtime()
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {
        runtime.ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY,
        runtime.ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR,
    }:
        return normalized
    return runtime.ALL_METHOD_SOURCE_SCHEDULING_DEFAULT


def _normalize_all_method_scheduler_scope(value: Any) -> str:
    runtime = _runtime()
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized == runtime.ALL_METHOD_SCHEDULER_SCOPE_GLOBAL:
        return normalized
    return runtime.ALL_METHOD_SCHEDULER_SCOPE_DEFAULT


def _resolve_interactive_labelstudio_settings(
    settings: Dict[str, Any],
) -> tuple[str, str] | None:
    runtime = _runtime()
    env_url = os.getenv("LABEL_STUDIO_URL")
    env_api_key = os.getenv("LABEL_STUDIO_API_KEY")
    stored_url = str(settings.get("label_studio_url", "") or "").strip()
    stored_api_key = str(settings.get("label_studio_api_key", "") or "").strip()

    label_studio_url = env_url or stored_url
    label_studio_api_key = env_api_key or stored_api_key

    if not label_studio_url:
        label_studio_url = runtime._prompt_text(
            "Label Studio URL:",
            default=stored_url or "http://localhost:8080",
        )
        if label_studio_url is None:
            return None
    if not label_studio_api_key:
        label_studio_api_key = runtime._prompt_password(
            "Label Studio API key:",
        )
        if label_studio_api_key is None:
            return None

    url, api_key = runtime._resolve_labelstudio_settings(
        label_studio_url,
        label_studio_api_key,
    )

    changed = False
    if not env_url and url != stored_url:
        settings["label_studio_url"] = url
        changed = True
    if not env_api_key and api_key != stored_api_key:
        settings["label_studio_api_key"] = api_key
        changed = True
    if changed:
        runtime._save_settings(settings)

    if not env_url and not env_api_key:
        preflight_error = runtime._preflight_labelstudio_credentials(url, api_key)
        if preflight_error and runtime._is_labelstudio_credential_error(preflight_error):
            runtime.typer.secho(
                "Saved Label Studio credentials were rejected. Please enter updated values.",
                fg=runtime.typer.colors.YELLOW,
            )
            refreshed_url = runtime._prompt_text(
                "Label Studio URL:",
                default=url,
            )
            refreshed_api_key = runtime._prompt_password(
                "Label Studio API key:",
            )
            if refreshed_url is None or refreshed_api_key is None:
                return None
            url, api_key = runtime._resolve_labelstudio_settings(
                refreshed_url,
                refreshed_api_key,
            )
            settings["label_studio_url"] = url
            settings["label_studio_api_key"] = api_key
            runtime._save_settings(settings)
            retry_error = runtime._preflight_labelstudio_credentials(url, api_key)
            if retry_error and runtime._is_labelstudio_credential_error(retry_error):
                runtime._fail(f"Updated Label Studio credentials were rejected: {retry_error}")

    return url, api_key


def _preflight_labelstudio_credentials(url: str, api_key: str) -> str | None:
    try:
        client = LabelStudioClient(url, api_key)
        client.list_projects()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def _is_labelstudio_credential_error(error_text: str) -> bool:
    normalized = error_text.lower()
    return (
        "api error 401" in normalized
        or "api error 403" in normalized
        or "api error 404" in normalized
    )


def _list_importable_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files = []
    for file_path in folder.glob("*"):
        if file_path.is_file() and not file_path.name.startswith("."):
            _, score = registry.best_importer_for_path(file_path)
            if score > 0:
                files.append(file_path)
    return sorted(files)


def _all_method_default_parallel_sources_from_cpu() -> int:
    runtime = _runtime()
    cpu_total = max(1, int(os.cpu_count() or 1))
    baseline = 2 if cpu_total >= 4 else 1
    cpu_scaled = max(baseline, cpu_total // 4)
    return max(1, min(runtime.ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT, cpu_scaled))


def _coerce_configured_epub_extractor(value: Any) -> str:
    normalized = normalize_epub_extractor_name(value or "unstructured")
    if normalized == "auto":
        return "unstructured"
    if normalized not in EPUB_EXTRACTOR_CANONICAL_SET:
        return "unstructured"
    if is_policy_locked_epub_extractor_name(normalized):
        return "unstructured"
    return normalized
