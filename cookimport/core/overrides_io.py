from __future__ import annotations

import json
from pathlib import Path

import yaml

from cookimport.core.models import ParsingOverrides


def load_parsing_overrides(path: Path) -> ParsingOverrides:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(raw)
    else:
        payload = yaml.safe_load(raw) or {}
    return ParsingOverrides.model_validate(payload)
