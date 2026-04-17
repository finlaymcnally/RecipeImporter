from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_BUNDLE_VERSION_V3: Literal["3"] = "3"
ALLOWED_KNOWLEDGE_CLASSIFICATION_CATEGORIES: tuple[str, ...] = (
    "keep_for_review",
    "other",
)
ALLOWED_KNOWLEDGE_FINAL_CATEGORIES: tuple[str, ...] = ("knowledge", "other")
ALLOWED_KNOWLEDGE_PROPOSAL_DECISIONS: tuple[str, ...] = (
    "not_applicable",
    "approved",
    "rejected",
)


class EvidencePointerV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    row_index: int = Field(alias="i")
    quote: str = Field(alias="q")

    @field_validator("row_index", mode="before")
    @classmethod
    def _coerce_row_index(cls, value: object) -> object:
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


class KnowledgeRowDecisionV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    row_index: int = Field(alias="i")
    category: Literal["knowledge", "other"] = Field(alias="c")
    grounding: KnowledgeGroundingV1 = Field(default_factory=KnowledgeGroundingV1, alias="gr")

    @field_validator("row_index", mode="before")
    @classmethod
    def _coerce_row_index(cls, value: object) -> object:
        return int(value)

    @model_validator(mode="after")
    def _validate_grounding(self) -> "KnowledgeRowDecisionV1":
        if self.category != "knowledge":
            if (
                self.grounding.tag_keys
                or self.grounding.category_keys
                or self.grounding.proposed_tags
            ):
                raise ValueError("other rows must not include grounding metadata.")
        return self


class KnowledgeRowGroupV1(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    group_id: str = Field(alias="gid")
    topic_label: str = Field(alias="l")
    row_indices: list[int] = Field(default_factory=list, alias="bi")
    grounding: KnowledgeGroundingV1 = Field(default_factory=KnowledgeGroundingV1, alias="gr")
    why_no_existing_tag: str | None = Field(default=None, alias="wn")
    retrieval_query: str | None = Field(default=None, alias="rq")
    snippets: list[KnowledgeSnippetV1] = Field(default_factory=list, alias="s")

    @field_validator("group_id", "topic_label", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()

    @field_validator("why_no_existing_tag", "retrieval_query", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("row_indices", mode="before")
    @classmethod
    def _coerce_row_indices(cls, value: object) -> object:
        if value is None:
            return []
        return [int(item) for item in value]

    @field_validator("row_indices")
    @classmethod
    def _require_unique_row_indices(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("row_groups must include at least one row index.")
        if len(set(value)) != len(value):
            raise ValueError("row_groups must not repeat row indices.")
        return value

    @model_validator(mode="after")
    def _validate_group_grounding(self) -> "KnowledgeRowGroupV1":
        has_existing_tags = bool(self.grounding.tag_keys)
        has_proposed_tags = bool(self.grounding.proposed_tags)
        if not has_existing_tags and not has_proposed_tags:
            raise ValueError(
                "row_groups must include at least one existing tag or proposed tag."
            )
        if has_proposed_tags and (
            not self.why_no_existing_tag or not self.retrieval_query
        ):
            raise ValueError(
                "row_groups with proposed_tags must include why_no_existing_tag and retrieval_query."
            )
        if not has_proposed_tags and (self.why_no_existing_tag or self.retrieval_query):
            raise ValueError(
                "row_groups without proposed_tags must not include proposal-only justification fields."
            )
        return self

class KnowledgeBundleOutputV2(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    bundle_version: Literal["3"] = Field(default=_BUNDLE_VERSION_V3, alias="v")
    bundle_id: str = Field(alias="bid")
    row_decisions: list[KnowledgeRowDecisionV1] = Field(default_factory=list, alias="d")
    row_groups: list[KnowledgeRowGroupV1] = Field(default_factory=list, alias="g")

    @field_validator("bundle_id", mode="before")
    @classmethod
    def _normalize_bundle_id(cls, value: object) -> object:
        return str(value).strip()

    @field_validator("row_decisions")
    @classmethod
    def _require_unique_row_decisions(
        cls, value: list[KnowledgeRowDecisionV1]
    ) -> list[KnowledgeRowDecisionV1]:
        seen: set[int] = set()
        for decision in value:
            if decision.row_index in seen:
                raise ValueError(
                    "row_decisions must not repeat row_index "
                    f"{decision.row_index}."
                )
            seen.add(decision.row_index)
        return value

    @field_validator("row_groups")
    @classmethod
    def _require_unique_group_ids(
        cls, value: list[KnowledgeRowGroupV1]
    ) -> list[KnowledgeRowGroupV1]:
        seen: set[str] = set()
        for group in value:
            if group.group_id in seen:
                raise ValueError(f"row_groups must not repeat group_id {group.group_id!r}.")
            seen.add(group.group_id)
        return value

    @property
    def is_useful(self) -> bool:
        return bool(self.row_groups)

    @property
    def snippets(self) -> list[KnowledgeSnippetV1]:
        return [
            snippet
            for group in self.row_groups
            for snippet in group.snippets
        ]

class KnowledgeSemanticEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int
    quote: str

    @field_validator("row_index", mode="before")
    @classmethod
    def _coerce_row_index(cls, value: object) -> object:
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


class KnowledgeProposalReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["not_applicable", "approved", "rejected"]
    proposed_tag: KnowledgeSemanticProposedTagV1 | None = None
    why_no_existing_tag: str | None = None
    retrieval_query: str | None = None

    @field_validator("why_no_existing_tag", "retrieval_query", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


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


class KnowledgeSemanticRowDecisionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int
    category: Literal["knowledge", "other"]
    grounding: KnowledgeSemanticGroundingV1 = Field(default_factory=KnowledgeSemanticGroundingV1)

    @field_validator("row_index", mode="before")
    @classmethod
    def _coerce_row_index(cls, value: object) -> object:
        return int(value)

    @model_validator(mode="after")
    def _validate_grounding(self) -> "KnowledgeSemanticRowDecisionV1":
        if self.category != "knowledge":
            if (
                self.grounding.tag_keys
                or self.grounding.category_keys
                or self.grounding.proposed_tags
            ):
                raise ValueError("other rows must not include grounding metadata.")
        return self


class KnowledgeSemanticRowGroupV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    topic_label: str
    row_indices: list[int] = Field(default_factory=list)
    grounding: KnowledgeSemanticGroundingV1 = Field(default_factory=KnowledgeSemanticGroundingV1)
    why_no_existing_tag: str | None = None
    retrieval_query: str | None = None
    snippets: list[KnowledgeSemanticSnippetV1] = Field(default_factory=list)

    @field_validator("group_id", "topic_label", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if value is None:
            return value
        return str(value).strip()

    @field_validator("why_no_existing_tag", "retrieval_query", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("row_indices", mode="before")
    @classmethod
    def _coerce_row_indices(cls, value: object) -> object:
        if value is None:
            return []
        return [int(item) for item in value]

    @model_validator(mode="after")
    def _validate_group_grounding(self) -> "KnowledgeSemanticRowGroupV1":
        has_existing_tags = bool(self.grounding.tag_keys)
        has_proposed_tags = bool(self.grounding.proposed_tags)
        if not has_existing_tags and not has_proposed_tags:
            raise ValueError(
                "row_groups must include at least one existing tag or proposed tag."
            )
        if has_proposed_tags and (
            not self.why_no_existing_tag or not self.retrieval_query
        ):
            raise ValueError(
                "row_groups with proposed_tags must include why_no_existing_tag and retrieval_query."
            )
        if not has_proposed_tags and (self.why_no_existing_tag or self.retrieval_query):
            raise ValueError(
                "row_groups without proposed_tags must not include proposal-only justification fields."
            )
        return self


class KnowledgePacketSemanticResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    row_decisions: list[KnowledgeSemanticRowDecisionV1] = Field(default_factory=list)
    row_groups: list[KnowledgeSemanticRowGroupV1] = Field(default_factory=list)

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
                "i": decision.row_index,
                "c": decision.category,
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
            for decision in result.row_decisions
        ],
        "g": [
            {
                "gid": group.group_id,
                "l": group.topic_label,
                "bi": list(group.row_indices),
                "gr": {
                    "tk": list(group.grounding.tag_keys),
                    "ck": list(group.grounding.category_keys),
                    "pt": [
                        {
                            "k": tag.key,
                            "d": tag.display_name,
                            "ck": tag.category_key,
                        }
                        for tag in group.grounding.proposed_tags
                    ],
                },
                "wn": group.why_no_existing_tag,
                "rq": group.retrieval_query,
                "s": [
                    {
                        "b": snippet.body,
                        "e": [
                            {
                                "i": evidence.row_index,
                                "q": evidence.quote,
                            }
                            for evidence in snippet.evidence
                        ],
                    }
                    for snippet in group.snippets
                ],
            }
            for group in result.row_groups
        ],
    }
