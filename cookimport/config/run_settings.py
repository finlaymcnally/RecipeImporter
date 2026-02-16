from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_UNKNOWN_KEY_WARNINGS: set[tuple[str, ...]] = set()
_UI_REQUIRED_KEYS = ("ui_group", "ui_label", "ui_order")
_SUMMARY_ORDER = (
    "epub_extractor",
    "ocr_device",
    "ocr_batch_size",
    "workers",
    "effective_workers",
    "pdf_split_workers",
    "epub_split_workers",
    "pdf_pages_per_job",
    "epub_spine_items_per_job",
    "warm_models",
    "mapping_path",
    "overrides_path",
)


class EpubExtractor(str, Enum):
    unstructured = "unstructured"
    legacy = "legacy"


class OcrDevice(str, Enum):
    auto = "auto"
    cpu = "cpu"
    cuda = "cuda"
    mps = "mps"


def _ui_meta(
    *,
    group: str,
    label: str,
    order: int,
    description: str,
    step: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "ui_group": group,
        "ui_label": label,
        "ui_order": order,
        "ui_description": description,
    }
    if step is not None:
        meta["ui_step"] = step
    if minimum is not None:
        meta["ui_min"] = minimum
    if maximum is not None:
        meta["ui_max"] = maximum
    return meta


class RunSettings(BaseModel):
    """Canonical per-run pipeline settings used by UI + reports + analytics."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    workers: int = Field(
        default=7,
        ge=1,
        le=128,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="Workers",
            order=10,
            description="Max parallel worker processes for this run.",
            step=1,
            minimum=1,
            maximum=128,
        ),
    )
    pdf_split_workers: int = Field(
        default=7,
        ge=1,
        le=128,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="PDF Split Workers",
            order=20,
            description="Max workers used while splitting one PDF run.",
            step=1,
            minimum=1,
            maximum=128,
        ),
    )
    epub_split_workers: int = Field(
        default=7,
        ge=1,
        le=128,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="EPUB Split Workers",
            order=30,
            description="Max workers used while splitting one EPUB run.",
            step=1,
            minimum=1,
            maximum=128,
        ),
    )
    pdf_pages_per_job: int = Field(
        default=50,
        ge=1,
        le=2000,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="PDF Pages / Job",
            order=40,
            description="Target page count per split PDF worker job.",
            step=5,
            minimum=1,
            maximum=2000,
        ),
    )
    epub_spine_items_per_job: int = Field(
        default=10,
        ge=1,
        le=2000,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="EPUB Spine Items / Job",
            order=50,
            description="Target spine-item count per split EPUB worker job.",
            step=1,
            minimum=1,
            maximum=2000,
        ),
    )
    epub_extractor: EpubExtractor = Field(
        default=EpubExtractor.unstructured,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="EPUB Extractor",
            order=60,
            description="EPUB extraction engine (unstructured or legacy).",
        ),
    )
    ocr_device: OcrDevice = Field(
        default=OcrDevice.auto,
        json_schema_extra=_ui_meta(
            group="OCR",
            label="OCR Device",
            order=70,
            description="OCR device selection for PDF processing.",
        ),
    )
    ocr_batch_size: int = Field(
        default=1,
        ge=1,
        le=256,
        json_schema_extra=_ui_meta(
            group="OCR",
            label="OCR Batch Size",
            order=80,
            description="Number of pages per OCR model batch.",
            step=1,
            minimum=1,
            maximum=256,
        ),
    )
    warm_models: bool = Field(
        default=False,
        json_schema_extra=_ui_meta(
            group="Advanced",
            label="Warm Models",
            order=90,
            description="Preload heavy OCR/parsing models before processing.",
        ),
    )
    # Derived from workload shape; not directly edited in the run settings UI.
    effective_workers: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra={"ui_hidden": True},
    )
    mapping_path: str | None = Field(default=None, json_schema_extra={"ui_hidden": True})
    overrides_path: str | None = Field(default=None, json_schema_extra={"ui_hidden": True})

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        warn_context: str = "run settings",
    ) -> "RunSettings":
        if payload is None:
            return cls()
        data = dict(payload)
        unknown = tuple(sorted(set(data) - set(cls.model_fields)))
        if unknown and unknown not in _UNKNOWN_KEY_WARNINGS:
            logger.warning(
                "Ignoring unknown %s keys: %s",
                warn_context,
                ", ".join(unknown),
            )
            _UNKNOWN_KEY_WARNINGS.add(unknown)
        return cls.model_validate(data)

    def to_run_config_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)

    def summary(self) -> str:
        payload = self.to_run_config_dict()
        parts: list[str] = []
        for key in _SUMMARY_ORDER:
            if key not in payload:
                continue
            value = payload[key]
            if key.endswith("_path"):
                value = Path(str(value)).name
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            else:
                rendered = str(value)
            parts.append(f"{key}={rendered}")
        return " | ".join(parts)

    def stable_hash(self) -> str:
        canonical_json = json.dumps(
            self.to_run_config_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def short_hash(self, length: int = 12) -> str:
        return self.stable_hash()[:length]


@dataclass(frozen=True)
class RunSettingUiSpec:
    name: str
    label: str
    group: str
    order: int
    description: str
    value_kind: Literal["enum", "bool", "int", "string"]
    choices: tuple[str, ...] = ()
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


def _value_kind_for_annotation(annotation: Any) -> Literal["enum", "bool", "int", "string"]:
    unwrapped = _unwrap_optional(annotation)
    if isinstance(unwrapped, type) and issubclass(unwrapped, Enum):
        return "enum"
    if unwrapped is bool:
        return "bool"
    if unwrapped is int:
        return "int"
    return "string"


def run_settings_ui_specs() -> list[RunSettingUiSpec]:
    specs: list[RunSettingUiSpec] = []
    for field_name, field in RunSettings.model_fields.items():
        extra = dict(field.json_schema_extra or {})
        if extra.get("ui_hidden"):
            continue
        for key in _UI_REQUIRED_KEYS:
            if key not in extra:
                raise ValueError(f"RunSettings.{field_name} missing UI metadata key: {key}")

        value_kind = _value_kind_for_annotation(field.annotation)
        choices: tuple[str, ...] = ()
        annotation = _unwrap_optional(field.annotation)
        if value_kind == "enum" and isinstance(annotation, type) and issubclass(annotation, Enum):
            choices = tuple(str(member.value) for member in annotation)

        specs.append(
            RunSettingUiSpec(
                name=field_name,
                label=str(extra["ui_label"]),
                group=str(extra["ui_group"]),
                order=int(extra["ui_order"]),
                description=str(extra.get("ui_description", "")).strip(),
                value_kind=value_kind,
                choices=choices,
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


def compute_effective_workers(
    *,
    workers: int,
    epub_split_workers: int,
    file_paths: Sequence[Path] | None = None,
    all_epub: bool | None = None,
) -> int:
    effective_all_epub = bool(all_epub)
    if all_epub is None and file_paths is not None:
        effective_all_epub = bool(file_paths) and all(
            path.suffix.lower() == ".epub" for path in file_paths
        )
    if effective_all_epub and epub_split_workers > workers:
        return epub_split_workers
    return workers


def build_run_settings(
    *,
    workers: int,
    pdf_split_workers: int,
    epub_split_workers: int,
    pdf_pages_per_job: int,
    epub_spine_items_per_job: int,
    epub_extractor: str | EpubExtractor,
    ocr_device: str | OcrDevice,
    ocr_batch_size: int,
    warm_models: bool,
    mapping_path: Path | None = None,
    overrides_path: Path | None = None,
    file_paths: Sequence[Path] | None = None,
    all_epub: bool | None = None,
    effective_workers: int | None = None,
) -> RunSettings:
    resolved_effective_workers = effective_workers
    if resolved_effective_workers is None:
        resolved_effective_workers = compute_effective_workers(
            workers=workers,
            epub_split_workers=epub_split_workers,
            file_paths=file_paths,
            all_epub=all_epub,
        )
    return RunSettings.model_validate(
        {
            "workers": workers,
            "pdf_split_workers": pdf_split_workers,
            "epub_split_workers": epub_split_workers,
            "pdf_pages_per_job": pdf_pages_per_job,
            "epub_spine_items_per_job": epub_spine_items_per_job,
            "epub_extractor": str(epub_extractor).strip().lower(),
            "ocr_device": str(ocr_device).strip().lower(),
            "ocr_batch_size": ocr_batch_size,
            "warm_models": bool(warm_models),
            "effective_workers": resolved_effective_workers,
            "mapping_path": str(mapping_path) if mapping_path is not None else None,
            "overrides_path": str(overrides_path) if overrides_path is not None else None,
        }
    )
