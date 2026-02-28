from __future__ import annotations

import os

import pytest

from cookimport.core import joblib_runtime


@pytest.fixture(autouse=True)
def _reset_guard_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(joblib_runtime, "_GUARD_CONFIGURED", False)
    monkeypatch.delenv("JOBLIB_MULTIPROCESSING", raising=False)
    monkeypatch.delenv("COOKIMPORT_DISABLE_JOBLIB_SEMLOCK_GUARD", raising=False)


def test_guard_disables_joblib_multiprocessing_on_semlock_restriction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        joblib_runtime,
        "_probe_semlock_available",
        lambda: (False, "PermissionError: [Errno 13] Permission denied"),
    )

    forced_serial = joblib_runtime.configure_joblib_runtime_for_restricted_hosts()

    assert forced_serial is True
    assert os.environ.get("JOBLIB_MULTIPROCESSING") == "0"


def test_guard_skips_probe_when_joblib_env_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_called = {"value": False}

    def _probe() -> tuple[bool, str | None]:
        probe_called["value"] = True
        return False, "should not be used"

    monkeypatch.setenv("JOBLIB_MULTIPROCESSING", "1")
    monkeypatch.setattr(joblib_runtime, "_probe_semlock_available", _probe)

    forced_serial = joblib_runtime.configure_joblib_runtime_for_restricted_hosts()

    assert forced_serial is False
    assert probe_called["value"] is False


def test_guard_can_be_disabled_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    probe_called = {"value": False}

    def _probe() -> tuple[bool, str | None]:
        probe_called["value"] = True
        return False, "permission denied"

    monkeypatch.setenv("COOKIMPORT_DISABLE_JOBLIB_SEMLOCK_GUARD", "1")
    monkeypatch.setattr(joblib_runtime, "_probe_semlock_available", _probe)

    forced_serial = joblib_runtime.configure_joblib_runtime_for_restricted_hosts()

    assert forced_serial is False
    assert probe_called["value"] is False
    assert os.environ.get("JOBLIB_MULTIPROCESSING") is None
