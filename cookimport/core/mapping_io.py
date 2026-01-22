from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from cookimport.core.models import MappingConfig


def _dump_mapping(mapping: MappingConfig) -> dict[str, Any]:
    return mapping.model_dump(by_alias=True, exclude_none=True)


def load_mapping_config(path: Path) -> MappingConfig:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(raw)
    else:
        payload = yaml.safe_load(raw) or {}
    return MappingConfig.model_validate(payload)


def save_mapping_config(path: Path, mapping: MappingConfig) -> None:
    payload = _dump_mapping(mapping)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
