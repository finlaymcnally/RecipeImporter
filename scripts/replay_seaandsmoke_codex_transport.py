#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cookimport.bench.codex_bridge_projection_policy import (
    resolve_trace_status,
    select_prompt_row_for_trace,
)
from cookimport.llm.codex_farm_transport import build_pass2_transport_selection
from cookimport.llm.evidence_normalizer import normalize_pass2_evidence


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_blocks_for_case(case: dict[str, Any]) -> dict[int, dict[str, Any]]:
    start = int(case["start_block_index_inclusive"])
    end = int(case["end_block_index_inclusive"])
    missing = {int(value) for value in case.get("missing_block_indices") or []}

    rows: dict[int, dict[str, Any]] = {}
    for index in range(start, end + 1):
        if index in missing:
            continue
        text = f"block {index}"
        if case.get("case_id") == "c6" and index == start:
            text = "Page 9 - 1 cup sugar 2 tbsp butter"
        rows[index] = {
            "index": index,
            "block_id": f"b{index}",
            "text": text,
        }
    return rows


def _run_transport_replay(cases: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    failures: list[str] = []

    for case in cases:
        case_id = str(case["case_id"])
        blocks_by_index = _build_blocks_for_case(case)
        selection = build_pass2_transport_selection(
            recipe_id=f"recipe:{case_id}",
            bundle_name=f"{case_id}.json",
            pass1_status="ok",
            start_block_index=int(case["start_block_index_inclusive"]),
            end_block_index=int(case["end_block_index_inclusive"]),
            excluded_block_ids=list(case.get("excluded_block_ids") or []),
            full_blocks_by_index=blocks_by_index,
        )

        expected_count = int(case["expected_effective_count"])
        actual_count = int(selection.audit.get("payload_count") or 0)
        missing_count = len(selection.audit.get("missing_effective_indices") or [])
        extra_count = len(selection.audit.get("unexpected_payload_indices") or [])
        exact_match = "yes" if (
            expected_count == actual_count and missing_count == 0 and extra_count == 0
        ) else "no"

        suffix_parts: list[str] = []
        if case_id == "c6":
            normalization = normalize_pass2_evidence(selection.included_blocks)
            stats = normalization.get("stats") or {}
            suffix_parts.append(
                f"joined_quantity_lines={int(stats.get('split_quantity_lines') or 0)}"
            )
            suffix_parts.append(
                f"dropped_page_markers={int(stats.get('folded_page_markers') or 0)}"
            )
        if case_id == "c7":
            threshold = int(case.get("expect_tail_index_gte") or 0)
            tail_ok = any(index >= threshold for index in selection.effective_indices)
            suffix_parts.append(f"tail_block_ge_{threshold}={'yes' if tail_ok else 'no'}")

        line = (
            f"{case_id} expected={expected_count} actual={actual_count} "
            f"missing={missing_count} extra={extra_count} exact_match={exact_match}"
        )
        if suffix_parts:
            line += " " + " ".join(suffix_parts)
        lines.append(line)

        if exact_match != "yes":
            failures.append(f"transport mismatch for {case_id}")

    return lines, failures


def _run_outside_span_policy_replay(rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    prompt_rows_by_recipe = {"recipe:c0": {"call_id": "c0-pass2"}}
    fallback_prompt_row = {"call_id": "fallback-pass3"}

    rows_with_fallback_prompt = 0
    outside_span_archive_only_rows = 0
    failures: list[str] = []

    for row in rows:
        selected = select_prompt_row_for_trace(
            recipe_key=str(row.get("recipe_key") or ""),
            span_region=str(row.get("span_region") or ""),
            prompt_rows_by_recipe=prompt_rows_by_recipe,
            fallback_prompt_row=fallback_prompt_row,
        )
        selected_call_id = None
        if isinstance(selected, dict):
            selected_call_id = str(selected.get("call_id") or "") or None

        status = resolve_trace_status(
            span_region=str(row.get("span_region") or ""),
            has_prompt_excerpt=bool(row.get("has_prompt_excerpt")),
            has_archive_excerpt=bool(row.get("has_archive_excerpt")),
        )

        expected_status = str(row.get("expected_trace_status") or "")
        expected_prompt = row.get("expected_selected_prompt")
        if status != expected_status:
            failures.append(
                f"outside-span status mismatch for {row.get('name')}: expected={expected_status} actual={status}"
            )
        if selected_call_id != expected_prompt:
            failures.append(
                f"outside-span prompt selection mismatch for {row.get('name')}: expected={expected_prompt!r} actual={selected_call_id!r}"
            )

        if str(row.get("span_region") or "") == "outside_active_recipe_span":
            if selected_call_id == "fallback-pass3":
                rows_with_fallback_prompt += 1
            if status == "outside_span_archive_only":
                outside_span_archive_only_rows += 1

    line = (
        "outside_span "
        f"rows_with_fallback_prompt={rows_with_fallback_prompt} "
        f"outside_span_archive_only_rows={outside_span_archive_only_rows}"
    )
    return line, failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fixture-backed replay for Pro3 transport and outside-span trace policy.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run the full fixture replay set (default behavior).",
    )
    args = parser.parse_args()
    _ = args.all

    root = _repo_root()
    transport_cases_path = root / "tests" / "fixtures" / "codex_transport_cases.json"
    outside_span_path = root / "tests" / "fixtures" / "codex_outside_span_bridge.json"

    transport_cases = list((_load_json(transport_cases_path).get("cases") or []))
    outside_span_rows = list((_load_json(outside_span_path).get("rows") or []))

    transport_lines, failures = _run_transport_replay(transport_cases)
    for line in transport_lines:
        print(line)

    outside_span_line, outside_failures = _run_outside_span_policy_replay(outside_span_rows)
    print(outside_span_line)
    failures.extend(outside_failures)

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
