from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cookimport.parsing.source_rows import SourceRow, build_source_rows


class AtomicLineCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recipe_id: str | None = None
    row_id: str = ""
    block_id: str
    block_index: int
    atomic_index: int
    row_ordinal: int = 0
    start_char_in_block: int = 0
    end_char_in_block: int = 0
    text: str
    within_recipe_span: bool | None = None
    rule_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_row_metadata(self) -> "AtomicLineCandidate":
        if not str(self.row_id or "").strip():
            self.row_id = f"row:{int(self.atomic_index)}"
        if self.end_char_in_block <= 0 and self.text:
            self.end_char_in_block = len(self.text)
        return self


def build_atomic_index_lookup(
    candidates: Sequence[AtomicLineCandidate],
) -> dict[int, AtomicLineCandidate]:
    return {int(candidate.atomic_index): candidate for candidate in candidates}


def get_atomic_line_neighbor_texts(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: Mapping[int, AtomicLineCandidate],
) -> tuple[str | None, str | None]:
    prev_candidate = by_atomic_index.get(int(candidate.atomic_index) - 1)
    next_candidate = by_atomic_index.get(int(candidate.atomic_index) + 1)
    prev_text = str(prev_candidate.text or "") if prev_candidate is not None else None
    next_text = str(next_candidate.text or "") if next_candidate is not None else None
    return prev_text, next_text


def atomize_blocks(
    blocks: Sequence[Any],
    *,
    recipe_id: str | None,
    within_recipe_span: bool | None,
    atomic_block_splitter: str = "atomic-v1",
) -> list[AtomicLineCandidate]:
    normalized_splitter = str(atomic_block_splitter or "").strip().lower().replace("_", "-")
    if normalized_splitter in {"", "off", "none", "default"}:
        output: list[AtomicLineCandidate] = []
        for atomic_index, block in enumerate(blocks):
            if not isinstance(block, Mapping):
                continue
            text = str(block.get("text") or "")
            if not text:
                continue
            block_index = int(block.get("block_index", block.get("index", atomic_index)))
            block_id = str(block.get("block_id") or f"block:{block_index}")
            output.append(
                AtomicLineCandidate(
                    recipe_id=recipe_id,
                    row_id=f"row:{atomic_index}",
                    block_id=block_id,
                    block_index=block_index,
                    atomic_index=atomic_index,
                    row_ordinal=0,
                    start_char_in_block=0,
                    end_char_in_block=len(text),
                    text=text,
                    within_recipe_span=within_recipe_span,
                    rule_tags=[],
                )
            )
        return output
    source_rows = build_source_rows(blocks, source_hash="unknown")
    return _source_rows_to_atomic_candidates(
        source_rows,
        recipe_id=recipe_id,
        within_recipe_span=within_recipe_span,
    )


def source_rows_to_atomic_candidates(
    rows: Sequence[SourceRow],
    *,
    recipe_id: str | None,
    within_recipe_span: bool | None,
) -> list[AtomicLineCandidate]:
    return _source_rows_to_atomic_candidates(
        rows,
        recipe_id=recipe_id,
        within_recipe_span=within_recipe_span,
    )


def _source_rows_to_atomic_candidates(
    rows: Sequence[SourceRow],
    *,
    recipe_id: str | None,
    within_recipe_span: bool | None,
) -> list[AtomicLineCandidate]:
    output: list[AtomicLineCandidate] = []
    for row in rows:
        rule_tags = list(row.rule_tags)
        if "explicit_prose" in rule_tags:
            if within_recipe_span is True and "recipe_span_fallback" not in rule_tags:
                rule_tags.append("recipe_span_fallback")
            if within_recipe_span is False and "outside_recipe_span" not in rule_tags:
                rule_tags.append("outside_recipe_span")
        output.append(
            AtomicLineCandidate(
                recipe_id=recipe_id,
                row_id=str(row.row_id),
                block_id=str(row.block_id),
                block_index=int(row.block_index),
                atomic_index=int(row.row_index),
                row_ordinal=int(row.row_ordinal),
                start_char_in_block=int(row.start_char_in_block),
                end_char_in_block=int(row.end_char_in_block),
                text=str(row.text),
                within_recipe_span=within_recipe_span,
                rule_tags=rule_tags,
            )
        )
    return output
