from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_BUNDLE_VERSION: Literal["1"] = "1"


class EvidencePointerV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_index: int
    quote: str

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: object) -> object:
        return int(value)

    @field_validator("quote", mode="before")
    @classmethod
    def _normalize_quote(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()


class KnowledgeSnippetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None)
    body: str
    tags: list[str] = Field(default_factory=list)
    evidence: list[EvidencePointerV1] = Field(default_factory=list)

    @field_validator("title", "body", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list):
            return [str(value)]
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("evidence")
    @classmethod
    def _require_evidence(cls, value: list[EvidencePointerV1]) -> list[EvidencePointerV1]:
        if not value:
            raise ValueError("Snippet evidence must be non-empty.")
        return value


class Pass4KnowledgeOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: Literal["1"] = _BUNDLE_VERSION
    chunk_id: str
    is_useful: bool
    snippets: list[KnowledgeSnippetV1] = Field(default_factory=list)

    @field_validator("chunk_id", mode="before")
    @classmethod
    def _normalize_chunk_id(cls, value: object) -> object:
        return str(value).strip()
