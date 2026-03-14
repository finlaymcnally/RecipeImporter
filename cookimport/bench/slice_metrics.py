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


def build_line_role_pass4_merge_summary(
    joined_line_rows: list[dict[str, Any]],
    pass4_merge_changed_rows: list[dict[str, Any]],
    *,
    merge_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    joined_by_line_index: dict[int, dict[str, Any]] = {}
    for row in joined_line_rows:
        try:
            line_index = int(row.get("line_index"))
        except (TypeError, ValueError):
            continue
        joined_by_line_index[line_index] = row

    matching_gold = 0
    wrong_after_merge = 0
    missing_eval_row = 0
    changed_to_knowledge = 0
    changed_to_knowledge_gold_knowledge = 0
    changed_to_knowledge_gold_other = 0
    changed_outside_recipe = 0

    for row in pass4_merge_changed_rows:
        try:
            line_index = int(row.get("line_index"))
        except (TypeError, ValueError):
            missing_eval_row += 1
            continue
        joined_row = joined_by_line_index.get(line_index)
        if joined_row is None:
            missing_eval_row += 1
            continue
        if not bool(joined_row.get("within_recipe_span")):
            changed_outside_recipe += 1
        gold_label = str(joined_row.get("gold_label") or "OTHER")
        new_label = str(row.get("new_label") or "OTHER")
        if gold_label == new_label:
            matching_gold += 1
        else:
            wrong_after_merge += 1
        if new_label == "KNOWLEDGE":
            changed_to_knowledge += 1
            if gold_label == "KNOWLEDGE":
                changed_to_knowledge_gold_knowledge += 1
            elif gold_label == "OTHER":
                changed_to_knowledge_gold_other += 1

    payload: dict[str, Any] = {
        "schema_version": "line_role_pass4_merge_summary.v1",
        "changed_line_count": len(pass4_merge_changed_rows),
        "changed_outside_recipe_count": changed_outside_recipe,
        "changed_lines_matching_gold": matching_gold,
        "changed_lines_wrong": wrong_after_merge,
        "changed_lines_missing_eval_row": missing_eval_row,
        "changed_to_knowledge_count": changed_to_knowledge,
        "changed_to_knowledge_gold_knowledge": changed_to_knowledge_gold_knowledge,
        "changed_to_knowledge_gold_other": changed_to_knowledge_gold_other,
    }
    if isinstance(merge_report, dict):
        payload["merge_report"] = {
            "merge_mode": merge_report.get("merge_mode"),
            "usable_evidence": merge_report.get("usable_evidence"),
            "selected_block_count": merge_report.get("selected_block_count"),
            "selected_line_count": merge_report.get("selected_line_count"),
            "upgraded_other_to_knowledge_count": merge_report.get(
                "upgraded_other_to_knowledge_count"
            ),
            "downgraded_knowledge_to_other_count": merge_report.get(
                "downgraded_knowledge_to_other_count"
            ),
        }
    return payload
