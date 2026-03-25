from __future__ import annotations

import sys

from . import recipe_stage as _recipe_stage

sys.modules[__name__] = _recipe_stage
