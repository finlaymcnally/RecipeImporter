from __future__ import annotations

import os

_RUNNING_UNDER_PYTEST_ENV = "COOKIMPORT_RUNNING_UNDER_PYTEST"
_DISABLE_HEAVY_TEST_SIDE_EFFECTS_ENV = "COOKIMPORT_DISABLE_HEAVY_TEST_SIDE_EFFECTS"
_ALLOW_HEAVY_TEST_SIDE_EFFECTS_ENV = "COOKIMPORT_ALLOW_HEAVY_TEST_SIDE_EFFECTS"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in _TRUTHY_ENV_VALUES


def running_under_pytest() -> bool:
    return _env_truthy(_RUNNING_UNDER_PYTEST_ENV) or bool(
        os.environ.get("PYTEST_CURRENT_TEST")
    )


def heavy_test_side_effects_disabled() -> bool:
    if _env_truthy(_ALLOW_HEAVY_TEST_SIDE_EFFECTS_ENV):
        return False
    if _env_truthy(_DISABLE_HEAVY_TEST_SIDE_EFFECTS_ENV):
        return True
    return running_under_pytest()


def should_skip_heavy_test_side_effects() -> bool:
    return heavy_test_side_effects_disabled()
