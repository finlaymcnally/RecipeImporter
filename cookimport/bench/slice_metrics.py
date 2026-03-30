from __future__ import annotations

from typing import Any, Callable

from cookimport.bench.eval_stage_blocks import compute_block_metrics


def build_line_role_slice_metrics(
    joined_line_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    slices: dict[str, Callable[[dict[str, Any]], bool]] = {
        "outside_recipe": lambda row: not bool(row.get("within_recipe_span")),
        "recipe_titles_and_variants": (
            lambda row: bool(row.get("within_recipe_span"))
            and str(row.get("gold_label") or "OTHER") in {"RECIPE_TITLE", "RECIPE_VARIANT"}
        ),
        "recipe_notes_and_yield": (
            lambda row: bool(row.get("within_recipe_span"))
            and str(row.get("gold_label") or "OTHER") in {"RECIPE_NOTES", "YIELD_LINE"}
        ),
        "recipe_ingredients": (
            lambda row: bool(row.get("within_recipe_span"))
            and str(row.get("gold_label") or "OTHER") == "INGREDIENT_LINE"
        ),
        "recipe_instructions": (
            lambda row: bool(row.get("within_recipe_span"))
            and str(row.get("gold_label") or "OTHER") in {"INSTRUCTION_LINE", "HOWTO_SECTION"}
        ),
    }

    payload: dict[str, Any] = {
        "schema_version": "line_role_slice_metrics.v1",
        "line_count": len(joined_line_rows),
        "slices": {},
    }

    for slice_name, predicate in slices.items():
        selected = [row for row in joined_line_rows if predicate(row)]
        gold: dict[int, str] = {}
        pred: dict[int, str] = {}
        for index, row in enumerate(selected):
            gold[index] = str(row.get("gold_label") or "OTHER")
            pred[index] = str(row.get("pred_label") or "OTHER")
        if not selected:
            payload["slices"][slice_name] = {
                "line_count": 0,
                "overall_line_accuracy": 0.0,
                "macro_f1_excluding_other": 0.0,
                "worst_label_recall": {"label": None, "recall": None},
            }
            continue
        metrics = compute_block_metrics(gold, pred)
        payload["slices"][slice_name] = {
            "line_count": len(selected),
            "overall_line_accuracy": float(metrics.get("overall_block_accuracy") or 0.0),
            "macro_f1_excluding_other": float(metrics.get("macro_f1_excluding_other") or 0.0),
            "worst_label_recall": metrics.get("worst_label_recall"),
        }
    return payload


def build_line_role_routing_summary(
    joined_line_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    inside_recipe_count = 0
    outside_recipe_count = 0
    unknown_recipe_status_count = 0
    outside_recipe_excluded_count = 0
    outside_recipe_candidate_count = 0
    outside_recipe_structured_count = 0
    recipe_local_label_count = 0
    exclusion_reason_counts: dict[str, int] = {}
    structured_labels = {
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
        "HOWTO_SECTION",
        "YIELD_LINE",
        "TIME_LINE",
        "RECIPE_NOTES",
        "RECIPE_VARIANT",
    }
    for row in joined_line_rows:
        label = str(row.get("pred_label") or "OTHER")
        within_recipe_span = row.get("within_recipe_span")
        if within_recipe_span is True:
            inside_recipe_count += 1
            if label in structured_labels:
                recipe_local_label_count += 1
        elif within_recipe_span is False:
            outside_recipe_count += 1
            if label in structured_labels:
                outside_recipe_structured_count += 1
            exclusion_reason = str(row.get("exclusion_reason") or "").strip()
            if label == "NONRECIPE_EXCLUDE" and exclusion_reason:
                outside_recipe_excluded_count += 1
                exclusion_reason_counts[exclusion_reason] = (
                    int(exclusion_reason_counts.get(exclusion_reason) or 0)
                    + 1
                )
            elif label == "NONRECIPE_CANDIDATE":
                outside_recipe_candidate_count += 1
        else:
            unknown_recipe_status_count += 1
    return {
        "schema_version": "line_role_routing_summary.v1",
        "line_count": len(joined_line_rows),
        "inside_recipe_line_count": inside_recipe_count,
        "outside_recipe_line_count": outside_recipe_count,
        "unknown_recipe_status_line_count": unknown_recipe_status_count,
        "recipe_local_label_count": recipe_local_label_count,
        "outside_recipe_structured_count": outside_recipe_structured_count,
        "outside_recipe_candidate_count": outside_recipe_candidate_count,
        "outside_recipe_excluded_count": outside_recipe_excluded_count,
        "exclusion_reason_counts": exclusion_reason_counts,
    }


def build_line_role_knowledge_budget(
    joined_line_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return build_line_role_routing_summary(joined_line_rows)
