from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from cookimport.config.codex_decision import BUCKET1_FIXED_BEHAVIOR_VERSION
from cookimport.config.run_settings import RunSettings
from cookimport.paths import resolve_book_cache_root

BOOK_CACHE_LOCK_SUFFIX = ".lock"
BOOK_CACHE_WAIT_SECONDS = 120.0
BOOK_CACHE_POLL_SECONDS = 0.25
CONVERSION_CACHE_SCHEMA_VERSION = "book_conversion_cache_entry.v1"
CONVERSION_CACHE_KEY_SCHEMA_VERSION = "book_conversion_cache_key.v1"
PREVIEW_CACHE_KEY_SCHEMA_VERSION = "book_preview_cache_key.v2"
_CONVERSION_CACHE_INCLUDED_FIELDS = (
    "bucket1_fixed_behavior_version",
    "epub_extractor",
    "epub_unstructured_html_parser_version",
    "epub_unstructured_skip_headers_footers",
    "epub_unstructured_preprocess_mode",
    "ocr_device",
    "pdf_ocr_policy",
    "ocr_batch_size",
    "pdf_column_gap_ratio",
    "multi_recipe_splitter",
    "multi_recipe_min_ingredient_lines",
    "multi_recipe_min_instruction_lines",
    "multi_recipe_for_the_guardrail",
    "web_schema_extractor",
    "web_schema_normalizer",
    "web_html_text_extractor",
    "web_schema_policy",
    "web_schema_min_confidence",
    "web_schema_min_ingredients",
    "web_schema_min_instruction_steps",
)
_PREVIEW_CACHE_INCLUDED_FIELDS = (
    "llm_recipe_pipeline",
    "llm_knowledge_pipeline",
    "line_role_pipeline",
    "atomic_block_splitter",
    "line_role_codex_exec_style",
    "knowledge_codex_exec_style",
    "recipe_prompt_target_count",
    "knowledge_prompt_target_count",
    "knowledge_packet_input_char_budget",
    "knowledge_packet_output_char_budget",
    "line_role_prompt_target_count",
    "line_role_shard_target_lines",
    "codex_farm_context_blocks",
    "codex_farm_knowledge_context_blocks",
)
_T = TypeVar("_T")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def stable_json_sha256(payload: Any) -> str:
    canonical = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_config_with_cache_versions(settings: RunSettings) -> dict[str, Any]:
    payload = settings.to_run_config_dict()
    payload["bucket1_fixed_behavior_version"] = BUCKET1_FIXED_BEHAVIOR_VERSION
    return payload


def build_conversion_cache_key(
    *,
    source_file: Path,
    source_hash: str,
    pipeline: str | None,
    run_settings: RunSettings,
) -> str:
    run_config = _run_config_with_cache_versions(run_settings)
    selected_inputs = {
        key: run_config.get(key)
        for key in _CONVERSION_CACHE_INCLUDED_FIELDS
        if key in run_config
    }
    payload = {
        "schema_version": CONVERSION_CACHE_KEY_SCHEMA_VERSION,
        "source_hash": str(source_hash or "").strip(),
        "source_suffix": source_file.suffix.lower(),
        "pipeline": str(pipeline or "auto").strip().lower() or "auto",
        "inputs": selected_inputs,
    }
    return stable_json_sha256(payload)


def build_preview_cache_key(selected_settings: RunSettings) -> str:
    run_config = _run_config_with_cache_versions(selected_settings)
    payload = {
        "schema_version": PREVIEW_CACHE_KEY_SCHEMA_VERSION,
        "settings": {
            key: run_config.get(key)
            for key in _PREVIEW_CACHE_INCLUDED_FIELDS
            if key in run_config
        },
    }
    return stable_json_sha256(payload)


def conversion_cache_entry_path(
    *,
    book_cache_root: Path | str | None,
    source_hash: str,
    conversion_key: str,
) -> Path:
    root = resolve_book_cache_root(book_cache_root)
    return root / "conversion" / str(source_hash or "unknown") / f"{conversion_key}.json"


def deterministic_prep_artifact_root(
    *,
    book_cache_root: Path | str | None,
    source_hash: str,
    prep_key: str,
) -> Path:
    root = resolve_book_cache_root(book_cache_root)
    return root / "deterministic-prep" / str(source_hash or "unknown") / prep_key


def preview_cache_manifest_path(
    *,
    book_cache_root: Path | str | None,
    source_hash: str,
    prep_key: str,
    selected_settings: RunSettings,
) -> Path:
    root = resolve_book_cache_root(book_cache_root)
    return (
        root
        / "preview"
        / str(source_hash or "unknown")
        / prep_key
        / f"{build_preview_cache_key(selected_settings)}.json"
    )


def entry_lock_path(entry_path: Path) -> Path:
    return entry_path.parent / f"{entry_path.name}{BOOK_CACHE_LOCK_SUFFIX}"


def read_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def load_json_dict_or_none(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = read_json_dict(path)
    except Exception:  # noqa: BLE001
        return None
    return payload


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}")
    tmp_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def acquire_entry_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except (FileExistsError, OSError):
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                    sort_keys=True,
                )
            )
    except Exception:  # noqa: BLE001
        try:
            lock_path.unlink()
        except OSError:
            pass
        return False
    return True


def release_entry_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        return


def wait_for_entry(
    *,
    load_entry: Callable[[], _T | None],
    lock_path: Path,
    wait_seconds: float = BOOK_CACHE_WAIT_SECONDS,
    poll_seconds: float = BOOK_CACHE_POLL_SECONDS,
) -> _T | None:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    sleep_seconds = max(0.05, float(poll_seconds))
    while time.monotonic() < deadline:
        cached = load_entry()
        if cached is not None:
            return cached
        if not lock_path.exists():
            break
        time.sleep(sleep_seconds)
    return load_entry()


__all__ = [
    "BOOK_CACHE_LOCK_SUFFIX",
    "BOOK_CACHE_POLL_SECONDS",
    "BOOK_CACHE_WAIT_SECONDS",
    "CONVERSION_CACHE_KEY_SCHEMA_VERSION",
    "CONVERSION_CACHE_SCHEMA_VERSION",
    "PREVIEW_CACHE_KEY_SCHEMA_VERSION",
    "acquire_entry_lock",
    "build_conversion_cache_key",
    "build_preview_cache_key",
    "conversion_cache_entry_path",
    "deterministic_prep_artifact_root",
    "entry_lock_path",
    "load_json_dict_or_none",
    "preview_cache_manifest_path",
    "read_json_dict",
    "release_entry_lock",
    "stable_json_sha256",
    "wait_for_entry",
    "write_json_atomic",
]
