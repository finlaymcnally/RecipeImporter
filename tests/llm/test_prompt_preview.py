from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cookimport.cf_debug_cli import app
from cookimport.llm.prompt_budget import build_prompt_preview_budget_summary
from cookimport.llm.prompt_preview import write_prompt_preview_for_existing_run


REPO_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_existing_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "processed-run"
    workbook_slug = "fixturebook"
    source_hash = "fixture-source-hash"

    _write_json(
        run_dir / "fixturebook.excel_import_report.json",
        {
            "sourceFile": "fixturebook.epub",
            "runConfig": {
                "atomic_block_splitter": "atomic-v1",
            },
        },
    )
    _write_json(
        run_dir / "raw" / "epub" / source_hash / "full_text.json",
        {
            "block_count": 4,
            "blocks": [
                {"index": 100, "text": "Ambiguous title-ish line"},
                {"index": 101, "text": "1 cup flour"},
                {"index": 102, "text": "Pan heat matters."},
                {"index": 103, "text": "Advertisement copy."},
            ],
        },
    )
    _write_json(
        run_dir / "group_recipe_spans" / workbook_slug / "authoritative_block_labels.json",
        {
            "schema_version": "authoritative_block_labels.v1",
            "workbook_slug": workbook_slug,
            "block_labels": [
                {
                    "source_block_id": "block:0",
                    "source_block_index": 0,
                    "supporting_atomic_indices": [0],
                    "deterministic_label": "RECIPE_TITLE",
                    "final_label": "RECIPE_TITLE",
                    "decided_by": "fallback",
                    "reason_tags": ["title_like"],
                    "escalation_reasons": ["deterministic_unresolved", "fallback_decision"],
                },
                {
                    "source_block_id": "block:1",
                    "source_block_index": 1,
                    "supporting_atomic_indices": [1],
                    "deterministic_label": "INGREDIENT_LINE",
                    "final_label": "INGREDIENT_LINE",
                    "decided_by": "rule",
                    "reason_tags": ["ingredient_like"],
                    "escalation_reasons": [],
                },
                {
                    "source_block_id": "block:2",
                    "source_block_index": 2,
                    "supporting_atomic_indices": [2],
                    "deterministic_label": "KNOWLEDGE",
                    "final_label": "KNOWLEDGE",
                    "decided_by": "rule",
                    "reason_tags": ["knowledge_like"],
                    "escalation_reasons": [],
                },
                {
                    "source_block_id": "block:3",
                    "source_block_index": 3,
                    "supporting_atomic_indices": [3],
                    "deterministic_label": "OTHER",
                    "final_label": "OTHER",
                    "decided_by": "rule",
                    "reason_tags": ["other"],
                    "escalation_reasons": [],
                },
            ],
        },
    )
    _write_json(
        run_dir / "group_recipe_spans" / workbook_slug / "recipe_spans.json",
        {
            "schema_version": "group_recipe_spans.v1",
            "workbook_slug": workbook_slug,
            "recipe_spans": [
                {
                    "span_id": "recipe_span_0",
                    "start_block_index": 0,
                    "end_block_index": 1,
                    "block_indices": [0, 1],
                    "source_block_ids": ["block:0", "block:1"],
                    "start_atomic_index": 0,
                    "end_atomic_index": 1,
                    "atomic_indices": [0, 1],
                    "title_block_index": 0,
                    "title_atomic_index": 0,
                    "warnings": [],
                    "escalation_reasons": [],
                    "decision_notes": [],
                }
            ],
        },
    )
    label_det_dir = run_dir / "label_det" / workbook_slug
    label_det_dir.mkdir(parents=True, exist_ok=True)
    (label_det_dir / "labeled_lines.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in [
                {
                    "atomic_index": 0,
                    "source_block_id": "block:0",
                    "source_block_index": 0,
                    "text": "Ambiguous title-ish line",
                    "label": "RECIPE_TITLE",
                    "final_label": "RECIPE_TITLE",
                    "decided_by": "fallback",
                    "reason_tags": ["title_like"],
                    "escalation_reasons": [
                        "deterministic_unresolved",
                        "fallback_decision",
                    ],
                },
                {
                    "atomic_index": 1,
                    "source_block_id": "block:1",
                    "source_block_index": 1,
                    "text": "1 cup flour",
                    "label": "INGREDIENT_LINE",
                    "final_label": "INGREDIENT_LINE",
                    "decided_by": "rule",
                    "reason_tags": ["ingredient_like"],
                    "escalation_reasons": [],
                },
                {
                    "atomic_index": 2,
                    "source_block_id": "block:2",
                    "source_block_index": 2,
                    "text": "Pan heat matters.",
                    "label": "KNOWLEDGE",
                    "final_label": "KNOWLEDGE",
                    "decided_by": "rule",
                    "reason_tags": ["knowledge_like"],
                    "escalation_reasons": [],
                },
                {
                    "atomic_index": 3,
                    "source_block_id": "block:3",
                    "source_block_index": 3,
                    "text": "Advertisement copy.",
                    "label": "OTHER",
                    "final_label": "OTHER",
                    "decided_by": "rule",
                    "reason_tags": ["other"],
                    "escalation_reasons": [],
                },
            ]
        ),
        encoding="utf-8",
    )
    _write_json(
        run_dir / "intermediate drafts" / workbook_slug / "r0.jsonld",
        {
            "@context": ["https://schema.org"],
            "@id": "urn:recipe:test:r0",
            "identifier": "urn:recipe:test:r0",
            "name": "Ambiguous title-ish line",
            "recipeIngredient": ["1 cup flour"],
            "recipeInstructions": [],
            "recipeimport:provenance": {
                "source_hash": source_hash,
                "location": {
                    "start_block": 0,
                    "end_block": 1,
                    "recipe_span_id": "recipe_span_0",
                },
            },
        },
    )
    _write_json(
        run_dir / "final drafts" / workbook_slug / "r0.json",
        {
            "title": "Ambiguous title-ish line",
            "ingredients": [{"raw_text": "1 cup flour"}],
            "steps": [],
            "source": "fixturebook.epub",
        },
    )
    return run_dir


def _write_worker_status(path: Path, row: dict[str, int]) -> None:
    _write_json(
        path,
        {
            "telemetry": {
                "rows": [row],
            },
            "telemetry_report": {
                "summary": {
                    "call_count": 1,
                    "tokens_input": row.get("tokens_input"),
                    "tokens_cached_input": row.get("tokens_cached_input"),
                    "tokens_output": row.get("tokens_output"),
                    "tokens_total": row.get("tokens_total"),
                }
            },
        },
    )


def test_prompt_preview_rebuilds_recipe_knowledge_and_line_role_prompts(
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    out_dir = tmp_path / "preview"

    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"] == {
        "knowledge_interaction_count": 0,
        "line_role_interaction_count": 1,
        "recipe_interaction_count": 1,
    }
    assert any(
        warning["code"] == "token_estimate_unavailable"
        for warning in manifest["warnings"]
    )
    assert manifest["surfaces"] == {
        "llm_recipe_pipeline": "codex-recipe-shard-v1",
        "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
        "line_role_pipeline": "codex-line-role-shard-v1",
    }
    phase_plans = manifest["phase_plans"]
    assert phase_plans["recipe_llm_correct_and_link"]["worker_count"] == 1
    assert phase_plans["recipe_llm_correct_and_link"]["shard_count"] == 1
    assert phase_plans["recipe_llm_correct_and_link"]["shards"][0]["owned_ids"] == [
        "urn:recipe:test:r0"
    ]
    assert phase_plans["line_role"]["worker_count"] == 1
    assert phase_plans["line_role"]["shard_count"] == 1
    assert phase_plans["line_role"]["shards"][0]["owned_ids"] == ["0", "1", "2", "3"]
    artifacts = manifest["artifacts"]
    assert artifacts["prompt_preview_budget_summary_json"] == "prompt_preview_budget_summary.json"
    assert artifacts["prompt_preview_budget_summary_md"] == "prompt_preview_budget_summary.md"

    full_prompt_rows = [
        json.loads(line)
        for line in (out_dir / "prompts" / "full_prompt_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert {row["stage_key"] for row in full_prompt_rows} == {
        "line_role",
        "recipe_llm_correct_and_link",
    }
    recipe_row = next(row for row in full_prompt_rows if row["stage_key"] == "recipe_llm_correct_and_link")
    assert "Read the authoritative shard JSON file at" in recipe_row["rendered_prompt_text"]
    assert "recipe-preview-shard-0001-r0.json" in recipe_row["rendered_prompt_text"]
    assert recipe_row["runtime_shard_id"] == "recipe-preview-shard-0001-r0"
    assert recipe_row["runtime_worker_id"] == "worker-001"
    assert recipe_row["runtime_owned_ids"] == ["urn:recipe:test:r0"]
    recipe_input_payload = json.loads(
        (
            out_dir
            / "raw"
            / "llm"
            / "fixturebook"
            / "recipe_llm_correct_and_link"
            / "in"
            / "recipe-preview-shard-0001-r0.json"
        ).read_text(encoding="utf-8")
    )
    assert "draft_hint" not in recipe_input_payload
    assert "provenance" not in recipe_input_payload["recipes"][0]["recipe_candidate_hint"]
    assert recipe_input_payload["tagging_guide"]["version"] == "recipe_tagging_guide.v1"
    assert recipe_input_payload["owned_recipe_ids"] == ["urn:recipe:test:r0"]

    line_role_row = next(row for row in full_prompt_rows if row["stage_key"] == "line_role")
    assert "Execute the line-role labeling task exactly." in line_role_row["rendered_prompt_text"]
    assert "line_role_prompt_0001.json" in line_role_row["rendered_prompt_text"]
    embedded_line_role_prompt = line_role_row["task_prompt_text"]
    assert "Compact input legends:" in embedded_line_role_prompt
    assert "Recipe atomic index ranges for this batch: 0-1" in embedded_line_role_prompt
    assert "RECIPE_TITLE" in embedded_line_role_prompt
    assert "KNOWLEDGE" in embedded_line_role_prompt
    assert "deterministic_unresolved" in embedded_line_role_prompt
    assert "fallback_decision" in embedded_line_role_prompt
    assert "Advertisement copy." in embedded_line_role_prompt
    assert line_role_row["request_input_payload"]["shard_id"].startswith("line-role-shard-0001")
    assert [row["atomic_index"] for row in line_role_row["request_input_payload"]["rows"]] == [
        0,
        1,
        2,
        3,
    ]
    assert line_role_row["request_input_text"] == embedded_line_role_prompt
    assert line_role_row["runtime_worker_id"] == "worker-001"
    assert line_role_row["runtime_owned_ids"] == ["0", "1", "2", "3"]
    assert (
        out_dir / "line-role-pipeline" / "in" / "line_role_prompt_0001.json"
    ).read_text(encoding="utf-8") == embedded_line_role_prompt

    assert (
        out_dir
        / "raw"
        / "llm"
        / "fixturebook"
        / "recipe_llm_correct_and_link"
        / "in"
        / "recipe-preview-shard-0001-r0.json"
    ).is_file()
    assert (out_dir / "line-role-pipeline" / "in" / "line_role_prompt_0001.json").is_file()
    assert (out_dir / "prompts" / "prompt_type_samples_from_full_prompt_log.md").is_file()
    budget_summary = json.loads(
        (out_dir / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
    )
    assert budget_summary["totals"]["call_count"] == 2
    assert budget_summary["totals"]["task_prompt_chars_total"] > 0
    assert budget_summary["totals"]["estimated_request_chars_total"] > budget_summary["totals"]["prompt_chars_total"]
    assert budget_summary["totals"]["transport_overhead_chars_total"] == 0
    line_role_budget = budget_summary["by_stage"]["line_role"]
    assert line_role_budget["worker_count"] == 1
    assert line_role_budget["shard_count"] == 1
    assert line_role_budget["owned_ids_per_shard"]["avg"] == 4.0
    assert line_role_budget["task_prompt_chars_total"] > line_role_budget["prompt_chars_total"]
    assert line_role_budget["transport_overhead_chars_total"] == 0
    assert any(
        warning["code"] == "token_estimate_unavailable"
        for warning in budget_summary["warnings"]
    )
    budget_summary_md = (out_dir / "prompt_preview_budget_summary.md").read_text(encoding="utf-8")
    assert "Workers" in budget_summary_md
    assert "Prompt Detail" in budget_summary_md
    assert "unavailable" in budget_summary_md
    assert (out_dir / "prompt_preview_budget_summary.md").is_file()


def test_prompt_preview_prefers_existing_live_codex_inputs(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    workbook_slug = "fixturebook"
    live_recipe_input = run_dir / "raw" / "llm" / workbook_slug / "recipe_correction" / "in" / "live_recipe.json"
    live_recipe_payload = {
        "bundle_version": "1",
        "recipe_id": "urn:recipe:test:live",
        "workbook_slug": workbook_slug,
        "source_hash": "fixture-source-hash",
        "canonical_text": "LIVE canonical text",
        "evidence_rows": [[42, "LIVE canonical text"]],
        "recipe_candidate_hint": {
            "identifier": "urn:recipe:test:live",
            "name": "Live Recipe Name",
            "recipeIngredient": ["2 tbsp butter"],
            "recipeInstructions": ["Melt the butter."],
            "description": None,
            "recipeYield": None,
        },
        "tagging_guide": {"version": "custom-live-guide"},
        "authority_notes": ["live_artifact_reuse"],
    }
    _write_json(live_recipe_input, live_recipe_payload)

    live_knowledge_input = run_dir / "raw" / "llm" / workbook_slug / "knowledge" / "in" / "live_knowledge.json"
    live_knowledge_payload = {
        "bundle_version": "2",
        "bundle_id": "fixturebook.kb9999.nr",
        "chunks": [
            {
                "chunk_id": "fixturebook.c9999.nr",
                "block_start_index": 7,
                "block_end_index": 8,
                "blocks": [{"block_index": 7, "text": "Live knowledge block."}],
                "heuristics": {"suggested_lane": "knowledge", "suggested_highlights": []},
            }
        ],
        "context": {"blocks_before": [], "blocks_after": []},
        "guardrails": {"context_recipe_block_indices": []},
    }
    _write_json(live_knowledge_input, live_knowledge_payload)

    out_dir = tmp_path / "preview"
    write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
        estimation_mode="observed",
    )

    copied_recipe_input = (
        out_dir
        / "raw"
        / "llm"
        / workbook_slug
        / "recipe_llm_correct_and_link"
        / "in"
        / "recipe-preview-shard-0001-live_recipe.json"
    )
    copied_knowledge_input = (
        out_dir
        / "raw"
        / "llm"
        / workbook_slug
        / "extract_knowledge_optional"
        / "in"
        / "live_knowledge.json"
    )
    copied_recipe_payload = json.loads(copied_recipe_input.read_text(encoding="utf-8"))
    assert copied_recipe_payload["owned_recipe_ids"] == ["urn:recipe:test:live"]
    assert copied_recipe_payload["recipes"] == [
        {
            "canonical_text": "LIVE canonical text",
            "evidence_rows": [[42, "LIVE canonical text"]],
            "recipe_candidate_hint": {
                "description": None,
                "identifier": "urn:recipe:test:live",
                "name": "Live Recipe Name",
                "recipeIngredient": ["2 tbsp butter"],
                "recipeInstructions": ["Melt the butter."],
                "recipeYield": None,
            },
            "recipe_id": "urn:recipe:test:live",
            "warnings": [],
        }
    ]
    assert copied_recipe_payload["tagging_guide"] == {"version": "custom-live-guide"}
    assert copied_recipe_payload["authority_notes"] == ["live_artifact_reuse"]
    assert copied_knowledge_input.read_text(encoding="utf-8") == live_knowledge_input.read_text(encoding="utf-8")

    full_prompt_rows = [
        json.loads(line)
        for line in (out_dir / "prompts" / "full_prompt_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    recipe_row = next(row for row in full_prompt_rows if row["stage_key"] == "recipe_llm_correct_and_link")
    knowledge_row = next(row for row in full_prompt_rows if row["stage_key"] == "extract_knowledge_optional")
    assert "Read the authoritative shard JSON file at" in recipe_row["rendered_prompt_text"]
    assert "LIVE canonical text" in recipe_row["request_input_text"]
    assert recipe_row["recipe_id"] == "urn:recipe:test:live"
    assert "Read the input JSON file at" in knowledge_row["rendered_prompt_text"]
    assert knowledge_row["task_prompt_text"] == knowledge_row["request_input_text"]
    assert "Live knowledge block." in knowledge_row["request_input_text"]
    assert knowledge_row["recipe_id"] == "fixturebook.c9999.nr"

    budget_summary = json.loads(
        (out_dir / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
    )
    knowledge_budget = budget_summary["by_stage"]["extract_knowledge_optional"]
    assert knowledge_budget["task_prompt_chars_total"] > 0
    assert (
        knowledge_budget["estimated_request_chars_total"]
        == knowledge_budget["task_prompt_chars_total"] + knowledge_budget["prompt_chars_total"]
    )


def test_prompt_preview_budget_prefers_live_stage_telemetry_when_available(
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    workbook_slug = "fixturebook"

    live_knowledge_input = run_dir / "raw" / "llm" / workbook_slug / "knowledge" / "in" / "live_knowledge.json"
    _write_json(
        live_knowledge_input,
        {
            "bundle_version": "2",
            "bundle_id": "fixturebook.kb0001.nr",
            "chunks": [
                {
                    "chunk_id": "fixturebook.c0001.nr",
                    "block_start_index": 7,
                    "block_end_index": 8,
                    "blocks": [{"block_index": 7, "text": "Live knowledge block."}],
                    "heuristics": {"suggested_lane": "knowledge", "suggested_highlights": []},
                }
            ],
            "context": {"blocks_before": [], "blocks_after": []},
            "guardrails": {"context_recipe_block_indices": []},
        },
    )

    _write_worker_status(
        run_dir
        / "raw"
        / "llm"
        / workbook_slug
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "status.json",
        {
            "tokens_input": 250,
            "tokens_cached_input": 25,
            "tokens_output": 45,
            "tokens_total": 295,
        },
    )
    _write_worker_status(
        run_dir
        / "raw"
        / "llm"
        / workbook_slug
        / "knowledge"
        / "workers"
        / "worker-001"
        / "status.json",
        {
            "tokens_input": 200,
            "tokens_cached_input": 20,
            "tokens_output": 30,
            "tokens_total": 230,
        },
    )
    _write_json(
        run_dir / "line-role-pipeline" / "telemetry_summary.json",
        {
            "summary": {
                "batch_count": 1,
                "attempt_count": 1,
                "tokens_input": 500,
                "tokens_cached_input": 50,
                "tokens_output": 60,
                "tokens_total": 560,
            }
        },
    )

    out_dir = tmp_path / "preview"
    write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
        estimation_mode="observed",
    )

    budget_summary = json.loads(
        (out_dir / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
    )
    assert budget_summary["estimation_method"]["type"] == "observed_live_telemetry"
    assert budget_summary["estimation_method"]["mode"] == "observed"
    assert budget_summary["totals"]["estimated_cached_input_tokens"] == 95
    assert budget_summary["totals"]["estimated_input_tokens"] == 950
    assert budget_summary["totals"]["estimated_output_tokens"] == 135
    assert budget_summary["totals"]["estimated_total_tokens"] == 1085

    recipe_budget = budget_summary["by_stage"]["recipe_llm_correct_and_link"]
    assert recipe_budget["estimation_basis"] == "live_telemetry"
    assert recipe_budget["estimated_input_tokens"] == 250
    assert recipe_budget["estimated_cached_input_tokens"] == 25
    assert recipe_budget["estimated_output_tokens"] == 45
    assert recipe_budget["estimated_total_tokens"] == 295

    knowledge_budget = budget_summary["by_stage"]["extract_knowledge_optional"]
    assert knowledge_budget["estimation_basis"] == "live_telemetry"
    assert knowledge_budget["estimated_input_tokens"] == 200
    assert knowledge_budget["estimated_cached_input_tokens"] == 20
    assert knowledge_budget["estimated_output_tokens"] == 30
    assert knowledge_budget["estimated_total_tokens"] == 230

    line_role_budget = budget_summary["by_stage"]["line_role"]
    assert line_role_budget["estimation_basis"] == "live_telemetry"
    assert line_role_budget["estimated_input_tokens"] == 500
    assert line_role_budget["estimated_cached_input_tokens"] == 50
    assert line_role_budget["estimated_output_tokens"] == 60
    assert line_role_budget["estimated_total_tokens"] == 560

    budget_summary_md = (out_dir / "prompt_preview_budget_summary.md").read_text(encoding="utf-8")
    assert "retrospective, not predictive" in budget_summary_md
    assert "live_telemetry" in budget_summary_md


def test_prompt_preview_budget_uses_historical_calibration_when_live_missing() -> None:
    summary = build_prompt_preview_budget_summary(
        prompt_rows=[
            {
                "stage_key": "line_role",
                "rendered_prompt_text": "wrapper",
                "prompt_input_mode": "path",
                "task_prompt_text": "x" * 1000,
            }
        ],
        preview_dir=Path("/tmp/preview"),
        phase_plans=None,
        live_stage_summaries={},
        stage_calibrations={
            "line_role": {
                "stage": "line_role",
                "sample_count": 2,
                "input_tokens_per_request_char": 4.0,
                "output_tokens_per_request_char": 0.2,
                "total_tokens_per_request_char": 4.2,
                "total_tokens_per_request_char_low": 3.5,
                "total_tokens_per_request_char_high": 5.1,
                "cached_input_share": 0.7,
            }
        },
    )

    assert summary["estimation_method"]["type"] == "predictive_historical_calibration"
    assert summary["estimation_method"]["mode"] == "predictive"
    line_role = summary["by_stage"]["line_role"]
    assert line_role["estimation_basis"] == "historical_calibration"
    assert line_role["estimated_input_tokens"] == 4028
    assert line_role["estimated_cached_input_tokens"] == 2820
    assert line_role["estimated_output_tokens"] == 201
    assert line_role["estimated_total_tokens"] == 4229
    assert line_role["estimated_total_tokens_low"] == 3524
    assert line_role["estimated_total_tokens_high"] == 5136


def test_prompt_preview_default_mode_ignores_exact_live_telemetry(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    workbook_slug = "fixturebook"

    _write_worker_status(
        run_dir
        / "raw"
        / "llm"
        / workbook_slug
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "status.json",
        {
            "tokens_input": 250,
            "tokens_cached_input": 25,
            "tokens_output": 45,
            "tokens_total": 295,
        },
    )

    out_dir = tmp_path / "preview"
    write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
        llm_knowledge_pipeline="off",
        line_role_pipeline="off",
    )

    budget_summary = json.loads(
        (out_dir / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
    )
    assert budget_summary["estimation_method"]["mode"] == "predictive"
    recipe_budget = budget_summary["by_stage"]["recipe_llm_correct_and_link"]
    assert recipe_budget["estimation_basis"] == "unavailable"
    assert recipe_budget["estimated_total_tokens"] is None


def test_prompt_preview_budget_reports_unavailable_without_live_or_calibration() -> None:
    summary = build_prompt_preview_budget_summary(
        prompt_rows=[
            {
                "stage_key": "line_role",
                "rendered_prompt_text": "wrapper",
                "prompt_input_mode": "path",
                "task_prompt_text": "x" * 1000,
            }
        ],
        preview_dir=Path("/tmp/preview"),
        phase_plans=None,
        live_stage_summaries={},
        stage_calibrations={},
    )

    assert summary["estimation_method"]["type"] == "no_token_estimate_available"
    assert summary["totals"]["estimated_input_tokens"] is None
    assert summary["totals"]["estimated_output_tokens"] is None
    assert summary["totals"]["estimated_total_tokens"] is None
    line_role = summary["by_stage"]["line_role"]
    assert line_role["estimation_basis"] == "unavailable"
    assert line_role["estimated_input_tokens"] is None
    assert line_role["estimated_output_tokens"] is None
    assert line_role["estimated_total_tokens"] is None
    assert any(
        warning["code"] == "token_estimate_unavailable"
        for warning in summary["warnings"]
    )


def test_prompt_preview_budget_summary_emits_extreme_warning(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    workbook_slug = "fixturebook"
    live_recipe_dir = run_dir / "raw" / "llm" / workbook_slug / "recipe_correction" / "in"
    huge_text = "X" * 20000
    for index in range(120):
        _write_json(
            live_recipe_dir / f"r{index:04d}.json",
            {
                "bundle_version": "1",
                "recipe_id": f"urn:recipe:test:{index}",
                "workbook_slug": workbook_slug,
                "source_hash": "fixture-source-hash",
                "canonical_text": huge_text,
                "evidence_rows": [[index, huge_text]],
                "recipe_candidate_hint": {
                    "identifier": f"urn:recipe:test:{index}",
                    "name": f"Recipe {index}",
                    "recipeIngredient": ["1 cup flour"],
                    "recipeInstructions": ["Mix."],
                    "description": None,
                    "recipeYield": None,
                },
                "tagging_guide": {"version": "custom-live-guide"},
                "authority_notes": ["warning_fixture"],
            },
        )

    out_dir = tmp_path / "preview"
    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
        llm_knowledge_pipeline="off",
        line_role_pipeline="off",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    warning_messages = [warning["message"] for warning in manifest["warnings"]]
    assert any("Token estimate unavailable for:" in message for message in warning_messages)

    budget_summary = json.loads(
        (out_dir / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
    )
    assert budget_summary["totals"]["call_count"] == 5
    assert budget_summary["totals"]["estimated_request_chars_total"] > 1_500_000
    assert any(
        warning["code"] == "token_estimate_unavailable" for warning in budget_summary["warnings"]
    )
    assert any(
        warning["code"] == "extreme_prompt_budget" for warning in budget_summary["warnings"]
    )
    assert "No predictive token estimate is shown" in (
        out_dir / "prompt_preview_budget_summary.md"
    ).read_text(encoding="utf-8")


def test_cf_debug_preview_prompts_resolves_processed_run_from_benchmark_manifest(
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    benchmark_root = tmp_path / "benchmark-root" / "line_role_only"
    benchmark_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        benchmark_root / "run_manifest.json",
        {
            "artifacts": {
                "processed_output_run_dir": str(run_dir),
            }
        },
    )

    out_dir = tmp_path / "preview"
    result = runner.invoke(
        app,
        [
            "preview-prompts",
            "--run",
            str(benchmark_root.parent),
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0
    manifest_path = Path(result.stdout.strip())
    assert manifest_path == out_dir / "prompt_preview_manifest.json"
    assert manifest_path.is_file()


def test_cf_debug_preview_prompts_emits_budget_warning_to_stderr(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    workbook_slug = "fixturebook"
    live_recipe_dir = run_dir / "raw" / "llm" / workbook_slug / "recipe_correction" / "in"
    huge_text = "X" * 20000
    for index in range(120):
        _write_json(
            live_recipe_dir / f"r{index:04d}.json",
            {
                "bundle_version": "1",
                "recipe_id": f"urn:recipe:test:{index}",
                "workbook_slug": workbook_slug,
                "source_hash": "fixture-source-hash",
                "canonical_text": huge_text,
                "evidence_rows": [[index, huge_text]],
                "recipe_candidate_hint": {
                    "identifier": f"urn:recipe:test:{index}",
                    "name": f"Recipe {index}",
                    "recipeIngredient": ["1 cup flour"],
                    "recipeInstructions": ["Mix."],
                    "description": None,
                    "recipeYield": None,
                },
                "tagging_guide": {"version": "custom-live-guide"},
                "authority_notes": ["warning_fixture"],
            },
        )
    out_dir = tmp_path / "preview"
    result = runner.invoke(
        app,
        [
            "preview-prompts",
            "--run",
            str(run_dir),
            "--out",
            str(out_dir),
            "--llm-knowledge-pipeline",
            "off",
            "--line-role-pipeline",
            "off",
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == str(out_dir / "prompt_preview_manifest.json")
    assert "Token estimate unavailable for:" in result.stderr


def test_cf_debug_preview_prompts_observed_mode_uses_live_telemetry(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    workbook_slug = "fixturebook"
    _write_worker_status(
        run_dir
        / "raw"
        / "llm"
        / workbook_slug
        / "recipe_phase_runtime"
        / "workers"
        / "worker-001"
        / "status.json",
        {
            "tokens_input": 250,
            "tokens_cached_input": 25,
            "tokens_output": 45,
            "tokens_total": 295,
        },
    )

    out_dir = tmp_path / "preview"
    result = runner.invoke(
        app,
        [
            "preview-prompts",
            "--run",
            str(run_dir),
            "--out",
            str(out_dir),
            "--llm-knowledge-pipeline",
            "off",
            "--line-role-pipeline",
            "off",
            "--estimation-mode",
            "observed",
        ],
    )
    assert result.exit_code == 0
    budget_summary = json.loads(
        (out_dir / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
    )
    assert budget_summary["estimation_method"]["mode"] == "observed"
    assert budget_summary["estimation_method"]["type"] == "observed_live_telemetry"
    recipe_budget = budget_summary["by_stage"]["recipe_llm_correct_and_link"]
    assert recipe_budget["estimation_basis"] == "live_telemetry"
    assert recipe_budget["estimated_total_tokens"] == 295


def test_cf_debug_preview_shard_sweep_writes_experiment_summaries(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    experiment_file = tmp_path / "shard_sweep.json"
    _write_json(
        experiment_file,
        {
            "experiments": [
                {
                    "name": "narrow",
                    "recipe_worker_count": 1,
                    "recipe_shard_target_recipes": 1,
                    "line_role_worker_count": 1,
                    "line_role_shard_target_lines": 2,
                },
                {
                    "name": "wider",
                    "recipe_worker_count": 2,
                    "recipe_shard_target_recipes": 1,
                    "line_role_worker_count": 2,
                    "line_role_shard_target_lines": 1,
                },
            ]
        },
    )

    out_dir = tmp_path / "sweep"
    result = runner.invoke(
        app,
        [
            "preview-shard-sweep",
            "--run",
            str(run_dir),
            "--experiment-file",
            str(experiment_file),
            "--out",
            str(out_dir),
            "--llm-knowledge-pipeline",
            "off",
        ],
    )

    assert result.exit_code == 0
    manifest_path = Path(result.stdout.strip())
    assert manifest_path == out_dir / "shard_sweep_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [row["name"] for row in payload["experiments"]] == ["narrow", "wider"]
    assert payload["experiments"][0]["phases"][0]["stage_key"] == "recipe_llm_correct_and_link"
    assert (out_dir / "shard_sweep_summary.md").is_file()
    assert (out_dir / "experiments" / "narrow" / "prompt_preview_manifest.json").is_file()
