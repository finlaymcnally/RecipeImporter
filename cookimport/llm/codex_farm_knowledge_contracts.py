from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_BUNDLE_VERSION: Literal["1"] = "1"
_JOB_VERSION: Literal["recipe.knowledge.job.v1"] = "recipe.knowledge.job.v1"


class SpanV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int
    end: int

    @field_validator("start", "end", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> Any:
        if value is None:
            return value
        return int(value)


class KnowledgeBlockV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_index: int
    block_id: str | None = None
    text: str
    page: int | None = None
    spine_index: int | None = None
    heading_level: int | None = None
    features_subset: dict[str, Any] = Field(default_factory=dict)

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: Any) -> Any:
        return int(value)


class KnowledgeChunkPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    block_start_index: int
    block_end_index: int
    blocks: list[KnowledgeBlockV1] = Field(default_factory=list)


class KnowledgeContextPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks_before: list[KnowledgeBlockV1] = Field(default_factory=list)
    blocks_after: list[KnowledgeBlockV1] = Field(default_factory=list)


class KnowledgeHeuristicsPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_lane: str | None = None
    suggested_highlights: list[str] = Field(default_factory=list)
    suggested_skip_reason: str | None = None


class KnowledgeGuardrailsPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_spans: list[SpanV1] = Field(default_factory=list)
    must_use_evidence: bool = True


class KnowledgeJobSourceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workbook_slug: str
    source_hash: str


class Pass4KnowledgeJobInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    job_version: Literal["recipe.knowledge.job.v1"] = _JOB_VERSION
    source: KnowledgeJobSourceV1
    chunk: KnowledgeChunkPayloadV1
    context: KnowledgeContextPayloadV1
    heuristics: KnowledgeHeuristicsPayloadV1
    guardrails: KnowledgeGuardrailsPayloadV1
