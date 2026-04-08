from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate

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
_PRE_GROUPING_LINE_ROLE_RULE_TAGS_TO_STRIP = frozenset(
    {"outside_recipe_span", "recipe_span_fallback"}
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


def sanitize_pre_grouping_line_role_candidates(
    candidates: Sequence[AtomicLineCandidate],
) -> list[AtomicLineCandidate]:
    sanitized: list[AtomicLineCandidate] = []
    for candidate in candidates:
        kept_rule_tags = [
            str(tag)
            for tag in candidate.rule_tags
            if str(tag or "").strip()
            and str(tag).strip() not in _PRE_GROUPING_LINE_ROLE_RULE_TAGS_TO_STRIP
        ]
        sanitized.append(
            candidate.model_copy(
                update={
                    "recipe_id": None,
                    "within_recipe_span": None,
                    "rule_tags": kept_rule_tags,
                }
            )
        )
    return sanitized


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

    @model_validator(mode="after")
    def _normalize_metadata(self) -> "CanonicalLineRolePrediction":
        self.escalation_reasons = _unique_string_list(self.escalation_reasons)
        self.reason_tags = _unique_string_list(self.reason_tags)
        return self
