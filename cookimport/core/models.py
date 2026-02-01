from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_WHITESPACE_RE = re.compile(r"[ \t]+")


def _normalize_text(value: str) -> str:
    cleaned = value.replace("\u00a0", " ")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = value.splitlines()
    else:
        items = list(value)
    normalized: list[str] = []
    for item in items:
        if item is None:
            continue
        item_str = _normalize_text(str(item))
        if item_str:
            normalized.append(item_str)
    return normalized


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _normalize_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    else:
        items = list(value)
    normalized: list[str] = []
    for item in items:
        if item is None:
            continue
        item_str = _normalize_text(str(item))
        if item_str:
            normalized.append(item_str)
    return normalized


class HowToStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: str = Field(default="HowToStep", alias="@type")
    text: str
    # Extension fields for extracted instruction metadata (not in schema.org)
    time_seconds: int | None = Field(default=None, alias="timeSeconds")
    temperature: float | None = None
    temperature_unit: str | None = Field(default=None, alias="temperatureUnit")

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_text_field(cls, value: Any) -> Any:
        if value is None:
            return value
        return _normalize_text(str(value))


class RecipeComment(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: str = Field(default="Comment", alias="@type")
    name: str | None = None
    text: str | None = None

    @field_validator("name", "text", mode="before")
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> Any:
        if value is None:
            return value
        return _normalize_text(str(value))


class AggregateRating(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: str = Field(default="AggregateRating", alias="@type")
    rating_value: str | float | int | None = Field(default=None, alias="ratingValue")
    rating_count: str | int | None = Field(default=None, alias="ratingCount")

    @field_validator("rating_value", "rating_count", mode="before")
    @classmethod
    def _normalize_rating_fields(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, str):
            return _normalize_text(value)
        return value


InstructionItem = str | HowToStep


class RecipeCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    context: str | None = Field(default="http://schema.org", alias="@context")
    type: str = Field(default="Recipe", alias="@type")
    name: str
    identifier: str | None = None
    date_published: str | None = Field(default=None, alias="datePublished")
    ingredients: list[str] = Field(default_factory=list, alias="recipeIngredient")
    instructions: list[InstructionItem] = Field(
        default_factory=list, alias="recipeInstructions"
    )
    description: str | None = None
    recipe_yield: str | None = Field(default=None, alias="recipeYield")
    prep_time: str | None = Field(default=None, alias="prepTime")
    cook_time: str | None = Field(default=None, alias="cookTime")
    total_time: str | None = Field(default=None, alias="totalTime")
    tags: list[str] = Field(default_factory=list)
    image: list[str] = Field(default_factory=list)
    recipe_category: list[str] = Field(default_factory=list, alias="recipeCategory")
    recipe_cuisine: list[str] = Field(default_factory=list, alias="recipeCuisine")
    cooking_method: list[str] = Field(default_factory=list, alias="cookingMethod")
    suitable_for_diet: list[str] = Field(default_factory=list, alias="suitableForDiet")
    author: str | None = Field(default=None, alias="author")
    publisher: str | None = Field(default=None, alias="publisher")
    date_modified: str | None = Field(default=None, alias="dateModified")
    credit_text: str | None = Field(default=None, alias="creditText")
    source_url: str | None = Field(default=None, alias="sourceUrl")
    is_based_on: str | None = Field(default=None, alias="isBasedOn")
    tools: list[str] = Field(default_factory=list, alias="tool")
    supplies: list[str] = Field(default_factory=list, alias="supply")
    nutrition: dict[str, Any] | None = Field(default=None, alias="nutrition")
    video: dict[str, Any] | None = Field(default=None, alias="video")
    comments: list[RecipeComment] = Field(default_factory=list, alias="comment")
    aggregate_rating: AggregateRating | None = Field(default=None, alias="aggregateRating")
    source: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None

    @field_validator(
        "source",
        "name",
        "identifier",
        "date_published",
        "date_modified",
        "description",
        "recipe_yield",
        "prep_time",
        "cook_time",
        "total_time",
        "author",
        "publisher",
        "credit_text",
        "source_url",
        "is_based_on",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> Any:
        if value is None:
            return value
        return _normalize_text(str(value))

    @field_validator(
        "ingredients",
        "tags",
        "recipe_category",
        "recipe_cuisine",
        "cooking_method",
        "suitable_for_diet",
        "tools",
        "supplies",
        mode="before",
    )
    @classmethod
    def _normalize_list_fields(cls, value: Any) -> list[str]:
        return _normalize_list(value)

    @field_validator("instructions", mode="before")
    @classmethod
    def _normalize_instruction_fields(cls, value: Any) -> list[InstructionItem]:
        if value is None:
            return []
        if isinstance(value, str):
            items = value.splitlines()
        else:
            items = list(value)
        normalized: list[InstructionItem] = []
        for item in items:
            if item is None:
                continue
            if isinstance(item, HowToStep):
                if item.text:
                    normalized.append(item)
                continue
            if isinstance(item, dict):
                step = HowToStep.model_validate(item)
                if step.text:
                    normalized.append(step)
                continue
            item_str = _normalize_text(str(item))
            if item_str:
                normalized.append(item_str)
        return normalized

    @field_validator("image", mode="before")
    @classmethod
    def _normalize_image_fields(cls, value: Any) -> list[str]:
        return _normalize_str_list(value)

    @field_validator("comments", mode="before")
    @classmethod
    def _normalize_comment_fields(cls, value: Any) -> list[RecipeComment]:
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        if isinstance(value, str):
            return [{"text": value}]
        return list(value)


class TipTags(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    recipes: list[str] = Field(default_factory=list)
    dishes: list[str] = Field(default_factory=list)
    meats: list[str] = Field(default_factory=list)
    vegetables: list[str] = Field(default_factory=list)
    herbs: list[str] = Field(default_factory=list)
    spices: list[str] = Field(default_factory=list)
    dairy: list[str] = Field(default_factory=list)
    grains: list[str] = Field(default_factory=list)
    legumes: list[str] = Field(default_factory=list)
    fruits: list[str] = Field(default_factory=list)
    sweeteners: list[str] = Field(default_factory=list)
    oils_fats: list[str] = Field(default_factory=list)
    techniques: list[str] = Field(default_factory=list)
    cooking_methods: list[str] = Field(default_factory=list, alias="cookingMethods")
    tools: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)

    @field_validator(
        "recipes",
        "dishes",
        "meats",
        "vegetables",
        "herbs",
        "spices",
        "dairy",
        "grains",
        "legumes",
        "fruits",
        "sweeteners",
        "oils_fats",
        "techniques",
        "cooking_methods",
        "tools",
        "other",
        mode="before",
    )
    @classmethod
    def _normalize_tag_lists(cls, value: Any) -> list[str]:
        return _normalize_list(value)


class TipCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    identifier: str | None = Field(default=None, alias="id")
    scope: Literal["general", "recipe_specific", "not_tip"] = "general"
    text: str
    source_text: str | None = Field(default=None, alias="sourceText")
    standalone: bool = True
    generality_score: float | None = Field(default=None, alias="generalityScore")
    tags: TipTags = Field(default_factory=TipTags)
    source_recipe_id: str | None = Field(default=None, alias="sourceRecipeId")
    source_recipe_title: str | None = Field(default=None, alias="sourceRecipeTitle")
    source: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None

    @field_validator("source", "text", "source_text", mode="before")
    @classmethod
    def _normalize_tip_text(cls, value: Any) -> Any:
        if value is None:
            return value
        return _normalize_text(str(value))

    @field_validator("identifier", "source_recipe_id", "source_recipe_title", mode="before")
    @classmethod
    def _normalize_identifier_fields(cls, value: Any) -> Any:
        if value is None:
            return value
        return _normalize_text(str(value))


class TopicCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    identifier: str | None = Field(default=None, alias="id")
    text: str
    tags: TipTags = Field(default_factory=TipTags)
    source: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    source_section: str | None = Field(default=None, alias="sourceSection")
    header: str | None = None

    @field_validator("source", "text", mode="before")
    @classmethod
    def _normalize_topic_text(cls, value: Any) -> Any:
        if value is None:
            return value
        return _normalize_text(str(value))

    @field_validator("identifier", "source_section", "header", mode="before")
    @classmethod
    def _normalize_topic_fields(cls, value: Any) -> Any:
        if value is None:
            return value
        return _normalize_text(str(value))


# --------------------------------------------------------------------------
# Knowledge Chunking Models
# --------------------------------------------------------------------------


class ChunkLane(str, Enum):
    """Classification lane for a knowledge chunk."""

    KNOWLEDGE = "knowledge"
    NARRATIVE = "narrative"
    NOISE = "noise"


class ChunkBoundaryReason(str, Enum):
    """Reason why a chunk boundary was created."""

    HEADING = "heading"
    RECIPE_BOUNDARY = "recipe_boundary"
    CALLOUT_SEED = "callout_seed"
    FORMAT_MODE_CHANGE = "format_mode_change"
    MAX_CHARS = "max_chars"
    NOISE_BREAK = "noise_break"
    TOPIC_PIVOT = "topic_pivot"
    END_OF_INPUT = "end_of_input"
    START_OF_INPUT = "start_of_input"


class ChunkHighlight(BaseModel):
    """A mined tip/highlight within a chunk."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    text: str
    source_block_ids: list[int] = Field(default_factory=list, alias="sourceBlockIds")
    offset_start: int | None = Field(default=None, alias="offsetStart")
    offset_end: int | None = Field(default=None, alias="offsetEnd")
    self_contained: bool = Field(default=True, alias="selfContained")
    tags: TipTags = Field(default_factory=TipTags)

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_highlight_text(cls, value: Any) -> Any:
        if value is None:
            return value
        return _normalize_text(str(value))


class KnowledgeChunk(BaseModel):
    """A coherent section of non-recipe text for knowledge extraction."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    identifier: str | None = Field(default=None, alias="id")
    lane: ChunkLane = ChunkLane.KNOWLEDGE
    title: str | None = None
    section_path: list[str] = Field(default_factory=list, alias="sectionPath")
    text: str
    block_ids: list[int] = Field(default_factory=list, alias="blockIds")
    aside_block_ids: list[int] = Field(default_factory=list, alias="asideBlockIds")
    excluded_block_ids: list[int] = Field(default_factory=list, alias="excludedBlockIds")
    distill_text: str | None = Field(default=None, alias="distillText")
    boundary_start_reason: ChunkBoundaryReason = Field(
        default=ChunkBoundaryReason.START_OF_INPUT, alias="boundaryStartReason"
    )
    boundary_end_reason: ChunkBoundaryReason = Field(
        default=ChunkBoundaryReason.END_OF_INPUT, alias="boundaryEndReason"
    )
    tags: TipTags = Field(default_factory=TipTags)
    tip_density: float = Field(default=0.0, alias="tipDensity")
    highlight_count: int = Field(default=0, alias="highlightCount")
    highlights: list[ChunkHighlight] = Field(default_factory=list)
    source: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text", "title", "distill_text", mode="before")
    @classmethod
    def _normalize_chunk_text(cls, value: Any) -> Any:
        if value is None:
            return value
        return _normalize_text(str(value))

    @field_validator("section_path", mode="before")
    @classmethod
    def _normalize_section_path(cls, value: Any) -> list[str]:
        return _normalize_str_list(value)


class SheetMapping(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    sheet_name: str | None = Field(default=None, alias="sheetName")
    name_pattern: str | None = Field(default=None, alias="namePattern")
    layout: str | None = None
    header_row: int | None = Field(default=None, alias="headerRow")
    low_confidence: bool = Field(default=False, alias="lowConfidence")
    column_aliases: dict[str, list[str]] = Field(default_factory=dict, alias="columnAliases")
    template_cells: dict[str, str] = Field(default_factory=dict, alias="templateCells")
    tall_keys: dict[str, str] = Field(default_factory=dict, alias="tallKeys")


class ParsingOverrides(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str | None = None
    ingredient_headers: list[str] = Field(default_factory=list, alias="ingredientHeaders")
    instruction_headers: list[str] = Field(default_factory=list, alias="instructionHeaders")
    tip_headers: list[str] = Field(default_factory=list, alias="tipHeaders")
    tip_prefixes: list[str] = Field(default_factory=list, alias="tipPrefixes")
    imperative_verbs: list[str] = Field(default_factory=list, alias="imperativeVerbs")
    unit_terms: list[str] = Field(default_factory=list, alias="unitTerms")
    enable_spacy: bool | None = Field(default=None, alias="enableSpacy")


class MappingConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    ingredient_delimiters: list[str] = Field(
        default_factory=lambda: ["\n"],
        alias="ingredientDelimiters",
    )
    instruction_delimiters: list[str] = Field(
        default_factory=lambda: ["\n"],
        alias="instructionDelimiters",
    )
    skip_rows: list[int] = Field(default_factory=list, alias="skipRows")
    row_skip_mode: str | None = Field(default=None, alias="rowSkipMode")
    default_layout: str | None = Field(default=None, alias="defaultLayout")
    parsing_overrides: ParsingOverrides | None = Field(default=None, alias="parsingOverrides")
    sheets: list[SheetMapping] = Field(default_factory=list)

    @field_validator("ingredient_delimiters", "instruction_delimiters", mode="before")
    @classmethod
    def _normalize_delimiters(cls, value: Any) -> list[str]:
        return _coerce_str_list(value)


class SheetInspection(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    layout: str | None = None
    header_row: int | None = Field(default=None, alias="headerRow")
    inferred_mapping: SheetMapping | None = Field(default=None, alias="inferredMapping")
    confidence: float | None = None
    low_confidence: bool = Field(default=False, alias="lowConfidence")
    warnings: list[str] = Field(default_factory=list)


class WorkbookInspection(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    path: str
    sheets: list[SheetInspection] = Field(default_factory=list)
    mapping_stub: MappingConfig | None = Field(default=None, alias="mappingStub")


class SkippedRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    sheet: str
    row_index: int = Field(alias="rowIndex")
    reason: str


class ConversionReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    run_timestamp: str | None = Field(default=None, alias="runTimestamp")
    source_file: str | None = Field(default=None, alias="sourceFile")
    importer_name: str | None = Field(default=None, alias="importerName")
    average_confidence: float | None = Field(default=None, alias="averageConfidence")
    category_confidence: dict[str, float] = Field(default_factory=dict, alias="categoryConfidence")
    
    total_recipes: int = Field(0, alias="totalRecipes")
    total_tips: int = Field(0, alias="totalTips")
    total_tip_candidates: int = Field(0, alias="totalTipCandidates")
    total_topic_candidates: int = Field(0, alias="totalTopicCandidates")
    total_general_tips: int = Field(0, alias="totalGeneralTips")
    total_recipe_specific_tips: int = Field(0, alias="totalRecipeSpecificTips")
    total_not_tips: int = Field(0, alias="totalNotTips")
    per_sheet_counts: dict[str, int] = Field(default_factory=dict, alias="perSheetCounts")
    skipped_rows: list[SkippedRow] = Field(default_factory=list, alias="skippedRows")
    missing_field_counts: dict[str, int] = Field(
        default_factory=dict, alias="missingFieldCounts"
    )
    low_confidence_sheets: list[str] = Field(
        default_factory=list, alias="lowConfidenceSheets"
    )
    samples: list[dict[str, Any]] = Field(default_factory=list)
    tip_samples: list[dict[str, Any]] = Field(default_factory=list, alias="tipSamples")
    topic_samples: list[dict[str, Any]] = Field(default_factory=list, alias="topicSamples")
    mapping_used: MappingConfig | None = Field(default=None, alias="mappingUsed")
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RawArtifact(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    importer: str
    source_hash: str = Field(alias="sourceHash")
    location_id: str = Field(alias="locationId")
    extension: str
    content: Any
    encoding: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversionResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    source: str | None = None
    recipes: list[RecipeCandidate] = Field(default_factory=list)
    tips: list[TipCandidate] = Field(default_factory=list)
    tip_candidates: list[TipCandidate] = Field(default_factory=list, alias="tipCandidates")
    topic_candidates: list[TopicCandidate] = Field(default_factory=list, alias="topicCandidates")
    chunks: list["KnowledgeChunk"] = Field(default_factory=list)
    non_recipe_blocks: list[dict[str, Any]] = Field(
        default_factory=list, alias="nonRecipeBlocks"
    )
    raw_artifacts: list[RawArtifact] = Field(default_factory=list, alias="rawArtifacts")
    report: ConversionReport
    workbook: str | None = None
    workbook_path: str | None = Field(default=None, alias="workbookPath")
