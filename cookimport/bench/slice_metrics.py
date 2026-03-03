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


def build_line_role_knowledge_budget(
    joined_line_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    inside_count = 0
    outside_count = 0
    for row in joined_line_rows:
        label = str(row.get("pred_label") or "OTHER")
        if label != "KNOWLEDGE":
            continue
        if bool(row.get("within_recipe_span")):
            inside_count += 1
        else:
            outside_count += 1
    total = inside_count + outside_count
    return {
        "schema_version": "line_role_knowledge_budget.v1",
        "line_count": len(joined_line_rows),
        "knowledge_pred_total": total,
        "knowledge_pred_inside_recipe": inside_count,
        "knowledge_pred_outside_recipe": outside_count,
        "knowledge_inside_ratio": (inside_count / total) if total else 0.0,
    }
