from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from cookimport.core.models import ConversionResult, RawArtifact, RecipeCandidate
from cookimport.core.source_model import source_blocks_to_rows
from cookimport.labelstudio.models import ArchiveBlock

_SOFT_HYPHEN = "\u00ad"


def normalize_display_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = cleaned.replace(_SOFT_HYPHEN, "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"(\w)-\n(\w)", r"\1\2", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _row_to_text(content: dict[str, object]) -> str:
    headers = content.get("headers") or []
    row = content.get("row") or []
    parts: list[str] = []
    if isinstance(row, dict):
        for key, value in row.items():
            if value is None:
                continue
            parts.append(f"{key}: {value}")
    elif isinstance(row, list):
        for idx, value in enumerate(row):
            if value is None:
                continue
            header = headers[idx] if idx < len(headers) else None
            label = f"{header}: " if header else ""
            parts.append(f"{label}{value}")
    else:
        parts.append(str(row))
    return normalize_display_text("\n".join(parts))


def _recipe_location(recipe: RecipeCandidate, recipe_index: int) -> dict[str, object]:
    provenance = recipe.provenance or {}
    location = provenance.get("location") if isinstance(provenance, dict) else None
    if not isinstance(location, dict):
        location = {}
    location = dict(location)
    if "row_index" not in location and provenance.get("row_index") is not None:
        location["row_index"] = provenance.get("row_index")
    if "sheet" not in location and provenance.get("sheet") is not None:
        location["sheet"] = provenance.get("sheet")
    location["recipe_index"] = recipe_index
    if recipe.identifier:
        location["recipe_id"] = recipe.identifier
    return location


def _recipe_section_lines(recipe: RecipeCandidate) -> list[str]:
    lines: list[str] = [recipe.name]
    if recipe.description:
        lines.append("")
        lines.append(recipe.description)
    if recipe.recipe_yield:
        lines.append("")
        lines.append(f"Yield: {recipe.recipe_yield}")
    if recipe.ingredients:
        lines.append("")
        lines.append("Ingredients:")
        lines.extend(recipe.ingredients)
    if recipe.instructions:
        lines.append("")
        lines.append("Instructions:")
        for step in recipe.instructions:
            if isinstance(step, str):
                lines.append(step)
            else:
                lines.append(step.text)
    if recipe.comments:
        lines.append("")
        lines.append("Notes:")
        for comment in recipe.comments:
            if comment.text:
                lines.append(comment.text)
            elif comment.name:
                lines.append(comment.name)
    return lines


def _build_recipe_text(recipe: RecipeCandidate) -> str:
    return normalize_display_text("\n".join(_recipe_section_lines(recipe)))


@dataclass(frozen=True)
class PreparedExtractedArchive:
    blocks: tuple[ArchiveBlock, ...]
    archive_payload: tuple[dict[str, Any], ...]
    extracted_text: str
    source_file: str | None = None
    source_hash: str | None = None

    @property
    def block_count(self) -> int:
        return len(self.blocks)


def build_extracted_archive(
    result: ConversionResult,
    raw_artifacts: list[RawArtifact],
) -> list[ArchiveBlock]:
    del raw_artifacts
    archive: list[ArchiveBlock] = []

    def add_block(index: int, text: str, location: dict[str, object], source: str | None) -> None:
        cleaned = normalize_display_text(text)
        if not cleaned:
            return
        location = dict(location)
        location.setdefault("block_index", index)
        archive.append(
            ArchiveBlock(
                index=index,
                text=cleaned,
                location=location,
                source_kind=source,
            )
        )

    if not result.source_blocks:
        raise ValueError("Expected canonical source_blocks before building extracted archive.")

    for block in source_blocks_to_rows(result.source_blocks):
        index = int(block.get("index", len(archive)))
        text = str(block.get("text", ""))
        location = block.get("location")
        if not isinstance(location, dict):
            location = {}
        location = dict(location)
        location.setdefault("block_id", str(block.get("block_id") or f"block:{index}"))
        add_block(index, text, location, "source_block")

    archive.sort(key=lambda block: block.index)
    return archive


def prepare_extracted_archive(
    *,
    result: ConversionResult,
    raw_artifacts: list[RawArtifact],
    source_file: str | None = None,
    source_hash: str | None = None,
    archive_builder: Callable[
        [ConversionResult, list[RawArtifact]],
        list[ArchiveBlock],
    ]
    | None = None,
) -> PreparedExtractedArchive:
    builder = archive_builder or build_extracted_archive
    blocks = list(builder(result, raw_artifacts))
    payload = tuple(
        {
            "index": block.index,
            "text": block.text,
            "location": dict(block.location),
            "source_kind": block.source_kind,
        }
        for block in blocks
    )
    extracted_text = normalize_display_text(
        "\n\n".join(block.text for block in blocks if block.text)
    )
    return PreparedExtractedArchive(
        blocks=tuple(blocks),
        archive_payload=payload,
        extracted_text=extracted_text,
        source_file=source_file,
        source_hash=source_hash,
    )


def prepared_archive_payload(prepared: PreparedExtractedArchive) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for item in prepared.archive_payload:
        copied = dict(item)
        location = item.get("location")
        copied["location"] = dict(location) if isinstance(location, dict) else {}
        payload.append(copied)
    return payload


def prepared_archive_text(prepared: PreparedExtractedArchive) -> str:
    return prepared.extracted_text
