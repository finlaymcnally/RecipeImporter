"""Tunable knob registry for benchmark parameter sweeps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class Tunable(BaseModel):
    """A single tunable parameter."""

    name: str
    kind: Literal["float", "int", "bool", "str"]
    default: float | int | bool | str
    bounds: tuple[float | int, float | int] | None = None
    choices: tuple[str, ...] | None = None
    description: str = ""


KNOB_REGISTRY: list[Tunable] = [
    Tunable(
        name="segment_blocks",
        kind="int",
        default=40,
        bounds=(10, 100),
        description="Blocks per freeform segment task.",
    ),
    Tunable(
        name="segment_overlap",
        kind="int",
        default=5,
        bounds=(0, 20),
        description="Overlapping blocks between freeform segments.",
    ),
    Tunable(
        name="workers",
        kind="int",
        default=1,
        bounds=(1, 8),
        description="Parallel conversion workers.",
    ),
    Tunable(
        name="epub_extractor",
        kind="str",
        default="unstructured",
        choices=("unstructured", "legacy", "markdown", "auto", "markitdown"),
        description="EPUB extractor backend used during prediction-run generation.",
    ),
]


def list_knobs() -> list[Tunable]:
    """Return all registered tunable knobs."""
    return list(KNOB_REGISTRY)


def load_config(path: Path | None) -> dict[str, Any]:
    """Load a knob config JSON file."""
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def effective_knobs(config: dict[str, Any] | None) -> dict[str, Any]:
    """Merge user config over registry defaults. Returns effective values."""
    result: dict[str, Any] = {}
    for knob in KNOB_REGISTRY:
        result[knob.name] = knob.default
    if config:
        for key, value in config.items():
            result[key] = value
    return result


def validate_knobs(config: dict[str, Any]) -> list[str]:
    """Validate knob values against registry bounds. Returns list of errors."""
    errors: list[str] = []
    registry_map = {k.name: k for k in KNOB_REGISTRY}
    for key, value in config.items():
        knob = registry_map.get(key)
        if knob is None:
            continue
        if knob.kind == "str":
            text = str(value).strip().lower()
            if knob.choices and text not in {choice.lower() for choice in knob.choices}:
                errors.append(
                    f"{key}={value!r} not in allowed values {list(knob.choices)}"
                )
            continue
        if knob.bounds is not None:
            lo, hi = knob.bounds
            if value < lo or value > hi:
                errors.append(
                    f"{key}={value} out of bounds [{lo}, {hi}]"
                )
    return errors
