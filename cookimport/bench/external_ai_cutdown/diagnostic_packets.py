from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Callable


def _write_jsonl_gzip_deterministic(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(fileobj=raw_handle, mode="wb", mtime=0) as gzip_handle:
            for row in rows:
                payload = json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                gzip_handle.write(payload)
                gzip_handle.write(b"\n")
                written += 1
    return written


def _load_extracted_archive_blocks(
    path: Path,
    *,
    coerce_int: Callable[[Any], int | None],
) -> dict[int, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}

    rows: list[dict[str, Any]]
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        blocks = payload.get("blocks")
        rows = [row for row in blocks if isinstance(row, dict)] if isinstance(blocks, list) else []
    else:
        rows = []

    indexed: dict[int, dict[str, Any]] = {}
    for fallback_index, row in enumerate(rows):
        index = coerce_int(row.get("index"))
        if index is None:
            index = coerce_int(row.get("block_index"))
        location = row.get("location")
        if index is None and isinstance(location, dict):
            index = coerce_int(location.get("block_index"))
        if index is None:
            index = fallback_index
        features = location.get("features") if isinstance(location, dict) else None
        indexed[int(index)] = {
            "text": str(row.get("text") or ""),
            "features": dict(features) if isinstance(features, dict) else {},
        }
    return indexed


def _prompt_row_sort_key(
    row: dict[str, Any],
    *,
    prompt_row_stage_key: Callable[[dict[str, Any]], str],
    llm_stage_map: dict[str, dict[str, Any]],
    parse_json_like: Callable[[Any], Any],
    coerce_str_list: Callable[[Any], list[str]],
) -> tuple[int, int, str]:
    stage_key = prompt_row_stage_key(row)
    pass_rank = int(llm_stage_map.get(stage_key, {}).get("sort_order") or 99)

    parsed_response = parse_json_like(row.get("parsed_response"))
    parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
    warning_count = len(coerce_str_list(parsed_response.get("warnings")))
    call_id = str(row.get("call_id") or "")
    return (pass_rank, -warning_count, call_id)


def _select_prompt_rows_by_recipe(
    full_prompt_rows: list[dict[str, Any]],
    *,
    prompt_row_sort_key: Callable[[dict[str, Any]], tuple[int, int, str]],
    prompt_row_owned_recipe_ids: Callable[[dict[str, Any]], list[str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    if not full_prompt_rows:
        return {}, None
    sorted_rows = sorted(full_prompt_rows, key=prompt_row_sort_key)
    by_recipe: dict[str, dict[str, Any]] = {}
    fallback: dict[str, Any] | None = sorted_rows[0]
    for row in sorted_rows:
        for recipe_id in prompt_row_owned_recipe_ids(row):
            if recipe_id not in by_recipe:
                by_recipe[recipe_id] = row
    return by_recipe, fallback


def _build_wrong_label_full_context_rows(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
    excerpt_limit: int,
    iter_jsonl: Callable[[Path], list[dict[str, Any]]],
    load_json: Callable[[Path], dict[str, Any]],
    coerce_int: Callable[[Any], int | None],
    source_file_name: Callable[[str | None], str | None],
    source_key: Callable[[str | None, str | None], str],
    build_line_prediction_view: Callable[..., Any],
    line_context: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    wrong_rows = iter_jsonl(run_dir / "wrong_label_lines.jsonl")
    if not wrong_rows:
        return []

    run_manifest_path = run_dir / "run_manifest.json"
    run_manifest = load_json(run_manifest_path) if run_manifest_path.is_file() else {}
    run_id = str(run_manifest.get("run_id") or run_dir.name)
    source = run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
    source_path = source.get("path") if isinstance(source, dict) else None
    source_hash = source.get("source_hash") if isinstance(source, dict) else None
    source_file = source_file_name(source_path if isinstance(source_path, str) else None)
    source_key_value = source_key(
        source_hash if isinstance(source_hash, str) else None,
        source_file,
    )

    line_view = build_line_prediction_view(run_dir=run_dir, recipe_spans=recipe_spans)

    rows: list[dict[str, Any]] = []
    for wrong_row in wrong_rows:
        line_index = coerce_int(wrong_row.get("line_index"))
        if line_index is None:
            continue
        recipe_id = line_view.recipe_id_by_index.get(line_index)
        span_region = line_view.recipe_span_by_index.get(line_index, "outside_active_recipe_span")
        gold_label = str(
            wrong_row.get("gold_label")
            or line_view.gold_label_by_index.get(line_index)
            or "OTHER"
        )
        pred_label = str(
            wrong_row.get("pred_label")
            or line_view.pred_label_by_index.get(line_index)
            or "OTHER"
        )
        rows.append(
            {
                "run_id": run_id,
                "line_index": line_index,
                "recipe_id": recipe_id,
                "span_region": span_region,
                "gold_label": gold_label,
                "pred_label": pred_label,
                "source_file": source_file,
                "source_hash": source_hash if isinstance(source_hash, str) else None,
                "source_key": source_key_value,
                **line_context(
                    line_text_by_index=line_view.line_text_by_index,
                    line_index=line_index,
                    excerpt_limit=excerpt_limit,
                ),
            }
        )
    rows.sort(key=lambda row: int(row.get("line_index") or 0))
    return rows


def _build_preprocess_trace_failure_rows(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    full_prompt_rows: list[dict[str, Any]],
    excerpt_limit: int,
    iter_jsonl: Callable[[Path], list[dict[str, Any]]],
    coerce_int: Callable[[Any], int | None],
    parse_json_like: Callable[[Any], Any],
    coerce_str_list: Callable[[Any], list[str]],
    normalize_whitespace: Callable[[str], str],
    prompt_warning_bucket: Callable[[str], str],
    prompt_row_stage_key: Callable[[dict[str, Any]], str],
    source_file_name: Callable[[str | None], str | None],
    source_key: Callable[[str | None, str | None], str],
    excerpt: Callable[..., str],
    line_context: Callable[..., dict[str, Any]],
    first_prompt_block_excerpt: Callable[..., str],
    select_prompt_row_for_trace: Callable[..., dict[str, Any] | None],
    resolve_trace_status: Callable[..., str],
    resolve_prediction_run_dir: Callable[..., Path | None],
    resolve_extracted_archive_path: Callable[..., Path | None],
    load_extracted_archive_blocks: Callable[[Path], dict[int, dict[str, Any]]],
    select_prompt_rows_by_recipe: Callable[
        [list[dict[str, Any]]], tuple[dict[str, dict[str, Any]], dict[str, Any] | None]
    ],
    build_recipe_spans_from_full_prompt_rows: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    build_line_prediction_view: Callable[..., Any],
) -> tuple[list[dict[str, Any]], str]:
    wrong_rows = iter_jsonl(run_dir / "wrong_label_lines.jsonl")
    if not wrong_rows:
        return [], "not_applicable"

    if not full_prompt_rows:
        return [], "missing_full_prompt_log"

    pred_run_dir = resolve_prediction_run_dir(run_dir, run_manifest)
    extracted_archive_path = resolve_extracted_archive_path(
        run_dir,
        run_manifest,
        pred_run_dir=pred_run_dir,
    )
    if extracted_archive_path is None:
        return [], "missing_prediction_run" if pred_run_dir is None else "missing_extracted_archive"

    archive_blocks = load_extracted_archive_blocks(extracted_archive_path)
    prompt_rows_by_recipe, fallback_prompt_row = select_prompt_rows_by_recipe(full_prompt_rows)
    recipe_spans = build_recipe_spans_from_full_prompt_rows(full_prompt_rows)
    line_view = build_line_prediction_view(run_dir=run_dir, recipe_spans=recipe_spans)

    run_id = str(run_manifest.get("run_id") or run_dir.name)
    source = run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
    source_path = source.get("path") if isinstance(source, dict) else None
    source_hash = source.get("source_hash") if isinstance(source, dict) else None
    source_file = source_file_name(source_path if isinstance(source_path, str) else None)
    source_key_value = source_key(
        source_hash if isinstance(source_hash, str) else None,
        source_file,
    )

    rows: list[dict[str, Any]] = []
    for wrong_row in wrong_rows:
        line_index = coerce_int(wrong_row.get("line_index"))
        if line_index is None:
            continue

        recipe_id = line_view.recipe_id_by_index.get(line_index)
        span_region = line_view.recipe_span_by_index.get(
            line_index,
            "outside_active_recipe_span",
        )
        recipe_key = str(recipe_id or "").strip()
        prompt_row = select_prompt_row_for_trace(
            recipe_key=recipe_key,
            span_region=span_region,
            prompt_rows_by_recipe=prompt_rows_by_recipe,
            fallback_prompt_row=fallback_prompt_row,
        )
        prompt_stage_key_value = (
            prompt_row_stage_key(prompt_row) if isinstance(prompt_row, dict) else None
        )
        call_id = str(prompt_row.get("call_id") or "").strip() if prompt_row else None

        parsed_response = (
            parse_json_like(prompt_row.get("parsed_response")) if isinstance(prompt_row, dict) else {}
        )
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = coerce_str_list(parsed_response.get("warnings"))
        warning_buckets = sorted(
            {
                prompt_warning_bucket(normalize_whitespace(warning))
                for warning in warnings
                if warning.strip()
            }
        )
        prompt_candidate_block_excerpt = (
            first_prompt_block_excerpt(prompt_row, excerpt_limit=excerpt_limit)
            if isinstance(prompt_row, dict)
            else ""
        )

        archive_row = archive_blocks.get(line_index, {})
        raw_block_text = str(archive_row.get("text") or "")
        raw_block_excerpt = (
            excerpt(normalize_whitespace(raw_block_text), max_len=excerpt_limit)
            if raw_block_text
            else ""
        )
        features = archive_row.get("features")
        features = features if isinstance(features, dict) else {}
        trace_status = resolve_trace_status(
            span_region=span_region,
            has_prompt_excerpt=bool(prompt_candidate_block_excerpt),
            has_archive_excerpt=bool(raw_block_excerpt),
        )

        rows.append(
            {
                "run_id": run_id,
                "line_index": line_index,
                "recipe_id": recipe_id,
                "span_region": span_region,
                "gold_label": str(
                    wrong_row.get("gold_label")
                    or line_view.gold_label_by_index.get(line_index)
                    or "OTHER"
                ),
                "pred_label": str(
                    wrong_row.get("pred_label")
                    or line_view.pred_label_by_index.get(line_index)
                    or "OTHER"
                ),
                "raw_block_excerpt": raw_block_excerpt,
                "raw_block_unstructured_preprocess_mode": features.get(
                    "unstructured_preprocess_mode"
                ),
                "raw_block_stable_key": features.get("unstructured_stable_key"),
                "prompt_candidate_block_excerpt": prompt_candidate_block_excerpt,
                "stage_key": prompt_stage_key_value,
                "call_id": call_id,
                "warning_buckets": warning_buckets,
                "trace_status": trace_status,
                "source_file": source_file,
                "source_hash": source_hash if isinstance(source_hash, str) else None,
                "source_key": source_key_value,
                **line_context(
                    line_text_by_index=line_view.line_text_by_index,
                    line_index=line_index,
                    excerpt_limit=excerpt_limit,
                ),
            }
        )

    rows.sort(key=lambda row: int(row.get("line_index") or 0))
    if not rows:
        return [], "not_applicable"
    return rows, "ready"
