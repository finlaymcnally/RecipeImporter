from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_BUNDLE_VERSION_V2: Literal["2"] = "2"
ALLOWED_KNOWLEDGE_FINAL_CATEGORIES: tuple[str, ...] = ("knowledge", "other")
ALLOWED_KNOWLEDGE_REVIEWER_CATEGORIES: tuple[str, ...] = (
    "knowledge",
    "chapter_taxonomy",
    "decorative_heading",
    "front_matter",
    "toc_navigation",
    "endorsement_or_marketing",
    "memoir_or_scene_setting",
    "reference_back_matter",
    "other",
)
ALLOWED_KNOWLEDGE_REASON_CODES: tuple[str, ...] = (
    "technique_or_mechanism",
    "diagnostic_or_troubleshooting",
    "reference_or_definition",
    "substitution_storage_or_safety",
    "book_framing_or_marketing",
    "memoir_or_scene_setting",
    "navigation_or_chapter_taxonomy",
    "decorative_heading_only",
    "true_but_low_utility",
    "not_cooking_knowledge",
    "review_not_completed",
    "strong_cue_review_required",
)
_REASON_CODE_ALIASES: dict[str, str] = {
    "grounded_useful": "technique_or_mechanism",
    "all_other": "not_cooking_knowledge",
}
_USEFUL_REASON_CODES = frozenset(
    {
        "technique_or_mechanism",
        "diagnostic_or_troubleshooting",
        "reference_or_definition",
        "substitution_storage_or_safety",
    }
)
_NON_USEFUL_REASON_CODES = frozenset(
    {
        "book_framing_or_marketing",
        "memoir_or_scene_setting",
        "navigation_or_chapter_taxonomy",
        "decorative_heading_only",
        "true_but_low_utility",
        "not_cooking_knowledge",
        "review_not_completed",
        "strong_cue_review_required",
    }
)


def normalize_knowledge_reason_code(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return _REASON_CODE_ALIASES.get(cleaned, cleaned)


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

    body: str = Field(alias="b")
    evidence: list[EvidencePointerV1] = Field(default_factory=list, alias="e")

    @field_validator("body", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()

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

    @model_validator(mode="after")
    def _validate_usefulness_consistency(self) -> "KnowledgeChunkResultV2":
        has_knowledge_decision = any(
            decision.category == "knowledge" for decision in self.block_decisions
        )
        has_snippets = bool(self.snippets)
        if self.is_useful:
            if not has_knowledge_decision:
                raise ValueError(
                    "useful chunk results must include at least one knowledge block decision."
                )
            if not has_snippets:
                raise ValueError("useful chunk results must include at least one snippet.")
            return self
        if has_knowledge_decision:
            raise ValueError(
                "non-useful chunk results must not include knowledge block decisions."
            )
        if has_snippets:
            raise ValueError("non-useful chunk results must not include snippets.")
        return self


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


class KnowledgeSemanticEvidenceV1(BaseModel):
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


class KnowledgeSemanticSnippetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str
    evidence: list[KnowledgeSemanticEvidenceV1] = Field(default_factory=list)

    @field_validator("body", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()

    @field_validator("evidence")
    @classmethod
    def _require_evidence(
        cls, value: list[KnowledgeSemanticEvidenceV1]
    ) -> list[KnowledgeSemanticEvidenceV1]:
        if not value:
            raise ValueError("Snippet evidence must be non-empty.")
        return value


class KnowledgeSemanticBlockDecisionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_index: int
    category: Literal["knowledge", "other"]
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
    ] | None = None

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: object) -> object:
        return int(value)

    @model_validator(mode="after")
    def _validate_reviewer_category(self) -> "KnowledgeSemanticBlockDecisionV1":
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


class KnowledgeSemanticChunkResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    is_useful: bool
    block_decisions: list[KnowledgeSemanticBlockDecisionV1] = Field(default_factory=list)
    snippets: list[KnowledgeSemanticSnippetV1] = Field(default_factory=list)
    reason_code: str | None = None

    @field_validator("chunk_id", mode="before")
    @classmethod
    def _normalize_chunk_id(cls, value: object) -> object:
        return str(value).strip()

    @field_validator("reason_code", mode="before")
    @classmethod
    def _normalize_reason_code(cls, value: object) -> object:
        return normalize_knowledge_reason_code(value)

    @field_validator("block_decisions")
    @classmethod
    def _require_unique_block_indices(
        cls, value: list[KnowledgeSemanticBlockDecisionV1]
    ) -> list[KnowledgeSemanticBlockDecisionV1]:
        seen: set[int] = set()
        for decision in value:
            if decision.block_index in seen:
                raise ValueError(
                    "block_decisions must not repeat block_index "
                    f"{decision.block_index}."
                )
            seen.add(decision.block_index)
        return value

    @model_validator(mode="after")
    def _validate_usefulness_consistency(self) -> "KnowledgeSemanticChunkResultV1":
        has_knowledge_decision = any(
            decision.category == "knowledge" for decision in self.block_decisions
        )
        has_snippets = bool(self.snippets)
        if self.reason_code is None:
            raise ValueError("chunk results must include a utility-focused reason_code.")
        if self.reason_code not in ALLOWED_KNOWLEDGE_REASON_CODES:
            raise ValueError(
                "reason_code must be one of "
                + ", ".join(repr(code) for code in ALLOWED_KNOWLEDGE_REASON_CODES)
                + f"; got {self.reason_code!r}."
            )
        if self.is_useful:
            if not has_knowledge_decision:
                raise ValueError(
                    "useful chunk results must include at least one knowledge block decision."
                )
            if not has_snippets:
                raise ValueError("useful chunk results must include at least one snippet.")
            if self.reason_code not in _USEFUL_REASON_CODES:
                raise ValueError(
                    "useful chunk reason_code must describe durable cooking leverage."
                )
            return self
        if has_knowledge_decision:
            raise ValueError(
                "non-useful chunk results must not include knowledge block decisions."
            )
        if has_snippets:
            raise ValueError("non-useful chunk results must not include snippets.")
        if self.reason_code not in _NON_USEFUL_REASON_CODES:
            raise ValueError(
                "non-useful chunk reason_code must describe why the chunk is not worth keeping."
            )
        return self


class KnowledgePacketSemanticResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    chunk_results: list[KnowledgeSemanticChunkResultV1] = Field(default_factory=list)

    @field_validator("packet_id", mode="before")
    @classmethod
    def _normalize_packet_id(cls, value: object) -> object:
        return str(value).strip()

    @field_validator("chunk_results")
    @classmethod
    def _require_unique_chunk_ids(
        cls, value: list[KnowledgeSemanticChunkResultV1]
    ) -> list[KnowledgeSemanticChunkResultV1]:
        seen: set[str] = set()
        for result in value:
            if result.chunk_id in seen:
                raise ValueError(
                    "chunk_results must not repeat chunk_id "
                    f"{result.chunk_id!r}."
                )
            seen.add(result.chunk_id)
        return value


def serialize_canonical_knowledge_packet(
    result: KnowledgePacketSemanticResultV1,
) -> dict[str, object]:
    return {
        "v": _BUNDLE_VERSION_V2,
        "bid": result.packet_id,
        "r": [
            {
                "cid": chunk_result.chunk_id,
                "u": chunk_result.is_useful,
                "d": [
                    {
                        "i": decision.block_index,
                        "c": decision.category,
                        "rc": decision.reviewer_category,
                    }
                    for decision in chunk_result.block_decisions
                ],
                "s": [
                    {
                        "b": snippet.body,
                        "e": [
                            {
                                "i": evidence.block_index,
                                "q": evidence.quote,
                            }
                            for evidence in snippet.evidence
                        ],
                    }
                    for snippet in chunk_result.snippets
                ],
            }
            for chunk_result in result.chunk_results
        ],
    }


def semantic_result_from_canonical_bundle(
    bundle: KnowledgeBundleOutputV2,
) -> KnowledgePacketSemanticResultV1:
    return KnowledgePacketSemanticResultV1.model_validate(
        {
            "packet_id": bundle.bundle_id,
            "chunk_results": [
                {
                    "chunk_id": result.chunk_id,
                    "is_useful": result.is_useful,
                    "block_decisions": [
                        {
                            "block_index": decision.block_index,
                            "category": decision.category,
                            "reviewer_category": decision.reviewer_category,
                        }
                        for decision in result.block_decisions
                    ],
                    "snippets": [
                        {
                            "body": snippet.body,
                            "evidence": [
                                {
                                    "block_index": evidence.block_index,
                                    "quote": evidence.quote,
                                }
                                for evidence in snippet.evidence
                            ],
                        }
                        for snippet in result.snippets
                    ],
                }
                for result in bundle.chunk_results
            ],
        }
    )
