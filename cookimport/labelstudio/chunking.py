from __future__ import annotations

import hashlib
import random
import re
from typing import Any, Iterable

from cookimport.core.models import ConversionResult, RawArtifact, RecipeCandidate, TopicCandidate
from cookimport.parsing.atoms import contextualize_atoms, split_text_to_atoms

from cookimport.labelstudio.models import ArchiveBlock, ChunkRecord, CoverageReport

_SOFT_HYPHEN = "\u00ad"


def normalize_display_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = cleaned.replace(_SOFT_HYPHEN, "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"(\w)-\n(\w)", r"\1\2", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _normalize_for_hash(text: str) -> str:
    cleaned = normalize_display_text(text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def _text_hash(text: str) -> str:
    normalized = _normalize_for_hash(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]


def _location_token(location: dict[str, Any]) -> str:
    keys = [
        "sheet",
        "row_index",
        "start_row",
        "end_row",
        "page",
        "chapter",
        "block_index",
        "start_block",
        "end_block",
        "atom_index",
        "line_index",
        "start_line",
        "end_line",
        "chunk_index",
        "recipe_index",
        "ingredient_index",
        "step_index",
    ]
    parts: list[str] = []
    for key in keys:
        if key in location and location[key] is not None:
            parts.append(f"{key}={location[key]}")
    if not parts:
        return "loc=unknown"
    return ";".join(parts)


def build_chunk_id(
    *,
    file_hash: str,
    pipeline: str,
    chunk_level: str,
    location: dict[str, Any],
    text: str,
) -> str:
    loc_token = _location_token(location)
    text_hash = _text_hash(text)
    short_hash = file_hash[:12] if file_hash else "unknown"
    return f"urn:recipeimport:chunk:{pipeline}:{short_hash}:{chunk_level}:{loc_token}:{text_hash}"


def _row_to_text(content: dict[str, Any]) -> str:
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


def build_extracted_archive(
    result: ConversionResult,
    raw_artifacts: list[RawArtifact],
) -> list[ArchiveBlock]:
    archive: list[ArchiveBlock] = []

    def add_block(index: int, text: str, location: dict[str, Any], source: str | None) -> None:
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

    for artifact in raw_artifacts:
        artifact_type = artifact.metadata.get("artifact_type") if artifact.metadata else None
        if artifact_type == "extracted_blocks":
            blocks = []
            if isinstance(artifact.content, dict):
                blocks = artifact.content.get("blocks", [])
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                index = int(block.get("index", len(archive)))
                text = block.get("text", "")
                location = {k: v for k, v in block.items() if k not in {"text", "html"}}
                add_block(index, text, location, artifact.importer)
        elif artifact_type == "extracted_text":
            lines = []
            if isinstance(artifact.content, dict):
                lines = artifact.content.get("lines", [])
            for line in lines:
                if not isinstance(line, dict):
                    continue
                index = int(line.get("index", len(archive)))
                text = line.get("text", "")
                add_block(index, text, {"line_index": index}, artifact.importer)
        elif artifact_type == "extracted_rows":
            rows = []
            if isinstance(artifact.content, dict):
                rows = artifact.content.get("rows", [])
            for row in rows:
                if not isinstance(row, dict):
                    continue
                index = int(row.get("row_index", len(archive)))
                location = {
                    "row_index": row.get("row_index"),
                    "sheet": row.get("sheet"),
                }
                add_block(index, _row_to_text(row), location, artifact.importer)

    if not archive:
        for artifact in raw_artifacts:
            if artifact.metadata:
                continue
            content = artifact.content
            if isinstance(content, dict) and "row" in content:
                index = int(content.get("row_index", len(archive)))
                location = {
                    "row_index": content.get("row_index"),
                    "sheet": content.get("sheet"),
                }
                add_block(index, _row_to_text(content), location, artifact.importer)
            if isinstance(content, dict) and "blocks" in content:
                blocks = content.get("blocks", [])
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    index = int(block.get("index", len(archive)))
                    text = block.get("text", "")
                    location = {k: v for k, v in block.items() if k not in {"text", "html"}}
                    add_block(index, text, location, artifact.importer)

    if not archive:
        for idx, recipe in enumerate(result.recipes):
            location = _recipe_location(recipe, idx)
            add_block(idx, _build_recipe_text(recipe), location, "recipe")

    archive.sort(key=lambda block: block.index)
    return archive


def _recipe_location(recipe: RecipeCandidate, recipe_index: int) -> dict[str, Any]:
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


def _covered_block_indices(recipes: list[RecipeCandidate]) -> set[int]:
    covered: set[int] = set()
    for recipe in recipes:
        provenance = recipe.provenance or {}
        location = provenance.get("location") if isinstance(provenance, dict) else None
        if not isinstance(location, dict):
            continue
        start = location.get("start_block")
        end = location.get("end_block")
        if isinstance(start, int) and isinstance(end, int):
            covered.update(range(start, end + 1))
    return covered


def _covered_line_indices(recipes: list[RecipeCandidate]) -> set[int]:
    covered: set[int] = set()
    for recipe in recipes:
        provenance = recipe.provenance or {}
        location = provenance.get("location") if isinstance(provenance, dict) else None
        if not isinstance(location, dict):
            continue
        start = location.get("start_line")
        end = location.get("end_line")
        if isinstance(start, int) and isinstance(end, int):
            covered.update(range(start, end + 1))
    return covered


def _topic_container_key(topic: TopicCandidate) -> tuple[Any, ...]:
    provenance = topic.provenance or {}
    location = provenance.get("location") if isinstance(provenance, dict) else {}
    if not isinstance(location, dict):
        location = {}
    return (
        location.get("start_block"),
        location.get("end_block"),
        location.get("start_line"),
        location.get("end_line"),
        location.get("sheet"),
        location.get("chunk_index"),
    )


def _group_topic_containers(topics: list[TopicCandidate]) -> dict[tuple[Any, ...], list[TopicCandidate]]:
    grouped: dict[tuple[Any, ...], list[TopicCandidate]] = {}
    for topic in topics:
        key = _topic_container_key(topic)
        grouped.setdefault(key, []).append(topic)
    return grouped


def _archive_text_from_range(
    archive: list[ArchiveBlock],
    start: int | None,
    end: int | None,
) -> str | None:
    if start is None or end is None:
        return None
    if start > end:
        start, end = end, start
    blocks = [block for block in archive if start <= block.index <= end]
    if not blocks:
        return None
    return normalize_display_text("\n\n".join(block.text for block in blocks if block.text))


def _chunk_type_hint_from_text(text: str) -> str | None:
    if re.match(r"^\s*\d+\.", text):
        return "step"
    if re.match(r"^\s*[-*]\s+", text):
        return "list_item"
    if re.match(r"^\s*\d+\s+\w+", text):
        return "ingredient_like"
    return None


def chunk_structural(
    result: ConversionResult,
    archive: list[ArchiveBlock],
    *,
    source_file: str,
    book_id: str,
    pipeline_used: str,
    file_hash: str,
    trace_collector: Any | None = None,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []

    for idx, recipe in enumerate(result.recipes):
        location = _recipe_location(recipe, idx)
        text_raw = _build_recipe_text(recipe)
        text_display = normalize_display_text(text_raw)
        chunk_id = build_chunk_id(
            file_hash=file_hash,
            pipeline=pipeline_used,
            chunk_level="structural",
            location=location,
            text=text_raw,
        )
        start_block = location.get("start_block", 0)
        if trace_collector is not None:
            trace_collector.record(
                "structural_span",
                start_block,
                {"chunk_type": "recipe_block", "recipe_index": idx},
            )
        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id,
                chunk_level="structural",
                chunk_type="recipe_block",
                text_raw=text_raw,
                text_display=text_display,
                source_file=source_file,
                book_id=book_id,
                pipeline_used=pipeline_used,
                location=location,
                chunk_type_hint="recipe",
                text_hash=_text_hash(text_raw),
            )
        )

    if result.topic_candidates:
        grouped = _group_topic_containers(result.topic_candidates)
        for key, topics in grouped.items():
            provenance = topics[0].provenance or {}
            location = provenance.get("location") if isinstance(provenance, dict) else {}
            if not isinstance(location, dict):
                location = {}
            start_block = location.get("start_block")
            end_block = location.get("end_block")
            start_line = location.get("start_line")
            end_line = location.get("end_line")
            text_raw = _archive_text_from_range(archive, start_block, end_block)
            if text_raw is None:
                text_raw = _archive_text_from_range(archive, start_line, end_line)
            if text_raw is None:
                text_raw = normalize_display_text("\n\n".join(topic.text for topic in topics))
            header = provenance.get("topic_header") if isinstance(provenance, dict) else None
            if header and header not in text_raw:
                text_raw = normalize_display_text(f"{header}\n\n{text_raw}")
            text_display = normalize_display_text(text_raw)
            chunk_id = build_chunk_id(
                file_hash=file_hash,
                pipeline=pipeline_used,
                chunk_level="structural",
                location=location,
                text=text_raw,
            )
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    chunk_level="structural",
                    chunk_type="standalone_block",
                    text_raw=text_raw,
                    text_display=text_display,
                    source_file=source_file,
                    book_id=book_id,
                    pipeline_used=pipeline_used,
                    location=location,
                    chunk_type_hint="standalone",
                    text_hash=_text_hash(text_raw),
                )
            )

    return chunks


def _topic_atom_chunks(
    topics: list[TopicCandidate],
    *,
    source_file: str,
    book_id: str,
    pipeline_used: str,
    file_hash: str,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    for topic in topics:
        provenance = topic.provenance or {}
        location = provenance.get("location") if isinstance(provenance, dict) else {}
        if not isinstance(location, dict):
            location = {}
        atom_meta = provenance.get("atom") if isinstance(provenance, dict) else None
        if isinstance(atom_meta, dict):
            location.setdefault("atom_index", atom_meta.get("index"))
            location.setdefault("block_index", atom_meta.get("block_index"))
        text_raw = topic.text
        text_display = normalize_display_text(text_raw)
        chunk_id = build_chunk_id(
            file_hash=file_hash,
            pipeline=pipeline_used,
            chunk_level="atomic",
            location=location,
            text=text_raw,
        )
        context_before = None
        context_after = None
        if isinstance(atom_meta, dict):
            context_before = atom_meta.get("context_prev")
            context_after = atom_meta.get("context_next")
        chunk_type = "atom"
        if isinstance(atom_meta, dict) and atom_meta.get("kind"):
            chunk_type = f"atom_{atom_meta['kind']}"
        chunk_hint = _chunk_type_hint_from_text(text_raw)
        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id,
                chunk_level="atomic",
                chunk_type=chunk_type,
                text_raw=text_raw,
                text_display=text_display,
                source_file=source_file,
                book_id=book_id,
                pipeline_used=pipeline_used,
                location=location,
                context_before=context_before,
                context_after=context_after,
                chunk_type_hint=chunk_hint,
                text_hash=_text_hash(text_raw),
            )
        )
    return chunks


def _archive_atom_chunks(
    archive: list[ArchiveBlock],
    *,
    covered_block_indices: set[int],
    covered_line_indices: set[int],
    source_file: str,
    book_id: str,
    pipeline_used: str,
    file_hash: str,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    for block in archive:
        block_index = block.location.get("block_index", block.index)
        line_index = block.location.get("line_index")
        if isinstance(block_index, int) and block_index in covered_block_indices:
            continue
        if isinstance(line_index, int) and line_index in covered_line_indices:
            continue
        atoms = split_text_to_atoms(block.text, int(block_index))
        contextualize_atoms(atoms)
        for atom in atoms:
            location = dict(block.location)
            location["block_index"] = atom.source_block_index
            location["atom_index"] = atom.sequence
            text_raw = atom.text
            text_display = normalize_display_text(text_raw)
            chunk_id = build_chunk_id(
                file_hash=file_hash,
                pipeline=pipeline_used,
                chunk_level="atomic",
                location=location,
                text=text_raw,
            )
            chunk_type = f"atom_{atom.kind}"
            chunk_hint = _chunk_type_hint_from_text(text_raw)
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    chunk_level="atomic",
                    chunk_type=chunk_type,
                    text_raw=text_raw,
                    text_display=text_display,
                    source_file=source_file,
                    book_id=book_id,
                    pipeline_used=pipeline_used,
                    location=location,
                    context_before=atom.context_prev,
                    context_after=atom.context_next,
                    chunk_type_hint=chunk_hint,
                    text_hash=_text_hash(text_raw),
                )
            )
    return chunks


def chunk_atomic(
    result: ConversionResult,
    archive: list[ArchiveBlock],
    *,
    source_file: str,
    book_id: str,
    pipeline_used: str,
    file_hash: str,
    trace_collector: Any | None = None,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []

    for recipe_index, recipe in enumerate(result.recipes):
        base_location = _recipe_location(recipe, recipe_index)

        if recipe.description:
            location = dict(base_location)
            location["chunk_index"] = "description"
            text_raw = recipe.description
            text_display = normalize_display_text(text_raw)
            chunk_id = build_chunk_id(
                file_hash=file_hash,
                pipeline=pipeline_used,
                chunk_level="atomic",
                location=location,
                text=text_raw,
            )
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    chunk_level="atomic",
                    chunk_type="recipe_description",
                    text_raw=text_raw,
                    text_display=text_display,
                    source_file=source_file,
                    book_id=book_id,
                    pipeline_used=pipeline_used,
                    location=location,
                    chunk_type_hint="paragraph",
                    text_hash=_text_hash(text_raw),
                )
            )

        for idx, ingredient in enumerate(recipe.ingredients):
            location = dict(base_location)
            location["ingredient_index"] = idx
            text_raw = ingredient
            text_display = normalize_display_text(text_raw)
            chunk_id = build_chunk_id(
                file_hash=file_hash,
                pipeline=pipeline_used,
                chunk_level="atomic",
                location=location,
                text=text_raw,
            )
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    chunk_level="atomic",
                    chunk_type="ingredient_line",
                    text_raw=text_raw,
                    text_display=text_display,
                    source_file=source_file,
                    book_id=book_id,
                    pipeline_used=pipeline_used,
                    location=location,
                    chunk_type_hint="ingredient",
                    text_hash=_text_hash(text_raw),
                )
            )

        for idx, step in enumerate(recipe.instructions):
            text_raw = step if isinstance(step, str) else step.text
            location = dict(base_location)
            location["step_index"] = idx
            text_display = normalize_display_text(text_raw)
            chunk_id = build_chunk_id(
                file_hash=file_hash,
                pipeline=pipeline_used,
                chunk_level="atomic",
                location=location,
                text=text_raw,
            )
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    chunk_level="atomic",
                    chunk_type="step_line",
                    text_raw=text_raw,
                    text_display=text_display,
                    source_file=source_file,
                    book_id=book_id,
                    pipeline_used=pipeline_used,
                    location=location,
                    chunk_type_hint="step",
                    text_hash=_text_hash(text_raw),
                )
            )

        for idx, comment in enumerate(recipe.comments):
            text_raw = comment.text or comment.name
            if not text_raw:
                continue
            location = dict(base_location)
            location["chunk_index"] = f"note_{idx}"
            text_display = normalize_display_text(text_raw)
            chunk_id = build_chunk_id(
                file_hash=file_hash,
                pipeline=pipeline_used,
                chunk_level="atomic",
                location=location,
                text=text_raw,
            )
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    chunk_level="atomic",
                    chunk_type="note",
                    text_raw=text_raw,
                    text_display=text_display,
                    source_file=source_file,
                    book_id=book_id,
                    pipeline_used=pipeline_used,
                    location=location,
                    chunk_type_hint="note",
                    text_hash=_text_hash(text_raw),
                )
            )

    if result.topic_candidates:
        chunks.extend(
            _topic_atom_chunks(
                result.topic_candidates,
                source_file=source_file,
                book_id=book_id,
                pipeline_used=pipeline_used,
                file_hash=file_hash,
            )
        )
    else:
        chunks.extend(
            _archive_atom_chunks(
                archive,
                covered_block_indices=_covered_block_indices(result.recipes),
                covered_line_indices=_covered_line_indices(result.recipes),
                source_file=source_file,
                book_id=book_id,
                pipeline_used=pipeline_used,
                file_hash=file_hash,
            )
        )

    return chunks


def compute_coverage(archive: list[ArchiveBlock], chunks: list[ChunkRecord]) -> CoverageReport:
    extracted_chars = sum(len(block.text) for block in archive)
    chunked_chars = sum(len(chunk.text_raw or "") for chunk in chunks)
    warnings: list[str] = []
    if extracted_chars == 0:
        warnings.append("No text extracted; OCR may be required for scanned documents.")
    elif chunked_chars < extracted_chars * 0.9:
        warnings.append(
            f"Chunk coverage low: {chunked_chars} of {extracted_chars} characters represented."
        )
    return CoverageReport(
        extracted_chars=extracted_chars,
        chunked_chars=chunked_chars,
        warnings=warnings,
    )


def chunk_records_to_tasks(
    chunks: Iterable[ChunkRecord], *, source_hash: str | None = None
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for chunk in chunks:
        data = {
            "chunk_id": chunk.chunk_id,
            "text_display": chunk.text_display,
            "text_raw": chunk.text_raw,
            "chunk_level": chunk.chunk_level,
            "chunk_type": chunk.chunk_type,
            "chunk_type_hint": chunk.chunk_type_hint,
            "source_file": chunk.source_file,
            "book_id": chunk.book_id,
            "pipeline_used": chunk.pipeline_used,
            "location": chunk.location,
            "context_before": chunk.context_before,
            "context_after": chunk.context_after,
        }
        if source_hash:
            data["source_hash"] = source_hash
        tasks.append({"data": data})
    return tasks


def sample_chunks(chunks: list[ChunkRecord], *, limit: int | None, sample: int | None) -> list[ChunkRecord]:
    if sample is not None and sample > 0:
        rng = random.Random(0)
        if sample >= len(chunks):
            return list(chunks)
        return rng.sample(chunks, sample)
    if limit is not None and limit > 0:
        return list(chunks)[:limit]
    return list(chunks)
