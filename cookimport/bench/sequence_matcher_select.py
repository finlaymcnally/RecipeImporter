from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import Any

SEQUENCE_MATCHER_ENV = "COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER"
_SUPPORTED_MODES: tuple[str, ...] = (
    "auto",
    "stdlib",
    "cydifflib",
    "cdifflib",
    "dmp",
    "multilayer",
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
    normalized = str(raw_value or "auto").strip().lower()
    if normalized not in _SUPPORTED_MODE_SET:
        supported = ", ".join(sorted(_SUPPORTED_MODES))
        raise ValueError(
            f"Invalid {SEQUENCE_MATCHER_ENV} value: {raw_value!r}. "
            f"Expected one of: {supported}."
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


def _stdlib_selection(*, forced_mode: str | None) -> SequenceMatcherSelection:
    from difflib import SequenceMatcher as StdlibSequenceMatcher

    return SequenceMatcherSelection(
        matcher_class=StdlibSequenceMatcher,
        implementation="stdlib",
        version=sys.version.split()[0],
        forced_mode=forced_mode,
        extra_telemetry=None,
    )


def _try_cydifflib(*, forced_mode: str | None) -> SequenceMatcherSelection | None:
    try:
        from cydifflib import SequenceMatcher as CySequenceMatcher
    except Exception:  # noqa: BLE001
        return None
    return SequenceMatcherSelection(
        matcher_class=CySequenceMatcher,
        implementation="cydifflib",
        version=_distribution_version("cydifflib"),
        forced_mode=forced_mode,
        extra_telemetry=None,
    )


def _try_cdifflib(*, forced_mode: str | None) -> SequenceMatcherSelection | None:
    try:
        from cdifflib import CSequenceMatcher
    except Exception:  # noqa: BLE001
        return None
    return SequenceMatcherSelection(
        matcher_class=CSequenceMatcher,
        implementation="cdifflib",
        version=_distribution_version("cdifflib"),
        forced_mode=forced_mode,
        extra_telemetry=None,
    )


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


def _try_multilayer(*, forced_mode: str | None) -> SequenceMatcherSelection | None:
    try:
        from cookimport.bench.sequence_matcher_multilayer import (
            MultiLayerSequenceMatcher,
            resolve_multilayer_runtime_options,
        )
    except Exception:  # noqa: BLE001
        return None
    options = resolve_multilayer_runtime_options()
    return SequenceMatcherSelection(
        matcher_class=MultiLayerSequenceMatcher,
        implementation="multilayer",
        version="spike-2026-02-27",
        forced_mode=forced_mode,
        extra_telemetry={
            "alignment_multilayer_memult": float(options["memult"]),
        },
    )


def select_sequence_matcher() -> SequenceMatcherSelection:
    mode = _normalized_mode(os.getenv(SEQUENCE_MATCHER_ENV))
    forced_mode = mode if mode != "auto" else None

    if mode == "stdlib":
        return _stdlib_selection(forced_mode=forced_mode)
    if mode == "cydifflib":
        selection = _try_cydifflib(forced_mode=forced_mode)
        if selection is None:
            raise RuntimeError(
                "COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=cydifflib requested, "
                "but cydifflib is not available."
            )
        return selection
    if mode == "cdifflib":
        selection = _try_cdifflib(forced_mode=forced_mode)
        if selection is None:
            raise RuntimeError(
                "COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=cdifflib requested, "
                "but cdifflib is not available."
            )
        return selection
    if mode == "dmp":
        selection = _try_dmp(forced_mode=forced_mode)
        if selection is None:
            raise RuntimeError(
                "COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=dmp requested, "
                "but fast-diff-match-patch is not available."
            )
        return selection
    if mode == "multilayer":
        selection = _try_multilayer(forced_mode=forced_mode)
        if selection is None:
            raise RuntimeError(
                "COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER=multilayer requested, "
                "but multilayer matcher is not available."
            )
        return selection

    selection = _try_cydifflib(forced_mode=None)
    if selection is not None:
        return selection
    selection = _try_cdifflib(forced_mode=None)
    if selection is not None:
        return selection
    selection = _try_dmp(forced_mode=None)
    if selection is not None:
        return selection
    return _stdlib_selection(forced_mode=None)


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
