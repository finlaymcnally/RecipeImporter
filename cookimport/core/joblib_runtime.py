from __future__ import annotations

import multiprocessing
import os
import threading
import warnings

_JOBLIB_MULTIPROCESSING_ENV = "JOBLIB_MULTIPROCESSING"
_GUARD_DISABLE_ENV = "COOKIMPORT_DISABLE_JOBLIB_SEMLOCK_GUARD"
_DISABLE_VALUES = {"1", "true", "yes", "on"}
_SERIAL_WARNING_PATTERN = r".*joblib will operate in serial mode.*"
_SERIAL_WARNING_MODULE = r"joblib\._multiprocessing_helpers"

_GUARD_LOCK = threading.Lock()
_GUARD_CONFIGURED = False


def _guard_disabled() -> bool:
    raw = str(os.getenv(_GUARD_DISABLE_ENV, "") or "").strip().lower()
    return raw in _DISABLE_VALUES


def _looks_like_semlock_restriction(exc: BaseException) -> bool:
    if isinstance(exc, (PermissionError, OSError)):
        return True
    detail = str(exc or "")
    lowered = detail.lower()
    return "permission denied" in lowered or "semlock" in lowered


def _probe_semlock_available() -> tuple[bool, str | None]:
    try:
        semaphore = multiprocessing.Semaphore(1)
        acquired = semaphore.acquire(block=False)
        if acquired:
            semaphore.release()
    except Exception as exc:  # noqa: BLE001
        if _looks_like_semlock_restriction(exc):
            return False, f"{type(exc).__name__}: {exc}"
        return True, f"ignored probe failure: {type(exc).__name__}: {exc}"
    return True, None


def configure_joblib_runtime_for_restricted_hosts() -> bool:
    """Disable joblib multiprocessing when SemLock is restricted in this runtime.

    Returns True when the guard forced `JOBLIB_MULTIPROCESSING=0`.
    """

    global _GUARD_CONFIGURED
    with _GUARD_LOCK:
        if _GUARD_CONFIGURED:
            return str(os.getenv(_JOBLIB_MULTIPROCESSING_ENV, "") or "").strip() == "0"
        _GUARD_CONFIGURED = True

        if _guard_disabled():
            return False

        existing = str(os.getenv(_JOBLIB_MULTIPROCESSING_ENV, "") or "").strip()
        if existing:
            return existing == "0"

        semlock_available, _probe_detail = _probe_semlock_available()
        if semlock_available:
            return False

        os.environ[_JOBLIB_MULTIPROCESSING_ENV] = "0"
        warnings.filterwarnings(
            "ignore",
            message=_SERIAL_WARNING_PATTERN,
            category=UserWarning,
            module=_SERIAL_WARNING_MODULE,
        )
        return True
