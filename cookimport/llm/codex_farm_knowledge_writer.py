from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .codex_farm_knowledge_models import KnowledgeChunkResultV2


@dataclass(frozen=True, slots=True)
class KnowledgeWriteReport:
    snippets_written: int
    snippets_path: Path
    preview_path: Path
    snippet_records: list[dict[str, Any]]


def write_knowledge_artifacts(
    *,
    run_root: Path,
    workbook_slug: str,
    outputs: Mapping[str, KnowledgeChunkResultV2],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    chunk_lane_by_id: Mapping[str, str | None] | None = None,
) -> KnowledgeWriteReport:
    """Write knowledge-stage reviewer artifacts under the run directory."""
    knowledge_dir = run_root / "knowledge" / workbook_slug
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    snippets_path = knowledge_dir / "snippets.jsonl"
    preview_path = knowledge_dir / "knowledge.md"

    lanes = dict(chunk_lane_by_id or {})
    snippet_records: list[dict[str, Any]] = []

    for chunk_id in sorted(outputs):
        output = outputs[chunk_id]
        lane = lanes.get(chunk_id)
        for snippet_index, snippet in enumerate(output.snippets):
            evidence_indices = [int(pointer.block_index) for pointer in snippet.evidence]
            for idx in evidence_indices:
                if int(idx) not in full_blocks_by_index:
                    raise ValueError(
                        "Evidence pointer references missing block index "
                        f"{idx} (chunk_id={chunk_id})."
                    )
            snippet_id = f"{chunk_id}.s{snippet_index:02d}"
            record = {
                "snippet_id": snippet_id,
                "chunk_id": chunk_id,
                "chunk_is_useful": bool(output.is_useful),
                "title": None,
                "body": snippet.body,
                "tags": [],
                "evidence": [
                    {"block_index": int(pointer.block_index), "quote": pointer.quote}
                    for pointer in snippet.evidence
                ],
                "provenance": {"block_indices": sorted(set(evidence_indices))},
            }
            if lane is not None:
                record["heuristic_lane"] = lane
            snippet_records.append(record)

    snippets_path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n"
            for record in snippet_records
        ),
        encoding="utf-8",
    )

    preview_path.write_text(
        _render_preview_md(
            workbook_slug=workbook_slug,
            records=snippet_records,
            full_blocks_by_index=full_blocks_by_index,
        ),
        encoding="utf-8",
    )

    return KnowledgeWriteReport(
        snippets_written=len(snippet_records),
        snippets_path=snippets_path,
        preview_path=preview_path,
        snippet_records=snippet_records,
    )


def _render_preview_md(
    *,
    workbook_slug: str,
    records: list[dict[str, Any]],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"# Knowledge Snippets ({workbook_slug})")
    lines.append("")
    lines.append(f"- Total snippets: {len(records)}")
    lines.append("")

    for ordinal, record in enumerate(records, start=1):
        title = str(record.get("title") or f"Snippet {ordinal}").strip()
        snippet_id = str(record.get("snippet_id") or "")
        chunk_id = str(record.get("chunk_id") or "")
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"- snippet_id: `{snippet_id}`")
        lines.append(f"- chunk_id: `{chunk_id}`")
        lane = record.get("heuristic_lane")
        if isinstance(lane, str) and lane.strip():
            lines.append(f"- heuristic_lane: `{lane.strip()}`")
        lines.append("")
        body = str(record.get("body") or "").strip()
        if body:
            lines.append(body)
            lines.append("")

        evidence = record.get("evidence") or []
        lines.append("Evidence:")
        for pointer in evidence:
            block_index = int(pointer.get("block_index"))
            quote = str(pointer.get("quote") or "").strip()
            quote_display = quote.replace("\n", " ")
            if len(quote_display) > 140:
                quote_display = quote_display[:137] + "..."
            lines.append(f"- block {block_index}: \"{quote_display}\"")
        lines.append("")

        lines.append("Source context:")
        for pointer in evidence:
            block_index = int(pointer.get("block_index"))
            block = full_blocks_by_index[int(block_index)]
            text = str(block.get("text") or "").strip()
            text_display = text if len(text) <= 600 else text[:597] + "..."
            lines.append(f"- block {block_index}: {text_display}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
