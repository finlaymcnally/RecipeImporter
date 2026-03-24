from __future__ import annotations

import sys

from cookimport.llm import knowledge_stage as _knowledge_stage

sys.modules[__name__] = _knowledge_stage
