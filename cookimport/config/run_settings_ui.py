from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, get_args, get_origin

from cookimport.epub_extractor_names import epub_extractor_enabled_choices
from cookimport.config.run_settings_contracts import (
    RUN_SETTING_SURFACE_PUBLIC,
    run_setting_surface,
)

from .run_settings import LlmRecipePipeline, RunSettings

_UI_REQUIRED_KEYS = ("ui_group", "ui_label", "ui_order")


@dataclass(frozen=True)
class RunSettingUiSpec:
    name: str
    label: str
    group: str
    order: int
    description: str
    value_kind: Literal["enum", "bool", "int", "string"]
    choices: tuple[str, ...] = ()
    allows_none: bool = False
    step: int = 1
    minimum: int | None = None
    maximum: int | None = None

def _unwrap_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if len(args) == 1:
        return args[0]
    return annotation


def _annotation_allows_none(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is None:
        return False
    return any(arg is type(None) for arg in get_args(annotation))


def _value_kind_for_annotation(annotation: Any) -> Literal["enum", "bool", "int", "string"]:
    unwrapped = _unwrap_optional(annotation)
    if isinstance(unwrapped, type) and issubclass(unwrapped, Enum):
        return "enum"
    if unwrapped is bool:
        return "bool"
    if unwrapped is int:
        return "int"
    return "string"


def run_settings_ui_specs(*, include_internal: bool = False) -> list[RunSettingUiSpec]:
    specs: list[RunSettingUiSpec] = []
    for field_name, field in RunSettings.model_fields.items():
        extra = dict(field.json_schema_extra or {})
        if extra.get("ui_hidden"):
            continue
        if (
            not include_internal
            and run_setting_surface(field_name) != RUN_SETTING_SURFACE_PUBLIC
        ):
            continue
        for key in _UI_REQUIRED_KEYS:
            if key not in extra:
                raise ValueError(f"RunSettings.{field_name} missing UI metadata key: {key}")

        value_kind = _value_kind_for_annotation(field.annotation)
        allows_none = _annotation_allows_none(field.annotation)
        choices: tuple[str, ...] = ()
        annotation = _unwrap_optional(field.annotation)
        if value_kind == "enum" and isinstance(annotation, type) and issubclass(annotation, Enum):
            choices = tuple(str(member.value) for member in annotation)
            if field_name == "llm_recipe_pipeline":
                choices = tuple(str(member.value) for member in LlmRecipePipeline)
            elif field_name == "epub_extractor":
                choices = epub_extractor_enabled_choices()
            if allows_none:
                none_label = (
                    "pipeline default"
                    if str(extra.get("ui_group", "")) == "LLM"
                    else "default"
                )
                choices = (none_label, *choices)
        specs.append(
            RunSettingUiSpec(
                name=field_name,
                label=str(extra["ui_label"]),
                group=str(extra["ui_group"]),
                order=int(extra["ui_order"]),
                description=str(extra.get("ui_description", "")).strip(),
                value_kind=value_kind,
                choices=choices,
                allows_none=allows_none,
                step=int(extra.get("ui_step", 1)),
                minimum=(
                    int(extra["ui_min"])
                    if extra.get("ui_min") is not None
                    else None
                ),
                maximum=(
                    int(extra["ui_max"])
                    if extra.get("ui_max") is not None
                    else None
                ),
            )
        )
    specs.sort(key=lambda spec: (spec.group, spec.order, spec.name))
    return specs
