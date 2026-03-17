from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_BUNDLE_VERSION_V2: Literal["2"] = "2"
_JOB_VERSION_V2: Literal["recipe.knowledge.bundle_job.v2"] = "recipe.knowledge.bundle_job.v2"


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


class KnowledgeTableHintV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str
    caption: str | None = None
    markdown: str | None = None
    row_index_in_table: int | None = None


class KnowledgeCompactTableHintV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str
    caption: str | None = None
    row_index_in_table: int | None = None


class KnowledgeCompactChunkBlockV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_index: int
    text: str
    heading_level: int | None = None
    table_hint: KnowledgeCompactTableHintV1 | None = None

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: Any) -> Any:
        return int(value)


class KnowledgeCompactContextBlockV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_index: int
    text: str
    heading_level: int | None = None

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: Any) -> Any:
        return int(value)


class KnowledgeCompactBundleChunkPayloadV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    block_start_index: int
    block_end_index: int
    blocks: list[KnowledgeCompactChunkBlockV1] = Field(default_factory=list)
    heuristics: "KnowledgeHeuristicsPayloadV1" = Field(default_factory=lambda: KnowledgeHeuristicsPayloadV1())


class KnowledgeCompactContextPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks_before: list[KnowledgeCompactContextBlockV1] = Field(default_factory=list)
    blocks_after: list[KnowledgeCompactContextBlockV1] = Field(default_factory=list)


class KnowledgeHeuristicsPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_lane: str | None = None
    suggested_highlights: list[str] = Field(default_factory=list)
    suggested_skip_reason: str | None = None


class KnowledgeCompactGuardrailsPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_recipe_block_indices: list[int] = Field(default_factory=list)
    must_use_evidence: bool = True

    @field_validator("context_recipe_block_indices", mode="before")
    @classmethod
    def _coerce_context_recipe_block_indices(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return [int(item) for item in value]
        return value


class KnowledgeJobSourceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workbook_slug: str
    source_hash: str


class KnowledgeCompactBundleJobInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["2"] = _BUNDLE_VERSION_V2
    job_version: Literal["recipe.knowledge.bundle_job.v2"] = _JOB_VERSION_V2
    source: KnowledgeJobSourceV1
    bundle_id: str
    chunks: list[KnowledgeCompactBundleChunkPayloadV2] = Field(default_factory=list)
    context: KnowledgeCompactContextPayloadV1
    guardrails: KnowledgeCompactGuardrailsPayloadV1
