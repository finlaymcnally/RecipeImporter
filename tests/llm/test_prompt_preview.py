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
from cookimport.staging.nonrecipe_stage import NonRecipeSpan, NonRecipeStageResult
from tests.nonrecipe_stage_helpers import (
    make_authority_result,
    make_candidate_status_result,
    make_routing_result,
    make_seed_result,
    make_stage_result,
)


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
                "knowledge_prompt_target_count": 5,
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
        run_dir / "recipe_boundary" / workbook_slug / "authoritative_block_labels.json",
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
                    "deterministic_label": "NONRECIPE_CANDIDATE",
                    "final_label": "NONRECIPE_CANDIDATE",
                    "decided_by": "rule",
                    "reason_tags": ["knowledge_like"],
                    "escalation_reasons": [],
                },
                {
                    "source_block_id": "block:3",
                    "source_block_index": 3,
                    "supporting_atomic_indices": [3],
                    "deterministic_label": "NONRECIPE_EXCLUDE",
                    "final_label": "NONRECIPE_EXCLUDE",
                    "decided_by": "rule",
                    "reason_tags": ["other"],
                    "escalation_reasons": [],
                },
            ],
        },
    )
    _write_json(
        run_dir / "recipe_boundary" / workbook_slug / "recipe_spans.json",
        {
            "schema_version": "recipe_boundary.v1",
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
    label_deterministic_dir = run_dir / "label_deterministic" / workbook_slug
    label_deterministic_dir.mkdir(parents=True, exist_ok=True)
    (label_deterministic_dir / "labeled_lines.jsonl").write_text(
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
                    "label": "NONRECIPE_CANDIDATE",
                    "final_label": "NONRECIPE_CANDIDATE",
                    "decided_by": "rule",
                    "reason_tags": ["knowledge_like"],
                    "escalation_reasons": [],
                },
                {
                    "atomic_index": 3,
                    "source_block_id": "block:3",
                    "source_block_index": 3,
                    "text": "Advertisement copy.",
                    "label": "NONRECIPE_EXCLUDE",
                    "final_label": "NONRECIPE_EXCLUDE",
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
        run_dir / "recipe_authority" / workbook_slug / "recipe_block_ownership.json",
        {
            "schema_version": "recipe_block_ownership.v1",
            "ownership_mode": "recipe_boundary_with_explicit_divestment",
            "owned_block_indices": [0, 1],
            "divested_block_indices": [],
            "available_to_nonrecipe_block_indices": [2, 3],
            "block_owner_by_index": {
                "0": "urn:recipe:test:r0",
                "1": "urn:recipe:test:r0",
            },
            "recipes": [
                {
                    "recipe_id": "urn:recipe:test:r0",
                    "recipe_span_id": "recipe_span_0",
                    "owned_block_indices": [0, 1],
                    "divested_block_indices": [],
                }
            ],
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
    codex_run_dir = _build_existing_run_at(tmp_path / "outputs" / "codex-exec" / "2026-03-17_16.07.50")

    vanilla_report_path = vanilla_run_dir / "fixturebook.excel_import_report.json"
    vanilla_report = json.loads(vanilla_report_path.read_text(encoding="utf-8"))
    vanilla_report["runConfig"] = {
        "llm_recipe_pipeline": "off",
        "llm_knowledge_pipeline": "off",
        "line_role_pipeline": "deterministic-route-v2",
    }
    vanilla_report_path.write_text(
        json.dumps(vanilla_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    codex_report_path = codex_run_dir / "fixturebook.excel_import_report.json"
    codex_report = json.loads(codex_report_path.read_text(encoding="utf-8"))
    codex_report["runConfig"] = {
        "llm_recipe_pipeline": "codex-recipe-shard-v1",
        "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
        "line_role_pipeline": "codex-line-role-route-v2",
    }
    codex_report_path.write_text(
        json.dumps(codex_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    _write_json(
        benchmark_root / "single-book-benchmark" / "fixturebook" / "vanilla" / "run_manifest.json",
        {
            "artifacts": {"processed_output_run_dir": str(vanilla_run_dir)},
            "run_config": vanilla_report["runConfig"],
        },
    )
    _write_json(
        benchmark_root / "single-book-benchmark" / "fixturebook" / "codex-exec" / "run_manifest.json",
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


def _run_prompt_preview_fixture(tmp_path: Path) -> dict[str, object]:
    run_dir = _build_existing_run(tmp_path)
    out_dir = tmp_path / "preview"

    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"] == {
        "knowledge_interaction_count": 1,
        "line_role_interaction_count": 1,
        "recipe_interaction_count": 1,
    }
    assert not any(
        warning["code"] == "token_estimate_unavailable"
        for warning in manifest["warnings"]
    )
    assert manifest["surfaces"] == {
        "llm_recipe_pipeline": "codex-recipe-shard-v1",
        "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
        "line_role_pipeline": "codex-line-role-route-v2",
    }
    phase_plans = manifest["phase_plans"]
    assert phase_plans["nonrecipe_finalize"]["worker_count"] == 1
    assert phase_plans["nonrecipe_finalize"]["shard_count"] == 1
    assert phase_plans["nonrecipe_finalize"]["requested_shard_count"] == 5
    assert phase_plans["nonrecipe_finalize"]["budget_native_shard_count"] == 1
    assert phase_plans["nonrecipe_finalize"]["launch_shard_count"] == 1
    assert [shard["owned_ids"] for shard in phase_plans["nonrecipe_finalize"]["shards"]] == [
        ["fixturebook.ks0000.nr"],
    ]
    assert phase_plans["recipe_refine"]["worker_count"] == 1
    assert phase_plans["recipe_refine"]["shard_count"] == 1
    assert phase_plans["recipe_refine"]["requested_shard_count"] == 1
    assert phase_plans["recipe_refine"]["shards"][0]["owned_ids"] == [
        "urn:recipe:test:r0"
    ]
    assert phase_plans["line_role"]["worker_count"] == 1
    assert phase_plans["line_role"]["shard_count"] == 1
    assert phase_plans["line_role"]["requested_shard_count"] == 1
    assert phase_plans["line_role"]["shards"][0]["owned_ids"] == [
        "0",
        "1",
        "2",
        "3",
    ]
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
    recipe_input_payload = json.loads(
        (
            out_dir
            / "raw"
            / "llm"
            / "fixturebook"
            / "recipe_refine"
            / "in"
            / "recipe-preview-shard-0001-r0.json"
        ).read_text(encoding="utf-8")
    )
    budget_summary = json.loads(
        (out_dir / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
    )
    return {
        "out_dir": out_dir,
        "manifest": manifest,
        "full_prompt_rows": full_prompt_rows,
        "rows_by_stage": {
            stage_key: [row for row in full_prompt_rows if row["stage_key"] == stage_key]
            for stage_key in {row["stage_key"] for row in full_prompt_rows}
        },
        "recipe_input_payload": recipe_input_payload,
        "budget_summary": budget_summary,
    }


def test_prompt_preview_rebuilds_manifest_counts_and_phase_plans(tmp_path: Path) -> None:
    fixture = _run_prompt_preview_fixture(tmp_path)
    manifest = fixture["manifest"]

    assert manifest["counts"] == {
        "knowledge_interaction_count": 1,
        "line_role_interaction_count": 1,
        "recipe_interaction_count": 1,
    }
    assert not any(
        warning["code"] == "token_estimate_unavailable"
        for warning in manifest["warnings"]
    )
    assert manifest["surfaces"] == {
        "llm_recipe_pipeline": "codex-recipe-shard-v1",
        "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
        "line_role_pipeline": "codex-line-role-route-v2",
    }
    phase_plans = manifest["phase_plans"]
    assert phase_plans["nonrecipe_finalize"]["worker_count"] == 1
    assert phase_plans["nonrecipe_finalize"]["shard_count"] == 1
    assert phase_plans["nonrecipe_finalize"]["requested_shard_count"] == 5
    assert phase_plans["nonrecipe_finalize"]["budget_native_shard_count"] == 1
    assert [shard["owned_ids"] for shard in phase_plans["nonrecipe_finalize"]["shards"]] == [
        ["fixturebook.ks0000.nr"],
    ]
    assert phase_plans["recipe_refine"]["worker_count"] == 1
    assert phase_plans["recipe_refine"]["shard_count"] == 1
    assert phase_plans["recipe_refine"]["requested_shard_count"] == 1
    assert phase_plans["recipe_refine"]["shards"][0]["owned_ids"] == [
        "urn:recipe:test:r0"
    ]
    assert phase_plans["line_role"]["worker_count"] == 1
    assert phase_plans["line_role"]["shard_count"] == 1
    assert phase_plans["line_role"]["requested_shard_count"] == 1
    assert phase_plans["line_role"]["shards"][0]["owned_ids"] == [
        "0",
        "1",
        "2",
        "3",
    ]


def test_prompt_preview_uses_pipeline_default_label_when_runtime_default_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "cookimport.llm.prompt_preview.default_codex_model",
        lambda cmd=None: None,
    )

    fixture = _run_prompt_preview_fixture(tmp_path)

    assert {row["model"] for row in fixture["full_prompt_rows"]} == {"pipeline/default"}


def test_prompt_preview_uses_resolved_runtime_default_model_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "cookimport.llm.prompt_preview.default_codex_model",
        lambda cmd=None: "gpt-runtime-default",
    )

    fixture = _run_prompt_preview_fixture(tmp_path)

    assert {row["model"] for row in fixture["full_prompt_rows"]} == {
        "gpt-runtime-default"
    }


def test_prompt_preview_uses_run_config_codex_cmd_for_runtime_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    _set_run_config(
        run_dir,
        {
            "atomic_block_splitter": "atomic-v1",
            "knowledge_prompt_target_count": 5,
            "codex_farm_cmd": "/tmp/custom-codex",
        },
    )
    captured: dict[str, list[str | None]] = {}

    def _capture_model_default(*, cmd=None):
        captured.setdefault("model_cmds", []).append(cmd)
        return "gpt-cmd-default"

    def _capture_effort_default(*, cmd=None):
        captured.setdefault("effort_cmds", []).append(cmd)
        return "high"

    monkeypatch.setattr(
        "cookimport.llm.prompt_preview.default_codex_model",
        _capture_model_default,
    )
    monkeypatch.setattr(
        "cookimport.llm.prompt_preview.default_codex_reasoning_effort",
        _capture_effort_default,
    )
    monkeypatch.setattr(
        "cookimport.llm.prompt_preview.default_codex_reasoning_effort_for_model",
        lambda model, cmd=None: None,
    )

    out_dir = tmp_path / "preview"
    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    full_prompt_rows = [
        json.loads(line)
        for line in (out_dir / "prompts" / "full_prompt_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    assert set(captured["model_cmds"]) == {"/tmp/custom-codex"}
    assert set(captured["effort_cmds"]) == {"/tmp/custom-codex"}
    assert manifest["codex_farm_cmd"] == "/tmp/custom-codex"
    assert {row["model"] for row in full_prompt_rows} == {"gpt-cmd-default"}
    assert {row["request"]["reasoning_effort"] for row in full_prompt_rows} == {"high"}


def test_prompt_preview_knowledge_prompt_target_count_controls_shard_count(
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    out_dir = tmp_path / "preview"

    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
        knowledge_prompt_target_count=1,
        knowledge_worker_count=1,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    knowledge_phase = manifest["phase_plans"]["nonrecipe_finalize"]

    assert manifest["preview_settings"]["knowledge_prompt_target_count"] == 1
    assert knowledge_phase["shard_count"] == 1
    assert knowledge_phase["requested_shard_count"] == 1
    assert knowledge_phase["budget_native_shard_count"] == 1
    assert knowledge_phase["launch_shard_count"] == 1
    assert knowledge_phase["survivability_recommended_shard_count"] == 1
    assert knowledge_phase["minimum_safe_shard_count"] == 1
    assert knowledge_phase["worker_count"] == 1
    assert knowledge_phase["shards"][0]["owned_ids"] == [
        "fixturebook.ks0000.nr",
    ]
    assert (
        out_dir
        / "raw"
        / "llm"
        / "fixturebook"
        / "nonrecipe_finalize"
        / "phase_plan.json"
    ).is_file()
    assert (
        out_dir
        / "raw"
        / "llm"
        / "fixturebook"
        / "nonrecipe_finalize"
        / "phase_plan_summary.json"
    ).is_file()
    artifacts = manifest["artifacts"]
    assert artifacts["prompt_preview_budget_summary_json"] == "prompt_preview_budget_summary.json"
    assert artifacts["prompt_preview_budget_summary_md"] == "prompt_preview_budget_summary.md"


def test_prompt_preview_threads_knowledge_packet_budgets_into_settings(
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    out_dir = tmp_path / "preview"

    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
        knowledge_packet_input_char_budget=321,
        knowledge_packet_output_char_budget=654,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["preview_settings"]["knowledge_packet_input_char_budget"] == 321
    assert manifest["preview_settings"]["knowledge_packet_output_char_budget"] == 654


def test_prompt_preview_knowledge_uses_unresolved_candidate_spans_not_seed_spans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    out_dir = tmp_path / "preview"
    candidate_span = NonRecipeSpan(
        span_id="nr.candidate.2.3",
        category="candidate",
        block_start_index=2,
        block_end_index=3,
        block_indices=[2],
        block_ids=["block:2"],
    )
    excluded_span = NonRecipeSpan(
        span_id="nr.exclude.3.4",
        category="exclude",
        block_start_index=3,
        block_end_index=4,
        block_indices=[3],
        block_ids=["block:3"],
    )

    def _fake_build_nonrecipe_stage_result(**_: object) -> NonRecipeStageResult:
        return make_stage_result(
            seed=make_seed_result(
                {2: "candidate", 3: "exclude"},
                nonrecipe_spans=[candidate_span, excluded_span],
                candidate_spans=[candidate_span],
                excluded_spans=[excluded_span],
            ),
            routing=make_routing_result(
                candidate_block_indices=[2],
                excluded_block_indices=[3],
            ),
            authority=make_authority_result({3: "other"}),
            candidate_status=make_candidate_status_result(
                finalized_candidate_block_indices=[],
                unresolved_candidate_route_by_index={2: "candidate"},
            ),
        )

    monkeypatch.setattr(
        "cookimport.llm.prompt_preview.build_nonrecipe_stage_result",
        _fake_build_nonrecipe_stage_result,
    )

    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    knowledge_phase = manifest["phase_plans"]["nonrecipe_finalize"]
    full_prompt_rows = [
        json.loads(line)
        for line in (out_dir / "prompts" / "full_prompt_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    knowledge_rows = [
        row for row in full_prompt_rows if row["stage_key"] == "nonrecipe_finalize"
    ]

    assert knowledge_phase["shard_count"] == 1
    assert knowledge_phase["shards"][0]["owned_ids"] == ["fixturebook.ks0000.nr"]
    assert len(knowledge_rows) == 1
    assert knowledge_rows[0]["request_input_payload"]["bid"] == "fixturebook.ks0000.nr"
    assert knowledge_rows[0]["request_input_payload"]["b"][0]["i"] == 2


def test_prompt_preview_knowledge_excludes_stale_recipe_like_nonrecipe_labels(
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    labels_path = (
        run_dir
        / "recipe_boundary"
        / "fixturebook"
        / "authoritative_block_labels.json"
    )
    labels_payload = json.loads(labels_path.read_text(encoding="utf-8"))
    for row in labels_payload["block_labels"]:
        if row["source_block_index"] == 3:
            row["final_label"] = "RECIPE_TITLE"
            break
    labels_path.write_text(
        json.dumps(labels_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "preview"
    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    knowledge_phase = manifest["phase_plans"]["nonrecipe_finalize"]
    full_prompt_rows = [
        json.loads(line)
        for line in (out_dir / "prompts" / "full_prompt_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    knowledge_rows = [
        row for row in full_prompt_rows if row["stage_key"] == "nonrecipe_finalize"
    ]

    assert knowledge_phase["owned_id_count"] == 1
    assert knowledge_phase["shard_count"] == 1
    assert len(knowledge_rows) == 1
    assert knowledge_rows[0]["request_input_payload"]["b"] == [
        {"i": 2, "t": "Pan heat matters."}
    ]


def test_prompt_preview_rebuilds_recipe_prompt_and_input_payload(tmp_path: Path) -> None:
    fixture = _run_prompt_preview_fixture(tmp_path)
    rows_by_stage = fixture["rows_by_stage"]
    recipe_input_payload = fixture["recipe_input_payload"]

    assert set(rows_by_stage) == {
        "line_role",
        "nonrecipe_finalize",
        "recipe_refine",
    }
    assert len(rows_by_stage["nonrecipe_finalize"]) == 1
    recipe_row = rows_by_stage["recipe_refine"][0]
    assert "deterministic recipe candidates" in recipe_row["rendered_prompt_text"]
    assert "authoritative recipe spans" not in recipe_row["rendered_prompt_text"]
    assert "triage each owned candidate first" in recipe_row["rendered_prompt_text"]
    assert '"sid":"recipe-preview-shard-0001-r0"' in recipe_row["rendered_prompt_text"]
    assert recipe_row["runtime_shard_id"] == "recipe-preview-shard-0001-r0"
    assert recipe_row["runtime_worker_id"] == "worker-001"
    assert recipe_row["runtime_owned_ids"] == ["urn:recipe:test:r0"]
    assert "draft_hint" not in recipe_input_payload
    assert recipe_input_payload["r"][0]["h"] == {
        "n": "Ambiguous title-ish line",
        "i": ["1 cup flour"],
    }
    assert recipe_input_payload["r"][0]["q"]["e"] == 2
    assert recipe_input_payload["r"][0]["q"]["es"] == 0
    assert "source_no_instruction_lines" in recipe_input_payload["r"][0]["q"]["f"]
    assert recipe_input_payload["tg"]["v"] == "recipe_tagging_guide.v3"
    assert recipe_input_payload["ids"] == ["urn:recipe:test:r0"]


def test_prompt_preview_recipe_falls_back_to_recipe_spans_when_draft_location_missing(
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    draft_path = run_dir / "intermediate drafts" / "fixturebook" / "r0.jsonld"
    draft_payload = json.loads(draft_path.read_text(encoding="utf-8"))
    draft_payload["recipeimport:provenance"] = {"source_hash": "fixture-source-hash"}
    _write_json(draft_path, draft_payload)

    out_dir = tmp_path / "preview"
    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["recipe_interaction_count"] == 1
    recipe_phase = manifest["phase_plans"]["recipe_refine"]
    assert recipe_phase["shard_count"] == 1
    assert recipe_phase["shards"][0]["owned_ids"] == ["urn:recipe:test:r0"]
    rows = [
        json.loads(line)
        for line in (out_dir / "prompts" / "full_prompt_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert any(row["stage_key"] == "recipe_refine" for row in rows)


def test_prompt_preview_recipe_respects_requested_shard_count(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    workbook_slug = "fixturebook"
    source_hash = "fixture-source-hash"
    _write_json(
        run_dir / "intermediate drafts" / workbook_slug / "r1.jsonld",
        {
            "@context": ["https://schema.org"],
            "@id": "urn:recipe:test:r1",
            "identifier": "urn:recipe:test:r1",
            "name": "Second Recipe",
            "recipeIngredient": ["2 cups water"],
            "recipeInstructions": ["Boil."],
            "recipeimport:provenance": {
                "source_hash": source_hash,
                "location": {
                    "start_block": 2,
                    "end_block": 3,
                    "recipe_span_id": "recipe_span_1",
                },
            },
        },
    )
    _write_json(
        run_dir / "recipe_boundary" / workbook_slug / "recipe_spans.json",
        {
            "schema_version": "recipe_boundary.v1",
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
                },
                {
                    "span_id": "recipe_span_1",
                    "start_block_index": 2,
                    "end_block_index": 3,
                    "block_indices": [2, 3],
                    "source_block_ids": ["block:2", "block:3"],
                    "start_atomic_index": 2,
                    "end_atomic_index": 3,
                    "atomic_indices": [2, 3],
                    "title_block_index": 2,
                    "title_atomic_index": 2,
                    "warnings": [],
                    "escalation_reasons": [],
                    "decision_notes": [],
                },
            ],
        },
    )

    out_dir = tmp_path / "preview"
    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run_dir,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
        line_role_pipeline="off",
        llm_knowledge_pipeline="off",
        recipe_prompt_target_count=1,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["recipe_interaction_count"] == 1
    recipe_phase = manifest["phase_plans"]["recipe_refine"]
    assert recipe_phase["shard_count"] == 1
    assert recipe_phase["owned_id_count"] == 2
    assert recipe_phase["shards"][0]["owned_ids"] == [
        "urn:recipe:test:r0",
        "urn:recipe:test:r1",
    ]
    rows = [
        json.loads(line)
        for line in (out_dir / "prompts" / "full_prompt_log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    recipe_rows = [row for row in rows if row["stage_key"] == "recipe_refine"]
    assert len(recipe_rows) == 1
    assert recipe_rows[0]["runtime_owned_ids"] == [
        "urn:recipe:test:r0",
        "urn:recipe:test:r1",
    ]


def test_prompt_preview_rebuilds_knowledge_and_line_role_prompts(tmp_path: Path) -> None:
    fixture = _run_prompt_preview_fixture(tmp_path)
    out_dir = fixture["out_dir"]
    rows_by_stage = fixture["rows_by_stage"]

    knowledge_rows = sorted(
        rows_by_stage["nonrecipe_finalize"],
        key=lambda row: row["call_id"],
    )
    assert len(knowledge_rows) == 1
    assert all(
        "Only mechanically true structure is provided." in row["rendered_prompt_text"]
        for row in knowledge_rows
    )
    assert all(
        "compact minified JSON on a single line" in row["rendered_prompt_text"]
        for row in knowledge_rows
    )
    assert all(row["request_input_payload"]["v"] == "1" for row in knowledge_rows)
    assert [row["request_input_payload"]["bid"] for row in knowledge_rows] == [
        "fixturebook.ks0000.nr",
    ]
    assert [row["recipe_id"] for row in knowledge_rows] == ["blocks:2..2"]
    assert [row["runtime_owned_ids"] for row in knowledge_rows] == [
        ["fixturebook.ks0000.nr"],
    ]
    assert knowledge_rows[0]["request_input_payload"]["b"][0]["i"] == 2

    line_role_row = rows_by_stage["line_role"][0]
    assert "You are labeling canonical line-role route labels" in line_role_row["rendered_prompt_text"]
    assert "line_role_input_0001.json" in line_role_row["rendered_prompt_text"]
    assert '<BEGIN_AUTHORITATIVE_ROWS>\n{"text": "Ambiguous title-ish line"}' in line_role_row["rendered_prompt_text"]
    assert "Return one label for every owned input row in `rows`." in line_role_row["rendered_prompt_text"]
    assert line_role_row["prompt_input_mode"] == "inline"
    assert line_role_row["request_input_payload"]["v"] == 2
    assert [row[0] for row in line_role_row["request_input_payload"]["rows"]] == [
        0,
        1,
        2,
        3,
    ]
    assert line_role_row["request_input_payload"]["rows"][0][1] == "Ambiguous title-ish line"
    assert line_role_row["request_input_payload"]["rows"][3][1] == "Advertisement copy."
    assert line_role_row["debug_input_payload"]["phase_key"] == "line_role"
    assert line_role_row["debug_input_payload"]["rows"][0]["current_line"] == "Ambiguous title-ish line"
    assert "block_index" in line_role_row["debug_input_payload"]["rows"][0]
    assert "rule_tags" in line_role_row["debug_input_payload"]["rows"][0]
    assert line_role_row["request_input_text"] == line_role_row["task_prompt_text"]
    assert line_role_row["runtime_worker_id"] == "worker-001"
    assert line_role_row["runtime_owned_ids"] == ["0", "1", "2", "3"]
    assert (
        out_dir / "line-role-pipeline" / "in" / "line_role_input_0001.json"
    ).read_text(encoding="utf-8") == line_role_row["task_prompt_text"]
    assert (
        out_dir / "line-role-pipeline" / "debug_in" / "line_role_input_0001.json"
    ).read_text(encoding="utf-8") == line_role_row["debug_input_text"]


def test_prompt_preview_writes_artifacts_and_budget_summary(tmp_path: Path) -> None:
    fixture = _run_prompt_preview_fixture(tmp_path)
    out_dir = fixture["out_dir"]
    budget_summary = fixture["budget_summary"]

    assert (
        out_dir
        / "raw"
        / "llm"
        / "fixturebook"
        / "recipe_refine"
        / "in"
        / "recipe-preview-shard-0001-r0.json"
    ).is_file()
    assert (out_dir / "line-role-pipeline" / "in" / "line_role_input_0001.json").is_file()
    assert (out_dir / "line-role-pipeline" / "debug_in" / "line_role_input_0001.json").is_file()
    assert (out_dir / "prompts" / "prompt_type_samples_from_full_prompt_log.md").is_file()
    assert budget_summary["totals"]["call_count"] == 3
    assert budget_summary["totals"]["task_prompt_chars_total"] > 0
    assert budget_summary["totals"]["estimated_request_chars_total"] >= budget_summary["totals"]["prompt_chars_total"]
    assert budget_summary["totals"]["transport_overhead_chars_total"] > 0
    line_role_budget = budget_summary["by_stage"]["line_role"]
    assert line_role_budget["worker_count"] == 1
    assert line_role_budget["shard_count"] == 1
    assert line_role_budget["minimum_safe_shard_count"] == 1
    assert line_role_budget["binding_limit"] in {
        "input",
        "output",
        "session_peak",
        "owned_units",
    }
    assert line_role_budget["owned_ids_per_shard"]["avg"] == 4.0
    assert line_role_budget["task_prompt_chars_total"] > 0
    knowledge_budget = budget_summary["by_stage"]["nonrecipe_finalize"]
    assert knowledge_budget["worker_count"] == 1
    assert knowledge_budget["shard_count"] == 1
    assert knowledge_budget["minimum_safe_shard_count"] == 1
    assert knowledge_budget["estimated_peak_session_tokens"] is not None
    assert knowledge_budget["estimated_followup_tokens"] is not None
    assert knowledge_budget["owned_ids_per_shard"]["avg"] == 1.0
    assert budget_summary["estimation_method"]["type"] == "structural_prompt_tokenization"
    assert budget_summary["estimation_method"]["mode"] == "predictive"
    assert budget_summary["totals"]["estimated_total_tokens"] is not None
    budget_summary_md = (out_dir / "prompt_preview_budget_summary.md").read_text(encoding="utf-8")
    assert "Workers" in budget_summary_md
    assert "Prompt Detail" in budget_summary_md
    assert "Min Safe" in budget_summary_md
    assert "Binding" in budget_summary_md
    assert "structural prompt tokenization" in budget_summary_md
    assert (out_dir / "prompt_preview_budget_summary.md").is_file()


def test_prompt_preview_ignores_live_codex_inputs_and_rebuilds_from_processed_state(
    tmp_path: Path,
) -> None:
    run_dir = _build_existing_run(tmp_path)
    workbook_slug = "fixturebook"
    live_recipe_input = run_dir / "raw" / "llm" / workbook_slug / "recipe_correction" / "in" / "live_recipe.json"
    live_recipe_payload = {
        "v": "1",
        "rid": "urn:recipe:test:live",
        "wb": workbook_slug,
        "sh": "fixture-source-hash",
        "txt": "LIVE canonical text",
        "ev": [[42, "LIVE canonical text"]],
        "h": {
            "identifier": "urn:recipe:test:live",
            "name": "Live Recipe Name",
            "recipeIngredient": ["2 tbsp butter"],
            "recipeInstructions": ["Melt the butter."],
            "description": None,
            "recipeYield": None,
        },
        "tg": {"version": "custom-live-guide"},
        "an": ["live_artifact_reuse"],
    }
    _write_json(live_recipe_input, live_recipe_payload)

    live_knowledge_input = run_dir / "raw" / "llm" / workbook_slug / "nonrecipe_finalize" / "in" / "live_knowledge.json"
    live_knowledge_payload = {
        "v": "1",
        "bid": "fixturebook.ks9999.nr",
        "b": [{"i": 7, "t": "Live knowledge block."}],
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
    recipe_row = next(row for row in full_prompt_rows if row["stage_key"] == "recipe_refine")
    assert "deterministic recipe candidates" in recipe_row["rendered_prompt_text"]
    assert "LIVE canonical text" not in recipe_row["request_input_text"]
    assert recipe_row["recipe_id"] == "urn:recipe:test:r0"
    knowledge_rows = [
        row for row in full_prompt_rows if row["stage_key"] == "nonrecipe_finalize"
    ]
    assert all("Live knowledge block." not in row["request_input_text"] for row in knowledge_rows)
    assert [row["request_input_payload"]["bid"] for row in knowledge_rows] == [
        "fixturebook.ks0000.nr",
    ]

    budget_summary = json.loads(
        (out_dir / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
    )
    assert "nonrecipe_finalize" in budget_summary["by_stage"]


def test_prompt_preview_budget_uses_structural_prompt_tokenization_when_live_missing() -> None:
    request_payload = {
        "v": 1,
        "rows": [
            [11, "L0", "Toast spices."],
            [12, "L1", "Keep stirring."],
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
    recipe_budget = budget_summary["by_stage"]["recipe_refine"]
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
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "line_role_pipeline": "codex-line-role-route-v2",
        },
    )

    with pytest.raises(ValueError, match="Predictive prompt preview only accepts deterministic/vanilla artifacts"):
        write_prompt_preview_for_existing_run(
            run_path=run_dir,
            out_dir=tmp_path / "preview",
            repo_root=REPO_ROOT,
        )


def test_prompt_preview_predictive_rejects_codex_only_benchmark_manifest(tmp_path: Path) -> None:
    codex_run_dir = _build_existing_run_at(tmp_path / "outputs" / "codex-exec" / "2026-03-17_16.07.50")
    _set_run_config(
        codex_run_dir,
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "line_role_pipeline": "codex-line-role-route-v2",
        },
    )
    benchmark_root = tmp_path / "benchmark-root"
    _write_json(
        benchmark_root / "single-book-benchmark" / "fixturebook" / "codex-exec" / "run_manifest.json",
        {
            "artifacts": {"processed_output_run_dir": str(codex_run_dir)},
            "run_config": {
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
                "line_role_pipeline": "codex-line-role-route-v2",
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
                "request_input_payload": {"v": 1, "rows": [[1, "L0", "Line one"]]},
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
    codex_run_dir = _build_existing_run_at(tmp_path / "outputs" / "codex-exec" / "2026-03-17_16.07.50")
    _set_run_config(
        codex_run_dir,
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
            "line_role_pipeline": "codex-line-role-route-v2",
        },
    )
    benchmark_root = tmp_path / "benchmark-root"
    _write_json(
        benchmark_root / "run_manifest.json",
        {
            "artifacts": {"processed_output_run_dir": str(codex_run_dir)},
            "run_config": {
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
                "line_role_pipeline": "codex-line-role-route-v2",
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


def test_cf_debug_preview_prompts_rejects_benchmark_results_out_path(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    out_dir = (
        REPO_ROOT
        / "data"
        / "golden"
        / "benchmark-vs-golden"
        / "2026-04-05_00.22.03"
        / "single-book-benchmark"
        / "fixturebook"
        / "prompt-preview-inline-json"
    )

    result = runner.invoke(
        app,
        [
            "preview-prompts",
            "--run",
            str(run_dir),
            "--out",
            str(out_dir),
        ],
    )

    message = "\n".join(
        part for part in (result.stdout, result.stderr, str(result.exception or "")) if part
    )
    assert result.exit_code != 0
    assert "may not write under" in message
    assert "benchmark-vs-golden" in message


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
                    "line_role_worker_count": 1,
                    "line_role_shard_target_lines": 2,
                },
                {
                    "name": "wider",
                    "recipe_worker_count": 2,
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
    assert payload["experiments"][0]["phases"][0]["stage_key"] == "recipe_refine"
    assert (out_dir / "shard_sweep_summary.md").is_file()
    assert (out_dir / "experiments" / "narrow" / "prompt_preview_manifest.json").is_file()


def test_cf_debug_preview_shard_sweep_rejects_benchmark_results_out_path(tmp_path: Path) -> None:
    run_dir = _build_existing_run(tmp_path)
    experiment_file = tmp_path / "shard_sweep.json"
    _write_json(
        experiment_file,
        {
            "experiments": [
                {
                    "name": "narrow",
                    "recipe_worker_count": 1,
                }
            ]
        },
    )
    out_dir = (
        REPO_ROOT
        / "data"
        / "golden"
        / "benchmark-vs-golden"
        / "2026-04-05_00.22.03"
        / "single-book-benchmark"
        / "fixturebook"
        / "preview-sweep"
    )

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
        ],
    )

    message = "\n".join(
        part for part in (result.stdout, result.stderr, str(result.exception or "")) if part
    )
    assert result.exit_code != 0
    assert "may not write under" in message
    assert "benchmark-vs-golden" in message
