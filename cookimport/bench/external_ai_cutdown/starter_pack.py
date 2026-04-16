from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


def _recipe_row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("source_key") or ""),
        str(row.get("codex_run_id") or ""),
        str(row.get("recipe_id") or ""),
    )


def _sort_recipe_rows_for_metric(
    rows: list[dict[str, Any]],
    *,
    metric_key: str,
    coerce_int: Callable[[Any], int | None],
    float_or_zero: Callable[[Any], float],
) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -int(coerce_int(row.get(metric_key)) or 0),
            -abs(float_or_zero(row.get("delta_codex_minus_baseline"))),
            str(row.get("recipe_id") or ""),
        ),
    )


def _select_starter_pack_recipe_cases(
    recipe_triage_rows: list[dict[str, Any]],
    *,
    coerce_int: Callable[[Any], int | None],
    float_or_zero: Callable[[Any], float],
    selection_policy: dict[str, int],
) -> list[dict[str, Any]]:
    def _row_loss_count(row: dict[str, Any]) -> int:
        return int(
            coerce_int(
                row.get("build_intermediate_missing_row_count")
                if row.get("build_intermediate_missing_row_count") is not None
                else row.get("build_intermediate_clamped_row_loss_count")
            )
            or 0
        )

    def _empty_mapping(row: dict[str, Any]) -> bool:
        return bool(
            row.get("final_recipe_empty_mapping") or row.get("correction_empty_mapping")
        )

    def _upstream_input_count(row: dict[str, Any]) -> int:
        return int(
            coerce_int(
                row.get("build_intermediate_selected_row_count")
                if row.get("build_intermediate_selected_row_count") is not None
                else row.get("correction_input_row_count")
            )
            or 0
        )

    def _warning_count(row: dict[str, Any]) -> int:
        return int(coerce_int(row.get("correction_warning_count")) or 0)

    def _instruction_count(row: dict[str, Any]) -> int:
        return int(coerce_int(row.get("correction_step_count")) or 0)

    selected_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    ordered_keys: list[tuple[str, str, str]] = []

    def reason_count(reason: str) -> int:
        return sum(
            1
            for entry in ordered_keys
            if reason in str(selected_by_key[entry].get("selection_reason") or "")
        )

    def add_rows(rows: list[dict[str, Any]], *, limit: int, reason: str) -> None:
        for row in rows:
            key = _recipe_row_key(row)
            if key not in selected_by_key:
                selected_by_key[key] = dict(row)
                selected_by_key[key]["selection_reason"] = reason
                ordered_keys.append(key)
            else:
                existing = str(selected_by_key[key].get("selection_reason") or "")
                if reason not in existing.split(", "):
                    selected_by_key[key]["selection_reason"] = (
                        f"{existing}, {reason}" if existing else reason
                    )
            if len(ordered_keys) >= 10:
                return
            if reason_count(reason) >= limit:
                return

    top_changed = _sort_recipe_rows_for_metric(
        recipe_triage_rows,
        metric_key="changed_lines_codex_vs_baseline",
        coerce_int=coerce_int,
        float_or_zero=float_or_zero,
    )
    add_rows(
        top_changed,
        limit=selection_policy["top_changed_lines"],
        reason="top_changed_lines",
    )

    top_warning_burden = sorted(
        recipe_triage_rows,
        key=lambda row: (
            -_row_loss_count(row),
            -abs(float_or_zero(row.get("delta_codex_minus_baseline"))),
            -int(coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            str(row.get("recipe_id") or ""),
        ),
    )
    top_warning_burden = [row for row in top_warning_burden if _row_loss_count(row) > 0]
    add_rows(
        top_warning_burden,
        limit=selection_policy["top_row_loss"],
        reason="top_row_loss",
    )

    empty_mapping_candidates = [
        row
        for row in recipe_triage_rows
        if _empty_mapping(row)
        and (
            _upstream_input_count(row) >= 8
            or _warning_count(row) >= 2
            or _instruction_count(row) == 0
        )
    ]
    empty_mapping_candidates.sort(
        key=lambda row: (
            -abs(float_or_zero(row.get("delta_codex_minus_baseline"))),
            -int(coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            -_upstream_input_count(row),
            str(row.get("recipe_id") or ""),
        )
    )
    add_rows(
        empty_mapping_candidates,
        limit=selection_policy["top_empty_mapping"],
        reason="top_empty_mapping_upstream_evidence",
    )

    outside_candidates = _sort_recipe_rows_for_metric(
        recipe_triage_rows,
        metric_key="outside_span_wrong_line_count",
        coerce_int=coerce_int,
        float_or_zero=float_or_zero,
    )
    outside_candidates = [
        row
        for row in outside_candidates
        if int(coerce_int(row.get("outside_span_wrong_line_count")) or 0) > 0
    ]
    add_rows(
        outside_candidates,
        limit=selection_policy["outside_span_case"],
        reason="outside_span_contamination",
    )

    healthy_controls = [
        row
        for row in recipe_triage_rows
        if _warning_count(row) == 0
        and not _empty_mapping(row)
    ]
    healthy_controls.sort(
        key=lambda row: (
            -float_or_zero(row.get("codex_accuracy")),
            str(row.get("recipe_id") or ""),
        )
    )
    add_rows(
        healthy_controls,
        limit=selection_policy["healthy_control"],
        reason="healthy_control",
    )

    if len(ordered_keys) < 6:
        for row in top_changed:
            key = _recipe_row_key(row)
            if key in selected_by_key:
                continue
            selected_by_key[key] = dict(row)
            selected_by_key[key]["selection_reason"] = "highest_remaining_signal"
            ordered_keys.append(key)
            if len(ordered_keys) >= min(10, len(recipe_triage_rows)):
                break
            if len(ordered_keys) >= 6:
                break

    return [selected_by_key[key] for key in ordered_keys[:10]]


def _group_changed_lines_by_recipe(
    changed_line_rows: list[dict[str, Any]],
    *,
    coerce_int: Callable[[Any], int | None],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in changed_line_rows:
        recipe_id = str(row.get("recipe_id") or "").strip()
        if not recipe_id:
            continue
        key = (
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
            recipe_id,
        )
        grouped[key].append(row)
    for key in grouped:
        grouped[key].sort(
            key=lambda row: (
                int(coerce_int(row.get("line_index")) or 0),
                str(row.get("gold_label") or ""),
            )
        )
    return grouped


def _bridge_anomaly_summary(
    row: dict[str, Any],
    *,
    coerce_int: Callable[[Any], int | None],
    serialize_bool: Callable[[bool], str],
) -> str:
    chunks = [
        "current_recipe_pipeline=single_correction",
        f"correction_warnings={int(coerce_int(row.get('correction_warning_count')) or 0)}",
        f"correction_empty_mapping={serialize_bool(bool(row.get('correction_empty_mapping')))}",
    ]
    final_mapping_status = str(row.get("final_mapping_status") or "").strip()
    if final_mapping_status:
        chunks.append(f"final_mapping_status={final_mapping_status}")
    if str(row.get("final_mapping_reason") or "").strip():
        chunks.append("final_mapping_reason=yes")
    structural_status = str(row.get("structural_status") or "").strip()
    if structural_status:
        chunks.append(f"structural_status={structural_status}")
    outside_count = int(coerce_int(row.get("outside_span_wrong_line_count")) or 0)
    if outside_count > 0:
        chunks.append(f"outside_span_wrong_lines={outside_count}")
    return ", ".join(chunks)


def _warning_summary_for_recipe(
    row: dict[str, Any],
    *,
    coerce_int: Callable[[Any], int | None],
    serialize_pipe_list: Callable[[list[str]], str],
    coerce_str_list: Callable[[Any], list[str]],
) -> str:
    chunks: list[str] = []
    correction_warning_count = int(coerce_int(row.get("correction_warning_count")) or 0)
    if correction_warning_count > 0:
        chunks.append(
            "recipe_refine"
            f"({correction_warning_count}): "
            f"{serialize_pipe_list(coerce_str_list(row.get('correction_warning_buckets')))}"
        )
    final_mapping_status = str(row.get("final_mapping_status") or "").strip()
    if final_mapping_status:
        chunks.append(f"recipe_build_final_mapping: {final_mapping_status}")
    structural_status = str(row.get("structural_status") or "").strip()
    if structural_status:
        chunks.append(f"structural_status: {structural_status}")
    return "; ".join(chunks) if chunks else "none"


def _build_selected_recipe_packets(
    *,
    selected_recipe_rows: list[dict[str, Any]],
    changed_line_rows: list[dict[str, Any]],
    default_recipe_stages: list[dict[str, str]] | None = None,
    coerce_int: Callable[[Any], int | None],
    coerce_float: Callable[[Any], float | None],
    coerce_str_list: Callable[[Any], list[str]],
    diagnostic_value_has_signal: Callable[[Any], bool],
    bridge_anomaly_summary: Callable[[dict[str, Any]], str],
    warning_summary_for_recipe: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    grouped_changed_lines = _group_changed_lines_by_recipe(
        changed_line_rows,
        coerce_int=coerce_int,
    )
    packets: list[dict[str, Any]] = []
    for row in selected_recipe_rows:
        key = _recipe_row_key(row)
        changed_rows = grouped_changed_lines.get(key, [])
        changed_examples = []
        for changed_row in changed_rows[:8]:
            changed_examples.append(
                {
                    "line_index": int(coerce_int(changed_row.get("line_index")) or 0),
                    "gold_label": str(changed_row.get("gold_label") or ""),
                    "baseline_pred": str(changed_row.get("vanilla_pred") or ""),
                    "codex_pred": str(changed_row.get("codex_pred") or ""),
                    "current_line": str(changed_row.get("current_line") or ""),
                    "previous_line": str(changed_row.get("previous_line") or ""),
                    "next_line": str(changed_row.get("next_line") or ""),
                }
            )

        intermediate_summary = {
            "call_id": str(row.get("build_intermediate_call_id") or ""),
            "status": str(row.get("build_intermediate_status") or ""),
            "input_row_count": int(coerce_int(row.get("correction_input_row_count")) or 0),
            "deterministic_stage": True,
            "clamped_row_loss_count": int(
                coerce_int(row.get("build_intermediate_clamped_row_loss_count")) or 0
            ),
            "clamped_row_loss_ratio": coerce_float(
                row.get("build_intermediate_clamped_row_loss_ratio")
            ),
        }
        correction_summary = {
            "call_id": str(row.get("correction_call_id") or ""),
            "status": str(row.get("correction_status") or ""),
            "input_row_count": int(coerce_int(row.get("correction_input_row_count")) or 0),
            "warning_count": int(coerce_int(row.get("correction_warning_count")) or 0),
            "warning_buckets": coerce_str_list(row.get("correction_warning_buckets")),
            "ingredient_count": int(coerce_int(row.get("correction_ingredient_count")) or 0),
            "step_count": int(coerce_int(row.get("correction_step_count")) or 0),
            "mapping_count": int(coerce_int(row.get("correction_mapping_count")) or 0),
            "empty_mapping": bool(row.get("correction_empty_mapping")),
            "degradation_reasons": coerce_str_list(row.get("correction_degradation_reasons")),
            "degradation_severity": str(row.get("correction_degradation_severity") or ""),
            "promotion_policy": str(row.get("correction_promotion_policy") or ""),
        }
        final_summary = {
            "call_id": str(row.get("build_final_call_id") or ""),
            "status": str(row.get("build_final_status") or ""),
            "mapping_status": str(row.get("final_mapping_status") or ""),
            "mapping_reason": str(row.get("final_mapping_reason") or ""),
            "structural_status": str(row.get("structural_status") or ""),
            "structural_reason_codes": coerce_str_list(row.get("structural_reason_codes")),
            "execution_mode": str(row.get("build_final_execution_mode") or ""),
            "routing_reason": str(row.get("build_final_routing_reason") or ""),
            "fallback_reason": str(row.get("build_final_fallback_reason") or ""),
        }
        recipe_quality_summary = {
            "warning_count": int(coerce_int(row.get("recipe_warning_count")) or 0),
            "error_count": int(coerce_int(row.get("recipe_error_count")) or 0),
        }
        transport_summary: dict[str, Any] = {}
        evidence_normalization_summary = {
            "split_quantity_lines": int(coerce_int(row.get("evidence_split_quantity_lines")) or 0),
            "dropped_page_markers": int(coerce_int(row.get("evidence_dropped_page_markers")) or 0),
            "folded_page_markers": int(coerce_int(row.get("evidence_folded_page_markers")) or 0),
        }
        if not any(
            diagnostic_value_has_signal(value)
            for value in evidence_normalization_summary.values()
        ):
            evidence_normalization_summary = {}
        recipe_stages = row.get("recipe_stages")
        recipe_stages = recipe_stages if isinstance(recipe_stages, list) else []
        if not recipe_stages:
            recipe_stages = list(default_recipe_stages or [])
        recipe_stage_summaries: list[dict[str, Any]] = []
        for recipe_stage in recipe_stages:
            if not isinstance(recipe_stage, dict):
                continue
            stage_key = str(recipe_stage.get("stage_key") or "").strip()
            stage_label = str(recipe_stage.get("stage_label") or stage_key).strip()
            if stage_key == "recipe_build_intermediate":
                recipe_stage_summaries.append(
                    {"stage_key": stage_key, "stage_label": stage_label, **intermediate_summary}
                )
                continue
            if stage_key == "recipe_refine":
                recipe_stage_summaries.append(
                    {"stage_key": stage_key, "stage_label": stage_label, **correction_summary}
                )
                continue
            if stage_key == "recipe_build_final":
                recipe_stage_summaries.append(
                    {"stage_key": stage_key, "stage_label": stage_label, **final_summary}
                )
                continue
        packets.append(
            {
                "selection_reason": str(row.get("selection_reason") or ""),
                "source_key": str(row.get("source_key") or ""),
                "codex_run_id": str(row.get("codex_run_id") or row.get("run_id") or ""),
                "baseline_run_id": str(row.get("baseline_run_id") or ""),
                "recipe_pipeline_id": str(row.get("recipe_pipeline_id") or ""),
                "recipe_stages": recipe_stage_summaries,
                "recipe_id": str(row.get("recipe_id") or ""),
                "short_title": str(row.get("short_title") or ""),
                "delta_codex_minus_baseline": coerce_float(row.get("delta_codex_minus_baseline")),
                "changed_lines_codex_vs_baseline": int(
                    coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0
                ),
                "bridge_anomaly_summary": bridge_anomaly_summary(row),
                "warning_summary": warning_summary_for_recipe(row),
                "build_intermediate_summary": intermediate_summary,
                "correction_summary": correction_summary,
                "build_final_summary": final_summary,
                "recipe_quality_summary": recipe_quality_summary,
                "transport_summary": transport_summary,
                "evidence_normalization_summary": evidence_normalization_summary,
                "changed_line_examples": changed_examples,
                "raw_block_window_excerpt": str(row.get("raw_block_window_excerpt") or ""),
            }
        )
    return packets


def _render_starter_pack_casebook(
    packets: list[dict[str, Any]],
    *,
    coerce_int: Callable[[Any], int | None],
    excerpt: Callable[..., str],
) -> str:
    lines = [
        "# Starter Pack Casebook",
        "",
        "Deterministic selected cases for first-pass benchmark and bridge diagnosis.",
        "",
    ]
    if not packets:
        lines.append("No recipe cases were selected.")
        lines.append("")
        return "\n".join(lines)

    for index, packet in enumerate(packets, start=1):
        recipe_pipeline_id = str(packet.get("recipe_pipeline_id") or "").strip()
        recipe_stages = packet.get("recipe_stages")
        recipe_stages = recipe_stages if isinstance(recipe_stages, list) else []
        recipe_stage_labels = [
            str(stage.get("stage_label") or stage.get("stage_key") or "").strip()
            for stage in recipe_stages
            if isinstance(stage, dict)
        ]
        lines.extend(
            [
                f"## Case {index}: {packet.get('recipe_id')}",
                f"- selection_reason: {packet.get('selection_reason')}",
                f"- short_title: {packet.get('short_title')}",
                f"- changed_lines_codex_vs_baseline: {packet.get('changed_lines_codex_vs_baseline')}",
                f"- bridge_anomaly_summary: {packet.get('bridge_anomaly_summary')}",
                f"- warning_summary: {packet.get('warning_summary')}",
                *([f"- recipe_pipeline_id: {recipe_pipeline_id}"] if recipe_pipeline_id else []),
                *([f"- recipe_stages: {', '.join(recipe_stage_labels)}"] if recipe_stage_labels else []),
                "",
                "### Stage Excerpts",
                (
                    "- recipe_build_intermediate: "
                    f"status={packet.get('build_intermediate_summary', {}).get('status')} "
                    "deterministic_stage=yes "
                    f"input_row_count={packet.get('build_intermediate_summary', {}).get('input_row_count')}"
                ),
                (
                    "- recipe_quality: "
                    f"warnings={packet.get('recipe_quality_summary', {}).get('warning_count')} "
                    f"errors={packet.get('recipe_quality_summary', {}).get('error_count')}"
                ),
                "",
            ]
        )
        for recipe_stage in recipe_stages:
            if not isinstance(recipe_stage, dict):
                continue
            stage_label = str(recipe_stage.get("stage_label") or recipe_stage.get("stage_key") or "")
            stage_key = str(recipe_stage.get("stage_key") or "")
            if stage_key == "recipe_build_intermediate":
                lines.append(
                    f"- {stage_label}: status={recipe_stage.get('status')} deterministic_stage=yes"
                )
                continue
            if stage_key == "recipe_refine":
                lines.append(
                    f"- {stage_label}: call_id={recipe_stage.get('call_id')} "
                    f"status={recipe_stage.get('status')} "
                    f"input_row_count={recipe_stage.get('input_row_count')} "
                    f"warning_count={recipe_stage.get('warning_count')} "
                    f"ingredient_count={recipe_stage.get('ingredient_count')} "
                    f"step_count={recipe_stage.get('step_count')} "
                    f"mapping_count={recipe_stage.get('mapping_count')} "
                    f"empty_mapping={recipe_stage.get('empty_mapping')}"
                )
                continue
            lines.append(
                f"- {stage_label}: status={recipe_stage.get('status')} "
                f"mapping_status={recipe_stage.get('mapping_status')} "
                f"structural_status={recipe_stage.get('structural_status')} "
                f"mapping_reason={'yes' if str(recipe_stage.get('mapping_reason') or '').strip() else 'no'}"
            )
        lines.append("")
        raw_excerpt = str(packet.get("raw_block_window_excerpt") or "").strip()
        if raw_excerpt:
            lines.extend(["### Raw Block Window Excerpt", "", raw_excerpt, ""])

        changed_examples = packet.get("changed_line_examples")
        changed_rows = changed_examples if isinstance(changed_examples, list) else []
        lines.append("### Changed Canonical Lines")
        lines.append("")
        if not changed_rows:
            lines.append("No changed canonical lines recorded for this recipe in this pair.")
            lines.append("")
            continue
        for changed_row in changed_rows[:8]:
            if not isinstance(changed_row, dict):
                continue
            lines.append(
                f"- line {int(coerce_int(changed_row.get('line_index')) or 0)} | "
                f"gold={changed_row.get('gold_label')} | "
                f"baseline={changed_row.get('baseline_pred')} | "
                f"codex={changed_row.get('codex_pred')} | "
                f"text={excerpt(str(changed_row.get('current_line') or ''), max_len=260)}"
            )
        lines.append("")
    return "\n".join(lines)


def _render_starter_pack_label_policy() -> str:
    lines = [
        "# Label Policy",
        "",
        "## Policy Notes",
        "",
        "- Treat labels as canonical line-space classes from benchmark evaluation artifacts.",
        "- Prefer recipe-local interpretations (`RECIPE_NOTES`) over broad `KNOWLEDGE` when context is inside an active recipe.",
        "- Keep benchmark adjudication deterministic: compare codex vs baseline using the same canonical text and line indices.",
        "",
        "## Known Structural Label Conventions",
        "",
        "- `RECIPE_TITLE`: canonical recipe name line.",
        "- `RECIPE_VARIANT`: explicit variant/alternative version wording.",
        "- `INGREDIENT_LINE`: ingredient inventory line.",
        "- `INSTRUCTION_LINE`: imperative cooking action line.",
        "- `HOWTO_SECTION`: section header-style line that introduces grouped instructions or ingredients.",
        "",
        "## How to Read False Positives/False Negatives",
        "",
        "- False positive: prediction label is present but does not match the gold line label.",
        "- False negative: gold label line was not predicted as that label.",
        "- Use changed-line context (`previous_line`, `current_line`, `next_line`) before escalating to full prompt/archive artifacts.",
        "",
    ]
    return "\n".join(lines)


def _write_starter_pack_readme(
    *,
    output_path: Path,
    comparison_summary: dict[str, Any],
    starter_pack_dir_name: str,
    starter_pack_triage_file_name: str,
    starter_pack_triage_packet_file_name: str,
    starter_pack_call_inventory_file_name: str,
    starter_pack_changed_lines_file_name: str,
    starter_pack_warning_trace_summary_file_name: str,
    starter_pack_bridge_summary_file_name: str,
    starter_pack_selected_packets_file_name: str,
    starter_pack_casebook_file_name: str,
    starter_pack_outside_trace_file_name: str,
    starter_pack_label_policy_file_name: str,
    starter_pack_manifest_file_name: str,
    starter_pack_comparison_mirror_file_name: str,
    starter_pack_breakdown_mirror_file_name: str,
    starter_pack_net_error_blame_file_name: str,
    starter_pack_config_version_metadata_file_name: str,
    starter_pack_explicit_escalation_changed_lines_file_name: str,
    starter_pack_baseline_trace_parity_file_name: str,
    timestamp_now: Callable[[], str],
) -> None:
    pair_count = len(comparison_summary.get("pairs") or [])
    lines = [
        "# Starter Pack v1",
        "",
        "## Source and Pairing",
        "",
        (
            "Codex runs are paired against nearest-timestamp baseline runs within each source key. "
            f"Pair count: {pair_count}."
        ),
        "",
        "## Benchmark Contract",
        "",
        "Canonical line-space scoring compares codex and baseline labels against the same gold canonical lines.",
        "",
        "## Label Ontology Cheat Sheet",
        "",
        "Common labels: `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `RECIPE_NOTES`, `OTHER`.",
        "",
        "## Starter Pack Inventory",
        "",
        "- `00_run_overview.md`",
        f"- `{starter_pack_triage_file_name}`",
        f"- `{starter_pack_triage_packet_file_name}`",
        f"- `{starter_pack_call_inventory_file_name}`",
        f"- `{starter_pack_changed_lines_file_name}`",
        f"- `{starter_pack_warning_trace_summary_file_name}`",
        f"- `{starter_pack_bridge_summary_file_name}`",
        f"- `{starter_pack_selected_packets_file_name}`",
        f"- `{starter_pack_casebook_file_name}`",
        f"- `{starter_pack_outside_trace_file_name}` (conditional)",
        f"- `{starter_pack_label_policy_file_name}`",
        f"- `{starter_pack_manifest_file_name}`",
        f"- `{starter_pack_comparison_mirror_file_name}`",
        f"- `{starter_pack_breakdown_mirror_file_name}`",
        f"- `{starter_pack_net_error_blame_file_name}`",
        f"- `{starter_pack_config_version_metadata_file_name}`",
        f"- `{starter_pack_explicit_escalation_changed_lines_file_name}`",
        f"- `{starter_pack_baseline_trace_parity_file_name}`",
        "",
        "## Follow-up Packet Rules",
        "",
        "Use this starter pack for first-pass triage. Request heavy artifacts only for selected cases.",
        "",
        "## Generated At",
        "",
        timestamp_now(),
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")
