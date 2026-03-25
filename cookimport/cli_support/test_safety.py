from __future__ import annotations

import os

_RUNNING_UNDER_PYTEST_ENV = "COOKIMPORT_RUNNING_UNDER_PYTEST"
_DISABLE_HEAVY_TEST_SIDE_EFFECTS_ENV = "COOKIMPORT_DISABLE_HEAVY_TEST_SIDE_EFFECTS"
_ALLOW_HEAVY_TEST_SIDE_EFFECTS_ENV = "COOKIMPORT_ALLOW_HEAVY_TEST_SIDE_EFFECTS"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


class HeavyTestSideEffectBlocked(RuntimeError):
    """Raised when pytest code reaches a heavy helper without explicit opt-in."""


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


def heavy_test_side_effects_allowed() -> bool:
    return not heavy_test_side_effects_disabled()


def heavy_test_side_effects_error_message(side_effect_name: str) -> str:
    action = str(side_effect_name or "heavy side effect").strip() or "heavy side effect"
    return (
        f"Blocked {action} during pytest. "
        "Add @pytest.mark.heavy_side_effects and use the "
        "`allow_heavy_test_side_effects` fixture, or set "
        "COOKIMPORT_ALLOW_HEAVY_TEST_SIDE_EFFECTS=1 for the scoped test process."
    )


def require_heavy_test_side_effect_permission(side_effect_name: str) -> None:
    if heavy_test_side_effects_allowed():
        return
    raise HeavyTestSideEffectBlocked(
        heavy_test_side_effects_error_message(side_effect_name)
    )


def should_skip_heavy_test_side_effects() -> bool:
    return heavy_test_side_effects_disabled()
