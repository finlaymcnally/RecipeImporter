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
    snippets_path: Path | None
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
    preview_path = knowledge_dir / "knowledge.md"

    group_records: list[dict[str, Any]] = []
    snippet_records: list[dict[str, Any]] = []
    for packet_id in sorted(outputs):
        output = outputs[packet_id]
        decisions_by_row_index = {
            int(decision.row_index): decision
            for decision in (output.row_decisions or [])
        }
        for group_index, group in enumerate(output.row_groups, start=1):
            knowledge_group_id = f"{packet_id}.{group.group_id}"
            shared_grounding = {
                "tag_keys": [
                    str(value).strip()
                    for value in (getattr(group.grounding, "tag_keys", ()) or ())
                    if str(value).strip()
                ],
                "category_keys": [
                    str(value).strip()
                    for value in (getattr(group.grounding, "category_keys", ()) or ())
                    if str(value).strip()
                ],
                "proposed_tags": [
                    {
                        "key": str(tag.key).strip(),
                        "display_name": str(tag.display_name).strip(),
                        "category_key": str(tag.category_key).strip(),
                    }
                    for tag in (getattr(group.grounding, "proposed_tags", ()) or ())
                    if str(getattr(tag, "key", "")).strip()
                ],
            }
            record = {
                "knowledge_group_id": knowledge_group_id,
                "packet_id": packet_id,
                "group_id": group.group_id,
                "topic_label": group.topic_label,
                "row_indices": list(group.row_indices),
                "shared_grounding": shared_grounding,
                "why_no_existing_tag": str(group.why_no_existing_tag or "").strip() or None,
                "retrieval_query": str(group.retrieval_query or "").strip() or None,
                "grounded_rows": [],
                "snippets": [],
            }
            if not record["row_indices"]:
                raise ValueError(
                    f"Knowledge row group {knowledge_group_id} had no row indices."
                )
            missing_row_indices = [
                int(row_index)
                for row_index in record["row_indices"]
                if int(row_index) not in full_blocks_by_index
            ]
            if missing_row_indices:
                raise ValueError(
                    "Knowledge row group "
                    f"{knowledge_group_id} referenced missing row index "
                    f"{missing_row_indices[0]}."
                )
            for row_index in record["row_indices"]:
                decision = decisions_by_row_index.get(int(row_index))
                if decision is None:
                    continue
                grounding = getattr(decision, "grounding", None)
                record["grounded_rows"].append(
                    {
                        "row_index": int(row_index),
                        "grounding": {
                            "tag_keys": [
                                str(value).strip()
                                for value in (getattr(grounding, "tag_keys", ()) or ())
                                if str(value).strip()
                            ],
                            "category_keys": [
                                str(value).strip()
                                for value in (getattr(grounding, "category_keys", ()) or ())
                                if str(value).strip()
                            ],
                            "proposed_tags": [
                                {
                                    "key": str(tag.key).strip(),
                                    "display_name": str(tag.display_name).strip(),
                                    "category_key": str(tag.category_key).strip(),
                                }
                                for tag in (getattr(grounding, "proposed_tags", ()) or ())
                                if str(getattr(tag, "key", "")).strip()
                            ],
                        },
                    }
                )
            record["ordinal"] = group_index
            group_records.append(record)

    groups_path.write_text(
        json.dumps(group_records, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
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
        snippets_written=0,
        groups_path=groups_path,
        snippets_path=None,
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
        row_indices = [int(value) for value in (record.get("row_indices") or [])]
        lines.append(f"## {topic_label}")
        lines.append("")
        lines.append(f"- knowledge_group_id: `{knowledge_group_id}`")
        lines.append(f"- packet_id: `{packet_id}`")
        if row_indices:
            lines.append(
                f"- row_indices: `{row_indices[0]}..{row_indices[-1]}` ({len(row_indices)} rows)"
            )
        shared_grounding = dict(record.get("shared_grounding") or {})
        tag_keys = ", ".join(str(value) for value in (shared_grounding.get("tag_keys") or []))
        if tag_keys:
            lines.append(f"- shared_tag_keys: {tag_keys}")
        proposed_tags = [
            str(row.get("display_name") or row.get("key") or "").strip()
            for row in (shared_grounding.get("proposed_tags") or [])
            if isinstance(row, Mapping)
            and str(row.get("display_name") or row.get("key") or "").strip()
        ]
        if proposed_tags:
            lines.append(f"- shared_proposed_tags: {', '.join(proposed_tags)}")
        why_no_existing_tag = str(record.get("why_no_existing_tag") or "").strip()
        if why_no_existing_tag:
            lines.append(f"- why_no_existing_tag: {why_no_existing_tag}")
        retrieval_query = str(record.get("retrieval_query") or "").strip()
        if retrieval_query:
            lines.append(f"- retrieval_query: {retrieval_query}")
        lines.append("")

        lines.append("Source context:")
        for row_index in row_indices:
            block = full_blocks_by_index.get(int(row_index)) or {}
            text = str(block.get("text") or "").strip()
            text_display = text if len(text) <= 600 else text[:597] + "..."
            lines.append(f"- row {row_index}: {text_display}")
            grounding_row = next(
                (
                    row
                    for row in (record.get("grounded_rows") or [])
                    if int(row.get("row_index") or -1) == int(row_index)
                ),
                None,
            )
            if grounding_row is None:
                continue
            grounding = dict(grounding_row.get("grounding") or {})
            tag_keys = ", ".join(str(value) for value in (grounding.get("tag_keys") or []))
            if tag_keys:
                lines.append(f"  tag_keys: {tag_keys}")
            proposed_tags = [
                str(row.get("display_name") or row.get("key") or "").strip()
                for row in (grounding.get("proposed_tags") or [])
                if isinstance(row, Mapping)
                and str(row.get("display_name") or row.get("key") or "").strip()
            ]
            if proposed_tags:
                lines.append(f"  proposed_tags: {', '.join(proposed_tags)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
