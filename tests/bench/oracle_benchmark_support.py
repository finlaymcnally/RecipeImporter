from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport.bench.followup_bundle import (
    CHANGED_LINES_PAYLOAD_PATH,
    PER_RECIPE_BREAKDOWN_PAYLOAD_PATH,
    TRIAGE_PACKET_PAYLOAD_PATH,
)


DEFAULT_SOURCE_SLUG = "saltfatacidheatcutdown"
DEFAULT_SOURCE_KEY = "789eb99e92fd73a31c559131124ac317fd039c440c1c759ed41d99d85af97f8c"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _relative_path(root: Path, path: Path) -> str:
    return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))


def build_minimal_upload_bundle(
    root: Path,
    *,
    source_slug: str = DEFAULT_SOURCE_SLUG,
    source_key: str = DEFAULT_SOURCE_KEY,
    codex_output_subdir: str = "codex-exec",
    baseline_output_subdir: str | None = "vanilla",
    include_knowledge: bool = False,
    knowledge_output_subdir: str = "line_role_only",
    knowledge_enabled: bool = True,
    recipe_rows: list[dict[str, Any]] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    bundle_dir = root / "upload_bundle_v1"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    source_file = f"{source_slug}.epub"

    output_subdirs: list[tuple[str, bool]] = [(codex_output_subdir, True)]
    if baseline_output_subdir is not None:
        output_subdirs.append((baseline_output_subdir, False))
    if include_knowledge and knowledge_output_subdir != codex_output_subdir:
        output_subdirs = [(knowledge_output_subdir, True)] + [
            row for row in output_subdirs if row[0] != knowledge_output_subdir
        ]

    run_diagnostics: list[dict[str, Any]] = []
    for output_subdir, codex_enabled in output_subdirs:
        run_dir = root / output_subdir
        run_manifest_payload: dict[str, Any] = {
            "run_id": output_subdir,
            "source_file": source_file,
            "run_config": {
                "llm_recipe_pipeline": "codex-recipe-shard-v1" if codex_enabled else "off",
            },
        }
        if include_knowledge and output_subdir == knowledge_output_subdir:
            run_manifest_payload["artifacts"] = {"artifact_root_dir": "prediction-run"}
        _write_json(
            run_dir / "run_manifest.json",
            run_manifest_payload,
        )
        _write_json(
            run_dir / "eval_report.json",
            {
                "schema_version": "benchmark_eval_report.v1",
                "overall_line_accuracy": 1.0,
            },
        )
        run_diagnostics.append(
            {
                "output_subdir": output_subdir,
                "run_id": output_subdir,
                "source_key": source_key,
                "source_file": source_file,
            }
        )

    normalized_recipe_rows = [dict(row) for row in (recipe_rows or [])]
    if normalized_recipe_rows:
        per_recipe_pairs = [
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_output_subdir,
                "baseline_run_id": baseline_output_subdir or "",
                "region_breakdown": {},
                "per_recipe_breakdown": [
                    {
                        "source_key": source_key,
                        **row,
                    }
                    for row in normalized_recipe_rows
                ],
            }
        ]
    else:
        per_recipe_pairs = []

    payload_rows: list[dict[str, Any]] = [
        {
            "path": CHANGED_LINES_PAYLOAD_PATH,
            "content_jsonl_rows": [],
        },
        {
            "path": TRIAGE_PACKET_PAYLOAD_PATH,
            "content_jsonl_rows": [],
        },
        {
            "path": PER_RECIPE_BREAKDOWN_PAYLOAD_PATH,
            "content_json": {"pairs": per_recipe_pairs},
        },
    ]

    analysis: dict[str, Any] = {
        "stage_separated_comparison": {"per_recipe": []},
    }

    if include_knowledge:
        run_dir = root / knowledge_output_subdir
        prompts_dir = run_dir / "prompts"
        prediction_run_dir = run_dir / "prediction-run"
        raw_llm_dir = prediction_run_dir / "raw" / "llm" / "fixture-slug"

        prompt_samples_path = prompts_dir / "prompt_type_samples_from_full_prompt_log.md"
        prompt_samples_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_samples_path.write_text(
            "# Prompt samples\n\n## knowledge (Knowledge)\n\ncall_id: `fixture-knowledge`\n",
            encoding="utf-8",
        )

        prompt_knowledge_path = prompts_dir / "prompt_nonrecipe_finalize.txt"
        prompt_knowledge_path.write_text("knowledge prompt body\n", encoding="utf-8")

        prompt_budget_path = prediction_run_dir / "prompt_budget_summary.json"
        _write_json(
            prompt_budget_path,
            {
                "schema_version": "prompt_budget_summary.v1",
                "by_stage": {"knowledge": {"call_count": 1, "tokens_total": 1234}},
            },
        )
        run_manifest_payload = json.loads(
            (run_dir / "run_manifest.json").read_text(encoding="utf-8")
        )
        artifacts = (
            run_manifest_payload.get("artifacts")
            if isinstance(run_manifest_payload.get("artifacts"), dict)
            else {}
        )
        artifacts["artifact_root_dir"] = "prediction-run"
        artifacts["prompt_budget_summary_json"] = "prediction-run/prompt_budget_summary.json"
        artifacts["actual_costs_json"] = "prediction-run/prompt_budget_summary.json"
        run_manifest_payload["artifacts"] = artifacts
        _write_json(run_dir / "run_manifest.json", run_manifest_payload)

        knowledge_manifest_path = raw_llm_dir / "knowledge_manifest.json"
        _write_json(
            knowledge_manifest_path,
            {"pipeline_id": "recipe.knowledge.compact.v1"},
        )
        _write_json(
            prediction_run_dir / "manifest.json",
            {
                "llm_codex_farm": {
                    "knowledge": {
                        "pipeline": "codex-knowledge-candidate-v2",
                        "pipeline_id": "recipe.knowledge.compact.v1",
                        "paths": {
                            "manifest_path": str(knowledge_manifest_path),
                        },
                    }
                }
            },
        )

        payload_rows.extend(
            [
                {
                    "path": _relative_path(root, prompt_samples_path),
                    "content_type": "text",
                    "category": "run_artifact",
                    "run_subdir": knowledge_output_subdir,
                    "bytes": prompt_samples_path.stat().st_size,
                    "sha256": "fixture-prompt-samples",
                    "content_text": prompt_samples_path.read_text(encoding="utf-8"),
                },
                {
                    "path": _relative_path(root, prompt_knowledge_path),
                    "content_type": "text",
                    "category": "run_artifact",
                    "run_subdir": knowledge_output_subdir,
                    "bytes": prompt_knowledge_path.stat().st_size,
                    "sha256": "fixture-knowledge-prompt",
                    "content_text": prompt_knowledge_path.read_text(encoding="utf-8"),
                },
                {
                    "path": _relative_path(root, knowledge_manifest_path),
                    "content_type": "json",
                    "category": "run_artifact",
                    "run_subdir": knowledge_output_subdir,
                    "bytes": knowledge_manifest_path.stat().st_size,
                    "sha256": "fixture-knowledge-manifest",
                    "content_json": json.loads(knowledge_manifest_path.read_text(encoding="utf-8")),
                },
                {
                    "path": _relative_path(root, prompt_budget_path),
                    "content_type": "json",
                    "category": "run_artifact",
                    "run_subdir": knowledge_output_subdir,
                    "bytes": prompt_budget_path.stat().st_size,
                    "sha256": "fixture-prompt-budget",
                    "content_json": json.loads(prompt_budget_path.read_text(encoding="utf-8")),
                },
            ]
        )

        analysis["knowledge"] = {
            "schema_version": "upload_bundle_knowledge.v1",
            "enabled_run_count": 1 if knowledge_enabled else 0,
            "rows": [
                {
                    "output_subdir": knowledge_output_subdir,
                    "source_key": source_key,
                    "enabled": knowledge_enabled,
                    "pipeline": "codex-knowledge-candidate-v2",
                    "pipeline_id": "recipe.knowledge.compact.v1",
                    "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
                    "knowledge_call_count": 1,
                    "knowledge_token_total": 1234,
                    "prompt_knowledge_status": "written",
                    "knowledge_manifest_status": "written",
                    "prompt_samples_status": "written",
                    "prompt_budget_summary_status": "written",
                    "prompt_knowledge_in_bundle": True,
                    "knowledge_manifest_in_bundle": True,
                    "prompt_samples_in_bundle": True,
                    "prompt_budget_summary_in_bundle": True,
                    "shards_written": 1,
                    "outputs_parsed": 1,
                    "snippets_written": 1,
                }
            ],
        }

    index_payload = {
        "generated_at": "2026-03-23_21.40.07",
        "source_dir": str(root),
        "topline": {
            "run_count": 1,
            "pair_count": 0,
            "changed_lines_total": 0,
        },
        "run_diagnostics": run_diagnostics,
        "analysis": analysis,
        "navigation": {"row_locators": {"knowledge_by_run": []}},
    }

    for review_profile in ("quality", "token"):
        review_dir = bundle_dir / review_profile
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "overview.md").write_text(
            "\n".join(
                [
                    f"# {review_profile.title()} Review Packet",
                    "",
                    f"- benchmark root: `{root}`",
                    "- run_count = 1",
                    "- pair_count = 0",
                    "- changed_lines_total = 0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        lane_index_payload = dict(index_payload)
        lane_index_payload["review_profile"] = review_profile
        _write_json(review_dir / "index.json", lane_index_payload)
        _write_json(
            review_dir / "payload.json",
            {
                "schema_version": "upload_bundle.review_payload.v1",
                "review_profile": review_profile,
                "row_count": len(payload_rows),
                "rows": payload_rows,
            },
        )
    return bundle_dir
