from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .codex_farm_knowledge_models import KnowledgeBundleOutputV2


@dataclass(frozen=True, slots=True)
class KnowledgeWriteReport:
    groups_written: int
    snippets_written: int
    groups_path: Path
    snippets_path: Path
    preview_path: Path
    group_records: list[dict[str, Any]]
    snippet_records: list[dict[str, Any]]


def write_knowledge_artifacts(
    *,
    run_root: Path,
    workbook_slug: str,
    outputs: Mapping[str, KnowledgeBundleOutputV2],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
) -> KnowledgeWriteReport:
    knowledge_dir = run_root / "knowledge" / workbook_slug
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    groups_path = knowledge_dir / "knowledge_groups.json"
    snippets_path = knowledge_dir / "snippets.jsonl"
    preview_path = knowledge_dir / "knowledge.md"

    group_records: list[dict[str, Any]] = []
    snippet_records: list[dict[str, Any]] = []
    for packet_id in sorted(outputs):
        output = outputs[packet_id]
        for group_index, group in enumerate(output.idea_groups, start=1):
            knowledge_group_id = f"{packet_id}.{group.group_id}"
            record = {
                "knowledge_group_id": knowledge_group_id,
                "packet_id": packet_id,
                "group_id": group.group_id,
                "topic_label": group.topic_label,
                "block_indices": list(group.block_indices),
                "snippets": [],
            }
            for snippet_index, snippet in enumerate(group.snippets):
                evidence_indices = [int(pointer.block_index) for pointer in snippet.evidence]
                for idx in evidence_indices:
                    if int(idx) not in full_blocks_by_index:
                        raise ValueError(
                            "Evidence pointer references missing block index "
                            f"{idx} (packet_id={packet_id}, group_id={group.group_id})."
                        )
                snippet_id = f"{knowledge_group_id}.s{snippet_index:02d}"
                snippet_record = {
                    "snippet_id": snippet_id,
                    "knowledge_group_id": knowledge_group_id,
                    "packet_id": packet_id,
                    "group_id": group.group_id,
                    "topic_label": group.topic_label,
                    "body": snippet.body,
                    "evidence": [
                        {"block_index": int(pointer.block_index), "quote": pointer.quote}
                        for pointer in snippet.evidence
                    ],
                    "provenance": {"block_indices": sorted(set(evidence_indices))},
                }
                snippet_records.append(snippet_record)
                record["snippets"].append(
                    {
                        "snippet_id": snippet_id,
                        "body": snippet.body,
                        "evidence": snippet_record["evidence"],
                    }
                )
            if not record["snippets"]:
                raise ValueError(
                    f"Knowledge idea group {knowledge_group_id} had no snippets after rendering."
                )
            if not record["block_indices"]:
                raise ValueError(
                    f"Knowledge idea group {knowledge_group_id} had no block indices."
                )
            record["ordinal"] = group_index
            group_records.append(record)

    groups_path.write_text(
        json.dumps(group_records, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
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
            records=group_records,
            full_blocks_by_index=full_blocks_by_index,
        ),
        encoding="utf-8",
    )

    return KnowledgeWriteReport(
        groups_written=len(group_records),
        snippets_written=len(snippet_records),
        groups_path=groups_path,
        snippets_path=snippets_path,
        preview_path=preview_path,
        group_records=group_records,
        snippet_records=snippet_records,
    )


def _render_preview_md(
    *,
    workbook_slug: str,
    records: list[dict[str, Any]],
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"# Knowledge Groups ({workbook_slug})")
    lines.append("")
    lines.append(f"- Total groups: {len(records)}")
    lines.append("")

    for ordinal, record in enumerate(records, start=1):
        topic_label = str(record.get("topic_label") or f"Knowledge Group {ordinal}").strip()
        knowledge_group_id = str(record.get("knowledge_group_id") or "")
        packet_id = str(record.get("packet_id") or "")
        block_indices = [int(value) for value in (record.get("block_indices") or [])]
        lines.append(f"## {topic_label}")
        lines.append("")
        lines.append(f"- knowledge_group_id: `{knowledge_group_id}`")
        lines.append(f"- packet_id: `{packet_id}`")
        if block_indices:
            lines.append(
                f"- block_indices: `{block_indices[0]}..{block_indices[-1]}` ({len(block_indices)} blocks)"
            )
        lines.append("")

        lines.append("Snippets:")
        for snippet in record.get("snippets") or []:
            body = str(snippet.get("body") or "").strip()
            lines.append(f"- {body}")
        lines.append("")

        lines.append("Source context:")
        for block_index in block_indices:
            block = full_blocks_by_index.get(int(block_index)) or {}
            text = str(block.get("text") or "").strip()
            text_display = text if len(text) <= 600 else text[:597] + "..."
            lines.append(f"- block {block_index}: {text_display}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
