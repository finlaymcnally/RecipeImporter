from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

RECIPE_LOCAL_LINE_ROLE_LABELS: tuple[str, ...] = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
)
NONRECIPE_ROUTE_LABELS: tuple[str, ...] = (
    "NONRECIPE_CANDIDATE",
    "NONRECIPE_EXCLUDE",
)
CANONICAL_LINE_ROLE_ALLOWED_LABELS: tuple[str, ...] = (
    *RECIPE_LOCAL_LINE_ROLE_LABELS,
    *NONRECIPE_ROUTE_LABELS,
)

_EXCLUSION_REASON_CODES = frozenset(
    {
        "navigation",
        "front_matter",
        "publishing_metadata",
        "copyright_legal",
        "endorsement",
        "publisher_promo",
        "page_furniture",
    }
)


def _unique_string_list(values: Sequence[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        rendered = str(value or "").strip()
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        output.append(rendered)
    return output


def _normalize_exclusion_reason(value: Any) -> str | None:
    rendered = str(value or "").strip().lower()
    if not rendered:
        return None
    if rendered not in _EXCLUSION_REASON_CODES:
        raise ValueError(f"unknown exclusion reason: {rendered}")
    return rendered


class CanonicalLineRolePrediction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recipe_id: str | None = None
    block_id: str
    block_index: int | None = None
    atomic_index: int
    text: str
    within_recipe_span: bool | None = None
    label: str
    decided_by: Literal["rule", "codex", "fallback"]
    reason_tags: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def _normalize_metadata(self) -> "CanonicalLineRolePrediction":
        self.escalation_reasons = _unique_string_list(self.escalation_reasons)
        self.reason_tags = _unique_string_list(self.reason_tags)
        self.exclusion_reason = _normalize_exclusion_reason(self.exclusion_reason)
        return self
