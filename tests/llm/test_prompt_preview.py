from __future__ import annotations

import json
from pathlib import Path
import pytest
import tiktoken

from typer.testing import CliRunner

from cookimport.cf_debug_cli import app
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from cookimport.llm.prompt_budget import (
    build_prompt_preview_budget_summary,
    write_prompt_preview_budget_summary,
)
from cookimport.llm.prompt_preview import write_prompt_preview_for_existing_run


REPO_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()
_ENCODING = tiktoken.get_encoding("o200k_base")


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_existing_run(tmp_path: Path) -> Path:
    return _build_existing_run_at(tmp_path / "processed-run")


def _build_existing_run_at(run_dir: Path) -> Path:
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


def _build_benchmark_root_with_vanilla_and_codex(tmp_path: Path) -> tuple[Path, Path, Path]:
    benchmark_root = tmp_path / "benchmark-root"
    vanilla_run_dir = _build_existing_run_at(tmp_path / "outputs" / "vanilla" / "2026-03-17_16.07.27")
    codex_run_dir = _build_existing_run_at(tmp_path / "outputs" / "codexfarm" / "2026-03-17_16.07.50")

    vanilla_report_path = vanilla_run_dir / "fixturebook.excel_import_report.json"
    vanilla_report = json.loads(vanilla_report_path.read_text(encoding="utf-8"))
    vanilla_report["runConfig"] = {
        "llm_recipe_pipeline": "off",
        "llm_knowledge_pipeline": "off",
        "line_role_pipeline": "deterministic-v1",
    }
    vanilla_report_path.write_text(
        json.dumps(vanilla_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    codex_report_path = codex_run_dir / "fixturebook.excel_import_report.json"
    codex_report = json.loads(codex_report_path.read_text(encoding="utf-8"))
    codex_report["runConfig"] = {
        "llm_recipe_pipeline": "codex-recipe-shard-v1",
        "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
        "line_role_pipeline": "codex-line-role-shard-v1",
    }
    codex_report_path.write_text(
        json.dumps(codex_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    _write_json(
        benchmark_root / "single-offline-benchmark" / "fixturebook" / "vanilla" / "run_manifest.json",
        {
            "artifacts": {"processed_output_run_dir": str(vanilla_run_dir)},
            "run_config": vanilla_report["runConfig"],
        },
    )
    _write_json(
        benchmark_root / "single-offline-benchmark" / "fixturebook" / "codexfarm" / "run_manifest.json",
        {
            "artifacts": {"processed_output_run_dir": str(codex_run_dir)},
            "run_config": codex_report["runConfig"],
        },
    )
    return benchmark_root, vanilla_run_dir, codex_run_dir


def _set_run_config(run_dir: Path, run_config: dict[str, object]) -> None:
    report_path = run_dir / "fixturebook.excel_import_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["runConfig"] = dict(run_config)
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_actual_costs_summary(path: Path) -> Path:
    _write_json(
        path,
        {
            "schema_version": "prompt_budget_summary.v1",
            "by_stage": {
                "line_role": {"call_count": 1, "tokens_total": 1234},
            },
            "totals": {"tokens_total": 1234},
        },
    )
    return path


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
    assert not any(
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
    assert "No prior recipe-span authority is provided for this batch." in embedded_line_role_prompt
    assert "RECIPE_TITLE" in embedded_line_role_prompt
    assert "KNOWLEDGE" in embedded_line_role_prompt
    assert "Advertisement copy." in embedded_line_role_prompt
    assert "0|L" in embedded_line_role_prompt
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
    assert budget_summary["estimation_method"]["type"] == "structural_prompt_tokenization"
    assert budget_summary["estimation_method"]["mode"] == "predictive"
    assert budget_summary["totals"]["estimated_total_tokens"] is not None
    budget_summary_md = (out_dir / "prompt_preview_budget_summary.md").read_text(encoding="utf-8")
    assert "Workers" in budget_summary_md
    assert "Prompt Detail" in budget_summary_md
    assert "structural prompt tokenization" in budget_summary_md
    assert (out_dir / "prompt_preview_budget_summary.md").is_file()


def test_prompt_preview_ignores_live_codex_inputs_and_rebuilds_from_processed_state(
    tmp_path: Path,
) -> None:
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
    )

    full_prompt_rows = [
        json.loads(line)
        for line in (out_dir / "prompts" / "full_prompt_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    recipe_row = next(row for row in full_prompt_rows if row["stage_key"] == "recipe_llm_correct_and_link")
    assert "Read the authoritative shard JSON file at" in recipe_row["rendered_prompt_text"]
    assert "LIVE canonical text" not in recipe_row["request_input_text"]
    assert recipe_row["recipe_id"] == "urn:recipe:test:r0"
    assert not any(
        row["stage_key"] == "extract_knowledge_optional"
        for row in full_prompt_rows
    )

    budget_summary = json.loads(
        (out_dir / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
    )
    assert "extract_knowledge_optional" not in budget_summary["by_stage"]


def test_prompt_preview_budget_uses_structural_prompt_tokenization_when_live_missing() -> None:
    request_payload = {
        "rows": [
            {"atomic_index": 11, "label_code": "OTHER", "current_line": "Toast spices."},
            {"atomic_index": 12, "label_code": "KNOWLEDGE", "current_line": "Keep stirring."},
        ]
    }
    task_prompt_text = json.dumps(request_payload, ensure_ascii=False, indent=2)
    expected_output = json.dumps(
        build_structural_pipeline_output("line-role.canonical.v1", request_payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    summary = build_prompt_preview_budget_summary(
        prompt_rows=[
            {
                "stage_key": "line_role",
                "pipeline_id": "line-role.canonical.v1",
                "model": "gpt-5",
                "rendered_prompt_text": "wrapper",
                "prompt_input_mode": "path",
                "task_prompt_text": task_prompt_text,
                "request_input_payload": request_payload,
            }
        ],
        preview_dir=Path("/tmp/preview"),
        phase_plans=None,
    )

    expected_input_tokens = _count_tokens("wrapper") + _count_tokens(task_prompt_text)
    expected_output_tokens = _count_tokens(expected_output)

    assert summary["estimation_method"]["type"] == "structural_prompt_tokenization"
    assert summary["estimation_method"]["mode"] == "predictive"
    line_role = summary["by_stage"]["line_role"]
    assert line_role["estimation_basis"] == "structural_prompt_tokenization"
    assert line_role["estimated_input_tokens"] == expected_input_tokens
    assert line_role["estimated_cached_input_tokens"] == 0
    assert line_role["estimated_output_tokens"] == expected_output_tokens
    assert line_role["estimated_total_tokens"] == expected_input_tokens + expected_output_tokens
    assert line_role["estimated_total_tokens_low"] == expected_input_tokens + expected_output_tokens
    assert line_role["estimated_total_tokens_high"] == expected_input_tokens + expected_output_tokens


def test_prompt_preview_ignores_exact_live_telemetry_and_uses_structural_prediction(
    tmp_path: Path,
) -> None:
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
    assert recipe_budget["estimation_basis"] == "structural_prompt_tokenization"
    assert recipe_budget["estimated_total_tokens"] is not None


def test_prompt_preview_budget_reports_unavailable_without_reconstructable_structure() -> None:
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


def test_prompt_preview_predictive_prefers_vanilla_benchmark_manifest(tmp_path: Path) -> None:
    benchmark_root, vanilla_run_dir, _ = _build_benchmark_root_with_vanilla_and_codex(tmp_path)
    out_dir = tmp_path / "preview-predictive"

    manifest_path = write_prompt_preview_for_existing_run(
        run_path=benchmark_root,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["resolved_processed_run_dir"] == str(vanilla_run_dir)


def test_prompt_preview_predictive_rejects_direct_codex_processed_run(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    _set_run_config(
        run_dir,
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "line_role_pipeline": "codex-line-role-shard-v1",
        },
    )

    with pytest.raises(ValueError, match="Predictive prompt preview only accepts deterministic/vanilla artifacts"):
        write_prompt_preview_for_existing_run(
            run_path=run_dir,
            out_dir=tmp_path / "preview",
            repo_root=REPO_ROOT,
        )


def test_prompt_preview_predictive_rejects_codex_only_benchmark_manifest(tmp_path: Path) -> None:
    codex_run_dir = _build_existing_run_at(tmp_path / "outputs" / "codexfarm" / "2026-03-17_16.07.50")
    _set_run_config(
        codex_run_dir,
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "line_role_pipeline": "codex-line-role-shard-v1",
        },
    )
    benchmark_root = tmp_path / "benchmark-root"
    _write_json(
        benchmark_root / "single-offline-benchmark" / "fixturebook" / "codexfarm" / "run_manifest.json",
        {
            "artifacts": {"processed_output_run_dir": str(codex_run_dir)},
            "run_config": {
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
                "line_role_pipeline": "codex-line-role-shard-v1",
            },
        },
    )

    with pytest.raises(ValueError, match="Could not resolve a predictive-safe processed stage run"):
        write_prompt_preview_for_existing_run(
            run_path=benchmark_root,
            out_dir=tmp_path / "preview",
            repo_root=REPO_ROOT,
        )


def test_prompt_preview_budget_summary_emits_extreme_warning(tmp_path: Path) -> None:
    huge_task_prompt = "X" * 1_600_000
    summary = build_prompt_preview_budget_summary(
        prompt_rows=[
            {
                "stage_key": "line_role",
                "pipeline_id": "line-role.canonical.v1",
                "model": "gpt-5",
                "rendered_prompt_text": "line-role wrapper",
                "prompt_input_mode": "path",
                "task_prompt_text": huge_task_prompt,
                "request_input_payload": {"rows": [{"atomic_index": 1, "current_line": "Line one"}]},
            },
        ],
        preview_dir=tmp_path / "preview",
        phase_plans=None,
    )
    out_dir = tmp_path / "preview"
    _, md_path = write_prompt_preview_budget_summary(out_dir, summary)

    assert summary["totals"]["call_count"] == 1
    assert summary["totals"]["estimated_request_chars_total"] > 1_500_000
    assert summary["estimation_method"]["type"] == "structural_prompt_tokenization"
    assert any(
        warning["code"] == "extreme_prompt_budget" for warning in summary["warnings"]
    )
    assert "tokenize the locally reconstructed wrapper prompts plus deposited task files" in (
        md_path
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


def test_cf_debug_preview_prompts_ignores_live_input_leftovers_in_budget_warning(
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    workbook_slug = "fixturebook"
    live_recipe_dir = run_dir / "raw" / "llm" / workbook_slug / "recipe_correction" / "in"
    huge_text = "X" * 1_600_000
    for index in range(1):
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
    assert result.stderr.strip() == ""


def test_cf_debug_preview_prompts_predictive_rejects_codex_only_root(tmp_path: Path) -> None:
    codex_run_dir = _build_existing_run_at(tmp_path / "outputs" / "codexfarm" / "2026-03-17_16.07.50")
    _set_run_config(
        codex_run_dir,
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
            "line_role_pipeline": "codex-line-role-shard-v1",
        },
    )
    benchmark_root = tmp_path / "benchmark-root"
    _write_json(
        benchmark_root / "run_manifest.json",
        {
            "artifacts": {"processed_output_run_dir": str(codex_run_dir)},
            "run_config": {
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "llm_knowledge_pipeline": "codex-knowledge-shard-v1",
                "line_role_pipeline": "codex-line-role-shard-v1",
            },
        },
    )

    result = runner.invoke(
        app,
        [
            "preview-prompts",
            "--run",
            str(benchmark_root),
            "--out",
            str(tmp_path / "preview"),
        ],
    )

    assert result.exit_code != 0
    assert result.exception is not None
    assert "Predictive prompt preview only accepts deterministic/vanilla artifacts" in str(result.exception)


def test_cf_debug_actual_costs_reads_direct_summary_file(tmp_path: Path) -> None:
    summary_path = _write_actual_costs_summary(tmp_path / "prompt_budget_summary.json")

    result = runner.invoke(
        app,
        [
            "actual-costs",
            "--run",
            str(summary_path),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == str(summary_path)


def test_cf_debug_actual_costs_resolves_manifest_artifact(tmp_path: Path) -> None:
    run_root = tmp_path / "finished-run"
    summary_path = _write_actual_costs_summary(run_root / "prediction-run" / "prompt_budget_summary.json")
    _write_json(
        run_root / "run_manifest.json",
        {
            "artifacts": {
                "actual_costs_json": "prediction-run/prompt_budget_summary.json",
                "prompt_budget_summary_json": "prediction-run/prompt_budget_summary.json",
            }
        },
    )

    result = runner.invoke(
        app,
        [
            "actual-costs",
            "--run",
            str(run_root),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == str(summary_path)


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
