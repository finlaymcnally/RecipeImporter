from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_BUNDLE_VERSION_V2: Literal["2"] = "2"


class EvidencePointerV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    block_index: int = Field(alias="i")
    quote: str = Field(alias="q")

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
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    title: str | None = Field(default=None, alias="t")
    body: str = Field(alias="b")
    tags: list[str] = Field(default_factory=list, alias="g")
    evidence: list[EvidencePointerV1] = Field(default_factory=list, alias="e")

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


class KnowledgeBlockDecisionV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    block_index: int = Field(alias="i")
    category: Literal["knowledge", "other"] = Field(alias="c")
    reviewer_category: Literal[
        "knowledge",
        "chapter_taxonomy",
        "decorative_heading",
        "front_matter",
        "toc_navigation",
        "endorsement_or_marketing",
        "memoir_or_scene_setting",
        "reference_back_matter",
        "other",
    ] | None = Field(default=None, alias="rc")

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: object) -> object:
        return int(value)

    @model_validator(mode="after")
    def _validate_reviewer_category(self) -> "KnowledgeBlockDecisionV1":
        if self.reviewer_category is None:
            self.reviewer_category = "knowledge" if self.category == "knowledge" else "other"
            return self
        if self.category == "knowledge" and self.reviewer_category != "knowledge":
            raise ValueError(
                "reviewer_category must be 'knowledge' when final category is 'knowledge'."
            )
        if self.category == "other" and self.reviewer_category == "knowledge":
            raise ValueError(
                "reviewer_category 'knowledge' is invalid when final category is 'other'."
            )
        return self


class KnowledgeChunkResultV2(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    chunk_id: str = Field(alias="cid")
    is_useful: bool = Field(alias="u")
    block_decisions: list[KnowledgeBlockDecisionV1] = Field(default_factory=list, alias="d")
    snippets: list[KnowledgeSnippetV1] = Field(default_factory=list, alias="s")

    @field_validator("chunk_id", mode="before")
    @classmethod
    def _normalize_chunk_id(cls, value: object) -> object:
        return str(value).strip()

    @field_validator("block_decisions")
    @classmethod
    def _require_unique_block_indices(
        cls, value: list[KnowledgeBlockDecisionV1]
    ) -> list[KnowledgeBlockDecisionV1]:
        seen: set[int] = set()
        for decision in value:
            if decision.block_index in seen:
                raise ValueError(
                    "block_decisions must not repeat block_index "
                    f"{decision.block_index}."
                )
            seen.add(decision.block_index)
        return value


class KnowledgeBundleOutputV2(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    bundle_version: Literal["2"] = Field(default=_BUNDLE_VERSION_V2, alias="v")
    bundle_id: str = Field(alias="bid")
    chunk_results: list[KnowledgeChunkResultV2] = Field(default_factory=list, alias="r")

    @field_validator("bundle_id", mode="before")
    @classmethod
    def _normalize_bundle_id(cls, value: object) -> object:
        return str(value).strip()

    @field_validator("chunk_results")
    @classmethod
    def _require_unique_chunk_ids(
        cls, value: list[KnowledgeChunkResultV2]
    ) -> list[KnowledgeChunkResultV2]:
        seen: set[str] = set()
        for result in value:
            if result.chunk_id in seen:
                raise ValueError(
                    "chunk_results must not repeat chunk_id "
                    f"{result.chunk_id!r}."
                )
            seen.add(result.chunk_id)
        return value
