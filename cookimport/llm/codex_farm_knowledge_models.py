from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_BUNDLE_VERSION_V3: Literal["3"] = "3"
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


class KnowledgeProposedTagV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    key: str = Field(alias="k")
    display_name: str = Field(alias="d")
    category_key: str = Field(alias="ck")

    @field_validator("key", "display_name", "category_key", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()


class KnowledgeGroundingV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    tag_keys: list[str] = Field(default_factory=list, alias="tk")
    category_keys: list[str] = Field(default_factory=list, alias="ck")
    proposed_tags: list[KnowledgeProposedTagV1] = Field(default_factory=list, alias="pt")

    @field_validator("tag_keys", "category_keys", mode="before")
    @classmethod
    def _coerce_key_list(cls, value: object) -> object:
        if value is None:
            return []
        return [str(item).strip() for item in value]

    @field_validator("tag_keys", "category_keys")
    @classmethod
    def _require_unique_keys(cls, value: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not item or item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped


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
    retrieval_concept: str | None = Field(default=None, alias="rt")
    grounding: KnowledgeGroundingV1 = Field(default_factory=KnowledgeGroundingV1, alias="gr")

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: object) -> object:
        return int(value)

    @field_validator("retrieval_concept", mode="before")
    @classmethod
    def _normalize_retrieval_concept(cls, value: object) -> object:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_reviewer_category(self) -> "KnowledgeBlockDecisionV1":
        if self.reviewer_category is None:
            self.reviewer_category = "knowledge" if self.category == "knowledge" else "other"
        if self.category == "knowledge" and self.reviewer_category != "knowledge":
            raise ValueError(
                "reviewer_category must be 'knowledge' when final category is 'knowledge'."
            )
        if self.category == "other" and self.reviewer_category == "knowledge":
            raise ValueError(
                "reviewer_category 'knowledge' is invalid when final category is 'other'."
            )
        if self.category == "knowledge":
            if self.retrieval_concept is None:
                raise ValueError("knowledge rows must include retrieval_concept.")
            if not self.grounding.tag_keys and not self.grounding.proposed_tags:
                raise ValueError(
                    "knowledge rows must include grounding tag_keys or proposed_tags."
                )
        else:
            if self.retrieval_concept is not None:
                raise ValueError("other rows must not include retrieval_concept.")
            if (
                self.grounding.tag_keys
                or self.grounding.category_keys
                or self.grounding.proposed_tags
            ):
                raise ValueError("other rows must not include grounding metadata.")
        return self


class KnowledgeIdeaGroupV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    group_id: str = Field(alias="gid")
    topic_label: str = Field(alias="l")
    block_indices: list[int] = Field(default_factory=list, alias="bi")
    snippets: list[KnowledgeSnippetV1] = Field(default_factory=list, alias="s")

    @field_validator("group_id", "topic_label", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()

    @field_validator("block_indices", mode="before")
    @classmethod
    def _coerce_block_indices(cls, value: object) -> object:
        if value is None:
            return []
        return [int(item) for item in value]

    @field_validator("block_indices")
    @classmethod
    def _require_unique_block_indices(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("idea_groups must include at least one block index.")
        if len(set(value)) != len(value):
            raise ValueError("idea_groups must not repeat block indices.")
        return value

class KnowledgeBundleOutputV2(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    bundle_version: Literal["3"] = Field(default=_BUNDLE_VERSION_V3, alias="v")
    bundle_id: str = Field(alias="bid")
    block_decisions: list[KnowledgeBlockDecisionV1] = Field(default_factory=list, alias="d")
    idea_groups: list[KnowledgeIdeaGroupV1] = Field(default_factory=list, alias="g")

    @field_validator("bundle_id", mode="before")
    @classmethod
    def _normalize_bundle_id(cls, value: object) -> object:
        return str(value).strip()

    @field_validator("block_decisions")
    @classmethod
    def _require_unique_block_decisions(
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

    @field_validator("idea_groups")
    @classmethod
    def _require_unique_group_ids(
        cls, value: list[KnowledgeIdeaGroupV1]
    ) -> list[KnowledgeIdeaGroupV1]:
        seen: set[str] = set()
        for group in value:
            if group.group_id in seen:
                raise ValueError(f"idea_groups must not repeat group_id {group.group_id!r}.")
            seen.add(group.group_id)
        return value

    @property
    def is_useful(self) -> bool:
        return bool(self.idea_groups)

    @property
    def snippets(self) -> list[KnowledgeSnippetV1]:
        return [
            snippet
            for group in self.idea_groups
            for snippet in group.snippets
        ]

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


class KnowledgeSemanticProposedTagV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    display_name: str
    category_key: str

    @field_validator("key", "display_name", "category_key", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()


class KnowledgeSemanticGroundingV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_keys: list[str] = Field(default_factory=list)
    category_keys: list[str] = Field(default_factory=list)
    proposed_tags: list[KnowledgeSemanticProposedTagV1] = Field(default_factory=list)

    @field_validator("tag_keys", "category_keys", mode="before")
    @classmethod
    def _coerce_key_list(cls, value: object) -> object:
        if value is None:
            return []
        return [str(item).strip() for item in value]

    @field_validator("tag_keys", "category_keys")
    @classmethod
    def _require_unique_keys(cls, value: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not item or item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped


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
    retrieval_concept: str | None = None
    grounding: KnowledgeSemanticGroundingV1 = Field(default_factory=KnowledgeSemanticGroundingV1)

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: object) -> object:
        return int(value)

    @field_validator("retrieval_concept", mode="before")
    @classmethod
    def _normalize_retrieval_concept(cls, value: object) -> object:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_reviewer_category(self) -> "KnowledgeSemanticBlockDecisionV1":
        if self.reviewer_category is None:
            self.reviewer_category = "knowledge" if self.category == "knowledge" else "other"
        if self.category == "knowledge" and self.reviewer_category != "knowledge":
            raise ValueError(
                "reviewer_category must be 'knowledge' when final category is 'knowledge'."
            )
        if self.category == "other" and self.reviewer_category == "knowledge":
            raise ValueError(
                "reviewer_category 'knowledge' is invalid when final category is 'other'."
            )
        if self.category == "knowledge":
            if self.retrieval_concept is None:
                raise ValueError("knowledge rows must include retrieval_concept.")
            if not self.grounding.tag_keys and not self.grounding.proposed_tags:
                raise ValueError(
                    "knowledge rows must include grounding tag_keys or proposed_tags."
                )
        else:
            if self.retrieval_concept is not None:
                raise ValueError("other rows must not include retrieval_concept.")
            if (
                self.grounding.tag_keys
                or self.grounding.category_keys
                or self.grounding.proposed_tags
            ):
                raise ValueError("other rows must not include grounding metadata.")
        return self


class KnowledgeSemanticIdeaGroupV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    topic_label: str
    block_indices: list[int] = Field(default_factory=list)
    snippets: list[KnowledgeSemanticSnippetV1] = Field(default_factory=list)

    @field_validator("group_id", "topic_label", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()

    @field_validator("block_indices", mode="before")
    @classmethod
    def _coerce_block_indices(cls, value: object) -> object:
        if value is None:
            return []
        return [int(item) for item in value]


class KnowledgePacketSemanticResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    block_decisions: list[KnowledgeSemanticBlockDecisionV1] = Field(default_factory=list)
    idea_groups: list[KnowledgeSemanticIdeaGroupV1] = Field(default_factory=list)

    @field_validator("packet_id", mode="before")
    @classmethod
    def _normalize_packet_id(cls, value: object) -> object:
        return str(value).strip()


def serialize_canonical_knowledge_packet(
    result: KnowledgePacketSemanticResultV1,
) -> dict[str, object]:
    return {
        "v": _BUNDLE_VERSION_V3,
        "bid": result.packet_id,
        "d": [
            {
                "i": decision.block_index,
                "c": decision.category,
                "rc": decision.reviewer_category,
                "rt": decision.retrieval_concept,
                "gr": {
                    "tk": list(decision.grounding.tag_keys),
                    "ck": list(decision.grounding.category_keys),
                    "pt": [
                        {
                            "k": tag.key,
                            "d": tag.display_name,
                            "ck": tag.category_key,
                        }
                        for tag in decision.grounding.proposed_tags
                    ],
                },
            }
            for decision in result.block_decisions
        ],
        "g": [
            {
                "gid": group.group_id,
                "l": group.topic_label,
                "bi": list(group.block_indices),
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
                    for snippet in group.snippets
                ],
            }
            for group in result.idea_groups
        ],
    }
