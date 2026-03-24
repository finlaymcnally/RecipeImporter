from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

_REVIEW_EXCLUSION_REASON_CODES = frozenset(
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


def _normalize_review_exclusion_reason(value: Any) -> str | None:
    rendered = str(value or "").strip().lower()
    if not rendered:
        return None
    if rendered not in _REVIEW_EXCLUSION_REASON_CODES:
        raise ValueError(f"unknown review exclusion reason: {rendered}")
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
    review_exclusion_reason: str | None = None

    @model_validator(mode="after")
    def _normalize_metadata(self) -> "CanonicalLineRolePrediction":
        self.escalation_reasons = _unique_string_list(self.escalation_reasons)
        self.reason_tags = _unique_string_list(self.reason_tags)
        self.review_exclusion_reason = _normalize_review_exclusion_reason(
            self.review_exclusion_reason
        )
        return self
