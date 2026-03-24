from __future__ import annotations

from .script_bootstrap import _JS_BOOTSTRAP
from .script_compare_control import _JS_COMPARE_CONTROL
from .script_filters import _JS_FILTERS
from .script_tables import _JS_TABLES

_JS = _JS_BOOTSTRAP + _JS_FILTERS + _JS_COMPARE_CONTROL + _JS_TABLES
