from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest


def _load_cutdown_module():
    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "benchmark_cutdown_for_external_ai.py"
    )
    spec = importlib.util.spec_from_file_location(
        "benchmark_cutdown_for_external_ai",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _resolve_bundle_file(path: Path) -> Path:
    if path.is_file():
        return path
    candidate = path.parent / "quality" / path.name
    if candidate.is_file():
        return candidate
    return path


def _read_json(path: Path) -> dict[str, object]:
    target_path = _resolve_bundle_file(path)
    return json.loads(target_path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    target_path = _resolve_bundle_file(path)
    if target_path.suffix == ".json":
        payload = json.loads(target_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            rows = payload.get("rows")
            return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
    rows: list[dict[str, object]] = []
    with target_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _read_text(path: Path) -> str:
    return _resolve_bundle_file(path).read_text(encoding="utf-8")


def _jsonl_rows_by_path(path: Path) -> dict[str, dict[str, object]]:
    rows = _read_jsonl(path)
    by_path: dict[str, dict[str, object]] = {}
    for row in rows:
        key = row.get("path")
        if isinstance(key, str) and key:
            by_path[key] = row
    return by_path


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


def _read_jsonl_gzip(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _bundle_dir_size_bytes(path: Path) -> int:
    return sum(
        int(candidate.stat().st_size)
        for candidate in path.rglob("*")
        if candidate.is_file()
    )


def _run_main(module, argv: list[str]) -> int:
    prior_argv = list(sys.argv)
    try:
        sys.argv = ["benchmark_cutdown_for_external_ai.py", *argv]
        return int(module.main())
    finally:
        sys.argv = prior_argv


def _set_pred_run_artifact(run_dir: Path, pred_run_value: str) -> None:
    run_manifest_path = run_dir / "run_manifest.json"
    payload = _read_json(run_manifest_path)
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    artifacts["pred_run_dir"] = pred_run_value
    payload["artifacts"] = artifacts
    _write_json(run_manifest_path, payload)


def _set_run_artifact(run_dir: Path, key: str, value: object) -> None:
    run_manifest_path = run_dir / "run_manifest.json"
    payload = _read_json(run_manifest_path)
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    artifacts[key] = value
    payload["artifacts"] = artifacts
    _write_json(run_manifest_path, payload)


def _write_prediction_run(
    run_dir: Path,
    *,
    with_extracted_archive: bool,
    llm_manifest_recipes: dict[str, object] | None = None,
) -> Path:
    prediction_run = run_dir / "prediction-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    if with_extracted_archive:
        _write_json(
            prediction_run / "extracted_archive.json",
            [
                {
                    "index": 1,
                    "text": "1 cup flour (raw block)",
                    "location": {
                        "features": {
                                "unstructured_preprocess_mode": "br_split_v1",
                            "unstructured_stable_key": "block-1",
                        }
                    },
                },
                {
                    "index": 3,
                    "text": "Chef note (raw block)",
                    "location": {
                        "features": {
                                "unstructured_preprocess_mode": "br_split_v1",
                            "unstructured_stable_key": "block-3",
                        }
                    },
                },
            ],
        )
    if llm_manifest_recipes is not None:
        llm_manifest_path = (
            prediction_run / "raw" / "llm" / "fixture-slug" / "recipe_manifest.json"
        )
        _write_json(
            llm_manifest_path,
            {
                "enabled": True,
                "recipes": llm_manifest_recipes,
            },
        )
    return prediction_run


def _write_prediction_run_stage_outputs(
    prediction_run: Path,
    *,
    recipe_id: str = "recipe:c0",
) -> None:
    llm_run_dir = prediction_run / "raw" / "llm" / "fixture-slug"
    safe_recipe_name = recipe_id.replace(":", "_")
    _write_json(
        llm_run_dir / "recipe_refine" / "in" / f"{safe_recipe_name}.json",
        {
            "recipe_id": recipe_id,
            "evidence_rows": [
                [0, "Dish Title"],
                [1, "1 cup flour"],
                [2, "Mix gently"],
                [3, "Chef note"],
            ],
        },
    )
    _write_json(
        llm_run_dir / "recipe_refine" / "out" / f"{safe_recipe_name}.json",
        {
            "recipe_id": recipe_id,
            "canonical_recipe": {
                "title": "Dish Title",
                "description": "Chef note",
                "ingredients": ["1 cup flour"],
                "steps": ["Mix gently"],
            },
            "ingredient_step_mapping": {"0": [0]},
        },
    )
    _write_json(
        llm_run_dir / "recipe_build_final" / "out" / f"{safe_recipe_name}.json",
        {
            "recipe_id": recipe_id,
            "draft_v1": {
                "recipe": {"title": "Dish Title"},
                "steps": [
                    {
                        "instruction": "Mix gently",
                        "ingredient_lines": [{"text": "1 cup flour"}],
                    }
                ],
            },
        },
    )


def _semantic_recipe_manifest_row(
    *,
    build_intermediate_status: str = "ok",
    correction_status: str = "degraded",
    build_final_status: str = "fallback",
    mapping_status: str = "fallback",
    mapping_reason: str = "deterministic final assembly kept fallback mapping",
    structural_status: str = "warning",
    structural_reason_codes: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict[str, object]:
    return {
        "recipe_build_intermediate": build_intermediate_status,
        "recipe_refine": correction_status,
        "recipe_build_final": build_final_status,
        "mapping_status": mapping_status,
        "mapping_reason": mapping_reason,
        "structural_status": structural_status,
        "structural_reason_codes": list(structural_reason_codes or []),
        "warnings": list(warnings or []),
        "errors": list(errors or []),
    }


def _write_knowledge_artifacts(
    run_dir: Path,
    *,
    workbook_slug: str = "fixture-slug",
    knowledge_call_count: int = 4,
    prompt_budget_at_run_root: bool = False,
    include_prediction_run_files: bool = True,
) -> None:
    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "prompt_type_samples_from_full_prompt_log.md").write_text(
        "\n".join(
            [
                "# Prompt samples",
                "",
                "## knowledge (Knowledge)",
                "",
                "call_id: `fixture-knowledge`",
                "",
                "Knowledge prompt body",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (prompts_dir / "prompt_nonrecipe_finalize.txt").write_text(
        "knowledge raw prompt body\n",
        encoding="utf-8",
    )
    prompt_budget_path = (
        run_dir / "prompt_budget_summary.json"
        if prompt_budget_at_run_root
        else run_dir / "prediction-run" / "prompt_budget_summary.json"
    )
    _write_json(
        prompt_budget_path,
        {
            "schema_version": "prompt_budget_summary.v1",
            "by_stage": {
                "knowledge": {
                    "call_count": knowledge_call_count,
                    "duration_total_ms": knowledge_call_count * 100,
                    "tokens_total": knowledge_call_count * 1000,
                }
            },
        },
    )
    if include_prediction_run_files:
        _write_json(
            run_dir / "prediction-run" / "manifest.json",
            {
                "llm_codex_farm": {
                    "knowledge": {
                        "enabled": True,
                        "pipeline": "codex-knowledge-candidate-v2",
                        "pipeline_id": "recipe.knowledge.compact.v1",
                        "counts": {
                            "shards_written": knowledge_call_count,
                            "outputs_parsed": knowledge_call_count,
                            "snippets_written": knowledge_call_count * 2,
                        },
                        "paths": {
                            "manifest_path": str(
                                run_dir
                                / "prediction-run"
                                / "raw"
                                / "llm"
                                / workbook_slug
                                / "knowledge_manifest.json"
                            )
                        },
                    }
                }
            },
        )
        _write_json(
            run_dir
            / "prediction-run"
            / "raw"
            / "llm"
            / workbook_slug
            / "knowledge_manifest.json",
            {
                "pipeline_id": "recipe.knowledge.compact.v1",
                "counts": {
                    "shards_written": knowledge_call_count,
                    "outputs_parsed": knowledge_call_count,
                    "snippets_written": knowledge_call_count * 2,
                },
            },
        )


def _write_processed_output_knowledge_artifacts(
    run_dir: Path,
    *,
    processed_output_root: Path,
    workbook_slug: str = "fixture-slug",
    knowledge_call_count: int = 4,
) -> None:
    _write_json(
        processed_output_root / "09_nonrecipe_finalize_status.json",
        {
            "enabled": True,
            "counts": {
                "shards_written": knowledge_call_count,
                "outputs_parsed": knowledge_call_count,
                "snippets_written": knowledge_call_count * 2,
            },
        },
    )
    _write_json(
        processed_output_root / "09_nonrecipe_authority.json",
        {
            "counts": {
                "final_authority_blocks": knowledge_call_count,
            },
        },
    )
    _write_json(
        processed_output_root / "raw" / "llm" / workbook_slug / "knowledge_manifest.json",
        {
            "pipeline_id": "recipe.knowledge.compact.v1",
            "counts": {
                "shards_written": knowledge_call_count,
                "outputs_parsed": knowledge_call_count,
                "snippets_written": knowledge_call_count * 2,
            },
        },
    )
    _set_run_artifact(run_dir, "processed_output_run_dir", str(processed_output_root))


def _write_processed_output_recipe_manifest(
    run_dir: Path,
    *,
    processed_output_root: Path,
    llm_manifest_recipes: dict[str, object],
    workbook_slug: str = "fixture-slug",
) -> Path:
    llm_manifest_path = (
        processed_output_root / "raw" / "llm" / workbook_slug / "recipe_manifest.json"
    )
    _write_json(
        llm_manifest_path,
        {
            "enabled": True,
            "recipes": llm_manifest_recipes,
        },
    )
    _set_run_artifact(run_dir, "processed_output_run_dir", str(processed_output_root))
    _set_run_artifact(run_dir, "stage_run_dir", str(processed_output_root))
    _set_run_artifact(run_dir, "recipe_manifest_json", str(llm_manifest_path))
    return llm_manifest_path


def _write_replay_extracted_archive(run_dir: Path) -> None:
    replay_path = (
        run_dir / ".prediction-record-replay" / "pipelined" / "extracted_archive.from_records.json"
    )
    _write_json(
        replay_path,
        [
            {
                "index": 1,
                "text": "1 cup flour (replay block)",
                "location": {"features": {"unstructured_stable_key": "block-1"}},
            },
            {
                "index": 3,
                "text": "Chef note (replay block)",
                "location": {"features": {"unstructured_stable_key": "block-3"}},
            },
        ],
    )
    _set_run_artifact(
        run_dir,
        "evaluation_extracted_archive_json",
        ".prediction-record-replay/pipelined/extracted_archive.from_records.json",
    )


def _write_prediction_run_knowledge_stage_outputs(
    prediction_run: Path,
    *,
    workbook_slug: str = "fixture-slug",
    chunk_id: str = "knowledge:c0",
) -> None:
    llm_run_dir = prediction_run / "raw" / "llm" / workbook_slug
    _write_json(
        llm_run_dir / "nonrecipe_finalize" / "in" / "r0000.json",
        {
            "v": "2",
            "bid": "knowledge:bundle0",
            "c": [
                {
                    "cid": chunk_id,
                    "b": [
                        {"i": 1, "t": "Roast until deeply browned."},
                        {"i": 2, "t": "Let the pan stay hot for 2 minutes."},
                    ],
                    "h": {"l": "knowledge", "f": "prose_like"},
                }
            ],
        },
    )
    _write_json(
        llm_run_dir / "nonrecipe_finalize" / "out" / "r0000.json",
        {
            "bundle_version": "2",
            "bundle_id": "knowledge:bundle0",
            "chunk_results": [
                {
                    "chunk_id": chunk_id,
                    "is_useful": True,
                    "block_decisions": [
                        {"block_index": 1, "category": "knowledge"},
                        {"block_index": 2, "category": "other"},
                    ],
                    "snippets": [
                        {
                            "title": "Browning",
                            "body": "Roast until deeply browned.",
                            "tags": ["fixture"],
                            "evidence": [
                                {"block_index": 1, "quote": "Roast until deeply browned."}
                            ],
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        prediction_run / "manifest.json",
        {
            "llm_codex_farm": {
                "knowledge": {
                    "enabled": True,
                    "pipeline": "codex-knowledge-candidate-v2",
                    "pipeline_id": "recipe.knowledge.compact.v1",
                    "process_run": {
                        "run_id": "run-knowledge-reconstruct",
                        "pipeline_id": "recipe.knowledge.compact.v1",
                    },
                }
            }
        },
    )


def _set_eval_report_per_label(
    run_dir: Path,
    *,
    per_label: dict[str, object],
) -> None:
    eval_report_path = run_dir / "eval_report.json"
    payload = _read_json(eval_report_path)
    payload["per_label"] = per_label
    _write_json(eval_report_path, payload)


def _set_eval_report_metrics(
    run_dir: Path,
    *,
    overall_line_accuracy: float,
    macro_f1_excluding_other: float,
    practical_f1: float,
) -> None:
    eval_report_path = run_dir / "eval_report.json"
    payload = _read_json(eval_report_path)
    payload["overall_line_accuracy"] = overall_line_accuracy
    payload["macro_f1_excluding_other"] = macro_f1_excluding_other
    payload["practical_f1"] = practical_f1
    _write_json(eval_report_path, payload)


def _prompt_rows_for_cutdown_fixture() -> list[dict[str, object]]:
    return [
        {
            "stage_key": "recipe_build_intermediate",
            "call_id": "fixture-build-intermediate",
            "recipe_id": "recipe:c0",
            "parsed_response": {
                "is_recipe": True,
                "recipe_id": "recipe:c0",
                "start_block_index": 0,
                "end_block_index": 3,
            },
            "request_input_payload": {"blocks_candidate": [{"text": "Dish Title"}]},
        },
        {
            "stage_key": "recipe_build_final",
            "call_id": "fixture-build-final",
            "recipe_id": "recipe:c0",
            "parsed_response": {
                "warnings": ["Serving information is split across two lines."],
                "ingredient_step_mapping": "{}",
            },
            "request_input_payload": {"blocks_candidate": [{"text": "Mix gently"}]},
        },
    ]


def _prompt_rows_for_starter_pack_fixture() -> list[dict[str, object]]:
    return [
        {
            "stage_key": "recipe_build_intermediate",
            "call_id": "starter-build-intermediate",
            "recipe_id": "recipe:c0",
            "timestamp_utc": "2026-03-03T10:00:00Z",
            "model": "gpt-test",
            "parsed_response": {
                "is_recipe": True,
                "recipe_id": "recipe:c0",
                "start_block_index": 0,
                "end_block_index": 2,
                "title": "Dish Title",
                "excluded_block_ids": [],
            },
            "request_input_payload": {
                "blocks_candidate": [
                    {"index": 0, "block_id": "b0", "text": "Dish Title"},
                    {"index": 1, "block_id": "b1", "text": "1 cup flour"},
                    {"index": 2, "block_id": "b2", "text": "Mix gently"},
                    {"index": 3, "block_id": "b3", "text": "Chef note"},
                ],
                "blocks_after": [],
                "blocks_before": [],
            },
        },
        {
            "stage_key": "recipe_refine",
            "call_id": "starter-correction",
            "recipe_id": "recipe:c0",
            "timestamp_utc": "2026-03-03T10:00:05Z",
            "model": "gpt-test",
            "parsed_response": {
                "warnings": ["No explicit cooking instructions were provided."],
                "canonical_recipe": {
                    "title": "Dish Title",
                    "ingredients": ["1 cup flour"],
                    "steps": ["Mix gently"],
                },
                "ingredient_step_mapping": {},
            },
            "request_input_payload": {
                "evidence_rows": [
                    [0, "Dish Title"],
                    [1, "1 cup flour"],
                    [2, "Mix gently"],
                    [3, "Chef note"],
                ],
                "canonical_text": "Dish Title\n1 cup flour\nMix gently\nChef note\n",
            },
        },
        {
            "stage_key": "recipe_build_final",
            "call_id": "starter-build-final",
            "recipe_id": "recipe:c0",
            "timestamp_utc": "2026-03-03T10:00:10Z",
            "model": "gpt-test",
            "parsed_response": {
                "warnings": ["No extracted instructions were provided."],
                "ingredient_step_mapping": "{}",
                "draft_v1": json.dumps(
                    {
                        "schema_v": 1,
                        "recipe": {"title": "Dish Title"},
                        "steps": [],
                    }
                ),
            },
            "request_input_payload": {
                "extracted_ingredients": [{"text": "1 cup flour"}],
                "extracted_instructions": [],
            },
        },
    ]


def _prompt_rows_for_sharded_recipe_fixture() -> list[dict[str, object]]:
    return [
        {
            "stage_key": "recipe_refine",
            "call_id": "recipe-shard-0000-r0000-r0001",
            "recipe_id": "recipe-shard-0000-r0000-r0001",
            "timestamp_utc": "2026-03-03T10:00:05Z",
            "model": "gpt-test",
            "parsed_response": {
                "payload": None,
                "reason_code": "watchdog_command_execution_forbidden",
                "reason_detail": "taskfile worker stage attempted tool use",
                "validation_errors": ["missing_output_file"],
            },
            "request_input_payload": {
                "ids": ["recipe:a0", "recipe:b0"],
                "r": [
                    {
                        "rid": "recipe:a0",
                        "ev": [[0, "Dish Title"], [1, "1 cup flour"]],
                        "h": {"n": "Dish Title"},
                    },
                    {
                        "rid": "recipe:b0",
                        "ev": [[2, "Mix gently"], [3, "Chef note"]],
                        "h": {"n": "Chef Note Dish"},
                    },
                ],
            },
        }
    ]


def _prompt_rows_for_compact_recipe_correction_fixture() -> list[dict[str, object]]:
    return [
        {
            "stage_key": "recipe_refine",
            "call_id": "recipe-shard-0000-r0000-r0001",
            "recipe_id": "recipe-shard-0000-r0000-r0001",
            "timestamp_utc": "2026-03-03T10:00:05Z",
            "model": "gpt-test",
            "parsed_response": {
                "final_supervision_state": "completed",
                "finalization_path": "raw_supervision",
                "payload": {
                    "sid": "recipe-shard-0000-r0000-r0001",
                    "v": "1",
                    "r": [
                        {
                            "rid": "recipe:a0",
                            "st": "repaired",
                            "sr": None,
                            "cr": {
                                "t": "Dish A",
                                "i": ["1 cup flour"],
                                "s": ["Mix gently"],
                                "d": None,
                                "y": None,
                            },
                            "m": {"0": [0]},
                            "mr": None,
                            "g": [],
                            "w": [],
                            "v": "1",
                        },
                        {
                            "rid": "recipe:b0",
                            "st": "repaired",
                            "sr": None,
                            "cr": {
                                "t": "Dish B",
                                "i": ["2 eggs"],
                                "s": ["Whisk well"],
                                "d": None,
                                "y": None,
                            },
                            "m": {},
                            "mr": "unclear_alignment",
                            "g": [],
                            "w": [],
                            "v": "1",
                        },
                    ],
                },
            },
            "request_input_payload": {
                "ids": ["recipe:a0", "recipe:b0"],
                "r": [
                    {
                        "rid": "recipe:a0",
                        "ev": [[0, "Dish A"], [1, "1 cup flour"], [2, "Mix gently"]],
                        "h": {"n": "Dish A"},
                    },
                    {
                        "rid": "recipe:b0",
                        "ev": [[3, "Dish B"], [4, "2 eggs"], [5, "Whisk well"]],
                        "h": {"n": "Dish B"},
                    },
                ],
            },
        }
    ]


def _build_eval_artifacts(module, run_dir: Path) -> tuple[Path, Path]:
    canonical_text = "Dish Title\n1 cup flour\nMix gently\nChef note\n"
    canonical_text_path = run_dir / "canonical_text.txt"
    canonical_spans_path = run_dir / "canonical_span_labels.jsonl"
    canonical_text_path.write_text(canonical_text, encoding="utf-8")

    lines = module._build_canonical_lines(canonical_text)
    labels_by_index = {
        0: "RECIPE_TITLE",
        1: "INGREDIENT_LINE",
        2: "INSTRUCTION_LINE",
        3: "RECIPE_NOTES",
    }
    span_rows = [
        {
            "label": labels_by_index[int(line["line_index"])],
            "start_char": int(line["start_char"]),
            "end_char": int(line["end_char"]),
        }
        for line in lines
    ]
    _write_jsonl(canonical_spans_path, span_rows)
    return canonical_text_path, canonical_spans_path


def _make_run_record(
    module,
    *,
    run_root: Path,
    run_id: str,
    llm_recipe_pipeline: str,
    wrong_label_rows: list[dict[str, object]],
    full_prompt_rows: list[dict[str, object]] | None = None,
    line_role_pipeline: str = "off",
    line_role_prediction_rows: list[dict[str, object]] | None = None,
    joined_line_rows: list[dict[str, object]] | None = None,
    projected_span_rows: list[dict[str, object]] | None = None,
    source_path: str = "/tmp/book.epub",
    source_hash: str = "source-hash",
) -> object:
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    canonical_text_path, canonical_spans_path = _build_eval_artifacts(module, run_dir)

    _write_jsonl(run_dir / "wrong_label_lines.jsonl", wrong_label_rows)
    _write_jsonl(run_dir / "missed_gold_lines.jsonl", [])
    _write_jsonl(run_dir / "unmatched_pred_blocks.jsonl", [])
    _write_jsonl(run_dir / "aligned_prediction_blocks.jsonl", [])
    _write_jsonl(run_dir / "alignment_gaps.jsonl", [])
    if line_role_prediction_rows is not None:
        _write_jsonl(
            run_dir / "line-role-pipeline" / "line_role_predictions.jsonl",
            line_role_prediction_rows,
        )
    if joined_line_rows is not None:
        _write_jsonl(
            run_dir / "line-role-pipeline" / "joined_line_table.jsonl",
            joined_line_rows,
        )
    if projected_span_rows is not None:
        _write_jsonl(
            run_dir / "line-role-pipeline" / "projected_spans.jsonl",
            projected_span_rows,
        )

    artifacts: dict[str, object] = {}
    full_prompt_log_rows = 0
    full_prompt_log_path: str | None = None
    if full_prompt_rows is not None:
        full_prompt_rel_path = "prompts/full_prompt_log.jsonl"
        _write_jsonl(run_dir / full_prompt_rel_path, full_prompt_rows)
        artifacts["full_prompt_log_path"] = full_prompt_rel_path
        full_prompt_log_rows = len(full_prompt_rows)
        full_prompt_log_path = full_prompt_rel_path

    run_manifest = {
        "run_id": run_id,
        "source": {"path": source_path, "source_hash": source_hash},
        "artifacts": artifacts,
        "run_config": {
            "llm_recipe_pipeline": llm_recipe_pipeline,
            "atomic_block_splitter": "off",
            "line_role_pipeline": line_role_pipeline,
            "prediction_run_config_hash": "hash-a",
        },
    }
    eval_report = {
        "canonical": {
            "canonical_text_path": str(canonical_text_path),
            "canonical_span_labels_path": str(canonical_spans_path),
        },
        "alignment": {
            "canonical_char_coverage": 0.995,
            "prediction_block_match_ratio": 0.996,
        },
        "counts": {"gold_total": 4, "pred_total": 4},
        "confusion": {},
        "per_label": {},
        "worst_label_recall": {},
        "overall_line_accuracy": 0.0,
        "macro_f1_excluding_other": 0.0,
        "practical_f1": 0.0,
    }
    _write_json(run_dir / "run_manifest.json", run_manifest)
    _write_json(run_dir / "eval_report.json", eval_report)

    return module.RunRecord(
        run_id=run_id,
        source_key=source_hash,
        source_file=Path(source_path).name,
        source_hash=source_hash,
        llm_recipe_pipeline=llm_recipe_pipeline,
        atomic_block_splitter="off",
        line_role_pipeline=line_role_pipeline,
        codex_enabled=llm_recipe_pipeline not in {"off", "none", ""},
        metric_overall_line_accuracy=0.0,
        metric_macro_f1_excluding_other=0.0,
        metric_practical_f1=0.0,
        worst_label_recall={},
        run_timestamp=module._parse_run_timestamp(run_id),
        output_subdir=run_id,
        config_snapshot=module._config_snapshot(run_manifest),
        top_confusions=[],
        summary_path=str(run_dir / "need_to_know_summary.json"),
        run_dir=str(run_dir),
        full_prompt_log_status="complete" if full_prompt_rows is not None else "not_applicable",
        full_prompt_log_rows=full_prompt_log_rows,
        full_prompt_log_path=full_prompt_log_path,
    )


def _build_starter_pack_v1_fixture(tmp_path: Path) -> dict[str, object]:
    module = _load_cutdown_module()
    run_root = tmp_path / "runs"
    codex_run_id = "2026-03-03_10.10.00"
    baseline_run_id = "2026-03-03_10.09.00"

    _make_run_record(
        module,
        run_root=run_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        wrong_label_rows=[
            {"line_index": 1, "pred_label": "RECIPE_NOTES"},
            {"line_index": 3, "pred_label": "KNOWLEDGE"},
        ],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
    )
    _make_run_record(
        module,
        run_root=run_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
    )

    codex_run_dir = run_root / codex_run_id
    _write_prediction_run(
        codex_run_dir,
        with_extracted_archive=True,
        llm_manifest_recipes={
            "recipe:c0": _semantic_recipe_manifest_row(
                warnings=["No explicit cooking instructions were provided."],
                structural_reason_codes=["missing_instructions"],
            )
        },
    )
    _set_pred_run_artifact(codex_run_dir, "prediction-run")

    original_preprocess = module._build_preprocess_trace_failure_rows

    def _fake_preprocess_rows(**kwargs):
        rows = []
        for index in range(10):
            rows.append(
                {
                    "span_region": "outside_active_recipe_span",
                    "line_index": index + 100,
                    "recipe_id": "recipe:c0",
                    "gold_label": "RECIPE_NOTES",
                    "pred_label": "KNOWLEDGE",
                    "trace_status": "joined_with_archive_only",
                    "warning_buckets": ["ocr_or_page_artifact"],
                    "raw_block_stable_key": f"block-{index}",
                    "raw_block_excerpt": f"raw excerpt {index}",
                    "prompt_candidate_block_excerpt": f"prompt excerpt {index}",
                    "call_id": "starter-correction",
                }
            )
        return rows, "ready"

    module._build_preprocess_trace_failure_rows = _fake_preprocess_rows
    try:
        output_dir = tmp_path / "cutdown_out"
        assert (
            _run_main(
                module,
                [str(run_root), "--output-dir", str(output_dir), "--overwrite", "--no-flatten"],
            )
            == 0
        )
    finally:
        module._build_preprocess_trace_failure_rows = original_preprocess

    starter_dir = output_dir / "starter_pack_v1"
    return {
        "module": module,
        "output_dir": output_dir,
        "root_comparison": _read_json(output_dir / "comparison_summary.json"),
        "root_manifest": _read_json(output_dir / "process_manifest.json"),
        "starter_call_inventory_rows": _read_jsonl(starter_dir / "02_call_inventory.jsonl"),
        "starter_comparison": _read_json(starter_dir / "11_comparison_summary.json"),
        "starter_dir": starter_dir,
        "starter_manifest": _read_json(starter_dir / "10_process_manifest.json"),
        "starter_selected_packets": _read_jsonl(starter_dir / "06_selected_recipe_packets.jsonl"),
        "starter_triage_rows": _read_jsonl(starter_dir / "01_recipe_triage.jsonl"),
        "warning_summary": _read_json(starter_dir / "04_warning_and_trace_summary.json"),
    }


def _build_existing_upload_bundle_fixture(tmp_path: Path) -> dict[str, object]:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-03_10.18.00"
    baseline_run_id = "2026-03-03_10.17.00"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
        line_role_prediction_rows=[
            {
                "atomic_index": 0,
                "label": "RECIPE_TITLE",
                "decided_by": "rule",
                "escalation_reasons": [],
                "text": "Dish Title",
            }
        ],
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
    )
    _write_json(
        session_root / "codex_vs_vanilla_comparison.json",
        {"schema_version": "codex_vs_vanilla_comparison.v2"},
    )
    codex_run_dir = session_root / codex_run_id
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(codex_run_dir, "prediction-run")
    seeded_cutdown_dir = tmp_path / "seed_cutdown" / codex_run_id
    module._build_run_cutdown(
        run_dir=codex_run_dir,
        output_run_dir=seeded_cutdown_dir,
        sample_limit=80,
        excerpt_limit=200,
        top_confusions_limit=8,
        top_labels_limit=6,
        prompt_pairs_per_category=3,
        prompt_excerpt_limit=400,
    )
    shutil.copy2(
        seeded_cutdown_dir / "need_to_know_summary.json",
        codex_run_dir / "need_to_know_summary.json",
    )

    bundle_dir = session_root / "upload_bundle_v1"
    metadata = module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    artifact_paths = {
        str(row.get("path") or "")
        for row in index_payload["artifact_index"]
        if isinstance(row, dict)
    }

    return {
        "artifact_paths": artifact_paths,
        "baseline_run_id": baseline_run_id,
        "bundle_dir": bundle_dir,
        "codex_run_id": codex_run_id,
        "index_payload": index_payload,
        "metadata": metadata,
        "module": module,
        "session_root": session_root,
    }


def _build_high_level_multi_book_upload_bundle_fixture(tmp_path: Path) -> dict[str, object]:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-profile-benchmark"

    def _prompt_rows_with_runtime(
        *,
        duration_values: tuple[int, int, int],
        token_values: tuple[int, int, int],
        cost_values: tuple[float, float, float],
    ) -> list[dict[str, object]]:
        rows = _prompt_rows_for_starter_pack_fixture()
        enriched: list[dict[str, object]] = []
        for index, row in enumerate(rows):
            row_copy = dict(row)
            row_copy["request_telemetry"] = {
                "duration_ms": duration_values[index],
                "tokens_input": token_values[index] - 10,
                "tokens_output": 10,
                "tokens_total": token_values[index],
                "cost_usd": cost_values[index],
            }
            enriched.append(row_copy)
        return enriched

    # Book A (duplicate run ids with book B on purpose: vanilla/codex-exec).
    _make_run_record(
        module,
        run_root=session_root / "book_a",
        run_id="vanilla",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
        source_path="/tmp/book_a.epub",
        source_hash="book-a-hash",
    )
    _make_run_record(
        module,
        run_root=session_root / "book_a",
        run_id="codex-exec",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_with_runtime(
            duration_values=(100, 200, 300),
            token_values=(120, 220, 320),
            cost_values=(0.12, 0.22, 0.32),
        ),
        line_role_prediction_rows=[
            {
                "line_index": 1,
                "label": "INGREDIENT_LINE",
                "decided_by": "llm",
                "escalation_reasons": ["explicit_escalation_reasons"],
                "text": "1 cup flour",
                "within_recipe_span": True,
                "page_type": "recipe_page",
                "chapter_title": "Chapter A",
            }
        ],
        source_path="/tmp/book_a.epub",
        source_hash="book-a-hash",
    )
    _set_eval_report_metrics(
        session_root / "book_a" / "vanilla",
        overall_line_accuracy=0.70,
        macro_f1_excluding_other=0.68,
        practical_f1=0.69,
    )
    _set_eval_report_metrics(
        session_root / "book_a" / "codex-exec",
        overall_line_accuracy=0.62,
        macro_f1_excluding_other=0.61,
        practical_f1=0.60,
    )

    # Book B.
    _make_run_record(
        module,
        run_root=session_root / "book_b",
        run_id="vanilla",
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
        source_path="/tmp/book_b.epub",
        source_hash="book-b-hash",
    )
    _make_run_record(
        module,
        run_root=session_root / "book_b",
        run_id="codex-exec",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_with_runtime(
            duration_values=(1000, 2000, 3000),
            token_values=(1120, 1220, 1320),
            cost_values=(1.12, 1.22, 1.32),
        ),
        line_role_prediction_rows=[
            {
                "line_index": 1,
                "label": "INGREDIENT_LINE",
                "decided_by": "llm",
                "escalation_reasons": ["explicit_escalation_reasons"],
                "text": "1 cup flour",
                "within_recipe_span": False,
                "page_type": "front_matter",
                "chapter_title": "Chapter B",
            }
        ],
        source_path="/tmp/book_b.epub",
        source_hash="book-b-hash",
    )
    _set_eval_report_metrics(
        session_root / "book_b" / "vanilla",
        overall_line_accuracy=0.62,
        macro_f1_excluding_other=0.61,
        practical_f1=0.60,
    )
    _set_eval_report_metrics(
        session_root / "book_b" / "codex-exec",
        overall_line_accuracy=0.71,
        macro_f1_excluding_other=0.70,
        practical_f1=0.72,
    )

    bundle_dir = session_root / "upload_bundle_v1"
    module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
        high_level_only=True,
        target_bundle_size_bytes=300_000,
    )

    return {
        "analysis": _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)["analysis"],
        "index_payload": _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME),
    }


def _build_existing_upload_bundle_fixture(tmp_path: Path) -> dict[str, object]:
    module = _load_cutdown_module()
    session_root = tmp_path / "single-book-benchmark"
    codex_run_id = "2026-03-03_10.18.00"
    baseline_run_id = "2026-03-03_10.17.00"

    _make_run_record(
        module,
        run_root=session_root,
        run_id=codex_run_id,
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        wrong_label_rows=[{"line_index": 1, "pred_label": "RECIPE_NOTES"}],
        full_prompt_rows=_prompt_rows_for_starter_pack_fixture(),
        line_role_prediction_rows=[
            {
                "atomic_index": 0,
                "label": "RECIPE_TITLE",
                "decided_by": "rule",
                "escalation_reasons": [],
                "text": "Dish Title",
            }
        ],
    )
    _make_run_record(
        module,
        run_root=session_root,
        run_id=baseline_run_id,
        llm_recipe_pipeline="off",
        wrong_label_rows=[{"line_index": 1, "pred_label": "YIELD_LINE"}],
        full_prompt_rows=None,
    )
    _write_json(
        session_root / "codex_vs_vanilla_comparison.json",
        {"schema_version": "codex_vs_vanilla_comparison.v2"},
    )
    codex_run_dir = session_root / codex_run_id
    _write_prediction_run(codex_run_dir, with_extracted_archive=True)
    _set_pred_run_artifact(codex_run_dir, "prediction-run")
    seeded_cutdown_dir = tmp_path / "seed_cutdown" / codex_run_id
    module._build_run_cutdown(
        run_dir=codex_run_dir,
        output_run_dir=seeded_cutdown_dir,
        sample_limit=80,
        excerpt_limit=200,
        top_confusions_limit=8,
        top_labels_limit=6,
        prompt_pairs_per_category=3,
        prompt_excerpt_limit=400,
    )
    shutil.copy2(
        seeded_cutdown_dir / "need_to_know_summary.json",
        codex_run_dir / "need_to_know_summary.json",
    )

    bundle_dir = session_root / "upload_bundle_v1"
    metadata = module.build_upload_bundle_for_existing_output(
        source_dir=session_root,
        output_dir=bundle_dir,
        overwrite=True,
        prune_output_dir=False,
    )

    index_payload = _read_json(bundle_dir / module.UPLOAD_BUNDLE_INDEX_FILE_NAME)
    artifact_paths = {
        str(row.get("path") or "")
        for row in index_payload["artifact_index"]
        if isinstance(row, dict)
    }

    return {
        "artifact_paths": artifact_paths,
        "baseline_run_id": baseline_run_id,
        "bundle_dir": bundle_dir,
        "codex_run_id": codex_run_id,
        "index_payload": index_payload,
        "metadata": metadata,
        "module": module,
        "session_root": session_root,
    }
