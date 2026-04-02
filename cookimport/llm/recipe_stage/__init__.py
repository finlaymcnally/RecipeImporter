from __future__ import annotations

"""Recipe-stage owner package.

Import specific owner modules from this package directly; avoid eager package-level
re-export glue so internal owner modules can be imported without recipe-stage
bootstrap cycles.
"""

from importlib import import_module
from typing import Any


def __getattr__(name: str) -> Any:
    return getattr(import_module("cookimport.llm.recipe_stage_shared"), name)
