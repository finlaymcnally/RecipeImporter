#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_GENERATED_AT_PATTERN = re.compile(r"Generated:\s*([^\n]+)")


def _extract_insert_values(sql_text: str, *, table_name: str) -> str:
    marker = f"INSERT INTO public.{table_name}"
    start = sql_text.find(marker)
    if start < 0:
        raise ValueError(f"Could not find INSERT for public.{table_name}")
    values_start = sql_text.find("VALUES", start)
    if values_start < 0:
        raise ValueError(f"Could not find VALUES for public.{table_name}")
    conflict_start = sql_text.find("ON CONFLICT", values_start)
    if conflict_start < 0:
        raise ValueError(f"Could not find ON CONFLICT for public.{table_name}")
    return sql_text[values_start + len("VALUES") : conflict_start]


def _split_sql_tuples(values_block: str) -> list[str]:
    rows: list[str] = []
    index = 0
    while index < len(values_block):
        while index < len(values_block) and values_block[index] != "(":
            index += 1
        if index >= len(values_block):
            break
        index += 1
        start = index
        in_string = False
        row_chars: list[str] = []
        while index < len(values_block):
            char = values_block[index]
            if in_string:
                row_chars.append(char)
                if char == "'":
                    next_char = values_block[index + 1] if index + 1 < len(values_block) else ""
                    if next_char == "'":
                        row_chars.append(next_char)
                        index += 2
                        continue
                    in_string = False
                index += 1
                continue
            if char == "'":
                in_string = True
                row_chars.append(char)
                index += 1
                continue
            if char == ")":
                rows.append("".join(row_chars).strip())
                index += 1
                break
            row_chars.append(char)
            index += 1
        else:
            raise ValueError("Unterminated SQL tuple in VALUES block")
    return rows


def _parse_sql_tuple(tuple_text: str) -> list[Any]:
    values: list[str] = []
    current: list[str] = []
    index = 0
    in_string = False
    while index < len(tuple_text):
        char = tuple_text[index]
        if in_string:
            current.append(char)
            if char == "'":
                next_char = tuple_text[index + 1] if index + 1 < len(tuple_text) else ""
                if next_char == "'":
                    current.append(next_char)
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if char == "'":
            in_string = True
            current.append(char)
            index += 1
            continue
        if char == ",":
            values.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    values.append("".join(current).strip())
    return [_parse_sql_value(value) for value in values]


def _parse_sql_value(raw_value: str) -> Any:
    value = raw_value.strip()
    lowered = value.lower()
    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def build_catalog_payload(*, sql_text: str, source_sql_path: str) -> dict[str, Any]:
    generated_match = _GENERATED_AT_PATTERN.search(sql_text)
    source_generated_at = generated_match.group(1).strip() if generated_match else None

    category_rows = [
        _parse_sql_tuple(row)
        for row in _split_sql_tuples(
            _extract_insert_values(sql_text, table_name="tag_categories")
        )
    ]
    categories = [
        {
            "id": str(row[0]),
            "key": str(row[1]),
            "display_name": str(row[2]),
            "sort_order": int(row[3]),
            "is_multi_select": bool(row[4]),
        }
        for row in category_rows
    ]
    category_key_by_id = {str(row["id"]): str(row["key"]) for row in categories}

    tag_rows = [
        _parse_sql_tuple(row)
        for row in _split_sql_tuples(
            _extract_insert_values(sql_text, table_name="recipe_tags")
        )
    ]
    tags = [
        {
            "id": str(row[0]),
            "key": str(row[1]),
            "display_name": str(row[2]),
            "category_key": category_key_by_id[str(row[3])],
            "sort_order": int(row[4]),
        }
        for row in tag_rows
    ]

    categories.sort(key=lambda row: (int(row["sort_order"]), row["key"]))
    tags.sort(key=lambda row: (row["category_key"], int(row["sort_order"]), row["key"]))
    return {
        "catalog_version": "cookbook-tag-catalog-2026-03-30",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_sql_path": source_sql_path,
        "source_sql_generated_at": source_generated_at,
        "category_count": len(categories),
        "tag_count": len(tags),
        "categories": categories,
        "tags": tags,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh cookimport/llm/knowledge_tag_catalog.json from Cookbook seed SQL."
    )
    parser.add_argument(
        "--catalog-sql",
        type=Path,
        default=Path("~/projects/cookbook/supabase/seeds/catalog.sql").expanduser(),
        help="Path to Cookbook catalog.sql",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "cookimport"
        / "llm"
        / "knowledge_tag_catalog.json",
        help="Path to the checked-in JSON catalog",
    )
    args = parser.parse_args()

    sql_path = args.catalog_sql.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    sql_text = sql_path.read_text(encoding="utf-8")
    payload = build_catalog_payload(
        sql_text=sql_text,
        source_sql_path=str(sql_path),
    )
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {output_path} with {payload['category_count']} categories and {payload['tag_count']} tags."
    )


if __name__ == "__main__":
    main()
