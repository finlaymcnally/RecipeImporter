from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import metadata
from typing import Any

SEQUENCE_MATCHER_ENV = "COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER"
_SUPPORTED_MODES: tuple[str, ...] = (
    "dmp",
)
_SUPPORTED_MODE_SET = set(_SUPPORTED_MODES)


@dataclass(frozen=True)
class SequenceMatcherSelection:
    matcher_class: type[Any]
    implementation: str
    version: str | None
    forced_mode: str | None
    extra_telemetry: dict[str, Any] | None = None


_SELECTION_CACHE: SequenceMatcherSelection | None = None


def _normalized_mode(raw_value: str | None) -> str:
    normalized = str(raw_value or "dmp").strip().lower()
    if normalized not in _SUPPORTED_MODE_SET:
        supported = ", ".join(_SUPPORTED_MODES)
        raise ValueError(
            f"Invalid {SEQUENCE_MATCHER_ENV} value: {raw_value!r}. "
            f"Expected one of: {supported}. "
            "Other matcher implementations are archived."
        )
    return normalized


def supported_sequence_matcher_modes() -> tuple[str, ...]:
    """Return all supported matcher selector modes in display order."""
    return _SUPPORTED_MODES


def _distribution_version(distribution_name: str) -> str | None:
    try:
        return metadata.version(distribution_name)
    except metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        return None


def _try_dmp(*, forced_mode: str | None) -> SequenceMatcherSelection | None:
    try:
        from cookimport.bench.dmp_sequence_matcher import (
            DmpSequenceMatcher,
            resolve_dmp_runtime_options,
        )
        from fast_diff_match_patch import diff as _dmp_diff
    except Exception:  # noqa: BLE001
        return None
    _ = _dmp_diff
    options = resolve_dmp_runtime_options()
    return SequenceMatcherSelection(
        matcher_class=DmpSequenceMatcher,
        implementation="dmp",
        version=_distribution_version("fast-diff-match-patch"),
        forced_mode=forced_mode,
        extra_telemetry={
            "alignment_dmp_cleanup": options.cleanup,
            "alignment_dmp_checklines": bool(options.checklines),
            "alignment_dmp_timelimit": float(options.timelimit),
        },
    )


def select_sequence_matcher() -> SequenceMatcherSelection:
    mode = _normalized_mode(os.getenv(SEQUENCE_MATCHER_ENV))
    if mode != "dmp":
        raise ValueError(
            f"Invalid {SEQUENCE_MATCHER_ENV} value: {mode!r}. Expected one of: dmp."
        )

    selection = _try_dmp(forced_mode="dmp")
    if selection is None:
        raise RuntimeError(
            "COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=dmp requested, "
            "but fast-diff-match-patch is not available."
        )
    return selection


def get_sequence_matcher_selection() -> SequenceMatcherSelection:
    global _SELECTION_CACHE
    if _SELECTION_CACHE is None:
        _SELECTION_CACHE = select_sequence_matcher()
    return _SELECTION_CACHE


def reset_sequence_matcher_selection_cache() -> None:
    global _SELECTION_CACHE
    _SELECTION_CACHE = None


def SequenceMatcher(*args: Any, **kwargs: Any) -> Any:
    return get_sequence_matcher_selection().matcher_class(*args, **kwargs)
