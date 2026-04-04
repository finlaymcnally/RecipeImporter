from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .io import _iter_jsonl, _sample_indices_evenly

_PROMPT_LOG_SEPARATOR = "--------------------------------------------------------------------------------"
_PROMPT_SECTION_HEADER_RE = re.compile(
    r"^---\s+([0-9A-Za-z_-]+)\s+(INPUT|RESPONSE)\s+FILES\s+---$"
)
_PROMPT_ENTRY_RE = re.compile(r"^(INPUT|OUTPUT)\s+([0-9A-Za-z_-]+)\s*=>\s*(.+)$")
_PROMPT_CATEGORY_SORT_RE = re.compile(r"^([a-z]+)(\d+)(.*)$")


def _parse_prompt_log_sections(source_path: Path) -> dict[str, dict[str, list[dict[str, str]]]]:
    sections: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(
        lambda: {"input": [], "output": []}
    )

    current_category: str | None = None
    current_kind: str | None = None
    current_filename: str | None = None
    current_lines: list[str] = []
    current_body_started = False
    collecting = False

    def flush_current_entry() -> None:
        nonlocal collecting, current_category, current_kind, current_filename, current_lines
        nonlocal current_body_started
        if not collecting or current_category is None or current_kind is None:
            return
        if current_filename is None:
            return
        text = "\n".join(current_lines).rstrip()
        if text:
            sections[current_category][current_kind].append(
                {"filename": current_filename, "text": text}
            )
        collecting = False
        current_filename = None
        current_lines = []
        current_kind = None
        current_body_started = False

    for raw_line in source_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()

        section_match = _PROMPT_SECTION_HEADER_RE.match(stripped)
        if section_match:
            flush_current_entry()
            current_category = section_match.group(1).lower()
            continue

        entry_match = _PROMPT_ENTRY_RE.match(stripped)
        if entry_match:
            flush_current_entry()
            current_category = entry_match.group(2).lower()
            current_kind = "input" if entry_match.group(1).upper() == "INPUT" else "output"
            current_filename = entry_match.group(3).strip()
            current_lines = [raw_line]
            current_body_started = False
            collecting = True
            continue

        if collecting and stripped == _PROMPT_LOG_SEPARATOR:
            current_lines.append(raw_line)
            if current_body_started:
                flush_current_entry()
            else:
                current_body_started = True
            continue

        if collecting and current_category is not None:
            current_lines.append(raw_line)

    flush_current_entry()
    return {
        category: payload
        for category, payload in sections.items()
        if payload["input"] or payload["output"]
    }


def _prompt_category_sort_key(
    category: str,
    *,
    llm_stage_map: dict[str, dict[str, Any]],
) -> tuple[int, str, int, str]:
    lower = category.lower()
    stage_sort = int(llm_stage_map.get(lower, {}).get("sort_order") or -1)
    if stage_sort >= 0:
        return (0, "", stage_sort, lower)
    match = _PROMPT_CATEGORY_SORT_RE.match(lower)
    if match:
        return (1, match.group(1), int(match.group(2)), match.group(3))
    return (2, lower, 0, "")


def _write_prompt_log_samples(
    *,
    source_path: Path,
    output_path: Path,
    max_pairs_per_category: int,
    llm_stage_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    parsed = _parse_prompt_log_sections(source_path)
    if not parsed:
        output_path.write_text(
            "No parseable prompt input/response sections were found in this log.\n",
            encoding="utf-8",
        )
        return {
            "status": "no_sections",
            "max_pairs_per_category": max_pairs_per_category,
            "categories": [],
            "sampled_pairs": 0,
        }

    lines: list[str] = [
        "# Codex Exec prompt input/output examples (sampled)",
        "",
        (
            "This file keeps a deterministic sample of whole prompt-input/output file "
            f"blocks from the full prompt log, at most {max_pairs_per_category} pairs "
            "per category."
        ),
        "",
        f"Source log: {source_path}",
        "",
    ]

    category_metadata: dict[str, dict[str, int]] = {}
    sampled_pairs = 0
    ordered_categories = sorted(
        parsed.keys(),
        key=lambda category: _prompt_category_sort_key(
            category,
            llm_stage_map=llm_stage_map,
        ),
    )
    for category in ordered_categories:
        input_blocks = parsed[category]["input"]
        output_blocks = parsed[category]["output"]
        pairable_count = min(len(input_blocks), len(output_blocks))
        sampled_pair_indices = _sample_indices_evenly(pairable_count, max_pairs_per_category)
        pair_count = len(sampled_pair_indices)

        category_metadata[category] = {
            "input_blocks": len(input_blocks),
            "output_blocks": len(output_blocks),
            "pairable_blocks": pairable_count,
            "sampled_pairs": pair_count,
            "sampled_pair_indices": sampled_pair_indices,
        }
        lines.append(
            (
                f"--- {category.upper()} INPUT/OUTPUT PAIRS (showing {pair_count} of "
                f"{pairable_count}) ---"
            )
        )
        if pair_count == 0:
            lines.append("No full input/output pair available for this category in this log.")
            lines.append("")
            continue

        for pair_no, pair_index in enumerate(sampled_pair_indices, start=1):
            input_block = input_blocks[pair_index]
            output_block = output_blocks[pair_index]
            lines.extend(
                [
                    (
                        f"[{category}] Pair {pair_no} (source index {pair_index + 1}) "
                        f"- INPUT file: {input_block['filename']}"
                    ),
                    input_block["text"],
                    _PROMPT_LOG_SEPARATOR,
                    (
                        f"[{category}] Pair {pair_no} (source index {pair_index + 1}) "
                        f"- OUTPUT file: {output_block['filename']}"
                    ),
                    output_block["text"],
                    _PROMPT_LOG_SEPARATOR,
                    "",
                ]
            )
            sampled_pairs += 1

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "status": "sampled",
        "source_path": str(source_path),
        "max_pairs_per_category": max_pairs_per_category,
        "categories": ordered_categories,
        "sampled_pairs": sampled_pairs,
        "category_metadata": category_metadata,
    }


def _write_prompt_log_samples_from_full_prompt_log(
    *,
    source_path: Path,
    output_path: Path,
    max_pairs_per_category: int,
    excerpt_limit: int,
    llm_stage_map: dict[str, dict[str, Any]],
    prompt_row_stage_key: Callable[[dict[str, Any]], str],
    clip_strings_deep: Callable[..., Any],
) -> dict[str, Any]:
    rows = _iter_jsonl(source_path)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        stage_key = prompt_row_stage_key(row) or "unknown"
        grouped[stage_key].append(row)

    if not grouped:
        output_path.write_text(
            "No parseable rows were found in full_prompt_log.jsonl.\n",
            encoding="utf-8",
        )
        return {
            "status": "no_rows",
            "source_path": str(source_path),
            "max_pairs_per_category": max_pairs_per_category,
            "categories": [],
            "sampled_pairs": 0,
        }

    for stage_key in grouped:
        grouped[stage_key].sort(
            key=lambda row: (
                str(row.get("call_id") or ""),
                str(row.get("timestamp_utc") or ""),
            )
        )

    lines: list[str] = [
        "# Codex Exec prompt input/output examples (from full_prompt_log.jsonl)",
        "",
        (
            "This convenience file is derived from full_prompt_log.jsonl and keeps "
            "request/response payload content for sampled calls (with long strings clipped)."
            if max_pairs_per_category > 0
            else (
                "This convenience file is derived from full_prompt_log.jsonl and keeps all calls "
                "(with long strings clipped)."
            )
        ),
        "",
        f"Source log: {source_path}",
        f"String clip limit: {excerpt_limit} chars",
        "",
    ]

    category_metadata: dict[str, dict[str, Any]] = {}
    sampled_pairs = 0
    ordered_categories = sorted(
        grouped.keys(),
        key=lambda category: _prompt_category_sort_key(
            category,
            llm_stage_map=llm_stage_map,
        ),
    )
    for category in ordered_categories:
        category_rows = grouped[category]
        if max_pairs_per_category <= 0:
            sampled_indices = list(range(len(category_rows)))
        else:
            sampled_indices = _sample_indices_evenly(
                len(category_rows),
                max_pairs_per_category,
            )
        pair_count = len(sampled_indices)
        category_metadata[category] = {
            "total_calls": len(category_rows),
            "sampled_calls": pair_count,
            "sampled_call_indices": sampled_indices,
        }

        lines.append(
            f"--- {category.upper()} STAGE CALLS (showing {pair_count} of {len(category_rows)}) ---"
        )
        if pair_count == 0:
            lines.append("No calls available for this stage category.")
            lines.append("")
            continue

        for sample_no, source_index in enumerate(sampled_indices, start=1):
            row = category_rows[source_index]
            call_id = str(row.get("call_id") or "").strip()
            recipe_id = str(row.get("recipe_id") or "").strip()
            timestamp_utc = str(row.get("timestamp_utc") or "").strip()
            source_file = str(row.get("source_file") or "").strip()
            lines.extend(
                [
                    (
                        f"[{category}] Sample {sample_no} (source index {source_index + 1})"
                        f" call_id={call_id} recipe_id={recipe_id} timestamp_utc={timestamp_utc}"
                    ),
                    f"source_file={source_file}",
                    "",
                    "REQUEST_MESSAGES:",
                    json.dumps(
                        clip_strings_deep(
                            row.get("request_messages"),
                            excerpt_limit=excerpt_limit,
                        ),
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "",
                    "RAW_RESPONSE:",
                    json.dumps(
                        clip_strings_deep(
                            row.get("raw_response"),
                            excerpt_limit=excerpt_limit,
                        ),
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "",
                    "PARSED_RESPONSE:",
                    json.dumps(
                        clip_strings_deep(
                            row.get("parsed_response"),
                            excerpt_limit=excerpt_limit,
                        ),
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    _PROMPT_LOG_SEPARATOR,
                    "",
                ]
            )
            sampled_pairs += 1

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "status": "sampled_from_full_prompt_log",
        "source_path": str(source_path),
        "max_pairs_per_category": max_pairs_per_category,
        "excerpt_limit": excerpt_limit,
        "categories": ordered_categories,
        "sampled_pairs": sampled_pairs,
        "category_metadata": category_metadata,
    }
