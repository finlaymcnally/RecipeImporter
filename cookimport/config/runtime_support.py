from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


def _normalized_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = env or os.environ
    return {str(key): str(value) for key, value in source.items()}


@lru_cache(maxsize=1)
def default_run_settings() -> Any:
    from cookimport.config.run_settings import RunSettings

    return RunSettings()


def run_setting_default(field_name: str) -> Any:
    settings = default_run_settings()
    if not hasattr(settings, field_name):
        raise KeyError(f"Unknown run setting default: {field_name}")
    return getattr(settings, field_name)


def serialized_run_setting_default(field_name: str) -> Any:
    value = run_setting_default(field_name)
    return getattr(value, "value", value)


def resolve_setting_value(
    settings: Mapping[str, Any] | Any | None,
    field_name: str,
    *,
    default: Any,
) -> Any:
    if settings is None:
        return default
    if isinstance(settings, Mapping) and field_name in settings:
        value = settings[field_name]
    else:
        value = getattr(settings, field_name, default)
    if value is None:
        return default
    return getattr(value, "value", value)


def _resolve_float(
    value: Any,
    *,
    default: float,
    minimum: float = 0.0,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if parsed < minimum:
        return float(default)
    return parsed


def _resolve_int(
    value: Any,
    *,
    default: int,
    minimum: int = 0,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    if parsed < minimum:
        return int(default)
    return parsed


def resolve_workspace_completion_quiescence_seconds(
    settings: Mapping[str, Any] | Any | None = None,
) -> float:
    return _resolve_float(
        resolve_setting_value(
            settings,
            "workspace_completion_quiescence_seconds",
            default=serialized_run_setting_default(
                "workspace_completion_quiescence_seconds"
            ),
        ),
        default=float(
            serialized_run_setting_default("workspace_completion_quiescence_seconds")
        ),
        minimum=0.1,
    )


def resolve_completed_termination_grace_seconds(
    settings: Mapping[str, Any] | Any | None = None,
) -> float:
    return _resolve_float(
        resolve_setting_value(
            settings,
            "completed_termination_grace_seconds",
            default=serialized_run_setting_default(
                "completed_termination_grace_seconds"
            ),
        ),
        default=float(
            serialized_run_setting_default("completed_termination_grace_seconds")
        ),
        minimum=0.1,
    )


def resolve_prelabel_cache_dir(
    cache_dir: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    if cache_dir is not None:
        return Path(cache_dir).expanduser()
    normalized_env = _normalized_env(env)
    xdg_cache_home = str(normalized_env.get("XDG_CACHE_HOME") or "").strip()
    if xdg_cache_home:
        cache_root = Path(xdg_cache_home).expanduser()
    else:
        cache_root = Path.home() / ".cache"
    return cache_root / "cookimport" / "prelabel"


def resolve_runtime_temp_root(
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    normalized_env = _normalized_env(env)
    for key in ("TMPDIR", "TEMP", "TMP"):
        raw_value = str(normalized_env.get(key) or "").strip()
        if raw_value:
            return Path(raw_value).expanduser().resolve(strict=False)
    return Path(tempfile.gettempdir()).expanduser().resolve(strict=False)


def workspace_allowed_temp_roots(
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    roots: list[Path] = [resolve_runtime_temp_root(env=env)]
    for candidate in (
        Path("/private/tmp"),
        Path("/var/tmp"),
        Path("/tmp"),
    ):
        roots.append(candidate)
    deduped: list[str] = []
    seen: set[str] = set()
    for root in roots:
        rendered = str(root.expanduser().resolve(strict=False))
        if rendered in seen:
            continue
        seen.add(rendered)
        deduped.append(rendered)
    return tuple(deduped)


def workspace_fs_cage_mktemp_template(
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    return str(resolve_runtime_temp_root(env=env) / "recipeimport-workspace-fs-cage.XXXXXX")


def resolve_single_book_split_cache_wait_seconds() -> float:
    return _resolve_float(
        os.environ.get("COOKIMPORT_SINGLE_BOOK_SPLIT_CACHE_WAIT_SECONDS"),
        default=120.0,
        minimum=0.0,
    )


def resolve_single_book_split_cache_poll_seconds() -> float:
    return _resolve_float(
        os.environ.get("COOKIMPORT_SINGLE_BOOK_SPLIT_CACHE_POLL_SECONDS"),
        default=0.25,
        minimum=0.01,
    )


@dataclass(frozen=True)
class SingleProfileSchedulerPolicy:
    parallel_books_cap: int
    worker_scale_numerator: int
    worker_scale_denominator: int
    split_phase_slots: int


def resolve_single_profile_scheduler_policy() -> SingleProfileSchedulerPolicy:
    numerator = _resolve_int(
        os.environ.get("COOKIMPORT_SINGLE_PROFILE_WORKER_SCALE_NUMERATOR"),
        default=8,
        minimum=1,
    )
    denominator = _resolve_int(
        os.environ.get("COOKIMPORT_SINGLE_PROFILE_WORKER_SCALE_DENOMINATOR"),
        default=10,
        minimum=1,
    )
    return SingleProfileSchedulerPolicy(
        parallel_books_cap=_resolve_int(
            os.environ.get("COOKIMPORT_SINGLE_PROFILE_PARALLEL_BOOKS_CAP"),
            default=3,
            minimum=1,
        ),
        worker_scale_numerator=numerator,
        worker_scale_denominator=denominator,
        split_phase_slots=_resolve_int(
            os.environ.get("COOKIMPORT_SINGLE_PROFILE_SPLIT_PHASE_SLOTS"),
            default=1,
            minimum=1,
        ),
    )


def resolve_oracle_browser_shard_target_bytes() -> int:
    return _resolve_int(
        os.environ.get("COOKIMPORT_ORACLE_BROWSER_SHARD_TARGET_BYTES"),
        default=900_000,
        minimum=1,
    )


def resolve_oracle_background_session_poll_seconds() -> float:
    return _resolve_float(
        os.environ.get("COOKIMPORT_ORACLE_BACKGROUND_SESSION_POLL_SECONDS"),
        default=3.0,
        minimum=0.0,
    )


def resolve_oracle_background_session_poll_interval_seconds() -> float:
    return _resolve_float(
        os.environ.get("COOKIMPORT_ORACLE_BACKGROUND_SESSION_POLL_INTERVAL_SECONDS"),
        default=0.1,
        minimum=0.0,
    )
