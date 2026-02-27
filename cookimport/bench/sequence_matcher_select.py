from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import Any

SEQUENCE_MATCHER_ENV = "COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER"
_SUPPORTED_MODES = {"auto", "stdlib", "cydifflib", "cdifflib"}


@dataclass(frozen=True)
class SequenceMatcherSelection:
    matcher_class: type[Any]
    implementation: str
    version: str | None
    forced_mode: str | None


_SELECTION_CACHE: SequenceMatcherSelection | None = None


def _normalized_mode(raw_value: str | None) -> str:
    normalized = str(raw_value or "auto").strip().lower()
    if normalized not in _SUPPORTED_MODES:
        supported = ", ".join(sorted(_SUPPORTED_MODES))
        raise ValueError(
            f"Invalid {SEQUENCE_MATCHER_ENV} value: {raw_value!r}. "
            f"Expected one of: {supported}."
        )
    return normalized


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

    selection = _try_cydifflib(forced_mode=None)
    if selection is not None:
        return selection
    selection = _try_cdifflib(forced_mode=None)
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
