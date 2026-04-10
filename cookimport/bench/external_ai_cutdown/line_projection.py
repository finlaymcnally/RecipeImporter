from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .canonical_lines import _build_canonical_lines, _line_gold_labels, _load_gold_spans
from .io import _coerce_int, _iter_jsonl, _load_json


def _build_recipe_spans_from_full_prompt_rows(
    *,
    rows: list[dict[str, Any]],
    prompt_row_stage_key: Callable[[dict[str, Any]], str],
    parse_json_like: Callable[[Any], Any],
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for row in rows:
        stage_key = prompt_row_stage_key(row)
        if stage_key not in {"recipe_refine", "recipe_build_intermediate"}:
            continue
        request_input_payload = parse_json_like(row.get("request_input_payload"))
        if not isinstance(request_input_payload, dict):
            continue
        parsed_response = parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}

        shard_recipe_rows = request_input_payload.get("r")
        if isinstance(shard_recipe_rows, list) and shard_recipe_rows:
            for recipe_row in shard_recipe_rows:
                if not isinstance(recipe_row, dict):
                    continue
                recipe_id = str(recipe_row.get("rid") or "").strip()
                if not recipe_id:
                    continue
                evidence_rows = recipe_row.get("ev")
                evidence_rows = evidence_rows if isinstance(evidence_rows, list) else []
                indices = [
                    int(index)
                    for index in (
                        _coerce_int(item[0])
                        for item in evidence_rows
                        if isinstance(item, (list, tuple)) and len(item) >= 2
                    )
                    if index is not None
                ]
                if not indices:
                    continue
                start = min(indices)
                end = max(indices)
                if start is None or end is None or end < start:
                    continue
                hints = recipe_row.get("h") if isinstance(recipe_row.get("h"), dict) else {}
                title = (
                    str(hints.get("n") or "").strip()
                    or str(recipe_row.get("txt") or "").strip()
                    or None
                )
                dedupe_key = (recipe_id, start, end)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                spans.append(
                    {
                        "recipe_id": recipe_id,
                        "start_block_index": start,
                        "end_block_index": end,
                        "title": title,
                        "call_id": row.get("call_id"),
                    }
                )
            continue

        evidence_rows = request_input_payload.get("evidence_rows")
        indices: list[int] = []
        if isinstance(evidence_rows, list) and evidence_rows:
            indices = [
                int(index)
                for index in (
                    _coerce_int(item[0])
                    for item in evidence_rows
                    if isinstance(item, (list, tuple)) and len(item) >= 2
                )
                if index is not None
            ]
        if not indices:
            start = _coerce_int(parsed_response.get("start_block_index"))
            end = _coerce_int(parsed_response.get("end_block_index"))
            if start is not None and end is not None and end >= start:
                indices = list(range(int(start), int(end) + 1))
        if not indices:
            continue
        start = min(indices)
        end = max(indices)
        if start is None or end is None or end < start:
            continue
        recipe_id = str(
            row.get("recipe_id") or request_input_payload.get("recipe_id") or ""
        ).strip()
        if not recipe_id:
            continue
        canonical_recipe = (
            parsed_response.get("canonical_recipe")
            if isinstance(parsed_response.get("canonical_recipe"), dict)
            else {}
        )
        dedupe_key = (recipe_id, start, end)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        spans.append(
            {
                "recipe_id": recipe_id,
                "start_block_index": start,
                "end_block_index": end,
                "title": canonical_recipe.get("title")
                or parsed_response.get("title")
                or None,
                "call_id": row.get("call_id"),
            }
        )
    spans.sort(
        key=lambda row: (
            int(row["start_block_index"]),
            int(row["end_block_index"]) - int(row["start_block_index"]),
            str(row["recipe_id"]),
        )
    )
    return spans


def _normalize_recipe_spans_to_line_coordinates(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not recipe_spans:
        return []

    normalized = [dict(span) for span in recipe_spans if isinstance(span, dict)]
    needs_projection = False
    for span in normalized:
        start_line_index = _coerce_int(span.get("start_line_index"))
        end_line_index = _coerce_int(span.get("end_line_index"))
        if start_line_index is not None and end_line_index is not None:
            continue
        if "line_indices" in span:
            continue
        needs_projection = True

    if not needs_projection:
        return normalized

    projected_rows = _iter_jsonl(run_dir / "line-role-pipeline" / "projected_spans.jsonl")
    if not projected_rows:
        return normalized

    line_indices_by_block_index: dict[int, set[int]] = defaultdict(set)
    for row in projected_rows:
        block_index = _coerce_int(row.get("block_index"))
        line_index = _coerce_int(row.get("line_index"))
        if block_index is None or line_index is None:
            continue
        line_indices_by_block_index[int(block_index)].add(int(line_index))

    if not line_indices_by_block_index:
        return normalized

    for span in normalized:
        if "line_indices" in span:
            continue
        start_block_index = _coerce_int(span.get("start_block_index"))
        end_block_index = _coerce_int(span.get("end_block_index"))
        if start_block_index is None or end_block_index is None or end_block_index < start_block_index:
            continue
        projected_line_indices = sorted(
            line_index
            for block_index, line_indices in line_indices_by_block_index.items()
            if start_block_index <= block_index <= end_block_index
            for line_index in line_indices
        )
        span["line_indices"] = projected_line_indices
        if projected_line_indices:
            span["start_line_index"] = projected_line_indices[0]
            span["end_line_index"] = projected_line_indices[-1]
    return normalized


def _span_line_indices(span: dict[str, Any]) -> list[int] | None:
    if "line_indices" not in span:
        return None
    raw_values = span.get("line_indices")
    if not isinstance(raw_values, list):
        return []
    seen: set[int] = set()
    line_indices: list[int] = []
    for value in raw_values:
        parsed = _coerce_int(value)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        line_indices.append(int(parsed))
    line_indices.sort()
    return line_indices


def _span_line_bounds(span: dict[str, Any]) -> tuple[int | None, int | None]:
    line_indices = _span_line_indices(span)
    if line_indices is not None:
        if not line_indices:
            return None, None
        return line_indices[0], line_indices[-1]

    start_line_index = _coerce_int(span.get("start_line_index"))
    end_line_index = _coerce_int(span.get("end_line_index"))
    if start_line_index is not None and end_line_index is not None:
        return int(start_line_index), int(end_line_index)

    start_block_index = _coerce_int(span.get("start_block_index"))
    end_block_index = _coerce_int(span.get("end_block_index"))
    if start_block_index is None or end_block_index is None:
        return None, None
    return int(start_block_index), int(end_block_index)


def _span_contains_line(*, span: dict[str, Any], line_index: int) -> bool:
    line_indices = _span_line_indices(span)
    if line_indices is not None:
        return line_index in line_indices
    start, end = _span_line_bounds(span)
    if start is None or end is None:
        return False
    return start <= line_index <= end


def _resolve_recipe_for_line(
    *,
    line_index: int,
    recipe_spans: list[dict[str, Any]],
) -> tuple[str | None, str]:
    matches: list[dict[str, Any]] = []
    for span in recipe_spans:
        if _span_contains_line(span=span, line_index=line_index):
            matches.append(span)
    if not matches:
        return None, "outside_active_recipe_span"
    best = sorted(
        matches,
        key=lambda span: (
            int((_span_line_bounds(span)[1] or 0) - (_span_line_bounds(span)[0] or 0)),
            int(_span_line_bounds(span)[0] or 0),
            str(span["recipe_id"]),
        ),
    )[0]
    return str(best["recipe_id"]), "inside_active_recipe_span"


def _build_line_prediction_view(
    *,
    run_dir: Path,
    recipe_spans: list[dict[str, Any]],
    line_prediction_view_type: Callable[..., Any],
) -> Any:
    normalized_recipe_spans = _normalize_recipe_spans_to_line_coordinates(
        run_dir=run_dir,
        recipe_spans=recipe_spans,
    )
    eval_report_path = run_dir / "eval_report.json"
    eval_report = _load_json(eval_report_path) if eval_report_path.is_file() else {}
    canonical = eval_report.get("canonical")
    if not isinstance(canonical, dict):
        return line_prediction_view_type({}, {}, {}, {}, {}, normalized_recipe_spans)

    canonical_text_path_raw = canonical.get("canonical_text_path")
    canonical_spans_path_raw = canonical.get("canonical_span_labels_path")
    if not isinstance(canonical_text_path_raw, str) or not isinstance(canonical_spans_path_raw, str):
        return line_prediction_view_type({}, {}, {}, {}, {}, normalized_recipe_spans)

    canonical_text_path = Path(canonical_text_path_raw)
    canonical_spans_path = Path(canonical_spans_path_raw)
    if not canonical_text_path.is_file() or not canonical_spans_path.is_file():
        return line_prediction_view_type({}, {}, {}, {}, {}, normalized_recipe_spans)

    canonical_text = canonical_text_path.read_text(encoding="utf-8")
    lines = _build_canonical_lines(canonical_text)
    gold_spans = _load_gold_spans(canonical_spans_path)
    gold_labels_by_line = _line_gold_labels(lines=lines, spans=gold_spans)

    wrong_label_rows = _iter_jsonl(run_dir / "wrong_label_lines.jsonl")
    predicted_overrides: dict[int, str] = {}
    for row in wrong_label_rows:
        line_index = _coerce_int(row.get("line_index"))
        if line_index is None:
            continue
        pred_label = str(row.get("pred_label") or "").strip()
        if not pred_label:
            continue
        predicted_overrides[line_index] = pred_label

    line_text_by_index: dict[int, str] = {}
    gold_label_by_index: dict[int, str] = {}
    pred_label_by_index: dict[int, str] = {}
    recipe_id_by_index: dict[int, str | None] = {}
    recipe_span_by_index: dict[int, str] = {}

    for line in lines:
        line_index = int(line["line_index"])
        line_text = str(line.get("text") or "")
        gold_labels = gold_labels_by_line.get(line_index, ["OTHER"])
        gold_label = gold_labels[0] if gold_labels else "OTHER"
        pred_label = predicted_overrides.get(line_index, gold_label)
        recipe_id, span_region = _resolve_recipe_for_line(
            line_index=line_index,
            recipe_spans=normalized_recipe_spans,
        )

        line_text_by_index[line_index] = line_text
        gold_label_by_index[line_index] = gold_label
        pred_label_by_index[line_index] = pred_label
        recipe_id_by_index[line_index] = recipe_id
        recipe_span_by_index[line_index] = span_region

    return line_prediction_view_type(
        line_text_by_index=line_text_by_index,
        gold_label_by_index=gold_label_by_index,
        pred_label_by_index=pred_label_by_index,
        recipe_id_by_index=recipe_id_by_index,
        recipe_span_by_index=recipe_span_by_index,
        recipe_spans=normalized_recipe_spans,
    )
