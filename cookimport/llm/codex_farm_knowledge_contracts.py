from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

_BUNDLE_VERSION_V2: Literal["2"] = "2"


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
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    table_id: str = Field(alias="id")
    caption: str | None = Field(default=None, alias="c")
    row_index_in_table: int | None = Field(default=None, alias="r")


class KnowledgeCompactChunkBlockV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    block_index: int = Field(alias="i")
    text: str = Field(alias="t")
    heading_level: int | None = Field(default=None, alias="hl")
    table_hint: KnowledgeCompactTableHintV1 | None = Field(default=None, alias="th")

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: Any) -> Any:
        return int(value)


class KnowledgeCompactContextBlockV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    block_index: int = Field(alias="i")
    text: str = Field(alias="t")
    heading_level: int | None = Field(default=None, alias="hl")

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: Any) -> Any:
        return int(value)


class KnowledgeCompactChunkHintsV2(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    suggested_lane: Literal["knowledge"] | None = Field(default=None, alias="l")
    text_form: Literal["heading_like", "prose_like", "mixed", "table_like"] | None = Field(
        default=None,
        alias="f",
    )


class KnowledgeCompactBundleChunkPayloadV2(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    chunk_id: str = Field(alias="cid")
    blocks: list[KnowledgeCompactChunkBlockV1] = Field(default_factory=list, alias="b")
    hints: KnowledgeCompactChunkHintsV2 | None = Field(default=None, alias="h")


class KnowledgeCompactContextPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    blocks_before: list[KnowledgeCompactContextBlockV1] = Field(default_factory=list, alias="p")
    blocks_after: list[KnowledgeCompactContextBlockV1] = Field(default_factory=list, alias="n")


class KnowledgeCompactGuardrailsPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    context_recipe_block_indices: list[int] = Field(default_factory=list, alias="r")

    @field_validator("context_recipe_block_indices", mode="before")
    @classmethod
    def _coerce_context_recipe_block_indices(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return [int(item) for item in value]
        return value


class KnowledgeCompactBundleJobInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    bundle_version: Literal["2"] = Field(default=_BUNDLE_VERSION_V2, alias="v")
    bundle_id: str = Field(alias="bid")
    chunks: list[KnowledgeCompactBundleChunkPayloadV2] = Field(default_factory=list, alias="c")
    context: KnowledgeCompactContextPayloadV1 | None = Field(default=None, alias="x")
    guardrails: KnowledgeCompactGuardrailsPayloadV1 | None = Field(default=None, alias="g")


def knowledge_input_bundle_id(payload: Mapping[str, Any] | None) -> str:
    data = payload or {}
    return str(data.get("bid") or data.get("bundle_id") or "").strip()


def knowledge_input_chunks(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    data = payload or {}
    chunks = data.get("c")
    if not isinstance(chunks, list):
        chunks = data.get("chunks")
    return [dict(item) for item in chunks if isinstance(item, dict)] if isinstance(chunks, list) else []


def knowledge_input_chunk_id(chunk_payload: Mapping[str, Any] | None) -> str:
    data = chunk_payload or {}
    return str(data.get("cid") or data.get("chunk_id") or "").strip()


def knowledge_input_blocks(chunk_payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    data = chunk_payload or {}
    blocks = data.get("b")
    if not isinstance(blocks, list):
        blocks = data.get("blocks")
    return [dict(item) for item in blocks if isinstance(item, dict)] if isinstance(blocks, list) else []


def knowledge_input_block_index(block_payload: Mapping[str, Any] | None) -> int | None:
    data = block_payload or {}
    value = data.get("i", data.get("block_index"))
    if value is None:
        return None
    return int(value)


def knowledge_input_block_text(block_payload: Mapping[str, Any] | None) -> str:
    data = block_payload or {}
    return str(data.get("t", data.get("text")) or "")
