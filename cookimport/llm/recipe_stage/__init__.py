from __future__ import annotations

from .. import recipe_stage_shared as _shared_module
from . import planning as _planning_module
from . import promotion as _promotion_module
from . import recovery as _recovery_module
from . import reporting as _reporting_module
from . import runtime as _runtime_module
from . import validation as _validation_module

for _module in (
    _shared_module,
    _planning_module,
    _runtime_module,
    _validation_module,
    _promotion_module,
    _recovery_module,
    _reporting_module,
):
    globals().update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        }
    )
